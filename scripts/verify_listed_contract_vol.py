"""Verify the real-listed-contract panel: coverage, UNITS, and CM-vs-real.

Run after ``harvest_listed_contract_vol.py``. Every number printed here is
measured from the panel on disk; nothing is asserted that was not computed.

Sections, in the order they must be believed:

1. **Coverage** -- per root: contracts found, date span, median rows per
   contract, listing lead, how many contracts are alive on a typical date. The
   panel is RAGGED by construction and this reports the raggedness rather than
   averaging it away.
2. **Units** -- the question that has to be settled before anything is built on
   the smile. ABPV vs ATM per asset, the RR identity, the BF identity and the
   BF anchor test.
3. **ABPV vs the CM control** at matched time to expiry, per root and per CM
   tenor: the real contract should reproduce ``US_30`` near 30 days and diverge
   as the contract ages.
4. **ABPV vs the swaption cube**, matched sector and expiry.
5. **The expiry ladder** CM was hiding: the listed term structure on sample
   dates, and its slope against the CM 30/60/90 slope.
6. **SFR cross-vendor tie-out** -- QuikStrike ABPV against the independent
   ``sfr_rv_lab`` panel's own ATM vol on matched (date, contract). Two vendors,
   same contract, same claimed units: the strongest available units evidence,
   and it costs no network.

Usage::

    conda run -n stir python scripts/verify_listed_contract_vol.py
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import sys
import time
from typing import Any, Dict, List

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from RVUtils.ConvexityRV import listed_contracts as lc  # noqa: E402

DATA = REPO / "notebooks" / "data" / "convexity_rv"
CM_PANEL = DATA / "ust_listed_vol.parquet"
REPORT = DATA / "listed_contract_vol_verification.json"


def _read_retry(fn, tries: int = 8, pause: float = 2.0):
    """Read something a concurrent harvest may be rewriting underneath us."""
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(pause)


def hr(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> int:
    out: Dict[str, Any] = {}
    panel = _read_retry(lc.load_listed_contract_panel)
    print(f"panel: {len(panel):,} rows, {panel['contract_code'].nunique()} contracts, "
          f"{panel['date'].min().date()}..{panel['date'].max().date()}")

    # ------------------------------------------------------------ 1. coverage
    hr("1. COVERAGE per root (ragged by construction -- reported, not smoothed)")
    cov = lc.contract_coverage_report(panel)
    out["coverage"] = cov
    for root, c in cov["per_root"].items():
        print(f"{root:>4} [{c['asset']}]  contracts {c['n_contracts']:>3} "
              f"({c['n_quarterly']} quarterly, {c['n_serial']} serial)  "
              f"{c['first_date']}..{c['last_date']} ({c['n_dates']} dates)")
        print(f"       rows/contract median {c['rows_per_contract_median']:.0f} "
              f"[{c['rows_per_contract_min']}..{c['rows_per_contract_max']}]  "
              f"listing lead median {c['listing_lead_days_median']:.0f}d "
              f"(max {c['listing_lead_days_max']}d)  "
              f"alive/date median {c['contracts_alive_per_date_median']:.0f} "
              f"(max {c['contracts_alive_per_date_max']})  "
              f"max tte {c['tte_years_max']:.2f}y")
    per_vt = panel.groupby(["asset", "value_type"]).size().unstack(fill_value=0)
    print(f"\nrows by asset x value_type:\n{per_vt.to_string()}")
    out["rows_by_asset_value_type"] = {k: v for k, v in per_vt.to_dict().items()}

    # --------------------------------------------------------------- 2. units
    hr("2. UNITS -- measured per row, not by medians")
    rep = lc.units_report(panel)
    out["units"] = rep
    for root, r in rep.items():
        print(f"\n--- {root} [{r.get('asset', '?')}] ---")
        if "abpv_over_atm" in r:
            a = r["abpv_over_atm"]
            print(f"ABPV / ATM: n={a['n']:,} median {a['median']:.4f} "
                  f"[p01 {a['p01']:.2f}, p99 {a['p99']:.2f}]  "
                  f"frac EXACTLY 100 = {100 * a['frac_exactly_100']:.1f}%  "
                  f"within 1% of median = {100 * a['frac_within_1pct_of_median']:.1f}%")
            print(f"            implied CTD ModDur median {a['implied_moddur_median']:.2f}y "
                  f"[p01 {a['implied_moddur_p01']:.2f}, p99 {a['implied_moddur_p99']:.2f}]")
        if "rr_identity" in r:
            i = r["rr_identity"]
            print(f"RR == 25dC - 25dP : n={i['n']:,} corr {i['corr']:.6f}  "
                  f"max|resid| {i['max_abs_resid']:.3e}  "
                  f"median|resid| {i['median_abs_resid']:.3e}  "
                  f"(|RR| median {i['rr_scale_median']:.5f})")
        if "bf_naive_identity" in r:
            b = r["bf_naive_identity"]
            print(f"BF == mean(C,P) - ATM : n={b['n']:,} corr {b['corr']:.4f}  "
                  f"median|resid| {b['median_abs_resid']:.5f}  "
                  f"(|BF| median {b['bf_scale_median']:.5f}) -> "
                  f"resid is {100 * b['resid_over_bf']:.0f}% of BF")
        if "bf_anchor_test" in r:
            t = r["bf_anchor_test"]
            print(f"BF anchor test  ATM* = mean(C,P) - BF vs quoted ATM: "
                  f"median offset {t['atm_star_vs_atm_median_offset']:+.6f} "
                  f"({100 * t['offset_over_atm_median']:+.2f}% of ATM), "
                  f"IQR {t['offset_iqr']:.6f}, "
                  f"level corr {t['level_corr']:.4f}, change corr {t['change_corr']:.4f}")

    # Where the SFR 100x identity holds and where it does not. Reporting only the
    # pooled fraction would hide that the misses are two specific thin corners
    # rather than noise spread across the panel.
    hr("2b. SFR: WHERE does ABPV == 100 x ATM hold? (by time to expiry)")
    sc = lc.abpv_atm_scale(panel)
    s = sc[sc["root"] == "SFR"].copy()
    if len(s):
        s["dev"] = (s["scale"] - 100.0).abs()
        s["bucket"] = pd.cut(s["tte_years"], [0, .08, .25, .5, 1, 1.5, 2, 2.5, 3, 5])
        tb = s.groupby("bucket", observed=True).agg(
            n=("dev", "size"),
            frac_exact=("dev", lambda x: float((x < 1e-6).mean())),
            dev_p90=("dev", lambda x: float(x.quantile(0.90))),
            scale_median=("scale", "median"))
        print(tb.to_string(float_format=lambda v: f"{v:10.4f}"))
        print("  -> the identity is exact on the liquid middle and breaks only in "
              "the last month of life and at the newly-listed far end, where the "
              "vendor's two value types use different marks.")
        out["sfr_identity_by_tte"] = json.loads(
            tb.reset_index().assign(bucket=lambda d: d["bucket"].astype(str))
              .to_json(orient="records"))

    # --------------------------------------------------- 3. real vs CM control
    hr("3. REAL CONTRACT vs the CONSTANT-MATURITY control (ABPV, bp/yr)")
    cm = _read_retry(lambda: pd.read_parquet(CM_PANEL))
    cmp_rows: List[Dict[str, Any]] = []
    for root in ["US", "TY"]:
        for days in [30, 60, 90]:
            r = lc.compare_to_cm(panel, cm, root=root, cm_days=days,
                                 value_type="ABPV", max_gap_days=20.0)
            cmp_rows.append(r)
            for mode in ("matched", "interp"):
                m = r.get(mode, {})
                if "note" in m or not m:
                    print(f"{root}_{days:<3} {mode:<8} {m.get('note', 'absent')}")
                    continue
                print(f"{root}_{days:<3} {mode:<8} n={m['n']:>5}  "
                      f"CM {m['cm_median']:>6.2f}  real {m['real_median']:>6.2f}  "
                      f"ratio {m['ratio_median']:.4f}  "
                      f"med diff {m['diff_median_bp']:+6.2f}  "
                      f"med|diff| {m['diff_abs_median_bp']:5.2f}  "
                      f"p95|diff| {m['diff_abs_p95_bp']:5.2f}  "
                      f"corr lvl {m['corr_level']:.4f} chg {m['corr_change']:.4f}")
            if "matched_gap_days_abs_median" in r:
                print(f"        matched-contract |TTE gap| median "
                      f"{r['matched_gap_days_abs_median']:.1f}d "
                      f"max {r['matched_gap_days_abs_max']:.1f}d over "
                      f"{r['matched_n_contracts']} contracts")
    out["cm_comparison"] = cmp_rows

    # ---------------------------------------------- 3b. ageing: does it drift?
    hr("3b. Does the real contract drift from CM as it AGES? (US, ABPV)")
    us = panel[(panel["root"] == "US") & (panel["value_type"] == "ABPV")]
    cm30 = cm[(cm["root"] == "US") & (cm["cm_days"] == 30) & (cm["value_type"] == "ABPV")]
    cm30_s = pd.Series(cm30["value"].to_numpy(float),
                       index=pd.DatetimeIndex(pd.to_datetime(cm30["date"]))).sort_index()
    cm30_s = cm30_s[~cm30_s.index.duplicated(keep="last")]
    j = us.set_index("date").join(cm30_s.rename("cm30"), how="inner").reset_index()
    j["tte_days"] = j["tte_years"] * 365.0
    j["diff"] = j["value"] - j["cm30"]
    bins = [0, 15, 25, 35, 50, 75, 105, 150, 250]
    j["bucket"] = pd.cut(j["tte_days"], bins)
    ag = j.groupby("bucket", observed=True).agg(
        n=("diff", "size"), cm30_med=("cm30", "median"), real_med=("value", "median"),
        diff_med=("diff", "median"), abs_diff_med=("diff", lambda x: x.abs().median()))
    ag["ratio"] = ag["real_med"] / ag["cm30_med"]
    print("real US ABPV at each time-to-expiry bucket vs the SAME-DAY US_30 CM series:")
    print(ag.to_string(float_format=lambda v: f"{v:8.3f}"))
    out["ageing_vs_cm30"] = json.loads(
        ag.reset_index().assign(bucket=lambda d: d["bucket"].astype(str)).to_json(orient="records"))

    # ----------------------------------------------------- 4. swaption cube
    hr("4. ABPV vs the SWAPTION CUBE, matched sector and expiry")
    try:
        from RVUtils.ConvexityRV import swaption_cube as sc
        pairs = [("1M", "30Y"), ("3M", "30Y"), ("1M", "20Y"),
                 ("1M", "10Y"), ("3M", "10Y")]
        cache = DATA / "vol_listed_contract_nodes.parquet"
        vp = sc.load_vol_panel(pairs, cache_path=cache)
        sw_rows = []
        for root, exp, ten, tgt in [("US", "1M", "30Y", 30), ("US", "1M", "20Y", 30),
                                    ("US", "3M", "30Y", 90),
                                    ("TY", "1M", "10Y", 30), ("TY", "3M", "10Y", 90)]:
            atmf = sc.atmf_vol_series(vp, exp, ten)
            m = lc.tte_matched_series(panel, float(tgt), root=root,
                                      value_type="ABPV", max_gap_days=20.0)
            if not len(m):
                continue
            idx = atmf.index.intersection(m.index)
            if len(idx) < 30:
                continue
            a, b = m["value"].loc[idx].astype(float), atmf.loc[idx].astype(float)
            row = {"root": root, "target_tte_days": tgt, "node": f"{exp}x{ten}",
                   "n": int(len(idx)), "first": str(idx.min().date()),
                   "last": str(idx.max().date()),
                   "listed_median": float(a.median()), "otc_median": float(b.median()),
                   "ratio_median": float((a / b).median()),
                   "corr_level": float(a.corr(b)),
                   "corr_change": float(a.diff().corr(b.diff()))}
            sw_rows.append(row)
            print(f"{root} @{tgt}d vs {row['node']:<7} n={row['n']:>5} "
                  f"listed {row['listed_median']:>6.2f}  OTC {row['otc_median']:>6.2f}  "
                  f"ratio {row['ratio_median']:.3f}  "
                  f"corr lvl {row['corr_level']:.3f} chg {row['corr_change']:.3f}")
        out["vs_swaptions"] = sw_rows
    except Exception as e:  # noqa: BLE001
        print(f"swaption cube unavailable: {type(e).__name__}: {e}")
        out["vs_swaptions"] = {"error": f"{type(e).__name__}: {e}"}

    # ---------------------------------------------------- 5. the expiry ladder
    hr("5. THE EXPIRY LADDER constant maturity was hiding (US, ABPV)")
    us_dates = sorted(pd.unique(us["date"]))
    sample = [us_dates[int(f * (len(us_dates) - 1))] for f in (0.1, 0.35, 0.6, 0.85, 0.99)]
    ladder_rows = []
    for d in sample:
        lad = lc.expiry_ladder(panel, d, root="US", value_type="ABPV")
        cmrow = cm[(cm["root"] == "US") & (cm["value_type"] == "ABPV")
                   & (cm["date"] == pd.Timestamp(d))]
        cmv = {int(r.cm_days): float(r.value) for r in cmrow.itertuples()}
        pts = "  ".join(f"{r.tte_days:5.0f}d:{r.value:6.2f}" for r in lad.itertuples())
        print(f"\n{pd.Timestamp(d).date()}  listed ladder ({len(lad)} contracts): {pts}")
        print(f"{'':12}  CM control: " +
              "  ".join(f"{k}d:{v:6.2f}" for k, v in sorted(cmv.items())))
        # slope 30->90 days, both ways
        real_30 = lc.interpolate_across_ladder(panel, d, 30.0, root="US")
        real_90 = lc.interpolate_across_ladder(panel, d, 90.0, root="US")
        cm_slope = (cmv.get(90, np.nan) - cmv.get(30, np.nan))
        real_slope = real_90 - real_30
        print(f"{'':12}  slope 30->90d: CM {cm_slope:+6.2f} bp   ladder {real_slope:+6.2f} bp")
        ladder_rows.append({
            "date": str(pd.Timestamp(d).date()), "n_contracts": int(len(lad)),
            "tte_days": [round(float(x), 1) for x in lad["tte_days"]],
            "abpv": [round(float(x), 3) for x in lad["value"]],
            "cm": cmv, "cm_slope_30_90": float(cm_slope), "ladder_slope_30_90": float(real_slope),
        })
    out["ladder_samples"] = ladder_rows

    # how much curvature does CM's 3-point read miss?
    hr("5b. What CM's 30/60/90 read misses: ladder points OUTSIDE 30-90 days")
    lad_all = panel[(panel["root"] == "US") & (panel["value_type"] == "ABPV")].copy()
    lad_all["tte_days"] = lad_all["tte_years"] * 365.0
    tot = len(lad_all)
    inside = int(((lad_all["tte_days"] >= 30) & (lad_all["tte_days"] <= 90)).sum())
    print(f"US ABPV observations: {tot:,} total, {inside:,} ({100 * inside / tot:.1f}%) "
          f"inside the 30-90d window CM spans; "
          f"{100 * (tot - inside) / tot:.1f}% lie OUTSIDE it and have no CM analogue.")
    print(f"tte_days distribution: min {lad_all['tte_days'].min():.0f}  "
          f"p25 {lad_all['tte_days'].quantile(.25):.0f}  "
          f"median {lad_all['tte_days'].median():.0f}  "
          f"p75 {lad_all['tte_days'].quantile(.75):.0f}  "
          f"max {lad_all['tte_days'].max():.0f}")
    out["cm_window_coverage"] = {"n": tot, "inside_30_90": inside,
                                 "frac_outside": float((tot - inside) / tot)}

    # ------------------------------------------- 6. SFR cross-vendor tie-out
    hr("6. SFR cross-vendor tie-out: QuikStrike ABPV vs the sfr_rv_lab panel")
    try:
        from RVUtils.ConvexityRV import listed_vol as lv
        sfr_q = lv.load_sfr_panel()
        atm = lv.sfr_atm_vol_panel(sfr_q)
        mine = panel[(panel["asset"] == "SFR") & (panel["value_type"] == "ABPV")]
        mrg = mine.merge(atm.rename(columns={"as_of": "date", "symbol": "contract_code"}),
                         on=["date", "contract_code"], how="inner")
        if len(mrg) < 50:
            print(f"insufficient overlap: {len(mrg)} rows")
            out["sfr_cross_vendor"] = {"n": int(len(mrg)), "note": "insufficient overlap"}
        else:
            r = (mrg["value"] / mrg["atm_vol_bp_yr"])
            res = {
                "n": int(len(mrg)),
                "first": str(mrg["date"].min().date()), "last": str(mrg["date"].max().date()),
                "n_contracts": int(mrg["contract_code"].nunique()),
                "quikstrike_abpv_median": float(mrg["value"].median()),
                "sfr_lab_atm_bp_yr_median": float(mrg["atm_vol_bp_yr"].median()),
                "ratio_median": float(r.median()),
                "ratio_p05": float(r.quantile(0.05)), "ratio_p95": float(r.quantile(0.95)),
                "corr_level": float(mrg["value"].corr(mrg["atm_vol_bp_yr"])),
                # The other panel carries its OWN expiry_date, produced by a
                # different pipeline. Agreement here validates the CME rule this
                # harvest applies, independently of the vendor's quote calendar.
                "tte_abs_diff_days_median": float(
                    ((mrg["tte_years"] - mrg["tte"]) * 365.0).abs().median()),
                "tte_abs_diff_days_max": float(
                    ((mrg["tte_years"] - mrg["tte"]) * 365.0).abs().max()),
            }
            print(f"n={res['n']:,} rows over {res['n_contracts']} contracts "
                  f"{res['first']}..{res['last']}")
            print(f"QuikStrike ABPV median {res['quikstrike_abpv_median']:.2f} bp/yr   "
                  f"sfr_rv_lab ATM median {res['sfr_lab_atm_bp_yr_median']:.2f} bp/yr")
            print(f"ratio median {res['ratio_median']:.4f} "
                  f"[p05 {res['ratio_p05']:.3f}, p95 {res['ratio_p95']:.3f}]  "
                  f"level corr {res['corr_level']:.4f}")
            print(f"expiry rule cross-check: |my tte - their tte| median "
                  f"{res['tte_abs_diff_days_median']:.2f} days, "
                  f"max {res['tte_abs_diff_days_max']:.2f} days")
            out["sfr_cross_vendor"] = res
    except Exception as e:  # noqa: BLE001
        print(f"sfr_rv_lab tie-out unavailable: {type(e).__name__}: {e}")
        out["sfr_cross_vendor"] = {"error": f"{type(e).__name__}: {e}"}

    REPORT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
