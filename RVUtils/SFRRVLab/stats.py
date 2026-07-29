"""Grid discipline, deflation and the honesty panels.

The top row of a sweep is never the verdict. These helpers produce the three
things every framework notebook must show alongside a headline number:

* the **distribution** of the sweep (median config, share net-positive),
* the **deflated Sharpe** of the selected config given how many configs were
  tried (Bailey & Lopez de Prado, via ``BT/signals/deflated_sharpe.py``), and
* **neighbourhood stability** — the same config with one parameter moved at a
  time, so a knife-edge optimum is visible as a knife edge.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from BT.signals.deflated_sharpe import deflated_sharpe, sharpe_stats

__all__ = [
    "grid_distribution", "deflated_for_grid", "neighbourhood_stability",
    "nw_tstat", "nonoverlapping_sharpe", "cost_curve", "verdict",
]


def grid_distribution(res: pd.DataFrame, metric: str = "total_net_bp") -> Dict[str, float]:
    """Median / quartiles / share-positive of a sweep, plus the best row's value."""
    x = res[metric].astype(float).dropna()
    if x.empty:
        return {"n_configs": 0}
    return {
        "n_configs": int(len(res)),
        "median": float(x.median()),
        "q25": float(x.quantile(0.25)),
        "q75": float(x.quantile(0.75)),
        "pct_positive": float((x > 0).mean()),
        "best": float(x.max()),
        "worst": float(x.min()),
    }


def deflated_for_grid(
    daily_bp: pd.Series, res: pd.DataFrame, *, sharpe_col: str = "sharpe"
) -> Dict[str, float]:
    """DSR of one config's daily P&L, deflated by the whole sweep.

    ``n_trials`` is the number of configs actually run; the cross-trial variance
    of per-period Sharpes comes from the sweep itself (the honest input — using
    the default would understate the multiple-testing penalty).
    """
    r = pd.Series(daily_bp).astype(float).dropna()
    if r.empty or len(r) < 5:
        return {"dsr_prob": np.nan, "sr_annualised": np.nan, "n_trials": len(res)}
    sr_per_period = res[sharpe_col].astype(float).dropna() / np.sqrt(252.0)
    var = float(sr_per_period.var(ddof=1)) if len(sr_per_period) > 2 else None
    out = deflated_sharpe(r.to_numpy(), n_trials=max(int(len(res)), 1),
                          sr_variance=var)
    out["n_trials"] = int(len(res))
    return out


def neighbourhood_stability(
    res: pd.DataFrame, best: pd.Series, params: Sequence[str],
    *, metric: str = "total_net_bp",
) -> pd.DataFrame:
    """One-param-at-a-time slice through the sweep around ``best``.

    Every row holds all parameters at the best config's values except one, which
    is swept over the values present in the grid.
    """
    rows = []
    for p in params:
        others = [q for q in params if q != p]
        mask = np.ones(len(res), dtype=bool)
        for q in others:
            mask &= (res[q] == best[q]).to_numpy()
        sl = res[mask].sort_values(p)
        for _, r in sl.iterrows():
            rows.append({"param": p, "value": r[p], metric: r[metric],
                         "n_trades": r.get("n_trades", np.nan),
                         "is_best": bool(r[p] == best[p])})
    return pd.DataFrame(rows)


def nw_tstat(x: Iterable[float], lags: int = 5) -> float:
    """Newey-West t-statistic of the mean (HAC, Bartlett kernel)."""
    a = np.asarray(list(x), dtype=float)
    a = a[np.isfinite(a)]
    n = a.size
    if n < 5:
        return float("nan")
    e = a - a.mean()
    gamma0 = float(e @ e) / n
    s = gamma0
    for l in range(1, min(lags, n - 1) + 1):
        g = float(e[l:] @ e[:-l]) / n
        s += 2.0 * (1.0 - l / (lags + 1.0)) * g
    if s <= 0:
        return float("nan")
    return float(a.mean() / np.sqrt(s / n))


def nonoverlapping_sharpe(trades: pd.DataFrame, *, pnl_col: str = "net_bp") -> float:
    """Per-trade Sharpe on non-overlapping trades only (greedy by entry date).

    Overlapping trades share market moves, so their per-trade dispersion
    understates risk; this keeps a maximal set of disjoint holding windows.
    """
    if trades.empty:
        return float("nan")
    t = trades.sort_values("entry")
    last_exit = pd.Timestamp.min
    keep = []
    for _, r in t.iterrows():
        if r["entry"] >= last_exit:
            keep.append(r[pnl_col])
            last_exit = r["exit"]
    a = np.asarray(keep, dtype=float)
    if a.size < 3 or a.std(ddof=1) == 0:
        return float("nan")
    return float(a.mean() / a.std(ddof=1))


def cost_curve(trades: pd.DataFrame, costs_bp: Sequence[float]) -> pd.DataFrame:
    """Total P&L and hit rate as a function of the round-trip cost charged.

    ``trades`` must carry ``gross_bp``; the stored ``cost_bp`` is replaced, so
    one backtest run yields the whole maker-to-taker curve.
    """
    rows = []
    for c in costs_bp:
        net = trades["gross_bp"] - c
        rows.append({"round_trip_bp": c, "n": len(trades),
                     "total_net_bp": float(net.sum()),
                     "avg_net_bp": float(net.mean()) if len(net) else np.nan,
                     "hit_rate": float((net > 0).mean()) if len(net) else np.nan})
    return pd.DataFrame(rows)


def verdict(
    *, net_bp_at_taker: float, net_bp_at_maker: float, dsr_prob: float,
    median_net_bp: float, n_trades: int,
) -> str:
    """DEAD / MARGINAL-maker-only / ALIVE, applied uniformly across frameworks.

    ALIVE needs all of: positive at taker costs, DSR probability above 0.5
    (the selected config beats the expected best-of-N under the null), a
    non-negative median config (the edge is not one lucky corner), and enough
    trades to say anything.
    """
    if n_trades < 10:
        return "DEAD (too few trades)"
    if net_bp_at_taker > 0 and dsr_prob > 0.5 and median_net_bp >= 0:
        return "ALIVE"
    if net_bp_at_maker > 0:
        return "MARGINAL-maker-only"
    return "DEAD"
