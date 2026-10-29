"""Preserve consumed refresh-token digests without changing existing domain tables."""

import sqlalchemy as sa
from alembic import op

revision: str = "0007_refresh_token_history"
down_revision: str | None = "0006_goals_allocations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "refresh_token_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "used_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_token_history"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            name="fk_refresh_token_history_session",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_history_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_refresh_token_history_hash"),
    )
    op.create_index("ix_refresh_token_history_session_id", "refresh_token_history", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_refresh_token_history_session_id", table_name="refresh_token_history")
    op.drop_table("refresh_token_history")
