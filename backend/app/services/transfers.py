"""One atomic transfer and durable owner-scoped creation identity."""

import hashlib
import hmac
import json
from datetime import date
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.models import Account, Transfer, TransferCreationRequest
from app.schemas.transfers import TransferInput, TransferListResponse, TransferResponse
from app.services.sessions import SessionService


class TransferNotFound(Exception):
    pass


class TransferRejected(Exception):
    pass


class TransferConflict(Exception):
    pass


class TransferService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    def create(self, token: SecretStr, key: UUID, data: TransferInput) -> UUID:
        canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            previous = session.get(TransferCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise TransferConflict()
                transfer_id = previous.transfer_id
            else:
                accounts = session.scalars(
                    select(Account)
                    .where(
                        Account.user_id == owner.user_id,
                        Account.id.in_([data.from_account_id, data.to_account_id]),
                    )
                    .order_by(Account.id)
                    .with_for_update()
                ).all()
                if len(accounts) != 2 or any(
                    not account.is_active
                    or account.currency != "BRL"
                    or data.effective_date <= account.opening_date
                    for account in accounts
                ):
                    raise TransferRejected()
                row = Transfer(user_id=owner.user_id, **data.model_dump())
                session.add(row)
                session.flush()
                transfer_id = row.id
                session.add(
                    TransferCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        transfer_id=transfer_id,
                    )
                )
                session.flush()
        return transfer_id

    def get(self, token: SecretStr, transfer_id: UUID) -> TransferResponse:
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.scalar(
                select(Transfer)
                .options(joinedload(Transfer.from_account), joinedload(Transfer.to_account))
                .where(Transfer.id == transfer_id, Transfer.user_id == owner.user_id)
            )
            if row is None:
                raise TransferNotFound()
            result = TransferResponse.model_validate(row)
        return result

    def list(
        self,
        token: SecretStr,
        *,
        limit: int,
        offset: int,
        account_id: UUID | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
    ):
        if date_from is not None and date_to is not None and date_from > date_to:
            raise TransferRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = (
                select(Transfer)
                .options(joinedload(Transfer.from_account), joinedload(Transfer.to_account))
                .where(Transfer.user_id == owner.user_id)
            )
            if account_id is not None:
                query = query.where(
                    or_(
                        Transfer.from_account_id == account_id, Transfer.to_account_id == account_id
                    )
                )
            if status is not None:
                query = query.where(Transfer.status == status)
            if date_from is not None:
                query = query.where(Transfer.effective_date >= date_from)
            if date_to is not None:
                query = query.where(Transfer.effective_date <= date_to)
            rows = session.scalars(
                query.order_by(
                    Transfer.effective_date.desc(), Transfer.created_at.desc(), Transfer.id.desc()
                )
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = TransferListResponse(
                items=[TransferResponse.model_validate(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result
