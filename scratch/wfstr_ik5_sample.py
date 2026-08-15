import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute("set statement_timeout = '280s'")


def q(sql, params=None, title="", show=300):
    t0 = time.time()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"--- {title} ({len(rows)} rows, {time.time()-t0:.1f}s) ---")
    print(" | ".join(cols))
    for r in rows[:show]:
        print(" | ".join("" if v is None else str(v) for v in r))
    print(flush=True)
    return rows


q("""select rate_index, tenor_label, count(*) n
     from arbs_dd_curve_mid_v1 where grid_date = date '2026-08-07'
     group by 1,2 order by 1, min(maturity_date)""", None, "curve_mid tenors on 2026-08-07")

q("""select u.package_id, u.kind, u.n_legs, u.rate_index, u.venue_class, u.rule,
        u.deviation_bps, u.special_tenor_type, u.exclusion_reason,
        l.leg_order, l.tenor_display, l.tenor_label, l.tenor_years,
        l.forward_start_years, l.rate_index_clean, l.special_tenor_type as leg_stt,
        l.fixed_rate, l.effective_date, l.expiration_date, l.tape_label
     from arbs_dd_unit_v1 u
     join arbs_usd_swap_tape_legs_v3 l
       on l.package_id = u.package_id and l.as_of_date = u.as_of_date
     where u.as_of_date = date '2026-08-07' and u.kind = 'CURVE'
     order by u.package_id, l.leg_order
     limit 40""", None, "sample CURVE legs 2026-08-07")

q("""select u.package_id, u.kind, u.n_legs, u.rate_index,
        l.leg_order, l.tenor_display, l.tenor_label, l.tenor_years, l.forward_start_years
     from arbs_dd_unit_v1 u
     join arbs_usd_swap_tape_legs_v3 l
       on l.package_id = u.package_id and l.as_of_date = u.as_of_date
     where u.as_of_date = date '2026-08-07' and u.kind = 'FLY'
     order by u.package_id, l.leg_order
     limit 30""", None, "sample FLY legs 2026-08-07")

q("""select l.tenor_display, count(*) n
     from arbs_dd_unit_v1 u
     join arbs_usd_swap_tape_legs_v3 l
       on l.package_id = u.package_id and l.as_of_date = u.as_of_date
     where u.as_of_date >= date '2026-06-01' and u.kind in ('CURVE','FLY')
     group by 1 order by 2 desc limit 60""", None, "tenor_display freq (since 2026-06-01)")

q("""select u.kind, u.n_legs, count(*) n
     from arbs_dd_unit_v1 u where u.as_of_date >= date '2026-06-01'
     group by 1,2 order by 1,2""", None, "kind x n_legs")

q("""select venue_class, count(*) n from arbs_dd_unit_v1
     where as_of_date >= date '2026-06-01' group by 1 order by 2 desc""",
  None, "venue_class")

conn.close()
