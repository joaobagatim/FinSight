"""Minimal owned advisory reports, with no matched third-party record details."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DuplicateItem(BaseModel):
    row_id: UUID
    row_number: int
    reasons: list[
        Literal[
            "same_preview_fingerprint",
            "same_preview_external_id",
            "other_preview_fingerprint",
            "other_preview_external_id",
            "transaction_fingerprint",
            "transaction_external_id",
        ]
    ]


class DuplicateReport(BaseModel):
    job_id: UUID
    checked_rows: int
    unchecked_rows: int
    period_start: date | None
    period_end: date | None
    overlapping_period: bool
    scan_limited: bool
    candidate_limit: int
    items: list[DuplicateItem]
