"""Current-day reservations never move bank money; later spending only creates alerts."""

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import Account, AllocationCreationRequest, FinancialGoal, GoalAllocation
from app.schemas.accounts import AccountResponse
from app.schemas.allocations import (
    AllocationContextResponse,
    AllocationInput,
    AllocationListResponse,
    AllocationResponse,
    AvailabilityResponse,
    GoalFundingResponse,
    ReservationAlertsResponse,
)
from app.schemas.goals import GoalResponse
from app.services.accounts import AccountNotFound
from app.services.goals import GoalConflict, GoalNotFound, GoalStale
from app.services.sessions import SessionService
from app.services.transactions import account_balance_query


def business_date() -> date:
    return datetime.now(UTC).astimezone(ZoneInfo("America/Sao_Paulo")).date()


class AllocationRejected(Exception):
    pass


def context_etag(data: AllocationContextResponse) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return '"' + hashlib.sha256(canonical.encode()).hexdigest() + '"'


def reserved_query(owner: UUID, day: date, *, account_id=None, goal_id=None):
    query = select(func.coalesce(func.sum(GoalAllocation.amount), 0)).where(
        GoalAllocation.user_id == owner, GoalAllocation.allocation_date <= day
    )
    if account_id is not None:
        query = query.where(GoalAllocation.account_id == account_id)
    if goal_id is not None:
        query = query.where(GoalAllocation.goal_id == goal_id)
    return query


def funding(goal, reserved: Decimal, day: date):
    with localcontext() as context:
        context.prec = 80
        percent = (reserved * 100 / goal.target_amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return GoalFundingResponse(
        goal=GoalResponse.model_validate(goal),
        as_of=day,
        reserved_amount=reserved,
        remaining_amount=max(Decimal(0), goal.target_amount - reserved),
        excess_amount=max(Decimal(0), reserved - goal.target_amount),
        progress_percent=percent,
    )


def availability(account, balance: Decimal, reserved: Decimal, day: date):
    return AvailabilityResponse(
        account=AccountResponse.model_validate(account),
        as_of=day,
        bank_balance=balance,
        reserved_amount=reserved,
        free_balance=balance - reserved,
        uncovered_reserved=max(Decimal(0), reserved - max(Decimal(0), balance)),
    )


def availability_query(owner: UUID, day: date):
    bank = account_balance_query(owner, day).subquery()
    committed = (
        reserved_query(owner, day, account_id=Account.id).correlate(Account).scalar_subquery()
    )
    return (
        select(Account, bank.c.balance, committed.label("reserved"))
        .join(bank, bank.c.id == Account.id)
        .where(Account.user_id == owner, Account.opening_date <= day)
    )


def context_query(owner: UUID, goal_id: UUID, account_id: UUID, day: date):
    return (
        availability_query(owner, day)
        .add_columns(
            FinancialGoal,
            reserved_query(owner, day, goal_id=FinancialGoal.id)
            .correlate(FinancialGoal)
            .scalar_subquery()
            .label("goal_reserved"),
            reserved_query(owner, day, goal_id=FinancialGoal.id, account_id=Account.id)
            .correlate(FinancialGoal, Account)
            .scalar_subquery()
            .label("pair_reserved"),
        )
        .join(FinancialGoal, FinancialGoal.user_id == Account.user_id)
        .where(
            Account.id == account_id, FinancialGoal.id == goal_id, FinancialGoal.user_id == owner
        )
    )


def context_response(row, day):
    return AllocationContextResponse(
        funding=funding(row.FinancialGoal, row.goal_reserved, day),
        availability=availability(row.Account, row.balance, row.reserved, day),
        reserved_in_account=row.pair_reserved,
    )


class AllocationService:
    def __init__(self, sessions: SessionService, today: Callable[[], date] = business_date):
        self.sessions = sessions
        self.today = today

    def funding(self, token: SecretStr, goal_id: UUID):
        day = self.today()
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.execute(
                select(
                    FinancialGoal,
                    reserved_query(owner.user_id, day, goal_id=FinancialGoal.id)
                    .correlate(FinancialGoal)
                    .scalar_subquery()
                    .label("reserved"),
                ).where(FinancialGoal.user_id == owner.user_id, FinancialGoal.id == goal_id)
            ).one_or_none()
            if row is None:
                raise GoalNotFound()
            result = funding(row.FinancialGoal, row.reserved, day)
        return result

    def context(self, token: SecretStr, goal_id: UUID, account_id: UUID):
        day = self.today()
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.execute(
                context_query(owner.user_id, goal_id, account_id, day)
            ).one_or_none()
            if row is None:
                raise GoalNotFound()
            result = context_response(row, day)
        return result

    def availability(self, token: SecretStr, account_id: UUID):
        day = self.today()
        with self.sessions.authorized_transaction(token) as (session, owner):
            row = session.execute(
                availability_query(owner.user_id, day).where(Account.id == account_id)
            ).one_or_none()
            if row is None:
                raise AccountNotFound()
            result = availability(row.Account, row.balance, row.reserved, day)
        return result

    def alerts(self, token: SecretStr):
        day = self.today()
        with self.sessions.authorized_transaction(token) as (session, owner):
            # One snapshot for each account balance and its reserved total; only compromised rows.
            query = availability_query(owner.user_id, day)
            reserved = query.selected_columns.reserved
            balance = query.selected_columns.balance
            rows = session.execute(
                query.add_columns(func.count().over().label("total"))
                .where(reserved > 0, reserved > balance)
                .order_by(Account.name, Account.id)
                .limit(50)
            ).all()
            result = ReservationAlertsResponse(
                as_of=day,
                account_count=rows[0].total if rows else 0,
                items=[availability(row.Account, row.balance, row.reserved, day) for row in rows],
            )
        return result

    def create(self, token: SecretStr, goal_id: UUID, key: UUID, data: AllocationInput, etag: str):
        canonical = json.dumps(
            {"goal_id": str(goal_id), **data.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self.sessions.authorized_transaction(token, lock=True) as (session, owner):
            goal = session.scalar(
                select(FinancialGoal)
                .where(FinancialGoal.user_id == owner.user_id, FinancialGoal.id == goal_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if goal is None:
                raise GoalNotFound()
            previous = session.get(AllocationCreationRequest, (owner.user_id, key))
            if previous is not None:
                if not hmac.compare_digest(previous.request_hash, digest):
                    raise GoalConflict()
                identity = previous.allocation_id
            else:
                day = self.today()
                account = session.scalar(
                    select(Account)
                    .where(Account.user_id == owner.user_id, Account.id == data.account_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if account is None or account.opening_date > day:
                    raise AllocationRejected()
                row = session.execute(context_query(owner.user_id, goal_id, account.id, day)).one()
                current = context_response(row, day)
                if not hmac.compare_digest(context_etag(current), etag):
                    raise GoalStale()
                if data.allocation_date != day or account.currency != "BRL":
                    raise AllocationRejected()
                if data.kind == "reserve":
                    if (
                        not account.is_active
                        or goal.status != "active"
                        or data.amount > current.availability.free_balance
                    ):
                        raise AllocationRejected()
                    amount = data.amount
                else:
                    if data.amount > current.reserved_in_account:
                        raise AllocationRejected()
                    amount = -data.amount
                movement = GoalAllocation(
                    user_id=owner.user_id,
                    goal_id=goal_id,
                    account_id=account.id,
                    amount=amount,
                    allocation_date=day,
                    notes=data.notes,
                )
                session.add(movement)
                session.flush()
                identity = movement.id
                session.add(
                    AllocationCreationRequest(
                        user_id=owner.user_id,
                        idempotency_key=key,
                        request_hash=digest,
                        allocation_id=identity,
                    )
                )
                session.flush()
        return identity

    def list(self, token: SecretStr, goal_id: UUID, *, limit: int, offset: int):
        with self.sessions.authorized_transaction(token) as (session, owner):
            if (
                session.scalar(
                    select(FinancialGoal.id).where(
                        FinancialGoal.id == goal_id, FinancialGoal.user_id == owner.user_id
                    )
                )
                is None
            ):
                raise GoalNotFound()
            rows = session.execute(
                select(GoalAllocation, Account.name)
                .join(
                    Account,
                    (Account.id == GoalAllocation.account_id)
                    & (Account.user_id == GoalAllocation.user_id),
                )
                .where(GoalAllocation.user_id == owner.user_id, GoalAllocation.goal_id == goal_id)
                .order_by(GoalAllocation.created_at.desc(), GoalAllocation.id.desc())
                .limit(limit + 1)
                .offset(offset)
            ).all()
            result = AllocationListResponse(
                items=[
                    AllocationResponse(
                        id=row.GoalAllocation.id,
                        goal_id=goal_id,
                        account_id=row.GoalAllocation.account_id,
                        account_name=row.name,
                        amount=row.GoalAllocation.amount,
                        allocation_date=row.GoalAllocation.allocation_date,
                        notes=row.GoalAllocation.notes,
                    )
                    for row in rows[:limit]
                ],
                limit=limit,
                offset=offset,
                has_more=len(rows) > limit,
            )
        return result
