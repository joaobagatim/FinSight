"""Retain preview creation identities without retaining uploaded source files."""

import uuid
from datetime import datetime

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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImportCreationRequest(Base):
    __tablename__ = "import_creation_requests"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_import_creation_requests"),
        ForeignKeyConstraint(
            ["user_id", "account_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.account_id", "import_jobs.id"],
            name="fk_import_creation_requests_owned_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$'", name="ck_import_creation_requests_hash"),
        CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_import_creation_requests_key_v4",
        ),
        Index("ix_import_creation_requests_job", "user_id", "account_id", "import_job_id"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_import_creation_requests_user", ondelete="RESTRICT"),
        primary_key=True,
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
