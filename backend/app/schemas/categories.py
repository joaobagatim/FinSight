"""Strict owner-independent category input and public representations."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.auth import RegistrationInput


class CategoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=100)
    type: Literal["income", "expense"]
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, max_length=50, pattern=r"^[a-z][a-z0-9-]*$")

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return RegistrationInput.trim_identity(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return RegistrationInput.nonblank_name(value)


class CategoryUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, max_length=50, pattern=r"^[a-z][a-z0-9-]*$")
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return RegistrationInput.trim_identity(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return RegistrationInput.nonblank_name(value)

    @model_validator(mode="after")
    def explicit_changes(self):
        if not self.model_fields_set or any(
            field in self.model_fields_set and getattr(self, field) is None
            for field in ("name", "is_active")
        ):
            raise ValueError("Provide valid category changes")
        return self


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: Literal["income", "expense"]
    color: str | None
    icon: str | None
    is_active: bool


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]
    limit: int
    offset: int
    has_more: bool
