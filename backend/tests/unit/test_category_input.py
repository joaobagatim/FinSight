"""Representative category boundaries without redundant input matrices."""

import pytest
from pydantic import ValidationError

from app.schemas.categories import CategoryInput, CategoryUpdateInput


def test_category_inputs_accept_safe_explicit_metadata():
    assert CategoryInput(name=" Food ", type="expense").name == "Food"
    assert CategoryUpdateInput(is_active=False).model_dump(exclude_unset=True) == {
        "is_active": False
    }
    assert CategoryUpdateInput(color=None, icon=None).model_dump(exclude_unset=True) == {
        "color": None,
        "icon": None,
    }
    assert (
        CategoryInput(name="Income", type="income", icon="briefcase", color="#12ABef").color
        == "#12ABef"
    )


def test_category_inputs_reject_owner_changes_and_unsafe_metadata():
    for data in (
        {},
        {"name": None},
        {"is_active": "false"},
        {"is_active": None},
        {"type": "income"},
        {"user_id": "other"},
        {"name": " "},
        {"color": "url(https://example.com)"},
        {"icon": "<svg>"},
    ):
        with pytest.raises(ValidationError):
            CategoryUpdateInput(**data)
