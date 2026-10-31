"""Own-profile changes on an owned PostgreSQL database, with one migration per module."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import User, UserSession
from app.schemas.users import ProfileUpdateInput
from app.services import sessions as module
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic profile password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/users/me"


@pytest.fixture(scope="module")
def profile_database(postgres_settings):
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


@pytest.fixture
def context(profile_database):
    # Distinct owners per test allow committed transactions without shared mutable rows.
    emails = [f"profile-{uuid4().hex}@example.com" for _ in range(2)]
    with profile_database.sessions.begin() as session:
        for email in emails:
            session.add(
                User(name="Synthetic Owner", email=email, password_hash=hash_password(PASSWORD))
            )
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_allowed_origins=[ORIGIN],
        auth_login_requests_per_minute=100,
        auth_password_change_requests_per_minute=100,
        auth_requests_per_minute=1000,
    )
    return profile_database, SessionService(profile_database, settings), settings, emails


def clients(context):
    database, _, settings, _ = context
    stack = ExitStack()

    def make():
        app = create_app(settings)
        app.dependency_overrides[get_database] = lambda: database
        return stack.enter_context(TestClient(app, base_url="https://api.example.test"))

    return stack, make


def login(client, email):
    response = client.post(
        "/api/v1/auth/csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
    )
    assert response.status_code == 200
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]},
    )
    assert response.status_code == 204


def patch(client, body, csrf=None):
    return client.patch(
        PATH,
        json=body,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": csrf or client.cookies.get("__Host-finsight-csrf") or "",
        },
    )


def test_own_name_update_and_http_authorization(context):
    _, _, _, emails = context
    stack, make = clients(context)
    with stack:
        client, other, anonymous = make(), make(), make()
        login(client, emails[0])
        login(other, emails[1])
        assert anonymous.get(PATH).status_code == 401
        assert anonymous.patch(PATH, json={"name": "Intruder"}).status_code == 403
        assert (
            anonymous.patch(PATH, json={"name": "Intruder"}, headers={"Origin": ORIGIN}).status_code
            == 401
        )
        initial = client.get(PATH).json()
        assert set(initial) == {"id", "name", "email"}
        assert patch(client, {"name": "Updated"}, csrf="invalid").status_code == 403
        response = patch(client, {"name": "Updated", "user_id": other.get(PATH).json()["id"]})
        assert response.status_code == 422 and "user_id" not in response.text
        response = patch(client, {"name": "  Updated  "})
        assert response.status_code == 204 and response.content == b""
        assert "set-cookie" not in response.headers
        assert client.get(PATH).json() == initial | {"name": "Updated"}
        assert client.get("/api/v1/auth/me").json() == client.get(PATH).json()
        assert other.get(PATH).json()["name"] == "Synthetic Owner"


def test_email_rejections_preserve_profile_and_session(context):
    _, _, _, emails = context
    stack, make = clients(context)
    with stack:
        client = make()
        login(client, emails[0])
        initial = client.get(PATH).json()
        responses = [
            patch(client, {"email": "new@example.com"}),
            patch(
                client, {"email": "new@example.com", "current_password": "wrong synthetic password"}
            ),
            patch(
                client, {"name": "Must roll back", "email": emails[1], "current_password": PASSWORD}
            ),
        ]
        assert [response.status_code for response in responses] == [422, 401, 409]
        for response in responses:
            assert "set-cookie" not in response.headers
            assert response.headers["cache-control"] == "no-store"
            assert PASSWORD not in response.text and emails[1] not in response.text
        assert client.get(PATH).json() == initial


def test_email_change_revokes_owned_devices_preserving_other_user(context):
    database, service, _, emails = context
    stack, make = clients(context)
    with stack:
        client, device, other = make(), make(), make()
        login(client, emails[0])
        login(device, emails[0])
        login(other, emails[1])
        revoked = service.login(emails[0], PASSWORD)
        service.revoke_by_access(revoked.access_token)
        with database.sessions() as session:
            first_revocation = session.get(UserSession, revoked.context.session_id).revoked_at
        # Equivalent normalized email does not require reauthentication or log users out.
        assert patch(client, {"email": f"  {emails[0].upper()}  "}).status_code == 204
        new_email = f"new-{uuid4().hex}@example.com"
        response = patch(client, {"email": new_email, "current_password": PASSWORD})
        assert response.status_code == 204 and not client.cookies
        assert client.get(PATH).status_code == device.get(PATH).status_code == 401
        assert other.get(PATH).status_code == 200
        with pytest.raises(AuthenticationDenied):
            service.login(emails[0], PASSWORD)
        with pytest.raises(AuthenticationDenied):
            service.refresh(revoked.refresh_token)
        login(client, new_email)
        assert client.get(PATH).json()["email"] == new_email
        with database.sessions() as session:
            assert (
                session.get(UserSession, revoked.context.session_id).revoked_at == first_revocation
            )


def test_commit_failure_rolls_back_profile_and_revocations(context):
    database, service, _, emails = context
    grant = service.login(emails[0], PASSWORD)
    session_class = database.sessions.class_

    def fail(_session):
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(session_class, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.update_profile(
                grant.access_token,
                ProfileUpdateInput(
                    name="Must roll back", email="rollback@example.com", current_password=PASSWORD
                ),
            )
    finally:
        event.remove(session_class, "before_commit", fail)
    owner = service.authenticate(grant.access_token)
    assert owner.email == emails[0] and owner.name == "Synthetic Owner"
    with database.sessions() as session:
        assert (
            session.scalar(
                select(UserSession.revoked_at).where(UserSession.id == grant.context.session_id)
            )
            is None
        )


def test_old_email_login_cannot_complete_after_email_change(context, monkeypatch):
    _, service, _, emails = context
    grant = service.login(emails[0], PASSWORD)
    ready, release = Event(), Event()
    original = module.verify_password

    def pause(password, encoded):
        result = original(password, encoded)
        ready.set()
        assert release.wait(timeout=10)
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(module, "verify_password", pause)
        future = executor.submit(service.login, emails[0], PASSWORD)
        try:
            assert ready.wait(timeout=10)
            monkeypatch.setattr(module, "verify_password", original)
            service.update_profile(
                grant.access_token,
                ProfileUpdateInput(
                    email=f"changed-{uuid4().hex}@example.com", current_password=SecretStr(PASSWORD)
                ),
            )
        finally:
            release.set()
        with pytest.raises(AuthenticationDenied):
            future.result(timeout=20)
