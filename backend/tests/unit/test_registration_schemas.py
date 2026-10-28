"""Strict registration boundaries and secret representations."""

import pytest
from pydantic import ValidationError

from app.schemas.auth import RegistrationInput

VALID = {
    "name": "Synthetic User",
    "email": "synthetic@example.com",
    "password": "synthetic password",
}


def test_identity_normalization_and_secret_representation():
    data = RegistrationInput(**(VALID | {"name": " Ana ", "email": " ANA@EXAMPLE.COM "}))
    assert data.name == "Ana"
    assert data.email == "ana@example.com"
    assert VALID["password"] not in repr(data)
    assert VALID["password"] not in data.model_dump_json()


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "a" * 121},
        {"name": 123},
        {"email": "invalid"},
        {"email": 12},
        {"email": "a" * 250 + "@example.com"},
        {"password": "a" * 14},
        {"password": "a" * 129},
        {"password": " " * 15},
        {"password": 123},
        {"password": None},
        {"password": ["synthetic"]},
        {"id": "synthetic"},
        {"user_id": "synthetic"},
        {"is_active": False},
        {"password_hash": "synthetic"},
        {"password": "a" * 15 + "\ud800"},
        {"name": "\ud800"},
    ],
)
def test_invalid_or_server_controlled_fields_are_rejected(changes):
    with pytest.raises(ValidationError):
        RegistrationInput(**(VALID | changes))


@pytest.mark.parametrize("password", ["a" * 15, "a" * 128, "  senha 🔐 sintética  "])
def test_password_boundaries_preserve_exact_value(password):
    data = RegistrationInput(**(VALID | {"password": password}))
    assert data.password.get_secret_value() == password
