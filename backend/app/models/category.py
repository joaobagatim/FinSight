"""Per-user classification with database-enforced normalized-name uniqueness."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("user_id", "id", name="uq_categories_user_id_id"),
        UniqueConstraint("user_id", "id", "type", name="uq_categories_user_id_id_type"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_categories_name_not_blank"),
        CheckConstraint("type IN ('income', 'expense')", name="ck_categories_type"),
        CheckConstraint("color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'", name="ck_categories_color"),
        CheckConstraint(
            "icon IS NULL OR char_length(btrim(icon)) > 0", name="ck_categories_icon_not_blank"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_categories_user_id_users", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(10))
    color: Mapped[str | None] = mapped_column(String(7))
    icon: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="categories")

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="category",
        passive_deletes="all",
        primaryjoin=(
            "and_(Category.user_id == Transaction.user_id, "
            "Category.id == foreign(Transaction.category_id), Category.type == Transaction.type)"
        ),
    )

    @validates("name")
    def trim_display_name(self, _key: str, value: str) -> str:
        return value.strip()


Index(
    "uq_categories_user_type_normalized_name",
    Category.user_id,
    Category.type,
    func.lower(func.btrim(Category.name)),
    unique=True,
)
