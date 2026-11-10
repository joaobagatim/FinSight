"""Idempotent manual movements and derived balances, authorized per owner."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from unicodedata import category as unicode_category
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import (
    Date,
    DateTime,
    case,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
    union_all,
)
from sqlalchemy.orm import joinedload

from app.models import Account, Category, Transaction, TransactionCreationRequest, Transfer
from app.schemas.transactions import (
    AccountBalanceResponse,
    BalanceHistoryPoint,
    BalanceHistoryResponse,
    ConsolidatedBalanceResponse,
    ProjectedBalanceResponse,
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


def account_balance_query(
    user_id: UUID, as_of: date, *, status: str = "posted", from_date: date | None = None
):
    """Opening plus signed movements; planned callers must subtract the opening."""
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
            Transaction.status == status,
            Transaction.deleted_at.is_(None),
            Transaction.effective_date > Account.opening_date,
            Transaction.effective_date <= as_of,
            *([Transaction.effective_date >= from_date] if from_date is not None else []),
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
            Transfer.status == status,
            Transfer.deleted_at.is_(None),
            or_(Transfer.to_account_id == Account.id, Transfer.from_account_id == Account.id),
            Transfer.effective_date > Account.opening_date,
            Transfer.effective_date <= as_of,
            *([Transfer.effective_date >= from_date] if from_date is not None else []),
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
        search: str | None = None,
    ):
        if date_from is not None and date_to is not None and date_from > date_to:
            raise TransactionRejected()
        if search is not None:
            if len(search) > 255:
                raise TransactionRejected()
            search = search.strip()
            if not search or any(unicode_category(char).startswith("C") for char in search):
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
            if search is not None:
                # A bound, literal substring: SQL wildcard characters are escaped.
                query = query.where(Transaction.description.icontains(search, autoescape=True))
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

    def projected_balance(
        self,
        token: SecretStr,
        *,
        base_date: date,
        target_date: date,
        overdue_policy: str,
        scope: str,
        account_ids: list[UUID] | None,
    ):
        selected = account_ids or []
        if (
            target_date <= base_date
            or overdue_policy not in {"include", "exclude"}
            or scope not in {"active", "all", "selected"}
            or (
                scope == "selected"
                and (not selected or len(selected) > 100 or len(set(selected)) != len(selected))
            )
            or (scope != "selected" and selected)
        ):
            raise TransactionRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = account_balance_query(owner.user_id, base_date)
            if scope == "active":
                query = query.where(Account.is_active.is_(True))
            elif scope == "selected":
                query = query.where(Account.id.in_(selected))
            base = query.cte("projection_base")
            included = select(base.c.id)
            future = (
                account_balance_query(owner.user_id, target_date)
                .where(Account.id.in_(included))
                .cte("projection_future")
            )
            planned = (
                account_balance_query(
                    owner.user_id,
                    target_date,
                    status="planned",
                    from_date=base_date if overdue_policy == "exclude" else None,
                )
                .where(Account.id.in_(included))
                .cte("projection_planned")
            )
            # One statement/snapshot for every component; each CTE has one row per account.
            row = session.execute(
                select(
                    func.count(base.c.id).label("account_count"),
                    func.max(base.c.opening_date).label("newest_opening"),
                    func.coalesce(func.sum(base.c.balance), 0).label("base_balance"),
                    func.coalesce(func.sum(future.c.balance - base.c.balance), 0).label(
                        "posted_future_delta"
                    ),
                    func.coalesce(func.sum(planned.c.balance - planned.c.opening_balance), 0).label(
                        "planned_delta"
                    ),
                )
                .select_from(base)
                .join(future, future.c.id == base.c.id)
                .join(planned, planned.c.id == base.c.id)
            ).one()
            if scope == "selected" and row.account_count != len(selected):
                raise AccountNotFound()
            if row.newest_opening is not None and base_date < row.newest_opening:
                raise TransactionRejected()
            result = ProjectedBalanceResponse(
                base_date=base_date,
                target_date=target_date,
                overdue_policy=overdue_policy,
                scope=scope,
                account_ids=sorted(selected, key=str) if scope == "selected" else None,
                account_count=row.account_count,
                base_balance=row.base_balance,
                posted_future_delta=row.posted_future_delta,
                planned_delta=row.planned_delta,
                projected_balance=row.base_balance + row.posted_future_delta + row.planned_delta,
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

    def balance_history(
        self, token: SecretStr, account_id: UUID, *, date_from: date, date_to: date
    ):
        if date_to < date_from or (date_to - date_from).days >= 93:
            raise TransactionRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            base = (
                account_balance_query(owner.user_id, date_from)
                .where(Account.id == account_id)
                .add_columns(Account.name.label("account_name"))
                .cte("history_base")
            )
            events = union_all(
                select(
                    Transaction.effective_date.label("day"),
                    case(
                        (Transaction.type == "income", Transaction.amount),
                        else_=-Transaction.amount,
                    ).label("amount"),
                ).where(
                    Transaction.user_id == owner.user_id,
                    Transaction.account_id == account_id,
                    Transaction.status == "posted",
                    Transaction.deleted_at.is_(None),
                    Transaction.effective_date > date_from,
                    Transaction.effective_date <= date_to,
                ),
                select(
                    Transfer.effective_date.label("day"),
                    case(
                        (Transfer.to_account_id == account_id, Transfer.amount),
                        else_=-Transfer.amount,
                    ).label("amount"),
                ).where(
                    Transfer.user_id == owner.user_id,
                    Transfer.status == "posted",
                    Transfer.deleted_at.is_(None),
                    or_(
                        Transfer.from_account_id == account_id, Transfer.to_account_id == account_id
                    ),
                    Transfer.effective_date > date_from,
                    Transfer.effective_date <= date_to,
                ),
            ).cte("history_events")
            daily = (
                select(events.c.day, func.sum(events.c.amount).label("amount"))
                .group_by(events.c.day)
                .cte("history_daily")
            )
            days = (
                func.generate_series(
                    cast(literal(date_from), DateTime()),
                    cast(literal(date_to), DateTime()),
                    literal_column("interval '1 day'"),
                )
                .table_valued("day")
                .render_derived("history_days")
            )
            point_date = cast(days.c.day, Date)
            # One financial statement: exact baseline plus daily deltas in the same snapshot.
            rows = session.execute(
                select(
                    base.c.id,
                    base.c.account_name,
                    base.c.opening_date,
                    point_date.label("point_date"),
                    (
                        base.c.balance
                        + func.sum(func.coalesce(daily.c.amount, 0)).over(
                            order_by=point_date, rows=(None, 0)
                        )
                    ).label("balance"),
                )
                .select_from(base)
                .join(days, true())
                .outerjoin(daily, daily.c.day == point_date)
                .order_by(point_date)
            ).all()
            if not rows:
                raise AccountNotFound()
            if date_from < rows[0].opening_date:
                raise TransactionRejected()
            result = BalanceHistoryResponse(
                account_id=rows[0].id,
                account_name=rows[0].account_name,
                opening_date=rows[0].opening_date,
                date_from=date_from,
                date_to=date_to,
                points=[
                    BalanceHistoryPoint(date=row.point_date, balance=row.balance) for row in rows
                ],
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
