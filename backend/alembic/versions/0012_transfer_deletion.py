"""Retain removed transfers and their creation identities without counting their money."""

import sqlalchemy as sa
from alembic import op

revision: str = "0012_transfer_deletion"
down_revision: str | None = "0011_transfer_requests"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # Dropping a populated marker would put removed money back into balances.
    op.execute("LOCK TABLE transfers IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM transfers WHERE deleted_at IS NOT NULL) THEN
            RAISE EXCEPTION 'Cannot downgrade while removed transfers are retained';
        END IF;
    END $$;""")
    op.drop_column("transfers", "deleted_at")
