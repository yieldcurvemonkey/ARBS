"""Excluded vs retained: is the retained population a biased sample?

Every table this prints goes into docs/dealer_direction/2026-08-11-package-exclusion-skew.md.
Run AFTER pkgskew_validate.py passes.

DV01 everywhere means the gross `_dv01_proxy` convention -- sum of leg |DV01|,
notional sentinels zeroed -- identical to the coverage report's.
"""
from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd

CACHE = pathlib.Path(os.environ.get("PKGSKEW_CACHE", r"D:\pkgskew_cache"))
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_columns", 60)
pd.set_option("display.float_format", lambda v: f"{v:,.3f}")

BUCKETS = ["0-1Y", "1-2Y", "2-3Y", "3-5Y", "5-7Y", "7-10Y",
           "10-15Y", "15-20Y", "20-30Y", "30Y+"]
CLASSES = ["KEPT", "PKG4", "ASSETSWAP", "OTHER_EXCL"]
# as_of day starts ~20:00 ET the previous evening
HOURS = list(range(20, 24)) + list(range(0, 20))


def load(kind):
    fs = sorted(CACHE.glob(f"{kind}_*.parquet"))
    assert len(fs) == 30, f"expected 30 {kind} chunks, found {len(fs)}"
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)


def hdr(s):
    print("\n" + "=" * 100)
    print(s)
    print("=" * 100)


def pct(x, tot):
    return 100.0 * x / tot


def main() -> int:
    units = load("units")
    legs = load("legs")
    units["excl_class"] = pd.Categorical(units["excl_class"], CLASSES)
    legs["excl_class"] = pd.Categorical(legs["excl_class"], CLASSES)
    legs["tenor_bucket"] = pd.Categorical(legs["tenor_bucket"], BUCKETS, True)
    units["month"] = pd.to_datetime(units["as_of_date"]).dt.to_period("M")
    legs["month"] = pd.to_datetime(legs["as_of_date"]).dt.to_period("M")
    units["excluded"] = units["exclusion"].notna()
    legs["excluded"] = legs["exclusion"].notna()

    TOT = units["dv01_proxy"].sum()
    EXC = units.loc[units["excluded"], "dv01_proxy"].sum()
    print(f"universe  {len(units):,} units / {len(legs):,} legs / "
          f"DV01 {TOT:,.0f}")
    print(f"excluded  {units['excluded'].sum():,} units "
          f"({pct(units['excluded'].sum(), len(units)):.2f}%) / "
          f"DV01 {EXC:,.0f} ({pct(EXC, TOT):.2f}%)")

    # ================================================================== 1
    hdr("1a. TENOR MIX AND PER-BUCKET EXCLUSION RATE (leg DV01, maturity point)")
    lb = legs.pivot_table(index="tenor_bucket", columns="excl_class",
                          values="dv01", aggfunc="sum", observed=False,
                          fill_value=0.0)
    lb = lb.reindex(columns=CLASSES).fillna(0.0)
    lb["TOTAL"] = lb.sum(axis=1)
    lb["excl_rate_%"] = 100 * (lb["TOTAL"] - lb["KEPT"]) / lb["TOTAL"]
    lb["pkg4_rate_%"] = 100 * lb["PKG4"] / lb["TOTAL"]
    lb["aswap_rate_%"] = 100 * lb["ASSETSWAP"] / lb["TOTAL"]
    lb["tape_share_%"] = 100 * lb["TOTAL"] / lb["TOTAL"].sum()
    lb["kept_share_%"] = 100 * lb["KEPT"] / lb["KEPT"].sum()
    lb["delta_pp"] = lb["kept_share_%"] - lb["tape_share_%"]
    lb["rel_%"] = 100 * (lb["kept_share_%"] / lb["tape_share_%"] - 1)
    print(lb[["TOTAL", "tape_share_%", "kept_share_%", "delta_pp", "rel_%",
              "excl_rate_%", "pkg4_rate_%", "aswap_rate_%"]])
    r = lb["excl_rate_%"]
    print(f"\n  exclusion rate spread across buckets: "
          f"{r.min():.2f}% ({r.idxmin()}) -> {r.max():.2f}% ({r.idxmax()})  "
          f"= {r.max() - r.min():.2f} pp")
    print(f"  largest composition delta: {lb['delta_pp'].abs().max():.2f} pp  "
          f"({lb['delta_pp'].abs().idxmax()})   "
          f"largest relative distortion: {lb['rel_%'].abs().max():.1f}% "
          f"({lb['rel_%'].abs().idxmax()})")
    print("  L1 composition distance (half sum |delta|): "
          f"{0.5 * lb['delta_pp'].abs().sum():.2f} pp")

    hdr("1b. same, by LEG COUNT")
    cb = legs.pivot_table(index="tenor_bucket", columns="excl_class",
                          values="dv01", aggfunc="size", observed=False,
                          fill_value=0)
    cb = cb.reindex(columns=CLASSES).fillna(0)
    cb["TOTAL"] = cb.sum(axis=1)
    cb["excl_rate_%"] = 100 * (cb["TOTAL"] - cb["KEPT"]) / cb["TOTAL"]
    cb["tape_share_%"] = 100 * cb["TOTAL"] / cb["TOTAL"].sum()
    cb["kept_share_%"] = 100 * cb["KEPT"] / cb["KEPT"].sum()
    cb["delta_pp"] = cb["kept_share_%"] - cb["tape_share_%"]
    print(cb[["TOTAL", "tape_share_%", "kept_share_%", "delta_pp",
              "excl_rate_%"]])

    hdr("1c. ROBUSTNESS -- annuity-spread DV01 allocation instead of maturity point")
    sp = load("spread")
    sp["excl_class"] = pd.Categorical(sp["excl_class"], CLASSES)
    sp["tenor_bucket"] = pd.Categorical(sp["tenor_bucket"], BUCKETS, True)
    ab = sp.pivot_table(index="tenor_bucket", columns="excl_class",
                        values="dv01", aggfunc="sum", observed=False,
                        fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    ab["TOTAL"] = ab.sum(axis=1)
    ab["excl_rate_%"] = 100 * (ab["TOTAL"] - ab["KEPT"]) / ab["TOTAL"]
    ab["tape_share_%"] = 100 * ab["TOTAL"] / ab["TOTAL"].sum()
    ab["kept_share_%"] = 100 * ab["KEPT"] / ab["KEPT"].sum()
    ab["delta_pp"] = ab["kept_share_%"] - ab["tape_share_%"]
    print(ab[["TOTAL", "tape_share_%", "kept_share_%", "delta_pp", "excl_rate_%"]])
    ra = ab["excl_rate_%"]
    print(f"\n  spread {ra.min():.2f}% ({ra.idxmin()}) -> {ra.max():.2f}% "
          f"({ra.idxmax()}) = {ra.max() - ra.min():.2f} pp   "
          f"L1 {0.5 * ab['delta_pp'].abs().sum():.2f} pp")

    # ================================================================== 2
    hdr("2. TIME OF DAY (execution hour, ET; as_of day runs 20:00 ET -> 19:59 ET)")
    lh = legs[legs["hour_et"] >= 0]
    hp = lh.pivot_table(index="hour_et", columns="excl_class", values="dv01",
                        aggfunc="sum", observed=False, fill_value=0.0)
    hp = hp.reindex(index=HOURS, columns=CLASSES).fillna(0.0)
    hp["TOTAL"] = hp.sum(axis=1)
    hp["excl_rate_%"] = 100 * (hp["TOTAL"] - hp["KEPT"]) / hp["TOTAL"]
    for c in CLASSES:
        hp[f"{c}_shr_%"] = 100 * hp[c] / hp[c].sum()
    hp["tape_shr_%"] = 100 * hp["TOTAL"] / hp["TOTAL"].sum()
    print(hp[["TOTAL", "tape_shr_%", "KEPT_shr_%", "PKG4_shr_%",
              "ASSETSWAP_shr_%", "excl_rate_%"]])
    core = [h for h in HOURS if 7 <= h <= 16]
    for c in ("KEPT", "PKG4", "ASSETSWAP", "OTHER_EXCL"):
        s = hp.loc[core, c].sum() / hp[c].sum()
        print(f"  {c:<11} 07:00-16:59 ET share of its own DV01: {100 * s:.2f}%")
    print(f"  {'TAPE':<11} 07:00-16:59 ET share: "
          f"{100 * hp.loc[core, 'TOTAL'].sum() / hp['TOTAL'].sum():.2f}%")
    ov = [h for h in HOURS if h >= 20 or h <= 2]
    for c in ("KEPT", "PKG4", "ASSETSWAP", "OTHER_EXCL"):
        print(f"  {c:<11} 20:00-02:59 ET (overnight) share: "
              f"{100 * hp.loc[ov, c].sum() / hp[c].sum():.2f}%")

    # ================================================================== 3
    hdr("3. VENUE MIX")
    vp = legs.pivot_table(index="venue_class", columns="excl_class",
                          values="dv01", aggfunc="sum", observed=False,
                          fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    vp["TOTAL"] = vp.sum(axis=1)
    print("DV01 by venue x class")
    print(vp)
    print("\nwithin-class venue share of DV01 (%)")
    print(100 * vp[CLASSES] / vp[CLASSES].sum(axis=0))
    print("\nexclusion rate within each venue (%)")
    print((100 * (vp["TOTAL"] - vp["KEPT"]) / vp["TOTAL"]).to_frame("excl_rate_%"))
    print("\nsame, by leg count")
    vc = legs.pivot_table(index="venue_class", columns="excl_class",
                          values="dv01", aggfunc="size", observed=False,
                          fill_value=0).reindex(columns=CLASSES).fillna(0)
    print(vc)
    print(100 * vc / vc.sum(axis=0))

    # ================================================================== 4
    hdr("4a. BLOCK / CAPPED SHARE")
    bt = legs.groupby("excl_class", observed=False).agg(
        n_legs=("dv01", "size"), dv01=("dv01", "sum"),
        block_legs=("is_block", "sum"), capped_legs=("is_capped", "sum"))
    bt["block_%"] = 100 * bt["block_legs"] / bt["n_legs"]
    bt["capped_%"] = 100 * bt["capped_legs"] / bt["n_legs"]
    bt["block_dv01_%"] = 100 * legs[legs["is_block"]].groupby(
        "excl_class", observed=False)["dv01"].sum() / bt["dv01"]
    bt["capped_dv01_%"] = 100 * legs[legs["is_capped"]].groupby(
        "excl_class", observed=False)["dv01"].sum() / bt["dv01"]
    print(bt[["n_legs", "block_%", "capped_%", "block_dv01_%", "capped_dv01_%"]])

    hdr("4b. NOTIONAL DISTRIBUTION (per leg, $mm)")
    nn = legs.dropna(subset=["notional"])
    q = nn.groupby("excl_class", observed=False)["notional"].describe(
        percentiles=[.1, .25, .5, .75, .9, .99])
    print((q[["count", "mean", "10%", "25%", "50%", "75%", "90%", "99%", "max"]]
           / [1, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6, 1e6]))
    print("\nper-leg DV01 ($ per bp)")
    print(legs.groupby("excl_class", observed=False)["dv01"].describe(
        percentiles=[.25, .5, .75, .9, .99])[
        ["mean", "25%", "50%", "75%", "90%", "99%", "max"]])

    hdr("4c. STRUCTURE / TRADE TYPE MIX")
    print("unit `kind` (n_legs derived) by class -- DV01 %")
    kp = units.pivot_table(index="kind", columns="excl_class",
                           values="dv01_proxy", aggfunc="sum", observed=False,
                           fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    print(100 * kp / kp.sum(axis=0))
    print("\nleg `trade_type` by class -- DV01 % within class (top 14)")
    tp = legs.pivot_table(index="trade_type", columns="excl_class",
                          values="dv01", aggfunc="sum", observed=False,
                          fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    tp = (100 * tp / tp.sum(axis=0))
    print(tp.sort_values("PKG4", ascending=False).head(14))
    print("\nrate_index by class -- DV01 % within class")
    rp = legs.pivot_table(index="rate_index", columns="excl_class",
                          values="dv01", aggfunc="sum", observed=False,
                          fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    print(100 * rp / rp.sum(axis=0))
    print("\nlifecycle share of DV01 within class (%)")
    print((100 * units[units["is_lifecycle"]].groupby("excl_class", observed=False)
           ["dv01_proxy"].sum() / units.groupby("excl_class", observed=False)
           ["dv01_proxy"].sum()).to_frame("lifecycle_dv01_%"))
    print("\nPKG-4+ package_structure, top 15 by DV01")
    p4 = units[units["excl_class"] == "PKG4"]
    print(p4.groupby("package_structure", observed=True)["dv01_proxy"]
            .agg(["size", "sum"]).sort_values("sum", ascending=False).head(15))

    # ================================================================== 5
    hdr("5. STABILITY OVER TIME -- monthly exclusion rate by DV01")
    m = legs.pivot_table(index="month", columns="excl_class", values="dv01",
                         aggfunc="sum", observed=False, fill_value=0.0)
    m = m.reindex(columns=CLASSES).fillna(0.0)
    m["TOTAL"] = m.sum(axis=1)
    m["excl_%"] = 100 * (m["TOTAL"] - m["KEPT"]) / m["TOTAL"]
    m["pkg4_%"] = 100 * m["PKG4"] / m["TOTAL"]
    m["aswap_%"] = 100 * m["ASSETSWAP"] / m["TOTAL"]
    m["other_%"] = 100 * m["OTHER_EXCL"] / m["TOTAL"]
    print(m[["TOTAL", "excl_%", "pkg4_%", "aswap_%", "other_%"]])
    full = m.iloc[:-1]                      # 2026-08 is 5 trading days
    x = np.arange(len(full))
    for col in ("excl_%", "pkg4_%", "aswap_%"):
        y = full[col].to_numpy()
        b1, b0 = np.polyfit(x, y, 1)
        resid = y - (b0 + b1 * x)
        se = np.sqrt((resid ** 2).sum() / (len(x) - 2) /
                     ((x - x.mean()) ** 2).sum())
        print(f"  {col:<8} mean {y.mean():6.2f}%  sd {y.std(ddof=1):5.2f}pp  "
              f"range {y.min():.2f}-{y.max():.2f}  trend {12 * b1:+.2f} pp/yr "
              f"(se {12 * se:.2f})  first-6m {y[:6].mean():.2f}% "
              f"last-6m {y[-6:].mean():.2f}%")
    print("\n  regime breaks -- daily DV01-weighted rate, mean either side")
    dly = legs.pivot_table(index="as_of_date", columns="excl_class",
                           values="dv01", aggfunc="sum", observed=False,
                           fill_value=0.0).reindex(columns=CLASSES).fillna(0.0)
    dly["TOTAL"] = dly.sum(axis=1)
    d = pd.to_datetime(pd.Series(dly.index, index=dly.index))
    def share(mask, col):
        tot = dly.loc[mask, "TOTAL"].sum()
        if col == "EXCL":
            return 100 * (1 - dly.loc[mask, "KEPT"].sum() / tot)
        return 100 * dly.loc[mask, col].sum() / tot

    for brk in ("2024-07-01", "2024-10-07"):
        b = pd.Timestamp(brk)
        pre, post = d < b, d >= b
        for col, name in (("EXCL", "excl"), ("PKG4", "pkg4"),
                          ("ASSETSWAP", "aswap")):
            a, z = share(pre, col), share(post, col)
            print(f"    {brk}  {name:<6} pre {a:6.2f}%  post {z:6.2f}%"
                  f"  step {z - a:+.2f} pp")
        # local window: 60 trading days either side
        idx = np.arange(len(dly))
        pos = int((d < b).sum())
        w0, w1 = max(0, pos - 60), min(len(dly), pos + 60)
        lo_m = (idx >= w0) & (idx < pos)
        hi_m = (idx >= pos) & (idx < w1)
        rate = lambda mk: 100 * (1 - dly.loc[mk, "KEPT"].sum()
                                 / dly.loc[mk, "TOTAL"].sum())
        print(f"    {brk}  local +/-60d  pre {rate(lo_m):6.2f}%  "
              f"post {rate(hi_m):6.2f}%  step {rate(hi_m) - rate(lo_m):+.2f} pp")

    # ================================================================== 6
    hdr("6. RV SHAPE -- how many tenor buckets does a unit span?")
    units["span"] = np.where(units["n_tenor_buckets"] <= 1, "one bucket",
                             np.where(units["n_tenor_buckets"] == 2, "two",
                                      "three or more"))
    sp2 = units.pivot_table(index="span", columns="excl_class",
                            values="dv01_proxy", aggfunc="sum",
                            observed=False, fill_value=0.0)
    sp2 = sp2.reindex(columns=CLASSES).fillna(0.0)
    print("DV01 % within class")
    print(100 * sp2 / sp2.sum(axis=0))
    print("\nunit counts")
    print(units.pivot_table(index="span", columns="excl_class",
                            values="dv01_proxy", aggfunc="size",
                            observed=False, fill_value=0)
               .reindex(columns=CLASSES))
    print("\nn_legs distribution within PKG-4+ (units, DV01)")
    print(p4.groupby("n_legs")["dv01_proxy"].agg(["size", "sum"])
            .assign(dv01_pct=lambda t: 100 * t["sum"] / t["sum"].sum())
            .head(14))
    print("\nmaturity span of a unit (mat_max - mat_min), years")
    units["mat_span"] = units["mat_max"] - units["mat_min"]
    print(units.groupby("excl_class", observed=False)["mat_span"].describe(
        percentiles=[.25, .5, .75, .9])[["mean", "25%", "50%", "75%", "90%"]])

    # ================================================================== 7
    hdr("7. RECOVERY PATH -- what carries a package price or spread?")
    ex = units[units["excluded"]].copy()
    unor = units[units["exclusion"] == "UNORIENTABLE_PKG"].copy()
    unor["route"] = np.where(unor["any_ptp"], "PTP",
                             np.where(unor["any_pts"], "PTS only", "neither"))
    tab = unor.pivot_table(index="exclusion_detail", columns="route",
                           values="dv01_proxy", aggfunc="sum", fill_value=0.0)
    tab["TOTAL"] = tab.sum(axis=1)
    tab["ptp_%"] = 100 * tab.get("PTP", 0) / tab["TOTAL"]
    tab["pts_only_%"] = 100 * tab.get("PTS only", 0) / tab["TOTAL"]
    tab["any_%"] = tab["ptp_%"] + tab["pts_only_%"]
    tab["dv01_of_universe_%"] = 100 * tab["TOTAL"] / TOT
    print(tab.sort_values("TOTAL", ascending=False))
    print("\nby class:")
    for cls in ("PKG4", "ASSETSWAP"):
        s = unor[unor["excl_class"] == cls]
        t = s["dv01_proxy"].sum()
        print(f"  {cls:<10} DV01 {t:,.0f} ({pct(t, TOT):.2f}% of universe)")
        for lab, mk in (("any-leg PTP", s["any_ptp"]),
                        ("any-leg PTS", s["any_pts"]),
                        ("PTP or PTS", s["any_ptp"] | s["any_pts"]),
                        ("PTP and PTS", s["any_ptp"] & s["any_pts"]),
                        ("ptp_group_id", s["any_ptp_grp"]),
                        ("neither", ~(s["any_ptp"] | s["any_pts"]))):
            v = s.loc[mk, "dv01_proxy"].sum()
            print(f"      {lab:<14} {pct(v, t):6.2f}% of class DV01   "
                  f"{pct(v, TOT):6.2f}% of universe   units {int(mk.sum()):>7,}")
        print(f"      identified UST (ust_cusip on any leg): "
              f"{pct(s.loc[s['any_ust_cusip'], 'dv01_proxy'].sum(), t):.2f}% "
              f"of class DV01")
    print("\nopa_sign_confidence on the excluded UNORIENTABLE units (DV01 %)")
    oc = unor.pivot_table(index="opa_sign_confidence", columns="excl_class",
                          values="dv01_proxy", aggfunc="sum", observed=False,
                          dropna=False, fill_value=0.0)
    print(100 * oc / oc.sum(axis=0))
    print("\nbaseline: the SAME flags on the RETAINED population (DV01 %)")
    kp2 = units[~units["excluded"]]
    kt = kp2["dv01_proxy"].sum()
    for lab, mk in (("any-leg PTP", kp2["any_ptp"]), ("any-leg PTS", kp2["any_pts"]),
                    ("PTP or PTS", kp2["any_ptp"] | kp2["any_pts"])):
        print(f"  retained {lab:<14} {pct(kp2.loc[mk, 'dv01_proxy'].sum(), kt):6.2f}%")

    # ================================================================== 8
    hdr("8. WHAT THE PKG-4+ POND LOOKS LIKE IF IT WERE RECOVERED")
    rec = unor[(unor["excl_class"] == "PKG4") & unor["any_ptp"]]
    rdv = rec["dv01_proxy"].sum()
    print(f"  recoverable-by-PTP PKG-4+ DV01 {rdv:,.0f} "
          f"= {pct(rdv, TOT):.2f}% of universe, {len(rec):,} units")
    new_kept = pct(units.loc[~units["excluded"], "dv01_proxy"].sum() + rdv, TOT)
    print(f"  retained DV01 would go 56.96% -> {new_kept:.2f}%")

    rl = legs[(legs["excl_class"] == "PKG4") & legs["unit_any_ptp"]]
    add = rl.groupby("tenor_bucket", observed=False)["dv01"].sum().reindex(BUCKETS)
    after = lb[["TOTAL", "KEPT"]].copy()
    after["KEPT2"] = after["KEPT"] + add.fillna(0.0)
    after["now_%"] = 100 * (1 - after["KEPT"] / after["TOTAL"])
    after["after_%"] = 100 * (1 - after["KEPT2"] / after["TOTAL"])
    after["tape_share_%"] = 100 * after["TOTAL"] / after["TOTAL"].sum()
    after["kept2_share_%"] = 100 * after["KEPT2"] / after["KEPT2"].sum()
    after["delta_pp_after"] = after["kept2_share_%"] - after["tape_share_%"]
    print("\n  per-bucket exclusion rate, now vs after recovering PKG-4+ with a PTP")
    print(after[["now_%", "after_%", "tape_share_%", "kept2_share_%",
                 "delta_pp_after"]])
    ra2 = after["after_%"]
    print(f"  rate spread would go {r.max() - r.min():.2f} pp -> "
          f"{ra2.max() - ra2.min():.2f} pp;  L1 composition distance "
          f"{0.5 * lb['delta_pp'].abs().sum():.2f} -> "
          f"{0.5 * after['delta_pp_after'].abs().sum():.2f} pp")

    print("\n  venue mix of the recoverable PKG-4+ pond (DV01 %)")
    print(100 * rl.groupby("venue_class", observed=True)["dv01"].sum()
          / rl["dv01"].sum())

    # ================================================================== 9
    hdr("9a. WHERE THE 2024 LEVEL SHIFT COMES FROM -- OTHER_EXCL by constant")
    oe = units[units["excl_class"] == "OTHER_EXCL"]
    om = oe.pivot_table(index="month", columns="exclusion",
                        values="dv01_proxy", aggfunc="sum", fill_value=0.0)
    tm = units.groupby("month")["dv01_proxy"].sum()
    print((100 * om.div(tm, axis=0)).round(3))
    print("\n  trend on 2024-07..2026-07 only (drops the pre-ingest-change tape)")
    m2 = m.loc["2024-07":"2026-07"]
    x2 = np.arange(len(m2))
    for col in ("excl_%", "pkg4_%", "aswap_%", "other_%"):
        y = m2[col].to_numpy()
        b1, b0 = np.polyfit(x2, y, 1)
        res = y - (b0 + b1 * x2)
        se = np.sqrt((res ** 2).sum() / (len(x2) - 2)
                     / ((x2 - x2.mean()) ** 2).sum())
        print(f"    {col:<8} mean {y.mean():6.2f}%  sd {y.std(ddof=1):5.2f}pp  "
              f"trend {12 * b1:+.2f} pp/yr (se {12 * se:.2f})  "
              f"t {b1 / se:+.2f}")

    hdr("9b. PER-BUCKET RETENTION FACTOR -- what a ladder level is multiplied by")
    rf = lb[["TOTAL", "KEPT"]].copy()
    rf["retention"] = rf["KEPT"] / rf["TOTAL"]
    rf["vs_best"] = rf["retention"] / rf["retention"].max()
    rf["tape_share_%"] = lb["tape_share_%"]
    print(rf[["tape_share_%", "retention", "vs_best"]])
    print(f"  retention ranges {rf['retention'].min():.3f} "
          f"({rf['retention'].idxmin()}) to {rf['retention'].max():.3f} "
          f"({rf['retention'].idxmax()}) -- a "
          f"{rf['retention'].max() / rf['retention'].min():.2f}x cross-bucket "
          f"scaling distortion")

    hdr("9c. SINGLE-BUCKET EXCLUDED PACKAGES -- the directly harmful case")
    for cls in ("PKG4", "ASSETSWAP"):
        s = units[(units["excl_class"] == cls) & (units["n_tenor_buckets"] == 1)]
        t = units.loc[units["excl_class"] == cls, "dv01_proxy"].sum()
        print(f"  {cls}: {len(s):,} units, DV01 {s['dv01_proxy'].sum():,.0f} "
              f"= {pct(s['dv01_proxy'].sum(), t):.2f}% of class, "
              f"{pct(s['dv01_proxy'].sum(), TOT):.2f}% of universe")
        b = (s.groupby("bucket_top_dv01", observed=True)["dv01_proxy"].sum()
              .reindex(BUCKETS).fillna(0.0))
        print((100 * b / b.sum()).round(2).to_frame(f"{cls} 1-bkt DV01 %").T)
    print("\n  same-tenor PKG-4+ (all legs one bucket) as a share of each "
          "bucket's TAPE DV01")
    s1 = units[(units["excl_class"] == "PKG4") & (units["n_tenor_buckets"] == 1)]
    b1s = (s1.groupby("bucket_top_dv01", observed=True)["dv01_proxy"].sum()
             .reindex(BUCKETS).fillna(0.0))
    print((100 * b1s / lb["TOTAL"]).round(2).to_frame("% of bucket tape DV01").T)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
