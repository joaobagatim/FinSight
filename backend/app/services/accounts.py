"""Own account queries and atomic, persistent account creation retries."""

import hashlib
import hmac
import json
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select

from app.models import Account, AccountCreationRequest
from app.schemas.accounts import AccountInput, AccountListResponse, AccountResponse
from app.services.sessions import SessionService


class AccountNotFound(Exception):
    pass


class AccountConflict(Exception):
    pass


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
