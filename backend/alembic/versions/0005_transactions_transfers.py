"""Persist transactions and transfers with ownership and category-type integrity."""

import sqlalchemy as sa
from alembic import op

revision: str = "0005_transactions_transfers"
down_revision: str | None = "0004_imports"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_categories_user_id_id_type", "categories", ["user_id", "id", "type"]
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("import_row_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transactions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transactions_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transactions_owned_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "category_id", "type"],
            ["categories.user_id", "categories.id", "categories.type"],
            name="fk_transactions_owned_category_type",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "account_id", "import_row_id"],
            ["import_rows.user_id", "import_rows.account_id", "import_rows.id"],
            name="fk_transactions_owned_import_row",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(btrim(description)) > 0", name="ck_transactions_description"
        ),
        sa.CheckConstraint(
            "amount > 0 AND amount <= 9999999999999.99", name="ck_transactions_amount"
        ),
        sa.CheckConstraint("type IN ('income', 'expense')", name="ck_transactions_type"),
        sa.CheckConstraint("status IN ('planned', 'posted')", name="ck_transactions_status"),
    )
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "effective_date"])
    op.create_index(
        "ix_transactions_account_date", "transactions", ["account_id", "effective_date"]
    )
    op.create_index(
        "uq_transactions_import_row",
        "transactions",
        ["import_row_id"],
        unique=True,
        postgresql_where=sa.text("import_row_id IS NOT NULL"),
    )
    op.create_table(
        "transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("from_account_id", sa.Uuid(), nullable=False),
        sa.Column("to_account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transfers"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transfers_user_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "from_account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transfers_owned_from_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "to_account_id"],
            ["accounts.user_id", "accounts.id"],
            name="fk_transfers_owned_to_account",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "from_account_id <> to_account_id", name="ck_transfers_distinct_accounts"
        ),
        sa.CheckConstraint("amount > 0 AND amount <= 9999999999999.99", name="ck_transfers_amount"),
        sa.CheckConstraint("status IN ('planned', 'posted')", name="ck_transfers_status"),
    )
    op.create_index("ix_transfers_user_date", "transfers", ["user_id", "effective_date"])


def downgrade() -> None:
    # This rollback removes the new financial records, never the earlier domain tables.
    op.drop_table("transfers")
    op.drop_table("transactions")
    op.drop_constraint("uq_categories_user_id_id_type", "categories", type_="unique")
