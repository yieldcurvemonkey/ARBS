"""Did the guard and the ET filter change a single number?

2026-06-16 was published before either existed. Re-priced with both in place
(dry-run, separate cache), every row must be bit-identical -- otherwise a
hardening change quietly moved the mid the chart draws.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd
from SDRUtils._swappulse_scripts import _dealer_direction_schema_v1 as S
from SDRUtils._swappulse_scripts.backfill_curve_mids import connect

DAY = "2026-06-16"
new = pd.read_parquet(rf"D:\midgrid_review\grid\{DAY}.parquet")

conn = connect()
try:
    old = pd.read_sql(
        f"SELECT rate_index, tenor_label, ts, mid_pct, pv01, effective_date, "
        f"maturity_date, snapshot_lag_seconds, snapshot_policy "
        f"FROM {S.CURVE_MID_TABLE} WHERE grid_date = %(d)s",
        conn, params={"d": DAY})
finally:
    conn.close()

for f in (new, old):
    f["ts"] = pd.to_datetime(f["ts"], utc=True)
    for c in ("effective_date", "maturity_date"):
        f[c] = pd.to_datetime(f[c]).dt.date

k = ["rate_index", "tenor_label", "ts"]
new = new.sort_values(k).reset_index(drop=True)
old = old.sort_values(k).reset_index(drop=True)
print(f"re-priced rows {len(new):,} | published rows {len(old):,}")
assert len(new) == len(old), "row count moved"

m = new.merge(old, on=k, suffixes=("_new", "_old"), how="outer", indicator=True)
print("join:", dict(m["_merge"].value_counts()))
assert (m["_merge"] == "both").all(), "the key set moved"

d = (m["mid_pct_new"].astype(float) - m["mid_pct_old"].astype(float)).abs()
print(f"max |mid_pct difference| = {d.max():.3e} percent "
      f"({d.max() * 100:.3e} bp)")
print(f"rows differing at all      = {int((d > 0).sum()):,}")
for c in ("pv01", "effective_date", "maturity_date", "snapshot_policy"):
    same = (m[f"{c}_new"] == m[f"{c}_old"]).all()
    print(f"{c:<18} identical: {same}")
print("\nBIT-IDENTICAL" if d.max() == 0 else "\nTHE NUMBERS MOVED")
