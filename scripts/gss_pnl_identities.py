"""Measure the P&L identities instead of reasoning about them.

Two rounds of reading the engine produced two confident stories about the gap between the equity
curve and the sum of closed-trade P&L, and the reconciliation assertion refuted both. So stop
reasoning and print the quantities.

The identities that SHOULD hold, and which this checks one by one:

    A. bt.realized_pnl            == sum(closed["realized_pnl"]) + carry realised during holds
    B. equity[-1]                 == bt.realized_pnl + (open positions' mark)
    C. handler bond_total + financing_total == equity[-1]     (the handler's own view)

Whichever fails is the one whose definition is not what it looks like. `on_unwind` returns
`bond_delta + financing_realized` where `bond_delta = cf + gross_mtm`
(Query/FixedRateBonds/position_handler.py:496-501) AND records those same amounts into the
component ledgers, so the closed log and the ledgers overlap rather than partitioning the P&L.

    conda run -n stir python scripts/gss_pnl_identities.py
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.ERROR)

from BT.gss_fly import GSSConfig, build_curve_panel  # noqa: E402
from BT.gss_fly.backtest import run_gss_backtest  # noqa: E402
from BT.gss_fly.data import ust_business_days  # noqa: E402
from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP  # noqa: E402


def main() -> int:
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    days = ust_business_days("2024-09-02", "2026-01-02")
    panel = build_curve_panel(days, mdp, cache_path=Path("notebooks/data/gss_fly/panel_cached"),
                              show_progress=False)
    print(f"ID: {panel.summary()}", flush=True)

    res = run_gss_backtest(panel, mdp, cfg=GSSConfig(), show_progress=False, strict=False)
    bt = res.backtest
    eq = res.equity.dropna()
    closed = res.closed

    realized_engine = float(getattr(bt, "realized_pnl", np.nan))
    closed_sum = float(closed["realized_pnl"].astype(float).sum()) if len(closed) else 0.0
    fees = float(closed["fee_allocated"].astype(float).sum()) if "fee_allocated" in closed else np.nan
    gross_sum = float(closed["gross_realized_pnl"].astype(float).sum()) if "gross_realized_pnl" in closed else np.nan

    hist = getattr(bt, "frb_component_histories", None) or {}

    def last(k):
        h = hist.get(k) or {}
        return float(pd.Series(h).sort_index().iloc[-1]) if h else np.nan

    print("ID: --- raw quantities ---", flush=True)
    print(f"ID: equity[-1]                 = {eq.iloc[-1]:>18,.2f}", flush=True)
    print(f"ID: equity[0]                  = {eq.iloc[0]:>18,.2f}", flush=True)
    print(f"ID: bt.realized_pnl (final)    = {realized_engine:>18,.2f}", flush=True)
    print(f"ID: sum closed.realized_pnl    = {closed_sum:>18,.2f}   n={len(closed)}", flush=True)
    print(f"ID: sum closed.gross_realized  = {gross_sum:>18,.2f}", flush=True)
    print(f"ID: sum closed.fee_allocated   = {fees:>18,.2f}", flush=True)
    for k in ("bond_realized", "financing_realized", "bond_open_mtm", "bond_total",
              "financing_total", "net_total"):
        print(f"ID: ledger {k:<20} = {last(k):>18,.2f}", flush=True)

    open_positions = list(getattr(bt.portfolio, "positions", []) or [])
    print(f"ID: still-open positions       = {len(open_positions)}", flush=True)

    print("ID: --- identities ---", flush=True)
    print(f"ID: A  realized_engine - closed_sum        = {realized_engine - closed_sum:>18,.2f}"
          "   (should be the carry realised during holds)", flush=True)
    print(f"ID: B  equity[-1] - realized_engine        = {eq.iloc[-1] - realized_engine:>18,.2f}"
          "   (should be the open-position mark)", flush=True)
    print(f"ID: B' ledger bond_open_mtm                = {last('bond_open_mtm'):>18,.2f}", flush=True)
    print(f"ID: C  ledger net_total - equity[-1]       = {last('net_total') - eq.iloc[-1]:>18,.2f}"
          "   (should be 0 if the handler's view agrees)", flush=True)

    # Does the equity curve's own increments reconcile to its endpoint? (sanity on the series)
    print(f"ID: D  equity[-1] - equity[0] - sum(diff)  = "
          f"{eq.iloc[-1] - eq.iloc[0] - eq.diff().dropna().sum():>18,.2e}", flush=True)

    # The realized history is cumulative; its last value should equal bt.realized_pnl
    rh = pd.Series(getattr(bt, "realized_pnl_history", {}) or {}, dtype=float).sort_index()
    if len(rh):
        print(f"ID: E  realized_pnl_history[-1]            = {rh.iloc[-1]:>18,.2f}", flush=True)
        print(f"ID:    equity[-1] - realized_history[-1]   = {eq.iloc[-1] - rh.iloc[-1]:>18,.2f}", flush=True)

    print("ID: --- closed log columns ---", flush=True)
    print("ID: " + ", ".join(map(str, closed.columns)), flush=True)
    if len(closed):
        cols = [c for c in ("closed_at", "realized_pnl", "gross_realized_pnl", "fee_allocated",
                            "holding_period_days") if c in closed.columns]
        print(closed[cols].head(10).to_string(), flush=True)
        print(f"ID: realized_pnl describe:\n{closed['realized_pnl'].astype(float).describe()}", flush=True)
    print("IDDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
