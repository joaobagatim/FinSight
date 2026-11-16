"""Persist goal creation keys scoped to their authenticated owner."""

import sqlalchemy as sa
from alembic import op

revision: str = "0013_goal_creation_requests"
down_revision: str | None = "0012_transfer_deletion"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "goal_creation_requests",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_goal_creation_requests"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_goal_creation_requests_user",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "goal_id"],
            ["financial_goals.user_id", "financial_goals.id"],
            name="fk_goal_creation_requests_owned_goal",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "request_hash ~ '^[0-9a-f]{64}$'", name="ck_goal_creation_requests_hash"
        ),
        sa.CheckConstraint(
            "substring(idempotency_key::text, 15, 1) = '4' AND "
            "substring(idempotency_key::text, 20, 1) IN ('8', '9', 'a', 'b')",
            name="ck_goal_creation_requests_key_v4",
        ),
    )
    op.create_index(
        "ix_goal_creation_requests_goal",
        "goal_creation_requests",
        ["user_id", "goal_id"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE goal_creation_requests IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM goal_creation_requests) THEN
            RAISE EXCEPTION 'Cannot discard retained goal creation identities';
        END IF;
    END $$;""")
    op.drop_index("ix_goal_creation_requests_goal", table_name="goal_creation_requests")
    op.drop_table("goal_creation_requests")
