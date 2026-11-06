"""Representative exact-money transfer boundaries, without Cartesian matrices."""

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.transfers import TransferInput

BODY = {
    "from_account_id": str(uuid4()),
    "to_account_id": str(uuid4()),
    "amount": "0.1",
    "status": "posted",
    "effective_date": "2026-01-02",
}


def test_transfer_input_keeps_exact_money_and_rejects_unsafe_transport():
    value = TransferInput(**BODY, description=" Synthetic ")
    assert value.model_dump()["amount"] == Decimal("0.1")
    assert value.model_dump(mode="json")["amount"] == "0.10"
    assert value.description == "Synthetic"
    for change in (
        {"to_account_id": BODY["from_account_id"]},
        {"amount": 0.1},
        {"amount": "0.00"},
        {"amount": "1.001"},
        {"amount": "NaN"},
        {"status": "pending"},
        {"effective_date": "2026-02-30"},
        {"user_id": str(uuid4())},
        {"description": " "},
    ):
        with pytest.raises(ValidationError):
            TransferInput(**(BODY | change))
