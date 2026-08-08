"""CM-4: can the price-impact exponent eta be measured from the Part 43 tape?

L-0068 names this as CM-2's next step. CM-3 was a cheaper attempt at the same
target (a level for the cost line) and it failed, but it handed this study its
on-ramp: the ONLY cells in this tape homogeneous enough to compare prints within
are one exact instrument (maturity AND effective date) inside a single hour.
Outside those, an apparent price difference is instrument dispersion, not
execution (L-0089: a 12.8x collapse as heterogeneity is removed).

TARGET. Aggregate impact is conventionally E|dp| ~ Q^eta, with eta ~ 0.5 the
square-root law. SIDE IS NOT INFERABLE from this tape (L-0041, re-confirmed at
L-0073), so SIGNED impact cannot be measured -- but the ABSOLUTE move scales with
the same exponent under symmetry, and that is what is fitted here.

THREE THINGS PRE-STATED, BEFORE ANY NUMBER, because each is a way this study
could flatter itself:

  1. CENSORING. 3.33% of USD notional strings are CAPPED ("1,100,000,000+") and
     the cap sits exactly where a power-law exponent is identified. PRIMARY: drop
     capped prints and fit strictly below the cap, REPORTING the size range that
     survives. SENSITIVITY: include them at the cap value, which understates their
     true size and therefore biases eta UPWARD -- so the two together bound it.

  2. REVERSE CAUSALITY, the confound that would flatter the study. Large prints
     cluster in volatile hours, so a raw size-vs-move regression conflates size
     with ambient volatility. CONTROLS: (a) the fit is WITHIN CELL -- one
     instrument, one hour -- so ambient volatility is differenced out by
     construction; (b) a SHUFFLE NULL that permutes sizes within each cell and
     refits, 200 draws. The measured eta must sit outside that null or it is not
     about size.

  3. THE FAILURE OUTCOME IS A VALID CLOSE. "eta cannot be measured from Part 43
     at this granularity", documented, is progress -- CM-3 is the precedent, and
     writing it down was worth more than the attempt.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_cm4_impact_exponent.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from s3_f7_package_extract import SDR_DIR, load_day

OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
TENORS = [2, 5, 10, 30]
MIN_PRINTS = 20          # per homogeneous (instrument, hour) cell
N_SHUFFLE = 200
SEED = 20260809


def build_pairs() -> pd.DataFrame:
    """Consecutive print pairs inside homogeneous (instrument, hour) cells."""
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    rows, t0 = [], time.time()
    for i, fp in enumerate(files):
        d = load_day(fp)
        if d.empty:
            continue
        d = d[d["_spot"] & d["_tenor"].notna() & d["_rate"].notna()
              & d["_notional"].notna()].copy()
        if d.empty:
            continue
        d["_exp"] = pd.to_datetime(d["Expiration Date"], errors="coerce")
        d["_eff"] = pd.to_datetime(d["Effective Date"], errors="coerce")
        d = d.dropna(subset=["_exp", "_eff"])
        d["_hr"] = d["_ts"].dt.floor("h")
        d = d[d["_tenor"].isin(TENORS)].sort_values("_ts")

        for key, g in d.groupby(["_tenor", "_exp", "_eff", "_hr"], sort=False):
            if len(g) < MIN_PRINTS:
                continue
            r = g["_rate"].to_numpy(float) * 1e4      # bp
            q = g["_notional"].to_numpy(float)
            cap = g["_capped"].to_numpy(bool)
            cell = f"{fp.stem}|{int(key[0])}|{key[1].date()}|{key[3]}"
            for j in range(1, len(g)):
                rows.append({"cell": cell, "tenor": int(key[0]),
                             "abs_move_bp": abs(r[j] - r[j - 1]),
                             "notional": q[j], "capped": bool(cap[j])})
        if (i + 1) % 150 == 0:
            print(f"  {i + 1}/{len(files)} ({time.time() - t0:.0f}s)", flush=True)
    return pd.DataFrame(rows)


def within_cell_fit(df: pd.DataFrame, rng=None) -> tuple:
    """Pooled within-cell slope of log|move| on log(size). Cell means removed."""
    d = df[(df.abs_move_bp > 0) & (df.notional > 0)].copy()
    if len(d) < 50:
        return np.nan, 0
    y = np.log(d.abs_move_bp.to_numpy())
    x = np.log(d.notional.to_numpy())
    if rng is not None:                                # shuffle sizes WITHIN cell
        x = (pd.Series(x, index=d.cell.to_numpy())
             .groupby(level=0).transform(lambda s: rng.permutation(s.to_numpy()))
             .to_numpy())
    cells = d.cell.to_numpy()
    ym = pd.Series(y, index=cells).groupby(level=0).transform("mean").to_numpy()
    xm = pd.Series(x, index=cells).groupby(level=0).transform("mean").to_numpy()
    yd, xd = y - ym, x - xm
    denom = float((xd * xd).sum())
    if denom <= 0:
        return np.nan, len(d)
    return float((xd * yd).sum() / denom), len(d)


def main() -> None:
    pairs = build_pairs()
    if pairs.empty:
        print("NO HOMOGENEOUS CELLS -- eta is not measurable at this granularity.")
        return
    pairs.to_parquet(OUT / "cm4_pairs.parquet", index=False)
    print(f"\n{len(pairs):,} consecutive pairs in {pairs.cell.nunique():,} homogeneous cells "
          f"(one instrument, one hour, >= {MIN_PRINTS} prints)")
    print(f"capped share of pairs: {pairs.capped.mean():.2%}")

    rng = np.random.default_rng(SEED)
    res = {"cells": int(pairs.cell.nunique()), "pairs": int(len(pairs)),
           "capped_share": float(pairs.capped.mean()), "per_tenor": []}

    print("\n=== eta = within-cell slope of log|move| on log(size) ===")
    print(f"{'tenor':>6} {'arm':>12} {'pairs':>8} {'cells':>7} {'eta':>8} "
          f"{'null_mean':>10} {'null_sd':>8} {'z_vs_null':>10} {'size_p5':>10} {'size_p95':>11}")
    for tenor in TENORS + ["ALL"]:
        sub_all = pairs if tenor == "ALL" else pairs[pairs.tenor == tenor]
        for arm, sub in (("primary_uncapped", sub_all[~sub_all.capped]),
                         ("sens_cap_at_floor", sub_all)):
            eta, n = within_cell_fit(sub)
            if not np.isfinite(eta):
                print(f"{str(tenor):>6} {arm:>12} {n:>8} {'-':>7} {'n/a':>8}")
                continue
            null = np.array([within_cell_fit(sub, rng)[0] for _ in range(N_SHUFFLE)])
            null = null[np.isfinite(null)]
            z = (eta - null.mean()) / null.std(ddof=1) if len(null) > 2 else np.nan
            q = sub[sub.notional > 0].notional
            print(f"{str(tenor):>6} {arm:>18} {n:>8,} {sub.cell.nunique():>7,} {eta:>8.4f} "
                  f"{null.mean():>10.4f} {null.std(ddof=1):>8.4f} {z:>10.2f} "
                  f"{q.quantile(.05):>10,.0f} {q.quantile(.95):>11,.0f}")
            res["per_tenor"].append({
                "tenor": str(tenor), "arm": arm, "pairs": int(n),
                "cells": int(sub.cell.nunique()), "eta": eta,
                "null_mean": float(null.mean()), "null_sd": float(null.std(ddof=1)),
                "z_vs_null": float(z),
                "size_p5": float(q.quantile(.05)), "size_p95": float(q.quantile(.95)),
            })

    (OUT / "cm4_eta_verdict.json").write_text(json.dumps(res, indent=2, default=str),
                                              encoding="utf-8")
    print("\nwrote cm4_pairs.parquet + cm4_eta_verdict.json")


if __name__ == "__main__":
    main()
