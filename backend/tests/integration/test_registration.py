"""Registration HTTP contracts and real independent PostgreSQL transactions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.db.session import Database
from app.main import create_app
from app.models import User
from app.schemas.auth import RegistrationInput, RegistrationResponse
from app.services.registration import RegistrationUnavailable, register_user

PATH = "/api/v1/auth/register"
VALID = {
    "name": "Synthetic User",
    "email": "synthetic@example.com",
    "password": "synthetic password",
}
MESSAGE = RegistrationResponse().model_dump()


@pytest.fixture
def client():
    app = create_app(
        Settings(_env_file=None, environment="test", cors_origins=["http://localhost:5173"])
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "body",
    [
        {"password": "sensitive-marker"},
        VALID | {"sensitive-marker": "sensitive-marker"},
        VALID | {"email": "sensitive-marker"},
        VALID | {"password": {"sensitive-marker": "sensitive-marker"}},
        ["sensitive-marker"],
        "sensitive-marker",
    ],
)
def test_validation_is_sanitized(client, body, caplog):
    response = client.post(PATH, json=body)
    assert response.status_code == 422
    assert "sensitive-marker" not in response.text
    assert "sensitive-marker" not in caplog.text
    assert response.json()["detail"] == "Invalid registration data"
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


def test_malformed_json_is_sanitized(client):
    response = client.post(
        PATH,
        content=b'{"password":"sensitive-marker",',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "sensitive-marker" not in response.text


def test_missing_database_is_safe_and_health_stays_available(client):
    response = client.post(PATH, json=VALID)
    assert response.status_code == 503
    assert response.json() == {"detail": "Registration temporarily unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/unknown").json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]
)
def test_only_json_is_accepted(client, content_type):
    response = client.post(PATH, content="synthetic", headers={"Content-Type": content_type})
    assert response.status_code == 415
    assert response.headers["cache-control"] == "no-store"


def test_large_body_rejected_before_session_or_hash(client):
    response = client.post(PATH, json=VALID | {"password": "synthetic" * 3000})
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"


def test_rate_does_not_trust_forwarded_for(client):
    for index in range(5):
        response = client.post(PATH, json={}, headers={"X-Forwarded-For": f"192.0.2.{index}"})
        assert response.status_code == 422
    response = client.post(PATH, json=VALID)
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert response.headers["cache-control"] == "no-store"


def test_cors_post_and_no_credentials(client):
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    response = client.options(PATH, headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    assert "access-control-allow-credentials" not in response.headers
    response = client.post(PATH, json=VALID, headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == headers["Origin"]


def test_openapi_password_is_write_only(client):
    document = client.get("/openapi.json").json()
    schema = document["components"]["schemas"]["RegistrationInput"]
    assert schema["properties"]["password"]["writeOnly"] is True
    assert schema["properties"]["password"]["minLength"] == 15
    assert schema["properties"]["password"]["maxLength"] == 128
    assert schema["additionalProperties"] is False


def test_database_failure_closes_session_and_hides_driver_details(client, caplog):
    session = MagicMock()
    session.commit.side_effect = SQLAlchemyError("sensitive-marker SQL synthetic password")
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    client.app.dependency_overrides[get_database] = lambda: SimpleNamespace(sessions=factory)
    response = client.post(PATH, json=VALID)
    assert response.status_code == 503
    assert "sensitive-marker" not in response.text + caplog.text
    assert VALID["password"] not in response.text + caplog.text
    session.rollback.assert_called_once()
    factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "state,constraint", [("23505", "other"), ("23514", "uq_users_email"), (None, None)]
)
def test_other_integrity_errors_do_not_become_success(state, constraint):
    class DriverError(Exception):
        sqlstate = state
        diag = SimpleNamespace(constraint_name=constraint)

    session = MagicMock()
    session.commit.side_effect = IntegrityError("synthetic sql", {}, DriverError())
    with pytest.raises(RegistrationUnavailable):
        register_user(session, RegistrationInput(**VALID))
    session.rollback.assert_called_once()


def test_hash_capacity_rejected_without_queue_and_released(client):
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    client.app.dependency_overrides[get_database] = lambda: SimpleNamespace(sessions=factory)
    slots = client.app.state.registration_limits.hash_slots
    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    try:
        response = client.post(PATH, json=VALID)
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
        session.commit.assert_not_called()
    finally:
        slots.release()
        slots.release()
    assert client.post(PATH, json=VALID).status_code == 200


def test_hash_slots_released_after_persistence_failure(client):
    session = MagicMock()
    session.commit.side_effect = SQLAlchemyError("synthetic failure")
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    client.app.dependency_overrides[get_database] = lambda: SimpleNamespace(sessions=factory)
    for _ in range(3):
        assert client.post(PATH, json=VALID).status_code == 503
    assert session.rollback.call_count == 3


def test_connection_failure_is_sanitized(client, caplog):
    factory = MagicMock()
    factory.return_value.__enter__.side_effect = SQLAlchemyError("sensitive-marker")
    client.app.dependency_overrides[get_database] = lambda: SimpleNamespace(sessions=factory)
    response = client.post(PATH, json=VALID)
    assert response.status_code == 503
    assert "sensitive-marker" not in response.text + caplog.text


def test_limits_are_application_scoped_and_cleaned_up():
    first = create_app(Settings(_env_file=None))
    second = create_app(Settings(_env_file=None))
    with TestClient(first) as client:
        for _ in range(5):
            assert client.post(PATH, json={}).status_code == 422
        assert client.post(PATH, json={}).status_code == 429
        with TestClient(second) as independent:
            assert independent.post(PATH, json={}).status_code == 422
    assert first.state.registration_limits.clients == {}


@pytest.fixture
def registration_database(postgres_settings):
    # Own test DB only. Commit DDL so two independent sessions can race; undo it finally.
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
            assert database.engine.pool.checkedout() == 0
        finally:
            database.dispose()


@pytest.mark.postgres
def test_http_creates_normalized_identity_with_real_hash(client, registration_database):
    client.app.dependency_overrides[get_database] = lambda: registration_database
    response = client.post(
        PATH, json=VALID | {"name": " Synthetic User ", "email": " SYNTHETIC@EXAMPLE.COM "}
    )
    assert response.status_code == 200
    assert response.json() == MESSAGE
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert "location" not in response.headers
    with registration_database.sessions() as session:
        user = session.scalars(select(User)).one()
        assert user.name == VALID["name"]
        assert user.email == VALID["email"]
        assert user.is_active
        assert user.id.version == 4
        assert verify_password(VALID["password"], user.password_hash)
        assert user.password_hash not in response.text
        assert str(user.id) not in response.text


@pytest.mark.postgres
@pytest.mark.parametrize("active", [True, False])
def test_duplicate_leaves_existing_identity_unchanged(client, registration_database, active):
    encoded = hash_password("original synthetic password")
    with registration_database.sessions() as session:
        user = User(name="Original", email=VALID["email"], password_hash=encoded, is_active=active)
        session.add(user)
        session.commit()
        before = (user.id, user.name, user.password_hash, user.is_active, user.updated_at)
    client.app.dependency_overrides[get_database] = lambda: registration_database
    response = client.post(PATH, json=VALID | {"email": " SYNTHETIC@EXAMPLE.COM "})
    assert response.status_code == 200
    assert response.json() == MESSAGE
    with registration_database.sessions() as session:
        user = session.scalars(select(User)).one()
        assert (user.id, user.name, user.password_hash, user.is_active, user.updated_at) == before


@pytest.mark.postgres
def test_concurrent_registration_has_one_winner_and_reusable_sessions(registration_database):
    barrier = Barrier(2)

    def attempt():
        with registration_database.sessions() as session:
            barrier.wait(timeout=10)
            register_user(session, RegistrationInput(**VALID))
            # The loser rolled back and its session remains usable.
            assert session.scalar(select(func.count()).select_from(User)) == 1
            return RegistrationResponse().model_dump()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results == [MESSAGE, MESSAGE]
    with registration_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.postgres
def test_concurrent_http_requests_have_identical_public_response(client, registration_database):
    client.app.dependency_overrides[get_database] = lambda: registration_database
    barrier = Barrier(2)

    def attempt(_index):
        barrier.wait(timeout=10)
        response = client.post(PATH, json=VALID)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(attempt, range(2))) == [MESSAGE, MESSAGE]
    with registration_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
