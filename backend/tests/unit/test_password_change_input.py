"""Password policy and private serialization/HTTP validation for RF-007."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.schemas.users import PasswordChangeInput

PATH = "/api/v1/users/me/change-password"


def test_password_values_preserve_unicode_and_whitespace():
    current = "  synthetic current password  "
    new = "\u00e9" * 128
    data = PasswordChangeInput(current_password=current, new_password=new)
    assert data.current_password.get_secret_value() == current
    assert data.new_password.get_secret_value() == new
    assert current not in repr(data) + data.model_dump_json()
    assert new not in repr(data) + data.model_dump_json()
    schema = PasswordChangeInput.model_json_schema()
    assert schema["additionalProperties"] is False
    assert all(
        schema["properties"][name]["writeOnly"] for name in ("current_password", "new_password")
    )


@pytest.mark.parametrize(
    "value",
    [None, 1, True, {}, [], "", "short", " " * 16, "x" * 129, "\ud800" * 16],
    ids=[f"input-{i}" for i in range(10)],
)
@pytest.mark.parametrize("field", ["current_password", "new_password"])
def test_invalid_password_input_rejected(field, value):
    body = {
        "current_password": "synthetic current password",
        "new_password": "synthetic new password",
    }
    body[field] = value
    with pytest.raises(ValidationError):
        PasswordChangeInput(**body)


def test_extra_identity_and_sensitive_inputs_are_not_echoed():
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_allowed_origins=["https://app.example.test"],
    )
    with TestClient(create_app(settings), base_url="https://api.example.test") as client:
        marker = "synthetic-private-marker"
        response = client.post(
            PATH,
            json={"current_password": marker, "new_password": marker, "user_id": marker},
            headers={"Origin": "https://app.example.test"},
        )
        # Missing session/CSRF may reject before body validation; neither path may echo inputs.
        assert response.status_code in (401, 403, 422)
        assert marker not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
