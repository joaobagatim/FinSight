"""Representative goal input boundaries; money is always a decimal string."""

import pytest
from pydantic import ValidationError

from app.schemas.goals import GoalInput, GoalUpdateInput


def test_goal_contract_preserves_exact_money_optional_deadline_and_rejects_owner_selection():
    data = {"name": " Synthetic goal ", "target_amount": "100.1"}
    result = GoalInput(**data).model_dump(mode="json")
    assert result == {
        "name": "Synthetic goal",
        "target_amount": "100.10",
        "target_date": None,
        "description": None,
    }
    for change in (
        {"target_amount": 0.1},
        {"target_amount": "0.00"},
        {"target_amount": "-1.00"},
        {"target_amount": "1.001"},
        {"target_date": "2026-02-30"},
        {"name": " "},
        {"name": "unsafe\x00name"},
        {"user_id": "other"},
        {"status": "completed"},
    ):
        with pytest.raises(ValidationError):
            GoalInput(**(data | change))
    assert GoalUpdateInput(description=None, target_date=None).model_dump(exclude_unset=True) == {
        "description": None,
        "target_date": None,
    }
    for changes in (
        {},
        {"name": None},
        {"target_amount": None},
        {"status": None},
        {"status": "unknown"},
        {"user_id": "other"},
    ):
        with pytest.raises(ValidationError):
            GoalUpdateInput(**changes)
