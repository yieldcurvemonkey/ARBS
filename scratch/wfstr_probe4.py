"""Two loose ends: (a) daytime NO_GRID_MINUTE, (b) does differencing cancel
the instrument mismatch, (c) does LOCF rescue the missing minutes."""
import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2, pandas as pd, numpy as np, datetime
pd.set_option('display.width', 240); pd.set_option('display.max_columns', 40)

df = pd.read_parquet("scratch/wfstr_structmid.parquet")
df["exact_dates"] = df["exact_dates"].map(
    lambda v: bool(v) if isinstance(v, (bool, np.bool_)) else False)
for c in ("resid_bp", "fwd_max", "max_abs_eff_off", "max_abs_mat_off"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["spot"] = df["fwd_max"].fillna(0.0) <= 1e-9
df["offmkt"] = df["off_market"].fillna(False).astype(bool)
df["broken"] = df["tenor_display"].fillna("").str.contains("~")
df["std_spot"] = df["spot"] & ~df["broken"] & ~df["offmkt"]

# ---------------------------------------------------------------- (a)
ng = df[df["status"] == "NO_GRID_MINUTE"].copy()
ng["ts"] = pd.to_datetime(ng["ts"], utc=True)
ng["et"] = ng["ts"].dt.tz_convert("America/New_York")
ng["et_hr"] = ng["et"].dt.hour
print("=== NO_GRID_MINUTE by ET hour ===")
print(ng["et_hr"].value_counts().sort_index().to_string())
day_ng = ng[(ng["et_hr"] >= 7) & (ng["et_hr"] <= 17)]
print(f"\ndaytime (07-17 ET) misses: {len(day_ng)} of {len(ng)}")
print(day_ng.groupby([day_ng['et'].dt.date])['et_hr'].count().to_string())
print("\nsample daytime miss minutes:")
print(day_ng[["day", "kind", "labels", "et"]].head(15).to_string(index=False))

conn = psycopg2.connect(resolve_pg_url())
with conn.cursor() as c:
    c.execute("SET statement_timeout = '600s'")

print("\n=== is the store simply missing those minutes for ALL tenors? ===")
for _, r in day_ng.head(8).iterrows():
    ts = pd.Timestamp(r["et"]).tz_convert("UTC")
    q = pd.read_sql("""SELECT count(*) n, count(DISTINCT tenor_label) nt
                       FROM arbs_dd_curve_mid_v1
                       WHERE rate_index='SOFR' AND ts = %(t)s""",
                    conn, params={"t": ts.to_pydatetime()})
    q2 = pd.read_sql("""SELECT min(ts) prev FROM arbs_dd_curve_mid_v1
                        WHERE rate_index='SOFR' AND tenor_label='10Y'
                          AND ts > %(t)s AND ts < %(t)s + interval '3 hours'""",
                     conn, params={"t": ts.to_pydatetime()})
    print(f"  {r['et']}  rows_at_ts={int(q['n'][0])} tenors={int(q['nt'][0])}"
          f"  next_10Y_row={q2['prev'][0]}")
conn.close()

# ---------------------------------------------------------------- (b)
print("\n=== (b) does the SPREAD cancel the instrument mismatch? ===")
sub = df[(df["status"] == "OK") & df["std_spot"] & ~df["exact_dates"]]
for k in ("OUTRIGHT", "CURVE", "FLY"):
    s = sub[sub["kind"] == k]
    a = s["resid_bp"].abs()
    print(f"  {k:9s} n={len(s):6d}  med={a.median():.3g}  p95={a.quantile(.95):.4f}"
          f"  p99={a.quantile(.99):.4f}  max={a.max():.4f}")
print("  -> same date-mismatch population; if the spread cancels the common")
print("     spot/roll error, CURVE/FLY p95 must be well below OUTRIGHT p95.")

print("\n  by |eff_off| on the day the whole tape's spot was 1bd off (2025-04-09):")
d = df[(df["day"] == "2025-04-09") & (df["status"] == "OK") & df["std_spot"]]
for k in ("OUTRIGHT", "CURVE", "FLY"):
    s = d[d["kind"] == k]
    if len(s) == 0:
        continue
    a = s["resid_bp"].abs()
    print(f"    {k:9s} n={len(s):5d} med={a.median():.4f} p95={a.quantile(.95):.4f} max={a.max():.4f}")
