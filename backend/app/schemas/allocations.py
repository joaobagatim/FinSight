"""Exact reservation ledger inputs and current-day availability snapshots."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.accounts import AccountInput, AccountResponse
from app.schemas.goals import GoalInput, GoalResponse
from app.schemas.transactions import TransactionDetailsInput


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    account_id: UUID4
    kind: Literal["reserve", "withdraw"]
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    allocation_date: date
    notes: str | None = Field(default=None, min_length=1, max_length=2000)

    @field_validator("account_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value):
        return TransactionDetailsInput.canonical_uuid(value)

    @field_validator("amount", mode="before")
    @classmethod
    def money(cls, value):
        return AccountInput.decimal_string(value)

    @field_validator("allocation_date", mode="before")
    @classmethod
    def iso_date(cls, value):
        return AccountInput.iso_date(value)

    @field_validator("notes", mode="before")
    @classmethod
    def trim_notes(cls, value):
        return GoalInput.trim_text(value)

    @field_validator("notes")
    @classmethod
    def safe_notes(cls, value):
        return GoalInput.safe_text(value)

    @field_serializer("amount", when_used="json")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class ExactAmounts(BaseModel):
    @field_serializer("*", check_fields=False, when_used="json")
    def serialize_exact(self, value):
        return format(value, ".2f") if isinstance(value, Decimal) else value


class GoalFundingResponse(ExactAmounts):
    goal: GoalResponse
    as_of: date
    reserved_amount: Decimal
    remaining_amount: Decimal
    excess_amount: Decimal
    progress_percent: Decimal


class AvailabilityResponse(ExactAmounts):
    account: AccountResponse
    as_of: date
    bank_balance: Decimal
    reserved_amount: Decimal
    free_balance: Decimal
    uncovered_reserved: Decimal


class AllocationContextResponse(BaseModel):
    funding: GoalFundingResponse
    availability: AvailabilityResponse
    reserved_in_account: Decimal

    @field_serializer("reserved_in_account")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class AllocationResponse(ExactAmounts):
    id: UUID
    goal_id: UUID
    account_id: UUID
    account_name: str
    amount: Decimal
    allocation_date: date
    notes: str | None


class AllocationCreatedResponse(BaseModel):
    id: UUID


class AllocationListResponse(BaseModel):
    items: list[AllocationResponse]
    limit: int
    offset: int
    has_more: bool


class ReservationAlertsResponse(BaseModel):
    as_of: date
    account_count: int
    items: list[AvailabilityResponse]
