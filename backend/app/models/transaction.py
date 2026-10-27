"""Income/expense persistence; balances and confirmation belong to later services."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, validates

from app.db.base import Base
from app.models.account import Account
from app.models.category import Category
from app.models.import_row import ImportRow
from app.models.money import positive_money

if TYPE_CHECKING:
    from app.models.user import User


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transactions_owned_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "category_id", "type"],
            ["categories.user_id", "categories.id", "categories.type"],
            name="fk_transactions_owned_category_type",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "account_id", "import_row_id"],
            ["import_rows.user_id", "import_rows.account_id", "import_rows.id"],
            name="fk_transactions_owned_import_row",
            ondelete="RESTRICT",
        ),
        CheckConstraint("char_length(btrim(description)) > 0", name="ck_transactions_description"),
        CheckConstraint("amount > 0 AND amount <= 9999999999999.99", name="ck_transactions_amount"),
        CheckConstraint("type IN ('income', 'expense')", name="ck_transactions_type"),
        CheckConstraint("status IN ('planned', 'posted')", name="ck_transactions_status"),
        Index("ix_transactions_user_date", "user_id", "effective_date"),
        Index("ix_transactions_account_date", "account_id", "effective_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_transactions_user_id_users", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    type: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    effective_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    import_row_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transactions", foreign_keys=[user_id])
    # Each relation writes only its own reference, never the shared owner/type/account keys.
    account: Mapped["Account"] = relationship(
        back_populates="transactions",
        primaryjoin=lambda: and_(
            Account.user_id == Transaction.user_id, Account.id == foreign(Transaction.account_id)
        ),
    )
    category: Mapped["Category"] = relationship(
        back_populates="transactions",
        primaryjoin=lambda: and_(
            Category.user_id == Transaction.user_id,
            Category.id == foreign(Transaction.category_id),
            Category.type == Transaction.type,
        ),
    )
    import_row: Mapped["ImportRow | None"] = relationship(
        back_populates="transaction",
        primaryjoin=lambda: and_(
            ImportRow.user_id == Transaction.user_id,
            ImportRow.account_id == Transaction.account_id,
            ImportRow.id == foreign(Transaction.import_row_id),
        ),
    )

    @validates("amount")
    def validate_amount(self, _key: str, value: Decimal) -> Decimal:
        return positive_money(value)

    @validates("description")
    def validate_description(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Transaction description must not be blank")
        return value.strip()


Index(
    "uq_transactions_import_row",
    Transaction.import_row_id,
    unique=True,
    postgresql_where=Transaction.import_row_id.is_not(None),
)
