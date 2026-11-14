"""Persist explicit preview selection without altering financial records."""

import sqlalchemy as sa
from alembic import op

revision: str = "0016_import_review_selection"
down_revision: str | None = "0015_import_creation_requests"
branch_labels: str | None = None
depends_on: str | None = None

SELECTABLE = (
    "NOT selected OR (status IN ('pending', 'duplicate_candidate') "
    "AND transaction_date IS NOT NULL AND description IS NOT NULL "
    "AND char_length(btrim(description)) > 0 AND amount IS NOT NULL AND amount > 0 "
    "AND type IS NOT NULL AND suggested_category_id IS NOT NULL)"
)


def upgrade():
    op.add_column(
        "import_rows",
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint("ck_import_rows_selected_valid", "import_rows", SELECTABLE)


def downgrade():
    op.execute("LOCK TABLE import_rows IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM import_rows WHERE selected) THEN
            RAISE EXCEPTION 'Cannot discard explicit import selections';
        END IF;
    END $$;""")
    op.drop_constraint("ck_import_rows_selected_valid", "import_rows", type_="check")
    op.drop_column("import_rows", "selected")
