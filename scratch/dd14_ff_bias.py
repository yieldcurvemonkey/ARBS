"""Measurement C - is the no-bias result true on FED FUNDS, or only on SOFR?

F-15's clean bill of health is SOFR-only: 200 on-market SOFR outrights, median
(printed - mid) = +0.021 bp with a bootstrap CI that includes zero. Fed Funds is
exactly where the OLD curve failed hardest - F-20 measured per-meeting sign
flips on the MIX23 build, ``FOMC_APR26`` +1.32 bp / 82.4% above mid against
``FOMC_JUL26`` -0.68 bp / 18.1% above - so "the Citi minute curve has no
convention bias" is a claim that has never been tested where it matters most.

Direction is the SIGN of (printed - mid), so a systematic median offset does not
degrade the call, it INVERTS a share of it: at a median of +0.3 bp every print
between 0 and +0.3 bp is labelled "dealer received" when the balanced reading is
the opposite. A Fed Funds bias means FF labels cannot ship.

Same statistic as dd06/dd07/dd08, run through the SHIPPED module. Two deliberate
departures from the SOFR study, both stated rather than buried:

  * the tenor floor is widened from 0.5y to 0.08y. Fed Funds on this tape is
    12,167 on-market outrights and skews hard to the front - 3,147 of them sit
    between 1 and 3 months - so SOFR's floor would throw away the population the
    curve is actually asked about. The tenor mix actually drawn is reported.
  * the tenor gradient is cut on Fed Funds' own bands, not SOFR's.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from scipy import stats

from dd_measure import LEG_COLS, connect, describe, even_subsample, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

TARGET = 300      # ~200 was asked for; 300 leaves the FOMC-dated cut usable
CURVE = "USD-FEDFUNDS-1D"
OUT = "C:/Users/chris/clee/ARBS-dd/scratch/out_ff_bias.csv"
BANDS = [0, 0.26, 0.51, 1.01, 2.01, 5.01, 31]
LABELS = ["<=3M", "3-6M", "6M-1Y", "1-2Y", "2-5Y", "5-30Y"]

# NOTE THE coalesce() ON EVERY BOOLEAN. dd06's predicate spelled these
# `NOT l.is_spreadover AND NOT l.is_asset_swap`, and both columns are NULL --
# not false -- on the FOMC-dated legs: `NOT NULL` is NULL, so the row is
# dropped. That silently removed **43.6% of the Fed Funds on-market outright
# population (8,789 legs) and 36.8% of the SOFR one (231,455 legs)**, including
# essentially the entire FOMC-dated Fed Funds cohort -- which is precisely the
# population F-20 found the old curve failing on. Measured, then fixed.
_FF = f"""
  FROM {LEGS_TABLE} l
  WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.rate_index_clean = 'FED_FUNDS'
    AND coalesce(l.trade_type,'') = 'OUTRIGHT'
    AND NOT coalesce(l.is_off_market,false) AND NOT coalesce(l.is_mac,false)
    AND NOT coalesce(l.is_spreadover,false) AND NOT coalesce(l.is_asset_swap,false)
    AND NOT coalesce(l.is_unwind,false)
    AND coalesce(l.is_new_risk, true)
    AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
    AND l.tenor_years BETWEEN 0.08 AND 31
"""


def known_answer(rep) -> bool:
    """Two ways this study could measure something other than a Fed Funds bias.

    K1  the FF curve must actually price, and land near the print. If the curve
        name did not resolve, or the FF store were cold, the statistic would be
        a study of the fallback path.
    K2  the strict branch must report a lag. A silent ``None`` means the branch
        is unverified for this curve, and the whole point is that FF has never
        been checked.
    """
    br = rep.pricer
    ok = True
    print("  K1: three Fed Funds instants, strict, must price and report a lag")
    for t in ("2025-06-11 10:30", "2026-03-30 14:40", "2024-09-18 13:15"):
        instant = pd.Timestamp(t, tz=snapshot.NY)
        try:
            mark = br.mark_curve(CURVE, instant)
            lp = br.price_leg(CURVE, instant,
                              pd.Timestamp(instant).date() + pd.Timedelta(days=2),
                              pd.Timestamp(instant).date() + pd.Timedelta(days=370),
                              1e7)
            print(f"    {t}  policy={mark.policy:24s} lag={mark.lag_seconds}s  "
                  f"1Y mid={lp.mid_pct:.5f}%  pv01={lp.pv01:,.0f}")
            ok = ok and mark.lag_seconds is not None and 0.0 < lp.mid_pct < 10.0
        except Exception as exc:  # noqa: BLE001
            print(f"    {t}  FAILED {type(exc).__name__}: {str(exc)[:110]}")
            ok = False
    return ok


def draw(conn) -> pd.DataFrame:
    n = read_sql(conn, f"SELECT count(*) n {_FF}")["n"].iloc[0]
    k = max(1, int(n // (TARGET * 4)))
    pool = read_sql(conn, f"""
        SELECT {LEG_COLS} {_FF}
          AND mod(abs(hashtext(l.trade_id)), {k}) = 0
        ORDER BY l.execution_timestamp, l.trade_id""")
    print(f"  population {n:,}  modulus {k}  pool {len(pool)}")
    keep = [snapshot.in_session(CURVE, unit_from_leg(r)[1]) for _, r in pool.iterrows()]
    ins = pool[pd.Series(keep, index=pool.index)].reset_index(drop=True)
    print(f"  in Citi's published session: {len(ins)} ({len(ins)/max(1,len(pool)):.1%})")
    take = even_subsample(ins, TARGET)
    return take.sort_values(["as_of_date", "execution_timestamp", "trade_id"]).reset_index(drop=True)


def run(rep, pool: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t0 = time.perf_counter()
    for day, chunk in pool.groupby("as_of_date", sort=True):
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, _ = unit_from_leg(r, with_upfront=False)
                printed = float(r["fixed_rate"]) * 100.0
                rec = {"trade_id": r["trade_id"], "as_of_date": day,
                       "tenor_years": float(r["tenor_years"]),
                       "tenor_label": r["tenor_label"],
                       "platform": r["platform_identifier"], "venue": r["venue"],
                       "special_tenor_type": r["special_tenor_type"],
                       "fomc_meeting_label": r["fomc_meeting_label"],
                       "is_off_date": bool(r["is_off_date"] or False),
                       "is_block": bool(r["is_block"]),
                       "snap_et": pd.Timestamp(snap).tz_convert(snapshot.NY
                                                                ).strftime("%Y-%m-%d %H:%M"),
                       "printed_pct": printed}
                out = rep.price_unit(unit)
                if out.failure is None:
                    rec["mid_pct"] = out.pricing.leg_mid_pct[0]
                    rec["pv01"] = out.pricing.leg_pv01[0]
                    rec["lag_s"] = out.pricing.snapshot_lag_seconds
                    rec["diff_bp"] = (printed - rec["mid_pct"]) * 100.0
                else:
                    rec["error"] = f"{out.failure}: {(out.failure_detail or '')[:70]}"
                # control: the same print against the curve one minute earlier.
                # A median that barely moves is a CONVENTION statement, not a
                # timing one.
                ctrl = pd.Timestamp(snap) - pd.Timedelta(minutes=1)
                o2 = rep.price_unit(unit, instant=ctrl)
                if o2.failure is None:
                    rec["diff_bp_m1"] = (printed - o2.pricing.leg_mid_pct[0]) * 100.0
                rows.append(rec)
    print(f"  priced {len(rows)} prints over {pool['as_of_date'].nunique()} days "
          f"in {time.perf_counter()-t0:.0f}s")
    return pd.DataFrame(rows)


def placebo(rep, pool: pd.DataFrame, out: pd.DataFrame) -> pd.DataFrame:
    """The same prints against the same wall-minute SEVEN DAYS EARLIER.

    Seven days keeps the weekday and the time of day, so anything the statistic
    picks up from "Wednesday mid-morning" survives; what does not survive is the
    curve actually being the one the trade was struck against. If the placebo's
    dispersion is not far wider, the statistic is not reading the curve and the
    headline median means nothing.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.snapshot_policy import SnapshotMiss

    recs = []
    for _, r in pool.iterrows():
        unit, snap, _ = unit_from_leg(r, with_upfront=False)
        shifted = pd.Timestamp(snap) - pd.Timedelta(days=7)
        printed = float(r["fixed_rate"]) * 100.0
        rec = {"trade_id": r["trade_id"], "printed_pct": printed}
        try:
            o = rep.price_unit(unit, instant=shifted)
            if o.failure is None:
                rec["diff_bp_placebo"] = (printed - o.pricing.leg_mid_pct[0]) * 100.0
            else:
                rec["placebo_error"] = o.failure
        except SnapshotMiss:
            rec["placebo_error"] = "NO_CURVE"
        except Exception as exc:  # noqa: BLE001
            rec["placebo_error"] = type(exc).__name__
        recs.append(rec)
    rep.clear()
    p = pd.DataFrame(recs)
    return out.merge(p.drop(columns=["printed_pct"]), on="trade_id", how="left")


def report(out: pd.DataFrame) -> None:
    d = out["diff_bp"].dropna()
    n_err = int(out["error"].notna().sum()) if "error" in out else 0
    print(f"\n=== FED FUNDS: (printed - mid) in basis points, n = {len(d)} "
          f"({n_err} failed) ===")
    describe(d, "ALL")

    n = len(d)
    x = d.to_numpy()
    rng = np.random.default_rng(20260811)
    boot = np.median(rng.choice(x, size=(25_000, n), replace=True), axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    verdict = "INCLUDES zero" if lo <= 0 <= hi else "EXCLUDES ZERO"
    print(f"\n  median            {np.median(x):+.4f} bp")
    print(f"  mean              {x.mean():+.4f} bp  (sd {x.std(ddof=1):.4f}, "
          f"{abs(x.mean()/(x.std(ddof=1)/np.sqrt(n))):.1f} s.e. from zero)")
    print(f"  trimmed mean 10%  {stats.trim_mean(x, 0.1):+.4f} bp")
    print(f"  bootstrap 95% CI on the median: [{lo:+.4f}, {hi:+.4f}] bp -> {verdict}")
    n_pos = int((x > 0).sum())
    print(f"  sign test: {n_pos}/{n} above mid ({n_pos/n:.1%}), two-sided p = "
          f"{stats.binomtest(n_pos, n, 0.5).pvalue:.4f}")
    print(f"  Wilcoxon signed-rank vs 0: p = {stats.wilcoxon(x).pvalue:.4f}")
    for band in (0.05, 0.10, 0.25, 0.50):
        print(f"    within +/-{band:.2f} bp of mid: {(np.abs(x) <= band).mean():5.1%}")

    print("\n=== by special_tenor_type -- FOMC-dated is where the OLD curve broke ===")
    if "special_tenor_type" in out:
        for k, g in out.groupby(out["special_tenor_type"].fillna("<none>")):
            describe(g["diff_bp"], str(k))

    print("\n=== tenor gradient (a day-count / roll / spot-lag error grows with tenor) ===")
    bucket = pd.cut(out["tenor_years"], BANDS, labels=LABELS)
    for b in LABELS:
        describe(out.loc[bucket == b, "diff_bp"], b)

    print("\n=== by year ===")
    for y, g in out.groupby(pd.to_datetime(out["as_of_date"]).dt.year):
        describe(g["diff_bp"], str(y))

    print("\n=== block vs non-block, and by venue ===")
    describe(out.loc[out["is_block"], "diff_bp"], "block")
    describe(out.loc[~out["is_block"], "diff_bp"], "non-block")
    for v, g in out.groupby(out["venue"].fillna("<null>")):
        describe(g["diff_bp"], str(v))

    print("\n=== control: the same prints one minute earlier ===")
    describe(out["diff_bp_m1"], "t-1min curve")
    both = out[["diff_bp", "diff_bp_m1"]].dropna()
    if len(both) > 5:
        sh = both["diff_bp_m1"] - both["diff_bp"]
        print(f"  median shift from moving the curve back one minute: {sh.median():+.4f} bp")

    print("\n=== PLACEBO: same prints, same wall-minute, SEVEN DAYS EARLIER ===")
    p = out["diff_bp_placebo"].dropna()
    describe(p, "7d earlier")
    if "placebo_error" in out:
        errs = out["placebo_error"].dropna()
        if len(errs):
            print(f"  {len(errs)} placebo instants had no curve "
                  f"(holiday / out of session): {errs.value_counts().to_dict()}")
    if len(p) >= 20:
        iqr_real = d.quantile(.75) - d.quantile(.25)
        iqr_plac = p.quantile(.75) - p.quantile(.25)
        print(f"  IQR real {iqr_real:.4f} bp vs placebo {iqr_plac:.4f} bp "
              f"-> ratio {iqr_plac/iqr_real:.1f}x")
        print("  -> a ratio near 1 would mean the statistic is NOT reading the curve")


def main() -> None:
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    print("=== known-answer checks before anything is measured ===")
    if not known_answer(rep):
        print("KNOWN-ANSWER CHECKS FAILED - not measuring the Fed Funds bias.")
        return
    rep.clear()

    print("\n=== draw ===")
    conn = connect()
    pool = draw(conn)
    conn.close()
    print(f"  measuring {len(pool)} prints over {pool['as_of_date'].nunique()} days, "
          f"{pool['as_of_date'].min()} .. {pool['as_of_date'].max()}")
    print("  tenor mix drawn:")
    print(pd.cut(pool["tenor_years"].astype(float), BANDS,
                 labels=LABELS).value_counts().sort_index().to_string())
    print("  special_tenor_type mix drawn:")
    print(pool["special_tenor_type"].fillna("<none>").value_counts().to_string())

    out = run(rep, pool)
    out = placebo(rep, pool, out)
    out.to_csv(OUT, index=False)
    report(out)


if __name__ == "__main__":
    main()
