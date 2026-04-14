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
from SDRUtils.analytics.seasonality import (
    add_event_classifications,
    analyze_seasonality_by_event,
    get_fomc_dates,
    get_imm_dates,
    get_month_end_dates,
    get_quarter_end_dates,
)

sdr.notebook_setup()

START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades across {df['execution_date'].nunique()} days")

fomc = get_fomc_dates()
fomc_in_range = [d for d in fomc if START.date() <= d <= END.date()]
qe = get_quarter_end_dates(START.date(), END.date())
me = get_month_end_dates(START.date(), END.date())
imm = get_imm_dates(START.date(), END.date())

print(f"FOMC meetings: {len(fomc_in_range)}")
print(f"Quarter-ends: {len(qe)}")
print(f"Month-ends: {len(me)}")
print(f"IMM rolls: {len(imm)}")

# Add event flags to DataFrame
if not df.empty:
    df_events = add_event_classifications(
        df, include_fomc=True, include_me=True, include_qe=True, days_before=3,
    )
else:
    df_events = df.copy()
    for col in ["is_month_end_window", "is_quarter_end_window", "is_fomc_window", "is_fomc_day"]:
        df_events[col] = False

daily_dv01 = df.groupby("execution_date")["dv01"].sum()
daily_dv01.index = pd.to_datetime(daily_dv01.index)

def event_window_analysis(event_dates, window=5, label="Event"):
    """Analyze volume in T-window..T+window around events."""
    all_windows = []
    for ed in event_dates:
        ed_ts = pd.Timestamp(ed)
        for offset in range(-window, window + 1):
            target = ed_ts + pd.Timedelta(days=offset)
            val = daily_dv01.get(target, np.nan)
            if not np.isnan(val):
                all_windows.append({"offset": offset, "dv01": val, "event_date": ed})
    
    if not all_windows:
        return pd.DataFrame()
    
    wdf = pd.DataFrame(all_windows)
    return wdf.groupby("offset")["dv01"].mean()

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

for ax, (dates, label) in zip(axes.flatten(), [
    (fomc_in_range, "FOMC"),
    (qe, "Quarter-End"),
    (me, "Month-End"),
    (imm, "IMM Roll"),
]):
    avg_profile = event_window_analysis(dates, window=5, label=label)
    if not avg_profile.empty:
        colors = ["#E45756" if x == 0 else "#4C78A8" for x in avg_profile.index]
        ax.bar(avg_profile.index, avg_profile.values, color=colors, alpha=0.8)
        ax.set_title(f"{label} (n={len(dates)} events)")
        ax.set_xlabel("Days from Event")
        ax.set_ylabel("Avg DV01")
        ax.axvline(0, color="red", linestyle="--", alpha=0.5)

plt.suptitle("Average DV01 Around Events (T-5 to T+5)", fontsize=13)
plt.tight_layout()
plt.show()

fomc_day_trades = df_events[df_events["is_fomc_day"] == True]
non_fomc_trades = df_events[df_events["is_fomc_day"] != True]

if not fomc_day_trades.empty:
    fomc_tenor = fomc_day_trades.groupby("tenor_bucket")["dv01"].sum()
    non_fomc_tenor = non_fomc_trades.groupby("tenor_bucket")["dv01"].sum()
    
    # Normalize to per-day averages
    fomc_days = fomc_day_trades["execution_date"].nunique()
    non_fomc_days = non_fomc_trades["execution_date"].nunique()
    
    comparison = pd.DataFrame({
        "FOMC Day": fomc_tenor / max(fomc_days, 1),
        "Non-FOMC": non_fomc_tenor / max(non_fomc_days, 1),
    }).reindex(sdr.TENOR_BUCKET_ORDER).fillna(0)
    
    comparison.plot.bar(figsize=(10, 5), alpha=0.8)
    plt.title("Average Daily DV01 by Tenor Bucket: FOMC vs Non-FOMC Days")
    plt.ylabel("Avg Daily DV01")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

_label_col = "trade_label" if "trade_label" in df_events.columns else "tenor_label"
fomc_season = analyze_seasonality_by_event(
    df_events,
    event_col="is_fomc_window",
    value_col="dv01",
    label_col=_label_col,
    show_progress=True,
)

if not fomc_season.empty:
    top = fomc_season.head(15)
    print("Top 15 trade labels by FOMC/non-FOMC volume ratio:")
    print(top[["trade_label", "event_avg_daily", "non_event_avg_daily", "volume_ratio"]].round(2))

def event_case_study(event_date, label, window_days=5):
    """Full flow analysis for a specific event date."""
    event_ts = pd.Timestamp(event_date)
    start = event_ts - pd.Timedelta(days=window_days)
    end = event_ts + pd.Timedelta(days=window_days)
    
    mask = (pd.to_datetime(df["execution_date"]) >= start) & (pd.to_datetime(df["execution_date"]) <= end)
    window = df[mask]
    
    if window.empty:
        print(f"No data for {label} ({event_date})")
        return
    
    print(f"\n{'='*60}")
    print(f"EVENT: {label} ({event_date})")
    print(f"{'='*60}")
    
    daily = window.groupby("execution_date").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    daily.index = pd.to_datetime(daily.index)
    
    fig, ax = plt.subplots(figsize=(12, 4))
    colors = ["#E45756" if d.date() == event_date else "#4C78A8" for d in daily.index]
    ax.bar(daily.index, daily["total_dv01"], color=colors, alpha=0.8)
    ax.axvline(event_ts, color="red", linestyle="--", linewidth=2)
    ax.set_title(f"{label}: DV01 ({window_days}d Window)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
    
    # Tenor breakdown on event day
    event_day = window[pd.to_datetime(window["execution_date"]) == event_ts]
    if not event_day.empty:
        tenor_dist = event_day.groupby("tenor_bucket")["dv01"].sum()
        print(f"\nEvent-day tenor distribution:")
        for t, v in tenor_dist.items():
            print(f"  {t}: {sdr.format_dv01(v)}")

# Run case studies for events in range
if datetime.date(2024, 11, 5) >= START.date():
    event_case_study(datetime.date(2024, 11, 5), "US Election 2024")

# Pick a recent high-volume date
recent_dates = sorted(df["execution_date"].unique())[-5:]

fig, ax = plt.subplots(figsize=(14, 6))
for date in recent_dates:
    day = df[df["execution_date"] == date].copy()
    day["exec_ts"] = pd.to_datetime(day["execution_timestamp"])
    day = day.sort_values("exec_ts")
    day["cumulative_dv01"] = day["dv01"].cumsum()
    
    # Normalize time to hours from midnight
    day["hour"] = day["exec_ts"].dt.hour + day["exec_ts"].dt.minute / 60
    
    ax.plot(day["hour"], day["cumulative_dv01"], alpha=0.6, linewidth=1, label=str(date))

ax.set_title("Intraday Cumulative DV01 (Recent Trading Days)")
ax.set_xlabel("Hour (UTC)")
ax.set_ylabel("Cumulative DV01 ($)")
ax.legend(fontsize=8)
ax.set_xlim(8, 22)
plt.tight_layout()
plt.show()
