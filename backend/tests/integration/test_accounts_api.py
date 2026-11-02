"""Account authorization, persistent retries and atomicity on owned PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import Account, AccountCreationRequest, Category, Transaction, User
from app.schemas.accounts import AccountInput, AccountUpdateInput
from app.services.accounts import AccountConflict, AccountService, AccountStale, account_etag
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic account password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/accounts"
BODY = {
    "name": "Synthetic account",
    "type": "checking",
    "opening_balance": "-10.25",
    "opening_date": "2026-01-01",
}


@pytest.fixture(scope="module")
def accounts_database(postgres_settings):
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
def context(accounts_database):
    emails = [f"accounts-{uuid4().hex}@example.com" for _ in range(2)]
    with accounts_database.sessions.begin() as session:
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
        auth_requests_per_minute=1000,
    )
    return accounts_database, SessionService(accounts_database, settings), settings, emails


def clients(context):
    database, _, settings, _ = context
    stack = ExitStack()

    def make(email=None):
        app = create_app(settings)
        app.dependency_overrides[get_database] = lambda: database
        client = stack.enter_context(TestClient(app, base_url="https://api.example.test"))
        if email:
            csrf = client.post(
                "/api/v1/auth/csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
            )
            assert csrf.status_code == 200
            assert (
                client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": PASSWORD},
                    headers={"Origin": ORIGIN, "X-CSRF-Token": csrf.json()["csrf_token"]},
                ).status_code
                == 204
            )
        return client

    return stack, make


def create(client, key, body=BODY):
    return client.post(
        PATH,
        json=body,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or "",
            "Idempotency-Key": str(key),
        },
    )


def counts(database, user):
    with database.sessions() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model).where(model.user_id == user))
            for model in (Account, AccountCreationRequest)
        )


def patch(client, location, etag, data):
    return client.patch(
        location,
        json=data,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or "",
            "If-Match": etag,
        },
    )


def test_conditional_edits_archive_and_owner_isolation(context):
    stack, make = clients(context)
    with stack:
        owner, other = make(context[3][0]), make(context[3][1])
        key = uuid4()
        created = create(owner, key)
        location = created.headers["location"]
        original = owner.get(location)
        etag = original.headers["etag"]
        changed = patch(owner, location, etag, {"name": "Renamed", "type": "savings"})
        assert changed.status_code == 200 and changed.headers["etag"] != etag
        assert changed.json() == original.json() | {"name": "Renamed", "type": "savings"}
        assert patch(owner, location, etag, {"name": "Stale"}).status_code == 412
        current = changed.headers["etag"]
        foreign = patch(other, location, current, {"is_active": False})
        missing = patch(other, f"{PATH}/{uuid4()}", current, {"is_active": False})
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        assert patch(owner, location, current, {"opening_balance": "99.00"}).status_code == 422
        assert (
            owner.patch(
                location,
                json={"name": "Rejected"},
                headers={
                    "Origin": ORIGIN,
                    "If-Match": current,
                },
            ).status_code
            == 403
        )
        assert (
            owner.patch(
                location,
                json={"name": "Rejected"},
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": owner.cookies.get("__Host-finsight-csrf"),
                },
            ).status_code
            == 422
        )
        archived = patch(owner, location, current, {"is_active": False})
        assert archived.status_code == 200 and not archived.json()["is_active"]
        repeated = patch(owner, location, archived.headers["etag"], {"is_active": False})
        assert repeated.status_code == 200 and repeated.headers["etag"] == archived.headers["etag"]
        assert create(owner, key).json() == created.json()
        assert owner.get(location).json() == archived.json()
        restored = patch(owner, location, archived.headers["etag"], {"is_active": True})
        assert restored.status_code == 200 and restored.json()["is_active"]
        assert restored.headers["cache-control"] == "no-store"
        cors = owner.options(
            location,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "if-match,content-type,x-csrf-token",
            },
        )
        assert (
            cors.status_code == 200 and "ETag" in restored.headers["access-control-expose-headers"]
        )
        assert (
            owner.patch(
                location,
                content="x" * 17000,
                headers={
                    "Content-Type": "application/json",
                    "Origin": ORIGIN,
                },
            ).status_code
            == 413
        )
        assert (
            owner.patch(
                location,
                json={"name": "Rejected"},
                headers=[
                    ("If-Match", etag),
                    ("If-Match", etag),
                    ("Origin", ORIGIN),
                ],
            ).status_code
            == 403
        )


def test_concurrent_account_edits_reject_stale_snapshot(context):
    _, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = AccountService(sessions)
    account_id = service.create(token, uuid4(), AccountInput(**BODY))
    etag = account_etag(service.get(token, account_id))
    barrier = Barrier(2)

    def run(name):
        barrier.wait(timeout=10)
        try:
            service.update(token, account_id, AccountUpdateInput(name=name), etag)
            return "saved"
        except AccountStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, name) for name in ("First", "Second")]
        assert sorted(f.result(timeout=20) for f in futures) == ["saved", "stale"]
    assert service.get(token, account_id).name in {"First", "Second"}


def test_failed_account_update_rolls_back(context):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = AccountService(sessions)
    account_id = service.create(token, uuid4(), AccountInput(**BODY))
    original = service.get(token, account_id)

    def fail(_session):
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.update(
                token,
                account_id,
                AccountUpdateInput(name="Lost", is_active=False),
                account_etag(original),
            )
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, account_id) == original


def test_archiving_preserves_existing_financial_history(context):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    service = AccountService(sessions)
    account_id = service.create(grant.access_token, uuid4(), AccountInput(**BODY))
    with database.sessions.begin() as session:
        category = Category(user_id=grant.context.user_id, name="Synthetic income", type="income")
        session.add(category)
        session.flush()
        transaction = Transaction(
            user_id=grant.context.user_id,
            account_id=account_id,
            category_id=category.id,
            description="Synthetic history",
            amount=Decimal("12.34"),
            type="income",
            status="posted",
            effective_date=date(2026, 1, 2),
        )
        session.add(transaction)
        session.flush()
        transaction_id = transaction.id
        snapshot = {
            column.name: getattr(transaction, column.name)
            for column in Transaction.__table__.columns
        }
    original = service.get(grant.access_token, account_id)
    archived = service.update(
        grant.access_token, account_id, AccountUpdateInput(is_active=False), account_etag(original)
    )
    assert not archived.is_active
    assert archived.opening_balance == original.opening_balance
    assert archived.opening_date == original.opening_date
    with database.sessions() as session:
        stored = session.get(Transaction, transaction_id)
        assert stored is not None
        assert {
            column.name: getattr(stored, column.name) for column in Transaction.__table__.columns
        } == snapshot


def test_http_create_retry_list_and_owner_isolation(context):
    _, _, _, emails = context
    stack, make = clients(context)
    with stack:
        first, other, anonymous = make(emails[0]), make(emails[1]), make()
        assert anonymous.get(PATH).status_code == 401
        key = uuid4()
        response = create(first, key)
        assert response.status_code == 201 and set(response.json()) == {"id"}
        location = response.headers["location"]
        assert create(first, key).json() == response.json()
        assert create(first, key, BODY | {"name": "Conflicting account"}).status_code == 409
        second = create(first, uuid4())
        assert second.status_code == 201
        foreign = create(other, key)
        assert foreign.status_code == 201 and foreign.json() != response.json()
        profile = first.get(location)
        assert profile.status_code == 200 and profile.json()["opening_balance"] == "-10.25"
        assert "user_id" not in profile.json() and "balance" not in profile.json()
        assert other.get(location).status_code == 404
        assert other.get(f"{PATH}/{uuid4()}").json() == other.get(location).json()
        page = first.get(PATH, params={"limit": 1}).json()
        assert len(page["items"]) == 1 and page["has_more"]
        assert not first.get(PATH, params={"limit": 1, "offset": 1}).json()["has_more"]
        assert len(other.get(PATH).json()["items"]) == 1
        rejected = create(first, uuid4(), BODY | {"user_id": "synthetic-private-marker"})
        assert rejected.status_code == 422 and "synthetic-private-marker" not in rejected.text
        assert create(first, uuid4(), BODY | {"opening_balance": 0.1}).status_code == 422
        assert (
            first.post(
                PATH, json=BODY, headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())}
            ).status_code
            == 403
        )
        assert (
            first.post(
                PATH,
                json=BODY,
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": first.cookies.get("__Host-finsight-csrf"),
                },
            ).status_code
            == 422
        )
        assert profile.headers["cache-control"] == response.headers["cache-control"] == "no-store"


def test_concurrent_retries_persist_one_account_across_service_instances(context):
    database, sessions, settings, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    owner = sessions.authenticate(token).user_id
    service = AccountService(sessions)
    key, barrier = uuid4(), Barrier(2)
    data = AccountInput(**(BODY | {"opening_balance": "0.1"}))

    def run():
        barrier.wait(timeout=10)
        return service.create(token, key, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1] and counts(database, owner) == (1, 1)
    replacement_service = AccountService(SessionService(database, settings))
    assert (
        replacement_service.create(token, key, AccountInput(**(BODY | {"opening_balance": "0.10"})))
        == ids[0]
    )
    with pytest.raises(AccountConflict):
        replacement_service.create(token, key, AccountInput(**(BODY | {"opening_balance": "0.20"})))
    assert counts(database, owner) == (1, 1)


def test_commit_failure_rolls_back_account_and_key(context):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    service, key = AccountService(sessions), uuid4()

    def fail(_session):
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(grant.access_token, key, AccountInput(**BODY))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert counts(database, grant.context.user_id) == (0, 0)
    service.create(grant.access_token, key, AccountInput(**BODY))
    assert counts(database, grant.context.user_id) == (1, 1)


def test_session_revoked_before_user_lock_cannot_create_account(context, monkeypatch):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    original = sessions._lock
    ready, release = Event(), Event()

    def pause(*args):
        ready.set()
        assert release.wait(timeout=10)
        return original(*args)

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(sessions, "_lock", pause)
        future = executor.submit(
            AccountService(sessions).create, grant.access_token, uuid4(), AccountInput(**BODY)
        )
        try:
            assert ready.wait(timeout=10)
            monkeypatch.setattr(sessions, "_lock", original)
            sessions.revoke_by_access(grant.access_token)
        finally:
            release.set()
        with pytest.raises(AuthenticationDenied):
            future.result(timeout=20)
    assert counts(database, grant.context.user_id) == (0, 0)
