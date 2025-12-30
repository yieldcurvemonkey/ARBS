"""
Core utilities for SDRUtils.

Contains date handling, financial calculations, and helper functions
used across the package.
"""

from typing import Optional, Union

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql


# Timezone constants
NY_tz = pytz.timezone("America/New_York")
UTC_tz = pytz.timezone("UTC")

# USD OIS calendar and conventions
USD_OIS_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
USD_OIS_DC = ql.Actual360()
USD_OIS_BDC = ql.ModifiedFollowing


def ensure_int64_epoch_seconds(ts: pd.Series) -> np.ndarray:
    """
    Convert timestamp series to int64 epoch seconds.

    Robust for both tz-aware and naive timestamps.
    """
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    return (t.view("int64") // 1_000_000_000).astype(np.int64)


def pv01_bucket(pv01: np.ndarray, tol: float) -> np.ndarray:
    """
    Bucket PV01 values by log scale for tolerance-based matching.

    Uses log scale so "within % tolerance" becomes "nearby buckets".
    """
    pv01_pos = np.maximum(pv01, 1e-12)
    return np.floor(np.log(pv01_pos) / np.log(1.0 + tol)).astype(np.int32)


def parse_notional(notional_str: Union[str, float, int]) -> float:
    """Parse notional string like '31,000,000' to float."""
    if pd.isna(notional_str) or notional_str == "":
        return 0.0
    if isinstance(notional_str, (int, float)):
        return float(notional_str)
    try:
        return float(str(notional_str).replace(",", "").strip())
    except Exception:
        return 0.0


def to_float(x) -> float:
    """Convert value to float, handling various input types."""
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def to_naive_timestamp(x) -> pd.Timestamp:
    """Convert to naive timestamp (drop timezone info)."""
    ts = pd.to_datetime(x, errors="coerce")
    if pd.isna(ts):
        return ts
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts


def ts_to_ql_date(ts: pd.Timestamp) -> ql.Date:
    """Convert pandas Timestamp to QuantLib Date."""
    return ql.Date(int(ts.day), int(ts.month), int(ts.year))


def to_ql_date(value) -> Optional[ql.Date]:
    """Convert various date types to QuantLib Date."""
    if isinstance(value, ql.Date):
        return value
    ts = to_naive_timestamp(value)
    if pd.isna(ts):
        return None
    return ts_to_ql_date(ts)


def adjust_ql_date(ql_date: ql.Date, calendar: ql.Calendar, bdc: int) -> ql.Date:
    """Adjust QuantLib date to business day if needed."""
    if not calendar.isBusinessDay(ql_date):
        return calendar.adjust(ql_date, bdc)
    return ql_date


def calculate_tenor_years(
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = USD_OIS_DC,
    calendar: ql.Calendar = USD_OIS_CAL,
    bdc: int = USD_OIS_BDC,
    adjust_to_business_day: bool = True,
) -> float:
    """
    Calculate trading-standard year fraction for tenor between effective and expiration.

    Defaults: ACT/360 with USD GovBond calendar and Modified Following adjustment.
    """
    ql_eff = to_ql_date(effective_date)
    ql_exp = to_ql_date(expiration_date)
    if ql_eff is None or ql_exp is None:
        return 0.0

    if adjust_to_business_day:
        ql_eff = adjust_ql_date(ql_eff, calendar, bdc)
        ql_exp = adjust_ql_date(ql_exp, calendar, bdc)

    if ql_exp <= ql_eff:
        return 0.0

    return float(day_counter.yearFraction(ql_eff, ql_exp))


def calculate_forward_start_years(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = USD_OIS_DC,
    calendar: ql.Calendar = USD_OIS_CAL,
    bdc: int = USD_OIS_BDC,
    adjust_to_business_day: bool = False,
    use_execution_date_only: bool = True,
) -> float:
    """
    Calculate forward start year fraction.

    Returns NEGATIVE values if effective_date < execution_date.
    """
    exec_ts = to_naive_timestamp(execution_timestamp)
    if pd.isna(exec_ts):
        return 0.0

    if use_execution_date_only:
        exec_ts = exec_ts.normalize()

    ql_exec = to_ql_date(exec_ts)
    ql_eff = to_ql_date(effective_date)
    if ql_exec is None or ql_eff is None:
        return 0.0

    if adjust_to_business_day:
        ql_exec = adjust_ql_date(ql_exec, calendar, bdc)
        ql_eff = adjust_ql_date(ql_eff, calendar, bdc)

    if ql_eff == ql_exec:
        return 0.0

    val = day_counter.yearFraction(min(ql_exec, ql_eff), max(ql_exec, ql_eff))
    return val if ql_eff > ql_exec else -val


def get_imm_label(effective_date: pd.Timestamp, tolerance_days: int = 7) -> Optional[str]:
    """
    Get IMM label (e.g., 'IMM_Z2025') with tolerance for unadjusted dates.
    """
    ql_date = to_ql_date(effective_date)
    if ql_date is None:
        return None

    # Strict Check
    if ql.IMM.isIMMdate(ql_date):
        code = ql.IMM.code(ql_date)
        return f"IMM_{code[0]}{ql_date.year()}"

    # Fuzzy Check - IMM dates are 3rd Wednesday of Mar/Jun/Sep/Dec
    m = ql_date.month()
    y = ql_date.year()

    if m not in [3, 6, 9, 12]:
        return None

    target_imm_date = ql.Date.nthWeekday(3, ql.Wednesday, m, y)
    diff = abs(ql_date - target_imm_date)

    if diff <= tolerance_days:
        code = ql.IMM.code(target_imm_date)
        return f"IMM_{code[0]}{target_imm_date.year()}"

    return None


def get_fomc_label(effective_date: pd.Timestamp) -> Optional[str]:
    """Get FOMC label if date matches an FOMC meeting date."""
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
    """Check if a date corresponds to a special label (IMM or FOMC)."""
    imm_label = get_imm_label(date_ts, tolerance_days=7)
    if imm_label:
        return imm_label

    fomc_label = get_fomc_label(date_ts)
    if fomc_label:
        return fomc_label

    return None


def special_forward_label(effective_date: pd.Timestamp) -> Optional[str]:
    """Get special forward label (IMM or FOMC) if applicable."""
    imm_label = get_imm_label(effective_date)
    if imm_label:
        return imm_label
    return get_fomc_label(effective_date)


def tenor_to_label(years: float, expiration_date: Optional[pd.Timestamp] = None) -> str:
    """
    Convert tenor in years to label like '1D', '2W', '3M', '10Y'.

    If expiration_date is provided and matches a special date (IMM/FOMC),
    returns that label.
    """
    # Check if expiration is a special date
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

    if years < 1:
        if days < 28:
            return f"{int(round(days))}D"
        months = int(round(years * 12))
        return f"{months}M"
    else:
        return f"{int(round(years))}Y"


def forward_to_label(years: float, effective_date: Optional[pd.Timestamp] = None) -> str:
    """
    Convert forward start in years to label, prioritizing IMM/FOMC even if past.
    """
    # Always check for Special Dates (IMM/FOMC) first
    if effective_date is not None:
        special_lbl = special_forward_label(effective_date)
        if special_lbl:
            return special_lbl

    # Standard spot/forward logic
    if years <= 0.009:  # Effectively Spot or Past
        return "spot"

    return tenor_to_label(years)


# Legacy aliases for backward compatibility
_ensure_int64_epoch_seconds = ensure_int64_epoch_seconds
_pv01_bucket = pv01_bucket
_parse_notional = parse_notional
_to_float = to_float
_to_naive_timestamp = to_naive_timestamp
_ts_to_ql_date = ts_to_ql_date
_to_ql_date = to_ql_date
_adjust_ql_date = adjust_ql_date
_get_imm_label = get_imm_label
_get_fomc_label = get_fomc_label
_get_special_label = get_special_label
_special_forward_label = special_forward_label
_USD_OIS_CAL = USD_OIS_CAL
_USD_OIS_DC = USD_OIS_DC
_USD_OIS_BDC = USD_OIS_BDC
