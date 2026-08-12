"""Tie-out comparator: the two D11 measurements, off the parquet the sweep wrote.

Nothing here touches a curve or a database. Every metric is recomputable from
``D:\\tieout_cache`` alone, which is what makes a metric change cheap and a
repricing change expensive -- the right way round.

THE THREE SIDE DEFINITIONS, AND WHY THERE ARE THREE
---------------------------------------------------
``p = sigmoid((dev - b0) / tau)``. On the legacy Barchart curve the fitted
``b0`` is about -0.48 bp (LEDGER F-20), so ``p > 0.5`` means ``dev > -0.48``
while the frozen classifier's rule is ``dev > 0``. That is a ~34 pp label shift
produced by the CALIBRATION, not by the decision logic, and a gate that counts
it as disagreement can only be passed by a system that reproduces the bias --
exactly the failure D11 decomposed the tie-out to avoid.

So the logic tie-out uses ``b0 = 0``, under which ``p > 0.5`` is identical to
``conventions.dealer_side(dev) > 0`` and the task's "RECEIVED if p > 0.5"
formulation is satisfied by the same rule the old code applies. ``tau`` is
still the fitted one, because ``tau`` sets the ABSTAIN band and nothing else.
The fitted ``b0`` is then reported as its own effect, and the curve effect
holds ``b0 = 0`` on BOTH curves so that measurement varies one thing too.

STRATA ARE EXCLUSIVE AND PRIORITISED
------------------------------------
Every joined row lands in exactly one stratum. Agreement is computed on
``DECISIVE`` only; every other stratum is reported with its count and is never
counted as agreement or as disagreement. The priority order puts the
*structural* reasons (a refusal, an UNKNOWN, a rule the other system does not
implement) above the *marginal* ones (knife-edge, dead zone), so a row is
named by the strongest reason it is not comparable.
"""
from __future__ import annotations

import argparse
import dataclasses
import glob
import json
import math
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from SDRUtils.dealer_direction import probability as prob  # noqa: E402
from SDRUtils.dealer_direction import upfront as uf  # noqa: E402

RATE_RULES = ("RATE_VS_MID", "SPREAD_VS_MID", "FLY_VS_MID")

STRATA_ORDER = [
    "NEW_REFUSED",        # the new package declined to price or to call
    "OLD_UNKNOWN",        # old produced no side
    "OLD_TICK_RULE",      # old's side came from a rule the new one has no analogue for
    "NEW_EXACT_TIE",      # dev == 0.0: old has no zero branch, new refuses (T-4)
    "CURVE_SUSPECT",      # old flagged the bucket-day curve
    "KNIFE_EDGE",         # |s2m| <= half the futures tick
    "NEW_ABSTAIN",        # |p - 0.5| < delta
    "DECISIVE",
]


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def _load(sub: str, root: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(root, sub, "*.parquet")))
    frames = [pd.read_parquet(f) for f in files]
    frames = [f for f in frames if len(f) and "unit_key" in f]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def load_all(root: str):
    old = _load("old", root)
    bar = _load("new_bar", root)
    citi = _load("new_citi", root)
    common = sorted(set(old["as_of_date"].astype(str)) & set(bar["as_of_date"].astype(str)))
    old = old[old["as_of_date"].astype(str).isin(common)].copy()
    bar = bar[bar["as_of_date"].astype(str).isin(common)].copy()
    if len(citi):
        citi = citi[citi["as_of_date"].astype(str).isin(common)].copy()
    return old, bar, citi, common


# --------------------------------------------------------------------------
# calibration -- fitted on the frame being scored, then b0 forced to zero
# --------------------------------------------------------------------------

def calibrate(new: pd.DataFrame):
    """``(Calibration_b0zero, fitted_b0_table, tau_upfront)`` for one curve's frame.

    The rate rule and the upfront rule are fitted on DIFFERENT statistics --
    a price-to-mid deviation and a fee residual -- so they get different taus,
    which is what the new package does in production.
    """
    ok = new[new["failure"].isna() & new["deviation_bps"].notna()].copy()
    rate = ok[ok["rule"] == "RATE_VS_MID"].copy()
    rate["venue_class"] = "D2C"
    rate["structure"] = rate["kind"]
    rate["special_tenor_type"] = rate["special_tenor_type"].fillna("STANDARD")
    rate[prob.DEVIATION_COL] = rate["deviation_bps"].astype(float)

    cal = prob.Calibration.fit(rate[[prob.DEVIATION_COL, *prob.BUCKET_COLS]])
    fitted_b0 = pd.DataFrame([
        {"bucket": k, "n": f.n, "n_trimmed": f.n_trimmed, "b0_bps": f.b0,
         "h_bps": f.h, "s_bps": f.s, "tau_bps": f.tau}
        for k, f in cal.fits.items()
    ]).sort_values("n", ascending=False)

    zero = {k: dataclasses.replace(f, b0=0.0) for k, f in cal.fits.items()}
    cal0 = prob.Calibration(zero, order=cal.order, min_n=cal.min_n)

    upf = ok[ok["rule"] == "NPV_VS_UPFRONT"]
    tau_uf = None
    if len(upf) >= 30 and "uf_residual_bps" in upf:
        res = upf["uf_residual_bps"].dropna().to_numpy(float)
        if len(res) >= 30:
            tau_uf = uf.robust_tau_upfront(res, population=uf.POPULATION_FLOW)
    return cal0, fitted_b0, tau_uf, cal


def score(new: pd.DataFrame, cal0, tau_uf, delta: float = prob.DEAD_ZONE_DELTA):
    """Attach ``p``, ``side_new`` and ``abstain`` under the b0 = 0 rule."""
    out = new.copy()
    p, band = [], []
    for _, r in out.iterrows():
        dev = r.get("deviation_bps")
        if r.get("failure") is not None and not pd.isna(r.get("failure")):
            p.append(np.nan); band.append(np.nan); continue
        if dev is None or pd.isna(dev):
            p.append(np.nan); band.append(np.nan); continue
        if r["rule"] == "RATE_VS_MID":
            key = prob.BucketKey("D2C", r["rate_index"], r["kind"],
                                 r.get("special_tenor_type") or "STANDARD",
                                 r["tenor_band"])
            fit = cal0.for_key(key)
            p.append(prob.p_customer_paid(float(dev), fit))
            band.append(prob.dead_zone_half_width_bps(fit.tau, delta))
        else:
            if tau_uf is None:
                p.append(np.nan); band.append(np.nan); continue
            p.append(uf.p_from_edge(float(dev), tau_uf.tau_bps))
            band.append(np.nan)
    out["p_new"] = p
    out["dead_zone_bps"] = band
    out["side_new"] = np.where(out["p_new"].isna(), None,
                               np.where(out["p_new"] > 0.5, "RECEIVED", "PAID"))
    out["abstain"] = (out["p_new"] - 0.5).abs() < delta
    return out


# --------------------------------------------------------------------------
# join + strata
# --------------------------------------------------------------------------

OLD_KEEP = ["unit_key", "as_of_date", "dealer_direction", "classification_method",
            "direction_confidence", "curve_suspect_trade", "spread_to_mid_bps",
            "p_flip", "quality_flags", "is_off_market", "trade_type",
            "futures_tick_bps", "bucket_median_tick_bps", "dealer_charge_bps",
            "structure_dv01", "curve_mid", "repriced_npv", "rate_index_clean",
            "tenor_bucket", "dv01_bucket", "is_block", "is_capped"]


def join(old: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    o = old[[c for c in OLD_KEEP if c in old.columns]].copy()
    n = scored[[c for c in scored.columns if c not in ("as_of_date",)]].copy()
    m = o.merge(n, on="unit_key", how="outer", indicator=True,
                suffixes=("", "_new"))
    return m


def half_tick(row) -> float:
    t = row.get("bucket_median_tick_bps")
    if t is None or pd.isna(t) or not (t > 0):
        t = row.get("futures_tick_bps")
    if t is None or pd.isna(t) or not (t > 0):
        t = 0.25
    return float(t) / 2.0


def assign_stratum(m: pd.DataFrame) -> pd.Series:
    s2m = m["spread_to_mid_bps"]
    ht = m.apply(half_tick, axis=1)
    new_no_call = (m["failure"].notna() | m["exclusion"].notna()
                   | m["dealer_sign"].isna())
    out = pd.Series("DECISIVE", index=m.index, dtype=object)
    out[m["abstain"].fillna(False)] = "NEW_ABSTAIN"
    out[(s2m.abs() <= ht) & s2m.notna()] = "KNIFE_EDGE"
    out[m["curve_suspect_trade"].fillna(False).astype(bool)] = "CURVE_SUSPECT"
    out[m["dealer_sign"] == 0] = "NEW_EXACT_TIE"
    out[m["classification_method"] == "TICK_RULE"] = "OLD_TICK_RULE"
    out[m["dealer_direction"].isin(["UNKNOWN", None]) | m["dealer_direction"].isna()] = "OLD_UNKNOWN"
    out[new_no_call] = "NEW_REFUSED"
    out[m["_merge"] != "both"] = "UNMATCHED"
    return out


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

def cohen_kappa(a, b) -> float:
    """Cohen's kappa on two label vectors. NaN when a margin is degenerate."""
    a = pd.Series(list(a)); b = pd.Series(list(b))
    n = len(a)
    if n == 0:
        return float("nan")
    labels = sorted(set(a) | set(b))
    po = float((a.to_numpy() == b.to_numpy()).mean())
    pe = 0.0
    for lab in labels:
        pe += float((a == lab).mean()) * float((b == lab).mean())
    if pe >= 1.0:
        return float("nan")
    return (po - pe) / (1.0 - pe)


def agreement_table(d: pd.DataFrame, by) -> pd.DataFrame:
    rows = []
    for keys, g in d.groupby(by, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        agree = int((g["dealer_direction"] == g["side_new"]).sum())
        rows.append({**dict(zip(by if isinstance(by, list) else [by], keys)),
                     "n": len(g), "agree": agree,
                     "pct": 100.0 * agree / len(g) if len(g) else float("nan"),
                     "kappa": cohen_kappa(g["dealer_direction"], g["side_new"])})
    return pd.DataFrame(rows).sort_values("n", ascending=False)


# --------------------------------------------------------------------------
# comparator self-validation, against known answers
# --------------------------------------------------------------------------

def selftest() -> int:
    bad = 0

    def chk(label, got, want, tol=None):
        nonlocal bad
        ok = (abs(got - want) <= tol) if tol is not None else (got == want)
        bad += not ok
        print(f"  {'OK  ' if ok else 'FAIL'} {label}: got {got!r} want {want!r}")

    # kappa on known answers
    a = ["PAID"] * 60 + ["RECEIVED"] * 40
    chk("kappa, identical labels", round(cohen_kappa(a, a), 12), 1.0)
    rng = np.random.default_rng(0)
    b = list(rng.permutation(a))
    chk("kappa, independent relabelling ~ 0", abs(cohen_kappa(a, b)) < 0.25, True)
    flipped = list(a); flipped[0] = "RECEIVED"
    n, po = 100, 0.99
    pe = (60 / 100) * (59 / 100) + (40 / 100) * (41 / 100)
    chk("kappa, one planted flip", round(cohen_kappa(a, flipped), 10),
        round((po - pe) / (1 - pe), 10))
    chk("kappa, total inversion", round(cohen_kappa(["PAID"] * 50 + ["RECEIVED"] * 50,
                                                    ["RECEIVED"] * 50 + ["PAID"] * 50), 10),
        -1.0)

    # strata: one planted row per stratum must land in exactly that stratum
    base = dict(spread_to_mid_bps=5.0, futures_tick_bps=0.25,
                bucket_median_tick_bps=0.4, curve_suspect_trade=False,
                dealer_direction="PAID", classification_method="RATE_VS_MID",
                failure=None, exclusion=None, dealer_sign=-1, abstain=False,
                _merge="both", side_new="PAID")
    cases = {
        "DECISIVE": {},
        "NEW_ABSTAIN": {"abstain": True},
        "KNIFE_EDGE": {"spread_to_mid_bps": 0.15},
        "CURVE_SUSPECT": {"curve_suspect_trade": True},
        "NEW_EXACT_TIE": {"dealer_sign": 0, "spread_to_mid_bps": 0.0},
        "OLD_TICK_RULE": {"classification_method": "TICK_RULE"},
        "OLD_UNKNOWN": {"dealer_direction": "UNKNOWN"},
        "NEW_REFUSED": {"failure": "NO_CURVE"},
        "UNMATCHED": {"_merge": "left_only"},
    }
    frame = pd.DataFrame([{**base, **v} for v in cases.values()])
    got = list(assign_stratum(frame))
    chk("strata assignment", got, list(cases))

    # priority: a row that qualifies for several strata takes the strongest
    multi = pd.DataFrame([{**base, "failure": "NO_CURVE", "abstain": True,
                           "curve_suspect_trade": True,
                           "classification_method": "TICK_RULE",
                           "dealer_direction": "UNKNOWN"}])
    chk("priority picks NEW_REFUSED", list(assign_stratum(multi)), ["NEW_REFUSED"])
    multi2 = pd.DataFrame([{**base, "abstain": True, "curve_suspect_trade": True}])
    chk("priority CURVE_SUSPECT over NEW_ABSTAIN",
        list(assign_stratum(multi2)), ["CURVE_SUSPECT"])

    # agreement_table on a frame whose answer is arithmetic
    # [P P P P P P P P R R] vs [P P P P P P P R R R] -> 9 of 10 agree.
    # The first spelling of this check asserted 80% by counting the two label
    # COUNTS rather than the element-wise matches, and the test caught it --
    # which is the point of asserting against a hand-counted answer.
    d = pd.DataFrame({"dealer_direction": ["PAID"] * 8 + ["RECEIVED"] * 2,
                      "side_new": ["PAID"] * 7 + ["RECEIVED"] * 3,
                      "g": ["A"] * 10})
    t = agreement_table(d, ["g"])
    chk("agreement pct", round(float(t["pct"].iloc[0]), 6), 90.0)
    chk("agreement count", int(t["agree"].iloc[0]), 9)
    d2 = pd.DataFrame({"dealer_direction": ["PAID", "PAID", "RECEIVED", "RECEIVED"],
                       "side_new": ["PAID", "RECEIVED", "PAID", "RECEIVED"],
                       "g": ["A", "A", "B", "B"]})
    t2 = agreement_table(d2, ["g"]).set_index("g")
    chk("grouped agreement A", round(float(t2.loc["A", "pct"]), 6), 50.0)
    chk("grouped agreement B", round(float(t2.loc["B", "pct"]), 6), 50.0)

    # the b0 identity the whole logic tie-out rests on
    f0 = prob.MixtureFit(bucket="X", n=1000, n_trimmed=1000, b0=0.0, h=0.3,
                         s=0.3, loglik=0.0)
    chk("b0=0 -> p>0.5 iff dev>0",
        [prob.p_customer_paid(d, f0) > 0.5 for d in (-1e-9, 1e-9)], [False, True])
    print(f"  selftest: {'PASS' if not bad else str(bad) + ' FAILURES'}")
    return bad


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=r"D:\tieout_cache")
    ap.add_argument("--out", default=r"D:\tieout_cache\analysis")
    ap.add_argument("--selftest-only", action="store_true")
    args = ap.parse_args()

    print("=" * 78)
    print("COMPARATOR SELF-VALIDATION (known answers, before any real data)")
    print("=" * 78)
    if selftest():
        print("comparator is wrong; refusing to score real data")
        return 1
    if args.selftest_only:
        return 0

    os.makedirs(args.out, exist_ok=True)
    old, bar, citi, days = load_all(args.root)
    print(f"\nloaded {len(days)} days: old {len(old)} units, "
          f"new_bar {len(bar)}, new_citi {len(citi)}")

    cal0, fitted_b0, tau_uf, cal_raw = calibrate(bar)
    print(f"\nfitted tau_upfront: {tau_uf}")
    fitted_b0.to_csv(os.path.join(args.out, "fitted_b0_barchart.csv"), index=False)
    print("\nfitted b0 on the LEGACY curve (F-20 cross-check; measured median "
          "s2m was -0.4836 bp):")
    print(fitted_b0.head(12).to_string(index=False))

    sb = score(bar, cal0, tau_uf)
    m = join(old, sb)
    m["stratum"] = assign_stratum(m)
    m.to_parquet(os.path.join(args.out, "joined_bar.parquet"), index=False)

    print("\n" + "=" * 78)
    print("MEASUREMENT 1 -- LOGIC TIE-OUT (same curve, same units, same instant)")
    print("=" * 78)
    print(m["stratum"].value_counts().to_string())

    d = m[m["stratum"] == "DECISIVE"].copy()
    print(f"\ndecisive rows: {len(d)}")
    print(f"overall agreement: {100.0 * (d['dealer_direction'] == d['side_new']).mean():.4f}%"
          f"   kappa {cohen_kappa(d['dealer_direction'], d['side_new']):.6f}")
    hi = d[d["direction_confidence"] == "HIGH"]
    if len(hi):
        print(f"old-HIGH decisive: n={len(hi)} "
              f"agreement {100.0 * (hi['dealer_direction'] == hi['side_new']).mean():.4f}%"
              f"   kappa {cohen_kappa(hi['dealer_direction'], hi['side_new']):.6f}")

    print("\nby (confidence x method x old side):")
    print(agreement_table(d, ["direction_confidence", "classification_method",
                              "dealer_direction"]).to_string(index=False))

    print("\naggregate gates:")
    for side in ("PAID", "RECEIVED"):
        g = d[d["dealer_direction"] == side]
        print(f"  mean new p over old-{side}: {g['p_new'].mean():.4f}  (n={len(g)})")

    dis = d[d["dealer_direction"] != d["side_new"]]
    dis.to_parquet(os.path.join(args.out, "disagreements_bar.parquet"), index=False)
    print(f"\ndisagreements on decisive rows: {len(dis)}")
    if len(dis):
        print(dis[["unit_key", "as_of_date", "classification_method",
                   "direction_confidence", "spread_to_mid_bps", "deviation_bps",
                   "p_new", "dealer_direction", "side_new"]].head(40).to_string(index=False))

    # ------------------------------------------------------------------
    # The excluded strata are where the old curve is WORST (LEDGER F-20), so a
    # number computed only on DECISIVE is inflated by construction. Every
    # stratum therefore gets its own agreement rate, and the union of every row
    # on which BOTH systems made a call gets one too.
    # ------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("AGREEMENT WITHIN EVERY STRATUM (nothing hidden by the exclusions)")
    print("-" * 78)
    both_call = m[m["dealer_direction"].isin(["PAID", "RECEIVED"])
                  & m["side_new"].notna() & (m["dealer_sign"] != 0)].copy()
    rows = []
    for st in STRATA_ORDER + ["UNMATCHED"]:
        g = m[m["stratum"] == st]
        gb = g[g["dealer_direction"].isin(["PAID", "RECEIVED"]) & g["side_new"].notna()
               & (g["dealer_sign"] != 0)]
        rows.append({"stratum": st, "n": len(g), "both_called": len(gb),
                     "agree": int((gb["dealer_direction"] == gb["side_new"]).sum()),
                     "pct": 100.0 * (gb["dealer_direction"] == gb["side_new"]).mean()
                     if len(gb) else float("nan"),
                     "kappa": cohen_kappa(gb["dealer_direction"], gb["side_new"])
                     if len(gb) else float("nan")})
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nUNRESTRICTED (every row where both systems called): n={len(both_call)}  "
          f"agreement {100.0 * (both_call['dealer_direction'] == both_call['side_new']).mean():.4f}%"
          f"  kappa {cohen_kappa(both_call['dealer_direction'], both_call['side_new']):.6f}")
    ubd = both_call[both_call["dealer_direction"] != both_call["side_new"]]
    print(f"unrestricted disagreements: {len(ubd)}")
    if len(ubd):
        ubd.to_parquet(os.path.join(args.out, "disagreements_unrestricted.parquet"),
                       index=False)
        print(ubd["stratum"].value_counts().to_string())
        print(ubd["classification_method"].value_counts().to_string())
        cols = ["unit_key", "as_of_date", "stratum", "classification_method",
                "direction_confidence", "spread_to_mid_bps", "deviation_bps",
                "p_new", "dealer_direction", "side_new"]
        print(ubd[cols].head(50).to_string(index=False))

    # ------------------------------------------------------------------
    # NUMERICAL IDENTITY: the strongest single statement the logic tie-out can
    # make. If the deviations are the same number then a side disagreement can
    # only come from a rule difference, and those are enumerable.
    # ------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("NUMERICAL IDENTITY OF THE TWO PRICING PATHS (same curve object)")
    print("-" * 78)
    rr = m[(m["rule"] == "RATE_VS_MID") & m["spread_to_mid_bps"].notna()
           & m["deviation_bps"].notna()]
    dd = (rr["spread_to_mid_bps"] - rr["deviation_bps"]).abs()
    print(f"rate rule   n={len(rr):>6}  max|s2m_old - dev_new| = {dd.max():.3e} bp"
          f"   p99 = {dd.quantile(0.99):.3e}   exactly 0 on {int((dd == 0).sum())}")
    uu = m[(m["rule"] == "NPV_VS_UPFRONT") & m["repriced_npv"].notna()
           & m["npv_pay"].notna()]
    du = (uu["repriced_npv"] - uu["npv_pay"]).abs()
    dv = (uu["structure_dv01"] - uu["structure_dv01_new"]).abs() \
        if "structure_dv01_new" in uu else pd.Series([float("nan")])
    print(f"upfront rule n={len(uu):>6}  max|npv_old - npv_new| = {du.max():.3e} USD"
          f"   max|dv01 diff| = {dv.max():.3e}")

    # ------------------------------------------------------------------
    # "WHEN THE NEW ONE IS WRONG" -- the pre-registered test
    # ------------------------------------------------------------------
    tick2 = 2.0 * m.apply(half_tick, axis=1) * 2.0     # 2 x the bucket median tick
    against = m[(m["direction_confidence"] == "HIGH")
                & ~m["curve_suspect_trade"].fillna(False).astype(bool)
                & (m["spread_to_mid_bps"].abs() > tick2)
                & m["dealer_direction"].isin(["PAID", "RECEIVED"])
                & m["side_new"].notna()
                & (m["dealer_direction"] != m["side_new"])
                & (((m["dealer_direction"] == "PAID") & (m["p_new"] > 0.7))
                   | ((m["dealer_direction"] == "RECEIVED") & (m["p_new"] < 0.3)))]
    print(f"\nrows that COUNT AGAINST the new classifier (HIGH, not curve-suspect, "
          f"|s2m| > 2x tick, new p decisively opposite): {len(against)}")

    # ------------------------------------------------------------------
    # THE CALIBRATION EFFECT -- the third number, reported separately
    # ------------------------------------------------------------------
    sb_fitted = score(bar, cal_raw, tau_uf)
    mf = old[["unit_key", "dealer_direction", "classification_method",
              "direction_confidence"]].merge(
        sb_fitted[["unit_key", "side_new", "p_new", "rule"]], on="unit_key")
    mf = mf[mf["dealer_direction"].isin(["PAID", "RECEIVED"]) & mf["side_new"].notna()]
    print("\n" + "-" * 78)
    print("CALIBRATION EFFECT (same curve, same code, fitted b0 instead of b0=0)")
    print("-" * 78)
    print(f"n={len(mf)}  old %PAID {100.0 * (mf['dealer_direction'] == 'PAID').mean():.2f}"
          f"  new-with-fitted-b0 %PAID {100.0 * (mf['side_new'] == 'PAID').mean():.2f}"
          f"  label shift {100.0 * (mf['dealer_direction'] != mf['side_new']).mean():.2f}%")

    # ------------------------------------------------------------------
    # PROBABILITY vs PROBABILITY, where the old row carries a p_flip
    # ------------------------------------------------------------------
    pf = m[m["p_flip"].notna() & m["p_new"].notna()
           & m["dealer_direction"].isin(["PAID", "RECEIVED"])].copy()
    if len(pf):
        pf["p_old_received"] = np.where(pf["dealer_direction"] == "RECEIVED",
                                        1.0 - pf["p_flip"], pf["p_flip"])
        print("\n" + "-" * 78)
        print(f"PROBABILITY vs PROBABILITY on the {len(pf)} rows carrying an old p_flip")
        print("-" * 78)
        print(f"  spearman(p_old_received, p_new) = "
              f"{pf['p_old_received'].corr(pf['p_new'], method='spearman'):.4f}")
        print(f"  pearson  = {pf['p_old_received'].corr(pf['p_new']):.4f}")
        print(f"  mean p_old_received {pf['p_old_received'].mean():.4f}  "
              f"mean p_new {pf['p_new'].mean():.4f}")

    # ------------------------------------------------------------------
    # the named exception classes, enumerated
    # ------------------------------------------------------------------
    print("\n" + "-" * 78)
    print("NAMED EXCEPTION CLASSES")
    print("-" * 78)
    ref = m[m["stratum"] == "NEW_REFUSED"]
    if len(ref):
        print("NEW_REFUSED by reason:")
        print(ref["failure"].fillna(ref["exclusion"]).value_counts().to_string())
        print("  old side on those rows:")
        print(ref["dealer_direction"].value_counts(dropna=False).to_string())
        ref.to_parquet(os.path.join(args.out, "new_refused.parquet"), index=False)
    tie = m[m["stratum"] == "NEW_EXACT_TIE"]
    if len(tie):
        print(f"\nNEW_EXACT_TIE: {len(tie)} rows, old side "
              f"{tie['dealer_direction'].value_counts().to_dict()}")
        print(f"  max |dev_new| on those rows: {tie['deviation_bps'].abs().max():.3e}")
        print(f"  max |s2m_old| on those rows: {tie['spread_to_mid_bps'].abs().max():.3e}")
    old_unk = m[m["stratum"] == "OLD_UNKNOWN"]
    if len(old_unk):
        print(f"\nOLD_UNKNOWN: {len(old_unk)} rows; new side "
              f"{old_unk['side_new'].value_counts(dropna=False).to_dict()}")
        fl = old_unk["quality_flags"].astype(str).str.slice(0, 70).value_counts()
        print(fl.head(10).to_string())
    tr = m[m["stratum"] == "OLD_TICK_RULE"]
    if len(tr):
        agree_tr = (tr["dealer_direction"] == tr["side_new"])
        print(f"\nOLD_TICK_RULE: {len(tr)} rows; the new package has no tick-rule "
              f"analogue. Curve-rule side agrees with the tick side on "
              f"{100.0 * agree_tr.mean():.1f}% (a coin-flip baseline is ~50%).")

    # -- measurement 2 ------------------------------------------------------
    if len(citi):
        calc, b0c, tau_c, _ = calibrate(citi)
        sc = score(citi, calc, tau_c)
        b0c.to_csv(os.path.join(args.out, "fitted_b0_citi.csv"), index=False)
        both = sb[["unit_key", "side_new", "p_new", "deviation_bps", "rule",
                   "kind", "rate_index", "tenor_band", "failure"]].merge(
            sc[["unit_key", "side_new", "p_new", "deviation_bps", "failure"]],
            on="unit_key", how="inner", suffixes=("_bar", "_citi"))
        both.to_parquet(os.path.join(args.out, "curve_effect.parquet"), index=False)
        c = both[both["side_new_bar"].notna() & both["side_new_citi"].notna()]
        print("\n" + "=" * 78)
        print("MEASUREMENT 2 -- CURVE EFFECT (same code, Barchart -> Citi minute)")
        print("=" * 78)
        print(f"comparable units: {len(c)}")
        print(f"  Barchart: {100.0 * (c['side_new_bar'] == 'PAID').mean():.2f}% PAID")
        print(f"  Citi:     {100.0 * (c['side_new_citi'] == 'PAID').mean():.2f}% PAID")
        print(f"  label shift: {100.0 * (c['side_new_bar'] != c['side_new_citi']).mean():.2f}%"
              f"   kappa {cohen_kappa(c['side_new_bar'], c['side_new_citi']):.4f}")
        print("\nby rule x rate_index:")
        for keys, g in c.groupby(["rule", "rate_index"], dropna=False):
            print(f"  {keys}: n={len(g)}  bar %PAID {100.0 * (g['side_new_bar'] == 'PAID').mean():.1f}"
                  f"  citi %PAID {100.0 * (g['side_new_citi'] == 'PAID').mean():.1f}"
                  f"  shift {100.0 * (g['side_new_bar'] != g['side_new_citi']).mean():.1f}%"
                  f"  median dev bar {g['deviation_bps_bar'].median():+.4f}"
                  f"  citi {g['deviation_bps_citi'].median():+.4f}")
    print("\nwrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
