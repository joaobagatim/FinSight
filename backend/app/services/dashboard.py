"""Owner-scoped activity totals in one financial SQL snapshot."""

from sqlalchemy import func, select

from app.models import Account, Transaction
from app.schemas.dashboard import DashboardSummaryResponse
from app.services.accounts import AccountNotFound
from app.services.allocations import business_date


class DashboardRejected(Exception):
    pass


class DashboardService:
    def __init__(self, sessions, *, today=None):
        self.sessions = sessions
        self.today = today or business_date

    def summary(self, token, *, date_from, date_to, scope, account_ids):
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
            income = func.coalesce(
                func.sum(Transaction.amount).filter(Transaction.type == "income"), 0
            )
            expense = func.coalesce(
                func.sum(Transaction.amount).filter(Transaction.type == "expense"), 0
            )
            # No joins to transfers/reservations/categories that could multiply money rows.
            row = session.execute(
                select(
                    select(func.count()).select_from(accounts).scalar_subquery().label("accounts"),
                    func.count(Transaction.id).label("transactions"),
                    income.label("income"),
                    expense.label("expense"),
                    (income - expense).label("net"),
                )
                .select_from(Transaction)
                .join(accounts, accounts.c.id == Transaction.account_id)
                .where(
                    Transaction.user_id == owner.user_id,
                    Transaction.status == "posted",
                    Transaction.deleted_at.is_(None),
                    Transaction.effective_date > accounts.c.opening_date,
                    Transaction.effective_date >= date_from,
                    Transaction.effective_date <= date_to,
                )
            ).one()
            if scope == "selected" and row.accounts != len(selected):
                raise AccountNotFound()
            result = DashboardSummaryResponse(
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
            )
        return result
