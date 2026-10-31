"""Representative profile boundaries, without a cross-product of equivalent inputs."""

import pytest
from pydantic import ValidationError

from app.schemas.users import ProfileUpdateInput


def test_profile_normalization_and_private_password():
    data = ProfileUpdateInput(
        name="  Ana  ", email=" NEW@EXAMPLE.COM ", current_password="  synthetic password  "
    )
    assert data.name == "Ana" and data.email == "new@example.com"
    assert data.current_password.get_secret_value() == "  synthetic password  "
    assert "synthetic password" not in repr(data) + data.model_dump_json()
    assert ProfileUpdateInput(name="Ana").email is None


def test_invalid_profile_shapes_are_rejected():
    for body in (
        {},
        {"name": None},
        {"name": " "},
        {"name": "x" * 121},
        {"email": "invalid"},
        {"email": None},
        {"name": "Ana", "user_id": "client-must-not-select-owner"},
        {"current_password": "synthetic password"},
        {"email": "new@example.com", "current_password": None},
    ):
        with pytest.raises(ValidationError):
            ProfileUpdateInput(**body)
