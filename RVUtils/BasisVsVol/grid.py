"""Grid search, pooling and placebo controls for the V2 backtest.

A grid search is a multiple-testing machine. This module is built so that the number of trials is
always known and always reported, so the deflated Sharpe ratio has a real ``n_trials`` rather than
a flattering one, and so the winning cell is never presented without the controls that say whether
it is a mechanism or a coincidence.

Three controls ship with the search, all of which the winner must survive:

* **shuffled-signal placebo** -- keep the trade calendar and sizing, randomise the sign. If the
  shuffled version performs comparably, the edge is in the exposure, not the signal.
* **mismatched-pair placebo** -- run the futures-option leg against an economically wrong swaption
  tail (a 2y tail against the bond contract). A signal that survives a deliberately wrong pairing
  is not measuring a cross-product wedge.
* **cost ladder** -- 1x, 2x, 3x assumed costs. Anything that dies at 2x was never alive.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import numpy as np
import pandas as pd

from .analytics import deflated_sharpe, expected_max_sharpe, sharpe, summarize
from .strategy import DEFAULT_UNIVERSE, BacktestResult, StrategyConfig, run_strategy
from .surfaces import SurfaceBook
from .voldata import PRODUCT_TAIL, VolData

__all__ = [
    "expand_grid",
    "run_grid",
    "pool_products",
    "run_pooled_grid",
    "shuffled_signal_placebo",
    "mismatched_pair_placebo",
    "cost_ladder",
    "deflate_grid",
]


def expand_grid(base: StrategyConfig, **axes) -> list[StrategyConfig]:
    """Cartesian product of the named axes, applied on top of ``base``."""
    if not axes:
        return [base]
    keys = list(axes)
    out = []
    for combo in itertools.product(*(axes[k] for k in keys)):
        out.append(replace(base, **dict(zip(keys, combo))))
    return out


def run_grid(vd: VolData, configs: list[StrategyConfig], book: SurfaceBook | None = None,
             keep_results: bool = False) -> tuple[pd.DataFrame, dict[str, BacktestResult]]:
    """Run every configuration. Returns (summary frame, optional per-key results)."""
    book = book or SurfaceBook(vd)
    rows, kept = [], {}
    for cfg in configs:
        try:
            res = run_strategy(vd, cfg, book)
        except Exception as exc:  # a broken cell must not silently vanish from the count
            rows.append({"key": cfg.key(), "product": cfg.product, "error": repr(exc)})
            continue
        s = summarize(res.daily, res.trades)
        s.update(
            key=cfg.key(), product=cfg.product, expiry_label=cfg.expiry_label,
            tail=cfg.resolved_tail(), offset_bps=cfg.offset_bps, z_window=cfg.z_window,
            entry_z=cfg.entry_z, exit_z=cfg.exit_z, max_hold_days=cfg.max_hold_days,
            rehedge_days=cfg.rehedge_days, cost_mult=cfg.cost_mult,
            signal_on=cfg.signal_on, min_tte_days=cfg.min_tte_days,
            require_on_support=cfg.require_on_support,
        )
        rows.append(s)
        if keep_results:
            kept[cfg.key()] = res
    return pd.DataFrame(rows), kept


def pool_products(vd: VolData, base: StrategyConfig, products=DEFAULT_UNIVERSE,
                  book: SurfaceBook | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run one parameter set across products and sum the daily P&L (equal vega each).

    Pooling is the only route to usable power here: a single product yields ~20 trades over the
    sample. Equal vega per product, not equal notional -- the legs are being compared in vol space.
    """
    book = book or SurfaceBook(vd)
    dailies, trades, diags = [], [], {}
    for p in products:
        cfg = replace(base, product=p, tail=PRODUCT_TAIL[p])
        res = run_strategy(vd, cfg, book)
        if res.daily.empty:
            continue
        d = res.daily[["pnl_volbp", "in_pos", "cost", "gross_pnl"]].copy()
        d.columns = [f"{c}_{p}" for c in d.columns]
        dailies.append(d)
        if not res.trades.empty:
            t = res.trades.copy()
            t["product"] = p
            trades.append(t)
        diags[p] = res.diagnostics
    if not dailies:
        return pd.DataFrame(), pd.DataFrame(), diags
    wide = pd.concat(dailies, axis=1).sort_index()
    pnl_cols = [c for c in wide.columns if c.startswith("pnl_volbp_")]
    pos_cols = [c for c in wide.columns if c.startswith("in_pos_")]
    out = pd.DataFrame(index=wide.index)
    out["pnl_volbp"] = wide[pnl_cols].fillna(0.0).sum(axis=1)
    out["in_pos"] = wide[pos_cols].fillna(0.0).sum(axis=1)
    out["cost"] = wide[[c for c in wide.columns if c.startswith("cost_")]].fillna(0.0).sum(axis=1)
    out["gross_pnl"] = wide[[c for c in wide.columns if c.startswith("gross_pnl_")]].fillna(0.0).sum(axis=1)
    out["equity_volbp"] = out["pnl_volbp"].cumsum()
    all_trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    return out, all_trades, diags


def run_pooled_grid(vd: VolData, configs: list[StrategyConfig], products=DEFAULT_UNIVERSE,
                    book: SurfaceBook | None = None, keep: bool = False):
    """Grid over parameters, each cell pooled across the product universe."""
    book = book or SurfaceBook(vd)
    rows, kept = [], {}
    for cfg in configs:
        daily, trades, diags = pool_products(vd, cfg, products, book)
        if daily.empty:
            continue
        s = summarize(daily, trades)
        s.update(
            key=cfg.key(), expiry_label=cfg.expiry_label, offset_bps=cfg.offset_bps,
            z_window=cfg.z_window, entry_z=cfg.entry_z, exit_z=cfg.exit_z,
            max_hold_days=cfg.max_hold_days, rehedge_days=cfg.rehedge_days,
            cost_mult=cfg.cost_mult, signal_on=cfg.signal_on, min_tte_days=cfg.min_tte_days,
            require_on_support=cfg.require_on_support, n_products=len(products),
        )
        rows.append(s)
        if keep:
            kept[cfg.key()] = (daily, trades, diags)
    return pd.DataFrame(rows), kept


def deflate_grid(grid: pd.DataFrame, daily: pd.Series, sharpe_col: str = "sharpe") -> dict:
    """Deflated Sharpe for one cell, using the grid's own cross-sectional Sharpe dispersion."""
    srs = pd.to_numeric(grid[sharpe_col], errors="coerce").dropna()
    n_trials = int(srs.size)
    var = float(srs.var(ddof=1)) if srs.size > 1 else 0.0
    return {
        "n_trials": n_trials,
        "sr_variance": var,
        "expected_max_sharpe": expected_max_sharpe(n_trials, var),
        "dsr": deflated_sharpe(daily, n_trials, var),
        "best_sharpe": float(srs.max()) if srs.size else np.nan,
    }


# --------------------------------------------------------------------------- controls


def shuffled_signal_placebo(vd: VolData, cfg: StrategyConfig, products=DEFAULT_UNIVERSE,
                            n_draws: int = 200, seed: int = 20260813,
                            book: SurfaceBook | None = None) -> pd.DataFrame:
    """Keep the trades, randomise the direction.

    Signs are drawn once into a fixed-shape array and consumed positionally, so the result is
    reproducible from the seed alone.
    """
    book = book or SurfaceBook(vd)
    daily, trades, _ = pool_products(vd, cfg, products, book)
    if trades.empty:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    n = len(trades)
    signs = rng.choice([-1.0, 1.0], size=(n_draws, n))
    base = trades["pnl_volbp"].to_numpy(float) * trades["side"].to_numpy(float)
    # base is the P&L a LONG-swaption position would have made; re-sign it per draw
    rows = []
    for k in range(n_draws):
        pnl = base * signs[k]
        rows.append({"draw": k, "total_volbp": float(pnl.sum()), "mean_volbp": float(pnl.mean()),
                     "hit": float((pnl > 0).mean())})
    out = pd.DataFrame(rows)
    out.attrs["actual_total"] = float(trades["pnl_volbp"].sum())
    out.attrs["actual_mean"] = float(trades["pnl_volbp"].mean())
    return out


def mismatched_pair_placebo(vd: VolData, cfg: StrategyConfig, wrong_tail: str = "2Y",
                            products=("US", "UL"), book: SurfaceBook | None = None) -> pd.DataFrame:
    """Pair the long-end futures option against a deliberately wrong (short) swaption tail."""
    book = book or SurfaceBook(vd)
    rows = []
    for p in products:
        for tail, label in ((PRODUCT_TAIL.get(p), "matched"), (wrong_tail, "mismatched")):
            if tail is None:
                continue
            res = run_strategy(vd, replace(cfg, product=p, tail=tail), book)
            s = summarize(res.daily, res.trades)
            s.update(product=p, tail=tail, pairing=label)
            rows.append(s)
    return pd.DataFrame(rows)


def cost_ladder(vd: VolData, cfg: StrategyConfig, mults=(0.0, 0.5, 1.0, 2.0, 3.0),
                products=DEFAULT_UNIVERSE, book: SurfaceBook | None = None) -> pd.DataFrame:
    """Re-run the pooled strategy at several cost multiples. Death at 2x means it was never alive."""
    book = book or SurfaceBook(vd)
    rows = []
    for m in mults:
        daily, trades, _ = pool_products(vd, replace(cfg, cost_mult=m), products, book)
        if daily.empty:
            continue
        s = summarize(daily, trades)
        s["cost_mult"] = m
        rows.append(s)
    return pd.DataFrame(rows)
