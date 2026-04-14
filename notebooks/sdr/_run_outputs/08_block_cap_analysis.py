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

# Include pre/post Oct 2024 recalibration for regime analysis
START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH
RECALIBRATION_DATE = datetime.date(2024, 10, 1)

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)
print(f"Loaded {len(df):,} new-risk trades")

blocks = sdr.filter_blocks(df)
non_blocks = df[~df.index.isin(blocks.index)]

_n_total = max(len(df), 1)
_df_dv01 = max(df['dv01'].sum(), 1)
print(f"Block trades: {len(blocks):,} ({len(blocks)/_n_total*100:.1f}%)")
print(f"  Block DV01: {sdr.format_dv01(blocks['dv01'].sum())} ({blocks['dv01'].sum()/_df_dv01*100:.1f}%)")
print(f"Non-block trades: {len(non_blocks):,}")

capped = sdr.filter_capped(df)
_df_n = max(len(df), 1)
print(f"Capped notional trades: {len(capped):,} ({len(capped)/_df_n*100:.1f}%)")
print(f"  Capped DV01: {sdr.format_dv01(capped['dv01'].sum())}")

# Daily capped percentage
capped_daily = capped.groupby("execution_date").size()
total_daily = df.groupby("execution_date").size()
capped_pct = (capped_daily / total_daily * 100).fillna(0)
capped_pct.index = pd.to_datetime(capped_pct.index)

fig, ax = plt.subplots(figsize=(14, 4))
ax.bar(capped_pct.index, capped_pct.values, alpha=0.6, color="#E45756")
ax.axvline(pd.Timestamp(RECALIBRATION_DATE), color="black", linestyle="--", linewidth=2, label="Oct 2024 Recalibration")
ax.set_title("Daily % of Trades with Capped Notional")
ax.set_ylabel("Capped %")
ax.legend()
plt.tight_layout()
plt.show()

if not blocks.empty:
    for tenor in ["5Y", "10Y", "30Y"]:
        t_blocks = blocks[blocks["tenor_label"] == tenor]
        if len(t_blocks) < 5:
            continue
        
        notionals = pd.to_numeric(t_blocks["notional"], errors="coerce").dropna() / 1e6
        
        fig, ax = plt.subplots(figsize=(10, 4))
        notionals.clip(upper=notionals.quantile(0.95)).hist(ax=ax, bins=30, color="#4C78A8", alpha=0.8)
        ax.set_title(f"{tenor} Block Trade Notional Distribution")
        ax.set_xlabel("Notional ($M)")
        ax.set_ylabel("Count")
        plt.tight_layout()
        plt.show()

pre = df[pd.to_datetime(df["execution_date"]) < pd.Timestamp(RECALIBRATION_DATE)]
post = df[pd.to_datetime(df["execution_date"]) >= pd.Timestamp(RECALIBRATION_DATE)]

pre_blocks = sdr.filter_blocks(pre)
post_blocks = sdr.filter_blocks(post)
pre_capped = sdr.filter_capped(pre)
post_capped = sdr.filter_capped(post)

pre_days = pre["execution_date"].nunique()
post_days = post["execution_date"].nunique()

regime = pd.DataFrame({
    "Pre-Oct 2024": {
        "Trading Days": pre_days,
        "Block % (count)": f"{len(pre_blocks)/max(len(pre),1)*100:.1f}%",
        "Block % (DV01)": f"{pre_blocks['dv01'].sum()/max(pre['dv01'].sum(),1)*100:.1f}%",
        "Capped % (count)": f"{len(pre_capped)/max(len(pre),1)*100:.1f}%",
        "Avg Daily Block Count": f"{len(pre_blocks)/max(pre_days,1):.0f}",
    },
    "Post-Oct 2024": {
        "Trading Days": post_days,
        "Block % (count)": f"{len(post_blocks)/max(len(post),1)*100:.1f}%",
        "Block % (DV01)": f"{post_blocks['dv01'].sum()/max(post['dv01'].sum(),1)*100:.1f}%",
        "Capped % (count)": f"{len(post_capped)/max(len(post),1)*100:.1f}%",
        "Avg Daily Block Count": f"{len(post_blocks)/max(post_days,1):.0f}",
    },
})
print(regime.T)

UPLIFT_FACTOR = 1.30

block_notional = blocks.groupby("execution_date")["notional"].sum()
adjusted_block_notional = block_notional * UPLIFT_FACTOR
uplift = adjusted_block_notional - block_notional

non_block_notional = non_blocks.groupby("execution_date")["notional"].sum()
total_reported = block_notional + non_block_notional
total_adjusted = adjusted_block_notional + non_block_notional

combined = pd.DataFrame({
    "Reported": total_reported,
    "Adjusted (+30% blocks)": total_adjusted,
}).sort_index() / 1e9  # billions
combined.index = pd.to_datetime(combined.index)

fig, ax = plt.subplots(figsize=(14, 5))
combined.plot(ax=ax, alpha=0.6)
ax.set_title("Reported vs Adjusted Notional (30% Block Uplift)")
ax.set_ylabel("Notional ($B)")
plt.tight_layout()
plt.show()

total_uplift = uplift.sum()
print(f"Total block uplift: ${total_uplift/1e9:.1f}B additional notional estimated")
