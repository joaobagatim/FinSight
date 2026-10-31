"""Persist account creation keys scoped to their authenticated owner."""

import sqlalchemy as sa
from alembic import op

revision: str = "0008_account_creation_requests"
down_revision: str | None = "0007_refresh_token_history"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "account_creation_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_account_creation_requests"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_account_creation_requests_user", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_account_creation_requests_owned_account",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_account_creation_requests_hash"
        ),
        sa.CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_account_creation_requests_key_v4",
        ),
    )
    op.create_index(
        "ix_account_creation_requests_account",
        "account_creation_requests",
        ["user_id", "account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_creation_requests_account", table_name="account_creation_requests")
    op.drop_table("account_creation_requests")
