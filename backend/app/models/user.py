"""User identity; password hashing belongs to the future authentication service."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    UniqueConstraint,
    Uuid,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.category import Category
    from app.models.import_job import ImportJob
    from app.models.user_session import UserSession


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_users_name_not_blank"),
        CheckConstraint(
            "email = lower(btrim(email)) AND char_length(email) > 0",
            name="ck_users_email_normalized",
        ),
        CheckConstraint(
            "char_length(btrim(password_hash)) > 0", name="ck_users_password_hash_not_blank"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", passive_deletes="all"
    )
    accounts: Mapped[list["Account"]] = relationship(back_populates="user", passive_deletes="all")
    categories: Mapped[list["Category"]] = relationship(
        back_populates="user", passive_deletes="all"
    )

    import_jobs: Mapped[list["ImportJob"]] = relationship(
        back_populates="user", passive_deletes="all", foreign_keys="ImportJob.user_id"
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        return value.strip().lower()
