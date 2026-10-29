"""Consumed digests on isolated PostgreSQL, including restriction and migration safety."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import delete, insert, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.refresh_tokens import refresh_token_digest
from app.db.session import Database
from app.models import (
    Account,
    Category,
    FinancialGoal,
    GoalAllocation,
    ImportJob,
    ImportRow,
    RefreshTokenHistory,
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


def seed_session(connection, email="owner@example.test", current_hash="a" * 64):
    owner = add(connection, User, name="Synthetic owner", email=email, password_hash="synthetic")
    session_id = add(
        connection,
        UserSession,
        user_id=owner,
        refresh_token_hash=current_hash,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    return owner, session_id


def test_orm_round_trip_has_private_digest_uuid_and_utc_default(connection):
    with Session(
        bind=connection, join_transaction_mode="create_savepoint", autoflush=False
    ) as session:
        owner = User(name="Synthetic owner", email="orm@example.test", password_hash="synthetic")
        auth = UserSession(
            user=owner,
            refresh_token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        digest = refresh_token_digest("A" * 43)
        history = RefreshTokenHistory(session=auth, token_hash=digest)
        session.add_all([owner, auth, history])
        session.commit()
        session.expire_all()
        stored = session.scalars(select(RefreshTokenHistory)).one()
        assert stored.id.version == 4
        assert stored.session_id == auth.id and stored.session is auth
        assert auth.used_refresh_tokens == [stored]
        assert stored.token_hash == digest and stored.token_hash != "A" * 43
        assert stored.used_at.utcoffset() == timedelta(0)
        assert stored.session.user_id == owner.id


def test_history_owner_is_derived_from_its_session(connection):
    first_owner, first = seed_session(connection)
    second_owner, second = seed_session(connection, "other@example.test", "b" * 64)
    add(connection, RefreshTokenHistory, session_id=first, token_hash="c" * 64)
    add(connection, RefreshTokenHistory, session_id=second, token_hash="d" * 64)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        query = (
            select(RefreshTokenHistory).join(UserSession).where(UserSession.user_id == first_owner)
        )
        assert [row.session_id for row in session.scalars(query)] == [first]
        query = (
            select(RefreshTokenHistory).join(UserSession).where(UserSession.user_id == second_owner)
        )
        assert [row.session_id for row in session.scalars(query)] == [second]


@pytest.mark.parametrize(
    "value",
    [None, "", " ", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 63 + "\n", "a" * 63 + " "],
)
def test_database_rejects_non_digest_values(connection, value):
    _, auth = seed_session(connection)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(insert(RefreshTokenHistory).values(session_id=auth, token_hash=value))


@pytest.mark.parametrize(
    "value", [None, 123, [], "", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "a" * 63 + "\n"]
)
def test_orm_rejects_non_digest_values_without_echo(value):
    with pytest.raises(
        ValueError, match="^Refresh token history requires a lowercase SHA-256 digest$"
    ):
        RefreshTokenHistory(session_id=uuid.uuid4(), token_hash=value)


@pytest.mark.parametrize("session_id", [None, uuid.UUID("99999999-9999-4999-8999-999999999999")])
def test_history_requires_an_existing_session(connection, session_id):
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(RefreshTokenHistory).values(session_id=session_id, token_hash="a" * 64)
        )


def test_digest_is_unique_across_sessions(connection):
    _, first = seed_session(connection)
    _, second = seed_session(connection, "second@example.test", "b" * 64)
    add(connection, RefreshTokenHistory, session_id=first, token_hash="c" * 64)
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(RefreshTokenHistory).values(session_id=second, token_hash="c" * 64)
        )


def test_database_does_not_allow_null_used_at(connection):
    _, auth = seed_session(connection)
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(RefreshTokenHistory).values(session_id=auth, token_hash="b" * 64, used_at=None)
        )


def test_sql_cannot_delete_a_session_with_history(connection):
    _, auth = seed_session(connection)
    add(connection, RefreshTokenHistory, session_id=auth, token_hash="b" * 64)
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(delete(UserSession).where(UserSession.id == auth))


def test_loaded_orm_relationship_keeps_restrict_and_does_not_null_or_delete_history(connection):
    _, auth = seed_session(connection)
    history_id = add(connection, RefreshTokenHistory, session_id=auth, token_hash="b" * 64)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        parent = session.get(UserSession, auth)
        assert [row.id for row in parent.used_refresh_tokens] == [history_id]
        with pytest.raises(IntegrityError) as error, session.begin_nested():
            session.delete(parent)
            session.flush()
        assert error.value.orig.sqlstate == "23001"  # PostgreSQL 18 RESTRICT violation.
        assert error.value.orig.diag.constraint_name == "fk_refresh_token_history_session"
        session.expire_all()
        assert session.get(UserSession, auth) is not None
        assert session.get(RefreshTokenHistory, history_id).session_id == auth


def test_schema_contains_only_digests_and_session_link(connection):
    schema = inspect(connection)
    columns = {column["name"]: column for column in schema.get_columns("refresh_token_history")}
    assert set(columns) == {"id", "session_id", "token_hash", "used_at"}
    assert columns["token_hash"]["type"].length == 64
    assert columns["used_at"]["type"].timezone
    assert all(not column["nullable"] for column in columns.values())
    assert "ix_refresh_token_history_session_id" in {
        row["name"] for row in schema.get_indexes("refresh_token_history")
    }
    assert schema.get_foreign_keys("refresh_token_history")[0]["options"]["ondelete"] == "RESTRICT"


def test_history_insertion_does_not_rotate_or_revoke_the_session(connection):
    _, auth = seed_session(connection)
    before = connection.execute(select(UserSession.__table__).where(UserSession.id == auth)).one()
    add(connection, RefreshTokenHistory, session_id=auth, token_hash="b" * 64)
    after = connection.execute(select(UserSession.__table__).where(UserSession.id == auth)).one()
    assert before == after


def test_upgrade_existing_data_and_downgrade_preserve_all_ten_domain_tables(connection):
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = connection
    command.downgrade(config, "0006_goals_allocations")
    owner, auth = seed_session(connection)
    accounts = [
        add(
            connection,
            Account,
            user_id=owner,
            name="Synthetic account",
            type="checking",
            opening_balance=Decimal("1000.25"),
            opening_date=date(2026, 1, 1),
        )
        for _ in range(2)
    ]
    category = add(connection, Category, user_id=owner, name="Synthetic category", type="expense")
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
    add(
        connection,
        Transaction,
        user_id=owner,
        account_id=accounts[0],
        category_id=category,
        description="Synthetic expense",
        amount=Decimal("1.25"),
        type="expense",
        status="posted",
        effective_date=date(2026, 2, 1),
        import_row_id=row,
    )
    add(
        connection,
        Transfer,
        user_id=owner,
        from_account_id=accounts[0],
        to_account_id=accounts[1],
        amount=Decimal("2.50"),
        status="planned",
        effective_date=date(2026, 2, 1),
    )
    goal = add(
        connection,
        FinancialGoal,
        user_id=owner,
        name="Synthetic goal",
        target_amount=Decimal("100.00"),
        status="active",
    )
    add(
        connection,
        GoalAllocation,
        user_id=owner,
        goal_id=goal,
        account_id=accounts[0],
        amount=Decimal("10.00"),
        allocation_date=date(2026, 2, 1),
    )
    tables = (
        "users",
        "user_sessions",
        "accounts",
        "categories",
        "import_jobs",
        "import_rows",
        "transactions",
        "transfers",
        "financial_goals",
        "goal_allocations",
    )

    def snapshot():
        return {
            table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
            for table in tables
        }

    before = snapshot()
    assert all(before.values())
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    assert connection.scalar(select(text("count(*)")).select_from(RefreshTokenHistory)) == 0
    assert before == snapshot()
    add(connection, RefreshTokenHistory, session_id=auth, token_hash="b" * 64)
    command.check(config)
    command.downgrade(config, "0006_goals_allocations")
    assert MigrationContext.configure(connection).get_current_revision() == "0006_goals_allocations"
    assert set(inspect(connection).get_table_names()) == {"alembic_version", *tables}
    assert before == snapshot()
    command.upgrade(config, "head")
    command.check(config)
    assert before == snapshot()
    assert connection.scalar(select(text("count(*)")).select_from(RefreshTokenHistory)) == 0
