"""
Tenor calculation and labeling utilities for SDR analytics.

This module provides functions for converting year fractions to standard
tenor labels and detecting special dates like IMM rolls and FOMC meetings.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import QuantLib as ql

from SDRUtils.core.dates import to_ql_date, to_naive_timestamp


def get_imm_label(effective_date: pd.Timestamp, tolerance_days: int = 3) -> Optional[str]:
    """
    Get IMM label (e.g., 'IMM_Z2025') with tolerance for unadjusted dates.

    IMM dates are the 3rd Wednesday of March, June, September, December.

    Args:
        effective_date: The date to check
        tolerance_days: Max days difference to still be considered an IMM date

    Returns:
        IMM label string (e.g., 'IMM_H2025') or None if not an IMM date
    """
    ql_date = to_ql_date(effective_date)
    if ql_date is None:
        return None

    # Strict Check (Fastest)
    if ql.IMM.isIMMdate(ql_date):
        code = ql.IMM.code(ql_date)
        return f"IMM_{code[0]}{ql_date.year()}"

    # Fuzzy Check (Tolerance)
    m = ql_date.month()
    y = ql_date.year()

    # Only check standard IMM months
    if m not in [3, 6, 9, 12]:
        return None

    # Calculate the actual 3rd Wednesday for this Month/Year
    target_imm_date = ql.Date.nthWeekday(3, ql.Wednesday, m, y)

    # Check if within tolerance
    diff = abs(ql_date - target_imm_date)
    if diff <= tolerance_days:
        code = ql.IMM.code(target_imm_date)
        return f"IMM_{code[0]}{target_imm_date.year()}"

    return None


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
    # Check IMM (with tolerance for expiration matching)
    imm_label = get_imm_label(date_ts, tolerance_days=7)
    if imm_label:
        return imm_label

    # Check FOMC
    fomc_label = get_fomc_label(date_ts)
    if fomc_label:
        return fomc_label

    return None


def tenor_to_label(years: float, expiration_date: Optional[pd.Timestamp] = None) -> str:
    """
    Convert tenor in years to label like '1D', '2W', '3M', '10Y'.

    If expiration_date is provided and matches a special date (IMM/FOMC),
    returns that label instead of the standard tenor.

    Args:
        years: Tenor in year fractions
        expiration_date: Optional expiration date to check for special dates

    Returns:
        Tenor label string
    """
    # Priority: Check if Expiration is a special date (IMM/FOMC)
    if expiration_date is not None:
        special_label = get_special_label(expiration_date)
        if special_label:
            return special_label

    # Standard Tenor Mapping
    if years == 0:
        return "0D"
    if years < 0:
        return "unwind"

    days = years * 360.0
    tenor_days = {}

    # Build standard tenor map
    for d in range(1, 7):
        tenor_days[d] = f"{d}D"
    for weeks in range(1, 5):
        tenor_days[7 * weeks] = f"{weeks}W"
    for months in range(1, 12):
        tenor_days[30 * months] = f"{months}M"
    for months in (15, 18, 21):
        tenor_days[30 * months] = f"{months}M"
    for yrs in range(1, 31):
        tenor_days[360 * yrs] = f"{yrs}Y"
    for yrs in (35, 40, 50, 100):
        tenor_days[360 * yrs] = f"{yrs}Y"

    closest_days = min(tenor_days.keys(), key=lambda x: abs(x - days))

    tolerance_days = 2 if days < 30 else (5 if days <= 360 else 10)

    if abs(closest_days - days) <= tolerance_days:
        if tenor_days[closest_days] == "2D":
            return "spot"
        return tenor_days[closest_days]

    # Fallback for non-standard tenors
    if years < 1:
        if days < 28:
            return f"{int(round(days))}D"
        months = int(round(years * 12))
        return f"{months}M"
    else:
        return f"{int(round(years))}Y"


def forward_to_label(years: float, effective_date: Optional[pd.Timestamp] = None) -> str:
    """
    Convert forward start in years to label, prioritizing IMM/FOMC dates.

    Args:
        years: Forward start in year fractions
        effective_date: Optional effective date to check for special dates

    Returns:
        Forward label string (e.g., 'spot', '1Y', 'IMM_U2025')
    """
    # Always check for Special Dates (IMM/FOMC) first
    if effective_date is not None:
        # Check IMM first
        imm_label = get_imm_label(effective_date)
        if imm_label:
            return imm_label
        # Then FOMC
        fomc_label = get_fomc_label(effective_date)
        if fomc_label:
            return fomc_label

    # If no special label, apply standard spot/forward logic
    if years <= 0.009:  # Effectively Spot or Past
        return "spot"

    # return tenor_to_label(years)
    if years < 1:
        return tenor_to_label(years)

    total_months = int(round(years * 12))
    years_part, months_part = divmod(total_months, 12)

    if months_part == 0:
        return f"{years_part}Y"
    if years_part == 0:
        return f"{months_part}M"
    return f"{years_part}Y{months_part}M"


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
