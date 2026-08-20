r"""What time of day is FedInvest's "EOD"? Answered by tying Citi's clock to it.

The daily study marks everything from FedInvest's daily file and could never establish
what moment that file represents. Citi's tape can, because it carries the same bonds at
every minute of the day: whichever Citi timestamp reproduces FedInvest's cross-section
best is what FedInvest's EOD is.

The discriminator is DISPERSION, not level
------------------------------------------
FedInvest and Citi are different sources on different bases, so a constant offset
between them says nothing about the clock -- it is the same at 09:30 as at 17:00 and
cannot separate two timestamps. What separates them is the part of the difference that
varies ACROSS BONDS on a day: if Citi's 15:00 cross-section is FedInvest's cross-section
then the two disagree only by a common level, and the cross-sectionally demeaned
residual is small. So the primary statistic is

    median over dates of  RMSE_bonds( (citi - fed) - mean_bonds(citi - fed) )

in yield bp, and the secondary is the cross-sectional Spearman correlation between the
two sources' richness residuals, which cancels the level by construction and additionally
cancels the curve.

Eleven timestamps is a SEARCH, so it is counted and its winner is reported with the
margin over the runner-up. The structural prior stated in advance is 15:00, the hour US
cash Treasury desks mark; a winner at 15:00 confirms a prior, a winner at 11:17 would be
an artefact. The hourly layer re-runs the same contest over seven years instead of the
minute layer's five, through ``intraday.ny_marks`` so the start-stamp convention is
handled by the audited reader rather than by hand.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from RVUtils.ETFRebalance import bond_panel as BP  # noqa: E402
from RVUtils.ETFRebalance import curve as CV  # noqa: E402
from RVUtils.ETFRebalance import intraday as ID  # noqa: E402
from RVUtils.ETFRebalance import intraday_panel as IP  # noqa: E402

DATA = IP.DATA
MIN_BONDS = IP.MIN_BONDS_PER_FIT


def fed_reference(cusips: set[str]) -> pd.DataFrame:
    """FedInvest's daily panel for this universe, with the SAME curve fitted to it."""
    d = BP.load()
    d = d[d["cusip"].isin(cusips) & d["ytm"].notna() & d["cpn"].notna() & d["ttm"].gt(0)]
    d = d[d["price_source"].eq("mid")]        # two-sided quotes only, one consistent basis
    n = d.groupby("date")["cusip"].transform("size")
    d = d[n >= MIN_BONDS]
    r = CV.fit_residuals(d[["date", "cusip", "ytm", "ttm", "cpn"]].copy(), **IP.CURVE_CFG)
    return r.rename(columns={"ytm": "ytm_fed", "resid_bp": "resid_bp_fed"})[
        ["date", "cusip", "ytm_fed", "resid_bp_fed"]]


def contest(marks: pd.DataFrame, fed: pd.DataFrame, label: str) -> pd.DataFrame:
    """``marks``: date, cusip, mark_time, ytm, resid_bp. One row per candidate time."""
    j = marks.merge(fed, on=["date", "cusip"], how="inner")
    j["diff_bp"] = (j["ytm"] - j["ytm_fed"]) * 100.0
    rows = []
    for mt, g in j.groupby("mark_time"):
        wide = g.groupby("date")
        dem = g["diff_bp"] - wide["diff_bp"].transform("mean")
        rmse = np.sqrt((dem ** 2).groupby(g["date"]).mean())
        n_per_date = wide.size()
        rmse = rmse[n_per_date >= MIN_BONDS]
        sp = (g.dropna(subset=["resid_bp", "resid_bp_fed"])
                .groupby("date")[["resid_bp", "resid_bp_fed"]]
                .apply(lambda x: x["resid_bp"].corr(x["resid_bp_fed"], method="spearman")
                       if len(x) >= MIN_BONDS else np.nan).dropna())
        rows.append({
            "layer": label, "mark_time": mt,
            "dates": int(len(rmse)), "bond_days": int(len(g)),
            "level_diff_bp_median": float(g["diff_bp"].median()),
            "xsec_rmse_bp_median": float(rmse.median()),
            "xsec_rmse_bp_mean": float(rmse.mean()),
            "resid_spearman_median": float(sp.median()) if len(sp) else np.nan,
            "diff_sd_bp": float(g["diff_bp"].std()),
        })
    out = pd.DataFrame(rows).sort_values("mark_time").reset_index(drop=True)
    return out


def announce(tab: pd.DataFrame, label: str) -> dict:
    t = tab.dropna(subset=["xsec_rmse_bp_median"]).sort_values("xsec_rmse_bp_median")
    win, run = t.iloc[0], t.iloc[1]
    s = tab.dropna(subset=["resid_spearman_median"]).sort_values(
        "resid_spearman_median", ascending=False)
    print(f"\n{label}: {len(tab)} candidate timestamps evaluated.")
    print(f"  best cross-sectional agreement : {win['mark_time']}  "
          f"{win['xsec_rmse_bp_median']:.4f} bp")
    print(f"  runner-up                      : {run['mark_time']}  "
          f"{run['xsec_rmse_bp_median']:.4f} bp   "
          f"(margin {run['xsec_rmse_bp_median'] - win['xsec_rmse_bp_median']:+.4f} bp, "
          f"{100*(run['xsec_rmse_bp_median']/win['xsec_rmse_bp_median']-1):+.1f}%)")
    if len(s):
        print(f"  best richness Spearman         : {s.iloc[0]['mark_time']}  "
              f"{s.iloc[0]['resid_spearman_median']:.4f}")
    return {"winner": win["mark_time"], "winner_rmse": float(win["xsec_rmse_bp_median"]),
            "runner_up": run["mark_time"], "runner_rmse": float(run["xsec_rmse_bp_median"]),
            "spearman_winner": (s.iloc[0]["mark_time"] if len(s) else None)}


def main() -> int:
    pd.set_option("display.width", 240)

    p = IP.load_panel("MI01")
    cusips = set(p["cusip"])
    fed = fed_reference(cusips)
    print(f"FedInvest reference: {len(fed):,} bond-days, "
          f"{fed['date'].nunique():,} dates, {fed['cusip'].nunique()} bonds")

    # ------------------------------------------------------------------ minute layer
    m = p[p["is_fresh"] & p["ytm"].notna()][
        ["date", "cusip", "mark_time", "ytm", "resid_bp"]]
    t_mi = contest(m, fed, "MI01 (fresh <=30m)")
    print("\nMI01 LAYER -- Citi vs FedInvest by mark time:")
    print(t_mi.round(4).to_string(index=False))
    r_mi = announce(t_mi, "MI01 layer")

    # ------------------------------------------------------------------ hourly layer
    # Seven years instead of five, at the cost of only on-the-hour marks. ny_marks
    # applies ny_stamp, so asking for 16:00 really reads the bar stamped 15.
    uni = ID.universe()
    meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip", "maturity_date", "cpn"]]
    frame = ID.drop_impossible(ID.hourly_frame("YIELD"), "YIELD")
    rows = []
    for hour in range(9, 18):
        sub = ID.ny_marks(frame, hour)
        long = sub.stack().rename("ytm").reset_index()
        long.columns = ["date", "isin", "ytm"]
        long = long.merge(meta, on="isin", how="left")
        long["ttm"] = (long["maturity_date"] - long["date"]).dt.days / 365.25
        long = long[(long["ttm"] > 0) & long["ytm"].notna() & long["cpn"].notna()]
        n = long.groupby("date")["cusip"].transform("size")
        long = long[n >= MIN_BONDS]
        if long.empty:
            continue
        r = CV.fit_residuals(long[["date", "cusip", "ytm", "ttm", "cpn"]].copy(),
                             **IP.CURVE_CFG)
        r["mark_time"] = f"{hour:02d}:00"
        rows.append(r[["date", "cusip", "mark_time", "ytm", "resid_bp"]])
    hm = pd.concat(rows, ignore_index=True)
    t_hr = contest(hm, fed, "HOURLY (7y)")
    print("\nHOURLY LAYER (2019-11 .. 2026-08) -- Citi vs FedInvest by mark time:")
    print(t_hr.round(4).to_string(index=False))
    r_hr = announce(t_hr, "HOURLY layer")

    both = pd.concat([t_mi, t_hr], ignore_index=True)
    both.to_csv(DATA / "ipanel_fedinvest_tieout.csv", index=False)

    # ------------------------------------------ the winner, by year, as a stability check
    win = r_mi["winner"]
    mw = m[m["mark_time"].eq(win)].merge(fed, on=["date", "cusip"], how="inner")
    mw["diff_bp"] = (mw["ytm"] - mw["ytm_fed"]) * 100.0
    by_year = []
    for layer, src in (("MI01", mw),):
        for y, g in src.groupby(src["date"].dt.year):
            dem = g["diff_bp"] - g.groupby("date")["diff_bp"].transform("mean")
            rmse = np.sqrt((dem ** 2).groupby(g["date"]).mean())
            by_year.append({"layer": layer, "mark_time": win, "year": int(y),
                            "dates": int(g["date"].nunique()),
                            "level_diff_bp_median": float(g["diff_bp"].median()),
                            "xsec_rmse_bp_median": float(rmse.median())})
    yr = pd.DataFrame(by_year)
    print(f"\nWINNER ({win}) BY YEAR:")
    print(yr.round(4).to_string(index=False))
    yr.to_csv(DATA / "ipanel_fedinvest_tieout_by_year.csv", index=False)

    pd.DataFrame([{**{"layer": "MI01"}, **r_mi}, {**{"layer": "HOURLY"}, **r_hr},
                  {"layer": "candidates_evaluated",
                   "winner": f"MI01 {len(t_mi)} + HOURLY {len(t_hr)} = "
                             f"{len(t_mi) + len(t_hr)}"}]
                 ).to_csv(DATA / "ipanel_fedinvest_tieout_verdict.csv", index=False)
    print("\nwrote ipanel_fedinvest_tieout.csv, _by_year.csv, _verdict.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
