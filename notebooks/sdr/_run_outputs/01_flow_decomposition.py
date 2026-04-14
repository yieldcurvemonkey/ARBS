import nest_asyncio
nest_asyncio.apply()
import sys, os
sys.path.insert(0, r'C:\Users\chris\clee\ARBS')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS\notebooks\sdr')
import matplotlib
matplotlib.use('Agg')

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath("__file__")))

import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

import _usd_swaps_common as sdr

sdr.notebook_setup()

# --- Parameters ---
START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} classified trades from {df['execution_date'].nunique()} trading days")
print(f"Total DV01: {sdr.format_dv01(df['dv01'].sum())}")
print(f"Columns: {list(df.columns)}")

# Assign effective trade type for visualization
def assign_trade_type(row):
    pkg = str(row.get("package_type", "")).upper()
    if pkg in ("CURVE", "FLY"):
        return pkg
    if row.get("is_spreadover", False):
        return "SPREADOVER"
    st = str(row.get("special_tenor_type", "STANDARD")).upper()
    if st in ("MAC", "IMM", "FOMC", "MATCHED_MATURITY", "INVOICE_SWAP"):
        return st
    return "OUTRIGHT"

df["trade_type"] = df.apply(assign_trade_type, axis=1)

pivot = sdr.daily_dv01_by_group(df, "trade_type")
type_order = ["OUTRIGHT", "CURVE", "FLY", "SPREADOVER", "MAC", "IMM", "FOMC", "MATCHED_MATURITY", "INVOICE_SWAP"]
pivot = pivot[[c for c in type_order if c in pivot.columns]]

sdr.plot_stacked_bar(pivot, "Daily DV01 by Trade Type", color_map=sdr.PACKAGE_COLORS)
plt.show()

# Summary stats
print("\nTrade Type Summary:")
type_summary = df.groupby("trade_type").agg(
    count=("dv01", "size"),
    total_dv01=("dv01", "sum"),
    pct_count=("dv01", "size"),
).assign(
    pct_count=lambda x: x["count"] / max(x["count"].sum(), 1) * 100,
    pct_dv01=lambda x: x["total_dv01"] / max(x["total_dv01"].sum(), 1) * 100,
)
print(type_summary.round(1).to_string())

packages = sdr.filter_packages(df)
if not packages.empty:
    pkg_summary = packages.groupby("package_id").agg(
        package_type=("package_type", "first"),
        num_legs=("trade_id", "size"),
        tenors=("tenor_label", lambda x: " / ".join(sorted(x.unique()))),
        net_dv01=("dv01", "sum"),
        execution_time=("execution_timestamp", "first"),
    ).sort_values("net_dv01", ascending=False)
    
    print(f"Detected {len(pkg_summary)} packages ({len(packages)} legs)")
    print(f"  Curves: {(pkg_summary['package_type'] == 'CURVE').sum()}")
    print(f"  Flies: {(pkg_summary['package_type'] == 'FLY').sum()}")
    print(f"\nTop 20 packages by DV01:")
    print(pkg_summary.head(20))
else:
    print("No packages detected in this date range.")

if "rate_index" in df.columns:
    ri_pivot = sdr.daily_dv01_by_group(df, "rate_index")
    sdr.plot_stacked_area(ri_pivot, "Daily DV01 by Rate Index", color_map=sdr.RATE_INDEX_COLORS)
    plt.show()

    # Pie chart
    ri_totals = df.groupby("rate_index")["dv01"].sum()
    fig, ax = plt.subplots(figsize=(8, 8))
    colors = [sdr.RATE_INDEX_COLORS.get(ri, "#999") for ri in ri_totals.index]
    ri_totals.plot.pie(ax=ax, autopct="%1.1f%%", colors=colors, startangle=90)
    ax.set_ylabel("")
    ax.set_title("DV01 Share by Rate Index")
    plt.tight_layout()
    plt.show()
else:
    print("rate_index column not available — skipping.")

fwd_labels = ["spot", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "2Y", "3Y+"]

def bucket_forward(label):
    if pd.isna(label) or str(label).lower() == "spot":
        return "spot"
    try:
        years = float(str(label).replace("Y", "").replace("M", ""))
    except ValueError:
        return str(label)
    return str(label) if str(label) in fwd_labels else "3Y+"

df["forward_bucket"] = df["forward_label"].apply(bucket_forward)
fwd_dv01 = df.groupby("forward_bucket")["dv01"].sum()
_total = fwd_dv01.sum()
spot_pct = fwd_dv01.get("spot", 0) / _total * 100 if _total > 0 else 0

fig, ax = plt.subplots(figsize=(10, 6))
fwd_order = [f for f in fwd_labels if f in fwd_dv01.index]
fwd_dv01[fwd_order].plot.bar(ax=ax, color="#4C78A8", alpha=0.8)
ax.set_title(f"DV01 by Forward Start Period (Spot: {spot_pct:.1f}%)")
ax.set_ylabel("DV01 ($)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

if "special_tenor_type" in df.columns:
    st_counts = df.groupby("special_tenor_type").agg(
        count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    st_counts["pct_count"] = st_counts["count"] / st_counts["count"].sum() * 100
    st_counts["pct_dv01"] = st_counts["total_dv01"] / st_counts["total_dv01"].sum() * 100
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    colors = [sdr.SPECIAL_TENOR_COLORS.get(st, "#999") for st in st_counts.index]
    st_counts["count"].plot.bar(ax=axes[0], color=colors, alpha=0.8)
    axes[0].set_title("Trade Count by Special Tenor Type")
    st_counts["total_dv01"].plot.bar(ax=axes[1], color=colors, alpha=0.8)
    axes[1].set_title("DV01 by Special Tenor Type")
    plt.tight_layout()
    plt.show()
    
    print(st_counts.round(1).to_string())

def top_tenors(group, n=3):
    return ", ".join(
        group.groupby("tenor_label")["dv01"]
        .sum()
        .nlargest(n)
        .index.tolist()
    )

daily = df.groupby("execution_date").agg(
    trade_count=("dv01", "size"),
    total_dv01=("dv01", "sum"),
    avg_dv01=("dv01", "mean"),
    pct_packages=("package_type", lambda x: (x.fillna("OUTRIGHT") != "OUTRIGHT").mean() * 100),
    pct_spreadovers=("is_spreadover", lambda x: x.fillna(False).mean() * 100),
    unique_tenors=("tenor_label", "nunique"),
)
daily["top_tenors"] = df.groupby("execution_date").apply(top_tenors)
daily["total_dv01_fmt"] = daily["total_dv01"].apply(sdr.format_dv01)

print(daily.round(1))
