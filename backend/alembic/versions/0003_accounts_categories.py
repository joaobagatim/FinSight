"""Add account/category persistence and ownership keys for future child records."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_accounts_categories"
down_revision: str | None = "0002_identity"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default="BRL", nullable=False),
        sa.Column("opening_balance", sa.Numeric(15, 2), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_accounts"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_accounts_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_accounts_user_id_id"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_accounts_name_not_blank"),
        sa.CheckConstraint(
            "type IN ('checking', 'savings', 'cash', 'investment')", name="ck_accounts_type"
        ),
        sa.CheckConstraint("currency = 'BRL'", name="ck_accounts_currency_brl"),
        sa.CheckConstraint(
            "opening_balance BETWEEN -9999999999999.99 AND 9999999999999.99",
            name="ck_accounts_opening_balance_finite",
        ),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_categories_user_id_users", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_categories_user_id_id"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_categories_name_not_blank"),
        sa.CheckConstraint("type IN ('income', 'expense')", name="ck_categories_type"),
        sa.CheckConstraint(
            "color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'", name="ck_categories_color"
        ),
        sa.CheckConstraint(
            "icon IS NULL OR char_length(btrim(icon)) > 0", name="ck_categories_icon_not_blank"
        ),
    )
    op.create_index(
        "uq_categories_user_type_normalized_name",
        "categories",
        ["user_id", "type", sa.text("lower(btrim(name))")],
        unique=True,
    )


def downgrade() -> None:
    # Explicit destructive rollback: keep users/sessions, remove account/category data.
    op.drop_table("categories")
    op.drop_table("accounts")
