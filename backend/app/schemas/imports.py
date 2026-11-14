"""Sensitive CSV sources and owned preview responses; no financial confirmation input."""

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
)

from app.imports.csv_parser import MAX_BYTES, CsvLayout
from app.schemas.goals import GoalInput
from app.schemas.transactions import TransactionDetailsInput

MAX_BASE64_CHARS = 4 * ((MAX_BYTES + 2) // 3)


class CsvMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    date_column: int = Field(ge=0, le=31)
    description_column: int = Field(ge=0, le=31)
    date_format: Literal["iso", "day-first"]
    money_format: Literal["decimal-dot", "decimal-comma"]
    amount_column: int | None = Field(default=None, ge=0, le=31)
    debit_column: int | None = Field(default=None, ge=0, le=31)
    credit_column: int | None = Field(default=None, ge=0, le=31)
    external_id_column: int | None = Field(default=None, ge=0, le=31)

    def layout(self) -> CsvLayout:
        return CsvLayout(**self.model_dump())


class ImportSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)
    account_id: UUID4
    filename: str = Field(min_length=5, max_length=255)
    content_base64: SecretStr = Field(min_length=1, max_length=MAX_BASE64_CHARS, repr=False)
    delimiter: Literal[",", ";"] | None = None

    @field_validator("account_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value):
        return TransactionDetailsInput.canonical_uuid(value)

    @field_validator("filename", mode="before")
    @classmethod
    def trim_filename(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        GoalInput.safe_text(value)
        if any(char in value for char in ("/", "\\", ":")) or not value.lower().endswith(".csv"):
            raise ValueError("Use a CSV base filename")
        return value


class ImportInput(ImportSourceInput):
    mapping: CsvMappingInput


class ImportInspectionResponse(BaseModel):
    account_id: UUID
    opening_date: date
    headers: list[str]
    delimiter: str
    total_rows: int
    sample: list[list[str]]
    matching_files: int


class ImportCreatedResponse(BaseModel):
    id: UUID


class ImportJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    filename: str
    status: str
    total_rows: int
    imported_rows: int
    invalid_rows: int
    matching_files: int
    selected_rows: int = 0


class ImportRowResponse(BaseModel):
    id: UUID
    row_number: int
    transaction_date: date | None
    description: str | None
    amount: Decimal | None
    type: str | None
    external_id: str | None
    status: str
    error_codes: list[str]
    selected: bool = False
    category_id: UUID | None = None
    category_name: str | None = None
    review_errors: list[str] = Field(default_factory=list)
    editable: bool = False
    selection_editable: bool = False
    selection_eligible: bool = False
    etag: str = ""

    @field_serializer("amount", when_used="json")
    def exact_money(self, value):
        return format(value, ".2f") if value is not None else None


class ImportListResponse(BaseModel):
    items: list[ImportJobResponse]
    limit: int
    offset: int
    has_more: bool


class ImportRowsResponse(BaseModel):
    items: list[ImportRowResponse]
    limit: int
    offset: int
    has_more: bool
