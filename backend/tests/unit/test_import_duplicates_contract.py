"""Matching fingerprints are exact, scoped and conservative normalization only."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.services.import_duplicates import fingerprint


def test_duplicate_fingerprint_normalizes_text_but_preserves_account_date_money_and_type():
    account, day, amount = uuid4(), date(2026, 1, 2), Decimal("12.30")
    key = fingerprint(account, day, amount, "expense", "  CAFÉ\tＡ  ")
    assert key == fingerprint(account, day, Decimal("12.3"), "expense", "café a")
    assert len(key) == 64
    assert key != fingerprint(uuid4(), day, amount, "expense", "café a")
    assert key != fingerprint(account, date(2026, 1, 3), amount, "expense", "café a")
    assert key != fingerprint(account, day, Decimal("12.31"), "expense", "café a")
    assert key != fingerprint(account, day, amount, "income", "café a")
    assert key != fingerprint(account, day, amount, "expense", "cafe a")
    assert fingerprint(account, None, amount, "expense", "x") is None
    assert fingerprint(account, day, Decimal("0"), "expense", "x") is None
    assert fingerprint(account, day, amount, "expense", "   ") is None
