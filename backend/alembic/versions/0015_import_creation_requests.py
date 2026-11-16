"""Retain preview creation keys; never discard their replay memory on downgrade."""

import sqlalchemy as sa
from alembic import op

revision: str = "0015_import_creation_requests"
down_revision: str | None = "0014_allocation_requests"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade():
    op.create_index(
        "ix_import_jobs_owner_account_checksum",
        "import_jobs",
        ["user_id", "account_id", "file_checksum"],
    )
    op.create_table(
        "import_creation_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_import_creation_requests"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_import_creation_requests_user", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id", "import_job_id"],
            ["import_jobs.user_id", "import_jobs.account_id", "import_jobs.id"],
            name="fk_import_creation_requests_owned_job",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_import_creation_requests_hash"
        ),
        sa.CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_import_creation_requests_key_v4",
        ),
    )
    op.create_index(
        "ix_import_creation_requests_job",
        "import_creation_requests",
        ["user_id", "account_id", "import_job_id"],
    )


def downgrade():
    op.execute("LOCK TABLE import_creation_requests IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM import_creation_requests) THEN
            RAISE EXCEPTION 'Cannot discard retained import creation identities';
        END IF;
    END $$;""")
    op.drop_index("ix_import_creation_requests_job", table_name="import_creation_requests")
    op.drop_table("import_creation_requests")
    op.drop_index("ix_import_jobs_owner_account_checksum", table_name="import_jobs")
