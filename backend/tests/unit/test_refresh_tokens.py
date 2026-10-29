"""Opaque credential format, generation, digest vectors and private diagnostics."""

import base64
import re

import pytest
from pydantic import SecretStr

from app.core import refresh_tokens
from app.core.refresh_tokens import (
    InvalidRefreshToken,
    generate_refresh_token,
    refresh_token_digest,
)

SYNTHETIC_TOKEN = "A" * 43  # Canonical encoding of 32 zero bytes; never an issued session.
EXPECTED_DIGEST = "0f007385b6f9d4b7eeb2748605afe1a984a0a3bfa3f014d09e2a784ce9e5cd1a"


def test_generation_delegates_to_secure_randomness_with_32_bytes(monkeypatch):
    requested = []

    def synthetic_generator(size):
        requested.append(size)
        return SYNTHETIC_TOKEN

    monkeypatch.setattr(refresh_tokens.secrets, "token_urlsafe", synthetic_generator)
    token = generate_refresh_token()
    assert isinstance(token, SecretStr)
    assert token.get_secret_value() == SYNTHETIC_TOKEN
    assert requested == [32]


def test_generated_samples_are_distinct_and_round_trip_without_format_changes():
    samples = [generate_refresh_token() for _ in range(16)]
    assert len({sample.get_secret_value() for sample in samples}) == 16
    for sample in samples:
        raw = sample.get_secret_value()
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", raw)
        decoded = base64.b64decode(raw + "=", altchars=b"-_", validate=True)
        assert len(decoded) == 32
        assert base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() == raw
        assert re.fullmatch(r"[0-9a-f]{64}", refresh_token_digest(sample))


def test_known_vector_hashes_the_canonical_ascii_representation():
    assert refresh_token_digest(SYNTHETIC_TOKEN) == EXPECTED_DIGEST
    assert refresh_token_digest(SecretStr(SYNTHETIC_TOKEN)) == EXPECTED_DIGEST


def test_different_canonical_credentials_produce_different_digests():
    other = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
    assert refresh_token_digest(other) != refresh_token_digest(SYNTHETIC_TOKEN)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        123,
        [],
        {},
        b"A" * 43,
        "",
        "a" * 42,
        "a" * 44,
        "a" * 100000,
        SYNTHETIC_TOKEN + "=",
        " " + "A" * 42,
        "A" * 42 + "\n",
        "+" * 43,
        "/" * 43,
        "=" * 43,
        "é" * 43,
        "\ud800" * 43,
    ],
    ids=lambda value: "invalid-" + type(value).__name__,
)
def test_bad_formats_have_uniform_errors_without_echoing_input(value, caplog):
    with pytest.raises(InvalidRefreshToken) as error:
        refresh_token_digest(value)
    assert str(error.value) == "Invalid refresh token"
    assert error.value.__cause__ is None
    assert not caplog.text


@pytest.mark.parametrize("last", ["B", "C", "D"])
def test_noncanonical_unused_bits_are_rejected_even_if_decoding_is_identical(last):
    alternate = "A" * 42 + last
    assert base64.b64decode(alternate + "=", altchars=b"-_", validate=True) == b"\x00" * 32
    with pytest.raises(InvalidRefreshToken):
        refresh_token_digest(alternate)


def test_bad_or_oversized_tokens_are_rejected_before_decoding_or_hashing(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Invalid credential reached decoding or hashing")

    monkeypatch.setattr(refresh_tokens.base64, "b64decode", unexpected)
    monkeypatch.setattr(refresh_tokens.hashlib, "sha256", unexpected)
    for value in ("a" * 100000, "é" * 43, "bad"):
        with pytest.raises(InvalidRefreshToken):
            refresh_token_digest(value)


def test_secret_wrapping_and_errors_do_not_reveal_credentials(caplog):
    token = SecretStr(SYNTHETIC_TOKEN)
    assert SYNTHETIC_TOKEN not in repr(token) + str(token)
    with pytest.raises(InvalidRefreshToken) as error:
        refresh_token_digest(SecretStr(SYNTHETIC_TOKEN + "private-marker"))
    assert SYNTHETIC_TOKEN not in str(error.value) + repr(error.value) + caplog.text
    assert "private-marker" not in str(error.value) + caplog.text
