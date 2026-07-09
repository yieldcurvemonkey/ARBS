"""PCA relative-value screener plots (data-agnostic).

Publication-quality charts for PCA-based RV analysis, inspired by:
    CS "PCA Unleashed", ING "Deconstructing EUR yield curve",
    JPM "RV on EUR swap yield curve", SSB "Principles of PCA",
    StanChart "Introducing a relative-value tool for swaps".

All functions accept a wide DataFrame (DatetimeIndex, cols = tenors/structures),
fit PCA internally, and return (fig, ax) or (fig, axes).
"""
from __future__ import annotations

import warnings
from itertools import combinations
from typing import Optional, Sequence, Union

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from RVUtils.pca_rv import make_pca_rv_builder

__all__ = [
    "plot_residual_snapshot",
    "plot_residual_range",
    "plot_pca_vs_actual",
    "plot_fly_scanner",
    "plot_fly_timeseries",
    "plot_loadings",
    "plot_variance_explained",
    "plot_residual_timeseries",
]

_CHEAP_COLOR = "#2ca02c"
_RICH_COLOR = "#d62728"
_NEUTRAL_COLOR = "#888888"


def _build_and_fit(df, *, on="levels", n_factors=3, matrix="cov"):
    builder = make_pca_rv_builder(df, on=on, n_factors=n_factors, matrix=matrix)
    fit_fn, fair_value_fn, residual_fn, fly_weights_fn, curve_weights_fn = builder[:5]
    get_model_fn = builder[-1]
    model = fit_fn()
    return model, fair_value_fn, residual_fn, fly_weights_fn, get_model_fn, fit_fn


def _full_residual_df(df, *, on="levels", n_factors=3, matrix="cov"):
    """Compute per-tenor residual DataFrame (actual - PCA fitted) for all dates."""
    model, fair_value_fn, *_ = _build_and_fit(df, on=on, n_factors=n_factors, matrix=matrix)
    fv = fair_value_fn()
    cols = list(model.columns)
    actual = df[cols].reindex(fv.index)
    return actual - fv


# ============================================================================
# 1. Residual snapshot bar chart (CS "PCA Unleashed" Exhibit 19)
# ============================================================================

def plot_residual_snapshot(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 3,
    zscore_window: int = 60,
    title: str = "PCA Residuals — Current Snapshot",
    figsize: tuple = (14, 5),
) -> tuple:
    """CS 'PCA Unleashed' Exhibit 19 style residual bar chart.

    Bars = current residual per tenor (green = cheap, red = rich).
    Historical markers: square = 1d ago, triangle = 1w, circle = 1m.
    """
    resid_df = _full_residual_df(df, on=on, n_factors=n_factors)
    cols = list(resid_df.columns)
    n_obs = len(resid_df)

    current = resid_df.iloc[-1]
    snap_date = resid_df.index[-1]

    fig, ax = plt.subplots(figsize=figsize)

    x = np.arange(len(cols))
    colors = [_CHEAP_COLOR if v >= 0 else _RICH_COLOR for v in current.values]
    ax.bar(x, current.values, color=colors, alpha=0.85, width=0.6, label="Current", zorder=3)
    ax.axhline(0, color="white", linewidth=0.6, alpha=0.5, zorder=1)

    lookbacks = [
        (-2, "s", "#aaaaaa", "1d ago"),
        (-5, "^", "#cccccc", "1w ago"),
        (-21, "o", "#666666", "1m ago"),
    ]
    for offset, marker, mcolor, label in lookbacks:
        idx = n_obs + offset - 1
        if idx >= 0:
            vals = resid_df.iloc[idx].values
            ax.scatter(x, vals, marker=marker, s=28, color=mcolor,
                       zorder=5, label=label, edgecolors="none")

    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Residual (actual − PCA fair value)")
    date_str = snap_date.strftime("%Y-%m-%d") if hasattr(snap_date, "strftime") else str(snap_date)
    ax.set_title(f"{title}  [{date_str}]", fontsize=11)
    ax.legend(fontsize=8, loc="upper right", framealpha=0.7)
    ax.grid(axis="y", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 2. Residual range chart (ING Fig 1)
# ============================================================================

def plot_residual_range(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 3,
    range_window: int = 756,
    title: str = "PCA Residual Range",
    figsize: tuple = (14, 5),
) -> tuple:
    """ING Fig 1 style whisker chart: historical residual range per tenor + current dot."""
    resid_df = _full_residual_df(df, on=on, n_factors=n_factors)
    tail = resid_df.iloc[-range_window:] if len(resid_df) >= range_window else resid_df
    cols = list(resid_df.columns)
    current = resid_df.iloc[-1]

    stats = pd.DataFrame({
        "min": tail.min(),
        "p5": tail.quantile(0.05),
        "median": tail.median(),
        "p95": tail.quantile(0.95),
        "max": tail.max(),
    })

    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(len(cols))

    for i, col in enumerate(cols):
        row = stats.loc[col]
        ax.plot([i, i], [row["min"], row["max"]], color="#555555", linewidth=1, zorder=2)
        ax.plot([i, i], [row["p5"], row["p95"]], color="#888888", linewidth=4, alpha=0.5, zorder=3)
        ax.scatter(i, row["median"], marker="_", s=60, color="#aaaaaa", zorder=4, linewidths=1.5)

    cur_colors = [_CHEAP_COLOR if v >= 0 else _RICH_COLOR for v in current.values]
    ax.scatter(x, current.values, s=50, color=cur_colors, zorder=6, edgecolors="white", linewidths=0.5)

    ax.axhline(0, color="white", linewidth=0.6, alpha=0.4, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Residual")

    window_label = f"{range_window}d" if range_window < 1000 else f"{range_window // 252:.0f}Y"
    ax.set_title(f"{title}  [{window_label} range]", fontsize=11)

    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color="#555555", linewidth=1, label="Min / Max"),
        Line2D([0], [0], color="#888888", linewidth=4, alpha=0.5, label="5th / 95th pctl"),
        Line2D([0], [0], marker="_", color="#aaaaaa", linewidth=0, markersize=8, label="Median"),
        Line2D([0], [0], marker="o", color=_CHEAP_COLOR, linewidth=0, markersize=6, label="Current"),
    ]
    ax.legend(handles=legend_elements, fontsize=8, loc="upper right", framealpha=0.7)
    ax.grid(axis="y", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 3. PCA vs actual term structure (StanChart style)
# ============================================================================

def plot_pca_vs_actual(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 3,
    title: str = "Actual vs PCA Fair Value Curve",
    figsize: tuple = (10, 5),
) -> tuple:
    """Actual curve vs PCA-reconstructed curve for the last date."""
    model, fair_value_fn, *_ = _build_and_fit(df, on=on, n_factors=n_factors)
    cols = list(model.columns)
    fv = fair_value_fn()

    actual_last = df[cols].dropna(how="any").iloc[-1]
    fv_last = fv.iloc[-1]
    snap_date = fv.index[-1]

    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(len(cols))

    ax.plot(x, actual_last.values, "o-", markersize=4, linewidth=1.5,
            color="#1f77b4", label="Actual", zorder=4)
    ax.plot(x, fv_last.values, "s--", markersize=3, linewidth=1.3,
            color="#ff7f0e", label="PCA Estimated", zorder=4)

    ax.fill_between(x, actual_last.values, fv_last.values,
                     alpha=0.15, color="#ff7f0e", zorder=2)

    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Rate / Level")
    date_str = snap_date.strftime("%Y-%m-%d") if hasattr(snap_date, "strftime") else str(snap_date)
    ax.set_title(f"{title}  [{date_str}]", fontsize=11)
    ax.legend(fontsize=9, framealpha=0.7)
    ax.grid(alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 4. Fly scanner horizontal bar chart
# ============================================================================

def plot_fly_scanner(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 3,
    zscore_window: int = 60,
    top_n: int = 15,
    title: str = "PCA Fly Scanner — Top Dislocations",
    figsize: tuple = (14, 6),
) -> tuple:
    """Horizontal bar chart of most dislocated PCA-neutral flies."""
    model, fair_value_fn, residual_fn, fly_weights_fn, get_model_fn, _ = _build_and_fit(
        df, on=on, n_factors=n_factors
    )
    cols = list(model.columns)
    if len(cols) < 3:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "Need >= 3 columns for fly combos",
                ha="center", va="center", transform=ax.transAxes)
        return fig, ax

    records = []
    for short, body, long in combinations(cols, 3):
        try:
            w = fly_weights_fn(short, body, long)
        except Exception:
            continue
        rv = residual_fn((short, body, long), weights=w)
        z_series = rv.zscore(zscore_window)
        if z_series.empty:
            continue
        z_last = float(z_series.iloc[-1]) if not np.isnan(z_series.iloc[-1]) else 0.0
        resid_last = rv.last()
        records.append({
            "fly": f"{short}/{body}/{long}",
            "zscore": z_last,
            "residual": resid_last,
        })

    if not records:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No valid fly combinations", ha="center", va="center",
                transform=ax.transAxes)
        return fig, ax

    scan = pd.DataFrame(records).sort_values("zscore", key=abs, ascending=False).head(top_n)
    scan = scan.iloc[::-1]

    fig, ax = plt.subplots(figsize=figsize)
    colors = [_CHEAP_COLOR if z >= 0 else _RICH_COLOR for z in scan["zscore"]]
    bars = ax.barh(scan["fly"], scan["zscore"], color=colors, alpha=0.85, height=0.6)

    for bar, resid_val in zip(bars, scan["residual"]):
        w = bar.get_width()
        offset = 0.05 if w >= 0 else -0.05
        ha = "left" if w >= 0 else "right"
        ax.text(w + offset, bar.get_y() + bar.get_height() / 2,
                f"{resid_val:+.1f}", va="center", ha=ha, fontsize=7, alpha=0.8)

    ax.axvline(0, color="white", linewidth=0.5, alpha=0.5)
    ax.set_xlabel(f"Z-score ({zscore_window}d rolling)")
    ax.set_title(title, fontsize=11)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="x", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 5. Fly timeseries with z-score (JPM / StanChart style)
# ============================================================================

def plot_fly_timeseries(
    df: pd.DataFrame,
    short: str,
    body: str,
    long: str,
    *,
    on: str = "levels",
    n_factors: int = 3,
    zscore_window: int = 60,
    title: Union[str, None] = None,
    figsize: tuple = (12, 6),
) -> tuple:
    """PCA-neutral fly spread timeseries + rolling z-score with sigma bands."""
    model, _, residual_fn, fly_weights_fn, *_ = _build_and_fit(
        df, on=on, n_factors=n_factors
    )
    w = fly_weights_fn(short, body, long)
    rv = residual_fn((short, body, long), weights=w)
    spread = rv.series
    z = rv.zscore(zscore_window)

    if title is None:
        w_s, w_l = w[short], w[long]
        title = f"{short}/{body}/{long} PCA-Neutral Fly  [{w_s:+.2f} / 1.00 / {w_l:+.2f}]"

    fig, axes = plt.subplots(2, 1, figsize=figsize, sharex=True,
                              gridspec_kw={"height_ratios": [2.5, 1]})
    ax_top, ax_bot = axes

    # --- Top: spread with bands ---
    r = spread.rolling(zscore_window)
    mu = r.mean()
    sigma = r.std(ddof=1)

    ax_top.plot(spread.index, spread.values, linewidth=1, color="#1f77b4", label="PCA Fly Spread")
    ax_top.plot(mu.index, mu.values, linewidth=0.8, color="#ff7f0e", linestyle="--",
                label=f"Mean ({zscore_window}d)", alpha=0.8)

    for k, alpha_val in [(1, 0.12), (2, 0.06)]:
        ax_top.fill_between(mu.index, (mu - k * sigma).values, (mu + k * sigma).values,
                            alpha=alpha_val, color="#ff7f0e")

    ax_top.set_ylabel("Spread")
    ax_top.set_title(title, fontsize=11)
    ax_top.legend(fontsize=8, loc="upper left", framealpha=0.7)
    ax_top.grid(alpha=0.2, linewidth=0.4)

    # --- Bottom: z-score ---
    ax_bot.plot(z.index, z.values, linewidth=0.9, color="#1f77b4")
    ax_bot.axhline(0, color="white", linewidth=0.4, alpha=0.4)
    for level in [2, -2]:
        ax_bot.axhline(level, color=_RICH_COLOR if level > 0 else _CHEAP_COLOR,
                        linewidth=0.6, linestyle=":", alpha=0.6)

    z_vals = z.values
    z_idx = z.index
    ax_bot.fill_between(z_idx, z_vals, 2,
                         where=z_vals > 2, alpha=0.25, color=_RICH_COLOR, interpolate=True)
    ax_bot.fill_between(z_idx, z_vals, -2,
                         where=z_vals < -2, alpha=0.25, color=_CHEAP_COLOR, interpolate=True)

    ax_bot.set_ylabel("Z-score")
    ax_bot.set_xlabel("Date")
    ax_bot.grid(alpha=0.2, linewidth=0.4)

    fig.tight_layout()
    return fig, axes


# ============================================================================
# 6. PCA Loadings chart
# ============================================================================

def plot_loadings(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 3,
    title: str = "PCA Loadings",
    figsize: tuple = (12, 5),
) -> tuple:
    """Classic PCA loadings: one line per PC across tenors with variance explained."""
    model, *_ = _build_and_fit(df, on=on, n_factors=n_factors)
    L = model.loadings
    ev = model.explained_variance()
    cols = list(model.columns)

    pc_labels = {
        "PC1": "Level",
        "PC2": "Slope",
        "PC3": "Curvature",
    }
    pc_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                 "#8c564b", "#e377c2", "#7f7f7f"]

    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(len(cols))

    for j, pc in enumerate(L.columns[:n_factors]):
        pct = ev.get(pc, 0) * 100
        label_suffix = pc_labels.get(pc, "")
        label = f"{pc} ({label_suffix}) {pct:.1f}%" if label_suffix else f"{pc}  {pct:.1f}%"
        ax.plot(x, L[pc].values, "o-", markersize=4, linewidth=1.4,
                color=pc_colors[j % len(pc_colors)], label=label, zorder=3)

    ax.axhline(0, color="white", linewidth=0.5, alpha=0.4, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Loading")
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=8, loc="best", framealpha=0.7)
    ax.grid(alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 7. Variance explained (bar + cumulative line)
# ============================================================================

def plot_variance_explained(
    df: pd.DataFrame,
    *,
    on: str = "levels",
    n_factors: int = 5,
    title: str = "Variance Explained",
    figsize: tuple = (8, 4),
) -> tuple:
    """Bar chart of individual + cumulative variance explained per PC."""
    model, *_ = _build_and_fit(df, on=on, n_factors=n_factors)
    ev = model.explained_variance()
    n_show = min(n_factors, len(ev))
    ev = ev.iloc[:n_show]

    fig, ax = plt.subplots(figsize=figsize)
    x = np.arange(n_show)
    pcts = ev.values * 100
    cum_pcts = np.cumsum(pcts)

    ax.bar(x, pcts, color="#1f77b4", alpha=0.8, width=0.5, label="Individual", zorder=3)
    ax2 = ax.twinx()
    ax2.plot(x, cum_pcts, "D-", color="#ff7f0e", markersize=5, linewidth=1.3,
             label="Cumulative", zorder=4)

    for i, (p, c) in enumerate(zip(pcts, cum_pcts)):
        ax.text(i, p + 0.5, f"{p:.1f}%", ha="center", va="bottom", fontsize=7)
        ax2.text(i + 0.15, c + 0.3, f"{c:.1f}%", ha="left", va="bottom",
                 fontsize=7, color="#ff7f0e")

    ax.set_xticks(x)
    ax.set_xticklabels([f"PC{i+1}" for i in range(n_show)], fontsize=9)
    ax.set_ylabel("Variance Explained (%)")
    ax2.set_ylabel("Cumulative (%)")
    ax2.set_ylim(0, 105)
    ax.set_title(title, fontsize=11)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="center right", framealpha=0.7)

    ax.grid(axis="y", alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax


# ============================================================================
# 8. Residual timeseries for selected tenors (ING Fig 2)
# ============================================================================

def plot_residual_timeseries(
    df: pd.DataFrame,
    tenors: Sequence[str],
    *,
    on: str = "levels",
    n_factors: int = 3,
    title: str = "PCA Residual Timeseries",
    figsize: tuple = (14, 5),
) -> tuple:
    """Timeseries of PCA residuals for selected tenors (ING Fig 2 style)."""
    resid_df = _full_residual_df(df, on=on, n_factors=n_factors)
    cmap = plt.colormaps.get_cmap("tab10")

    fig, ax = plt.subplots(figsize=figsize)
    for i, tenor in enumerate(tenors):
        if tenor not in resid_df.columns:
            warnings.warn(f"Tenor '{tenor}' not in residual columns, skipping.")
            continue
        series = resid_df[tenor].dropna()
        ax.plot(series.index, series.values, linewidth=1.1,
                color=cmap(i % 10), label=tenor, alpha=0.85)

    ax.axhline(0, color="white", linewidth=0.5, alpha=0.4)
    ax.set_ylabel("Residual")
    ax.set_title(title, fontsize=11)
    ax.legend(fontsize=8, loc="best", framealpha=0.7)
    ax.grid(alpha=0.2, linewidth=0.4)
    fig.tight_layout()
    return fig, ax
