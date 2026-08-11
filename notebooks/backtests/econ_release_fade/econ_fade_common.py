"""Fade the initial move after a tier-1/tier-2 economic data release.

A scheduled release lands at a known minute. Rates futures move within seconds.
This module measures that first move, takes the opposite side, and holds for a
configured horizon -- through the shipped ``QueryDrivenBacktest`` engine, on
STIR futures and UST futures.

Three things here are not conveniences, they are the reason the numbers can be
believed at all.

**The release minute is the unit of trading, not the release.** Of the 2,040
distinct USD tier-1/2 release minutes 2019-2026, 437 carry two events, 223 carry
three, and two carry six and seven. CPI prints with Core CPI; NFP prints with the
unemployment rate and average hourly earnings. A config that filters to "CPI" is
selecting a *minute* that also contains Core CPI, and pretending otherwise would
double-count the same price move under two names.

**Every price is the last bar at or before the timestamp.** Both shipped MDPs
resolve an intraday stamp with ``index.get_indexer(..., method="nearest")``
(``USTFuturesMDP.py:791``), which can mark against a bar that had not yet
printed. The FOMC configurable notebook traced exactly that to 64 of its 783
trades. For a strategy whose whole signal is the first minutes after a print,
a mark from after the entry is not a rounding error -- it is the signal. The
``BarCache*MDP`` shims below exist to make that impossible.

**The bar cache is warmed by RANGE, not by day.** Measured: a 3-month 1-minute
range fetch is 48,151 rows in 3.6s for SR3 and 79,044 rows in 5.3s for ZN. The
same coverage day-by-day is thousands of calls against a 55-request/60s ceiling.

Direction convention, used everywhere below:

    move_bp  > 0   the release pushed RATES UP   (futures price down)
    side     = +1  LONG the future               (profits if rates fall)
    fade     ->    side = +sign(move_bp)
    momentum ->    side = -sign(move_bp)
    pnl_bp   =     realized_pnl / dv01_usd       (bp of favourable rate move)
"""

from __future__ import annotations

import datetime
import json
import math
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pytz

from rateslib.scheduling import next_imm

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, FlowSignalTriggerRequirements

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP, _to_barchart_symbol
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue
from Query.USTFutures.USTFutureQuery import USTFutureQuery
from Query.USTFutures.USTFutureStructure import USTFutureStructure
from Query.USTFutures.USTFutureValue import USTFutureValue

from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher

HERE = Path(__file__).parent
CACHE = HERE / "_cache"
CACHE.mkdir(exist_ok=True)

MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
               7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
QUARTERLY_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}


# ===========================================================================
# Instrument registry
# ===========================================================================
@dataclass(frozen=True)
class Instrument:
    """One tradeable leg: how to name its contract, and how to turn its price
    into basis points of rate."""

    key: str
    family: str                       # "stir" | "ust"
    root: str
    ccy: str
    market_tz: str
    label: str
    #: "imm_quarterly" | "serial_monthly" | "ust_front"
    contract_kind: str = "imm_quarterly"
    #: ((from_date, root), ...) newest last. USD STIR was Eurodollar before SOFR.
    root_splice: Tuple[Tuple[datetime.date, str], ...] = ()
    #: reference round-trip cost in bp of rate, for the cost sensitivity panels
    ref_cost_bp: float = 0.5
    #: first date the vendor serves usable minute bars (measured, see MODULE notes)
    bars_from: Optional[datetime.date] = None

    @property
    def tz(self):
        return pytz.timezone(self.market_tz)

    def root_for(self, d: datetime.date) -> str:
        root = self.root
        for start, r in self.root_splice:
            if d >= start:
                root = r
        return root


#: ``bars_from`` values are measured, not guessed. SR3 barely traded before 2022
#: (2021-03: GE 541 bars/day against SR3 37), hence the splice. ZQ minute bars
#: begin around 2024-11 and thin out past rank 6 -- that is surfaced as a funnel
#: exclusion rather than hidden.
INSTRUMENTS: Dict[str, Instrument] = {
    "USD_STIR": Instrument(
        key="USD_STIR", family="stir", root="SR3", ccy="USD",
        market_tz="America/Chicago", label="USD 3M STIR (GE->SR3)",
        contract_kind="imm_quarterly",
        root_splice=((datetime.date(2019, 1, 1), "GE"),
                     (datetime.date(2022, 1, 1), "SR3")),
        ref_cost_bp=0.5, bars_from=datetime.date(2019, 1, 1),
    ),
    "ZQ": Instrument(
        key="ZQ", family="stir", root="ZQ", ccy="USD",
        market_tz="America/Chicago", label="30-day Fed Funds",
        contract_kind="serial_monthly",
        ref_cost_bp=0.5, bars_from=datetime.date(2024, 11, 1),
    ),
    "TU": Instrument(key="TU", family="ust", root="TU", ccy="USD",
                     market_tz="America/Chicago", label="2y note future (ZT)",
                     contract_kind="ust_front", ref_cost_bp=0.25),
    "FV": Instrument(key="FV", family="ust", root="FV", ccy="USD",
                     market_tz="America/Chicago", label="5y note future (ZF)",
                     contract_kind="ust_front", ref_cost_bp=0.25),
    "TY": Instrument(key="TY", family="ust", root="TY", ccy="USD",
                     market_tz="America/Chicago", label="10y note future (ZN)",
                     contract_kind="ust_front", ref_cost_bp=0.25),
    "US": Instrument(key="US", family="ust", root="US", ccy="USD",
                     market_tz="America/Chicago", label="30y bond future (ZB)",
                     contract_kind="ust_front", ref_cost_bp=0.4),
}

#: INTERNAL root -> the root Barchart actually lists it under.
#:
#: This is not cosmetic. ``USTFuturesMDP`` and the position handler both speak
#: the internal roots (``TYZ25``, and ``UST_FUTURE_TICK_SPECS`` is keyed on
#: ``TY``), while the vendor only knows ``ZNZ25``. Asking Barchart for ``TYZ25``
#: returns an empty frame rather than an error -- measured: every FV/TY/TU/US
#: contract came back with zero bars and was logged as a quiet market. Cache
#: keys and query symbols stay INTERNAL; only the wire is translated.
UST_VENDOR_ROOT: Dict[str, str] = {
    "TU": "ZT", "FV": "ZF", "TY": "ZN", "US": "ZB", "WN": "UB", "UXY": "TN",
}


def to_vendor_symbol(symbol: str) -> str:
    root = re.sub(r"[FGHJKMNQUVXZ]\d{2}$", "", symbol)
    if root in UST_VENDOR_ROOT:
        return UST_VENDOR_ROOT[root] + symbol[len(root):]
    return _to_barchart_symbol(symbol)


#: tick_size (fraction of a price point), tick_value (USD per contract).
#: Mirrors definitions/USTFutures.py:33-42 -- kept local so the bp conversion
#: below is readable next to the P&L formula it inverts.
UST_TICKS: Dict[str, Tuple[float, float]] = {
    "TU": (1.0 / 256, 7.8125),
    "FV": (1.0 / 128, 7.8125),
    "TY": (1.0 / 64, 15.625),
    "UXY": (1.0 / 64, 15.625),
    "US": (1.0 / 32, 31.25),
    "WN": (1.0 / 32, 31.25),
}


def nth_quarterly_contract(root: str, ref: datetime.date, n: int) -> str:
    """The Nth listed IMM quarterly contract as of ``ref``.

    Seeded on ``ref`` itself, not ``ref + 1 day``: seeding a day later rolls the
    contract one business day early and disagrees with the repo's own alias
    resolver on the Tuesday before every IMM Wednesday.
    """
    imm = datetime.datetime(ref.year, ref.month, ref.day)
    for _ in range(n):
        imm = next_imm(imm)
    return f"{root}{QUARTERLY_CODES[imm.month]}{str(imm.year)[-2:]}"


def nth_serial_monthly(root: str, ref: datetime.date, n: int) -> str:
    """The Nth listed serial-monthly contract as of ``ref``.

    Rank 1 is the CURRENT month's contract while it is still listed. ZQ settles
    on the arithmetic average of the month's fixings, so the current month is a
    live -- if increasingly deterministic -- instrument all month.
    """
    y, m = ref.year, ref.month
    for _ in range(n - 1):
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return f"{root}{MONTH_CODES[m]}{str(y)[-2:]}"


_UST_CAL = None


def _ust_calendar():
    global _UST_CAL
    if _UST_CAL is None:
        import QuantLib as ql
        _UST_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    return _UST_CAL


def ust_front_contract(root: str, d: datetime.date, rank: int = 1,
                       roll_days: int = 6) -> str:
    """The Nth quarterly UST future held on ``d``.

    Rolls ``roll_days`` business days before the first business day of the
    delivery month -- the same rule ``BT/signals/ustf_basis.front_contract``
    uses, so a basis backtest and this one hold the same contract on the same
    day. Three different front-month rules coexist in this repo and they
    disagree near rolls; this picks one explicitly.
    """
    import QuantLib as ql

    cal = _ust_calendar()

    def _nth_bd(y: int, month: int) -> datetime.date:
        dt0 = ql.Date(1, month, y)
        while not cal.isBusinessDay(dt0):
            dt0 = dt0 + 1
        return datetime.date(dt0.year(), dt0.month(), dt0.dayOfMonth())

    def _n_bd_before(d0: datetime.date, n: int) -> datetime.date:
        q = ql.Date(d0.day, d0.month, d0.year)
        for _ in range(n):
            q = cal.advance(q, ql.Period(-1, ql.Days))
        return datetime.date(q.year(), q.month(), q.dayOfMonth())

    y, m = d.year, d.month
    while m not in (3, 6, 9, 12):
        m += 1
        if m > 12:
            m, y = 1, y + 1

    found = 0
    for _ in range(16):
        if _n_bd_before(_nth_bd(y, m), roll_days) >= d:
            found += 1
            if found == rank:
                return f"{root}{QUARTERLY_CODES[m]}{y % 100:02d}"
        m += 3
        if m > 12:
            m -= 12
            y += 1
    raise RuntimeError(f"could not resolve contract {rank} for {root} @ {d}")


def contract_for(inst: Instrument, d: datetime.date, rank: int) -> str:
    if inst.contract_kind == "imm_quarterly":
        return nth_quarterly_contract(inst.root_for(d), d, rank)
    if inst.contract_kind == "serial_monthly":
        return nth_serial_monthly(inst.root_for(d), d, rank)
    if inst.contract_kind == "ust_front":
        return ust_front_contract(inst.root, d, rank)
    raise ValueError(f"unknown contract_kind {inst.contract_kind!r}")


# ===========================================================================
# The economic calendar
# ===========================================================================
#: Titles that carry an Actual/Forecast but are a POLICY DECISION rather than a
#: data release. They are a different animal -- the move is a committee's
#: choice, not a statistic -- so they are excluded unless a config asks for them.
CB_DECISION_PATTERNS = (
    r"^Federal Funds Rate$", r"^FOMC ", r"^Main Refinancing Rate$",
    r"^Official Bank Rate$", r"^Monetary Policy Statement$",
    r"^BOJ Policy Rate$", r"^Deposit Facility Rate$", r"^Overnight Rate$",
    r"^Cash Rate$", r"^Official Cash Rate$", r"^SNB Policy Rate$",
    r"^Rate Statement$", r"^MPC Official Bank Rate Votes$",
)

TIER1 = ("high",)
TIER12 = ("high", "medium")


def load_calendar(start: str | datetime.date, end: str | datetime.date,
                  *, fetcher: Optional[ForexFactoryCalendarFetcher] = None) -> pd.DataFrame:
    """The ForexFactory calendar, read from the LOCAL partitioned store.

    ``read_range`` never touches the network. That matters: a notebook kernel
    that silently fell back to scraping would produce a book whose coverage
    depended on whether the proxy happened to be up.
    """
    f = fetcher or ForexFactoryCalendarFetcher()
    return f.read_range(start, end)


def is_data_release(frame: pd.DataFrame) -> pd.Series:
    """A release has a NUMBER; a speech does not.

    Measured on USD tier-1/2, 2019-2026: 3,275 rows carry an Actual or a
    Forecast and 968 do not, and the second set is exactly the speeches,
    pressers, minutes and projections.
    """
    actual = frame["Actual"].fillna("").astype(str).str.strip()
    forecast = frame["Forecast"].fillna("").astype(str).str.strip()
    return (actual != "") | (forecast != "")


def is_cb_decision(frame: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    for pat in CB_DECISION_PATTERNS:
        mask |= frame["Title"].str.contains(pat, case=False, regex=True, na=False)
    return mask


# ===========================================================================
# Minute-bar cache
# ===========================================================================
#: (symbol, local date) -> DataFrame indexed by bar timestamp in the
#: instrument's market tz. Shared across every config in the process: the
#: entry/exit sweep re-gates the same symbol-days dozens of times.
_BAR_CACHE: Dict[Tuple[str, datetime.date], pd.DataFrame] = {}

#: Symbols whose range fetch FAILED, as opposed to symbols that genuinely have
#: no bars. An empty frame means opposite things in the two cases and conflating
#: them is how a sweep ends up computed from nothing.
FETCH_FAILURES: Dict[str, str] = {}

BARS_PKL = CACHE / "bars.pkl"


def save_bar_cache(path: Path = BARS_PKL) -> int:
    with open(path, "wb") as f:
        pickle.dump(_BAR_CACHE, f, protocol=4)
    return len(_BAR_CACHE)


def load_bar_cache(path: Path = BARS_PKL, *, verify: bool = True) -> int:
    """Load the warmed bars, and check the one property the pricer depends on.

    ``px_before`` finds its bar with ``searchsorted``, which returns a WRONG
    answer rather than an error on an unsorted index -- a silent mis-mark on
    every trade in the affected day. The frames are sorted on the way in, but
    "sorted on the way in" is a claim about code and this is a check on data.
    """
    if not Path(path).exists():
        return 0
    with open(path, "rb") as f:
        loaded = pickle.load(f)
    if verify:
        bad = [k for k, v in loaded.items()
               if v is not None and len(v) and not v.index.is_monotonic_increasing]
        if bad:
            raise RuntimeError(
                f"{len(bad)} cached bar frames have a non-monotonic index "
                f"(e.g. {bad[:3]}). searchsorted would mis-mark every trade on those "
                f"days -- re-run `python econ_fade_prewarm.py --stage bars --force`.")
    _BAR_CACHE.update(loaded)
    return len(_BAR_CACHE)


def cached_symbols() -> set:
    return {s for s, _ in _BAR_CACHE}


def _split_into_days(df: pd.DataFrame, symbol: str) -> int:
    """Store one frame per local calendar date.

    A day is only written if it has at least two distinct closes. Barchart pads
    days on which an illiquid contract never traded -- a full 1,440-minute grid
    carrying ONE price -- and those bars pass every timestamp check before
    booking a guaranteed zero.
    """
    n = 0
    if df is None or df.empty:
        return 0
    df = df[["Close"]].sort_index()          # searchsorted below needs it sorted
    for day, chunk in df.groupby(df.index.date):
        if len(chunk) and int(chunk["Close"].nunique()) >= 2:
            _BAR_CACHE[(symbol, day)] = chunk
            n += 1
    return n


def warm_symbol(fetcher, symbol: str, start: datetime.date, end: datetime.date,
                tz) -> int:
    """One range fetch for a whole contract's useful life.

    ``barchart_timeseries_api`` pages intraday BACKWARD in 5,000-row slices up
    to 100 slices, so a 3-month 1-minute window arrives in one call. It also
    REJECTS naive bounds and, if a window returns nothing, silently reindexes
    onto a synthetic date_range -- which is why the result is checked for a
    real, varying close before anything is stored.
    """
    s = tz.localize(datetime.datetime(start.year, start.month, start.day, 0, 0))
    e = tz.localize(datetime.datetime(end.year, end.month, end.day, 23, 59))
    bc = to_vendor_symbol(symbol)
    try:
        per = fetcher.barchart_timeseries_api(
            barchart_symbols=[bc], start_date=s, end_date=e,
            interval=1, one_df=False, show_tqdm=False,
        ) or {}
    except Exception as ex:  # noqa: BLE001
        FETCH_FAILURES[symbol] = f"{type(ex).__name__}: {ex}"[:200]
        return 0

    if hasattr(per, "__await__") or not isinstance(per, dict):
        raise RuntimeError(
            f"barchart_timeseries_api returned {type(per).__name__} for {symbol} -- "
            "it cannot fetch inside a running event loop (Jupyter). Pre-warm with "
            "`python econ_fade_prewarm.py --stage bars` from a plain process."
        )

    total = 0
    for _k, v in per.items():
        if v is None or not len(v):
            continue
        df = v.copy()
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_convert(tz)
        else:
            df.index = df.index.tz_localize(tz)
        total += _split_into_days(df, symbol)
    if total == 0 and symbol not in FETCH_FAILURES:
        FETCH_FAILURES[symbol] = "no_usable_bars"
    return total


def bars_for(symbol: str, day: datetime.date) -> Optional[pd.DataFrame]:
    return _BAR_CACHE.get((symbol, day))


#: MEASURED, and it changes what this whole study measures.
#:
#: Barchart minute bars are START-stamped: the bar labelled 07:30 America/Chicago
#: covers 07:30:00-07:30:59 and its Close is the price AT 07:31. On non-farm
#: payrolls, 2019-01-04 (312K against a 179K forecast), the 07:30 bar of the
#: 5-year note future carries Volume 22,239 against ~1,500 in each of the five
#: bars before it, Open 115.0859 and Close 114.8281 -- the release is INSIDE
#: that bar.
#:
#: So "the last bar at or before T" is not a pre-release price at T; it is a
#: price from up to a minute AFTER T. Reading the move from it would compare two
#: post-release prices and measure the residual drift instead of the release.
#: Every price in this module therefore comes from the last bar that had
#: FULLY CLOSED by the timestamp -- ``px_before`` -- whose Close is a print that
#: had genuinely happened.
BAR_INTERVAL_MIN = 1


def px_before(symbol: str, ts: pd.Timestamp) -> Optional[Tuple[pd.Timestamp, float]]:
    """The last bar to have CLOSED at or before ``ts``, and its closing price.

    A bar stamped ``b`` covers ``[b, b + BAR_INTERVAL_MIN)``, so its close is
    observable at ``b + BAR_INTERVAL_MIN``. The bar qualifies when
    ``b + BAR_INTERVAL_MIN <= ts``.

    Returns ``None`` when the day has no bars, or when no bar had closed yet --
    the second case is the ``*_before_first_bar`` exclusion, and it is common
    for an 08:30 release on a contract whose session had not opened.
    """
    df = _BAR_CACHE.get((symbol, ts.date()))
    if df is None or df.empty:
        return None
    idx = df.index
    cutoff = ts - pd.Timedelta(minutes=BAR_INTERVAL_MIN)
    # searchsorted, not a boolean mask: the grid re-gates the same symbol-days
    # dozens of times and an O(n) scan per lookup is what makes a sweep of a few
    # hundred configurations take an hour instead of a minute.
    pos = int(idx.searchsorted(cutoff, side="right")) - 1
    if pos < 0:
        return None
    return idx[pos], float(df["Close"].iloc[pos])


def px_at(symbol: str, ts: pd.Timestamp) -> Optional[Tuple[pd.Timestamp, float]]:
    """The last bar whose STAMP is at or before ``ts``.

    Kept only for diagnostics -- it is what the shipped MDPs approximate, and
    §2 of the notebook uses it to show what the contaminated reading looks like.
    Nothing in the pricing path calls it.
    """
    df = _BAR_CACHE.get((symbol, ts.date()))
    if df is None or df.empty:
        return None
    idx = df.index
    pos = int(idx.searchsorted(ts, side="right")) - 1
    if pos < 0:
        return None
    return idx[pos], float(df["Close"].iloc[pos])


# ===========================================================================
# Price <-> basis points
# ===========================================================================
DV01_JSON = CACHE / "ust_dv01.json"
#: symbol -> USD per bp per contract.
_DV01: Dict[str, float] = {}
#: STIR symbol -> USD per bp per contract (from the rateslib pricer, not assumed).
_STIR_PV01: Dict[str, float] = {}


def load_dv01(path: Path = DV01_JSON) -> int:
    if Path(path).exists():
        _DV01.update({k: float(v) for k, v in json.loads(Path(path).read_text()).items()})
    return len(_DV01)


def save_dv01(path: Path = DV01_JSON) -> int:
    Path(path).write_text(json.dumps(_DV01, indent=1, sort_keys=True))
    return len(_DV01)


def stir_pv01(symbol: str) -> float:
    """USD per bp for ONE contract at a $1mm notional, from the rateslib pricer.

    $25 for a 3M contract, which is the real SR3/GE contract value. It is NOT
    the exchange contract value for ZQ: a 30-day accrual on $1mm is $8.33/bp
    where the listed 30-day Fed Funds future is $5mm and $41.67/bp. That is
    harmless HERE because the same number sizes the position and divides the
    P&L, so ``pnl_bp`` is exactly basis points of rate either way -- but the
    ``dv01_usd`` column is a $1mm-notional figure and must not be quoted as a
    contract DV01.
    """
    if symbol in _STIR_PV01:
        return _STIR_PV01[symbol]
    from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

    eff, mat = _contract_dates(symbol)
    pr = RLSTIRFuturePricer(
        rl_stirf_id=symbol, reference_date=eff, effective_date=eff,
        maturity_date=mat, price=95.0, contracts=1, notional=1_000_000,
    )
    v = abs(float(pr.pv01(contracts=1)))
    _STIR_PV01[symbol] = v
    return v


def _contract_dates(symbol: str) -> Tuple[datetime.date, datetime.date]:
    """(effective, maturity) for a STIR contract code."""
    from rateslib.scheduling import get_imm

    root = re.sub(r"[FGHJKMNQUVXZ]\d{2}$", "", symbol)
    code = symbol[-3:]
    mcode, yy = code[0], int(code[1:])
    year = 2000 + yy
    month = {v: k for k, v in MONTH_CODES.items()}[mcode]
    if root in ("ZQ", "SR1", "SL", "IJ", "JU"):
        eff = datetime.date(year, month, 1)
        mat = datetime.date(year + (month == 12), (month % 12) + 1, 1)
        return eff, mat
    e = get_imm(code=code)
    m = next_imm(e)
    to_d = lambda d: d.date() if isinstance(d, datetime.datetime) else d  # noqa: E731
    return to_d(e), to_d(m)


#: The notional ``measure_ust_dv01`` prices at. ``RLUSTFuturePricer`` defaults to
#: 100,000 face, so a measured DV01 is dollars per bp on 100,000 -- and one price
#: POINT on 100,000 face is $1,000, whatever the listed contract's real size.
_DV01_MEASURED_AT_NOTIONAL = 100_000.0
_DOLLARS_PER_POINT_AT_MEASURED_NOTIONAL = _DV01_MEASURED_AT_NOTIONAL / 100.0   # $1,000


def px_per_bp(inst: Instrument, symbol: str) -> float:
    """Price POINTS that a one basis point change of rate is worth.

    STIR is exact -- the contract is quoted as ``100 - rate``, so 0.01 of price
    is one basis point by construction.

    A UST future needs its CTD, and the conversion has a trap in it. The DV01
    table is measured with ``RLUSTFuturePricer`` at its default 100,000 face, so
    it must be divided by the $1,000-per-point that 100,000 face implies -- NOT
    by the tick spec's dollars-per-point, which encodes the contract's REAL
    size. Those agree for FV/TY/US (100,000 face, $1,000 a point) and disagree
    for TU by a factor of two: ZT is a 200,000-face contract, so its tick spec
    gives $2,000 a point. Dividing a 100,000-face DV01 by $2,000 halves
    ``px_per_bp`` and therefore DOUBLES every ``move_bp`` and every ``pnl_bp``
    on the 2-year -- which would also have doubled it through the
    ``min_move_bp`` filter and changed which trades were taken.

    Per CONTRACT and not per root, because a 10-year future's DV01 ran $58.08 in
    2022 and $69.05 in 2019.
    """
    if inst.family == "stir":
        return 0.01
    dv01 = _DV01.get(symbol)
    if dv01 is None:
        raise KeyError(
            f"no measured DV01 for {symbol}. Run "
            f"`python econ_fade_prewarm.py --stage dv01` -- a UST price cannot be "
            f"turned into basis points without it."
        )
    return dv01 / _DOLLARS_PER_POINT_AT_MEASURED_NOTIONAL


def dv01_usd(inst: Instrument, symbol: str, contracts: int) -> float:
    """Dollars per bp for the position AS THE HANDLER PRICES IT.

    The handler's P&L is ``(dprice / tick_size) * tick_value * contracts``, so
    the dollars-per-bp that makes ``realized_pnl / dv01_usd`` come out in basis
    points is ``px_per_bp * (tick_value / tick_size) * contracts`` -- the real
    contract's DV01, which for TU is twice the 100,000-face number in the table.
    """
    if inst.family == "stir":
        return contracts * stir_pv01(symbol)
    tick_size, tick_value = UST_TICKS[inst.root]
    return contracts * px_per_bp(inst, symbol) * (tick_value / tick_size)


def measure_ust_dv01(symbols: Sequence[str], *, mdp=None,
                     show_progress: bool = True) -> Dict[str, float]:
    """DV01 per contract, from the repo's own pricer with a live deliverable basket.

    Measured cost: 0.2-2.5s per contract once the basket cache is warm, so the
    whole 2019-2026 universe is minutes.
    """
    from MDP.USTFutures.USTFuturesMDP import USTFuturesMDP

    mdp = mdp or USTFuturesMDP(source="BARCHART_USTF-RL")
    it = symbols
    if show_progress:
        try:
            from tqdm.auto import tqdm
            it = tqdm(symbols, desc="DV01")
        except Exception:  # noqa: BLE001
            pass

    out: Dict[str, float] = {}
    for sym in it:
        if sym in _DV01:
            out[sym] = _DV01[sym]
            continue
        try:
            ref = _ust_measure_date(sym)
            got = mdp.get_pricer({"symbols": [sym], "timestamp": ref, "include_basket": True})
            for _k, pr in got.items():
                u = pr.build_ustf()
                _DV01[sym] = abs(float(pr.pv01(u)))
                out[sym] = _DV01[sym]
                break
        except Exception as ex:  # noqa: BLE001
            FETCH_FAILURES[f"dv01:{sym}"] = f"{type(ex).__name__}: {ex}"[:200]
    return out


def _ust_measure_date(symbol: str) -> datetime.date:
    """A business day inside the contract's front window, ~1 month before delivery."""
    code = symbol[-3:]
    month = {v: k for k, v in QUARTERLY_CODES.items()}[code[0]]
    year = 2000 + int(code[1:])
    d = datetime.date(year, month, 1) - datetime.timedelta(days=17)
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


# ===========================================================================
# Event book
# ===========================================================================
def build_raw_events(cal: pd.DataFrame, *, currencies: Sequence[str] = ("USD",),
                     impacts: Sequence[str] = TIER12) -> pd.DataFrame:
    """One row per RELEASE MINUTE, carrying every title that printed in it.

    This is the RAW book: no config filter, no overlap rule, no data gate. Each
    of those runs downstream and is counted, so a book that shrinks is a book
    that can be explained.
    """
    df = cal[cal["Currency"].isin([c.upper() for c in currencies])].copy()
    df = df[df["Impact"].isin(list(impacts))]
    df = df[df["Timestamp"].notna()]
    df["is_release"] = is_data_release(df)
    df["is_cb"] = is_cb_decision(df)

    rows: List[dict] = []
    for ts, chunk in df.groupby("Timestamp", sort=True):
        chunk = chunk.sort_values("ImpactRank", ascending=False)
        rows.append({
            "release_ts": ts,                                   # tz-aware UTC
            "release_ts_ny": chunk["TimestampNYC"].iloc[0],
            "date": chunk["TimestampNYC"].iloc[0].date(),
            "currency": chunk["Currency"].iloc[0],
            "titles": tuple(chunk["Title"].tolist()),
            "lead_title": chunk["Title"].iloc[0],
            "n_events": int(len(chunk)),
            "impact": chunk["Impact"].iloc[0],
            "impact_rank": int(chunk["ImpactRank"].max()),
            "any_high": bool((chunk["Impact"] == "high").any()),
            "any_release": bool(chunk["is_release"].any()),
            "all_release": bool(chunk["is_release"].all()),
            "any_cb": bool(chunk["is_cb"].any()),
            "outcomes": tuple(chunk["ActualOutcome"].fillna("none").tolist()),
            "lead_outcome": chunk["ActualOutcome"].iloc[0] or "none",
            "event_ids": tuple(int(x) for x in chunk["EventId"].dropna().tolist()),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("release_ts").reset_index(drop=True)
    return out


# ===========================================================================
# Config -> book
# ===========================================================================
DEFAULT_CONFIG: Dict[str, Any] = {
    "name": "baseline",

    # WHAT IS TRADED -------------------------------------------------------
    #   family "stir": root USD_STIR (GE->SR3 splice) or ZQ, rank = Nth contract
    #   family "ust" : root TU|FV|TY|US, rank = Nth quarterly (1 = front)
    "instrument": {"family": "stir", "root": "USD_STIR", "rank": 3},

    # WHICH RELEASES -------------------------------------------------------
    "events": {
        "currencies": ["USD"],
        "impacts": ["high"],            # ["high"] tier 1, ["high","medium"] tier 1+2
        "titles_include": None,         # list of regex, matched against ANY title in the minute
        "titles_exclude": None,
        "require_actual": True,         # a release has a number; a speech does not
        "include_cb_decisions": False,  # FOMC/BoE/ECB rate decisions are a different animal
        "start": None,                  # "2022-01-01"
        "end": None,
        "weekdays": None,               # [0,1,2,3,4], Monday = 0
        "surprise": "any",              # any | better | worse | surprised
        "min_events_in_minute": 1,      # 2 -> only clustered prints
        "release_times_ny": None,       # ["08:30"] -> only the 08:30 block
    },

    # WHEN, in minutes relative to the release ------------------------------
    #
    # Every offset resolves to the last bar that had FULLY CLOSED by then, so
    # ``measure_start_min: 0`` really is the pre-release price -- the close of
    # the bar ending at T -- and not a price from inside the release minute.
    #
    # ``entry_offset_min`` defaults to one minute AFTER the measurement ends.
    # Entering at ``measure_end_min`` would fill at exactly the price the signal
    # was read from, which is a zero-latency assumption no desk can make; the
    # extra minute is the cost of having had to look first.
    "timing": {
        "measure_start_min": 0,         # the move is measured from here...
        "measure_end_min": 1,           # ...to here
        "entry_offset_min": 2,          # and traded from here
        "exit_offset_min": 60,
        "max_staleness_min": 5,         # how old a closed bar may be
        "same_day_exit": True,          # never mark against tomorrow's bars
    },

    # THE SIGNAL -----------------------------------------------------------
    "signal": {
        "direction": "fade",            # fade | momentum
        "source": "move",               # move | surprise (ForexFactory's better/worse)
        "min_move_bp": 0.0,             # skip prints that barely moved anything
        "max_move_bp": None,
    },

    # HOW MUCH -------------------------------------------------------------
    "sizing": "equal",                  # equal | move (scale by |initial move|)
    "contracts": 1,
    "cost_bp": 0.0,                     # round trip, per unit of gross risk
}


def _merge_config(cfg: Optional[dict]) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def apply_event_filters(raw: pd.DataFrame, f: dict) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Config filters, applied to the RAW book BEFORE the overlap rule.

    The order matters and it is deliberate. A CPI-only config resolves its own
    overlaps, so it trades more CPI prints than a CPI-shaped slice of a mixed
    book does -- 46 more, in the analogous FOMC study. Both are legitimate; this
    one answers "what if I only traded CPI".
    """
    drops: Dict[str, int] = defaultdict(int)
    df = raw.copy()

    def _cut(mask: pd.Series, reason: str):
        nonlocal df
        bad = int((~mask).sum())
        if bad:
            drops[reason] += bad
        df = df[mask]

    if f.get("currencies"):
        _cut(df["currency"].isin([c.upper() for c in f["currencies"]]), "currency")
    if f.get("impacts"):
        _cut(df["impact_rank"].isin([{"high": 3, "medium": 2, "low": 1}[i] for i in f["impacts"]]),
             "impact")
    if f.get("require_actual", True):
        _cut(df["any_release"], "not_a_data_release")
    if not f.get("include_cb_decisions", False):
        _cut(~df["any_cb"], "central_bank_decision")
    if f.get("start"):
        _cut(df["date"] >= pd.Timestamp(f["start"]).date(), "before_start")
    if f.get("end"):
        _cut(df["date"] <= pd.Timestamp(f["end"]).date(), "after_end")
    if f.get("weekdays") is not None:
        _cut(df["release_ts_ny"].apply(lambda t: t.weekday()).isin(list(f["weekdays"])), "weekday")
    if f.get("min_events_in_minute", 1) > 1:
        _cut(df["n_events"] >= int(f["min_events_in_minute"]), "not_clustered")
    if f.get("release_times_ny"):
        want = set(f["release_times_ny"])
        _cut(df["release_ts_ny"].apply(lambda t: t.strftime("%H:%M")).isin(want), "release_time")
    if f.get("titles_include"):
        m = pd.Series(False, index=df.index)
        for pat in f["titles_include"]:
            m |= df["titles"].apply(lambda ts, p=pat: any(re.search(p, t, re.I) for t in ts))
        _cut(m, "title_not_included")
    if f.get("titles_exclude"):
        m = pd.Series(True, index=df.index)
        for pat in f["titles_exclude"]:
            m &= ~df["titles"].apply(lambda ts, p=pat: any(re.search(p, t, re.I) for t in ts))
        _cut(m, "title_excluded")
    s = f.get("surprise", "any")
    if s != "any":
        if s == "surprised":
            _cut(df["outcomes"].apply(lambda o: any(x in ("better", "worse") for x in o)), "no_surprise")
        else:
            _cut(df["outcomes"].apply(lambda o, w=s: w in o), f"surprise_not_{s}")

    return df.reset_index(drop=True), dict(drops)


def attach_instrument(events: pd.DataFrame, inst: Instrument, rank: int) -> pd.DataFrame:
    df = events.copy()
    if df.empty:
        return df
    tz = inst.tz
    df["symbol"] = [contract_for(inst, d, rank) for d in df["date"]]
    df["local_ts"] = df["release_ts"].apply(lambda t: t.tz_convert(tz))
    df["instrument"] = inst.key
    df["rank"] = rank
    return df


def retime(events: pd.DataFrame, t: dict) -> pd.DataFrame:
    df = events.copy()
    if df.empty:
        return df
    mm = lambda n: pd.Timedelta(minutes=int(n))  # noqa: E731
    df["m0_ts"] = df["local_ts"] + mm(t["measure_start_min"])
    df["m1_ts"] = df["local_ts"] + mm(t["measure_end_min"])
    df["entry_ts"] = df["local_ts"] + mm(t["entry_offset_min"])
    df["exit_ts"] = df["local_ts"] + mm(t["exit_offset_min"])
    return df


def drop_overlaps(events: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """One position at a time.

    The engine's exit trigger unwinds by TAG, so overlapping positions would in
    fact be handled -- but they would also make two releases share one price
    path, and a book in which the same minute is counted twice is not a book of
    independent trades.
    """
    if events.empty:
        return events, 0
    df = events.sort_values("entry_ts").reset_index(drop=True)
    keep, busy_until = [], None
    for i, r in df.iterrows():
        if busy_until is not None and r["entry_ts"] < busy_until:
            continue
        keep.append(i)
        busy_until = r["exit_ts"]
    return df.loc[keep].reset_index(drop=True), int(len(df) - len(keep))


def gate_and_measure(events: pd.DataFrame, inst: Instrument, t: dict,
                     ) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Keep only releases with a genuine CAUSAL bar at all four stamps, and
    measure the initial move.

    Every exclusion is named. ``entry_before_first_bar`` in particular is not
    belt-and-braces: an 08:30 ET release on a contract whose session had not
    opened would otherwise be marked against a bar from later in the morning,
    which is the whole trade leaking backwards in time.
    """
    reasons: Dict[str, int] = defaultdict(int)
    rows: List[dict] = []
    stale_cap = float(t["max_staleness_min"])

    for _, r in events.iterrows():
        sym = r["symbol"]
        day = r["entry_ts"].date()
        if (sym, day) not in _BAR_CACHE:
            reasons["no_bars_that_day"] += 1
            continue
        if t.get("same_day_exit", True) and r["exit_ts"].date() != day:
            reasons["exit_crosses_day"] += 1
            continue

        got = {}
        bad = None
        for tag, ts in (("m0", r["m0_ts"]), ("m1", r["m1_ts"]),
                        ("entry", r["entry_ts"]), ("exit", r["exit_ts"])):
            hit = px_before(sym, ts)
            if hit is None:
                bad = f"{tag}_before_first_bar"
                break
            bar_ts, px = hit
            # Staleness is measured from when the bar CLOSED, not when it opened.
            stale = (ts - (bar_ts + pd.Timedelta(minutes=BAR_INTERVAL_MIN))).total_seconds() / 60.0
            if stale > stale_cap:
                bad = f"{tag}_stale_quote"
                break
            got[tag] = (bar_ts, px, stale)
        if bad:
            reasons[bad] += 1
            continue

        if got["m0"][0] == got["m1"][0]:
            reasons["move_window_same_bar"] += 1     # would measure a fake zero move
            continue
        if got["entry"][0] == got["exit"][0]:
            reasons["entry_exit_same_bar"] += 1      # would book a fake zero P&L
            continue

        ppb = px_per_bp(inst, sym)
        move_bp = -(got["m1"][1] - got["m0"][1]) / ppb

        d = r.to_dict()
        d.update({
            "m0_bar": got["m0"][0], "m0_px": got["m0"][1],
            "m1_bar": got["m1"][0], "m1_px": got["m1"][1],
            "entry_bar": got["entry"][0], "entry_px": got["entry"][1],
            "exit_bar": got["exit"][0], "exit_px": got["exit"][1],
            "entry_stale_min": round(got["entry"][2], 2),
            "exit_stale_min": round(got["exit"][2], 2),
            "move_bp": move_bp,
            "px_per_bp": ppb,
        })
        rows.append(d)
        reasons["ok"] += 1

    out = pd.DataFrame(rows)
    return out, dict(reasons)


def apply_signal(events: pd.DataFrame, sig: dict, sizing: str, contracts: int,
                 inst: Instrument) -> Tuple[pd.DataFrame, Dict[str, int]]:
    """Turn the measured move into a side and a size."""
    reasons: Dict[str, int] = defaultdict(int)
    if events.empty:
        return events, dict(reasons)
    df = events.copy()

    if sig.get("source", "move") == "surprise":
        # ForexFactory's own better/worse flag on the lead event. "better" means
        # the print beat its forecast, which for a growth/inflation statistic is
        # a HIGHER rate. This is the direction the release IMPLIES, not the one
        # the market took -- the two disagree often, which is the point of
        # offering both.
        implied = df["lead_outcome"].map({"better": 1.0, "worse": -1.0}).fillna(0.0)
        base = implied
        drop = int((base == 0).sum())
        if drop:
            reasons["no_surprise_direction"] += drop
        df = df[base != 0]
        base = base[base != 0]
    else:
        base = np.sign(df["move_bp"])
        drop = int((base == 0).sum())
        if drop:
            reasons["zero_move"] += drop
        df = df[base != 0]
        base = base[base != 0]

    if df.empty:
        return df, dict(reasons)

    lo = float(sig.get("min_move_bp") or 0.0)
    if lo > 0:
        m = df["move_bp"].abs() >= lo
        reasons["move_below_threshold"] += int((~m).sum())
        df, base = df[m], base[m]
    hi = sig.get("max_move_bp")
    if hi is not None:
        m = df["move_bp"].abs() <= float(hi)
        reasons["move_above_threshold"] += int((~m).sum())
        df, base = df[m], base[m]
    if df.empty:
        return df, dict(reasons)

    flip = 1.0 if sig.get("direction", "fade") == "fade" else -1.0
    df = df.copy()
    df["side"] = (flip * base).astype(float)

    if sizing == "move":
        # Conviction = how far the print pushed it. Normalised to a mean of 1 so
        # the book's gross risk is comparable with the equal-weight one.
        w = df["move_bp"].abs()
        df["contracts"] = np.maximum(1, np.round(contracts * w / w.mean())).astype(int)
    else:
        df["contracts"] = int(contracts)

    df["dv01_usd"] = [dv01_usd(inst, s, int(c)) for s, c in zip(df["symbol"], df["contracts"])]
    return df.reset_index(drop=True), dict(reasons)


def assert_entry_is_after_the_signal(timing: dict) -> None:
    """Refuse a config that fills at the price its signal was read from.

    With ``entry_offset_min == measure_end_min`` the entry price IS the second
    measurement price, identically. The side is then ``sign(m1 - m0)``, so any
    bid-ask bounce that made ``m1`` print low both sets the side to LONG and
    supplies the low entry. Half the tick noise is recovered by construction and
    the book shows a fade edge that is a property of the quote, not the market.

    This is not a hypothetical: it is what an entry/exit sweep starting at
    ``entry = 1`` with the default one-minute measurement window selects, and
    that cell would have reported the contaminated row as its best.
    """
    e, m = int(timing["entry_offset_min"]), int(timing["measure_end_min"])
    if e <= m:
        raise ValueError(
            f"entry_offset_min={e} is not after measure_end_min={m}: the trade would fill "
            f"at the exact price the signal was read from, which manufactures a fade edge "
            f"out of bid-ask bounce. Use entry_offset_min >= {m + 1}.")


def build_book(cfg: dict, raw: pd.DataFrame) -> "Book":
    """RAW calendar -> the exact set of trades one config would have taken."""
    cfg = _merge_config(cfg)
    assert_entry_is_after_the_signal(cfg["timing"])
    ispec = cfg["instrument"]
    inst = INSTRUMENTS[ispec["root"]]
    rank = int(ispec.get("rank", 1))

    funnel: Dict[str, Any] = {"raw": int(len(raw))}
    ev, drops = apply_event_filters(raw, cfg["events"])
    funnel["filter_drops"] = drops
    funnel["after_filters"] = int(len(ev))

    ev = attach_instrument(ev, inst, rank)
    ev = retime(ev, cfg["timing"])
    ev, n_over = drop_overlaps(ev)
    funnel["overlap_dropped"] = n_over
    funnel["after_overlap"] = int(len(ev))

    ev, gate = gate_and_measure(ev, inst, cfg["timing"])
    funnel["gate_reasons"] = gate
    funnel["after_gate"] = int(len(ev))

    ev, sig_drops = apply_signal(ev, cfg["signal"], cfg["sizing"],
                                 int(cfg.get("contracts", 1)), inst)
    funnel["signal_drops"] = sig_drops
    funnel["TRADEABLE"] = int(len(ev))

    if not ev.empty:
        ev = ev.copy()
        ev["tag"] = [f"{cfg['name']}|{s}|{t.strftime('%Y%m%d%H%M')}"
                     for s, t in zip(ev["symbol"], ev["entry_ts"])]
    return Book(config=cfg, instrument=inst, events=ev, funnel=funnel)


@dataclass
class Book:
    config: dict
    instrument: Instrument
    events: pd.DataFrame
    funnel: Dict[str, Any]


# ===========================================================================
# Bar-cache MDP shims
# ===========================================================================
class _BarCacheMDPBase:
    """The ``get_pricer`` surface ``QueryDrivenBacktest`` uses, served from the
    warmed minute cache instead of the vendor.

    This is the same construction ``CitiVeloSTIRFutureMDP`` uses for the JPY leg
    of the hawk/dove study: the engine, the queries, the adapters and the
    position handlers are all untouched -- only where the price comes from
    changes. It buys three things at once.

    *Causality.* The price is the last bar at or before the timestamp. The
    shipped MDPs use ``method="nearest"``, which can mark against a bar that had
    not printed.

    *Speed.* ``USTFuturesMDP`` keys its cache on the requested ISO timestamp and
    refetches a whole Chicago day per mark, against a 55-request/60s ceiling. A
    single config would take hours.

    *Reproducibility.* A config re-run tomorrow reads the same bars.
    """

    def __init__(self, inst: Instrument, *, max_stale_min: float = 5.0):
        self.inst = inst
        self.max_stale_min = float(max_stale_min)
        self._cache: Dict[Any, Any] = {}
        self.misses: Dict[Tuple[str, Any], str] = {}

    def _price(self, symbol: str, ts: datetime.datetime) -> float:
        t = pd.Timestamp(ts)
        if t.tzinfo is None:
            t = t.tz_localize(self.inst.tz)
        else:
            t = t.tz_convert(self.inst.tz)
        hit = px_before(symbol, t)
        if hit is None:
            raise RuntimeError(f"{type(self).__name__}: no closed bar for {symbol} at {t}")
        bar_ts, px = hit
        stale = (t - (bar_ts + pd.Timedelta(minutes=BAR_INTERVAL_MIN))).total_seconds() / 60.0
        if stale > self.max_stale_min:
            raise RuntimeError(
                f"{type(self).__name__}: {symbol} at {t} is {stale:.1f} min stale "
                f"(cap {self.max_stale_min})")
        return px

    def get_data(self, request: Dict[str, Any]) -> Dict[str, Any]:
        return self.get_pricer(request)

    @staticmethod
    def _unpack(request: Dict[str, Any]) -> Tuple[List[str], datetime.datetime]:
        symbols = request.get("symbols") or request.get("tickers") or []
        if not symbols:
            raise ValueError("request needs 'symbols'")
        ts = request.get("timestamp")
        if not isinstance(ts, datetime.datetime):
            raise TypeError(
                f"bar-cache MDP needs a datetime timestamp, got {type(ts)}. The query's "
                f"market_request must carry {{'timestamp': 'now'}}.")
        return list(symbols), ts


class BarCacheSTIRMDP(_BarCacheMDPBase):
    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from Query.STIRFutures.backends.rateslib.RLSTIRFuturePricer import RLSTIRFuturePricer

        symbols, ts = self._unpack(request)
        out: Dict[str, Any] = {}
        for sym in symbols:
            price = self._price(sym, ts)
            eff, mat = _contract_dates(sym)
            out[sym] = RLSTIRFuturePricer(
                rl_stirf_id=sym, reference_date=ts.date(),
                effective_date=eff, maturity_date=mat, price=price,
                contracts=1, notional=1_000_000,
            )
        return out


class BarCacheUSTMDP(_BarCacheMDPBase):
    """UST futures priced off the cache.

    ``basket=None`` is deliberate: the position handler's P&L path uses
    ``entry_leg_prices`` and the root's tick spec, so the deliverable basket is
    not needed to mark a futures-only position -- and hydrating it would pull
    the whole FedInvest curve at 14:00 Chicago for every single mark. DV01 is
    supplied separately from the measured table.
    """

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer

        symbols, ts = self._unpack(request)
        out: Dict[str, Any] = {}
        for sym in symbols:
            price = self._price(sym, ts)
            out[sym] = RLUSTFuturePricer(
                symbol=sym, reference_date=ts.date(), price=price,
                contracts=1, notional=100_000,
            )
        return out


def mdp_for(inst: Instrument, *, max_stale_min: float = 5.0):
    return (BarCacheSTIRMDP(inst, max_stale_min=max_stale_min) if inst.family == "stir"
            else BarCacheUSTMDP(inst, max_stale_min=max_stale_min))


# ===========================================================================
# Queries and the engine
# ===========================================================================
def make_query(ev: dict, inst: Instrument):
    """One outright, direction in ``risk_weights``.

    ``risk_weights=[side]`` is the ONLY correct way to short either product. A
    negative contract count does NOT short: both structure builders flip the
    risk weight negative when contracts < 0 while the leg keeps its negative
    count, and the handler multiplies by both, so the signs cancel and a
    "short" books a long. Measured on TYZ25: contracts=-1 gives +$1,000 on a
    +1.00 point move, identical to contracts=+1.
    """
    meta = {
        "instrument": inst.key, "family": inst.family, "symbol": ev["symbol"],
        "side": float(ev["side"]), "contracts": int(ev["contracts"]),
        "dv01_usd": float(ev["dv01_usd"]), "move_bp": float(ev["move_bp"]),
        "release_ts": ev["release_ts"], "lead_title": ev["lead_title"],
        "titles": ev["titles"], "n_events": int(ev["n_events"]),
        "impact": ev["impact"], "lead_outcome": ev["lead_outcome"],
        "currency": ev["currency"], "rank": int(ev["rank"]),
        "entry_px": float(ev["entry_px"]), "exit_px": float(ev["exit_px"]),
    }
    if inst.family == "stir":
        return STIRFutureQuery(
            structure=STIRFutureStructure.OUTRIGHT,
            value=STIRFutureValue.PRICE,
            symbol=ev["symbol"],
            structure_kwargs={"contracts": int(ev["contracts"]),
                              "risk_weights": [float(ev["side"])]},
            market_request={"timestamp": "now"},
            tags=(ev["tag"],), meta=meta,
        )
    return USTFutureQuery(
        structure=USTFutureStructure.OUTRIGHT,
        value=USTFutureValue.PRICE,
        symbol=ev["symbol"],
        structure_kwargs={"contracts": int(ev["contracts"]),
                          "risk_weights": [float(ev["side"])]},
        market_request={"timestamp": "now", "include_basket": False},
        tags=(ev["tag"],), meta=meta,
    )


def run_backtest(book: Book, *, show_progress: bool = True,
                 mdp=None, fee_usd: float = 0.0) -> pd.DataFrame:
    """The shipped ``QueryDrivenBacktest``, one trade per surviving release.

    Exits unwind BY TAG rather than ``match_all``. With ``match_all`` the first
    exit timestamp on the grid closes every open position, which is invisible
    while the overlap rule guarantees one position at a time and silently wrong
    the moment it does not.
    """
    ev = book.events
    if ev.empty:
        return pd.DataFrame()

    inst = book.instrument
    mdp = mdp or mdp_for(inst, max_stale_min=book.config["timing"]["max_staleness_min"])

    all_ts = sorted({_plain(t) for t in ev["entry_ts"]} | {_plain(t) for t in ev["exit_ts"]})

    triggers: List[Trigger] = []
    for _, r in ev.iterrows():
        entry, exit_, tag = _plain(r["entry_ts"]), _plain(r["exit_ts"]), r["tag"]

        def _entry_fn(state, backtest, _t=entry):
            return state == _t

        def _exit_fn(state, backtest, _t=exit_):
            return state == _t

        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_entry_fn),
            actions=[AddQueryAction(query=make_query(r.to_dict(), inst))],
        ))
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(signal_fn=_exit_fn),
            actions=[UnwindPositionsAction(match_tag=tag, fee=fee_usd)],
        ))

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(all_ts),
        mdp=mdp,
        strategy=QueryStrategy(name=book.config["name"], triggers=triggers),
        show_progress=show_progress,
        progress_desc=book.config["name"],
    )
    bt.run()

    closed = pd.DataFrame(bt.portfolio.closed_positions_log)
    if closed.empty:
        return closed
    return enrich_closed(closed, book)


def _plain(ts) -> datetime.datetime:
    """A plain ``datetime.datetime``, tz-aware, in the market's own zone.

    ``STIRFutureMDP._as_datetime`` uses ``type(ts) == datetime.datetime`` rather
    than ``isinstance``, so a ``pd.Timestamp`` -- a subclass -- is rejected
    outright. Every timestamp that can reach an MDP goes through here.
    """
    t = pd.Timestamp(ts)
    return datetime.datetime(t.year, t.month, t.day, t.hour, t.minute, t.second,
                             tzinfo=t.tzinfo)


def enrich_closed(closed: pd.DataFrame, book: Book) -> pd.DataFrame:
    closed = closed.copy()
    m = closed["source_query"].apply(lambda q: q.meta or {})
    for k in ("instrument", "family", "symbol", "side", "contracts", "dv01_usd",
              "move_bp", "release_ts", "lead_title", "titles", "n_events", "impact",
              "lead_outcome", "currency", "rank", "entry_px", "exit_px"):
        closed[k] = m.apply(lambda d, _k=k: d.get(_k))
    closed["tag"] = closed["source_query"].apply(lambda q: next(iter(q.tags), None))
    closed["opened_at"] = pd.to_datetime(closed["opened_at"], utc=True)
    closed["closed_at"] = pd.to_datetime(closed["closed_at"], utc=True)
    closed["release_ts"] = pd.to_datetime(closed["release_ts"], utc=True)
    closed["date"] = closed["release_ts"].dt.tz_convert("America/New_York").dt.date
    closed["year"] = closed["release_ts"].dt.tz_convert("America/New_York").dt.year
    closed["release_time_ny"] = (closed["release_ts"].dt.tz_convert("America/New_York")
                                 .dt.strftime("%H:%M"))
    closed["hold_min"] = (closed["closed_at"] - closed["opened_at"]).dt.total_seconds() / 60.0

    # bp of FAVOURABLE rate move, per unit of gross risk. This is the only unit
    # in which a 2-year note future and a SOFR future belong in one book.
    closed["pnl_bp_gross"] = closed["gross_realized_pnl"] / closed["dv01_usd"]
    cost = float(book.config.get("cost_bp", 0.0))
    closed["cost_bp"] = cost
    closed["pnl_bp"] = closed["pnl_bp_gross"] - cost
    closed["profitable"] = closed["pnl_bp"] > 0
    closed["abs_move_bp"] = closed["move_bp"].abs()
    closed["direction"] = np.where(closed["side"] > 0, "long future", "short future")
    return closed.sort_values("release_ts").reset_index(drop=True)


# ===========================================================================
# Closed-form pricer -- the grid's fast path
# ===========================================================================
def fast_backtest(book: Book) -> pd.DataFrame:
    """The same book priced arithmetically off the same causal bars.

    Exists so a few hundred grid configurations are minutes rather than hours.
    It is only trustworthy because ``validate_fast_vs_engine`` asserts it
    reproduces the engine trade for trade -- a fast path that is never checked
    against the slow one is a second implementation of the strategy, not an
    optimisation of the first.
    """
    ev = book.events
    if ev.empty:
        return pd.DataFrame()
    cost = float(book.config.get("cost_bp", 0.0))
    d = ev.copy()
    # side = +1 is LONG the future: it profits when the price rises, and a
    # rising price is a falling rate. Dividing by px_per_bp turns the price move
    # into basis points of rate, which is the unit the engine's
    # realized_pnl / dv01_usd also lands in.
    d["pnl_bp_gross"] = d["side"] * (d["exit_px"] - d["entry_px"]) / d["px_per_bp"]
    d["cost_bp"] = cost
    d["pnl_bp"] = d["pnl_bp_gross"] - cost
    d["profitable"] = d["pnl_bp"] > 0
    d["opened_at"] = pd.to_datetime(d["entry_ts"], utc=True)
    d["closed_at"] = pd.to_datetime(d["exit_ts"], utc=True)
    d["release_ts"] = pd.to_datetime(d["release_ts"], utc=True)
    d["year"] = d["release_ts"].dt.tz_convert("America/New_York").dt.year
    d["release_time_ny"] = (d["release_ts"].dt.tz_convert("America/New_York")
                            .dt.strftime("%H:%M"))
    d["hold_min"] = (d["closed_at"] - d["opened_at"]).dt.total_seconds() / 60.0
    d["abs_move_bp"] = d["move_bp"].abs()
    d["direction"] = np.where(d["side"] > 0, "long future", "short future")
    return d.sort_values("release_ts").reset_index(drop=True)


def validate_fast_vs_engine(book: Book, *, tol: float = 1e-6,
                            show_progress: bool = False) -> Dict[str, Any]:
    """Run both and account for EVERY disagreement.

    Not a smoke test. If the engine and the closed form differ the difference is
    reported per trade with its size, because "close enough on average" is how a
    systematic one-tick bias hides.
    """
    eng = run_backtest(book, show_progress=show_progress)
    fast = fast_backtest(book)
    if eng.empty or fast.empty:
        return {"trades_engine": int(len(eng)), "trades_fast": int(len(fast)),
                "matched": 0, "max_abs_diff": float("nan"), "ok": bool(len(eng) == len(fast))}

    j = fast[["tag", "pnl_bp_gross", "entry_ts", "exit_ts"]].merge(
        eng[["tag", "pnl_bp_gross", "opened_at", "closed_at"]].rename(
            columns={"pnl_bp_gross": "engine_bp"}),
        on="tag", how="inner")
    j["diff"] = j["pnl_bp_gross"] - j["engine_bp"]
    ad = j["diff"].abs()
    return {
        "trades_engine": int(len(eng)), "trades_fast": int(len(fast)),
        "matched": int(len(j)),
        "max_abs_diff": float(ad.max()), "mean_diff": float(j["diff"].mean()),
        "n_over_tol": int((ad > tol).sum()),
        "ok": bool(len(j) == len(eng) == len(fast) and (ad <= tol).all()),
        "detail": j.loc[ad > tol],
    }


# ===========================================================================
# Metrics
# ===========================================================================
def summarize(closed: pd.DataFrame, pnl_col: str = "pnl_bp") -> Dict[str, Any]:
    if closed is None or closed.empty:
        return {"trades": 0}
    p = closed[pnl_col].astype(float)
    n = len(p)
    span = (closed["release_ts"].max() - closed["release_ts"].min()).days
    years = max(span / 365.25, 1e-9)
    tpy = n / years
    std = float(p.std(ddof=1)) if n > 1 else 0.0
    cum = p.cumsum()
    return {
        "trades": n,
        "total_bp": float(p.sum()),
        "avg_bp": float(p.mean()),
        "std_bp": std,
        "hit_rate": float((p > 0).mean()),
        "sharpe": float(p.mean() / std * math.sqrt(tpy)) if std > 0 else 0.0,
        "sr_per_trade": float(p.mean() / std) if std > 0 else 0.0,
        "t_stat": float(p.mean() / (std / math.sqrt(n))) if std > 0 else 0.0,
        "max_dd_bp": float((cum - cum.cummax()).min()),
        "trades_per_year": float(tpy),
        "first": closed["release_ts"].min(),
        "last": closed["release_ts"].max(),
    }


def sign_flip_permutation(closed: pd.DataFrame, n_perm: int = 5000, seed: int = 42,
                          pnl_col: str = "pnl_bp") -> Dict[str, Any]:
    """The null is that the SIGN carried no information.

    Randomly flipping each trade's sign keeps the magnitude distribution exactly
    and destroys only the direction -- so it tests the thing the strategy claims
    rather than testing that rates futures move.
    """
    p = closed[pnl_col].to_numpy(float)
    if len(p) < 2 or p.std(ddof=1) == 0:
        return {"p_value": float("nan"), "realized_sharpe": 0.0,
                "perm": np.zeros(1), "perm_mean": 0.0, "perm_std": 0.0}
    rng = np.random.default_rng(seed)
    real = p.mean() / p.std(ddof=1)
    perm = np.empty(n_perm)
    for i in range(n_perm):
        s = rng.choice([-1.0, 1.0], size=len(p))
        q = p * s
        perm[i] = q.mean() / q.std(ddof=1)
    return {"realized_sharpe": float(real), "perm": perm,
            "perm_mean": float(perm.mean()), "perm_std": float(perm.std(ddof=1)),
            "p_value": float((np.abs(perm) >= abs(real)).mean())}


def expected_max_sharpe(var_sr: float, n_trials: int) -> float:
    """E[max Sharpe] under the null that every configuration has zero edge.

    Bailey & Lopez de Prado's approximation. ``var_sr`` is the observed variance
    of the trial Sharpes, which makes the hurdle GENEROUS here: the configs
    overlap heavily in events, so they are far from the independent draws the
    formula assumes.
    """
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    from scipy.stats import norm
    e = 0.5772156649015329
    a = (1 - e) * norm.ppf(1 - 1.0 / n_trials)
    b = e * norm.ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sr) * (a + b)


def deflated_sharpe(pnl: np.ndarray, sr_star: float) -> float:
    """Probability the observed Sharpe beats the selection hurdle, adjusted for
    the skew and kurtosis of the actual returns."""
    from scipy.stats import norm, skew, kurtosis
    p = np.asarray(pnl, dtype=float)
    n = len(p)
    if n < 3:
        return float("nan")
    sd = p.std(ddof=1)
    if sd <= 0:
        return float("nan")
    sr = p.mean() / sd
    g1 = float(skew(p))
    g2 = float(kurtosis(p, fisher=False))
    denom = math.sqrt(max(1e-12, 1 - g1 * sr + (g2 - 1) / 4.0 * sr ** 2))
    return float(norm.cdf((sr - sr_star) * math.sqrt(n - 1) / denom))


def bootstrap_ci(pnl: np.ndarray, n_boot: int = 5000, seed: int = 7,
                 alpha: float = 0.05) -> Tuple[float, float]:
    p = np.asarray(pnl, dtype=float)
    if len(p) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(p, size=len(p), replace=True).mean() for _ in range(n_boot)])
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))
