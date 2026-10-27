"""Goal persistence; progress and reservation policies belong to later services."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base
from app.models.money import positive_money

if TYPE_CHECKING:
    from app.models.goal_allocation import GoalAllocation
    from app.models.user import User


class FinancialGoal(Base):
    __tablename__ = "financial_goals"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_financial_goals_user_id_id"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_financial_goals_name"),
        CheckConstraint(
            "target_amount > 0 AND target_amount <= 9999999999999.99",
            name="ck_financial_goals_target_amount",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')", name="ck_financial_goals_status"
        ),
        Index("ix_financial_goals_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_financial_goals_user_id_users", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="financial_goals")
    allocations: Mapped[list["GoalAllocation"]] = relationship(
        back_populates="goal",
        passive_deletes="all",
        primaryjoin=(
            "and_(FinancialGoal.user_id == GoalAllocation.user_id, "
            "FinancialGoal.id == foreign(GoalAllocation.goal_id))"
        ),
    )

    @validates("target_amount")
    def validate_target_amount(self, _key: str, value: Decimal) -> Decimal:
        return positive_money(value)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Goal name must not be blank")
        return value.strip()
