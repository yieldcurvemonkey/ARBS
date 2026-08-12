"""Measure what the web tier actually pays, with EXPLAIN (ANALYZE, BUFFERS).

The consumer is a web page. A query that takes eight seconds is a design
failure even if it is correct, and the tape grid in particular is the primary
view of the app -- it went from a 60 ms index scan to a 29 s seq-scan once
before, over an ORDER BY that stopped matching its index.

So every read this feature adds is measured here, and the tape query is
measured BOTH ways so the cost of the new LEFT JOIN is a number rather than an
expectation.

    C:/Users/chris/anaconda3/envs/stir/python.exe scratch/ddfe06_read_cost.py
"""
from __future__ import annotations

import os
import statistics
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import psycopg2  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S  # noqa: E402
from SDRUtils._swappulse_scripts._tape_tables import DISPLAY_VIEW  # noqa: E402
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

REPS = 5

DD_COLS = (
    "dd.dealer_direction, dd.dealer_sign, dd.p, dd.signed_weight, dd.rule, "
    "dd.deviation_bps, dd.tau_bps, dd.in_dead_zone, dd.exclusion_reason, "
    "dd.exclusion_detail, dd.venue_class, dd.series, dd.total_delta_dv01, "
    "dd.total_dv01_if_received, dd.visibility_timestamp, "
    "dd.visibility_lag_seconds, dd.visibility_source, dd.curve_name, "
    "dd.curve_timestamp, dd.snapshot_lag_seconds, dd.snapshot_policy, "
    "dd.notional_imputed, dd.code_vintage, dd.tape_generation"
)

TAPE_BASE = f"""
    SELECT d.*
    FROM {DISPLAY_VIEW} d
    ORDER BY d.execution_start DESC NULLS LAST
    LIMIT 200
"""

TAPE_JOINED = f"""
    SELECT d.*, {DD_COLS}
    FROM {DISPLAY_VIEW} d
    LEFT JOIN {S.UNIT_TABLE} dd ON dd.package_id = d.package_id
    ORDER BY d.execution_start DESC NULLS LAST
    LIMIT 200
"""

TAPE_FILTERED = f"""
    SELECT d.*, {DD_COLS}
    FROM {DISPLAY_VIEW} d
    LEFT JOIN {S.UNIT_TABLE} dd ON dd.package_id = d.package_id
    WHERE LOWER(dd.dealer_direction) = 'received'
    ORDER BY d.execution_start DESC NULLS LAST
    LIMIT 200
"""

QUERIES = [
    ("tape grid, 200 rows, NO direction join (the baseline)", TAPE_BASE, ()),
    ("tape grid, 200 rows, WITH the direction join", TAPE_JOINED, ()),
    ("tape grid, filtered to dealer RECEIVED", TAPE_FILTERED, ()),
    (
        "/direction/bucket -- one bucket, whole history",
        f"""
        SELECT visibility_date, observed, delta_dv01, delta_dv01_cov_adj,
               abs_dv01, n_units, mean_abs_signed_weight, z_raw, z_cov_adj,
               pct_raw, z_n_obs, coverage_frac, coverage_smooth,
               coverage_drift_flag, coverage_dv01_kept, coverage_dv01_total
        FROM {S.LADDER_TABLE}
        WHERE bucket_space = 'TENOR10' AND bucket_key = %s
          AND venue_class = %s AND series = %s
          AND visibility_date >= %s::date
        ORDER BY visibility_date
        """,
        ("5-7Y", "D2C", "FLOW", "2024-07-01"),
    ),
    (
        "/direction/standardised -- ten buckets, whole history",
        f"""
        SELECT bucket_key, visibility_date, observed, z_raw, z_cov_adj,
               pct_raw, z_n_obs, n_units, mean_abs_signed_weight,
               coverage_frac, coverage_drift_flag
        FROM {S.LADDER_TABLE}
        WHERE bucket_space = 'TENOR10' AND venue_class = %s AND series = %s
          AND visibility_date >= %s::date
        ORDER BY visibility_date, bucket_key
        """,
        ("D2C", "FLOW", "2024-07-01"),
    ),
    (
        "/direction/coverage -- exclusion breakdown, by bucket",
        f"""
        WITH scoped AS (
          SELECT bucket_key, reason, n_units, dv01
          FROM {S.COVERAGE_TABLE}
          WHERE venue_class = %s AND series = %s
            AND visibility_date >= %s::date
        ), agg AS (
          SELECT bucket_key, reason, SUM(n_units)::bigint AS n_units,
                 SUM(dv01) AS dv01
          FROM scoped GROUP BY bucket_key, reason
        )
        SELECT bucket_key, reason, n_units, dv01,
               dv01 / NULLIF(SUM(dv01) OVER (PARTITION BY bucket_key), 0)
        FROM agg ORDER BY bucket_key, dv01 DESC
        """,
        ("D2C", "FLOW", "2024-07-01"),
    ),
    (
        "/direction/summary",
        f"""
        WITH bounds AS (
          SELECT max(visibility_date) hi, min(visibility_date) lo
          FROM {S.LADDER_TABLE} WHERE bucket_space = 'TENOR10'
        ), cov AS (
          SELECT SUM(coverage_dv01_kept) k, SUM(coverage_dv01_total) t
          FROM {S.LADDER_TABLE}
          WHERE bucket_space = 'TENOR10' AND venue_class = %s AND series = %s
        ), units AS (
          SELECT count(*)::bigint n,
                 count(*) FILTER (WHERE exclusion_reason IS NULL)::bigint c,
                 max(as_of_date) d
          FROM {S.UNIT_TABLE}
        )
        SELECT * FROM bounds, cov, units
        """,
        ("D2C", "FLOW"),
    ),
    (
        "per-trade drill-down: one package's bucket profile",
        f"SELECT bucket_key, dv01_if_received, delta_dv01 "
        f"FROM {S.UNIT_BUCKET_TABLE} WHERE package_id = %s",
        ("__PKG__",),
    ),
]


def main() -> int:
    conn = psycopg2.connect(resolve_pg_url())
    conn.autocommit = True

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT package_id FROM {S.UNIT_BUCKET_TABLE} LIMIT 1")
        row = cur.fetchone()
    pkg = row[0] if row else None
    if pkg is None:
        print("no rows in the unit-bucket table yet; run `publish` first")
        return 2

    print(f"{'query':<56} {'median ms':>10} {'p95 ms':>9} {'rows':>8}")
    print("-" * 88)
    results = []
    for label, sql, params in QUERIES:
        params = tuple(pkg if p == "__PKG__" else p for p in params)
        times, nrows = [], 0
        for i in range(REPS):
            t0 = time.perf_counter()
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                nrows = len(cur.fetchall())
            times.append((time.perf_counter() - t0) * 1000.0)
        med = statistics.median(times)
        p95 = sorted(times)[-1]
        results.append((label, med, p95, nrows))
        print(f"{label:<56} {med:>10.1f} {p95:>9.1f} {nrows:>8,}")

    print("\n--- EXPLAIN (ANALYZE, BUFFERS) on the tape grid, both ways ---")
    for label, sql in (("NO join", TAPE_BASE), ("WITH join", TAPE_JOINED)):
        with conn.cursor() as cur:
            cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql)
            plan = [r[0] for r in cur.fetchall()]
        print(f"\n== {label} ==")
        for line in plan:
            print("  " + line)

    base = next(r for r in results if "NO direction join" in r[0])[1]
    joined = next(r for r in results if "WITH the direction join" in r[0])[1]
    print(f"\njoin cost on the tape grid: {joined - base:+.1f} ms "
          f"({joined / max(base, 1e-9):.2f}x)")
    conn.close()
    slow = [r for r in results if r[1] > 1000.0]
    if slow:
        print("\nOVER 1s -- a web page cannot wait for these:")
        for label, med, _p95, _n in slow:
            print(f"  {med:8.0f} ms  {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
