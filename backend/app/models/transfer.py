"""One transfer row; no synthetic income/expense rows or balance mutation."""

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
    Uuid,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, validates

from app.db.base import Base
from app.models.account import Account
from app.models.money import positive_money

if TYPE_CHECKING:
    from app.models.user import User


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "from_account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transfers_owned_from_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "to_account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transfers_owned_to_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint("from_account_id <> to_account_id", name="ck_transfers_distinct_accounts"),
        CheckConstraint("amount > 0 AND amount <= 9999999999999.99", name="ck_transfers_amount"),
        CheckConstraint("status IN ('planned', 'posted')", name="ck_transfers_status"),
        Index("ix_transfers_user_date", "user_id", "effective_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_transfers_user_id_users", ondelete="RESTRICT")
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    to_account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    status: Mapped[str] = mapped_column(String(10))
    effective_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="transfers", foreign_keys=[user_id])
    from_account: Mapped["Account"] = relationship(
        back_populates="outgoing_transfers",
        primaryjoin=lambda: and_(
            Account.user_id == Transfer.user_id, Account.id == foreign(Transfer.from_account_id)
        ),
    )
    to_account: Mapped["Account"] = relationship(
        back_populates="incoming_transfers",
        primaryjoin=lambda: and_(
            Account.user_id == Transfer.user_id, Account.id == foreign(Transfer.to_account_id)
        ),
    )

    @validates("amount")
    def validate_amount(self, _key: str, value: Decimal) -> Decimal:
        return positive_money(value)
