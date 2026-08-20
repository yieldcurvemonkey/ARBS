"""Smoke the QueryDrivenBacktest bridge on a small slice before the notebook needs it."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from BT.signals import etf_rebalance as QDB  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

pd.set_option("display.width", 200)

N_TRADES = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def main() -> int:
    panel = FP.asof_join(BP.load(), FP.load())
    joined = HP.build(["TLT"], panel=panel)
    # price_basis="eod" for the comparison ONLY. The QDB prices through
    # FixedRateBondsMDP, which solves its yields off FedInvest's eod_price, while the
    # panel prices off the mid of the two-sided quote. Those are a genuine basis
    # difference (measured: eod reaches +-20 spread widths from the mid at the 1st/99th
    # percentiles) and a butterfly AMPLIFIES it, because three near-identical legs cancel
    # the level and leave the basis. Comparing mid-marks against eod-marks measures that
    # basis, not the two marking models -- on the SVB week of March 2023 it showed up as
    # a 13x daily disagreement. Put both sides on eod and the comparison is about the
    # thing it claims to be about.
    cfg = EN.merge_config({"fund": "TLT", "universe": {"start": "2023-01-01"},
                           "price_basis": "eod",
                           "timing": {"hold_days": 10, "entry_every": 21}})
    uni, funnel = EN.prepare_universe(cfg, joined=joined, panel=panel)
    res = EN.run_config(cfg, universe=uni, prepared_funnel=funnel, keep_segments=True)
    print(f"fast engine: {len(res.closed)} trades")

    sub = res.closed.sort_values("opened_at").head(N_TRADES)
    legs = res.legs[res.legs.trade_id.isin(sub.trade_id)]
    dates = res.daily.loc[(res.daily["date"] >= sub["opened_at"].min())
                          & (res.daily["date"] <= sub["closed_at"].max()), "date"]
    print(f"QDB slice: {len(sub)} packages, {len(legs)} legs, {len(dates)} marking days")

    t0 = time.time()
    # charge_fee=False: the fast segment curve is GROSS, so the QDB must be too.
    out = QDB.run_qdb(sub, legs, dates=dates, charge_fee=False, show_progress=True,
                      name="smoke")
    print(f"QDB ran in {(time.time() - t0)/60:.1f} min, holes {out['holes']}")

    # Like for like: the fast curve for THESE trades only, not the whole book's.
    fast = QDB.fast_daily_for(res.segments, sub["trade_id"], dates)
    j = QDB.tie_out(fast, out["daily"])
    rep = QDB.tie_out_report(j)
    print("\n" + pd.Series(rep).to_frame("fast vs QDB").round(4).to_string())

    print("\nlast 8 days of both curves:")
    print(j.tail(8).round(4).to_string())

    ok = [
        # The two marking models decompose the same total differently -- the QDB books
        # coupon cash and dirty NPV, the fast engine one yield-space carry term -- so the
        # LEVEL is the testable claim and the path is not. Measured: daily-change
        # correlation ~0.45 with identical price inputs and both packages DV01-neutral to
        # 1e-16, so the residual is the decomposition and nothing else.
        ("levels agree to under 1bp", abs(rep["end_gap_bp"]) < 1.0,
         f"{rep['end_gap_bp']:+.4f} bp"),
        ("daily changes are positively related", (rep["daily_change_corr"] or 0) > 0.3,
         f"corr {rep['daily_change_corr']:.4f} (path is NOT expected to match)"),
        ("QDB produced a curve", len(out["equity"]) > 10, f"{len(out['equity'])} marks"),
        ("QDB booked the packages", len(out["closed_log"]) > 0,
         f"{len(out['closed_log'])} closed legs"),
        ("no marking holes", out["holes"] == 0, str(out["holes"])),
        ("QDB P&L is not identically zero", abs(float(out["equity"].iloc[-1])) > 1e-9,
         f"{float(out['equity'].iloc[-1]):+.4f} bp"),
    ]
    print()
    for nm, good, v in ok:
        print(f"  [{'PASS' if good else 'FAIL'}] {nm:36s} {v}")
    return 0 if all(g for _, g, _ in ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
