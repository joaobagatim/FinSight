"""Internal access JWT primitives; callers must still authorize users and sessions.

No routes, cookies or session persistence are provided by this module. A valid
signature does not prove that the user is active or that the session is live.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from pydantic import SecretStr

from app.core.config import Settings

ALGORITHM = "HS256"
TOKEN_TYPE = "finsight-access+jwt"
TOKEN_USE = "access"
MAX_TOKEN_BYTES = 4096
REQUIRED_CLAIMS = frozenset({"sub", "sid", "iss", "aud", "iat", "nbf", "exp", "jti", "token_use"})


class _UTF8JSONEncoder(json.JSONEncoder):
    """Keep allowed Unicode identifiers within the token byte budget."""

    def __init__(self, **kwargs):
        super().__init__(**(kwargs | {"ensure_ascii": False}))


class TokenConfigurationError(Exception):
    """Signing configuration is unavailable; never substitute a default key."""


class InvalidAccessToken(Exception):
    """Uniform invalid-token signal without credentials or parser details."""


@dataclass(frozen=True, repr=False)
class AccessTokenClaims:
    user_id: UUID
    session_id: UUID
    token_id: UUID
    issuer: str
    audience: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime


def _uuid4_claim(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("Invalid UUID claim")
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Invalid UUID claim")
    return parsed


class AccessTokenService:
    """Use one configured signing key and a fixed algorithm for this API."""

    def __init__(self, settings: Settings):
        if settings.jwt_signing_key is None:
            raise TokenConfigurationError("JWT signing key is not configured")
        self._key = bytes.fromhex(settings.jwt_signing_key.get_secret_value())
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl = settings.jwt_access_ttl_seconds

    def issue(self, user_id: UUID, session_id: UUID) -> SecretStr:
        """Called by a future authenticated login service, never directly by request data."""
        if any(
            not isinstance(value, UUID) or value.version != 4 for value in (user_id, session_id)
        ):
            raise ValueError("User and session IDs must be UUIDv4")
        now = int(datetime.now(UTC).timestamp())
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now,
            "nbf": now,
            "exp": now + self._ttl,
            "jti": str(uuid4()),
            "token_use": TOKEN_USE,
        }
        encoded = jwt.encode(
            payload,
            self._key,
            algorithm=ALGORITHM,
            headers={"typ": TOKEN_TYPE},
            json_encoder=_UTF8JSONEncoder,
        )
        return SecretStr(encoded)

    def verify(self, token: str | SecretStr) -> AccessTokenClaims:
        """Verify cryptographic claims only; no database/user/session lookup occurs here."""
        value = token.get_secret_value() if isinstance(token, SecretStr) else token
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_TOKEN_BYTES
            or not value.isascii()
        ):
            raise InvalidAccessToken("Invalid access token")
        try:
            header = jwt.get_unverified_header(value)
            if header != {"alg": ALGORITHM, "typ": TOKEN_TYPE}:
                raise ValueError("Invalid token header")
            payload = jwt.decode(
                value,
                self._key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                leeway=0,
                options={
                    "require": sorted(REQUIRED_CLAIMS),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "strict_aud": True,
                },
            )
            if set(payload) != REQUIRED_CLAIMS or payload["token_use"] != TOKEN_USE:
                raise ValueError("Invalid token purpose or claims")
            if any(type(payload[name]) is not int for name in ("iat", "nbf", "exp")):
                raise ValueError("Invalid token timestamps")
            if (
                payload["nbf"] != payload["iat"]
                or not 0 < payload["exp"] - payload["iat"] <= self._ttl
            ):
                raise ValueError("Invalid token lifetime")
            return AccessTokenClaims(
                user_id=_uuid4_claim(payload["sub"]),
                session_id=_uuid4_claim(payload["sid"]),
                token_id=_uuid4_claim(payload["jti"]),
                issuer=payload["iss"],
                audience=payload["aud"],
                issued_at=datetime.fromtimestamp(payload["iat"], UTC),
                not_before=datetime.fromtimestamp(payload["nbf"], UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError, RecursionError):
            raise InvalidAccessToken("Invalid access token") from None
