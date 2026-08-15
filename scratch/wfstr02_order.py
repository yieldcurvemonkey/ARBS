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
    for r in rows:
        print("  " + " | ".join(str(x) for x in r))
    return rows


q("""
SELECT kind, rule, n_legs, count(*) AS n,
       count(*) FILTER (WHERE exclusion_reason IS NULL) AS n_kept
FROM arbs_dd_unit_v1
WHERE kind IN ('CURVE','FLY')
GROUP BY 1,2,3 ORDER BY 1,2,3
""", title="unit census CURVE/FLY")

q("""
SELECT rate_index, count(*) n
FROM arbs_dd_unit_v1
WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
GROUP BY 1 ORDER BY 2 DESC
""", title="rate_index mix (kept RATE_VS_MID CURVE/FLY)")

q("""
SELECT min(as_of_date), max(as_of_date), count(*)
FROM arbs_dd_unit_v1
WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
""", title="date span")

# leg_order integrity
q("""
SELECT count(*) AS n_legs_total,
       count(*) FILTER (WHERE leg_order IS NULL) AS n_null,
       min(leg_order) AS lo_min, max(leg_order) AS lo_max
FROM arbs_usd_swap_tape_legs_v3
""", title="leg_order null/base")

# duplicates within package for a sample of recent days
q("""
WITH l AS (
  SELECT package_id, as_of_date, leg_order
  FROM arbs_usd_swap_tape_legs_v3
  WHERE as_of_date BETWEEN '2026-05-01' AND '2026-06-30' AND package_id IS NOT NULL
)
SELECT count(*) AS n_pkg_leg_pairs,
       count(*) FILTER (WHERE c > 1) AS n_dup_groups
FROM (SELECT package_id, as_of_date, leg_order, count(*) c
      FROM l GROUP BY 1,2,3) t
""", title="leg_order duplicates within (package_id, as_of_date) May-Jun 2026")

# does the canonical triple sort agree with leg_order rank?
q("""
WITH u AS (
  SELECT package_id, as_of_date FROM arbs_dd_unit_v1
  WHERE kind IN ('CURVE','FLY') AND rule='RATE_VS_MID' AND exclusion_reason IS NULL
),
l AS (
  SELECT g.package_id, g.as_of_date, g.trade_id,
         row_number() OVER (PARTITION BY g.package_id, g.as_of_date
              ORDER BY g.expiration_date, g.effective_date, g.trade_id, g.leg_order) AS r_triple,
         row_number() OVER (PARTITION BY g.package_id, g.as_of_date
              ORDER BY g.leg_order, g.expiration_date, g.effective_date, g.trade_id) AS r_legorder,
         row_number() OVER (PARTITION BY g.package_id, g.as_of_date
              ORDER BY g.tenor_years, g.expiration_date, g.effective_date, g.trade_id) AS r_tenor
  FROM arbs_usd_swap_tape_legs_v3 g
  JOIN u ON u.package_id = g.package_id AND u.as_of_date = g.as_of_date
)
SELECT count(*) AS n_legs,
       count(*) FILTER (WHERE r_triple <> r_legorder) AS legorder_disagrees,
       count(*) FILTER (WHERE r_triple <> r_tenor)    AS tenor_disagrees
FROM l
""", title="rank agreement: canonical triple vs leg_order vs tenor_years")

conn.close()
