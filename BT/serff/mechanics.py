"""Contract mechanics for ZQ (30-day fed funds) and SR3 (3m SOFR) futures.

Everything here is deterministic calendar/settlement arithmetic:

- accrual windows (ZQ calendar month, SR3 IMM quarter) and weekend/holiday
  carry weights (a Friday print counts three times),
- settlement recomputation from fixings (ZQ arithmetic average, SR3 daily
  compounding, ACT/360),
- meeting-dated policy path bootstrapped from the ZQ strip (never regressed),
- market-implied remaining-rate backout given realized fixings,
- FOMC day-count weights per window.

Rate/price space convention: futures prices are ``100 - rate``; every
function below works in RATE space (percent) and converts at the price
boundary only, explicitly.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import QuantLib as ql

# US government securities market calendar (SOFR publication calendar);
# EFFR shares the federal holiday schedule.
SOFR_CAL = ql.UnitedStates(ql.UnitedStates.SOFR)

_MONTH_CODES = "FGHJKMNQUVXZ"
_CODE_TO_MONTH = {c: i + 1 for i, c in enumerate(_MONTH_CODES)}
_MONTH_TO_CODE = {i + 1: c for i, c in enumerate(_MONTH_CODES)}

_SYMBOL_RE = re.compile(r"^(?P<root>SR3|SR1|ZQ)(?P<code>[FGHJKMNQUVXZ])(?P<yy>\d{2})$")


# --------------------------------------------------------------------------
# dates & symbols
# --------------------------------------------------------------------------
def _to_ql(d: datetime.date) -> ql.Date:
    return ql.Date(d.day, d.month, d.year)


def _to_py(d: ql.Date) -> datetime.date:
    return datetime.date(d.year(), d.month(), d.dayOfMonth())


def is_business_day(d: datetime.date, cal: ql.Calendar = SOFR_CAL) -> bool:
    return bool(cal.isBusinessDay(_to_ql(d)))


def next_business_day(d: datetime.date, cal: ql.Calendar = SOFR_CAL) -> datetime.date:
    return _to_py(cal.advance(_to_ql(d), 1, ql.Days))


def prev_business_day_on_or_before(d: datetime.date, cal: ql.Calendar = SOFR_CAL) -> datetime.date:
    return _to_py(cal.adjust(_to_ql(d), ql.Preceding))


def third_wednesday(year: int, month: int) -> datetime.date:
    d = datetime.date(year, month, 1)
    offset = (2 - d.weekday()) % 7  # Wednesday == 2
    return d + datetime.timedelta(days=offset + 14)


def parse_symbol(symbol: str) -> Tuple[str, int, int]:
    """'SR3M26' -> ('SR3', 2026, 6); 'ZQN26' -> ('ZQ', 2026, 7)."""
    m = _SYMBOL_RE.match(symbol.strip().upper())
    if m is None:
        raise ValueError(f"Cannot parse STIR futures symbol {symbol!r}")
    yy = int(m.group("yy"))
    year = 2000 + yy if yy < 70 else 1900 + yy
    return m.group("root"), year, _CODE_TO_MONTH[m.group("code")]


def make_symbol(root: str, year: int, month: int) -> str:
    return f"{root}{_MONTH_TO_CODE[month]}{year % 100:02d}"


@dataclass(frozen=True)
class ContractWindow:
    """Half-open accrual window [start, end); settle references fixings in it."""

    symbol: str
    root: str
    start: datetime.date
    end: datetime.date

    @property
    def calendar_days(self) -> int:
        return (self.end - self.start).days

    def contains(self, d: datetime.date) -> bool:
        return self.start <= d < self.end


def contract_window(symbol: str) -> ContractWindow:
    """Accrual window for a ZQ / SR1 (calendar month) or SR3 (IMM quarter) symbol."""
    root, year, month = parse_symbol(symbol)
    if root in ("ZQ", "SR1"):
        start = datetime.date(year, month, 1)
        end = datetime.date(year + (month == 12), month % 12 + 1, 1)
    elif root == "SR3":
        start = third_wednesday(year, month)
        m2, y2 = month + 3, year
        if m2 > 12:
            m2, y2 = m2 - 12, y2 + 1
        end = third_wednesday(y2, m2)
    else:  # pragma: no cover - parse_symbol restricts roots
        raise ValueError(root)
    return ContractWindow(symbol=symbol.upper(), root=root, start=start, end=end)


def sr3_quarterly_symbols(start: datetime.date, end: datetime.date) -> List[str]:
    """SR3 quarterlies whose accrual window intersects [start, end]."""
    out = []
    for year in range(start.year - 1, end.year + 1):
        for month in (3, 6, 9, 12):
            w = contract_window(make_symbol("SR3", year, month))
            if w.end > start and w.start <= end:
                out.append(w.symbol)
    return out


def zq_monthly_symbols(start: datetime.date, end: datetime.date) -> List[str]:
    out = []
    d = datetime.date(start.year, start.month, 1)
    while d <= end:
        out.append(make_symbol("ZQ", d.year, d.month))
        d = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


# --------------------------------------------------------------------------
# carry weights (weekend/holiday rate carry)
# --------------------------------------------------------------------------
def carry_weights(window: ContractWindow, cal: ql.Calendar = SOFR_CAL) -> pd.Series:
    """Calendar-day weight per fixing date over a contract window.

    Each calendar day in [start, end) accrues the rate of the latest business
    day on or before it (CME rule: weekends/holidays carry the prior business
    day's print -- a Friday counts three times).  If the window starts on a
    non-business day the carried fixing date falls *before* the window start.

    Returns a Series indexed by fixing date, values = number of calendar days
    carried; values sum to ``window.calendar_days``.
    """
    weights: Dict[datetime.date, int] = {}
    d = window.start
    while d < window.end:
        f = prev_business_day_on_or_before(d, cal)
        weights[f] = weights.get(f, 0) + 1
        d += datetime.timedelta(days=1)
    s = pd.Series(weights, dtype=float).sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


# --------------------------------------------------------------------------
# settlement math (rate space, percent)
# --------------------------------------------------------------------------
def zq_settlement_rate(fixings: pd.Series, window: ContractWindow, cal: ql.Calendar = SOFR_CAL) -> float:
    """Arithmetic average EFFR (%) over the contract month with carry."""
    w = carry_weights(window, cal)
    r = fixings.reindex(w.index)
    if r.isna().any():
        missing = list(r[r.isna()].index.date)
        raise ValueError(f"{window.symbol}: missing fixings for {missing[:5]}{'...' if len(missing) > 5 else ''}")
    return float((r * w).sum() / w.sum())


def sr3_settlement_rate(fixings: pd.Series, window: ContractWindow, cal: ql.Calendar = SOFR_CAL) -> float:
    """Annualized daily-compounded SOFR (%) over the IMM window (ACT/360)."""
    w = carry_weights(window, cal)
    r = fixings.reindex(w.index)
    if r.isna().any():
        missing = list(r[r.isna()].index.date)
        raise ValueError(f"{window.symbol}: missing fixings for {missing[:5]}{'...' if len(missing) > 5 else ''}")
    growth = float(((1.0 + (r / 100.0) * w / 360.0)).prod())
    return (growth - 1.0) * 360.0 / w.sum() * 100.0


def settlement_rate(fixings: pd.Series, symbol: str, cal: ql.Calendar = SOFR_CAL) -> float:
    window = contract_window(symbol)
    if window.root == "SR3":
        return sr3_settlement_rate(fixings, window, cal)
    return zq_settlement_rate(fixings, window, cal)


def settlement_price(fixings: pd.Series, symbol: str, cal: ql.Calendar = SOFR_CAL) -> float:
    """Price boundary: settle price = 100 - settle rate."""
    return 100.0 - settlement_rate(fixings, symbol, cal)


# --------------------------------------------------------------------------
# FOMC weights
# --------------------------------------------------------------------------
def fomc_effective_date(decision_date: datetime.date, cal: ql.Calendar = SOFR_CAL) -> datetime.date:
    """Rate changes take effect the business day after the decision."""
    return next_business_day(decision_date, cal)


def fomc_decision_dates(
    start: datetime.date,
    end: datetime.date,
) -> List[datetime.date]:
    """FOMC decision dates from the repo's central-bank calendar."""
    from Query.IRSwaps._CENTRAL_BANK_DATES import central_bank_date_map

    dates = sorted({decision for decision, _next in central_bank_date_map("USD-FEDFUNDS").values()})
    return [d for d in dates if start <= d <= end]


def fomc_window_weight(
    window: ContractWindow,
    effective_date: datetime.date,
    cal: ql.Calendar = SOFR_CAL,
) -> float:
    """Fraction of a window's accrual affected by a move effective on a date.

    A move of size m effective at t contributes m * weight to the contract's
    settlement rate.  E.g. effective 2026-07-30: 2/31 of ZQN26 but 48/91 of
    SR3M26; effective 2026-09-17 is worth exactly zero to SR3M26.
    """
    if effective_date >= window.end:
        return 0.0
    if effective_date <= window.start:
        return 1.0
    days_after = (window.end - effective_date).days
    return days_after / window.calendar_days


# --------------------------------------------------------------------------
# meeting-dated policy path from the ZQ strip (Layer 0 input)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PolicyPath:
    """Piecewise-constant expected EFFR path implied by the ZQ strip.

    ``base_rate`` applies from ``anchor`` until the first effective date;
    each (effective_date, level) then applies onward.  Rates in percent.
    """

    anchor: datetime.date
    base_rate: float
    steps: Tuple[Tuple[datetime.date, float], ...]  # (effective_date, new level)

    def rate_on(self, d: datetime.date) -> float:
        level = self.base_rate
        for eff, lvl in self.steps:
            if d >= eff:
                level = lvl
            else:
                break
        return level

    def daily(self, dates: Iterable[datetime.date]) -> pd.Series:
        idx = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in dates))
        return pd.Series([self.rate_on(d.date()) for d in idx], index=idx, name="effr_expected")


def bootstrap_policy_path(
    as_of: datetime.date,
    zq_prices: Dict[str, float],
    effr_fixings: pd.Series,
    meeting_decisions: Sequence[datetime.date],
    cal: ql.Calendar = SOFR_CAL,
) -> PolicyPath:
    """Meeting-dated forwards from ZQ settlement prices (mechanical, no fit).

    Walks the ZQ strip month by month; realized fixings pin the elapsed part
    of the front month; each month containing exactly one effective date
    solves that meeting's jump; months with no meeting are carry months and
    provide no new unknown (their implied average is diagnostic only).

    zq_prices: symbol -> settle price as of the decision date (100 - rate).
    effr_fixings: published EFFR history (%), indexed by fixing date.
    """
    if effr_fixings.empty:
        raise ValueError("bootstrap_policy_path requires EFFR fixing history")
    last_fix_date = effr_fixings.index.max().date()
    base = float(effr_fixings.iloc[-1])

    effectives = sorted(fomc_effective_date(d, cal) for d in meeting_decisions if fomc_effective_date(d, cal) > last_fix_date)

    steps: List[Tuple[datetime.date, float]] = []
    level = base

    for symbol in sorted(zq_prices, key=lambda s: contract_window(s).start):
        window = contract_window(symbol)
        if window.end <= as_of:
            continue
        implied_avg = 100.0 - zq_prices[symbol]
        w = carry_weights(window, cal)
        total = w.sum()

        # realized portion of the window (fixings published as of the anchor)
        realized_mask = w.index.date <= last_fix_date
        realized_sum = float((effr_fixings.reindex(w.index[realized_mask]) * w[realized_mask]).sum())
        if pd.isna(realized_sum):
            realized_sum = 0.0
        rem_idx = w.index[~realized_mask]
        if len(rem_idx) == 0:
            continue

        effs_in = [e for e in effectives if rem_idx[0].date() <= e <= rem_idx[-1].date() and all(e != s[0] for s in steps)]
        if not effs_in:
            continue  # carry month: no new unknown to solve

        if len(effs_in) > 1:
            # FOMC effective dates never share a calendar month in practice;
            # if they do, attribute the whole solved jump to the last one.
            effs_in = effs_in[-1:]

        eff = effs_in[0]
        w_rem = w[~realized_mask]
        pre_mask = w_rem.index.date < eff
        pre_sum = float((w_rem[pre_mask]).sum()) * level
        # include any previously solved steps landing before this month's eff
        # (cannot happen given one-step-per-month walk, but keep exact):
        post_w = float(w_rem[~pre_mask].sum())
        if post_w <= 0:
            continue
        new_level = (implied_avg * total - realized_sum - pre_sum) / post_w
        steps.append((eff, new_level))
        level = new_level

    return PolicyPath(anchor=as_of, base_rate=base, steps=tuple(steps))


# --------------------------------------------------------------------------
# market-implied remaining rate (given realized fixings)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ImpliedRemainder:
    """Flat remaining rate/add-on consistent with a futures price."""

    symbol: str
    price: float
    realized_days: float          # carry-weighted days already fixed
    remaining_days: float
    flat_rate: Optional[float]    # flat remaining rate (%), shape=None case
    flat_addon: Optional[float]   # flat add-on over the supplied shape (%)


def implied_remainder(
    symbol: str,
    price: float,
    fixings: pd.Series,
    *,
    last_published: Optional[datetime.date] = None,
    shape: Optional[pd.Series] = None,
    cal: ql.Calendar = SOFR_CAL,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> ImpliedRemainder:
    """Solve the flat remaining rate (or add-on over ``shape``) for a price.

    Given realized fixings through ``last_published`` (default: last index of
    ``fixings``) and the current futures price, solves what the remaining
    fixings must average (ZQ, arithmetic) or compound (SR3) to for the price
    to be fair.  If ``shape`` (a %-rate Series over remaining fixing dates,
    e.g. the Layer-0 expected EFFR path) is supplied, solves the flat add-on
    ``a`` such that remaining fixings = shape + a instead.
    """
    window = contract_window(symbol)
    w = carry_weights(window, cal)
    lp = last_published or (fixings.index.max().date() if len(fixings) else None)

    realized_mask = w.index.date <= lp if lp is not None else pd.Series(False, index=w.index).values
    w_real, w_rem = w[realized_mask], w[~realized_mask]
    r_real = fixings.reindex(w_real.index)
    if len(w_real) and r_real.isna().any():
        raise ValueError(f"{symbol}: realized window days missing fixings")

    target_rate = 100.0 - price
    D = w.sum()

    if len(w_rem) == 0:
        return ImpliedRemainder(symbol, price, float(D), 0.0, None, None)

    if shape is not None:
        shape_rem = shape.reindex(w_rem.index)
        if shape_rem.isna().any():
            raise ValueError(f"{symbol}: shape does not cover remaining fixing dates")

    if window.root in ("ZQ", "SR1"):
        realized_sum = float((r_real * w_real).sum()) if len(w_real) else 0.0
        remainder_sum = target_rate * D - realized_sum
        if shape is None:
            flat = remainder_sum / w_rem.sum()
            return ImpliedRemainder(symbol, price, float(w_real.sum()), float(w_rem.sum()), flat, None)
        addon = (remainder_sum - float((shape_rem * w_rem).sum())) / w_rem.sum()
        return ImpliedRemainder(symbol, price, float(w_real.sum()), float(w_rem.sum()), None, addon)

    # SR3: solve growth factor equation by Newton on the flat unknown.
    growth_real = float((1.0 + (r_real / 100.0) * w_real / 360.0).prod()) if len(w_real) else 1.0
    target_growth = 1.0 + (target_rate / 100.0) * D / 360.0
    needed = target_growth / growth_real

    base = shape_rem.values / 100.0 if shape is not None else 0.0
    wv = w_rem.values / 360.0

    def g(x: float) -> float:
        rates = base + x / 100.0 if shape is not None else x / 100.0
        return float(np.prod(1.0 + rates * wv)) - needed

    x = float(target_rate if shape is None else 0.0)
    for _ in range(max_iter):
        fx = g(x)
        if abs(fx) < tol:
            break
        h = 1e-6
        deriv = (g(x + h) - fx) / h
        if deriv == 0:
            break
        x -= fx / deriv
    if shape is None:
        return ImpliedRemainder(symbol, price, float(w_real.sum()), float(w_rem.sum()), x, None)
    return ImpliedRemainder(symbol, price, float(w_real.sum()), float(w_rem.sum()), None, x)


# --------------------------------------------------------------------------
# ZQ strip coverage of an SR3 window (hedge construction)
# --------------------------------------------------------------------------
def covering_zq_months(window: ContractWindow) -> List[Tuple[str, float]]:
    """ZQ symbols covering an SR3 window with stub weights.

    Weight = (calendar days of the month inside the window) / (days in the
    month).  DV01 logic: 5 SR3 : 1 ZQ per fully covered month; stub months at
    the window edges scale by the weight (aggregate ~= 3 ZQ per 5 SR3).
    """
    out: List[Tuple[str, float]] = []
    d = datetime.date(window.start.year, window.start.month, 1)
    while d < window.end:
        month_end = datetime.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        overlap = (min(window.end, month_end) - max(window.start, d)).days
        if overlap > 0:
            out.append((make_symbol("ZQ", d.year, d.month), overlap / (month_end - d).days))
        d = month_end
    return out
