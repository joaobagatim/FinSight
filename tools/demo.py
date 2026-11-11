"""Isolated local demo. Never reads the personal .env or accepts a database URL."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".demo"
HOST = "127.0.0.2"
API = f"http://{HOST}:8010"
WEB = f"http://{HOST}:5180"
PROJECT = "finsight-demo"
CONTAINER = "finsight-demo-postgres"
VOLUME = "finsight-demo-data"
IMAGE = (
    "postgres:18.6-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc"
)


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def clean_env():
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FINSIGHT_", "VITE_", "DEMO_", "PG", "DATABASE_URL", "COMPOSE_"))
    }


def run(args, *, env=None):
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=env or clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        # Docker/driver errors can contain credentials. Never print raw stderr.
        raise RuntimeError(f"Command failed ({Path(args[0]).name}); details suppressed")
    return result.stdout


def docker(*args):
    return run(["docker", *args])


def compose(*args):
    return docker(
        "compose",
        "--env-file",
        str(LOCAL / ".env"),
        "-f",
        str(ROOT / "docker-compose.demo.yml"),
        "-p",
        PROJECT,
        *args,
    )


def config():
    values = dict(
        line.split("=", 1)
        for line in (LOCAL / ".env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    required = {
        "DEMO_DB_PASSWORD",
        "DEMO_EMAIL",
        "DEMO_PASSWORD",
        "DEMO_JWT_KEY",
        "DEMO_CSRF_KEY",
        "DEMO_INSTANCE_ID",
    }
    if set(values) != required or any(not v or "<" in v for v in values.values()):
        raise RuntimeError("Invalid demo credentials; personal configuration will not be used")
    return values


def initialize():
    LOCAL.mkdir(exist_ok=True)
    if not (LOCAL / ".env").exists():
        if docker("ps", "-aq", "--filter", f"name=^/{CONTAINER}$").strip():
            raise RuntimeError(
                "Existing demo container without local credentials; refusing overwrite"
            )
        if VOLUME in docker("volume", "ls", "--format", "{{.Name}}").splitlines():
            raise RuntimeError("Existing demo volume without credentials; refusing overwrite")
        values = dict(
            DEMO_DB_PASSWORD=secrets.token_urlsafe(32),
            DEMO_EMAIL="demo.finsight@example.com",
            DEMO_PASSWORD=secrets.token_urlsafe(18),
            DEMO_JWT_KEY=secrets.token_hex(32),
            DEMO_CSRF_KEY=secrets.token_hex(32),
            DEMO_INSTANCE_ID=str(uuid4()),
        )
        descriptor = os.open(LOCAL / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    config()


def personal_snapshot():
    ids = docker("ps", "-aq").split()
    containers = json.loads(docker("inspect", *ids)) if ids else []
    volumes = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    result = {"containers": {}, "volumes": {}, "env_files": {}}
    for item in containers:
        if item["Name"] == "/" + CONTAINER:
            continue
        # Compare immutable configuration plus lifecycle; no personal DB connection.
        result["containers"][item["Id"]] = {
            "config_sha256": hashlib.sha256(
                json.dumps(item["Config"], sort_keys=True).encode()
            ).hexdigest(),
            "mounts": item["Mounts"],
            "started": item["State"]["StartedAt"],
            "running": item["State"]["Running"],
            "restart_count": item["RestartCount"],
        }
    for name in volumes:
        if name != VOLUME:
            result["volumes"][name] = json.loads(docker("volume", "inspect", name))[0]
    for folder in (ROOT, ROOT / "frontend"):
        for path in folder.glob(".env*"):
            if path.is_file() and not path.name.endswith(".example"):
                result["env_files"][str(path.relative_to(ROOT))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return result


def verify_resources(*, running=False):
    ids = docker("ps", "-aq", "--filter", f"name=^/{CONTAINER}$").split()
    volumes = docker("volume", "ls", "--format", "{{.Name}}").splitlines()
    if VOLUME in volumes:
        volume = json.loads(docker("volume", "inspect", VOLUME))[0]
        labels = volume.get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.volume") != "demo_data"
        ):
            raise RuntimeError("Demo volume ownership mismatch")
    if not ids:
        if running:
            raise RuntimeError("Demo container missing")
        return
    item = json.loads(docker("inspect", ids[0]))[0]
    labels = item["Config"].get("Labels") or {}
    mounts = [m for m in item["Mounts"] if m["Destination"] == "/var/lib/postgresql"]
    ports = item["HostConfig"]["PortBindings"]
    if (
        labels.get("com.docker.compose.project") != PROJECT
        or labels.get("com.docker.compose.service") != "postgres"
        or item["Config"]["Image"] != IMAGE
        or len(mounts) != 1
        or mounts[0].get("Name") != VOLUME
        or ports != {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5544"}]}
        or (running and not item["State"]["Running"])
    ):
        raise RuntimeError("Demo container/port/mount ownership mismatch")
    return item["Id"]


def database_port():
    path = LOCAL / "transport.json"
    if not path.exists():
        return 5544
    mode = json.loads(path.read_text())
    if mode not in ({"port": 5544}, {"port": 5546}):
        raise RuntimeError("Invalid demo transport; refusing database connection")
    return mode["port"]


def settings():
    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import Settings

    c = config()
    return Settings(
        _env_file=None,
        environment="development",
        db_host="127.0.0.1",
        db_port=database_port(),
        db_connect_timeout=15,
        db_name="finsight_demo",
        db_user="finsight_demo",
        db_password=c["DEMO_DB_PASSWORD"],
        jwt_signing_key=c["DEMO_JWT_KEY"],
        auth_csrf_signing_key=c["DEMO_CSRF_KEY"],
        jwt_issuer="finsight-demo-api",
        jwt_audience="finsight-demo-web",
        auth_cookie_secure=False,
        auth_allowed_origins=[WEB],
        cors_origins=[WEB],
    )


def migrate():
    verify_resources(running=True)
    from alembic import command
    from alembic.config import Config

    configured = settings()
    from app.db.session import Database
    from sqlalchemy import text

    database = Database(configured)
    try:
        with database.engine.connect() as connection:
            identity = connection.execute(text("SELECT current_database(), current_user")).one()
            if tuple(identity) != ("finsight_demo", "finsight_demo"):
                raise RuntimeError("Refusing migrations: unexpected database identity")
            connection.commit()
            print(
                "Verified migration target: finsight-demo-postgres / finsight-demo-data / "
                f"127.0.0.1:{database_port()} / finsight_demo"
            )
            alembic = Config(str(ROOT / "backend/alembic.ini"))
            alembic.set_main_option("script_location", str(ROOT / "backend/alembic"))
            alembic.attributes["connection"] = connection
            command.upgrade(alembic, "head")
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            save(
                LOCAL / "migration-result.json",
                {
                    "database": identity[0],
                    "user": identity[1],
                    "port": database_port(),
                    "volume": VOLUME,
                    "revision": revision,
                },
            )
    finally:
        database.dispose()


def client():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )


def request(opener, path, data=None, headers=None):
    req = urllib.request.Request(
        API + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Origin": WEB, "Content-Type": "application/json", **(headers or {})},
    )
    try:
        with opener.open(req, timeout=10) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Demo API request failed: HTTP {error.code}, {path}") from None


def identity():
    if request(client(), "/__demo/identity") != {"instance": config()["DEMO_INSTANCE_ID"]}:
        raise RuntimeError("Unexpected API process; refusing seed or control action")


def seed():
    verify_resources(running=True)
    identity()
    from demo_seed import seed_demo

    return seed_demo(LOCAL, config(), client(), request, save)


def serve_api():
    import uvicorn

    configured = settings()
    from app.main import create_app

    app = create_app(configured)
    instance = config()["DEMO_INSTANCE_ID"]

    @app.get("/__demo/identity", include_in_schema=False)
    def demo_identity():
        return {"instance": instance}

    uvicorn.run(app, host=HOST, port=8010, access_log=False, proxy_headers=False)


def supervise():
    children = []
    handles = []
    tunnel = None
    try:
        if database_port() == 5546:
            from demo_tunnel import open_tunnel

            tunnel = open_tunnel(verify_resources(running=True))
        commands = [
            (sys.executable, str(Path(__file__).resolve()), "_api"),
            (
                "node",
                str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
                "--config",
                "vite.demo.config.js",
            ),
        ]
        for index, command in enumerate(commands):
            handle = (LOCAL / ("api.log" if index == 0 else "frontend.log")).open("ab")
            handles.append(handle)
            env = clean_env()
            if index:
                env.update(VITE_API_BASE_URL=API, VITE_DEMO_MODE="true")
            children.append(
                subprocess.Popen(
                    command,
                    cwd=ROOT / "frontend" if index else ROOT,
                    env=env,
                    stdout=handle,
                    stderr=handle,
                )
            )
        while not (LOCAL / "stop").exists() and all(p.poll() is None for p in children):
            time.sleep(0.5)
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()  # Only this supervisor's own child, never a stored PID.
                    process.wait()
        for handle in handles:
            handle.close()
        if tunnel is not None:
            from demo_tunnel import close_tunnel

            close_tunnel(tunnel)
        (LOCAL / "running.lock").unlink(missing_ok=True)
        (LOCAL / "stop").unlink(missing_ok=True)


def start():
    initialize()
    if (LOCAL / "running.lock").exists():
        identity()
        print("Demo is already running: " + WEB)
        return
    for port in (8010, 5180):
        with socket.socket() as probe:
            probe.bind((HOST, port))  # Fail closed rather than stop another process.
    before = personal_snapshot()
    save(LOCAL / "personal-before.json", before)
    verify_resources()
    compose("up", "-d", "--wait", "--wait-timeout", "90")
    try:
        with socket.create_connection(("127.0.0.1", 5544), timeout=2) as probe:
            probe.sendall(struct.pack("!II", 8, 80877103))
            if probe.recv(1) not in (b"N", b"S"):
                raise OSError("No PostgreSQL protocol response")
        port = 5544
    except OSError:
        # Fixed loopback port and verified container ID; never use a personal URL.
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 5546))
        port = 5546
        print("Docker port publisher unavailable; using demo-only loopback tunnel on 5546")
    save(LOCAL / "transport.json", {"port": port})
    descriptor = os.open(LOCAL / "running.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    (LOCAL / "stop").unlink(missing_ok=True)
    log = (LOCAL / "supervisor.log").open("ab")
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )
    supervisor = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_supervise"],
        cwd=ROOT,
        env=clean_env(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    log.close()
    for _ in range(60):
        if supervisor.poll() is not None:
            raise RuntimeError("Demo supervisor exited; inspect local logs")
        try:
            identity()
            with client().open(WEB, timeout=2) as response:
                if response.status == 200:
                    break
        except (OSError, RuntimeError):
            time.sleep(0.5)
    else:
        (LOCAL / "stop").touch()
        raise RuntimeError("Demo startup failed; inspect local logs, no data was deleted")
    try:
        migrate()
        seed()
    except Exception:
        (LOCAL / "stop").touch()
        raise
    after = personal_snapshot()
    if before != after:
        raise RuntimeError(
            "Personal resource metadata changed; inspect local snapshot before continuing"
        )
    save(
        LOCAL / "preservation-result.json",
        {
            "personal_env_bytes_unchanged": True,
            "non_demo_container_configuration_and_lifecycle_unchanged": True,
            "non_demo_volume_metadata_unchanged": True,
            "personal_database_connected": False,
        },
    )
    print("Demo ready: " + WEB + "; credentials: .demo/.env; personal resources preserved")


def stop():
    config()
    verify_resources()
    if (LOCAL / "running.lock").exists():
        identity()
        (LOCAL / "stop").touch()
        for _ in range(40):
            if not (LOCAL / "running.lock").exists():
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Supervisor did not stop; database left untouched")
    compose("stop")  # No down, volume deletion, reset or reseed.
    print("Demo stopped; demo data retained; personal services untouched")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "seed", "status", "stop", "_api", "_supervise"])
    action = parser.parse_args().action
    if action == "_api":
        serve_api()
    elif action == "_supervise":
        supervise()
    elif action == "start":
        start()
    elif action == "stop":
        stop()
    elif action == "seed":
        print(json.dumps(seed()))
    else:
        identity()
        print("Demo running: " + WEB)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not expose settings, credentials, HTTP bodies or SQL in terminal output.
        print(
            f"Demo operation failed ({type(error).__name__}). No automatic data cleanup. "
            "Verify Docker, dedicated ports and local logs.",
            file=sys.stderr,
        )
        sys.exit(1)
