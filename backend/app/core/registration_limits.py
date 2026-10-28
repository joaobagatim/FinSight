"""Bound registration body size, request rate and concurrent hashing per process."""

import math
import threading
import time
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.error_handlers import REGISTRATION_PATH
from app.core.config import Settings


class RegistrationLimits:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.rate = settings.registration_requests_per_minute
        self.capacity = settings.registration_client_capacity
        self.clients: dict[str, tuple[float, int]] = {}
        self.lock = threading.Lock()
        self.hash_slots = threading.BoundedSemaphore(settings.registration_concurrent_hashes)

    def admit(self, client: str) -> int:
        """Return zero when admitted, otherwise seconds until the next attempt."""
        with self.lock:
            now = self.clock()
            self.clients = {key: row for key, row in self.clients.items() if row[0] > now}
            if client not in self.clients:
                if len(self.clients) >= self.capacity:
                    return max(1, math.ceil(min(row[0] for row in self.clients.values()) - now))
                self.clients[client] = (now + 60, 1)
                return 0
            end, count = self.clients[client]
            if count >= self.rate:
                return max(1, math.ceil(end - now))
            self.clients[client] = (end, count + 1)
            return 0

    def clear(self) -> None:
        with self.lock:
            self.clients.clear()


class RegistrationMiddleware:
    def __init__(self, app: ASGIApp, limits: RegistrationLimits, body_bytes: int):
        self.app = app
        self.limits = limits
        self.body_bytes = body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != REGISTRATION_PATH:
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
            headers = {"Retry-After": str(retry)} if retry else None
            await JSONResponse({"detail": detail}, status_code=status, headers=headers)(
                scope, receive, no_store
            )

        if scope["method"] != "POST":
            await self.app(scope, receive, no_store)
            return
        retry = self.limits.admit((scope.get("client") or ("unknown",))[0])
        if retry:
            await reject(429, "Registration limit reached", retry)
            return
        headers = dict(scope["headers"])
        if (
            headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
            != b"application/json"
        ):
            await reject(415, "Content-Type must be application/json")
            return
        # Read bounded actual chunks, regardless of absent or dishonest Content-Length.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.body_bytes:
                await reject(413, "Registration body too large")
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
