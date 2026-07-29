"""One honest backtest loop, shared by every framework in the SR3 RV lab.

The engine takes (a) a long signal frame — one row per (key, as_of) with a
``signal`` and a ``gate`` — and (b) a callback that builds the tradeable
:class:`~RVUtils.SFRRVLab.structures.Structure` for a key on the EXECUTION date.
It never sees a model price: P&L is the change in the package's listed premium
between the execution bar and the exit bar.

The rules that are structural, not configurable:

* **Lag.** A signal observed on bar ``i`` is executed on bar ``i + lag``
  (default 1). Exit signals are likewise observed on ``i`` and filled on
  ``i + lag``. Nothing is ever decided using a mark it could not have seen.
* **Strikes are fixed at execution** and marked at those same strikes for the
  whole holding period.
* **Costs are charged once per completed trade**, on the exit date, in the
  daily P&L series as well as in the trade row.
* **Gates apply at entry only** — a position is never force-closed because a
  surface later fails a quality check, since that would be a look-ahead exit.

``direction='fade'`` shorts a high signal; ``direction='momentum'`` buys it.
Both are always reported: the sign is a finding, not an assumption.
"""
from __future__ import annotations

import dataclasses
import itertools
import re
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from RVUtils.SFRRVLab.structures import (
    DOLLARS_PER_BP,
    MarkBook,
    Structure,
    hedged_path,
    mark_structure,
    package_contracts,
    round_trip_cost_bp,
)

__all__ = ["LabConfig", "LabResult", "run_backtest", "grid_search", "COST_SCENARIOS"]

#: headline cost scenarios, round-trip bp charged on the whole package
COST_SCENARIOS = {"maker": 0.0, "tight": 1.5, "taker": 2.5}


@dataclasses.dataclass(frozen=True)
class LabConfig:
    ma: int = 5
    zscore_window: int = 120
    zscore_min_periods: int = 40
    entry_min_zscore: float = 2.0
    direction: str = "fade"                 # 'fade' | 'momentum'
    exit_style: str = "z0"                  # 'z0' | 'half' | 't<N>'
    exit_max_holding_days: int = 20
    stop_loss_bp: Optional[float] = None
    lag: int = 1
    cost_mode: str = "flat"                 # 'flat' | 'per_leg'
    round_trip_cost_bp: float = 2.5
    option_leg_bp: float = 0.5
    future_leg_bp: float = 0.25
    quality_gate: bool = True
    contracts_per_leg: int = 100
    entry_every: int = 1                    # 1 = daily, 5 = weekly rebalance
    delta_hedge: str = "none"               # 'none' | 'daily'
    rehedge_band: float = 0.0               # delta drift tolerated before re-hedging
    max_concurrent_per_key: int = 1
    keys: Optional[Sequence[str]] = None

    def label(self) -> str:
        return (f"{self.direction}|ma{self.ma}|w{self.zscore_window}"
                f"|z{self.entry_min_zscore}|{self.exit_style}|lag{self.lag}"
                f"|every{self.entry_every}"
                + ("|dh" if self.delta_hedge == "daily" else ""))


@dataclasses.dataclass
class LabResult:
    config: LabConfig
    trades: pd.DataFrame
    daily_bp: pd.Series
    metrics: Dict[str, float]

    @property
    def daily_usd(self) -> pd.Series:
        return self.daily_bp * DOLLARS_PER_BP * self.config.contracts_per_leg


def _zscore(sub: pd.DataFrame, cfg: LabConfig) -> np.ndarray:
    s = sub["signal"].rolling(cfg.ma).mean()
    mu = s.rolling(cfg.zscore_window, min_periods=cfg.zscore_min_periods).mean()
    sd = s.rolling(cfg.zscore_window, min_periods=cfg.zscore_min_periods).std(ddof=0)
    return ((s - mu) / sd.where(sd > 1e-12)).to_numpy()


def _exit_horizon(exit_style: str) -> Optional[int]:
    m = re.fullmatch(r"t(\d+)", exit_style)
    return int(m.group(1)) if m else None


def run_backtest(
    config: LabConfig,
    *,
    signals: pd.DataFrame,
    book: MarkBook,
    builder: Callable[[str, pd.Timestamp, int], Optional[Structure]],
) -> LabResult:
    """Run one config.

    Parameters
    ----------
    signals
        Long frame with ``key``, ``as_of``, ``signal`` and optionally ``gate``
        (bool, default True) and ``eligible`` (bool, default True — an extra
        entry filter such as an FOMC window).
    builder
        ``builder(key, exec_date, direction) -> Structure | None``. Returning
        None (no listed strike within tolerance, missing leg) skips the entry;
        such skips are counted in ``metrics['n_skipped']``.
    """
    need = {"key", "as_of", "signal"}
    missing = need - set(signals.columns)
    if missing:
        raise ValueError(f"signals frame missing columns {sorted(missing)}")
    sig = signals.copy()
    sig["as_of"] = pd.to_datetime(sig["as_of"])
    if "gate" not in sig.columns:
        sig["gate"] = True
    if "eligible" not in sig.columns:
        sig["eligible"] = True

    keys = list(config.keys) if config.keys is not None else sorted(sig["key"].unique())
    horizon = _exit_horizon(config.exit_style)
    trades: List[dict] = []
    daily: Dict[pd.Timestamp, float] = {}
    n_skipped = 0

    for key in keys:
        sub = (sig[sig["key"] == key].sort_values("as_of")
               .drop_duplicates("as_of").reset_index(drop=True))
        if len(sub) < config.zscore_min_periods + config.lag + 2:
            continue
        z = _zscore(sub, config)
        gate = sub["gate"].to_numpy(dtype=bool)
        elig = sub["eligible"].to_numpy(dtype=bool)
        dates = pd.DatetimeIndex(sub["as_of"])
        n = len(sub)

        pos, sig_i, exec_i, path, cost, stale = 0, None, None, None, 0.0, 0.0
        i = 0
        while i < n:
            if pos == 0:
                can_enter = (i % config.entry_every == 0) and elig[i]
                if (can_enter and np.isfinite(z[i])
                        and abs(z[i]) >= config.entry_min_zscore
                        and (gate[i] or not config.quality_gate)
                        and i + config.lag < n - 1):
                    j = i + config.lag
                    d = int(np.sign(z[i]))
                    d = -d if config.direction == "fade" else d
                    st = builder(key, dates[j], d)
                    if st is None:
                        n_skipped += 1
                        i += 1
                        continue
                    if config.delta_hedge == "daily":
                        marks, stale, _hc = hedged_path(
                            book, st, dates[j:], rehedge_band=config.rehedge_band,
                            future_cost_bp=config.future_leg_bp)
                    else:
                        marks, stale = mark_structure(book, st, dates[j:])
                    if not np.isfinite(marks).all():
                        n_skipped += 1
                        i += 1
                        continue
                    cost = (config.round_trip_cost_bp if config.cost_mode == "flat"
                            else round_trip_cost_bp(
                                st, option_leg_bp=config.option_leg_bp,
                                future_leg_bp=config.future_leg_bp))
                    pos, sig_i, exec_i, path = d, i, j, d * marks
                    struct_label = st.label
                    pkg_contracts = package_contracts(st)
            else:
                held = i - exec_i
                mark_now = path[i - exec_i] - path[0]     # observable at bar i
                if config.exit_style == "z0":
                    exit_sig = np.isfinite(z[i]) and (z[i] * (-pos) <= 0) \
                        if config.direction == "fade" else \
                        (np.isfinite(z[i]) and (z[i] * pos <= 0))
                elif config.exit_style == "half":
                    exit_sig = np.isfinite(z[i]) and abs(z[i]) <= 0.5
                else:
                    exit_sig = held >= (horizon or 10)
                reason = None
                if exit_sig:
                    reason = ("mean_reversion" if config.exit_style == "z0"
                              else "take_profit" if config.exit_style == "half"
                              else "time")
                elif config.stop_loss_bp is not None and mark_now <= -config.stop_loss_bp:
                    reason = "stop_loss"
                elif held >= config.exit_max_holding_days:
                    reason = "max_hold"
                elif i >= n - 1 - config.lag:
                    reason = "eod"
                if reason is not None:
                    # A deterministic exit date (fixed horizon, max hold, end of
                    # sample) is known at entry, so it is filled on the bar
                    # itself; only a *signal-driven* exit costs a lag day.
                    deterministic = reason in ("time", "max_hold", "eod")
                    j1 = min(i if deterministic else i + config.lag, n - 1)
                    gross = float(path[j1 - exec_i] - path[0])
                    for k in range(exec_i + 1, j1 + 1):
                        daily[dates[k]] = daily.get(dates[k], 0.0) + float(
                            path[k - exec_i] - path[k - 1 - exec_i])
                    daily[dates[j1]] = daily.get(dates[j1], 0.0) - cost
                    trades.append({
                        "key": key, "dir": pos, "structure": struct_label,
                        "signal_date": dates[sig_i], "entry": dates[exec_i],
                        "exit": dates[j1], "days": j1 - exec_i,
                        "z_in": round(float(z[sig_i]), 3),
                        "gross_bp": round(gross, 4),
                        "cost_bp": round(cost, 4),
                        "net_bp": round(gross - cost, 4),
                        "net_usd": round((gross - cost) * DOLLARS_PER_BP
                                         * config.contracts_per_leg, 2),
                        "stale_frac": round(float(stale), 3),
                        "pkg_contracts": round(float(pkg_contracts), 2),
                        "exit_reason": reason,
                    })
                    pos, sig_i, exec_i, path = 0, None, None, None
            i += 1

    trades_df = pd.DataFrame(trades)
    daily_s = pd.Series(daily).sort_index() if daily else pd.Series(dtype=float)
    return LabResult(config=config, trades=trades_df, daily_bp=daily_s,
                     metrics=compute_metrics(trades_df, daily_s, config,
                                             n_skipped=n_skipped))


def compute_metrics(
    trades: pd.DataFrame, daily: pd.Series, config: LabConfig, *, n_skipped: int = 0
) -> Dict[str, float]:
    mult = DOLLARS_PER_BP * config.contracts_per_leg
    if trades.empty or daily.empty:
        return {"n_trades": 0, "n_skipped": n_skipped, "total_net_bp": 0.0,
                "total_net_usd": 0.0, "hit_rate": np.nan, "avg_net_bp": np.nan,
                "sharpe": np.nan, "max_dd_bp": 0.0, "max_dd_usd": 0.0,
                "avg_hold_days": np.nan, "worst_bp": np.nan, "t_stat": np.nan,
                "n_days": 0, "avg_stale": np.nan}
    cum = daily.cumsum()
    dd = float((cum - cum.cummax()).min())
    sd = daily.std(ddof=1)
    g = trades["net_bp"]
    return {
        "n_trades": int(len(trades)),
        "n_skipped": int(n_skipped),
        "total_gross_bp": float(trades["gross_bp"].sum()),
        "total_net_bp": float(g.sum()),
        "total_net_usd": float(g.sum() * mult),
        "hit_rate": float((g > 0).mean()),
        "avg_net_bp": float(g.mean()),
        "sharpe": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else np.nan,
        "max_dd_bp": dd,
        "max_dd_usd": dd * mult,
        "avg_hold_days": float(trades["days"].mean()),
        "worst_bp": float(g.min()),
        "t_stat": (float(g.mean() / (g.std(ddof=1) / np.sqrt(len(g))))
                   if len(g) > 2 and g.std(ddof=1) > 0 else np.nan),
        "n_days": int(len(daily)),
        "avg_stale": float(trades["stale_frac"].mean()),
        "pkg_contracts": (float(trades["pkg_contracts"].median())
                          if "pkg_contracts" in trades.columns else np.nan),
    }


def grid_search(
    param_grid: Dict[str, Sequence],
    *,
    signals: pd.DataFrame,
    book: MarkBook,
    builder: Callable[[str, pd.Timestamp, int], Optional[Structure]],
    base: Optional[LabConfig] = None,
    show_progress: bool = False,
    keep_results: bool = False,
) -> pd.DataFrame:
    """Cartesian sweep; one summary row per config (plus the LabResult if asked)."""
    base = base or LabConfig()
    keys = list(param_grid)
    combos = list(itertools.product(*(param_grid[k] for k in keys)))
    rows = []
    for n, combo in enumerate(combos):
        cfg = dataclasses.replace(base, **dict(zip(keys, combo)))
        res = run_backtest(cfg, signals=signals, book=book, builder=builder)
        row = {**dict(zip(keys, combo)), "config": cfg.label(), **res.metrics}
        if keep_results:
            row["_result"] = res
        rows.append(row)
        if show_progress and (n + 1) % 25 == 0:
            print(f"  {n + 1}/{len(combos)} configs", flush=True)
    return pd.DataFrame(rows)
