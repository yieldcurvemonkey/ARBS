"""
Addendum-1 diagnostic D1 — quantify the attenuation of R0's median-based direction sign.

Run only because R0's verdict is FAIL, which makes the addendum's downgrade rule live.
Operationalisation frozen in r0_deviations.md section R10 BEFORE any number was computed.

  dev_median  = fixed_rate - trailing same-key median   (R0's ACTUAL input)
  dev_curve   = fixed_rate - Citi minute-curve par rate (REFERENCE ONLY)

Reports rho at print / 1-minute / daily level, the per-print sign-agreement rate, and the
implied MDE. Does NOT rebuild X and does NOT re-run the regression.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from run_r0 import rolling_scale, DECISION_BUCKETS          # noqa: E402  (same frozen rule)

SE_SUM_BETA_KPOS = 0.01280      # pooled, dissemination clock, day-clustered; fixed by the run
CURVE = "USD-SOFR-1D"
SOURCE = "citivelo_excel_rl"
TOL = pd.Timedelta("2min")
OUT = os.path.join(HERE, "out")

_L: list[str] = []


def log(m: str = "") -> None:
    print(m, flush=True)
    _L.append(m)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    from scripts.citivelo_intraday_ts_warm import SPOT_TENORS

    legs = pd.read_parquet(os.path.join(HERE, "cache", "tape_legs_signed.parquet"))
    log("=" * 96)
    log("D1 — attenuation of R0's median-based sign (addendum 1). Reference only.")
    log("=" * 96)
    log(f"tape legs handed over by the X workstream: {len(legs):,}")

    # ---- the frozen D1 sample (R10, narrowed by R10b) ----------------------
    # R10b: the twelve highest-print-count tenors covering all five decision buckets.
    # Chosen by print count with no rho computed for any tenor at the time of choosing.
    D1_TENORS = ["1m", "2m", "3m", "6m", "1y", "2y", "3y", "5y", "7y", "10y", "20y", "30y"]
    assert set(D1_TENORS) <= {t.lower() for t in SPOT_TENORS}
    # R10c: use R10b INTERSECT what is actually cached. A tenor whose reference pull did
    # not complete reduces coverage; it must not silently block the diagnostic, and the
    # per-bucket coverage table below discloses exactly what was retained.
    refdir0 = os.path.join(HERE, "cache_d1_ref")
    have = {f[4:-8] for f in os.listdir(refdir0) if f.startswith("ref_")} \
        if os.path.isdir(refdir0) else set()
    warm = set(D1_TENORS) & have
    missing = sorted(set(D1_TENORS) - have)
    log(f"R10b tenor set: {len(D1_TENORS)}; reference available for {len(warm)} "
        f"({', '.join(sorted(warm))})")
    if missing:
        log(f"  NOT AVAILABLE, excluded from D1: {', '.join(missing)}")
    legs["tenor_lc"] = legs["tenor_label"].astype(str).str.lower()
    in_window = (legs["execution_timestamp"] >= pd.Timestamp("2026-05-01", tz="UTC")) & \
                (legs["execution_timestamp"] < pd.Timestamp("2026-08-08", tz="UTC"))
    sel = (legs["fwd_key"] == "spot") & (~legs["is_mac"]) & \
          legs["tenor_lc"].isin(warm) & legs["dev_median"].notna() & \
          legs["bucket"].isin(DECISION_BUCKETS) & in_window
    # R10a: the reference is only real inside Citi's published USD session, 01:00-22:59 ET
    et_hour = legs["execution_timestamp"].dt.tz_convert("America/New_York").dt.hour
    in_citi_session = et_hour.between(1, 22)
    n_pre = int((sel).sum())
    sel = sel & in_citi_session
    log(f"R10a Citi-session restriction (01:00-22:59 ET): {int(sel.sum()):,} of {n_pre:,} "
        f"= {sel.sum()/max(n_pre,1):.1%} of the otherwise-eligible prints retained")
    d = legs[sel].copy()
    log(f"D1 sample: {len(d):,} prints "
        f"({len(d)/len(legs):.1%} of legs, {d['dv01'].sum()/legs['dv01'].sum():.1%} of DV01)")
    log("  retained per bucket (prints / DV01 share of that bucket):")
    for b in DECISION_BUCKETS:
        ab = legs[legs["bucket"] == b]
        sb = d[d["bucket"] == b]
        log(f"    {b:8s} {len(sb):7,} / {len(ab):7,} = {len(sb)/max(len(ab),1):6.1%} prints  "
            f"{sb['dv01'].sum()/max(ab['dv01'].sum(),1):6.1%} DV01")
    if d.empty:
        log("D1 sample is empty — cannot quantify attenuation.")
        return 1

    d["exec_min"] = d["execution_timestamp"].dt.floor("min")
    tenors = sorted(d["tenor_lc"].unique())
    log(f"  tenors needed: {len(tenors)} -> {tenors}")

    # ---- load the reference par rates from the out-of-band cache -----------
    # The pull itself is done by scratch_d1_fullwin.py (chunked by month, one process per
    # tenor, because an unchunked long-tenor pull thrashes at >6 GB). Nothing is fetched
    # here, so the pricing stack is never constructed.
    refdir = os.path.join(HERE, "cache_d1_ref")
    frames = []
    for i, tn in enumerate(tenors, 1):
        cpath = os.path.join(refdir, f"ref_{tn}.parquet")
        if not os.path.exists(cpath):
            raise RuntimeError(
                f"reference series for {tn!r} is not in {refdir}. Run "
                f"`python scratch_d1_fullwin.py {tn}` first.")
        f = pd.read_parquet(cpath)
        frames.append(f)
        log(f"    [{i}/{len(tenors)}] {tn:5s} {len(f):7,} minutes  "
            f"{f['ref_min'].min()} .. {f['ref_min'].max()}")
    if not frames:
        log("no reference series available — D1 cannot be computed.")
        return 1
    ref = pd.concat(frames, ignore_index=True).drop_duplicates(["tenor_lc", "ref_min"])
    ref = ref.sort_values("ref_min")

    # ---- join (R10: merge_asof backward, 2-minute tolerance) ---------------
    d = d.sort_values("exec_min")
    parts = []
    for tn, g in d.groupby("tenor_lc"):
        r = ref[ref["tenor_lc"] == tn]
        if r.empty:
            continue
        m = pd.merge_asof(g.sort_values("exec_min"), r[["ref_min", "ref_rate"]].sort_values("ref_min"),
                          left_on="exec_min", right_on="ref_min",
                          direction="backward", tolerance=TOL)
        parts.append(m)
    j = pd.concat(parts, ignore_index=True)
    matched = j["ref_rate"].notna()
    log("")
    log(f"join match rate: {matched.sum():,} / {len(j):,} = {matched.mean():.1%} "
        f"(backward, tolerance {TOL})")
    j = j[matched].copy()
    if j.empty:
        log("nothing matched — D1 cannot be computed.")
        return 1

    # rates: tape fixed_rate is a decimal; the reference comes back in percent
    scale = float(np.nanmedian(j["ref_rate"] / j["fixed_rate"]))
    log(f"reference/tape rate scale (median ratio) = {scale:.3f} -> "
        f"{'reference is PERCENT, tape is DECIMAL' if scale > 50 else 'same units'}")
    j["ref_dec"] = j["ref_rate"] / (100.0 if scale > 50 else 1.0)
    j["dev_curve"] = j["fixed_rate"] - j["ref_dec"]

    # ---- known-answer check on the join (R10) -----------------------------
    log("")
    log("known-answer check — per-day median dev_curve must sit near zero (bp):")
    daymed = (j.assign(day=j["exec_min"].dt.date)
                .groupby("day")["dev_curve"].median() * 1e4)
    log(f"  n_days {len(daymed)}  p5 {daymed.quantile(.05):+.2f}  p50 {daymed.median():+.2f}  "
        f"p95 {daymed.quantile(.95):+.2f}  min {daymed.min():+.2f}  max {daymed.max():+.2f}")
    log(f"  overall median dev_curve = {j['dev_curve'].median()*1e4:+.2f} bp   "
        f"IQR = {(j['dev_curve'].quantile(.75)-j['dev_curve'].quantile(.25))*1e4:.2f} bp")
    log(f"  for comparison, median dev_median = {j['dev_median'].median()*1e4:+.2f} bp   "
        f"IQR = {(j['dev_median'].quantile(.75)-j['dev_median'].quantile(.25))*1e4:.2f} bp")
    drift = float(np.corrcoef(j["dev_curve"], j["ref_dec"])[0, 1])
    log(f"  corr(dev_curve, level of the reference rate) = {drift:+.3f}  "
        f"(a tz/units error would drive this toward +-1)")

    # ---- sign agreement, per print ----------------------------------------
    j["sign_median"] = np.sign(j["dev_median"]).astype(int)
    j["sign_curve"] = np.sign(j["dev_curve"]).astype(int)
    both = j[(j["sign_median"] != 0) & (j["sign_curve"] != 0)]
    agree_all = float((both["sign_median"] == both["sign_curve"]).mean())
    log("")
    log(f"PER-PRINT SIGN AGREEMENT (both non-zero, n={len(both):,}): {agree_all:.1%}")
    for b in DECISION_BUCKETS:
        bb = both[both["bucket"] == b]
        if len(bb):
            log(f"    {b:8s} {(bb['sign_median']==bb['sign_curve']).mean():6.1%}  (n={len(bb):,})")

    # ---- rho at print / 1-minute / daily ----------------------------------
    log("")
    log("rho = corr(X_median, X_curve), both built from the SAME print set (R10):")
    j["x_med"] = j["dv01"] * j["sign_median"]
    j["x_cur"] = j["dv01"] * j["sign_curve"]
    rows = []
    for b in DECISION_BUCKETS:
        bb = j[j["bucket"] == b]
        if len(bb) < 100:
            continue
        r_print = float(np.corrcoef(bb["x_med"], bb["x_cur"])[0, 1])
        mn = bb.groupby("exec_min")[["x_med", "x_cur"]].sum()
        bc = np.zeros(len(mn), dtype=int)
        a = mn["x_med"].to_numpy(float) / rolling_scale(mn["x_med"].to_numpy(float), bc)
        c = mn["x_cur"].to_numpy(float) / rolling_scale(mn["x_cur"].to_numpy(float), bc)
        r_min = float(np.corrcoef(a, c)[0, 1])
        # cross-check: the same minute-level correlation WITHOUT the rolling
        # standardisation, so rho does not rest on the R4 scaling choice
        r_min_raw = float(np.corrcoef(mn["x_med"], mn["x_cur"])[0, 1])
        dy = bb.assign(day=bb["exec_min"].dt.date).groupby("day")[["x_med", "x_cur"]].sum()
        r_day = float(np.corrcoef(dy["x_med"], dy["x_cur"])[0, 1])
        rows.append(dict(bucket=b, n_prints=len(bb), n_minutes=len(mn), n_days=len(dy),
                         dv01=float(bb["dv01"].sum()),
                         rho_print=r_print, rho_minute=r_min, rho_minute_raw=r_min_raw,
                         rho_daily=r_day,
                         sign_agreement=float((bb["sign_median"] == bb["sign_curve"])[
                             (bb["sign_median"] != 0) & (bb["sign_curve"] != 0)].mean())))
        log(f"    {b:8s} print {r_print:+.3f}   1-minute {r_min:+.3f} "
            f"(raw {r_min_raw:+.3f})   daily {r_day:+.3f}"
            f"   (n_prints {len(bb):,}, n_min {len(mn):,}, n_days {len(dy)})")
    rdf = pd.DataFrame(rows)
    w = rdf["dv01"] / rdf["dv01"].sum()
    rho_pooled_min = float((rdf["rho_minute"] * w).sum())
    rho_pooled_print = float((rdf["rho_print"] * w).sum())
    rho_pooled_day = float((rdf["rho_daily"] * w).sum())
    log("")
    log(f"  DV01-weighted pooled: print {rho_pooled_print:+.3f}   "
        f"1-minute {rho_pooled_min:+.3f} <- DECIDING (R10)   daily {rho_pooled_day:+.3f}")
    collapse = rho_pooled_day < rho_pooled_min
    log(f"  rho collapses under aggregation (daily < 1-minute): {collapse}  "
        f"-> {'consistent with the median HIGH-PASSING the flow' if collapse else 'more consistent with plain noise than with high-passing'}")

    # ---- MDE ---------------------------------------------------------------
    log("")
    mde = 1.96 * SE_SUM_BETA_KPOS / rho_pooled_min if rho_pooled_min > 0 else np.nan
    log(f"implied MDE = 1.96 * SE(sum beta_k, k>=1) / rho "
        f"= 1.96 * {SE_SUM_BETA_KPOS:.5f} / {rho_pooled_min:.3f} = {mde:+.4f}")
    log(f"  i.e. the smallest TRUE post-print effect this test could have detected is "
        f"|sum beta_k| >= {mde:.4f} standard deviations of Y per standard deviation of X.")

    # ---- the downgrade rule -------------------------------------------------
    n_below = int((rdf["rho_minute"] < 0.5).sum())
    trigger = (rho_pooled_min < 0.5) or (n_below > len(rdf) / 2) or (agree_all < 0.60)
    log("")
    log("=" * 96)
    log("ADDENDUM-1 DOWNGRADE RULE (applies only to a FAIL; can never create a PASS)")
    log("=" * 96)
    log(f"  pooled 1-minute rho          = {rho_pooled_min:.3f}   (threshold 0.50)")
    log(f"  decision buckets with rho<0.5 = {n_below} of {len(rdf)}")
    log(f"  per-print sign agreement      = {agree_all:.1%}  (threshold 60%)")
    log(f"  DOWNGRADE TRIGGERS = {trigger}")
    log(f"  -> verdict is reported as {'UNINFORMATIVE' if trigger else 'FAIL'}")

    rdf.to_csv(os.path.join(OUT, "r0_d1_rho.csv"), index=False)
    with open(os.path.join(OUT, "r0_d1.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(_L) + "\n")
    with open(os.path.join(OUT, "r0_d1_downgrade.txt"), "w", encoding="utf-8") as f:
        f.write(("UNINFORMATIVE" if trigger else "FAIL") + "\n")
    log("")
    log(f"wrote out/r0_d1_rho.csv, out/r0_d1.log   ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
