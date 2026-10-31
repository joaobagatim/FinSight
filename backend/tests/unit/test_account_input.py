"""Representative account input boundaries; model money matrices already exist."""

import pytest
from pydantic import ValidationError

from app.schemas.accounts import AccountInput

BODY = {
    "name": " Synthetic account ",
    "type": "checking",
    "opening_balance": "-10.25",
    "opening_date": "2026-01-01",
}


def test_account_input_preserves_decimal_and_normalizes_identity():
    data = AccountInput(**BODY)
    assert data.name == "Synthetic account" and data.currency == "BRL"
    assert data.model_dump(mode="json")["opening_balance"] == "-10.25"
    assert (
        AccountInput(**(BODY | {"opening_balance": "-0.00"})).model_dump(mode="json")[
            "opening_balance"
        ]
        == "0.00"
    )
    assert (
        AccountInput(**(BODY | {"opening_balance": "0.1"})).model_dump(mode="json")[
            "opening_balance"
        ]
        == "0.10"
    )


def test_account_input_rejects_unsafe_money_and_owner_selection():
    for change in (
        {"opening_balance": 0.1},
        {"opening_balance": "1.001"},
        {"opening_balance": "NaN"},
        {"opening_balance": "10000000000000.00"},
        {"opening_date": "2026-02-30"},
        {"name": " "},
        {"type": "credit_card"},
        {"currency": "USD"},
        {"user_id": "synthetic-owner"},
    ):
        with pytest.raises(ValidationError):
            AccountInput(**(BODY | change))
