"""Real committed PostgreSQL transactions, replay persistence and session isolation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.refresh_tokens import generate_refresh_token, refresh_token_digest
from app.core.security import hash_password
from app.core.tokens import TokenConfigurationError
from app.db.session import Database
from app.models import RefreshTokenHistory, User, UserSession
from app.services import sessions as module
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic session password"
EMAIL = "owner@example.test"


@pytest.fixture
def database(postgres_settings):
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
def settings():
    return Settings(_env_file=None, environment="test", jwt_signing_key="ab" * 32)


def add_user(database, *, email=EMAIL, active=True):
    with database.sessions.begin() as session:
        user = User(
            name="Synthetic owner",
            email=email,
            password_hash=hash_password(PASSWORD),
            is_active=active,
        )
        session.add(user)
        session.flush()
        return user.id


@pytest.fixture
def owner(database):
    return add_user(database)


@pytest.fixture
def service(database, settings):
    return SessionService(database, settings)


def counts(database):
    with database.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model))
            for model in (UserSession, RefreshTokenHistory)
        )


def test_login_digest_claims_and_absolute_expiry(database, service, owner, caplog):
    grant = service.login(" OWNER@EXAMPLE.TEST ", SecretStr(PASSWORD))
    assert grant.context.user_id == owner
    assert service.authenticate(grant.access_token) == grant.context
    with database.sessions() as session:
        row = session.get(UserSession, grant.context.session_id)
        assert row.refresh_token_hash == refresh_token_digest(grant.refresh_token)
        assert row.expires_at - row.created_at == timedelta(days=7)
        assert row.last_used_at is None and row.revoked_at is None
        assert grant.refresh_token.get_secret_value() not in row.refresh_token_hash
    claims = service._tokens.verify(grant.access_token)
    assert claims.user_id == owner and claims.session_id == grant.context.session_id
    assert claims.expires_at == grant.access_expires_at
    assert not caplog.text


@pytest.mark.parametrize("case", ["wrong", "missing", "inactive"])
def test_uniform_credential_failure(database, service, case, caplog):
    if case != "missing":
        add_user(database, active=case != "inactive")
    with pytest.raises(AuthenticationDenied) as caught:
        service.login(EMAIL, PASSWORD if case != "wrong" else "different synthetic password")
    assert str(caught.value) == "Authentication denied"
    assert counts(database) == (0, 0)
    assert not caplog.text


def test_unknown_identity_uses_dummy_verification(database, service, monkeypatch):
    seen = []
    original = module.verify_password

    def record(password, encoded):
        seen.append(encoded)
        return original(password, encoded)

    monkeypatch.setattr(module, "verify_password", record)
    for _ in range(2):
        with pytest.raises(AuthenticationDenied):
            service.login(EMAIL, PASSWORD)
    assert len(seen) == 2 and seen[0] == seen[1]
    assert seen[0].startswith("$argon2id$")


@pytest.mark.parametrize("mutation", ["inactive", "password", "email"])
def test_login_rechecks_after_password_verification(
    database, service, owner, monkeypatch, mutation
):
    original = module.verify_password

    def race(password, encoded):
        valid = original(password, encoded)
        with database.sessions.begin() as session:
            row = session.get(User, owner)
            if mutation == "inactive":
                row.is_active = False
            elif mutation == "password":
                row.password_hash = hash_password("changed synthetic password")
            else:
                row.email = "changed@example.test"
        return valid

    monkeypatch.setattr(module, "verify_password", race)
    with pytest.raises(AuthenticationDenied):
        service.login(EMAIL, PASSWORD)
    assert counts(database) == (0, 0)


def test_rotation_then_replay_commits_revocation(database, service, owner):
    first = service.login(EMAIL, PASSWORD)
    other = service.login(EMAIL, PASSWORD)
    second = service.refresh(first.refresh_token)
    assert first.refresh_token != second.refresh_token
    assert first.context.session_expires_at == second.context.session_expires_at
    with database.sessions() as session:
        row = session.get(UserSession, first.context.session_id)
        history = session.scalars(select(RefreshTokenHistory)).one()
        assert history.token_hash == refresh_token_digest(first.refresh_token)
        assert history.session_id == row.id
        assert row.refresh_token_hash == refresh_token_digest(second.refresh_token)
        assert row.last_used_at >= row.created_at
    with pytest.raises(AuthenticationDenied):
        service.refresh(first.refresh_token)
    with database.sessions() as session:
        revoked_at = session.get(UserSession, first.context.session_id).revoked_at
        assert revoked_at is not None
    for token in (first.access_token, second.access_token):
        with pytest.raises(AuthenticationDenied):
            service.authenticate(token)
    with pytest.raises(AuthenticationDenied):
        service.refresh(second.refresh_token)
    with pytest.raises(AuthenticationDenied):
        service.refresh(first.refresh_token)
    with database.sessions() as session:
        assert session.get(UserSession, first.context.session_id).revoked_at == revoked_at
    assert service.authenticate(other.access_token) == other.context


@pytest.mark.parametrize(
    "token",
    [None, "bad-marker", "x" * 100000, generate_refresh_token()],
    ids=["none", "malformed", "large", "unknown"],
)
def test_unknown_refresh_never_revokes(database, service, owner, token):
    grant = service.login(EMAIL, PASSWORD)
    for operation in (service.refresh, service.revoke_by_refresh):
        with pytest.raises(AuthenticationDenied):
            operation(token)
    assert service.authenticate(grant.access_token) == grant.context
    assert counts(database) == (1, 0)


@pytest.mark.parametrize("state", ["inactive", "expired", "future", "revoked"])
def test_session_state_denies_access_and_refresh(database, service, owner, state):
    grant = service.login(EMAIL, PASSWORD)
    with database.sessions.begin() as session:
        row = session.get(UserSession, grant.context.session_id)
        if state == "inactive":
            session.get(User, owner).is_active = False
        elif state == "expired":
            row.created_at -= timedelta(days=8)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif state == "future":
            row.created_at += timedelta(hours=1)
        else:
            row.revoked_at = datetime.now(UTC)
    with pytest.raises(AuthenticationDenied):
        service.authenticate(grant.access_token)
    with pytest.raises(AuthenticationDenied):
        service.refresh(grant.refresh_token)
    assert counts(database) == (1, 0)


@pytest.mark.parametrize("credential", ["access", "refresh", "consumed"])
def test_logout_idempotent_and_other_user_session_untouched(database, service, owner, credential):
    grant = service.login(EMAIL, PASSWORD)
    own_other = service.login(EMAIL, PASSWORD)
    add_user(database, email="other@example.test")
    other = service.login("other@example.test", PASSWORD)
    if credential == "consumed":
        service.refresh(grant.refresh_token)
    operation = service.revoke_by_access if credential == "access" else service.revoke_by_refresh
    token = grant.access_token if credential == "access" else grant.refresh_token
    operation(token)
    with database.sessions() as session:
        before = session.get(UserSession, grant.context.session_id).revoked_at
    operation(token)
    with database.sessions() as session:
        assert session.get(UserSession, grant.context.session_id).revoked_at == before
    with pytest.raises(AuthenticationDenied):
        service.authenticate(grant.access_token)
    assert service.authenticate(other.access_token) == other.context
    assert service.authenticate(own_other.access_token) == own_other.context


def test_signed_mismatched_owner_and_unknown_session_denied(database, service, owner):
    grant = service.login(EMAIL, PASSWORD)
    other_id = add_user(database, email="other@example.test")
    for user_id, session_id in ((other_id, grant.context.session_id), (owner, uuid4())):
        token = service._tokens.issue(user_id, session_id)
        for operation in (service.authenticate, service.revoke_by_access):
            with pytest.raises(AuthenticationDenied):
                operation(token)
    assert service.authenticate(grant.access_token) == grant.context


def test_refresh_atomic_rollback_on_grant_failure(database, service, owner, monkeypatch):
    grant = service.login(EMAIL, PASSWORD)

    def fail(*args):
        raise SQLAlchemyError("synthetic-private-marker")

    monkeypatch.setattr(service, "_grant", fail)
    with pytest.raises(SessionUnavailable) as caught:
        service.refresh(grant.refresh_token)
    assert str(caught.value) == "Session service unavailable"
    assert caught.value.__suppress_context__
    assert counts(database) == (1, 0)
    with database.sessions() as session:
        assert session.get(
            UserSession, grant.context.session_id
        ).refresh_token_hash == refresh_token_digest(grant.refresh_token)


def test_login_rollback_on_grant_failure(database, service, owner, monkeypatch):
    def fail(*args):
        raise SQLAlchemyError("synthetic-private-marker")

    monkeypatch.setattr(service, "_grant", fail)
    with pytest.raises(SessionUnavailable):
        service.login(EMAIL, PASSWORD)
    assert counts(database) == (0, 0)


def test_replacement_equal_to_consumed_token_fails_closed(database, service, owner, monkeypatch):
    grant = service.login(EMAIL, PASSWORD)
    monkeypatch.setattr(module, "generate_refresh_token", lambda: grant.refresh_token)
    with pytest.raises(SessionUnavailable):
        service.refresh(grant.refresh_token)
    assert counts(database) == (1, 0)
    assert service.authenticate(grant.access_token) == grant.context


def test_ambiguous_cross_table_digest_denied_without_revoking(database, service, owner):
    grant = service.login(EMAIL, PASSWORD)
    service.refresh(grant.refresh_token)
    with database.sessions.begin() as session:
        session.add(
            UserSession(
                user_id=owner,
                refresh_token_hash=refresh_token_digest(grant.refresh_token),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    with pytest.raises(AuthenticationDenied):
        service.refresh(grant.refresh_token)
    with database.sessions() as session:
        assert all(row.revoked_at is None for row in session.scalars(select(UserSession)))


@pytest.mark.parametrize("logout_race", [False, True])
def test_concurrent_refresh_and_logout_policy(database, service, owner, monkeypatch, logout_race):
    grant = service.login(EMAIL, PASSWORD)
    barrier = Barrier(2, timeout=10)
    resolve = service._resolve

    def synchronized(session, digest):
        candidate = resolve(session, digest)
        barrier.wait()
        return candidate

    monkeypatch.setattr(service, "_resolve", synchronized)

    def rotate():
        try:
            return service.refresh(grant.refresh_token)
        except AuthenticationDenied:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(rotate)
        second = (
            executor.submit(service.revoke_by_refresh, grant.refresh_token)
            if logout_race
            else executor.submit(rotate)
        )
        results = [first.result(timeout=20), second.result(timeout=20)]
    if not logout_race:
        assert sum(result is not None for result in results) == 1
    with database.sessions() as session:
        assert session.get(UserSession, grant.context.session_id).revoked_at is not None
    with pytest.raises(AuthenticationDenied):
        service.authenticate(grant.access_token)
    for result in results:
        if result is not None:
            with pytest.raises(AuthenticationDenied):
                service.authenticate(result.access_token)


def test_absolute_expiry_uses_injected_clock(database, settings, owner):
    now = datetime.now(UTC)
    service = SessionService(database, settings, clock=lambda: now)
    first = service.login(EMAIL, PASSWORD)
    now += timedelta(days=6)
    second = service.refresh(first.refresh_token)
    assert second.context.session_expires_at == first.context.session_expires_at
    now += timedelta(days=1)
    with pytest.raises(AuthenticationDenied):
        service.refresh(second.refresh_token)


def test_missing_database_or_signing_key_fails_closed(settings):
    database = Database(Settings(_env_file=None))
    service = SessionService(database, settings)
    with pytest.raises(SessionUnavailable):
        service.login(EMAIL, PASSWORD)
    with pytest.raises(TokenConfigurationError):
        SessionService(database, Settings(_env_file=None))


def test_csrf_binding_is_not_authorization_and_accepts_consumed_digest(database, service, owner):
    grant = service.login(EMAIL, PASSWORD)
    second = service.refresh(grant.refresh_token)
    assert (
        service.csrf_binding(refresh=grant.refresh_token, access=second.access_token)
        == grant.context.session_id
    )
    service.revoke_by_refresh(second.refresh_token)
    assert service.csrf_binding(refresh=second.refresh_token) == grant.context.session_id
    with pytest.raises(AuthenticationDenied):
        service.authenticate(second.access_token)


def test_csrf_binding_rejects_conflicting_signed_credentials(database, service, owner):
    first = service.login(EMAIL, PASSWORD)
    second = service.login(EMAIL, PASSWORD)
    with pytest.raises(module.SessionBindingMismatch):
        service.csrf_binding(refresh=first.refresh_token, access=second.access_token)


def test_access_only_binding_requires_existing_owned_session(database, service, owner):
    grant = service.login(EMAIL, PASSWORD)
    assert service.csrf_binding(access=grant.access_token) == grant.context.session_id
    with pytest.raises(AuthenticationDenied):
        service.csrf_binding(access=service._tokens.issue(owner, uuid4()))
