"""What is already in the mid-grid tables, before the pilot."""
import os, sys, pathlib
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S
from SDRUtils._swappulse_scripts.backfill_dealer_direction import connect

conn = connect()
cur = conn.cursor()
for t in (S.CURVE_MID_TABLE, S.CURVE_MID_DAY_TABLE):
    cur.execute("SELECT to_regclass(%s)", (t,))
    print(t, "exists:", cur.fetchone()[0])

cur.execute(f"SELECT grid_date, rate_index, count(*) FROM {S.CURVE_MID_TABLE} "
            "GROUP BY 1,2 ORDER BY 1,2")
print("\nmid rows by grid_date/index:")
for r in cur.fetchall():
    print("  ", r)

cur.execute(f"SELECT count(*) FROM {S.CURVE_MID_TABLE}")
print("total mid rows:", cur.fetchone()[0])
cur.execute(f"SELECT grid_date, rate_index, status, minutes_served, "
            f"minutes_missed, n_rows FROM {S.CURVE_MID_DAY_TABLE} ORDER BY 1,2")
print("\nday ledger:")
for r in cur.fetchall():
    print("  ", r)

# do the three pilot days have prints on the tape?
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
for d in ("2026-04-01", "2026-06-17", "2025-04-07"):
    cur.execute(
        f"SELECT count(*) FROM {LEGS_TABLE} WHERE "
        "(event_timestamp AT TIME ZONE 'America/New_York')::date = %s", (d,))
    print(f"tape legs on ET {d}:", cur.fetchone()[0])
conn.close()
