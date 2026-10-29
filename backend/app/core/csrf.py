"""Signed double-submit primitives; transport must supply a verified binding."""

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, SecretStr, TypeAdapter, ValidationError

from app.core.config import Settings
from app.core.refresh_tokens import (
    InvalidRefreshToken,
    generate_refresh_token,
    refresh_token_digest,
)

_ORIGIN = TypeAdapter(AnyHttpUrl)
_TOKEN = re.compile(r"v1\.([1-9][0-9]{0,11})\.([A-Za-z0-9_-]{43})\.([A-Za-z0-9_-]{43})")


class CsrfRejected(Exception):
    def __init__(self):
        super().__init__("CSRF verification failed")


class CsrfConfigurationError(Exception):
    def __init__(self):
        super().__init__("CSRF signing configuration unavailable")


def _raw(value: str | SecretStr) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


class CsrfService:
    def __init__(
        self, settings: Settings, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ):
        if settings.auth_csrf_signing_key is None:
            raise CsrfConfigurationError()
        self._key = bytes.fromhex(settings.auth_csrf_signing_key.get_secret_value())
        self._ttl = settings.auth_csrf_ttl_seconds
        self._origins = frozenset(str(origin) for origin in settings.auth_allowed_origins)
        self._clock = clock

    def _now(self) -> int:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise CsrfConfigurationError()
        return int(now.timestamp())

    def check_origin(self, origin: str | None) -> None:
        if not isinstance(origin, str) or len(origin) > 2048 or not origin.isascii():
            raise CsrfRejected()
        # Browser Origin is serialized without a path or a trailing slash.
        if origin != origin.strip() or origin.endswith("/"):
            raise CsrfRejected()
        try:
            parsed = _ORIGIN.validate_python(origin)
            Settings.validate_origins([parsed])
        except (ValidationError, ValueError):
            raise CsrfRejected() from None
        if origin != str(parsed).rstrip("/") or str(parsed) not in self._origins:
            raise CsrfRejected()

    @staticmethod
    def new_preauth_context() -> SecretStr:
        return generate_refresh_token()

    @staticmethod
    def _binding(purpose: Literal["preauth", "session"], binding: SecretStr | UUID) -> str:
        if purpose == "session" and isinstance(binding, UUID) and binding.version == 4:
            return str(binding)
        if purpose == "preauth" and isinstance(binding, SecretStr):
            try:
                refresh_token_digest(binding)
            except InvalidRefreshToken:
                raise CsrfRejected() from None
            return binding.get_secret_value()
        raise CsrfRejected()

    def _mac(self, purpose: str, binding: str, expires: int, nonce: str) -> str:
        message = json.dumps(
            ["finsight-csrf-v1", purpose, binding, expires, nonce], separators=(",", ":")
        ).encode("ascii")
        return (
            base64.urlsafe_b64encode(hmac.digest(self._key, message, hashlib.sha256))
            .rstrip(b"=")
            .decode("ascii")
        )

    def issue(self, purpose: Literal["preauth", "session"], binding: SecretStr | UUID) -> SecretStr:
        bound = self._binding(purpose, binding)
        expires = self._now() + self._ttl
        nonce = generate_refresh_token().get_secret_value()
        return SecretStr(f"v1.{expires}.{nonce}.{self._mac(purpose, bound, expires, nonce)}")

    def verify(
        self,
        cookie: str | SecretStr,
        header: str | SecretStr,
        *,
        purpose: Literal["preauth", "session"],
        binding: SecretStr | UUID,
    ) -> None:
        value, submitted = _raw(cookie), _raw(header)
        if any(
            not isinstance(item, str) or not item.isascii() or not 1 <= len(item) <= 256
            for item in (value, submitted)
        ):
            raise CsrfRejected()
        if not hmac.compare_digest(value, submitted):
            raise CsrfRejected()
        match = _TOKEN.fullmatch(value)
        if match is None:
            raise CsrfRejected()
        expires, nonce, signature = match.groups()
        try:
            # The same canonical 32-byte base64url grammar applies to nonce and MAC.
            refresh_token_digest(nonce)
            refresh_token_digest(signature)
        except InvalidRefreshToken:
            raise CsrfRejected() from None
        now = self._now()
        if not now < int(expires) <= now + self._ttl:
            raise CsrfRejected()
        bound = self._binding(purpose, binding)
        if not hmac.compare_digest(signature, self._mac(purpose, bound, int(expires), nonce)):
            raise CsrfRejected()
