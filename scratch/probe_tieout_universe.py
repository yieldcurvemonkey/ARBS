"""Tie-out universe size: v3 kept units vs persisted rows, sampled across the range."""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.stir_flow.trade_selection import (
    ELIGIBLE_LEGS_SQL, ALL_PKG_LEGS_SQL, build_units, is_excluded_unit)

DAYS = ["2026-01-13", "2026-02-11", "2026-03-11", "2026-04-08", "2026-05-13",
        "2026-06-10", "2026-07-09", "2026-07-22", "2026-07-29"]
conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
tot = dict(per=0, kept=0, inter=0)
print(f"{'date':12s} {'persist':>8s} {'v3kept':>7s} {'inter':>6s} {'onlyP':>6s} {'onlyN':>6s}  skipped")
for d in DAYS:
    elig = pd.read_sql(ELIGIBLE_LEGS_SQL, conn, params={"start": d, "end": d})
    pkg = sorted(set(elig.loc[elig["n_package_legs"].fillna(1) > 1, "package_id"].dropna()))
    allp = elig.head(0) if not pkg else pd.read_sql(ALL_PKG_LEGS_SQL, conn, params={"package_ids": pkg})
    kept, skipped = set(), {}
    for u in build_units(elig, allp):
        r = is_excluded_unit(u.legs)
        if r: skipped[r] = skipped.get(r, 0) + 1
        else: kept.add(u.unit_key)
    cur.execute("SELECT unit_key FROM arbs_stir_direction_v1 WHERE as_of_date=%s", (d,))
    per = {r[0] for r in cur.fetchall()}
    tot["per"] += len(per); tot["kept"] += len(kept); tot["inter"] += len(per & kept)
    print(f"{d:12s} {len(per):8d} {len(kept):7d} {len(per&kept):6d} "
          f"{len(per-kept):6d} {len(kept-per):6d}  {skipped}")
print(f"\nTOTAL persisted={tot['per']} v3kept={tot['kept']} intersection={tot['inter']} "
      f"({100*tot['inter']/max(tot['per'],1):.1f}% of persisted, "
      f"{100*tot['inter']/max(tot['kept'],1):.1f}% of v3 kept)")

# whole-tape denominator for the NEW classifier's candidate universe
cur.execute("""SELECT count(*) FROM arbs_usd_swap_tape_legs_v3
               WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
                 AND venue='D2C' AND rate_index_clean IN ('SOFR','FED_FUNDS')
                 AND fixed_rate IS NOT NULL""")
print("v3 legs passing the SQL eligibility predicate (all 610 days):", cur.fetchone()[0])
cur.execute("""SELECT count(*) FROM arbs_usd_swap_tape_legs_v3
               WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
                 AND venue='D2C' AND rate_index_clean IN ('SOFR','FED_FUNDS')
                 AND fixed_rate IS NOT NULL
                 AND expiration_date <= as_of_date + INTERVAL '1105 day'""")
print("  ... and within the 1105-day horizon:", cur.fetchone()[0])
conn.close()
