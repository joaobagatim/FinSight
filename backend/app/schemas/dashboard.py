"""Exact, descriptive activity totals; these are not accumulated balances."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class DashboardSummaryResponse(BaseModel):
    date_from: date
    date_to: date
    as_of: date
    scope: Literal["active", "all", "selected"]
    account_ids: list[UUID] | None
    account_count: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    currency: Literal["BRL"] = "BRL"
    income: Decimal = Field(ge=0)
    expense: Decimal = Field(ge=0)
    net: Decimal

    @field_serializer("income", "expense", "net")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")
