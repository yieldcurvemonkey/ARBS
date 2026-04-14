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

# Use wider lookback for baseline comparison
START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
print(f"Loaded {len(df):,} trades across {df['execution_date'].nunique()} trading days")

pivot = sdr.daily_dv01_by_group(df, "tenor_bucket")
pivot = pivot[[c for c in sdr.TENOR_BUCKET_ORDER if c in pivot.columns]]

sdr.plot_stacked_area(pivot, "Daily DV01 by Tenor Bucket", ylabel="DV01 ($)")
plt.show()

daily_total = df.groupby("execution_date")["dv01"].sum().sort_index()
daily_total.index = pd.to_datetime(daily_total.index)

fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

# Panel 1: Daily DV01 with rolling averages
axes[0].bar(daily_total.index, daily_total.values, alpha=0.4, color="#4C78A8", label="Daily DV01")
for window, color, label in [(20, "#F58518", "20d MA"), (60, "#E45756", "60d MA"), (252, "#54A24B", "252d MA")]:
    ma = daily_total.rolling(window, min_periods=5).mean()
    axes[0].plot(ma.index, ma.values, color=color, linewidth=1.5, label=label)
axes[0].set_title("Daily DV01 with Rolling Averages")
axes[0].set_ylabel("DV01 ($)")
axes[0].legend()

# Panel 2: Z-scores
for window, color, label in [(20, "#F58518", "20d Z"), (60, "#E45756", "60d Z")]:
    z = sdr.rolling_zscore(daily_total, window=window)
    axes[1].plot(z.index, z.values, color=color, linewidth=1, label=label, alpha=0.8)
axes[1].axhline(2, color="red", linestyle="--", alpha=0.5, label="+2\u03c3")
axes[1].axhline(-2, color="red", linestyle="--", alpha=0.5, label="-2\u03c3")
axes[1].set_title("Volume Z-Scores (vs Rolling Baselines)")
axes[1].set_ylabel("Z-Score")
axes[1].legend()

plt.tight_layout()
plt.show()

# Flag spike days
z20 = sdr.rolling_zscore(daily_total, window=20)
spikes = z20[z20.abs() > 2].sort_values(ascending=False)
if not spikes.empty:
    print(f"\n{len(spikes)} volume spike days (|Z| > 2):")
    for date, z_val in spikes.head(10).items():
        vol = daily_total.get(date, 0)
        print(f"  {date.date()}: Z={z_val:+.1f}, DV01={sdr.format_dv01(vol)}")

new_risk = sdr.filter_new_risk(df)
compression = sdr.filter_compression_heuristic(df)

nr_daily = new_risk.groupby("execution_date")["dv01"].sum()
comp_daily = compression.groupby("execution_date")["dv01"].sum()

combined = pd.DataFrame({
    "New Risk": nr_daily,
    "Compression": comp_daily,
}).fillna(0).sort_index()
combined.index = pd.to_datetime(combined.index)

sdr.plot_stacked_area(combined, "Daily DV01: New Risk vs Compression")
plt.show()

total_nr = nr_daily.sum()
total_comp = comp_daily.sum()
print(f"New Risk: {sdr.format_dv01(total_nr)} ({total_nr / (total_nr + total_comp) * 100:.1f}%)")
print(f"Compression: {sdr.format_dv01(total_comp)} ({total_comp / (total_nr + total_comp) * 100:.1f}%)")

reset_opt = sdr.filter_reset_optimization(df)
clean = df[~df.index.isin(reset_opt.index)]

reset_daily = reset_opt.groupby("execution_date")["dv01"].sum()
clean_daily = clean.groupby("execution_date")["dv01"].sum()

fig, ax = plt.subplots(figsize=(14, 6))
combined_ro = pd.DataFrame({
    "Clean Volume": clean_daily,
    "Reset Optimization": reset_daily,
}).fillna(0).sort_index()
combined_ro.index = pd.to_datetime(combined_ro.index)
combined_ro.plot.area(ax=ax, stacked=True, alpha=0.8, color=["#4C78A8", "#BFBFBF"])
ax.set_title("Daily DV01: Clean Volume vs Reset Optimization")
ax.set_ylabel("DV01 ($)")
plt.tight_layout()
plt.show()

print(f"Reset optimization: {len(reset_opt):,} trades ({len(reset_opt)/len(df)*100:.1f}% of total)")

df_dt = df.copy()
df_dt["execution_date_dt"] = pd.to_datetime(df_dt["execution_date"])
df_dt["weekday"] = df_dt["execution_date_dt"].dt.day_name()
df_dt["month"] = df_dt["execution_date_dt"].dt.month_name()

daily_dv01 = df_dt.groupby(["execution_date", "weekday", "month"])["dv01"].sum().reset_index()
season_pivot = daily_dv01.pivot_table(
    index="weekday",
    columns="month",
    values="dv01",
    aggfunc="mean",
)
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
month_order = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
season_pivot = season_pivot.reindex(index=[d for d in weekday_order if d in season_pivot.index],
                                     columns=[m for m in month_order if m in season_pivot.columns])

sdr.plot_heatmap(season_pivot / 1e6, "Average Daily DV01 by Weekday x Month ($M)", fmt=".2f", cmap="YlOrRd")
plt.show()

from SDRUtils.analytics.seasonality import get_fomc_dates, get_quarter_end_dates, get_imm_dates

fomc = get_fomc_dates()
qe = get_quarter_end_dates(START.date(), END.date())
imm = get_imm_dates(START.date(), END.date())

def classify_spike(date):
    d = date.date() if hasattr(date, "date") else date
    tags = []
    if d in fomc:
        tags.append("FOMC")
    if d in qe:
        tags.append("Quarter-End")
    if d in imm:
        tags.append("IMM Roll")
    # Check +/- 1 day
    for event_dates, label in [(fomc, "FOMC\u00b11"), (qe, "QE\u00b11")]:
        for ed in event_dates:
            if abs((d - ed).days) == 1:
                tags.append(label)
                break
    return ", ".join(tags) if tags else "None"

z20 = sdr.rolling_zscore(daily_total, window=20)
spikes_df = pd.DataFrame({
    "dv01": daily_total,
    "z_score_20d": z20,
}).dropna()
spikes_df["is_spike"] = spikes_df["z_score_20d"].abs() > 2
spikes_df["event_context"] = spikes_df.index.map(classify_spike)

spike_days = spikes_df[spikes_df["is_spike"]].sort_values("z_score_20d", ascending=False)
print(f"Volume spike days (|Z| > 2): {len(spike_days)}")
print(spike_days[["dv01", "z_score_20d", "event_context"]].head(15))
