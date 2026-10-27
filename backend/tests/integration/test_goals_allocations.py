"""Goal schema and signed movements on disposable PostgreSQL, without reservation services."""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Database
from app.models import (
    Account,
    Category,
    FinancialGoal,
    GoalAllocation,
    ImportJob,
    ImportRow,
    Transaction,
    Transfer,
    User,
    UserSession,
)

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


def add(connection, model, **values):
    return connection.execute(insert(model).values(**values).returning(model.id)).scalar_one()


def account_values(owner):
    return dict(
        user_id=owner,
        name="Synthetic account",
        type="checking",
        opening_balance=Decimal("10000.00"),
        opening_date=date(2026, 1, 1),
    )


def goal_values(owner, **overrides):
    return (
        dict(
            user_id=owner, name="Synthetic goal", target_amount=Decimal("1000.00"), status="active"
        )
        | overrides
    )


def seed(connection, email="owner@example.test"):
    owner = add(connection, User, name="Synthetic owner", email=email, password_hash="synthetic")
    account = add(connection, Account, **account_values(owner))
    goal = add(connection, FinancialGoal, **goal_values(owner))
    return dict(owner=owner, account=account, goal=goal)


def allocation_values(resources, **overrides):
    return (
        dict(
            user_id=resources["owner"],
            account_id=resources["account"],
            goal_id=resources["goal"],
            amount=Decimal("500.00"),
            allocation_date=date(2026, 2, 1),
        )
        | overrides
    )


def test_orm_round_trip_signed_money_relationships_utc_and_goal_update(connection):
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        owner = User(name="Synthetic owner", email="owner@example.test", password_hash="synthetic")
        account = Account(**account_values(None), user=owner)
        original = datetime(2000, 1, 1, tzinfo=UTC)
        goal = FinancialGoal(
            **goal_values(None, name="  Display goal  "),
            user=owner,
            description="Synthetic description",
            target_date=date(2001, 2, 3),
            created_at=original,
            updated_at=original,
        )
        reserve = GoalAllocation(
            user=owner,
            account=account,
            goal=goal,
            amount=Decimal("500.10"),
            allocation_date=date(2026, 2, 1),
        )
        withdraw = GoalAllocation(
            user=owner,
            account=account,
            goal=goal,
            amount=Decimal("-100.05"),
            allocation_date=date(2026, 2, 2),
            notes="Synthetic withdrawal",
        )
        session.add_all([reserve, withdraw])
        session.commit()
        session.expire_all()
        assert owner.financial_goals == [goal]
        assert (
            set(owner.goal_allocations)
            == set(account.goal_allocations)
            == set(goal.allocations)
            == {reserve, withdraw}
        )
        assert goal.name == "Display goal" and goal.target_date == date(2001, 2, 3)
        assert goal.target_amount == Decimal("1000.00") and goal.status == "active"
        assert goal.description == "Synthetic description"
        assert reserve.user_id == withdraw.user_id == goal.user_id == owner.id
        assert reserve.account_id == withdraw.account_id == account.id
        assert reserve.goal_id == withdraw.goal_id == goal.id
        assert reserve.amount == Decimal("500.10") and withdraw.amount == Decimal("-100.05")
        assert reserve.notes is None and withdraw.notes == "Synthetic withdrawal"
        assert reserve.allocation_date == date(2026, 2, 1)
        assert withdraw.allocation_date == date(2026, 2, 2)
        for record in (goal, reserve, withdraw):
            assert isinstance(record.id, uuid.UUID) and record.id.version == 4
            assert record.created_at.utcoffset() == timedelta(0)
        assert isinstance(goal.target_amount, Decimal) and isinstance(withdraw.amount, Decimal)
        goal.description = "Changed synthetic description"
        session.commit()
        session.refresh(goal)
        assert goal.created_at == original and goal.updated_at > original
        assert goal.updated_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("status", ["active", "completed", "cancelled"])
def test_goal_statuses_optional_fields_and_repeated_names(connection, status):
    resources = seed(connection)
    goal_id = add(connection, FinancialGoal, **goal_values(resources["owner"], status=status))
    row = connection.execute(select(FinancialGoal).where(FinancialGoal.id == goal_id)).one()
    assert row.status == status and row.target_date is row.description is None


@pytest.mark.parametrize(
    "model,field", [(FinancialGoal, "target_amount"), (GoalAllocation, "amount")]
)
@pytest.mark.parametrize("value", [Decimal("0.01"), Decimal("0.10"), Decimal("9999999999999.99")])
def test_positive_decimal_boundaries_round_trip(connection, model, field, value):
    resources = seed(connection)
    values = (
        goal_values(resources["owner"]) if model is FinancialGoal else allocation_values(resources)
    )
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = model(**(values | {field: value}))
        session.add(record)
        session.commit()
        session.refresh(record)
        assert getattr(record, field) == value and isinstance(getattr(record, field), Decimal)


@pytest.mark.parametrize(
    "value", [Decimal("-0.01"), Decimal("-0.10"), Decimal("-9999999999999.99")]
)
def test_negative_allocation_boundaries_round_trip(connection, value):
    resources = seed(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = GoalAllocation(**allocation_values(resources, amount=value))
        session.add(record)
        session.commit()
        session.refresh(record)
        assert record.amount == value and isinstance(record.amount, Decimal)


@pytest.mark.parametrize(
    "model,field", [(FinancialGoal, "target_amount"), (GoalAllocation, "amount")]
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        True,
        0.1,
        "1.00",
        Decimal("0"),
        Decimal("-0.00"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("0.001"),
        Decimal("-0.001"),
        Decimal("10000000000000"),
        Decimal("-10000000000000"),
        Decimal("1e1000000"),
        Decimal("-1e1000000"),
        Decimal("1e-1000000"),
        Decimal("-1e-1000000"),
    ],
)
def test_orm_rejects_invalid_or_inexact_money(model, field, value):
    with pytest.raises(ValueError, match="finite Decimal"):
        model(**{field: value})


def test_goal_reuses_positive_validator_and_rejects_negative_target():
    with pytest.raises(ValueError, match="positive finite Decimal"):
        FinancialGoal(target_amount=Decimal("-0.01"))


@pytest.mark.parametrize("value", [None, "", " ", "\t\n", True])
def test_orm_rejects_blank_or_invalid_goal_name(value):
    with pytest.raises(ValueError, match="Goal name"):
        FinancialGoal(name=value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"user_id": uuid.UUID(int=1)},
        {"name": None},
        {"name": ""},
        {"name": " "},
        {"name": "n" * 151},
        {"target_amount": None},
        {"target_amount": Decimal("0")},
        {"target_amount": Decimal("-0.01")},
        {"target_amount": Decimal("NaN")},
        {"target_amount": Decimal("Infinity")},
        {"target_amount": Decimal("-Infinity")},
        {"target_amount": Decimal("10000000000000")},
        {"status": None},
        {"status": "planned"},
    ],
)
def test_database_rejects_invalid_goals(connection, overrides):
    resources = seed(connection)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(
            insert(FinancialGoal).values(**goal_values(resources["owner"], **overrides))
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": None},
        {"user_id": uuid.UUID(int=1)},
        {"account_id": None},
        {"goal_id": None},
        {"account_id": uuid.UUID(int=1)},
        {"goal_id": uuid.UUID(int=1)},
        {"amount": None},
        {"amount": Decimal("0")},
        {"amount": Decimal("NaN")},
        {"amount": Decimal("Infinity")},
        {"amount": Decimal("-Infinity")},
        {"amount": Decimal("10000000000000")},
        {"amount": Decimal("-10000000000000")},
        {"allocation_date": None},
        {"notes": "n" * 256},
    ],
)
def test_database_rejects_invalid_allocations(connection, overrides):
    resources = seed(connection)
    with pytest.raises((IntegrityError, DataError)), connection.begin_nested():
        connection.execute(
            insert(GoalAllocation).values(**allocation_values(resources, **overrides))
        )


@pytest.mark.parametrize("field,resource", [("account_id", "account"), ("goal_id", "goal")])
def test_database_rejects_cross_owner_allocation_references(connection, field, resource):
    resources = seed(connection)
    other = seed(connection, "other@example.test")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            insert(GoalAllocation).values(
                **allocation_values(resources, **{field: other[resource]})
            )
        )


@pytest.mark.parametrize(
    "reference,model,resource", [("account", Account, "account"), ("goal", FinancialGoal, "goal")]
)
def test_orm_reference_cannot_silently_reassign_allocation_owner(
    connection, reference, model, resource
):
    resources = seed(connection)
    other = seed(connection, "other@example.test")
    with Session(
        bind=connection, join_transaction_mode="create_savepoint", autoflush=False
    ) as session:
        record = GoalAllocation(**allocation_values(resources))
        record.user = session.get(User, resources["owner"])
        setattr(record, reference, session.get(model, other[resource]))
        session.add(record)
        with pytest.raises(IntegrityError):
            session.flush()
        assert record.user_id == resources["owner"]
        assert getattr(record, reference + "_id") == other[resource]
        session.rollback()


@pytest.mark.parametrize("parent", [User, Account, FinancialGoal])
def test_deleting_loaded_allocation_references_is_restricted(connection, parent):
    resources = seed(connection)
    allocation_id = add(connection, GoalAllocation, **allocation_values(resources))
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        record = session.get(GoalAllocation, allocation_id)
        assert (
            record.user.goal_allocations
            == record.account.goal_allocations
            == record.goal.allocations
            == [record]
        )
        target = {User: record.user, Account: record.account, FinancialGoal: record.goal}[parent]
        session.delete(target)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(GoalAllocation, allocation_id) is not None


def test_goal_without_allocations_still_restricts_owner_deletion(connection):
    owner_id = add(
        connection,
        User,
        name="Synthetic owner",
        email="owner@example.test",
        password_hash="synthetic",
    )
    goal_id = add(connection, FinancialGoal, **goal_values(owner_id))
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        owner = session.get(User, owner_id)
        assert owner.financial_goals[0].id == goal_id
        session.delete(owner)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.get(FinancialGoal, goal_id) is not None


def test_allocations_do_not_create_ledger_entries_change_opening_balance_or_goal_status(connection):
    resources = seed(connection)
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        for amount in (Decimal("500.00"), Decimal("-125.00")):
            session.add(GoalAllocation(**allocation_values(resources, amount=amount)))
        session.commit()
        assert session.scalars(select(Transaction)).all() == []
        assert session.scalars(select(Transfer)).all() == []
        assert session.scalar(select(Account.opening_balance)) == Decimal("10000.00")
        assert session.scalar(select(FinancialGoal.status)) == "active"


def test_upgrade_existing_data_downgrade_preserves_all_prior_values_and_reupgrade_is_clean(
    connection,
):
    config = Config(str(CONFIG_PATH))
    config.attributes["connection"] = connection
    command.downgrade(config, "0005_transactions_transfers")
    owner = add(
        connection,
        User,
        name="Synthetic owner",
        email="owner@example.test",
        password_hash="synthetic",
    )
    accounts = [add(connection, Account, **account_values(owner)) for _ in range(2)]
    category = add(connection, Category, user_id=owner, name="Synthetic category", type="expense")
    add(
        connection,
        UserSession,
        user_id=owner,
        refresh_token_hash="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    job = add(
        connection,
        ImportJob,
        user_id=owner,
        account_id=accounts[0],
        filename="synthetic.csv",
        file_checksum="a" * 64,
    )
    row = add(
        connection,
        ImportRow,
        user_id=owner,
        account_id=accounts[0],
        import_job_id=job,
        row_number=1,
    )
    add(
        connection,
        Transaction,
        user_id=owner,
        account_id=accounts[0],
        category_id=category,
        description="Synthetic expense",
        amount=Decimal("10.00"),
        type="expense",
        status="posted",
        effective_date=date(2026, 2, 1),
        import_row_id=row,
    )
    add(
        connection,
        Transfer,
        user_id=owner,
        from_account_id=accounts[0],
        to_account_id=accounts[1],
        amount=Decimal("1.00"),
        status="planned",
        effective_date=date(2026, 2, 1),
    )
    prior_tables = (
        "users",
        "user_sessions",
        "accounts",
        "categories",
        "import_jobs",
        "import_rows",
        "transactions",
        "transfers",
    )
    before = {
        table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
        for table in prior_tables
    }
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    goal = add(connection, FinancialGoal, **goal_values(owner))
    add(
        connection,
        GoalAllocation,
        user_id=owner,
        account_id=accounts[0],
        goal_id=goal,
        amount=Decimal("5.00"),
        allocation_date=date(2026, 2, 1),
    )
    command.check(config)
    command.downgrade(config, "0005_transactions_transfers")
    assert set(inspect(connection).get_table_names()) == {"alembic_version", *prior_tables}
    after = {
        table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
        for table in prior_tables
    }
    assert before == after
    command.upgrade(config, "head")
    command.check(config)
