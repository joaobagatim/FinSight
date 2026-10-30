"""Atomic own-password changes and real PostgreSQL credential/session races."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
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
from app.core.security import hash_password, verify_password
from app.db.session import Database
from app.main import create_app
from app.models import User, UserSession
from app.services import sessions as module
from app.services.sessions import (
    AuthenticationDenied,
    PasswordChangeRejected,
    SessionService,
    SessionUnavailable,
)

pytestmark = pytest.mark.postgres
CURRENT = "synthetic current password"
NEW = "synthetic replacement password"
EMAIL = "owner@example.com"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/users/me/change-password"


@pytest.fixture
def context(postgres_settings):
    assert postgres_settings.db_name.startswith("finsight_test_")
    database = Database(postgres_settings)
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_allowed_origins=[ORIGIN],
        auth_login_requests_per_minute=100,
        auth_requests_per_minute=1000,
        auth_password_change_requests_per_minute=100,
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with database.sessions.begin() as session:
            for email in (EMAIL, "other@example.com"):
                session.add(
                    User(name="Synthetic", email=email, password_hash=hash_password(CURRENT))
                )
        yield database, SessionService(database, settings), settings
    finally:
        try:
            with database.engine.begin() as connection:
                config.attributes["connection"] = connection
                command.downgrade(config, "base")
                connection.exec_driver_sql("DROP TABLE alembic_version")
            assert database.engine.pool.checkedout() == 0
        finally:
            database.dispose()


def change(service, grant, current=CURRENT, new=NEW):
    service.change_password(grant.access_token, SecretStr(current), SecretStr(new))


def snapshot(database):
    with database.sessions() as session:
        users = [
            (row.id, row.password_hash, row.updated_at)
            for row in session.scalars(select(User).order_by(User.id))
        ]
        sessions = [
            (row.id, row.refresh_token_hash, row.revoked_at)
            for row in session.scalars(select(UserSession).order_by(UserSession.id))
        ]
        return users, sessions


def test_change_revokes_every_owned_session_and_preserves_other_user(context):
    database, service, _ = context
    first = service.login(EMAIL, CURRENT)
    second = service.login(EMAIL, CURRENT)
    revoked = service.login(EMAIL, CURRENT)
    service.revoke_by_access(revoked.access_token)
    other = service.login("other@example.com", CURRENT)
    with database.sessions() as session:
        original_revocation = session.get(UserSession, revoked.context.session_id).revoked_at
    change(service, first)
    for grant in (first, second, revoked):
        with pytest.raises(AuthenticationDenied):
            service.authenticate(grant.access_token)
        with pytest.raises(AuthenticationDenied):
            service.refresh(grant.refresh_token)
    with database.sessions() as session:
        owner = session.get(User, first.context.user_id)
        assert verify_password(NEW, owner.password_hash)
        assert not verify_password(CURRENT, owner.password_hash)
        assert owner.password_hash.startswith("$argon2id$")
        assert (
            session.get(UserSession, revoked.context.session_id).revoked_at == original_revocation
        )
    assert service.authenticate(other.access_token) == other.context
    with pytest.raises(AuthenticationDenied):
        service.login(EMAIL, CURRENT)
    assert service.login(EMAIL, NEW).context.user_id == first.context.user_id


@pytest.mark.parametrize(
    "current,new,error",
    [
        ("wrong synthetic password", NEW, AuthenticationDenied),
        (CURRENT, CURRENT, PasswordChangeRejected),
    ],
)
def test_rejected_change_does_not_touch_password_or_sessions(context, current, new, error):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    before = snapshot(database)
    with pytest.raises(error):
        change(service, grant, current, new)
    assert snapshot(database) == before


@pytest.mark.parametrize("state", ["inactive", "revoked", "expired"])
def test_invalid_user_or_session_cannot_change_password(context, state):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    with database.sessions.begin() as session:
        row = session.get(UserSession, grant.context.session_id)
        if state == "inactive":
            session.get(User, grant.context.user_id).is_active = False
        elif state == "revoked":
            row.revoked_at = datetime.now(UTC)
        else:
            row.created_at -= timedelta(days=8)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    before = snapshot(database)
    with pytest.raises(AuthenticationDenied):
        change(service, grant)
    assert snapshot(database) == before


def test_failed_commit_rolls_back_hash_and_all_revocations(context):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    service.login(EMAIL, CURRENT)
    before = snapshot(database)

    def fail(_session):
        raise SQLAlchemyError("synthetic-private-driver-marker")

    event.listen(database.sessions, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable) as caught:
            change(service, grant)
        assert str(caught.value) == "Session service unavailable"
    finally:
        event.remove(database.sessions, "before_commit", fail)
    assert snapshot(database) == before


def test_future_owned_session_causes_safe_rollback(context):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    with database.sessions.begin() as session:
        session.add(
            UserSession(
                user_id=grant.context.user_id,
                refresh_token_hash=uuid4().hex,
                created_at=datetime.now(UTC) + timedelta(days=1),
                expires_at=datetime.now(UTC) + timedelta(days=2),
            )
        )
    before = snapshot(database)
    with pytest.raises(SessionUnavailable):
        change(service, grant)
    assert snapshot(database) == before


def test_user_deactivation_during_verification_is_rechecked(context, monkeypatch):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    verify = module.verify_password

    def deactivate(password, encoded):
        result = verify(password, encoded)
        with database.sessions.begin() as session:
            session.get(User, grant.context.user_id).is_active = False
        return result

    monkeypatch.setattr(module, "verify_password", deactivate)
    with pytest.raises(AuthenticationDenied):
        change(service, grant)
    with database.sessions() as session:
        assert verify(CURRENT, session.get(User, grant.context.user_id).password_hash)
        assert session.get(UserSession, grant.context.session_id).revoked_at is None


def test_two_concurrent_changes_cannot_overwrite_each_other(context, monkeypatch):
    database, service, _ = context
    first = service.login(EMAIL, CURRENT)
    second = service.login(EMAIL, CURRENT)
    barrier = Barrier(2, timeout=10)
    verify = module.verify_password

    def synchronized(password, encoded):
        result = verify(password, encoded)
        barrier.wait()
        return result

    monkeypatch.setattr(module, "verify_password", synchronized)

    def attempt(grant, new):
        try:
            change(service, grant, new=new)
            return True
        except AuthenticationDenied:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(attempt, first, NEW)
        b = executor.submit(attempt, second, "other synthetic new password")
        results = [a.result(timeout=20), b.result(timeout=20)]
    assert sum(results) == 1
    with database.sessions() as session:
        owner = session.get(User, first.context.user_id)
        winner = NEW if results[0] else "other synthetic new password"
        assert verify(winner, owner.password_hash)
        assert all(row.revoked_at is not None for row in session.scalars(select(UserSession)))


def test_old_login_waiting_for_user_lock_is_denied_after_change(context, monkeypatch):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    verified, release = Event(), Event()
    original = module.verify_password

    def pause_old_login(password, encoded):
        result = original(password, encoded)
        verified.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test coordination timed out")
        return result

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(module, "verify_password", pause_old_login)
        future = executor.submit(service.login, EMAIL, CURRENT)
        try:
            assert verified.wait(timeout=10)
            monkeypatch.setattr(module, "verify_password", original)
            change(service, grant)
        finally:
            release.set()
        with pytest.raises(AuthenticationDenied):
            future.result(timeout=20)
    with database.sessions() as session:
        assert all(row.revoked_at is not None for row in session.scalars(select(UserSession)))


@pytest.mark.parametrize("refresh_first", [True, False])
def test_refresh_password_change_lock_order(context, monkeypatch, refresh_first):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    ready, release = Event(), Event()
    original = service._lock

    def pause(session, user_id, session_id):
        ready.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test coordination timed out")
        return original(session, user_id, session_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(service, "_lock", pause)
        if refresh_first:
            future = executor.submit(service.refresh, grant.refresh_token)
        else:
            future = executor.submit(change, service, grant)
        try:
            assert ready.wait(timeout=10)
            monkeypatch.setattr(service, "_lock", original)
            if refresh_first:
                change(service, grant)
            else:
                service.refresh(grant.refresh_token)
        finally:
            release.set()
        if refresh_first:
            with pytest.raises(AuthenticationDenied):
                future.result(timeout=20)
        else:
            future.result(timeout=20)
    with database.sessions() as session:
        assert all(row.revoked_at is not None for row in session.scalars(select(UserSession)))


def http_clients(context):
    database, _, settings = context
    stack = ExitStack()

    def make():
        app = create_app(settings)
        app.dependency_overrides[get_database] = lambda: database
        return stack.enter_context(TestClient(app, base_url="https://api.example.test"))

    return stack, make


def http_login(client, email=EMAIL, password=CURRENT):
    bootstrap = client.post(
        "/api/v1/auth/csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
    )
    assert bootstrap.status_code == 200
    token = bootstrap.json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"Origin": ORIGIN, "X-CSRF-Token": token},
    )
    assert response.status_code == 204


def http_change(client, body=None, token=None):
    return client.post(
        PATH,
        json=body or {"current_password": CURRENT, "new_password": NEW},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": token or client.cookies.get("__Host-finsight-csrf") or "",
        },
    )


def test_http_success_clears_cookies_and_revokes_other_device(context):
    stack, make = http_clients(context)
    with stack:
        client, device, other = make(), make(), make()
        http_login(client)
        http_login(device)
        http_login(other, "other@example.com")
        response = http_change(client)
        assert response.status_code == 204 and response.content == b""
        assert response.headers["cache-control"] == "no-store"
        assert not any(name.startswith("__Host-finsight-") for name in client.cookies)
        assert client.get("/api/v1/auth/me").status_code == 401
        assert device.get("/api/v1/auth/me").status_code == 401
        assert other.get("/api/v1/auth/me").status_code == 200
        http_login(client, password=NEW)


def test_http_password_change_uses_shared_hash_slots(context):
    database, _, _ = context
    stack, make = http_clients(context)
    with stack:
        client = make()
        http_login(client)
        before = snapshot(database)
        slots = client.app.state.registration_limits.hash_slots
        assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
        try:
            response = http_change(client)
            assert response.status_code == 429 and response.headers["retry-after"] == "1"
            assert "set-cookie" not in response.headers
        finally:
            slots.release()
            slots.release()
        assert snapshot(database) == before


def test_access_expiring_during_reauthentication_does_not_change_state(context, monkeypatch):
    database, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    now = datetime.now(UTC)
    monkeypatch.setattr(service, "_clock", lambda: now)
    verify = module.verify_password

    def advance(password, encoded):
        nonlocal now
        valid = verify(password, encoded)
        now += timedelta(minutes=16)
        return valid

    monkeypatch.setattr(module, "verify_password", advance)
    before = snapshot(database)
    with pytest.raises(AuthenticationDenied):
        change(service, grant)
    assert snapshot(database) == before


def test_http_accepts_full_length_unicode_passwords_without_trimming(context):
    _, service, _ = context
    grant = service.login(EMAIL, CURRENT)
    unicode_current = "\U0001f512" * 128
    unicode_new = "\U0001f511" * 128
    change(service, grant, new=unicode_current)
    stack, make = http_clients(context)
    with stack:
        client = make()
        http_login(client, password=unicode_current)
        response = http_change(
            client, {"current_password": unicode_current, "new_password": unicode_new}
        )
        assert response.status_code == 204
        http_login(client, password=unicode_new)


@pytest.mark.parametrize(
    "case,status", [("wrong", 401), ("equal", 422), ("csrf", 403), ("identity", 422)]
)
def test_http_rejections_do_not_mutate_or_echo(context, case, status, caplog):
    database, _, _ = context
    stack, make = http_clients(context)
    with stack:
        client = make()
        http_login(client)
        body = {"current_password": CURRENT, "new_password": NEW}
        token = None
        if case == "wrong":
            body["current_password"] = "synthetic-private-password-marker"
        elif case == "equal":
            body["new_password"] = CURRENT
        elif case == "identity":
            body["user_id"] = "synthetic-private-password-marker"
        else:
            token = "synthetic-private-password-marker"
        before = snapshot(database)
        response = http_change(client, body, token)
        assert response.status_code == status
        assert (
            response.headers["cache-control"] == "no-store" and "set-cookie" not in response.headers
        )
        assert "synthetic-private-password-marker" not in response.text + caplog.text
        assert snapshot(database) == before
        assert client.get("/api/v1/auth/me").status_code == 200
