"""Import metadata only; uploading and processing files belong to later services."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, validates

from app.db.base import Base
from app.models.account import Account

if TYPE_CHECKING:
    from app.models.import_row import ImportRow
    from app.models.user import User


def normalize_sha256(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("Checksum or fingerprint must be a SHA-256 hexadecimal digest")
    return value.lower()


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_import_jobs_owned_account",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "account_id", "id", name="uq_import_jobs_owner_account_id"),
        CheckConstraint(
            "filename = btrim(filename) AND char_length(filename) > 0 "
            "AND filename NOT IN ('.', '..') AND position('/' in filename) = 0 "
            "AND position(chr(92) in filename) = 0 AND filename !~ '[[:cntrl:]]'",
            name="ck_import_jobs_filename_base",
        ),
        CheckConstraint("file_type = 'csv'", name="ck_import_jobs_file_type"),
        CheckConstraint("file_checksum ~ '^[0-9a-f]{64}$'", name="ck_import_jobs_checksum"),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'review', 'completed', 'failed', 'cancelled')",
            name="ck_import_jobs_status",
        ),
        CheckConstraint(
            "total_rows >= 0 AND imported_rows >= 0 AND imported_rows <= total_rows",
            name="ck_import_jobs_counters",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_import_jobs_completion_date",
        ),
        Index("ix_import_jobs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_import_jobs_user_id_users", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(10), server_default="csv")
    file_checksum: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), server_default="uploaded")
    total_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    imported_rows: Mapped[int] = mapped_column(Integer, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="import_jobs", foreign_keys=[user_id])
    account: Mapped["Account"] = relationship(
        back_populates="import_jobs",
        primaryjoin=lambda: and_(
            Account.user_id == ImportJob.user_id, Account.id == foreign(ImportJob.account_id)
        ),
    )
    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="import_job",
        passive_deletes="all",
        foreign_keys="[ImportRow.user_id, ImportRow.account_id, ImportRow.import_job_id]",
    )

    @validates("filename")
    def validate_filename(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Filename must be a sanitized base name")
        value = value.strip()
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
        ):
            raise ValueError("Filename must be a sanitized base name")
        return value

    @validates("file_checksum")
    def validate_checksum(self, _key: str, value: str) -> str:
        return normalize_sha256(value)
