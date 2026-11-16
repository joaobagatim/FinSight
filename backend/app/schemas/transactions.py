"""Manual transaction contracts with exact decimal money and calendar dates."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    UUID4,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.accounts import AccountInput
from app.schemas.auth import RegistrationInput


class TransactionDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    account_id: UUID4
    category_id: UUID4
    description: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    type: Literal["income", "expense"]
    effective_date: date
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("account_id", "category_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value):
        if not isinstance(value, str):
            raise ValueError("Use a UUID string")
        parsed = UUID(value)
        if str(parsed) != value.lower():
            raise ValueError("Use a canonical UUID")
        return parsed

    @field_validator("description", "notes", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", "notes")
    @classmethod
    def unicode_text(cls, value):
        if value is None:
            return None
        return RegistrationInput.nonblank_name(value)

    @field_validator("amount", mode="before")
    @classmethod
    def money(cls, value):
        return AccountInput.decimal_string(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        return AccountInput.iso_date(value)

    @field_serializer("amount", when_used="json")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class TransactionInput(TransactionDetailsInput):
    status: Literal["planned", "posted"]


class TransactionUpdateInput(TransactionDetailsInput):
    account_id: UUID4 | None = None
    category_id: UUID4 | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    type: Literal["income", "expense"] | None = None
    effective_date: date | None = None

    @model_validator(mode="after")
    def nonempty_nonnull(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set - {"notes"}
        ):
            raise ValueError("Supply at least one field; only notes may be null")
        return self


class TransactionPostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    category_id: UUID
    account_name: str = Field(validation_alias=AliasPath("account", "name"))
    category_name: str = Field(validation_alias=AliasPath("category", "name"))
    description: str
    amount: Decimal
    type: Literal["income", "expense"]
    status: Literal["planned", "posted"]
    effective_date: date
    notes: str | None

    @field_serializer("amount")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class TransactionCreatedResponse(BaseModel):
    id: UUID


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    limit: int
    offset: int
    has_more: bool


class AccountBalanceResponse(BaseModel):
    account_id: UUID
    as_of: date
    currency: Literal["BRL"] = "BRL"
    opening_date: date
    opening_balance: Decimal
    balance: Decimal

    @field_serializer("opening_balance", "balance")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class ConsolidatedBalanceResponse(BaseModel):
    as_of: date
    scope: Literal["active", "all", "selected"]
    currency: Literal["BRL"] = "BRL"
    account_ids: list[UUID] | None
    account_count: int = Field(ge=0)
    balance: Decimal

    @field_serializer("balance")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class ProjectedBalanceResponse(BaseModel):
    base_date: date
    target_date: date
    overdue_policy: Literal["include", "exclude"]
    scope: Literal["active", "all", "selected"]
    currency: Literal["BRL"] = "BRL"
    account_ids: list[UUID] | None
    account_count: int = Field(ge=0)
    base_balance: Decimal
    posted_future_delta: Decimal
    planned_delta: Decimal
    projected_balance: Decimal

    @field_serializer("base_balance", "posted_future_delta", "planned_delta", "projected_balance")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class BalanceHistoryPoint(BaseModel):
    date: date
    balance: Decimal

    @field_serializer("balance")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class BalanceHistoryResponse(BaseModel):
    account_id: UUID
    account_name: str
    opening_date: date
    date_from: date
    date_to: date
    currency: Literal["BRL"] = "BRL"
    points: list[BalanceHistoryPoint] = Field(min_length=1, max_length=93)
