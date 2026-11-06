"""Persist transfer creation keys scoped to their authenticated owner."""

import sqlalchemy as sa
from alembic import op

revision: str = "0011_transfer_requests"
down_revision: str | None = "0010_transaction_deletion"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_transfers_user_id_id", "transfers", ["user_id", "id"])
    op.create_table(
        "transfer_creation_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_transfer_creation_requests"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transfer_creation_requests_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "transfer_id"],
            ["transfers.user_id", "transfers.id"],
            name="fk_transfer_creation_requests_owned_transfer",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_transfer_creation_requests_hash"
        ),
        sa.CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_transfer_creation_requests_key_v4",
        ),
    )
    op.create_index(
        "ix_transfer_creation_requests_transfer",
        "transfer_creation_requests",
        ["user_id", "transfer_id"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE transfer_creation_requests IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM transfer_creation_requests) THEN
            RAISE EXCEPTION 'Cannot discard retained transfer creation identities';
        END IF;
    END $$;""")
    op.drop_index("ix_transfer_creation_requests_transfer", table_name="transfer_creation_requests")
    op.drop_table("transfer_creation_requests")
    op.drop_constraint("uq_transfers_user_id_id", "transfers", type_="unique")
