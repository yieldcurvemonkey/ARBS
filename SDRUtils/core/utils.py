import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union
from tqdm import tqdm
from collections import defaultdict, deque

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz


NY_tz = pytz.timezone("America/New_York")
UTC_tz = pytz.timezone("UTC")


def _ensure_int64_epoch_seconds(ts: pd.Series) -> np.ndarray:
    # robust for tz-aware / naive
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    # int64 ns -> seconds
    return (t.view("int64") // 1_000_000_000).astype(np.int64)


def _pv01_bucket(pv01: np.ndarray, tol: float) -> np.ndarray:
    # bucket by log scale so "within % tolerance" becomes "nearby buckets"
    # Use log to make constant relative width buckets.
    pv01_pos = np.maximum(pv01, 1e-12)
    return np.floor(np.log(pv01_pos) / np.log(1.0 + tol)).astype(np.int32)


def _parse_notional(notional_str: Union[str, float, int]) -> float:
    """Parse notional string like '31,000,000' to float"""
    if pd.isna(notional_str) or notional_str == "":
        return 0.0
    if isinstance(notional_str, (int, float)):
        return float(notional_str)
    # Remove commas and convert
    try:
        return float(str(notional_str).replace(",", "").strip())
    except:
        return 0.0


def _to_float(x) -> float:
    if pd.isna(x) or x == "":
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return np.nan


def _to_naive_timestamp(x) -> pd.Timestamp:
    ts = pd.to_datetime(x, errors="coerce")
    if pd.isna(ts):
        return ts
    # drop tz to avoid ql.Date confusion
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts


def _ts_to_ql_date(ts: pd.Timestamp) -> ql.Date:
    return ql.Date(int(ts.day), int(ts.month), int(ts.year))


def _to_ql_date(value) -> Optional[ql.Date]:
    if isinstance(value, ql.Date):
        return value
    ts = _to_naive_timestamp(value)
    if pd.isna(ts):
        return None
    return _ts_to_ql_date(ts)


def _adjust_ql_date(ql_date: ql.Date, calendar: ql.Calendar, bdc: int) -> ql.Date:
    if not calendar.isBusinessDay(ql_date):
        return calendar.adjust(ql_date, bdc)
    return ql_date


_USD_OIS_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
_USD_OIS_DC = ql.Actual360()
_USD_OIS_BDC = ql.ModifiedFollowing


def calculate_tenor_years(
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = _USD_OIS_DC,
    calendar: ql.Calendar = _USD_OIS_CAL,
    bdc: int = _USD_OIS_BDC,
    adjust_to_business_day: bool = True,
) -> float:
    """
    Trading-standard year fraction for tenor between effective and expiration.

    Defaults: ACT/360 with USD GovBond calendar and Modified Following adjustment.
    """
    ql_eff = _to_ql_date(effective_date)
    ql_exp = _to_ql_date(expiration_date)
    if ql_eff is None or ql_exp is None:
        return 0.0

    if adjust_to_business_day:
        ql_eff = _adjust_ql_date(ql_eff, calendar, bdc)
        ql_exp = _adjust_ql_date(ql_exp, calendar, bdc)

    if ql_exp <= ql_eff:
        return 0.0

    return float(day_counter.yearFraction(ql_eff, ql_exp))


def calculate_forward_start_years(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = _USD_OIS_DC,
    calendar: ql.Calendar = _USD_OIS_CAL,
    bdc: int = _USD_OIS_BDC,
    adjust_to_business_day: bool = False,
    use_execution_date_only: bool = True,
) -> float:
    """
    Forward start year fraction.
    Returns NEGATIVE values if effective_date < execution_date.
    """
    exec_ts = _to_naive_timestamp(execution_timestamp)
    if pd.isna(exec_ts):
        return 0.0

    if use_execution_date_only:
        exec_ts = exec_ts.normalize()

    ql_exec = _to_ql_date(exec_ts)
    ql_eff = _to_ql_date(effective_date)
    if ql_exec is None or ql_eff is None:
        return 0.0

    if adjust_to_business_day:
        ql_exec = _adjust_ql_date(ql_exec, calendar, bdc)
        ql_eff = _adjust_ql_date(ql_eff, calendar, bdc)

    # Use yearFraction directly; QL handles negative dates if start > end,
    # but strictly speaking yearFraction(d1, d2) is usually positive.
    # We manually enforce sign.
    if ql_eff == ql_exec:
        return 0.0

    val = day_counter.yearFraction(min(ql_exec, ql_eff), max(ql_exec, ql_eff))
    return val if ql_eff > ql_exec else -val


def _get_special_label(date_ts: pd.Timestamp) -> Optional[str]:
    """Check if a date corresponds to a special label (IMM or FOMC)."""
    # 1. Check IMM (with tolerance for expiration matching)
    imm_label = _get_imm_label(date_ts, tolerance_days=7)
    if imm_label:
        return imm_label

    # 2. Check FOMC (Strict check usually preferred for central bank dates)
    fomc_label = _get_fomc_label(date_ts)
    if fomc_label:
        return fomc_label

    return None


def tenor_to_label(years: float, expiration_date: Optional[pd.Timestamp] = None) -> str:
    """
    Convert tenor in years to label like '1D', '2W', '3M', '10Y'.
    If expiration_date is provided and matches a special date (IMM/FOMC), returns that label.
    """
    # 1. Priority: Check if Expiration is a special date (IMM/FOMC)
    if expiration_date is not None:
        special_label = _get_special_label(expiration_date)
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


def _get_imm_label(effective_date: pd.Timestamp, tolerance_days: int = 7) -> Optional[str]:
    """
    Get IMM label (e.g., 'IMM_Z2025') with tolerance for unadjusted dates.

    Args:
        effective_date: The date to check
        tolerance_days: Max days difference to still be considered an IMM date
                        (handles cases where tenor is simply +2Y from start, missing the exact IMM roll)
    """
    ql_date = _to_ql_date(effective_date)
    if ql_date is None:
        return None

    # 1. Strict Check (Fastest)
    if ql.IMM.isIMMdate(ql_date):
        code = ql.IMM.code(ql_date)
        return f"IMM_{code[0]}{ql_date.year()}"

    # 2. Fuzzy Check (Tolerance)
    # IMM dates are generally the 3rd Wednesday of Mar(3), Jun(6), Sep(9), Dec(12).
    m = ql_date.month()
    y = ql_date.year()

    # If strictly standard IMM months only:
    if m not in [3, 6, 9, 12]:
        return None

    # Calculate the actual 3rd Wednesday for this Month/Year
    target_imm_date = ql.Date.nthWeekday(3, ql.Wednesday, m, y)

    # Calculate difference in days
    diff = abs(ql_date - target_imm_date)

    if diff <= tolerance_days:
        # Use the code from the *target* IMM date, not the off-target input date
        code = ql.IMM.code(target_imm_date)
        return f"IMM_{code[0]}{target_imm_date.year()}"

    return None


def _get_fomc_label(effective_date: pd.Timestamp) -> Optional[str]:
    ts = _to_naive_timestamp(effective_date)
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


def _special_forward_label(effective_date: pd.Timestamp) -> Optional[str]:
    imm_label = _get_imm_label(effective_date)
    if imm_label:
        return imm_label
    return _get_fomc_label(effective_date)


def forward_to_label(years: float, effective_date: Optional[pd.Timestamp] = None) -> str:
    """Convert forward start in years to label, prioritizing IMM/FOMC even if past."""

    # 1. Always check for Special Dates (IMM/FOMC) first
    #    This ensures "IMM_U2025" is returned even if 'years' is negative (past).
    if effective_date is not None:
        special_label = _special_forward_label(effective_date)
        if special_label:
            return special_label

    # 2. If no special label, apply standard spot/forward logic
    if years <= 0.009:  # Effectively Spot or Past (excluding special dates caught above)
        return "spot"

    return tenor_to_label(years)


def calculate_forward_start_years(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    day_counter: ql.DayCounter = _USD_OIS_DC,
    calendar: ql.Calendar = _USD_OIS_CAL,
    bdc: int = _USD_OIS_BDC,
    adjust_to_business_day: bool = False,
    use_execution_date_only: bool = True,
) -> float:
    """
    Forward start year fraction.
    Returns NEGATIVE values if effective_date < execution_date.
    """
    exec_ts = _to_naive_timestamp(execution_timestamp)
    if pd.isna(exec_ts):
        return 0.0

    if use_execution_date_only:
        exec_ts = exec_ts.normalize()

    ql_exec = _to_ql_date(exec_ts)
    ql_eff = _to_ql_date(effective_date)
    if ql_exec is None or ql_eff is None:
        return 0.0

    if adjust_to_business_day:
        ql_exec = _adjust_ql_date(ql_exec, calendar, bdc)
        ql_eff = _adjust_ql_date(ql_eff, calendar, bdc)

    # Use yearFraction directly; QL handles negative dates if start > end,
    # but strictly speaking yearFraction(d1, d2) is usually positive.
    # We manually enforce sign.
    if ql_eff == ql_exec:
        return 0.0

    val = day_counter.yearFraction(min(ql_exec, ql_eff), max(ql_exec, ql_eff))
    return val if ql_eff > ql_exec else -val


def forward_to_label(years: float, effective_date: Optional[pd.Timestamp] = None) -> str:
    """Convert forward start in years to label, prioritizing IMM/FOMC even if past."""

    # 1. Always check for Special Dates (IMM/FOMC) first
    #    This ensures "IMM_U2025" is returned even if 'years' is negative (past).
    if effective_date is not None:
        special_label = _special_forward_label(effective_date)
        if special_label:
            return special_label

    # 2. If no special label, apply standard spot/forward logic
    if years <= 0.009:  # Effectively Spot or Past (excluding special dates caught above)
        return "spot"

    return tenor_to_label(years)
