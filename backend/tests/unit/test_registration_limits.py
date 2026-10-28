"""Resource limits use deterministic time and bounded process-local storage."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.core.config import Settings
from app.core.registration_limits import RegistrationLimits, RegistrationMiddleware


def test_fixed_window_expiration_and_capacity():
    now = [100.0]
    limits = RegistrationLimits(
        Settings(_env_file=None, registration_client_capacity=1), lambda: now[0]
    )
    assert [limits.admit("one") for _ in range(6)] == [0, 0, 0, 0, 0, 60]
    assert limits.admit("two") == 60
    assert len(limits.clients) == 1
    now[0] += 59.1
    assert limits.admit("one") == 1
    now[0] += 0.9
    assert limits.admit("two") == 0
    assert "one" not in limits.clients
    limits.clear()
    assert not limits.clients


def test_thread_safe_rate_and_nonblocking_hash_slots():
    limits = RegistrationLimits(Settings(_env_file=None))
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(limits.admit, ["same"] * 30))
    assert results.count(0) == 5
    assert limits.hash_slots.acquire(blocking=False)
    assert limits.hash_slots.acquire(blocking=False)
    assert not limits.hash_slots.acquire(blocking=False)
    limits.hash_slots.release()
    assert limits.hash_slots.acquire(blocking=False)
    limits.hash_slots.release()
    limits.hash_slots.release()


def test_chunked_body_limit_ignores_dishonest_content_length():
    async def run():
        called = False
        output = []
        chunks = iter(
            [
                {"type": "http.request", "body": b"a" * 9000, "more_body": True},
                {"type": "http.request", "body": b"b" * 9000, "more_body": True},
            ]
        )

        async def receive():
            return next(chunks)

        async def send(message):
            output.append(message)

        async def app(scope, receive, send):
            nonlocal called
            called = True

        limits = RegistrationLimits(Settings(_env_file=None))
        middleware = RegistrationMiddleware(app, limits, 16384)
        await middleware(
            {
                "type": "http",
                "path": "/api/v1/auth/register",
                "method": "POST",
                "client": ("synthetic", 1),
                "headers": [(b"content-type", b"application/json"), (b"content-length", b"1")],
            },
            receive,
            send,
        )
        assert not called
        assert output[0]["status"] == 413
        assert (b"cache-control", b"no-store") in output[0]["headers"]

    asyncio.run(run())
