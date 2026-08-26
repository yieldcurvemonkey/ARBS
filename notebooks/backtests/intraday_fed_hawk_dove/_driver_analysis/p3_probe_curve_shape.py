"""Probe 3: when does the USD-SOFR-1D curve acquire REAL term structure?

Probe 2 turned up something that has to be settled before any panel is built: in
January 2019 ``IMM_3xIMM_4`` sat within 0.7 bp of the overnight rate on every
day, and the two moved 1-for-1. A ~9-12 month forward 3m rate pinned to the ON
fixing with a constant offset is a FLAT curve, i.e. a curve that carries no
forward information at all -- exactly the identity-curve failure mode this repo
has hit before. If that persists through 2019-2020 then d_rate_bp over those
years is overnight-fixing noise wearing the label of a forward rate.

Sampled monthly, with 2y and 5y alongside so the shape is visible.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append(r"C:\Users\chris\clee\ARBS")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

CURVE = "USD-SOFR-1D"
OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis"


def main() -> None:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False)
    qs = [
        UnifiedQuery(curve=CURVE, tenor="IMM_3xIMM_4", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve=CURVE, tenor="1d", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve=CURVE, tenor="2y", value=UnifiedValue.IRS_RATE),
        UnifiedQuery(curve=CURVE, tenor="5y", value=UnifiedValue.IRS_RATE),
    ]

    frames = []
    for y in range(2019, 2027):
        # first ten calendar days of Feb / Jun / Oct -- three probes a year is
        # enough to locate a regime boundary to the month.
        for m in (2, 6, 10):
            a = dt.date(y, m, 1)
            b = dt.date(y, m, 10)
            if a > dt.date(2026, 8, 24):
                continue
            try:
                df = TimeseriesBuilder().get_timeseries(
                    start=a, end=b, queries=qs, n_jobs=4, routers={"IRS": tb})
                if df is None or df.empty:
                    print(f"{y}-{m:02d}: EMPTY")
                    continue
                df.index = pd.to_datetime(df.index)
                frames.append(df)
                print(f"{y}-{m:02d}: {df.shape[0]} rows")
            except Exception as exc:  # noqa: BLE001
                print(f"{y}-{m:02d}: FAILED {type(exc).__name__}: {exc}")

    tb.close()
    if not frames:
        print("nothing fetched")
        return

    all_df = pd.concat(frames).sort_index()
    all_df = all_df[~all_df.index.duplicated(keep="last")]
    c_imm = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE"
    c_on = f"{CURVE} 1d OUTRIGHT RATE"
    c_2y = f"{CURVE} 2y OUTRIGHT RATE"
    c_5y = f"{CURVE} 5y OUTRIGHT RATE"

    all_df["imm_minus_on_bp"] = (all_df[c_imm] - all_df[c_on]) * 100
    all_df["2y_minus_on_bp"] = (all_df[c_2y] - all_df[c_on]) * 100
    all_df["5y_minus_2y_bp"] = (all_df[c_5y] - all_df[c_2y]) * 100
    all_df.to_csv(os.path.join(OUT, "p3_curve_shape.csv"))

    print("\n=== spreads to the ON rate, bp -- by year ===")
    g = all_df.groupby(all_df.index.year)[
        ["imm_minus_on_bp", "2y_minus_on_bp", "5y_minus_2y_bp"]]
    print(g.agg(["count", "mean", "std", "min", "max"]).round(2).to_string())

    print("\n=== a FLAT curve shows as a near-constant imm_minus_on_bp ===")
    print("per-year std of (IMM_3xIMM_4 - ON), bp -- near 0 means degenerate:")
    print(all_df.groupby(all_df.index.year)["imm_minus_on_bp"].std().round(3).to_string())

    print("\n=== daily rows, first 40 ===")
    cols = [c_on, c_imm, c_2y, c_5y, "imm_minus_on_bp"]
    print(all_df[cols].head(40).round(4).to_string())
    print("\n=== daily rows, last 20 ===")
    print(all_df[cols].tail(20).round(4).to_string())


if __name__ == "__main__":
    main()
