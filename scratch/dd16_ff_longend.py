"""Measurement C2 - two things dd14's pooled sample cannot settle.

1. **Per-cohort inference.** Pooling FOMC-dated Fed Funds prints with standard
   ones mixes two populations whose dispersion differs by an order of magnitude
   (IQR 4.90 bp against 0.42 bp), and a pooled median can hide two opposite
   biases -- which is exactly how F-20's per-meeting sign flip would look if it
   survived. Each cohort gets its own bootstrap CI and sign test.

2. **The long end.** dd14's tenor cut shows medians walking from +0.04 bp at
   3-6M to -0.21 bp at 5-30Y on n = 9..35 per band. A monotone tenor gradient is
   the signature F-20 used to convict the old Barchart curve, so it cannot be
   left at n = 9. This draws a supplementary Fed Funds sample restricted to
   tenor >= 1Y and runs the same statistic, with the same 7-day placebo.
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

TARGET = 260
CURVE = "USD-FEDFUNDS-1D"
OUT = "C:/Users/chris/clee/ARBS-dd/scratch/out_ff_longend.csv"

_FF_LONG = f"""
  FROM {LEGS_TABLE} l
  WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.rate_index_clean = 'FED_FUNDS'
    AND coalesce(l.trade_type,'') = 'OUTRIGHT'
    AND NOT coalesce(l.is_off_market,false) AND NOT coalesce(l.is_mac,false)
    AND NOT coalesce(l.is_spreadover,false) AND NOT coalesce(l.is_asset_swap,false)
    AND NOT coalesce(l.is_unwind,false)
    AND coalesce(l.is_new_risk, true)
    AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
    AND l.tenor_years BETWEEN 1.0 AND 31
"""


def infer(x, label: str) -> None:
    """Median, bootstrap CI and sign test -- the three dd07 reports."""
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    if len(x) < 15:
        print(f"  {label:22s} n={len(x):4d}  (too few for inference)")
        return
    rng = np.random.default_rng(20260811)
    boot = np.median(rng.choice(x, size=(25_000, len(x)), replace=True), axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    n_pos = int((x > 0).sum())
    print(f"  {label:22s} n={len(x):4d}  median {np.median(x):+.4f}  "
          f"CI [{lo:+.4f}, {hi:+.4f}] {'0' if lo <= 0 <= hi else 'EXCLUDES 0':>10s}  "
          f"above mid {n_pos}/{len(x)} ({n_pos/len(x):5.1%}) p={stats.binomtest(n_pos, len(x), 0.5).pvalue:.3f}  "
          f"IQR {np.percentile(x, 75) - np.percentile(x, 25):.3f}")


def reanalyse() -> None:
    d = pd.read_csv("C:/Users/chris/clee/ARBS-dd/scratch/out_ff_bias.csv")
    d = d.dropna(subset=["diff_bp"])
    print(f"=== dd14's {len(d)} Fed Funds prints, re-cut per cohort ===")
    infer(d["diff_bp"], "ALL")
    for k, g in d.groupby(d["special_tenor_type"].fillna("<none>")):
        infer(g["diff_bp"], f"stt={k}")
    print("\n  by FOMC meeting label (the F-20 failure mode), n>=8 only:")
    lab = d["fomc_meeting_label"].fillna("<none>")
    meds = []
    for k, g in d.groupby(lab):
        if k == "<none>" or len(g) < 8:
            continue
        infer(g["diff_bp"], str(k))
        meds.append(g["diff_bp"].median())
    if meds:
        m = np.array(meds)
        print(f"    {len(m)} meeting buckets: medians {m.min():+.3f} .. {m.max():+.3f} bp, "
              f"{int((m > 0).sum())} positive / {int((m < 0).sum())} negative")
    else:
        sizes = lab[lab != "<none>"].value_counts()
        print(f"    no meeting bucket reaches n=8; largest are "
              f"{sizes.head(6).to_dict()}")


def main() -> None:
    reanalyse()

    print("\n\n=== supplementary draw: Fed Funds, tenor >= 1Y ===")
    conn = connect()
    n = read_sql(conn, f"SELECT count(*) n {_FF_LONG}")["n"].iloc[0]
    k = max(1, int(n // (TARGET * 4)))
    pool = read_sql(conn, f"""
        SELECT {LEG_COLS} {_FF_LONG}
          AND mod(abs(hashtext(l.trade_id)), {k}) = 0
        ORDER BY l.execution_timestamp, l.trade_id""")
    conn.close()
    keep = [snapshot.in_session(CURVE, unit_from_leg(r)[1]) for _, r in pool.iterrows()]
    ins = pool[pd.Series(keep, index=pool.index)].reset_index(drop=True)
    take = even_subsample(ins, TARGET).sort_values(
        ["as_of_date", "execution_timestamp", "trade_id"]).reset_index(drop=True)
    print(f"  population {n:,}  modulus {k}  pool {len(pool)}  in-session {len(ins)}  "
          f"drawn {len(take)} over {take['as_of_date'].nunique()} days")

    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    rows, t0 = [], time.perf_counter()
    for day, chunk in take.groupby("as_of_date", sort=True):
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, _ = unit_from_leg(r, with_upfront=False)
                printed = float(r["fixed_rate"]) * 100.0
                rec = {"trade_id": r["trade_id"], "as_of_date": day,
                       "tenor_years": float(r["tenor_years"]),
                       "special_tenor_type": r["special_tenor_type"],
                       "printed_pct": printed}
                o = rep.price_unit(unit)
                if o.failure is None:
                    rec["diff_bp"] = (printed - o.pricing.leg_mid_pct[0]) * 100.0
                    rec["pv01"] = o.pricing.leg_pv01[0]
                else:
                    rec["error"] = o.failure
                p = rep.price_unit(unit, instant=pd.Timestamp(snap) - pd.Timedelta(days=7))
                if p.failure is None:
                    rec["diff_bp_placebo"] = (printed - p.pricing.leg_mid_pct[0]) * 100.0
                rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"  priced in {time.perf_counter()-t0:.0f}s; "
          f"{int(out['diff_bp'].notna().sum())}/{len(out)} succeeded")

    print("\n=== Fed Funds >= 1Y ===")
    infer(out["diff_bp"], "ALL >=1Y")
    bands = [0.99, 2.01, 3.01, 5.01, 10.01, 31]
    labels = ["1-2Y", "2-3Y", "3-5Y", "5-10Y", "10-30Y"]
    bucket = pd.cut(out["tenor_years"], bands, labels=labels)
    for b in labels:
        infer(out.loc[bucket == b, "diff_bp"], b)

    print("\n  Spearman rank correlation of diff_bp against tenor "
          "(a convention error is monotone in tenor):")
    g = out.dropna(subset=["diff_bp"])
    rho, p = stats.spearmanr(g["tenor_years"], g["diff_bp"])
    print(f"    rho = {rho:+.4f}, p = {p:.4f}  (n = {len(g)})")

    print("\n=== placebo, same prints 7 days earlier ===")
    describe(out["diff_bp_placebo"], "7d earlier")
    real = out["diff_bp"].dropna()
    plac = out["diff_bp_placebo"].dropna()
    if len(plac) > 20:
        ir = real.quantile(.75) - real.quantile(.25)
        ip = plac.quantile(.75) - plac.quantile(.25)
        print(f"  IQR real {ir:.4f} vs placebo {ip:.4f} -> ratio {ip/ir:.1f}x")


if __name__ == "__main__":
    main()
