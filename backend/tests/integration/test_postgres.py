"""Real SQLAlchemy/psycopg integration against an isolated, temporary database."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.db.session import Database
from app.main import create_app

pytestmark = pytest.mark.postgres


def test_session_uses_the_temporary_database_and_releases_connection(postgres_settings):
    database = Database(postgres_settings)
    try:
        with database.sessions() as session:
            assert (
                session.execute(text("SELECT current_database()")).scalar_one()
                == postgres_settings.db_name
            )
            assert session.execute(text("SELECT 1")).scalar_one() == 1
            assert session.execute(text("SHOW timezone")).scalar_one() == "UTC"
        assert database.engine.pool.checkedout() == 0
    finally:
        database.dispose()


def test_ready_uses_postgresql_and_pool_is_disposed_on_shutdown(postgres_settings):
    app = create_app(postgres_settings)
    with TestClient(app) as client:
        original_pool = app.state.database.engine.pool
        for _ in range(3):
            response = client.get("/health/ready")
            assert response.status_code == 200
            assert response.json() == {"status": "ok", "database": "ok"}
            assert response.headers["cache-control"] == "no-store"
            assert app.state.database.engine.pool.checkedout() == 0
        assert client.get("/health").status_code == 200

    assert app.state.database.engine.pool is not original_pool


def test_wrong_password_is_sanitized_without_breaking_process_health(postgres_settings, caplog):
    marker = "synthetic-invalid-db-password"
    settings = postgres_settings.model_copy(update={"db_password": SecretStr(marker)})
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "unavailable"}
    assert marker not in response.text
    assert marker not in caplog.text


def test_statement_timeout_is_applied(postgres_settings):
    database = Database(postgres_settings)
    try:
        with database.engine.connect() as connection:
            timeout = connection.execute(
                text("SELECT current_setting('statement_timeout')::interval")
            ).scalar_one()
        assert timeout.total_seconds() == postgres_settings.db_statement_timeout_ms / 1000
    finally:
        database.dispose()
