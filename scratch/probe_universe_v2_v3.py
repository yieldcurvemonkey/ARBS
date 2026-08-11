"""Eligible-unit universe on v2 vs v3 tape for a few days, vs persisted rows. READ ONLY."""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts import _tape_tables as TT
from SDRUtils.stir_flow import trade_selection as TS
from SDRUtils.stir_flow.trade_selection import build_units, is_excluded_unit

DAYS = ["2026-07-17", "2026-07-24", "2026-07-29"]
conn = psycopg2.connect(resolve_pg_url())

def sql_for(gen):
    return (TS.ELIGIBLE_LEGS_SQL.replace(f"_{TT.TAPE_GENERATION}", f"_{gen}"),
            TS.ALL_PKG_LEGS_SQL.replace(f"_{TT.TAPE_GENERATION}", f"_{gen}"))

for gen in ("v2", "v3"):
    esql, asql = sql_for(gen)
    print(f"\n===== tape {gen} =====")
    for d in DAYS:
        try:
            elig = pd.read_sql(esql, conn, params={"start": d, "end": d})
        except Exception as e:
            conn.rollback(); print(f"{d} {gen}: ERROR {e}"); continue
        pkg_ids = sorted(set(elig.loc[elig["n_package_legs"].fillna(1) > 1, "package_id"].dropna()))
        allp = elig.head(0)
        if pkg_ids:
            allp = pd.read_sql(asql, conn, params={"package_ids": pkg_ids})
        units = list(build_units(elig, allp))
        kept, skipped = [], {}
        for u in units:
            r = is_excluded_unit(u.legs)
            if r:
                skipped[r] = skipped.get(r, 0) + 1
            else:
                kept.append(u)
        print(f"{d} {gen}: eligible_legs={len(elig)} units={len(units)} kept={len(kept)} skipped={skipped}")
        globals().setdefault("KEEP", {})[(gen, d)] = {u.unit_key for u in kept}

print("\n===== persisted vs kept =====")
cur = conn.cursor()
for d in DAYS:
    cur.execute("SELECT unit_key FROM arbs_stir_direction_v1 WHERE as_of_date=%s", (d,))
    per = {r[0] for r in cur.fetchall()}
    for gen in ("v2", "v3"):
        k = KEEP.get((gen, d), set())
        print(f"{d} {gen}: persisted={len(per)} kept={len(k)} "
              f"inter={len(per & k)} only_persisted={len(per - k)} only_kept={len(k - per)}")
conn.close()
