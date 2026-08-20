r"""Build the timestamp-aware intraday UST panel and its coverage/staleness tables.

Writes, all under ``notebooks/backtests/etf_rebalance/_data``:

* ``ipanel_mi01.parquet``          the panel itself
* ``ipanel_columns.csv``           the column dictionary
* ``ipanel_coverage.csv``          bond-days resolved per mark time, and at what freshness
* ``ipanel_staleness.csv``         the staleness distribution per mark time
* ``ipanel_richness_by_mark.csv``  the cross-sectional richness dispersion per mark time
* ``ipanel_reproduce_seam.csv``    the independent-implementation tie-out
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402

DATA = IP.DATA
FLY_ROUND_TRIP_BP = 0.535
DAILY_RICHNESS_SD_BP = 0.434


def main() -> int:
    pd.set_option("display.width", 220)

    print("BUILDING ipanel_mi01 ...", flush=True)
    p = IP.build_panel(freq="MI01")

    # ------------------------------------------------------------------ dictionary
    pd.DataFrame({"column": list(IP.PANEL_COLUMNS),
                  "meaning": list(IP.PANEL_COLUMNS.values())}
                 ).to_csv(DATA / "ipanel_columns.csv", index=False)

    # ------------------------------------------------------------------- coverage
    rows = []
    n_days = p["date"].nunique()
    for mt, g in p.groupby("mark_time"):
        y = g["ytm"].notna()
        rows.append({
            "mark_time": mt,
            "dates": int(g["date"].nunique()),
            "bond_days_resolved": int(y.sum()),
            "bond_days_fresh_30m": int((y & g["is_fresh"]).sum()),
            "frac_fresh_30m": float((y & g["is_fresh"]).sum() / max(1, y.sum())),
            "frac_fresh_5m": float(((y & g["stale_min_ytm"].le(5)).sum()) / max(1, y.sum())),
            "frac_print_at_mark": float(((y & g["stale_min_ytm"].eq(0)).sum()) / max(1, y.sum())),
            "bonds_median_per_date": float(g[y].groupby("date").size().median()),
        })
    cov = pd.DataFrame(rows).sort_values("mark_time")
    print(f"\nCOVERAGE ({n_days:,} dates, {p['cusip'].nunique()} bonds):")
    print(cov.round(4).to_string(index=False))
    cov.to_csv(DATA / "ipanel_coverage.csv", index=False)

    # ------------------------------------------------------------------ staleness
    rows = []
    for mt, g in p.groupby("mark_time"):
        for col, lbl in (("stale_min_ytm", "YIELD"), ("stale_min_px", "PRICE")):
            s = g[col].dropna()
            if s.empty:
                continue
            rows.append({
                "mark_time": mt, "value": lbl, "n": int(len(s)),
                "mean_min": float(s.mean()), "median_min": float(s.median()),
                "p75_min": float(s.quantile(.75)), "p90_min": float(s.quantile(.90)),
                "p99_min": float(s.quantile(.99)), "max_min": float(s.max()),
                "frac_gt_30m": float((s > 30).mean()),
            })
    st = pd.DataFrame(rows).sort_values(["value", "mark_time"])
    print("\nSTALENESS (minutes the mark was carried forward):")
    print(st.round(3).to_string(index=False))
    st.to_csv(DATA / "ipanel_staleness.csv", index=False)

    # ------------------------------------------------- richness dispersion per mark
    fr = p[p["is_fresh"] & p["resid_bp"].notna()]
    rows = []
    for mt, g in fr.groupby("mark_time"):
        sd = g.groupby("date")["resid_bp"].std()
        sdb = g.groupby("date")["resid_bp_band"].std()
        rows.append({
            "mark_time": mt, "dates": int(sd.notna().sum()),
            "bonds_median": float(g.groupby("date").size().median()),
            "resid_sd_bp_median": float(sd.median()),
            "resid_sd_band_bp_median": float(sdb.median()),
            "fit_rmse_bp_median": float(g.groupby("date")["fit_rmse_bp"].first().median()),
            "vs_daily_0434": float(sd.median() / DAILY_RICHNESS_SD_BP),
            "vs_fly_round_trip": float(sd.median() / FLY_ROUND_TRIP_BP),
        })
    rich = pd.DataFrame(rows).sort_values("mark_time")
    print("\nCROSS-SECTIONAL RICHNESS DISPERSION, refitted at each timestamp:")
    print(rich.round(4).to_string(index=False))
    rich.to_csv(DATA / "ipanel_richness_by_mark.csv", index=False)

    # ------------------------------------------ tie-out to the backfill's own numbers
    #
    # An independent implementation of the same measurement must reproduce it. The
    # backfill's scripts/etf_seam_minute.py resolved its own as-of marks with a
    # different code path and reported xsec_sd_bp_median = 0.1217 bp for 15:00->16:00
    # (30-minute tolerance, dates carrying >=10 bonds). If this panel does not land on
    # that number, one of the two is wrong and neither should be trusted.
    ref = pd.read_csv(DATA / "intraday_seam_minute.csv").set_index("window")
    rows = []
    for lo, hi in (("15:00", "16:00"), ("14:00", "15:00"), ("16:00", "17:00"),
                   ("15:00", "15:30"), ("15:30", "16:00"), ("16:00", "16:15")):
        w = p[p["mark_time"].isin((lo, hi)) & p["stale_min_ytm"].le(30) & p["ytm"].notna()]
        piv = w.pivot_table(index=["date", "cusip"], columns="mark_time", values="ytm")
        piv = piv.dropna()
        d = ((piv[hi] - piv[lo]) * 100.0).unstack("cusip")
        d = d[d.notna().sum(axis=1) >= 10]
        key = f"{lo}->{hi}"
        got = float(d.std(axis=1).median())
        want = float(ref.loc[key, "xsec_sd_bp_median"]) if key in ref.index else np.nan
        rows.append({"window": key, "dates_here": int(len(d)),
                     "dates_backfill": int(ref.loc[key, "dates"]) if key in ref.index else -1,
                     "xsec_sd_bp_here": got, "xsec_sd_bp_backfill": want,
                     "abs_diff_bp": abs(got - want),
                     "mean_abs_move_bp_here": float(np.nanmean(np.abs(d.to_numpy())))})
    rep = pd.DataFrame(rows)
    print("\nINDEPENDENT-IMPLEMENTATION TIE-OUT vs intraday_seam_minute.csv:")
    print(rep.round(4).to_string(index=False))
    rep.to_csv(DATA / "ipanel_reproduce_seam.csv", index=False)
    worst = rep["abs_diff_bp"].max()
    print(f"\nworst absolute disagreement: {worst:.4f} bp "
          f"({'TIES OUT' if worst < 0.01 else 'DOES NOT TIE OUT - investigate'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
