"""Owned CSV previews, bounded transport and atomic retries on disposable PostgreSQL."""

import base64
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
    GoalAllocation,
    GoalCreationRequest,
    ImportCreationRequest,
    ImportJob,
    ImportRow,
    Transaction,
    Transfer,
    User,
)
from app.schemas.imports import ImportInput
from app.services.imports import ImportRejected, ImportService, upload_slot
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import TransactionService

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic account password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/imports"
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
                connection.execute(delete(ImportCreationRequest))
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


CSV = (
    b"Date;Description;Amount\n"
    b"2026-01-02;Synthetic purchase;-10.20\n"
    b"2026-01-02;Synthetic purchase;-10.20\n"
    b"2026-01-01;Opening day;20\n"
    b"2026-99-99;Invalid date;50\n"
)
MAPPING = {
    "date_column": 0,
    "description_column": 1,
    "amount_column": 2,
    "date_format": "iso",
    "money_format": "decimal-dot",
}


def seed(context, index=0):
    database, sessions, _, emails = context
    grant = sessions.login(emails[index], PASSWORD)
    with database.sessions.begin() as session:
        account = Account(
            user_id=grant.context.user_id,
            name="Synthetic import account",
            type="checking",
            opening_balance=Decimal("1000.00"),
            opening_date=date(2026, 1, 1),
        )
        session.add(account)
        session.flush()
        identity = account.id
    data = {
        "account_id": str(identity),
        "filename": "synthetic.csv",
        "content_base64": base64.b64encode(CSV).decode(),
        "mapping": MAPPING,
    }
    return grant.access_token, identity, data


def headers(client, key=None):
    result = {"Origin": ORIGIN, "X-CSRF-Token": client.cookies.get("__Host-finsight-csrf") or ""}
    if key is not None:
        result["Idempotency-Key"] = str(key)
    return result


def test_preview_http_is_owned_private_and_never_creates_financial_movements(context):
    token, account, data = seed(context)
    _, other_account, other_data = seed(context, 1)
    database, sessions, _, emails = context
    stack, make = clients(context)
    with stack:
        owner, other, anonymous = make(emails[0]), make(emails[1]), make()
        source = {key: value for key, value in data.items() if key != "mapping"}
        assert anonymous.get(PATH).status_code == 401
        assert owner.post(PATH, json=data).status_code == 403
        assert other.post(PATH + "/inspect", json=source, headers=headers(other)).status_code == 404
        inspected = owner.post(PATH + "/inspect", json=source, headers=headers(owner))
        assert inspected.status_code == 200 and inspected.headers["cache-control"] == "no-store"
        assert inspected.json()["headers"] == ["Date", "Description", "Amount"]
        assert inspected.json()["matching_files"] == 0 and inspected.json()["total_rows"] == 4
        with database.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ImportJob)) == 0
        key = uuid4()
        created = owner.post(PATH, json=data, headers=headers(owner, key))
        assert created.status_code == 201
        path = created.headers["location"]
        assert owner.post(PATH, json=data, headers=headers(owner, key)).json() == created.json()
        assert (
            owner.post(
                PATH, json=data | {"filename": "different.csv"}, headers=headers(owner, key)
            ).status_code
            == 409
        )
        assert other.post(PATH, json=other_data, headers=headers(other, key)).status_code == 201
        assert other.get(path).status_code == other.get(path + "/rows").status_code == 404
        summary = owner.get(path)
        assert summary.headers["cache-control"] == "no-store"
        assert (
            summary.json()["status"],
            summary.json()["total_rows"],
            summary.json()["invalid_rows"],
            summary.json()["imported_rows"],
        ) == ("review", 4, 2, 0)
        assert "user_id" not in summary.json() and "content_base64" not in summary.text
        rows = owner.get(path + "/rows", params={"limit": 2}).json()
        assert rows["has_more"] and [row["amount"] for row in rows["items"]] == ["10.20", "10.20"]
        assert rows["items"][0]["id"] != rows["items"][1]["id"]
        invalid = owner.get(path + "/rows", params={"offset": 2}).json()["items"]
        assert [row["error_codes"] for row in invalid] == [
            ["date_not_after_opening"],
            ["invalid_date"],
        ]
        assert owner.post(PATH, json=data, headers=headers(owner, uuid4())).status_code == 201
        assert owner.get(path).json()["matching_files"] == 1
        assert owner.get(PATH, params={"limit": 1}).json()["has_more"]
        assert {item["account_id"] for item in other.get(PATH).json()["items"]} == {
            str(other_account)
        }
        confirmation_status = owner.post(
            path + "/confirm", json={}, headers=headers(owner)
        ).status_code
        posting_status = owner.post(path + "/post", json={}, headers=headers(owner)).status_code
        assert confirmation_status == 422
        assert posting_status == 404
    assert TransactionService(sessions).balance(
        token, account, date(2026, 1, 2)
    ).balance == Decimal("1000.00")
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0
        assert session.scalar(select(func.count()).select_from(Transfer)) == 0
        assert session.scalar(select(func.count()).select_from(GoalAllocation)) == 0


def test_import_body_limits_csrf_cors_errors_and_busy_retries_are_bounded(context):
    _, _, data = seed(context)
    _, _, _, emails = context
    stack, make = clients(context)
    with stack:
        owner = make(emails[0])
        request_headers = headers(owner, uuid4())
        rejected = owner.post(PATH, json=data | {"user_id": str(uuid4())}, headers=request_headers)
        assert rejected.status_code == 422 and data["content_base64"] not in rejected.text
        for changes in [{"filename": "../secret.csv"}, {"content_base64": "secret invalid base64"}]:
            response = owner.post(PATH, json=data | changes, headers=request_headers)
            assert response.status_code == 422 and "secret" not in response.text
        broken = base64.b64encode(b'Date;Description;Amount\n"secret unmatched quote').decode()
        error = owner.post(PATH, json=data | {"content_base64": broken}, headers=request_headers)
        assert (
            error.status_code == 422
            and "secret" not in error.text
            and error.json()["code"] == "malformed_csv"
        )
        duplicate = list(headers(owner).items()) + [
            ("Idempotency-Key", str(uuid4())),
            ("Idempotency-Key", str(uuid4())),
        ]
        assert owner.post(PATH, json=data, headers=duplicate).status_code == 403
        preflight = owner.options(
            PATH,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type,X-CSRF-Token,Idempotency-Key",
            },
        )
        assert (
            preflight.status_code == 200
            and preflight.headers["access-control-allow-origin"] == ORIGIN
        )
        assert (
            owner.post(
                PATH,
                content=b"x" * 1_500_001,
                headers=request_headers
                | {"Content-Type": "application/json", "Content-Length": "1"},
            ).status_code
            == 413
        )
        assert (
            owner.post(
                "/api/v1/goals",
                content=b"x" * 20_000,
                headers=request_headers | {"Content-Type": "application/json"},
            ).status_code
            == 413
        )
        content = (
            b"Date;Description;Amount\n" + b"2026-01-02;Synthetic bounded transport;10\n" * 500
        )
        assert len(content) > 16_384
        larger = {key: value for key, value in data.items() if key != "mapping"} | {
            "content_base64": base64.b64encode(content).decode()
        }
        assert (
            owner.post(PATH + "/inspect", json=larger, headers=headers(owner)).json()["total_rows"]
            == 500
        )
        with upload_slot(), upload_slot():
            busy = owner.post(PATH, json=data, headers=request_headers)
            assert busy.status_code == 503 and busy.headers["retry-after"] == "1"
        assert owner.post(PATH, json=data, headers=request_headers).status_code == 201


def test_preview_concurrency_rollback_archive_replay_and_revocation(context):
    token, account, data = seed(context)
    database, sessions, _, _ = context
    service = ImportService(sessions)
    body = ImportInput(**data)
    key = uuid4()
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=10)
        return service.create(token, key, body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(save) for _ in range(2)]
        ids = [result.result(timeout=20) for result in results]
    assert ids[0] == ids[1] and len(service.rows(token, ids[0], limit=100, offset=0).items) == 4
    before = service.list(token, limit=50, offset=0)
    failed_key = uuid4()

    def fail(_session):
        raise SQLAlchemyError("synthetic preview commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            service.create(token, failed_key, body)
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert service.list(token, limit=50, offset=0) == before
    with database.sessions.begin() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ImportCreationRequest)
                .where(ImportCreationRequest.idempotency_key == failed_key)
            )
            == 0
        )
        session.get(Account, account).is_active = False
    assert service.create(token, key, body) == ids[0]
    with pytest.raises(ImportRejected):
        service.create(token, uuid4(), body)
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        service.create(token, key, body)


def test_import_request_migration_preserves_preview_and_owned_retry_memory(context):
    token, _, data = seed(context)
    database, sessions, _, emails = context
    service = ImportService(sessions)
    identity = service.create(token, uuid4(), ImportInput(**data))
    before = service.rows(token, identity, limit=100, offset=0)
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        other = connection.scalar(select(User.id).where(User.email == emails[1]))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                insert(ImportCreationRequest).values(
                    user_id=other,
                    account_id=data["account_id"],
                    import_job_id=identity,
                    idempotency_key=uuid4(),
                    request_hash="a" * 64,
                )
            )
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0014_allocation_requests")
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == "0017_import_confirmation"
        )
        command.check(config)
        connection.execute(delete(ImportCreationRequest))
        command.downgrade(config, "0014_allocation_requests")
        assert (
            connection.scalar(
                select(func.count())
                .select_from(ImportRow)
                .where(ImportRow.import_job_id == identity)
            )
            == 4
        )
        command.upgrade(config, "head")
        command.check(config)
    assert service.rows(token, identity, limit=100, offset=0) == before
