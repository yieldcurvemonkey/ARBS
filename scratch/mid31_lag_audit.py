"""Retroactive lookahead audit: do the rows ALREADY in the grid table pass the
new verify check? The in-process guard can only speak for rows written after it
existed; 1.38 M were written before it did."""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S
from SDRUtils._swappulse_scripts.backfill_curve_mids import connect

SQL = f"""
SELECT grid_date, rate_index, count(*) n,
       count(*) FILTER (WHERE mid_pct IS NULL)              n_null_mid,
       count(*) FILTER (WHERE snapshot_lag_seconds IS NULL) n_null_lag,
       min(snapshot_lag_seconds) min_lag,
       max(abs(snapshot_lag_seconds)) max_abs_lag,
       count(DISTINCT snapshot_policy) n_pol,
       count(*) FILTER (WHERE served_ts IS NULL)            n_null_served,
       count(*) FILTER (WHERE served_ts > ts)               n_served_after,
       count(DISTINCT code_vintage) n_vintage
FROM {S.CURVE_MID_TABLE}
GROUP BY grid_date, rate_index ORDER BY grid_date, rate_index
"""

conn = connect()
try:
    with conn.cursor() as cur:
        cur.execute(SQL)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
finally:
    conn.close()

i = {c: k for k, c in enumerate(cols)}
print(f"{len(rows)} (grid_date, rate_index) cells over "
      f"{len({r[0] for r in rows})} grid dates")
print(f"{sum(r[i['n']] for r in rows):,} rows total\n")

bad = []
for r in rows:
    why = []
    if r[i["n_null_mid"]]:
        why.append(f"{r[i['n_null_mid']]} NULL mid")
    if r[i["n_null_lag"]]:
        why.append(f"{r[i['n_null_lag']]} NULL lag")
    if r[i["min_lag"]] is not None and float(r[i["min_lag"]]) < 0:
        why.append(f"min lag {r[i['min_lag']]}")
    if r[i["n_served_after"]]:
        why.append(f"{r[i['n_served_after']]} served_ts > ts")
    if r[i["n_null_served"]]:
        why.append(f"{r[i['n_null_served']]} NULL served_ts")
    if why:
        bad.append((r[i["grid_date"]], r[i["rate_index"]], "; ".join(why)))

print(f"cells failing the new checks: {len(bad)}")
for d, ix, why in bad[:40]:
    print(f"  FAIL {d}/{ix}: {why}")

lags = [float(r[i["max_abs_lag"]]) for r in rows if r[i["max_abs_lag"]] is not None]
mins = [float(r[i["min_lag"]]) for r in rows if r[i["min_lag"]] is not None]
print(f"\nmax |lag| across every cell: {max(lags) if lags else None}")
print(f"min  lag  across every cell: {min(mins) if mins else None}")
print(f"distinct code_vintage per cell: {sorted({r[i['n_vintage']] for r in rows})}")
print(f"distinct snapshot_policy per cell: {sorted({r[i['n_pol']] for r in rows})}")
print(f"\ndates: {sorted({str(r[0]) for r in rows})}")
