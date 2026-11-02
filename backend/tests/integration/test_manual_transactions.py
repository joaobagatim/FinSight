"""Manual movement ownership, exact balances, retry identity and migration safety."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import (
    Account,
    Category,
    ImportJob,
    ImportRow,
    Transaction,
    TransactionCreationRequest,
    Transfer,
    User,
)
from app.schemas.transactions import TransactionInput, TransactionUpdateInput
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import (
    TransactionRejected,
    TransactionRemoved,
    TransactionService,
    TransactionStale,
    transaction_etag,
)

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
        financial_columns = [
            column for column in Transaction.__table__.columns if column.name != "deleted_at"
        ]
        before = connection.execute(
            select(*financial_columns).where(Transaction.id == transaction_id)
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
                select(*financial_columns).where(Transaction.id == transaction_id)
            ).one()
            == before
        )
        command.upgrade(config, "head")
        command.check(config)
        assert (
            connection.execute(
                select(*financial_columns).where(Transaction.id == transaction_id)
            ).one()
            == before
        )


def test_posting_http_is_conditional_owned_and_preserves_creation_retry(context, resources):
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        key = uuid4()
        data = body(resources[0], status="planned")
        created = create(client, data, key)
        location = created.headers["location"]
        snapshot = client.get(location)
        etag = snapshot.headers["etag"]
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
            "If-Match": etag,
        }
        assert balance(client, resources[0]).json()["balance"] == "1000.00"
        assert (
            client.post(
                location + "/post",
                json={},
                headers={k: v for k, v in headers.items() if k != "If-Match"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                location + "/post", json={}, headers={"Origin": ORIGIN, "If-Match": etag}
            ).status_code
            == 403
        )
        rejected = client.post(
            location + "/post", json={"amount": "private-marker"}, headers=headers
        )
        assert rejected.status_code == 422 and "private-marker" not in rejected.text
        assert (
            client.post(
                location + "/post", json={}, headers=headers | {"If-Match": '"' + "0" * 64 + '"'}
            ).status_code
            == 412
        )
        foreign_headers = headers | {"X-CSRF-Token": other.cookies.get("__Host-finsight-csrf")}
        foreign = other.post(location + "/post", json={}, headers=foreign_headers)
        missing = other.post(f"{PATH}/{uuid4()}/post", json={}, headers=foreign_headers)
        assert (
            foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()
        )
        response = client.post(location + "/post", json={}, headers=headers)
        assert response.status_code == 200 and response.json() == snapshot.json() | {
            "status": "posted"
        }
        assert response.headers["etag"] != etag
        assert response.headers["cache-control"] == "no-store"
        assert "ETag" in response.headers["access-control-expose-headers"]
        assert balance(client, resources[0]).json()["balance"] == "850.00"
        assert client.post(location + "/post", json={}, headers=headers).json() == response.json()
        assert (
            client.post(
                location + "/post",
                json={},
                headers=headers | {"If-Match": response.headers["etag"]},
            ).status_code
            == 200
        )
        assert create(client, data, key).json() == created.json()
        assert client.get(location).json()["status"] == "posted"
        assert balance(client, resources[0]).json()["balance"] == "850.00"


def test_posting_rechecks_snapshot_active_references_and_manual_origin(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own, status="planned")))
    original = service.get(token, transaction_id)
    with database.sessions.begin() as session:
        session.get(Category, own["expense"]).name = "Renamed before confirmation"
    with pytest.raises(TransactionStale):
        service.post(token, transaction_id, transaction_etag(original))
    current = service.get(token, transaction_id)
    for model, record in ((Account, own["account"]), (Category, own["expense"])):
        with database.sessions.begin() as session:
            session.get(model, record).is_active = False
        with pytest.raises(TransactionRejected):
            service.post(token, transaction_id, transaction_etag(current))
        with database.sessions.begin() as session:
            session.get(model, record).is_active = True
    with database.sessions.begin() as session:
        session.get(Transaction, transaction_id).effective_date = date(2026, 1, 1)
    invalid_date = service.get(token, transaction_id)
    with pytest.raises(TransactionRejected):
        service.post(token, transaction_id, transaction_etag(invalid_date))
    with database.sessions.begin() as session:
        job = ImportJob(
            user_id=own["owner"],
            account_id=own["account"],
            filename="synthetic.csv",
            file_checksum="a" * 64,
        )
        session.add(job)
        session.flush()
        imported = ImportRow(
            user_id=own["owner"], account_id=own["account"], import_job_id=job.id, row_number=1
        )
        session.add(imported)
        session.flush()
        row = session.get(Transaction, transaction_id)
        row.effective_date = date(2026, 1, 2)
        row.import_row_id = imported.id
    imported_snapshot = service.get(token, transaction_id)
    with pytest.raises(TransactionRejected):
        service.post(token, transaction_id, transaction_etag(imported_snapshot))
    assert service.get(token, transaction_id).status == "planned"
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("1000.00")


def test_posting_concurrent_confirmations_book_one_movement_and_allow_archived_replay(
    context, resources
):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own, status="planned")))
    etag = transaction_etag(service.get(token, transaction_id))
    barrier = Barrier(2)

    def confirm():
        barrier.wait(timeout=10)
        return service.post(token, transaction_id, etag)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm) for _ in range(2)]
        posted = [future.result(timeout=20) for future in futures]
    assert all(row.id == transaction_id and row.status == "posted" for row in posted)
    with database.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.user_id == own["owner"])
            )
            == 1
        )
        session.get(Account, own["account"]).is_active = False
        session.get(Category, own["expense"]).is_active = False
    assert service.post(token, transaction_id, etag).status == "posted"
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("850.00")


def test_posting_commit_failure_and_revocation_leave_planned_balance_unchanged(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own, status="planned")))
    snapshot = service.get(token, transaction_id)

    def fail(_session):
        raise SQLAlchemyError("synthetic posting failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.post(token, transaction_id, transaction_etag(snapshot))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, transaction_id) == snapshot
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("1000.00")
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.post(token, transaction_id, transaction_etag(snapshot))
    with database.sessions() as session:
        assert session.get(Transaction, transaction_id).status == "planned"


def test_editing_http_is_owned_conditional_and_preserves_creation_identity(context, resources):
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        own, foreign = resources
        key = uuid4()
        original = body(own, notes="Original note")
        created = create(client, original, key)
        location = created.headers["location"]
        snapshot = client.get(location)
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
            "If-Match": snapshot.headers["etag"],
        }
        patch = {"amount": "200.10", "description": " Updated ", "notes": None}
        assert client.patch(location, json=patch, headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.patch(
                location, json=patch, headers={k: v for k, v in headers.items() if k != "If-Match"}
            ).status_code
            == 422
        )
        invalid = client.patch(location, json={"user_id": "private-marker"}, headers=headers)
        assert invalid.status_code == 422 and "private-marker" not in invalid.text
        assert (
            client.patch(location, json={"status": "planned"}, headers=headers).status_code == 422
        )
        foreign_headers = headers | {"X-CSRF-Token": other.cookies.get("__Host-finsight-csrf")}
        denied = other.patch(location, json=patch, headers=foreign_headers)
        missing = other.patch(f"{PATH}/{uuid4()}", json=patch, headers=foreign_headers)
        assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()
        assert (
            client.patch(
                location, json={"account_id": str(foreign["account"])}, headers=headers
            ).status_code
            == 422
        )
        response = client.patch(location, json=patch, headers=headers)
        assert response.status_code == 200
        assert response.json() == snapshot.json() | {
            "amount": "200.10",
            "description": "Updated",
            "notes": None,
        }
        assert response.headers["etag"] != snapshot.headers["etag"]
        assert response.headers["cache-control"] == "no-store"
        assert balance(client, own).json()["balance"] == "799.90"
        assert client.patch(location, json={"amount": "250.00"}, headers=headers).status_code == 412
        assert create(client, original, key).json() == created.json()
        assert client.get(location).json() == response.json()
        assert create(client, original | {"amount": "200.10"}, key).status_code == 409


def test_editing_moves_exact_balances_and_rechecks_references_dates_and_imports(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own)))
    with database.sessions.begin() as session:
        target = Account(
            user_id=own["owner"],
            name="Target",
            type="savings",
            opening_balance=Decimal("10.00"),
            opening_date=date(2026, 1, 3),
        )
        session.add(target)
        session.flush()
        target_id = target.id
    current = service.get(token, transaction_id)
    for change in (
        {"category_id": str(resources[1]["expense"])},
        {"category_id": str(own["income"])},
        {"account_id": str(target_id)},
        {"effective_date": "2026-01-01"},
    ):
        with pytest.raises(TransactionRejected):
            service.update(
                token, transaction_id, TransactionUpdateInput(**change), transaction_etag(current)
            )
    for model, record in ((Account, own["account"]), (Category, own["expense"])):
        with database.sessions.begin() as session:
            session.get(model, record).is_active = False
        with pytest.raises(TransactionRejected):
            service.update(
                token,
                transaction_id,
                TransactionUpdateInput(description="No mutation"),
                transaction_etag(current),
            )
        with database.sessions.begin() as session:
            session.get(model, record).is_active = True
    moved = service.update(
        token,
        transaction_id,
        TransactionUpdateInput(
            account_id=str(target_id),
            category_id=str(own["income"]),
            type="income",
            effective_date="2026-01-05",
            amount="0.10",
        ),
        transaction_etag(current),
    )
    assert moved.account_name == "Target" and moved.category_name == "Income"
    assert service.balance(token, own["account"], date(2026, 1, 6)).balance == Decimal("1000.00")
    assert service.balance(token, target_id, date(2026, 1, 4)).balance == Decimal("10.00")
    assert service.balance(token, target_id, date(2026, 1, 5)).balance == Decimal("10.10")
    planned_id = service.create(token, uuid4(), TransactionInput(**body(own, status="planned")))
    planned = service.get(token, planned_id)
    changed = service.update(
        token, planned_id, TransactionUpdateInput(amount="300.00"), transaction_etag(planned)
    )
    assert changed.status == "planned"
    assert service.balance(token, own["account"], date(2026, 1, 6)).balance == Decimal("1000.00")
    with pytest.raises(TransactionStale):
        service.post(token, planned_id, transaction_etag(planned))
    with database.sessions.begin() as session:
        job = ImportJob(
            user_id=own["owner"],
            account_id=own["account"],
            filename="synthetic.csv",
            file_checksum="b" * 64,
        )
        session.add(job)
        session.flush()
        imported = ImportRow(
            user_id=own["owner"], account_id=own["account"], import_job_id=job.id, row_number=1
        )
        session.add(imported)
        session.flush()
        session.get(Transaction, planned_id).import_row_id = imported.id
    with pytest.raises(TransactionRejected):
        service.update(
            token,
            planned_id,
            TransactionUpdateInput(notes="Cannot edit import"),
            transaction_etag(changed),
        )
    assert service.get(token, planned_id) == changed


def test_editing_concurrent_writers_do_not_overwrite_and_failures_roll_back(context, resources):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own)))
    etag = transaction_etag(service.get(token, transaction_id))
    barrier = Barrier(2)

    def update(amount):
        barrier.wait(timeout=10)
        try:
            return service.update(
                token, transaction_id, TransactionUpdateInput(amount=amount), etag
            )
        except TransactionStale:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(update, amount) for amount in ("200.00", "250.00")]
        results = [future.result(timeout=20) for future in futures]
    assert sum(row is not None for row in results) == 1
    current = service.get(token, transaction_id)
    assert (
        service.balance(token, own["account"], date(2026, 1, 4)).balance
        == Decimal("1000.00") - current.amount
    )

    def fail(_session):
        raise SQLAlchemyError("synthetic editing failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.update(
                token,
                transaction_id,
                TransactionUpdateInput(amount="300.00"),
                transaction_etag(current),
            )
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, transaction_id) == current
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.update(
            token, transaction_id, TransactionUpdateInput(notes="Denied"), transaction_etag(current)
        )
    with database.sessions() as session:
        assert session.get(Transaction, transaction_id).amount == current.amount


@pytest.fixture
def deletion_resources(context, resources):
    yield resources
    # Synthetic-only shared-fixture cleanup, so its downgrade can remove the test schema.
    # Production has no restore operation; never bypass the downgrade guard there.
    database = context[0]
    assert database.engine.url.database.startswith("finsight_test_")
    with database.sessions.begin() as session:
        session.execute(
            update(Transaction)
            .where(Transaction.user_id.in_([item["owner"] for item in resources]))
            .values(deleted_at=None)
        )


def test_deletion_http_is_conditional_owned_and_never_recreates_on_creation_retry(
    context, deletion_resources
):
    resources = deletion_resources
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        key = uuid4()
        data = body(resources[0])
        created = create(client, data, key)
        location = created.headers["location"]
        snapshot = client.get(location)
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
            "If-Match": snapshot.headers["etag"],
        }
        assert balance(client, resources[0]).json()["balance"] == "850.00"
        assert (
            client.request("DELETE", location, json={}, headers={"Origin": ORIGIN}).status_code
            == 403
        )
        assert (
            client.request(
                "DELETE",
                location,
                json={},
                headers={k: v for k, v in headers.items() if k != "If-Match"},
            ).status_code
            == 422
        )
        rejected = client.request(
            "DELETE", location, json={"user_id": "private-marker"}, headers=headers
        )
        assert rejected.status_code == 422 and "private-marker" not in rejected.text
        assert (
            client.request(
                "DELETE", location, content="{}", headers=headers | {"Content-Type": "text/plain"}
            ).status_code
            == 415
        )
        assert (
            client.request(
                "DELETE",
                location,
                content='"' + "x" * 17000 + '"',
                headers=headers | {"Content-Type": "application/json"},
            ).status_code
            == 413
        )
        foreign_headers = headers | {"X-CSRF-Token": other.cookies.get("__Host-finsight-csrf")}
        denied = other.request("DELETE", location, json={}, headers=foreign_headers)
        missing = other.request("DELETE", f"{PATH}/{uuid4()}", json={}, headers=foreign_headers)
        assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()
        assert (
            client.request(
                "DELETE", location, json={}, headers=headers | {"If-Match": '"' + "0" * 64 + '"'}
            ).status_code
            == 412
        )
        preflight = client.options(
            location,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "Content-Type,X-CSRF-Token,If-Match",
            },
        )
        assert (
            preflight.status_code == 200
            and "DELETE" in preflight.headers["access-control-allow-methods"]
        )
        response = client.request("DELETE", location, json={}, headers=headers)
        assert response.status_code == 204 and response.content == b""
        assert response.headers["cache-control"] == "no-store"
        assert client.request("DELETE", location, json={}, headers=headers).status_code == 204
        assert client.get(location).status_code == 410
        assert other.get(location).status_code == 404
        assert client.get(PATH).json()["items"] == []
        assert balance(client, resources[0]).json()["balance"] == "1000.00"
        assert client.patch(location, json={"amount": "1.00"}, headers=headers).status_code == 410
        assert client.post(location + "/post", json={}, headers=headers).status_code == 410
        assert create(client, data, key).status_code == 410
        assert create(client, data | {"amount": "1.00"}, key).status_code == 409
        with context[0].sessions() as session:
            row = session.get(Transaction, UUID(created.json()["id"]))
            assert row.deleted_at is not None and row.amount == Decimal("150.00")
            assert session.get(TransactionCreationRequest, (resources[0]["owner"], key)) is not None


def test_deletion_races_with_edit_and_post_without_reviving_money(context, deletion_resources):
    _, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = deletion_resources[0]
    for status in ("posted", "planned"):
        transaction_id = service.create(
            token, uuid4(), TransactionInput(**body(own, status=status))
        )
        etag = transaction_etag(service.get(token, transaction_id))
        barrier = Barrier(2)

        def remove(barrier=barrier, transaction_id=transaction_id, etag=etag):
            barrier.wait(timeout=10)
            try:
                service.delete(token, transaction_id, etag)
                return "removed"
            except TransactionStale:
                return "stale"

        def change(barrier=barrier, transaction_id=transaction_id, etag=etag, status=status):
            barrier.wait(timeout=10)
            try:
                if status == "planned":
                    service.post(token, transaction_id, etag)
                else:
                    service.update(
                        token, transaction_id, TransactionUpdateInput(amount="200.00"), etag
                    )
                return "changed"
            except TransactionRemoved:
                return "removed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(remove), executor.submit(change)]
            outcomes = [future.result(timeout=20) for future in futures]
        assert outcomes in (["removed", "removed"], ["stale", "changed"])
        if outcomes[0] == "stale":
            current = service.get(token, transaction_id)
            service.delete(token, transaction_id, transaction_etag(current))
        service.delete(token, transaction_id, etag)
        with pytest.raises(TransactionRemoved):
            service.get(token, transaction_id)
        assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal(
            "1000.00"
        )


def test_deletion_rejects_imports_and_commit_failures_but_allows_archived_manual_history(
    context, deletion_resources
):
    database, sessions, _, emails = context
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    own = deletion_resources[0]
    transaction_id = service.create(token, uuid4(), TransactionInput(**body(own)))
    snapshot = service.get(token, transaction_id)

    def fail(_session):
        raise SQLAlchemyError("synthetic deletion failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.delete(token, transaction_id, transaction_etag(snapshot))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, transaction_id) == snapshot
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("850.00")
    with database.sessions.begin() as session:
        job = ImportJob(
            user_id=own["owner"],
            account_id=own["account"],
            filename="synthetic.csv",
            file_checksum="c" * 64,
        )
        session.add(job)
        session.flush()
        imported = ImportRow(
            user_id=own["owner"], account_id=own["account"], import_job_id=job.id, row_number=1
        )
        session.add(imported)
        session.flush()
        session.get(Transaction, transaction_id).import_row_id = imported.id
    with pytest.raises(TransactionRejected):
        service.delete(token, transaction_id, transaction_etag(snapshot))
    with database.sessions.begin() as session:
        session.get(Transaction, transaction_id).import_row_id = None
        session.get(Account, own["account"]).is_active = False
        session.get(Category, own["expense"]).is_active = False
    service.delete(token, transaction_id, transaction_etag(snapshot))
    assert service.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("1000.00")
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.delete(token, transaction_id, transaction_etag(snapshot))
