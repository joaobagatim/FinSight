"""Validated configuration loaded from the environment or the root .env file."""

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

    @field_validator("cors_origins")
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
            origin.scheme != "https" for origin in self.cors_origins
        ):
            raise ValueError("Production CORS origins must use HTTPS")
        return self
