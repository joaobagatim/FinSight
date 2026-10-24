"""Validated configuration loaded from the environment or the root .env file."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINSIGHT_",
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    cors_origins: list[AnyHttpUrl] = []

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
