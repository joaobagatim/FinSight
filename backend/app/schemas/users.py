"""Credential-only input for authenticated password changes; never echo secrets."""

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.schemas.auth import RegistrationInput


class PasswordChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    current_password: SecretStr = Field(min_length=15, max_length=128)
    new_password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("current_password", "new_password")
    @classmethod
    def valid_password(cls, value: SecretStr) -> SecretStr:
        return RegistrationInput.nonblank_password(value)


class ProfileUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = Field(default=None, max_length=255)
    current_password: SecretStr | None = Field(default=None, min_length=15, max_length=128)

    @field_validator("name", "email", "current_password", mode="before")
    @classmethod
    def supplied_values_are_not_null(cls, value):
        if value is None:
            raise ValueError("Null is not a profile update")
        return value

    @field_validator("name", "email", mode="before")
    @classmethod
    def trim_identity(cls, value):
        return RegistrationInput.trim_identity(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        return RegistrationInput.nonblank_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return RegistrationInput.normalize_email(value)

    @field_validator("current_password")
    @classmethod
    def valid_password(cls, value: SecretStr) -> SecretStr:
        return RegistrationInput.nonblank_password(value)

    @model_validator(mode="after")
    def requires_profile_field(self):
        if self.name is None and self.email is None:
            raise ValueError("A profile field is required")
        if self.current_password is not None and self.email is None:
            raise ValueError("Reauthentication requires an email update")
        return self
