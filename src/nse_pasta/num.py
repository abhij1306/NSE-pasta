"""Numbers read from outside become exact `Decimal`s here, by one rule, never floats."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

_ALLOWED = set("0123456789+-.eE")


def exact(text: str | None, *, grouped: bool = False) -> Decimal | None:
    """`text` as a finite Decimal, or None when it is not a plain number. `grouped` drops
    thousands separators first ("1,23,456.50", as screener.in writes them)."""
    if text is None:
        return None
    raw = text.strip()
    if grouped:
        raw = raw.replace(",", "")
    if not raw or not set(raw) <= _ALLOWED:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None
