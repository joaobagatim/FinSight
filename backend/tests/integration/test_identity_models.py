"""Identity constraints exercised on migrated disposable PostgreSQL, never create_all."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import User, UserSession

pytestmark = pytest.mark.postgres
CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"
PASSWORD_HASH = "$argon2id$synthetic-test-placeholder-not-a-real-password-hash"


@pytest.fixture
def identity_connection(postgres_settings):
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


def user_values(**overrides):
    return {
        "name": "Synthetic User",
        "email": "person@example.test",
        "password_hash": PASSWORD_HASH,
        **overrides,
    }


def session_values(owner_id, **overrides):
    return {
        "user_id": owner_id,
        "refresh_token_hash": "a" * 64,
        "expires_at": datetime.now(UTC) + timedelta(days=7),
        **overrides,
    }


def test_orm_round_trip_normalizes_email_and_preserves_owner_and_utc(identity_connection):
    with Session(bind=identity_connection, join_transaction_mode="create_savepoint") as session:
        owner = User(**user_values(email="  Person@Example.TEST  "))
        other = User(**user_values(email="other@example.test"))
        token_session = UserSession(**session_values(None), user=owner)
        session.add_all([owner, other, token_session])
        session.commit()
        session.expire_all()
        assert isinstance(owner.id, uuid.UUID) and owner.id.version == 4
        assert isinstance(token_session.id, uuid.UUID) and token_session.id.version == 4
        assert owner.is_active is True
        assert owner.email == "person@example.test"
        assert owner.created_at.utcoffset() == timedelta(0)
        assert owner.updated_at.utcoffset() == timedelta(0)
        assert token_session.created_at.utcoffset() == timedelta(0)
        assert token_session.expires_at.utcoffset() == timedelta(0)
        assert token_session.revoked_at is None and token_session.last_used_at is None
        assert token_session.user_id == owner.id
        assert token_session.user is owner
        assert owner.sessions == [token_session]
        assert other.sessions == []
        assert session.scalar(select(UserSession).where(UserSession.user_id == other.id)) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "Mixed@Example.test"},
        {"email": " person@example.test "},
        {"email": ""},
        {"email": None},
        {"name": "   "},
        {"name": None},
        {"name": "n" * 121},
        {"password_hash": " "},
        {"password_hash": None},
        {"password_hash": "h" * 256},
    ],
)
def test_database_rejects_invalid_users_even_outside_orm(identity_connection, overrides):
    with pytest.raises((IntegrityError, DataError)), identity_connection.begin_nested():
        identity_connection.execute(insert(User).values(**user_values(**overrides)))


def test_normalized_email_is_unique(identity_connection):
    with Session(bind=identity_connection, join_transaction_mode="create_savepoint") as session:
        session.add(User(**user_values()))
        session.commit()
        session.add(User(**user_values(email=" PERSON@example.test ")))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": uuid.UUID(int=1)},
        {"user_id": None},
        {"refresh_token_hash": " "},
        {"refresh_token_hash": None},
        {"refresh_token_hash": "h" * 256},
        {"expires_at": None},
        {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"revoked_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"last_used_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
)
def test_database_rejects_invalid_sessions(identity_connection, overrides):
    owner_id = identity_connection.execute(
        insert(User).values(**user_values()).returning(User.id)
    ).scalar_one()
    with pytest.raises((IntegrityError, DataError)), identity_connection.begin_nested():
        identity_connection.execute(
            insert(UserSession).values(**session_values(owner_id, **overrides))
        )


def test_refresh_hash_is_unique_and_user_deletion_is_restricted(identity_connection):
    with Session(bind=identity_connection, join_transaction_mode="create_savepoint") as session:
        owner = User(**user_values())
        other = User(**user_values(email="other@example.test"))
        session.add(other)
        session.add(UserSession(**session_values(None), user=owner))
        session.commit()
        # Loaded relationships must not turn a user deletion into silent session deletion.
        assert len(owner.sessions) == 1
        session.delete(owner)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert len(owner.sessions) == 1
        session.add(UserSession(**session_values(other.id)))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert len(owner.sessions) == 1


def test_profile_update_advances_timestamp_and_session_lifecycle_dates_round_trip(
    identity_connection,
):
    with Session(bind=identity_connection, join_transaction_mode="create_savepoint") as session:
        original_time = datetime(2000, 1, 1, tzinfo=UTC)
        owner = User(**user_values(), created_at=original_time, updated_at=original_time)
        token_session = UserSession(**session_values(None), user=owner)
        session.add(token_session)
        session.commit()
        owner.name = "Updated Synthetic User"
        token_session.last_used_at = datetime.now(UTC)
        token_session.revoked_at = datetime.now(UTC)
        session.commit()
        session.expire_all()
        assert owner.updated_at > original_time
        assert owner.created_at == original_time
        assert token_session.last_used_at >= token_session.created_at
        assert token_session.revoked_at >= token_session.last_used_at


def test_migrated_schema_has_timezone_columns_indexes_and_no_raw_secret_fields(identity_connection):
    schema = inspect(identity_connection)
    for table, timestamps in (
        ("users", ["created_at", "updated_at"]),
        ("user_sessions", ["created_at", "expires_at", "revoked_at", "last_used_at"]),
    ):
        columns = {column["name"]: column for column in schema.get_columns(table)}
        assert "password" not in columns and "refresh_token" not in columns
        assert all(columns[name]["type"].timezone for name in timestamps)
    indexes = {item["name"] for item in schema.get_indexes("user_sessions")}
    assert {"ix_user_sessions_user_id", "ix_user_sessions_expires_at"} <= indexes


def test_identity_downgrade_preserves_baseline_and_can_reupgrade(identity_connection):
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = identity_connection
    command.downgrade(config, "0001_phase0")
    assert inspect(identity_connection).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    command.check(config)
