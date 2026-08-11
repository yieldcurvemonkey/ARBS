"""Measurement B - does the T-1min rule decide the answer?

T-1min is the stated snapshot rule and it is one arbitrary choice. The
classification is the **sign** of (printed - mid), so the question is not how
much the mid moves but how often that sign flips when the instant moves by five
or thirty seconds. If it flips materially at five seconds, a ladder built on one
choice is a ladder built on a coin toss, and that has to be known first.

What "T-5s" actually means here, said plainly because the label is misleading:
``alternative_snaps`` steps back five seconds from the print and does **not**
floor to the minute, and the store is stamped on whole minutes under a backward
-only ``asof``. So a 14:30:41 print asks for 14:30:36 and is served **14:30:00**
- the print's own minute, 5 to 60 seconds old rather than 5 seconds old. It is
still strictly before the print. T-1min asks for 14:29:00 and gets the previous
minute. So the comparison is really "the print's own minute vs the one before
it", and the fraction of prints where the two coincide is reported.

Harness validation before any of it is believed: the 200 legs behind LEDGER F-15
are repriced through the shipped module and must reproduce the recorded mids.
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

from dd_measure import LEG_COLS, connect, even_subsample, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import snap_timestamp

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

TARGET = 600
CURVE = "USD-SOFR-1D"
F15_CSV = "C:/Users/chris/clee/ARBS-dd/scratch/out_bias200.csv"
OUT = "C:/Users/chris/clee/ARBS-dd/scratch/out_snap_sensitivity.csv"

# coalesce() on every boolean: `NOT l.is_spreadover` is NULL, not true, on the
# 231,455 SOFR on-market outrights where that column is unset -- 36.8% of the
# population, silently dropped by dd06's spelling of this predicate.
_ON_MARKET = f"""
  FROM {LEGS_TABLE} l
  WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.rate_index_clean = 'SOFR'
    AND coalesce(l.trade_type,'') = 'OUTRIGHT'
    AND NOT coalesce(l.is_off_market,false) AND NOT coalesce(l.is_mac,false)
    AND NOT coalesce(l.is_spreadover,false) AND NOT coalesce(l.is_asset_swap,false)
    AND NOT coalesce(l.is_unwind,false)
    AND coalesce(l.is_new_risk, true)
    AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
    AND l.tenor_years BETWEEN 0.5 AND 31
"""


def validate_against_f15(rep) -> bool:
    """Reprice the exact legs behind F-15 and account for every difference.

    A tool that measures a *change* in the mid is worthless if it cannot first
    reproduce the mid. These 200 numbers came out of ``dd06_bias.py`` through
    ``dd_common``'s wiring; the shipped module is a different call path to the
    same curve.

    The bar is **not** "all 200 agree", and getting that wrong would have hidden
    the interesting part. ``dd06`` snapped on ``snap_timestamp(orig, exec)``,
    i.e. field #96 for every row; the shipped module routes a lifecycle row to
    #30 (F-12), so on a TERMINATION the two ask for genuinely different minutes
    and *must* differ. The bar is: bit-identical wherever the snapped instant is
    the same, and every remaining difference explained by the clock.
    """
    prev = pd.read_csv(F15_CSV)
    prev = prev[prev["mid_pct"].notna()]
    ids = [str(t) for t in prev["trade_id"]]
    conn = connect()
    rows = read_sql(conn, f"SELECT {LEG_COLS} FROM {LEGS_TABLE} l "
                          f"WHERE l.trade_id = ANY(%(ids)s)", {"ids": ids})
    conn.close()
    rows = rows.sort_values("as_of_date").reset_index(drop=True)
    got, same_snap = {}, {}
    for day, chunk in rows.groupby("as_of_date", sort=True):
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, _ = unit_from_leg(r, with_upfront=False)
                old = pd.Timestamp(snap_timestamp(r["original_execution_timestamp"],
                                                  r["execution_timestamp"]))
                same_snap[str(r["trade_id"])] = pd.Timestamp(snap) == old
                out = rep.price_unit(unit)
                if out.failure is None:
                    got[str(r["trade_id"])] = out.pricing.leg_mid_pct[0]
    prev["shipped_mid"] = [got.get(str(t)) for t in prev["trade_id"]]
    prev["same_snap"] = [same_snap.get(str(t)) for t in prev["trade_id"]]
    m = prev.dropna(subset=["shipped_mid"])
    agree = m[m["same_snap"]]
    moved = m[~m["same_snap"].astype(bool)]
    d = (agree["shipped_mid"] - agree["mid_pct"]).abs()
    ok = bool(len(m) >= 190 and (d.max() if len(d) else 0.0) < 1e-9)
    print(f"  repriced {len(m)}/{len(prev)} of the F-15 legs")
    print(f"  same snapped instant: {len(agree)} legs, "
          f"max |shipped - recorded| = {(d.max() if len(d) else 0.0):.3e} %  "
          f"-> {'bit-identical' if ok else 'DISAGREES'}")
    print(f"  different snapped instant: {len(moved)} legs -- all of them "
          f"lifecycle rows that dd06 priced at the FROZEN #96 and this prices at "
          f"#30 (F-12), median mid move "
          f"{((moved['shipped_mid'] - moved['mid_pct']).abs().median() * 100 if len(moved) else 0.0):.3f} bp")
    if len(moved):
        print(moved[["trade_id", "snap_et", "mid_pct", "shipped_mid"]].to_string(index=False))
    if not ok and len(d):
        print(agree.loc[d.nlargest(5).index,
                        ["trade_id", "snap_et", "mid_pct", "shipped_mid"]].to_string())
    return ok


def draw(conn) -> pd.DataFrame:
    n = read_sql(conn, f"SELECT count(*) n {_ON_MARKET}")["n"].iloc[0]
    k = max(1, int(n // (TARGET * 3)))
    pool = read_sql(conn, f"""
        SELECT {LEG_COLS} {_ON_MARKET}
          AND mod(abs(hashtext(l.trade_id)), {k}) = 0
        ORDER BY l.execution_timestamp, l.trade_id""")
    print(f"  population {n:,}  modulus {k}  pool {len(pool)}")
    # In-session only. Out of session the branch serves an hours-old curve for
    # all three snaps, so the three would agree by construction and the flip
    # rate would be diluted by rows that cannot flip.
    keep = []
    for _, r in pool.iterrows():
        _, snap, _ = unit_from_leg(r)
        keep.append(snapshot.in_session(CURVE, snap))
    ins = pool[pd.Series(keep, index=pool.index)].reset_index(drop=True)
    print(f"  in Citi's published session: {len(ins)} ({len(ins)/len(pool):.1%})")
    take = even_subsample(ins, TARGET)
    return take.sort_values(["as_of_date", "execution_timestamp", "trade_id"]).reset_index(drop=True)


def run(rep, pool: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t0 = time.perf_counter()
    for day, chunk in pool.groupby("as_of_date", sort=True):
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, _ = unit_from_leg(r, with_upfront=False)
                alts = snapshot.alternative_snaps(unit.clocks.pricing)
                printed = float(r["fixed_rate"]) * 100.0
                rec = {"trade_id": r["trade_id"], "as_of_date": day,
                       "tenor_years": float(r["tenor_years"]),
                       "printed_pct": printed,
                       "exec_et": pd.Timestamp(unit.clocks.pricing).tz_convert(
                           snapshot.NY).strftime("%Y-%m-%d %H:%M:%S")}
                for label, instant in (("t1m", snap), ("t30s", alts[30]), ("t5s", alts[5])):
                    out = rep.price_unit(unit, instant=instant)
                    if out.failure is not None:
                        rec[f"err_{label}"] = out.failure
                        continue
                    lag = out.pricing.snapshot_lag_seconds
                    req = pd.Timestamp(out.pricing.curve_timestamp)
                    rec[f"diff_{label}"] = (printed - out.pricing.leg_mid_pct[0]) * 100.0
                    rec[f"lag_{label}"] = lag
                    rec[f"served_{label}"] = (req - pd.Timedelta(seconds=lag)
                                              ).tz_convert("UTC").strftime("%Y-%m-%d %H:%M")
                rows.append(rec)
    dt = time.perf_counter() - t0
    print(f"  priced {len(rows)} prints x 3 snaps over "
          f"{pool['as_of_date'].nunique()} days in {dt:.0f}s")
    return pd.DataFrame(rows)


def report(out: pd.DataFrame) -> None:
    base = out.dropna(subset=["diff_t1m"]).copy()
    print(f"\n=== n = {len(base)} prints with a T-1min mid "
          f"({len(out) - len(base)} failed at T-1min) ===")

    print("\n--- what each snap was actually served ---")
    for lab in ("t1m", "t30s", "t5s"):
        g = base.dropna(subset=[f"diff_{lab}"])
        lag = g[f"lag_{lab}"]
        same = (g[f"served_{lab}"] == g["served_t1m"]).mean() if lab != "t1m" else 1.0
        print(f"  {lab:5s} n={len(g):4d}  served-lag median {lag.median():5.0f}s "
              f"p90 {lag.quantile(.9):5.0f}s max {lag.max():5.0f}s   "
              f"same served minute as T-1min: {same:6.1%}")

    print("\n--- sign of (printed - mid) ---")
    for lab in ("t1m", "t30s", "t5s"):
        g = base.dropna(subset=[f"diff_{lab}"])[f"diff_{lab}"]
        print(f"  {lab:5s} median {g.median():+.4f} bp  frac above mid {(g > 0).mean():6.1%}  "
              f"IQR width {g.quantile(.75) - g.quantile(.25):.3f} bp")

    print("\n--- SIGN FLIPS vs T-1min (the number that decides whether the rule matters) ---")
    for lab in ("t30s", "t5s"):
        g = base.dropna(subset=[f"diff_{lab}"]).copy()
        flip = np.sign(g[f"diff_{lab}"]) != np.sign(g["diff_t1m"])
        print(f"  {lab:5s} overall               {flip.mean():6.2%} "
              f"({int(flip.sum())}/{len(g)})")
        for band in (0.05, 0.10, 0.25, 0.50):
            m = g["diff_t1m"].abs() > band
            if m.sum() >= 20:
                print(f"        |diff at T-1min| > {band:.2f} bp   "
                      f"{flip[m].mean():6.2%} ({int(flip[m].sum())}/{int(m.sum())})"
                      f"   [{m.mean():.0%} of the sample]")
        # A flip on rows served the SAME minute is impossible - it would mean
        # the pass is not deterministic. Checked, not assumed.
        same = g[f"served_{lab}"] == g["served_t1m"]
        bad = int((flip & same).sum())
        print(f"        flips among the {int(same.sum())} rows served the SAME "
              f"minute: {bad}  (must be 0)")

    print("\n--- how far the mid itself moved ---")
    for lab in ("t30s", "t5s"):
        g = base.dropna(subset=[f"diff_{lab}"])
        d = (g[f"diff_{lab}"] - g["diff_t1m"]).abs()
        print(f"  {lab:5s} |change in (printed-mid)| median {d.median():.4f} bp  "
              f"p90 {d.quantile(.9):.4f}  max {d.max():.4f}")

    print("\n--- flip rate by tenor ---")
    g = base.dropna(subset=["diff_t5s"]).copy()
    g["flip"] = np.sign(g["diff_t5s"]) != np.sign(g["diff_t1m"])
    bucket = pd.cut(g["tenor_years"], [0, 1.01, 2.01, 5.01, 10.01, 31],
                    labels=["<=1Y", "1-2Y", "2-5Y", "5-10Y", "10-30Y"])
    for b in bucket.cat.categories:
        m = bucket == b
        if m.sum():
            print(f"  {str(b):8s} n={int(m.sum()):4d}  flip {g.loc[m, 'flip'].mean():6.2%}")


def main() -> None:
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    print("=== harness validation: reproduce the F-15 mids through the shipped module ===")
    if not validate_against_f15(rep):
        print("HARNESS DOES NOT REPRODUCE A KNOWN ANSWER - not measuring anything.")
        return

    print("\n=== draw ===")
    conn = connect()
    pool = draw(conn)
    conn.close()
    print(f"  measuring {len(pool)} prints over {pool['as_of_date'].nunique()} days")

    out = run(rep, pool)
    out.to_csv(OUT, index=False)
    report(out)


if __name__ == "__main__":
    main()
