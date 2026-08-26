"""ONE SOURCE OF TRUTH for every corrected number the deck prints.

Four adversarial reviews landed on this deck.  Two of them changed the ANSWER
rather than the presentation:

  * reviewer 2 (k1-k7): the panel ships DAY release flags where WINDOW flags are
    needed.  28% of [-60,+240] windows contain a scheduled high/medium US macro
    release, and the whole positive composite lives in them.  Day fixed effects
    (hawk vs dove ON THE SAME DAY) kill it independently.
  * reviewer 3 (skeptic_*): the headline mean is three events.  Trimming the top
    1% of DAYS takes +0.3614 bp -> +0.0083 bp.

and two changed what the figures SAY:

  * reviewer 4 (crit_*): fig1's annotation box prints the signed-composite excess
    next to the hawk-dove gap as though it were that gap's placebo-adjusted
    version.  It is a different quantity, 1.9x smaller by construction.
  * reviewer 1 (z1-z4): the bar rule is causal and stricter than the brief asked;
    the leaky alternative would have inflated signed_30 by 6.3x.  That contrast
    belongs on the figure.

Reviewer 4 wrote its fig1b fix WITHOUT reviewer 2's release result.  Those two
must be reconciled, not stacked: the missing number is the RELEASE-CLEAN gap DiD,
computed here, and it decides the fig1b title.

Every clean cut is emitted NEXT TO its full-book number with both n's.  Nothing
is narrowed silently.

Run directly: executes the known-answer tests, then writes c5_fixes.json.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")
sys.path.append(str(HERE))

from c_common import OFFSETS, arm_paths, cluster_mean_se, cluster_ols, wide  # noqa: E402
from k1_release_window import (flag_windows, load_calendar, selftest_calendar,  # noqa: E402
                               selftest_flagger)

JSON_OUT = HERE / "c5_fixes.json"

# the two unlabelled macro contaminants the reviews named
TARIFF_DAY = pd.Timestamp("2025-04-09").date()
YEN_CARRY_DAY = pd.Timestamp("2024-08-05").date()


# ==========================================================================
# estimators
# ==========================================================================
def gap_at(piv, meta, o):
    """hawk - dove at offset o, day-clustered."""
    v = piv[o].to_numpy()
    hk = (meta["stance_sign"] == 1).to_numpy().astype(float)
    ok = np.isfinite(v)
    if ok.sum() < 4:
        return dict(coef=np.nan, t=np.nan, n=0)
    X = np.column_stack([np.ones(ok.sum()), hk[ok]])
    r = cluster_ols(v[ok], X, meta["date"].to_numpy()[ok], names=["const", "hawk"])
    return dict(coef=r["hawk"]["coef"], se=r["hawk"]["se"], t=r["hawk"]["t"], n=r["n"])


def gap_did(piv, meta, ppiv, pmeta, o):
    """DiD of the hawk-dove GAP: (hawk-dove | real) - (hawk-dove | placebo).

    This is the placebo-adjusted version of gap_at.  It is NOT the same quantity
    as excess_composite below, and printing the two in one sentence is the defect
    reviewer 4 found.
    """
    yr, yp = piv[o].to_numpy(), ppiv[o].to_numpy()
    hr = (meta["stance_sign"] == 1).to_numpy().astype(float)
    hp = (pmeta["stance_sign"] == 1).to_numpy().astype(float)
    y = np.concatenate([yr, yp])
    h = np.concatenate([hr, hp])
    real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
    day = np.concatenate([meta["date"].astype(str).to_numpy(),
                          pmeta["date"].astype(str).to_numpy()])
    ok = np.isfinite(y)
    X = np.column_stack([np.ones(ok.sum()), h[ok], real[ok], (h * real)[ok]])
    r = cluster_ols(y[ok], X, day[ok], names=["const", "hawk", "real", "hxr"])
    return dict(coef=r["hxr"]["coef"], se=r["hxr"]["se"], t=r["hxr"]["t"], n=r["n"])


def excess_composite(piv, meta, ppiv, pmeta, o):
    """signed composite, real minus placebo (the OTHER quantity)."""
    yr = piv[o].to_numpy() * meta["stance_sign"].to_numpy()
    yp = ppiv[o].to_numpy() * pmeta["stance_sign"].to_numpy()
    y = np.concatenate([yr, yp])
    real = np.concatenate([np.ones(len(yr)), np.zeros(len(yp))])
    day = np.concatenate([meta["date"].astype(str).to_numpy(),
                          pmeta["date"].astype(str).to_numpy()])
    ok = np.isfinite(y)
    X = np.column_stack([np.ones(ok.sum()), real[ok]])
    r = cluster_ols(y[ok], X, day[ok], names=["const", "is_real"])
    return dict(coef=r["is_real"]["coef"], se=r["is_real"]["se"],
                t=r["is_real"]["t"], n=r["n"])


def signed_mean(piv, meta, o):
    v = piv[o].to_numpy() * meta["stance_sign"].to_numpy()
    return cluster_mean_se(v, meta["date"].to_numpy())


def day_fe_slope(piv, meta, o):
    """stance_sign slope with DAY fixed effects: hawks vs doves on the SAME day.

    Identified only off days carrying both arms.  This is the within-day test
    that a market-wide drift cannot pass.
    """
    v = piv[o].to_numpy()
    s = meta["stance_sign"].to_numpy().astype(float)
    d = meta["date"].astype(str).to_numpy()
    ok = np.isfinite(v)
    v, s, d = v[ok], s[ok], d[ok]
    both = pd.Series(s).groupby(d).nunique()
    keep = np.isin(d, both[both > 1].index.to_numpy())
    if keep.sum() < 8:
        return dict(coef=np.nan, t=np.nan, n=0, n_id_days=0)
    v, s, d = v[keep], s[keep], d[keep]
    dm = pd.get_dummies(pd.Series(d), drop_first=True).to_numpy().astype(float)
    X = np.column_stack([np.ones(len(v)), s, dm])
    r = cluster_ols(v, X, d, names=["const", "stance"] + [f"d{i}" for i in range(dm.shape[1])])
    return dict(coef=r["stance"]["coef"], se=r["stance"]["se"], t=r["stance"]["t"],
                n=r["n"], n_id_days=int(pd.unique(d).size))


def trim_top_days(piv, meta, o, frac=0.01):
    """Drop the top `frac` of DAYS by |day-mean signed move| at offset o."""
    v = piv[o].to_numpy() * meta["stance_sign"].to_numpy()
    d = meta["date"].to_numpy()
    ok = np.isfinite(v)
    dm = pd.Series(v[ok]).groupby(pd.Series(d[ok]).values).mean()
    k = int(np.ceil(frac * dm.size))
    drop = dm.abs().sort_values(ascending=False).head(k).index.to_numpy()
    keep = ~np.isin(d, drop)
    r = cluster_mean_se(v[keep], d[keep])
    return r, [str(x) for x in drop], [float(dm.loc[x]) for x in drop]


# ==========================================================================
# known-answer tests -- an estimator that is itself wrong hides the thing it
# was built to find, so each one is pinned AND mutated.
# ==========================================================================
def _selftest():
    ok = True

    def chk(c, m):
        nonlocal ok
        print(("  OK   " if c else "  FAIL ") + m)
        ok = ok and bool(c)

    rng = np.random.default_rng(11)
    n_r, n_p = 3000, 6000
    INJ = 0.80  # bp of hawk-minus-dove, REAL book only

    def mk(n, inject, tag):
        sgn = rng.choice([1.0, -1.0], size=n)
        didx = rng.integers(0, 300, n)
        day = (pd.to_datetime("2024-01-01") + pd.to_timedelta(didx, "D")).date
        drift = rng.normal(0, 1.0, size=300)[didx]
        y = drift + rng.normal(0, 1.0, n) + (inject * (sgn > 0))
        piv = pd.DataFrame({240: y}, index=pd.RangeIndex(n))
        meta = pd.DataFrame({"stance_sign": sgn.astype(int), "date": day}, index=piv.index)
        return piv, meta

    # 1. gap_did recovers an effect injected into the REAL arm only
    rp, rm = mk(n_r, INJ, "real")
    pp, pm = mk(n_p, 0.0, "plac")
    got = gap_did(rp, rm, pp, pm, 240)
    chk(abs(got["coef"] - INJ) < 3 * got["se"],
        f"gap_did recovers a real-arm-only {INJ:+.2f} bp gap  "
        f"(got {got['coef']:+.4f} +/- {got['se']:.4f})")

    # 1b. MUTATION: injected into BOTH arms, the DiD must return ~0 while the
    #     raw gap still shows it -- proving the DiD really differences.
    pp2, pm2 = mk(n_p, INJ, "plac_inj")
    did2 = gap_did(rp, rm, pp2, pm2, 240)
    raw2 = gap_at(rp, rm, 240)
    chk(abs(did2["coef"]) < 2.5 * did2["se"] and raw2["coef"] > INJ / 2,
        f"mutation: injected into BOTH arms the DiD is {did2['coef']:+.4f} "
        f"(~0) while the raw gap is {raw2['coef']:+.4f} - the DiD differences")

    # 2. gap_did != excess_composite -- they are different regressands.
    exc = excess_composite(rp, rm, pp, pm, 240)
    chk(abs(exc["coef"] - got["coef"]) > 0.1,
        f"gap DiD {got['coef']:+.4f} and composite excess {exc['coef']:+.4f} are "
        f"DIFFERENT quantities (ratio {got['coef'] / exc['coef']:.2f}x) - "
        "the fig1 box conflated them")

    # 3. day_fe_slope: a pure market-wide DAY drift where the day's HAWK SHARE is
    #    correlated with that drift -- exactly the confound measured on the real
    #    panel (corr(hawk share of a month, that month's move) = +0.27).  Stance
    #    must vary WITHIN the day or there is nothing for FE to identify off, so
    #    the share (not the sign) carries the confound.
    ndays, per = 300, 6
    day = np.repeat(pd.date_range("2024-01-01", periods=ndays).date, per)
    drift_d = rng.normal(0, 3.0, ndays)
    drift = np.repeat(drift_d, per)
    p_hawk = 1.0 / (1.0 + np.exp(-drift_d / 2.0))          # hawk share tracks the drift
    sgn = np.where(rng.random(ndays * per) < np.repeat(p_hawk, per), 1.0, -1.0)
    y_conf = drift + rng.normal(0, 0.5, ndays * per)        # y knows nothing about stance
    piv = pd.DataFrame({240: y_conf})
    meta = pd.DataFrame({"stance_sign": sgn.astype(int), "date": day})
    naive = gap_at(piv, meta, 240)
    fe = day_fe_slope(piv, meta, 240)
    chk(abs(naive["t"]) > 4 and abs(fe["t"]) < 2.5,
        f"day FE kills a trend-assigns-stance confound  (naive t {naive['t']:+.2f} "
        f"-> FE t {fe['t']:+.2f})")

    # 3b. MUTATION: inject a genuine WITHIN-day effect; day FE must keep it.
    y_real = y_conf + 0.9 * sgn
    piv2 = pd.DataFrame({240: y_real})
    fe2 = day_fe_slope(piv2, meta, 240)
    chk(fe2["coef"] > 0.5 and fe2["t"] > 3,
        f"mutation: day FE RETAINS a genuine within-day +0.90 bp effect "
        f"(coef {fe2['coef']:+.4f}, t {fe2['t']:+.2f}) - it does not eat real signal")

    # 4. trim_top_days: a broad real effect must SURVIVE the trim; a
    #    three-outlier "effect" must not.
    n = 200
    day4 = pd.date_range("2024-01-01", periods=n).date
    sgn4 = rng.choice([1, -1], size=n)
    broad = pd.DataFrame({240: 1.0 * sgn4 + rng.normal(0, 1.0, n)})
    m4 = pd.DataFrame({"stance_sign": sgn4, "date": day4})
    rb, _, _ = trim_top_days(broad, m4, 240, 0.01)
    spike = np.zeros(n)
    spike[[3, 40, 111]] = 60.0 * sgn4[[3, 40, 111]]
    spk = pd.DataFrame({240: spike + rng.normal(0, 1.0, n)})
    rs, _, _ = trim_top_days(spk, m4, 240, 0.02)
    raw_s = cluster_mean_se(spk[240].to_numpy() * sgn4, day4)
    chk(rb["t"] > 5, f"trim KEEPS a broad +1.0 bp effect (t {rb['t']:+.2f})")
    chk(raw_s["mean"] > 0.5 and abs(rs["mean"]) < 0.35,
        f"mutation: trim REMOVES a 3-outlier pseudo-effect "
        f"({raw_s['mean']:+.3f} -> {rs['mean']:+.3f} bp) - the trim discriminates")

    print("SELFTEST:", "PASS" if ok else "FAIL")
    return ok


# ==========================================================================
def main():
    if not _selftest():
        print("SELFTEST FAILED -- refusing to emit numbers")
        return 1

    print("\n" + "=" * 96)
    print("CALENDAR + FLAGGER SELF-TESTS (reused from k1)")
    print("=" * 96)
    cal_all, rel = load_calendar()
    if not (selftest_calendar(rel) and selftest_flagger(rel["ts"])):
        print("k1 SELFTEST FAILED -- refusing to emit numbers")
        return 1
    CAL_END = cal_all["release_ts_ny"].max()
    rel_hm = rel[rel["impact"].isin(["high", "medium"])]["ts"]
    print(f"\ncalendar covers -> {CAL_END};  high+medium release minutes: {len(rel_hm)}")

    ev = pd.read_parquet(HERE / "event_paths.parquet")
    pl = pd.read_parquet(HERE / "placebo_paths.parquet")
    ev = ev[ev["contract_rank"] == 3].copy()
    pl = pl[pl["contract_rank"] == 3].copy()

    OUT: dict = {"_meta": dict(
        rank=3, baseline_offset_min=-60,
        window_words="-60 -> +240 min is FIVE hours, of which FOUR are after the speech",
        calendar_end=str(CAL_END),
        release_impact="high+medium USD, ForexFactory, window [-60,+240] inclusive")}

    # ---------------------------------------------------------------- flags
    def add_flags(d):
        m = d.drop_duplicates("event_id")[["event_id", "speech_ts"]].copy()
        covered = m["speech_ts"] <= CAL_END
        f240, n240 = flag_windows(m, rel_hm, -60, 240)
        f30, _ = flag_windows(m, rel_hm, -60, 30)
        m["rel_covered"] = covered.to_numpy()
        m["rel_contam_240"] = f240
        m["rel_n_240"] = n240
        m["rel_contam_30"] = f30
        return d.merge(m[["event_id", "rel_covered", "rel_contam_240",
                          "rel_n_240", "rel_contam_30"]], on="event_id", how="left")

    ev = add_flags(ev)
    pl = add_flags(pl)

    for tag, d in (("real", ev), ("placebo", pl)):
        s = d.drop_duplicates("event_id")
        s = s[s["stance_sign"] != 0]
        OUT[f"coverage_{tag}"] = dict(
            n_signed=int(len(s)),
            n_uncovered=int((~s["rel_covered"]).sum()),
            contam_share_240=float(s.loc[s["rel_covered"], "rel_contam_240"].mean()),
            contam_share_30=float(s.loc[s["rel_covered"], "rel_contam_30"].mean()))
        print(f"\n{tag}: {len(s)} signed, {int((~s['rel_covered']).sum())} outside calendar "
              f"coverage (EXCLUDED from both arms), "
              f"{s.loc[s['rel_covered'], 'rel_contam_240'].mean():.1%} of covered "
              f"[-60,+240] windows contain a high/med US release")

    ev_cov = ev[ev["rel_covered"]]
    pl_cov = pl[pl["rel_covered"]]

    BOOKS = (("fig1_nonoverlap", ev[~ev["is_overlapping"]], ev_cov[~ev_cov["is_overlapping"]]),
             ("fig1b_all", ev, ev_cov))

    ppiv_full, pmeta_full = wide(pl)

    # ---------------------------------------------------------------- per book
    for bname, braw, bcov in BOOKS:
        print("\n" + "=" * 96)
        print(f"BOOK: {bname}")
        print("=" * 96)
        piv, meta = wide(braw)
        b: dict = {}

        # ---- sample
        b["n_signed"] = int(len(meta))
        b["n_hawk"] = int((meta["stance_sign"] == 1).sum())
        b["n_dove"] = int((meta["stance_sign"] == -1).sum())
        b["n_days"] = int(meta["date"].nunique())
        hk = arm_paths(piv, meta, 1)
        dv = arm_paths(piv, meta, -1)
        b["priced_n_by_offset"] = {str(o): dict(hawk=int(hk.loc[o, "n"]), dove=int(dv.loc[o, "n"]))
                                   for o in OFFSETS}
        gap_path = (hk["mean"] - dv["mean"])
        pre = [o for o in OFFSETS if o < 0]
        b["gap_path_bp"] = {str(o): float(gap_path.loc[o]) for o in OFFSETS}
        b["pre_event_gap_max_abs_bp"] = float(gap_path.loc[pre].abs().max())
        b["pre_event_gap_argmax_offset"] = int(gap_path.loc[pre].abs().idxmax())
        b["pre_event_gap_at_argmax_bp"] = float(gap_path.loc[gap_path.loc[pre].abs().idxmax()])

        # ---- the four +240 quantities, kept distinct
        b["gap_240"] = gap_at(piv, meta, 240)
        b["gap_did_240_fullplacebo"] = gap_did(piv, meta, ppiv_full, pmeta_full, 240)
        b["composite_240"] = signed_mean(piv, meta, 240)
        b["composite_excess_240_fullplacebo"] = excess_composite(piv, meta, ppiv_full,
                                                                 pmeta_full, 240)
        b["gap_over_composite_ratio"] = float(
            b["gap_240"]["coef"] / b["composite_excess_240_fullplacebo"]["coef"])

        # ---- parent-matched placebo (like-for-like band)
        ids = set(braw["event_id"].unique())
        pm_sub = pl[pl["parent_event_id"].isin(ids)]
        ppm, pmm = wide(pm_sub)
        b["placebo_parent_matched"] = dict(
            n_signed_pseudo=int(len(pmm)),
            n_signed_pseudo_full=int(len(pmeta_full)),
            gap_did_240=gap_did(piv, meta, ppm, pmm, 240),
            composite_excess_240=excess_composite(piv, meta, ppm, pmm, 240),
            band_se_240_full=float(cluster_mean_se(ppiv_full[240].to_numpy(),
                                                   pmeta_full["date"].to_numpy())["se"]),
            band_se_240_matched=float(cluster_mean_se(ppm[240].to_numpy(),
                                                      pmm["date"].to_numpy())["se"]))

        # ---- RELEASE-CLEAN: the number that reconciles reviewer 2 and reviewer 4
        pivc, metac = wide(bcov)
        clean_r = metac["rel_contam_240"].to_numpy().astype(bool)
        pcov_piv, pcov_meta = wide(pl_cov)
        clean_p = pcov_meta["rel_contam_240"].to_numpy().astype(bool)

        def sub(piv_, meta_, m):
            return piv_.loc[m], meta_.loc[m]

        pr_c, mr_c = sub(pivc, metac, ~clean_r)
        pr_x, mr_x = sub(pivc, metac, clean_r)
        pp_c, mp_c = sub(pcov_piv, pcov_meta, ~clean_p)

        b["release_split_240"] = dict(
            full=signed_mean(pivc, metac, 240),
            clean=signed_mean(pr_c, mr_c, 240),
            contaminated=signed_mean(pr_x, mr_x, 240),
            gap_full=gap_at(pivc, metac, 240),
            gap_clean=gap_at(pr_c, mr_c, 240),
            gap_contaminated=gap_at(pr_x, mr_x, 240),
            gap_did_clean=gap_did(pr_c, mr_c, pp_c, mp_c, 240),
            composite_excess_clean=excess_composite(pr_c, mr_c, pp_c, mp_c, 240),
            placebo_clean_composite=signed_mean(pp_c, mp_c, 240))

        # same thing against the PARENT-MATCHED placebo, so the box can compare
        # like with like (band drawn = placebo used = parents of these events).
        pm_cov = pm_sub[pm_sub["rel_covered"]]
        ppm_c, pmm_c = wide(pm_cov)
        cl_pm = pmm_c["rel_contam_240"].to_numpy().astype(bool)
        b["release_split_240"]["gap_did_clean_parent_matched"] = gap_did(
            pr_c, mr_c, ppm_c.loc[~cl_pm], pmm_c.loc[~cl_pm], 240)

        # ---- day fixed effects
        b["day_fe_240"] = day_fe_slope(piv, meta, 240)
        b["day_fe_240_clean"] = day_fe_slope(pr_c, mr_c, 240)

        # ---- post-only legs (baseline moved to offset 0)
        post = {}
        for o in (5, 15, 30, 60, 240, 300):
            v = (piv[o].to_numpy() - piv[0].to_numpy()) * meta["stance_sign"].to_numpy()
            post[str(o)] = cluster_mean_se(v, meta["date"].to_numpy())
        b["post_only_signed"] = post
        pre_leg = signed_mean(piv, meta, 0)
        b["pre_leg_minus60_to_0"] = pre_leg
        b["pre_leg_share_of_composite_240_pct"] = float(
            100.0 * pre_leg["mean"] / b["composite_240"]["mean"]) if b["composite_240"]["mean"] else np.nan

        # ---- tail sensitivity
        tr, dropped, dvals = trim_top_days(piv, meta, 240, 0.01)
        b["trim_top1pct_days_240"] = dict(**tr, dropped_days=dropped, dropped_day_means_bp=dvals)
        dts = meta["date"].to_numpy()
        keep_both = ~np.isin(dts, [TARIFF_DAY, YEN_CARRY_DAY])
        b["ex_two_named_contaminants_240"] = signed_mean(piv.loc[keep_both], meta.loc[keep_both], 240)
        v240 = (piv[240].to_numpy() * meta["stance_sign"].to_numpy())
        v240 = v240[np.isfinite(v240)]
        srt = np.sort(np.abs(v240))[::-1]
        b["tail_concentration"] = dict(
            n=int(v240.size), total_bp=float(v240.sum()),
            top3_abs_sum_bp=float(np.sort(v240)[::-1][:3].sum()),
            top3_share_of_total_pct=float(100 * np.sort(v240)[::-1][:3].sum() / v240.sum())
            if v240.sum() else np.nan,
            median_bp=float(np.median(v240)),
            top1_share_of_sq_var_pct=float(100 * srt[0] ** 2 / (v240 ** 2).sum()))

        OUT[bname] = b

        # ---- print
        g, gd = b["gap_240"], b["gap_did_240_fullplacebo"]
        rc = b["release_split_240"]
        print(f"  n = {b['n_signed']} signed ({b['n_hawk']}h/{b['n_dove']}d) on {b['n_days']} days")
        print(f"  priced at +240: hawk {b['priced_n_by_offset']['240']['hawk']} / "
              f"dove {b['priced_n_by_offset']['240']['dove']}")
        print(f"  hawk-dove GAP  +240        = {g['coef']:+.4f} bp  t={g['t']:+.3f}  n={g['n']}")
        print(f"  gap DiD (full placebo)     = {gd['coef']:+.4f} bp  t={gd['t']:+.3f}")
        print(f"  gap DiD (parent-matched)   = {b['placebo_parent_matched']['gap_did_240']['coef']:+.4f} bp"
              f"  t={b['placebo_parent_matched']['gap_did_240']['t']:+.3f}")
        print(f"  composite excess (the box) = {b['composite_excess_240_fullplacebo']['coef']:+.4f} bp"
              f"  t={b['composite_excess_240_fullplacebo']['t']:+.3f}"
              f"   <- {b['gap_over_composite_ratio']:.2f}x smaller than the gap")
        print(f"  >>> RELEASE-CLEAN gap      = {rc['gap_clean']['coef']:+.4f} bp "
              f"t={rc['gap_clean']['t']:+.3f} (n={rc['gap_clean']['n']})   "
              f"contaminated = {rc['gap_contaminated']['coef']:+.4f} t={rc['gap_contaminated']['t']:+.3f}")
        print(f"  >>> RELEASE-CLEAN gap DiD  = {rc['gap_did_clean']['coef']:+.4f} bp "
              f"t={rc['gap_did_clean']['t']:+.3f}")
        print(f"  composite  full {rc['full']['mean']:+.4f} (t {rc['full']['t']:+.2f}, n {rc['full']['n']}) | "
              f"clean {rc['clean']['mean']:+.4f} (t {rc['clean']['t']:+.2f}, n {rc['clean']['n']}) | "
              f"contam {rc['contaminated']['mean']:+.4f} (t {rc['contaminated']['t']:+.2f}, n {rc['contaminated']['n']})")
        print(f"  day-FE stance slope +240   = {b['day_fe_240']['coef']:+.4f} bp "
              f"t={b['day_fe_240']['t']:+.3f} ({b['day_fe_240']['n_id_days']} identifying days)")
        print(f"  pre-leg [-60->0] signed    = {pre_leg['mean']:+.4f} bp "
              f"({b['pre_leg_share_of_composite_240_pct']:.0f}% of the +240 composite)")
        print(f"  post-only [0->+240]        = {post['240']['mean']:+.4f} bp t={post['240']['t']:+.2f}")
        print(f"  trim top 1% of days        = {tr['mean']:+.4f} bp t={tr['t']:+.3f}  "
              f"(dropped {dropped})")
        print(f"  top 3 events = {b['tail_concentration']['top3_share_of_total_pct']:.0f}% of the summed move")

    # ---------------------------------------------------------------- fig2 restatement
    print("\n" + "=" * 96)
    print("FIG-2 RESTATEMENT: the strip response, release-clean, by contract rank")
    print("=" * 96)
    strip = {}
    ev_all = pd.read_parquet(HERE / "event_paths.parquet")
    pl_all = pd.read_parquet(HERE / "placebo_paths.parquet")
    ev_all = add_flags(ev_all)
    pl_all = add_flags(pl_all)
    for rk in (1, 2, 3, 4, 5):
        e = ev_all[(ev_all["contract_rank"] == rk) & ev_all["rel_covered"]]
        p = pl_all[(pl_all["contract_rank"] == rk) & pl_all["rel_covered"]]
        pe, me = wide(e)
        pp, mp = wide(p)
        ce = me["rel_contam_240"].to_numpy().astype(bool)
        cp = mp["rel_contam_240"].to_numpy().astype(bool)
        full = signed_mean(pe, me, 240)
        clean = signed_mean(pe.loc[~ce], me.loc[~ce], 240)
        contam = signed_mean(pe.loc[ce], me.loc[ce], 240)
        pl_clean = signed_mean(pp.loc[~cp], mp.loc[~cp], 240)
        did_clean = excess_composite(pe.loc[~ce], me.loc[~ce], pp.loc[~cp], mp.loc[~cp], 240)
        fe = day_fe_slope(pe, me, 240)
        fec = day_fe_slope(pe.loc[~ce], me.loc[~ce], 240)
        strip[str(rk)] = dict(full=full, clean=clean, contaminated=contam,
                              placebo_clean=pl_clean, excess_clean=did_clean,
                              day_fe=fe, day_fe_clean=fec)
        print(f"  rank {rk}: full {full['mean']:+.3f} (t {full['t']:+.2f}, n {full['n']}) | "
              f"clean {clean['mean']:+.3f} (t {clean['t']:+.2f}, n {clean['n']}) | "
              f"contam {contam['mean']:+.3f} (t {contam['t']:+.2f}, n {contam['n']}) | "
              f"clean excess vs placebo {did_clean['coef']:+.3f} (t {did_clean['t']:+.2f}) | "
              f"dayFE {fe['coef']:+.3f} (t {fe['t']:+.2f})")
    OUT["fig2_strip_release_clean"] = strip

    # ------------------------------------------------- are the two checks the same cut?
    # If the release flag already removes the two named outlier days, then
    # "release-clean" and "trimmed" are one check wearing two hats, not two.
    print("\n" + "=" * 96)
    print("ARE THE RELEASE CUT AND THE TAIL TRIM THE SAME CUT?")
    print("=" * 96)
    e1 = ev.drop_duplicates("event_id")
    for d in (TARIFF_DAY, YEN_CARRY_DAY):
        r = e1[e1["date"] == d]
        print(f"  {d}: {len(r)} events, release-contaminated [-60,+240] = "
              f"{list(r['rel_contam_240'].unique())}, signed = {list(r['stance_sign'].unique())}")
    joint = {}
    for bname, braw, bcov in BOOKS:
        pivc, metac = wide(bcov)
        cl = ~metac["rel_contam_240"].to_numpy().astype(bool)
        pc, mc = pivc.loc[cl], metac.loc[cl]
        tr, dd, _ = trim_top_days(pc, mc, 240, 0.01)
        joint[bname] = dict(clean_then_trim=dict(**tr, dropped_days=dd),
                            named_days_contaminated={
                                str(TARIFF_DAY): bool(e1.loc[e1["date"] == TARIFF_DAY,
                                                             "rel_contam_240"].any()),
                                str(YEN_CARRY_DAY): bool(e1.loc[e1["date"] == YEN_CARRY_DAY,
                                                                "rel_contam_240"].any())})
        print(f"  {bname}: release-clean THEN trim top 1% of days = "
              f"{tr['mean']:+.4f} bp t={tr['t']:+.3f} (n={tr['n']}, dropped {dd})")
    OUT["joint_clean_and_trim"] = joint

    # ---------------------------------------------------------------- extras
    # the double-count number, and the placebo blackout mismatch direction
    g = ev.drop_duplicates("event_id")
    grp = ev[ev["offset_min"] == 240].groupby(["date", "symbol"])["d_rate_bp_from_baseline"]
    multi = grp.agg(["count", "nunique"])
    multi = multi[multi["count"] > 1]
    OUT["overlap_double_count"] = dict(
        n_multi_groups=int(len(multi)),
        n_identical_groups=int((multi["nunique"] == 1).sum()),
        max_events_in_group=int(multi["count"].max()) if len(multi) else 0)
    evs = ev.drop_duplicates("event_id")
    pls = pl.drop_duplicates("event_id")
    OUT["placebo_blackout_mismatch"] = dict(
        real_share_within_10d_fomc_pct=float(
            100 * (evs.loc[evs["stance_sign"] != 0, "days_to_fomc"].abs() <= 10).mean()),
        placebo_share_within_10d_fomc_pct=float(
            100 * (pls.loc[pls["stance_sign"] != 0, "days_to_fomc"].abs() <= 10).mean()),
        direction="placebo sits on quieter, closer-to-FOMC-blackout days, so every "
                  "excess-over-placebo number is biased UPWARD; the true excess is smaller")
    # SVB week coverage hole
    svb = evs[(evs["date"] >= pd.Timestamp("2023-03-06").date()) &
              (evs["date"] <= pd.Timestamp("2023-03-17").date())]
    OUT["svb_week_hole"] = dict(n_calendar_events=int(len(svb)),
                                n_signed=int((svb["stance_sign"] != 0).sum()))
    print(f"\noverlap double-count: {OUT['overlap_double_count']}")
    print(f"placebo blackout mismatch: real {OUT['placebo_blackout_mismatch']['real_share_within_10d_fomc_pct']:.1f}% "
          f"vs placebo {OUT['placebo_blackout_mismatch']['placebo_share_within_10d_fomc_pct']:.1f}% within 10d of FOMC")
    print(f"SVB week 2023-03-06..17: {OUT['svb_week_hole']}")

    with open(JSON_OUT, "w") as fh:
        json.dump(OUT, fh, indent=1, default=float)
    print(f"\nwrote {JSON_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
