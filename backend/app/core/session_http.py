"""Bound session HTTP before parsing/hashing; keep registration CORS unchanged."""

import math
import threading
import time
from collections.abc import Callable

from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings

PASSWORD_CHANGE_PATH = "/api/v1/users/me/change-password"
PROFILE_PATH = "/api/v1/users/me"
ACCOUNTS_PATH = "/api/v1/accounts"
SESSION_PATHS = frozenset(
    {f"/api/v1/auth/{name}" for name in ("csrf", "login", "refresh", "logout", "me")}
    | {PASSWORD_CHANGE_PATH, PROFILE_PATH}
)
_SINGLE_HEADERS = {b"origin", b"content-type", b"x-csrf-token", b"x-csrf-bootstrap"}


def is_account_path(path: str) -> bool:
    return path == ACCOUNTS_PATH or path.startswith(ACCOUNTS_PATH + "/")


def is_session_path(path: str) -> bool:
    return path in SESSION_PATHS or is_account_path(path)


class SessionHttpLimits:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.login_rate = settings.auth_login_requests_per_minute
        self.password_rate = settings.auth_password_change_requests_per_minute
        self.rate = settings.auth_requests_per_minute
        self.capacity = settings.auth_client_capacity
        self.clients: dict[tuple[str, str], tuple[float, int]] = {}
        self.lock = threading.Lock()

    def admit(self, client: str, *, login: bool, password_change: bool = False) -> int:
        with self.lock:
            now = self.clock()
            self.clients = {key: row for key, row in self.clients.items() if row[0] > now}
            bucket = "password" if password_change else "login" if login else "session"
            rate = (
                self.password_rate if password_change else self.login_rate if login else self.rate
            )
            key = (bucket, client)
            if key not in self.clients:
                if len(self.clients) >= self.capacity:
                    return max(1, math.ceil(min(row[0] for row in self.clients.values()) - now))
                self.clients[key] = (now + 60, 1)
                return 0
            end, count = self.clients[key]
            if count >= rate:
                return max(1, math.ceil(end - now))
            self.clients[key] = (end, count + 1)
            return 0

    def clear(self) -> None:
        with self.lock:
            self.clients.clear()


class SessionHttpMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, limits: SessionHttpLimits):
        self.app = app
        self.settings = settings
        self.limits = limits

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_session_path(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def no_store(message):
            if message["type"] == "http.response.start":
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        async def reject(status: int, detail: str, retry: int | None = None):
            await JSONResponse(
                {"detail": detail},
                status_code=status,
                headers={"Retry-After": str(retry)} if retry else None,
            )(scope, receive, no_store)

        seen = set()
        for key, _ in scope["headers"]:
            key = key.lower()
            if key in _SINGLE_HEADERS or (
                key == b"idempotency-key" and is_account_path(scope["path"])
            ):
                if key in seen:
                    await reject(403, "Authentication request rejected")
                    return
                seen.add(key)
        retry = self.limits.admit(
            (scope.get("client") or ("unknown",))[0],
            login=scope["path"] == "/api/v1/auth/login",
            password_change=scope["path"] == PASSWORD_CHANGE_PATH
            or (scope["path"] == PROFILE_PATH and scope["method"] == "PATCH"),
        )
        if retry:
            await reject(429, "Authentication limit reached", retry)
            return
        if scope["method"] != "POST" and not (
            scope["path"] == PROFILE_PATH and scope["method"] == "PATCH"
        ):
            await self.app(scope, receive, no_store)
            return
        headers = dict(scope["headers"])
        if (
            headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            != b"application/json"
        ):
            await reject(415, "Content-Type must be application/json")
            return
        bound = (
            self.settings.auth_login_body_bytes
            if scope["path"]
            in {"/api/v1/auth/login", PASSWORD_CHANGE_PATH, PROFILE_PATH, ACCOUNTS_PATH}
            else self.settings.auth_body_bytes
        )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > bound:
                await reject(413, "Authentication body too large")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        async def replay():
            nonlocal body
            if body is not None:
                value = bytes(body)
                body = None
                return {"type": "http.request", "body": value, "more_body": False}
            return await receive()

        await self.app(scope, replay, no_store)


class SessionCorsMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.session = CORSMiddleware(
            app,
            allow_origins=[str(origin).rstrip("/") for origin in settings.auth_allowed_origins],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Accept", "Content-Type", "X-CSRF-Token", "X-CSRF-Bootstrap"],
        )
        self.other = CORSMiddleware(
            app,
            allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Accept", "Content-Type"],
        )
        self.profile = CORSMiddleware(
            app,
            allow_origins=[str(origin).rstrip("/") for origin in settings.auth_allowed_origins],
            allow_credentials=True,
            allow_methods=["GET", "PATCH"],
            allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
        )
        self.accounts = CORSMiddleware(
            app,
            allow_origins=[str(origin).rstrip("/") for origin in settings.auth_allowed_origins],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Accept", "Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        handler = self.session if scope.get("path") in SESSION_PATHS else self.other
        if scope.get("path") == PROFILE_PATH:
            handler = self.profile
        if is_account_path(scope.get("path", "")):
            handler = self.accounts
        if scope["type"] == "http" and is_session_path(scope["path"]):

            async def no_store(message):
                if message["type"] == "http.response.start":
                    message["headers"] = [
                        (key, value)
                        for key, value in message["headers"]
                        if key.lower() != b"cache-control"
                    ] + [(b"cache-control", b"no-store")]
                await send(message)

            seen = set()
            for key, _ in scope["headers"]:
                key = key.lower()
                if key in _SINGLE_HEADERS or (
                    key == b"idempotency-key" and is_account_path(scope["path"])
                ):
                    if key in seen:
                        await JSONResponse(
                            {"detail": "Authentication request rejected"}, status_code=403
                        )(scope, receive, no_store)
                        return
                    seen.add(key)
            await handler(scope, receive, no_store)
        else:
            await handler(scope, receive, send)
