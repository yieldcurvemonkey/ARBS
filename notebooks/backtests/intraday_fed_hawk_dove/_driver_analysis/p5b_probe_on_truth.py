"""Probe 5b: the ON leg against the PUBLISHED SOFR fixing.

rateslib's shipped ``sofr`` file is a -500 placeholder, so the independent series
is the repo's own fixings cache, which is the published fixing history and owes
nothing to the Citi curve build:

    MDP/IRSwaps/fixings_cache/USD-SOFR-1D_fixings/2025-10-02/fixings.csv
    1,875 rows, 2018-04-02..2025-10-01, quoted as a DECIMAL (0.0420 = 4.20%).

Run against 2024-2025 FIRST -- where probe 4 found the ON leg never frozen and it
must therefore agree. A checker that fails its own control is not evidence about
2019.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
FIX = pathlib.Path(r"C:\Users\chris\clee\ARBS\MDP\IRSwaps\fixings_cache"
                   r"\USD-SOFR-1D_fixings\2025-10-02\fixings.csv")
CURVE = "USD-SOFR-1D"
C_ON = f"{CURVE} 1d OUTRIGHT RATE"
C_IMM = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE"


def main() -> None:
    r = pd.read_parquet(OUT / "rates_daily.parquet")
    r.index = pd.to_datetime(r.index)
    r = r.sort_index()

    f = pd.read_csv(FIX)
    f["date"] = pd.to_datetime(f["USD-SOFR-1D"])
    fix = f.set_index("date")["Fixing"].sort_index() * 100.0     # decimal -> percent
    print(f"published SOFR fixings: {len(fix)} rows "
          f"{fix.index.min().date()}..{fix.index.max().date()}  "
          f"range {fix.min():.3f}..{fix.max():.3f} %")
    # known answer on the fixing series itself: SOFR spiked to ~5.25% on
    # 2019-09-17 in the repo squeeze. If that is not there, the file is not SOFR.
    sp = fix.loc["2019-09-15":"2019-09-20"]
    print(f"\nSOFR 2019-09-15..20 (the repo squeeze; the 17th printed ~5.25%):")
    print(sp.round(3).to_string())

    j = pd.DataFrame({"curve_on": r[C_ON], "imm": r[C_IMM]}).join(
        fix.rename("sofr_fix"), how="inner").dropna(subset=["curve_on", "sofr_fix"])
    j["diff_bp"] = (j["curve_on"] - j["sofr_fix"]) * 100
    print(f"\njoined {len(j)} days {j.index.min().date()}..{j.index.max().date()}")

    print("\n=== CONTROL: 2024-2025, where probe 4 found the ON leg never frozen ===")
    c = j.loc["2024":"2025"]
    med = c["diff_bp"].abs().median()
    print(f"  n={len(c)}  mean {c['diff_bp'].mean():.2f}  median|.| {med:.2f}  "
          f"max|.| {c['diff_bp'].abs().max():.2f} bp")
    ok = med < 5
    print(f"  control {'PASSES -- the comparison is trustworthy' if ok else 'FAILS -- do not trust the 2019 read'}")

    print("\n=== per-year: curve ON leg vs the published fixing ===")
    g = j.groupby(j.index.year)["diff_bp"]
    tbl = g.agg(["count", "mean", "std",
                 ("median_abs", lambda x: x.abs().median()),
                 ("max_abs", lambda x: x.abs().max())]).round(2)
    print(tbl.to_string())

    print("\n=== verdict per year ===")
    for y, row in tbl.iterrows():
        m = row["median_abs"]
        print(f"  {y}: median |curve_ON - SOFR| = {m:8.2f} bp   "
              f"{'OK' if m < 5 else 'BROKEN -- do not use on_sofr_rate this year'}")

    print("\n=== the smoking gun: 2019-07-09 .. 2019-11-25 ===")
    w = j.loc["2019-07-09":"2019-11-25"]
    print(f"  curve ON leg: {w['curve_on'].nunique()} distinct value(s) over "
          f"{len(w)} days -- {sorted(w['curve_on'].round(4).unique())[:5]}")
    print(f"  published SOFR over the same window: "
          f"{w['sofr_fix'].min():.3f}..{w['sofr_fix'].max():.3f} %, "
          f"{w['sofr_fix'].nunique()} distinct values")
    print("  the window spans the FOMC cuts of 2019-07-31, 2019-09-18 and "
          "2019-10-30 -- three consecutive 25bp cuts.")
    print(f"  median |diff| over the window: {w['diff_bp'].abs().median():.1f} bp")

    print("\n=== and the IMM leg over that same window, for contrast ===")
    print(f"  IMM_3xIMM_4 range {w['imm'].min():.4f}..{w['imm'].max():.4f} %, "
          f"{w['imm'].nunique()} distinct values, "
          f"daily change std {(w['imm'].diff() * 100).std():.2f} bp")
    print("  -> the FORWARD moves; it is the ON leg alone that is stuck.")

    j.to_csv(OUT / "p5b_on_vs_fixing.csv")


if __name__ == "__main__":
    main()
