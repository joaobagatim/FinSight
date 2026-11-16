"""Complete preview corrections and explicit selection; no financial confirmation."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_validator

from app.schemas.accounts import AccountInput
from app.schemas.goals import GoalInput
from app.schemas.transactions import TransactionDetailsInput


class ImportRowEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    transaction_date: date
    description: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    type: Literal["income", "expense"]
    category_id: UUID4 | None = None

    @field_validator("transaction_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        return AccountInput.iso_date(value)

    @field_validator("description", mode="before")
    @classmethod
    def trim_description(cls, value):
        return GoalInput.trim_text(value)

    @field_validator("description")
    @classmethod
    def safe_description(cls, value):
        return GoalInput.safe_text(value)

    @field_validator("amount", mode="before")
    @classmethod
    def exact_money(cls, value):
        return AccountInput.decimal_string(value)

    @field_validator("category_id", mode="before")
    @classmethod
    def owned_category_key(cls, value):
        return None if value is None else TransactionDetailsInput.canonical_uuid(value)


class ImportSelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    selected: bool
