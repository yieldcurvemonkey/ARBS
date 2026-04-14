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
# Focus on new risk with valid rates
trades = sdr.filter_new_risk(df)
trades = trades[pd.to_numeric(trades["fixed_rate"], errors="coerce").notna()].copy()
trades["fixed_rate"] = pd.to_numeric(trades["fixed_rate"], errors="coerce")
print(f"Loaded {len(trades):,} trades with valid fixed rates")

benchmark = trades[trades["tenor_label"].isin(sdr.BENCHMARK_TENORS)].copy()
benchmark["execution_timestamp_dt"] = pd.to_datetime(benchmark["execution_timestamp"])
benchmark = benchmark.sort_values("execution_timestamp_dt")

# Daily price dispersion (std of fixed_rate) per tenor
daily_disp = benchmark.groupby(["execution_date", "tenor_label"])["fixed_rate"].std().reset_index()
daily_disp.columns = ["execution_date", "tenor_label", "price_dispersion_bps"]
daily_disp["price_dispersion_bps"] = daily_disp["price_dispersion_bps"] * 10_000  # convert to bps

disp_pivot = daily_disp.pivot_table(
    index="execution_date", columns="tenor_label", values="price_dispersion_bps",
)
disp_pivot.index = pd.to_datetime(disp_pivot.index)
disp_pivot = disp_pivot[[c for c in sdr.BENCHMARK_TENORS if c in disp_pivot.columns]]

fig, ax = plt.subplots(figsize=(14, 6))
for col in disp_pivot.columns:
    rolling = disp_pivot[col].rolling(5, min_periods=1).mean()
    ax.plot(rolling.index, rolling.values, label=col, linewidth=1.2)
ax.set_title("Price Dispersion by Tenor (5-day Rolling Avg, bps)")
ax.set_ylabel("Std Dev of Fixed Rate (bps)")
ax.legend()
plt.tight_layout()
plt.show()

ticks = {}
for tenor in sdr.BENCHMARK_TENORS:
    tenor_trades = benchmark[benchmark["tenor_label"] == tenor].sort_values("execution_timestamp_dt")
    if len(tenor_trades) < 2:
        continue
    diffs = tenor_trades["fixed_rate"].diff().dropna().abs() * 10_000  # bps
    diffs = diffs[diffs > 0]  # exclude zero ticks
    ticks[tenor] = diffs

fig, axes = plt.subplots(2, 4, figsize=(16, 8))
axes = axes.flatten()
for i, (tenor, tick_data) in enumerate(ticks.items()):
    if i >= len(axes):
        break
    ax = axes[i]
    tick_data.clip(upper=tick_data.quantile(0.95)).hist(ax=ax, bins=50, color="#4C78A8", alpha=0.8)
    ax.axvline(tick_data.median(), color="red", linestyle="--", label=f"Median: {tick_data.median():.2f}bp")
    ax.set_title(f"{tenor} Tick Distribution")
    ax.legend(fontsize=8)
for j in range(len(ticks), len(axes)):
    axes[j].set_visible(False)
plt.suptitle("Tick Size Distribution (bps)", fontsize=13)
plt.tight_layout()
plt.show()

if "platform_identifier" in trades.columns:
    # Common D2D platforms (IDB SEFs)
    D2D_PLATFORMS = {"ICAU", "BGCD", "TLAD", "TRAD", "DWUS", "MARF"}
    
    trades_plat = trades[trades["platform_identifier"].notna()].copy()
    trades_plat["venue_type"] = trades_plat["platform_identifier"].apply(
        lambda x: "D2D" if str(x).upper() in D2D_PLATFORMS else "D2C"
    )
    
    for tenor in ["5Y", "10Y", "30Y"]:
        tenor_df = trades_plat[trades_plat["tenor_label"] == tenor]
        if len(tenor_df) < 10:
            continue
        d2d = tenor_df[tenor_df["venue_type"] == "D2D"]["fixed_rate"]
        d2c = tenor_df[tenor_df["venue_type"] == "D2C"]["fixed_rate"]
        
        daily_d2d_disp = tenor_df[tenor_df["venue_type"] == "D2D"].groupby("execution_date")["fixed_rate"].std() * 10_000
        daily_d2c_disp = tenor_df[tenor_df["venue_type"] == "D2C"].groupby("execution_date")["fixed_rate"].std() * 10_000
        
        print(f"\n{tenor}: D2D median dispersion = {daily_d2d_disp.median():.2f}bp, D2C = {daily_d2c_disp.median():.2f}bp")

if "block_trade_election_indicator" in trades.columns:
    trades_block = trades.copy()
    trades_block["is_block"] = trades_block["block_trade_election_indicator"] == True
    
    for tenor in ["5Y", "10Y", "30Y"]:
        t = trades_block[trades_block["tenor_label"] == tenor]
        blocks = t[t["is_block"]]
        non_blocks = t[~t["is_block"]]
        
        if len(blocks) > 5 and len(non_blocks) > 5:
            block_disp = blocks.groupby("execution_date")["fixed_rate"].std() * 10_000
            nonblock_disp = non_blocks.groupby("execution_date")["fixed_rate"].std() * 10_000
            print(f"{tenor}: Block dispersion={block_disp.median():.2f}bp, Non-block={nonblock_disp.median():.2f}bp")

# Monthly aggregation for cleaner heatmap
benchmark_monthly = benchmark.copy()
benchmark_monthly["month"] = pd.to_datetime(benchmark_monthly["execution_date"]).dt.to_period("M").astype(str)

monthly_disp = benchmark_monthly.groupby(["month", "tenor_label"])["fixed_rate"].std().reset_index()
monthly_disp["dispersion_bps"] = monthly_disp["fixed_rate"] * 10_000

hm_pivot = monthly_disp.pivot_table(index="tenor_label", columns="month", values="dispersion_bps")
hm_pivot = hm_pivot.reindex([t for t in sdr.BENCHMARK_TENORS if t in hm_pivot.index])

if not hm_pivot.empty:
    sdr.plot_heatmap(hm_pivot, "Monthly Price Dispersion by Tenor (bps)", cmap="RdYlGn_r", fmt=".1f")
    plt.show()
else:
    print("No data for liquidity heatmap.")

scores = []
for tenor in sdr.BENCHMARK_TENORS:
    t = trades[trades["tenor_label"] == tenor]
    if len(t) < 10:
        continue
    
    disp = t.groupby("execution_date")["fixed_rate"].std().median() * 10_000
    tick_data = t.sort_values("execution_timestamp")["fixed_rate"].diff().abs() * 10_000
    tick_data = tick_data[tick_data > 0]
    tick_med = tick_data.median() if len(tick_data) > 0 else np.nan
    avg_daily_dv01 = t.groupby("execution_date")["dv01"].sum().median()
    daily_count = t.groupby("execution_date").size().median()
    
    scores.append({
        "tenor": tenor,
        "dispersion_bps": disp,
        "median_tick_bps": tick_med,
        "median_daily_dv01": avg_daily_dv01,
        "median_daily_count": daily_count,
    })

score_df = pd.DataFrame(scores)
if score_df.empty:
    print("Insufficient data for composite liquidity scores.")
else:
    score_df = score_df.set_index("tenor")
    # Normalize each metric to 0-100 (higher = more liquid)
    for col in ["dispersion_bps", "median_tick_bps"]:
        if col in score_df.columns:
            score_df[f"{col}_score"] = 100 * (1 - (score_df[col] - score_df[col].min()) / (score_df[col].max() - score_df[col].min() + 1e-10))
    for col in ["median_daily_dv01", "median_daily_count"]:
        if col in score_df.columns:
            score_df[f"{col}_score"] = 100 * (score_df[col] - score_df[col].min()) / (score_df[col].max() - score_df[col].min() + 1e-10)

    score_cols = [c for c in score_df.columns if c.endswith("_score")]
    score_df["composite_score"] = score_df[score_cols].mean(axis=1)

    print("Composite Liquidity Scores (100 = most liquid):")
    print(score_df.round(1))
