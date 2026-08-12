"""Financial formatting helpers shared by the UI, evidence builder and
deterministic fallback answers."""
from __future__ import annotations

import math


# Fields that are calendar years or plain ordinals: always rendered as bare
# integers (2026), never with thousands separators or decimals (2,026.0).
YEAR_FIELDS = {"accident_year", "underwriting_year", "origin_year"}
INTEGER_FIELDS = YEAR_FIELDS | {"development_period_quarters", "slide_number",
                                "sequence_no"}


def is_year_field(field: str) -> bool:
    return str(field).strip().lower() in YEAR_FIELDS


def is_integer_field(field: str) -> bool:
    return str(field).strip().lower() in INTEGER_FIELDS


def fmt_year(value) -> str:
    """Render a year (or any bare ordinal) with no separators or decimals."""
    if value is None:
        return "n/a"
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return str(value)


def to_millions(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return round(value / 1e6, 1)


def fmt_gbp_m(value: float | None, signed: bool = False, decimals: int = 1) -> str:
    """Format a GBP amount (in pounds) as e.g. 'GBP 640m' / '+GBP 26m'."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    m = value / 1e6
    if abs(m - round(m)) < 0.05:
        text = f"{abs(round(m)):,}"
    else:
        text = f"{abs(m):,.{decimals}f}"
    sign = "-" if m < 0 else ("+" if signed else "")
    return f"{sign}GBP {text}m"


def fmt_pct(value: float | None, decimals: int = 1, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    sign = "+" if (signed and value > 0) else ""
    return f"{sign}{value:.{decimals}f}%"


def fmt_count(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:,.0f}"


def fmt_ratio(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value * 100:.1f}%"


def fmt_measure(value: float | None, unit: str, signed: bool = False) -> str:
    if unit == "GBP":
        return fmt_gbp_m(value, signed=signed)
    if unit == "ratio":
        return fmt_ratio(value)
    if unit == "count":
        return fmt_count(value)
    if unit == "factor":
        return "n/a" if value is None else f"{value:.3f}"
    return "n/a" if value is None else f"{value:,.2f}"


def display_unit(unit: str) -> str:
    return {"GBP": "GBP millions", "ratio": "percent", "count": "claims",
            "factor": "factor"}.get(unit, unit)
