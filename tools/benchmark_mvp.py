"""Opt-in HTTP reference measurements on an exclusively owned, disposable database."""

import base64
import http.cookiejar
import importlib.metadata
import json
import math
import os
import platform
import re
import secrets
import socket
import statistics
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IMAGE = (
    "postgres:18.6-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc"
)


def clean_environment():
    return {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(
            ("FINSIGHT_", "VITE_", "DEMO_", "PG", "DATABASE_URL", "COMPOSE_")
        )
    }


def docker(*args, env=None):
    result = subprocess.run(
        ["docker", *args],
        cwd=ROOT,
        env=env or clean_environment(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError("Owned Docker operation failed: " + args[0])
    return result.stdout.strip()


def distribution(values, threshold_ms):
    ordered = sorted(values)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return {
        "samples": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(p95, 3),
        "max_ms": round(ordered[-1], 3),
        "threshold_ms": threshold_ms,
        "passed": (p95 if len(ordered) >= 20 else ordered[-1]) <= threshold_ms,
    }


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )

    def request(self, path, data=None, headers=None):
        req = urllib.request.Request(
            self.base + "/api/v1" + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={
                "Origin": self.base,
                "Content-Type": "application/json",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        with self.opener.open(req, timeout=60) as response:
            body = response.read()
            return json.loads(body) if body else None

    def csrf(self):
        return self.request("/auth/csrf", {}, {"X-CSRF-Bootstrap": "1"})["csrf_token"]

    def create(self, path, data):
        return self.request(
            path,
            data,
            {"X-CSRF-Token": self.csrf(), "Idempotency-Key": str(uuid4())},
        )


def measure(settings, report, secret_values):
    # Explicit configuration only. Never load the developer's .env or accept a DB URL.
    sys.path.insert(0, str(ROOT / "backend"))
    import uvicorn
    from alembic import command
    from alembic.config import Config
    from app.db.session import Database
    from app.main import create_app
    from app.models import Transaction
    from sqlalchemy import func, insert, select

    database = Database(settings)
    server = None
    thread = None
    listener = socket.socket()
    try:
        with database.engine.begin() as connection:
            config = Config(str(ROOT / "backend/alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            report["schema_revision"] = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            report["postgres_version"] = connection.exec_driver_sql(
                "SHOW server_version"
            ).scalar_one()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        assert port not in (8000, 8002, 8010, 5180)
        base = f"http://127.0.0.1:{port}"
        configured = type(settings)(
            _env_file=None,
            **(
                {key: getattr(settings, key) for key in type(settings).model_fields}
                | {"auth_allowed_origins": [base], "cors_origins": [base]}
            ),
        )
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(configured),
                log_level="critical",
                access_log=False,
                proxy_headers=False,
            )
        )
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Owned API startup failed")
            time.sleep(0.05)
        client = Client(base)
        password = secrets.token_urlsafe(24)
        secret_values.append(password)
        email = "benchmark@example.com"
        client.request(
            "/auth/register", {"name": "Synthetic benchmark", "email": email, "password": password}
        )
        client.request(
            "/auth/login", {"email": email, "password": password}, {"X-CSRF-Token": client.csrf()}
        )
        owner = client.request("/users/me")["id"]
        today = datetime.now(UTC).astimezone(ZoneInfo("America/Sao_Paulo")).date()
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        account = client.create(
            "/accounts",
            {
                "name": "Synthetic benchmark account",
                "type": "checking",
                "currency": "BRL",
                "opening_balance": "1000.00",
                "opening_date": (start - timedelta(days=1)).isoformat(),
            },
        )["id"]
        income_category = client.create(
            "/categories", {"name": "Synthetic income", "type": "income"}
        )["id"]
        expenses = [
            client.create("/categories", {"name": f"Synthetic expense {i}", "type": "expense"})[
                "id"
            ]
            for i in range(24)
        ]
        rows = []
        income = Decimal(0)
        expense = Decimal(0)
        expense_index = 0
        for i in range(10_000):
            is_income = i % 3 == 0
            amount = Decimal("50.00") if is_income else Decimal("10.00")
            category = income_category if is_income else expenses[expense_index % len(expenses)]
            if is_income:
                income += amount
            else:
                expense += amount
                expense_index += 1
            rows.append(
                {
                    "user_id": UUID(owner),
                    "account_id": UUID(account),
                    "category_id": UUID(category),
                    "description": f"Synthetic benchmark {i}",
                    "amount": amount,
                    "type": "income" if is_income else "expense",
                    "status": "posted",
                    "effective_date": start + timedelta(days=i % end.day),
                }
            )
        with database.sessions.begin() as session:
            session.execute(insert(Transaction), rows)
        dashboard = f"/dashboard/breakdown?date_from={start}&date_to={end}"
        expected = {
            "income": format(income, ".2f"),
            "expense": format(expense, ".2f"),
            "net": format(income - expense, ".2f"),
        }

        def check_dashboard(result):
            assert result["transaction_count"] == 10_000
            assert all(result[k] == v for k, v in expected.items())
            assert (
                result["expense_category_count"] == 24 and len(result["expense_categories"]) == 20
            )
            assert result["other_expenses"]["category_count"] == 4
            assert (
                sum(Decimal(x["amount"]) for x in result["expense_categories"])
                + Decimal(result["other_expenses"]["amount"])
                == expense
            )

        check_dashboard(client.request(dashboard))
        for _ in range(3):
            client.request("/accounts?limit=50")
            check_dashboard(client.request(dashboard))
        simple_times = []
        dashboard_times = []
        for _ in range(50):
            before = time.perf_counter()
            result = client.request("/accounts?limit=50")
            simple_times.append((time.perf_counter() - before) * 1000)
            assert len(result["items"]) == 1
        for _ in range(30):
            before = time.perf_counter()
            result = client.request(dashboard)
            dashboard_times.append((time.perf_counter() - before) * 1000)
            check_dashboard(result)
        report["simple_api"] = distribution(simple_times, 500)
        report["monthly_dashboard_10000"] = distribution(dashboard_times, 2000)
        csv = "Date;Description;Amount\n" + "".join(
            f"{start};Synthetic CSV {i};10.00\n" for i in range(5000)
        )
        encoded = base64.b64encode(csv.encode()).decode()
        mapping = {
            "date_column": 0,
            "description_column": 1,
            "amount_column": 2,
            "date_format": "iso",
            "money_format": "decimal-dot",
        }
        csv_times = []
        for i in range(3):
            source = {
                "account_id": account,
                "filename": f"reference-{i}.csv",
                "content_base64": encoded,
            }
            before = time.perf_counter()
            inspection = client.request("/imports/inspect", source, {"X-CSRF-Token": client.csrf()})
            preview = client.create("/imports", {**source, "mapping": mapping})
            receipt = client.request("/imports/" + preview["id"])
            csv_times.append((time.perf_counter() - before) * 1000)
            assert inspection["total_rows"] == receipt["total_rows"] == 5000
            assert receipt["invalid_rows"] == receipt["imported_rows"] == 0
        report["csv_5000_preview"] = distribution(csv_times, 15000)
        with database.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Transaction)) == 10_000
        report["fixture"] = {
            "transactions": 10000,
            "expense_categories": 24,
            "csv_rows": 5000,
            "preview_samples": 3,
            "financial_confirmation_executed": False,
            "expected_money": expected,
            "period": [start.isoformat(), end.isoformat()],
        }
        report["samples_ms"] = {
            "simple_api": simple_times,
            "dashboard": dashboard_times,
            "csv": csv_times,
        }
        client.request("/auth/logout", {}, {"X-CSRF-Token": client.csrf()})
    finally:
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=15)
            report["api_stopped"] = not thread.is_alive()
        listener.close()
        database.dispose()


def main():
    for key in tuple(os.environ):
        if key.upper().startswith(
            ("FINSIGHT_", "VITE_", "DEMO_", "PG", "DATABASE_URL", "COMPOSE_")
        ):
            del os.environ[key]  # This process only; no shell/profile or .env is changed.
    run_id = uuid4().hex
    output = ROOT / ".cache/mvp-performance" / run_id
    output.mkdir(parents=True)
    name = "finsight-perf-" + run_id[:12]
    container = None
    secret_values = [secrets.token_urlsafe(32), secrets.token_hex(32), secrets.token_hex(32)]
    report = {
        "reference": "local development HTTP; synthetic isolated fixture; not a production SLA",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "image": IMAGE,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "host_logical_cpus": os.cpu_count(),
        "database_limits": {"cpus": 2, "memory_mib": 1024},
        "api_cpu_cap": None,
        "auth_requests_per_minute_test_only": 1000,
        "network": "actual HTTP over IPv4 loopback; no TLS or browser rendering",
        "warmup_requests_per_read_scenario": 3,
        "container_removed": False,
        "api_stopped": False,
        "passed": False,
    }
    try:
        endpoint = os.environ.get("DOCKER_HOST") or docker(
            "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
        )
        if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
            raise RuntimeError("A local Docker socket or named pipe is required")
        assert docker("info", "--format", "{{.OSType}}") == "linux"
        report["cpu_model"] = platform.processor()
        if os.name == "nt":
            report["host_memory_bytes"] = int(
                subprocess.check_output(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
                    ],
                    text=True,
                    timeout=30,
                ).strip()
            )
        else:
            report["host_memory_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        report["docker_resources"] = json.loads(
            docker("info", "--format", '{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}}}')
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert port not in (5432, 5433, 5544, 5546)
        env = clean_environment()
        env["POSTGRES_PASSWORD"] = secret_values[0]
        container = docker(
            "run",
            "--rm",
            "--detach",
            "--name",
            name,
            "--label",
            "finsight.validation=mvp-performance",
            "--cpus",
            "2",
            "--memory",
            "1g",
            "--publish",
            f"127.0.0.1:{port}:5432",
            "--env",
            "POSTGRES_DB=finsight_benchmark",
            "--env",
            "POSTGRES_USER=finsight_benchmark",
            "--env",
            "POSTGRES_PASSWORD",
            IMAGE,
            env=env,
        )
        assert re.fullmatch(r"[0-9a-f]{64}", container)
        deadline = time.monotonic() + 45
        while subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "finsight_benchmark",
            ],
            capture_output=True,
        ).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError("Owned database readiness timeout")
            time.sleep(0.25)
        sys.path.insert(0, str(ROOT / "backend"))
        from app.core.config import Settings

        settings = Settings(
            _env_file=None,
            environment="test",
            db_host="127.0.0.1",
            db_port=port,
            db_name="finsight_benchmark",
            db_user="finsight_benchmark",
            db_password=secret_values[0],
            jwt_signing_key=secret_values[1],
            auth_csrf_signing_key=secret_values[2],
            auth_cookie_secure=False,
            auth_requests_per_minute=1000,
        )
        report["libraries"] = {
            package: importlib.metadata.version(package)
            for package in ["fastapi", "SQLAlchemy", "alembic", "uvicorn", "psycopg"]
        }
        measure(settings, report, secret_values)
        report["passed"] = all(
            report[k]["passed"]
            for k in ["simple_api", "monthly_dashboard_10000", "csv_5000_preview"]
        )
    except Exception as error:
        details = traceback.format_exc()
        for value in secret_values:
            details = details.replace(value, "[redacted]")
        details = re.sub(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", "[redacted token]", details)
        (output / "error.log").write_text(details, encoding="utf-8")
        report["error_type"] = type(error).__name__
    finally:
        if container:
            assert (
                docker(
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "finsight.validation"}}',
                    container,
                )
                == "mvp-performance"
            )
            docker("stop", "--time", "5", container)
            deadline = time.monotonic() + 15
            while docker(
                "container", "ls", "--all", "--filter", "id=" + container, "--format", "{{.ID}}"
            ):
                if time.monotonic() > deadline:
                    raise RuntimeError("Owned container removal timeout")
                time.sleep(0.25)
            report["container_removed"] = not docker(
                "container", "ls", "--all", "--filter", "id=" + container, "--format", "{{.ID}}"
            )
        report["passed"] = (
            report["passed"] and report["container_removed"] and report["api_stopped"]
        )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "report": str((output / "report.json").relative_to(ROOT)),
                    "passed": report["passed"],
                    "container_removed": report["container_removed"],
                    "api_stopped": report["api_stopped"],
                    **{
                        k: report[k]
                        for k in [
                            "simple_api",
                            "monthly_dashboard_10000",
                            "csv_5000_preview",
                            "error_type",
                        ]
                        if k in report
                    },
                }
            )
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
