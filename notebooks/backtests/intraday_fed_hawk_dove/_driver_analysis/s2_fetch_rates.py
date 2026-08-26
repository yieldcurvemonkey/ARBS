"""Stage 2: the target rate and its policy-rate control, daily.

    UnifiedQuery(curve="USD-SOFR-1D", tenor="IMM_3xIMM_4", value=IRS_RATE)  <- SR3 3rd deferred
    UnifiedQuery(curve="USD-SOFR-1D", tenor="1d",          value=IRS_RATE)  <- policy control

Year-chunked, and that is a convention rather than a style choice: a single
multi-year span request returns DIFFERENT par rates for the same dates (up to
1.2 bp on the 10y), measured and documented in
``notebooks/backtests/convexity_rv/_p4_build_panel.py``.

Two extra tenors (2y, 5y) ride along purely as curve-shape diagnostics -- probe 3
found the 2019 short end degenerate (IMM_3xIMM_4 pinned to the ON leg at a
constant 0.35-0.69 bp through Feb and Jun 2019, and an ON leg frozen at exactly
2.5000 through Oct 2019), and the panel has to be able to say which years carry a
real forward and which do not. They are written to the diagnostic file, not to
the panel.

Writes rates_daily.parquet.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append(r"C:\Users\chris\clee\ARBS")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
CURVE = "USD-SOFR-1D"
START, END = dt.date(2019, 1, 1), dt.date(2026, 8, 24)

C_IMM = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE"
C_ON = f"{CURVE} 1d OUTRIGHT RATE"
C_2Y = f"{CURVE} 2y OUTRIGHT RATE"
C_5Y = f"{CURVE} 5y OUTRIGHT RATE"


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

    frames, failed = [], []
    for y in range(START.year, END.year + 1):
        a = max(START, dt.date(y, 1, 1))
        b = min(END, dt.date(y, 12, 31))
        if a > b:
            continue
        t0 = time.time()
        try:
            df = TimeseriesBuilder().get_timeseries(
                start=a, end=b, queries=qs, n_jobs=9, routers={"IRS": tb})
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            failed.append((y, f"{type(exc).__name__}: {exc}"))
            print(f"  {y}: FAILED {type(exc).__name__}: {exc}")
            continue
        if df is None or df.empty:
            failed.append((y, "empty"))
            print(f"  {y}: EMPTY")
            continue
        df.index = pd.to_datetime(df.index)
        frames.append(df)
        print(f"  {y}: {df.shape}  {df.index.min().date()}..{df.index.max().date()} "
              f"  ({time.time() - t0:.0f}s)")

    tb.close()
    if not frames:
        raise SystemExit("no rate data at all -- refusing to continue")

    rates = pd.concat(frames).sort_index()
    rates = rates[~rates.index.duplicated(keep="last")]
    rates.index.name = "date"
    print(f"\ncombined {rates.shape}  {rates.index.min().date()}..{rates.index.max().date()}")
    if failed:
        print(f"YEARS THAT FAILED: {failed}")

    # ---- degeneracy diagnostic --------------------------------------------
    d = rates.copy()
    d["imm_minus_on_bp"] = (d[C_IMM] - d[C_ON]) * 100
    d["d_imm_bp"] = d[C_IMM].diff() * 100
    d["d_on_bp"] = d[C_ON].diff() * 100
    d.to_parquet(OUT / "rates_diagnostic.parquet")

    print("\n=== per-year diagnostic ===")
    rows = []
    for y, g in d.groupby(d.index.year):
        # a curve whose forward is pinned to its own overnight leg shows up as a
        # near-constant spread AND a near-unit regression of one change on the other
        gg = g.dropna(subset=["d_imm_bp", "d_on_bp"])
        corr = gg["d_imm_bp"].corr(gg["d_on_bp"]) if len(gg) > 5 else np.nan
        beta = (np.polyfit(gg["d_on_bp"], gg["d_imm_bp"], 1)[0]
                if len(gg) > 5 and gg["d_on_bp"].std() > 1e-9 else np.nan)
        on_frozen = (g[C_ON].diff().abs() < 1e-9).mean()
        rows.append({
            "year": y, "n": len(g),
            "imm_mean": g[C_IMM].mean(), "on_mean": g[C_ON].mean(),
            "spread_mean_bp": g["imm_minus_on_bp"].mean(),
            "spread_std_bp": g["imm_minus_on_bp"].std(),
            "d_imm_std_bp": g["d_imm_bp"].std(),
            "d_on_std_bp": g["d_on_bp"].std(),
            "corr_dimm_don": corr, "beta_dimm_on_don": beta,
            "frac_on_unchanged": on_frozen,
        })
    diag = pd.DataFrame(rows).set_index("year")
    print(diag.round(3).to_string())
    diag.to_csv(OUT / "rates_year_diagnostic.csv")

    print("\n=== the degeneracy read ===")
    print("beta near 1.00 with |spread_std| tiny means IMM_3xIMM_4 is NOT an")
    print("independent forward that year -- it is the overnight leg re-labelled.")
    for y, r in diag.iterrows():
        flag = ""
        if r["spread_std_bp"] < 5 and r["beta_dimm_on_don"] > 0.9:
            flag = "  <-- DEGENERATE"
        elif r["frac_on_unchanged"] > 0.5:
            flag = "  <-- ON leg frozen on >50% of days"
        print(f"  {y}: spread_std={r['spread_std_bp']:.2f}bp  "
              f"beta={r['beta_dimm_on_don']:.3f}  "
              f"frac_on_unchanged={r['frac_on_unchanged']:.2f}{flag}")

    rates.to_parquet(OUT / "rates_daily.parquet")
    print(f"\nwrote {OUT / 'rates_daily.parquet'}")


if __name__ == "__main__":
    main()
