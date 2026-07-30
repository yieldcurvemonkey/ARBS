"""One honest backtest loop over a wide level panel.

The traded object is a **level series in the traded unit** (bp for a butterfly),
so P&L is ``direction * (level[exit] - level[entry])`` and there is no mark
model to get wrong. That is the whole reason this engine exists alongside
:mod:`RVUtils.SFRRVLab.engine`, which marks option structures through a
``MarkBook`` and cannot price a futures package without inventing one.

Structural rules (not configurable, each one earned in the prior lab):

* signal on bar ``i`` fills on bar ``i + lag`` (default 1);
* a signal-driven exit also costs a lag day, but a **deterministic** exit
  (fixed horizon, max hold, stop already breached, end of sample) is known at
  entry and fills on the bar itself;
* the round-trip cost is charged once, on the exit bar, in both the trade row
  and the daily series;
* gates apply at entry only.

:class:`MRResult` carries the same fields as
``RVUtils.SFRRVLab.engine.LabResult``, so ``RVUtils.SFRRVLab.stats`` grades both
labs with identical code.
"""
from __future__ import annotations

import dataclasses
import itertools
import re
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "MRConfig", "MRResult", "run_backtest", "run_continuous", "grid_search",
    "compute_metrics", "COST_SCENARIOS", "DOLLARS_PER_BP", "leg_round_trip_bp",
]

#: SR3 (and every other CME STIR future quoted in bp of a 3M rate): $25 per bp
#: per contract. A 1/-2/1 butterfly is 4 contracts and moves $25 per bp of fly.
DOLLARS_PER_BP = 25.0

#: headline round-trip cost scenarios, bp on the whole package
COST_SCENARIOS = {"maker": 0.0, "tight": 1.5, "taker": 2.5}


def leg_round_trip_bp(n_legs: int, per_leg_one_way_bp: float = 0.25) -> float:
    """Round-trip package cost from a per-leg one-way cost.

    3 legs at 0.25bp one way = 1.5bp round trip on a butterfly, 1.0bp on a
    calendar spread, 0.5bp on an outright. Charging every structure the fly's
    1.5bp would hand the simpler shadows a cost handicap they do not have, and
    the shadow test is only meaningful if each instrument pays its own spread.
    """
    return 2.0 * int(n_legs) * float(per_leg_one_way_bp)


@dataclasses.dataclass(frozen=True)
class MRConfig:
    direction: str = "fade"                  # 'fade' | 'momentum'
    entry_z: float = 2.0
    exit_style: str = "z0"                   # 'z0' | 'half' | 'band' | 't<N>'
    exit_z: float = 0.5                      # used by 'band'
    max_hold: int = 20
    min_hold: int = 0
    stop_loss_bp: Optional[float] = None
    lag: int = 1
    round_trip_cost_bp: float = 1.5
    n_packages: int = 100
    entry_every: int = 1                     # 1 = daily, 5 = weekly
    entry_rule: str = "zscore"               # 'zscore' | 'always'
    keys: Optional[Sequence[str]] = None
    label_extra: str = ""

    def label(self) -> str:
        return (f"{self.direction}|z{self.entry_z}|{self.exit_style}"
                f"|hold{self.max_hold}|lag{self.lag}|every{self.entry_every}"
                f"|c{self.round_trip_cost_bp}"
                + (f"|{self.label_extra}" if self.label_extra else ""))


@dataclasses.dataclass
class MRResult:
    config: MRConfig
    trades: pd.DataFrame
    daily_bp: pd.Series
    metrics: Dict[str, float]

    @property
    def daily_usd(self) -> pd.Series:
        return self.daily_bp * DOLLARS_PER_BP * self.config.n_packages


def _exit_horizon(exit_style: str) -> Optional[int]:
    m = re.fullmatch(r"t(\d+)", exit_style)
    return int(m.group(1)) if m else None


def _align(levels: pd.DataFrame, signal: pd.DataFrame,
           gate: Optional[pd.DataFrame]) -> tuple:
    idx = levels.index.union(signal.index).sort_values()
    cols = [c for c in levels.columns if c in signal.columns]
    lv = levels.reindex(index=idx, columns=cols)
    sg = signal.reindex(index=idx, columns=cols)
    if gate is None:
        gt = pd.DataFrame(True, index=idx, columns=cols)
    else:
        gt = gate.reindex(index=idx, columns=cols).fillna(False).astype(bool)
    return lv, sg, gt, idx, cols


def run_backtest(
    config: MRConfig, *, levels: pd.DataFrame, signal: pd.DataFrame,
    gate: Optional[pd.DataFrame] = None,
) -> MRResult:
    """Run one config over the whole panel.

    ``levels`` and ``signal`` are wide ``date x key`` frames. ``signal`` is
    oriented so that **high means rich**: ``direction='fade'`` shorts a high
    signal, ``direction='momentum'`` buys it.
    """
    lv, sg, gt, idx, cols = _align(levels, signal, gate)
    keys = list(config.keys) if config.keys is not None else cols
    horizon = _exit_horizon(config.exit_style)
    lag = int(config.lag)
    cost = float(config.round_trip_cost_bp)

    trades: List[dict] = []
    daily: Dict[pd.Timestamp, float] = {}
    n_skipped = 0
    dates = idx.to_numpy()

    for key in keys:
        if key not in lv.columns:
            continue
        L = lv[key].to_numpy(dtype=float)
        Z = sg[key].to_numpy(dtype=float)
        G = gt[key].to_numpy(dtype=bool)
        n = L.size
        if n < lag + 3:
            continue
        pos = 0
        exec_i = -1
        entry_px = np.nan
        entry_sign = 0
        i = 0
        while i < n:
            if pos == 0:
                if i % config.entry_every != 0:
                    i += 1
                    continue
                if config.entry_rule == "always":
                    trig = bool(G[i])
                    d = 1 if config.direction == "momentum" else -1
                else:
                    trig = (bool(G[i]) and np.isfinite(Z[i])
                            and abs(Z[i]) >= config.entry_z)
                    d = int(np.sign(Z[i])) if trig else 0
                    if config.direction == "fade":
                        d = -d
                if not trig or d == 0 or i + lag >= n - 1:
                    i += 1
                    continue
                j = i + lag
                if not np.isfinite(L[j]):
                    n_skipped += 1
                    i += 1
                    continue
                pos, exec_i, entry_px = d, j, L[j]
                entry_sign = int(np.sign(Z[i])) if np.isfinite(Z[i]) else 0
                sig_i = i
                i = j + 1
                continue

            held = i - exec_i
            mark = pos * (L[i] - entry_px) if np.isfinite(L[i]) else np.nan
            if config.exit_style == "z0":
                exit_sig = (entry_sign != 0 and np.isfinite(Z[i])
                            and Z[i] * entry_sign <= 0)
            elif config.exit_style == "half":
                exit_sig = np.isfinite(Z[i]) and abs(Z[i]) <= 0.5
            elif config.exit_style == "band":
                exit_sig = np.isfinite(Z[i]) and abs(Z[i]) <= config.exit_z
            else:
                exit_sig = held >= (horizon or 10)
            if held < config.min_hold:
                exit_sig = False

            reason = None
            if exit_sig:
                reason = ("mean_reversion" if config.exit_style in ("z0", "band")
                          else "take_profit" if config.exit_style == "half" else "time")
            elif (config.stop_loss_bp is not None and np.isfinite(mark)
                  and mark <= -float(config.stop_loss_bp)):
                reason = "stop_loss"
            elif held >= config.max_hold:
                reason = "max_hold"
            elif i >= n - 1 - lag:
                reason = "eod"

            if reason is None:
                i += 1
                continue

            # A deterministic exit date is known at entry and is filled on the
            # bar itself; only a signal-driven exit costs a lag day. The stop is
            # deterministic too -- the breach is observed on the bar, not
            # forecast.
            deterministic = reason in ("time", "max_hold", "eod", "stop_loss")
            j1 = min(i if deterministic else i + lag, n - 1)
            while j1 > exec_i and not np.isfinite(L[j1]):
                j1 -= 1
            if j1 <= exec_i:
                pos = 0
                i += 1
                continue
            gross = float(pos * (L[j1] - entry_px))
            for k in range(exec_i + 1, j1 + 1):
                if np.isfinite(L[k]) and np.isfinite(L[k - 1]):
                    t = dates[k]
                    daily[t] = daily.get(t, 0.0) + float(pos * (L[k] - L[k - 1]))
            daily[dates[j1]] = daily.get(dates[j1], 0.0) - cost
            trades.append({
                "key": key, "dir": pos,
                "signal_date": dates[sig_i], "entry": dates[exec_i],
                "exit": dates[j1], "days": int(j1 - exec_i),
                "z_in": (round(float(Z[sig_i]), 3) if np.isfinite(Z[sig_i])
                         else float("nan")),
                "level_in": round(float(entry_px), 4),
                "level_out": round(float(L[j1]), 4),
                "gross_bp": round(gross, 4),
                "cost_bp": round(cost, 4),
                "net_bp": round(gross - cost, 4),
                "net_usd": round((gross - cost) * DOLLARS_PER_BP * config.n_packages, 2),
                "exit_reason": reason,
            })
            pos, exec_i = 0, -1
            i = j1 + 1

    trades_df = pd.DataFrame(trades)
    daily_s = pd.Series(daily).sort_index() if daily else pd.Series(dtype=float)
    return MRResult(config=config, trades=trades_df, daily_bp=daily_s,
                    metrics=compute_metrics(trades_df, daily_s, config,
                                            n_skipped=n_skipped))


def run_continuous(
    config: MRConfig, *, levels: pd.DataFrame, signal: pd.DataFrame,
    gate: Optional[pd.DataFrame] = None, cap: float = 2.0,
    per_leg_one_way_bp: Optional[float] = None, n_legs: int = 3,
) -> MRResult:
    """Continuous (proportional) sizing instead of a threshold rule.

    Position in packages per key is ``-clip(signal, -cap, cap)`` for ``fade``
    (``+`` for momentum), formed on bar ``i`` and held from bar ``i + lag``.
    Cost is charged on **turnover**, ``|dposition| * one-way leg cost``, which
    is the honest accounting for a strategy that never fully closes: a
    threshold rule's round trip is two one-way crossings of the same size.
    """
    lv, sg, gt, idx, cols = _align(levels, signal, gate)
    keys = list(config.keys) if config.keys is not None else cols
    one_way = (per_leg_one_way_bp if per_leg_one_way_bp is not None
               else config.round_trip_cost_bp / (2.0 * n_legs))
    leg_cost = float(one_way) * int(n_legs)          # one-way, whole package
    sign = -1.0 if config.direction == "fade" else 1.0

    raw = sg[keys].clip(-cap, cap) * sign
    raw = raw.where(gt[keys], 0.0).fillna(0.0)
    pos = raw.shift(config.lag).fillna(0.0)
    dl = lv[keys].diff()
    pnl = (pos.shift(1) * dl).sum(axis=1, min_count=1).fillna(0.0)
    turn = pos.diff().abs().sum(axis=1).fillna(0.0)
    daily = pnl - turn * leg_cost

    trades = pd.DataFrame({
        "key": ["<continuous>"], "dir": [0],
        "signal_date": [idx[0]], "entry": [idx[0]], "exit": [idx[-1]],
        "days": [len(idx)], "z_in": [np.nan],
        "level_in": [np.nan], "level_out": [np.nan],
        "gross_bp": [float(pnl.sum())],
        "cost_bp": [float((turn * leg_cost).sum())],
        "net_bp": [float(daily.sum())],
        "net_usd": [float(daily.sum()) * DOLLARS_PER_BP * config.n_packages],
        "exit_reason": ["continuous"],
    })
    m = compute_metrics(trades, daily, config, n_skipped=0)
    m["n_trades"] = int((pos.diff().abs() > 1e-9).to_numpy().sum())
    m["avg_hold_days"] = float(np.nan)
    m["turnover"] = float(turn.sum())
    return MRResult(config=config, trades=trades, daily_bp=daily, metrics=m)


def compute_metrics(trades: pd.DataFrame, daily: pd.Series, config: MRConfig, *,
                    n_skipped: int = 0) -> Dict[str, float]:
    mult = DOLLARS_PER_BP * config.n_packages
    if trades.empty or daily.empty:
        return {"n_trades": 0, "n_skipped": n_skipped, "total_gross_bp": 0.0,
                "total_net_bp": 0.0, "total_net_usd": 0.0, "hit_rate": np.nan,
                "avg_net_bp": np.nan, "sharpe": np.nan, "max_dd_bp": 0.0,
                "max_dd_usd": 0.0, "avg_hold_days": np.nan, "worst_bp": np.nan,
                "t_stat": np.nan, "n_days": 0}
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
    }


def grid_search(
    param_grid: Dict[str, Sequence], *, levels: pd.DataFrame,
    signal: pd.DataFrame, gate: Optional[pd.DataFrame] = None,
    base: Optional[MRConfig] = None, signal_fn=None,
    show_progress: bool = False, keep_results: bool = False,
) -> pd.DataFrame:
    """Cartesian sweep; one summary row per config.

    ``signal_fn(levels, **signal_params) -> DataFrame`` lets signal-construction
    parameters (lookback, smoothing) join the same grid as execution parameters.
    Any grid key that is not a field of :class:`MRConfig` is routed to it, and
    identical signal-parameter combinations are computed once and cached -- a
    120-config sweep over 6 lookbacks then builds 6 signal panels, not 120.
    """
    base = base or MRConfig()
    cfg_fields = {f.name for f in dataclasses.fields(MRConfig)}
    keys = list(param_grid)
    sig_keys = [k for k in keys if k not in cfg_fields]
    if sig_keys and signal_fn is None:
        raise ValueError(f"grid keys {sig_keys} are not MRConfig fields and no "
                         f"signal_fn was given")
    combos = list(itertools.product(*(param_grid[k] for k in keys)))
    cache: Dict[tuple, pd.DataFrame] = {}
    rows = []
    for n, combo in enumerate(combos):
        vals = dict(zip(keys, combo))
        sig_params = {k: vals[k] for k in sig_keys}
        if sig_keys:
            ck = tuple(sorted(sig_params.items()))
            if ck not in cache:
                cache[ck] = signal_fn(levels, **sig_params)
            sig = cache[ck]
        else:
            sig = signal
        cfg = dataclasses.replace(base, **{k: v for k, v in vals.items()
                                           if k in cfg_fields})
        res = run_backtest(cfg, levels=levels, signal=sig, gate=gate)
        row = {**vals, "config": cfg.label(), **res.metrics}
        if keep_results:
            row["_result"] = res
        rows.append(row)
        if show_progress and (n + 1) % 25 == 0:
            print(f"  {n + 1}/{len(combos)} configs", flush=True)
    return pd.DataFrame(rows)
