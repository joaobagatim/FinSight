"""Retain deleted movements and creation keys while excluding them from balances."""

import sqlalchemy as sa
from alembic import op

revision: str = "0010_transaction_deletion"
down_revision: str | None = "0009_transaction_requests"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    # Serialize the guard with financial writes; dropping the marker would revive deleted money.
    op.execute("LOCK TABLE transactions IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM transactions WHERE deleted_at IS NOT NULL) THEN
                RAISE EXCEPTION 'Cannot downgrade while deleted transactions are retained';
            END IF;
        END $$;
    """)
    op.drop_column("transactions", "deleted_at")
