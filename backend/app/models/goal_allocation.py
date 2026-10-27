"""Signed allocation movements; aggregate balance checks require later services."""

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
from app.models.financial_goal import FinancialGoal
from app.models.money import nonzero_money

if TYPE_CHECKING:
    from app.models.user import User


class GoalAllocation(Base):
    __tablename__ = "goal_allocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "goal_id"],
            ["financial_goals.user_id", "financial_goals.id"],
            name="fk_goal_allocations_owned_goal",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_goal_allocations_owned_account",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "amount <> 0 AND amount BETWEEN -9999999999999.99 AND 9999999999999.99",
            name="ck_goal_allocations_amount",
        ),
        Index("ix_goal_allocations_user_goal_date", "user_id", "goal_id", "allocation_date"),
        Index("ix_goal_allocations_user_account_date", "user_id", "account_id", "allocation_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_goal_allocations_user_id_users", ondelete="RESTRICT")
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    allocation_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="goal_allocations", foreign_keys=[user_id])
    # Only reference columns are written; the shared owner always remains explicit.
    goal: Mapped["FinancialGoal"] = relationship(
        back_populates="allocations",
        primaryjoin=lambda: and_(
            FinancialGoal.user_id == GoalAllocation.user_id,
            FinancialGoal.id == foreign(GoalAllocation.goal_id),
        ),
    )
    account: Mapped["Account"] = relationship(
        back_populates="goal_allocations",
        primaryjoin=lambda: and_(
            Account.user_id == GoalAllocation.user_id,
            Account.id == foreign(GoalAllocation.account_id),
        ),
    )

    @validates("amount")
    def validate_amount(self, _key: str, value: Decimal) -> Decimal:
        return nonzero_money(value)
