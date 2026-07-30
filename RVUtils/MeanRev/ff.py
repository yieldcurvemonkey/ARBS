"""30-day Fed Funds futures (ZQ): settlement, meeting exposure, ticks and costs.

Everything here follows CBOT rulebook Chapter 22 and nothing here is
approximated, because the whole reason to look at ZQ instead of SR3 is that its
calendar component is *exactly* computable.

**Settlement (§22102.B, §22103).** The contract settles at ``100 - R``, where
``R`` is the **arithmetic average of the daily FRBNY effective federal funds rate
over every calendar day of the delivery month**. For any day the FRBNY does not
publish a rate -- a weekend or a US bank holiday -- the rate for that day is
*the rate for the last preceding day for which a rate was published*. The
average is rounded to the nearest **tenth of a basis point**, with ties rounded
**up**. Each contract is $4,167 per index point, so one basis point is
**$41.67**.

Contrast with SR3, which settles on a *compounded* average over a quarterly IMM
window. Two consequences, both of which are why this module exists:

* **arithmetic, not compounded** -- a compounded window overstates the implied
  rate by roughly ``r^2 * n / 720``, about 0.66bp on a 31-day month at 4%. That
  is larger than a ZQ half-tick, so it is not a rounding detail;
* **one calendar month, not one quarter** -- a policy step enters as a clean
  day-count blend of exactly two regimes rather than a diluted overlap of
  several. A December-9 decision is 9/31 pre and 22/31 post in the December
  contract and *entirely* post in January until the late-January meeting clips
  the tail, so **the January contract is the clean read on the December
  meeting**.

**Price increments (§22102.C).** 0.005 index points ($20.835) normally, halving
to 0.0025 ($10.4175) near delivery on a rule with a precise onset that this
module encodes rather than approximates -- it decides which contract-days cost
0.25bp to cross and which cost 0.5bp.
"""
from __future__ import annotations

import calendar
import datetime
import functools
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "ZQ_DV01_USD", "ZQ_POINT_USD", "ZQ_TICK_BP", "ZQ_HALF_TICK_BP",
    "ZQ_SETTLE_ROUNDING_BP", "MONTH_CODES", "month_code", "code_to_month",
    "delivery_window", "effr_publication_days", "applicable_source_day",
    "day_regime_index", "zq_exposure_vector", "zq_exposure_matrix",
    "zq_regime_weights", "expected_settle_rate", "round_settle_rate",
    "half_tick_onset", "tick_bp", "round_trip_bp", "compounding_bias_bp",
]

#: dollars per basis point of the settlement rate, per contract (§22102.B)
ZQ_DV01_USD = 41.67

#: dollars per full index point, per contract (§22101)
ZQ_POINT_USD = 4167.0

#: the normal minimum price fluctuation, in bp of rate (0.005 index points)
ZQ_TICK_BP = 0.5

#: the near-delivery minimum price fluctuation, in bp of rate (0.0025 points)
ZQ_HALF_TICK_BP = 0.25

#: final settlement is rounded to the nearest tenth of a basis point, ties up
ZQ_SETTLE_ROUNDING_BP = 0.1

#: CME month codes, January first
MONTH_CODES = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"]
_CODE_TO_NUM = {c: i + 1 for i, c in enumerate(MONTH_CODES)}


def month_code(year: int, month: int) -> str:
    """``(2026, 12) -> 'Z26'``."""
    return f"{MONTH_CODES[int(month) - 1]}{int(year) % 100:02d}"


def code_to_month(code: str) -> Tuple[int, int]:
    """``'Z26' -> (2026, 12)``."""
    c = str(code).strip().upper()
    if c[:2] == "ZQ":
        c = c[2:]
    return 2000 + int(c[1:]), _CODE_TO_NUM[c[0]]


def delivery_window(code: str) -> Tuple[datetime.date, datetime.date, int]:
    """``(first day of the delivery month, first day of the NEXT month, n_days)``.

    Half-open on the right, so ``n_days`` is exactly the number of calendar days
    the settlement average runs over -- 28, 29, 30 or 31.
    """
    y, m = code_to_month(code)
    start = datetime.date(y, m, 1)
    n = calendar.monthrange(y, m)[1]
    return start, start + datetime.timedelta(days=n), n


# ---------------------------------------------------------------------------
# the publication calendar
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=8)
def _ql_calendar(name: str):
    import QuantLib as ql

    return {
        "federal_reserve": ql.UnitedStates(ql.UnitedStates.FederalReserve),
        "government_bond": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        "nyse": ql.UnitedStates(ql.UnitedStates.NYSE),
        "settlement": ql.UnitedStates(ql.UnitedStates.Settlement),
    }[name]


def _is_business(d: datetime.date, cal_name: str) -> bool:
    import QuantLib as ql

    return bool(_ql_calendar(cal_name).isBusinessDay(
        ql.Date(d.day, d.month, d.year)))


def effr_publication_days(start: datetime.date, end: datetime.date, *,
                          calendar_name: str = "federal_reserve") -> List[datetime.date]:
    """Days for which the FRBNY publishes an effective federal funds rate.

    EFFR exists for each day the Federal Reserve Banks are open, which is why
    the default is QuantLib's ``UnitedStates.FederalReserve`` and not NYSE: the
    Fed observes Columbus Day and Veterans Day and the stock exchange does not,
    and on those days there is no EFFR to publish, so the previous day's rate
    carries. Getting this wrong shifts a day of weight between regimes.
    """
    out, d = [], start
    while d < end:
        if _is_business(d, calendar_name):
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def applicable_source_day(days: Sequence[datetime.date], *,
                          calendar_name: str = "federal_reserve",
                          lookback_days: int = 14) -> List[datetime.date]:
    """For each calendar day, the publication day whose rate applies to it.

    This is §22103's carry rule made explicit: a non-publication day takes the
    rate of the last preceding publication day, so a Friday's rate is the one
    used for Friday, Saturday and Sunday and therefore carries **three days of
    weight** in the settlement average.
    """
    if not days:
        return []
    lo = min(days) - datetime.timedelta(days=int(lookback_days))
    pub = set(effr_publication_days(lo, max(days) + datetime.timedelta(days=1),
                                    calendar_name=calendar_name))
    out = []
    for d in days:
        s = d
        while s not in pub:
            s -= datetime.timedelta(days=1)
            if (d - s).days > int(lookback_days):
                raise ValueError(f"no publication day within {lookback_days}d of {d}")
        out.append(s)
    return out


def _effective_days(meetings: Sequence[datetime.date], *,
                    effective_lag_days: int = 1,
                    calendar_name: str = "federal_reserve") -> List[datetime.date]:
    """The first day whose PUBLISHED rate reflects each decision.

    A decision on day ``D`` takes effect on ``D + effective_lag_days``, but if
    that day does not publish there is no new rate until the next one that does
    -- until then §22103's carry rule keeps the *old* regime in force.

    **This is not hypothetical.** The 2025-06-18 decision takes effect on
    2025-06-19, which is **Juneteenth** -- a federal holiday since 2021, so the
    FRBNY publishes nothing and Thursday carries Wednesday's (pre-decision) rate.
    The new regime does not reach the settlement average until Friday the 20th,
    which moves one of June 2025's thirty days from post to pre: a 3.3% shift in
    the contract's exposure to that meeting, worth 0.8bp on a 25bp move. A naive
    calendar-day count gets it wrong, and it is exactly the kind of single day
    that is invisible until it is not.
    """
    out = []
    for m in meetings:
        d = m + datetime.timedelta(days=int(effective_lag_days))
        for _ in range(10):
            if _is_business(d, calendar_name):
                break
            d += datetime.timedelta(days=1)
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# meeting exposure
# ---------------------------------------------------------------------------

def day_regime_index(window: Tuple[datetime.date, datetime.date],
                     meetings: Sequence[datetime.date], *,
                     effective_lag_days: int = 1,
                     calendar_name: str = "federal_reserve") -> np.ndarray:
    """Per calendar day of the window, how many meetings are already in force.

    0 means the day sits at the pre-window rate, 1 after the first meeting
    inside the window, and so on. The classification is done on the day's
    **source publication day**, which is what makes the weekend carry rule bite.
    """
    start, end = window
    days = [start + datetime.timedelta(days=i) for i in range((end - start).days)]
    src = applicable_source_day(days, calendar_name=calendar_name)
    eff = _effective_days(meetings, effective_lag_days=effective_lag_days,
                          calendar_name=calendar_name)
    out = np.zeros(len(days), dtype=int)
    for e in eff:
        out += np.array([1 if s >= e else 0 for s in src], dtype=int)
    return out


def zq_exposure_vector(window: Tuple[datetime.date, datetime.date],
                       meetings: Sequence[datetime.date], *,
                       effective_lag_days: int = 1,
                       calendar_name: str = "federal_reserve") -> np.ndarray:
    """Share of the delivery month sitting at or after each meeting's new rate.

    ``w[m]`` is the fraction of the month's calendar days whose applicable
    published rate is dated on or after meeting ``m``'s effective day -- 1.0 for
    a meeting already in force before the month starts, 0.0 for one after it
    ends, and a day-count blend in between. Under the step model the contract's
    settlement rate is ``base + sum_m w[m] * jump_m``.
    """
    start, end = window
    days = [start + datetime.timedelta(days=i) for i in range((end - start).days)]
    n = len(days)
    src = applicable_source_day(days, calendar_name=calendar_name)
    eff = _effective_days(meetings, effective_lag_days=effective_lag_days,
                          calendar_name=calendar_name)
    return np.array([sum(1 for s in src if s >= e) / n for e in eff], dtype=float)


def zq_exposure_matrix(windows: Sequence[Tuple[datetime.date, datetime.date]],
                       meetings: Sequence[datetime.date], *,
                       effective_lag_days: int = 1,
                       calendar_name: str = "federal_reserve") -> np.ndarray:
    """``W[i, m]`` -- :func:`zq_exposure_vector` stacked over contracts."""
    if not windows:
        return np.zeros((0, len(meetings)))
    return np.vstack([
        zq_exposure_vector(w, meetings, effective_lag_days=effective_lag_days,
                           calendar_name=calendar_name) for w in windows])


def zq_regime_weights(window: Tuple[datetime.date, datetime.date],
                      meetings: Sequence[datetime.date], *,
                      effective_lag_days: int = 1,
                      calendar_name: str = "federal_reserve") -> np.ndarray:
    """Day-share of the month spent in each policy regime. **Sums to exactly 1.**

    Regime ``k`` is the state after ``k`` of the supplied meetings have taken
    effect, so with ``M`` meetings inside the window there are ``M + 1`` regimes.
    This is the partition-of-unity form of :func:`zq_exposure_vector` and exists
    because "the weights sum to one" is a property that can be asserted without
    reference to the implementation -- which is the only kind of check worth
    writing for arithmetic this fiddly.
    """
    idx = day_regime_index(window, meetings, effective_lag_days=effective_lag_days,
                           calendar_name=calendar_name)
    n_reg = int(len(meetings)) + 1
    counts = np.bincount(idx, minlength=n_reg).astype(float)
    return counts / float(idx.size)


def expected_settle_rate(window: Tuple[datetime.date, datetime.date],
                         meetings: Sequence[datetime.date],
                         regime_rates: Sequence[float], *,
                         effective_lag_days: int = 1,
                         calendar_name: str = "federal_reserve") -> float:
    """The month's arithmetic average rate under a pure policy-step path.

    ``regime_rates[k]`` is the overnight rate once ``k`` meetings have taken
    effect, so there must be ``len(meetings) + 1`` of them. This is the model the
    FF "kink" is defined as a residual from.
    """
    w = zq_regime_weights(window, meetings, effective_lag_days=effective_lag_days,
                          calendar_name=calendar_name)
    r = np.asarray(regime_rates, dtype=float)
    if r.size != w.size:
        raise ValueError(f"need {w.size} regime rates, got {r.size}")
    return float(np.dot(w, r))


def round_settle_rate(rate: float, *, unit_bp: float = ZQ_SETTLE_ROUNDING_BP) -> float:
    """Round a settlement rate in **percent** to the nearest 0.1bp, ties **up**.

    §22103's own example: 2.5915 rounds up to 2.592, giving a settlement price of
    97.408.

    Done in :mod:`decimal`, not in floats, and that is not fastidiousness. The
    obvious ``floor(x / step + 0.5) * step`` gets 2.5925 wrong -- in binary that
    value is 2592.4999999999995 steps, a hair *below* the tie, so it rounds
    **down** to 2.592 when the rule says 2.593. Python's own ``round`` is worse
    again: it breaks exact ties to even, which is a different rule entirely.
    Half a tenth of a basis point is $2.08 a contract and the whole point of ZQ
    here is that its settlement is exactly computable.
    """
    from decimal import Decimal, ROUND_HALF_UP

    step = Decimal(str(float(unit_bp) / 100.0))       # 0.1bp expressed in percent
    q = (Decimal(str(rate)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(q * step)


def compounding_bias_bp(rate_pct: float, n_days: int) -> float:
    """How far a COMPOUNDED window overstates the ARITHMETIC average, in bp.

    To second order the daily-compounded average rate over ``n`` days at ``r``
    exceeds the arithmetic mean by about ``r^2 * n / 720`` when ``r`` is in
    percent and the day count basis is 360. At 4% over 31 days that is 0.69bp --
    bigger than a ZQ half-tick, which is why a ZQ built with a SOFR (compounded)
    spec is the wrong contract rather than a close one.
    """
    return float(rate_pct) ** 2 * float(n_days) / 720.0


# ---------------------------------------------------------------------------
# ticks and costs (§22102.C)
# ---------------------------------------------------------------------------

def _last_sunday(year: int, month: int) -> datetime.date:
    d = datetime.date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() != 6:                  # Sunday
        d -= datetime.timedelta(days=1)
    return d


def _next_trading_day(d: datetime.date, *, calendar_name: str) -> datetime.date:
    x = d + datetime.timedelta(days=1)
    for _ in range(15):
        if _is_business(x, calendar_name):
            return x
        x += datetime.timedelta(days=1)
    raise ValueError(f"no trading day within 15d of {d}")


def _first_trading_day(year: int, month: int, *, calendar_name: str) -> datetime.date:
    d = datetime.date(year, month, 1)
    for _ in range(15):
        if _is_business(d, calendar_name):
            return d
        d += datetime.timedelta(days=1)
    raise ValueError(f"no trading day at the start of {year}-{month}")


def half_tick_onset(code: str, *, calendar_name: str = "nyse") -> datetime.date:
    """First trading day on which ``code`` quotes in **0.0025** index points.

    §22102.C, encoded rather than approximated because it decides which
    contract-days cost 0.25bp to cross and which cost 0.5bp:

    * delivery month starts **Sat, Sun or Mon** -> the first Trading Day **of**
      the delivery month;
    * delivery month starts **Tue-Fri** -> the Trading Day immediately following
      the **last Sunday of the preceding month**, so the half-tick can begin
      several days *before* the delivery month.
    """
    y, m = code_to_month(code)
    first = datetime.date(y, m, 1)
    if first.weekday() in (5, 6, 0):                   # Sat, Sun, Mon
        return _first_trading_day(y, m, calendar_name=calendar_name)
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
    return _next_trading_day(_last_sunday(py, pm), calendar_name=calendar_name)


def tick_bp(code: str, as_of: datetime.date, *,
            calendar_name: str = "nyse") -> float:
    """Minimum price fluctuation for ``code`` on ``as_of``, in bp of rate."""
    return (ZQ_HALF_TICK_BP if as_of >= half_tick_onset(code, calendar_name=calendar_name)
            else ZQ_TICK_BP)


def round_trip_bp(codes: Sequence[str], as_of: datetime.date,
                  weights: Optional[Sequence[float]] = None, *,
                  half_spread_ticks: float = 0.5,
                  calendar_name: str = "nyse") -> float:
    """Round-trip cost of a ZQ package on ``as_of``, in bp of the spread.

    Cost is per **contract** -- the same rule as SR3 -- but unlike SR3 the tick
    is not uniform across the package: a spread straddling the half-tick onset
    pays 0.5bp on one leg and 0.25bp on the other. ``weights`` are contract
    counts per leg (defaults to 1 each); ``half_spread_ticks`` is how much of a
    tick crossing costs, half by default.
    """
    w = ([1.0] * len(codes)) if weights is None else list(weights)
    if len(w) != len(codes):
        raise ValueError("weights must match codes")
    return float(sum(abs(wi) * 2.0 * float(half_spread_ticks)
                     * tick_bp(c, as_of, calendar_name=calendar_name)
                     for c, wi in zip(codes, w)))
