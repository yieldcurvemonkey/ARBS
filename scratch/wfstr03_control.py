import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
cur = conn.cursor()


def q(sql, args=None, title=""):
    cur.execute(sql, args)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"\n--- {title} ---")
    print("  " + " | ".join(cols))
    for r in rows[:40]:
        print("  " + " | ".join(str(x) for x in r))
    if len(rows) > 40:
        print(f"  ... {len(rows)} rows")
    return rows


# GUARD 1: is (package_id, as_of_date) unique among kept RATE_VS_MID CURVE units?
q("""
SELECT count(*) AS n_units,
       count(DISTINCT (package_id, as_of_date)) AS n_distinct_pkg_day,
       count(*) FILTER (WHERE package_id IS NULL) AS n_null_pkg
FROM arbs_dd_unit_v1
WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
""", title="GUARD unit (package_id, as_of_date) uniqueness")

# GUARD 1b: any package_id shared between a CURVE unit and other units on same day?
q("""
SELECT count(*) AS pkg_days_with_multiple_units
FROM (
  SELECT package_id, as_of_date, count(*) c
  FROM arbs_dd_unit_v1
  WHERE package_id IS NOT NULL
  GROUP BY 1,2 HAVING count(*) > 1
) t
""", title="GUARD package/day carrying >1 unit row (all kinds/rules)")

# GUARD 2: leg count per package/day vs unit.n_legs
q("""
WITH u AS (
  SELECT package_id, as_of_date, n_legs FROM arbs_dd_unit_v1
  WHERE kind='CURVE' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-05-01' AND '2026-06-30'
), c AS (
  SELECT g.package_id, g.as_of_date, count(*) n_tape_legs
  FROM arbs_usd_swap_tape_legs_v3 g
  JOIN u ON u.package_id=g.package_id AND u.as_of_date=g.as_of_date
  GROUP BY 1,2
)
SELECT count(*) n, count(*) FILTER (WHERE u.n_legs <> c.n_tape_legs) n_mismatch
FROM u JOIN c ON c.package_id=u.package_id AND c.as_of_date=u.as_of_date
""", title="GUARD unit.n_legs vs tape leg count (CURVE, May-Jun 2026)")

# grid vocabulary
q("""
SELECT rate_index, count(DISTINCT tenor_label) n_tenors,
       string_agg(DISTINCT tenor_label, ',') labels
FROM arbs_dd_curve_mid_v1 GROUP BY 1
""", title="grid tenor vocabulary")

# CONTROL: OUTRIGHT known answer
q("""
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps,
         dealer_direction, dealer_sign
  FROM arbs_dd_unit_v1
  WHERE kind='OUTRIGHT' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-05-01' AND '2026-06-30'
    AND curve_timestamp IS NOT NULL
  LIMIT 4000
), j AS (
  SELECT u.*, g.fixed_rate, g.tenor_label, g.is_off_market,
         m.mid_pct,
         (g.fixed_rate::float8*100.0 - m.mid_pct)*100.0 AS pred_dev
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  LEFT JOIN arbs_dd_curve_mid_v1 m
    ON m.rate_index=u.rate_index AND m.tenor_label=g.tenor_label
   AND m.ts=u.curve_timestamp
)
SELECT count(*) n,
       count(mid_pct) n_grid_hit,
       count(*) FILTER (WHERE is_off_market) n_offmkt,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pred_dev-deviation_bps))::numeric, 10) med_abs_err,
       round(max(abs(pred_dev-deviation_bps))::numeric, 8) max_abs_err,
       count(*) FILTER (WHERE abs(pred_dev-deviation_bps) < 1e-6) n_exact
FROM j WHERE mid_pct IS NOT NULL AND NOT is_off_market
""", title="CONTROL OUTRIGHT: dev == (fixed_rate*100 - mid_pct)*100 ?")

conn.close()
