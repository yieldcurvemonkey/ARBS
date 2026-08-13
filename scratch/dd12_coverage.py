"""Measurement A - the leg-level success rate, stratified by how the leg starts.

The only success rates measured anywhere in this programme so far are n = 34 and
a pre-filtered n = 200 of liquid on-market SOFR outrights. Neither can see the
failure that matters: **past-start legs are 14.6% of the tape (339,497 legs)**
and are the only ones whose rate depends on published fixings, so a fixings
failure would be invisible inside an aggregate that is 85% spot.

So: draw PER STRATUM rather than once, from the full ECONOMIC_FLOW population
with no on-market / outright pre-filter -- the pre-filtering is exactly what this
measurement exists to undo. The SQL predicate only over-samples; the stratum
actually reported is ``LegQuote.start_class``, which cuts against the SNAP, not
against ``as_of_date``.

Every failure carries a reason (``SnapshotMiss`` -> ``NO_CURVE``, a rateslib or
schedule error -> ``PRICING_ERROR``, the spec sentinels -> ``RISK_IMPLAUSIBLE``).
A silent NaN is not a possible outcome of this run; if the counts do not add up
the harness is wrong, and that is checked.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from dd_measure import LEG_COLS, connect, even_subsample, read_sql, unit_from_leg
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils.dealer_direction import midprice, snapshot

pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 40)

PER_STRATUM = 220
OUT = "C:/Users/chris/clee/ARBS-dd/scratch/out_coverage_strata.csv"

#: The draw predicates. ``effective_date`` against ``as_of_date`` is a proxy for
#: the module's snap-based rule and is only used to over-sample each stratum.
STRATA = {
    "PAST_START": "l.effective_date < l.as_of_date",
    "SPOT": "l.effective_date BETWEEN l.as_of_date AND l.as_of_date + 3",
    "FORWARD_START": "l.effective_date > l.as_of_date + 3",
    "CAPPED": "l.is_capped",
}

_BASE = f"""
  FROM {LEGS_TABLE} l
  WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    AND l.rate_index_clean IN ('SOFR','FED_FUNDS')
    AND l.fixed_rate IS NOT NULL AND l.effective_date IS NOT NULL
    AND l.expiration_date IS NOT NULL AND l.notional IS NOT NULL
"""


def draw(conn) -> pd.DataFrame:
    frames = []
    for name, pred in STRATA.items():
        n = read_sql(conn, f"SELECT count(*) n {_BASE} AND {pred}")["n"].iloc[0]
        # A modulus that lands near 3x the target, then an even subsample over
        # time order -- reproducible, and spread across the whole 610-day span
        # rather than concentrated wherever the hash happens to be dense.
        k = max(1, int(n // (PER_STRATUM * 3)))
        pool = read_sql(conn, f"""
            SELECT {LEG_COLS} {_BASE} AND {pred}
              AND mod(abs(hashtext(l.trade_id)), {k}) = 0
            ORDER BY l.execution_timestamp, l.trade_id""")
        take = even_subsample(pool, PER_STRATUM)
        take["draw_stratum"] = name
        frames.append(take)
        print(f"  {name:14s} population {n:>9,}  modulus {k:>6}  "
              f"pool {len(pool):>6}  drawn {len(take)}")
    out = pd.concat(frames, ignore_index=True)
    # A leg can be drawn by two predicates (a capped past-start one). Keep the
    # first and record it, so the denominator is legs and not draws.
    dupes = out["trade_id"].duplicated().sum()
    out = out.drop_duplicates("trade_id").reset_index(drop=True)
    print(f"  {dupes} legs drawn by two predicates; {len(out)} distinct legs")
    return out.sort_values(["as_of_date", "execution_timestamp", "trade_id"]).reset_index(drop=True)


def run(pool: pd.DataFrame) -> pd.DataFrame:
    rep = midprice.UnitRepricer.for_source(snapshot.CURVE_SOURCE)
    rows, peak = [], 0
    t0 = time.perf_counter()
    for day, chunk in pool.groupby("as_of_date", sort=True):
        # Per-day scope: a single-process 610-day run otherwise accumulates
        # ~500k handles, none of which is ever evicted.
        with rep.day_scope():
            for _, r in chunk.iterrows():
                unit, snap, clock_field = unit_from_leg(r)
                curve = snapshot.CURVE_FOR.get(r["rate_index_clean"], "")
                try:
                    in_sess = snapshot.in_session(curve, snap) if curve else False
                except Exception:  # noqa: BLE001
                    in_sess = None
                out = rep.price_unit(unit)
                q = out.legs[0]
                rows.append({
                    "trade_id": r["trade_id"],
                    "as_of_date": day,
                    "index": r["rate_index_clean"],
                    "draw_stratum": r["draw_stratum"],
                    "start_class": q.start_class,
                    "is_capped": bool(r["is_capped"] or False),
                    "in_session": in_sess,
                    "clock_field": clock_field,
                    "policy": out.pricing.snapshot_policy,
                    "tenor_years": float(r["tenor_years"]) if pd.notna(r["tenor_years"]) else None,
                    "has_upfront": unit.upfront is not None,
                    "ok": q.ok,
                    "reason": q.failure,
                    "detail": (q.failure_detail or "")[:120],
                    "mid_pct": q.mid_pct,
                    "pv01": q.pv01,
                    "npv_pay": q.npv_pay,
                    "lag_s": out.pricing.snapshot_lag_seconds,
                })
            peak = max(peak, rep.pricer.n_handles)
    dt = time.perf_counter() - t0
    print(f"\npriced {len(rows)} legs over {pool['as_of_date'].nunique()} days in "
          f"{dt:.0f}s ({dt/max(1,len(rows))*1000:.0f} ms/leg); peak handles held "
          f"within a day: {peak}; handles after the last scope exit: "
          f"{rep.pricer.n_handles}")
    return pd.DataFrame(rows)


def _rate(g) -> str:
    return f"{g['ok'].mean():6.1%} ({int(g['ok'].sum()):>4}/{len(g):>4})"


def main() -> None:
    conn = connect()
    pool = draw(conn)
    conn.close()
    out = run(pool)
    out.to_csv(OUT, index=False)

    # The harness must account for every leg. If these disagree the numbers
    # below are measuring the harness, not the pass.
    assert len(out) == len(pool), (len(out), len(pool))
    assert (out["ok"] ^ out["reason"].notna()).all(), "a leg is neither ok nor reasoned"

    print("\n=== leg success rate by the stratum the MODULE assigned ===")
    for s, g in out.groupby("start_class"):
        print(f"  {s:14s} {_rate(g)}")
    print(f"  {'ALL':14s} {_rate(out)}")

    print("\n=== capped (orthogonal cut) ===")
    for c, g in out.groupby("is_capped"):
        print(f"  is_capped={c!s:5s}  {_rate(g)}")

    print("\n=== by stratum x session ===")
    for (s, sess), g in out.groupby(["start_class", "in_session"], dropna=False):
        print(f"  {s:14s} in_session={sess!s:5s}  {_rate(g)}")

    print("\n=== by rate index ===")
    for i, g in out.groupby("index"):
        print(f"  {i:10s} {_rate(g)}")

    print("\n=== failure reasons ===")
    bad = out[~out["ok"]]
    if bad.empty:
        print("  none")
    else:
        print(bad.groupby(["reason", "start_class"]).size().to_string())
        print("\n  a sample of each reason:")
        for reason, g in bad.groupby("reason"):
            r = g.iloc[0]
            print(f"    {reason:18s} {r['trade_id']} {r['as_of_date']} "
                  f"{r['start_class']} in_session={r['in_session']} -> {r['detail']}")

    print("\n=== the draw predicate vs the module's stratum (they should mostly agree) ===")
    print(pd.crosstab(out["draw_stratum"], out["start_class"]).to_string())

    print("\n=== policy branch mix, and the lag it served ===")
    for p, g in out.groupby("policy"):
        lag = g["lag_s"].dropna()
        print(f"  {p:26s} n={len(g):5d}  lag reported on {len(lag)}/{len(g)}  "
              + (f"median {lag.median():.0f}s max {lag.max():.0f}s" if len(lag) else ""))
    n_null = int(out.loc[out["ok"], "lag_s"].isna().sum())
    print(f"  priced legs with a NULL lag: {n_null} "
          f"(the strict/hole branches must never produce one)")

    print("\n=== upfront path exercised ===")
    up = out[out["has_upfront"]]
    print(f"  {len(up)} legs carry an other-payment amount; "
          f"{int(up['npv_pay'].notna().sum())} produced a payer-frame NPV")


if __name__ == "__main__":
    main()
