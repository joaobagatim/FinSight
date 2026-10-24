"""Keep tests independent of machine configuration and local .env files."""

import os
import uuid

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database


def pytest_addoption(parser):
    parser.addoption(
        "--run-postgres", action="store_true", default=False, help="Run isolated PostgreSQL tests"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-postgres"):
        return
    skip = pytest.mark.skip(
        reason="Use --run-postgres to run isolated PostgreSQL integration tests"
    )
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def clear_application_environment(monkeypatch):
    for name in list(os.environ):
        if name.upper().startswith("FINSIGHT_"):
            monkeypatch.delenv(name)


@pytest.fixture(scope="session")
def postgres_settings(request):
    if not request.config.getoption("--run-postgres"):
        pytest.skip("PostgreSQL integration tests are opt-in")
    admin_settings = Settings()
    if (
        admin_settings.environment == "production"
        or admin_settings.db_host not in {"localhost", "127.0.0.1"}
        or admin_settings.db_port == 5432
        or admin_settings.db_password is None
    ):
        pytest.fail(
            "PostgreSQL tests require an explicitly configured local development container",
            pytrace=False,
        )
    name = "finsight_test_" + uuid.uuid4().hex
    admin = Database(admin_settings)
    created = False
    try:
        with admin.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            assert (
                connection.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname = :name"), {"name": name}
                ).scalar_one()
                == 0
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        yield admin_settings.model_copy(update={"environment": "test", "db_name": name})
    finally:
        try:
            if created:
                with admin.engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        finally:
            admin.dispose()
