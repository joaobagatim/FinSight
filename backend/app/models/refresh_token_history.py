"""Consumed refresh digests; replay handling belongs to the future session service."""

import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user_session import UserSession


class RefreshTokenHistory(Base):
    __tablename__ = "refresh_token_history"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_token_history_token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_refresh_token_history_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "user_sessions.id", name="fk_refresh_token_history_session", ondelete="RESTRICT"
        ),
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["UserSession"] = relationship(back_populates="used_refresh_tokens")

    @validates("token_hash")
    def validate_token_hash(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Refresh token history requires a lowercase SHA-256 digest")
        return value
