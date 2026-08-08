"""AUDIT probe: WHICH leg filter removes the flow, and is its window well-placed?

s3_f7_package_extract keeps a leg only if it (a) buckets within 15 calendar days of a
standard tenor and (b) is "spot starting": (effective - exec_date_ET).days in [-1, +5].
A mis-placed window here would delete real packages from the flow variable and bias the
gate toward NO effect. This measures the leg-level attrition and the actual spot-lag and
tenor-error distributions, so the window can be read against the data rather than assumed.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/audit_f7_filter_decomp.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import s3_f7_package_extract as e  # noqa: E402


def main() -> None:
    files = sorted(pathlib.Path(p) for p in
                   glob.glob(str(e.SDR_DIR / "*" / "*" / "*.parquet")))[::8]
    lag, terr, n_tot = [], [], 0
    t0 = time.time()
    for i, fp in enumerate(files):
        names = set(pq.read_schema(fp).names)
        want = [c for c in e._COLS if c in names]
        df = pq.read_table(fp, columns=want).to_pandas()
        key = "UPI FISN" if "UPI FISN" in df.columns else "Product name"
        m = (df["Action type"].astype(str).eq("NEWT")
             & df["Event type"].astype(str).eq("TRAD")
             & df["Notional currency-Leg 1"].astype(str).eq("USD")
             & df[key].astype(str).str.contains("OIS", na=False))
        df = df.loc[m]
        if df.empty:
            continue
        ts = pd.to_datetime(df["Execution Timestamp"], errors="coerce", utc=True)
        eff = pd.to_datetime(df["Effective Date"], errors="coerce")
        exp = pd.to_datetime(df["Expiration Date"], errors="coerce")
        exec_d = ts.dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        lag.append((eff - exec_d).dt.days.to_numpy())
        yrs = ((exp - eff).dt.days / 365.25).to_numpy(dtype=float)
        idx = np.abs(yrs[:, None] - e.STD_TENORS[None, :]).argmin(axis=1)
        terr.append(np.abs((yrs - e.STD_TENORS[idx]) * 365.25))
        n_tot += len(df)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(files)} ({time.time()-t0:.0f}s)", flush=True)

    lag = np.concatenate(lag).astype(float)
    terr = np.concatenate(terr)
    print(f"\nUSD OIS NEWT+TRAD legs sampled: {n_tot:,}")

    print("\n=== SPOT-LAG (effective - exec_date_ET), calendar days ===")
    vc = pd.Series(lag).value_counts().sort_index()
    tot = len(lag)
    for v, c in vc.items():
        if -6 <= v <= 12 or c / tot > 0.01:
            mark = "  <-- INSIDE window" if -1 <= v <= e.MAX_SPOT_LAG_D else ""
            print(f"  lag {int(v) if np.isfinite(v) else v:>4}d : {c:>8,} ({c/tot:6.2%}){mark}")
    inside = np.nansum((lag >= -1) & (lag <= e.MAX_SPOT_LAG_D))
    print(f"  INSIDE [-1,{e.MAX_SPOT_LAG_D}] : {inside:,} ({inside/tot:.2%})")
    for hi in (6, 7, 10):
        j = np.nansum((lag >= -1) & (lag <= hi))
        print(f"  (counterfactual window [-1,{hi}]: {j:,} = {j/tot:.2%}, "
              f"+{(j-inside)/max(1,inside):.2%} more legs)")
    print(f"  NaN lag: {int(np.isnan(lag).sum()):,}")

    print("\n=== TENOR bucketing error, |years - nearest standard| in days ===")
    ok = terr <= e.TENOR_TOL_D
    print(f"  within {e.TENOR_TOL_D:.0f}d tolerance: {np.nansum(ok):,} "
          f"({np.nansum(ok)/len(terr):.2%})")
    for q in (50, 75, 90, 95, 99):
        print(f"  p{q} error {np.nanpercentile(terr, q):8.1f}d")
    for tol in (20, 30, 45):
        j = np.nansum(terr <= tol)
        print(f"  (counterfactual tol {tol}d: {j:,} = {j/len(terr):.2%}, "
              f"+{(j-np.nansum(ok))/max(1,np.nansum(ok)):.2%} more legs)")

    both = np.nansum(ok & (lag >= -1) & (lag <= e.MAX_SPOT_LAG_D))
    print(f"\nlegs surviving BOTH filters: {both:,} ({both/tot:.2%} of USD OIS NEWT+TRAD)")


if __name__ == "__main__":
    main()
