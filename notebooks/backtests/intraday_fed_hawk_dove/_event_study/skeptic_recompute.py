"""INDEPENDENT skeptic recompute. Deliberately does NOT import c_common.py
(that is the code under review). Uses statsmodels cluster covariance plus a
fully transparent day-mean collapse as two routes to the same t-stat.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
OUT = {}


def p(*a):
    print(" ".join(str(x) for x in a), flush=True)


def three_ts(v, day, tag):
    """naive iid t, statsmodels day-clustered t, and day-mean-collapse t."""
    v = np.asarray(v, float)
    day = np.asarray(day)
    ok = np.isfinite(v)
    v, day = v[ok], day[ok]
    n = v.size
    mean = float(v.mean())
    se_iid = float(v.std(ddof=1) / np.sqrt(n))
    X = np.ones((n, 1))
    r_iid = sm.OLS(v, X).fit()
    r_cl = sm.OLS(v, X).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(day)[0]})
    se_cl = float(r_cl.bse[0])
    # transparent route: collapse to day means, plain one-sample t
    dm = pd.Series(v).groupby(pd.Series(day).values).mean()
    t_dm = float(dm.mean() / (dm.std(ddof=1) / np.sqrt(dm.size)))
    d = dict(tag=tag, n=int(n), n_days=int(dm.size), mean_bp=mean,
             se_iid=se_iid, t_iid=mean / se_iid,
             se_cluster=se_cl, t_cluster=mean / se_cl,
             se_ratio_cluster_over_iid=se_cl / se_iid,
             daymean_bp=float(dm.mean()), t_daymean_collapse=t_dm,
             sm_t_iid=float(r_iid.tvalues[0]), sm_t_cluster=float(r_cl.tvalues[0]))
    p(f"  {tag:<46} n={n:5d} days={dm.size:4d}  mean={mean:+.4f}bp  "
      f"t_iid={mean/se_iid:+.3f}  t_CLUSTER={mean/se_cl:+.3f}  "
      f"t_daymean={t_dm:+.3f}  SEratio={se_cl/se_iid:.3f}")
    return d


def main():
    ev = pd.read_parquet(HERE / "event_paths.parquet")
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    p(f"event_paths {ev.shape}  placebo_paths {pl.shape}")

    # ---- integrity: is signed_d_bp really d_rate * stance_sign? ----
    m = ev[ev["stance_sign"] != 0].copy()
    lhs = m["signed_d_bp"].to_numpy()
    rhs = (m["d_rate_bp_from_baseline"] * m["stance_sign"]).to_numpy()
    both = np.isfinite(lhs) & np.isfinite(rhs)
    p(f"CHECK signed_d_bp == d_rate*sign on {both.sum()} rows: "
      f"maxabs diff {np.nanmax(np.abs(lhs[both]-rhs[both])):.3e}; "
      f"NaN mismatch {int((np.isfinite(lhs)!=np.isfinite(rhs)).sum())}")
    OUT["identity_maxabs_diff"] = float(np.nanmax(np.abs(lhs[both] - rhs[both])))

    r3 = ev[ev["contract_rank"] == 3]
    sg = r3[r3["stance_sign"] != 0]
    p(f"rank3 signed rows {len(sg)}; unique events {sg['event_id'].nunique()}")
    p(f"overlap: overlapping events {ev[ev['is_overlapping']]['event_id'].nunique()}  "
      f"clean {ev[~ev['is_overlapping']]['event_id'].nunique()}")

    # =================================================================
    # HEADLINE 1: non-overlapping signed rank3 at +240
    # =================================================================
    p("")
    p("=" * 100)
    p("REQUIRED RECOMPUTE 1 - headline: rank3, signed, NON-OVERLAPPING, offset +240")
    p("=" * 100)
    h = sg[(~sg["is_overlapping"]) & (sg["offset_min"] == 240)].copy()
    h = h.dropna(subset=["signed_d_bp"])
    h["day"] = pd.to_datetime(h["date"].astype(str))
    p(f"reconcile: agent claims n=184 / 165 days.  I get n={len(h)} / {h['day'].nunique()} days")
    OUT["headline_n"] = int(len(h))
    OUT["headline_n_days"] = int(h["day"].nunique())
    OUT["headline_base"] = three_ts(h["signed_d_bp"], h["day"], "BASE (untrimmed)")

    # ---- required: top 1% of DAYS trimmed ----
    dm = h.groupby("day")["signed_d_bp"].mean()
    k = max(1, int(np.ceil(0.01 * dm.size)))
    worst = dm.abs().sort_values(ascending=False).head(k)
    p(f"\n  TRIM RULE: rank days by |day-mean signed move| at +240, drop the top 1% "
      f"= {k} of {dm.size} days")
    for d_, v_ in worst.items():
        p(f"     dropping {d_.date()}  day-mean {dm.loc[d_]:+.3f}bp  "
          f"(n={int((h['day']==d_).sum())} events)")
    OUT["trim_days_dropped"] = [str(d_.date()) for d_ in worst.index]
    ht = h[~h["day"].isin(worst.index)]
    OUT["headline_trim1pct_days"] = three_ts(ht["signed_d_bp"], ht["day"], "TRIM top 1% of DAYS (|day mean|)")

    # variant: trim top 1% of EVENTS by |signed move| (both tails)
    q = h["signed_d_bp"].abs().quantile(0.99)
    he = h[h["signed_d_bp"].abs() <= q]
    OUT["headline_trim1pct_events"] = three_ts(he["signed_d_bp"], he["day"], "TRIM top 1% of EVENTS (|move|)")

    # variant: one-sided trim of the largest POSITIVE days only (hardest test)
    worst_pos = dm.sort_values(ascending=False).head(k)
    hp = h[~h["day"].isin(worst_pos.index)]
    OUT["headline_trim1pct_pos_days"] = three_ts(hp["signed_d_bp"], hp["day"],
                                                 "TRIM top 1% most POSITIVE days")

    # ---- SVB week ----
    svb = (h["day"] >= "2023-03-06") & (h["day"] <= "2023-03-17")
    p(f"\n  SVB week 2023-03-06..17 in headline book: {int(svb.sum())} events "
      f"on {h.loc[svb,'day'].nunique()} days")
    OUT["svb_n_in_headline"] = int(svb.sum())
    if svb.sum():
        OUT["headline_ex_svb"] = three_ts(h.loc[~svb, "signed_d_bp"], h.loc[~svb, "day"], "EX SVB week")
    # share of squared variation carried by SVB week + by the top day
    ss = (h["signed_d_bp"] ** 2).sum()
    OUT["svb_share_sqvar_pct"] = float(100 * (h.loc[svb, "signed_d_bp"] ** 2).sum() / ss) if svb.sum() else 0.0
    top_ev = h["signed_d_bp"].abs().nlargest(1).index
    OUT["top1event_share_sqvar_pct"] = float(100 * (h.loc[top_ev, "signed_d_bp"] ** 2).sum() / ss)
    top5 = h["signed_d_bp"].abs().nlargest(5).index
    OUT["top5event_share_sqvar_pct"] = float(100 * (h.loc[top5, "signed_d_bp"] ** 2).sum() / ss)
    p(f"  share of TOTAL squared variation: SVB week {OUT['svb_share_sqvar_pct']:.1f}%  "
      f"single largest event {OUT['top1event_share_sqvar_pct']:.1f}%  top5 {OUT['top5event_share_sqvar_pct']:.1f}%")
    p(f"  kurtosis of signed_d_bp at +240: {stats.kurtosis(h['signed_d_bp'], fisher=True):.2f} (excess)")
    OUT["excess_kurtosis_240"] = float(stats.kurtosis(h["signed_d_bp"], fisher=True))

    # ---- 2025-04-09 tariff day ----
    tar = h["day"] == "2025-04-09"
    p(f"  2025-04-09 events in headline book: {int(tar.sum())}")
    if tar.sum():
        OUT["headline_ex_tariff"] = three_ts(h.loc[~tar, "signed_d_bp"], h.loc[~tar, "day"], "EX 2025-04-09 tariff day")

    # ---- robust location: median, trimmed, sign test, Wilcoxon ----
    p("")
    p("  DISTRIBUTION-ROBUST at +240 (headline book):")
    v = h["signed_d_bp"].to_numpy()
    med = float(np.median(v))
    tm = float(stats.trim_mean(v, 0.1))
    nz = v[v != 0]
    npos = int((nz > 0).sum())
    binom = stats.binomtest(npos, len(nz), 0.5)
    wil = stats.wilcoxon(v, zero_method="wilcox", alternative="two-sided")
    p(f"    median {med:+.4f}bp   10%-trimmed mean {tm:+.4f}bp   "
      f"zero-move share {100*(v==0).mean():.1f}%")
    p(f"    sign test on {len(nz)} nonzero: {npos} positive = {100*npos/len(nz):.1f}%  "
      f"binomial p={binom.pvalue:.3f}  CI95 {np.round(binom.proportion_ci(),3)}")
    p(f"    Wilcoxon signed-rank (IID, ignores day clustering): p={wil.pvalue:.3f}")
    OUT["headline_robust_240"] = dict(median_bp=med, trim10_mean_bp=tm,
                                      zero_share_pct=float(100 * (v == 0).mean()),
                                      n_nonzero=int(len(nz)), pct_positive=100 * npos / len(nz),
                                      sign_test_p=float(binom.pvalue),
                                      sign_ci=[float(x) for x in binom.proportion_ci()],
                                      wilcoxon_p=float(wil.pvalue))
    # day-clustered sign test: collapse to day-level sign of the day mean
    dsg = np.sign(h.groupby("day")["signed_d_bp"].mean())
    dsg = dsg[dsg != 0]
    b2 = stats.binomtest(int((dsg > 0).sum()), len(dsg), 0.5)
    p(f"    DAY-LEVEL sign test: {int((dsg>0).sum())}/{len(dsg)} days positive = "
      f"{100*(dsg>0).mean():.1f}%  p={b2.pvalue:.3f}")
    OUT["headline_day_sign_test"] = dict(n_days=int(len(dsg)), pct_pos=float(100 * (dsg > 0).mean()),
                                         p=float(b2.pvalue))

    # =================================================================
    # HEADLINE 2: all-events +5min hit rate (the one live positive)
    # =================================================================
    p("")
    p("=" * 100)
    p("REQUIRED RECOMPUTE 2 - the only nominal positive: all-events +5min hit rate")
    p("=" * 100)
    for tag, src in (("ALL events", sg), ("NON-OVERLAP", sg[~sg["is_overlapping"]])):
        a = src[src["offset_min"] == 5].dropna(subset=["signed_d_bp"]).copy()
        a["day"] = pd.to_datetime(a["date"].astype(str))
        mv = a[a["signed_d_bp"] != 0]
        hit = (mv["signed_d_bp"] > 0).astype(float)
        d = three_ts(hit - 0.5, mv["day"], f"{tag} +5min hit-0.5")
        p(f"    -> hit rate {100*(hit.mean()):.2f}%  on {len(mv)} moved of {len(a)} priced")
        bt = stats.binomtest(int(hit.sum()), len(hit), 0.5)
        p(f"    -> IID binomial p={bt.pvalue:.4f} (ignores clustering)")
        OUT[f"hit5_{tag.replace(' ','_').replace('-','_')}"] = dict(
            hit_pct=float(100 * hit.mean()), n_moved=int(len(mv)), n_priced=int(len(a)),
            t_cluster=d["t_cluster"], t_iid=d["t_iid"], binom_p_iid=float(bt.pvalue),
            n_days=d["n_days"])
        # mean move at +5 too
        three_ts(a["signed_d_bp"], a["day"], f"{tag} +5min MEAN signed move")

    # =================================================================
    # placebo sanity: is the matching real?
    # =================================================================
    p("")
    p("=" * 100)
    p("PLACEBO MATCH AUDIT")
    p("=" * 100)
    e1 = ev.drop_duplicates("event_id")
    p1 = pl.drop_duplicates("event_id")
    for col in ("weekday", "clock"):
        a = e1[col].value_counts(normalize=True)
        b = p1[col].value_counts(normalize=True)
        t = pd.DataFrame({"real": a, "fake": b}).fillna(0.0)
        p(f"  {col}: max |share gap| {100*(t['fake']-t['real']).abs().max():.2f} pp "
          f"over {len(t)} levels")
        OUT[f"placebo_{col}_max_gap_pp"] = float(100 * (t["fake"] - t["real"]).abs().max())
    ey = pd.to_datetime(e1["date"].astype(str)).dt.year.value_counts(normalize=True)
    py_ = pd.to_datetime(p1["date"].astype(str)).dt.year.value_counts(normalize=True)
    t = pd.DataFrame({"real": ey, "fake": py_}).fillna(0.0)
    p(f"  year: max |share gap| {100*(t['fake']-t['real']).abs().max():.2f} pp -> {t.round(3).to_dict()}")
    OUT["placebo_year_max_gap_pp"] = float(100 * (t["fake"] - t["real"]).abs().max())
    # placebo effective n: how many DISTINCT days does the band really rest on?
    p3 = pl[(pl["contract_rank"] == 3) & (pl["stance_sign"] != 0) & (pl["offset_min"] == 240)]
    p3 = p3.dropna(subset=["signed_d_bp"])
    p(f"  placebo at +240 rank3 signed: n={len(p3)} pseudo-events on "
      f"{pd.to_datetime(p3['date'].astype(str)).nunique()} DISTINCT DAYS "
      f"(the band's true dof is the day count, not the event count)")
    OUT["placebo_n_events_240"] = int(len(p3))
    OUT["placebo_n_days_240"] = int(pd.to_datetime(p3["date"].astype(str)).nunique())
    pp = p3.copy()
    pp["day"] = pd.to_datetime(pp["date"].astype(str))
    OUT["placebo_240"] = three_ts(pp["signed_d_bp"], pp["day"], "PLACEBO signed +240")

    # excess = real - placebo, day-clustered on the pooled stack
    stack = pd.concat([
        h.assign(real=1.0)[["signed_d_bp", "day", "real"]],
        pp.assign(real=0.0)[["signed_d_bp", "day", "real"]]])
    X = sm.add_constant(stack["real"].to_numpy())
    r = sm.OLS(stack["signed_d_bp"].to_numpy(), X).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(stack["day"])[0]})
    p(f"  EXCESS (real - placebo) at +240, day-clustered OLS: "
      f"{r.params[1]:+.4f} bp  t={r.tvalues[1]:+.3f}  p={r.pvalues[1]:.3f}")
    OUT["excess_real_minus_placebo_240"] = dict(coef=float(r.params[1]), t=float(r.tvalues[1]),
                                                p=float(r.pvalues[1]))

    (HERE / "skeptic_recompute.json").write_text(json.dumps(OUT, indent=1, default=float),
                                                 encoding="utf-8")
    p("\nwrote skeptic_recompute.json")


if __name__ == "__main__":
    main()
