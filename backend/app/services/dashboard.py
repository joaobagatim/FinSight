"""Owner-scoped activity totals in one financial SQL snapshot."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import String, cast, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.models import Account, Category, Transaction
from app.schemas.dashboard import (
    DailyActivity,
    DashboardBreakdownResponse,
    DashboardSummaryResponse,
)
from app.services.accounts import AccountNotFound
from app.services.allocations import business_date


class DashboardRejected(Exception):
    pass


def breakdown_columns(movements, owner):
    income = func.coalesce(func.sum(movements.c.amount).filter(movements.c.type == "income"), 0)
    expense = func.coalesce(func.sum(movements.c.amount).filter(movements.c.type == "expense"), 0)
    daily = (
        select(
            movements.c.effective_date.label("date"),
            func.count().label("transaction_count"),
            income.label("income"),
            expense.label("expense"),
            (income - expense).label("net"),
        )
        .group_by(movements.c.effective_date)
        .cte("dashboard_daily")
    )
    # JSON numeric decoding can introduce float money: serialize amounts as SQL text first.
    daily_json = (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "date",
                            daily.c.date,
                            "transaction_count",
                            daily.c.transaction_count,
                            "income",
                            cast(daily.c.income, String),
                            "expense",
                            cast(daily.c.expense, String),
                            "net",
                            cast(daily.c.net, String),
                        ),
                        daily.c.date,
                    )
                ),
                func.jsonb_build_array(),
            )
        )
        .select_from(daily)
        .scalar_subquery()
    )
    grouped = (
        select(
            movements.c.category_id,
            func.sum(movements.c.amount).label("amount"),
            func.count().label("transaction_count"),
        )
        .where(movements.c.type == "expense")
        .group_by(movements.c.category_id)
        .cte("dashboard_expenses")
    )
    ranked = (
        select(
            grouped,
            Category.name,
            func.row_number()
            .over(order_by=(grouped.c.amount.desc(), grouped.c.category_id))
            .label("rank"),
        )
        .join(Category, Category.id == grouped.c.category_id)
        .where(Category.user_id == owner)
        .cte("dashboard_categories")
    )
    categories_json = (
        select(
            func.coalesce(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "category_id",
                            ranked.c.category_id,
                            "name",
                            ranked.c.name,
                            "amount",
                            cast(ranked.c.amount, String),
                            "transaction_count",
                            ranked.c.transaction_count,
                        ),
                        ranked.c.rank,
                    )
                ),
                func.jsonb_build_array(),
            )
        )
        .where(ranked.c.rank <= 20)
        .scalar_subquery()
    )
    other = (
        select(
            func.jsonb_build_object(
                "category_count",
                func.count(),
                "transaction_count",
                func.coalesce(func.sum(ranked.c.transaction_count), 0),
                "amount",
                cast(func.coalesce(func.sum(ranked.c.amount), 0), String),
            )
        )
        .where(ranked.c.rank > 20)
        .scalar_subquery()
    )
    return [
        daily_json.label("daily"),
        categories_json.label("expense_categories"),
        select(func.count()).select_from(ranked).scalar_subquery().label("expense_category_count"),
        other.label("other_expenses"),
    ]


class DashboardService:
    def __init__(self, sessions, *, today=None):
        self.sessions = sessions
        self.today = today or business_date

    def summary(self, token, *, date_from, date_to, scope, account_ids, include_breakdown=False):
        day = self.today()
        selected = account_ids or []
        if (
            date_from > date_to
            or (date_to - date_from).days >= 366
            or date_to > day
            or scope not in {"active", "all", "selected"}
            or (
                scope == "selected"
                and (not selected or len(selected) > 100 or len(set(selected)) != len(selected))
            )
            or (scope != "selected" and selected)
        ):
            raise DashboardRejected()
        with self.sessions.authorized_transaction(token) as (session, owner):
            query = select(Account.id, Account.opening_date).where(Account.user_id == owner.user_id)
            if scope == "active":
                query = query.where(Account.is_active.is_(True))
            elif scope == "selected":
                query = query.where(Account.id.in_(selected))
            accounts = query.cte("dashboard_accounts")
            movements = (
                select(
                    Transaction.id,
                    Transaction.category_id,
                    Transaction.amount,
                    Transaction.type,
                    Transaction.effective_date,
                )
                .join(accounts, accounts.c.id == Transaction.account_id)
                .where(
                    Transaction.user_id == owner.user_id,
                    Transaction.status == "posted",
                    Transaction.deleted_at.is_(None),
                    Transaction.effective_date > accounts.c.opening_date,
                    Transaction.effective_date >= date_from,
                    Transaction.effective_date <= date_to,
                )
                .cte("dashboard_movements")
            )
            income = func.coalesce(
                func.sum(movements.c.amount).filter(movements.c.type == "income"), 0
            )
            expense = func.coalesce(
                func.sum(movements.c.amount).filter(movements.c.type == "expense"), 0
            )
            # No joins to transfers/reservations/categories that could multiply money rows.
            row = session.execute(
                select(
                    select(func.count()).select_from(accounts).scalar_subquery().label("accounts"),
                    func.count(movements.c.id).label("transactions"),
                    income.label("income"),
                    expense.label("expense"),
                    (income - expense).label("net"),
                    *(breakdown_columns(movements, owner.user_id) if include_breakdown else []),
                ).select_from(movements)
            ).one()
            if scope == "selected" and row.accounts != len(selected):
                raise AccountNotFound()
            extra = {}
            if include_breakdown:
                by_day = {point["date"]: point for point in row.daily}
                # Fill calendar gaps only; all financial arithmetic stays in the same SQL statement.
                daily_points = []
                for offset in range((date_to - date_from).days + 1):
                    day_date = date_from + timedelta(days=offset)
                    point = by_day.get(day_date.isoformat())
                    daily_points.append(
                        DailyActivity(**point)
                        if point
                        else DailyActivity(
                            date=day_date,
                            transaction_count=0,
                            income=Decimal(0),
                            expense=Decimal(0),
                            net=Decimal(0),
                        )
                    )
                extra = dict(
                    daily=daily_points,
                    expense_categories=row.expense_categories,
                    expense_category_count=row.expense_category_count,
                    other_expenses=row.other_expenses,
                )
            response = DashboardBreakdownResponse if include_breakdown else DashboardSummaryResponse
            result = response(
                date_from=date_from,
                date_to=date_to,
                as_of=day,
                scope=scope,
                account_ids=sorted(selected, key=str) if scope == "selected" else None,
                account_count=row.accounts,
                transaction_count=row.transactions,
                income=row.income,
                expense=row.expense,
                net=row.net,
                **extra,
            )
        return result
