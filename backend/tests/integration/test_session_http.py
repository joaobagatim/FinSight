"""Cookie transport and CSRF over real isolated PostgreSQL session operations."""

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import User, UserSession

pytestmark = pytest.mark.postgres
ORIGIN = "https://app.example.test"
PASSWORD = "synthetic session password"
PREFIX = "/api/v1/auth/"


@pytest.fixture
def clients(postgres_settings):
    assert postgres_settings.db_name.startswith("finsight_test_")
    database = Database(postgres_settings)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_allowed_origins=[ORIGIN],
        auth_login_requests_per_minute=100,
        auth_requests_per_minute=1000,
    )
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with database.sessions.begin() as session:
            for name in ("alice", "bob"):
                session.add(
                    User(
                        name=name,
                        email=f"{name}@example.com",
                        password_hash=hash_password(PASSWORD),
                    )
                )
        with ExitStack() as stack:

            def make():
                app = create_app(settings)
                app.dependency_overrides[get_database] = lambda: database
                return stack.enter_context(TestClient(app, base_url="https://api.example.test"))

            yield make(), make(), database
    finally:
        try:
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "base")
                connection.exec_driver_sql("DROP TABLE alembic_version")
            assert database.engine.pool.checkedout() == 0
        finally:
            database.dispose()


def bootstrap(client):
    response = client.post(
        PREFIX + "csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
    )
    assert response.status_code == 200
    assert set(response.json()) == {"csrf_token"}
    return response.json()["csrf_token"]


def csrf(client):
    return client.cookies.get("__Host-finsight-csrf")


def post(client, route, body=None, token=None):
    return client.post(
        PREFIX + route,
        json={} if body is None else body,
        headers={"Origin": ORIGIN, "X-CSRF-Token": token or csrf(client) or ""},
    )


def login(client, name="alice"):
    token = bootstrap(client)
    response = post(client, "login", {"email": f"{name}@example.com", "password": PASSWORD}, token)
    assert response.status_code == 204
    assert response.content == b""
    assert "__Host-finsight-preauth" not in client.cookies


def test_two_users_profile_rotation_and_logout(clients):
    alice, bob, database = clients
    login(alice)
    login(bob, "bob")
    first = alice.get(PREFIX + "me")
    second = bob.get(PREFIX + "me")
    assert first.status_code == second.status_code == 200
    assert set(first.json()) == {"id", "name", "email"}
    assert first.json()["email"] == "alice@example.com"
    assert second.json()["email"] == "bob@example.com"
    assert first.json()["id"] != second.json()["id"]
    assert alice.get(PREFIX + "me", params={"user_id": second.json()["id"]}).json() == first.json()
    assert post(alice, "refresh").status_code == 204
    assert post(alice, "logout").status_code == 204
    assert alice.get(PREFIX + "me").status_code == 401
    assert bob.get(PREFIX + "me").status_code == 200
    bootstrap(alice)
    assert post(alice, "logout").status_code == 204
    with database.sessions() as session:
        rows = session.scalars(select(UserSession)).all()
        assert sum(row.revoked_at is not None for row in rows) == 1


def test_consumed_refresh_replay_commits_revocation_over_http(clients):
    client, _, database = clients
    login(client)
    old_refresh = client.cookies.get("__Host-finsight-refresh")
    assert post(client, "refresh").status_code == 204
    # A stale independent request replays the original opaque credential.
    client.cookies.set("__Host-finsight-refresh", old_refresh, domain="api.example.test", path="/")
    response = post(client, "refresh")
    assert response.status_code == 401
    assert not any(name.startswith("__Host-finsight-") for name in client.cookies)
    with database.sessions() as session:
        assert session.scalars(select(UserSession)).one().revoked_at is not None


def test_csrf_failure_cannot_revoke_or_clear_cookies(clients):
    client, _, database = clients
    login(client)
    response = post(client, "logout", token="synthetic-invalid-csrf")
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert client.get(PREFIX + "me").status_code == 200
    with database.sessions() as session:
        assert session.scalars(select(UserSession)).one().revoked_at is None


@pytest.mark.parametrize("state", ["inactive", "expired", "revoked"])
def test_dead_session_rejected_and_logout_idempotent(clients, state):
    client, _, database = clients
    login(client)
    with database.sessions.begin() as session:
        row = session.scalars(select(UserSession)).one()
        if state == "inactive":
            session.get(User, row.user_id).is_active = False
        elif state == "expired":
            row.created_at -= timedelta(days=8)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            row.revoked_at = datetime.now(UTC)
    assert client.get(PREFIX + "me").status_code == 401
    # A known credential can still bind CSRF for idempotent logout, not grant access.
    assert post(client, "logout").status_code == 204


def test_expired_access_does_not_prevent_valid_refresh(clients):
    client, _, _ = clients
    login(client)
    raw = client.cookies.get("__Host-finsight-access")
    payload = jwt.decode(raw, options={"verify_signature": False})
    payload.update(iat=payload["iat"] - 1800, nbf=payload["nbf"] - 1800, exp=payload["exp"] - 1800)
    expired = jwt.encode(
        payload, bytes.fromhex("ab" * 32), algorithm="HS256", headers={"typ": "finsight-access+jwt"}
    )
    client.cookies.set("__Host-finsight-access", expired, domain="api.example.test", path="/")
    assert client.get(PREFIX + "me").status_code == 401
    assert post(client, "refresh").status_code == 204
    assert client.get(PREFIX + "me").status_code == 200


def test_mismatched_known_credentials_cannot_choose_session(clients):
    alice, bob, database = clients
    login(alice)
    login(bob, "bob")
    alice.cookies.set(
        "__Host-finsight-access",
        bob.cookies.get("__Host-finsight-access"),
        domain="api.example.test",
        path="/",
    )
    assert alice.get(PREFIX + "me").status_code == 401
    for route in ("refresh", "logout"):
        response = post(alice, route)
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    assert (
        alice.post(
            PREFIX + "csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
        ).status_code
        == 401
    )
    with database.sessions() as session:
        assert all(row.revoked_at is None for row in session.scalars(select(UserSession)))


def test_authenticated_login_needs_logout_and_preauth_is_not_session_csrf(clients):
    client, _, _ = clients
    preauth = bootstrap(client)
    assert (
        post(client, "login", {"email": "alice@example.com", "password": PASSWORD}).status_code
        == 204
    )
    assert post(client, "refresh", token=preauth).status_code == 403
    assert (
        post(client, "login", {"email": "bob@example.com", "password": PASSWORD}).status_code == 409
    )
    assert client.get(PREFIX + "me").json()["email"] == "alice@example.com"


@pytest.mark.parametrize(
    "email,password",
    [("missing@example.com", PASSWORD), ("alice@example.com", "wrong synthetic password")],
)
def test_uniform_failed_login_retains_preauth(clients, email, password):
    client, _, _ = clients
    token = bootstrap(client)
    response = post(client, "login", {"email": email, "password": password}, token)
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication denied"}
    assert "set-cookie" not in response.headers
    assert "__Host-finsight-preauth" in client.cookies


def test_unknown_cookie_bootstrap_only_clears_local_context(clients):
    alice, bob, database = clients
    login(bob, "bob")
    alice.cookies.set(
        "__Host-finsight-refresh", "synthetic-unknown", domain="api.example.test", path="/"
    )
    bootstrap(alice)
    assert "__Host-finsight-refresh" not in alice.cookies
    assert post(alice, "logout").status_code == 204
    assert bob.get(PREFIX + "me").status_code == 200
    with database.sessions() as session:
        assert session.scalars(select(UserSession)).one().revoked_at is None
