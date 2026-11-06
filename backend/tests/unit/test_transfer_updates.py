"""Strict transfer patches preserve the original creation representation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.transfers import TransferInput, TransferUpdateInput


def test_transfer_patch_money_nulls_and_creation_identity_stay_strict():
    original = {
        "from_account_id": str(uuid4()),
        "to_account_id": str(uuid4()),
        "amount": "500.00",
        "status": "planned",
        "effective_date": "2026-01-04",
        "description": None,
    }
    assert TransferInput(**original).model_dump(mode="json") == original
    assert TransferUpdateInput(description="  Revised  ").model_dump(
        mode="json", exclude_unset=True
    ) == {"description": "Revised"}
    assert TransferUpdateInput(description=None).model_dump(mode="json", exclude_unset=True) == {
        "description": None
    }
    for invalid in (
        {},
        {"amount": None},
        {"amount": 1.1},
        {"amount": "0.00"},
        {"amount": "-1.00"},
        {"amount": "0.001"},
        {"from_account_id": None},
        {"effective_date": None},
        {"status": "posted"},
        {"user_id": str(uuid4())},
        {"description": "   "},
        {
            "from_account_id": original["from_account_id"],
            "to_account_id": original["from_account_id"],
        },
    ):
        with pytest.raises(ValidationError):
            TransferUpdateInput(**invalid)
