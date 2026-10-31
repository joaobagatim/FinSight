"""Strict account inputs and money serialized as decimal strings."""

import re
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.auth import RegistrationInput


class AccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True, frozen=True)

    name: str = Field(min_length=1, max_length=100)
    type: Literal["checking", "savings", "cash", "investment"]
    currency: Literal["BRL"] = "BRL"
    opening_balance: Decimal = Field(max_digits=15, decimal_places=2)
    opening_date: date

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return RegistrationInput.trim_identity(value)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        return RegistrationInput.nonblank_name(value)

    @field_validator("opening_balance", mode="before")
    @classmethod
    def decimal_string(cls, value):
        if (
            not isinstance(value, str)
            or re.fullmatch(r"-?(0|[1-9][0-9]{0,12})(\.[0-9]{1,2})?", value) is None
        ):
            raise ValueError("Use a finite decimal string with at most two decimal places")
        amount = Decimal(value).quantize(Decimal("0.01"))
        return Decimal("0.00") if amount == 0 else amount

    @field_validator("opening_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Use an ISO date")
        return date.fromisoformat(value)

    @field_serializer("opening_balance", when_used="json")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: str
    currency: str
    opening_balance: Decimal
    opening_date: date
    is_active: bool

    @field_serializer("opening_balance")
    def serialize_money(self, value: Decimal) -> str:
        return format(value, ".2f")


class AccountCreatedResponse(BaseModel):
    id: UUID


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    limit: int
    offset: int
    has_more: bool
