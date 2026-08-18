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
    for r in rows[:60]:
        print("  " + " | ".join(str(x) for x in r))
    if len(rows) > 60:
        print(f"  ... {len(rows)} rows")
    return rows


BASE = """
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps,
         dealer_direction, special_tenor_type
  FROM arbs_dd_unit_v1
  WHERE kind='OUTRIGHT' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-06-01' AND '2026-06-30'
    AND curve_timestamp IS NOT NULL
), j AS (
  SELECT u.deviation_bps, u.dealer_direction, u.special_tenor_type AS u_stt,
         g.forward_start_years, g.is_off_date, g.is_non_standard_term,
         g.is_mac, g.is_spreadover, g.special_tenor_type AS l_stt,
         g.tenor_label, m.mid_pct, g.fixed_rate,
         (g.fixed_rate::float8*100.0 - m.mid_pct)*100.0 - u.deviation_bps AS err
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  JOIN arbs_dd_curve_mid_v1 m
    ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
  WHERE NOT g.is_off_market
)
"""

q(BASE + """
SELECT (forward_start_years::float8 = 0) AS spot_start,
       is_off_date, is_non_standard_term,
       count(*) n,
       count(*) FILTER (WHERE abs(err) < 1e-6) n_exact,
       round(max(abs(err))::numeric, 4) max_abs_err
FROM j GROUP BY 1,2,3 ORDER BY n DESC
""", title="OUTRIGHT residual by forward-start / off-date / non-standard")

q(BASE + """
SELECT count(*) n,
       count(*) FILTER (WHERE abs(err) < 1e-6) n_exact,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(err)) med,
       max(abs(err)) mx
FROM j
WHERE forward_start_years::float8 = 0 AND NOT is_off_date AND NOT is_non_standard_term
""", title="OUTRIGHT grid-clean subset exactness")

conn.close()
