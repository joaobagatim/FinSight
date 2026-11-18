"""One seed journey against real APIs and disposable PostgreSQL, including a lost response."""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from tools import demo
from tools.demo_seed import seed_demo

from app.api.dependencies import get_database
from app.core.config import Settings
from app.db.session import Database
from app.main import create_app

pytestmark = pytest.mark.postgres


@pytest.fixture
def seed_settings(postgres_settings):
    assert postgres_settings.db_name.startswith("finsight_test_")
    name = "finsight_test_demo_seed_" + uuid4().hex
    admin = Database(postgres_settings)
    try:
        with admin.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            original_tables = set(inspect(connection).get_table_names())
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            try:
                yield postgres_settings.model_copy(update={"db_name": name})
            finally:
                assert name.startswith("finsight_test_demo_seed_")
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
                assert set(inspect(connection).get_table_names()) == original_tables
    finally:
        admin.dispose()


def test_demo_seed_recovers_lost_reservation_without_duplicating_money(seed_settings, tmp_path):
    assert seed_settings.db_name.startswith("finsight_test_demo_seed_")
    database = Database(seed_settings)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    credentials = {
        "DEMO_EMAIL": "seed@example.com",
        "DEMO_PASSWORD": "synthetic demo test password",
    }
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_signing_key="ab" * 32,
        auth_csrf_signing_key="cd" * 32,
        auth_cookie_secure=False,
        auth_allowed_origins=[demo.WEB],
        auth_requests_per_minute=1000,
    )
    app = create_app(settings)
    app.dependency_overrides[get_database] = lambda: database

    class Opener:
        lose_response = True
        allocation_posts = 0

        @contextmanager
        def open(self, req, timeout):
            response = client.request(
                req.get_method(), req.full_url, content=req.data, headers=req.headers
            )
            if response.status_code >= 400:
                raise HTTPError(
                    req.full_url, response.status_code, "Synthetic API failure", {}, None
                )
            if req.get_method() == "POST" and req.full_url.endswith("/allocations"):
                self.allocation_posts += 1
                if self.lose_response:
                    self.lose_response = False
                    raise URLError("Synthetic lost response after reservation commit")
            yield SimpleNamespace(read=lambda: response.content, headers=response.headers)

    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with TestClient(app, base_url=demo.API, client=("127.0.0.1", 40000)) as client:
            opener = Opener()
            # Registration is real but the test never uses the personal/demo database or network.
            with pytest.raises(URLError, match="lost response"):
                seed_demo(tmp_path, credentials, opener, demo.request, demo.save)
            pending = json.loads((tmp_path / "seed.json").read_text())["goal_seed"]["allocation"]
            assert "id" not in pending
            expected = {
                "accounts": 2,
                "categories": 4,
                "transactions": 6,
                "goals": 1,
                "allocations": 1,
            }
            assert seed_demo(tmp_path, credentials, opener, demo.request, demo.save) == expected
            plan = (tmp_path / "seed.json").read_bytes()
            csv = (tmp_path / "import-example.csv").read_bytes()
            assert seed_demo(tmp_path, credentials, opener, demo.request, demo.save) == expected
            assert (tmp_path / "seed.json").read_bytes() == plan
            assert (tmp_path / "import-example.csv").read_bytes() == csv
            assert (
                opener.allocation_posts == 2
            )  # A retry, not a second reservation; third seed skips it.
            saved = json.loads(plan)["goal_seed"]["allocation"]
            assert {k: v for k, v in saved.items() if k != "id"} == pending
            token = demo.request(opener, "/api/v1/auth/csrf", {}, {"X-CSRF-Bootstrap": "1"})
            demo.request(
                opener,
                "/api/v1/auth/login",
                {"email": credentials["DEMO_EMAIL"], "password": credentials["DEMO_PASSWORD"]},
                {"X-CSRF-Token": token["csrf_token"]},
            )
            goal_id = demo.request(opener, "/api/v1/goals?limit=100")["items"][0]["id"]
            funding = demo.request(opener, f"/api/v1/goals/{goal_id}/funding")
            available = demo.request(
                opener, f"/api/v1/accounts/{saved['body']['account_id']}/availability"
            )
            assert funding["reserved_amount"] == "500.00" and funding["progress_percent"] == "50.00"
            assert available["bank_balance"] == "2850.00"
            assert (
                available["reserved_amount"] == "500.00" and available["free_balance"] == "2350.00"
            )
    finally:
        database.dispose()
