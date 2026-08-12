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
from BT.gss_fly.strategy import GSSSignalEngine, build_gss_trigger, scan_candidates
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
    """Summary metrics, with the book-level view and the per-trade view kept apart.

    ``equity`` is the number that means "what the book made". The engine's ``mtm_history`` is
    **cumulative total P&L** — ``mark_to_market`` seeds it with ``self.realized_pnl`` and adds the
    open positions' marks (``BT/query_engine.py:278``), and the financed-bond handler marks each
    position net of its entry NPV (``Query/FixedRateBonds/position_handler.py:431``) — so Sharpe
    and drawdown are computed from it.

    Everything named ``*_per_trade`` is the **trade ledger** view: it answers "what did the average
    trade do", not "what did the strategy return". The two are not interchangeable and are never
    given the same name here, because the first version of this function reported the ledger sum as
    ``net_realized_usd`` and it was read — by me — as the strategy's P&L. It is not: it is already
    net of fees, already contains the carry realised at unwind, and for this book it came to
    +$7.9m against a book that made +$431k.

    :func:`_pnl_components` supplies the disjoint decomposition and asserts that it sums to the
    equity curve.
    """
    eq = res.equity.dropna()
    daily = eq.diff().dropna()
    out: Dict[str, float] = {
        "marked_days": int(len(eq)),
        # cumulative total P&L: bond + financing - fees + open mark
        "end_equity_usd": float(eq.iloc[-1]) if len(eq) else np.nan,
        "closed_trades": int(len(res.closed)),
    }
    if len(daily) > 5 and daily.std(ddof=1) > 0:
        out["daily_sharpe_ann"] = float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
    cum = eq - eq.cummax()
    out["max_dd_usd"] = float(cum.min()) if len(cum) else np.nan

    out.update(_pnl_components(res))

    if not res.closed.empty and "realized_pnl" in res.closed.columns:
        p = res.closed["realized_pnl"].astype(float)
        out.update(
            {
                # A DIFFERENT CUT, not a component: already net of fees and already containing
                # the carry realised at unwind, so it must never be added to the ledgers above.
                "per_trade_pnl_usd": float(p.sum()),
                "avg_per_trade_usd": float(p.mean()),
                "hit_rate_per_trade": float((p > 0).mean()),
                "median_hold_days": float(res.closed["holding_period_days"].median())
                if "holding_period_days" in res.closed.columns
                else np.nan,
            }
        )
        if len(p) > 2 and p.std(ddof=1) > 0:
            # tests whether the mean TRADE differs from zero; not a strategy Sharpe
            out["t_stat_per_trade"] = float(p.mean() / (p.std(ddof=1) / np.sqrt(len(p))))
    return out


def _pnl_components(res: "GSSResult") -> Dict[str, float]:
    """The book's P&L as four **disjoint** parts that sum to the equity curve.

    The identity, derived from the engine and then checked against two variants that differ only
    in their fee::

        equity[-1] == bond_total + financing_total - fees + open_mark

    ``FinancedFixedRateBondHandler`` keeps running totals on the backtest object as
    ``frb_component_histories`` (``Query/FixedRateBonds/position_handler.py:236-262``).
    ``bond_total`` is coupons **plus** the price convergence booked at unwind, because
    ``on_unwind`` records ``bond_delta = cf + gross_mtm`` into that ledger *and* returns it to the
    engine (``position_handler.py:496-501``). Financing is the same shape.

    That overlap is why the first attempt at this did not reconcile. ``sum(closed["realized_pnl"])``
    is **not** a component: it is a different cut of the same money — the per-trade view, already
    net of fees and already containing the carry realised at unwind. Adding it alongside the
    ledgers double-counted every unwind, by $10.7m on the first GSS run. It is still reported,
    because the per-trade view is what a trade-level statistic needs, but it is named
    ``per_trade_pnl_usd`` and kept out of the sum.

    ``reconciliation_gap_usd`` asserts the identity rather than asking to be believed. It was worth
    adding: it refuted two successive and confident explanations of this book's P&L, including one
    that had already been reported.
    """
    out: Dict[str, float] = {}
    hist = getattr(res.backtest, "frb_component_histories", None)
    if not hist:
        return out

    eq_all = res.equity.dropna()
    last_ts = pd.Timestamp(eq_all.index[-1]) if len(eq_all) else None

    def _last_cumulative(key: str) -> float:
        """For a RUNNING TOTAL, the final recorded value is the total — carry it forward."""
        h = hist.get(key) or {}
        if not h:
            return 0.0
        return float(pd.Series(h).sort_index().iloc[-1])

    def _at(key: str, when) -> float:
        """For a PER-DATE value, read that date and treat absence as zero.

        `bond_open_mtm` is the sum of the open positions' marks ON a date, not a running total.
        Reading "the last entry present" instead returns a stale mark from whenever the book last
        held something — so a config that ends FLAT was credited with an open position it no
        longer had. Caught by the reconciliation guard at $181,386 on the sweep; the incumbent
        never showed it because the incumbent ends with one position still open.
        """
        h = hist.get(key) or {}
        if not h or when is None:
            return 0.0
        s = pd.Series(h)
        s.index = pd.to_datetime(s.index)
        val = s.reindex([when]).iloc[0]
        return 0.0 if pd.isna(val) else float(val)

    bond = _last_cumulative("bond_realized")   # coupons during the hold + everything at unwind
    financing = _last_cumulative("financing_realized")
    open_mtm = _at("bond_open_mtm", last_ts)

    closed = res.closed
    have = lambda c: (not closed.empty) and c in closed.columns  # noqa: E731
    fees = float(closed["fee_allocated"].astype(float).sum()) if have("fee_allocated") else 0.0
    # Everything the unwinds returned, before their fee: cf + price convergence + financing.
    unwind = float(closed["gross_realized_pnl"].astype(float).sum()) if have("gross_realized_pnl") else np.nan

    # Carry accrued while the position was HELD is what is left of the ledgers once the unwind
    # bookings are removed from them. Splitting it out is the point: for this book it is the
    # largest single term and it has the opposite sign to the convergence.
    carry = (bond + financing - unwind) if np.isfinite(unwind) else np.nan

    out["carry_during_hold_usd"] = carry
    out["unwind_proceeds_usd"] = unwind
    out["fees_usd"] = -fees
    out["open_mtm_usd"] = open_mtm
    out["bond_ledger_usd"] = bond
    out["financing_ledger_usd"] = financing

    # Gross from the ENGINE's own endpoint, not from the ledgers: the identity says
    # equity = gross - fees, so gross = equity + fees exactly. `end_equity_usd` comes straight
    # from `mtm_history` and `fees` straight from the closed log, so this survives any defect in
    # the component ledgers — which is worth having, since a ledger defect is precisely what the
    # reconciliation gap below exists to detect, and a cost verdict must not depend on the thing
    # under test.
    gross = float(eq_all.iloc[-1]) + fees if len(eq_all) else np.nan
    out["gross_before_fees_usd"] = gross
    if gross and np.isfinite(gross):
        out["cost_share_of_gross"] = fees / gross
    # m*: the fraction of the CHARGED bid/offer this book can actually pay. >= 1 survives.
    out["breakeven_cost_multiplier"] = (gross / fees) if fees > 0 and np.isfinite(gross) else np.nan

    eq = res.equity.dropna()
    if len(eq):
        # equity == bond_ledger + financing_ledger - fees + open_mark, identically; the finer
        # split above is that same identity with the unwind bookings separated from the carry.
        out["reconciliation_gap_usd"] = float(eq.iloc[-1] - (bond + financing - fees + open_mtm))
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
    candidates=None,
) -> GSSResult:
    """Fit the signals, wire the trigger, run the engine, and prove it actually traded.

    ``strict=False`` downgrades the assertions to warnings — useful when deliberately running a
    configuration expected to trade rarely, and dangerous otherwise.
    """
    cfg = cfg or GSSConfig()

    sig = build_bond_signals(panel.s2c, cfg.signal)
    engine = GSSSignalEngine(panel, sig["signal"], cfg, repo_curve=repo_curve,
                             repo_tenor=repo_tenor, candidates=candidates)

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
