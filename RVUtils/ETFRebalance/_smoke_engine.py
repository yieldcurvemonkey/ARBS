"""End-to-end smoke: does the pipeline produce a book, and does its arithmetic close?"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.ETFHoldings.universe import spec  # noqa: E402
from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import costs as C  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import engine as EN  # noqa: E402
from RVUtils.ETFRebalance import float_panel as FP  # noqa: E402
from RVUtils.ETFRebalance import holdings_panel as HP  # noqa: E402

pd.set_option("display.width", 200)


def main() -> int:
    t0 = time.time()
    panel = FP.asof_join(BP.load(), FP.load())
    print(f"panel {len(panel):,} rows in {time.time() - t0:.1f}s")

    t0 = time.time()
    joined = HP.build(["TLT"], panel=panel)
    print(f"TLT joined: {len(joined):,} rows  {joined['date'].min().date()} .. "
          f"{joined['date'].max().date()}  {joined['date'].nunique():,} dates  "
          f"{joined['cusip'].nunique()} cusips   ({time.time() - t0:.1f}s)")
    print(f"  priced: {joined['priced'].mean() * 100:.2f}%   "
          f"float_stale_days median {joined['float_stale_days'].median():.0f}")

    print("\n--- measured cost, 20-31y, by year ---")
    cs = C.measured_spread_summary(panel[panel.ttm.between(20, 31)], bands=((20, 31),))
    print(cs.round(3).to_string(index=False))

    print("\n--- which outstanding measure explains TLT's published weights? ---")
    dates = sorted(set(pd.to_datetime(joined["date"]).unique()))[::120]
    fit = FP.benchmark_fit(HP.load_holdings(["TLT"]),
                           panel, ticker="TLT", band=(20.0, 31.0), dates=dates)
    if not fit.empty:
        print(fit.groupby("benchmark").agg(
            n=("r2", "size"), r2=("r2", "mean"), slope=("slope", "mean"),
            mae_bp=("mae_weight_bp", "mean"), n_index=("n_index", "mean"),
            n_fund=("n_fund", "mean"), covered=("fund_weight_covered", "mean"),
        ).round(4).to_string())

    t0 = time.time()
    cfg = {"name": "smoke", "fund": "TLT", "universe": {"start": "2016-01-01"}}
    uni, funnel = EN.prepare_universe(EN.merge_config(cfg), joined=joined, panel=panel)
    print(f"\n--- universe funnel ({time.time() - t0:.1f}s) ---")
    print(pd.Series(funnel).to_string())

    print("\n--- residual QC (the check that catches a corrupted panel) ---")
    q = CV.residual_quality(uni)
    print(q.describe(percentiles=[.05, .5, .95]).round(4).to_string())

    t0 = time.time()
    res = EN.run_config(cfg, universe=uni, prepared_funnel=funnel)
    print(f"\n--- run_config ({time.time() - t0:.1f}s) ---")
    print(pd.Series(res.funnel).to_string())
    s = EN.summarize(res)
    print("\n" + pd.Series(s).to_string())

    if not res.closed.empty:
        print("\nfirst 5 trades:")
        print(res.closed.head(5).round(4).to_string(index=False))

        # Arithmetic identity: the daily equity curve must end exactly where the trade
        # log says. They are built by different code paths -- per-day marks against a
        # per-trade close -- so agreeing is evidence, not tautology.
        eq_end = float(res.daily["mtm_bp"].iloc[-1])
        log_sum = float(res.closed["pnl_bp"].sum())
        print(f"\nequity curve end {eq_end:+.4f}bp   trade log sum {log_sum:+.4f}bp   "
              f"gap {eq_end - log_sum:+.6f}bp")
        assert abs(eq_end - log_sum) < 1e-6, "daily marks and the trade log disagree"
        print("IDENTITY OK: daily marks reconcile to the trade log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
