"""Readiness behavior without requiring a running PostgreSQL server."""

import socket

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database
from app.core.config import Settings
from app.main import create_app


def test_missing_database_configuration_does_not_break_process_health():
    with TestClient(create_app(Settings(_env_file=None, environment="test"))) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_readiness_error_response_and_logs_do_not_expose_exception_details(caplog):
    marker = "synthetic-sensitive-error"

    class UnavailableDatabase:
        def check_connection(self):
            raise OperationalError(marker, None, Exception(marker))

    app = create_app(Settings(_env_file=None, environment="test"))
    app.dependency_overrides[get_database] = lambda: UnavailableDatabase()
    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert marker not in response.text
    assert marker not in caplog.text


def test_refused_connection_returns_503_while_process_remains_healthy():
    with socket.socket() as reserved_port:
        reserved_port.bind(("127.0.0.1", 0))
        settings = Settings(
            _env_file=None,
            environment="test",
            db_host="127.0.0.1",
            db_port=reserved_port.getsockname()[1],
            db_password=SecretStr("synthetic-unreachable-password"),
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").status_code == 200
            response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}


def test_openapi_describes_unavailable_readiness_response():
    with TestClient(create_app(Settings(_env_file=None, environment="test"))) as client:
        responses = client.get("/openapi.json").json()["paths"]["/health/ready"]["get"]["responses"]

    assert "200" in responses and "503" in responses
