"""Vectorized EOD rate computation engine.

Computes par swap rates from raw discount factor nodes using NumPy,
bypassing per-tenor QuantLib/rateslib curve reconstruction.
"""
from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenor parsing
# ---------------------------------------------------------------------------
_TENOR_RE = re.compile(
    r"^(?:(\d+[MY]))?(\d+[MY])$",
    re.IGNORECASE,
)


def parse_tenor(tenor: str) -> Tuple[Optional[str], str]:
    """Parse a tenor string into (forward_period, swap_period).

    Examples:
        "5Y"    -> (None, "5Y")
        "2Y3Y"  -> ("2Y", "3Y")
        "18M5Y" -> ("18M", "5Y")
        "6M"    -> (None, "6M")
    """
    tenor = tenor.strip().upper()
    m = _TENOR_RE.match(tenor)
    if m is None:
        raise ValueError(f"Cannot parse tenor: {tenor!r}")
    fwd_part, swap_part = m.group(1), m.group(2)
    return (fwd_part, swap_part)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------
def _period_to_ql(period_str: str) -> ql.Period:
    """Convert e.g. '18M' or '5Y' to a QuantLib Period."""
    period_str = period_str.strip().upper()
    num = int(period_str[:-1])
    unit_char = period_str[-1]
    if unit_char == "M":
        return ql.Period(num, ql.Months)
    elif unit_char == "Y":
        return ql.Period(num, ql.Years)
    raise ValueError(f"Unknown period unit: {unit_char!r}")


def _ql_date(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _py_date(d: ql.Date) -> datetime.date:
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


# ---------------------------------------------------------------------------
# Payment schedule
# ---------------------------------------------------------------------------
_US_CALENDAR = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
_BDC = ql.ModifiedFollowing
_EOM = False  # no end-of-month convention for SOFR swaps


@dataclass(frozen=True)
class PaymentSchedule:
    """Pre-computed payment schedule for a fixed leg."""
    effective_date: datetime.date
    maturity_date: datetime.date
    payment_dates: List[datetime.date]
    accrual_fractions: List[float]  # ACT/360 day count fractions


def build_payment_schedule(
    trading_date: datetime.date,
    tenor: str,
    *,
    settlement_days: int = 2,
    calendar: ql.Calendar = _US_CALENDAR,
    frequency: int = ql.Annual,
    day_counter: ql.DayCounter = ql.Actual360(),
    business_day_convention: int = _BDC,
) -> PaymentSchedule:
    """Build the fixed-leg payment schedule for a given tenor on a trading date."""
    fwd_period, swap_period = parse_tenor(tenor)

    ql_trade_date = _ql_date(trading_date)
    ql_spot = calendar.advance(ql_trade_date, settlement_days, ql.Days)

    if fwd_period is not None:
        ql_effective = calendar.advance(ql_spot, _period_to_ql(fwd_period), business_day_convention, _EOM)
    else:
        ql_effective = ql_spot

    ql_maturity = calendar.advance(ql_effective, _period_to_ql(swap_period), business_day_convention, _EOM)

    schedule = ql.Schedule(
        ql_effective,
        ql_maturity,
        ql.Period(frequency),
        calendar,
        business_day_convention,
        business_day_convention,
        ql.DateGeneration.Forward,
        _EOM,
    )

    dates = list(schedule)
    payment_dates: List[datetime.date] = []
    accrual_fractions: List[float] = []
    for i in range(1, len(dates)):
        payment_dates.append(_py_date(dates[i]))
        accrual_fractions.append(day_counter.yearFraction(dates[i - 1], dates[i]))

    return PaymentSchedule(
        effective_date=_py_date(ql_effective),
        maturity_date=_py_date(ql_maturity),
        payment_dates=payment_dates,
        accrual_fractions=accrual_fractions,
    )
