"""Representative financial transport boundaries without Cartesian test matrices."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.transactions import TransactionInput

BODY = {
    "account_id": str(uuid4()),
    "category_id": str(uuid4()),
    "description": " Synthetic ",
    "type": "expense",
    "status": "posted",
    "amount": "0.1",
    "effective_date": "2026-01-02",
}


def test_transaction_input_preserves_exact_money_and_calendar_date():
    value = TransactionInput(**BODY)
    assert value.model_dump(mode="json")["amount"] == "0.10"
    assert value.model_dump()["amount"] == Decimal("0.10")
    assert value.description == "Synthetic" and value.effective_date.isoformat() == "2026-01-02"


def test_transaction_input_rejects_invalid_financial_values_and_client_ownership():
    for change in (
        {"amount": 0.1},
        {"amount": "0"},
        {"amount": "-1.00"},
        {"amount": "1.001"},
        {"amount": "NaN"},
        {"amount": "10000000000000.00"},
        {"status": "pending"},
        {"description": " "},
        {"effective_date": "2026-02-30"},
        {"account_id": "other"},
        {"user_id": str(uuid4())},
        {"import_row_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            TransactionInput(**(BODY | change))
