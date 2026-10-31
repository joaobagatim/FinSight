"""HTTP guards before database work, including streamed bodies and ambiguous headers."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_session_service
from app.core.config import Settings
from app.core.session_http import SessionHttpLimits, SessionHttpMiddleware
from app.main import create_app

ORIGIN = "https://app.example.test"


def settings(**kwargs):
    return Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_allowed_origins=[ORIGIN],
        cors_origins=[ORIGIN],
        **kwargs,
    )


@pytest.fixture
def client():
    with TestClient(create_app(settings()), base_url="https://api.example.test") as client:
        yield client


def bootstrap(client):
    response = client.post(
        "/api/v1/auth/csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_bootstrap_and_missing_database_are_safe(client, caplog):
    csrf = bootstrap(client)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "synthetic@example.com", "password": "synthetic password"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication temporarily unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert csrf not in response.text + caplog.text
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "headers", [{}, {"Origin": "null"}, {"Origin": "https://evil.test"}, {"Origin": ORIGIN}]
)
def test_bootstrap_rejects_origin_or_missing_header(client, headers):
    response = client.post("/api/v1/auth/csrf", json={}, headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("name", ["Origin", "Content-Type", "X-CSRF-Token", "X-CSRF-Bootstrap"])
def test_duplicate_security_headers_rejected(client, name):
    headers = [("Origin", ORIGIN), ("X-CSRF-Bootstrap", "1"), ("Content-Type", "application/json")]
    if name not in {"Origin", "Content-Type", "X-CSRF-Bootstrap"}:
        headers.append((name, "synthetic"))
    headers.append((name, "synthetic-duplicate"))
    response = client.post("/api/v1/auth/csrf", content="{}", headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_duplicate_cookie_does_not_clear_context(client):
    response = client.post(
        "/api/v1/auth/csrf",
        json={},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Bootstrap": "1",
            "Cookie": "__Host-finsight-access=a; __Host-finsight-access=b",
        },
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", ["login", "refresh", "logout"])
def test_mutations_need_csrf_before_service(client, path):
    response = client.post(
        f"/api/v1/auth/{path}",
        json=(
            {"email": "synthetic@example.com", "password": "synthetic password"}
            if path == "login"
            else {}
        ),
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


def test_validation_never_echoes_unknown_keys_or_input(client):
    csrf = bootstrap(client)
    marker = "synthetic-private-marker"
    response = client.post(
        "/api/v1/auth/login",
        json={marker: marker, "password": {marker: marker}},
        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid authentication data"}
    assert marker not in response.text


def test_cors_is_credentialed_only_for_new_paths(client):
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-csrf-token",
    }
    response = client.options("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["cache-control"] == "no-store"

    response = client.options(
        "/api/v1/auth/register",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "access-control-allow-credentials" not in response.headers
    response = client.options(
        "/api/v1/auth/refresh", headers=headers | {"Origin": "https://evil.test"}
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_duplicate_origin_preflight_is_rejected(client):
    response = client.options(
        "/api/v1/auth/refresh",
        headers=[
            ("Origin", ORIGIN),
            ("Origin", "https://evil.test"),
            ("Access-Control-Request-Method", "POST"),
        ],
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "method,path,kwargs,status",
    [
        ("get", "csrf", {}, 405),
        ("get", "me", {}, 401),
        ("post", "csrf", {"content": "x", "headers": {"Content-Type": "text/plain"}}, 415),
        (
            "post",
            "csrf",
            {"content": "x" * 1025, "headers": {"Content-Type": "application/json"}},
            413,
        ),
    ],
)
def test_errors_no_store(client, method, path, kwargs, status):
    response = getattr(client, method)(f"/api/v1/auth/{path}", **kwargs)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"


def test_hash_slots_shared_with_registration(client):
    csrf = bootstrap(client)
    slots = client.app.state.registration_limits.hash_slots
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "synthetic@example.com", "password": "synthetic password"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "1"
    finally:
        slots.release()
        slots.release()


def test_rate_is_bounded_expires_and_ignores_forwarded_for(client):
    for i in range(5):
        response = client.post(
            "/api/v1/auth/login", json={}, headers={"X-Forwarded-For": f"192.0.2.{i}"}
        )
        assert response.status_code != 429
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code == 429
    assert 1 <= int(response.headers["retry-after"]) <= 60
    now = 0
    limits = SessionHttpLimits(settings(auth_client_capacity=1), clock=lambda: now)
    assert limits.admit("one", login=True) == 0
    assert limits.admit("two", login=True) == 60
    now = 61
    assert limits.admit("two", login=True) == 0
    limits.clear()
    assert limits.clients == {}


def test_streamed_size_guard_ignores_content_length():
    called = []
    sent = []
    chunks = iter(
        [
            {"type": "http.request", "body": b"x" * 700, "more_body": True},
            {"type": "http.request", "body": b"x" * 700, "more_body": False},
        ]
    )

    async def app(scope, receive, send):
        called.append(True)

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    cfg = settings()
    middleware = SessionHttpMiddleware(app, cfg, SessionHttpLimits(cfg))
    asyncio.run(
        middleware(
            {
                "type": "http",
                "path": "/api/v1/auth/csrf",
                "method": "POST",
                "client": ("127.0.0.1", 1),
                "headers": [(b"content-type", b"application/json"), (b"content-length", b"2")],
            },
            receive,
            send,
        )
    )
    assert not called
    assert sent[0]["status"] == 413


@pytest.mark.parametrize("key", ["jwt_signing_key", "auth_csrf_signing_key"])
def test_missing_signing_configuration_keeps_health_available(key):
    cfg = settings().model_copy(update={key: None})
    with TestClient(create_app(cfg), base_url="https://api.example.test") as client:
        response = client.post(
            "/api/v1/auth/csrf", json={}, headers={"Origin": ORIGIN, "X-CSRF-Bootstrap": "1"}
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication temporarily unavailable"}
        assert client.get("/health").status_code == 200


def test_unexpected_internal_error_is_static_and_not_cached():
    app = create_app(settings())

    def fail():
        raise RuntimeError("synthetic-private-marker")

    app.dependency_overrides[get_session_service] = fail
    with TestClient(
        app, base_url="https://api.example.test", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
        assert "synthetic-private-marker" not in response.text


def test_password_change_has_explicit_cors_and_independent_rate(client):
    path = "/api/v1/users/me/change-password"
    response = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["cache-control"] == "no-store"
    for _ in range(5):
        assert client.post(path, json={}, headers={"Origin": ORIGIN}).status_code != 429
    response = client.post(
        path, json={}, headers={"Origin": ORIGIN, "X-Forwarded-For": "192.0.2.1"}
    )
    assert response.status_code == 429 and int(response.headers["retry-after"]) >= 1
    # Separate bucket; changing password attempts do not consume the login quota.
    assert client.post("/api/v1/auth/login", json={}).status_code != 429


def test_password_change_header_guards_and_large_unicode_body(client):
    path = "/api/v1/users/me/change-password"
    response = client.post(path, json={}, headers=[("Origin", ORIGIN), ("Origin", ORIGIN)])
    assert response.status_code == 403 and "set-cookie" not in response.headers
    body = {"current_password": "\U0001f512" * 128, "new_password": "\U0001f513" * 128}
    response = client.post(path, json=body, headers={"Origin": ORIGIN})
    assert response.status_code == 401  # Valid-sized body reaches the missing-access guard.
    response = client.post(path, content="x" * 16385, headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and response.headers["cache-control"] == "no-store"


def test_password_change_bucket_shares_total_capacity_and_expires():
    now = 0
    limits = SessionHttpLimits(settings(auth_client_capacity=1), clock=lambda: now)
    assert limits.admit("one", login=False, password_change=True) == 0
    assert limits.admit("one", login=True) == 60
    now = 61
    assert limits.admit("one", login=True) == 0


def test_profile_patch_has_cors_body_guard_and_shared_sensitive_rate(client):
    path = "/api/v1/users/me"
    response = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert client.patch(path, content="plain").status_code == 415
    assert (
        client.patch(
            path, content="x" * 16385, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )
    for _ in range(3):
        assert (
            client.patch(path, json={"name": "Synthetic"}, headers={"Origin": ORIGIN}).status_code
            == 401
        )
    response = client.patch(path, json={"name": "Synthetic"})
    assert response.status_code == 429 and response.headers["cache-control"] == "no-store"
    assert client.post("/api/v1/auth/login", json={}).status_code != 429
