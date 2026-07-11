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


def _standard_tenor_label(
    years: float,
    *,
    is_swaptions: bool = False,
    days_fallback: bool = False,
) -> tuple[str, bool]:
    """Return the standard tenor label and whether it matched a benchmark cleanly.

    Args:
        years: Tenor in year fractions.
        is_swaptions: Apply swaption-specific shortcuts.
        days_fallback: When True, inputs that do not match a standard benchmark
            fall back to raw days (e.g. ``"73D"``) rather than a rounded months
            bucket. Used for forward-start labels so we never emit a misleading
            "2M" for what is really a 73-day forward.
    """
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

    # No benchmark match — choose a fallback representation.
    if days_fallback:
        return f"{int(round(days))}D", False

    if years < 1:
        if days < 28:
            return f"{int(round(days))}D", False
        months = int(round(years * 12))
        return f"{months}M", False

    # 1-2Y off-benchmark tenors keep month resolution: a 14.2-month swap
    # reads "~14M", not a misleading "~1Y".
    if years < 2:
        months = int(round(years * 12))
        if months % 12 != 0:
            return f"~{months}M", False

    return f"{int(round(years))}Y", False


def _standard_forward_label(years: float, *, is_swaptions: bool = False) -> tuple[str, bool]:
    """Return the standard forward label and whether it matched a benchmark cleanly."""
    # T+2 settlement can span up to 6 calendar days (Friday + holiday Monday)
    # 6/360 ≈ 0.017; use 0.02 as safe threshold
    if years <= 0.02 and not is_swaptions:
        return "spot", True

    if years < 1:
        # Swap forward starts < 1Y: when the period does not land on a standard
        # bucket (1W/2W/1M/2M/3M/6M/9M), return raw days rather than rounding to
        # months. Previously a 73-day forward rendered as "2M" which materially
        # misrepresents the trade (see bug report: "thats not really a 2m forward
        # swap"). Swaption labels keep the month-bucket behavior by design — the
        # nc-period for bermudans is typically expressed in months (e.g. "6Mnc4Y").
        return _standard_tenor_label(
            years,
            is_swaptions=is_swaptions,
            days_fallback=not is_swaptions,
        )

    total_months_float = years * 12.0
    total_months = int(round(total_months_float))
    tolerance_months = 10.0 / 30.0
    return _format_months_label(total_months), abs(total_months_float - total_months) <= tolerance_months


def get_imm_label(effective_date: pd.Timestamp, tolerance_days: int = 1) -> Optional[str]:
    """
    Get IMM label for a date on or within ±N business days of an IMM date.

    IMM dates are the 3rd Wednesday of March, June, September, December.
    A tolerance of 1 business day handles T+1 settlement adjustments and
    business-day convention differences (e.g. effective 6/16 when the IMM
    date is 6/17).

    Args:
        effective_date: The date to check
        tolerance_days: Max business days away from an IMM date to still
            match. Uses the US government bond calendar. Default 1.

    Returns:
        IMM label string (e.g., 'IMM_H2025') or None if not near an IMM date
    """
    ql_date = to_ql_date(effective_date)
    if ql_date is None:
        return None

    if ql.IMM.isIMMdate(ql_date):
        code = ql.IMM.code(ql_date)
        return f"IMM_{code[0]}{ql_date.year()}"

    if tolerance_days > 0:
        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        for offset in range(1, tolerance_days + 1):
            for sign in (1, -1):
                neighbor = cal.advance(ql_date, sign * offset, ql.Days)
                if ql.IMM.isIMMdate(neighbor):
                    code = ql.IMM.code(neighbor)
                    return f"IMM_{code[0]}{neighbor.year()}"

    # Holiday-rolled IMM dates: when the mathematical 3rd Wednesday is a
    # holiday (June 19 = Juneteenth in some years), traded effective dates
    # roll to the next business day. The business-day neighbor search above
    # steps OVER the holiday, so probe the month's 3rd Wednesday directly
    # and compare its Following-adjusted date to the input.
    third_wed = ql.Date.nthWeekday(3, ql.Wednesday, ql_date.month(), ql_date.year())
    if ql.IMM.isIMMdate(third_wed):
        cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
        if cal.adjust(third_wed, ql.Following) == ql_date:
            code = ql.IMM.code(third_wed)
            return f"IMM_{code[0]}{third_wed.year()}"

    return None


def get_fomc_label(effective_date: pd.Timestamp, tolerance_days: int = 1) -> Optional[str]:
    """
    Get FOMC meeting label for a date on or within ±N business days of a meeting.

    A tolerance of 1 business day handles the meeting-day vs decision-day and
    T+1 settlement conventions (e.g. a swap effective 9/15 when the meeting
    decision date is 9/16). Mirrors ``get_imm_label``. The returned label always
    identifies the MEETING date, not the (possibly offset) input date. Pass
    ``tolerance_days=0`` for exact matching.

    Args:
        effective_date: The date to check
        tolerance_days: Max business days away from a meeting date to still
            match. Uses the US government bond calendar. Default 1.

    Returns:
        FOMC label string (e.g., 'FOMC_20250115') or None if not near a meeting
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

    if tolerance_days > 0:
        ql_date = to_ql_date(ts)
        if ql_date is not None:
            cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
            for offset in range(1, tolerance_days + 1):
                for sign in (1, -1):
                    neighbor = cal.advance(ql_date, sign * offset, ql.Days)
                    nd = pd.Timestamp(
                        neighbor.year(), neighbor.month(), neighbor.dayOfMonth()
                    ).date()
                    if nd in fomc_dates:
                        return f"FOMC_{nd.strftime('%Y%m%d')}"
    return None


_FOMC_MEETING_DATES_CACHE: Optional[list] = None


def _fomc_meeting_dates_sorted() -> list:
    """Sorted list of FOMC meeting dates from the central-bank calendar."""
    global _FOMC_MEETING_DATES_CACHE
    if _FOMC_MEETING_DATES_CACHE is None:
        try:
            from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

            _FOMC_MEETING_DATES_CACHE = sorted(
                {m[0] for m in _CENTRAL_BANK_DATES["USD-FEDFUNDS"].values()}
            )
        except Exception:
            _FOMC_MEETING_DATES_CACHE = []
    return _FOMC_MEETING_DATES_CACHE


def is_consecutive_fomc_pair(
    effective_date: Optional[pd.Timestamp],
    expiration_date: Optional[pd.Timestamp],
) -> bool:
    """True iff effective and expiration land on CONSECUTIVE FOMC meetings.

    This is the defining property of an FOMC-dated swap: the accrual period
    spans exactly one meeting-to-meeting window. Both endpoints tolerate the
    ±1-business-day noise handled by :func:`get_fomc_label`.
    """
    if effective_date is None or expiration_date is None:
        return False
    eff_lbl = get_fomc_label(effective_date)
    mat_lbl = get_fomc_label(expiration_date)
    if not eff_lbl or not mat_lbl:
        return False
    dates = _fomc_meeting_dates_sorted()
    if not dates:
        return False
    try:
        eff_d = pd.Timestamp(eff_lbl[5:]).date()
        mat_d = pd.Timestamp(mat_lbl[5:]).date()
        return dates.index(mat_d) == dates.index(eff_d) + 1
    except (ValueError, TypeError):
        return False


def get_special_label(date_ts: pd.Timestamp) -> Optional[str]:
    """
    Check if a date corresponds to a special label (FOMC or IMM).

    FOMC is checked first so that FOMC meeting dates that fall within
    the IMM tolerance window are labeled as FOMC, not IMM.

    Args:
        date_ts: The date to check

    Returns:
        Special label string or None
    """
    fomc_label = get_fomc_label(date_ts)
    if fomc_label:
        return fomc_label

    imm_label = get_imm_label(date_ts)
    if imm_label:
        return imm_label

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
    days_tolerance: int = 3,
) -> str:
    """
    Build tenor label using calendar components between two dates.

    Args:
        effective_date: Start date of the swap
        expiration_date: End date of the swap
        is_swaptions: Whether to apply swaption-specific rules
        days_tolerance: Maximum ``days_part`` value that is still treated as a
            clean year/month combination. Captures the 1-3 day noise introduced
            by business-day adjustments so a 3Y6M+2d swap renders as ``"3Y6M"``
            rather than falling through to the bucketed ``"~4Y"``.

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
        # Whole weeks read as weeks: a 7-day swap is "1W", not "7D".
        if 7 <= days_part <= 28 and days_part % 7 == 0:
            return f"{days_part // 7}W"
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

    # Small residual days_part (business-day adjustment) — treat as the clean
    # Y/M combination. Avoids off-date buckets for trades that are genuinely
    # clean like 5Y6M with a weekend/holiday roll.
    if abs(days_part) <= days_tolerance:
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

    IMM/FOMC labels take priority over relative labels (e.g. "3W") so
    that a 3-week forward landing on an IMM date renders as "IMM_M2026"
    rather than the ambiguous "3W".  Spot (T+2 settlement) is never
    overridden.

    Args:
        years: Forward start in year fractions
        effective_date: Optional effective date to check for special dates

    Returns:
        Forward label string (e.g., 'spot', '1Y', 'IMM_U2025')
    """
    standard_label, matched_benchmark = _standard_forward_label(years, is_swaptions=is_swaptions)
    if standard_label == "spot":
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


def detect_special_tenor(
    tenor_label: str,
    forward_label: str,
    effective_date: Optional[pd.Timestamp],
    expiration_date: Optional[pd.Timestamp],
    is_forward: bool,
) -> tuple[str, str, list[str]]:
    """Classify special tenor with strict tier priority.

    Priority (highest first):
      1. ``effective_date`` and ``expiration_date`` land on CONSECUTIVE
         FOMC meeting dates  => FOMC (tags=["FOMC"]). An FOMC-dated swap
         is *defined* by spanning exactly one meeting-to-meeting window —
         non-consecutive meeting endpoints do NOT qualify.
      2. ``effective_date`` is a quarterly IMM date (H/M/U/Z) and the
         maturity side is a constant-maturity tenor (no IMM_/FOMC_
         prefix on ``tenor_label``)  => IMM (tags=["IMM"]).
      else => STANDARD (with legacy label/maturity-date fallbacks below).

    This supersedes the legacy FOMC > IMM tag-priority rule. IMM and FOMC
    dates coincide on quarterly meetings; the old rule flipped quarterly
    IMM trades to FOMC erroneously, and the old tier 3 tagged any swap
    merely *starting* on a meeting date as FOMC.

    Returns:
        ``(special_tenor_type, special_tenor_confidence, special_tenor_tags)``
    """
    eff_is_fomc = effective_date is not None and get_fomc_label(effective_date) is not None
    mat_is_fomc = expiration_date is not None and get_fomc_label(expiration_date) is not None
    eff_is_imm_q = effective_date is not None and get_imm_label(effective_date) is not None
    mat_is_imm = expiration_date is not None and get_imm_label(expiration_date) is not None

    tenor_is_constant = not (
        tenor_label.startswith("IMM_") or tenor_label.startswith("FOMC_")
    )

    # Tier 1 — consecutive FOMC meeting endpoints only.
    if eff_is_fomc and mat_is_fomc and is_consecutive_fomc_pair(
        effective_date, expiration_date
    ):
        return "FOMC", "high", ["FOMC"]

    # Tier 2 — quarterly IMM eff + constant-tenor mat. Runs before any FOMC
    # fallback so an IMM-effective swap whose maturity happens to sit near a
    # meeting date labels as IMM ("IMM_U2026 6M"), not FOMC.
    if eff_is_imm_q and tenor_is_constant:
        return "IMM", "high", ["IMM"]

    # Label-based fallback (matches legacy behaviour for edge cases where
    # tenor_to_label already baked in IMM_/FOMC_ but dates don't resolve).
    if tenor_label.startswith("IMM_") or forward_label.startswith("IMM_"):
        tags = ["IMM"]
        if tenor_label.startswith("FOMC_") or forward_label.startswith("FOMC_"):
            tags.append("FOMC")
        if mat_is_imm:
            pass  # already IMM-tagged
        return "IMM", "medium", tags
    if tenor_label.startswith("FOMC_") or forward_label.startswith("FOMC_"):
        return "FOMC", "medium", ["FOMC"]

    # Date-only fallback: if only expiration is on the IMM calendar (non-forward
    # spot trade maturing on a special date), preserve legacy tagging so the tag
    # pipeline downstream can still reason about it. The equivalent FOMC-maturity
    # fallback was removed: a spot swap that merely MATURES near a meeting date
    # (e.g. a spot 11M) is not an FOMC-dated instrument.
    if mat_is_imm:
        return "IMM", "high", ["IMM"]

    return "STANDARD", "high", []


# Legacy alias — callers historically used this name. Signature adjusted to
# match the old keyword order so existing kwarg-call sites keep working.
def classify_intrinsic_special_tenor(
    effective_date: Optional[pd.Timestamp],
    expiration_date: Optional[pd.Timestamp],
    tenor_label: str,
    forward_label: str,
    is_forward: bool,
) -> tuple[str, str, list[str]]:
    """Legacy wrapper — see :func:`detect_special_tenor`."""
    return detect_special_tenor(
        tenor_label=tenor_label,
        forward_label=forward_label,
        effective_date=effective_date,
        expiration_date=expiration_date,
        is_forward=is_forward,
    )


# Backward compatibility aliases
_get_imm_label = get_imm_label
_get_fomc_label = get_fomc_label
_get_special_label = get_special_label
_special_forward_label = lambda ed: get_imm_label(ed) or get_fomc_label(ed)
