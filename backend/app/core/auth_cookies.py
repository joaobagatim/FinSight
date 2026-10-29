"""Cookie transport policy only; no routes are registered by these helpers."""

import ipaddress
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.services.session_types import SessionGrant

CookieKind = Literal["access", "refresh", "preauth", "csrf"]
_KINDS = ("access", "refresh", "preauth", "csrf")


class CookiePolicyRejected(Exception):
    def __init__(self):
        super().__init__("Authentication cookie policy rejected")


class AuthCookies:
    def __init__(
        self,
        settings: Settings,
        request: Request,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._secure = settings.auth_cookie_secure
        self._clock = clock
        self._csrf_ttl = settings.auth_csrf_ttl_seconds
        self._request = request
        if self._secure:
            if request.url.scheme != "https":
                raise CookiePolicyRejected()
        else:
            peer = request.client.host if request.client is not None else ""
            try:
                local_peer = ipaddress.ip_address(peer).is_loopback
            except ValueError:
                local_peer = False
            if (
                settings.environment not in {"development", "test"}
                or request.url.scheme not in {"http", "https"}
                or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or not local_peer
            ):
                raise CookiePolicyRejected()

    def name(self, kind: CookieKind) -> str:
        if kind not in _KINDS:
            raise CookiePolicyRejected()
        return f"__Host-finsight-{kind}" if self._secure else f"finsight_{kind}"

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise CookiePolicyRejected()
        return now

    def _set(
        self, response: Response, kind: CookieKind, value: SecretStr, expires: datetime
    ) -> None:
        if not isinstance(value, SecretStr):
            raise CookiePolicyRejected()
        raw = value.get_secret_value()
        if (
            not raw
            or len(raw) > 4096
            or any(ord(char) < 33 or ord(char) > 126 or char in '";,\\' for char in raw)
        ):
            raise CookiePolicyRejected()
        now = self._now()
        if expires.tzinfo is None or expires.utcoffset() != timedelta(0):
            raise CookiePolicyRejected()
        age = int((expires - now).total_seconds())
        if age <= 0:
            raise CookiePolicyRejected()
        response.set_cookie(
            self.name(kind),
            raw,
            max_age=age,
            expires=expires,
            path="/",
            secure=self._secure,
            httponly=kind != "csrf",
            samesite="lax",
        )

    def set_grant(self, response: Response, grant: SessionGrant) -> None:
        for deadline in (grant.access_expires_at, grant.context.session_expires_at):
            if deadline.tzinfo is None or deadline.utcoffset() != timedelta(0):
                raise CookiePolicyRejected()
        access_expiry = min(grant.access_expires_at, grant.context.session_expires_at)
        # Validate both deadlines before mutating the response.
        now = self._now()
        if any(
            int((deadline - now).total_seconds()) <= 0
            for deadline in (access_expiry, grant.context.session_expires_at)
        ):
            raise CookiePolicyRejected()
        pending = Response()
        self._set(pending, "access", grant.access_token, access_expiry)
        self._set(pending, "refresh", grant.refresh_token, grant.context.session_expires_at)
        response.raw_headers.extend(
            (name, value) for name, value in pending.raw_headers if name == b"set-cookie"
        )

    def set_csrf(self, response: Response, token: SecretStr, *, expires_at: datetime) -> None:
        self._context_deadline(expires_at)
        self._set(response, "csrf", token, expires_at)

    def set_preauth(self, response: Response, context: SecretStr, *, expires_at: datetime) -> None:
        self._context_deadline(expires_at)
        self._set(response, "preauth", context, expires_at)

    def _context_deadline(self, expires_at: datetime) -> None:
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() != timedelta(0)
            or expires_at > self._now() + timedelta(seconds=self._csrf_ttl)
        ):
            raise CookiePolicyRejected()

    def clear(self, response: Response, *, kinds: tuple[CookieKind, ...] = _KINDS) -> None:
        for kind in kinds:
            response.delete_cookie(
                self.name(kind),
                path="/",
                secure=self._secure,
                httponly=kind != "csrf",
                samesite="lax",
            )

    def read(self) -> dict[str, SecretStr]:
        headers = [
            value for key, value in self._request.scope["headers"] if key.lower() == b"cookie"
        ]
        if sum(len(value) for value in headers) > 16384:
            raise CookiePolicyRejected()
        names = {self.name(kind): kind for kind in _KINDS}
        found = {}
        for value in headers:
            try:
                raw = value.decode("ascii")
            except UnicodeDecodeError:
                raise CookiePolicyRejected() from None
            for part in raw.split(";"):
                name, separator, token = part.strip().partition("=")
                if name not in names:
                    continue
                kind = names[name]
                if (
                    kind in found
                    or not separator
                    or not token
                    or len(token) > 4096
                    or any(ord(char) < 33 or ord(char) > 126 or char in '";,\\' for char in token)
                ):
                    raise CookiePolicyRejected()
                found[kind] = SecretStr(token)
        return found
