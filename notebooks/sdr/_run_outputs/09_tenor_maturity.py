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
from SDRUtils.analytics.seasonality import get_fomc_dates, get_imm_dates

sdr.notebook_setup()

START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")

tenor_dv01 = df.groupby("tenor_label")["dv01"].sum()
ordered_tenors = [t for t in sdr.TENOR_ORDER if t in tenor_dv01.index]
tenor_dv01 = tenor_dv01[ordered_tenors]

fig, ax = plt.subplots(figsize=(14, 6))
tenor_dv01.plot.bar(ax=ax, color="#4C78A8", alpha=0.8)
ax.set_title("Total DV01 by Tenor")
ax.set_ylabel("DV01 ($)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

_tenor_total = tenor_dv01.sum()
print("Top 5 tenors by DV01:")
for tenor, val in tenor_dv01.nlargest(5).items():
    print(f"  {tenor}: {sdr.format_dv01(val)} ({val/max(_tenor_total, 1)*100:.1f}%)")

bucket_pivot = sdr.daily_dv01_by_group(df, "tenor_bucket")
bucket_pivot = bucket_pivot[[c for c in sdr.TENOR_BUCKET_ORDER if c in bucket_pivot.columns]]

if not bucket_pivot.empty:
    bucket_pct = bucket_pivot.div(bucket_pivot.sum(axis=1), axis=0) * 100
    bucket_pct.index = pd.to_datetime(bucket_pct.index)

    # 20-day rolling average for smoother view
    bucket_pct_smooth = bucket_pct.rolling(20, min_periods=5).mean()

    sdr.plot_stacked_area(bucket_pct_smooth, "Tenor Bucket Share Over Time (20d Rolling, %)", ylabel="Share %")
    plt.show()
else:
    print("No tenor bucket data available for plotting.")

df_fwd = df.copy()
df_fwd["fwd_type"] = df_fwd["is_forward"].apply(lambda x: "Forward" if x else "Spot")

fwd_split = df_fwd.groupby(["tenor_label", "fwd_type"])["dv01"].sum().unstack(fill_value=0)
fwd_split = fwd_split.reindex([t for t in sdr.TENOR_ORDER if t in fwd_split.index])

fig, ax = plt.subplots(figsize=(14, 6))
if not fwd_split.empty:
    fwd_split.plot.bar(ax=ax, stacked=True, color=["#4C78A8", "#F58518"], alpha=0.8)
else:
    ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
ax.set_title("DV01 by Tenor: Spot vs Forward-Starting")
ax.set_ylabel("DV01 ($)")
ax.legend(["Spot", "Forward"])
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

_fwd_total = df_fwd["dv01"].sum()
fwd_pct = df_fwd[df_fwd["is_forward"] == True]["dv01"].sum() / max(_fwd_total, 1) * 100 if _fwd_total > 0 else 0
print(f"Forward-starting trades: {fwd_pct:.1f}% of total DV01")

imm_trades = df[df["special_tenor_type"].astype(str) == "IMM"]
if not imm_trades.empty:
    imm_daily = imm_trades.groupby("execution_date")["dv01"].sum()
    imm_daily.index = pd.to_datetime(imm_daily.index)
    
    # Overlay IMM roll dates
    imm_dates = get_imm_dates(START.date(), END.date())
    
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(imm_daily.index, imm_daily.values, alpha=0.6, color="#F58518")
    for imd in imm_dates:
        ax.axvline(pd.Timestamp(imd), color="red", linestyle="--", alpha=0.4, linewidth=0.8)
    ax.set_title("IMM-Dated Swap DV01 (vertical lines = IMM roll dates)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
    
    print(f"IMM trades: {len(imm_trades):,} ({len(imm_trades)/len(df)*100:.1f}%)")
else:
    print("No IMM-dated swaps found in this period.")

fomc_trades = df[df["special_tenor_type"].astype(str) == "FOMC"]
mac_trades = df[df["special_tenor_type"].astype(str) == "MAC"]

print(f"FOMC-dated swaps: {len(fomc_trades):,} ({len(fomc_trades)/len(df)*100:.1f}%)")
print(f"MAC swaps: {len(mac_trades):,} ({len(mac_trades)/len(df)*100:.1f}%)")

# FOMC activity around meeting dates
if not fomc_trades.empty:
    fomc_dates = get_fomc_dates()
    fomc_daily = fomc_trades.groupby("execution_date")["dv01"].sum()
    fomc_daily.index = pd.to_datetime(fomc_daily.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ax.bar(fomc_daily.index, fomc_daily.values, alpha=0.6, color="#E45756")
    for fd in fomc_dates:
        if START.date() <= fd <= END.date():
            ax.axvline(pd.Timestamp(fd), color="blue", linestyle="--", alpha=0.3)
    ax.set_title("FOMC-Dated Swap DV01 (blue lines = FOMC meetings)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()

df_life = df.copy()
df_life["tenor_years_num"] = pd.to_numeric(df_life["tenor_years"], errors="coerce")

if df_life.empty or df_life["tenor_years_num"].notna().sum() == 0:
    daily_avg_life = pd.Series(dtype=float)
else:
    daily_avg_life = df_life.groupby("execution_date").apply(
        lambda g: np.average(
            g["tenor_years_num"].dropna(),
            weights=g.loc[g["tenor_years_num"].notna(), "dv01"].clip(lower=0.01),
        ) if len(g["tenor_years_num"].dropna()) > 0 else np.nan
    )

if daily_avg_life.empty:
    print("No data for average life trend.")
else:
    daily_avg_life.index = pd.to_datetime(daily_avg_life.index)

    fig, ax = plt.subplots(figsize=(14, 5))
    ma = daily_avg_life.rolling(20, min_periods=5).mean()
    ax.plot(ma.index, ma.values, color="#4C78A8", linewidth=2)
    ax.fill_between(ma.index, ma.values, alpha=0.2, color="#4C78A8")
    ax.set_title("DV01-Weighted Average Tenor (20d Rolling)")
    ax.set_ylabel("Average Tenor (Years)")
    plt.tight_layout()
    plt.show()

    print(f"Current avg life (last 20d): {daily_avg_life.tail(20).mean():.1f}Y")
    print(f"Period average: {daily_avg_life.mean():.1f}Y")
