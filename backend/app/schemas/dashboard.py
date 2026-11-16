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


class DailyActivity(BaseModel):
    date: date
    transaction_count: int = Field(ge=0)
    income: Decimal = Field(ge=0)
    expense: Decimal = Field(ge=0)
    net: Decimal

    @field_serializer("income", "expense", "net")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class CategoryExpense(BaseModel):
    category_id: UUID
    name: str
    amount: Decimal = Field(gt=0)
    transaction_count: int = Field(ge=1)

    @field_serializer("amount")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class OtherExpenses(BaseModel):
    category_count: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    amount: Decimal = Field(ge=0)

    @field_serializer("amount")
    def money_string(self, value: Decimal) -> str:
        return format(value, ".2f")


class DashboardBreakdownResponse(DashboardSummaryResponse):
    daily: list[DailyActivity] = Field(min_length=1, max_length=366)
    expense_categories: list[CategoryExpense] = Field(max_length=20)
    category_limit: Literal[20] = 20
    expense_category_count: int = Field(ge=0)
    other_expenses: OtherExpenses
