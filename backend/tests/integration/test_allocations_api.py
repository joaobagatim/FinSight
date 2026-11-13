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

from app.api.allocations import allocation_service
from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import (
    Account,
    AllocationCreationRequest,
    Category,
    FinancialGoal,
    GoalAllocation,
    GoalCreationRequest,
    Transaction,
    TransactionCreationRequest,
    User,
)
from app.schemas.allocations import AllocationInput
from app.schemas.goals import GoalInput
from app.schemas.transactions import TransactionInput
from app.services.allocations import AllocationRejected, AllocationService, context_etag
from app.services.goals import GoalService, GoalStale
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import TransactionService

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic account password"
ORIGIN = "https://app.example.test"
DAY = date(2026, 1, 2)
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
                connection.execute(delete(AllocationCreationRequest))
                connection.execute(delete(GoalCreationRequest))
                connection.execute(delete(TransactionCreationRequest))
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
        app.dependency_overrides[allocation_service] = lambda: AllocationService(
            context[1], today=lambda: DAY
        )
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


def seed(context):
    database, sessions, _, emails = context
    grant = sessions.login(emails[0], PASSWORD)
    owner = grant.context.user_id
    with database.sessions.begin() as session:
        account = Account(
            user_id=owner,
            name="Synthetic reserve account",
            type="checking",
            opening_balance=Decimal("1000.00"),
            opening_date=date(2026, 1, 1),
        )
        category = Category(user_id=owner, name="Synthetic expenses", type="expense")
        session.add_all([account, category])
        session.flush()
        account_id, category_id = account.id, category.id
    goal = GoalService(sessions).create(
        grant.access_token, uuid4(), GoalInput(**(BODY | {"target_amount": "500.00"}))
    )
    return grant.access_token, goal, account_id, category_id


def payload(account_id, amount="800.00", kind="reserve"):
    return {
        "account_id": str(account_id),
        "amount": amount,
        "kind": kind,
        "allocation_date": DAY.isoformat(),
    }


def test_allocation_http_ownership_retry_dates_and_pair_limits(context):
    token, goal, account, _ = seed(context)
    database, sessions, _, emails = context
    path = f"{PATH}/{goal}/allocations"
    stack, make = clients(context)
    with stack:
        owner, other, anonymous = make(emails[0]), make(emails[1]), make()
        snapshot = owner.get(
            f"{PATH}/{goal}/allocation-context", params={"account_id": str(account)}
        )
        assert snapshot.status_code == 200
        assert snapshot.headers["cache-control"] == "no-store"
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": owner.cookies.get("__Host-finsight-csrf"),
            "Idempotency-Key": str(uuid4()),
            "If-Match": snapshot.headers["etag"],
        }
        assert anonymous.get(path).status_code == 401
        assert owner.post(path, json=payload(account)).status_code == 403
        assert other.get(path).status_code == 404
        assert other.get(f"/api/v1/accounts/{account}/availability").status_code == 404
        assert (
            owner.post(
                path, json=payload(account) | {"allocation_date": "2026-01-01"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            owner.post(
                path,
                json=payload(account),
                headers={k: v for k, v in headers.items() if k != "If-Match"},
            ).status_code
            == 422
        )
        created = owner.post(path, json=payload(account), headers=headers)
        assert created.status_code == 201
        assert owner.post(path, json=payload(account), headers=headers).json() == created.json()
        assert owner.post(path, json=payload(account, "1.00"), headers=headers).status_code == 409
        stale = headers | {"Idempotency-Key": str(uuid4())}
        assert owner.post(path, json=payload(account, "1.00"), headers=stale).status_code == 412
        data = owner.get(f"{PATH}/{goal}/funding").json()
        assert (
            data["reserved_amount"],
            data["progress_percent"],
            data["excess_amount"],
            data["remaining_amount"],
        ) == ("800.00", "160.00", "300.00", "0.00")
        availability = owner.get(f"/api/v1/accounts/{account}/availability").json()
        assert (
            availability["bank_balance"],
            availability["reserved_amount"],
            availability["free_balance"],
        ) == ("1000.00", "800.00", "200.00")
        current = owner.get(
            f"{PATH}/{goal}/allocation-context", params={"account_id": str(account)}
        )
        headers.update({"Idempotency-Key": str(uuid4()), "If-Match": current.headers["etag"]})
        assert (
            owner.post(
                path, json=payload(account, "800.01", "withdraw"), headers=headers
            ).status_code
            == 422
        )
        withdrawn = owner.post(path, json=payload(account, "200.00", "withdraw"), headers=headers)
        assert withdrawn.status_code == 201
        ledger = owner.get(path, params={"limit": 1}).json()
        assert ledger["has_more"] and len(ledger["items"]) == 1
        assert len(owner.get(path).json()["items"]) == 2
        assert (
            owner.get(f"/api/v1/accounts/{account}/availability").json()["bank_balance"]
            == "1000.00"
        )
        assert other.get("/api/v1/reservations/alerts").json()["items"] == []
    assert AllocationService(sessions, today=lambda: DAY).funding(
        token, goal
    ).reserved_amount == Decimal("600.00")


def test_concurrent_reserves_withdrawals_rollback_and_next_day_replay(context):
    token, goal, account, _ = seed(context)
    database, sessions, _, _ = context
    service = AllocationService(sessions, today=lambda: DAY)
    data = AllocationInput(**payload(account, "700.00"))
    etag = context_etag(service.context(token, goal, account))
    barrier = Barrier(2)

    def save(kind, value, version):
        barrier.wait(timeout=10)
        try:
            return service.create(
                token, goal, uuid4(), AllocationInput(**payload(account, value, kind)), version
            )
        except GoalStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(save, "reserve", "700.00", etag) for _ in range(2)]
        assert sum(result.result(timeout=20) == "stale" for result in results) == 1
    etag = context_etag(service.context(token, goal, account))
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(save, "withdraw", "400.00", etag) for _ in range(2)]
        assert sum(result.result(timeout=20) == "stale" for result in results) == 1
    assert service.funding(token, goal).reserved_amount == Decimal("300.00")
    before = service.context(token, goal, account)
    key = uuid4()

    def fail(_session):
        raise SQLAlchemyError("synthetic allocation rollback")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(token, goal, key, data, context_etag(before))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.context(token, goal, account) == before
    with database.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(AllocationCreationRequest)
                .where(AllocationCreationRequest.idempotency_key == key)
            )
            == 0
        )
    key = uuid4()
    created = service.create(token, goal, key, data, context_etag(before))
    with database.sessions.begin() as session:
        session.get(Account, account).is_active = False
        session.get(FinancialGoal, goal).status = "cancelled"
    assert (
        AllocationService(sessions, today=lambda: date(2026, 1, 3)).create(
            token, goal, key, data, '"' + "0" * 64 + '"'
        )
        == created
    )
    current = service.context(token, goal, account)
    with pytest.raises(AllocationRejected):
        service.create(
            token, goal, uuid4(), AllocationInput(**payload(account, "1.00")), context_etag(current)
        )
    service.create(
        token,
        goal,
        uuid4(),
        AllocationInput(**payload(account, "1000.00", "withdraw")),
        context_etag(current),
    )
    assert service.funding(token, goal).reserved_amount == 0
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.create(token, goal, key, data, context_etag(current))


def test_spending_is_allowed_and_alerts_are_derived_without_releasing_reserves(context):
    token, goal, account, category = seed(context)
    database, sessions, _, _ = context
    service = AllocationService(sessions, today=lambda: DAY)
    service.create(
        token,
        goal,
        uuid4(),
        AllocationInput(**payload(account)),
        context_etag(service.context(token, goal, account)),
    )
    transactions = TransactionService(sessions)
    identity = transactions.create(
        token,
        uuid4(),
        TransactionInput(
            account_id=str(account),
            category_id=str(category),
            description="Synthetic expense",
            amount="500.00",
            type="expense",
            status="posted",
            effective_date=DAY.isoformat(),
        ),
    )
    result = service.availability(token, account)
    assert (
        result.bank_balance,
        result.reserved_amount,
        result.free_balance,
        result.uncovered_reserved,
    ) == (Decimal("500.00"), Decimal("800.00"), Decimal("-300.00"), Decimal("300.00"))
    assert service.alerts(token).account_count == 1
    with database.sessions.begin() as session:
        # Synthetic correction exercises shared reads; deletion has its own tests.
        session.get(Transaction, identity).amount = Decimal("100.00")
    assert service.alerts(token).account_count == 0
    assert service.funding(token, goal).reserved_amount == Decimal("800.00")


def test_allocation_request_migration_preserves_ledger_and_protects_retry_memory(context):
    token, goal, account, _ = seed(context)
    database, sessions, _, emails = context
    service = AllocationService(sessions, today=lambda: DAY)
    identity = service.create(
        token,
        goal,
        uuid4(),
        AllocationInput(**payload(account)),
        context_etag(service.context(token, goal, account)),
    )
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        other = connection.scalar(select(User.id).where(User.email == emails[1]))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(AllocationCreationRequest).values(
                    user_id=other,
                    idempotency_key=uuid4(),
                    request_hash="a" * 64,
                    allocation_id=identity,
                )
            )
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0013_goal_creation_requests")
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == "0014_allocation_requests"
        )
        command.check(config)
        connection.execute(delete(AllocationCreationRequest))
        command.downgrade(config, "0013_goal_creation_requests")
        assert connection.scalar(
            select(GoalAllocation.amount).where(GoalAllocation.id == identity)
        ) == Decimal("800.00")
        command.upgrade(config, "head")
        command.check(config)
    assert service.funding(token, goal).reserved_amount == Decimal("800.00")
