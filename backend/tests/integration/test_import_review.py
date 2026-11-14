"""Owned CSV corrections, conditional selection and safe rollback on disposable PostgreSQL."""

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
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.core.security import hash_password
from app.db.session import Database
from app.main import create_app
from app.models import (
    Account,
    Category,
    GoalCreationRequest,
    ImportCreationRequest,
    ImportJob,
    ImportRow,
    Transaction,
    User,
)
from app.schemas.import_review import ImportRowEditInput, ImportSelectionInput
from app.schemas.imports import ImportInput
from app.services.import_duplicates import ImportDuplicateService
from app.services.import_review import ImportReviewClosed, ImportReviewService, ImportReviewStale
from app.services.imports import ImportRejected, ImportService
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


def review_seed(context):
    token, account, source = seed(context)
    database, sessions, _, emails = context
    service = ImportService(sessions)
    identity = service.create(token, uuid4(), ImportInput(**source))
    with database.sessions.begin() as session:
        owner = session.scalar(select(User.id).where(User.email == emails[0]))
        other = session.scalar(select(User.id).where(User.email == emails[1]))
        categories = [
            Category(user_id=owner, name="Synthetic expense", type="expense"),
            Category(user_id=owner, name="Synthetic income", type="income"),
            Category(user_id=other, name="Foreign category", type="expense"),
        ]
        session.add_all(categories)
        session.flush()
        category_ids = [category.id for category in categories]
    rows = service.rows(token, identity, limit=100, offset=0).items
    return token, account, identity, rows, category_ids, source


def corrected(category):
    return {
        "transaction_date": "2026-01-02",
        "description": "Synthetic reviewed expense",
        "amount": "12.34",
        "type": "expense",
        "category_id": str(category),
    }


def test_owned_conditional_review_repairs_invalid_rows_and_explicitly_selects_without_posting(
    context,
):
    token, account, identity, rows, categories, source = review_seed(context)
    database, sessions, _, emails = context
    review = ImportReviewService(sessions)
    stack, make = clients(context)
    path = f"{PATH}/{identity}/rows/{rows[2].id}"
    with stack:
        owner, other = make(emails[0]), make(emails[1])
        snapshot = owner.get(path)
        assert snapshot.status_code == 200 and snapshot.headers["etag"] == snapshot.json()["etag"]
        assert not snapshot.json()["selected"] and not snapshot.json()["selection_eligible"]
        assert snapshot.headers["cache-control"] == "no-store"
        assert other.get(path).status_code == 404
        assert owner.patch(path, json=corrected(categories[0])).status_code == 403
        request_headers = headers(owner) | {"If-Match": snapshot.headers["etag"]}
        assert (
            other.patch(
                path,
                json=corrected(categories[0]),
                headers=headers(other) | {"If-Match": snapshot.headers["etag"]},
            ).status_code
            == 404
        )
        assert (
            owner.patch(
                path + "/selection", json={"selected": True}, headers=request_headers
            ).status_code
            == 422
        )
        assert (
            owner.patch(path, json=corrected(categories[2]), headers=request_headers).status_code
            == 422
        )
        assert (
            owner.patch(path, json=corrected(categories[1]), headers=request_headers).status_code
            == 422
        )
        assert (
            owner.patch(
                path,
                json=corrected(categories[0]) | {"transaction_date": "2026-01-01"},
                headers=request_headers,
            ).status_code
            == 422
        )
        fixed = owner.patch(path, json=corrected(categories[0]), headers=request_headers)
        assert fixed.status_code == 200 and fixed.json()["error_codes"] == []
        assert fixed.json()["selection_eligible"] and not fixed.json()["selected"]
        assert (
            fixed.json()["amount"] == "12.34"
            and fixed.json()["category_name"] == "Synthetic expense"
        )
        assert (
            owner.patch(path, json=corrected(categories[0]), headers=request_headers).status_code
            == 412
        )
        selected = owner.patch(
            path + "/selection",
            json={"selected": True},
            headers=headers(owner) | {"If-Match": fixed.headers["etag"]},
        )
        assert selected.status_code == 200 and selected.json()["selected"]
        assert owner.get(f"{PATH}/{identity}").json()["selected_rows"] == 1
        changed = owner.patch(
            path,
            json=corrected(categories[0]) | {"amount": "15.20"},
            headers=headers(owner) | {"If-Match": selected.headers["etag"]},
        )
        assert changed.status_code == 200 and not changed.json()["selected"]
        assert owner.get(f"{PATH}/{identity}").json()["selected_rows"] == 0
        assert owner.get(f"{PATH}/{identity}").json()["invalid_rows"] == 1
        bad_job = f"{PATH}/{uuid4()}/rows/{rows[2].id}"
        assert owner.get(bad_job).status_code == 404
        assert (
            owner.patch(
                path,
                json=corrected(categories[0]) | {"account_id": str(account)},
                headers=headers(owner) | {"If-Match": changed.headers["etag"]},
            ).status_code
            == 422
        )
    assert TransactionService(sessions).balance(
        token, account, date(2026, 1, 3)
    ).balance == Decimal("1000.00")
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Transaction)) == 0
    # Replaying original upload must not restore the old imported preview values.
    with database.sessions() as session:
        key = session.scalar(
            select(ImportCreationRequest.idempotency_key).where(
                ImportCreationRequest.import_job_id == identity
            )
        )
    assert ImportService(sessions).create(token, key, ImportInput(**source)) == identity
    assert review.get(token, identity, rows[2].id).amount == Decimal("15.20")


def test_review_concurrency_rollback_category_archival_and_linked_records_are_protected(context):
    token, account, identity, rows, categories, _ = review_seed(context)
    database, sessions, _, _ = context
    review = ImportReviewService(sessions)
    row_id = rows[0].id
    start = review.get(token, identity, row_id)
    fixed = review.edit(
        token, identity, row_id, ImportRowEditInput(**corrected(categories[0])), start.etag
    )
    barrier = Barrier(2)

    def save(amount):
        barrier.wait(timeout=10)
        try:
            review.edit(
                token,
                identity,
                row_id,
                ImportRowEditInput(**(corrected(categories[0]) | {"amount": amount})),
                fixed.etag,
            )
            return "saved"
        except ImportReviewStale:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [executor.submit(save, amount) for amount in ("20.00", "30.00")]
        assert sorted(result.result(timeout=20) for result in results) == ["saved", "stale"]
    current = review.get(token, identity, row_id)

    def fail(_session):
        raise SQLAlchemyError("synthetic review commit failure")

    event.listen(database.sessions.class_, "before_commit", fail)
    try:
        with pytest.raises(SessionUnavailable):
            review.select(
                token, identity, row_id, ImportSelectionInput(selected=True), current.etag
            )
    finally:
        event.remove(database.sessions.class_, "before_commit", fail)
    assert review.get(token, identity, row_id) == current
    selected = review.select(
        token, identity, row_id, ImportSelectionInput(selected=True), current.etag
    )
    with database.sessions.begin() as session:
        session.get(Category, categories[0]).is_active = False
        session.get(Account, account).is_active = False
    unavailable = review.get(token, identity, row_id)
    assert unavailable.selected and not unavailable.selection_eligible and not unavailable.editable
    assert unavailable.etag != selected.etag
    deselected = review.select(
        token, identity, row_id, ImportSelectionInput(selected=False), unavailable.etag
    )
    assert not deselected.selected
    with pytest.raises(ImportRejected):
        review.select(token, identity, row_id, ImportSelectionInput(selected=True), deselected.etag)
    with database.sessions.begin() as session:
        session.get(Account, account).is_active = True
        session.get(Category, categories[0]).is_active = True
        session.add(
            Transaction(
                user_id=session.get(ImportRow, row_id).user_id,
                account_id=account,
                category_id=categories[0],
                import_row_id=row_id,
                amount=Decimal("1.00"),
                description="Synthetic protected linked transaction",
                type="expense",
                status="posted",
                effective_date=date(2026, 1, 2),
            )
        )
    linked = review.get(token, identity, row_id)
    assert not linked.editable and not linked.selection_editable
    with pytest.raises(ImportReviewClosed):
        review.edit(
            token, identity, row_id, ImportRowEditInput(**corrected(categories[0])), linked.etag
        )
    with database.sessions.begin() as session:
        session.get(ImportJob, identity).status = "cancelled"
    other = review.get(token, identity, rows[1].id)
    with pytest.raises(ImportReviewClosed):
        review.select(token, identity, rows[1].id, ImportSelectionInput(selected=False), other.etag)
    sessions.revoke_by_access(token)
    with pytest.raises(AuthenticationDenied):
        review.get(token, identity, row_id)


def test_selection_migration_preserves_corrections_and_refuses_to_lose_user_choices(context):
    token, _, identity, rows, categories, _ = review_seed(context)
    database, sessions, _, _ = context
    review = ImportReviewService(sessions)
    row_id = rows[0].id
    fixed = review.edit(
        token, identity, row_id, ImportRowEditInput(**corrected(categories[0])), rows[0].etag
    )
    selected = review.select(
        token, identity, row_id, ImportSelectionInput(selected=True), fixed.etag
    )
    with database.engine.begin() as connection:
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.attributes["connection"] = connection
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                update(ImportRow).where(ImportRow.id == rows[3].id).values(selected=True)
            )
        with pytest.raises(CommandError), connection.begin_nested():
            command.downgrade(config, "0015_import_creation_requests")
        assert (
            MigrationContext.configure(connection).get_current_revision()
            == "0016_import_review_selection"
        )
        assert connection.scalar(select(ImportRow.selected).where(ImportRow.id == row_id))
        command.check(config)
        # Disposable fixture only: explicit selections are cleared to test the safe rollback path.
        connection.execute(update(ImportRow).values(selected=False))
        command.downgrade(config, "0015_import_creation_requests")
        assert (
            connection.scalar(select(ImportRow.amount).where(ImportRow.id == row_id))
            == selected.amount
        )
        command.upgrade(config, "head")
        command.check(config)
    after = review.get(token, identity, row_id)
    assert (
        after.amount == fixed.amount
        and after.category_id == fixed.category_id
        and not after.selected
    )


def test_duplicate_report_is_owned_read_only_and_matches_preview_reference_and_transactions(
    context,
):
    token, account, identity, rows, categories, source = review_seed(context)
    database, sessions, _, emails = context
    duplicates = ImportDuplicateService(sessions)
    review = ImportReviewService(sessions)
    original = duplicates.report(token, identity)
    assert len(original.items) == 2 and original.checked_rows == 2 and original.unchecked_rows == 2
    assert all(item.reasons == ["same_preview_fingerprint"] for item in original.items)
    with database.sessions.begin() as session:
        for row in rows[:2]:
            session.get(ImportRow, row.id).external_id = "synthetic-current-reference"
    assert all(
        "same_preview_external_id" in item.reasons
        for item in duplicates.report(token, identity).items
    )
    # Identical data owned by another user or in another own account must not match.
    for index in (0, 1):
        other_token, _, other_source = seed(context, index)
        ImportService(sessions).create(other_token, uuid4(), ImportInput(**other_source))
    with database.sessions.begin() as session:
        session.get(ImportRow, rows[1].id).status = "ignored"
    assert duplicates.report(token, identity).items == []
    assert not duplicates.report(token, identity).overlapping_period
    other_job = ImportService(sessions).create(token, uuid4(), ImportInput(**source))
    other_rows = ImportService(sessions).rows(token, other_job, limit=50, offset=0).items
    with database.sessions.begin() as session:
        session.get(ImportRow, rows[0].id).external_id = "synthetic-ref"
        reference = session.get(ImportRow, other_rows[0].id)
        reference.external_id = "synthetic-ref"
        reference.transaction_date = date(2026, 4, 1)
        reference.description = "Different reference data must still warn"
        session.add(
            Transaction(
                user_id=reference.user_id,
                account_id=account,
                category_id=categories[0],
                description=" SYNTHETIC PURCHASE ",
                amount=Decimal("10.20"),
                type="expense",
                status="planned",
                effective_date=date(2026, 1, 2),
            )
        )
        session.add(
            Transaction(
                user_id=reference.user_id,
                account_id=account,
                category_id=categories[0],
                import_row_id=reference.id,
                description=reference.description,
                amount=reference.amount,
                type=reference.type,
                status="planned",
                effective_date=reference.transaction_date,
            )
        )
    before = review.get(token, identity, rows[0].id)
    report = duplicates.report(token, identity)
    assert report.overlapping_period and not report.scan_limited
    assert len(report.items) == 1
    assert set(report.items[0].reasons) == {
        "other_preview_fingerprint",
        "other_preview_external_id",
        "transaction_fingerprint",
        "transaction_external_id",
    }
    assert review.get(token, identity, rows[0].id) == before
    with database.sessions.begin() as session:
        session.get(ImportJob, other_job).status = "cancelled"
        session.execute(
            update(Transaction)
            .where(Transaction.account_id == account)
            .values(deleted_at=func.now())
        )
    assert duplicates.report(token, identity).items == []
    with database.sessions.begin() as session:
        current = session.get(ImportRow, rows[0].id)
        session.add(
            Transaction(
                user_id=current.user_id,
                account_id=account,
                category_id=categories[0],
                import_row_id=current.id,
                description=current.description,
                amount=current.amount,
                type=current.type,
                status="planned",
                effective_date=current.transaction_date,
            )
        )
    assert (
        duplicates.report(token, identity).items == []
    )  # Its own linked transaction is not a duplicate.
    stack, make = clients(context)
    with stack:
        owner, other, anonymous = make(emails[0]), make(emails[1]), make()
        path = f"{PATH}/{identity}/duplicates"
        response = owner.get(path)
        assert response.status_code == 200 and response.json()["job_id"] == str(identity)
        assert response.headers["cache-control"] == "no-store"
        assert other.get(path).status_code == 404 and anonymous.get(path).status_code == 401
    # Remove this synthetic soft-deleted fixture before the guarded migration teardown.
    with database.sessions.begin() as session:
        session.execute(delete(Transaction).where(Transaction.account_id == account))


def test_duplicate_report_refreshes_after_correction_and_reports_containing_period_and_limits(
    context,
    monkeypatch,
):
    token, account, identity, rows, categories, source = review_seed(context)
    database, sessions, _, _ = context
    duplicates, review = ImportDuplicateService(sessions), ImportReviewService(sessions)
    corrected_row = review.edit(
        token, identity, rows[0].id, ImportRowEditInput(**corrected(categories[0])), rows[0].etag
    )
    selected = review.select(
        token, identity, rows[0].id, ImportSelectionInput(selected=True), corrected_row.etag
    )
    assert duplicates.report(token, identity).items == []
    assert review.get(token, identity, rows[0].id) == selected
    with database.sessions.begin() as session:
        for row in session.scalars(select(ImportRow).where(ImportRow.import_job_id == identity)):
            row.transaction_date = date(2026, 1, 15) if row.status == "pending" else None
    other = ImportService(sessions).create(token, uuid4(), ImportInput(**source))
    other_rows = ImportService(sessions).rows(token, other, limit=50, offset=0).items
    with database.sessions.begin() as session:
        session.get(ImportRow, other_rows[0].id).transaction_date = date(2026, 1, 2)
        session.get(ImportRow, other_rows[1].id).transaction_date = date(2026, 1, 31)
    contained = duplicates.report(token, identity)
    assert contained.overlapping_period and contained.items == []
    # Bound the number of historical candidates, and disclose partial coverage.
    with database.sessions.begin() as session:
        for other_row in other_rows[:2]:
            session.get(ImportRow, other_row.id).transaction_date = date(2026, 1, 15)
    monkeypatch.setattr("app.services.import_duplicates.MAX_CANDIDATES", 1)
    limited = duplicates.report(token, identity)
    assert limited.scan_limited and limited.candidate_limit == 1
    assert review.get(token, identity, rows[0].id).selected
    assert TransactionService(sessions).balance(
        token, account, date(2026, 1, 31)
    ).balance == Decimal("1000.00")
