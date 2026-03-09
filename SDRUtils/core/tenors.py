"""
Tenor calculation and labeling utilities for SDR analytics.

This module provides functions for converting year fractions to standard
tenor labels and detecting special dates like IMM rolls and FOMC meetings.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import QuantLib as ql

from SDRUtils.core.dates import calculate_tenor_components, to_ql_date, to_naive_timestamp


_TENOR_DAYS: dict[int, str] = {}
for _d in range(1, 7):
    _TENOR_DAYS[_d] = f"{_d}D"
for _weeks in range(1, 5):
    _TENOR_DAYS[7 * _weeks] = f"{_weeks}W"
for _months in range(1, 12):
    _TENOR_DAYS[30 * _months] = f"{_months}M"
for _months in (15, 18, 21):
    _TENOR_DAYS[30 * _months] = f"{_months}M"
for _years in range(1, 31):
    _TENOR_DAYS[360 * _years] = f"{_years}Y"
for _years in (35, 40, 50, 100):
    _TENOR_DAYS[360 * _years] = f"{_years}Y"


def _format_months_label(total_months: int) -> str:
    years_part, months_part = divmod(total_months, 12)
    if months_part == 0:
        return f"{years_part}Y"
    if years_part == 0:
        return f"{months_part}M"
    return f"{years_part}Y{months_part}M"


def _standard_tenor_label(years: float, *, is_swaptions: bool = False) -> tuple[str, bool]:
    """Return the standard tenor label and whether it matched a benchmark cleanly."""
    if years == 0:
        return "0D", True
    if years < 0:
        return "unwind", True

    approx_days = years * 365.0
    if is_swaptions and 26.5 <= approx_days <= 31.5:
        return "1M", True

    days = years * 360.0
    closest_days = min(_TENOR_DAYS.keys(), key=lambda x: abs(x - days))
    tolerance_days = 2 if days < 30 else (5 if days <= 360 else 10)

    if abs(closest_days - days) <= tolerance_days:
        label = _TENOR_DAYS[closest_days]
        if label == "2D" and not is_swaptions:
            return "spot", True
        if label == "4W" and days >= 27:
            return "1M", True
        return label, True

    if years < 1:
        if days < 28:
            return f"{int(round(days))}D", False
        months = int(round(years * 12))
        return f"{months}M", False

    return f"{int(round(years))}Y", False


def _standard_forward_label(years: float, *, is_swaptions: bool = False) -> tuple[str, bool]:
    """Return the standard forward label and whether it matched a benchmark cleanly."""
    if years <= 0.009 and not is_swaptions:
        return "spot", True

    if years < 1:
        return _standard_tenor_label(years, is_swaptions=is_swaptions)

    total_months_float = years * 12.0
    total_months = int(round(total_months_float))
    tolerance_months = 10.0 / 30.0
    return _format_months_label(total_months), abs(total_months_float - total_months) <= tolerance_months


def get_imm_label(effective_date: pd.Timestamp, tolerance_days: int = 0) -> Optional[str]:
    """
    Get IMM label (e.g., 'IMM_Z2025') for an exact IMM date.

    IMM dates are the 3rd Wednesday of March, June, September, December.

    Args:
        effective_date: The date to check
        tolerance_days: Deprecated and ignored; IMM matching is exact only.

    Returns:
        IMM label string (e.g., 'IMM_H2025') or None if not an IMM date
    """
    ql_date = to_ql_date(effective_date)
    if ql_date is None:
        return None

    if not ql.IMM.isIMMdate(ql_date):
        return None

    code = ql.IMM.code(ql_date)
    return f"IMM_{code[0]}{ql_date.year()}"


def get_fomc_label(effective_date: pd.Timestamp) -> Optional[str]:
    """
    Get FOMC meeting label if the date is a FOMC meeting date.

    Args:
        effective_date: The date to check

    Returns:
        FOMC label string (e.g., 'FOMC_20250115') or None if not a FOMC date
    """
    ts = to_naive_timestamp(effective_date)
    if pd.isna(ts):
        return None

    try:
        from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

        fomc_dates = {m[0] for m in _CENTRAL_BANK_DATES["USD-FEDFUNDS"].values()}
    except Exception:
        return None

    if ts.date() in fomc_dates:
        return f"FOMC_{ts.strftime('%Y%m%d')}"
    return None


def get_special_label(date_ts: pd.Timestamp) -> Optional[str]:
    """
    Check if a date corresponds to a special label (IMM or FOMC).

    IMM is checked first, then FOMC.

    Args:
        date_ts: The date to check

    Returns:
        Special label string or None
    """
    imm_label = get_imm_label(date_ts)
    if imm_label:
        return imm_label

    # Check FOMC
    fomc_label = get_fomc_label(date_ts)
    if fomc_label:
        return fomc_label

    return None


def tenor_to_label(years: float, expiration_date: Optional[pd.Timestamp] = None, is_swaptions=False) -> str:
    """
    Convert tenor in years to label like '1D', '2W', '3M', '10Y'.

    Standard constant-maturity labels take precedence. Exact special-date
    labels (IMM/FOMC) are only used as a fallback for non-benchmark tenors.

    Args:
        years: Tenor in year fractions
        expiration_date: Optional expiration date to check for special dates

    Returns:
        Tenor label string
    """
    standard_label, matched_benchmark = _standard_tenor_label(years, is_swaptions=is_swaptions)
    if matched_benchmark or standard_label == "spot":
        return standard_label

    if expiration_date is not None:
        special_label = get_special_label(expiration_date)
        if special_label:
            return special_label

    return standard_label


def tenor_from_dates(
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    *,
    is_swaptions: bool = False,
) -> str:
    """
    Build tenor label using calendar components between two dates.

    Args:
        effective_date: Start date of the swap
        expiration_date: End date of the swap
        is_swaptions: Whether to apply swaption-specific rules

    Returns:
        Tenor label string
    """
    years_part, months_part, days_part = calculate_tenor_components(
        effective_date,
        expiration_date,
    )

    if years_part == 0 and months_part == 0:
        if days_part == 2 and not is_swaptions:
            return "spot"
        return f"{days_part}D"

    if years_part == 0 and days_part == 0:
        return f"{months_part}M"

    if months_part == 0 and days_part == 0:
        return f"{years_part}Y"

    if days_part == 0:
        if years_part == 0:
            return f"{months_part}M"
        if months_part == 0:
            return f"{years_part}Y"
        return f"{years_part}Y{months_part}M"

    total_years = years_part + months_part / 12.0 + days_part / 360.0
    return tenor_to_label(total_years, expiration_date=expiration_date, is_swaptions=is_swaptions)


def forward_to_label(years: float, effective_date: Optional[pd.Timestamp] = None, is_swaptions=False) -> str:
    """
    Convert forward start in years to label.

    Standard constant-maturity labels take precedence. Exact special-date
    labels (IMM/FOMC) are only used as a fallback for non-benchmark forwards,
    and never override spot.

    Args:
        years: Forward start in year fractions
        effective_date: Optional effective date to check for special dates

    Returns:
        Forward label string (e.g., 'spot', '1Y', 'IMM_U2025')
    """
    standard_label, matched_benchmark = _standard_forward_label(years, is_swaptions=is_swaptions)
    if matched_benchmark or standard_label == "spot":
        return standard_label

    if effective_date is not None:
        special_label = get_special_label(effective_date)
        if special_label:
            return special_label

    return standard_label


def build_trade_label(
    forward_label: str,
    tenor_label: str,
    is_forward: bool,
) -> str:
    """
    Build composite trade label from forward and tenor labels.

    Examples:
        - "spot 10Y" for spot starting 10Y swap
        - "1Y 5Y" for 1Y forward starting 5Y swap
        - "IMM_H2025 2Y" for IMM forward starting 2Y swap

    Args:
        forward_label: Forward start label
        tenor_label: Tenor label
        is_forward: Whether the trade is forward starting

    Returns:
        Composite trade label
    """
    is_special_forward = forward_label.startswith("IMM_") or forward_label.startswith("FOMC_")

    if is_forward or is_special_forward:
        return f"{forward_label} {tenor_label}"
    else:
        return f"spot {tenor_label}"


# Backward compatibility aliases
_get_imm_label = get_imm_label
_get_fomc_label = get_fomc_label
_get_special_label = get_special_label
_special_forward_label = lambda ed: get_imm_label(ed) or get_fomc_label(ed)
