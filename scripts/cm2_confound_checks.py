"""CM-2 confound checks — the three ways the measured line could be too good.

CM-2 measures |printed fixed rate - same-day EOD mid| and calls it an upper
bound on the half-spread. Three things could make that number smaller than the
truth, and each gets a test rather than a caveat.

1. **Drift, not spread.** At the stamp hour the residual could still be mostly
   intraday drift. A half-spread is BIMODAL (trades happen at bid or offer, not
   at mid); drift is unimodal around zero. Measured: the share of prints inside
   +/-0.05bp of mid, and a dip test — the density at zero against the density at
   the modal |deviation|. A spread shows a DIP at zero.
2. **Mid-market printing.** Compression and portfolio-rebalancing trades print
   AT mid and would drag the median down. Measured: the mass at |dev| ~ 0, and
   the cleared/uncleared split.
3. **Size.** If only tiny clips trade near mid, the number is not the line a
   $100k-DV01 package would pay. Measured: median |dev| by notional quartile.

Run after cost_swap_sdr.py.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import json
import pathlib
import sys

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

import numpy as np
import pandas as pd

DATA = _REPO / "notebooks" / "data" / "citivelo_rv"


def main() -> None:
    d = pd.read_parquet(DATA / "swap_cost_prints.parquet")
    v = json.loads((DATA / "swap_cost_verdict.json").read_text())
    stamp = int(v["stamp_hour_et"])
    pd.set_option("display.width", 200)
    print(f"{len(d):,} prints; stamp hour {stamp}:00 ET")

    at = d[d["exec_hour_et"] == stamp]
    print(f"\nat the stamp hour: {len(at):,} prints, "
          f"median |dev| {at['abs_dev_bp'].median():.3f} bp")

    # --- 1. bimodality -----------------------------------------------------
    print("\n=== 1. is it a spread or is it drift? ===")
    for label, g in (("all hours", d), (f"stamp hour {stamp}", at)):
        x = g["dev_bp"].to_numpy()
        x = x[np.abs(x) < 5.0]
        if len(x) < 500:
            continue
        hist, edges = np.histogram(x, bins=61, range=(-3, 3))
        centre = hist[len(hist) // 2]
        peak = hist.max()
        peak_at = float((edges[hist.argmax()] + edges[hist.argmax() + 1]) / 2)
        print(f"  {label:16s} n={len(x):7,d}  density at 0 = {centre:6d}  "
              f"peak = {peak:6d} at {peak_at:+.2f} bp  "
              f"centre/peak = {centre / peak:.3f}  "
              f"{'DIP at zero -> spread-like' if centre < 0.9 * peak else 'no dip at zero'}")
    print("  NOTE the test is one-directional. A dip at zero is evidence of a")
    print("  spread; the ABSENCE of one is not evidence of drift — SDR flow at a")
    print("  given hour can be one-sided, and a one-sided spread is a SHIFTED")
    print("  UNIMODAL distribution, not a bimodal one.")

    # --- 2. mid-market printing -------------------------------------------
    print("\n=== 2. mid-market printing ===")
    for thr in (0.02, 0.05, 0.10, 0.25):
        print(f"  share of stamp-hour prints within +/-{thr:.2f} bp of mid: "
              f"{float((at['abs_dev_bp'] < thr).mean()):.3%}")
    if "cleared" in d:
        cl = d.groupby(d["cleared"].astype(str))["abs_dev_bp"].agg(["size", "median"])
        print("\n  by cleared flag:")
        print(cl[cl["size"] >= 100].round(3).to_string())

    # --- 3. size ------------------------------------------------------------
    print("\n=== 3. does size trade wider? ===")
    rows = []
    for tenor in (2, 5, 10, 30):
        g = at[(at["tenor"] == tenor) & at["notional"].notna() & (at["notional"] > 0)]
        if len(g) < 200:
            continue
        try:
            q = pd.qcut(g["notional"], 4, labels=["q1", "q2", "q3", "q4"])
        except ValueError:
            continue
        for lab, gg in g.groupby(q, observed=True):
            rows.append({"tenor": tenor, "notional_q": str(lab), "n": len(gg),
                         "median_notional_mm": float(gg["notional"].median() / 1e6),
                         "median_abs_dev_bp": float(gg["abs_dev_bp"].median())})
    if rows:
        print(pd.DataFrame(rows).round(3).to_string(index=False))

    out = {"stamp_hour_et": stamp, "n_prints": int(len(d)),
           "n_at_stamp": int(len(at)),
           "stamp_median_abs_dev_bp": float(at["abs_dev_bp"].median()),
           "share_within_0.05bp_of_mid_at_stamp": float((at["abs_dev_bp"] < 0.05).mean())}
    (DATA / "cm2_confounds.json").write_text(json.dumps(out, indent=1))
    print("\n" + json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
