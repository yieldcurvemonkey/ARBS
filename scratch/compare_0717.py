"""Re-run 2026-07-17 exactly as production, compare to persisted rows. READ ONLY."""
import os, sys, time, math
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import warnings; warnings.filterwarnings("ignore")

import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts.backfill_stir_direction import (
    run_calibration, run_classification, DIRECTION_COLUMNS)

DATE = "2026-07-17"
conn = psycopg2.connect(resolve_pg_url())
t0 = time.time()
stats = run_calibration(conn, "2026-06-01", "2026-06-30", "ticks-only")
t1 = time.time(); print(f"calibration: {len(stats)} rows in {t1-t0:.1f}s", flush=True)
rows = run_classification(conn, DATE, stats, dry_run=True, warm_jobs=8)
t2 = time.time(); print(f"classification: {len(rows)} rows in {t2-t1:.1f}s", flush=True)

new = pd.DataFrame(rows)
new.to_parquet(r"C:\Users\chris\clee\ARBS-dd\scratch\rerun_0717.parquet")

old = pd.read_sql("SELECT * FROM arbs_stir_direction_v1 WHERE as_of_date=%(d)s",
                  conn, params={"d": DATE})
print("\npersisted rows:", len(old), " rerun rows:", len(new))
print("persisted vintage:", old["code_vintage"].dropna().unique())
print("rerun vintage:", new["code_vintage"].unique())

o = old.set_index("unit_key"); n = new.set_index("unit_key")
common = sorted(set(o.index) & set(n.index))
print(f"unit_key: common={len(common)} only_persisted={len(set(o.index)-set(n.index))} "
      f"only_rerun={len(set(n.index)-set(o.index))}")

o, n = o.loc[common], n.loc[common]
print("\n-- categorical agreement --")
for c in ["dealer_direction", "classification_method", "direction_confidence",
          "is_off_market", "trade_type", "tenor_bucket", "dv01_bucket",
          "curve_suspect_trade", "rate_index_clean", "curve_name"]:
    a = o[c].astype(object).where(o[c].notna(), None)
    b = n[c].astype(object).where(n[c].notna(), None)
    eq = (a.values == b.values).sum()
    print(f"{c:24s} same={eq}/{len(common)} ({100*eq/len(common):.2f}%)")

print("\n-- direction confusion (persisted -> rerun) --")
print(pd.crosstab(o["dealer_direction"], n["dealer_direction"]))

print("\n-- numeric drift --")
for c in ["curve_mid", "spread_to_mid_bps", "repriced_pv01", "repriced_npv",
          "dealer_charge_bps", "structure_dv01", "p_flip", "dv01"]:
    a = pd.to_numeric(o[c], errors="coerce").astype(float)
    b = pd.to_numeric(n[c], errors="coerce").astype(float)
    m = a.notna() & b.notna()
    if not m.any():
        print(f"{c:20s} no overlap"); continue
    d = (b[m] - a[m]).abs()
    print(f"{c:20s} n={m.sum():4d} exact={(d==0).sum():4d} maxabs={d.max():.6g} "
          f"med={d.median():.3g}")

print("\n-- curve_timestamp identical? --")
ct = (pd.to_datetime(o["curve_timestamp"], utc=True) ==
      pd.to_datetime(n["curve_timestamp"], utc=True)).sum()
print(f"same={ct}/{len(common)}")

print("\n-- rerun direction / confidence summary --")
print(new["dealer_direction"].value_counts().to_dict())
print(new["direction_confidence"].value_counts(dropna=False).to_dict())
print("\n-- persisted 07-17 summary --")
print(old["dealer_direction"].value_counts().to_dict())
print(old["direction_confidence"].value_counts(dropna=False).to_dict())
conn.close()
