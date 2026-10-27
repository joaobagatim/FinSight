"""Exact positive and signed money validation for domain persistence models."""

from decimal import Decimal


def positive_money(value: Decimal) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= 0
        or value > Decimal("9999999999999.99")
        or value != value.quantize(Decimal("0.01"))
    ):
        raise ValueError("Amount must be a positive finite Decimal within NUMERIC(15,2)")
    return value


def nonzero_money(value: Decimal) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value == 0
        or value.copy_abs() > Decimal("9999999999999.99")
        or value != value.quantize(Decimal("0.01"))
    ):
        raise ValueError("Amount must be a nonzero finite Decimal within NUMERIC(15,2)")
    return value
