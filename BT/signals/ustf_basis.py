"""UST futures basis backtest runner.

Drives the QueryDrivenBacktest engine with the USTFutureBasis product + handler to
produce a continuous, quarterly-rolled daily mark-to-market PnL series per tenor.

Public surface:
  - front_contract / contract_segments : quarterly roll calendar
  - UstfBasisConfig                     : backtest configuration
  - run_ustf_basis_backtest(config)     : -> UstfBasisResult (per-tenor + combined)
  - build_basis_panel(...)              : daily CTD basis panel (for signals / NB 2 & 4)
  - plot_pnl(result)                    : matplotlib daily MTM PnL figure
"""
from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd
import QuantLib as ql

from BT.data_handler import TimeGrid
from BT.misc import _n_business_days_before, _nth_business_day_of_month, ql_cal_date_range
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from MDP.USTFutures.USTFuturesMDP import _BASIS_REPORT_SCHEMA_VERSION, USTFuturesMDP
from Query.USTFutureBasis.USTFutureBasisQuery import USTFutureBasisQuery

# ----------------------------------------------------------------------------
# Roll calendar
# ----------------------------------------------------------------------------
_MONTH_CODE = {3: "H", 6: "M", 9: "U", 12: "Z"}
DEFAULT_TENORS = ("TU", "FV", "TY", "US")
GOVT_CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)


def _quarterly_months_from(d: datetime.date, n: int = 12) -> List[tuple]:
    """The next `n` (year, quarterly-month) pairs at/after d's month (Mar/Jun/Sep/Dec)."""
    y, m = d.year, d.month
    while m not in (3, 6, 9, 12):
        m += 1
        if m > 12:
            m, y = 1, y + 1
    out = []
    for _ in range(n):
        out.append((y, m))
        m += 3
        if m > 12:
            m -= 12
            y += 1
    return out


def _roll_date_for(y: int, month: int, roll_days: int, cal: ql.Calendar) -> datetime.date:
    first_bd = _nth_business_day_of_month(cal, y, month, 1)
    return _n_business_days_before(cal, first_bd, roll_days)


def front_contract(root: str, d: datetime.date, roll_days: int = 6, cal: ql.Calendar = GOVT_CAL) -> str:
    """Front quarterly contract held on date `d`.

    We roll out of a contract `roll_days` business days before the first business day
    of its delivery month, so the front is the earliest quarterly contract whose roll
    date has not yet passed.
    """
    for (y, month) in _quarterly_months_from(d):
        if _roll_date_for(y, month, roll_days, cal) >= d:
            return f"{root}{_MONTH_CODE[month]}{y % 100:02d}"
    raise RuntimeError(f"could not resolve front contract for {root} @ {d}")


@dataclass(frozen=True)
class Segment:
    symbol: str
    start: datetime.date
    end: datetime.date


def contract_segments(root: str, dates: Sequence[datetime.date], roll_days: int = 6, cal: ql.Calendar = GOVT_CAL) -> List[Segment]:
    """Group business days into contiguous holding segments per front contract."""
    dates = list(dates)
    if not dates:
        return []
    fronts = [front_contract(root, d, roll_days, cal) for d in dates]
    segments: List[Segment] = []
    i, n = 0, len(dates)
    while i < n:
        sym = fronts[i]
        j = i
        while j + 1 < n and fronts[j + 1] == sym:
            j += 1
        segments.append(Segment(symbol=sym, start=dates[i], end=dates[j]))
        i = j + 1
    return segments


# ----------------------------------------------------------------------------
# Config / result
# ----------------------------------------------------------------------------
@dataclass
class UstfBasisConfig:
    tenors: List[str] = field(default_factory=lambda: list(DEFAULT_TENORS))
    start: datetime.date = datetime.date(2024, 6, 1)
    end: datetime.date = datetime.date(2026, 5, 31)
    direction: int = 1                       # +1 long basis (buy cash / sell futures), -1 short
    bond_face: float = 100_000_000.0         # cash face per tenor; futures CF-weighted to it
    specialness_bps: Union[float, Dict[str, float]] = 0.0  # CTD repo specialness (per root or scalar)
    haircut: float = 0.0
    roll_days_before_first_notice: int = 6
    tx_cost_32nds: float = 0.0               # round-trip basis cost per roll, in 32nds of face
    mdp_source: str = "BARCHART_USTF-RL"
    show_progress: bool = False

    def specialness_for(self, root: str) -> float:
        if isinstance(self.specialness_bps, dict):
            return float(self.specialness_bps.get(root, 0.0))
        return float(self.specialness_bps)

    def tx_cost_ccy(self) -> float:
        # cost of crossing `tx_cost_32nds` 32nds on the cash face
        return float(self.tx_cost_32nds) / 32.0 / 100.0 * float(self.bond_face)


@dataclass
class UstfBasisResult:
    config: UstfBasisConfig
    mtm_by_tenor: Dict[str, pd.Series]                       # cumulative total PnL ($) by date
    components_by_tenor: Dict[str, Dict[str, pd.Series]]     # financing / coupons cumulative
    backtests: Dict[str, QueryDrivenBacktest]
    time_grid_dates: List[datetime.date]

    @property
    def combined(self) -> pd.Series:
        if not self.mtm_by_tenor:
            return pd.Series(dtype=float)
        df = pd.DataFrame(self.mtm_by_tenor).sort_index().ffill().fillna(0.0)
        return df.sum(axis=1)

    def daily_pnl_by_tenor(self) -> Dict[str, pd.Series]:
        return {t: s.sort_index().diff().fillna(0.0) for t, s in self.mtm_by_tenor.items()}


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------
def _mtm_series(bt: QueryDrivenBacktest) -> pd.Series:
    data = {(ts.date() if isinstance(ts, datetime.datetime) else ts): float(v) for ts, v in bt.mtm_history.items()}
    return pd.Series(data).sort_index()


def _component_series(bt: QueryDrivenBacktest, key: str) -> pd.Series:
    comp = getattr(bt, "ustf_basis_components", {}) or {}
    hist = comp.get(key, {}) or {}
    data = {(ts.date() if isinstance(ts, datetime.datetime) else ts): float(v) for ts, v in hist.items()}
    return pd.Series(data).sort_index()


def _build_continuous_triggers(root: str, segments: List[Segment], config: UstfBasisConfig) -> List[DateTrigger]:
    spec = config.specialness_for(root)
    triggers: List[DateTrigger] = []
    for i, seg in enumerate(segments):
        tag = f"{root}#{i}#{seg.symbol}"
        q = USTFutureBasisQuery(
            symbol=seg.symbol,
            direction=config.direction,
            bond_notional=config.bond_face,
            meta={"financing": {"specialness_bps": spec, "haircut": config.haircut}},
            tags=(tag,),
        )
        triggers.append(
            DateTrigger(DateTriggerRequirements(dates=[seg.start]), actions=[AddQueryAction(query=q, meta={"tags": [tag]})])
        )
        unwind_date = segments[i + 1].start if i + 1 < len(segments) else seg.end
        triggers.append(
            DateTrigger(DateTriggerRequirements(dates=[unwind_date]), actions=[UnwindPositionsAction(match_tag=tag, fee=config.tx_cost_ccy())])
        )
    return triggers


def run_ustf_basis_backtest(config: UstfBasisConfig, mdp: Optional[USTFuturesMDP] = None) -> UstfBasisResult:
    """Run a continuous, quarterly-rolled CTD basis backtest for each tenor."""
    cal = GOVT_CAL
    grid_dt = ql_cal_date_range(
        ql_cal=cal,
        start=datetime.datetime(config.start.year, config.start.month, config.start.day),
        end=datetime.datetime(config.end.year, config.end.month, config.end.day),
        freq="1b",
    )
    grid_dates = [d.date() for d in grid_dt]
    if mdp is None:
        mdp = USTFuturesMDP(source=config.mdp_source)

    mtm_by_tenor: Dict[str, pd.Series] = {}
    components_by_tenor: Dict[str, Dict[str, pd.Series]] = {}
    backtests: Dict[str, QueryDrivenBacktest] = {}

    for root in config.tenors:
        segments = contract_segments(root, grid_dates, config.roll_days_before_first_notice, cal)
        triggers = _build_continuous_triggers(root, segments, config)
        side = "L" if config.direction >= 0 else "S"
        strat = QueryStrategy(name=f"ustfb-{root}-{side}", triggers=triggers)
        bt = QueryDrivenBacktest(time_grid=TimeGrid(grid_dt), mdp=mdp, strategy=strat, show_progress=config.show_progress)
        bt.run()

        backtests[root] = bt
        mtm_by_tenor[root] = _mtm_series(bt)
        components_by_tenor[root] = {
            "financing": _component_series(bt, "financing"),
            "coupons": _component_series(bt, "coupons"),
        }

    return UstfBasisResult(
        config=config,
        mtm_by_tenor=mtm_by_tenor,
        components_by_tenor=components_by_tenor,
        backtests=backtests,
        time_grid_dates=grid_dates,
    )


# ----------------------------------------------------------------------------
# Daily basis panel (for signals: notebooks 2 & 4)
# ----------------------------------------------------------------------------
# Stays anchored to this file, NOT routed through utils.storage_paths: four of
# these panels are TRACKED IN GIT (`git ls-files BT/signals/_ustf_basis_cache`).
# Routing it through the shared data root moves the tracked files out of the
# checkout, which shows up as four deletions in `git status` and splits the
# directory in two -- committed panels in the repo, new ones on another drive.
# "Not gitignored" is the test, and this directory fails it.
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "_ustf_basis_cache")

_PANEL_COLS = ("symbol", "ctd_cusip", "gross_basis", "bnoc", "irr", "cf", "future_price", "futures_ytm", "repo_rate")


def build_basis_panel(
    root: str,
    start: datetime.date,
    end: datetime.date,
    *,
    roll_days: int = 6,
    cal: ql.Calendar = GOVT_CAL,
    mdp: Optional[USTFuturesMDP] = None,
    force_refresh: bool = False,
    show_progress: bool = True,
) -> pd.DataFrame:
    """Daily front-contract CTD basis metrics (gross/net basis, IRR, CF) for a tenor.

    Cached to parquet under BT/signals/_ustf_basis_cache/. Used by the BNOC signal
    (NB 2) and the CTD-switch (NB 4) notebooks.
    """
    os.makedirs(_CACHE_DIR, exist_ok=True)
    # The schema stamp is part of the filename so a panel built by older code cannot be served
    # after a data-layer fix. Without it this cache is a permanent hiding place: nothing in the
    # file or its name distinguishes a pre-fix panel from a post-fix one, and the parquet is read
    # in preference to rebuilding.
    cache_path = os.path.join(
        _CACHE_DIR,
        f"panel_{root}_{start:%Y%m%d}_{end:%Y%m%d}_r{roll_days}_v{_BASIS_REPORT_SCHEMA_VERSION}.parquet",
    )
    if os.path.exists(cache_path) and not force_refresh:
        return pd.read_parquet(cache_path)

    if mdp is None:
        mdp = USTFuturesMDP(source="BARCHART_USTF-RL")

    grid_dt = ql_cal_date_range(
        ql_cal=cal,
        start=datetime.datetime(start.year, start.month, start.day),
        end=datetime.datetime(end.year, end.month, end.day),
        freq="1b",
    )
    dates = [d.date() for d in grid_dt]

    iterator = dates
    try:  # optional progress bar
        import tqdm

        if show_progress:
            iterator = tqdm.tqdm(dates, desc=f"basis panel {root}", unit="day")
    except Exception:
        pass

    rows = []
    n_rejected = 0
    n_error = 0
    for d in iterator:
        sym = front_contract(root, d, roll_days, cal)
        try:
            # on_bad_data="warn" rather than the default raise: this loop wraps everything in
            # `except Exception: continue`, so a raise here would be indistinguishable from a
            # market holiday -- the exact failure this whole exercise was about. Ask for the
            # verdict in the data instead, and drop the flagged days explicitly.
            rep = mdp.get_basis_report(symbol=sym, timestamp=d, on_bad_data="warn")
            if rep is None or rep.empty:
                continue
            if "data_ok" in rep.columns and not bool(rep["data_ok"].iloc[0]):
                n_rejected += 1
                continue
            rep_sorted = rep.sort_values("irr", ascending=False) if "irr" in rep.columns else rep
            ctd = rep_sorted.iloc[0]
            second_irr = float(rep_sorted.iloc[1]["irr"]) if len(rep_sorted) > 1 else float("nan")
            rows.append(
                {
                    "date": d,
                    "symbol": sym,
                    "ctd_cusip": ctd.get("cusip"),
                    "gross_basis": float(ctd.get("gross_basis")),
                    "bnoc": float(ctd.get("bnoc")),
                    "irr": float(ctd.get("irr")),
                    "irr_gap": float(ctd.get("irr")) - second_irr,   # CTD - runner-up: small => switch risk
                    "n_deliverables": int(len(rep_sorted)),
                    "cf": float(ctd.get("invoice_cf")),
                    "future_price": float(ctd.get("futures_price")),
                    "futures_ytm": float(ctd.get("futures_ytm")) if ctd.get("futures_ytm") is not None else None,
                    "repo_rate": float(ctd.get("repo_rate")) if ctd.get("repo_rate") is not None else None,
                }
            )
        except Exception:
            n_error += 1
            continue

    # Say what was dropped. A silently truncated panel reads as "covered everything" when it did
    # not, and that is how a strategy ends up backtested on the days that happened to survive.
    if n_rejected or n_error:
        print(
            f"basis panel {root}: {len(rows)} rows kept, {n_rejected} dropped by the consistency "
            f"gate, {n_error} dropped by errors",
            flush=True,
        )

    panel = pd.DataFrame(rows)
    if not panel.empty:
        panel = panel.set_index("date").sort_index()
        panel.to_parquet(cache_path)
    return panel


# ----------------------------------------------------------------------------
# Plotting
# ----------------------------------------------------------------------------
def plot_pnl(result: UstfBasisResult, title: str = "UST futures basis — daily MTM PnL", figsize=(13, 7)):
    """Cumulative daily MTM PnL per tenor + the combined book."""
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, height_ratios=[3, 1], sharex=True)
    for tenor, series in result.mtm_by_tenor.items():
        ax1.plot(series.index, series.values, label=tenor, lw=1.3)
    combined = result.combined
    ax1.plot(combined.index, combined.values, label="COMBINED", color="black", lw=2.0)
    ax1.axhline(0.0, color="grey", lw=0.6)
    side = "LONG" if result.config.direction >= 0 else "SHORT"
    ax1.set_title(f"{title}  [{side} basis]")
    ax1.set_ylabel("cumulative PnL ($)")
    ax1.legend(ncol=len(result.mtm_by_tenor) + 1, fontsize=8)
    ax1.grid(alpha=0.3)

    daily = result.daily_pnl_by_tenor()
    combined_daily = pd.DataFrame(daily).sum(axis=1) if daily else pd.Series(dtype=float)
    ax2.bar(combined_daily.index, combined_daily.values, width=1.0, color="steelblue")
    ax2.set_ylabel("daily PnL ($)")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    return fig


# ----------------------------------------------------------------------------
# Signal-driven runner (notebooks 2 & 4)  +  calendar-roll runner (notebook 3)
# ----------------------------------------------------------------------------
def _grid(config: "UstfBasisConfig"):
    grid_dt = ql_cal_date_range(
        ql_cal=GOVT_CAL,
        start=datetime.datetime(config.start.year, config.start.month, config.start.day),
        end=datetime.datetime(config.end.year, config.end.month, config.end.day),
        freq="1b",
    )
    return grid_dt, [d.date() for d in grid_dt]


def run_ustf_basis_signal_backtest(
    config: UstfBasisConfig,
    signal_fn: Callable[[str, pd.DataFrame], pd.Series],
    *,
    mdp: Optional[USTFuturesMDP] = None,
    panels: Optional[Dict[str, pd.DataFrame]] = None,
) -> UstfBasisResult:
    """Signal-driven CTD basis: hold long/short/flat per tenor from `signal_fn`.

    signal_fn(root, panel) -> pd.Series indexed by date with values in {-1, 0, +1}
    (the desired basis direction). Positions automatically roll when the front
    contract changes while the signal is on.
    """
    grid_dt, grid_dates = _grid(config)
    if mdp is None:
        mdp = USTFuturesMDP(source=config.mdp_source)

    mtm_by_tenor: Dict[str, pd.Series] = {}
    components_by_tenor: Dict[str, Dict[str, pd.Series]] = {}
    backtests: Dict[str, QueryDrivenBacktest] = {}
    signals_by_tenor: Dict[str, pd.Series] = {}

    for root in config.tenors:
        panel = (panels or {}).get(root)
        if panel is None:
            panel = build_basis_panel(
                root, config.start, config.end, roll_days=config.roll_days_before_first_notice, cal=GOVT_CAL, mdp=mdp, show_progress=config.show_progress
            )
        desired = signal_fn(root, panel)
        sig_map = {d: int(v) for d, v in desired.items()}
        signals_by_tenor[root] = desired

        spec = config.specialness_for(root)
        triggers: List[DateTrigger] = []
        seg_id = 0
        i, n = 0, len(grid_dates)
        while i < n:
            d = grid_dates[i]
            contract = front_contract(root, d, config.roll_days_before_first_notice, GOVT_CAL)
            dirn = int(sig_map.get(d, 0))
            if dirn == 0:
                i += 1
                continue
            j = i
            while j + 1 < n:
                d2 = grid_dates[j + 1]
                if front_contract(root, d2, config.roll_days_before_first_notice, GOVT_CAL) == contract and int(sig_map.get(d2, 0)) == dirn:
                    j += 1
                else:
                    break
            tag = f"{root}#s{seg_id}#{contract}#{'L' if dirn > 0 else 'S'}"
            q = USTFutureBasisQuery(
                symbol=contract,
                direction=dirn,
                bond_notional=config.bond_face,
                meta={"financing": {"specialness_bps": spec, "haircut": config.haircut}},
                tags=(tag,),
            )
            triggers.append(DateTrigger(DateTriggerRequirements(dates=[grid_dates[i]]), actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
            unwind_idx = j + 1 if j + 1 < n else j
            triggers.append(DateTrigger(DateTriggerRequirements(dates=[grid_dates[unwind_idx]]), actions=[UnwindPositionsAction(match_tag=tag, fee=config.tx_cost_ccy())]))
            seg_id += 1
            i = j + 1

        strat = QueryStrategy(name=f"ustfb-sig-{root}", triggers=triggers)
        bt = QueryDrivenBacktest(time_grid=TimeGrid(grid_dt), mdp=mdp, strategy=strat, show_progress=config.show_progress)
        bt.run()
        backtests[root] = bt
        mtm_by_tenor[root] = _mtm_series(bt)
        components_by_tenor[root] = {"financing": _component_series(bt, "financing"), "coupons": _component_series(bt, "coupons")}

    res = UstfBasisResult(config=config, mtm_by_tenor=mtm_by_tenor, components_by_tenor=components_by_tenor, backtests=backtests, time_grid_dates=grid_dates)
    res.signals_by_tenor = signals_by_tenor  # type: ignore[attr-defined]
    return res


def bnoc_zscore_signal(window: int = 60, z_entry: float = 1.0, z_exit: float = 0.25) -> Callable[[str, pd.DataFrame], pd.Series]:
    """Mean-reversion on net basis (BNOC): long basis when cheap, short when rich.

    BNOC = market price of the short's delivery options. z<0 => options cheap => BUY
    the basis (long optionality); z>0 => rich => SELL. Hysteresis exits near the mean.
    """
    def _sig(root: str, panel: pd.DataFrame) -> pd.Series:
        if panel is None or panel.empty or "bnoc" not in panel.columns:
            return pd.Series(dtype=int)
        s = panel["bnoc"].astype(float)
        mp = max(10, window // 3)
        mu = s.rolling(window, min_periods=mp).mean()
        sd = s.rolling(window, min_periods=mp).std().replace(0.0, np.nan)
        z = (s - mu) / sd
        out: Dict[Any, int] = {}
        pos = 0
        for d in s.index:
            zz = z.get(d, np.nan)
            if pd.isna(zz):
                out[d] = pos
                continue
            if pos == 0:
                if zz <= -z_entry:
                    pos = 1
                elif zz >= z_entry:
                    pos = -1
            elif pos == 1 and zz >= -z_exit:
                pos = 0
            elif pos == -1 and zz <= z_exit:
                pos = 0
            out[d] = pos
        return pd.Series(out, dtype=int)

    return _sig


def ctd_optionality_signal(
    vol_window: int = 21,
    vol_quantile: float = 0.6,
    z_window: int = 60,
    z_max: float = 0.0,
    irr_gap_max: Optional[float] = 0.10,
) -> Callable[[str, pd.DataFrame], pd.Series]:
    """Long-only delivery-optionality harvest (CTD-switch trade).

    Go LONG the basis when the embedded option looks cheap and likely to pay:
      - net basis (BNOC) at/below its trailing mean (cheap optionality), AND
      - elevated realised futures vol (the switch/timing options have value), AND
      - small CTD-vs-runner-up IRR gap (a CTD switch is near).
    """
    def _sig(root: str, panel: pd.DataFrame) -> pd.Series:
        if panel is None or panel.empty:
            return pd.Series(dtype=int)
        fp = panel["future_price"].astype(float)
        rv = fp.pct_change().rolling(vol_window, min_periods=max(5, vol_window // 2)).std()
        rv_thresh = rv.expanding(min_periods=vol_window).quantile(vol_quantile)
        s = panel["bnoc"].astype(float)
        mu = s.rolling(z_window, min_periods=20).mean()
        sd = s.rolling(z_window, min_periods=20).std().replace(0.0, np.nan)
        z = (s - mu) / sd
        out: Dict[Any, int] = {}
        for d in panel.index:
            cond_vol = (not pd.isna(rv.get(d))) and (not pd.isna(rv_thresh.get(d))) and rv.get(d) >= rv_thresh.get(d)
            cond_cheap = (not pd.isna(z.get(d))) and z.get(d) <= z_max
            cond_switch = True
            if irr_gap_max is not None and "irr_gap" in panel.columns:
                g = panel["irr_gap"].get(d)
                cond_switch = (not pd.isna(g)) and abs(float(g)) <= irr_gap_max
            out[d] = 1 if (cond_vol and cond_cheap and cond_switch) else 0
        return pd.Series(out, dtype=int)

    return _sig


def run_ustf_calendar_roll_backtest(
    config: UstfBasisConfig,
    *,
    mdp: Optional[USTFuturesMDP] = None,
    entry_days_before_roll: int = 5,
    calendar_contracts: int = 100,
    long_front: bool = True,
) -> UstfBasisResult:
    """Front-vs-back futures calendar (roll) spread around each quarterly roll.

    Futures-only (no cash leg / financing). Enters `entry_days_before_roll` business
    days before each roll and exits at the roll. long_front=True is long front / short
    back (i.e. short the deferred); set False to long the deferred.
    """
    from Query.USTFutures.USTFutureQuery import USTFutureQuery
    from Query.USTFutures.USTFutureValue import USTFutureValue

    grid_dt, grid_dates = _grid(config)
    if mdp is None:
        mdp = USTFuturesMDP(source=config.mdp_source)

    mtm_by_tenor: Dict[str, pd.Series] = {}
    backtests: Dict[str, QueryDrivenBacktest] = {}

    for root in config.tenors:
        segs = contract_segments(root, grid_dates, config.roll_days_before_first_notice, GOVT_CAL)
        triggers: List[DateTrigger] = []
        for i in range(len(segs) - 1):
            front, back = segs[i].symbol, segs[i + 1].symbol
            roll_date = segs[i + 1].start
            entry_date = _n_business_days_before(GOVT_CAL, roll_date, entry_days_before_roll)
            if entry_date < grid_dates[0]:
                entry_date = grid_dates[0]
            if entry_date >= roll_date:
                continue
            tag = f"{root}#cal{i}#{front}-{back}"
            rw = [1.0, -1.0] if long_front else [-1.0, 1.0]
            q = USTFutureQuery(
                symbol=f"{front}/{back}",
                value=USTFutureValue.PRICE,
                structure_kwargs={"front_contracts": calendar_contracts, "back_contracts": calendar_contracts, "risk_weights": rw},
                market_request={"include_basket": False},  # futures-only: skip the (deferred) basket
                tags=(tag,),
            )
            triggers.append(DateTrigger(DateTriggerRequirements(dates=[entry_date]), actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
            triggers.append(DateTrigger(DateTriggerRequirements(dates=[roll_date]), actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]))

        strat = QueryStrategy(name=f"ustf-roll-{root}", triggers=triggers)
        bt = QueryDrivenBacktest(time_grid=TimeGrid(grid_dt), mdp=mdp, strategy=strat, show_progress=config.show_progress)
        bt.run()
        backtests[root] = bt
        mtm_by_tenor[root] = _mtm_series(bt)

    return UstfBasisResult(config=config, mtm_by_tenor=mtm_by_tenor, components_by_tenor={}, backtests=backtests, time_grid_dates=grid_dates)
