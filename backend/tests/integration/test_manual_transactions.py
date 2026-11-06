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
from alembic.util.exc import CommandError
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, insert, inspect, select, update
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
    TransferCreationRequest,
    User,
)
from app.schemas.transactions import TransactionInput, TransactionUpdateInput
from app.schemas.transfers import TransferInput
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import (
    TransactionRejected,
    TransactionRemoved,
    TransactionService,
    TransactionStale,
    transaction_etag,
)
from app.services.transfers import TransferRejected, TransferService, TransferStale, transfer_etag

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


def test_description_search_combines_filters_pagination_and_literal_text(
    context, resources, deletion_resources
):
    database, sessions, _, emails = context
    own, foreign = resources
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    ids = []
    for day, status in (("2026-01-02", "posted"), ("2026-01-03", "planned")):
        ids.append(
            service.create(
                token,
                uuid4(),
                TransactionInput(
                    **body(own, description="Compra 100%_/ Café", effective_date=day, status=status)
                ),
            )
        )
    income = service.create(
        token,
        uuid4(),
        TransactionInput(
            **body(
                own,
                description="Compra 100%_/ Café",
                type="income",
                category_id=str(own["income"]),
                effective_date="2026-01-04",
            )
        ),
    )
    service.create(token, uuid4(), TransactionInput(**body(own, description="Compra 100xx/ Café")))
    removed = service.create(
        token, uuid4(), TransactionInput(**body(own, description="Compra 100%_/ Café"))
    )
    service.delete(token, removed, transaction_etag(service.get(token, removed)))
    other_token = sessions.login(emails[1], PASSWORD).access_token
    service.create(
        other_token, uuid4(), TransactionInput(**body(foreign, description="Compra 100%_/ Café"))
    )
    stack, make = clients(context)
    with stack:
        client, anonymous = make(emails[0]), make()
        assert anonymous.get(PATH, params={"q": "Café"}).status_code == 401
        query = {"q": "  100%_/ cAFÉ  ", "limit": 1}
        first = client.get(PATH, params=query)
        assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
        assert [item["id"] for item in first.json()["items"]] == [str(income)]
        assert first.json()["has_more"]
        second = client.get(PATH, params=query | {"offset": 1})
        assert [item["id"] for item in second.json()["items"]] == [str(ids[1])]
        filtered = client.get(
            PATH,
            params={
                "q": "100%_/",
                "account_id": str(own["account"]),
                "category_id": str(own["expense"]),
                "type": "expense",
                "status": "planned",
                "date_from": "2026-01-03",
                "date_to": "2026-01-03",
            },
        )
        assert filtered.status_code == 200 and [
            item["id"] for item in filtered.json()["items"]
        ] == [str(ids[1])]
        assert not filtered.json()["has_more"]
        for value in ("cafe", "' OR 1=1 --", "not present"):
            assert client.get(PATH, params={"q": value}).json()["items"] == []
        assert (
            client.get(PATH, params={"q": "100%_/", "account_id": str(foreign["account"])}).json()[
                "items"
            ]
            == []
        )
        for value in ("", "   ", "x" * 256, "bad\x00text", "bad\ntext"):
            assert client.get(PATH, params={"q": value}).status_code == 422
        with database.sessions.begin() as session:
            session.get(Account, own["account"]).is_active = False
            session.get(Category, own["expense"]).is_active = False
        assert client.get(PATH, params={"q": "100%_/", "category_id": str(own["expense"])}).json()[
            "items"
        ]


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


@pytest.fixture
def transfer_resources(context, resources):
    database = context[0]
    with database.sessions.begin() as session:
        for item in resources:
            target = Account(
                user_id=item["owner"],
                name="Destination",
                type="savings",
                opening_balance=Decimal("1000.00"),
                opening_date=date(2026, 1, 3),
            )
            session.add(target)
            session.flush()
            item["target"] = target.id
    yield resources
    assert database.engine.url.database.startswith("finsight_test_")
    # Remove only this test's synthetic request records before the shared schema teardown.
    with database.sessions.begin() as session:
        session.execute(
            delete(TransferCreationRequest).where(
                TransferCreationRequest.user_id.in_([item["owner"] for item in resources])
            )
        )


def transfer_body(resource, **changes):
    return {
        "from_account_id": str(resource["account"]),
        "to_account_id": str(resource["target"]),
        "amount": "500.00",
        "status": "posted",
        "effective_date": "2026-01-04",
    } | changes


def test_transfers_http_authorizes_both_accounts_and_preserves_exact_total(
    context, transfer_resources
):
    own, foreign = transfer_resources
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        path = "/api/v1/transfers"
        key = uuid4()
        data = transfer_body(own)
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
            "Idempotency-Key": str(key),
        }
        assert client.post(path, json=data, headers={"Origin": ORIGIN}).status_code == 403
        assert (
            client.post(
                path,
                json=data,
                headers={k: v for k, v in headers.items() if k != "Idempotency-Key"},
            ).status_code
            == 422
        )
        for change in (
            {"to_account_id": str(own["account"])},
            {"to_account_id": str(foreign["target"])},
            {"from_account_id": str(foreign["account"])},
            {"effective_date": "2026-01-03"},
        ):
            assert client.post(path, json=data | change, headers=headers).status_code == 422
        invalid = client.post(path, json=data | {"user_id": "private-marker"}, headers=headers)
        assert invalid.status_code == 422 and "private-marker" not in invalid.text
        response = client.post(path, json=data, headers=headers)
        assert response.status_code == 201 and set(response.json()) == {"id"}
        location = response.headers["location"]
        assert client.post(path, json=data, headers=headers).json() == response.json()
        assert (
            client.post(path, json=data | {"amount": "500.01"}, headers=headers).status_code == 409
        )
        detail = client.get(location)
        assert (
            detail.json()["amount"] == "500.00"
            and detail.json()["to_account_name"] == "Destination"
        )
        assert detail.headers["cache-control"] == "no-store"
        assert (
            other.get(location).status_code
            == other.get(path + "/" + str(uuid4())).status_code
            == 404
        )
        assert other.get(path).json()["items"] == []
        first = balance(client, own).json()["balance"]
        target = client.get(
            f"/api/v1/accounts/{own['target']}/balance", params={"as_of": "2026-01-04"}
        ).json()["balance"]
        assert first == "500.00" and target == "1500.00"
        assert Decimal(first) + Decimal(target) == Decimal("2000.00")
        assert balance(client, own, "2026-01-03").json()["balance"] == "1000.00"
        assert client.get(PATH).json()["items"] == []
        assert (
            client.post(
                path,
                json=data | {"status": "planned", "amount": "200.00"},
                headers=headers | {"Idempotency-Key": str(uuid4())},
            ).status_code
            == 201
        )
        assert balance(client, own).json()["balance"] == "500.00"
        page = client.get(path, params={"limit": 1, "account_id": str(own["target"])}).json()
        assert len(page["items"]) == 1 and page["has_more"]
        assert len(client.get(path, params={"status": "planned"}).json()["items"]) == 1
        assert (
            client.get(
                path, params={"date_from": "2026-02-01", "date_to": "2026-01-01"}
            ).status_code
            == 422
        )
        with context[0].sessions.begin() as session:
            session.get(Account, own["target"]).is_active = False
        assert client.post(path, json=data, headers=headers).json() == response.json()
        assert (
            client.post(
                path, json=data, headers=headers | {"Idempotency-Key": str(uuid4())}
            ).status_code
            == 422
        )


def test_transfers_concurrent_retries_book_once_and_migration_retains_identity(
    context, transfer_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransferService(sessions)
    key = uuid4()
    data = TransferInput(**transfer_body(own))
    barrier = Barrier(2)

    def create_once():
        barrier.wait(timeout=10)
        return service.create(token, key, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_once) for _ in range(2)]
        ids = [future.result(timeout=20) for future in futures]
    assert ids[0] == ids[1]
    with database.sessions() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.user_id == own["owner"])
            )
            == 1
        )
        assert session.get(TransferCreationRequest, (own["owner"], key)).transfer_id == ids[0]
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(TransferCreationRequest).values(
                    user_id=transfer_resources[1]["owner"],
                    idempotency_key=uuid4(),
                    request_hash="a" * 64,
                    transfer_id=ids[0],
                )
            )
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0010_transaction_deletion")
        command.check(config)
    assert service.create(token, key, data) == ids[0]


def test_transfer_commit_failure_and_revocation_leave_both_accounts_unchanged(
    context, transfer_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransferService(sessions)
    balances = TransactionService(sessions)
    key = uuid4()
    data = TransferInput(**transfer_body(own))

    def fail(_session):
        raise SQLAlchemyError("synthetic atomic transfer failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(token, key, data)
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    for account in (own["account"], own["target"]):
        assert balances.balance(token, account, date(2026, 1, 4)).balance == Decimal("1000.00")
    with database.sessions() as session:
        assert session.get(TransferCreationRequest, (own["owner"], key)) is None
        assert (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.user_id == own["owner"])
            )
            == 0
        )
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.create(token, key, data)


def test_transfer_posting_http_requires_confirmation_and_preserves_creation_identity(
    context, transfer_resources
):
    own = transfer_resources[0]
    stack, make = clients(context)
    with stack:
        client, other = make(context[3][0]), make(context[3][1])
        key = uuid4()
        data = transfer_body(own, status="planned")
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf"),
            "Idempotency-Key": str(key),
        }
        created = client.post("/api/v1/transfers", json=data, headers=headers)
        location = created.headers["location"]
        snapshot = client.get(location)
        confirm = {
            "Origin": ORIGIN,
            "X-CSRF-Token": headers["X-CSRF-Token"],
            "If-Match": snapshot.headers["etag"],
        }
        assert (
            client.post(
                location + "/post",
                json={},
                headers={"Origin": ORIGIN, "If-Match": confirm["If-Match"]},
            ).status_code
            == 403
        )
        assert (
            client.post(
                location + "/post",
                json={},
                headers={k: v for k, v in confirm.items() if k != "If-Match"},
            ).status_code
            == 422
        )
        invalid = client.post(
            location + "/post", json={"amount": "private-marker"}, headers=confirm
        )
        assert invalid.status_code == 422 and "private-marker" not in invalid.text
        assert (
            client.post(
                location + "/post", json={}, headers=confirm | {"If-Match": '"' + "0" * 64 + '"'}
            ).status_code
            == 412
        )
        foreign = confirm | {"X-CSRF-Token": other.cookies.get("__Host-finsight-csrf")}
        denied = other.post(location + "/post", json={}, headers=foreign)
        missing = other.post(
            "/api/v1/transfers/" + str(uuid4()) + "/post", json={}, headers=foreign
        )
        assert denied.status_code == missing.status_code == 404 and denied.json() == missing.json()
        assert balance(client, own).json()["balance"] == "1000.00"
        response = client.post(location + "/post", json={}, headers=confirm)
        assert response.status_code == 200 and response.json() == snapshot.json() | {
            "status": "posted"
        }
        assert (
            response.headers["etag"] != confirm["If-Match"]
            and response.headers["cache-control"] == "no-store"
        )
        assert "ETag" in response.headers["access-control-expose-headers"]
        assert client.post(location + "/post", json={}, headers=confirm).json() == response.json()
        assert (
            client.post(
                location + "/post",
                json={},
                headers=confirm | {"If-Match": response.headers["etag"]},
            ).status_code
            == 200
        )
        assert client.post("/api/v1/transfers", json=data, headers=headers).json() == created.json()
        assert client.get(location).json()["status"] == "posted"
        first = balance(client, own).json()["balance"]
        target = client.get(
            f"/api/v1/accounts/{own['target']}/balance", params={"as_of": "2026-01-04"}
        ).json()["balance"]
        assert (
            first == "500.00"
            and target == "1500.00"
            and Decimal(first) + Decimal(target) == Decimal("2000.00")
        )
        assert balance(client, own, "2026-01-03").json()["balance"] == "1000.00"
        assert client.get(PATH).json()["items"] == []


def test_transfer_posting_rechecks_names_both_accounts_and_opening_dates(
    context, transfer_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransferService(sessions)
    transfer_id = service.create(
        token, uuid4(), TransferInput(**transfer_body(own, status="planned"))
    )
    original = service.get(token, transfer_id)
    with database.sessions.begin() as session:
        session.get(Account, own["target"]).name = "Revised destination"
    with pytest.raises(TransferStale):
        service.post(token, transfer_id, transfer_etag(original))
    current = service.get(token, transfer_id)
    for account_id in (own["account"], own["target"]):
        with database.sessions.begin() as session:
            session.get(Account, account_id).is_active = False
        with pytest.raises(TransferRejected):
            service.post(token, transfer_id, transfer_etag(current))
        with database.sessions.begin() as session:
            session.get(Account, account_id).is_active = True
    with database.sessions.begin() as session:
        session.get(Transfer, transfer_id).effective_date = date(2026, 1, 3)
    invalid = service.get(token, transfer_id)
    with pytest.raises(TransferRejected):
        service.post(token, transfer_id, transfer_etag(invalid))
    assert service.get(token, transfer_id).status == "planned"
    assert TransactionService(sessions).balance(
        token, own["account"], date(2026, 1, 4)
    ).balance == Decimal("1000.00")


def test_transfer_posting_concurrency_rollback_revocation_and_archived_replay(
    context, transfer_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransferService(sessions)
    data = TransferInput(**transfer_body(own, status="planned"))
    transfer_id = service.create(token, uuid4(), data)
    etag = transfer_etag(service.get(token, transfer_id))
    barrier = Barrier(2)

    def confirm():
        barrier.wait(timeout=10)
        return service.post(token, transfer_id, etag)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm) for _ in range(2)]
        posted = [future.result(timeout=20) for future in futures]
    assert all(row.id == transfer_id and row.status == "posted" for row in posted)
    second_id = service.create(token, uuid4(), data)
    second = service.get(token, second_id)

    def fail(_session):
        raise SQLAlchemyError("synthetic transfer posting failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.post(token, second_id, transfer_etag(second))
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.get(token, second_id) == second
    with database.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(Transfer).where(Transfer.user_id == own["owner"])
            )
            == 2
        )
        session.get(Account, own["account"]).is_active = False
        session.get(Account, own["target"]).is_active = False
    assert service.post(token, transfer_id, etag).status == "posted"
    balances = TransactionService(sessions)
    assert balances.balance(token, own["account"], date(2026, 1, 4)).balance == Decimal("500.00")
    assert balances.balance(token, own["target"], date(2026, 1, 4)).balance == Decimal("1500.00")
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.post(token, second_id, transfer_etag(second))


def test_balance_history_has_exact_daily_closings_and_preserves_archived_history(
    context, transfer_resources, deletion_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    for amount, day, status in (
        ("150.00", "2026-01-02", "posted"),
        ("0.10", "2026-01-04", "posted"),
        ("100.00", "2026-01-05", "posted"),
        ("999.00", "2026-01-04", "planned"),
    ):
        service.create(
            token,
            uuid4(),
            TransactionInput(**body(own, amount=amount, effective_date=day, status=status)),
        )
    transfers = TransferService(sessions)
    transfers.create(token, uuid4(), TransferInput(**transfer_body(own)))
    transfers.create(
        token,
        uuid4(),
        TransferInput(**transfer_body(own, status="planned", effective_date="2026-01-05")),
    )
    removed = service.create(
        token, uuid4(), TransactionInput(**body(own, amount="25.00", effective_date="2026-01-04"))
    )
    service.delete(token, removed, transaction_etag(service.get(token, removed)))
    stack, make = clients(context)
    with stack:
        client = make(emails[0])
        path = f"/api/v1/accounts/{own['account']}/balance/history"
        response = client.get(path, params={"date_from": "2026-01-01", "date_to": "2026-01-06"})
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["account_id"] == str(own["account"])
        assert response.json()["points"] == [
            {"date": f"2026-01-0{index}", "balance": amount}
            for index, amount in enumerate(
                ("1000.00", "850.00", "850.00", "349.90", "249.90", "249.90"), 1
            )
        ]
        # A subrange starts from its actual closing, not from the opening balance again.
        subrange = client.get(path, params={"date_from": "2026-01-04", "date_to": "2026-01-05"})
        assert subrange.json()["points"] == response.json()["points"][3:5]
        assert (
            response.json()["points"][-1]["balance"]
            == balance(client, own, "2026-01-06").json()["balance"]
        )
        with database.sessions.begin() as session:
            session.get(Account, own["account"]).is_active = False
        assert (
            client.get(path, params={"date_from": "2026-01-01", "date_to": "2026-01-06"}).json()
            == response.json()
        )
        target = client.get(
            f"/api/v1/accounts/{own['target']}/balance/history",
            params={"date_from": "2026-01-03", "date_to": "2026-01-05"},
        )
        assert [point["balance"] for point in target.json()["points"]] == [
            "1000.00",
            "1500.00",
            "1500.00",
        ]


def test_balance_history_rejects_foreign_accounts_invalid_dates_and_oversized_periods(
    context, resources
):
    stack, make = clients(context)
    with stack:
        client, other, anonymous = make(context[3][0]), make(context[3][1]), make()
        own, foreign = resources
        path = f"/api/v1/accounts/{own['account']}/balance/history"
        params = {"date_from": "2026-01-01", "date_to": "2026-01-01"}
        assert anonymous.get(path, params=params).status_code == 401
        assert other.get(path, params=params).status_code == 404
        for unavailable in (foreign["account"], uuid4()):
            response = client.get(f"/api/v1/accounts/{unavailable}/balance/history", params=params)
            assert response.status_code == 404 and response.json() == {
                "detail": "Account not found"
            }
        assert client.get(path, params=params).json()["points"] == [
            {"date": "2026-01-01", "balance": "1000.00"}
        ]
        for changes in (
            {"date_from": "2025-12-31"},
            {"date_from": "2026-01-02"},
            {"date_to": "2026-02-30"},
            {"date_to": "2026-04-04"},
        ):
            assert client.get(path, params=params | changes).status_code == 422
        assert client.get(path).status_code == 422
        longest = client.get(path, params=params | {"date_to": "2026-04-03"})
        assert longest.status_code == 200 and len(longest.json()["points"]) == 93
        assert all(point["balance"] == "1000.00" for point in longest.json()["points"])
        with context[0].sessions.begin() as session:
            session.get(Account, own["account"]).opening_balance = Decimal("-0.10")
        assert client.get(path, params=params).json()["points"][0]["balance"] == "-0.10"


def test_consolidated_balance_scopes_cancel_transfers_and_exclude_unbooked_money(
    context, transfer_resources, deletion_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    TransferService(sessions).create(token, uuid4(), TransferInput(**transfer_body(own)))
    service.create(token, uuid4(), TransactionInput(**body(own, effective_date="2026-01-04")))
    service.create(
        token,
        uuid4(),
        TransactionInput(
            **body(own, status="planned", amount="200.00", effective_date="2026-01-04")
        ),
    )
    service.create(
        token, uuid4(), TransactionInput(**body(own, amount="100.00", effective_date="2026-01-06"))
    )
    removed = service.create(
        token,
        uuid4(),
        TransactionInput(
            **body(
                own,
                type="income",
                category_id=str(own["income"]),
                amount="25.00",
                effective_date="2026-01-04",
            )
        ),
    )
    service.delete(token, removed, transaction_etag(service.get(token, removed)))
    stack, make = clients(context)
    with stack:
        client, other = make(emails[0]), make(emails[1])
        path = "/api/v1/accounts/balances/consolidated"
        params = {"as_of": "2026-01-04"}
        combined = client.get(path, params=params)
        assert combined.status_code == 200 and combined.json() == {
            "as_of": "2026-01-04",
            "scope": "active",
            "currency": "BRL",
            "account_ids": None,
            "account_count": 2,
            "balance": "1850.00",
        }
        assert combined.headers["cache-control"] == "no-store"
        assert other.get(path, params=params).json()["balance"] == "2000.00"
        with database.sessions.begin() as session:
            session.get(Account, own["target"]).is_active = False
        assert client.get(path, params=params).json()["balance"] == "350.00"
        assert client.get(path, params=params | {"scope": "all"}).json()["balance"] == "1850.00"
        for ids, expected in (
            ([own["account"]], "350.00"),
            ([own["target"]], "1500.00"),
            ([own["account"], own["target"]], "1850.00"),
        ):
            response = client.get(
                path,
                params=[("as_of", params["as_of"]), ("scope", "selected")]
                + [("account_id", str(value)) for value in ids],
            )
            assert response.status_code == 200 and response.json()["balance"] == expected
            assert response.json()["account_ids"] == sorted(str(value) for value in ids)
        assert client.get(path, params={"as_of": "2026-01-02", "scope": "all"}).status_code == 422
        assert client.get(path, params={"as_of": "2026-01-02"}).json()["balance"] == "1000.00"


def test_consolidated_balance_rejects_partial_foreign_selections_and_handles_empty_scope(
    context, resources
):
    stack, make = clients(context)
    with stack:
        client = make(context[3][0])
        path = "/api/v1/accounts/balances/consolidated"
        own, foreign = resources
        for foreign_id in (foreign["account"], uuid4()):
            rejected = client.get(
                path,
                params=[
                    ("as_of", "2026-01-04"),
                    ("scope", "selected"),
                    ("account_id", str(own["account"])),
                    ("account_id", str(foreign_id)),
                ],
            )
            assert rejected.status_code == 404 and rejected.json() == {
                "detail": "Account not found"
            }
        for changes in (
            {"scope": "selected"},
            {"scope": "unknown"},
            {"account_id": str(own["account"])},
            {"as_of": "2026-02-30"},
        ):
            assert client.get(path, params={"as_of": "2026-01-04"} | changes).status_code == 422
        assert (
            client.get(
                path,
                params=[
                    ("as_of", "2026-01-04"),
                    ("scope", "selected"),
                    ("account_id", str(own["account"])),
                    ("account_id", str(own["account"])),
                ],
            ).status_code
            == 422
        )
        assert (
            client.get(
                path,
                params=[("as_of", "2026-01-04"), ("scope", "selected")]
                + [("account_id", str(uuid4())) for _ in range(101)],
            ).status_code
            == 422
        )
        assert client.get(path).status_code == 422
        with context[0].sessions.begin() as session:
            session.get(Account, own["account"]).is_active = False
        empty = client.get(path, params={"as_of": "2026-01-04"})
        assert (
            empty.status_code == 200
            and empty.json()["account_count"] == 0
            and empty.json()["balance"] == "0.00"
        )
        assert (
            client.get(path, params={"as_of": "2026-01-04", "scope": "all"}).json()["balance"]
            == "1000.00"
        )


def test_projected_balance_separates_posted_planned_and_overdue_without_mutation(
    context, transfer_resources, deletion_resources
):
    database, sessions, _, emails = context
    own = transfer_resources[0]
    token = sessions.login(emails[0], PASSWORD).access_token
    service = TransactionService(sessions)
    ids = []
    for amount, day, status in (
        ("150.00", "2026-01-04", "posted"),
        ("100.00", "2026-01-08", "posted"),
        ("30.00", "2026-01-04", "planned"),
        ("10.00", "2026-01-05", "planned"),
        ("50.00", "2026-01-10", "planned"),
        ("999.00", "2026-01-11", "planned"),
    ):
        ids.append(
            service.create(
                token,
                uuid4(),
                TransactionInput(**body(own, amount=amount, effective_date=day, status=status)),
            )
        )
    service.create(
        token,
        uuid4(),
        TransactionInput(
            **body(
                own,
                type="income",
                category_id=str(own["income"]),
                amount="200.10",
                effective_date="2026-01-10",
                status="planned",
            )
        ),
    )
    removed = service.create(
        token,
        uuid4(),
        TransactionInput(
            **body(own, amount="999.00", effective_date="2026-01-08", status="planned")
        ),
    )
    service.delete(token, removed, transaction_etag(service.get(token, removed)))
    transfers = TransferService(sessions)
    transfer_id = transfers.create(
        token,
        uuid4(),
        TransferInput(**transfer_body(own, status="planned", effective_date="2026-01-10")),
    )
    transfers.create(
        token,
        uuid4(),
        TransferInput(
            **transfer_body(own, amount="20.00", status="planned", effective_date="2026-01-04")
        ),
    )
    stack, make = clients(context)
    with stack:
        client = make(emails[0])
        path = "/api/v1/accounts/balances/projected"
        params = {
            "base_date": "2026-01-05",
            "target_date": "2026-01-10",
            "overdue_policy": "exclude",
        }
        response = client.get(path, params=params)
        assert response.status_code == 200 and response.json() == {
            **params,
            "scope": "active",
            "currency": "BRL",
            "account_ids": None,
            "account_count": 2,
            "base_balance": "1850.00",
            "posted_future_delta": "-100.00",
            "planned_delta": "140.10",
            "projected_balance": "1890.10",
        }
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.get(path, params=params | {"overdue_policy": "include"}).json()[
                "projected_balance"
            ]
            == "1860.10"
        )
        for account, expected in ((own["account"], "390.10"), (own["target"], "1500.00")):
            selected = client.get(
                path, params=params | {"scope": "selected", "account_id": str(account)}
            )
            assert selected.status_code == 200 and selected.json()["projected_balance"] == expected
        with database.sessions.begin() as session:
            session.get(Account, own["target"]).is_active = False
        assert client.get(path, params=params).json()["projected_balance"] == "390.10"
        assert (
            client.get(path, params=params | {"scope": "all"}).json()["projected_balance"]
            == "1890.10"
        )
        assert (
            client.get(
                path, params=params | {"base_date": "2026-01-02", "scope": "all"}
            ).status_code
            == 422
        )
    with database.sessions() as session:
        assert [session.get(Transaction, value).status for value in ids] == [
            "posted",
            "posted",
            "planned",
            "planned",
            "planned",
            "planned",
        ]
        assert session.get(Transfer, transfer_id).status == "planned"
    assert service.balance(token, own["account"], date(2026, 1, 10)).balance == Decimal("750.00")


def test_projected_balance_rejects_partial_selection_invalid_assumptions_and_missing_session(
    context, resources
):
    stack, make = clients(context)
    with stack:
        client, anonymous = make(context[3][0]), make()
        own, foreign = resources
        path = "/api/v1/accounts/balances/projected"
        params = {
            "base_date": "2026-01-05",
            "target_date": "2026-01-10",
            "overdue_policy": "exclude",
        }
        assert anonymous.get(path, params=params).status_code == 401
        for invalid in (foreign["account"], uuid4()):
            response = client.get(
                path,
                params=params
                | {"scope": "selected", "account_id": [str(own["account"]), str(invalid)]},
            )
            assert response.status_code == 404 and response.json() == {
                "detail": "Account not found"
            }
        for field in params:
            assert (
                client.get(
                    path, params={key: value for key, value in params.items() if key != field}
                ).status_code
                == 422
            )
        for changes in (
            {"target_date": "2026-01-05"},
            {"target_date": "2026-01-04"},
            {"target_date": "2026-02-30"},
            {"base_date": "2025-12-31"},
            {"overdue_policy": "automatic"},
            {"scope": "selected"},
            {"scope": "unknown"},
            {"account_id": str(own["account"])},
            {"scope": "selected", "account_id": [str(own["account"])] * 2},
            {"scope": "selected", "account_id": [str(uuid4()) for _ in range(101)]},
        ):
            assert client.get(path, params=params | changes).status_code == 422
        with context[0].sessions.begin() as session:
            session.get(Account, own["account"]).is_active = False
        empty = client.get(path, params=params)
        assert empty.status_code == 200 and empty.json()["account_count"] == 0
        assert all(
            empty.json()[field] == "0.00"
            for field in (
                "base_balance",
                "posted_future_delta",
                "planned_delta",
                "projected_balance",
            )
        )
        assert (
            client.get(path, params=params | {"scope": "all"}).json()["projected_balance"]
            == "1000.00"
        )
