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
    return rows


q("""
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps
  FROM arbs_dd_unit_v1
  WHERE kind='OUTRIGHT' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND as_of_date BETWEEN '2026-06-01' AND '2026-06-30'
    AND curve_timestamp IS NOT NULL
), j AS (
  SELECT (g.effective_date = m.effective_date) AS eff_ok,
         (g.expiration_date = m.maturity_date) AS mat_ok,
         (g.fixed_rate::float8*100.0 - m.mid_pct)*100.0 - u.deviation_bps AS err
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g
    ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  JOIN arbs_dd_curve_mid_v1 m
    ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
  WHERE NOT g.is_off_market
)
SELECT eff_ok, mat_ok, count(*) n,
       count(*) FILTER (WHERE abs(err) < 1e-6) n_exact,
       max(abs(err)) mx
FROM j GROUP BY 1,2 ORDER BY n DESC
""", title="OUTRIGHT exactness by grid date-identity match")

conn.close()
