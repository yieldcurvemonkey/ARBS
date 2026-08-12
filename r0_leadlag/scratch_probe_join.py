"""Probe: does trade_id join to the slice Dissemination Identifier, and does the
recovered lag reproduce the independently-measured p50 5.23 min / p95 11.3 min?

Three known-answer checks (the tool is validated before it is trusted):
  1. match rate should be near 100% (config.py: TRADE_ID = "Dissemination Identifier")
  2. every matched dissem time must be >= execution_timestamp
  3. the lag distribution must reproduce the prior measurement
Uses build_x_tape's OWN harvest code, not a re-implementation.
"""
import os, sys, datetime as dt
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-r0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-r0\r0_leadlag")

import numpy as np
import pandas as pd
import psycopg2
import build_x_tape as B
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

DAY = dt.date(2026, 8, 6)
sess = B._session()
frames = []
for d in (DAY, DAY + dt.timedelta(days=1)):
    df = B.harvest_day(sess, d)
    print(f"harvest {d}: rows={len(df)} max_seq={df['slice_seq'].max() if len(df) else 0}")
    frames.append(df)
sl = pd.concat(frames, ignore_index=True)

print(f"\nslice rows total          : {len(sl)}")
print(f"distinct dissem ids       : {sl['dissem_id'].nunique()}")
print(f"duplicate dissem id rows  : {len(sl) - sl['dissem_id'].nunique()}")
print("action_type mix:", sl["action_type"].value_counts().head(8).to_dict())

sl["dissem_ts_utc"] = pd.to_datetime(sl["mtime_naive_et"]) + B.ET_OFFSET
sl["dissem_ts_utc"] = sl["dissem_ts_utc"].dt.tz_localize("UTC")
first = sl.sort_values("dissem_ts_utc").drop_duplicates("dissem_id", keep="first")

conn = psycopg2.connect(resolve_pg_url())
sql = B.TAPE_SQL.format(legs=LEGS_TABLE) + " AND as_of_date = %(start)s"
tp = pd.read_sql(B.TAPE_SQL.format(legs=LEGS_TABLE), conn,
                 params={"start": str(DAY), "end": str(DAY)})
conn.close()
tp["execution_timestamp"] = pd.to_datetime(tp["execution_timestamp"], utc=True)
print(f"\nin-scope tape legs for {DAY}: {len(tp)}")

m = tp.merge(first[["dissem_id", "dissem_ts_utc", "slice_day"]],
             left_on="trade_id", right_on="dissem_id", how="left")
matched = m["dissem_ts_utc"].notna()
print(f"CHECK 1  match rate       : {matched.sum()}/{len(m)} = {matched.mean()*100:.2f}%")

lag = (m.loc[matched, "dissem_ts_utc"] - m.loc[matched, "execution_timestamp"]).dt.total_seconds()
n_neg = int((lag < 0).sum())
print(f"CHECK 2  dissem < exec    : {n_neg} violations ({n_neg/max(1,len(lag))*100:.3f}%)"
      f"   min lag = {lag.min():.0f}s")
qs = np.percentile(lag, [1, 5, 25, 50, 75, 90, 95, 99])
print(f"CHECK 3  lag minutes      : p1={qs[0]/60:.2f} p5={qs[1]/60:.2f} p25={qs[2]/60:.2f} "
      f"p50={qs[3]/60:.2f} p75={qs[4]/60:.2f} p90={qs[5]/60:.2f} p95={qs[6]/60:.2f} p99={qs[7]/60:.2f}")
print("         prior (independent): p50 = 5.23 min, p95 = 11.3 min")
print(f"  block p50={lag[m.loc[matched,'is_block'].values].median()/60:.2f}min  "
      f"nonblock p50={lag[~m.loc[matched,'is_block'].values].median()/60:.2f}min")

sp = m.loc[matched, "slice_day"].value_counts()
print(f"\nspillover to next UTC day : {sp.to_dict()}")
um = m[~matched]
print(f"unmatched sample trade_ids: {um['trade_id'].head(5).tolist()}")
if len(um):
    print("unmatched by trade_type   :", um["trade_type"].value_counts().head(6).to_dict())
    print("unmatched exec hour (UTC) :", um["execution_timestamp"].dt.hour.value_counts().head(6).to_dict())

# --- forward_bucket sanity (is the tape column consistent with forward_start_years?)
conn = psycopg2.connect(resolve_pg_url())
fb = pd.read_sql(f"""
 SELECT forward_bucket, count(*) n,
        min(forward_start_years) mn, max(forward_start_years) mx,
        percentile_disc(0.5) WITHIN GROUP (ORDER BY forward_start_years) med
 FROM {LEGS_TABLE}
 WHERE as_of_date BETWEEN '2026-05-01' AND '2026-08-07' AND economic_class='ECONOMIC_FLOW'
   AND contributes_to_flow AND rate_index_clean IN ('SOFR','FED_FUNDS')
   AND fixed_rate IS NOT NULL AND notional < 1e19 AND tenor_years > 0
 GROUP BY 1 ORDER BY 2 DESC""", conn)
conn.close()
print("\n=== forward_bucket vs forward_start_years ===")
print(fb.to_string(index=False))
