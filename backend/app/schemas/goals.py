"""Owned goal metadata; targets are exact BRL amounts, not reserved money."""

from datetime import date
from decimal import Decimal
from typing import Literal
from unicodedata import category
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.accounts import AccountInput
from app.schemas.auth import RegistrationInput


class GoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    target_amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    target_date: date | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "description")
    @classmethod
    def safe_text(cls, value):
        if value is not None and any(category(char) in {"Cc", "Cf", "Cs"} for char in value):
            raise ValueError("Use single-line Unicode text without control characters")
        return RegistrationInput.nonblank_name(value) if value is not None else None

    @field_validator("target_amount", mode="before")
    @classmethod
    def exact_money(cls, value):
        return AccountInput.decimal_string(value)

    @field_validator("target_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        return None if value is None else AccountInput.iso_date(value)

    @field_serializer("target_amount", when_used="json")
    def money_string(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")


class GoalUpdateInput(GoalInput):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    status: Literal["active", "completed", "cancelled"] | None = None

    @model_validator(mode="after")
    def explicit_changes(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None
            for field in self.model_fields_set - {"description", "target_date"}
        ):
            raise ValueError("Supply goal changes; only description and target date may be null")
        return self


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: str | None
    target_amount: Decimal
    target_date: date | None
    status: Literal["active", "completed", "cancelled"]

    @field_serializer("target_amount")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class GoalCreatedResponse(BaseModel):
    id: UUID


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
    limit: int
    offset: int
    has_more: bool
