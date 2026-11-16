"""Atomic CSV confirmation, retained receipts and guarded rollback on disposable PostgreSQL."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date, timedelta
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
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import (
    Account,
    Category,
    FinancialGoal,
    GoalAllocation,
    GoalCreationRequest,
    ImportCreationRequest,
    ImportJob,
    ImportRow,
    Transaction,
    User,
)
from app.schemas.import_confirmation import ImportConfirmationInput
from app.schemas.import_review import ImportRowEditInput, ImportSelectionInput
from app.schemas.imports import ImportInput
from app.services.allocations import business_date
from app.services.import_confirmation import ImportConfirmationService
from app.services.import_review import ImportReviewService, ImportReviewStale
from app.services.imports import ImportConflict, ImportRejected, ImportService
from app.services.sessions import AuthenticationDenied, SessionService, SessionUnavailable
from app.services.transactions import TransactionService

pytestmark = pytest.mark.postgres
PASSWORD = "synthetic account password"
ORIGIN = "https://app.example.test"
PATH = "/api/v1/imports"


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
                connection.execute(update(ImportRow).values(selected=False))
                connection.execute(
                    update(ImportJob).values(
                        confirmation_key=None, confirmation_hash=None, confirmation_result=None
                    )
                )
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


ACK = {
    "acknowledge_duplicates": True,
    "acknowledge_classification": True,
    "acknowledge_reservations": True,
}


def confirmation_seed(context, *, total=2, selected=1):
    token, account, source = seed(context)
    database, sessions, _, emails = context
    csv = "Date;Description;Amount\n" + "\n".join(
        f"2026-01-02;Synthetic statement {index};-10.00" for index in range(total)
    )
    source["content_base64"] = base64.b64encode(csv.encode()).decode()
    identity = ImportService(sessions).create(token, uuid4(), ImportInput(**source))
    with database.sessions.begin() as session:
        owner = session.scalar(select(User.id).where(User.email == emails[0]))
        category = Category(user_id=owner, name="Synthetic confirmed expense", type="expense")
        session.add(category)
        session.flush()
        category_id = category.id
    rows = ImportService(sessions).rows(token, identity, limit=100, offset=0).items
    review = ImportReviewService(sessions)
    for row in rows[:selected]:
        updated = review.edit(
            token,
            identity,
            row.id,
            ImportRowEditInput(
                transaction_date="2026-01-02",
                description=row.description,
                amount="10.00",
                type="expense",
                category_id=str(category_id),
            ),
            row.etag,
        )
        review.select(token, identity, row.id, ImportSelectionInput(selected=True), updated.etag)
    return token, account, identity, category_id, source


def test_confirmation_http_posts_only_selection_with_owned_receipt_retry_and_reservation_warning(
    context,
):
    token, account, identity, category, source = confirmation_seed(context, total=10, selected=8)
    database, sessions, _, emails = context
    with database.sessions.begin() as session:
        owner = session.get(Account, account).user_id
        goal = FinancialGoal(
            user_id=owner,
            name="Synthetic protected reserve",
            target_amount=Decimal("2000.00"),
            status="active",
        )
        session.add(goal)
        session.flush()
        session.add(
            GoalAllocation(
                user_id=owner,
                account_id=account,
                goal_id=goal.id,
                amount=Decimal("995.00"),
                allocation_date=business_date(),
            )
        )
    stack, make = clients(context)
    with stack:
        owner, other = make(emails[0]), make(emails[1])
        path = f"{PATH}/{identity}"
        snapshot = owner.get(path + "/confirmation")
        assert snapshot.status_code == 200 and snapshot.headers["cache-control"] == "no-store"
        context_data = snapshot.json()
        assert context_data["eligible"] and context_data["selected_count"] == 8
        assert context_data["bank_balance_after"] == "920.00"
        assert context_data["free_balance_after"] == "-75.00"
        assert context_data["uncovered_reserved_after"] == "75.00"
        assert other.get(path + "/confirmation").status_code == 404
        key = uuid4()
        versioned = headers(owner, key) | {"If-Match": snapshot.headers["etag"]}
        assert owner.post(path + "/confirm", json=ACK).status_code == 403
        assert (
            owner.post(path + "/confirm", json=ACK, headers=headers(owner, key)).status_code == 422
        )
        assert (
            owner.post(
                path + "/confirm", json=ACK | {"acknowledge_duplicates": False}, headers=versioned
            ).status_code
            == 422
        )
        assert (
            other.post(
                path + "/confirm",
                json=ACK,
                headers=headers(other, key) | {"If-Match": snapshot.headers["etag"]},
            ).status_code
            == 404
        )
        result = owner.post(path + "/confirm", json=ACK, headers=versioned)
        assert result.status_code == 200
        receipt = result.json()
        assert receipt["imported_rows"] == 8 and receipt["not_imported_rows"] == 2
        assert receipt["bank_balance_after"] == "920.00"
        with database.sessions.begin() as session:
            session.get(Account, account).is_active = False
            session.get(Category, category).is_active = False
        replay = owner.post(path + "/confirm", json=ACK, headers=versioned)
        assert replay.status_code == 200 and replay.json() == receipt
        assert owner.get(path + "/confirmation").json()["receipt"] == receipt
        assert (
            owner.post(
                path + "/confirm",
                json=ACK,
                headers=headers(owner, uuid4()) | {"If-Match": snapshot.headers["etag"]},
            ).status_code
            == 409
        )
    with database.sessions() as session:
        transactions = session.scalars(
            select(Transaction).where(Transaction.account_id == account)
        ).all()
        assert len(transactions) == 8 and len({row.import_row_id for row in transactions}) == 8
        assert all(row.status == "posted" and row.import_row_id for row in transactions)
        rows = session.scalars(select(ImportRow).where(ImportRow.import_job_id == identity)).all()
        assert sum(row.status == "imported" for row in rows) == 8
        assert sum(row.status == "ignored" for row in rows) == 2
        assert all(not row.selected for row in rows)
        assert session.scalar(
            select(func.sum(GoalAllocation.amount)).where(GoalAllocation.account_id == account)
        ) == Decimal("995.00")
        original_key = session.scalar(
            select(ImportCreationRequest.idempotency_key).where(
                ImportCreationRequest.import_job_id == identity
            )
        )
    assert ImportService(sessions).create(token, original_key, ImportInput(**source)) == identity
    assert TransactionService(sessions).balance(token, account, business_date()).balance == Decimal(
        "920.00"
    )


def test_confirmation_stale_metadata_dates_and_rollback_then_concurrent_retries_are_safe(context):
    token, account, identity, category, _ = confirmation_seed(context)
    database, sessions, _, _ = context
    day = [date(2026, 1, 3)]
    confirmation = ImportConfirmationService(sessions, today=lambda: day[0])
    data = ImportConfirmationInput(**ACK)
    snapshot = confirmation.get(token, identity)
    with database.sessions.begin() as session:
        session.get(Category, category).is_active = False
    with pytest.raises(ImportReviewStale):
        confirmation.confirm(token, identity, uuid4(), snapshot.etag, data)
    current = confirmation.get(token, identity)
    assert not current.eligible and "invalid_selection" in current.issues
    with pytest.raises(ImportRejected):
        confirmation.confirm(token, identity, uuid4(), current.etag, data)
    with database.sessions.begin() as session:
        session.get(Category, category).is_active = True
    snapshot = confirmation.get(token, identity)
    with database.sessions.begin() as session:
        movement = Transaction(
            user_id=session.get(Account, account).user_id,
            account_id=account,
            category_id=category,
            description="Synthetic intervening movement",
            amount=Decimal("1.00"),
            type="expense",
            status="posted",
            effective_date=date(2026, 1, 2),
        )
        session.add(movement)
        session.flush()
        movement_id = movement.id
    with pytest.raises(ImportReviewStale):
        confirmation.confirm(token, identity, uuid4(), snapshot.etag, data)
    with database.sessions.begin() as session:
        session.execute(delete(Transaction).where(Transaction.id == movement_id))
    day[0] = date(2026, 1, 4)
    with pytest.raises(ImportReviewStale):
        confirmation.confirm(token, identity, uuid4(), snapshot.etag, data)
    snapshot = confirmation.get(token, identity)
    key = uuid4()

    def fail(_session):
        raise SQLAlchemyError("synthetic confirmation commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            confirmation.confirm(token, identity, key, snapshot.etag, data)
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert confirmation.get(token, identity) == snapshot
    with database.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.account_id == account)
            )
            == 0
        )
    barrier = Barrier(2)

    def confirm():
        barrier.wait(timeout=10)
        return confirmation.confirm(token, identity, key, snapshot.etag, data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(confirm) for _ in range(2)]
        assert futures[0].result(timeout=30) == futures[1].result(timeout=30)
    with pytest.raises(ImportConflict):
        confirmation.confirm(token, identity, key, '"' + "f" * 64 + '"', data)
    assert TransactionService(sessions).balance(token, account, day[0]).balance == Decimal("990.00")


def test_confirmation_migration_preserves_receipts_and_refuses_unsafe_downgrade(context):
    token, account, identity, _, _ = confirmation_seed(context)
    database, sessions, _, _ = context
    confirmation = ImportConfirmationService(sessions)
    future = business_date() + timedelta(days=1)
    with database.sessions.begin() as session:
        row = session.scalar(
            select(ImportRow).where(
                ImportRow.import_job_id == identity, ImportRow.selected.is_(True)
            )
        )
        row.transaction_date = future
    snapshot = confirmation.get(token, identity)
    assert snapshot.future_rows == 1 and snapshot.bank_balance_after == Decimal("1000.00")
    receipt = confirmation.confirm(
        token, identity, uuid4(), snapshot.etag, ImportConfirmationInput(**ACK)
    )
    assert receipt.bank_balance_after == Decimal("1000.00")
    assert TransactionService(sessions).balance(token, account, future).balance == Decimal("990.00")
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.check(config)
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0016_import_review_selection")
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == "0017_import_confirmation"
        )
        stored = connection.scalar(
            select(ImportJob.confirmation_result).where(ImportJob.id == identity)
        )
        assert stored == receipt.model_dump(mode="json")
        assert (
            connection.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.account_id == account)
            )
            == 1
        )
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        confirmation.get(token, identity)
