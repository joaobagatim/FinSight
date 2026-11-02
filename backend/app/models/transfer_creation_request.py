"""Persist transfer creation identity without retaining request bodies or credentials."""

import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.transfer import Transfer


class TransferCreationRequest(Base):
    __tablename__ = "transfer_creation_requests"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_transfer_creation_requests"),
        ForeignKeyConstraint(
            ["user_id", "transfer_id"],
            ["transfers.user_id", "transfers.id"],
            name="fk_transfer_creation_requests_owned_transfer",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_transfer_creation_requests_hash"
        ),
        CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_transfer_creation_requests_key_v4",
        ),
        Index("ix_transfer_creation_requests_transfer", "user_id", "transfer_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_transfer_creation_requests_user", ondelete="RESTRICT"),
        primary_key=True,
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    transfer_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transfer: Mapped["Transfer"] = relationship()

    @validates("request_hash")
    def validate_request_hash(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Transfer creation requires a lowercase SHA-256 digest")
        return value

    @validates("idempotency_key")
    def validate_key(self, _key: str, value: uuid.UUID) -> uuid.UUID:
        if not isinstance(value, uuid.UUID) or value.version != 4:
            raise ValueError("Transfer creation requires a UUIDv4 idempotency key")
        return value
