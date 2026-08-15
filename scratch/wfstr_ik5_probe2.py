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


D0 = "date '2026-05-10'"   # ~60 published days back, generous

q(f"""select venue_class, count(*) n from arbs_dd_unit_v1
      where as_of_date >= {D0} group by 1 order by 2 desc""", None, "venue_class")

q(f"""select special_tenor_type, kind, count(*) n from arbs_dd_unit_v1
      where as_of_date >= {D0} and kind in ('CURVE','FLY')
      group by 1,2 order by 3 desc""", None, "unit special_tenor_type x kind")

q(f"""select exclusion_reason, count(*) n from arbs_dd_unit_v1
      where as_of_date >= {D0} and kind in ('CURVE','FLY')
      group by 1 order by 2 desc""", None, "exclusion_reason CURVE/FLY")

# leg_order sanity: is leg_order ascending in expiration_date?
q(f"""with l as (
        select u.package_id, u.as_of_date, u.kind, l.leg_order, l.expiration_date,
               l.effective_date, l.tenor_years,
               row_number() over (partition by u.package_id order by l.leg_order) rn_lo,
               row_number() over (partition by u.package_id
                    order by l.expiration_date, l.effective_date, l.trade_id) rn_dt
        from arbs_dd_unit_v1 u
        join arbs_usd_swap_tape_legs_v3 l
          on l.package_id=u.package_id and l.as_of_date=u.as_of_date
        where u.as_of_date >= {D0} and u.kind in ('CURVE','FLY'))
      select kind, count(*) n_legs,
             count(*) filter (where rn_lo <> rn_dt) n_mismatch
      from l group by 1""", None, "leg_order vs date-order agreement")

# duplicate legs / leg count vs n_legs
q(f"""with c as (
        select u.package_id, u.kind, u.n_legs, count(l.trade_id) n_joined
        from arbs_dd_unit_v1 u
        join arbs_usd_swap_tape_legs_v3 l
          on l.package_id=u.package_id and l.as_of_date=u.as_of_date
        where u.as_of_date >= {D0} and u.kind in ('CURVE','FLY')
        group by 1,2,3)
      select kind, n_legs, n_joined, count(*) n from c
      group by 1,2,3 order by 4 desc limit 20""", None, "n_legs vs joined leg count")

# tenor_display -> tenor_label mapping for fuzzy
q(f"""select l.tenor_display, l.tenor_label, count(*) n
      from arbs_dd_unit_v1 u
      join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where u.as_of_date >= {D0} and u.kind in ('CURVE','FLY')
        and l.tenor_display like '~%'
      group by 1,2 order by 3 desc limit 40""", None, "fuzzy tenor_display -> tenor_label")

# forward labels
q(f"""select l.forward_label, l.forward_bucket, count(*) n
      from arbs_dd_unit_v1 u
      join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where u.as_of_date >= {D0} and u.kind in ('CURVE','FLY')
      group by 1,2 order by 3 desc limit 40""", None, "forward_label/bucket")

# tape_label variants for a given structure
q(f"""select l.tape_label, count(distinct u.package_id) n
      from arbs_dd_unit_v1 u
      join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where u.as_of_date >= {D0} and u.kind = 'CURVE' and u.rate_index='SOFR'
      group by 1 order by 2 desc limit 30""", None, "tape_label variants (CURVE SOFR)")

q(f"""select l.normalized_tape_label, count(distinct u.package_id) n
      from arbs_dd_unit_v1 u
      join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where u.as_of_date >= {D0} and u.kind = 'CURVE' and u.rate_index='SOFR'
      group by 1 order by 2 desc limit 30""", None, "normalized_tape_label variants (CURVE SOFR)")

conn.close()
