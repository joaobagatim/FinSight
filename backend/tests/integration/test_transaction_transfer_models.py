"""Financial persistence constraints on disposable PostgreSQL, with synthetic data only."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, select, text, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import (
    Account,
    Category,
    ImportJob,
    ImportRow,
    Transaction,
    Transfer,
    User,
    UserSession,
)

pytestmark = pytest.mark.postgres
CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def connection(postgres_settings):
    database = Database(postgres_settings)
    try:
        with database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                config = Config(str(CONFIG_PATH))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                yield connection
            finally:
                transaction.rollback()
    finally:
        database.dispose()


def add(connection, model, **values):
    return connection.execute(insert(model).values(**values).returning(model.id)).scalar_one()


def seed(connection, email="owner@example.test"):
    owner = add(connection, User, name="Synthetic", email=email, password_hash="synthetic")
    accounts = [
        add(
            connection,
            Account,
            user_id=owner,
            name="Synthetic",
            type="checking",
            opening_balance=Decimal("0.00"),
            opening_date=date(2026, 1, 1),
        )
        for _ in range(2)
    ]
    categories = {
        kind: add(connection, Category, user_id=owner, name="Synthetic", type=kind)
        for kind in ("income", "expense")
    }
    job = add(
        connection,
        ImportJob,
        user_id=owner,
        account_id=accounts[0],
        filename="synthetic.csv",
        file_checksum="a" * 64,
    )
    row = add(
        connection,
        ImportRow,
        user_id=owner,
        account_id=accounts[0],
        import_job_id=job,
        row_number=1,
    )
    return dict(
        owner=owner,
        account=accounts[0],
        other_account=accounts[1],
        categories=categories,
        job=job,
        row=row,
    )


def transaction_values(resources, **overrides):
    return (
        dict(
            user_id=resources["owner"],
            account_id=resources["account"],
            category_id=resources["categories"]["expense"],
            description="Synthetic expense",
            amount=Decimal("123.45"),
            type="expense",
            status="posted",
            effective_date=date(2026, 2, 1),
        )
        | overrides
    )


def transfer_values(resources, **overrides):
    return (
        dict(
            user_id=resources["owner"],
            from_account_id=resources["account"],
            to_account_id=resources["other_account"],
            amount=Decimal("100.00"),
            status="planned",
            effective_date=date(2026, 2, 1),
        )
        | overrides
    )


def test_orm_round_trip_relationships_money_dates_and_update_timestamps(connection):
    resources = seed(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        owner = session.get(User, resources["owner"])
        account = session.get(Account, resources["account"])
        destination = session.get(Account, resources["other_account"])
        category = session.get(Category, resources["categories"]["expense"])
        row = session.get(ImportRow, resources["row"])
        original = datetime(2000, 1, 1, tzinfo=UTC)
        transaction = Transaction(
            user=owner,
            account=account,
            category=category,
            import_row=row,
            description="  Synthetic expense  ",
            amount=Decimal("0.01"),
            type="expense",
            status="posted",
            effective_date=date(2026, 2, 1),
            created_at=original,
            updated_at=original,
        )
        transfer = Transfer(
            user=owner,
            from_account=account,
            to_account=destination,
            amount=Decimal("9999999999999.99"),
            status="planned",
            effective_date=date(2026, 2, 2),
            created_at=original,
            updated_at=original,
        )
        session.add_all([transaction, transfer])
        session.commit()
        session.expire_all()
        assert owner.transactions == account.transactions == category.transactions == [transaction]
        assert row.transaction is transaction and transaction.import_row is row
        assert (
            owner.transfers
            == account.outgoing_transfers
            == destination.incoming_transfers
            == [transfer]
        )
        assert transaction.user_id == transfer.user_id == owner.id
        assert transaction.account_id == transfer.from_account_id == account.id
        assert transaction.category_id == category.id and transaction.import_row_id == row.id
        assert transfer.to_account_id == destination.id
        assert transaction.description == "Synthetic expense" and transaction.notes is None
        assert transfer.description is None and transaction.effective_date == date(2026, 2, 1)
        assert transfer.effective_date == date(2026, 2, 2)
        assert transaction.amount == Decimal("0.01")
        assert transfer.amount == Decimal("9999999999999.99")
        transaction.notes = "Synthetic note"
        transfer.description = "Synthetic transfer"
        session.commit()
        session.expire_all()
        for record in (transaction, transfer):
            assert isinstance(record.amount, Decimal)
            assert record.id.version == 4 and isinstance(record.id, uuid.UUID)
            assert record.created_at == original and record.updated_at > original
            assert record.updated_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("model", [Transaction, Transfer])
@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        0,
        0.1,
        "1.00",
        Decimal("0"),
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0.001"),
        Decimal("10000000000000"),
        Decimal("1e1000000"),
        Decimal("-1e1000000"),
        Decimal("1e-1000000"),
    ],
)
def test_orm_rejects_invalid_amounts_before_database(model, value):
    with pytest.raises(ValueError, match="positive finite Decimal"):
        model(amount=value)


@pytest.mark.parametrize("value", [None, "", " ", "\t\n"])
def test_orm_rejects_blank_description(value):
    with pytest.raises(ValueError, match="description must not be blank"):
        Transaction(description=value)


@pytest.mark.parametrize(
    "model,factory", [(Transaction, transaction_values), (Transfer, transfer_values)]
)
@pytest.mark.parametrize("value", [Decimal("0.01"), Decimal("0.10"), Decimal("9999999999999.99")])
def test_exact_decimal_boundaries_round_trip(connection, model, factory, value):
    resources = seed(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = model(**factory(resources, amount=value))
        session.add(record)
        session.commit()
        session.refresh(record)
        assert record.amount == value and isinstance(record.amount, Decimal)


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"user_id": uuid.UUID(int=1)},
        {"account_id": None},
        {"account_id": uuid.UUID(int=1)},
        {"category_id": None},
        {"category_id": uuid.UUID(int=1)},
        {"description": None},
        {"description": ""},
        {"description": " "},
        {"description": "x" * 256},
        {"amount": None},
        {"amount": Decimal("0")},
        {"amount": Decimal("-0.01")},
        {"amount": Decimal("NaN")},
        {"amount": Decimal("Infinity")},
        {"amount": Decimal("-Infinity")},
        {"amount": Decimal("10000000000000")},
        {"type": None},
        {"type": "transfer"},
        {"status": None},
        {"status": "cancelled"},
        {"effective_date": None},
        {"import_row_id": uuid.UUID(int=1)},
    ],
)
def test_database_rejects_invalid_transactions(connection, overrides):
    resources = seed(connection)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(insert(Transaction).values(**transaction_values(resources, **overrides)))


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"user_id": uuid.UUID(int=1)},
        {"from_account_id": None},
        {"to_account_id": None},
        {"from_account_id": uuid.UUID(int=1)},
        {"to_account_id": uuid.UUID(int=1)},
        {"amount": None},
        {"amount": Decimal("0")},
        {"amount": Decimal("-0.01")},
        {"amount": Decimal("NaN")},
        {"amount": Decimal("Infinity")},
        {"amount": Decimal("-Infinity")},
        {"amount": Decimal("10000000000000")},
        {"status": None},
        {"status": "cancelled"},
        {"effective_date": None},
        {"description": "x" * 256},
    ],
)
def test_database_rejects_invalid_transfers(connection, overrides):
    resources = seed(connection)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(insert(Transfer).values(**transfer_values(resources, **overrides)))


@pytest.mark.parametrize("kind", ["income", "expense"])
@pytest.mark.parametrize("status", ["planned", "posted"])
def test_all_types_statuses_and_many_manual_null_import_links(connection, kind, status):
    resources = seed(connection)
    for _ in range(2):
        connection.execute(
            insert(Transaction).values(
                **transaction_values(
                    resources, category_id=resources["categories"][kind], type=kind, status=status
                )
            )
        )
    assert connection.execute(select(Transaction.import_row_id)).all() == [(None,), (None,)]


@pytest.mark.parametrize("status", ["planned", "posted"])
def test_transfer_is_one_row_and_never_creates_income_expense(connection, status):
    resources = seed(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(Transfer(**transfer_values(resources, status=status)))
        session.commit()
        assert len(session.scalars(select(Transfer)).all()) == 1
        assert session.scalars(select(Transaction)).all() == []
        assert all(
            balance == Decimal("0") for balance in session.scalars(select(Account.opening_balance))
        )


def test_database_rejects_category_type_and_all_cross_owner_references(connection):
    resources = seed(connection)
    other = seed(connection, "other@example.test")
    for overrides in (
        {"account_id": other["account"]},
        {"category_id": other["categories"]["expense"]},
        {"category_id": resources["categories"]["income"]},
        {"import_row_id": other["row"]},
    ):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(Transaction).values(**transaction_values(resources, **overrides))
            )
    for field in ("from_account_id", "to_account_id"):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(Transfer).values(**transfer_values(resources, **{field: other["account"]}))
            )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(Transfer).values(
                **transfer_values(resources, to_account_id=resources["account"])
            )
        )


def test_import_link_requires_same_account_and_is_unique(connection):
    resources = seed(connection)
    values = transaction_values(resources, import_row_id=resources["row"])
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(Transaction).values(**(values | {"account_id": resources["other_account"]}))
        )
    connection.execute(insert(Transaction).values(**values))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(insert(Transaction).values(**values))
    assert connection.execute(select(ImportRow.status)).scalar_one() == "pending"
    indexes = {index["name"]: index for index in inspect(connection).get_indexes("transactions")}
    index = indexes["uq_transactions_import_row"]
    assert index["unique"] and index["column_names"] == ["import_row_id"]
    assert "IS NOT NULL" in index["dialect_options"]["postgresql_where"]


@pytest.mark.parametrize(
    "reference", ["account", "category_owner", "category_type", "import_owner", "import_account"]
)
def test_orm_references_cannot_silently_reassign_owner_type_or_account(connection, reference):
    resources = seed(connection)
    other = seed(connection, "other@example.test")
    # Assemble all references before the explicit flush that must exercise the FK.
    with Session(
        bind=connection, join_transaction_mode="create_savepoint", autoflush=False
    ) as session:
        record = Transaction(**transaction_values(resources))
        record.user = session.get(User, resources["owner"])
        if reference == "account":
            record.account = session.get(Account, other["account"])
        elif reference.startswith("category"):
            category = (other if reference == "category_owner" else resources)["categories"]
            record.category = session.get(
                Category, category["expense" if reference == "category_owner" else "income"]
            )
        else:
            # A row of account A must not reassign a transaction explicitly targeting B.
            record.import_row = session.get(
                ImportRow, other["row"] if reference == "import_owner" else resources["row"]
            )
            if reference == "import_account":
                record.account_id = resources["other_account"]
        expected_account = other["account"] if reference == "account" else record.account_id
        session.add(record)
        with pytest.raises(IntegrityError):
            session.flush()
        assert record.user_id == resources["owner"] and record.type == "expense"
        assert record.account_id == expected_account
        session.rollback()


@pytest.mark.parametrize("field", ["from_account", "to_account"])
def test_orm_transfer_reference_cannot_silently_reassign_owner(connection, field):
    resources = seed(connection)
    other = seed(connection, "other@example.test")
    with Session(
        bind=connection, join_transaction_mode="create_savepoint", autoflush=False
    ) as session:
        record = Transfer(**transfer_values(resources))
        record.user = session.get(User, resources["owner"])
        setattr(record, field, session.get(Account, other["account"]))
        session.add(record)
        with pytest.raises(IntegrityError):
            session.flush()
        assert record.user_id == resources["owner"]
        session.rollback()


@pytest.mark.parametrize("parent", [User, Account, Category, ImportRow])
def test_deleting_loaded_transaction_references_is_restricted(connection, parent):
    resources = seed(connection)
    transaction_id = add(
        connection, Transaction, **transaction_values(resources, import_row_id=resources["row"])
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = session.get(Transaction, transaction_id)
        assert (
            record.user.transactions
            == record.account.transactions
            == record.category.transactions
            == [record]
        )
        assert record.import_row.transaction is record
        target = {
            User: record.user,
            Account: record.account,
            Category: record.category,
            ImportRow: record.import_row,
        }[parent]
        session.delete(target)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(Transaction, transaction_id) is not None


@pytest.mark.parametrize("reference", ["user", "from_account", "to_account"])
def test_deleting_loaded_transfer_references_is_restricted(connection, reference):
    resources = seed(connection)
    transfer_id = add(connection, Transfer, **transfer_values(resources))
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = session.get(Transfer, transfer_id)
        assert (
            record.user.transfers
            == record.from_account.outgoing_transfers
            == record.to_account.incoming_transfers
            == [record]
        )
        session.delete(getattr(record, reference))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(Transfer, transfer_id) is not None


@pytest.mark.parametrize("load_reverse", [False, True])
def test_import_link_cannot_be_replaced_by_silently_unlinking_existing_transaction(
    connection, load_reverse
):
    resources = seed(connection)
    original_id = add(
        connection, Transaction, **transaction_values(resources, import_row_id=resources["row"])
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        row = session.get(ImportRow, resources["row"])
        if load_reverse:
            assert row.transaction.id == original_id
        replacement = Transaction(**transaction_values(resources), import_row=row)
        session.add(replacement)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(Transaction, original_id).import_row_id == resources["row"]
        assert session.scalars(select(Transaction.id)).all() == [original_id]


def test_category_type_and_transaction_type_cannot_become_incompatible(connection):
    resources = seed(connection)
    add(connection, Transaction, **transaction_values(resources))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            update(Category)
            .where(Category.id == resources["categories"]["expense"])
            .values(type="income", name="Other synthetic")
        )
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(update(Transaction).values(type="income"))


def test_upgrade_existing_data_downgrade_preserves_prior_tables_and_reupgrade_is_clean(connection):
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = connection
    command.downgrade(config, "0004_imports")
    resources = seed(connection)
    add(
        connection,
        UserSession,
        user_id=resources["owner"],
        refresh_token_hash="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    prior_tables = (
        "users",
        "user_sessions",
        "accounts",
        "categories",
        "import_jobs",
        "import_rows",
    )
    before = {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in prior_tables
    }
    command.upgrade(config, "head")
    add(connection, Transaction, **transaction_values(resources, import_row_id=resources["row"]))
    add(connection, Transfer, **transfer_values(resources))
    command.check(config)
    command.downgrade(config, "0004_imports")
    assert set(inspect(connection).get_table_names()) == {"alembic_version", *prior_tables}
    after = {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in prior_tables
    }
    assert before == after
    assert connection.execute(select(ImportRow.id)).scalar_one() == resources["row"]
    constraints = {
        constraint["name"]
        for constraint in inspect(connection).get_unique_constraints("categories")
    }
    assert "uq_categories_user_id_id_type" not in constraints
    assert "uq_categories_user_id_id" in constraints
    command.upgrade(config, "head")
    command.check(config)
