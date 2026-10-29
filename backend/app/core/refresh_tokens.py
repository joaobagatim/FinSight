"""Opaque refresh token primitives; no sessions, cookies or rotation are issued here."""

import base64
import binascii
import hashlib
import re
import secrets

from pydantic import SecretStr

TOKEN_BYTES = 32
TOKEN_LENGTH = 43
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class InvalidRefreshToken(Exception):
    """Uniform signal that never includes the supplied credential."""


def generate_refresh_token() -> SecretStr:
    return SecretStr(secrets.token_urlsafe(TOKEN_BYTES))


def refresh_token_digest(token: str | SecretStr) -> str:
    """Digest only a canonical base64url encoding of 32 random bytes."""
    value = token.get_secret_value() if isinstance(token, SecretStr) else token
    if (
        not isinstance(value, str)
        or len(value) != TOKEN_LENGTH
        or not _TOKEN_PATTERN.fullmatch(value)
    ):
        raise InvalidRefreshToken("Invalid refresh token")
    try:
        decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
        canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        if len(decoded) != TOKEN_BYTES or canonical != value:
            raise InvalidRefreshToken("Invalid refresh token")
    except (binascii.Error, ValueError):
        raise InvalidRefreshToken("Invalid refresh token") from None
    return hashlib.sha256(value.encode("ascii")).hexdigest()
