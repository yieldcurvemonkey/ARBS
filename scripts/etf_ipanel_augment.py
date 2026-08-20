r"""Refit the panel's three curve variants and rewrite the coverage/richness tables.

The build's first pass fitted the curve to every bond that priced. That fit spans ttm
9.5 to 30 years, because the universe is "ever held by TLT since 2021" and a bond bought
at 20 years is now 15. A cubic across twenty years of maturity leaves curve SHAPE in its
residual, and the resulting 1.64 bp cross-sectional dispersion is not comparable with the
daily study's 0.434 bp, which came from a 20-30y fit. This adds the band-matched variant
so the comparison is like for like, and states the gap that remains.
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
    pd.set_option("display.width", 240)
    path = DATA / "ipanel_mi01.parquet"
    p = pd.read_parquet(path)
    p["date"] = pd.to_datetime(p["date"])
    print(f"loaded {len(p):,} rows", flush=True)

    p = IP.add_fit_variants(p)
    p.to_parquet(path, index=False)
    print(f"rewrote {path}", flush=True)

    pd.DataFrame({"column": list(IP.PANEL_COLUMNS),
                  "meaning": list(IP.PANEL_COLUMNS.values())}
                 ).to_csv(DATA / "ipanel_columns.csv", index=False)

    # ---------------------------------------------------------------- coverage, fixed
    # The first pass mixed two freshness definitions in one table (one leg vs both).
    # Every column here is on the YIELD leg, and the both-legs column says so.
    rows = []
    for mt, g in p.groupby("mark_time"):
        y = g["ytm"].notna()
        gy = g[y]
        rows.append({
            "mark_time": mt,
            "dates": int(g["date"].nunique()),
            "bond_days_resolved": int(y.sum()),
            "frac_print_at_mark": float(gy["stale_min_ytm"].eq(0).mean()),
            "frac_yield_fresh_5m": float(gy["stale_min_ytm"].le(5).mean()),
            "frac_yield_fresh_30m": float(gy["stale_min_ytm"].le(30).mean()),
            "frac_both_legs_fresh_30m": float(gy["is_fresh"].mean()),
            "bond_days_fresh_30m": int(gy["is_fresh"].sum()),
            "bonds_median_per_date": float(gy.groupby("date").size().median()),
        })
    cov = pd.DataFrame(rows).sort_values("mark_time")
    print("\nCOVERAGE (freshness always on the YIELD leg unless the name says otherwise):")
    print(cov.round(4).to_string(index=False))
    cov.to_csv(DATA / "ipanel_coverage.csv", index=False)

    # ------------------------------------------------------- richness, three variants
    fr = p[p["is_fresh"]]
    rows = []
    for mt, g in fr.groupby("mark_time"):
        rec = {"mark_time": mt}
        for col in IP.FIT_VARIANTS:
            sd = g.groupby("date")[col].std()
            rec[f"{col}_sd_median"] = float(sd.median())
            rec[f"{col}_dates"] = int(sd.notna().sum())
            rec[f"{col}_bonds_med"] = float(g[g[col].notna()].groupby("date").size().median())
        rec["tlt19_vs_daily_0434"] = rec["resid_bp_tlt19_sd_median"] / DAILY_RICHNESS_SD_BP
        rec["tlt19_vs_fly_cost"] = rec["resid_bp_tlt19_sd_median"] / FLY_ROUND_TRIP_BP
        rows.append(rec)
    rich = pd.DataFrame(rows).sort_values("mark_time")
    print("\nCROSS-SECTIONAL RICHNESS DISPERSION (bp), refitted at every timestamp:")
    print(rich.round(4).to_string(index=False))
    rich.to_csv(DATA / "ipanel_richness_by_mark.csv", index=False)

    # ---------------------------------- persistence: is the residual signal or noise?
    # curve.residual_quality's own band for a genuine per-bond richness series is
    # lag-1 autocorrelation 0.85-0.99. Near zero means pricing noise, and a
    # mean-reversion signal fitted to noise reverts beautifully in sample.
    rows = []
    for col in IP.FIT_VARIANTS:
        sub = fr[fr["mark_time"].eq("15:00")][["date", "cusip", col]].dropna()
        piv = sub.pivot_table(index="date", columns="cusip", values=col).sort_index()
        ac1 = piv.apply(lambda c: c.dropna().autocorr(1)).dropna()
        rows.append({"variant": col, "bonds": int(len(ac1)),
                     "autocorr_1day_median": float(ac1.median()),
                     "ts_sd_bp_median": float(piv.std().median())})
    q = pd.DataFrame(rows)
    print("\nRESIDUAL PERSISTENCE at 15:00 (repo's band for a genuine series: 0.85-0.99):")
    print(q.round(4).to_string(index=False))
    q.to_csv(DATA / "ipanel_residual_quality.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
