"""Real password hashing, including parameters and preservation of user input."""

import pytest

from app.core.security import hash_password, verify_password


@pytest.mark.parametrize("password", ["a" * 15, "a" * 128, "  Senha sintética 🔐 com espaços  "])
def test_argon2id_round_trip_and_random_salts(password):
    first = hash_password(password)
    second = hash_password(password)
    assert first != second
    assert first.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert len(first) <= 255
    assert verify_password(password, first)
    assert not verify_password(password + "x", first)


def test_password_is_not_trimmed_or_unicode_normalized():
    assert not verify_password("senha com espaços", hash_password(" senha com espaços "))
    assert not verify_password("é" * 15, hash_password("e\u0301" * 15))


@pytest.mark.parametrize("encoded", ["", "invalid", "$argon2id$invalid", "$2b$invalid"])
def test_invalid_hash_is_safe(encoded):
    assert not verify_password("synthetic password", encoded)
