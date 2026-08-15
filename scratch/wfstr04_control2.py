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
    for r in rows[:50]:
        print("  " + " | ".join(str(x) for x in r))
    if len(rows) > 50:
        print(f"  ... {len(rows)} rows")
    return rows


q("""
SELECT rate_index, count(DISTINCT tenor_label) n_tenors,
       string_agg(DISTINCT tenor_label, ',') labels
FROM arbs_dd_curve_mid_v1
WHERE grid_date = '2026-06-16'
GROUP BY 1
""", title="grid tenor vocabulary (2026-06-16)")

# CONTROL: OUTRIGHT known answer, one month, bounded by grid_date too
q("""
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps,
         dealer_direction, dealer_sign
  FROM arbs_dd_unit_v1
  WHERE kind='OUTRIGHT' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-06-01' AND '2026-06-30'
    AND curve_timestamp IS NOT NULL
), j AS (
  SELECT u.deviation_bps, u.dealer_direction, u.dealer_sign,
         g.fixed_rate, g.tenor_label, g.is_off_market, m.mid_pct,
         (g.fixed_rate::float8*100.0 - m.mid_pct)*100.0 AS pred_dev
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  LEFT JOIN arbs_dd_curve_mid_v1 m
    ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
)
SELECT count(*) n_units,
       count(mid_pct) n_grid_hit,
       count(*) FILTER (WHERE is_off_market) n_offmkt
FROM j
""", title="CONTROL OUTRIGHT join coverage (Jun 2026)")

q("""
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps,
         dealer_direction, dealer_sign
  FROM arbs_dd_unit_v1
  WHERE kind='OUTRIGHT' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-06-01' AND '2026-06-30'
    AND curve_timestamp IS NOT NULL
), j AS (
  SELECT u.deviation_bps, u.dealer_direction, u.dealer_sign,
         g.fixed_rate, m.mid_pct,
         (g.fixed_rate::float8*100.0 - m.mid_pct)*100.0 AS pred_dev
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  JOIN arbs_dd_curve_mid_v1 m
    ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
  WHERE NOT g.is_off_market
)
SELECT count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(pred_dev-deviation_bps)) med_abs_err,
       max(abs(pred_dev-deviation_bps)) max_abs_err,
       count(*) FILTER (WHERE abs(pred_dev-deviation_bps) < 1e-6) n_exact,
       count(*) FILTER (WHERE deviation_bps > 0 AND dealer_direction='RECEIVED') a,
       count(*) FILTER (WHERE deviation_bps < 0 AND dealer_direction='PAID') b,
       count(DISTINCT dealer_direction) n_dirs
FROM j
""", title="CONTROL OUTRIGHT exactness + dealer_direction identity")

conn.close()
