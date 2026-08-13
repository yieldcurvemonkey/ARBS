"""Stage 5 - what repricing a whole tape day against the minute store costs.

Three numbers, kept apart because they scale with different things:

  T1  the FIRST curve-minute of a day. Pays the three-partition ``day_window``
      read (D, D-1, D+1) on top of one reconstruct, and is paid once per day.
  T2  each ADDITIONAL distinct curve-minute on that same day. Just the
      reconstruct + solve; this is the number that multiplies by ~1,000.
  T3  each additional leg priced on an ALREADY-BUILT handle. Reported by tenor,
      because a 30Y leg builds a much longer schedule than a 1Y one and the
      average of the two is a number that describes neither.

Reporting a single "seconds per leg" would hide which of the three dominates,
and they differ by two orders of magnitude.

The fourth quantity is not a timing at all - it is how many DISTINCT snapped
minutes a day's flow legs actually need, which is what decides whether T2 or T3
sets the wall clock.
"""
from __future__ import annotations

import datetime
import os
import statistics
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import psycopg2

from dd_common import CURVE_FOR, make_pricer, strict_policy
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow.pricing import snap_timestamp

DAY = datetime.date(2026, 4, 1)          # dense Wednesday, 1,319 stored snapshots
CURVE = "USD-SOFR-1D"

pd.set_option("display.width", 240)


def q(conn, sql, params=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params)


def main() -> None:
    conn = psycopg2.connect(resolve_pg_url())

    # ---- how many distinct curve-minutes does one day need? -----------------
    print(f"=== distinct curve-minutes needed for {DAY} ===")
    counts = q(conn, f"""
        SELECT rate_index_clean,
               count(*) AS legs,
               count(DISTINCT date_trunc('minute',
                     coalesce(original_execution_timestamp, execution_timestamp))) AS distinct_minutes
        FROM {LEGS_TABLE}
        WHERE as_of_date = %(d)s
          AND economic_class = 'ECONOMIC_FLOW' AND contributes_to_flow
          AND rate_index_clean IN ('SOFR','FED_FUNDS')
        GROUP BY 1 ORDER BY 2 DESC""", {"d": DAY})
    print(counts.to_string())
    # A whole-tape view too, so "typical" is not one lucky day.
    span = q(conn, f"""
        WITH per_day AS (
          SELECT as_of_date, rate_index_clean, count(*) legs,
                 count(DISTINCT date_trunc('minute',
                       coalesce(original_execution_timestamp, execution_timestamp))) dm
          FROM {LEGS_TABLE}
          WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
            AND rate_index_clean IN ('SOFR','FED_FUNDS')
          GROUP BY 1,2)
        SELECT rate_index_clean, count(*) days,
               round(avg(legs)) avg_legs, round(avg(dm)) avg_distinct_min,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY dm) p50_dm,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY dm) p90_dm,
               max(dm) max_dm, sum(legs) total_legs, sum(dm) total_dm
        FROM per_day GROUP BY 1""")
    print("\n=== whole v3 tape, per day ===")
    print(span.to_string())

    legs = q(conn, f"""
        SELECT trade_id, execution_timestamp, original_execution_timestamp,
               effective_date, expiration_date, notional, tenor_years, tenor_label
        FROM {LEGS_TABLE}
        WHERE as_of_date = %(d)s AND rate_index_clean = 'SOFR'
          AND economic_class = 'ECONOMIC_FLOW' AND contributes_to_flow
          AND effective_date IS NOT NULL AND expiration_date IS NOT NULL
          AND notional IS NOT NULL AND tenor_years BETWEEN 0.5 AND 31
        ORDER BY trade_id""", {"d": DAY})
    conn.close()
    legs["snap"] = [snap_timestamp(a, b) for a, b in
                    zip(legs["original_execution_timestamp"], legs["execution_timestamp"])]
    # Keep the snapped instants in NEW YORK, not UTC. `is_ambiguous_midnight`
    # tests the WALL CLOCK of the object it is handed, so a perfectly ordinary
    # 20:00 ET snap (= 00:00 UTC on EDT) trips CurvePricer's midnight guard the
    # moment you normalise the column to UTC. Measured here: 2026-03-31 20:00 ET
    # raised "which is exactly midnight" on the first curve of the day.
    legs["snap"] = pd.to_datetime(legs["snap"], utc=True).dt.tz_convert("America/New_York")
    minutes = sorted(legs["snap"].unique())
    print(f"\n{len(legs)} priceable SOFR flow legs on {DAY}, "
          f"{len(minutes)} distinct snapped minutes "
          f"({len(legs)/max(len(minutes),1):.2f} legs per minute)")

    # ---- T1: the first curve-minute of the day (cold) -----------------------
    pricer = make_pricer(strict_policy(1))
    m0 = pd.Timestamp(minutes[0])
    t0 = time.perf_counter()
    pricer.handle(CURVE, m0.to_pydatetime())
    t_first = time.perf_counter() - t0
    print(f"\nT1  first curve-minute of the day (incl. 3-partition day_window read): "
          f"{t_first*1000:.1f} ms")

    # ---- T2: each additional distinct curve-minute --------------------------
    sample = [pd.Timestamp(m) for m in minutes[1:201]]
    ts = []
    for m in sample:
        t0 = time.perf_counter()
        try:
            pricer.handle(CURVE, m.to_pydatetime())
        except Exception:  # noqa: BLE001 - a strict miss is not a timing
            continue
        ts.append(time.perf_counter() - t0)
    print(f"T2  additional curve-minute, same day (n={len(ts)}): "
          f"mean {statistics.mean(ts)*1000:.2f} ms  "
          f"p50 {statistics.median(ts)*1000:.2f}  "
          f"p90 {sorted(ts)[int(0.9*len(ts))]*1000:.2f}  "
          f"max {max(ts)*1000:.2f}")
    t_build = statistics.mean(ts)

    # ---- T3: an additional leg on an already-built handle -------------------
    warm_minute = sample[0]
    pricer.handle(CURVE, warm_minute.to_pydatetime())      # ensure warm
    by_tenor: dict[str, list[float]] = {}
    for _, r in legs.head(400).iterrows():
        bucket = ("<=2Y" if r["tenor_years"] <= 2 else
                  "2-10Y" if r["tenor_years"] <= 10 else ">10Y")
        t0 = time.perf_counter()
        try:
            pricer.price_leg(CURVE, warm_minute.to_pydatetime(),
                             r["effective_date"], r["expiration_date"], float(r["notional"]))
        except Exception:  # noqa: BLE001
            continue
        by_tenor.setdefault(bucket, []).append(time.perf_counter() - t0)
    allt = [x for v in by_tenor.values() for x in v]
    print(f"T3  additional leg on a warm handle (n={len(allt)}): "
          f"mean {statistics.mean(allt)*1000:.2f} ms  p50 {statistics.median(allt)*1000:.2f}  "
          f"p90 {sorted(allt)[int(0.9*len(allt))]*1000:.2f}")
    for b in ("<=2Y", "2-10Y", ">10Y"):
        v = by_tenor.get(b) or []
        if v:
            print(f"      {b:>6s}: n={len(v):4d} mean {statistics.mean(v)*1000:.2f} ms  "
                  f"p90 {sorted(v)[int(0.9*len(v))]*1000:.2f}")
    t_leg = statistics.mean(allt)

    # ---- projection ----------------------------------------------------------
    n_min, n_legs = len(minutes), len(legs)
    per_day = t_first + (n_min - 1) * t_build + n_legs * t_leg
    print(f"\n=== projection (single process, warm OS page cache) ===")
    print(f"  one day  ({n_min} minutes, {n_legs} legs): "
          f"{per_day:.1f} s  = {t_first:.2f} build0 + {(n_min-1)*t_build:.1f} builds "
          f"+ {n_legs*t_leg:.1f} legs")
    print(f"  610 days at this shape:  {per_day*610/60:.0f} min "
          f"({per_day*610/3600:.2f} h)")
    tot_dm = float(span["total_dm"].sum())
    tot_legs = float(span["total_legs"].sum())
    print(f"  610 days at the tape's OWN totals "
          f"({tot_dm:,.0f} distinct minutes, {tot_legs:,.0f} flow legs): "
          f"{(610*t_first + tot_dm*t_build + tot_legs*t_leg)/3600:.2f} h")
    print("  (all three components measured on THIS machine, single-threaded, "
          "local parquet already in the OS page cache)")


if __name__ == "__main__":
    main()
