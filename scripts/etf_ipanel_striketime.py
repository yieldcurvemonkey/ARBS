r"""What moment is FedInvest's daily file struck at? Identified from segment returns.

Why the first tie-out was not enough
------------------------------------
``etf_ipanel_tieout.py`` ranked timestamps by how closely Citi's cross-section matches
FedInvest's, and got 12:00 by a 2.2% margin on both layers -- not the 15:00 structural
prior. That statistic is **confounded**: RMSE(citi - fed) mixes "is this the right
moment" with "how noisy is Citi's own cross-section right now", and Citi's marks are
quietest at midday. A metric that is minimised at midday whatever the true strike time
cannot identify the strike time, and a 2.2% margin over the neighbouring hour is exactly
what a smooth intraday noise profile looks like.

The identified test
-------------------
A daily mark struck at time ``T`` contains every move up to ``T`` and none after it. So
regress FedInvest's day-over-day yield change on the SEGMENTS of Citi's intraday path:

    d(fed)_t  =  a + b_0 * overnight_t + b_1 * seg(09:30->10:00)_t + ... + e_t

Segments before the strike must load at **b ~ 1**; segments after it at **b ~ 0**. The
strike is where the coefficients fall off the cliff. This is an identification, not a
ranking: it does not care how noisy any hour is, only whether that hour's move is
*inside* FedInvest's day. The segments are near-orthogonal (intraday returns are close
to serially uncorrelated) so the coefficients are separately estimable.

Two readings are run, and they answer different questions:

* **level** -- the cross-sectional mean yield, one series. Asks when the MARKET move
  stops entering FedInvest.
* **pooled per bond** -- every bond-day. Same question with 40x the data and a
  cross-sectionally correlated error, so its standard errors are date-clustered.

The same regression is run on the hourly layer's seven years as a replication.
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


def ols_cluster(y: np.ndarray, X: np.ndarray, groups: np.ndarray | None = None):
    """OLS with (optionally) one-way cluster-robust standard errors."""
    A = np.column_stack([np.ones(len(y)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ beta
    XtXi = np.linalg.pinv(A.T @ A)
    if groups is None:
        s2 = float(r @ r) / max(1, len(y) - A.shape[1])
        V = s2 * XtXi
    else:
        meat = np.zeros((A.shape[1], A.shape[1]))
        for g in np.unique(groups):
            m = groups == g
            u = A[m].T @ r[m]
            meat += np.outer(u, u)
        V = XtXi @ meat @ XtXi
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    ss_res = float(r @ r)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return beta, se, 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan


def segment_test(marks: pd.DataFrame, fed: pd.DataFrame, times: list[str],
                 label: str) -> pd.DataFrame:
    """``marks``: date, cusip, mark_time, ytm (percent). ``fed``: date, cusip, ytm_fed."""
    w = marks.pivot_table(index=["date", "cusip"], columns="mark_time", values="ytm")
    w = w[[t for t in times if t in w.columns]].dropna()
    f = fed.set_index(["date", "cusip"])["ytm_fed"]
    w = w.join(f, how="inner").dropna()
    w = w.reset_index().sort_values(["cusip", "date"])

    # Previous PANEL row for the same bond, and only when it is the previous business
    # day: the minute layer is warmed in month-turn blocks, so consecutive rows can be
    # a month apart, and a "daily change" across a block boundary is a month of market.
    g = w.groupby("cusip")
    prev_date = g["date"].shift(1)
    has_prev = prev_date.notna()
    gap_bd = np.full(len(w), -1, dtype=int)
    gap_bd[has_prev.to_numpy()] = np.busday_count(
        prev_date[has_prev].values.astype("datetime64[D]"),
        w.loc[has_prev.to_numpy(), "date"].values.astype("datetime64[D]"))
    ok = pd.Series(gap_bd == 1, index=w.index) & has_prev

    cols = [t for t in times if t in w.columns]
    d_fed = (w["ytm_fed"] - g["ytm_fed"].shift(1)) * 100.0
    overnight = (w[cols[0]] - g[cols[-1]].shift(1)) * 100.0
    segs = {"overnight": overnight}
    for a, b in zip(cols[:-1], cols[1:]):
        segs[f"{a}->{b}"] = (w[b] - w[a]) * 100.0

    S = pd.DataFrame(segs)
    keep = ok & d_fed.notna() & S.notna().all(axis=1)
    S, d_fed, dates = S[keep], d_fed[keep], w.loc[keep, "date"]

    rows = []
    # ---- level: the cross-sectional mean, one observation per date
    lvl = S.groupby(dates.values).mean()
    ylvl = d_fed.groupby(dates.values).mean()
    b, se, r2 = ols_cluster(ylvl.to_numpy(), lvl.to_numpy())
    for name, coef, s in zip(["const"] + list(S.columns), b, se):
        rows.append({"layer": label, "spec": "level", "term": name,
                     "coef": coef, "se": s, "t": coef / s if s > 0 else np.nan,
                     "n": len(ylvl), "r2": r2})
    # ---- pooled per bond, date-clustered
    b, se, r2 = ols_cluster(d_fed.to_numpy(), S.to_numpy(), dates.to_numpy())
    for name, coef, s in zip(["const"] + list(S.columns), b, se):
        rows.append({"layer": label, "spec": "pooled (date-clustered)", "term": name,
                     "coef": coef, "se": s, "t": coef / s if s > 0 else np.nan,
                     "n": len(d_fed), "r2": r2})
    return pd.DataFrame(rows)


def main() -> int:
    pd.set_option("display.width", 240)

    p = IP.load_panel("MI01")
    d = BP.load()
    d = d[d["cusip"].isin(set(p["cusip"])) & d["ytm"].notna() & d["price_source"].eq("mid")]
    fed = d[["date", "cusip", "ytm", "ttm", "cpn"]].rename(columns={"ytm": "ytm_fed"})

    m = p[p["is_fresh"] & p["ytm"].notna()][["date", "cusip", "mark_time", "ytm"]]
    t1 = segment_test(m, fed[["date", "cusip", "ytm_fed"]], list(IP.MARK_TIMES),
                      "MI01 (11 marks, 2021-2026)")

    # hourly replication over seven years
    uni = ID.universe()
    meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip"]]
    frame = ID.drop_impossible(ID.hourly_frame("YIELD"), "YIELD")
    hrs = []
    for hour in range(9, 18):
        sub = ID.ny_marks(frame, hour)
        long = sub.stack().rename("ytm").reset_index()
        long.columns = ["date", "isin", "ytm"]
        long = long.merge(meta, on="isin", how="left")
        long["mark_time"] = f"{hour:02d}:00"
        hrs.append(long[["date", "cusip", "mark_time", "ytm"]])
    hm = pd.concat(hrs, ignore_index=True).dropna()
    t2 = segment_test(hm, fed[["date", "cusip", "ytm_fed"]],
                      [f"{h:02d}:00" for h in range(9, 18)], "HOURLY (9 marks, 7y)")

    tab = pd.concat([t1, t2], ignore_index=True)
    print("SEGMENT-LOADING TEST -- does this slice of the day enter FedInvest's mark?")
    print("(coef ~1 = inside FedInvest's day; coef ~0 = after its strike)\n")
    for (layer, spec), g in tab.groupby(["layer", "spec"], sort=False):
        print(f"--- {layer} | {spec} | n={int(g['n'].iloc[0]):,} R2={g['r2'].iloc[0]:.4f}")
        print(g[g["term"].ne("const")][["term", "coef", "se", "t"]]
              .round(4).to_string(index=False))
        print()
    tab.to_csv(DATA / "ipanel_striketime_segments.csv", index=False)

    # ------------------------------------------------ the 0.89-vs-0.434 attribution
    #
    # Citi's band-matched cross-sectional richness dispersion is 0.89 bp against the
    # daily study's 0.434 bp on FedInvest. Either Citi carries information FedInvest
    # smooths away, or Citi adds mark noise. RMSE(citi - fed) cannot tell them apart;
    # these two can.
    fedb = fed[fed["ttm"].ge(19.0) & fed["cpn"].notna()].copy()
    n = fedb.groupby("date")["cusip"].transform("size")
    fedb = fedb[n >= IP.MIN_BONDS_PER_FIT]
    rf = CV.fit_residuals(fedb.rename(columns={"ytm_fed": "ytm"})[
        ["date", "cusip", "ytm", "ttm", "cpn"]].copy(), **IP.CURVE_CFG)
    rf = rf.rename(columns={"resid_bp": "resid_fed"})[["date", "cusip", "resid_fed"]]

    rows = []
    for mt in ("12:00", "15:00", "16:00"):
        c = p[p["is_fresh"] & p["mark_time"].eq(mt)][["date", "cusip", "resid_bp_tlt19"]]
        j = c.merge(rf, on=["date", "cusip"], how="inner").dropna()
        if j.empty:
            continue
        per = j.groupby("date")
        sd_c = per["resid_bp_tlt19"].std()
        sd_f = per["resid_fed"].std()
        cov = per.apply(lambda x: float(np.cov(x["resid_bp_tlt19"], x["resid_fed"])[0, 1]),
                        include_groups=False)
        cor = per.apply(lambda x: float(np.corrcoef(x["resid_bp_tlt19"], x["resid_fed"])[0, 1]),
                        include_groups=False)
        # per-bond persistence of the SOURCE DIFFERENCE, cross-sectionally demeaned
        j["diff"] = j["resid_bp_tlt19"] - j["resid_fed"]
        j["diff"] = j["diff"] - j.groupby("date")["diff"].transform("mean")
        piv = j.pivot_table(index="date", columns="cusip", values="diff").sort_index()
        ac1 = piv.apply(lambda s: s.dropna().autocorr(1)).dropna()
        common = float(np.sqrt(max(0.0, cov.median())))
        rows.append({
            "mark_time": mt, "dates": int(len(sd_c)),
            "citi_resid_sd_bp": float(sd_c.median()),
            "fed_resid_sd_bp": float(sd_f.median()),
            "corr_median": float(cor.median()),
            "common_component_sd_bp": common,
            "citi_only_sd_bp": float(np.sqrt(max(0.0, sd_c.median() ** 2 - common ** 2))),
            "fed_only_sd_bp": float(np.sqrt(max(0.0, sd_f.median() ** 2 - common ** 2))),
            "source_diff_autocorr_1d_median": float(ac1.median()),
        })
    att = pd.DataFrame(rows)
    print("ATTRIBUTION of the Citi-vs-FedInvest richness dispersion gap "
          "(ttm>=19y fit, both sides):")
    print(att.round(4).to_string(index=False))
    att.to_csv(DATA / "ipanel_dispersion_attribution.csv", index=False)
    print("\nwrote ipanel_striketime_segments.csv, ipanel_dispersion_attribution.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
