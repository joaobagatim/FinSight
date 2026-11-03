"""Idempotent manual movements and derived balances, authorized per owner."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import joinedload

from app.models import Account, Category, Transaction, TransactionCreationRequest, Transfer
from app.schemas.transactions import (
    AccountBalanceResponse,
    ConsolidatedBalanceResponse,
    TransactionInput,
    TransactionListResponse,
    TransactionResponse,
    TransactionUpdateInput,
)
from app.services.accounts import AccountNotFound
from app.services.sessions import SessionService


class TransactionNotFound(Exception):
    pass


class TransactionRejected(Exception):
    pass


class TransactionConflict(Exception):
    pass


class TransactionStale(Exception):
    pass


class TransactionRemoved(Exception):
    pass


def transaction_etag(data: TransactionResponse) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'


def account_balance_query(user_id: UUID, as_of: date):
    movements = (
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.type == "income", Transaction.amount),
                        else_=-Transaction.amount,
                    )
                ),
                0,
            )
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.account_id == Account.id,
            Transaction.status == "posted",
            Transaction.deleted_at.is_(None),
            Transaction.effective_date > Account.opening_date,
            Transaction.effective_date <= as_of,
        )
        .correlate(Account)
        .scalar_subquery()
    )
    transfers = (
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transfer.to_account_id == Account.id, Transfer.amount),
                        else_=-Transfer.amount,
                    )
                ),
                0,
            )
        )
        .where(
            Transfer.user_id == user_id,
            Transfer.status == "posted",
            or_(Transfer.to_account_id == Account.id, Transfer.from_account_id == Account.id),
            Transfer.effective_date > Account.opening_date,
            Transfer.effective_date <= as_of,
        )
        .correlate(Account)
        .scalar_subquery()
    )
    return select(
        Account.id,
        Account.opening_date,
        Account.opening_balance,
        (Account.opening_balance + movements + transfers).label("balance"),
    ).where(Account.user_id == user_id)


class TransactionService:
    def __init__(self, sessions: SessionService):
        self.sessions = sessions

    def create(self, token: SecretStr, key: UUID, data: TransactionInput) -> UUID:
        canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            previous = session.get(TransactionCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise TransactionConflict()
                if previous.transaction.deleted_at is not None:
                    raise TransactionRemoved()
                transaction_id = previous.transaction_id
            else:
                account = session.scalar(
                    select(Account)
                    .where(Account.id == data.account_id, Account.user_id == owner.user_id)
                    .with_for_update()
                )
                category = session.scalar(
                    select(Category)
                    .where(Category.id == data.category_id, Category.user_id == owner.user_id)
                    .with_for_update()
                )
                if (
                    account is None
                    or category is None
                    or not account.is_active
                    or not category.is_active
                    or category.type != data.type
                    or data.effective_date <= account.opening_date
                ):
                    raise TransactionRejected()
                row = Transaction(user_id=owner.user_id, **data.model_dump())
                session.add(row)
                session.flush()
                transaction_id = row.id
                session.add(
                    TransactionCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        transaction_id=transaction_id,
                    )
                )
                session.flush()
        return transaction_id

    def list(
        self,
        token: SecretStr,
        *,
        limit: int,
        offset: int,
        account_id: UUID | None,
        category_id: UUID | None,
        kind: str | None,
        status: str | None,
        date_from: date | None,
        date_to: date | None,
    ):
        if date_from is not None and date_to is not None and date_from > date_to:
            raise TransactionRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = (
                select(Transaction)
                .options(joinedload(Transaction.account), joinedload(Transaction.category))
                .where(Transaction.user_id == owner.user_id, Transaction.deleted_at.is_(None))
            )
            for field, value in (
                (Transaction.account_id, account_id),
                (Transaction.category_id, category_id),
                (Transaction.type, kind),
                (Transaction.status, status),
            ):
                if value is not None:
                    query = query.where(field == value)
            if date_from is not None:
                query = query.where(Transaction.effective_date >= date_from)
            if date_to is not None:
                query = query.where(Transaction.effective_date <= date_to)
            rows = session.scalars(
                query.order_by(
                    Transaction.effective_date.desc(),
                    Transaction.created_at.desc(),
                    Transaction.id.desc(),
                )
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = TransactionListResponse(
                items=[TransactionResponse.model_validate(row) for row in rows[:limit]],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result

    def get(self, token: SecretStr, transaction_id: UUID):
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.scalar(
                select(Transaction)
                .options(joinedload(Transaction.account), joinedload(Transaction.category))
                .where(Transaction.id == transaction_id, Transaction.user_id == owner.user_id)
            )
            if row is None:
                raise TransactionNotFound()
            if row.deleted_at is not None:
                raise TransactionRemoved()
            result = TransactionResponse.model_validate(row)
        return result

    def update(
        self, token: SecretStr, transaction_id: UUID, data: TransactionUpdateInput, etag: str
    ) -> TransactionResponse:
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Transaction)
                .where(Transaction.id == transaction_id, Transaction.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise TransactionNotFound()
            if row.deleted_at is not None:
                raise TransactionRemoved()
            current = TransactionResponse.model_validate(row)
            if not hmac.compare_digest(transaction_etag(current), etag):
                raise TransactionStale()
            if row.import_row_id is not None:
                # Imported provenance needs a dedicated reconciliation policy.
                raise TransactionRejected()
            changes = data.model_dump(exclude_unset=True)
            account_id = changes.get("account_id", row.account_id)
            category_id = changes.get("category_id", row.category_id)
            account = session.scalar(
                select(Account)
                .where(Account.id == account_id, Account.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            category = session.scalar(
                select(Category)
                .where(Category.id == category_id, Category.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                account is None
                or category is None
                or not account.is_active
                or not category.is_active
                or category.type != changes.get("type", row.type)
                or changes.get("effective_date", row.effective_date) <= account.opening_date
            ):
                raise TransactionRejected()
            for field, value in changes.items():
                setattr(row, field, value)
            row.account, row.category = account, category
            session.flush()
            result = TransactionResponse.model_validate(row)
        return result

    def delete(self, token: SecretStr, transaction_id: UUID, etag: str) -> None:
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Transaction)
                .where(Transaction.id == transaction_id, Transaction.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise TransactionNotFound()
            if row.deleted_at is None:
                if not hmac.compare_digest(
                    transaction_etag(TransactionResponse.model_validate(row)), etag
                ):
                    raise TransactionStale()
                if row.import_row_id is not None:
                    raise TransactionRejected()
                # Keep the row, owner and immutable creation identity; never restore via retry.
                row.deleted_at = func.now()
                session.flush()

    def post(self, token: SecretStr, transaction_id: UUID, etag: str) -> TransactionResponse:
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            row = session.scalar(
                select(Transaction)
                .where(Transaction.id == transaction_id, Transaction.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise TransactionNotFound()
            if row.deleted_at is not None:
                raise TransactionRemoved()
            account = session.scalar(
                select(Account)
                .where(Account.id == row.account_id, Account.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            category = session.scalar(
                select(Category)
                .where(Category.id == row.category_id, Category.user_id == owner.user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if account is None or category is None:
                raise TransactionRejected()
            current = TransactionResponse.model_validate(row)
            matches = hmac.compare_digest(transaction_etag(current), etag)
            if row.status == "posted":
                # Repeating the same confirmed planned snapshot cannot book a second movement.
                planned = current.model_copy(update={"status": "planned"})
                if not matches and not hmac.compare_digest(transaction_etag(planned), etag):
                    raise TransactionStale()
                result = current
            else:
                if not matches:
                    raise TransactionStale()
                if (
                    not account.is_active
                    or not category.is_active
                    or category.type != row.type
                    or row.effective_date <= account.opening_date
                    or row.import_row_id is not None
                ):
                    raise TransactionRejected()
                row.status = "posted"
                session.flush()
                result = TransactionResponse.model_validate(row)
        return result

    def balance(self, token: SecretStr, account_id: UUID, as_of: date):
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.execute(
                account_balance_query(owner.user_id, as_of).where(Account.id == account_id)
            ).one_or_none()
            if row is None:
                raise AccountNotFound()
            if as_of < row.opening_date:
                raise TransactionRejected()
            result = AccountBalanceResponse(
                account_id=row.id,
                as_of=as_of,
                opening_date=row.opening_date,
                opening_balance=row.opening_balance,
                balance=row.balance,
            )
        return result

    def consolidated_balance(
        self, token: SecretStr, *, as_of: date, scope: str, account_ids: list[UUID] | None
    ):
        selected = account_ids or []
        if (
            scope not in {"active", "all", "selected"}
            or (
                scope == "selected"
                and (not selected or len(selected) > 100 or len(set(selected)) != len(selected))
            )
            or (scope != "selected" and selected)
        ):
            raise TransactionRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = account_balance_query(owner.user_id, as_of)
            if scope == "active":
                query = query.where(Account.is_active.is_(True))
            elif scope == "selected":
                query = query.where(Account.id.in_(selected))
            balances = query.subquery()
            # One aggregate statement gives a single MVCC snapshot, including both transfer sides.
            result_row = session.execute(
                select(
                    func.count(balances.c.id).label("account_count"),
                    func.coalesce(func.sum(balances.c.balance), 0).label("balance"),
                    func.max(balances.c.opening_date).label("newest_opening"),
                )
            ).one()
            if scope == "selected" and result_row.account_count != len(selected):
                raise AccountNotFound()
            if result_row.newest_opening is not None and as_of < result_row.newest_opening:
                raise TransactionRejected()
            result = ConsolidatedBalanceResponse(
                as_of=as_of,
                scope=scope,
                account_ids=sorted(selected, key=str) if scope == "selected" else None,
                account_count=result_row.account_count,
                balance=result_row.balance,
            )
        return result
