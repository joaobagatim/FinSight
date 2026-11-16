"""Own account queries and atomic, persistent account creation retries."""

import hashlib
import hmac
import json
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import or_, select

from app.models import (
    Account,
    AccountCreationRequest,
    GoalAllocation,
    ImportJob,
    Transaction,
    Transfer,
)
from app.schemas.accounts import (
    AccountInput,
    AccountListResponse,
    AccountOpeningInput,
    AccountResponse,
    AccountUpdateInput,
)
from app.services.sessions import SessionService


class AccountNotFound(Exception):
    pass


class AccountConflict(Exception):
    pass


class AccountStale(Exception):
    pass


class AccountOpeningLocked(Exception):
    pass


def account_etag(account: AccountResponse) -> str:
    canonical = json.dumps(
        account.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest() + '"'


class AccountService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    def create(self, token: SecretStr, key: UUID, data: AccountInput) -> UUID:
        canonical = json.dumps(
            data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            previous = session.get(AccountCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise AccountConflict()
                account_id = previous.account_id
            else:
                account = Account(user_id=owner.user_id, **data.model_dump())
                session.add(account)
                session.flush()
                account_id = account.id
                session.add(
                    AccountCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        account_id=account_id,
                    )
                )
                session.flush()
        return account_id

    def list(self, token: SecretStr, *, limit: int, offset: int) -> AccountListResponse:
        with self.sessions.authorized_transaction(token) as (session, owner):
            rows = session.scalars(
                select(Account)
                .where(Account.user_id == owner.user_id)
                .order_by(Account.created_at, Account.id)
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = AccountListResponse(
                items=[AccountResponse.model_validate(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def get(self, token: SecretStr, account_id: UUID) -> AccountResponse:
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.scalar(
                select(Account).where(Account.id == account_id, Account.user_id == owner.user_id)
            )
            if row is None:
                raise AccountNotFound()
            result = AccountResponse.model_validate(row)
        return result

    def update(
        self, token: SecretStr, account_id: UUID, data: AccountUpdateInput, expected_etag: str
    ) -> AccountResponse:
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Account)
                .where(Account.id == account_id, Account.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise AccountNotFound()
            if not hmac.compare_digest(
                account_etag(AccountResponse.model_validate(row)), expected_etag
            ):
                raise AccountStale()
            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(row, field, value)
            session.flush()
            result = AccountResponse.model_validate(row)
        return result

    def correct_opening(
        self, token: SecretStr, account_id: UUID, data: AccountOpeningInput, expected_etag: str
    ) -> AccountResponse:
        # Financial writers use the same owner/account locks. Future import/allocation
        # services must follow this order before inserting references to an account.
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Account)
                .where(Account.id == account_id, Account.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise AccountNotFound()
            if not hmac.compare_digest(
                account_etag(AccountResponse.model_validate(row)), expected_etag
            ):
                raise AccountStale()
            if row.opening_balance != data.opening_balance or row.opening_date != data.opening_date:
                # Include removed movements, both transfer legs and every import status.
                references = session.scalar(
                    select(
                        or_(
                            select(Transaction.id)
                            .where(
                                Transaction.user_id == owner.user_id,
                                Transaction.account_id == account_id,
                            )
                            .exists(),
                            select(Transfer.id)
                            .where(
                                Transfer.user_id == owner.user_id,
                                or_(
                                    Transfer.from_account_id == account_id,
                                    Transfer.to_account_id == account_id,
                                ),
                            )
                            .exists(),
                            select(ImportJob.id)
                            .where(
                                ImportJob.user_id == owner.user_id,
                                ImportJob.account_id == account_id,
                            )
                            .exists(),
                            select(GoalAllocation.id)
                            .where(
                                GoalAllocation.user_id == owner.user_id,
                                GoalAllocation.account_id == account_id,
                            )
                            .exists(),
                        )
                    )
                )
                if references:
                    raise AccountOpeningLocked()
                row.opening_balance, row.opening_date = data.opening_balance, data.opening_date
                session.flush()
            result = AccountResponse.model_validate(row)
        return result
