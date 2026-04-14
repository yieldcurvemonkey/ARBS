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
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")

spreadovers = sdr.filter_spreadovers(df)
non_spreadovers = df[~df.index.isin(spreadovers.index)]

n_total = max(len(df), 1)
total_dv01 = max(df['dv01'].sum(), 1)
print(f"Spreadovers: {len(spreadovers):,} trades ({len(spreadovers)/n_total*100:.1f}%)")
print(f"  DV01: {sdr.format_dv01(spreadovers['dv01'].sum())} ({spreadovers['dv01'].sum()/total_dv01*100:.1f}% of total)")
print(f"Non-spreadovers: {len(non_spreadovers):,}")

sprd_rates = spreadovers[pd.to_numeric(spreadovers["fixed_rate"], errors="coerce").notna()].copy()
if sprd_rates.empty:
    print("No spreadover trades with valid fixed rates.")
    daily_vwaps = pd.DataFrame()
else:
    sprd_rates["fixed_rate"] = pd.to_numeric(sprd_rates["fixed_rate"])
    daily_vwaps = sdr.daily_vwap(sprd_rates, group_col="tenor_label")

for tenor in ["2Y", "5Y", "10Y", "30Y"]:
    if daily_vwaps.empty:
        break
    tv = daily_vwaps[daily_vwaps["tenor_label"] == tenor].set_index("execution_date")["vwap"].sort_index()
    if len(tv) < 5:
        continue
    tv.index = pd.to_datetime(tv.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.plot(tv.index, tv.values, color="#4C78A8", linewidth=1, label="VWAP")
    ma20 = tv.rolling(20, min_periods=3).mean()
    ax.plot(ma20.index, ma20.values, color="#F58518", linewidth=1.5, linestyle="--", label="20d MA")
    ax.set_title(f"{tenor} Spreadover VWAP")
    ax.set_ylabel("Fixed Rate")
    ax.legend()
    plt.tight_layout()
    plt.show()

sprd_pivot = sdr.daily_dv01_by_group(spreadovers, "tenor_label")
sprd_pivot = sprd_pivot[[c for c in sdr.BENCHMARK_TENORS if c in sprd_pivot.columns]]

if not sprd_pivot.empty:
    sdr.plot_stacked_area(sprd_pivot, "Daily Spreadover DV01 by Tenor")
    plt.show()
else:
    print("No spreadover data for tenor plot.")

# Swapalypse detection
sprd_daily = spreadovers.groupby("execution_date")["dv01"].sum()
sprd_daily.index = pd.to_datetime(sprd_daily.index)
z = sdr.rolling_zscore(sprd_daily, window=20)
swapalypse = z[z > 2].sort_values(ascending=False)

if not swapalypse.empty:
    print(f"\n'Swapalypse' days (spreadover volume >2\u03c3): {len(swapalypse)}")
    for date, z_val in swapalypse.head(10).items():
        vol = sprd_daily.get(date, 0)
        print(f"  {date.date()}: Z={z_val:+.1f}, DV01={sdr.format_dv01(vol)}")

tenor_dv01 = spreadovers.groupby("tenor_label")["dv01"].sum().sort_values(ascending=False)
top_tenors = tenor_dv01.head(10)

if top_tenors.empty:
    print("No spreadover tenor data to plot.")
else:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    top_tenors.plot.bar(ax=axes[0], color="#72B7B2", alpha=0.8)
    axes[0].set_title("Spreadover DV01 by Tenor")
    axes[0].set_ylabel("DV01 ($)")

    top_tenors.plot.pie(ax=axes[1], autopct="%1.1f%%", startangle=90)
    axes[1].set_ylabel("")
    axes[1].set_title("Spreadover Tenor Distribution")
    plt.tight_layout()
    plt.show()

sprd_daily_dv01 = spreadovers.groupby("execution_date")["dv01"].sum()
total_daily_dv01 = df.groupby("execution_date")["dv01"].sum()

ratio = (sprd_daily_dv01 / total_daily_dv01 * 100).fillna(0)
ratio.index = pd.to_datetime(ratio.index)

fig, ax = plt.subplots(figsize=(14, 5))
ax.bar(ratio.index, ratio.values, alpha=0.4, color="#72B7B2")
ma20 = ratio.rolling(20, min_periods=3).mean()
ax.plot(ma20.index, ma20.values, color="#E45756", linewidth=2, label="20d MA")
ax.set_title("Spreadover as % of Total DV01")
ax.set_ylabel("Spreadover %")
ax.legend()
plt.tight_layout()
plt.show()

print(f"Average spreadover share: {ratio.mean():.1f}%")
print(f"Current (last 20d): {ratio.tail(20).mean():.1f}%")
