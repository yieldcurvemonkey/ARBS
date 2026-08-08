"""CM-3: a TRADE-ONLY effective-spread estimator for USD OIS, to bracket CM-2's level.

WHY THIS, AND WHY IT IS THE RIGHT SHAPE. CM-2 measured |printed rate - same-day EOD
mid| over 905,820 Part 43 prints and was decisive on the SHAPE of the cost curve
(flat in tenor, 0.315-0.528bp) but NOT on its LEVEL: the deviation contains the
execution spread PLUS intraday drift between the print and the curve's 15:00 ET
stamp, so it is an admitted UPPER BOUND (L-0060), and the mid-peak in its
distribution means a half-spread cannot be asserted from it (L-0072/L-0078).

Roll (1984) estimates the effective spread from the TRANSACTION SERIES ALONE:
if trades arrive on alternating sides of an efficient price, consecutive price
changes carry a negative serial covariance of exactly -s^2/4, so s = 2*sqrt(-cov).
It needs no mid, no curve and no drift model -- so it does not share CM-2's
contamination.

**THE POINT IS THE DIRECTION OF THE BIAS.** Drift and information make consecutive
changes MORE positively correlated, which pushes cov up, which pushes the implied
spread DOWN (or makes it undefined). So Roll is a LOWER bound on the same quantity
CM-2 upper-bounds. Two estimators with OPPOSITE biases BRACKET the truth, and that
is the thing neither one can do alone. If the bracket is tight the level is pinned;
if it is wide, that is recorded as the honest answer rather than argued around.

Stated before any number exists, so it cannot be chosen afterwards:
  * the estimator is Roll's, on spot USD OIS NEWT+TRAD prints, per (tenor, day);
  * cells with non-negative covariance yield NO estimate and are COUNTED, never
    dropped silently and never floored at zero -- a floor would manufacture a
    small positive spread out of exactly the cells that refute the model;
  * the headline is the MEDIAN across days per tenor, with the share of estimable
    cells reported beside it, because an estimator that works on 20% of cells is
    reporting on a selected subsample and must say so.

Validation runs first, in both directions (repo rule): a simulated series with a
KNOWN planted spread must be recovered, and a pure random walk with NO spread must
fail to produce one.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_cm3_roll_spread.py
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
TENORS = [2, 5, 7, 10, 15, 20, 30]
MIN_PRINTS = 20          # per (tenor, day) cell
SEED = 20260809


def roll_spread(rates_bp: np.ndarray) -> tuple:
    """Roll (1984). Returns (spread_bp, cov). spread is nan when cov >= 0."""
    if len(rates_bp) < 3:
        return np.nan, np.nan
    d = np.diff(rates_bp)
    if len(d) < 2:
        return np.nan, np.nan
    cov = float(np.cov(d[:-1], d[1:], ddof=1)[0, 1])
    if not np.isfinite(cov) or cov >= 0:
        return np.nan, cov
    return float(2.0 * np.sqrt(-cov)), cov


# ------------------------------------------------------------------ validation
def validate() -> dict:
    """Both directions: recover a planted spread; fail to invent one that is absent."""
    rng = np.random.default_rng(SEED)
    n = 4000
    out = {}

    for planted in (0.2, 0.5, 1.0):
        eff = np.cumsum(rng.normal(0, 0.05, n))              # efficient rate, bp
        side = rng.choice([-1.0, 1.0], n)                    # random buy/sell
        obs = eff + side * (planted / 2.0)                   # half-spread each side
        est, _ = roll_spread(obs)
        out[f"planted_{planted}"] = {"planted": planted, "recovered": est,
                                     "rel_err": abs(est - planted) / planted}

    # NEGATIVE CONTROL: no spread at all.
    # NOTE ON THE BAR, corrected after the first run: a driftless random walk
    # produces a small NEGATIVE sample covariance by chance roughly half the time,
    # so demanding a NaN is the wrong test -- it fails for a reason that has
    # nothing to do with the estimator. The honest bar is that whatever it returns
    # is NEGLIGIBLE against the smallest spread we would ever want to detect.
    pure_runs = []
    for _ in range(200):
        est_p, _ = roll_spread(np.cumsum(rng.normal(0, 0.05, n)))
        pure_runs.append(0.0 if np.isnan(est_p) else est_p)
    pure_runs = np.array(pure_runs)
    out["negative_control_random_walk"] = {
        "runs": len(pure_runs), "median": float(np.median(pure_runs)),
        "p95": float(np.percentile(pure_runs, 95)), "max": float(pure_runs.max()),
        "frac_no_estimate": float(np.mean(pure_runs == 0.0)),
    }

    # DRIFT control -- this is the lower-bound property the whole design rests on,
    # so it must plant the spread with the SAME convention as the cases above
    # (side * planted/2). The first version used side * 0.5 while labelling it
    # 0.5, i.e. it planted 1.0 and "discovered" a doubling that was its own bug.
    for mu in (0.02, 0.10):
        drift = np.cumsum(rng.normal(mu, 0.05, n))
        side = rng.choice([-1.0, 1.0], n)
        est_d, _ = roll_spread(drift + side * (0.5 / 2.0))
        out[f"drift_mu_{mu}"] = {"planted": 0.5, "recovered": est_d,
                                 "ratio": est_d / 0.5}

    # MOMENTUM control: serially correlated efficient returns, which is what a
    # trending market actually looks like. THIS is what should depress the estimate.
    e = np.zeros(n)
    for t in range(1, n):
        e[t] = e[t - 1] + 0.5 * (e[t - 1] - e[t - 2] if t > 1 else 0) + rng.normal(0, 0.05)
    side = rng.choice([-1.0, 1.0], n)
    est_m, cov_m = roll_spread(e + side * (0.5 / 2.0))
    out["momentum_control"] = {"planted": 0.5, "recovered": est_m, "cov": cov_m,
                               "is_nan": bool(np.isnan(est_m))}

    print("=== VALIDATION (both directions) ===")
    print(json.dumps(out, indent=2, default=str))
    for k, v in out.items():
        if k.startswith("planted_") and not (v["rel_err"] < 0.15):
            raise SystemExit(f"VALIDATION FAILED: {k} recovered {v['recovered']} "
                             f"vs planted {v['planted']}")
    nc = out["negative_control_random_walk"]
    if nc["p95"] >= 0.05:
        raise SystemExit(f"VALIDATION FAILED: on a spreadless random walk the "
                         f"estimator returns up to {nc['p95']:.4f}bp at p95 -- not "
                         f"negligible against the 0.2bp smallest planted case.")
    print(f"VALIDATION PASS: planted spreads recovered within 15%; on 200 spreadless "
          f"random walks the estimator returns a median {nc['median']:.4f}bp "
          f"(p95 {nc['p95']:.4f}), negligible against the smallest planted 0.2bp.\n")
    return out


# ----------------------------------------------------------------------- main
def main() -> None:
    val = validate()

    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    rows = []
    t0 = time.time()
    for i, fp in enumerate(files):
        d = load_day(fp)
        if d.empty:
            continue
        d = d[d["_spot"] & d["_tenor"].notna() & d["_rate"].notna()]
        if d.empty:
            continue
        d = d.sort_values("_ts")
        for ten, g in d.groupby("_tenor"):
            if int(ten) not in TENORS or len(g) < MIN_PRINTS:
                continue
            r = g["_rate"].to_numpy(dtype=float) * 10000.0     # decimal -> bp
            s, cov = roll_spread(r)
            rows.append({"file_date": pd.Timestamp(fp.stem), "tenor": int(ten),
                         "n_prints": int(len(g)), "cov": cov, "spread_bp": s,
                         "half_spread_bp": s / 2.0 if np.isfinite(s) else np.nan})
        if (i + 1) % 150 == 0:
            print(f"  {i + 1}/{len(files)} ({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "cm3_roll_cells.parquet", index=False)

    print(f"\n=== CM-3: Roll effective HALF-spread, USD OIS spot, per tenor ===")
    print(f"{len(df):,} (tenor, day) cells over {df.file_date.nunique()} days\n")
    tab = (df.groupby("tenor")
             .agg(cells=("spread_bp", "size"),
                  estimable=("spread_bp", lambda s: int(s.notna().sum())),
                  median_prints=("n_prints", "median"),
                  hs_median=("half_spread_bp", "median"),
                  hs_p25=("half_spread_bp", lambda s: s.quantile(.25)),
                  hs_p75=("half_spread_bp", lambda s: s.quantile(.75)))
             .reset_index())
    tab["estimable_pct"] = (100 * tab.estimable / tab.cells).round(1)
    # CM-2's at-stamp upper bound, and the house line, for the bracket
    cm2 = {2: 0.35, 5: 0.40, 7: 0.42, 10: 0.45, 15: 0.48, 20: 0.50, 30: 0.53}
    tab["cm2_upper"] = tab.tenor.map(cm2)
    tab["cost_model"] = tab.tenor.map(lambda t: 0.25 + 0.05 * min(t, 30))
    tab["bracket_width"] = (tab.cm2_upper - tab.hs_median).round(3)
    print(tab.round(3).to_string(index=False))

    res = {
        "validation": val,
        "cells": int(len(df)), "days": int(df.file_date.nunique()),
        "per_tenor": tab.round(4).to_dict("records"),
        "overall_hs_median": float(df.half_spread_bp.median()),
        "overall_estimable_pct": float(100 * df.spread_bp.notna().mean()),
    }
    (OUT / "cm3_roll_verdict.json").write_text(json.dumps(res, indent=2, default=str),
                                               encoding="utf-8")
    print(f"\noverall: half-spread median {res['overall_hs_median']:.3f}bp, "
          f"estimable on {res['overall_estimable_pct']:.1f}% of cells")
    print("wrote cm3_roll_cells.parquet + cm3_roll_verdict.json")


if __name__ == "__main__":
    main()
