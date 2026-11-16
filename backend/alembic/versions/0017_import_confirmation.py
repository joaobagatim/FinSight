"""Retain one immutable confirmation identity and receipt per import job."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_import_confirmation"
down_revision = "0016_import_review_selection"
branch_labels = None
depends_on = None

CONFIRMATION = (
    "(confirmation_key IS NULL AND confirmation_hash IS NULL AND confirmation_result IS NULL) OR "
    "(confirmation_key IS NOT NULL AND confirmation_hash IS NOT NULL "
    "AND confirmation_result IS NOT NULL AND status = 'completed' "
    "AND completed_at IS NOT NULL AND imported_rows > 0 "
    "AND confirmation_hash ~ '^[0-9a-f]{64}$' "
    "AND substring(confirmation_key::text, 15, 1) = '4' "
    "AND substring(confirmation_key::text, 20, 1) IN ('8', '9', 'a', 'b') "
    "AND jsonb_typeof(confirmation_result) = 'object')"
)


def upgrade():
    op.add_column("import_jobs", sa.Column("confirmation_key", sa.Uuid(), nullable=True))
    op.add_column("import_jobs", sa.Column("confirmation_hash", sa.String(64), nullable=True))
    op.add_column(
        "import_jobs", sa.Column("confirmation_result", postgresql.JSONB(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_import_jobs_confirmation_key", "import_jobs", ["user_id", "confirmation_key"]
    )
    op.create_check_constraint("ck_import_jobs_confirmation", "import_jobs", CONFIRMATION)


def downgrade():
    op.execute("LOCK TABLE import_jobs IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM import_jobs WHERE confirmation_key IS NOT NULL) THEN
            RAISE EXCEPTION 'Cannot discard retained import confirmations';
        END IF;
    END $$;""")
    op.drop_constraint("ck_import_jobs_confirmation", "import_jobs", type_="check")
    op.drop_constraint("uq_import_jobs_confirmation_key", "import_jobs", type_="unique")
    op.drop_column("import_jobs", "confirmation_result")
    op.drop_column("import_jobs", "confirmation_hash")
    op.drop_column("import_jobs", "confirmation_key")
