"""Disposable Playwright API: explicit synthetic settings, never personal .env."""

import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "backend"))

import uvicorn
from alembic import command
from alembic.config import Config
from app.core.config import Settings
from app.db.session import Database
from app.main import create_app


def run():
    name = os.environ["SESSION_TEST_DB_NAME"]
    port = int(os.environ["SESSION_TEST_DB_PORT"])
    if not re.fullmatch(r"finsight_test_pw_[a-f0-9]{32}", name) or port in (5432, 5433):
        raise RuntimeError("Invalid isolated test database")
    settings = Settings(
        _env_file=None,
        environment="test",
        db_host="127.0.0.1",
        db_port=port,
        db_name=name,
        db_user="finsight_pw",
        db_password=os.environ["SESSION_TEST_DB_PASSWORD"],
        jwt_signing_key=os.environ["SESSION_TEST_JWT_KEY"],
        auth_csrf_signing_key=os.environ["SESSION_TEST_CSRF_KEY"],
        auth_cookie_secure=False,
        cors_origins=["http://127.0.0.1:4175"],
        auth_allowed_origins=["http://127.0.0.1:4175"],
        auth_login_requests_per_minute=100,
        auth_password_change_requests_per_minute=100,
        auth_requests_per_minute=1000,
        registration_requests_per_minute=100,
    )
    database = Database(settings)
    try:
        config = Config(str(root / "backend/alembic.ini"))
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        database.dispose()
    application = create_app(settings)

    @application.middleware("http")
    async def mark_owned_readiness(request, call_next):
        response = await call_next(request)
        if request.url.path == "/health/ready":
            response.headers["X-FinSight-Test-Run"] = name.removeprefix(
                "finsight_test_pw_"
            )
        return response

    uvicorn.run(
        application,
        host="127.0.0.1",
        port=8002,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    try:
        run()
    except Exception:  # noqa: BLE001 - startup details must never reach test reports
        print(
            "Isolated session API could not start; configuration/database details suppressed.",
            file=sys.stderr,
        )
        sys.exit(1)
