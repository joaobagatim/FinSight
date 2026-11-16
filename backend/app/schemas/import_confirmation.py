"""Explicit acknowledgements and exact historical receipts for CSV confirmation."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.allocations import ExactAmounts
from app.schemas.import_duplicates import DuplicateReport
from app.schemas.imports import ImportRowResponse


class ImportConfirmationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    acknowledge_duplicates: bool
    acknowledge_classification: bool
    acknowledge_reservations: bool

    @field_validator("*")
    @classmethod
    def explicit_acceptance(cls, value):
        if value is not True:
            raise ValueError("Explicit acknowledgement required")
        return value


class ConfirmationAmounts(ExactAmounts):
    job_id: UUID
    account_id: UUID
    account_name: str
    filename: str
    as_of: date
    income_total: Decimal
    expense_total: Decimal
    bank_balance_before: Decimal
    bank_balance_after: Decimal
    reserved_amount: Decimal
    free_balance_after: Decimal
    uncovered_reserved_after: Decimal
    invalid_rows: int
    future_rows: int


class ImportConfirmationReceipt(ConfirmationAmounts):
    imported_rows: int
    not_imported_rows: int
    completed_at: datetime


class ImportConfirmationContext(ConfirmationAmounts):
    total_rows: int
    selected_count: int
    selected_rows: list[ImportRowResponse] = Field(default_factory=list)
    eligible: bool
    issues: list[str] = Field(default_factory=list)
    matching_files: int = 0
    duplicates: DuplicateReport | None = None
    receipt: ImportConfirmationReceipt | None = None
    etag: str = ""
