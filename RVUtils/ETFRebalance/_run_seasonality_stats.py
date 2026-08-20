"""The numbers the seasonality captions quote, computed once and written to disk.

Three corrections live here rather than in the cell tables, because each one changes what
a cell t-statistic MEANS and none of them is visible in the table itself.

**A cell t against zero is partly measuring the LEVEL, not the season.**  The real spread
has an unconditional mean of about -0.026bp -- the backwards sign RESULTS.md §3.1 already
established -- while a within-stratum permutation has an unconditional mean of zero by
construction.  So "August is significant against zero" is partly "the whole series is
negative".  Every headline cell is therefore restated as a deviation from the series' own
unconditional mean, which is the only version that is about seasonality.

**The search is family-wide, not per-key.**  Selecting the strongest cell across business
day, day of month, day of week and month of year is a ~69-trial search.  The same 100
placebo series are read the same way, and the max over ALL keys within each draw is the
null the selection has to clear.  Per-key nulls understate it.

**Two funds that share a calendar are a stronger test than either alone.**  TLT and TLH
sit in adjacent maturity bands, reconstitute on the same day, and are priced off the same
FedInvest file.  A genuine calendar effect has to appear in both; a selected one has no
reason to.
"""

from __future__ import annotations

import json
import os
import pathlib

os.environ.setdefault("ARBS_ETF_HOLDINGS_DIR",
                      "C:/Users/chris/clee/ARBS/MDP/ETFHoldings/etf_holdings_cache")

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import _run_seasonality as S
from RVUtils.ETFRebalance import ic as IC

DATA = S.DATA
KEYS = ("bd_me", "dom", "dow", "moy")


def main() -> None:
    out: dict = {}

    for fund in ("TLT", "TLH"):
        sp = pd.read_parquet(DATA / f"seas_spread_thesis_{fund}.parquet")
        cal = pd.read_csv(DATA / f"seas_calendar_{fund}.csv", parse_dates=["date"])
        df = sp.merge(cal, on="date", how="left")
        f: dict = {}

        # ---- unconditional level of the spread, which every cell t is measured against
        v_all = df["real_10"].to_numpy(float)
        v_all = v_all[np.isfinite(v_all)]
        uncond = float(v_all.mean())
        f["uncond_bp"] = uncond
        f["uncond_t_hac"] = IC.newey_west_t(v_all, lags=9)
        f["n_dates"] = int(v_all.size)

        # ---- per-key real max, and the FAMILY-WISE placebo null across all four keys
        nl = pd.read_csv(DATA / f"seas_placebo_null_{fund}.csv")
        fam = nl.groupby("draw")["max_abs_t"].max().to_numpy()
        per_key = {}
        real_best_t, real_best = 0.0, None
        for k in KEYS:
            t = pd.read_csv(DATA / f"seas_cells_{fund}_{k}_h10.csv")
            if k == "bd_me":
                t = t[t["bd_me"].between(-10, 10)]
            i = t["t_hac"].abs().idxmax()
            mt = float(abs(t.loc[i, "t_hac"]))
            nn = nl[nl["key"] == k]["max_abs_t"].to_numpy()
            per_key[k] = {"cell": t.loc[i, k].item(), "mean_bp": float(t.loc[i, "mean_bp"]),
                          "t_hac": float(t.loc[i, "t_hac"]),
                          "plc_med": float(np.median(nn)), "plc_max": float(nn.max()),
                          "p_per_key": float((nn >= mt).mean())}
            if mt > real_best_t:
                real_best_t, real_best = mt, k
        f["per_key"] = per_key
        f["family"] = {
            "best_key": real_best, "best_t": real_best_t,
            "plc_med": float(np.median(fam)), "plc_p90": float(np.percentile(fam, 90)),
            "plc_max": float(fam.max()),
            "p_familywise": float((fam >= real_best_t).mean()),
            "n_draws": int(fam.size), "n_cells_searched": int(
                sum(len(pd.read_csv(DATA / f"seas_cells_{fund}_{k}_h10.csv")) for k in KEYS)),
        }

        # ---- the strongest cell restated as a DEVIATION from the unconditional level
        bk = real_best
        bt = pd.read_csv(DATA / f"seas_cells_{fund}_{bk}_h10.csv")
        if bk == "bd_me":
            bt = bt[bt["bd_me"].between(-10, 10)]
        bi = bt["t_hac"].abs().idxmax()
        bval = bt.loc[bi, bk].item()
        g = df[df[bk] == bval].sort_values("pos")
        v = g["real_10"].to_numpy(float)
        v = v[np.isfinite(v)]
        gap = float(np.median(np.diff(g.loc[np.isfinite(g["real_10"]), "pos"].to_numpy(float))))
        dev = v - uncond
        f["best_cell"] = {
            "key": bk, "value": bval, "n": int(v.size),
            "mean_bp": float(v.mean()), "t_vs_zero_hac": S._hac_t(v, gap, 10),
            "dev_bp": float(dev.mean()), "t_vs_level_hac": S._hac_t(dev, gap, 10),
        }

        # ---- year-by-year: does one year carry it?
        yb = pd.read_csv(DATA / f"seas_yearly_best_{fund}.csv")
        gy = df[df[bk] == bval]
        big = yb.reindex(yb["mean_bp"].abs().sort_values(ascending=False).index).iloc[0]
        ex = gy[gy["year"] != int(big["year"])].sort_values("pos")
        ve = ex["real_10"].to_numpy(float)
        ve = ve[np.isfinite(ve)]
        gape = float(np.median(np.diff(ex.loc[np.isfinite(ex["real_10"]), "pos"].to_numpy(float))))
        f["best_cell_ex_year"] = {
            "dropped_year": int(big["year"]), "dropped_mean_bp": float(big["mean_bp"]),
            "n": int(ve.size), "mean_bp": float(ve.mean()),
            "t_vs_zero_hac": S._hac_t(ve, gape, 10),
            "t_vs_level_hac": S._hac_t(ve - uncond, gape, 10),
            "years_same_sign": int((np.sign(yb["mean_bp"]) == np.sign(v.mean())).sum()),
            "years_total": int(len(yb)),
        }

        # ---- the pre/post month-end contrast, all four horizons, with its own null
        mc = []
        for h in S.HORIZONS:
            m = pd.read_csv(DATA / f"seas_me_contrast_{fund}_h{h}.csv")
            r = m[m["series"] == "real"].iloc[0]
            p = m[m["series"] != "real"]["t_hac"].abs().to_numpy()
            mc.append({"h": h, "n_cycles": int(r["n_cycles"]),
                       "pre_bp": float(r["pre_bp"]), "post_bp": float(r["post_bp"]),
                       "diff_bp": float(r["diff_bp"]), "t_hac": float(r["t_hac"]),
                       "plc_med": float(np.median(p)), "plc_max": float(p.max()),
                       "p": float((p >= abs(r["t_hac"])).mean())})
        f["me_contrast"] = mc

        # ---- dispersion, mean AND median (the pack's 0.81x headline is the MEDIAN)
        for k in ("bd_me", "moy"):
            dd = pd.read_csv(DATA / f"seas_disp_{fund}_{k}.csv")
            if k == "bd_me":
                dd = dd[dd[k].between(-10, 10)]
            f[f"disp_{k}"] = {
                "median_lo": float(dd["median"].min()), "median_hi": float(dd["median"].max()),
                "median_lo_cell": dd.loc[dd["median"].idxmin(), k].item(),
                "median_hi_cell": dd.loc[dd["median"].idxmax(), k].item(),
                "mean_lo": float(dd["mean"].min()), "mean_hi": float(dd["mean"].max()),
                "range_pct_of_median": float((dd["median"].max() / dd["median"].min() - 1) * 100),
            }

        # ---- measured cost, from the study's own table
        co = pd.read_csv(DATA / "multifund_cost.csv")
        co = co[co["fund"] == fund]
        f["fly_rt_bp_median"] = float(co["fly_rt_bp_med"].median())
        out[fund] = f

    # ---- cross-fund agreement, which is the strongest single test here
    a = pd.read_csv(DATA / "seas_cells_TLT_moy_h10.csv")[["moy", "mean_bp", "t_hac"]]
    b = pd.read_csv(DATA / "seas_cells_TLH_moy_h10.csv")[["moy", "mean_bp", "t_hac"]]
    m = a.merge(b, on="moy", suffixes=("_TLT", "_TLH"))
    da = pd.read_csv(DATA / "seas_disp_TLT_moy.csv")[["moy", "median"]]
    db = pd.read_csv(DATA / "seas_disp_TLH_moy.csv")[["moy", "median"]]
    dm = da.merge(db, on="moy", suffixes=("_TLT", "_TLH"))
    ab = pd.read_csv(DATA / "seas_cells_TLT_bd_me_h10.csv").query("-10<=bd_me<=10")[["bd_me", "mean_bp"]]
    bb = pd.read_csv(DATA / "seas_cells_TLH_bd_me_h10.csv").query("-10<=bd_me<=10")[["bd_me", "mean_bp"]]
    mb = ab.merge(bb, on="bd_me", suffixes=("_TLT", "_TLH"))
    # TLH's gated universe only reaches the 20-name minimum from 2022, so the profiles
    # above are measured over different windows. The comparison is repeated on the window
    # both funds actually cover -- a cross-fund disagreement measured on disjoint samples
    # would prove nothing.
    common = {}
    for f in ("TLT", "TLH"):
        s = pd.read_parquet(DATA / f"seas_spread_thesis_{f}.parquet")
        c = pd.read_csv(DATA / f"seas_calendar_{f}.csv", parse_dates=["date"])
        g = s.merge(c, on="date").query("year >= 2022")
        common[f] = g.groupby("moy")["real_10"].mean()
        common[f + "_n"] = int(len(g))
    cm = pd.concat([common["TLT"].rename("TLT"), common["TLH"].rename("TLH")], axis=1).dropna()
    out["cross_fund_common_window"] = {
        "window": "2022-01-01 onwards, the span TLH's gated universe covers",
        "n_dates_TLT": common["TLT_n"], "n_dates_TLH": common["TLH_n"],
        "moy_signal_corr": float(np.corrcoef(cm["TLT"], cm["TLH"])[0, 1]),
        "TLT_by_month_bp": {int(k): float(v) for k, v in cm["TLT"].items()},
        "TLH_by_month_bp": {int(k): float(v) for k, v in cm["TLH"].items()},
    }

    out["cross_fund"] = {
        "moy_signal_corr": float(np.corrcoef(m["mean_bp_TLT"], m["mean_bp_TLH"])[0, 1]),
        "bd_me_signal_corr": float(np.corrcoef(mb["mean_bp_TLT"], mb["mean_bp_TLH"])[0, 1]),
        "moy_dispersion_corr": float(np.corrcoef(dm["median_TLT"], dm["median_TLH"])[0, 1]),
        "tlt_best_month": int(m.loc[m["t_hac_TLT"].abs().idxmax(), "moy"]),
        "tlh_best_month": int(m.loc[m["t_hac_TLH"].abs().idxmax(), "moy"]),
        "tlt_at_tlh_best": float(m.loc[m["t_hac_TLH"].abs().idxmax(), "t_hac_TLT"]),
        "tlh_at_tlt_best": float(m.loc[m["t_hac_TLT"].abs().idxmax(), "t_hac_TLH"]),
        "disp_peak_month_TLT": int(dm.loc[dm["median_TLT"].idxmax(), "moy"]),
        "disp_peak_month_TLH": int(dm.loc[dm["median_TLH"].idxmax(), "moy"]),
    }

    # ---- the fund's own measured turnover, which is the part that IS seasonal
    fi = pd.read_csv(DATA / "seas_fund_intensity.csv", parse_dates=["date"])
    cal = pd.read_csv(DATA / "seas_calendar_ALL.csv", parse_dates=["date"])
    d = fi.merge(cal, on="date", how="left")
    d = d[d["gap_days"] <= 5]                      # a 4-day file gap is 4 days of trading
    # Normalise by the fund's own MEAN. Four of the twelve funds (GOVZ and three iBonds)
    # have a MEDIAN daily |d par/share| of exactly zero -- they barely trade -- and
    # dividing by it makes their normalised intensity infinite.
    d["norm"] = d["intensity"] / d.groupby("ticker")["intensity"].transform("mean")
    w = d[d["bd_me"].between(-10, 10)]
    prof = w.groupby("bd_me")["norm"].agg(["mean", "median", "size"])
    base = prof.loc[[b for b in prof.index if abs(b) > 3], "median"].median()
    # Per fund, the SHARE of its measured turnover that lands on the single month-end
    # day. A ratio of medians is the natural statistic and it is unusable here: four of
    # the twelve funds trade on fewer than half their days, so the denominator is exactly
    # zero and the multiple is infinite. A share of total turnover is bounded, needs no
    # denominator that can vanish, and has an exact no-seasonality benchmark: 1/21 of the
    # trading days in a month is 4.8%.
    tot = d.groupby("ticker")["intensity"].sum()
    me0 = d[d["bd_me"] == 0].groupby("ticker")["intensity"].sum()
    ndays = d.groupby("ticker")["intensity"].size()
    nme0 = d[d["bd_me"] == 0].groupby("ticker")["intensity"].size()
    per_fund = (me0 / tot).reindex(tot.index).fillna(0.0)
    expected = (nme0 / ndays).reindex(tot.index)
    dowp = w.groupby("dow")["norm"].median()
    out["flow"] = {
        "n_fund_days": int(len(fi)), "n_funds": int(fi["ticker"].nunique()),
        "me0_median": float(prof.loc[0, "median"]), "me1_median": float(prof.loc[1, "median"]),
        "me2_median": float(prof.loc[2, "median"]),
        "baseline_median": float(base),
        "me0_multiple": float(prof.loc[0, "median"] / base),
        "me1_multiple": float(prof.loc[1, "median"] / base),
        "me0_share_of_turnover": {k: float(v) for k, v in per_fund.sort_values().items()},
        "me0_share_expected": {k: float(v) for k, v in expected.items()},
        "me0_share_pooled": float(me0.sum() / tot.sum()),
        "me0_share_expected_pooled": float(nme0.sum() / ndays.sum()),
        "funds_above_expected": int((per_fund > expected).sum()),
        "funds_total": int(len(per_fund)),
        "dow_median_lo": float(dowp.min()), "dow_median_hi": float(dowp.max()),
        "dow_range_multiple": float(dowp.max() / dowp.min()),
    }

    p = DATA / "seas_headline_numbers.json"
    p.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {p}")


if __name__ == "__main__":
    main()
