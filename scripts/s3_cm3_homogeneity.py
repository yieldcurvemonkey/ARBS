"""Why does Roll return an impossible number on this tape?

CM-3's first pass gave half-spreads of 1.6-13.3bp per tenor against CM-2's
MEASURED UPPER BOUND of 0.32-0.53bp. Two estimates of the same quantity cannot
sit 3-30x apart on opposite sides of a bound, so one of them is not measuring
what it claims. The simulation says the estimator is correctly implemented
(planted 0.2/0.5/1.0 recovered to 4%), so the suspect is the DATA: Roll assumes
consecutive prints are the SAME instrument at the SAME efficient price, differing
only by which side of the spread they crossed.

A "10Y" cell in this tape is not that. It pools every maturity inside a 15-day
bucket, every effective date inside a 5-day spot window, package legs struck away
from mid, and prints spread over an 8-hour session. Any of that looks exactly like
bid-ask bounce to a serial-covariance estimator.

THE TEST, which is decisive in one direction: progressively remove the
heterogeneity and see whether the estimate falls toward CM-2's band. If it does,
Roll was measuring instrument dispersion. If it does not, the contamination is
something else and CM-3 is unexplained rather than explained.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_cm3_homogeneity.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import json
import pathlib
import sys

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

from s3_cm3_roll_spread import roll_spread
from s3_f7_package_extract import SDR_DIR, load_day

OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
TENORS = [2, 5, 10, 30]
MIN_PRINTS = 20


def main() -> None:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    files = files[::2]                      # every other day; this is a diagnostic
    rows = []
    for fp in files:
        d = load_day(fp)
        if d.empty:
            continue
        d = d[d["_spot"] & d["_tenor"].notna() & d["_rate"].notna()].copy()
        if d.empty:
            continue
        d["_exp"] = pd.to_datetime(d["Expiration Date"], errors="coerce")
        d["_eff"] = pd.to_datetime(d["Effective Date"], errors="coerce")
        d = d.dropna(subset=["_exp", "_eff"]).sort_values("_ts")

        for ten, g in d.groupby("_tenor"):
            t = int(ten)
            if t not in TENORS:
                continue

            # LEVEL 0: the tape cell as CM-3 used it -- one tenor bucket, whole day
            if len(g) >= MIN_PRINTS:
                s, _ = roll_spread(g["_rate"].to_numpy(float) * 1e4)
                rows.append({"level": "0_tenor_bucket", "tenor": t, "file_date": fp.stem,
                             "n": len(g), "hs": s / 2 if np.isfinite(s) else np.nan})

            # LEVEL 1: one EXACT maturity date (the modal one that day)
            top = g["_exp"].value_counts()
            if len(top) and top.iloc[0] >= MIN_PRINTS:
                gg = g[g["_exp"] == top.index[0]]
                s, _ = roll_spread(gg["_rate"].to_numpy(float) * 1e4)
                rows.append({"level": "1_exact_maturity", "tenor": t, "file_date": fp.stem,
                             "n": len(gg), "hs": s / 2 if np.isfinite(s) else np.nan})

                # LEVEL 2: exact maturity AND one effective date
                top2 = gg["_eff"].value_counts()
                if len(top2) and top2.iloc[0] >= MIN_PRINTS:
                    g3 = gg[gg["_eff"] == top2.index[0]]
                    s, _ = roll_spread(g3["_rate"].to_numpy(float) * 1e4)
                    rows.append({"level": "2_exact_mat_and_eff", "tenor": t,
                                 "file_date": fp.stem, "n": len(g3),
                                 "hs": s / 2 if np.isfinite(s) else np.nan})

                    # LEVEL 3: same, restricted to a 60-minute window (the busiest hour)
                    g3 = g3.copy()
                    g3["_hr"] = g3["_ts"].dt.floor("h")
                    hh = g3["_hr"].value_counts()
                    if len(hh) and hh.iloc[0] >= MIN_PRINTS:
                        g4 = g3[g3["_hr"] == hh.index[0]]
                        s, _ = roll_spread(g4["_rate"].to_numpy(float) * 1e4)
                        rows.append({"level": "3_exact_and_1hr", "tenor": t,
                                     "file_date": fp.stem, "n": len(g4),
                                     "hs": s / 2 if np.isfinite(s) else np.nan})

    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "cm3_homogeneity.parquet", index=False)

    tab = (df.groupby(["level", "tenor"])
             .agg(cells=("hs", "size"), estimable=("hs", lambda s: int(s.notna().sum())),
                  median_n=("n", "median"), hs_median=("hs", "median"))
             .reset_index())
    cm2 = {2: 0.35, 5: 0.40, 10: 0.45, 30: 0.53}
    tab["cm2_upper"] = tab.tenor.map(cm2)
    tab["ratio_to_cm2"] = (tab.hs_median / tab.cm2_upper).round(1)
    print(f"=== Roll half-spread as heterogeneity is removed ({len(files)} days sampled) ===")
    print(tab.round(3).to_string(index=False))

    print("\n=== median across tenors, by level ===")
    for lvl in sorted(df["level"].unique()):
        s = tab[tab.level == lvl]
        print(f"  {lvl:<24} hs_median {s.hs_median.median():7.3f}bp   "
              f"vs CM-2 upper ~0.45bp -> {s.hs_median.median() / 0.45:6.1f}x   "
              f"(median n per cell {s.median_n.median():.0f})")

    (OUT / "cm3_homogeneity.json").write_text(
        json.dumps(tab.round(4).to_dict("records"), indent=2, default=str), encoding="utf-8")
    print("\nwrote cm3_homogeneity.parquet + cm3_homogeneity.json")


if __name__ == "__main__":
    main()
