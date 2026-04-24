"""Debug why detect_sub_package_curve_fly finds nothing on real MMS data."""
import pandas as pd
from pathlib import Path

from SDRUtils.products.usd.usd_swaps import detect_sub_package_curve_fly

root = Path(
    "C:/Users/chris/clee/ARBS/sdr_cache/classification_cache/"
    "usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
    "curve1_fly1_mms1_invoice1_mac1_spreadover1/"
    "2026/04/2026-04-10"
)
files = list(root.glob("*.parquet"))
df = pd.read_parquet(files[0])

print("MMS rows:", (df["package_type"] == "MATCHED_MATURITY").sum())
print("SPREADOVER rows:", (df["package_type"] == "SPREADOVER").sum())

# Pick a subset of MMS trades executed close together
mms = df[df["package_type"] == "MATCHED_MATURITY"].copy()
print("\nMMS head columns relevant to detector:")
print(mms[[
    "trade_id", "execution_timestamp", "tenor_label", "estimated_pv01",
    "effective_date", "forward_label",
    "platform_identifier", "unique_product_identifier",
]].head(20).to_string(index=False))

# Directly call the curve detector on just the MMS subset, masquerading.
from SDRUtils.packages.curve import detect_curve_trades_df

subset = df[df["package_type"] == "MATCHED_MATURITY"].copy()
print(f"\nMMS subset size: {len(subset)}")

subset["package_type"] = "OUTRIGHT"
subset["package_id"] = None
subset["package_legs"] = None

print(f"\nSubset columns (first 15): {list(subset.columns)[:15]}")
print(f"product_type uniques: {subset['product_type'].unique() if 'product_type' in subset.columns else 'MISSING'}")
print(f"pv01 (estimated_pv01) stats: min={subset['estimated_pv01'].min()}, max={subset['estimated_pv01'].max()}")

result = detect_curve_trades_df(
    subset,
    underlier_col="upi_underlier_name",
    platform_col="platform_identifier",
    cleared_col="cleared",
    upi_col="unique_product_identifier",
)
n_curve = (result["package_type"] == "CURVE").sum()
print(f"\nCURVE hits on MMS subset: {n_curve}")
if n_curve > 0:
    print(result[result["package_type"] == "CURVE"][[
        "trade_id", "tenor_label", "estimated_pv01", "package_id",
        "platform_identifier"
    ]].head(10).to_string(index=False))

# Look for *potential* MMS curve candidates: MMS trades paired on
# (execution_timestamp, platform, UPI) with different tenors.
print("\n=== Potential MMS curve candidates (same exec window + pv01 ~match, diff tenor) ===")
mms_subset = df[df["package_type"] == "MATCHED_MATURITY"].copy()
mms_subset["exec_sec"] = pd.to_datetime(mms_subset["execution_timestamp"], utc=True).astype("int64") // 1_000_000_000
# Group by (platform, upi, effective_date, exec_sec bucketed by minute)
mms_subset["minute"] = mms_subset["exec_sec"] // 60
groups = mms_subset.groupby([
    "minute", "platform_identifier", "unique_product_identifier", "effective_date", "forward_label"
])
for key, g in groups:
    if len(g) < 2:
        continue
    # Same key but different tenors
    tenors = g["tenor_label"].unique()
    if len(tenors) < 2:
        continue
    pvs = g["estimated_pv01"].values
    if max(pvs) / min(pvs) > 1.15:  # outside 15% curve tol
        continue
    print(f"key={key}  n={len(g)}  tenors={list(tenors)}  pv range=({min(pvs):.0f}, {max(pvs):.0f})")
    if len([r for r in groups.groups if True]) > 1:  # stop after a few
        pass

print("\n=== Potential SPREADOVER curve candidates (same exec window + pv01 ~match, diff tenor) ===")
spr_subset = df[df["package_type"] == "SPREADOVER"].copy()
spr_subset["exec_sec"] = pd.to_datetime(spr_subset["execution_timestamp"], utc=True).astype("int64") // 1_000_000_000
spr_subset["minute"] = spr_subset["exec_sec"] // 60
groups = spr_subset.groupby([
    "minute", "platform_identifier", "unique_product_identifier", "effective_date", "forward_label"
])
count = 0
for key, g in groups:
    if len(g) < 2:
        continue
    tenors = g["tenor_label"].unique()
    if len(tenors) < 2:
        continue
    pvs = g["estimated_pv01"].values
    if max(pvs) / min(pvs) > 1.15:
        continue
    print(f"key={key}  n={len(g)}  tenors={list(tenors)}  pv range=({min(pvs):.0f}, {max(pvs):.0f})")
    count += 1
    if count > 5:
        break
print(f"Total SPREADOVER candidate curve groups: {count}")


# Try a wider scan: ALL pairs of MMS within 60s of each other on same platform
# with same UPI, different tenor, pv01 within 10%.
print("\n=== Wider MMS pair scan (within 60s) ===")
mms_sorted = mms_subset.sort_values("execution_timestamp").reset_index(drop=True)
found = 0
for i in range(len(mms_sorted)):
    a = mms_sorted.iloc[i]
    for j in range(i + 1, len(mms_sorted)):
        b = mms_sorted.iloc[j]
        dt = (b["execution_timestamp"] - a["execution_timestamp"]).total_seconds()
        if dt > 60:
            break
        if (
            a["platform_identifier"] == b["platform_identifier"]
            and a["unique_product_identifier"] == b["unique_product_identifier"]
            and a["effective_date"] == b["effective_date"]
            and a["forward_label"] == b["forward_label"]
            and a["tenor_label"] != b["tenor_label"]
            and a["estimated_pv01"] > 0
            and b["estimated_pv01"] > 0
            and abs(a["estimated_pv01"] - b["estimated_pv01"]) / (0.5 * (a["estimated_pv01"] + b["estimated_pv01"])) < 0.10
        ):
            found += 1
            if found <= 5:
                print(
                    f"  pair: {a['trade_id']} ({a['tenor_label']} {a['estimated_pv01']:.0f}) "
                    f"<-> {b['trade_id']} ({b['tenor_label']} {b['estimated_pv01']:.0f}) "
                    f"dt={dt:.0f}s platform={a['platform_identifier']}"
                )
print(f"Total MMS curve-candidate pairs within 60s: {found}")
