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


def test_revision_graph_preserves_prior_revisions_and_has_one_refresh_history_head():
    script = ScriptDirectory.from_config(Config(str(CONFIG_PATH)))
    assert script.get_heads() == ["0007_refresh_token_history"]
    assert script.get_bases() == ["0001_phase0"]
    assert script.get_revision("0001_phase0").down_revision is None
    assert script.get_revision("0002_identity").down_revision == "0001_phase0"
    assert script.get_revision("0003_accounts_categories").down_revision == "0002_identity"
    assert script.get_revision("0004_imports").down_revision == "0003_accounts_categories"
    assert script.get_revision("0005_transactions_transfers").down_revision == "0004_imports"
    assert (
        script.get_revision("0006_goals_allocations").down_revision == "0005_transactions_transfers"
    )
    assert script.get_revision("head").down_revision == "0006_goals_allocations"


def test_template_generates_an_importable_revision_outside_the_repository(tmp_path):
    scripts = tmp_path / "alembic"
    shutil.copytree(BACKEND_DIR / "alembic", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    config = Config(str(CONFIG_PATH))
    config.set_main_option("script_location", str(scripts))
    revision = command.revision(config, message="synthetic template probe", rev_id="template_probe")
    assert revision.down_revision == "0007_refresh_token_history"
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
    assert "CREATE TABLE users" in result.stdout
    assert "CREATE TABLE user_sessions" in result.stdout
    assert "CREATE TABLE accounts" in result.stdout
    assert "CREATE TABLE categories" in result.stdout
    assert "CREATE TABLE import_jobs" in result.stdout
    assert "CREATE TABLE import_rows" in result.stdout
    assert "CREATE TABLE transactions" in result.stdout
    assert "CREATE TABLE transfers" in result.stdout
    assert "CREATE TABLE financial_goals" in result.stdout
    assert "CREATE TABLE goal_allocations" in result.stdout
    assert "CREATE TABLE refresh_token_history" in result.stdout
    assert result.stdout.count("CREATE TABLE") == 12
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
