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

START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} trades across {df['execution_date'].nunique()} trading days")

# Signal 1: Non-NEWT action types (lifecycle events)
non_newt = df[df["event_action"].astype(str).str.upper() != "NEWT"] if "event_action" in df.columns else pd.DataFrame()

# Signal 2: NEWT trades (potential new risk)
newt = sdr.filter_new_risk(df)

# Signal 3: Reset optimization (tenor < 6M)
reset_opt = sdr.filter_reset_optimization(newt)
non_reset = newt[~newt.index.isin(reset_opt.index)]

print(f"Total trades: {len(df):,}")
print(f"  NEWT (new risk candidates): {len(newt):,} ({len(newt)/len(df)*100:.1f}%)")
print(f"  Non-NEWT (lifecycle/compression): {len(non_newt):,} ({len(non_newt)/len(df)*100:.1f}%)")
_newt_n = max(len(newt), 1)
print(f"  Reset optimization (< 6M tenor): {len(reset_opt):,} ({len(reset_opt)/_newt_n*100:.1f}% of NEWT)")
print(f"  Clean new risk: {len(non_reset):,} ({len(non_reset)/len(df)*100:.1f}% of total)")

clean_daily = non_reset.groupby("execution_date")["dv01"].sum()
reset_daily = reset_opt.groupby("execution_date")["dv01"].sum()
lifecycle_daily = non_newt.groupby("execution_date")["dv01"].sum() if not non_newt.empty else pd.Series(dtype=float)

combined = pd.DataFrame({
    "Clean New Risk": clean_daily,
    "Reset Optimization": reset_daily,
    "Lifecycle (TERM/CORR/MODI)": lifecycle_daily,
}).fillna(0).sort_index()
combined.index = pd.to_datetime(combined.index)

sdr.plot_stacked_area(
    combined,
    "Daily DV01: Clean vs Reset Optimization vs Lifecycle",
    color_map={"Clean New Risk": "#4C78A8", "Reset Optimization": "#BFBFBF", "Lifecycle (TERM/CORR/MODI)": "#F58518"},
)
plt.show()

if "platform_identifier" in df.columns:
    platform_dv01 = df.groupby("platform_identifier")["dv01"].sum().sort_values(ascending=False)
    top_platforms = platform_dv01.head(10)
    
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # Bar chart
    top_platforms.plot.barh(ax=axes[0], color="#4C78A8", alpha=0.8)
    axes[0].set_title("DV01 by Platform (Top 10)")
    axes[0].set_xlabel("DV01 ($)")
    
    # Pie chart
    top_platforms.plot.pie(ax=axes[1], autopct="%1.1f%%", startangle=90)
    axes[1].set_ylabel("")
    axes[1].set_title("Platform Market Share (DV01)")
    
    plt.tight_layout()
    plt.show()
else:
    print("platform_identifier column not available.")

if not reset_opt.empty:
    reset_opt_dt = reset_opt.copy()
    reset_opt_dt["execution_date_dt"] = pd.to_datetime(reset_opt_dt["execution_date"])
    reset_opt_dt["weekday"] = reset_opt_dt["execution_date_dt"].dt.day_name()
    
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    weekday_counts = reset_opt_dt.groupby("weekday").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    ).reindex(weekday_order)
    
    fig, ax = plt.subplots(figsize=(10, 5))
    weekday_counts["trade_count"].plot.bar(ax=ax, color="#E45756", alpha=0.8)
    ax.set_title("Reset Optimization Trade Count by Weekday")
    ax.set_ylabel("Trade Count")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
    
    print(weekday_counts.to_string())

raw_daily = df.groupby("execution_date")["dv01"].sum()
clean_daily_final = non_reset.groupby("execution_date")["dv01"].sum()

comparison = pd.DataFrame({
    "Raw Reported": raw_daily,
    "Clean (New Risk Only)": clean_daily_final,
}).fillna(0).sort_index()
comparison.index = pd.to_datetime(comparison.index)

fig, ax = plt.subplots(figsize=(14, 6))
comparison["Raw Reported"].plot(ax=ax, alpha=0.4, color="#BFBFBF", label="Raw Reported")
comparison["Clean (New Risk Only)"].plot(ax=ax, color="#4C78A8", linewidth=1.5, label="Clean New Risk")
ax.set_title("Raw vs Clean Volume (DV01)")
ax.set_ylabel("DV01 ($)")
ax.legend()
plt.tight_layout()
plt.show()

_raw_total = raw_daily.sum()
ratio = clean_daily_final.sum() / _raw_total * 100 if _raw_total > 0 else 0
print(f"Clean/Raw ratio: {ratio:.1f}% \u2014 {100-ratio:.1f}% of reported volume is non-new-risk")

# Align on datetime index
raw_s = raw_daily.copy()
raw_s.index = pd.to_datetime(raw_s.index)
clean_s = clean_daily_final.copy()
clean_s.index = pd.to_datetime(clean_s.index)

monthly = pd.DataFrame({
    "raw": raw_s.resample("ME").sum(),
    "clean": clean_s.resample("ME").sum(),
})
monthly["compression_pct"] = (1 - monthly["clean"] / monthly["raw"]) * 100

fig, ax = plt.subplots(figsize=(14, 5))
monthly["compression_pct"].plot.bar(ax=ax, color="#E45756", alpha=0.8)
ax.set_title("Monthly Compression as % of Total Volume")
ax.set_ylabel("Compression %")
ax.axhline(33, color="black", linestyle="--", alpha=0.5, label="33% benchmark")
ax.legend()
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()
