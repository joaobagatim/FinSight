"""Import domain models explicitly to register Alembic metadata."""

from app.models.account import Account
from app.models.category import Category
from app.models.import_job import ImportJob
from app.models.import_row import ImportRow
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "Account",
    "Category",
    "ImportJob",
    "ImportRow",
    "Transaction",
    "Transfer",
    "User",
    "UserSession",
]
