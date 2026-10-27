"""Import persistence on owned disposable PostgreSQL; no file parsing or real data."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import Account, Category, ImportJob, ImportRow, User, UserSession

pytestmark = pytest.mark.postgres
CONFIG_PATH = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def connection(postgres_settings):
    database = Database(postgres_settings)
    try:
        with database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                config = Config(str(CONFIG_PATH))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                yield connection
            finally:
                transaction.rollback()
    finally:
        database.dispose()


def owner_account(connection, email="owner@example.test"):
    owner = connection.execute(
        insert(User)
        .values(name="Synthetic", email=email, password_hash="synthetic")
        .returning(User.id)
    ).scalar_one()
    account = connection.execute(
        insert(Account).values(**account_values(owner)).returning(Account.id)
    ).scalar_one()
    return owner, account


def account_values(owner):
    return dict(
        user_id=owner,
        name="Synthetic",
        type="checking",
        opening_balance=Decimal("0.00"),
        opening_date=date(2026, 1, 1),
    )


def job_values(owner, account, **overrides):
    return dict(
        user_id=owner,
        account_id=account,
        filename="synthetic.csv",
        file_checksum="a" * 64,
        **overrides,
    )


def add_job(connection):
    owner, account = owner_account(connection)
    job = connection.execute(
        insert(ImportJob).values(**job_values(owner, account)).returning(ImportJob.id)
    ).scalar_one()
    return dict(user_id=owner, account_id=account, import_job_id=job, row_number=1)


def test_orm_round_trip_derives_ownership_and_preserves_preview(connection):
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        owner = User(name="Synthetic", email="owner@example.test", password_hash="synthetic")
        account = Account(**account_values(None), user=owner)
        category = Category(user=owner, name="Synthetic", type="expense")
        job = ImportJob(
            user=owner, account=account, filename="  synthetic.csv  ", file_checksum="A" * 64
        )
        row = ImportRow(
            import_job=job,
            row_number=1,
            suggested_category=category,
            transaction_date=date(2026, 1, 2),
            description="Synthetic preview",
            amount=Decimal("123.45"),
            type="expense",
            fingerprint="B" * 64,
            external_id="synthetic-reference",
        )
        session.add(row)
        session.commit()
        session.expire_all()
        assert row.user_id == job.user_id == owner.id
        assert row.account_id == job.account_id == account.id
        assert row.import_job_id == job.id and row.suggested_category_id == category.id
        assert owner.import_jobs == account.import_jobs == [job] and job.rows == [row]
        assert job.filename == "synthetic.csv" and job.file_checksum == "a" * 64
        assert job.file_type == "csv" and job.status == "uploaded"
        assert job.total_rows == job.imported_rows == 0 and job.completed_at is None
        assert row.status == "pending" and row.fingerprint == "b" * 64
        assert row.amount == Decimal("123.45") and isinstance(row.amount, Decimal)
        assert row.transaction_date == date(2026, 1, 2)
        for model in (job, row):
            assert isinstance(model.id, uuid.UUID) and model.id.version == 4
            assert model.created_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("amount", [None, Decimal("0"), Decimal("9999999999999.99")])
def test_incomplete_invalid_preview_and_decimal_boundaries(connection, amount):
    values = add_job(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        row = ImportRow(**values, amount=amount, status="invalid", error_message="Synthetic error")
        session.add(row)
        session.commit()
        session.refresh(row)
        assert row.amount == amount
        assert (
            row.transaction_date is row.description is row.type is row.suggested_category_id is None
        )


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        0,
        "1.00",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("-0.01"),
        Decimal("0.001"),
        Decimal("10000000000000"),
        Decimal("1e1000000"),
        Decimal("-1e1000000"),
    ],
)
def test_orm_rejects_inexact_or_invalid_amounts(value):
    with pytest.raises(ValueError, match="Preview amount"):
        ImportRow(amount=value)


@pytest.mark.parametrize(
    "filename", [None, "", " ", ".", "..", "a/b.csv", "a\\b.csv", "a\nb.csv", "a\x7fb"]
)
def test_orm_rejects_unsafe_filenames(filename):
    with pytest.raises(ValueError, match="sanitized base name"):
        ImportJob(filename=filename)


@pytest.mark.parametrize("model,field", [(ImportJob, "file_checksum"), (ImportRow, "fingerprint")])
@pytest.mark.parametrize("value", ["", "g" * 64, "a" * 63, "a" * 65, " a" * 32])
def test_orm_rejects_invalid_digests(model, field, value):
    with pytest.raises(ValueError, match="SHA-256"):
        model(**{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"account_id": None},
        {"account_id": uuid.UUID(int=1)},
        {"filename": None},
        {"filename": ""},
        {"filename": " "},
        {"filename": ".."},
        {"filename": "a/b"},
        {"filename": "a\\b"},
        {"filename": "a\nb"},
        {"filename": " x.csv "},
        {"filename": "x" * 256},
        {"file_type": "pdf"},
        {"file_checksum": None},
        {"file_checksum": "A" * 64},
        {"file_checksum": "bad"},
        {"status": "unknown"},
        {"status": None},
        {"total_rows": -1},
        {"imported_rows": -1},
        {"total_rows": 2, "imported_rows": 3},
        {
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
            "completed_at": datetime(2026, 1, 1, tzinfo=UTC),
        },
    ],
)
def test_database_rejects_invalid_jobs(connection, overrides):
    owner, account = owner_account(connection)
    values = job_values(owner, account)
    values.update(overrides)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(insert(ImportJob).values(**values))


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"account_id": None},
        {"import_job_id": None},
        {"user_id": uuid.UUID(int=1)},
        {"account_id": uuid.UUID(int=1)},
        {"import_job_id": uuid.UUID(int=1)},
        {"suggested_category_id": uuid.UUID(int=1)},
        {"row_number": 0},
        {"row_number": -1},
        {"row_number": None},
        {"amount": Decimal("-0.01")},
        {"amount": Decimal("NaN")},
        {"amount": Decimal("Infinity")},
        {"amount": Decimal("10000000000000")},
        {"type": "transfer"},
        {"status": "unknown"},
        {"status": None},
        {"fingerprint": "B" * 64},
        {"fingerprint": "bad"},
        {"description": "x" * 256},
    ],
)
def test_database_rejects_invalid_rows(connection, overrides):
    values = add_job(connection)
    values.update(overrides)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(insert(ImportRow).values(**values))


@pytest.mark.parametrize(
    "status", ["uploaded", "processing", "review", "completed", "failed", "cancelled"]
)
def test_job_statuses_and_repeated_checksums_are_allowed(connection, status):
    owner, account = owner_account(connection)
    for _ in range(2):
        connection.execute(
            insert(ImportJob).values(
                **job_values(owner, account), status=status, total_rows=2, imported_rows=1
            )
        )


@pytest.mark.parametrize(
    "status", ["pending", "duplicate_candidate", "invalid", "imported", "ignored"]
)
def test_row_statuses_repeated_fingerprints_and_job_row_uniqueness(connection, status):
    values = add_job(connection)
    connection.execute(insert(ImportRow).values(**values, status=status, fingerprint="b" * 64))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(insert(ImportRow).values(**values))
    connection.execute(
        insert(ImportRow).values(**{**values, "row_number": 2}, fingerprint="b" * 64)
    )
    job = connection.execute(
        insert(ImportJob)
        .values(**job_values(values["user_id"], values["account_id"]))
        .returning(ImportJob.id)
    ).scalar_one()
    connection.execute(insert(ImportRow).values(**{**values, "import_job_id": job}))


def test_database_rejects_other_owners_account_and_category(connection):
    values = add_job(connection)
    other, account = owner_account(connection, "other@example.test")
    category = connection.execute(
        insert(Category)
        .values(user_id=other, name="Synthetic", type="expense")
        .returning(Category.id)
    ).scalar_one()
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(insert(ImportJob).values(**job_values(values["user_id"], account)))
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(insert(ImportRow).values(**values, suggested_category_id=category))


def test_orm_account_assignment_cannot_reparent_job(connection):
    owner, _ = owner_account(connection)
    _, other_account = owner_account(connection, "other@example.test")
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        job = ImportJob(
            user=session.get(User, owner),
            account=session.get(Account, other_account),
            filename="synthetic.csv",
            file_checksum="a" * 64,
        )
        session.add(job)
        with pytest.raises(IntegrityError):
            session.flush()
        assert job.user_id == owner and job.account_id == other_account
        session.rollback()


def test_orm_category_assignment_cannot_reparent_row(connection):
    values = add_job(connection)
    other, _ = owner_account(connection, "other@example.test")
    category = connection.execute(
        insert(Category)
        .values(user_id=other, name="Synthetic", type="expense")
        .returning(Category.id)
    ).scalar_one()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        row = ImportRow(
            import_job=session.get(ImportJob, values["import_job_id"]),
            row_number=1,
            suggested_category=session.get(Category, category),
        )
        session.add(row)
        with pytest.raises(IntegrityError):
            session.flush()
        assert row.user_id == values["user_id"] and row.account_id == values["account_id"]
        session.rollback()


def test_future_transaction_fk_requires_same_owner_and_account(connection):
    values = add_job(connection)
    row = connection.execute(
        insert(ImportRow).values(**values).returning(ImportRow.id)
    ).scalar_one()
    other, other_account = owner_account(connection, "other@example.test")
    same_owner_account = connection.execute(
        insert(Account).values(**account_values(values["user_id"])).returning(Account.id)
    ).scalar_one()
    connection.exec_driver_sql(
        "CREATE TABLE transaction_import_probe (user_id UUID NOT NULL, account_id UUID NOT NULL, "
        "import_row_id UUID NOT NULL, FOREIGN KEY (user_id, account_id, import_row_id) "
        "REFERENCES import_rows(user_id, account_id, id))"
    )
    statement = text("INSERT INTO transaction_import_probe VALUES (:user, :account, :row)")
    connection.execute(
        statement, {"user": values["user_id"], "account": values["account_id"], "row": row}
    )
    for owner, account in [(other, other_account), (values["user_id"], same_owner_account)]:
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(statement, {"user": owner, "account": account, "row": row})


@pytest.mark.parametrize("parent", [ImportJob, Account, Category, User])
def test_deletion_restricted_even_with_loaded_relationships(connection, parent):
    values = add_job(connection)
    category = connection.execute(
        insert(Category)
        .values(user_id=values["user_id"], name="Synthetic", type="expense")
        .returning(Category.id)
    ).scalar_one()
    connection.execute(insert(ImportRow).values(**values, suggested_category_id=category))
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        job = session.get(ImportJob, values["import_job_id"])
        assert len(job.rows) == len(job.user.import_jobs) == len(job.account.import_jobs) == 1
        target = {
            ImportJob: job,
            Account: job.account,
            User: job.user,
            Category: session.get(Category, category),
        }[parent]
        session.delete(target)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(ImportJob, values["import_job_id"]) is not None


def test_downgrade_preserves_prior_domain_data_and_reupgrade_has_no_drift(connection):
    values = add_job(connection)
    connection.execute(insert(ImportRow).values(**values))
    connection.execute(
        insert(Category).values(user_id=values["user_id"], name="Synthetic", type="expense")
    )
    connection.execute(
        insert(UserSession).values(
            user_id=values["user_id"],
            refresh_token_hash="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = connection
    command.downgrade(config, "0003_accounts_categories")
    assert set(inspect(connection).get_table_names()) == {
        "alembic_version",
        "users",
        "user_sessions",
        "accounts",
        "categories",
    }
    for table in ("users", "user_sessions", "accounts", "categories"):
        assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
    command.upgrade(config, "head")
    command.check(config)
