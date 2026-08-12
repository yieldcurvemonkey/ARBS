"""Run the GSS butterfly book on ``QueryDrivenBacktest``.

The assertions in :func:`run_gss_backtest` are not decoration. ``QueryDrivenBacktest.run()``
catches every per-step exception and prints it, so a book whose triggers never fire, or whose
pricing fails on half the grid, produces a clean flat equity curve and no error. A handsome
equity curve from a book that never traded is *more* persuasive than a messy one, not less —
so the run refuses to return until it has shown otherwise.
"""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from BT.data_handler import TimeGrid
from BT.gss_fly.config import GSSConfig
from BT.gss_fly.costs import RepoCurve
from BT.gss_fly.data import CurvePanel
from BT.gss_fly.signals import build_bond_signals
from BT.gss_fly.strategy import GSSSignalEngine, build_gss_trigger
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy

logger = logging.getLogger(__name__)

__all__ = ["GSSResult", "run_gss_backtest", "summarize"]


@dataclass
class GSSResult:
    equity: pd.Series
    closed: pd.DataFrame
    trade_log: pd.DataFrame
    backtest: Any
    engine: GSSSignalEngine
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> Dict[str, float]:
        return summarize(self)


def summarize(res: "GSSResult") -> Dict[str, float]:
    eq = res.equity.dropna()
    daily = eq.diff().dropna()
    out: Dict[str, float] = {
        "marked_days": int(len(eq)),
        "end_equity_usd": float(eq.iloc[-1]) if len(eq) else np.nan,
        "closed_trades": int(len(res.closed)),
    }
    if len(daily) > 5 and daily.std(ddof=1) > 0:
        out["daily_sharpe_ann"] = float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
    cum = eq - eq.cummax()
    out["max_dd_usd"] = float(cum.min()) if len(cum) else np.nan
    if not res.closed.empty and "realized_pnl" in res.closed.columns:
        p = res.closed["realized_pnl"].astype(float)
        out.update(
            {
                "net_realized_usd": float(p.sum()),
                "avg_per_trade_usd": float(p.mean()),
                "hit_rate": float((p > 0).mean()),
                "median_hold_days": float(res.closed["holding_period_days"].median())
                if "holding_period_days" in res.closed.columns
                else np.nan,
            }
        )
        if len(p) > 2 and p.std(ddof=1) > 0:
            out["t_stat"] = float(p.mean() / (p.std(ddof=1) / np.sqrt(len(p))))
    return out


def run_gss_backtest(
    panel: CurvePanel,
    mdp,
    *,
    cfg: Optional[GSSConfig] = None,
    dates: Optional[Sequence] = None,
    repo_curve: Optional[RepoCurve] = None,
    repo_tenor: str = "ON",
    leg_specialness_bps: Optional[Dict[str, float]] = None,
    show_progress: bool = True,
    strict: bool = True,
) -> GSSResult:
    """Fit the signals, wire the trigger, run the engine, and prove it actually traded.

    ``strict=False`` downgrades the assertions to warnings — useful when deliberately running a
    configuration expected to trade rarely, and dangerous otherwise.
    """
    cfg = cfg or GSSConfig()

    sig = build_bond_signals(panel.s2c, cfg.signal)
    engine = GSSSignalEngine(panel, sig["signal"], cfg, repo_curve=repo_curve, repo_tenor=repo_tenor)

    gc_rate = None
    if repo_curve is not None:
        col = repo_tenor.upper()
        if col in repo_curve.frame.columns:
            gc_rate = repo_curve.frame[col].dropna()

    trigger = build_gss_trigger(engine, gc_rate=gc_rate, leg_specialness_bps=leg_specialness_bps)

    grid_dates = [pd.Timestamp(d) for d in (dates if dates is not None else panel.dates)]
    grid_dates = sorted(set(grid_dates))
    if len(grid_dates) < 10:
        raise ValueError(f"time grid has {len(grid_dates)} steps — nothing to backtest")

    strategy = QueryStrategy(name=cfg.name, triggers=[trigger])
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid_dates),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
        progress_desc="GSS FLY BACKTEST",
    )

    t0 = time.time()
    bt.run()
    elapsed = time.time() - t0

    equity = pd.Series(bt.mtm_history).sort_index()
    equity.index = pd.to_datetime(equity.index)
    closed = pd.DataFrame(bt.portfolio.closed_positions_log or [])
    trade_log = pd.DataFrame(engine.log)

    holes = sorted(set(grid_dates) - set(equity.index))
    n_nonzero = int((equity.abs() > 1e-9).sum())
    n_entries = int((trade_log["event"] == "ENTER").sum()) if not trade_log.empty else 0
    n_exits = int((trade_log["event"] == "EXIT").sum()) if not trade_log.empty else 0

    diagnostics = {
        "elapsed_s": round(elapsed, 1),
        "grid_days": len(grid_dates),
        "marked_days": int(len(equity)),
        "equity_holes": len(holes),
        "first_holes": [str(h.date()) for h in holes[:5]],
        "nonzero_marks": n_nonzero,
        "signal_entries": n_entries,
        "signal_exits": n_exits,
        "closed_positions": int(len(closed)),
        "still_open": len(engine.open),
        "median_rmse_bp": float(panel.rmse.median()),
    }
    logger.info("GSS backtest diagnostics: %s", diagnostics)

    def _check(ok: bool, msg: str) -> None:
        if ok:
            return
        if strict:
            raise AssertionError(msg)
        logger.warning("GSS backtest check failed (strict=False): %s", msg)

    _check(n_entries > 0, "the signal never fired an entry — the book did not trade")
    _check(n_nonzero > 0, "engine equity is identically zero — no position was ever marked")
    _check(
        len(holes) <= max(2, int(0.01 * len(grid_dates))),
        f"{len(holes)} of {len(grid_dates)} grid days produced no mark "
        f"(QueryDrivenBacktest.run swallows per-step exceptions) — first {diagnostics['first_holes']}",
    )
    _check(
        len(closed) >= n_exits,
        f"engine closed {len(closed)} positions but the signal emitted {n_exits} exits",
    )

    return GSSResult(
        equity=equity,
        closed=closed,
        trade_log=trade_log,
        backtest=bt,
        engine=engine,
        diagnostics=diagnostics,
    )
