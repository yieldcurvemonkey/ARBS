"""
Data parsing utilities for SDR analytics.

This module provides functions for parsing SDR data fields
like notional amounts, rates, and other numeric values.

Sentinel values are canonical "unknown" markers defined by CFTC Part 43/45
v3.1 Tech Spec — a field reported at its sentinel means "not disclosed" and
must be masked before numeric aggregation.
"""

from __future__ import annotations

from typing import Any, List, Literal, Tuple, Union

import numpy as np
import pandas as pd


# Canonical "unknown" sentinels per Tech Spec Appendix G
PRICE_SENTINEL: float = 99999.9999999999999
SPREAD_DECIMAL_SENTINEL: float = 9.9999999999
SPREAD_BPS_SENTINEL: float = 99999.0
PACKAGE_PRICE_SENTINEL: float = 99999.9999999999999

_SENTINEL_TOL = 1e-6

_FIELD_SENTINELS: dict[str, float] = {
    "price": PRICE_SENTINEL,
    "spread_decimal": SPREAD_DECIMAL_SENTINEL,
    "spread_bps": SPREAD_BPS_SENTINEL,
    "package_price": PACKAGE_PRICE_SENTINEL,
}


def parse_notional(notional_str: Union[str, float, int]) -> Tuple[float, bool]:
    # parsed notional as type float, boolean is capped notional reported
    if pd.isna(notional_str) or notional_str == "":
        return 0.0, False
    if isinstance(notional_str, (int, float)):
        return float(notional_str), False

    # capped notionals
    if "+" in notional_str:
        return float(str(notional_str).replace(",", "").replace("+", "").strip()), True

    # Remove commas and convert
    try:
        return float(str(notional_str).replace(",", "").strip()), False
    except Exception:
        return 0.0, False


def mask_sentinels(
    series: pd.Series,
    field_type: Literal["price", "spread_decimal", "spread_bps", "package_price"],
) -> pd.Series:
    """Replace Part 43/45 "unknown" sentinels with NaN.

    Args:
        series: Numeric series (already coerced to float).
        field_type: Which sentinel table to consult.

    Returns:
        Series with sentinel cells replaced by ``np.nan``.
    """
    sentinel = _FIELD_SENTINELS.get(field_type)
    if sentinel is None:
        return series
    numeric = pd.to_numeric(series, errors="coerce")
    mask = np.isclose(numeric.to_numpy(dtype=float, na_value=np.nan), sentinel, atol=_SENTINEL_TOL)
    out = numeric.astype(float).copy()
    out[mask] = np.nan
    return out


def _is_sentinel_scalar(value: float, field_type: str) -> bool:
    sentinel = _FIELD_SENTINELS.get(field_type)
    if sentinel is None:
        return False
    try:
        return abs(float(value) - sentinel) <= _SENTINEL_TOL
    except (TypeError, ValueError):
        return False


def parse_notation_scalar(value: Any, notation: Any) -> float:
    """Normalize a scalar to decimal per CFTC Part 43/45 notation codes.

    Codes per [#52]/[#77]:
      - 1: monetary (caller must pair with currency; returned as-is)
      - 3: decimal (e.g. ``0.0257`` for 2.57%)
      - 4: basis points (e.g. ``257`` for 2.57%); divided by 10,000 here

    Unknown/missing notation falls back to decimal. Sentinel values map to NaN.

    Args:
        value: The reported numeric value.
        notation: Notation code (int or string).

    Returns:
        Decimal-normalized float (NaN on sentinel or unparseable).
    """
    val = to_float(value)
    if pd.isna(val):
        return float("nan")
    if _is_sentinel_scalar(val, "spread_decimal") or _is_sentinel_scalar(val, "spread_bps"):
        return float("nan")

    try:
        code = int(float(notation)) if notation is not None and not pd.isna(notation) else None
    except (TypeError, ValueError):
        code = None

    if code == 4:
        return val / 10000.0
    # codes 1 and 3 pass through; unknown defaults to decimal
    return val


def parse_sdr_timestamp(value: Any) -> pd.Timestamp:
    """Coerce an SDR-reported timestamp to a UTC-aware pandas Timestamp.

    Naive timestamps are assumed UTC (SDR reports in UTC per §45.3(a)).
    Returns ``pd.NaT`` on unparseable input.
    """
    if value is None:
        return pd.NaT
    try:
        if isinstance(value, pd.Timestamp) and pd.isna(value):
            return pd.NaT
    except (TypeError, ValueError):
        pass
    ts = pd.to_datetime(value, errors="coerce", utc=False)
    if pd.isna(ts):
        return pd.NaT
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def parse_schedule(cell: Any) -> List[Any]:
    """Parse a `;`-delimited SDR schedule cell into a list.

    N7: the SDR public tape uses ``;`` (semicolon) — not ``,`` — as the
    delimiter inside multi-value cells such as [#33] Effective date of
    the notional amount-Leg 1 and [#34] Notional amount in effect on
    associated effective date-Leg 1. Commas inside numeric values are
    stripped separately. Used for schedule fields and other multi-row
    data elements. Numeric cells are returned as ``float``, otherwise
    stripped strings. Empty/NaN → empty list.
    """
    if cell is None:
        return []
    if isinstance(cell, float) and pd.isna(cell):
        return []
    if isinstance(cell, list):
        return list(cell)
    raw = str(cell).strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(";") if p.strip() != ""]
    out: List[Any] = []
    for part in parts:
        cleaned = part.replace(",", "")
        try:
            out.append(float(cleaned))
        except ValueError:
            out.append(part)
    return out


def to_float(x) -> float:
    """
    Convert value to float, returning NaN for invalid values.

    Handles:
    - Numeric types (int, float, numpy numeric)
    - String representations with commas
    - Empty/null values

    Args:
        x: Value to convert

    Returns:
        Float value, or np.nan if conversion fails
    """
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def pv01_bucket(pv01: np.ndarray, tol: float) -> np.ndarray:
    """
    Bucket PV01 values by log scale for grouping similar-risk trades.

    Uses log scale so that "within % tolerance" becomes "nearby buckets".

    Args:
        pv01: Array of PV01 values
        tol: Tolerance as fraction (e.g., 0.10 for 10%)

    Returns:
        Array of bucket indices
    """
    pv01_pos = np.maximum(pv01, 1e-12)
    return np.floor(np.log(pv01_pos) / np.log(1.0 + tol)).astype(np.int32)


def tenor_bucket(tenor_years: np.ndarray, bucket_size: float = 0.25) -> np.ndarray:
    """
    Bucket tenor values for grouping similar tenors.

    Args:
        tenor_years: Array of tenor values in years
        bucket_size: Size of each bucket in years

    Returns:
        Array of bucket indices
    """
    return np.floor(tenor_years / bucket_size).astype(np.int32)


def extract_numeric_from_string(s: str, default: float = np.nan) -> float:
    """
    Extract first numeric value from a string.

    Args:
        s: String that may contain a number
        default: Default value if no number found

    Returns:
        Extracted float value or default
    """
    import re

    if pd.isna(s) or s == "":
        return default

    match = re.search(r"[-+]?\d*\.?\d+", str(s))
    if match:
        try:
            return float(match.group())
        except Exception:
            return default
    return default


def safe_get(row: pd.Series, key: str, default=None):
    """
    Safely get a value from a pandas Series.

    Args:
        row: pandas Series (typically a DataFrame row)
        key: Column name to retrieve
        default: Default value if key not found or value is null

    Returns:
        Value or default
    """
    val = row.get(key)
    if pd.isna(val):
        return default
    return val


def normalize_currency(currency: str) -> str:
    """
    Normalize currency code to uppercase 3-letter format.

    Args:
        currency: Currency string

    Returns:
        Normalized currency code
    """
    if pd.isna(currency) or currency == "":
        return ""
    return str(currency).strip().upper()[:3]


# Backward compatibility aliases
_parse_notional = parse_notional
_to_float = to_float
_pv01_bucket = pv01_bucket
