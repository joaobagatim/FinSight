"""Category ownership, conflicts and preserved history on disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import Account, Transaction, User
from app.schemas.categories import CategoryInput, CategoryUpdateInput
from app.services.categories import CategoryConflict, CategoryService, CategoryStale, category_etag
from app.services.sessions import SessionService, SessionUnavailable

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic category password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/categories"


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


def headers(client, etag=None):
    result = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or ""}
    if etag is not None:
        result["If-Match"] = etag
    return result


def test_category_http_contract_and_owner_isolation(context):
    stack, make = clients(context)
    with stack:
        owner, other, anonymous = make(context[3][0]), make(context[3][1]), make()
        assert anonymous.get(PATH).status_code == 401
        response = owner.post(
            PATH, json={"name": " Synthetic ", "type": "expense"}, headers=headers(owner)
        )
        assert response.status_code == 201 and response.json()["name"] == "Synthetic"
        location = response.headers["location"]
        assert "user_id" not in response.json()
        assert (
            owner.post(
                PATH, json={"name": "synthetic", "type": "expense"}, headers=headers(owner)
            ).status_code
            == 409
        )
        assert (
            owner.post(
                PATH, json={"name": "Synthetic", "type": "income"}, headers=headers(owner)
            ).status_code
            == 201
        )
        assert (
            other.post(
                PATH, json={"name": "Synthetic", "type": "expense"}, headers=headers(other)
            ).status_code
            == 201
        )
        page = owner.get(PATH, params={"limit": 1}).json()
        assert len(page["items"]) == 1 and page["has_more"]
        assert not owner.get(PATH, params={"limit": 1, "offset": 1}).json()["has_more"]
        assert len(owner.get(PATH, params={"type": "income"}).json()["items"]) == 1
        etag = owner.get(location).headers["etag"]
        changed = owner.patch(
            location, json={"name": "Updated", "color": "#123456"}, headers=headers(owner, etag)
        )
        assert changed.status_code == 200 and changed.headers["etag"] != etag
        assert (
            owner.patch(location, json={"name": "Stale"}, headers=headers(owner, etag)).status_code
            == 412
        )
        foreign = other.patch(location, json={"is_active": False}, headers=headers(other, etag))
        missing = other.patch(
            f"{PATH}/{uuid4()}", json={"is_active": False}, headers=headers(other, etag)
        )
        assert (
            foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
        )
        assert other.get(location).status_code == 404
        assert (
            owner.patch(
                location, json={"type": "income"}, headers=headers(owner, changed.headers["etag"])
            ).status_code
            == 422
        )
        rejected = owner.post(
            PATH,
            json={"name": "X", "type": "expense", "user_id": "private-marker"},
            headers=headers(owner),
        )
        assert rejected.status_code == 422 and "private-marker" not in rejected.text
        assert (
            owner.post(
                PATH, json={"name": "Missing CSRF", "type": "expense"}, headers={"Origin": ORIGIN}
            ).status_code
            == 403
        )
        assert (
            owner.patch(location, json={"name": "No version"}, headers=headers(owner)).status_code
            == 422
        )
        assert (
            owner.patch(
                location,
                content="x" * 17000,
                headers={"Origin": ORIGIN, "Content-Type": "application/json"},
            ).status_code
            == 413
        )
        assert (
            owner.patch(
                location, json={}, headers=[("If-Match", etag), ("If-Match", etag)]
            ).status_code
            == 403
        )
        assert changed.headers["cache-control"] == "no-store"
        assert "ETag" in changed.headers["access-control-expose-headers"]
        assert (
            owner.options(
                location,
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "PATCH",
                    "Access-Control-Request-Headers": "if-match,x-csrf-token",
                },
            ).status_code
            == 200
        )


def test_category_history_conflicts_and_atomic_rollback(context):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    service = CategoryService(sessions)
    category = service.create(grant.access_token, CategoryInput(name="History", type="income"))
    service.create(grant.access_token, CategoryInput(name="Taken", type="income"))
    with database.sessions.begin() as session:
        account = Account(
            user_id=grant.context.user_id,
            name="Synthetic",
            type="checking",
            opening_balance=Decimal("0.00"),
            opening_date=date(2026, 1, 1),
        )
        session.add(account)
        session.flush()
        transaction = Transaction(
            user_id=grant.context.user_id,
            account_id=account.id,
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
        before = {
            column.name: getattr(transaction, column.name)
            for column in Transaction.__table__.columns
        }
    with pytest.raises(CategoryConflict):
        service.update(
            grant.access_token,
            category.id,
            CategoryUpdateInput(name="taken"),
            category_etag(category),
        )
    assert service.get(grant.access_token, category.id) == category

    def fail(_session):
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.update(
                grant.access_token,
                category.id,
                CategoryUpdateInput(is_active=False),
                category_etag(category),
            )
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(grant.access_token, category.id) == category
    disabled = service.update(
        grant.access_token,
        category.id,
        CategoryUpdateInput(is_active=False),
        category_etag(category),
    )
    assert not disabled.is_active
    with database.sessions() as session:
        row = session.get(Transaction, transaction_id)
        assert row is not None
        assert {
            column.name: getattr(row, column.name) for column in Transaction.__table__.columns
        } == before
    assert service.update(
        grant.access_token,
        category.id,
        CategoryUpdateInput(is_active=True),
        category_etag(disabled),
    ).is_active


def test_concurrent_category_updates_reject_stale_data(context):
    _, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = CategoryService(sessions)
    category = service.create(token, CategoryInput(name="Original", type="expense"))
    barrier = Barrier(2)

    def update(name):
        barrier.wait(timeout=10)
        try:
            service.update(
                token, category.id, CategoryUpdateInput(name=name), category_etag(category)
            )
            return "saved"
        except CategoryStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, name) for name in ("First", "Second")]
        assert sorted(f.result(timeout=20) for f in futures) == ["saved", "stale"]
