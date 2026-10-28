"""In-process HTTP integration tests; no database required in this step."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client():
    settings = Settings(_env_file=None, environment="test", cors_origins=["http://localhost:5173"])
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_health_returns_only_process_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"
    assert "set-cookie" not in response.headers


def test_health_contract_is_in_openapi(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_documentation_is_available_in_test_environment(client):
    assert client.get("/docs").status_code == 200


def test_production_hides_documentation():
    settings = Settings(_env_file=None, environment="production")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_allowed_origin_receives_cors_headers(client):
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_disallowed_origin_receives_no_cors_permission(client):
    response = client.get("/health", headers={"Origin": "https://untrusted.example.test"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_allowed_get_preflight(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unconfigured_cross_origin_method_is_rejected(client):
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 400
