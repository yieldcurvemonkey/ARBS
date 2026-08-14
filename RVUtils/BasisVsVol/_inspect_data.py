import json
import pathlib

import pandas as pd

D = pathlib.Path(__file__).resolve().parents[2] / "notebooks" / "backtests" / "basis_vs_vol" / "_data"
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

u = pd.read_parquet(D / "arbs_ustf_vol_snapshots_v2.parquet")
s = pd.read_parquet(D / "arbs_swaption_vol_snapshots_v2.parquet")
c = pd.read_parquet(D / "arbs_ustf_vs_swaption_comparison_v2.parquet")

for name, df in (("USTF", u), ("SWPT", s), ("CMP", c)):
    print(f"\n{'=' * 30} {name} {'=' * 30}")
    print("columns:", list(df.columns))
    print(df.dtypes.to_string())
    print("\nhead(2):")
    print(df.head(2).to_string(max_colwidth=60))

print("\n\n=== USTF: products x expiry coverage ===")
print(u.groupby(["product", "expiry_label"]).size().unstack(fill_value=0).to_string())
print("\n=== USTF: sample non-null counts ===")
print(u.notna().sum().to_string())

print("\n\n=== SWPT: expiry x tail coverage ===")
print(s.groupby(["expiry_label", "tail_label"]).size().unstack(fill_value=0).to_string())
print("\n=== SWPT: non-null counts ===")
print(s.notna().sum().to_string())

row = u.iloc[len(u) // 2]
print("\n\n=== USTF sample row (mid-sample) ===")
for k, v in row.items():
    if k in ("smile_points", "delta_otm_vols", "strike_offset_otm_vols"):
        continue
    print(f"  {k}: {v}")
print("\n  strike_offset_otm_vols keys:", list(json.loads(row["strike_offset_otm_vols"]).keys())[:8])
so = json.loads(row["strike_offset_otm_vols"])
k0 = list(so.keys())[0]
print(f"  strike_offset_otm_vols['{k0}'] =", json.dumps(so[k0], indent=2)[:900])
sp = json.loads(row["smile_points"])
print(f"\n  smile_points: n={len(sp)}, first =", json.dumps(sp[0], indent=2)[:700] if sp else "EMPTY")
do = json.loads(row["delta_otm_vols"])
kd = list(do.keys())[0] if do else None
print(f"\n  delta_otm_vols keys: {list(do.keys())[:8]}")
if kd:
    print(f"  delta_otm_vols['{kd}'] =", json.dumps(do[kd], indent=2)[:700])

srow = s.iloc[len(s) // 2]
print("\n\n=== SWPT sample row (mid-sample) ===")
for k, v in srow.items():
    if k in ("smile_points", "delta_otm_vols", "strike_offset_otm_vols"):
        continue
    print(f"  {k}: {v}")
sso = json.loads(srow["strike_offset_otm_vols"])
print("\n  strike_offset_otm_vols keys:", list(sso.keys())[:8])
if sso:
    kk = list(sso.keys())[0]
    print(f"  ['{kk}'] =", json.dumps(sso[kk], indent=2)[:900])

print("\n\n=== CMP sample ===")
print(c.tail(8).to_string())
print("\n=== CMP vol_diff_bps describe by product ===")
print(c.groupby("product")["vol_diff_bps"].describe().to_string())
