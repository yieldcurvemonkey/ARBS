"""Run the cross-currency basis book, and check it against the archive's own numbers.

Two entry points, deliberately separate:

* :func:`run_panel_backtest` is the **tie-out**. It reproduces the archive's own arithmetic in
  return space — signal, no-trade band, P&L — with no engine involved, so it can be compared
  directly against the reference numbers recovered from the archive.
* :func:`run_qdb_backtest` is the **engine run**. The same signals and the same allocator, but
  every position resolved, marked and unwound by ``QueryDrivenBacktest``.

Keeping both is the point: the first says the port is faithful, the second says it is executable,
and a discrepancy between them is information rather than a bug to be hidden.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.xccy_rv.config import XccyConfig
from BT.xccy_rv.data import XccyPanel
from BT.xccy_rv.product import XccyPanelMDP
from BT.xccy_rv.signals import build_signals, combine_alpha
from BT.xccy_rv.strategy import XccyAllocator, build_xccy_trigger

logger = logging.getLogger(__name__)

__all__ = ["PanelResult", "QDBResult", "run_panel_backtest", "run_qdb_backtest", "information_ratio"]


def information_ratio(pnl: pd.Series) -> float:
    p = pnl.dropna()
    sd = p.std(ddof=1) * np.sqrt(252.0)
    return float(p.mean() * 252.0 / sd) if sd > 0 else float("nan")


@dataclass
class PanelResult:
    gross: pd.Series
    net: pd.Series
    turnover: pd.Series
    holdings: pd.DataFrame
    alpha: pd.DataFrame

    def summary(self) -> Dict[str, float]:
        g, n = self.gross.dropna(), self.net.dropna()
        return {
            "days": int(len(g)),
            "start": str(g.index.min().date()) if len(g) else "",
            "end": str(g.index.max().date()) if len(g) else "",
            "ir_gross": information_ratio(g),
            "ir_net": information_ratio(n),
            "ann_gross_bp": float(g.mean() * 252 * 1e4),
            "ann_net_bp": float(n.mean() * 252 * 1e4),
            "ann_vol_bp": float(g.std(ddof=1) * np.sqrt(252) * 1e4),
            "mean_turnover": float(self.turnover.mean()),
            "breakeven_cost_bp": float(g.sum() / self.turnover.sum() * 1e4)
            if self.turnover.sum() > 0
            else float("nan"),
        }

    def by_era(self, eras: Optional[List[tuple]] = None) -> pd.DataFrame:
        eras = eras or [
            ("2007-2009", "2007-01-01", "2009-12-31"),
            ("2010-2012", "2010-01-01", "2012-12-31"),
            ("2013-2015", "2013-01-01", "2015-12-31"),
        ]
        rows = []
        for name, lo, hi in eras:
            m = (self.gross.index >= lo) & (self.gross.index <= hi)
            if m.sum() < 60:
                continue
            rows.append(
                {
                    "era": name,
                    "days": int(m.sum()),
                    "ir_gross": information_ratio(self.gross[m]),
                    "ir_net": information_ratio(self.net[m]),
                    "ann_gross_bp": float(self.gross[m].mean() * 252 * 1e4),
                }
            )
        return pd.DataFrame(rows).set_index("era") if rows else pd.DataFrame()


@dataclass
class QDBResult:
    equity: pd.Series
    closed: pd.DataFrame
    allocator: XccyAllocator
    backtest: Any
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def _alpha_and_vol(panel: XccyPanel, cfg: XccyConfig):
    sig = build_signals(panel, cfg.signal)
    alpha = combine_alpha(sig, cfg.signal)
    vol = sig["vol"]
    idx = alpha.dropna(how="all").index
    return alpha.loc[idx], vol.loc[idx], sig


def run_panel_backtest(panel: XccyPanel, cfg: Optional[XccyConfig] = None) -> PanelResult:
    """The archive's own arithmetic, in return space. This is the tie-out."""
    cfg = cfg or XccyConfig()
    alpha, vol, _ = _alpha_and_vol(panel, cfg)
    alloc = XccyAllocator(alpha, vol, cfg)

    rows = {}
    for ts in alpha.index:
        rows[ts] = alloc.targets(ts)
        alloc.holdings = rows[ts]
    H = pd.DataFrame(rows).T.reindex(alpha.index)

    R = panel.returns.reindex(index=H.index, columns=H.columns).fillna(0.0)
    gross = (H.shift(1) * R).sum(axis=1).dropna()
    turnover = H.diff().abs().sum(axis=1).reindex(gross.index).fillna(0.0)
    net = gross - cfg.optimizer.transaction_costs * turnover
    return PanelResult(gross=gross, net=net, turnover=turnover, holdings=H, alpha=alpha)


def run_qdb_backtest(
    panel: XccyPanel,
    cfg: Optional[XccyConfig] = None,
    *,
    show_progress: bool = True,
    strict: bool = True,
) -> QDBResult:
    """The same book, executed by ``QueryDrivenBacktest``."""
    cfg = cfg or XccyConfig()
    alpha, vol, _ = _alpha_and_vol(panel, cfg)

    alloc = XccyAllocator(alpha, vol, cfg, carry=panel.carry().reindex_like(alpha))
    mdp = XccyPanelMDP(panel.fwd_basis)
    strategy = QueryStrategy(name=cfg.name, triggers=[build_xccy_trigger(alloc)])

    grid = [pd.Timestamp(d) for d in alpha.index]
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(grid),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
        progress_desc="XCCY RV BACKTEST",
    )
    t0 = time.time()
    bt.run()
    elapsed = time.time() - t0

    equity = pd.Series(bt.mtm_history).sort_index()
    equity.index = pd.to_datetime(equity.index)
    closed = pd.DataFrame(bt.portfolio.closed_positions_log or [])

    holes = sorted(set(grid) - set(equity.index))
    diagnostics = {
        "elapsed_s": round(elapsed, 1),
        "grid_days": len(grid),
        "marked_days": int(len(equity)),
        "equity_holes": len(holes),
        "nonzero_marks": int((equity.abs() > 1e-9).sum()),
        "rebalances": len(alloc.log),
        "closed_positions": int(len(closed)),
        "instruments": len(alpha.columns),
    }
    logger.info("xccy QDB diagnostics: %s", diagnostics)

    def _check(ok: bool, msg: str) -> None:
        if ok:
            return
        if strict:
            raise AssertionError(msg)
        logger.warning("xccy backtest check failed (strict=False): %s", msg)

    _check(len(alloc.log) > 0, "the allocator never traded — no order was ever emitted")
    _check(diagnostics["nonzero_marks"] > 0, "engine equity is identically zero")
    _check(
        len(holes) <= max(2, int(0.01 * len(grid))),
        f"{len(holes)} of {len(grid)} grid days produced no mark — run() swallows per-step errors",
    )

    return QDBResult(equity=equity, closed=closed, allocator=alloc, backtest=bt, diagnostics=diagnostics)
