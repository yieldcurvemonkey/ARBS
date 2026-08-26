"""Probe 5: is the ``1d`` leg really the overnight rate, or the front of the swap
curve wearing that label?

Probe 4 found the ON leg frozen at exactly 2.5000 for 95 days across Jul-Nov 2019
and carrying a 0.0000 somewhere in H1 2019, while the same window's IMM_3xIMM_4
moved sensibly. That is an accusation about one series, so it gets tested against
an INDEPENDENT one: rateslib ships the published SOFR fixing history, which owes
nothing to the Citi curve build.

A checking tool that is itself wrong reports success, so the comparison is run
first on 2024-2025 -- where the ON leg is never frozen and must therefore agree
-- before it is trusted on 2019.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
CURVE = "USD-SOFR-1D"
C_ON = f"{CURVE} 1d OUTRIGHT RATE"
C_IMM = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE"


def load_sofr_fixings() -> pd.Series | None:
    try:
        from rateslib import defaults
        fx = defaults.fixings
        for name in ("usd_rfr", "sofr", "usd_sofr"):
            try:
                s = fx[name]
            except Exception:  # noqa: BLE001
                continue
            if s is None:
                continue
            ser = s.iloc[:, 0] if isinstance(s, pd.DataFrame) else s
            ser.index = pd.to_datetime(ser.index)
            print(f"rateslib fixings['{name}']: {len(ser)} rows "
                  f"{ser.index.min().date()}..{ser.index.max().date()}")
            return ser.sort_index()
    except Exception as exc:  # noqa: BLE001
        print(f"rateslib fixings unavailable: {type(exc).__name__}: {exc}")
    return None


def main() -> None:
    r = pd.read_parquet(OUT / "rates_daily.parquet")
    r.index = pd.to_datetime(r.index)
    r = r.sort_index()

    print("=== hard errors in the ON leg ===")
    z = r[r[C_ON].abs() < 1e-9]
    print(f"days where the ON leg is exactly 0.0000: {len(z)}")
    if len(z):
        print(z[[C_ON, C_IMM]].to_string())
    neg = r[r[C_ON] < 0]
    print(f"days where the ON leg is negative: {len(neg)}")
    if len(neg):
        print(neg[[C_ON, C_IMM]].head(20).to_string())

    fix = load_sofr_fixings()
    if fix is None:
        print("\nNO INDEPENDENT SOFR SERIES AVAILABLE -- the ON verdict stays "
              "'suspicious', not 'proven wrong'.")
        return

    j = pd.DataFrame({"curve_on": r[C_ON]}).join(fix.rename("sofr_fix"), how="inner")
    j = j.dropna()
    j["diff_bp"] = (j["curve_on"] - j["sofr_fix"]) * 100
    print(f"\njoined {len(j)} days {j.index.min().date()}..{j.index.max().date()}")

    print("\n=== CONTROL first: 2024-2025, where the ON leg is never frozen. ===")
    print("If the comparison is sound it must agree here.")
    c = j.loc["2024":"2025"]
    print(f"  n={len(c)}  mean diff {c['diff_bp'].mean():.2f}bp  "
          f"median |diff| {c['diff_bp'].abs().median():.2f}bp  "
          f"max |diff| {c['diff_bp'].abs().max():.2f}bp")
    ok = c["diff_bp"].abs().median() < 5
    print(f"  control {'PASSES' if ok else 'FAILS'} -- "
          f"{'the comparison is trustworthy' if ok else 'do NOT trust the 2019 read'}")

    print("\n=== per-year agreement of the curve ON leg with the published fixing ===")
    g = j.groupby(j.index.year)["diff_bp"]
    print(g.agg(["count", "mean", "std",
                 lambda x: x.abs().median(), lambda x: x.abs().max()]).round(2).to_string(
        header=["n", "mean_bp", "std_bp", "median_abs_bp", "max_abs_bp"]))

    if ok:
        print("\n=== verdict ===")
        for y, gg in j.groupby(j.index.year):
            m = gg["diff_bp"].abs().median()
            print(f"  {y}: median |curve_ON - SOFR fixing| = {m:7.2f} bp   "
                  f"{'OK' if m < 5 else 'BROKEN -- do not use the ON control this year'}")


if __name__ == "__main__":
    main()
