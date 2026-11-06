"""Strict BRL transfers between distinct owned accounts."""

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

from app.schemas.transactions import TransactionDetailsInput


class TransferDetailsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)

    from_account_id: UUID4
    to_account_id: UUID4
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    effective_date: date
    description: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("from_account_id", "to_account_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value):
        return TransactionDetailsInput.canonical_uuid(value)

    @field_validator("amount", mode="before")
    @classmethod
    def money(cls, value):
        return TransactionDetailsInput.money(value)

    @field_validator("effective_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        return TransactionDetailsInput.iso_date(value)

    @field_validator("description", mode="before")
    @classmethod
    def description_text(cls, value):
        return TransactionDetailsInput.unicode_text(TransactionDetailsInput.trim_text(value))

    @model_validator(mode="after")
    def distinct_accounts(self):
        if self.from_account_id is not None and self.from_account_id == self.to_account_id:
            raise ValueError("Select distinct accounts")
        return self

    @field_serializer("amount", when_used="json")
    def money_string(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, ".2f")


class TransferInput(TransferDetailsInput):
    status: Literal["planned", "posted"]


class TransferUpdateInput(TransferDetailsInput):
    from_account_id: UUID4 | None = None
    to_account_id: UUID4 | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    effective_date: date | None = None

    @model_validator(mode="after")
    def nonempty_nonnull(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set - {"description"}
        ):
            raise ValueError("Supply at least one field; only description may be null")
        return self


class TransferPostInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class TransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    from_account_id: UUID
    to_account_id: UUID
    from_account_name: str = Field(validation_alias=AliasPath("from_account", "name"))
    to_account_name: str = Field(validation_alias=AliasPath("to_account", "name"))
    amount: Decimal
    status: Literal["planned", "posted"]
    effective_date: date
    description: str | None

    @field_serializer("amount")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class TransferCreatedResponse(BaseModel):
    id: UUID


class TransferListResponse(BaseModel):
    items: list[TransferResponse]
    limit: int
    offset: int
    has_more: bool
