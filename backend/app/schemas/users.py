"""Credential-only input for authenticated password changes; never echo secrets."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.auth import RegistrationInput


class PasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    current_password: SecretStr = Field(min_length=15, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("current_password", "new_password")
    @classmethod
    def valid_password(cls, value: SecretStr) -> SecretStr:
        return RegistrationInput.nonblank_password(value)
