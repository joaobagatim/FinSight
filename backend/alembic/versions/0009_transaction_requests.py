"""Persist transaction creation keys scoped to their authenticated owner."""

import sqlalchemy as sa
from alembic import op

revision: str = "0009_transaction_requests"
down_revision: str | None = "0008_account_creation_requests"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_transactions_user_id_id", "transactions", ["user_id", "id"])
    op.create_table(
        "transaction_creation_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "idempotency_key", name="pk_transaction_creation_requests"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transaction_creation_requests_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_transaction_creation_requests_owned_transaction",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_transaction_creation_requests_hash"
        ),
        sa.CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_transaction_creation_requests_key_v4",
        ),
    )
    op.create_index(
        "ix_transaction_creation_requests_transaction",
        "transaction_creation_requests",
        ["user_id", "transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_creation_requests_transaction", table_name="transaction_creation_requests"
    )
    op.drop_table("transaction_creation_requests")
    op.drop_constraint("uq_transactions_user_id_id", "transactions", type_="unique")
