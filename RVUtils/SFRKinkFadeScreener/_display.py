"""Notebook rendering helpers for the kink-fade screener."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from RVUtils.SFRKinkFadeScreener.screener import KinkFadeScreenerSnapshot


def render_dashboard_table(snapshot: KinkFadeScreenerSnapshot) -> pd.DataFrame:
    """Styled DataFrame for notebook display with color coding.

    Green rows = entry eligible, yellow = approaching (|z|>1.5 buy_kink reds),
    gray = inactive. Reds bold, whites/greens dimmed.
    """
    df = snapshot.to_dataframe()
    if df.empty:
        return df

    def _row_style(row):
        r = snapshot.results[row.name] if row.name < len(snapshot.results) else None
        if r is None:
            return [""] * len(row)

        if r.entry_eligible:
            bg = "background-color: #c8e6c9"
        elif (r.direction == "buy_kink" and r.region == "reds"
              and abs(r.zscore) >= 1.5):
            bg = "background-color: #fff9c4"
        else:
            bg = "background-color: #f5f5f5; color: #999"

        return [bg] * len(row)

    return df.style.apply(_row_style, axis=1).format({
        "Level (bp)": "{:+.2f}",
        "Z-Score": "{:+.2f}",
        "Pctile": "{:.2f}",
        "XS Rank": "{:.2f}",
        "Z 1d Chg": "{:+.2f}",
        "Lvl 1d Chg": "{:+.2f}",
    })


def render_strip_chart(snapshot: KinkFadeScreenerSnapshot, ax=None):
    """Strip rates with BF_6M kink markers."""
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(16, 5))

    ranks = sorted(snapshot.strip_rates.keys(), key=lambda k: int(k.replace("SFR", "")))
    x = [int(k.replace("SFR", "")) for k in ranks]
    y = [snapshot.strip_rates[k] for k in ranks]

    ax.plot(x, y, "o-", color="steelblue", linewidth=2, markersize=8, label="Strip Rate")

    for r in snapshot.results:
        parts = r.structure_id.split("/")
        if len(parts) != 3:
            continue
        belly_x = r.belly_rank
        belly_y = snapshot.strip_rates.get(f"SFR{belly_x}", None)
        if belly_y is None:
            continue

        if r.entry_eligible:
            color, marker, size = "green", "^", 14
        elif r.direction == "buy_kink" and r.region == "reds" and abs(r.zscore) >= 1.5:
            color, marker, size = "#FFC107", "^", 12
        elif r.region == "reds":
            color, marker, size = "gray", "o", 6
        else:
            continue

        ax.plot(belly_x, belly_y, marker=marker, color=color, markersize=size,
                zorder=5, markeredgecolor="black", markeredgewidth=0.5)

    ax.axvspan(4.5, 8.5, alpha=0.08, color="blue", label="Reds (SFR5-8)")
    ax.set_xticks(x)
    ax.set_xticklabels(ranks, fontsize=9)
    ax.set_ylabel("Rate (%)")
    ax.set_title(f"SOFR Strip with BF_6M Kink Signals ({snapshot.as_of})", fontweight="bold")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    return ax


def render_zscore_chart(
    snapshot: KinkFadeScreenerSnapshot,
    zscore_history: pd.DataFrame,
    ax=None,
    n_days: int = 120,
):
    """Trailing z-score time series for reds flies with threshold bands."""
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(16, 6))

    reds_cols = [r.structure_id for r in snapshot.results if r.region == "reds"]
    tail = zscore_history[reds_cols].tail(n_days) if reds_cols else pd.DataFrame()

    if tail.empty:
        ax.text(0.5, 0.5, "No reds data", ha="center", va="center", transform=ax.transAxes)
        return ax

    for col in tail.columns:
        ax.plot(tail.index, tail[col], linewidth=1.2, label=col, alpha=0.8)

    ax.axhline(-2.0, color="green", linestyle="--", linewidth=1, alpha=0.5, label="Entry threshold (-2.0)")
    ax.axhline(-1.5, color="#FFC107", linestyle=":", linewidth=1, alpha=0.5, label="Approaching (-1.5)")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.axhline(1.5, color="#FFC107", linestyle=":", linewidth=1, alpha=0.5)
    ax.axhline(2.0, color="red", linestyle="--", linewidth=1, alpha=0.5, label="sell_kink zone (+2.0)")

    ax.set_title(f"Reds BF_6M Z-Scores (trailing {n_days}d)", fontweight="bold")
    ax.set_ylabel("Z-Score")
    ax.legend(fontsize=8, loc="upper left", ncol=2)
    ax.grid(True, alpha=0.3)
    return ax


def render_filter_panel(snapshot: KinkFadeScreenerSnapshot):
    """Print compact filter status."""
    print(f"Date: {snapshot.as_of}")
    fomc_status = f"BLOCKED ({snapshot.days_to_fomc}d)" if snapshot.fomc_blackout_active else f"CLEAR ({snapshot.days_to_fomc}d to next)"
    roll_status = f"BLOCKED ({snapshot.days_to_imm_roll}d)" if snapshot.roll_blackout_active else f"CLEAR ({snapshot.days_to_imm_roll}d to next)"
    print(f"FOMC:     {fomc_status}")
    print(f"IMM Roll: {roll_status}")
    print(f"Actionable: {snapshot.n_actionable} signals")
    if snapshot.run_warnings:
        for w in snapshot.run_warnings:
            print(f"WARNING: {w}")

    cm = snapshot.cm_resolution
    if cm:
        mapping = ", ".join(f"{k}={v}" for k, v in sorted(cm.items(), key=lambda x: int(x[0].replace("SFR", "")))[:12])
        print(f"Contracts: {mapping}")
