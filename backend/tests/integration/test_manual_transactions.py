"""Manual movement ownership, exact balances, retry identity and migration safety."""

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
from sqlalchemy import event, func, insert, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import Account, Category, Transaction, TransactionCreationRequest, Transfer, User
from app.schemas.transactions import TransactionInput
from app.services.sessions import SessionService, SessionUnavailable
from app.services.transactions import TransactionService

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic transaction password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/transactions"


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


@pytest.fixture
def resources(context):
    database, _, _, emails = context
    result = []
    with database.sessions.begin() as session:
        for email in emails:
            owner = session.scalar(select(User.id).where(User.email == email))
            account = Account(
                user_id=owner,
                name="Synthetic account",
                type="checking",
                opening_balance=Decimal("1000.00"),
                opening_date=date(2026, 1, 1),
            )
            expense = Category(user_id=owner, name="Expense", type="expense")
            income = Category(user_id=owner, name="Income", type="income")
            session.add_all([account, expense, income])
            session.flush()
            result.append(
                {"owner": owner, "account": account.id, "expense": expense.id, "income": income.id}
            )
    return result


def body(resource, **changes):
    return {
        "account_id": str(resource["account"]),
        "category_id": str(resource["expense"]),
        "description": "Synthetic movement",
        "amount": "150.00",
        "type": "expense",
        "status": "posted",
        "effective_date": "2026-01-02",
    } | changes


def create(client, data, key=None):
    return client.post(
        PATH,
        json=data,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or "",
            "Idempotency-Key": str(key or uuid4()),
        },
    )


def balance(client, resource, day="2026-01-04"):
    return client.get(f"/api/v1/accounts/{resource['account']}/balance", params={"as_of": day})


def test_posted_expense_changes_exact_balance_but_planned_does_not(context, resources):
    stack, make = clients(context)
    with stack:
        client = make(context[3][0])
        resource = resources[0]
        assert balance(client, resource).json()["balance"] == "1000.00"
        response = create(client, body(resource))
        assert response.status_code == 201 and set(response.json()) == {"id"}
        assert balance(client, resource).json()["balance"] == "850.00"
        assert create(client, body(resource, status="planned", amount="200.00")).status_code == 201
        assert balance(client, resource).json()["balance"] == "850.00"
        for _ in range(2):
            assert (
                create(
                    client,
                    body(
                        resource, type="income", category_id=str(resource["income"]), amount="0.10"
                    ),
                ).status_code
                == 201
            )
        assert balance(client, resource).json()["balance"] == "850.20"
        assert (
            create(
                client,
                body(
                    resource,
                    type="income",
                    category_id=str(resource["income"]),
                    amount="10.00",
                    effective_date="2026-01-05",
                ),
            ).status_code
            == 201
        )
        assert balance(client, resource).json()["balance"] == "850.20"
        assert balance(client, resource, "2026-01-05").json()["balance"] == "860.20"
        assert balance(client, resource, "2026-01-01").json()["balance"] == "1000.00"
        assert balance(client, resource, "2025-12-31").status_code == 422
        detail = client.get(response.headers["location"])
        assert detail.json()["account_name"] == "Synthetic account"
        assert detail.json()["category_name"] == "Expense"
        assert detail.json()["amount"] == "150.00" and "user_id" not in detail.json()
        assert detail.headers["cache-control"] == "no-store"
        page = client.get(PATH, params={"limit": 1}).json()
        assert len(page["items"]) == 1 and page["has_more"]
        filtered = client.get(
            PATH,
            params={"status": "planned", "account_id": str(resource["account"]), "type": "expense"},
        ).json()
        assert len(filtered["items"]) == 1 and not filtered["has_more"]
        assert (
            client.get(
                PATH, params={"date_from": "2026-01-05", "date_to": "2026-01-04"}
            ).status_code
            == 422
        )
        assert (
            client.get(
                PATH, params={"date_from": "2026-01-05", "category_id": str(resource["income"])}
            ).json()["items"][0]["amount"]
            == "10.00"
        )


def test_transaction_references_security_and_date_boundaries(context, resources):
    stack, make = clients(context)
    with stack:
        client, other, anonymous = make(context[3][0]), make(context[3][1]), make()
        own, foreign = resources
        assert anonymous.get(PATH).status_code == 401
        for change in (
            {"account_id": str(foreign["account"])},
            {"category_id": str(foreign["expense"])},
            {"category_id": str(own["income"])},
            {"effective_date": "2026-01-01"},
            {"effective_date": "2025-12-31", "status": "planned"},
        ):
            assert create(client, body(own, **change)).status_code == 422
        rejected = create(client, body(own, user_id="private-owner-marker"))
        assert rejected.status_code == 422 and "private-owner-marker" not in rejected.text
        assert create(client, body(own, amount=0.1)).status_code == 422
        assert create(client, body(own, import_row_id=str(uuid4()))).status_code == 422
        assert (
            client.post(
                PATH, json=body(own), headers={"Origin": ORIGIN, "Idempotency-Key": str(uuid4())}
            ).status_code
            == 403
        )
        assert (
            client.post(
                PATH,
                json=body(own),
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                PATH, content="x" * 17000, headers={"Content-Type": "application/json"}
            ).status_code
            == 413
        )
        assert (
            client.post(
                PATH,
                json={},
                headers=[("Idempotency-Key", str(uuid4())), ("Idempotency-Key", str(uuid4()))],
            ).status_code
            == 403
        )
        created = create(client, body(own))
        location = created.headers["location"]
        missing = other.get(f"{PATH}/{uuid4()}")
        assert missing.status_code == other.get(location).status_code == 404
        assert missing.json() == other.get(location).json()
        assert balance(other, own).status_code == 404
        assert other.get(PATH, params={"account_id": str(own["account"])}).json()["items"] == []
        assert (
            client.options(
                PATH,
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "idempotency-key,x-csrf-token",
                },
            ).status_code
            == 200
        )


def test_retry_identity_survives_archiving_and_is_scoped_to_owner(context, resources):
    database = context[0]
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        own, foreign = resources
        key = uuid4()
        first = create(client, body(own, amount="150.0"), key)
        assert first.status_code == 201
        assert create(client, body(own), key).json() == first.json()
        assert create(client, body(own, amount="151.00"), key).status_code == 409
        assert create(other, body(foreign), key).json() != first.json()
        with database.sessions.begin() as session:
            session.get(Account, own["account"]).is_active = False
            session.get(Category, own["expense"]).is_active = False
        assert create(client, body(own), key).json() == first.json()
        assert create(client, body(own)).status_code == 422
        assert balance(client, own).json()["balance"] == "850.00"


def test_concurrent_retries_create_one_financial_movement(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service, key, barrier = TransactionService(sessions), uuid4(), Barrier(2)
    data = TransactionInput(**body(resources[0]))

    def run():
        barrier.wait(timeout=10)
        return service.create(token, key, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run) for _ in range(2)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1]
    with database.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == resources[0]["owner"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(TransactionCreationRequest)
                .where(TransactionCreationRequest.user_id == resources[0]["owner"])
            )
            == 1
        )
    assert service.balance(token, resources[0]["account"], date(2026, 1, 3)).balance == Decimal(
        "850.00"
    )


def test_failed_commit_rolls_back_transaction_and_creation_key(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service, key = TransactionService(sessions), uuid4()
    data = TransactionInput(**body(resources[0]))

    def fail(_session):
        raise SQLAlchemyError("synthetic commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(token, key, data)
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    with database.sessions() as session:
        assert session.get(TransactionCreationRequest, (resources[0]["owner"], key)) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == resources[0]["owner"])
            )
            == 0
        )
    service.create(token, key, data)
    assert service.balance(token, resources[0]["account"], date(2026, 1, 3)).balance == Decimal(
        "850.00"
    )


def test_transfer_net_and_archived_history_are_counted_without_multiplication(context, resources):
    database, sessions, _, emails = context
    own = resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    service.create(token, uuid4(), TransactionInput(**body(own)))
    with database.sessions.begin() as session:
        second = Account(
            user_id=own["owner"],
            name="Other synthetic",
            type="cash",
            opening_balance=Decimal("0.00"),
            opening_date=date(2026, 1, 1),
        )
        session.add(second)
        session.flush()
        session.add_all(
            [
                Transfer(
                    user_id=own["owner"],
                    from_account_id=own["account"],
                    to_account_id=second.id,
                    amount=Decimal("50.00"),
                    status="posted",
                    effective_date=date(2026, 1, 2),
                ),
                Transfer(
                    user_id=own["owner"],
                    from_account_id=second.id,
                    to_account_id=own["account"],
                    amount=Decimal("7.00"),
                    status="posted",
                    effective_date=date(2026, 1, 3),
                ),
                Transfer(
                    user_id=own["owner"],
                    from_account_id=own["account"],
                    to_account_id=second.id,
                    amount=Decimal("9.00"),
                    status="planned",
                    effective_date=date(2026, 1, 3),
                ),
            ]
        )
        session.get(Account, own["account"]).is_active = False
        session.get(Category, own["expense"]).is_active = False
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("807.00")


def test_request_constraints_and_downgrade_preserve_financial_rows(context, resources):
    database, sessions, _, emails = context
    own = resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    transaction_id = TransactionService(sessions).create(
        token, uuid4(), TransactionInput(**body(own))
    )
    with database.engine.begin() as connection:
        before = connection.execute(
            select(Transaction.__table__).where(Transaction.id == transaction_id)
        ).one()
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(TransactionCreationRequest).values(
                    user_id=resources[1]["owner"],
                    idempotency_key=uuid4(),
                    request_hash="a" * 64,
                    transaction_id=transaction_id,
                )
            )
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.downgrade(config, "0008_account_creation_requests")
        assert "transaction_creation_requests" not in inspect(connection).get_table_names()
        assert (
            connection.execute(
                select(Transaction.__table__).where(Transaction.id == transaction_id)
            ).one()
            == before
        )
        command.upgrade(config, "head")
        command.check(config)
        assert (
            connection.execute(
                select(Transaction.__table__).where(Transaction.id == transaction_id)
            ).one()
            == before
        )
