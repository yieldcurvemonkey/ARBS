"""Performance statistics for the basis-vs-vol backtests.

The default statistics are chosen for the specific failure mode this research programme keeps
hitting: a handful of overlapping trades produce a flattering Sharpe, and a grid search then picks
the luckiest cell. So:

* daily P&L from a position held for weeks is **autocorrelated**; the plain t-stat is inflated by
  roughly sqrt(days per trade). Use :func:`newey_west_tstat`.
* the independent unit is closer to a **trade** than a day. :func:`trade_stats` reports it.
* a grid search over N configurations must be judged by the **deflated Sharpe ratio**, which asks
  whether the best cell beats what N random cells would have produced anyway.
* concentration matters: if the top 3 trades carry the whole result, the strategy has not been
  measured. :func:`concentration` reports it.

All P&L inputs are in **vol bp** (dollars divided by the target vega), so results are scale-free
and comparable across configurations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

__all__ = [
    "EULER",
    "newey_west_tstat",
    "sharpe",
    "probabilistic_sharpe",
    "expected_max_sharpe",
    "deflated_sharpe",
    "max_drawdown",
    "concentration",
    "trade_stats",
    "summarize",
    "block_bootstrap_ci",
    "regime_split",
]

EULER = 0.5772156649015329
ANN = 252.0


def newey_west_tstat(x: pd.Series | np.ndarray, lags: int | None = None) -> tuple[float, float]:
    """(t-stat, standard error) of the mean under Newey-West (Bartlett) autocorrelation.

    ``lags=None`` uses the standard ``floor(4*(n/100)^(2/9))`` rule. For overlapping option
    positions pass the typical holding period in days -- that is the horizon over which daily P&L
    is mechanically correlated.
    """
    x = np.asarray(pd.Series(x).dropna(), float)
    n = x.size
    if n < 5:
        return float("nan"), float("nan")
    if lags is None:
        lags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(int(lags), n - 2))
    e = x - x.mean()
    gamma0 = float(e @ e) / n
    var = gamma0
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        cov = float(e[L:] @ e[:-L]) / n
        var += 2.0 * w * cov
    var = max(var, 1e-30)
    se = np.sqrt(var / n)
    return float(x.mean() / se), float(se)


def sharpe(daily: pd.Series | np.ndarray, ann: float = ANN) -> float:
    x = np.asarray(pd.Series(daily).dropna(), float)
    if x.size < 5 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / x.std(ddof=1) * np.sqrt(ann))


def probabilistic_sharpe(daily, sr_benchmark: float = 0.0, ann: float = ANN) -> float:
    """P(true Sharpe > benchmark), correcting for skew and kurtosis (Bailey & Lopez de Prado)."""
    x = np.asarray(pd.Series(daily).dropna(), float)
    n = x.size
    if n < 10 or x.std(ddof=1) == 0:
        return float("nan")
    sr = x.mean() / x.std(ddof=1)  # per-period
    srb = sr_benchmark / np.sqrt(ann)
    g3 = float(pd.Series(x).skew())
    g4 = float(pd.Series(x).kurt()) + 3.0  # non-excess
    denom = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr**2
    if denom <= 0:
        return float("nan")
    return float(norm.cdf((sr - srb) * np.sqrt(n - 1) / np.sqrt(denom)))


def expected_max_sharpe(n_trials: int, sr_variance: float, ann: float = ANN) -> float:
    """Expected maximum annualised Sharpe from ``n_trials`` independent null strategies."""
    if n_trials < 2 or not np.isfinite(sr_variance) or sr_variance <= 0:
        return 0.0
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1 - EULER) * z1 + EULER * z2))


def deflated_sharpe(daily, n_trials: int, sr_variance: float, ann: float = ANN) -> float:
    """PSR against the expected maximum Sharpe of ``n_trials`` trials.

    ``sr_variance`` is the variance of the **annualised** Sharpe ratios actually observed across
    the grid. Using the realised cross-sectional dispersion rather than an assumed one is the
    point: a grid whose cells disagree wildly needs a higher bar than one whose cells agree.
    """
    return probabilistic_sharpe(daily, expected_max_sharpe(n_trials, sr_variance, ann), ann)


def max_drawdown(equity: pd.Series | np.ndarray) -> float:
    e = np.asarray(pd.Series(equity).dropna(), float)
    if e.size == 0:
        return float("nan")
    return float(np.min(e - np.maximum.accumulate(e)))


def concentration(trade_pnl: pd.Series | np.ndarray, top: int = 3) -> dict:
    """How much of the result rests on the best few trades."""
    x = np.asarray(pd.Series(trade_pnl).dropna(), float)
    if x.size == 0:
        return {"total": np.nan, f"top{top}_share": np.nan, "n": 0}
    tot = float(x.sum())
    best = float(np.sort(x)[-top:].sum()) if x.size >= top else float(x.sum())
    return {
        "total": tot,
        f"top{top}_share": float(best / tot) if tot != 0 else np.nan,
        "n": int(x.size),
        "pnl_ex_top": float(tot - best),
    }


def trade_stats(trades: pd.DataFrame, col: str = "pnl_volbp") -> dict:
    if trades is None or trades.empty or col not in trades:
        return {"n_trades": 0}
    x = trades[col].astype(float)
    t, se = newey_west_tstat(x, lags=0)  # trades are the (approximately) independent unit
    return {
        "n_trades": int(x.size),
        "mean_volbp": float(x.mean()),
        "median_volbp": float(x.median()),
        "std_volbp": float(x.std(ddof=1)) if x.size > 1 else np.nan,
        "hit_rate": float((x > 0).mean()),
        "t_trade": t,
        "mean_hold_days": float(trades["held_days"].mean()) if "held_days" in trades else np.nan,
        **concentration(x),
    }


def summarize(daily: pd.DataFrame, trades: pd.DataFrame | None = None, col: str = "pnl_volbp",
              nw_lags: int | None = None, ann: float = ANN) -> dict:
    """One row of headline statistics for a single configuration."""
    if daily is None or daily.empty or col not in daily:
        return {"n_days": 0, "sharpe": np.nan}
    x = daily[col].astype(float)
    eq = x.cumsum()
    if nw_lags is None and trades is not None and not trades.empty and "held_days" in trades:
        nw_lags = int(max(1, round(trades["held_days"].mean())))
    t_nw, _ = newey_west_tstat(x, lags=nw_lags)
    t_naive, _ = newey_west_tstat(x, lags=0)
    days_in = int(daily["in_pos"].sum()) if "in_pos" in daily else int((x != 0).sum())
    out = {
        "n_days": int(x.size),
        "days_in_pos": days_in,
        "total_volbp": float(x.sum()),
        "ann_volbp": float(x.mean() * ann),
        "ann_vol": float(x.std(ddof=1) * np.sqrt(ann)) if x.size > 1 else np.nan,
        "sharpe": sharpe(x, ann),
        "t_naive": t_naive,
        "t_nw": t_nw,
        "nw_lags": nw_lags,
        "max_dd_volbp": max_drawdown(eq),
        "psr_0": probabilistic_sharpe(x, 0.0, ann),
    }
    if trades is not None:
        out.update(trade_stats(trades, "pnl_volbp"))
    if "cost" in daily and "gross_pnl" in daily:
        gross = float(daily["gross_pnl"].sum())
        cost = float(daily["cost"].sum())
        tv = float(abs(gross)) if gross else np.nan
        out["gross_volbp_raw"] = gross
        out["cost_raw"] = cost
        out["cost_over_gross"] = float(cost / tv) if tv and np.isfinite(tv) and tv > 0 else np.nan
    return out


def block_bootstrap_ci(daily: pd.Series, block: int = 21, n_boot: int = 2000,
                       stat=None, alpha: float = 0.05, seed: int = 12345) -> tuple[float, float]:
    """Circular block bootstrap CI. Blocks preserve the autocorrelation the positions create.

    The RNG is seeded AND consumed in a fixed order over a fixed-length array, so the result is
    reproducible -- a seed alone is not reproducibility if the draw order can vary.
    """
    x = np.asarray(pd.Series(daily).dropna(), float)
    n = x.size
    if n < block * 2:
        return (float("nan"), float("nan"))
    if stat is None:
        stat = lambda a: sharpe(a)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    samples = x[idx.reshape(n_boot, -1)[:, :n]]
    vals = np.array([stat(s) for s in samples], float)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return (float("nan"), float("nan"))
    return (float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2)))


def regime_split(daily: pd.DataFrame, col: str = "pnl_volbp", by: str = "year") -> pd.DataFrame:
    """Per-period breakdown -- a strategy alive in one regime and dead in three is not alive."""
    if daily is None or daily.empty:
        return pd.DataFrame()
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    keys = d.index.year if by == "year" else d.index.to_period("Q")
    rows = []
    for k, g in d.groupby(keys):
        rows.append({"period": str(k), "n_days": len(g), "total_volbp": float(g[col].sum()),
                     "sharpe": sharpe(g[col])})
    return pd.DataFrame(rows)
