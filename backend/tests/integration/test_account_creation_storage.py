"""Account request ownership and migration safety on disposable PostgreSQL only."""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid1, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import Account, AccountCreationRequest, User

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def storage_database(postgres_settings):
    assert postgres_settings.db_name.startswith("finsight_test_")
    database = Database(postgres_settings)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield database
    finally:
        try:
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "base")
                connection.exec_driver_sql("DROP TABLE alembic_version")
        finally:
            database.dispose()


@pytest.fixture
def connection(storage_database):
    with storage_database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def seed(connection):
    user = connection.scalar(
        insert(User)
        .values(
            name="Synthetic owner", email=f"{uuid4().hex}@example.test", password_hash="synthetic"
        )
        .returning(User.id)
    )
    account = connection.scalar(
        insert(Account)
        .values(
            user_id=user,
            name="Synthetic account",
            type="checking",
            opening_balance=Decimal("-10.25"),
            opening_date=date(2026, 1, 1),
        )
        .returning(Account.id)
    )
    return user, account


def test_round_trip_and_same_key_for_distinct_owners(connection):
    first, account = seed(connection)
    other, other_account = seed(connection)
    key = uuid4()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        row = AccountCreationRequest(
            user_id=first, idempotency_key=key, request_hash="a" * 64, account_id=account
        )
        session.add(row)
        session.add(
            AccountCreationRequest(
                user_id=other, idempotency_key=key, request_hash="b" * 64, account_id=other_account
            )
        )
        session.commit()
        session.expire_all()
        stored = session.get(AccountCreationRequest, (first, key))
        assert stored.account.id == account and stored.account.user_id == first
        assert stored.request_hash == "a" * 64
        assert stored.created_at.utcoffset() == timedelta(0)
        assert session.get(AccountCreationRequest, (other, key)).account_id == other_account


def test_database_rejects_duplicate_key_wrong_owner_and_invalid_metadata(connection):
    owner, account = seed(connection)
    _, other_account = seed(connection)
    key = uuid4()
    values = dict(user_id=owner, account_id=account, idempotency_key=key, request_hash="a" * 64)
    connection.execute(insert(AccountCreationRequest).values(**values))
    for changes, constraint in (
        ({}, "pk_account_creation_requests"),
        (
            {"idempotency_key": uuid4(), "account_id": other_account},
            "fk_account_creation_requests_owned_account",
        ),
        (
            {"idempotency_key": uuid4(), "request_hash": "not-a-digest"},
            "ck_account_creation_requests_hash",
        ),
        ({"idempotency_key": uuid1()}, "ck_account_creation_requests_key_v4"),
    ):
        with pytest.raises(IntegrityError) as failure, connection.begin_nested():
            connection.execute(insert(AccountCreationRequest).values(**(values | changes)))
        assert failure.value.orig.diag.constraint_name == constraint


def test_upgrade_downgrade_preserves_account_and_clears_only_request_memory(connection):
    owner, account = seed(connection)
    before = connection.execute(select(Account.__table__).where(Account.id == account)).one()
    connection.execute(
        insert(AccountCreationRequest).values(
            user_id=owner, account_id=account, idempotency_key=uuid4(), request_hash="a" * 64
        )
    )
    tables = set(inspect(connection).get_table_names())
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = connection
    command.downgrade(config, "0007_refresh_token_history")
    assert (
        MigrationContext.configure(connection).get_current_revision()
        == "0007_refresh_token_history"
    )
    assert set(inspect(connection).get_table_names()) == tables - {"account_creation_requests"}
    assert (
        connection.execute(select(Account.__table__).where(Account.id == account)).one() == before
    )
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    assert (
        connection.execute(select(Account.__table__).where(Account.id == account)).one() == before
    )
    assert connection.execute(select(AccountCreationRequest)).first() is None
