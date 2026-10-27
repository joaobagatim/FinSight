"""Persist goals and signed allocation movements with ownership constraints."""

import sqlalchemy as sa
from alembic import op

revision: str = "0006_goals_allocations"
down_revision: str | None = "0005_transactions_transfers"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "financial_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_goals"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_financial_goals_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_financial_goals_user_id_id"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_financial_goals_name"),
        sa.CheckConstraint(
            "target_amount > 0 AND target_amount <= 9999999999999.99",
            name="ck_financial_goals_target_amount",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled')", name="ck_financial_goals_status"
        ),
    )
    op.create_index("ix_financial_goals_user_status", "financial_goals", ["user_id", "status"])
    op.create_table(
        "goal_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("allocation_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_goal_allocations"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_goal_allocations_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "goal_id"],
            ["financial_goals.user_id", "financial_goals.id"],
            name="fk_goal_allocations_owned_goal",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_goal_allocations_owned_account",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "amount <> 0 AND amount BETWEEN -9999999999999.99 AND 9999999999999.99",
            name="ck_goal_allocations_amount",
        ),
    )
    op.create_index(
        "ix_goal_allocations_user_goal_date",
        "goal_allocations",
        ["user_id", "goal_id", "allocation_date"],
    )
    op.create_index(
        "ix_goal_allocations_user_account_date",
        "goal_allocations",
        ["user_id", "account_id", "allocation_date"],
    )


def downgrade() -> None:
    # Explicit rollback removes goal/allocation data, leaving all earlier domain tables intact.
    op.drop_table("goal_allocations")
    op.drop_table("financial_goals")
