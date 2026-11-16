"""Pure CSV parsing with explicit formats, exact money and recoverable row errors.

Never log input/preview objects. This module neither authorizes accounts nor writes
files, jobs or transactions. Callers must obtain opening_date from an owned account.
"""

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 32
MAX_CELL_CHARS = 4096
MAX_MONEY = Decimal("9999999999999.99")


class CsvRejected(ValueError):
    """Only fixed diagnostic codes, never source data or library error messages."""


@dataclass(frozen=True, slots=True, repr=False)
class CsvDocument:
    headers: tuple[str, ...]
    rows: tuple[tuple[int, tuple[str, ...]], ...]
    delimiter: str
    checksum: str


@dataclass(frozen=True, slots=True, repr=False)
class CsvLayout:
    date_column: int
    description_column: int
    date_format: Literal["iso", "day-first"]
    money_format: Literal["decimal-dot", "decimal-comma"]
    amount_column: int | None = None
    debit_column: int | None = None
    credit_column: int | None = None
    external_id_column: int | None = None


@dataclass(frozen=True, slots=True, repr=False)
class PreviewRow:
    row_number: int
    transaction_date: date | None
    description: str | None
    amount: Decimal | None
    type: Literal["income", "expense"] | None
    external_id: str | None
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def _safe_text(value: str) -> bool:
    return not any(unicodedata.category(char).startswith("C") for char in value)


def _reader(text: str, delimiter: str):
    # Do not mutate csv.field_size_limit: it is process-global and unsafe across requests.
    return csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)


def _delimiter(text: str) -> str:
    candidates = []
    for delimiter in (",", ";"):
        try:
            header = next(_reader(text, delimiter), [])
        except csv.Error:
            continue
        if len(header) > 1:
            candidates.append(delimiter)
    if len(candidates) != 1:
        raise CsvRejected("choose_delimiter")
    return candidates[0]


def read_csv(content: bytes, *, delimiter: str | None = None) -> CsvDocument:
    """Read bounded UTF-8 bytes; ambiguous delimiters require an explicit choice.

    Row numbers are CSV record ordinals (header is 1), not physical line numbers:
    quoted cells can contain line breaks. Empty physical records are skipped.
    """
    if not isinstance(content, bytes):
        raise CsvRejected("invalid_content")
    if not content:
        raise CsvRejected("empty_file")
    if len(content) > MAX_BYTES:
        raise CsvRejected("file_too_large")
    try:
        text = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise CsvRejected("unsupported_encoding") from None
    if not text.strip():
        raise CsvRejected("empty_file")
    if any(ord(char) < 32 and char not in "\r\n\t" for char in text):
        raise CsvRejected("invalid_control_character")
    if delimiter is None:
        delimiter = _delimiter(text)
    if delimiter not in (",", ";"):
        raise CsvRejected("invalid_delimiter")
    try:
        reader = _reader(text, delimiter)
        headers = tuple(cell.strip() for cell in next(reader, []))
        if (
            not headers
            or len(headers) > MAX_COLUMNS
            or any(not cell or len(cell) > 100 or not _safe_text(cell) for cell in headers)
            or len({cell.casefold() for cell in headers}) != len(headers)
        ):
            raise CsvRejected("invalid_headers")
        rows = []
        for number, cells in enumerate(reader, start=2):
            if not cells:
                continue
            if len(rows) >= MAX_ROWS:
                raise CsvRejected("too_many_rows")
            if len(cells) > MAX_COLUMNS or any(len(cell) > MAX_CELL_CHARS for cell in cells):
                raise CsvRejected("row_too_large")
            rows.append((number, tuple(cells)))
        if not rows:
            raise CsvRejected("empty_data")
    except csv.Error:
        raise CsvRejected("malformed_csv") from None
    return CsvDocument(headers, tuple(rows), delimiter, hashlib.sha256(content).hexdigest())


def _validate_layout(document: CsvDocument, layout: CsvLayout, opening_date: date):
    if (
        type(opening_date) is not date
        or layout.date_format not in ("iso", "day-first")
        or layout.money_format not in ("decimal-dot", "decimal-comma")
    ):
        raise CsvRejected("invalid_layout")
    signed = layout.amount_column is not None
    split = layout.debit_column is not None and layout.credit_column is not None
    if signed == split or (
        signed and (layout.debit_column is not None or layout.credit_column is not None)
    ):
        raise CsvRejected("invalid_amount_mapping")
    columns = [layout.date_column, layout.description_column]
    columns += [
        i
        for i in (
            layout.amount_column,
            layout.debit_column,
            layout.credit_column,
            layout.external_id_column,
        )
        if i is not None
    ]
    if any(
        type(index) is not int or not 0 <= index < len(document.headers) for index in columns
    ) or len(set(columns)) != len(columns):
        raise CsvRejected("invalid_column_mapping")


def _date(value: str, date_format: str) -> date:
    value = value.strip()
    if date_format == "iso" and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    if date_format == "day-first" and re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", value):
        day, month, year = map(int, value.split("/"))
        return date(year, month, day)
    raise ValueError("invalid_date")


def _money(value: str, money_format: str) -> Decimal:
    value = value.strip()
    pattern = (
        r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,2})?"
        if money_format == "decimal-comma"
        else r"[+-]?[0-9]+(?:\.[0-9]{1,2})?"
    )
    if not re.fullmatch(pattern, value):
        raise ValueError("invalid_amount")
    normalized = (
        value.replace(".", "").replace(",", ".") if money_format == "decimal-comma" else value
    )
    # Bound significant digits before Decimal operations; long zero padding is harmless.
    integer = normalized.lstrip("+-").split(".")[0].lstrip("0")
    if len(integer) > 13:
        raise ValueError("invalid_amount")
    amount = Decimal(normalized)
    if abs(amount) > MAX_MONEY:
        raise ValueError("invalid_amount")
    return amount.quantize(Decimal("0.01"))


def normalize_rows(
    document: CsvDocument, layout: CsvLayout, *, opening_date: date
) -> tuple[PreviewRow, ...]:
    """Produce a technical preview; valid rows still require review and authorization.

    No duplicate removal, categorization, transfer inference or financial posting.
    Invalid data is represented by field-specific codes, without copying raw values.
    """
    _validate_layout(document, layout, opening_date)
    result = []
    for number, cells in document.rows:
        errors = []
        day = description = amount = kind = external_id = None
        if len(cells) != len(document.headers):
            errors.append("column_count")
        else:
            try:
                day = _date(cells[layout.date_column], layout.date_format)
                if day <= opening_date:
                    errors.append("date_not_after_opening")
            except ValueError:
                errors.append("invalid_date")
            description = cells[layout.description_column].strip()
            if not 1 <= len(description) <= 255 or not _safe_text(description):
                description = None
                errors.append("invalid_description")
            try:
                if layout.amount_column is not None:
                    signed = _money(cells[layout.amount_column], layout.money_format)
                    kind = "expense" if signed < 0 else "income"
                    amount = abs(signed)
                else:
                    debit = cells[layout.debit_column].strip()
                    credit = cells[layout.credit_column].strip()
                    debit = _money(debit, layout.money_format) if debit else Decimal(0)
                    credit = _money(credit, layout.money_format) if credit else Decimal(0)
                    if debit < 0 or credit < 0 or bool(debit) == bool(credit):
                        raise ValueError("invalid_amount")
                    kind, amount = ("expense", debit) if debit else ("income", credit)
                if amount == 0:
                    raise ValueError("invalid_amount")
            except ValueError:
                amount = kind = None
                errors.append("invalid_amount")
            if layout.external_id_column is not None:
                external_id = cells[layout.external_id_column].strip() or None
                if external_id is not None and (
                    len(external_id) > 255 or not _safe_text(external_id)
                ):
                    external_id = None
                    errors.append("invalid_external_id")
        result.append(
            PreviewRow(number, day, description, amount, kind, external_id, tuple(errors))
        )
    return tuple(result)
