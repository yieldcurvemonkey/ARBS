"""Visualization functions for SFR implied distributions."""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from RVUtils.ImpliedDistribution._types import (
    BreedenLitzenbergerResult,
    GaussianMixtureResult,
    ImpliedDistributionSnapshot,
)


_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]


def plot_rnd_density(
    bl: BreedenLitzenbergerResult,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    show_percentiles: bool = True,
) -> plt.Axes:
    """Plot the Breeden-Litzenberger risk-neutral density in rate space."""
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 6))

    rate = bl.strike_grid_rate
    density = bl.rnd_density

    ax.plot(rate, density, color="black", linewidth=1.5, label="RND")
    ax.axvline(bl.input.forward_rate, color="gray", linestyle="--", linewidth=1, label=f"Forward ({bl.input.forward_rate:.3f}%)")
    ax.axvline(bl.mean_rate, color="blue", linestyle=":", linewidth=1, label=f"Mean ({bl.mean_rate:.3f}%)")

    if show_percentiles:
        p5 = bl.percentile(5)
        p25 = bl.percentile(25)
        p75 = bl.percentile(75)
        p95 = bl.percentile(95)
        ax.fill_between(rate, density, where=(rate >= p25) & (rate <= p75), alpha=0.3, color="steelblue", label="25th-75th pctl")
        ax.fill_between(rate, density, where=(rate >= p5) & (rate <= p95), alpha=0.1, color="steelblue", label="5th-95th pctl")

    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.set_title(title or f"Risk-Neutral Density — {bl.input.symbol} as of {bl.input.as_of}")
    ax.legend(fontsize=8)
    ax.set_xlim(bl.percentile(0.5), bl.percentile(99.5))
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)
    return ax


def plot_scenario_probabilities(
    bl: BreedenLitzenbergerResult,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    min_prob: float = 0.005,
) -> plt.Axes:
    """Plot bar chart of binned scenario probabilities from BL."""
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5))

    mask = bl.bin_probabilities >= min_prob
    labels = [bl.bin_labels[i] for i in range(len(bl.bin_labels)) if mask[i]]
    probs = bl.bin_probabilities[mask]

    colors = ["steelblue" if float(l) <= bl.input.forward_rate else "coral" for l in labels]
    ax.bar(range(len(labels)), probs * 100, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, fontsize=7)
    ax.set_ylabel("Probability (%)")
    ax.set_xlabel("Rate bin midpoint (%)")
    ax.set_title(title or f"Scenario Probabilities (25bp bins) — {bl.input.symbol} as of {bl.input.as_of}")
    ax.grid(True, axis="y", alpha=0.3)
    return ax


def plot_gaussian_mixture(
    gm: GaussianMixtureResult,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    show_components: bool = True,
) -> plt.Axes:
    """Plot composite density and individual scenario components."""
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 6))

    rate = gm.strike_grid_rate
    ax.plot(rate, gm.composite_density, color="black", linewidth=2, label="Composite")

    if show_components:
        for j, (scenario, w) in enumerate(zip(gm.scenarios, gm.weights)):
            if w < 0.01:
                continue
            color = _COLORS[j % len(_COLORS)]
            ax.plot(
                rate,
                gm.component_densities[j] * w,
                linestyle="--",
                linewidth=1,
                color=color,
                label=f"{scenario.label} (w={w:.0%})",
            )

    ax.axvline(gm.input.forward_rate, color="gray", linestyle="--", linewidth=1, label=f"Forward ({gm.input.forward_rate:.3f}%)")
    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.set_title(title or f"Gaussian Mixture — {gm.input.symbol} as of {gm.input.as_of}")
    ax.legend(fontsize=7, loc="upper right")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)
    return ax


def plot_scenario_weights_bar(
    gm: GaussianMixtureResult,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
) -> plt.Axes:
    """Horizontal bar chart of scenario weights (JPM Figure 17 style)."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8, max(4, len(gm.scenarios) * 0.6)))

    labels = [s.label for s in gm.scenarios]
    weights = gm.weights * 100

    colors = [_COLORS[i % len(_COLORS)] for i in range(len(labels))]
    y_pos = range(len(labels))
    ax.barh(y_pos, weights, color=colors, edgecolor="white")
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Weight (%)")
    ax.set_title(title or f"Scenario Weights — {gm.input.symbol} as of {gm.input.as_of}")
    ax.set_xlim(0, max(weights) * 1.15)
    for i, w in enumerate(weights):
        if w >= 1.0:
            ax.text(w + 0.5, i, f"{w:.1f}%", va="center", fontsize=8)
    ax.grid(True, axis="x", alpha=0.3)
    return ax


def plot_scenario_weights_timeseries(
    ts_results: "OrderedDict",
    *,
    figsize: tuple = (14, 7),
    title: Optional[str] = None,
    stacked: bool = True,
) -> plt.Figure:
    """Time evolution of scenario weights (JPM Figure 2 style).

    Stacked area chart showing how market-implied probability of each
    Fed path evolves over time.
    """
    dates = []
    weight_series: dict[str, list[float]] = {}

    for as_of, snapshot in ts_results.items():
        if snapshot.gm_result is None:
            continue
        dates.append(as_of)
        for scenario, w in zip(snapshot.gm_result.scenarios, snapshot.gm_result.weights):
            weight_series.setdefault(scenario.label, []).append(float(w) * 100)

    if not dates:
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, "No GM results available", ha="center", va="center", transform=ax.transAxes)
        return fig

    fig, ax = plt.subplots(figsize=figsize)
    labels = list(weight_series.keys())
    data = np.array([weight_series[lbl] for lbl in labels])

    if stacked:
        ax.stackplot(dates, data, labels=labels, colors=_COLORS[: len(labels)], alpha=0.8)
    else:
        for i, lbl in enumerate(labels):
            ax.plot(dates, data[i], label=lbl, color=_COLORS[i % len(_COLORS)], linewidth=1.5)

    ax.set_ylabel("Weight (%)")
    ax.set_xlabel("Date")
    ax.set_title(title or "Scenario Weights Over Time")
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def plot_rnd_comparison(
    bl: BreedenLitzenbergerResult,
    gm: GaussianMixtureResult,
    *,
    figsize: tuple = (14, 6),
    title: Optional[str] = None,
) -> plt.Figure:
    """Overlay BL density and GM composite density."""
    fig, ax = plt.subplots(figsize=figsize)

    ax.plot(bl.strike_grid_rate, bl.rnd_density, color="black", linewidth=1.5, label="Breeden-Litzenberger")
    ax.plot(gm.strike_grid_rate, gm.composite_density, color="red", linewidth=1.5, linestyle="--", label="Gaussian Mixture")
    ax.axvline(bl.input.forward_rate, color="gray", linestyle="--", linewidth=1, alpha=0.5)

    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.set_title(title or f"RND Comparison — {bl.input.symbol} as of {bl.input.as_of}")
    ax.legend()
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    # Set common x-range
    lo = min(bl.percentile(1), gm.strike_grid_rate[gm.composite_density > 1e-6][0] if np.any(gm.composite_density > 1e-6) else bl.percentile(1))
    hi = max(bl.percentile(99), gm.strike_grid_rate[gm.composite_density > 1e-6][-1] if np.any(gm.composite_density > 1e-6) else bl.percentile(99))
    ax.set_xlim(lo, hi)

    fig.tight_layout()
    return fig


def plot_distribution_change(
    snap_before: ImpliedDistributionSnapshot,
    snap_after: ImpliedDistributionSnapshot,
    *,
    figsize: tuple = (18, 14),
) -> plt.Figure:
    """Multi-panel dashboard showing how the implied distribution changed between two dates.

    Panels:
        Top-left:   Overlaid BL densities with shaded gain/loss regions
        Top-right:  Overlaid GM composite densities with components
        Mid-left:   Grouped bar chart of 25bp bin probabilities (before vs after)
        Mid-right:  Scenario weight changes (paired horizontal bars with delta annotation)
        Bottom:     Summary statistics delta table
    """
    bl1, bl2 = snap_before.bl_result, snap_after.bl_result
    gm1, gm2 = snap_before.gm_result, snap_after.gm_result
    date1, date2 = snap_before.as_of, snap_after.as_of
    label1 = str(date1)
    label2 = str(date2)

    fig, axes = plt.subplots(3, 2, figsize=figsize, gridspec_kw={"height_ratios": [3, 3, 2]})
    fig.suptitle(
        f"Distribution Change — {snap_before.symbol}:  {label1}  →  {label2}",
        fontsize=14,
        fontweight="bold",
    )

    # ── Top-left: Overlaid BL densities ──────────────────────────────────
    ax = axes[0, 0]
    if bl1 is not None and bl2 is not None:
        # Interpolate both onto a common grid
        lo = min(bl1.strike_grid_rate[0], bl2.strike_grid_rate[0])
        hi = max(bl1.strike_grid_rate[-1], bl2.strike_grid_rate[-1])
        common = np.linspace(lo, hi, 2000)
        d1 = np.interp(common, bl1.strike_grid_rate, bl1.rnd_density)
        d2 = np.interp(common, bl2.strike_grid_rate, bl2.rnd_density)

        ax.plot(common, d1, color="#1f77b4", linewidth=1.5, label=label1)
        ax.plot(common, d2, color="#d62728", linewidth=1.5, label=label2)
        diff = d2 - d1
        ax.fill_between(common, d1, d2, where=diff > 0, alpha=0.25, color="green", label="Density gain")
        ax.fill_between(common, d1, d2, where=diff < 0, alpha=0.25, color="red", label="Density loss")
        ax.axvline(bl1.input.forward_rate, color="#1f77b4", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axvline(bl2.input.forward_rate, color="#d62728", linestyle="--", linewidth=0.8, alpha=0.6)

        vis_lo = min(bl1.percentile(1), bl2.percentile(1))
        vis_hi = max(bl1.percentile(99), bl2.percentile(99))
        ax.set_xlim(vis_lo, vis_hi)
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "BL not computed", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Risk-Neutral Density Shift")
    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    # ── Top-right: Overlaid GM composite densities ───────────────────────
    ax = axes[0, 1]
    if gm1 is not None and gm2 is not None:
        ax.plot(gm1.strike_grid_rate, gm1.composite_density, color="#1f77b4", linewidth=2, label=f"Composite {label1}")
        ax.plot(gm2.strike_grid_rate, gm2.composite_density, color="#d62728", linewidth=2, label=f"Composite {label2}")
        # Show date2 components (dashed)
        for j, (scenario, w) in enumerate(zip(gm2.scenarios, gm2.weights)):
            if w < 0.02:
                continue
            ax.plot(
                gm2.strike_grid_rate,
                gm2.component_densities[j] * w,
                linestyle=":",
                linewidth=0.8,
                color=_COLORS[j % len(_COLORS)],
                alpha=0.6,
            )
        ax.axvline(gm1.input.forward_rate, color="#1f77b4", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axvline(gm2.input.forward_rate, color="#d62728", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Gaussian Mixture Shift")
    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    # ── Mid-left: Grouped bar chart of bin probabilities ─────────────────
    ax = axes[1, 0]
    if bl1 is not None and bl2 is not None:
        # Find common bins (union of labels present in either)
        all_labels = sorted(set(bl1.bin_labels) | set(bl2.bin_labels), key=lambda x: float(x))
        prob_map1 = dict(zip(bl1.bin_labels, bl1.bin_probabilities))
        prob_map2 = dict(zip(bl2.bin_labels, bl2.bin_probabilities))
        # Filter to bins with at least 0.5% in either date
        filtered = [(lbl, prob_map1.get(lbl, 0.0), prob_map2.get(lbl, 0.0)) for lbl in all_labels]
        filtered = [(lbl, p1, p2) for lbl, p1, p2 in filtered if max(p1, p2) >= 0.005]
        if filtered:
            labels_f = [f[0] for f in filtered]
            p1s = np.array([f[1] for f in filtered]) * 100
            p2s = np.array([f[2] for f in filtered]) * 100
            x = np.arange(len(labels_f))
            w = 0.35
            ax.bar(x - w / 2, p1s, w, color="#1f77b4", alpha=0.8, label=label1)
            ax.bar(x + w / 2, p2s, w, color="#d62728", alpha=0.8, label=label2)
            ax.set_xticks(x)
            ax.set_xticklabels(labels_f, rotation=45, fontsize=7)
            ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "BL not computed", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Probability Mass by Rate Bin (25bp)")
    ax.set_ylabel("Probability (%)")
    ax.set_xlabel("Rate bin midpoint (%)")
    ax.grid(True, axis="y", alpha=0.3)

    # ── Mid-right: Scenario weight deltas ────────────────────────────────
    ax = axes[1, 1]
    if gm1 is not None and gm2 is not None:
        labels_s = [s.label for s in gm2.scenarios]
        w1_map = {s.label: float(w) for s, w in zip(gm1.scenarios, gm1.weights)}
        w1s = np.array([w1_map.get(lbl, 0.0) for lbl in labels_s]) * 100
        w2s = np.array([float(w) for w in gm2.weights]) * 100
        deltas = w2s - w1s

        y = np.arange(len(labels_s))
        bar_h = 0.35
        ax.barh(y - bar_h / 2, w1s, bar_h, color="#1f77b4", alpha=0.8, label=label1)
        ax.barh(y + bar_h / 2, w2s, bar_h, color="#d62728", alpha=0.8, label=label2)
        # Annotate delta
        for i, (w1, w2, d) in enumerate(zip(w1s, w2s, deltas)):
            x_pos = max(w1, w2) + 1
            sign = "+" if d >= 0 else ""
            color = "green" if d >= 0 else "red"
            if abs(d) >= 0.5:
                ax.text(x_pos, i, f"{sign}{d:.1f}pp", va="center", fontsize=7, color=color, fontweight="bold")
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels_s, fontsize=8)
        ax.set_xlabel("Weight (%)")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Scenario Weight Changes")
    ax.grid(True, axis="x", alpha=0.3)

    # ── Bottom: Summary stats delta table ────────────────────────────────
    for bottom_ax in [axes[2, 0], axes[2, 1]]:
        bottom_ax.axis("off")
    ax = axes[2, 0]

    rows = []
    if bl1 is not None and bl2 is not None:
        rows.append(("Forward Rate", f"{bl1.input.forward_rate:.3f}%", f"{bl2.input.forward_rate:.3f}%", f"{bl2.input.forward_rate - bl1.input.forward_rate:+.3f}%"))
        rows.append(("Mean Rate", f"{bl1.mean_rate:.3f}%", f"{bl2.mean_rate:.3f}%", f"{bl2.mean_rate - bl1.mean_rate:+.3f}%"))
        rows.append(("Std Dev", f"{bl1.std_rate:.3f}%", f"{bl2.std_rate:.3f}%", f"{bl2.std_rate - bl1.std_rate:+.3f}%"))
        rows.append(("Skewness", f"{bl1.skewness:.3f}", f"{bl2.skewness:.3f}", f"{bl2.skewness - bl1.skewness:+.3f}"))
        rows.append(("Kurtosis", f"{bl1.kurtosis:.3f}", f"{bl2.kurtosis:.3f}", f"{bl2.kurtosis - bl1.kurtosis:+.3f}"))
        rows.append(("5th Pctl", f"{bl1.percentile(5):.3f}%", f"{bl2.percentile(5):.3f}%", f"{bl2.percentile(5) - bl1.percentile(5):+.3f}%"))
        rows.append(("95th Pctl", f"{bl1.percentile(95):.3f}%", f"{bl2.percentile(95):.3f}%", f"{bl2.percentile(95) - bl1.percentile(95):+.3f}%"))

    if rows:
        col_labels = ["Metric", label1, label2, "Δ"]
        table = ax.table(
            cellText=rows,
            colLabels=col_labels,
            loc="center",
            cellLoc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.4)
        # Color delta column
        for i in range(len(rows)):
            cell = table[i + 1, 3]
            val_str = rows[i][3]
            if val_str.startswith("+"):
                cell.set_text_props(color="green", fontweight="bold")
            elif val_str.startswith("-"):
                cell.set_text_props(color="red", fontweight="bold")
        ax.set_title("Distribution Summary", fontsize=11, pad=10)

    # Scenario weight table on the right
    ax2 = axes[2, 1]
    if gm1 is not None and gm2 is not None:
        gm_rows = []
        labels_s = [s.label for s in gm2.scenarios]
        w1_map = {s.label: float(w) for s, w in zip(gm1.scenarios, gm1.weights)}
        for s, w2 in zip(gm2.scenarios, gm2.weights):
            w1 = w1_map.get(s.label, 0.0)
            d = float(w2) - w1
            sign = "+" if d >= 0 else ""
            gm_rows.append((s.label, f"{w1:.1%}", f"{float(w2):.1%}", f"{sign}{d:.1%}"))
        if gm_rows:
            col_labels = ["Scenario", label1, label2, "Δ"]
            table2 = ax2.table(
                cellText=gm_rows,
                colLabels=col_labels,
                loc="center",
                cellLoc="center",
            )
            table2.auto_set_font_size(False)
            table2.set_fontsize(9)
            table2.scale(1, 1.4)
            for i in range(len(gm_rows)):
                cell = table2[i + 1, 3]
                val_str = gm_rows[i][3]
                if val_str.startswith("+"):
                    cell.set_text_props(color="green", fontweight="bold")
                elif val_str.startswith("-"):
                    cell.set_text_props(color="red", fontweight="bold")
            ax2.set_title("Scenario Weight Changes", fontsize=11, pad=10)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def plot_snapshot_dashboard(
    snapshot: ImpliedDistributionSnapshot,
    *,
    figsize: tuple = (18, 10),
) -> plt.Figure:
    """Full 2x2 dashboard: RND density, scenario probs, GM components, weights bar."""
    fig, axes = plt.subplots(2, 2, figsize=figsize)
    fig.suptitle(f"Implied Distribution — {snapshot.symbol} as of {snapshot.as_of}", fontsize=14, fontweight="bold")

    if snapshot.bl_result is not None:
        plot_rnd_density(snapshot.bl_result, ax=axes[0, 0], title="Risk-Neutral Density (BL)")
        plot_scenario_probabilities(snapshot.bl_result, ax=axes[1, 0], title="Scenario Probabilities (25bp bins)")
    else:
        for ax in [axes[0, 0], axes[1, 0]]:
            ax.text(0.5, 0.5, "BL not computed", ha="center", va="center", transform=ax.transAxes)

    if snapshot.gm_result is not None:
        plot_gaussian_mixture(snapshot.gm_result, ax=axes[0, 1], title="Gaussian Mixture Decomposition")
        plot_scenario_weights_bar(snapshot.gm_result, ax=axes[1, 1], title="Scenario Weights")
    else:
        for ax in [axes[0, 1], axes[1, 1]]:
            ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig
