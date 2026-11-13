"""Goal ownership, persistent retries and migration safety on disposable PostgreSQL."""

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
from alembic.migration import MigrationContext
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, insert, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import (
    Account,
    FinancialGoal,
    GoalAllocation,
    GoalCreationRequest,
    Transaction,
    Transfer,
    User,
)
from app.schemas.goals import GoalInput, GoalUpdateInput
from app.services.goals import GoalService, GoalStale, goal_etag
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import TransactionService

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic account password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/goals"
BODY = {
    "name": "Synthetic goal",
    "target_amount": "1500.10",
    "description": "Synthetic travel plan",
    "target_date": "2027-12-31",
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
                assert database.engine.url.database.startswith("finsight_test_")
                connection.execute(delete(GoalCreationRequest))
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


def create(client, key, data=BODY):
    return client.post(
        PATH,
        json=data,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or "",
            "Idempotency-Key": str(key),
        },
    )


def patch(client, path, etag, data):
    return client.patch(
        path,
        json=data,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or "",
            "If-Match": etag,
        },
    )


def test_goals_http_is_owned_conditional_and_creation_retry_never_restores_old_metadata(context):
    database, sessions, _, emails = context
    stack, make = clients(context)
    with stack:
        owner, other, anonymous = make(emails[0]), make(emails[1]), make()
        key = uuid4()
        assert anonymous.get(PATH).status_code == 401
        assert owner.post(PATH, json=BODY).status_code == 403
        created = create(owner, key)
        assert created.status_code == 201
        path = created.headers["location"]
        before = owner.get(path)
        assert before.status_code == 200 and before.json()["status"] == "active"
        assert before.json()["target_amount"] == "1500.10" and "user_id" not in before.json()
        assert before.headers["cache-control"] == "no-store"
        assert other.get(path).status_code == 404
        assert patch(other, path, before.headers["etag"], {"name": "Denied"}).status_code == 404
        assert create(owner, key).json() == created.json()
        assert create(owner, key, BODY | {"target_amount": "1.00"}).status_code == 409
        assert create(other, key).status_code == 201
        changed = patch(
            owner,
            path,
            before.headers["etag"],
            {
                "name": "Updated goal",
                "target_amount": "2000.00",
                "description": None,
                "target_date": None,
                "status": "completed",
            },
        )
        assert changed.status_code == 200 and changed.json()["status"] == "completed"
        assert changed.headers["etag"] != before.headers["etag"]
        assert patch(owner, path, before.headers["etag"], {"name": "Stale"}).status_code == 412
        assert create(owner, key).json() == created.json()
        assert owner.get(path).json() == changed.json()
        assert owner.get(PATH, params={"status": "active"}).json()["items"] == []
        assert len(owner.get(PATH, params={"status": "completed", "limit": 1}).json()["items"]) == 1
        assert (
            patch(owner, path, changed.headers["etag"], {"status": "cancelled"}).status_code == 200
        )
        latest = owner.get(path)
        assert patch(owner, path, latest.headers["etag"], {"status": "active"}).status_code == 200
        with database.sessions() as session:
            assert session.scalar(select(func.count()).select_from(GoalAllocation)) == 0
            assert session.scalar(select(func.count()).select_from(Transaction)) == 0
            assert session.scalar(select(func.count()).select_from(Transfer)) == 0


def test_goals_concurrent_retries_edits_rollback_revocation_and_no_balance_mutation(context):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    token = grant.access_token
    service = GoalService(sessions)
    key = uuid4()
    data = GoalInput(**BODY)
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=10)
        return service.create(token, key, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save), executor.submit(save)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1]
    before = service.get(token, ids[0])
    etag = goal_etag(before)
    barrier = Barrier(2)

    def edit(name):
        barrier.wait(timeout=10)
        try:
            service.update(token, ids[0], GoalUpdateInput(name=name), etag)
            return "saved"
        except GoalStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(edit, name) for name in ("First", "Second")]
        assert sorted(future.result(timeout=20) for future in futures) == ["saved", "stale"]
    current = service.get(token, ids[0])

    def fail(_session):
        raise SQLAlchemyError("synthetic goal failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(token, uuid4(), data)
        with pytest.raises(SessionUnavailable):
            service.update(token, ids[0], GoalUpdateInput(status="cancelled"), goal_etag(current))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, ids[0]) == current
    with database.sessions.begin() as session:
        account = Account(
            user_id=grant.context.user_id,
            name="Synthetic balance",
            type="checking",
            opening_balance=Decimal("1234.56"),
            opening_date=date(2026, 1, 1),
        )
        session.add(account)
        session.flush()
        account_id = account.id
    balances = TransactionService(sessions)
    assert balances.balance(token, account_id, date(2026, 1, 2)).balance == Decimal("1234.56")
    service.update(token, ids[0], GoalUpdateInput(status="completed"), goal_etag(current))
    assert balances.balance(token, account_id, date(2026, 1, 2)).balance == Decimal("1234.56")
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.create(token, uuid4(), data)


def test_goal_request_migration_preserves_existing_goal_and_cannot_discard_retained_identity(
    context,
):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = GoalService(sessions)
    identity = service.create(token, uuid4(), GoalInput(**BODY))
    before = service.get(token, identity)
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        other_owner = connection.scalar(select(User.id).where(User.email == emails[1]))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(GoalCreationRequest).values(
                    user_id=other_owner,
                    idempotency_key=uuid4(),
                    request_hash="a" * 64,
                    goal_id=identity,
                )
            )
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0012_transfer_deletion")
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == "0013_goal_creation_requests"
        )
        assert (
            connection.execute(
                select(FinancialGoal.target_amount).where(FinancialGoal.id == identity)
            ).scalar_one()
            == before.target_amount
        )
        command.check(config)
        # Disposable fixture only: remove its request keys to exercise the safe downgrade path.
        connection.execute(delete(GoalCreationRequest))
        command.downgrade(config, "0012_transfer_deletion")
        assert (
            connection.execute(
                select(FinancialGoal.name).where(FinancialGoal.id == identity)
            ).scalar_one()
            == before.name
        )
        command.upgrade(config, "head")
        command.check(config)
    assert service.get(token, identity) == before
