"""Persist import previews with ownership keys for future transaction links."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_imports"
down_revision: str | None = "0003_accounts_categories"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_type", sa.String(10), server_default="csv", nullable=False),
        sa.Column("file_checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="uploaded", nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_import_jobs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_import_jobs_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_import_jobs_owned_account",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "account_id", "id", name="uq_import_jobs_owner_account_id"),
        sa.CheckConstraint(
            "filename = btrim(filename) AND char_length(filename) > 0 "
            "AND filename NOT IN ('.', '..') AND position('/' in filename) = 0 "
            "AND position(chr(92) in filename) = 0 AND filename !~ '[[:cntrl:]]'",
            name="ck_import_jobs_filename_base",
        ),
        sa.CheckConstraint("file_type = 'csv'", name="ck_import_jobs_file_type"),
        sa.CheckConstraint("file_checksum ~ '^[0-9a-f]{64}$'", name="ck_import_jobs_checksum"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'review', 'completed', 'failed', 'cancelled')",
            name="ck_import_jobs_status",
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND imported_rows >= 0 AND imported_rows <= total_rows",
            name="ck_import_jobs_counters",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_import_jobs_completion_date",
        ),
    )
    op.create_index("ix_import_jobs_user_created", "import_jobs", ["user_id", "created_at"])
    op.create_table(
        "import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("type", sa.String(10), nullable=True),
        sa.Column("suggested_category_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_rows"),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.account_id", "import_jobs.id"],
            name="fk_import_rows_owned_job",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "suggested_category_id"],
            ["categories.user_id", "categories.id"],
            name="fk_import_rows_owned_category",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "account_id", "id", name="uq_import_rows_owner_account_id"),
        sa.UniqueConstraint("import_job_id", "row_number", name="uq_import_rows_job_row_number"),
        sa.CheckConstraint("row_number > 0", name="ck_import_rows_number_positive"),
        sa.CheckConstraint(
            "amount IS NULL OR amount BETWEEN 0 AND 9999999999999.99", name="ck_import_rows_amount"
        ),
        sa.CheckConstraint(
            "type IS NULL OR type IN ('income', 'expense')", name="ck_import_rows_type"
        ),
        sa.CheckConstraint(
            "fingerprint IS NULL OR fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_import_rows_fingerprint",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'duplicate_candidate', 'invalid', 'imported', 'ignored')",
            name="ck_import_rows_status",
        ),
    )


def downgrade() -> None:
    # Explicit rollback deletes preview/job data; earlier identity/account/category tables remain.
    op.drop_table("import_rows")
    op.drop_table("import_jobs")
