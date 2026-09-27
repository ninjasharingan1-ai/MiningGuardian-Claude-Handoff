"""Numeric validation without conflating missing, malformed, and zero."""

import math
from decimal import Decimal, InvalidOperation

from .models import Quality


def numeric(raw: object, *, minimum: float = 0, maximum: float | int | None = None,
            integer: bool = False) -> tuple[int | float | None, Quality]:
    if raw is None:
        return None, Quality.MISSING
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None, Quality.CORRUPTED
    try:
        value = Decimal(str(raw))
        if not value.is_finite():
            return None, Quality.CORRUPTED
        if integer and value != value.to_integral_value():
            return None, Quality.CORRUPTED
        upper = (2**63 - 1) if integer and maximum is None else maximum
        if value < minimum or (upper is not None and value > upper):
            return None, Quality.OUT_OF_RANGE
        result = int(value) if integer else float(value)
        if not math.isfinite(result):
            return None, Quality.OUT_OF_RANGE
        return result, Quality.VALID
    except (ValueError, OverflowError, InvalidOperation):
        return None, Quality.CORRUPTED


def raw_scalar(raw: object) -> str | int | float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            if math.isfinite(raw):
                return raw
        except OverflowError:
            pass
    # A diagnostic representation, never a successful canonical numeric value.
    return str(raw)[:512]
