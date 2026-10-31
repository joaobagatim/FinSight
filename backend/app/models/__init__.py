"""Import domain models explicitly to register Alembic metadata."""

from app.models.account import Account
from app.models.account_creation_request import AccountCreationRequest
from app.models.category import Category
from app.models.financial_goal import FinancialGoal
from app.models.goal_allocation import GoalAllocation
from app.models.import_job import ImportJob
from app.models.import_row import ImportRow
from app.models.refresh_token_history import RefreshTokenHistory
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "Account",
    "AccountCreationRequest",
    "Category",
    "FinancialGoal",
    "GoalAllocation",
    "ImportJob",
    "ImportRow",
    "RefreshTokenHistory",
    "Transaction",
    "Transfer",
    "User",
    "UserSession",
]
