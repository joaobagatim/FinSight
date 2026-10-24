"""Migration discovery and SQL generation must work without a database or secrets."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BACKEND_DIR / "alembic.ini"


def test_revision_graph_has_one_empty_baseline():
    script = ScriptDirectory.from_config(Config(str(CONFIG_PATH)))
    assert script.get_heads() == ["0001_phase0"]
    assert script.get_bases() == ["0001_phase0"]
    assert script.get_revision("head").down_revision is None


def test_template_generates_an_importable_revision_outside_the_repository(tmp_path):
    scripts = tmp_path / "alembic"
    shutil.copytree(BACKEND_DIR / "alembic", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config(str(CONFIG_PATH))
    config.set_main_option("script_location", str(scripts))
    revision = command.revision(config, message="synthetic template probe", rev_id="template_probe")
    assert revision.down_revision == "0001_phase0"
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
    assert ScriptDirectory.from_config(config).get_heads() == ["template_probe"]


@pytest.mark.parametrize("working_directory", ["backend", "unrelated"])
def test_offline_sql_is_independent_of_cwd_database_and_credentials(tmp_path, working_directory):
    marker = "synthetic-secret-%-not-for-sql"
    environment = dict(
        os.environ,
        FINSIGHT_DB_HOST="invalid.invalid",
        FINSIGHT_DB_PORT="invalid-port",
        FINSIGHT_DB_PASSWORD=marker,
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(CONFIG_PATH), "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR if working_directory == "backend" else tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert "CREATE TABLE alembic_version" in result.stdout
    assert "0001_phase0" in result.stdout
    assert "COMMIT;" in result.stdout
    assert result.stdout.count("CREATE TABLE") == 1
    assert marker not in result.stdout + result.stderr
    assert "invalid.invalid" not in result.stdout + result.stderr


def test_invalid_settings_fail_without_leaking_values(tmp_path):
    marker = "synthetic-invalid-config-secret"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(CONFIG_PATH), "current"],
        cwd=tmp_path,
        env=dict(os.environ, FINSIGHT_DB_PORT="invalid-port", FINSIGHT_DB_PASSWORD=marker),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "check database configuration and availability" in result.stdout + result.stderr
    assert marker not in result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr
