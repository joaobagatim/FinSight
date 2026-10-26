"""Add users and refresh-session persistence without authentication endpoints."""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity"
down_revision: str | None = "0001_phase0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_users_name_not_blank"),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND char_length(email) > 0",
            name="ck_users_email_normalized",
        ),
        sa.CheckConstraint(
            "char_length(btrim(password_hash)) > 0", name="ck_users_password_hash_not_blank"
        ),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("refresh_token_hash", name="uq_user_sessions_refresh_token_hash"),
        sa.CheckConstraint(
            "char_length(btrim(refresh_token_hash)) > 0",
            name="ck_user_sessions_refresh_hash_not_blank",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_user_sessions_expiry_after_creation"
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_user_sessions_revocation_after_creation",
        ),
        sa.CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_user_sessions_last_use_after_creation",
        ),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])


def downgrade() -> None:
    # Explicit rollback destroys identity/session records; never run on real data without approval.
    op.drop_table("user_sessions")
    op.drop_table("users")
