"""Registration accepts credentials but never serializes them in a response."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class RegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=120)
    email: EmailStr = Field(max_length=255)
    password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("name", "email", mode="before")
    @classmethod
    def trim_identity(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value:
            raise ValueError("Name is required")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Name must contain valid Unicode") from None
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("password")
    @classmethod
    def nonblank_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Password is required")
        try:
            value.get_secret_value().encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Password must contain valid Unicode") from None
        return value


class RegistrationResponse(BaseModel):
    message: str = "Solicitação processada. Tente entrar com os dados informados."
