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

if "cleared" in df.columns:
    # SDR 'Cleared' field values: 'C' = cleared, 'U' = uncleared, 'I' = intent-to-clear
    cleared = df[df["cleared"].astype(str).str.upper().isin(["C", "I"])].copy()
    
    # CCP inference from platform identifier
    # CME platforms contain "CME" or known codes; LCH is default for cleared USD swaps
    def infer_ccp(row):
        platform = str(row.get("platform_identifier", "")).upper()
        if "CME" in platform:
            return "CME"
        return "LCH"  # Default for USD cleared swaps
    
    cleared["ccp"] = cleared.apply(infer_ccp, axis=1)
    
    ccp_summary = cleared.groupby("ccp").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
    )
    _ccp_total = max(ccp_summary["total_dv01"].sum(), 1)
    ccp_summary["share_pct"] = ccp_summary["total_dv01"] / _ccp_total * 100
    print("CCP Market Share:")
    print(ccp_summary.round(1).to_string())
else:
    print("cleared column not available.")
    cleared = df.copy()
    cleared["ccp"] = "UNKNOWN"

ccp_pivot = sdr.daily_dv01_by_group(cleared, "ccp")
if not ccp_pivot.empty:
    sdr.plot_stacked_area(ccp_pivot, "Daily DV01 by CCP")
    plt.show()
else:
    print("No CCP data available for plotting.")

# CME share over time
if "CME" in ccp_pivot.columns:
    cme_share = ccp_pivot["CME"] / ccp_pivot.sum(axis=1).clip(lower=1) * 100
    cme_share.index = pd.to_datetime(cme_share.index)
    
    fig, ax = plt.subplots(figsize=(14, 4))
    ma = cme_share.rolling(20, min_periods=3).mean()
    ax.plot(ma.index, ma.values, color="#F58518", linewidth=2)
    ax.fill_between(ma.index, ma.values, alpha=0.2, color="#F58518")
    ax.set_title("CME Market Share (20d Rolling Avg)")
    ax.set_ylabel("CME %")
    plt.tight_layout()
    plt.show()

# For each benchmark tenor, compare rates between CCP pools on the same day
cleared_rates = cleared[pd.to_numeric(cleared["fixed_rate"], errors="coerce").notna()].copy()
cleared_rates["fixed_rate"] = pd.to_numeric(cleared_rates["fixed_rate"])

basis_estimates = []
for tenor in sdr.BENCHMARK_TENORS:
    for date in cleared_rates["execution_date"].unique():
        day_tenor = cleared_rates[(cleared_rates["execution_date"] == date) & (cleared_rates["tenor_label"] == tenor)]
        cme = day_tenor[day_tenor["ccp"] == "CME"]["fixed_rate"]
        lch = day_tenor[day_tenor["ccp"] == "LCH"]["fixed_rate"]
        
        if len(cme) >= 2 and len(lch) >= 5:
            basis_bps = (cme.median() - lch.median()) * 10_000
            basis_estimates.append({
                "date": date, "tenor": tenor, "basis_bps": basis_bps,
            })

if basis_estimates:
    basis_df = pd.DataFrame(basis_estimates)
    basis_pivot = basis_df.pivot_table(index="date", columns="tenor", values="basis_bps")
    basis_pivot.index = pd.to_datetime(basis_pivot.index)
    
    fig, ax = plt.subplots(figsize=(14, 5))
    for tenor in ["10Y", "30Y"]:
        if tenor in basis_pivot.columns:
            ma = basis_pivot[tenor].rolling(10, min_periods=3).mean()
            ax.plot(ma.index, ma.values, label=tenor, linewidth=1.5)
    ax.axhline(0, color="black", linestyle="-", alpha=0.3)
    ax.set_title("Estimated CME-LCH Basis (bps, 10d rolling)")
    ax.set_ylabel("Basis (bps)")
    ax.legend()
    plt.tight_layout()
    plt.show()
else:
    print("Insufficient data for basis estimation (need CME and LCH trades at same tenor/date).")

# CCP switch = offsetting trades (same notional, same tenor, opposite direction)
# at different CCPs within a short time window
# This is a simplified heuristic - real implementation would need more fields

print("CCP switch detection requires directional information (pay/receive)")
print("which is not directly available in CFTC SDR data.")
print("Alternative: look for same-day, same-tenor, same-notional pairs across CCPs.")

if "CME" in cleared["ccp"].values and "LCH" in cleared["ccp"].values:
    for tenor in ["10Y", "30Y"]:
        t = cleared[cleared["tenor_label"] == tenor]
        daily_cme = t[t["ccp"] == "CME"].groupby("execution_date").size()
        daily_lch = t[t["ccp"] == "LCH"].groupby("execution_date").size()
        both_days = daily_cme.index.intersection(daily_lch.index)
        print(f"\n{tenor}: {len(both_days)} days with both CME and LCH trades")
