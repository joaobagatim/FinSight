"""Preview rows retain incomplete data while ownership stays database-enforced."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship, validates

from app.db.base import Base
from app.models.category import Category
from app.models.import_job import normalize_sha256

if TYPE_CHECKING:
    from app.models.import_job import ImportJob
    from app.models.transaction import Transaction


class ImportRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "account_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.account_id", "import_jobs.id"],
            name="fk_import_rows_owned_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["user_id", "suggested_category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_import_rows_owned_category",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "account_id", "id", name="uq_import_rows_owner_account_id"),
        UniqueConstraint("import_job_id", "row_number", name="uq_import_rows_job_row_number"),
        CheckConstraint("row_number > 0", name="ck_import_rows_number_positive"),
        CheckConstraint(
            "amount IS NULL OR amount BETWEEN 0 AND 9999999999999.99", name="ck_import_rows_amount"
        ),
        CheckConstraint(
            "type IS NULL OR type IN ('income', 'expense')", name="ck_import_rows_type"
        ),
        CheckConstraint(
            "fingerprint IS NULL OR fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_import_rows_fingerprint",
        ),
        CheckConstraint(
            "status IN ('pending', 'duplicate_candidate', 'invalid', 'imported', 'ignored')",
            name="ck_import_rows_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Technical keys derived from import_job; they prepare ownership-safe transaction references.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    import_job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    row_number: Mapped[int] = mapped_column(Integer)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
    type: Mapped[str | None] = mapped_column(String(10))
    suggested_category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    external_id: Mapped[str | None] = mapped_column(String(255))
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    import_job: Mapped["ImportJob"] = relationship(
        back_populates="rows", foreign_keys=[user_id, account_id, import_job_id]
    )
    suggested_category: Mapped["Category | None"] = relationship(
        primaryjoin=lambda: and_(
            Category.user_id == ImportRow.user_id,
            Category.id == foreign(ImportRow.suggested_category_id),
        )
    )

    transaction: Mapped["Transaction | None"] = relationship(
        back_populates="import_row",
        passive_deletes="all",
        primaryjoin=(
            "and_(ImportRow.user_id == Transaction.user_id, "
            "ImportRow.account_id == Transaction.account_id, "
            "ImportRow.id == foreign(Transaction.import_row_id))"
        ),
    )

    @validates("amount")
    def validate_amount(self, _key: str, value: Decimal | None) -> Decimal | None:
        # Zero can be retained in an invalid preview; confirmed transactions will require > 0.
        if value is not None and (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value < 0
            or value > Decimal("9999999999999.99")
            or value != value.quantize(Decimal("0.01"))
        ):
            raise ValueError(
                "Preview amount must be a non-negative finite Decimal within NUMERIC(15,2)"
            )
        return value

    @validates("fingerprint")
    def validate_fingerprint(self, _key: str, value: str | None) -> str | None:
        return None if value is None else normalize_sha256(value)
