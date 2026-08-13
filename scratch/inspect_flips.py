import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)

new = pd.read_parquet(r"C:\Users\chris\clee\ARBS-dd\scratch\rerun_0717.parquet").set_index("unit_key")
conn = psycopg2.connect(resolve_pg_url())
old = pd.read_sql("SELECT * FROM arbs_stir_direction_v1 WHERE as_of_date='2026-07-17'", conn).set_index("unit_key")
conn.close()
common = sorted(set(old.index) & set(new.index))
o, n = old.loc[common], new.loc[common]
diff = [k for k in common if o.at[k, "dealer_direction"] != n.at[k, "dealer_direction"]]
print("flipped unit_keys:", diff)
cols = ["trade_type", "rate_index_clean", "is_off_market", "classification_method",
        "dealer_direction", "direction_confidence", "p_flip", "curve_mid",
        "fixed_rate", "spread_to_mid_bps", "traded_spread_bps", "curve_mid_spread_bps",
        "repriced_npv", "reported_opa", "reported_ptp", "dealer_charge_bps",
        "structure_dv01", "dv01", "tenor_bucket", "curve_suspect_trade", "quality_flags"]
for k in diff:
    print("\n=== ", k)
    for c in cols:
        print(f"  {c:24s} old={o.at[k,c]!r:60s} new={n.at[k,c]!r}")

# how marginal is the on-market population?
s2m = pd.to_numeric(n["spread_to_mid_bps"], errors="coerce").abs()
print("\n|s2m| distribution (rerun, on-market):")
print(s2m.describe(percentiles=[.05,.1,.25,.5,.75,.9]).to_string())
for thr in (0.01, 0.05, 0.125, 0.25, 0.5):
    print(f"  |s2m| < {thr:>5}: {(s2m < thr).sum():4d} / {s2m.notna().sum()}")
print("  s2m exactly 0:", (s2m == 0).sum())
print("\nrerun classification_method:", n["classification_method"].value_counts().to_dict())
