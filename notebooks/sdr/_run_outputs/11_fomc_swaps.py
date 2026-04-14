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
import matplotlib.dates as mdates
import seaborn as sns

import _usd_swaps_common as sdr

sdr.notebook_setup()

# --- Parameters ---
START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
CACHE_PATH = sdr.DEFAULT_CACHE_PATH
CURVE_NAME = "USD-SOFR-1D"  # FOMC schedule lookup key (shared by both curves)
SOFR_CURVE_NAME = "USD-SOFR-1D-Q12xM12STIRT"
OIS_CURVE_NAME = "USD-OIS-Q12xM12STIRT-SERFFX-MIX23"

# Dynamic overnight fixing rates from NY Fed API
CURRENT_SOFR = sdr.get_current_fixing("USD-SOFR-1D")
CURRENT_EFFR = sdr.get_current_fixing("USD-OIS")
print(f"Current SOFR: {CURRENT_SOFR*100:.4f}%")
print(f"Current EFFR: {CURRENT_EFFR*100:.4f}%")
print(f"SOFR-EFFR spread: {(CURRENT_SOFR - CURRENT_EFFR)*10000:.1f}bp")

from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

# Each entry: label -> (effective_date, maturity_date)
# effective_date = FOMC meeting date, maturity_date = next FOMC meeting date
fomc_schedule_raw = _CENTRAL_BANK_DATES.get("USD-SOFR-1D", {})

# Build clean schedule DataFrame
fomc_meetings = []
for label, (eff, mat) in sorted(fomc_schedule_raw.items(), key=lambda x: x[1][0]):
    fomc_meetings.append({
        "meeting_label": label,
        "effective_date": eff,
        "maturity_date": mat,
        "period_days": (mat - eff).days,
    })

fomc_df = pd.DataFrame(fomc_meetings)
fomc_df["effective_date"] = pd.to_datetime(fomc_df["effective_date"])
fomc_df["maturity_date"] = pd.to_datetime(fomc_df["maturity_date"])

# Filter to analysis window with some lookahead
schedule_start = pd.Timestamp(START).tz_localize(None) - pd.Timedelta(days=90)
schedule_end = pd.Timestamp(END).tz_localize(None) + pd.Timedelta(days=365)
fomc_df = fomc_df[
    (fomc_df["effective_date"] >= schedule_start) &
    (fomc_df["effective_date"] <= schedule_end)
].reset_index(drop=True)

# Build lookup: effective_date -> meeting_label
eff_to_label = dict(zip(fomc_df["effective_date"].dt.date, fomc_df["meeting_label"]))
mat_to_label = dict(zip(fomc_df["maturity_date"].dt.date, fomc_df["meeting_label"]))

print(f"FOMC meetings in window: {len(fomc_df)}")
print(fomc_df.head(15))

df = sdr.load_usd_swaps(START, END, cache_path=CACHE_PATH)
df = sdr.filter_new_risk(df)

# Filter to FOMC-dated trades
if df.empty:
    print("WARNING: No SDR trade data available. Part 1 (flow analytics) will be skipped.")
    print("Part 2 (curve-based implied rates) will still run.")
    fomc_trades = pd.DataFrame()
else:
    fomc_trades = df[df["special_tenor_type"].astype(str) == "FOMC"].copy()

# Assign meeting_label based on expiration_date matching a meeting maturity
# FOMC swaps expire on the next meeting date (maturity of the meeting period)
def assign_meeting_label(row):
    exp = pd.to_datetime(row.get("expiration_date"))
    eff = pd.to_datetime(row.get("effective_date"))
    if pd.notna(exp):
        exp_date = exp.date() if hasattr(exp, "date") else exp
        # Check if expiration matches any meeting's maturity (= swap covers that meeting period)
        label = mat_to_label.get(exp_date)
        if label:
            return label
    if pd.notna(eff):
        eff_date = eff.date() if hasattr(eff, "date") else eff
        label = eff_to_label.get(eff_date)
        if label:
            return label
    return "UNKNOWN"

if not fomc_trades.empty:
    fomc_trades["meeting_label"] = fomc_trades.apply(assign_meeting_label, axis=1)
    fomc_trades = fomc_trades[fomc_trades["meeting_label"] != "UNKNOWN"]

    # Merge in meeting schedule info
    fomc_trades = fomc_trades.merge(
        fomc_df[["meeting_label", "effective_date", "maturity_date", "period_days"]].rename(
            columns={"effective_date": "meeting_eff", "maturity_date": "meeting_mat"}
        ),
        on="meeting_label",
        how="left",
    )

n_total = len(df)
print(f"Total new-risk trades: {n_total:,}")
print(f"FOMC-dated trades: {len(fomc_trades):,} ({len(fomc_trades)/max(n_total,1)*100:.2f}%)")
if not fomc_trades.empty:
    print(f"Unique meetings traded: {fomc_trades['meeting_label'].nunique()}")
    print(f"DV01: {sdr.format_dv01(fomc_trades['dv01'].sum())}")

if not fomc_trades.empty:
    meeting_dv01 = fomc_trades.groupby("meeting_label").agg(
        trade_count=("dv01", "size"),
        total_dv01=("dv01", "sum"),
        total_notional=("notional", "sum"),
        avg_rate=("fixed_rate", lambda x: pd.to_numeric(x, errors="coerce").mean()),
    ).sort_index()
    
    # Sort by meeting date order
    label_order = fomc_df["meeting_label"].tolist()
    meeting_dv01 = meeting_dv01.reindex([l for l in label_order if l in meeting_dv01.index])
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    # DV01 by meeting
    axes[0].bar(range(len(meeting_dv01)), meeting_dv01["total_dv01"], color="#4C78A8", alpha=0.8)
    axes[0].set_ylabel("DV01 ($)")
    axes[0].set_title("DV01 by FOMC Meeting")
    
    # Trade count by meeting
    axes[1].bar(range(len(meeting_dv01)), meeting_dv01["trade_count"], color="#F58518", alpha=0.8)
    axes[1].set_ylabel("Trade Count")
    axes[1].set_xticks(range(len(meeting_dv01)))
    axes[1].set_xticklabels(meeting_dv01.index, rotation=45, ha="right")
    
    plt.tight_layout()
    plt.show()
    
    print("\nVolume by Meeting:")
    print(meeting_dv01.round(2))
else:
    print("Skipped: no FOMC-dated trades in SDR data.")

if not fomc_trades.empty:
    fomc_daily = fomc_trades.groupby("execution_date")["dv01"].sum()
    fomc_daily.index = pd.to_datetime(fomc_daily.index)
    
    # Meeting dates as vertical lines
    fomc_eff_dates = fomc_df["effective_date"].tolist()
    
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(fomc_daily.index, fomc_daily.values, alpha=0.6, color="#4C78A8", width=1)
    
    for fd in fomc_eff_dates:
        if pd.Timestamp(START).tz_localize(None) <= fd <= pd.Timestamp(END).tz_localize(None):
            ax.axvline(fd, color="red", linestyle="--", alpha=0.4, linewidth=0.8)
    
    ax.set_title("Daily FOMC-Dated Swap DV01 (red lines = FOMC meetings)")
    ax.set_ylabel("DV01 ($)")
    plt.tight_layout()
    plt.show()
else:
    print("Skipped: no FOMC-dated trades in SDR data.")

if not fomc_trades.empty:
    # Split by proximity: next 1-3 meetings vs 4+ meetings from trade date
    def meetings_ahead(row):
        exec_date = pd.to_datetime(row["execution_timestamp"]).date()
        meeting_eff = row["meeting_eff"]
        if pd.isna(meeting_eff):
            return 99
        meeting_date = meeting_eff.date() if hasattr(meeting_eff, "date") else meeting_eff
        # Count how many meetings are between exec_date and meeting_date
        upcoming = [m for m in fomc_df["effective_date"].dt.date if m >= exec_date]
        try:
            rank = sorted(upcoming).index(meeting_date) + 1
        except ValueError:
            rank = 99
        return rank
    
    fomc_trades["meetings_ahead"] = fomc_trades.apply(meetings_ahead, axis=1)
    fomc_trades["proximity"] = fomc_trades["meetings_ahead"].apply(
        lambda x: "Near (1-3)" if x <= 3 else ("Mid (4-6)" if x <= 6 else "Far (7+)")
    )
    
    prox_dv01 = fomc_trades.groupby("proximity")["dv01"].sum()
    fig, ax = plt.subplots(figsize=(8, 5))
    prox_dv01.plot.pie(ax=ax, autopct="%1.1f%%", colors=["#4C78A8", "#F58518", "#E45756"], startangle=90)
    ax.set_ylabel("")
    ax.set_title("FOMC Swap DV01: Near vs Mid vs Far Meetings")
    plt.tight_layout()
    plt.show()
else:
    print("Skipped: no FOMC-dated trades in SDR data.")

if not fomc_trades.empty:
    all_daily = df.groupby("execution_date")["dv01"].sum()
    all_daily.index = pd.to_datetime(all_daily.index)
    
    def meeting_window_profile(meeting_dates, window=10):
        """Average FOMC-dated DV01 in T-window..T+2 around meetings."""
        profiles = []
        for md in meeting_dates:
            md_ts = pd.Timestamp(md)
            for offset in range(-window, 3):
                target = md_ts + pd.Timedelta(days=offset)
                # Find the fomc-dated trades on this date for THIS meeting's label
                label = eff_to_label.get(md.date() if hasattr(md, "date") else md)
                if label is None:
                    continue
                day_trades = fomc_trades[
                    (pd.to_datetime(fomc_trades["execution_date"]) == target) &
                    (fomc_trades["meeting_label"] == label)
                ]
                val = day_trades["dv01"].sum() if not day_trades.empty else 0
                profiles.append({"offset": offset, "dv01": val, "meeting": label})
        
        if not profiles:
            return pd.Series(dtype=float)
        return pd.DataFrame(profiles).groupby("offset")["dv01"].mean()
    
    # Meetings within our trade data window
    meetings_in_range = fomc_df[
        (fomc_df["effective_date"] >= pd.Timestamp(START).tz_localize(None)) &
        (fomc_df["effective_date"] <= pd.Timestamp(END).tz_localize(None))
    ]["effective_date"]
    
    avg_profile = meeting_window_profile(meetings_in_range.tolist())
    
    if not avg_profile.empty:
        fig, ax = plt.subplots(figsize=(12, 5))
        colors = ["#E45756" if x == 0 else "#4C78A8" for x in avg_profile.index]
        ax.bar(avg_profile.index, avg_profile.values, color=colors, alpha=0.8)
        ax.axvline(0, color="red", linestyle="--", alpha=0.5, linewidth=2)
        ax.set_title(f"Average FOMC-Swap DV01 Around Meeting Dates (n={len(meetings_in_range)})")
        ax.set_xlabel("Business Days from FOMC Meeting")
        ax.set_ylabel("Avg DV01 ($)")
        plt.tight_layout()
        plt.show()
else:
    print("Skipped: no FOMC-dated trades in SDR data.")

if not fomc_trades.empty:
    # Compare FOMC vs non-FOMC swaps
    non_fomc = df[df["special_tenor_type"].astype(str) != "FOMC"]
    
    print("FOMC vs Non-FOMC Swap Characteristics:")
    print(f"  FOMC avg notional: ${fomc_trades['notional'].mean()/1e6:.1f}M")
    print(f"  Non-FOMC avg notional: ${non_fomc['notional'].mean()/1e6:.1f}M")
    print(f"  FOMC median notional: ${fomc_trades['notional'].median()/1e6:.1f}M")
    print(f"  Non-FOMC median notional: ${non_fomc['notional'].median()/1e6:.1f}M")
    
    # Package analysis
    pkg_dist = fomc_trades["package_type"].fillna("OUTRIGHT").value_counts()
    print(f"\nFOMC trade package types:")
    for pkg, count in pkg_dist.items():
        print(f"  {pkg}: {count} ({count/len(fomc_trades)*100:.1f}%)")
    
    # Block analysis
    if "block_trade_election_indicator" in fomc_trades.columns:
        blocks = fomc_trades[fomc_trades["block_trade_election_indicator"] == True]
        print(f"\nBlock trades: {len(blocks)} ({len(blocks)/len(fomc_trades)*100:.1f}%)")
    
    # FOMC curve detection (consecutive meeting trades at same timestamp)
    fomc_sorted = fomc_trades.sort_values("execution_timestamp")
    fomc_sorted["exec_ts_round"] = pd.to_datetime(fomc_sorted["execution_timestamp"]).dt.round("60s")
    
    potential_curves = fomc_sorted.groupby("exec_ts_round").filter(
        lambda g: g["meeting_label"].nunique() >= 2
    )
    n_curve_legs = len(potential_curves)
    print(f"\nPotential FOMC curve legs (2+ meetings within 60s): {n_curve_legs} trades")
else:
    print("Skipped: no FOMC-dated trades in SDR data.")

if not fomc_trades.empty:
    # SDR VWAP: volume-weighted average fixed rate per meeting
    fomc_rates = fomc_trades[pd.to_numeric(fomc_trades["fixed_rate"], errors="coerce").notna()].copy()
    fomc_rates["fixed_rate"] = pd.to_numeric(fomc_rates["fixed_rate"])
    
    sdr_implied = fomc_rates.groupby("meeting_label").apply(
        lambda g: sdr.vwap(g, rate_col="fixed_rate", weight_col="dv01")
    ).rename("sdr_implied_rate")
    
    # Also compute the most recent day's VWAP per meeting
    recent_date = fomc_rates["execution_date"].max()
    recent_trades = fomc_rates[fomc_rates["execution_date"] == recent_date]
    sdr_latest = recent_trades.groupby("meeting_label").apply(
        lambda g: sdr.vwap(g, rate_col="fixed_rate", weight_col="dv01")
    ).rename("sdr_latest_rate")
    
    print(f"SDR implied rates extracted for {len(sdr_implied)} meetings")
    print(f"Latest trading date: {recent_date}")
else:
    sdr_implied = pd.Series(dtype=float, name="sdr_implied_rate")
    sdr_latest = pd.Series(dtype=float, name="sdr_latest_rate")
    recent_date = None
    print("No SDR trade data available for VWAP calculation.")

# Build both SOFR and OIS short-end curves (BARCHART_STIRF)
curves = sdr.build_fomc_curves(
    sofr_curve_name=SOFR_CURVE_NAME,
    ois_curve_name=OIS_CURVE_NAME,
)
print(f"Pricing date: {curves['pricing_date']}")

# Price each upcoming meeting on both curves
curve_rates_df = sdr.price_fomc_meetings(fomc_df, curves, schedule_key=CURVE_NAME)

sofr_n = curve_rates_df["sofr_implied_rate"].notna().sum()
ois_n = curve_rates_df["ois_implied_rate"].notna().sum()
print(f"SOFR-implied rates: {sofr_n} meetings")
print(f"OIS-implied rates:  {ois_n} meetings")

# Merge all implied rates into meeting schedule
implied_df = fomc_df[["meeting_label", "effective_date", "maturity_date", "period_days"]].copy()

# SDR VWAP rates (may be empty if no trade data)
if not sdr_implied.empty:
    sdr_df = sdr_implied.reset_index()
    sdr_df.columns = ["meeting_label", "sdr_implied_rate"]
    implied_df = implied_df.merge(sdr_df, on="meeting_label", how="left")
else:
    implied_df["sdr_implied_rate"] = np.nan

if not sdr_latest.empty:
    latest_df = sdr_latest.reset_index()
    latest_df.columns = ["meeting_label", "sdr_latest_rate"]
    implied_df = implied_df.merge(latest_df, on="meeting_label", how="left")
else:
    implied_df["sdr_latest_rate"] = np.nan

# Curve-implied rates (SOFR and OIS)
if not curve_rates_df.empty:
    implied_df = implied_df.merge(
        curve_rates_df[["meeting_label", "sofr_implied_rate", "ois_implied_rate"]],
        on="meeting_label", how="left",
    )
else:
    implied_df["sofr_implied_rate"] = np.nan
    implied_df["ois_implied_rate"] = np.nan

# Implied moves from respective current fixings
implied_df["sofr_move_bps"] = (implied_df["sofr_implied_rate"] - CURRENT_SOFR) * 10_000
implied_df["ois_move_bps"] = (implied_df["ois_implied_rate"] - CURRENT_EFFR) * 10_000

# SOFR-OIS basis at each meeting
implied_df["sofr_ois_basis_bps"] = (implied_df["sofr_implied_rate"] - implied_df["ois_implied_rate"]) * 10_000

# Best implied: prefer SOFR, fall back to OIS, then SDR
implied_df["best_implied"] = implied_df["sofr_implied_rate"].fillna(
    implied_df["ois_implied_rate"]
).fillna(implied_df["sdr_implied_rate"])

implied_df["implied_move_bps"] = (implied_df["best_implied"] - CURRENT_SOFR) * 10_000

# Filter to meetings with at least one data point
implied_df = implied_df[
    implied_df["sofr_implied_rate"].notna() | implied_df["ois_implied_rate"].notna() | implied_df["sdr_implied_rate"].notna()
].reset_index(drop=True)

# Display table
display_df = implied_df.copy()
for col in ["sdr_implied_rate", "sofr_implied_rate", "ois_implied_rate"]:
    if col in display_df.columns:
        display_df[col] = display_df[col].apply(lambda x: f"{x*100:.3f}%" if pd.notna(x) else "N/A")
display_df["sofr_move_bps"] = display_df["sofr_move_bps"].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "N/A")
display_df["ois_move_bps"] = display_df["ois_move_bps"].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "N/A")
display_df["sofr_ois_basis_bps"] = display_df["sofr_ois_basis_bps"].apply(lambda x: f"{x:+.1f}" if pd.notna(x) else "N/A")

print(f"Meeting-by-Meeting Implied Rates (SOFR: {CURRENT_SOFR*100:.2f}%, EFFR: {CURRENT_EFFR*100:.2f}%)")
print(display_df[["meeting_label", "effective_date", "period_days",
                     "sofr_implied_rate", "ois_implied_rate", "sofr_move_bps", "ois_move_bps", "sofr_ois_basis_bps"]])

BP25 = 0.0025  # 25 basis points

# Cut probabilities from each curve
implied_df["p_cut_sofr"] = ((CURRENT_SOFR - implied_df["sofr_implied_rate"]) / BP25 * 100).clip(-50, 200)
implied_df["p_cut_ois"] = ((CURRENT_EFFR - implied_df["ois_implied_rate"]) / BP25 * 100).clip(-50, 200)
implied_df["cumulative_cuts_sofr"] = (CURRENT_SOFR - implied_df["sofr_implied_rate"]) / BP25
implied_df["cumulative_cuts_ois"] = (CURRENT_EFFR - implied_df["ois_implied_rate"]) / BP25

fig, axes = plt.subplots(2, 1, figsize=(14, 10))

# Panel 1: Cut probability per meeting (grouped bars)
x = np.arange(len(implied_df))
w = 0.35
sofr_vals = implied_df["p_cut_sofr"].fillna(0)
ois_vals = implied_df["p_cut_ois"].fillna(0)
axes[0].bar(x - w/2, sofr_vals, w, color="#4C78A8", alpha=0.8, label="SOFR")
axes[0].bar(x + w/2, ois_vals, w, color="#F58518", alpha=0.8, label="OIS (FF)")
axes[0].axhline(50, color="black", linestyle="--", alpha=0.3, label="50%")
axes[0].axhline(100, color="red", linestyle="--", alpha=0.3, label="100%")
axes[0].set_xticks(x)
axes[0].set_xticklabels(implied_df["meeting_label"], rotation=45, ha="right")
axes[0].set_ylabel("Probability (%)")
axes[0].set_title("Implied Probability of 25bp Cut: SOFR vs OIS")
axes[0].legend()

# Panel 2: Cumulative cuts (dual lines)
axes[1].plot(x, implied_df["cumulative_cuts_sofr"], marker="o", color="#4C78A8",
             linewidth=2, markersize=6, label="SOFR")
axes[1].plot(x, implied_df["cumulative_cuts_ois"], marker="s", color="#F58518",
             linewidth=2, markersize=6, label="OIS (FF)")
axes[1].axhline(0, color="black", linewidth=0.5)
axes[1].fill_between(x, implied_df["cumulative_cuts_sofr"], alpha=0.15, color="#4C78A8")
axes[1].fill_between(x, implied_df["cumulative_cuts_ois"], alpha=0.15, color="#F58518")
axes[1].set_xticks(x)
axes[1].set_xticklabels(implied_df["meeting_label"], rotation=45, ha="right")
axes[1].set_ylabel("Cumulative 25bp Cuts")
axes[1].set_title("Cumulative Implied Easing: SOFR vs OIS")
axes[1].legend()

plt.tight_layout()
plt.show()

sofr_total = implied_df["cumulative_cuts_sofr"].iloc[-1] if len(implied_df) > 0 else 0
ois_total = implied_df["cumulative_cuts_ois"].iloc[-1] if len(implied_df) > 0 else 0
through = implied_df["meeting_label"].iloc[-1] if len(implied_df) > 0 else "N/A"
print(f"Total SOFR-implied easing through {through}: {sofr_total:.1f} cuts ({sofr_total*25:.0f}bp)")
print(f"Total OIS-implied easing through {through}: {ois_total:.1f} cuts ({ois_total*25:.0f}bp)")

fig, ax = plt.subplots(figsize=(14, 6))

meeting_dates = implied_df["effective_date"]

# SOFR curve
sofr_rates = implied_df["sofr_implied_rate"] * 100
ax.plot(meeting_dates, sofr_rates, marker="o", color="#4C78A8", linewidth=2,
        markersize=8, label="SOFR Curve", zorder=3)

# OIS curve
ois_rates = implied_df["ois_implied_rate"] * 100
ax.plot(meeting_dates, ois_rates, marker="s", color="#F58518", linewidth=2,
        markersize=7, label="OIS (FF) Curve", zorder=3)

# Reference lines
ax.axhline(CURRENT_SOFR * 100, color="#4C78A8", linestyle="--", alpha=0.4,
           linewidth=1.5, label=f"Current SOFR ({CURRENT_SOFR*100:.2f}%)")
ax.axhline(CURRENT_EFFR * 100, color="#F58518", linestyle="--", alpha=0.4,
           linewidth=1.5, label=f"Current EFFR ({CURRENT_EFFR*100:.2f}%)")

# Annotate meeting labels on SOFR curve
for _, row in implied_df.iterrows():
    if pd.notna(row["sofr_implied_rate"]):
        ax.annotate(
            row["meeting_label"],
            (row["effective_date"], row["sofr_implied_rate"] * 100),
            textcoords="offset points", xytext=(0, 12),
            fontsize=8, ha="center", color="#333",
        )

ax.set_title("FOMC Curve: SOFR vs OIS (Fed Funds) Implied Rates")
ax.set_ylabel("Implied Rate (%)")
ax.set_xlabel("Meeting Date")
ax.legend()
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
plt.xticks(rotation=45)
plt.tight_layout()
plt.show()

# Historical FOMC curves for comparison (1 week ago, 1 month ago)
# Uses BARCHART_STIRF dual-curve infrastructure
comparison_dates = {
    "1 week ago": datetime.date.today() - datetime.timedelta(days=7),
    "1 month ago": datetime.date.today() - datetime.timedelta(days=30),
}

historical_curves = {}
for label, as_of in comparison_dates.items():
    try:
        hist_curves = sdr.build_fomc_curves(
            pricing_date=as_of,
            sofr_curve_name=SOFR_CURVE_NAME,
            ois_curve_name=OIS_CURVE_NAME,
        )
        hist_rates = sdr.price_fomc_meetings(fomc_df, hist_curves, schedule_key=CURVE_NAME)
        if not hist_rates.empty:
            historical_curves[label] = hist_rates
    except Exception as e:
        print(f"Failed to load {label}: {e}")

if historical_curves:
    fig, ax = plt.subplots(figsize=(14, 6))

    meeting_dates = implied_df["effective_date"]
    sofr_rates = implied_df["sofr_implied_rate"] * 100
    ax.plot(meeting_dates, sofr_rates, marker="o", color="#4C78A8", linewidth=2,
            markersize=8, label="Current (SOFR)", zorder=3)

    hist_colors = {"1 week ago": "#72B7B2", "1 month ago": "#E45756"}
    for label, hist_df in historical_curves.items():
        hist_meetings = [m for m in implied_df["meeting_label"] if m in hist_df["meeting_label"].values]
        hist_dates = implied_df[implied_df["meeting_label"].isin(hist_meetings)]["effective_date"]
        hist_vals = [hist_df[hist_df["meeting_label"] == m]["sofr_implied_rate"].iloc[0] * 100
                     for m in hist_meetings if not hist_df[hist_df["meeting_label"] == m].empty]
        if hist_vals:
            ax.plot(hist_dates[:len(hist_vals)], hist_vals, marker="s",
                    color=hist_colors.get(label, "#999"),
                    linewidth=1.5, markersize=5, alpha=0.7, linestyle="--", label=f"{label} (SOFR)")

    ax.axhline(CURRENT_SOFR * 100, color="red", linestyle=":", alpha=0.3)
    ax.set_title("FOMC SOFR Curve: Current vs Historical")
    ax.set_ylabel("Implied Rate (%)")
    ax.legend()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %%y"))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

    most_recent_hist = list(historical_curves.values())[0]
    reprice = {}
    for m in implied_df["meeting_label"]:
        curr_rate = implied_df[implied_df["meeting_label"] == m]["sofr_implied_rate"].iloc[0]
        hist_row = most_recent_hist[most_recent_hist["meeting_label"] == m]
        if not hist_row.empty and pd.notna(curr_rate):
            hist_rate = hist_row["sofr_implied_rate"].iloc[0]
            if pd.notna(hist_rate):
                reprice[m] = (curr_rate - hist_rate) * 10_000
    if reprice:
        reprice_s = pd.Series(reprice)
        biggest = reprice_s.abs().idxmax()
        print(f"Largest SOFR repricing vs 1w ago: {biggest} ({reprice_s[biggest]:+.1f}bp)")
else:
    print("Historical curves not available. Skipping comparison.")

# Compute calendar spreads for both curves
spreads = []
for i in range(len(implied_df) - 1):
    curr = implied_df.iloc[i]
    nxt = implied_df.iloc[i + 1]
    rec = {
        "spread_label": f"{curr['meeting_label']} / {nxt['meeting_label']}",
        "front_meeting": curr["meeting_label"],
        "back_meeting": nxt["meeting_label"],
    }
    for prefix, col in [("sofr", "sofr_implied_rate"), ("ois", "ois_implied_rate")]:
        c_rate = curr[col]
        n_rate = nxt[col]
        if pd.notna(c_rate) and pd.notna(n_rate):
            rec[f"{prefix}_spread_bps"] = (n_rate - c_rate) * 10_000
        else:
            rec[f"{prefix}_spread_bps"] = np.nan
    spreads.append(rec)

spread_df = pd.DataFrame(spreads)

if not spread_df.empty:
    fig, ax = plt.subplots(figsize=(14, 6))
    x = np.arange(len(spread_df))
    w = 0.35
    sofr_s = spread_df["sofr_spread_bps"].fillna(0)
    ois_s = spread_df["ois_spread_bps"].fillna(0)
    ax.bar(x - w/2, sofr_s, w, color="#4C78A8", alpha=0.8, label="SOFR")
    ax.bar(x + w/2, ois_s, w, color="#F58518", alpha=0.8, label="OIS (FF)")
    ax.set_xticks(x)
    ax.set_xticklabels(spread_df["spread_label"], rotation=45, ha="right", fontsize=9)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("Spread (bps)")
    ax.set_title("FOMC Calendar Spreads: SOFR vs OIS")
    ax.legend()

    # Annotate SOFR values
    for i, (_, row) in enumerate(spread_df.iterrows()):
        if pd.notna(row["sofr_spread_bps"]):
            ax.annotate(f"{row['sofr_spread_bps']:+.1f}", (i - w/2, row["sofr_spread_bps"]),
                         textcoords="offset points", xytext=(0, 8 if row["sofr_spread_bps"] >= 0 else -15),
                         ha="center", fontsize=7, color="#4C78A8", fontweight="bold")

    plt.tight_layout()
    plt.show()

    print("Calendar Spread Table (bps):")
    print(spread_df[["spread_label", "sofr_spread_bps", "ois_spread_bps"]].round(1))
else:
    print("Insufficient data for calendar spreads.")

print("=" * 70)
print("FOMC-DATED SWAP ANALYTICS SUMMARY")
print("=" * 70)
print(f"Data period: {START.date()} to {END.date()}")
print(f"Current SOFR: {CURRENT_SOFR*100:.4f}%  |  Current EFFR: {CURRENT_EFFR*100:.4f}%  |  Spread: {(CURRENT_SOFR-CURRENT_EFFR)*10000:.1f}bp")
print()

print("--- Flow ---")
n_fomc = len(fomc_trades)
print(f"Total FOMC-dated trades: {n_fomc:,}")
if n_fomc > 0:
    print(f"Total DV01: {sdr.format_dv01(fomc_trades['dv01'].sum())}")
    n_all = max(len(df), 1)
    print(f"Share of all trades: {n_fomc/n_all*100:.2f}%")
    print(f"Meetings with activity: {fomc_trades['meeting_label'].nunique()}")
    if 'meeting_dv01' in dir() and not meeting_dv01.empty:
        top_meeting = meeting_dv01["total_dv01"].idxmax()
        print(f"Busiest meeting: {top_meeting}")
else:
    print("(No SDR trade data available)")
print()

print("--- Implied Rates (Dual-Curve) ---")
if not implied_df.empty:
    next_mtg = implied_df.iloc[0]
    print(f"Next meeting: {next_mtg['meeting_label']}")
    if pd.notna(next_mtg.get("sofr_implied_rate")):
        print(f"  SOFR implied: {next_mtg['sofr_implied_rate']*100:.3f}% ({next_mtg['sofr_move_bps']:+.1f}bp)")
    if pd.notna(next_mtg.get("ois_implied_rate")):
        print(f"  OIS implied:  {next_mtg['ois_implied_rate']*100:.3f}% ({next_mtg['ois_move_bps']:+.1f}bp)")

    sofr_cuts = implied_df["cumulative_cuts_sofr"].iloc[-1] if "cumulative_cuts_sofr" in implied_df else 0
    ois_cuts = implied_df["cumulative_cuts_ois"].iloc[-1] if "cumulative_cuts_ois" in implied_df else 0
    through = implied_df["meeting_label"].iloc[-1]
    print(f"\nCumulative easing through {through}:")
    print(f"  SOFR: {sofr_cuts:.1f} cuts ({sofr_cuts*25:.0f}bp)")
    print(f"  OIS:  {ois_cuts:.1f} cuts ({ois_cuts*25:.0f}bp)")

    basis = implied_df["sofr_ois_basis_bps"].dropna()
    if not basis.empty:
        print(f"\nSOFR-OIS basis range: {basis.min():.1f}bp to {basis.max():.1f}bp")

if 'spread_df' in dir() and not spread_df.empty:
    sofr_dovish = spread_df.loc[spread_df["sofr_spread_bps"].idxmin()] if spread_df["sofr_spread_bps"].notna().any() else None
    if sofr_dovish is not None:
        print(f"\nMost dovish SOFR spread: {sofr_dovish['spread_label']} ({sofr_dovish['sofr_spread_bps']:+.1f}bp)")
print("=" * 70)
