"""Exact reservation arithmetic, contract and PostgreSQL query composition."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.models import Account, FinancialGoal
from app.schemas.allocations import AllocationInput
from app.services.allocations import availability, context_query, funding


def test_reservation_contract_and_exact_totals_do_not_confuse_reserved_with_bank_money():
    day = date(2026, 1, 2)
    owner, account_id, goal_id = uuid4(), uuid4(), uuid4()
    data = {
        "account_id": str(account_id),
        "kind": "reserve",
        "amount": "10.10",
        "allocation_date": "2026-01-02",
    }
    assert AllocationInput(**data).model_dump(mode="json")["amount"] == "10.10"
    for change in (
        {"amount": 0.1},
        {"amount": "0.00"},
        {"amount": "-1.00"},
        {"amount": "1.001"},
        {"allocation_date": "2026-02-30"},
        {"user_id": str(owner)},
        {"kind": "unknown"},
        {"notes": "bad\x00note"},
    ):
        with pytest.raises(ValidationError):
            AllocationInput(**(data | change))
    goal = FinancialGoal(
        id=goal_id,
        user_id=owner,
        name="Synthetic goal",
        description=None,
        target_amount=Decimal("100.00"),
        target_date=None,
        status="active",
    )
    summary = funding(goal, Decimal("150.10"), day).model_dump(mode="json")
    assert summary["reserved_amount"] == "150.10" and summary["remaining_amount"] == "0.00"
    assert summary["excess_amount"] == "50.10" and summary["progress_percent"] == "150.10"
    assert summary["goal"]["target_amount"] == "100.00" and summary["as_of"] == "2026-01-02"
    account = Account(
        id=account_id,
        user_id=owner,
        name="Synthetic account",
        type="checking",
        currency="BRL",
        opening_balance=Decimal("0.00"),
        opening_date=date(2026, 1, 1),
        is_active=True,
    )
    result = availability(account, Decimal("-20.00"), Decimal("100.00"), day).model_dump(
        mode="json"
    )
    assert result["bank_balance"] == "-20.00" and result["free_balance"] == "-120.00"
    assert result["uncovered_reserved"] == "100.00"
    assert availability(account, Decimal("-20.00"), Decimal("0.00"), day).uncovered_reserved == 0
    assert "goal_allocations" in str(
        context_query(owner, goal_id, account_id, day).compile(dialect=postgresql.dialect())
    )
