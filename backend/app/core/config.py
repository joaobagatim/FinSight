"""Validated configuration loaded from the environment or the root .env file."""

import re
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINSIGHT_",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    cors_origins: list[AnyHttpUrl] = []
    db_host: str = Field(default="localhost", min_length=1)
    db_port: int = Field(default=5433, ge=1, le=65535)
    db_name: str = Field(default="finsight", min_length=1)
    db_user: str = Field(default="finsight", min_length=1)
    db_password: SecretStr | None = Field(default=None, exclude=True, repr=False)
    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    db_pool_timeout: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=3000, ge=100, le=30000)
    registration_body_bytes: int = Field(default=16384, ge=1024, le=65536)
    registration_requests_per_minute: int = Field(default=5, ge=1, le=100)
    registration_client_capacity: int = Field(default=4096, ge=1, le=65536)
    registration_concurrent_hashes: int = Field(default=2, ge=1, le=8)
    jwt_signing_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    jwt_issuer: str = Field(default="finsight-api", min_length=1, max_length=120)
    jwt_audience: str = Field(default="finsight-web", min_length=1, max_length=120)
    jwt_access_ttl_seconds: int = Field(default=900, ge=60, le=900)
    auth_refresh_ttl_seconds: int = Field(default=604800, ge=3600, le=604800)
    auth_csrf_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    auth_csrf_signing_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    auth_cookie_secure: bool = True
    auth_allowed_origins: list[AnyHttpUrl] = []
    auth_login_requests_per_minute: int = Field(default=5, ge=1, le=100)
    auth_requests_per_minute: int = Field(default=60, ge=1, le=1000)
    auth_client_capacity: int = Field(default=4096, ge=1, le=65536)
    auth_login_body_bytes: int = Field(default=16384, ge=1024, le=65536)
    auth_body_bytes: int = Field(default=1024, ge=2, le=4096)

    @field_validator("jwt_signing_key", "auth_csrf_signing_key")
    @classmethod
    def validate_jwt_signing_key(cls, key: SecretStr | None) -> SecretStr | None:
        if key is not None and re.fullmatch(r"[0-9a-fA-F]{64}", key.get_secret_value()) is None:
            raise ValueError("Signing keys must contain exactly 64 hexadecimal characters")
        return key

    @field_validator("jwt_issuer", "jwt_audience", mode="before")
    @classmethod
    def trim_jwt_identifier(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("jwt_issuer", "jwt_audience")
    @classmethod
    def validate_jwt_identifier_unicode(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("JWT identifiers must contain valid Unicode") from None
        return value

    @field_validator("db_password")
    @classmethod
    def validate_database_password(cls, password: SecretStr | None) -> SecretStr | None:
        if password is not None and (
            not password.get_secret_value().strip()
            or password.get_secret_value() == "replace-with-a-long-random-local-password"
        ):
            raise ValueError(
                "Set a database password instead of an empty value or example placeholder"
            )
        return password

    @field_validator("cors_origins", "auth_allowed_origins")
    @classmethod
    def validate_origins(cls, origins: list[AnyHttpUrl]) -> list[AnyHttpUrl]:
        for origin in origins:
            if (
                origin.username is not None
                or origin.password is not None
                or origin.path not in (None, "/")
                or origin.query is not None
                or origin.fragment is not None
                or "*" in (origin.host or "")
            ):
                raise ValueError("CORS entries must be explicit HTTP origins without credentials")
        return origins

    @model_validator(mode="after")
    def validate_production_origins(self) -> "Settings":
        if self.environment == "production" and any(
            origin.scheme != "https" for origin in [*self.cors_origins, *self.auth_allowed_origins]
        ):
            raise ValueError("Production CORS origins must use HTTPS")
        if self.environment == "production" and not self.auth_cookie_secure:
            raise ValueError("Production authentication cookies must be secure")
        if (
            self.jwt_signing_key is not None
            and self.auth_csrf_signing_key is not None
            and bytes.fromhex(self.jwt_signing_key.get_secret_value())
            == bytes.fromhex(self.auth_csrf_signing_key.get_secret_value())
        ):
            raise ValueError("Authentication signing keys must be distinct")
        return self
