"""Measurement C3 - is the -0.19 bp at 3-5Y a FED FUNDS defect or a curve-family one?

dd16 found the only Fed Funds cell whose bootstrap CI excludes zero: 3-5Y,
median -0.1930 bp, CI [-0.3468, -0.0710], 35.5% above mid, n = 62. Spearman
against tenor over the whole >=1Y sample is rho = -0.149, p = 0.017.

Two things have to happen before that is called a Fed Funds bias:

  * **power.** n = 62 in a five-band cut. One band at p = 0.030 out of five is
    roughly one expected false positive at the 5% level, so the cell needs its
    own draw.
  * **a same-tenor control.** If SOFR 3-5Y shows the same offset, it is a
    property of how these Citi curves are built, not of Fed Funds, and F-15's
    "no tenor gradient" was simply measured with ~30 prints in that band.

Both cells also get the one-minute control (timing vs convention) and the
seven-day placebo (does the statistic read the curve at all).
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scipy import stats

from dd_measure import LEG_COLS, connect, describe, even_subsample, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot

pd.set_option("display.width", 260)

TARGET = 220
OUT = "C:/Users/chris/clee/ARBS-dd/scratch/out_35y_control.csv"


def sql(index: str) -> str:
    return f"""
  FROM {LEGS_TABLE} l
  WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.rate_index_clean = '{index}'
    AND coalesce(l.trade_type,'') = 'OUTRIGHT'
    AND NOT coalesce(l.is_off_market,false) AND NOT coalesce(l.is_mac,false)
    AND NOT coalesce(l.is_spreadover,false) AND NOT coalesce(l.is_asset_swap,false)
    AND NOT coalesce(l.is_unwind,false)
    AND coalesce(l.is_new_risk, true)
    AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
    AND l.tenor_years > 3.0 AND l.tenor_years <= 5.01
"""


def infer(x, label: str) -> tuple:
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    if len(x) < 15:
        print(f"  {label:26s} n={len(x):4d}  (too few)")
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(20260811)
    boot = np.median(rng.choice(x, size=(25_000, len(x)), replace=True), axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    n_pos = int((x > 0).sum())
    print(f"  {label:26s} n={len(x):4d}  median {np.median(x):+.4f}  "
          f"CI [{lo:+.4f}, {hi:+.4f}] {'includes 0' if lo <= 0 <= hi else 'EXCLUDES 0':>10s}  "
          f"above mid {n_pos/len(x):5.1%} p={stats.binomtest(n_pos, len(x), 0.5).pvalue:.4f}  "
          f"IQR {np.percentile(x, 75) - np.percentile(x, 25):.3f}")
    return (float(np.median(x)), lo, hi)


def measure(rep, index: str) -> pd.DataFrame:
    curve = snapshot.CURVE_FOR[index]
    conn = connect()
    n = read_sql(conn, f"SELECT count(*) n {sql(index)}")["n"].iloc[0]
    k = max(1, int(n // (TARGET * 4)))
    pool = read_sql(conn, f"""SELECT {LEG_COLS} {sql(index)}
        AND mod(abs(hashtext(l.trade_id)), {k}) = 0
        ORDER BY l.execution_timestamp, l.trade_id""")
    conn.close()
    keep = [snapshot.in_session(curve, unit_from_leg(r)[1]) for _, r in pool.iterrows()]
    ins = pool[pd.Series(keep, index=pool.index)].reset_index(drop=True)
    take = even_subsample(ins, TARGET).sort_values(
        ["as_of_date", "execution_timestamp", "trade_id"]).reset_index(drop=True)
    print(f"  {index}: population {n:,}  modulus {k}  pool {len(pool)}  "
          f"in-session {len(ins)}  drawn {len(take)} over "
          f"{take['as_of_date'].nunique()} days")

    rows, t0 = [], time.perf_counter()
    for day, chunk in take.groupby("as_of_date", sort=True):
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, _ = unit_from_leg(r, with_upfront=False)
                printed = float(r["fixed_rate"]) * 100.0
                rec = {"index": index, "trade_id": r["trade_id"], "as_of_date": day,
                       "tenor_years": float(r["tenor_years"]),
                       "special_tenor_type": r["special_tenor_type"],
                       "is_off_date": bool(r["is_off_date"] or False),
                       "platform": r["platform_identifier"],
                       "printed_pct": printed}
                o = rep.price_unit(unit)
                if o.failure is None:
                    rec["diff_bp"] = (printed - o.pricing.leg_mid_pct[0]) * 100.0
                m1 = rep.price_unit(unit, instant=pd.Timestamp(snap) - pd.Timedelta(minutes=1))
                if m1.failure is None:
                    rec["diff_bp_m1"] = (printed - m1.pricing.leg_mid_pct[0]) * 100.0
                p7 = rep.price_unit(unit, instant=pd.Timestamp(snap) - pd.Timedelta(days=7))
                if p7.failure is None:
                    rec["diff_bp_placebo"] = (printed - p7.pricing.leg_mid_pct[0]) * 100.0
                rows.append(rec)
    print(f"  {index}: priced in {time.perf_counter()-t0:.0f}s")
    return pd.DataFrame(rows)


def main() -> None:
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    print("=== draws: 3Y < tenor <= 5Y, on-market outrights, in-session ===")
    ff = measure(rep, "FED_FUNDS")
    sofr = measure(rep, "SOFR")
    out = pd.concat([ff, sofr], ignore_index=True)
    out.to_csv(OUT, index=False)

    print("\n=== (printed - mid) at 3-5Y ===")
    infer(ff["diff_bp"], "FED_FUNDS 3-5Y")
    infer(sofr["diff_bp"], "SOFR 3-5Y  (control)")

    print("\n=== control: the same prints one minute earlier ===")
    infer(ff["diff_bp_m1"], "FED_FUNDS 3-5Y  t-1min")
    infer(sofr["diff_bp_m1"], "SOFR 3-5Y  t-1min")
    for nm, g in (("FED_FUNDS", ff), ("SOFR", sofr)):
        b = g[["diff_bp", "diff_bp_m1"]].dropna()
        if len(b) > 20:
            print(f"  {nm}: median shift from one minute earlier "
                  f"{(b['diff_bp_m1'] - b['diff_bp']).median():+.4f} bp "
                  "-> a shift near zero means CONVENTION, not timing")

    print("\n=== placebo, seven days earlier ===")
    for nm, g in (("FED_FUNDS", ff), ("SOFR", sofr)):
        describe(g["diff_bp_placebo"], f"{nm} 7d earlier")
        r, p = g["diff_bp"].dropna(), g["diff_bp_placebo"].dropna()
        if len(p) > 20:
            ir = r.quantile(.75) - r.quantile(.25)
            ip = p.quantile(.75) - p.quantile(.25)
            print(f"    IQR real {ir:.4f} vs placebo {ip:.4f} -> {ip/ir:.1f}x")

    print("\n=== is the Fed Funds 3-5Y offset concentrated anywhere? ===")
    for col in ("special_tenor_type", "is_off_date"):
        for k, g in ff.groupby(ff[col].fillna("<none>") if col == "special_tenor_type"
                               else ff[col]):
            infer(g["diff_bp"], f"FF {col}={k}")
    print("  by year:")
    for y, g in ff.groupby(pd.to_datetime(ff["as_of_date"]).dt.year):
        infer(g["diff_bp"], f"FF {y}")
    print("  by platform (top 4):")
    for pl in ff["platform"].value_counts().head(4).index:
        infer(ff.loc[ff["platform"] == pl, "diff_bp"], f"FF {pl}")


if __name__ == "__main__":
    main()
