import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
warnings.filterwarnings('ignore')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
cur = conn.cursor()


def q(sql, title):
    cur.execute(sql)
    rows = cur.fetchall()
    print(f"\n--- {title} ---")
    print("  " + " | ".join(d[0] for d in cur.description))
    for r in rows[:30]:
        print("  " + " | ".join(str(x) for x in r))
    return rows


q("""
SELECT kind,
  count(*) n_units,
  count(*) FILTER (WHERE curve_timestamp IS NULL) n_null_ts,
  count(*) FILTER (WHERE curve_timestamp::time = '00:00:00') n_midnight_ts,
  count(*) FILTER (WHERE deviation_bps IS NULL) n_null_dev,
  count(DISTINCT snapshot_policy) n_policies,
  string_agg(DISTINCT snapshot_policy, ',') policies
FROM arbs_dd_unit_v1
WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
GROUP BY 1
""", "curve_timestamp / snapshot policy hazards (kept units)")

q("""
WITH u AS (
  SELECT package_id, as_of_date, kind FROM arbs_dd_unit_v1
  WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
)
SELECT u.kind, count(DISTINCT (u.package_id,u.as_of_date)) n_units,
  count(DISTINCT (u.package_id,u.as_of_date)) FILTER (WHERE g.is_off_market) n_with_offmkt_leg,
  count(DISTINCT (u.package_id,u.as_of_date)) FILTER (WHERE g.forward_start_years::float8 > 0) n_with_fwd_leg
FROM u JOIN arbs_usd_swap_tape_legs_v3 g
  ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
GROUP BY 1
""", "off-market / forward-start prevalence among kept CURVE-FLY units")

# does the identity survive with off-market legs included?
q("""
WITH u AS (
  SELECT package_id, as_of_date, curve_timestamp, rate_index, deviation_bps
  FROM arbs_dd_unit_v1
  WHERE kind='CURVE' AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
    AND n_legs=2 AND curve_timestamp IS NOT NULL
    AND as_of_date BETWEEN '2026-01-01' AND '2026-08-07'
), l AS (
  SELECT u.package_id, u.as_of_date, u.deviation_bps, g.fixed_rate::float8 fr,
         m.mid_pct, g.is_off_market,
    row_number() OVER (PARTITION BY u.package_id, u.as_of_date
      ORDER BY g.expiration_date, g.effective_date, g.trade_id, g.leg_order) rc
  FROM u
  JOIN arbs_usd_swap_tape_legs_v3 g ON g.package_id=u.package_id AND g.as_of_date=u.as_of_date
  JOIN arbs_dd_curve_mid_v1 m ON m.grid_date=u.as_of_date AND m.rate_index=u.rate_index
   AND m.tenor_label=g.tenor_label AND m.ts=u.curve_timestamp
   AND m.effective_date=g.effective_date AND m.maturity_date=g.expiration_date
), a AS (
  SELECT package_id, as_of_date, deviation_bps, bool_or(is_off_market) has_om,
    (max(fr) FILTER (WHERE rc=2) - max(fr) FILTER (WHERE rc=1))*10000.0 AS t_bp,
    (max(mid_pct) FILTER (WHERE rc=2) - max(mid_pct) FILTER (WHERE rc=1))*100.0 AS m_bp
  FROM l GROUP BY 1,2,3 HAVING count(*)=2
)
SELECT has_om, count(*) n,
  count(*) FILTER (WHERE abs(t_bp-m_bp-deviation_bps) < 1e-6) n_exact,
  max(abs(t_bp-m_bp-deviation_bps)) max_err
FROM a GROUP BY 1
""", "CURVE identity WITH off-market legs included (2026 H1)")

conn.close()
