"""Configuration precedence and rejection of unsafe or invalid origins."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_defaults_deny_cross_origin_requests():
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.cors_origins == []
    assert settings.registration_body_bytes == 16384
    assert settings.registration_requests_per_minute == 5
    assert settings.registration_client_capacity == 4096
    assert settings.registration_concurrent_hashes == 2
    assert settings.jwt_signing_key is None
    assert settings.jwt_issuer == "finsight-api"
    assert settings.jwt_audience == "finsight-web"
    assert settings.jwt_access_ttl_seconds == 900


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
        {"registration_body_bytes": 1023},
        {"registration_body_bytes": 65537},
        {"registration_requests_per_minute": 0},
        {"registration_requests_per_minute": 101},
        {"registration_client_capacity": 0},
        {"registration_client_capacity": 65537},
        {"registration_concurrent_hashes": 0},
        {"registration_concurrent_hashes": 9},
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


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "not-a-key",
        "<64-hex-characters-generated-locally>",
        "a" * 63,
        "a" * 65,
        "g" * 64,
        "a" * 63 + " ",
    ],
)
def test_invalid_jwt_signing_configuration_is_rejected_without_echo(value):
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, jwt_signing_key=value)
    if value.strip():
        assert value not in str(error.value)


@pytest.mark.parametrize("value", [bytes(range(32)).hex(), bytes(range(32)).hex().upper()])
def test_valid_jwt_key_is_excluded_from_diagnostics_and_exports(value):
    settings = Settings(_env_file=None, jwt_signing_key=value)
    assert settings.jwt_signing_key.get_secret_value() == value
    assert "jwt_signing_key" not in settings.model_dump()
    assert value not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    "changes",
    [
        {"jwt_issuer": ""},
        {"jwt_issuer": " "},
        {"jwt_issuer": "a" * 121},
        {"jwt_audience": ""},
        {"jwt_audience": " "},
        {"jwt_audience": "a" * 121},
        {"jwt_access_ttl_seconds": 59},
        {"jwt_access_ttl_seconds": 901},
        {"jwt_issuer": "\ud800"},
        {"jwt_audience": "\ud800"},
    ],
)
def test_invalid_jwt_identifiers_and_lifetimes_are_rejected(changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **changes)


def test_jwt_configuration_precedence_and_identifier_normalization(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "FINSIGHT_JWT_ISSUER=file-api\nFINSIGHT_JWT_ACCESS_TTL_SECONDS=120\n", encoding="utf-8"
    )
    monkeypatch.setenv("FINSIGHT_JWT_ISSUER", "env-api")
    monkeypatch.setenv("FINSIGHT_JWT_SIGNING_KEY", bytes(range(32)).hex())
    settings = Settings(_env_file=path, jwt_audience=" web ")
    assert settings.jwt_issuer == "env-api" and settings.jwt_audience == "web"
    assert settings.jwt_access_ttl_seconds == 120
    assert settings.jwt_signing_key is not None
    assert Settings(_env_file=path, jwt_issuer="constructor-api").jwt_issuer == "constructor-api"
