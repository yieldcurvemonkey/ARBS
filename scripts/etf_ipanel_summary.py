r"""Consolidate every headline number, and verify the panel against its own documentation.

The second half is the part that matters: a column dictionary that has drifted from the
file it documents is worse than no dictionary, because it is believed.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402

DATA = IP.DATA


def main() -> int:
    pd.set_option("display.width", 220)
    p = IP.load_panel("MI01")

    # ------------------------------------------------------ documentation vs reality
    doc, actual = set(IP.PANEL_COLUMNS), set(p.columns)
    missing_doc = sorted(actual - doc)
    stale_doc = sorted(doc - actual)
    print(f"PANEL {len(p):,} rows x {len(p.columns)} columns")
    print(f"  columns in the file but NOT documented : {missing_doc or 'none'}")
    print(f"  columns documented but NOT in the file : {stale_doc or 'none'}")
    if missing_doc or stale_doc:
        print("  ^^ FIX BEFORE SHIPPING")

    rows = []
    A = rows.append
    A(("panel", "rows", len(p), "count", "ipanel_mi01.parquet"))
    A(("panel", "dates", p["date"].nunique(), "count", "ipanel_mi01.parquet"))
    A(("panel", "cusips", p["cusip"].nunique(), "count", "ipanel_mi01.parquet"))
    A(("panel", "mark times", p["mark_time"].nunique(), "count", "ipanel_mi01.parquet"))
    A(("panel", "date floor", str(p["date"].min().date()), "", "ipanel_mi01.parquet"))
    A(("panel", "date ceiling", str(p["date"].max().date()), "", "ipanel_mi01.parquet"))
    A(("panel", "bond-days with a resolved yield", int(p["ytm"].notna().sum()),
       "count", "ipanel_mi01.parquet"))
    A(("panel", "of those fresh (both legs <=30 min)", int(p["is_fresh"].sum()),
       "count", "ipanel_mi01.parquet"))
    A(("panel", "yields refused by the long-end gate", int(p["ytm_gate_fail"].sum()),
       "count", "ipanel_mi01.parquet"))

    rep = pd.read_csv(DATA / "ipanel_reproduce_seam.csv")
    A(("validation", "worst disagreement vs the backfill's independent seam code",
       float(rep["abs_diff_bp"].max()), "bp", "ipanel_reproduce_seam.csv"))
    A(("validation", "seam windows reproduced exactly", int((rep["abs_diff_bp"] < 1e-9).sum()),
       f"of {len(rep)}", "ipanel_reproduce_seam.csv"))

    st = pd.read_csv(DATA / "ipanel_staleness.csv")
    y = st[st["value"].eq("YIELD")].set_index("mark_time")
    for mt in ("09:30", "12:00", "15:00", "16:00", "16:15"):
        A(("staleness", f"{mt} median minutes stale", float(y.loc[mt, "median_min"]),
           "min", "ipanel_staleness.csv"))
        A(("staleness", f"{mt} fraction more than 30 min stale",
           float(y.loc[mt, "frac_gt_30m"]), "frac", "ipanel_staleness.csv"))

    ri = pd.read_csv(DATA / "ipanel_richness_by_mark.csv").set_index("mark_time")
    for mt in ("12:00", "15:00", "16:00"):
        A(("richness", f"{mt} xsec sd, all bonds (ttm 9.5-30y fit)",
           float(ri.loc[mt, "resid_bp_sd_median"]), "bp", "ipanel_richness_by_mark.csv"))
        A(("richness", f"{mt} xsec sd, ttm>=19y fit (comparable with 0.434)",
           float(ri.loc[mt, "resid_bp_tlt19_sd_median"]), "bp",
           "ipanel_richness_by_mark.csv"))

    at = pd.read_csv(DATA / "ipanel_dispersion_attribution.csv").set_index("mark_time")
    A(("attribution", "Citi xsec richness sd (ttm>=19y)",
       float(at.loc["12:00", "citi_resid_sd_bp"]), "bp", "ipanel_dispersion_attribution.csv"))
    A(("attribution", "FedInvest xsec richness sd, SAME bonds/dates/fit",
       float(at.loc["12:00", "fed_resid_sd_bp"]), "bp", "ipanel_dispersion_attribution.csv"))
    A(("attribution", "cross-sectional correlation of the two sources' richness",
       float(at.loc["12:00", "corr_median"]), "", "ipanel_dispersion_attribution.csv"))
    A(("attribution", "common component sd",
       float(at.loc["12:00", "common_component_sd_bp"]), "bp",
       "ipanel_dispersion_attribution.csv"))

    step = pd.read_csv(DATA / "ipanel_striketime_step.csv")
    tw = pd.read_csv(DATA / "ipanel_striketime_twoday.csv")
    h = tw[tw["layer"].str.startswith("HOURLY") & tw["spec"].eq("level")].set_index("term")
    A(("strike time", "HOURLY: day-t 11:00->12:00 loading",
       float(h.loc["t   11:00->12:00", "coef"]), "coef", "ipanel_striketime_twoday.csv"))
    A(("strike time", "HOURLY: day-(t-1) 11:00->12:00 loading",
       float(h.loc["t-1 11:00->12:00", "coef"]), "coef", "ipanel_striketime_twoday.csv"))
    A(("strike time", "the two halves sum to (1.00 = internally consistent)",
       float(h.loc["t   11:00->12:00", "coef"] + h.loc["t-1 11:00->12:00", "coef"]),
       "", "ipanel_striketime_twoday.csv"))
    frac = float(h.loc["t   11:00->12:00", "coef"])
    A(("strike time", "implied strike, day-t side", f"11:{int(round(frac*60)):02d} NY",
       "", "ipanel_striketime_twoday.csv"))
    frac2 = 1.0 - float(h.loc["t-1 11:00->12:00", "coef"])
    A(("strike time", "implied strike, day-(t-1) side", f"11:{int(round(frac2*60)):02d} NY",
       "", "ipanel_striketime_twoday.csv"))
    A(("strike time", "mean loading, day-t segments after 12:00",
       float(step[step["layer"].str.startswith("HOURLY")
                  & step["spec"].eq("level")]["mean_coef_day_t_last4"].iloc[0]),
       "coef", "ipanel_striketime_step.csv"))

    dc = pd.read_csv(DATA / "ipanel_striketime_dailycorr.csv")
    for lab in ("MI01 (2021-2026)", "HOURLY (2019-2026)"):
        s = dc[dc["layer"].eq(lab)].sort_values("corr_level", ascending=False)
        A(("strike time", f"{lab}: peak daily-change corr at",
           f"{s.iloc[0]['mark_time']} ({s.iloc[0]['corr_level']:.4f})", "",
           "ipanel_striketime_dailycorr.csv"))

    to = pd.read_csv(DATA / "ipanel_fedinvest_tieout.csv")
    for lab in to["layer"].unique():
        s = to[to["layer"].eq(lab)].sort_values("xsec_rmse_bp_median")
        A(("tie-out", f"{lab}: min xsec RMSE at",
           f"{s.iloc[0]['mark_time']} ({s.iloc[0]['xsec_rmse_bp_median']:.4f} bp), "
           f"runner-up {s.iloc[1]['mark_time']} ({s.iloc[1]['xsec_rmse_bp_median']:.4f})",
           "", "ipanel_fedinvest_tieout.csv"))

    fq = pd.read_csv(DATA / "ipanel_fedinvest_quality.csv", index_col=0)["value"]
    for k, u in (("fed_level_sd_bp", "bp"), ("citi_level_sd_bp", "bp"),
                 ("fed_level_autocorr1", ""), ("citi_level_autocorr1", ""),
                 ("corr_1d", ""), ("corr_2d", ""), ("corr_5d", ""),
                 ("fed_px_unchanged_frac", "frac"), ("citi_px_unchanged_frac", "frac"),
                 ("whole_file_stale_days", "count")):
        A(("fedinvest quality", k, float(fq[k]), u, "ipanel_fedinvest_quality.csv"))

    ch = pd.read_csv(DATA / "ipanel_cost_headline.csv", index_col=0)["value"]
    for k in ch.index:
        A(("cost", k, float(ch[k]), "bp" if "bp" in k else "", "ipanel_cost_headline.csv"))
    rf = pd.read_csv(DATA / "ipanel_roll_floor_headline.csv").iloc[0]
    for k in ("sigma_price_bp_measured", "floor_median_price_bp", "floor_p90_price_bp",
              "roll_price_bp_median", "roll_over_floor", "frac_zero_change"):
        A(("cost", f"roll: {k}", float(rf[k]), "", "ipanel_roll_floor_headline.csv"))
    A(("cost", "roll: median estimate exceeds its p90 noise floor",
       str(bool(rf["above_p90_floor"])), "", "ipanel_roll_floor_headline.csv"))

    s = pd.DataFrame(rows, columns=["section", "metric", "value", "unit", "source"])
    s.to_csv(DATA / "ipanel_SUMMARY.csv", index=False)
    print("\n" + s.to_string(index=False))
    print("\nwrote ipanel_SUMMARY.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
