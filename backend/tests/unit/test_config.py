"""Configuration precedence and rejection of unsafe or invalid origins."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_deny_cross_origin_requests():
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.cors_origins == []


def test_environment_overrides_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "FINSIGHT_ENVIRONMENT=development\n"
        'FINSIGHT_CORS_ORIGINS=["http://localhost:5173"]\n'
        "UNRELATED_SETTING=synthetic\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FINSIGHT_ENVIRONMENT", "test")

    settings = Settings(_env_file=env_file)

    assert settings.environment == "test"
    assert [str(origin) for origin in settings.cors_origins] == ["http://localhost:5173/"]


def test_constructor_overrides_environment(monkeypatch):
    monkeypatch.setenv("FINSIGHT_ENVIRONMENT", "production")

    assert Settings(_env_file=None, environment="test").environment == "test"


def test_invalid_environment_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="invalid")


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://*.example.test",
        "ftp://example.test",
        "https://example.test/path",
        "https://example.test?query=1",
        "https://example.test#fragment",
        "https://synthetic:placeholder@example.test",
    ],
)
def test_invalid_cors_origin_is_rejected(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_production_rejects_http_origins():
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(_env_file=None, environment="production", cors_origins=["http://example.test"])


def test_production_accepts_explicit_https_origin():
    settings = Settings(
        _env_file=None, environment="production", cors_origins=["https://example.test"]
    )

    assert str(settings.cors_origins[0]) == "https://example.test/"


@pytest.mark.parametrize("password", ["", "   ", "replace-with-a-long-random-local-password"])
def test_empty_or_example_database_password_is_rejected(password):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_password=password)


@pytest.mark.parametrize(
    "values",
    [
        {"db_port": 0},
        {"db_port": 65536},
        {"db_connect_timeout": 0},
        {"db_pool_timeout": 0},
        {"db_statement_timeout_ms": 0},
        {"db_host": ""},
        {"db_name": ""},
        {"db_user": ""},
    ],
)
def test_invalid_database_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_validation_errors_hide_raw_database_password():
    marker = "synthetic-secret-marker"
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            environment="production",
            cors_origins=["http://example.test"],
            db_password=marker,
        )

    assert marker not in str(error.value)
