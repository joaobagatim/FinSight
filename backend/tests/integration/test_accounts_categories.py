"""Persist financial foundations on migrated disposable PostgreSQL with synthetic owners."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import Account, Category, User, UserSession

pytestmark = pytest.mark.postgres
CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def resource_connection(postgres_settings):
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


def add_owner(connection, email="owner@example.test"):
    return connection.execute(
        insert(User)
        .values(
            name="Synthetic Owner",
            email=email,
            password_hash="$argon2id$synthetic-not-a-real-hash",
        )
        .returning(User.id)
    ).scalar_one()


def account_values(owner_id, **overrides):
    return {
        "user_id": owner_id,
        "name": "Synthetic Account",
        "type": "checking",
        "opening_balance": Decimal("-123.45"),
        "opening_date": date(2026, 1, 31),
        **overrides,
    }


def category_values(owner_id, **overrides):
    return {"user_id": owner_id, "name": "Synthetic Category", "type": "expense", **overrides}


def test_orm_round_trip_exact_money_dates_ownership_and_archiving(resource_connection):
    with Session(bind=resource_connection, join_transaction_mode="create_savepoint") as session:
        original = datetime(2000, 1, 1, tzinfo=UTC)
        owner = User(name="Synthetic Owner", email="owner@example.test", password_hash="synthetic")
        account = Account(
            **account_values(None), user=owner, created_at=original, updated_at=original
        )
        category = Category(
            **category_values(None, name="  Display Name  "),
            user=owner,
            color="#12aB9f",
            icon="wallet",
            created_at=original,
            updated_at=original,
        )
        session.add_all([account, category])
        session.commit()
        session.expire_all()
        assert account.opening_balance == Decimal("-123.45")
        assert isinstance(account.opening_balance, Decimal)
        assert account.opening_date == date(2026, 1, 31)
        assert account.currency == "BRL" and account.is_active is True
        assert category.name == "Display Name" and category.is_active is True
        assert category.color == "#12aB9f" and category.icon == "wallet"
        assert isinstance(account.id, uuid.UUID) and account.id.version == 4
        assert isinstance(category.id, uuid.UUID) and category.id.version == 4
        assert owner.accounts == [account] and owner.categories == [category]
        assert account.user_id == category.user_id == owner.id
        account.is_active = category.is_active = False
        session.commit()
        session.expire_all()
        assert not account.is_active and not category.is_active
        assert account.updated_at > original and category.updated_at > original
        assert account.created_at == category.created_at == original
        assert account.updated_at.utcoffset() == category.updated_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    [
        Decimal("0.00"),
        Decimal("0.10"),
        Decimal("-0.01"),
        Decimal("9999999999999.99"),
        Decimal("-9999999999999.99"),
    ],
)
def test_numeric_boundaries_round_trip_without_float(resource_connection, value):
    owner_id = add_owner(resource_connection)
    with Session(bind=resource_connection, join_transaction_mode="create_savepoint") as session:
        account = Account(**account_values(owner_id, opening_balance=value))
        session.add(account)
        session.commit()
        session.refresh(account)
        assert account.opening_balance == value
        assert isinstance(account.opening_balance, Decimal)


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        0,
        "1.00",
        None,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("10000000000000"),
        Decimal("1e1000000"),
        Decimal("1.001"),
    ],
)
def test_orm_rejects_invalid_or_lossy_money(resource_connection, value):
    with pytest.raises(ValueError, match="finite Decimal"):
        Account(**account_values(None, opening_balance=value))


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": " "},
        {"name": None},
        {"name": "n" * 101},
        {"type": "credit_card"},
        {"type": None},
        {"currency": "USD"},
        {"currency": "brl"},
        {"currency": None},
        {"user_id": uuid.UUID(int=1)},
        {"user_id": None},
        {"opening_date": None},
        {"opening_balance": None},
        {"opening_balance": Decimal("NaN")},
        {"opening_balance": Decimal("Infinity")},
        {"opening_balance": Decimal("10000000000000")},
    ],
)
def test_database_rejects_invalid_accounts_outside_orm(resource_connection, overrides):
    owner_id = add_owner(resource_connection)
    with pytest.raises((IntegrityError, DataError)), resource_connection.begin_nested():
        resource_connection.execute(insert(Account).values(**account_values(owner_id, **overrides)))


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": " "},
        {"name": None},
        {"name": "n" * 101},
        {"type": "transfer"},
        {"type": None},
        {"user_id": uuid.UUID(int=1)},
        {"user_id": None},
        {"color": "#12345G"},
        {"color": "123456"},
        {"color": "#123"},
        {"icon": " "},
        {"icon": "i" * 51},
    ],
)
def test_database_rejects_invalid_categories(resource_connection, overrides):
    owner_id = add_owner(resource_connection)
    with pytest.raises((IntegrityError, DataError)), resource_connection.begin_nested():
        resource_connection.execute(
            insert(Category).values(**category_values(owner_id, **overrides))
        )


@pytest.mark.parametrize(
    "model,field,value",
    [(Account, "type", t) for t in ("checking", "savings", "cash", "investment")]
    + [(Category, "type", t) for t in ("income", "expense")],
)
def test_all_specified_types_are_accepted(resource_connection, model, field, value):
    owner_id = add_owner(resource_connection)
    factory = account_values if model is Account else category_values
    resource_connection.execute(insert(model).values(**factory(owner_id, **{field: value})))


def test_category_name_uniqueness_normalizes_case_and_trim_within_owner_and_type(
    resource_connection,
):
    owner_id = add_owner(resource_connection)
    other_id = add_owner(resource_connection, "other@example.test")
    resource_connection.execute(
        insert(Category).values(**category_values(owner_id, name="Food", is_active=False))
    )
    with pytest.raises(IntegrityError), resource_connection.begin_nested():
        resource_connection.execute(
            insert(Category).values(**category_values(owner_id, name="  FOOD  "))
        )
    # Another owner or category type is allowed; inactive categories still reserve their name.
    resource_connection.execute(insert(Category).values(**category_values(other_id, name="food")))
    resource_connection.execute(
        insert(Category).values(**category_values(owner_id, name="food", type="income"))
    )
    resource_connection.execute(insert(Category).values(**category_values(owner_id, name="Café")))
    resource_connection.execute(insert(Category).values(**category_values(owner_id, name="Cafe")))


@pytest.mark.parametrize(
    "model,table,factory",
    [(Account, "accounts", account_values), (Category, "categories", category_values)],
)
def test_composite_ownership_key_rejects_cross_user_reference(
    resource_connection, model, table, factory
):
    owner_id = add_owner(resource_connection)
    other_id = add_owner(resource_connection, "other@example.test")
    resource_id = resource_connection.execute(
        insert(model).values(**factory(owner_id)).returning(model.id)
    ).scalar_one()
    # Synthetic child exists only in this transaction to exercise the future composite FK contract.
    assert table in {"accounts", "categories"}
    resource_connection.exec_driver_sql(
        f"CREATE TABLE ownership_probe (user_id UUID NOT NULL, resource_id UUID NOT NULL, "
        f"FOREIGN KEY (user_id, resource_id) REFERENCES {table}(user_id, id))"
    )
    statement = text("INSERT INTO ownership_probe VALUES (:user_id, :resource_id)")
    resource_connection.execute(statement, {"user_id": owner_id, "resource_id": resource_id})
    with pytest.raises(IntegrityError), resource_connection.begin_nested():
        resource_connection.execute(statement, {"user_id": other_id, "resource_id": resource_id})


@pytest.mark.parametrize(
    "model,factory,relation",
    [(Account, account_values, "accounts"), (Category, category_values, "categories")],
)
def test_deleting_user_does_not_cascade_resources(resource_connection, model, factory, relation):
    with Session(bind=resource_connection, join_transaction_mode="create_savepoint") as session:
        owner = User(name="Synthetic Owner", email="owner@example.test", password_hash="synthetic")
        session.add(model(**factory(None), user=owner))
        session.commit()
        assert len(getattr(owner, relation)) == 1
        session.delete(owner)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert len(getattr(owner, relation)) == 1


def test_downgrade_preserves_existing_identity_data_and_reupgrade_is_clean(resource_connection):
    owner_id = add_owner(resource_connection)
    resource_connection.execute(
        insert(UserSession).values(
            user_id=owner_id,
            refresh_token_hash="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    resource_connection.execute(insert(Account).values(**account_values(owner_id)))
    resource_connection.execute(insert(Category).values(**category_values(owner_id)))
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = resource_connection
    command.downgrade(config, "0002_identity")
    assert set(inspect(resource_connection).get_table_names()) == {
        "alembic_version",
        "users",
        "user_sessions",
    }
    assert resource_connection.execute(text("SELECT count(*) FROM users")).scalar_one() == 1
    assert resource_connection.execute(text("SELECT count(*) FROM user_sessions")).scalar_one() == 1
    command.upgrade(config, "head")
    command.check(config)
