"""Account persistence; balances derived from transactions belong to later services."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.goal_allocation import GoalAllocation
    from app.models.import_job import ImportJob
    from app.models.transaction import Transaction
    from app.models.transfer import Transfer
    from app.models.user import User


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_accounts_user_id_id"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_accounts_name_not_blank"),
        CheckConstraint(
            "type IN ('checking', 'savings', 'cash', 'investment')", name="ck_accounts_type"
        ),
        CheckConstraint("currency = 'BRL'", name="ck_accounts_currency_brl"),
        # The upper bound also excludes PostgreSQL numeric NaN, which sorts above finite numbers.
        CheckConstraint(
            "opening_balance BETWEEN -9999999999999.99 AND 9999999999999.99",
            name="ck_accounts_opening_balance_finite",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_accounts_user_id_users", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="BRL")
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    opening_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="accounts")
    import_jobs: Mapped[list["ImportJob"]] = relationship(
        back_populates="account",
        passive_deletes="all",
        primaryjoin=(
            "and_(Account.user_id == ImportJob.user_id, "
            "Account.id == foreign(ImportJob.account_id))"
        ),
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account",
        passive_deletes="all",
        primaryjoin=(
            "and_(Account.user_id == Transaction.user_id, "
            "Account.id == foreign(Transaction.account_id))"
        ),
    )
    outgoing_transfers: Mapped[list["Transfer"]] = relationship(
        back_populates="from_account",
        passive_deletes="all",
        primaryjoin=(
            "and_(Account.user_id == Transfer.user_id, "
            "Account.id == foreign(Transfer.from_account_id))"
        ),
    )
    incoming_transfers: Mapped[list["Transfer"]] = relationship(
        back_populates="to_account",
        passive_deletes="all",
        primaryjoin=(
            "and_(Account.user_id == Transfer.user_id, "
            "Account.id == foreign(Transfer.to_account_id))"
        ),
    )

    goal_allocations: Mapped[list["GoalAllocation"]] = relationship(
        back_populates="account",
        passive_deletes="all",
        primaryjoin=(
            "and_(Account.user_id == GoalAllocation.user_id, "
            "Account.id == foreign(GoalAllocation.account_id))"
        ),
    )

    @validates("opening_balance")
    def validate_opening_balance(self, _key: str, value: Decimal) -> Decimal:
        if (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value.copy_abs() > Decimal("9999999999999.99")
            or value != value.quantize(Decimal("0.01"))
        ):
            raise ValueError("Opening balance must be a finite Decimal within NUMERIC(15,2)")
        return value
