"""Visualization functions for SFR implied distributions."""

from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Optional, Sequence

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from RVUtils.ImpliedDistribution._types import (
    BreedenLitzenbergerResult,
    GaussianMixtureResult,
    ImpliedDistributionSnapshot,
    StripComparisonResult,
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


# Rows of the distribution-summary delta table whose sign carries an
# easing/tightening direction (rate levels, not dispersion or shape).
_RATE_LEVEL_METRICS = frozenset({"Forward Rate", "Mean Rate", "5th Pctl", "95th Pctl"})


def _bin_width_pct(bl: Optional[BreedenLitzenbergerResult]) -> float:
    """Actual scenario-bin width in rate percent, read off the result's bin edges."""
    if bl is None:
        return 0.25
    edges = np.asarray(bl.bin_edges_rate, dtype=float)
    if edges.size >= 2:
        return float(edges[1] - edges[0])
    return 0.25


def _bin_width_label(*bls: Optional[BreedenLitzenbergerResult]) -> str:
    """Human label for the bin width, e.g. ``"25bp"`` — never hardcode 25."""
    widths = {round(_bin_width_pct(bl) * 100.0, 3) for bl in bls if bl is not None}
    if not widths:
        return ""
    if len(widths) > 1:
        return "/".join(f"{w:g}bp" for w in sorted(widths))
    return f"{widths.pop():g}bp"


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
    idx = np.flatnonzero(mask)
    labels = [bl.bin_labels[i] for i in idx]
    probs = bl.bin_probabilities[idx]
    # Bars must sit at their true rate midpoint: filtering by ``min_prob`` can drop
    # interior bins (clipped/near-zero density between modes), and a categorical
    # 0..n-1 x-axis would render the survivors as if they were contiguous.
    centers = np.array([float(l) for l in labels], dtype=float)

    width_pct = _bin_width_pct(bl)
    colors = ["steelblue" if c <= bl.input.forward_rate else "coral" for c in centers]
    ax.bar(centers, probs * 100, width=width_pct * 0.9, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(centers)
    ax.set_xticklabels(labels, rotation=45, fontsize=7)
    ax.set_ylabel("Probability (%)")
    ax.set_xlabel("Rate bin midpoint (%)")
    ax.set_title(title or f"Scenario Probabilities ({_bin_width_label(bl)} bins) — {bl.input.symbol} as of {bl.input.as_of}")
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


def _plot_discrete_scenario_bars(
    gm: GaussianMixtureResult,
    *,
    ax: plt.Axes,
    title: Optional[str] = None,
    color: str = "steelblue",
) -> None:
    """Plot discrete scenario probabilities as bars at their mean rates."""
    labels = [s.label for s in gm.scenarios]
    weights = gm.weights * 100
    x = np.arange(len(labels))
    colors = [_COLORS[i % len(_COLORS)] for i in range(len(labels))]
    ax.bar(x, weights, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, fontsize=8, ha="right")
    ax.set_ylabel("Probability (%)")
    ax.set_title(title or "Scenario Probabilities")
    ax.grid(True, axis="y", alpha=0.3)
    # Annotate
    for i, w in enumerate(weights):
        if w >= 1.0:
            ax.text(i, w + 0.3, f"{w:.1f}%", ha="center", fontsize=7)


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

    fig, axes = plt.subplots(3, 1, figsize=figsize, gridspec_kw={"height_ratios": [3, 3, 2]})
    fig.suptitle(
        f"Distribution Change — {snap_before.symbol}:  {label1}  →  {label2}",
        fontsize=14,
        fontweight="bold",
    )

    # ── Top-left: Overlaid BL densities (or GM fallback) ─────────────────
    ax = axes[0]
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
    elif gm1 is not None and gm2 is not None:
        # scenarios_only fallback: use GM composite densities
        lo = min(gm1.strike_grid_rate[0], gm2.strike_grid_rate[0])
        hi = max(gm1.strike_grid_rate[-1], gm2.strike_grid_rate[-1])
        common = np.linspace(lo, hi, 2000)
        d1 = np.interp(common, gm1.strike_grid_rate, gm1.composite_density)
        d2 = np.interp(common, gm2.strike_grid_rate, gm2.composite_density)

        ax.plot(common, d1, color="#1f77b4", linewidth=1.5, label=label1)
        ax.plot(common, d2, color="#d62728", linewidth=1.5, label=label2)
        diff = d2 - d1
        ax.fill_between(common, d1, d2, where=diff > 0, alpha=0.25, color="green", label="Density gain")
        ax.fill_between(common, d1, d2, where=diff < 0, alpha=0.25, color="red", label="Density loss")
        ax.axvline(gm1.input.forward_rate, color="#1f77b4", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.axvline(gm2.input.forward_rate, color="#d62728", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "Not computed", ha="center", va="center", transform=ax.transAxes)
    ax.set_title("Risk-Neutral Density Shift" + (" (GM)" if bl1 is None and gm1 is not None else ""))
    ax.set_xlabel("Rate (%)")
    ax.set_ylabel("Density")
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)

    # ── Top-right: Overlaid GM composite densities ───────────────────────
    # ax = axes[0, 1]
    # if gm1 is not None and gm2 is not None:
    #     ax.plot(gm1.strike_grid_rate, gm1.composite_density, color="#1f77b4", linewidth=2, label=f"Composite {label1}")
    #     ax.plot(gm2.strike_grid_rate, gm2.composite_density, color="#d62728", linewidth=2, label=f"Composite {label2}")
    #     # Show date2 components (dashed)
    #     for j, (scenario, w) in enumerate(zip(gm2.scenarios, gm2.weights)):
    #         if w < 0.02:
    #             continue
    #         ax.plot(
    #             gm2.strike_grid_rate,
    #             gm2.component_densities[j] * w,
    #             linestyle=":",
    #             linewidth=0.8,
    #             color=_COLORS[j % len(_COLORS)],
    #             alpha=0.6,
    #         )
    #     ax.axvline(gm1.input.forward_rate, color="#1f77b4", linestyle="--", linewidth=0.8, alpha=0.6)
    #     ax.axvline(gm2.input.forward_rate, color="#d62728", linestyle="--", linewidth=0.8, alpha=0.6)
    #     ax.legend(fontsize=7)
    # else:
    #     ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)
    # ax.set_title("Gaussian Mixture Shift")
    # ax.set_xlabel("Rate (%)")
    # ax.set_ylabel("Density")
    # ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    # ax.grid(True, alpha=0.3)

    # ── Mid-left: Grouped bar chart of bin probabilities (or GM fallback)
    ax = axes[1]
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
        _w = _bin_width_label(bl1, bl2)
        ax.set_title(f"Probability Mass by Rate Bin ({_w})" if _w else "Probability Mass by Rate Bin")
        ax.set_xlabel("Rate bin midpoint (%)")
    elif gm1 is not None and gm2 is not None:
        # scenarios_only fallback: grouped bars of GM scenario weights
        labels_s = [s.label for s in gm2.scenarios]
        w1_map = {s.label: float(w) for s, w in zip(gm1.scenarios, gm1.weights)}
        w1s = np.array([w1_map.get(lbl, 0.0) for lbl in labels_s]) * 100
        w2s = np.array([float(w) for w in gm2.weights]) * 100
        x = np.arange(len(labels_s))
        w = 0.35
        ax.bar(x - w / 2, w1s, w, color="#1f77b4", alpha=0.8, label=label1)
        ax.bar(x + w / 2, w2s, w, color="#d62728", alpha=0.8, label=label2)
        ax.set_xticks(x)
        ax.set_xticklabels(labels_s, rotation=30, fontsize=7, ha="right")
        ax.legend(fontsize=8)
        ax.set_title("Scenario Probability Change")
        ax.set_xlabel("Scenario")
    else:
        ax.text(0.5, 0.5, "Not computed", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Probability Mass by Rate Bin")
        ax.set_xlabel("Rate bin midpoint (%)")
    ax.set_ylabel("Probability (%)")
    ax.grid(True, axis="y", alpha=0.3)

    # # ── Mid-right: Scenario weight deltas ────────────────────────────────
    # ax = axes[1, 1]
    # if gm1 is not None and gm2 is not None:
    #     labels_s = [s.label for s in gm2.scenarios]
    #     w1_map = {s.label: float(w) for s, w in zip(gm1.scenarios, gm1.weights)}
    #     w1s = np.array([w1_map.get(lbl, 0.0) for lbl in labels_s]) * 100
    #     w2s = np.array([float(w) for w in gm2.weights]) * 100
    #     deltas = w2s - w1s

    #     y = np.arange(len(labels_s))
    #     bar_h = 0.35
    #     ax.barh(y - bar_h / 2, w1s, bar_h, color="#1f77b4", alpha=0.8, label=label1)
    #     ax.barh(y + bar_h / 2, w2s, bar_h, color="#d62728", alpha=0.8, label=label2)
    #     # Annotate delta
    #     for i, (w1, w2, d) in enumerate(zip(w1s, w2s, deltas)):
    #         x_pos = max(w1, w2) + 1
    #         sign = "+" if d >= 0 else ""
    #         color = "green" if d >= 0 else "red"
    #         if abs(d) >= 0.5:
    #             ax.text(x_pos, i, f"{sign}{d:.1f}pp", va="center", fontsize=7, color=color, fontweight="bold")
    #     ax.set_yticks(list(y))
    #     ax.set_yticklabels(labels_s, fontsize=8)
    #     ax.set_xlabel("Weight (%)")
    #     ax.legend(fontsize=8)
    # else:
    #     ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)
    # ax.set_title("Scenario Weight Changes")
    # ax.grid(True, axis="x", alpha=0.3)

    # ── Bottom: Summary stats delta table ────────────────────────────────
    for bottom_ax in [axes[2], axes[2]]:
        bottom_ax.axis("off")
    ax = axes[2]

    rows = []
    if bl1 is not None and bl2 is not None:
        rows.append(("Forward Rate", f"{bl1.input.forward_rate:.3f}%", f"{bl2.input.forward_rate:.3f}%", f"{bl2.input.forward_rate - bl1.input.forward_rate:+.3f}%"))
        rows.append(("Mean Rate", f"{bl1.mean_rate:.3f}%", f"{bl2.mean_rate:.3f}%", f"{bl2.mean_rate - bl1.mean_rate:+.3f}%"))
        rows.append(("Std Dev", f"{bl1.std_rate:.3f}%", f"{bl2.std_rate:.3f}%", f"{bl2.std_rate - bl1.std_rate:+.3f}%"))
        rows.append(("Skewness", f"{bl1.skewness:.3f}", f"{bl2.skewness:.3f}", f"{bl2.skewness - bl1.skewness:+.3f}"))
        rows.append(("Kurtosis", f"{bl1.kurtosis:.3f}", f"{bl2.kurtosis:.3f}", f"{bl2.kurtosis - bl1.kurtosis:+.3f}"))
        rows.append(("5th Pctl", f"{bl1.percentile(5):.3f}%", f"{bl2.percentile(5):.3f}%", f"{bl2.percentile(5) - bl1.percentile(5):+.3f}%"))
        rows.append(("95th Pctl", f"{bl1.percentile(95):.3f}%", f"{bl2.percentile(95):.3f}%", f"{bl2.percentile(95) - bl1.percentile(95):+.3f}%"))
    elif gm1 is not None and gm2 is not None:
        # scenarios_only fallback: derive stats from GM weights
        fwd1, fwd2 = gm1.input.forward_rate, gm2.input.forward_rate
        mean1 = float(np.dot(gm1.weights, [s.mean_rate for s in gm1.scenarios]))
        mean2 = float(np.dot(gm2.weights, [s.mean_rate for s in gm2.scenarios]))
        rows.append(("Forward Rate", f"{fwd1:.3f}%", f"{fwd2:.3f}%", f"{fwd2 - fwd1:+.3f}%"))
        rows.append(("Mean Rate", f"{mean1:.3f}%", f"{mean2:.3f}%", f"{mean2 - mean1:+.3f}%"))

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
        # Color delta column. House rule (see plot_strip_distribution_change and
        # _plot_strip_summary_table): higher rate = hawkish = red, lower rate =
        # easing = green. Only rate-LEVEL metrics carry that direction; dispersion
        # and shape stats (std/skew/kurtosis) are left uncoloured.
        for i in range(len(rows)):
            if rows[i][0] not in _RATE_LEVEL_METRICS:
                continue
            cell = table[i + 1, 3]
            val_str = rows[i][3]
            if val_str.startswith("+"):
                cell.set_text_props(color="red", fontweight="bold")
            elif val_str.startswith("-"):
                cell.set_text_props(color="green", fontweight="bold")
        ax.set_title("Distribution Summary", fontsize=11, pad=10)

    # Scenario weight table on the right
    ax2 = axes[2]
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
    """Full 2x2 dashboard: RND density, scenario probs, GM components, weights bar.

    When ``scenarios_only`` is active (bl_result is None, gm_result present),
    the left panels show the GM composite density and discrete scenario weights
    instead of the BL-derived panels.
    """
    fig, axes = plt.subplots(2, 1, figsize=figsize)
    fig.suptitle(f"Implied Distribution — {snapshot.symbol} as of {snapshot.as_of}", fontsize=14, fontweight="bold")

    scenarios_only = snapshot.bl_result is None and snapshot.gm_result is not None

    if snapshot.bl_result is not None:
        plot_rnd_density(snapshot.bl_result, ax=axes[0], title="Risk-Neutral Density (BL)")
        plot_scenario_probabilities(
            snapshot.bl_result,
            ax=axes[1],
            title=f"Scenario Probabilities ({_bin_width_label(snapshot.bl_result)} bins)",
        )
    elif scenarios_only:
        # Fall back to GM composite density
        plot_gaussian_mixture(snapshot.gm_result, ax=axes[0], title="Risk-Neutral Density (GM)")
        # Discrete scenario weight bars
        _plot_discrete_scenario_bars(snapshot.gm_result, ax=axes[1], title="Scenario Probabilities")
    else:
        for ax in [axes[0], axes[1]]:
            ax.text(0.5, 0.5, "BL not computed", ha="center", va="center", transform=ax.transAxes)

    # if snapshot.gm_result is not None:
    #     plot_gaussian_mixture(snapshot.gm_result, ax=axes[0, 1], title="Gaussian Mixture Decomposition")
    #     plot_scenario_weights_bar(snapshot.gm_result, ax=axes[1, 1], title="Scenario Weights")
    # else:
    #     for ax in [axes[0, 1], axes[1, 1]]:
    #         ax.text(0.5, 0.5, "GM not computed", ha="center", va="center", transform=ax.transAxes)

    # Surface fit diagnostics: a non-converged GM or a clipped/truncated BL density
    # would otherwise be plotted as if it were clean.
    notes = list(snapshot.all_warnings())
    if snapshot.gm_result is not None and not snapshot.gm_result.optimization_success:
        notes.insert(0, "gm::optimization did not converge")
    if notes:
        shown = notes[:4]
        extra = f"  (+{len(notes) - len(shown)} more)" if len(notes) > len(shown) else ""
        fig.text(
            0.01,
            0.005,
            "⚠ " + "  |  ".join(shown) + extra,
            fontsize=7,
            color="#b22222",
            ha="left",
            va="bottom",
        )
        fig.tight_layout(rect=[0, 0.03, 1, 0.96])
    else:
        fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


def plot_strip_distribution_change(
    result: StripComparisonResult,
    *,
    figsize: Optional[tuple] = None,
    show_components: bool = False,
) -> plt.Figure:
    """Multi-panel dashboard comparing implied distributions across a strip of contracts.

    Layout:
        Row 0:       Forward curve shift (left) + scenario weight heatmap (right)
        Rows 1..N:   Per-contract density shift (left) + scenario weight bars (right)
        Bottom row:  Summary statistics table

    Parameters
    ----------
    result : StripComparisonResult
        Output of ``SFRImpliedDistribution.compare_strip()``.
    figsize : tuple, optional
        Figure size. Auto-scaled if None.
    show_components : bool
        If True, show individual GM components on density panels.
    """
    n = result.n_contracts
    strip_title = result.strip_label.upper() if result.strip_label else "Custom Strip"
    label1 = str(result.date_before)
    label2 = str(result.date_after)

    # Layout: 1 summary row + N contract rows + 1 table row
    n_rows = 1 + n + 1
    if figsize is None:
        figsize = (20, 3.5 * n_rows)

    fig = plt.figure(figsize=figsize)
    gs = fig.add_gridspec(n_rows, 2, hspace=0.4, wspace=0.3, height_ratios=[3] + [3] * n + [2.5])

    fig.suptitle(
        f"Strip Distribution Change \u2014 {strip_title}:  {label1}  \u2192  {label2}",
        fontsize=15,
        fontweight="bold",
        y=0.995,
    )

    # ── Row 0, Left: Forward rate curve shift ────────────────────────────
    ax_fwd = fig.add_subplot(gs[0, 0])
    fwd1_vals = []
    fwd2_vals = []
    fwd_syms = []
    for sym in result.symbols:
        snap1 = result.snapshots_before.get(sym)
        snap2 = result.snapshots_after.get(sym)
        bl1 = snap1.bl_result if snap1 else None
        bl2 = snap2.bl_result if snap2 else None
        if bl1 and bl2:
            fwd_syms.append(sym)
            fwd1_vals.append(bl1.input.forward_rate)
            fwd2_vals.append(bl2.input.forward_rate)

    if fwd_syms:
        x = np.arange(len(fwd_syms))
        ax_fwd.plot(x, fwd1_vals, "o-", color="#1f77b4", linewidth=2, markersize=7, label=label1)
        ax_fwd.plot(x, fwd2_vals, "s-", color="#d62728", linewidth=2, markersize=7, label=label2)
        # Annotate deltas
        for i, (f1, f2) in enumerate(zip(fwd1_vals, fwd2_vals)):
            delta = f2 - f1
            sign = "+" if delta >= 0 else ""
            color = "green" if delta <= 0 else "red"  # lower rate = easing = green
            ax_fwd.annotate(
                f"{sign}{delta:.2f}%",
                xy=(i, f2),
                xytext=(0, 12),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                fontweight="bold",
                color=color,
            )
        ax_fwd.set_xticks(x)
        ax_fwd.set_xticklabels(fwd_syms, fontsize=9)
        ax_fwd.legend(fontsize=9)
    ax_fwd.set_title("Forward Rate Curve Shift", fontsize=11)
    ax_fwd.set_ylabel("Rate (%)")
    ax_fwd.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax_fwd.grid(True, alpha=0.3)

    # ── Row 0, Right: Scenario weight change heatmap ─────────────────────
    ax_heat = fig.add_subplot(gs[0, 1])
    _plot_strip_weight_heatmap(result, ax=ax_heat, label1=label1, label2=label2)

    # ── Rows 1..N: Per-contract density shift + weight bars ──────────────
    for i, sym in enumerate(result.symbols):
        row = i + 1
        snap1 = result.snapshots_before.get(sym)
        snap2 = result.snapshots_after.get(sym)

        # Left: BL density overlay
        ax_dens = fig.add_subplot(gs[row, 0])
        _plot_contract_density_shift(snap1, snap2, sym=sym, ax=ax_dens, label1=label1, label2=label2)

        # Right: GM weight comparison
        ax_wt = fig.add_subplot(gs[row, 1])
        _plot_contract_weight_comparison(snap1, snap2, sym=sym, ax=ax_wt, label1=label1, label2=label2)

    # ── Bottom row: Summary table ────────────────────────────────────────
    ax_tbl = fig.add_subplot(gs[n_rows - 1, :])
    ax_tbl.axis("off")
    _plot_strip_summary_table(result, ax=ax_tbl, label1=label1, label2=label2)

    return fig


def _plot_strip_weight_heatmap(
    result: StripComparisonResult,
    *,
    ax: plt.Axes,
    label1: str,
    label2: str,
) -> None:
    """Scenario weight delta heatmap: contracts on y-axis, scenarios on x-axis."""
    # Collect scenario labels from the first available GM result
    scenario_labels = None
    for sym in result.symbols:
        for snap_dict in [result.snapshots_after, result.snapshots_before]:
            snap = snap_dict.get(sym)
            if snap and snap.gm_result:
                scenario_labels = [s.label for s in snap.gm_result.scenarios]
                break
        if scenario_labels:
            break

    if scenario_labels is None:
        ax.text(0.5, 0.5, "No GM results available", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Scenario Weight Changes (\u0394pp)")
        return

    n_syms = len(result.symbols)
    n_scen = len(scenario_labels)
    delta_matrix = np.full((n_syms, n_scen), np.nan)

    for i, sym in enumerate(result.symbols):
        snap1 = result.snapshots_before.get(sym)
        snap2 = result.snapshots_after.get(sym)
        gm1 = snap1.gm_result if snap1 else None
        gm2 = snap2.gm_result if snap2 else None
        if gm1 and gm2:
            w1_map = {s.label: float(w) for s, w in zip(gm1.scenarios, gm1.weights)}
            w2_map = {s.label: float(w) for s, w in zip(gm2.scenarios, gm2.weights)}
            for j, lbl in enumerate(scenario_labels):
                w1 = w1_map.get(lbl, 0.0)
                w2 = w2_map.get(lbl, 0.0)
                delta_matrix[i, j] = (w2 - w1) * 100  # percentage points

    # Plot heatmap
    vmax = np.nanmax(np.abs(delta_matrix)) if not np.all(np.isnan(delta_matrix)) else 10
    vmax = max(vmax, 1.0)
    im = ax.imshow(delta_matrix, cmap="RdYlGn_r", aspect="auto", vmin=-vmax, vmax=vmax)

    ax.set_xticks(range(n_scen))
    ax.set_xticklabels([_shorten_scenario_label(lbl) for lbl in scenario_labels], fontsize=7, rotation=45, ha="right")
    ax.set_yticks(range(n_syms))
    ax.set_yticklabels(result.symbols, fontsize=9)

    # Annotate cells
    for i in range(n_syms):
        for j in range(n_scen):
            val = delta_matrix[i, j]
            if not np.isnan(val) and abs(val) >= 0.5:
                sign = "+" if val > 0 else ""
                ax.text(j, i, f"{sign}{val:.1f}", ha="center", va="center", fontsize=7, fontweight="bold")

    plt.colorbar(im, ax=ax, label="\u0394 Weight (pp)", shrink=0.8)
    ax.set_title(f"Scenario Weight Changes ({label1} \u2192 {label2})", fontsize=11)


def _shorten_scenario_label(label: str) -> str:
    """Shorten scenario labels for heatmap display."""
    # e.g. "3 cuts (3.58%)" -> "3 cuts"
    paren_idx = label.find("(")
    if paren_idx > 0:
        return label[:paren_idx].strip()
    return label


def _plot_contract_density_shift(
    snap1: Optional[ImpliedDistributionSnapshot],
    snap2: Optional[ImpliedDistributionSnapshot],
    *,
    sym: str,
    ax: plt.Axes,
    label1: str,
    label2: str,
) -> None:
    """Single-contract BL density overlay (compact version)."""
    bl1 = snap1.bl_result if snap1 else None
    bl2 = snap2.bl_result if snap2 else None

    if bl1 is not None and bl2 is not None:
        # Common grid
        lo = min(bl1.strike_grid_rate[0], bl2.strike_grid_rate[0])
        hi = max(bl1.strike_grid_rate[-1], bl2.strike_grid_rate[-1])
        common = np.linspace(lo, hi, 1500)
        d1 = np.interp(common, bl1.strike_grid_rate, bl1.rnd_density)
        d2 = np.interp(common, bl2.strike_grid_rate, bl2.rnd_density)

        ax.plot(common, d1, color="#1f77b4", linewidth=1.5, label=label1)
        ax.plot(common, d2, color="#d62728", linewidth=1.5, label=label2)
        diff = d2 - d1
        ax.fill_between(common, d1, d2, where=diff > 0, alpha=0.2, color="green")
        ax.fill_between(common, d1, d2, where=diff < 0, alpha=0.2, color="red")

        # Forward lines
        ax.axvline(bl1.input.forward_rate, color="#1f77b4", linestyle="--", linewidth=0.7, alpha=0.5)
        ax.axvline(bl2.input.forward_rate, color="#d62728", linestyle="--", linewidth=0.7, alpha=0.5)

        # Set visible range
        vis_lo = min(bl1.percentile(1), bl2.percentile(1))
        vis_hi = max(bl1.percentile(99), bl2.percentile(99))
        ax.set_xlim(vis_lo, vis_hi)

        # Annotations
        delta_fwd = bl2.input.forward_rate - bl1.input.forward_rate
        delta_std = bl2.std_rate - bl1.std_rate
        info_text = f"\u0394fwd={delta_fwd:+.2f}%  \u0394\u03c3={delta_std:+.3f}%"
        ax.text(
            0.02,
            0.95,
            info_text,
            transform=ax.transAxes,
            fontsize=7,
            va="top",
            ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.7),
        )
        ax.legend(fontsize=7, loc="upper right")
    elif bl1 is not None or bl2 is not None:
        bl = bl1 or bl2
        lbl = label1 if bl1 else label2
        ax.plot(bl.strike_grid_rate, bl.rnd_density, color="black", linewidth=1.5, label=lbl)
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "No BL data", ha="center", va="center", transform=ax.transAxes)

    ax.set_title(f"{sym} \u2014 Density Shift", fontsize=10)
    ax.set_xlabel("Rate (%)", fontsize=8)
    ax.set_ylabel("Density", fontsize=8)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.grid(True, alpha=0.3)


def _plot_contract_weight_comparison(
    snap1: Optional[ImpliedDistributionSnapshot],
    snap2: Optional[ImpliedDistributionSnapshot],
    *,
    sym: str,
    ax: plt.Axes,
    label1: str,
    label2: str,
) -> None:
    """Single-contract scenario weight comparison (paired horizontal bars)."""
    gm1 = snap1.gm_result if snap1 else None
    gm2 = snap2.gm_result if snap2 else None

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

        for i, (w1, w2, d) in enumerate(zip(w1s, w2s, deltas)):
            x_pos = max(w1, w2) + 1
            if abs(d) >= 0.5:
                sign = "+" if d >= 0 else ""
                color = "green" if d >= 0 else "red"
                ax.text(x_pos, i, f"{sign}{d:.1f}pp", va="center", fontsize=7, color=color, fontweight="bold")

        ax.set_yticks(list(y))
        ax.set_yticklabels([_shorten_scenario_label(lbl) for lbl in labels_s], fontsize=7)
        ax.set_xlabel("Weight (%)", fontsize=8)
        ax.legend(fontsize=7, loc="lower right")
    elif gm1 is not None or gm2 is not None:
        gm = gm1 or gm2
        lbl = label1 if gm1 else label2
        labels_s = [s.label for s in gm.scenarios]
        ws = gm.weights * 100
        y = np.arange(len(labels_s))
        ax.barh(y, ws, color="#1f77b4" if gm1 else "#d62728", alpha=0.8, label=lbl)
        ax.set_yticks(list(y))
        ax.set_yticklabels([_shorten_scenario_label(lbl) for lbl in labels_s], fontsize=7)
        ax.legend(fontsize=7)
    else:
        ax.text(0.5, 0.5, "No GM data", ha="center", va="center", transform=ax.transAxes)

    ax.set_title(f"{sym} \u2014 Scenario Weights", fontsize=10)
    ax.grid(True, axis="x", alpha=0.3)


def _plot_strip_summary_table(
    result: StripComparisonResult,
    *,
    ax: plt.Axes,
    label1: str,
    label2: str,
) -> None:
    """Summary statistics table across the strip."""
    rows = []
    for sym in result.symbols:
        snap1 = result.snapshots_before.get(sym)
        snap2 = result.snapshots_after.get(sym)
        bl1 = snap1.bl_result if snap1 else None
        bl2 = snap2.bl_result if snap2 else None

        if bl1 and bl2:
            rows.append(
                [
                    sym,
                    f"{bl1.input.forward_rate:.3f}%",
                    f"{bl2.input.forward_rate:.3f}%",
                    f"{bl2.input.forward_rate - bl1.input.forward_rate:+.3f}%",
                    f"{bl1.mean_rate:.3f}%",
                    f"{bl2.mean_rate:.3f}%",
                    f"{bl2.mean_rate - bl1.mean_rate:+.3f}%",
                    f"{bl1.std_rate:.3f}%",
                    f"{bl2.std_rate:.3f}%",
                    f"{bl2.std_rate - bl1.std_rate:+.3f}%",
                ]
            )
        elif bl1 or bl2:
            bl = bl1 or bl2
            is_before = bl1 is not None
            fwd = f"{bl.input.forward_rate:.3f}%"
            mean = f"{bl.mean_rate:.3f}%"
            std = f"{bl.std_rate:.3f}%"
            rows.append(
                [
                    sym,
                    fwd if is_before else "\u2014",
                    "\u2014" if is_before else fwd,
                    "\u2014",
                    mean if is_before else "\u2014",
                    "\u2014" if is_before else mean,
                    "\u2014",
                    std if is_before else "\u2014",
                    "\u2014" if is_before else std,
                    "\u2014",
                ]
            )

    if not rows:
        ax.text(0.5, 0.5, "No BL data for summary", ha="center", va="center", transform=ax.transAxes)
        return

    col_labels = [
        "Contract",
        f"Fwd\n{label1}",
        f"Fwd\n{label2}",
        "\u0394Fwd",
        f"Mean\n{label1}",
        f"Mean\n{label2}",
        "\u0394Mean",
        f"Std\n{label1}",
        f"Std\n{label2}",
        "\u0394Std",
    ]
    table = ax.table(
        cellText=rows,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.5)

    # Color delta columns (indices 3, 6, 9)
    delta_cols = [3, 6, 9]
    for i in range(len(rows)):
        for dc in delta_cols:
            cell = table[i + 1, dc]
            val_str = rows[i][dc]
            if val_str.startswith("+"):
                cell.set_text_props(color="red", fontweight="bold")  # rate increase = hawkish
            elif val_str.startswith("-"):
                cell.set_text_props(color="green", fontweight="bold")  # rate decrease = dovish

    # Header styling
    for j in range(len(col_labels)):
        cell = table[0, j]
        cell.set_text_props(fontweight="bold", fontsize=7)
        cell.set_facecolor("#e6e6e6")

    ax.set_title(f"Strip Summary \u2014 {label1} \u2192 {label2}", fontsize=11, pad=15)


def plot_sabr_smiles(
    smiles,
    labels=None,
    *,
    align_atm=True,
    y_mode="vol",  # "vol", "vol_minus_atm", "vol_ratio_to_atm"
    use_market_points=True,
    use_sabr_fit=True,
    strike_pad_rate=0.10,  # in rate units, e.g. 0.10 = 10bp
    n_grid=400,
    annotate=False,
    figsize=(11, 7),
    title=None,
):
    """
    Plot one or more STIRFutureOptionSABRSmile objects.

    Parameters
    ----------
    smiles : list
        List of STIRFutureOptionSABRSmile objects.
    labels : list[str] | None
        Optional legend labels. Defaults to "{symbol} | {as_of}".
    align_atm : bool
        If True, x-axis is strike rate relative to ATM forward rate.
        If False, x-axis is absolute strike rate.
    y_mode : str
        "vol"              -> plot normal vol in bps
        "vol_minus_atm"    -> plot vol - ATM vol in bps
        "vol_ratio_to_atm" -> plot vol / ATM vol
    use_market_points : bool
        Plot market smile points.
    use_sabr_fit : bool
        Plot fitted SABR curve.
    strike_pad_rate : float
        Padding for SABR fit grid in strike-rate units.
    n_grid : int
        Number of points in smooth SABR curve.
    annotate : bool
        Annotate market points with option labels.
    """

    def _default_label(smile):
        return f"{smile.symbol} | {smile.params.as_of}"

    def _dedupe_points(points):
        # Some smiles may contain duplicated strikes / duplicated deltas.
        # Keep first occurrence for plotting cleanliness.
        seen = set()
        out = []
        for p in sorted(points, key=lambda p: (p.strike_rate, p.right, p.label)):
            key = (round(float(p.strike_rate), 10), p.right)
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _atm_vol_from_points(points, fwd_rate):
        # Prefer explicit ATM point if present; otherwise interpolate nearest strike.
        pts_sorted = sorted(points, key=lambda p: abs(p.strike_rate - fwd_rate))
        if not pts_sorted:
            raise ValueError("Smile has no points.")
        return pts_sorted[0].iv_normal_bps

    if labels is None:
        labels = [_default_label(smile) for smile in smiles]

    if len(labels) != len(smiles):
        raise ValueError("labels must have same length as smiles")

    fig, ax = plt.subplots(figsize=figsize)

    for smile, label in zip(smiles, labels):
        pts = _dedupe_points(smile.points)
        if not pts:
            continue

        fwd = float(smile.params.forward_rate)
        atm_vol = _atm_vol_from_points(pts, fwd)

        put_pts = [p for p in pts if p.right == "P"]
        call_pts = [p for p in pts if p.right == "C"]

        # Smooth strike grid in absolute strike-rate space for model eval
        x_min_abs = min(p.strike_rate for p in pts) - strike_pad_rate
        x_max_abs = max(p.strike_rate for p in pts) + strike_pad_rate
        strike_grid_abs = np.linspace(x_min_abs, x_max_abs, n_grid)

        # SABR fitted vols
        if use_sabr_fit:
            sabr_vols = np.asarray(
                smile.normal_vol(
                    strike_grid_abs,
                    strike_space="rate",
                    vol_units="bps",
                )
            )

            if y_mode == "vol":
                y_fit = sabr_vols
                y_label = "Normal Vol (bps)"
            elif y_mode == "vol_minus_atm":
                y_fit = sabr_vols - atm_vol
                y_label = "Normal Vol - ATM Vol (bps)"
            elif y_mode == "vol_ratio_to_atm":
                y_fit = sabr_vols / atm_vol
                y_label = "Normal Vol / ATM Vol"
            else:
                raise ValueError("y_mode must be one of: vol, vol_minus_atm, vol_ratio_to_atm")

            x_fit = strike_grid_abs - fwd if align_atm else strike_grid_abs
            (line,) = ax.plot(x_fit, y_fit, lw=2, label=f"{label} SABR")

        # Market points
        if use_market_points:

            def _transform_point_y(p):
                vol = p.iv_normal_bps
                if y_mode == "vol":
                    return vol
                elif y_mode == "vol_minus_atm":
                    return vol - atm_vol
                elif y_mode == "vol_ratio_to_atm":
                    return vol / atm_vol
                else:
                    raise ValueError("invalid y_mode")

            def _transform_point_x(p):
                return p.strike_rate - fwd if align_atm else p.strike_rate

            call_x = [_transform_point_x(p) for p in call_pts]
            call_y = [_transform_point_y(p) for p in call_pts]
            put_x = [_transform_point_x(p) for p in put_pts]
            put_y = [_transform_point_y(p) for p in put_pts]

            # Match scatter color to fitted line color if line exists
            scatter_kwargs = {}
            if use_sabr_fit:
                scatter_kwargs["color"] = line.get_color()

            ax.scatter(call_x, call_y, marker="o", s=40, **scatter_kwargs)
            ax.scatter(put_x, put_y, marker="x", s=40, **scatter_kwargs)

            if annotate:
                for p in pts:
                    ax.annotate(
                        p.label.split("|")[-1],
                        (_transform_point_x(p), _transform_point_y(p)),
                        xytext=(4, 4),
                        textcoords="offset points",
                        fontsize=8,
                    )

    # ATM reference
    if align_atm:
        ax.axvline(0.0, ls="--", lw=1)
        ax.set_xlabel("Strike Relative to ATM Forward Rate")
    else:
        ax.set_xlabel("Strike Rate")

    if y_mode == "vol":
        ax.set_ylabel("Normal Vol (bps)")
    elif y_mode == "vol_minus_atm":
        ax.set_ylabel("Normal Vol - ATM Vol (bps)")
        ax.axhline(0.0, ls="--", lw=1, alpha=0.7)
    elif y_mode == "vol_ratio_to_atm":
        ax.set_ylabel("Normal Vol / ATM Vol")
        ax.axhline(1.0, ls="--", lw=1, alpha=0.7)

    if title is None:
        # title = "SABR Smile Comparison"
        unique_symbols = sorted({smile.symbol for smile in smiles})
        symbol_str = unique_symbols[0] if len(unique_symbols) == 1 else " / ".join(unique_symbols)
        title = f"{symbol_str} SABR fit"
        if align_atm:
            title += " (ATM-aligned)"
        if y_mode == "vol_minus_atm":
            title += " | ATM-normalized level"
        elif y_mode == "vol_ratio_to_atm":
            title += " | ATM ratio"

    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    return fig, ax


def plot_sfr_smile(smile):
    pts = sorted(smile.points, key=lambda p: p.strike_rate)

    # In rate/yield strike space:
    # C = receiver wing (left / lower strikes)
    # P = payer wing   (right / higher strikes)
    receiver_pts = [p for p in pts if p.right == "C"]
    payer_pts = [p for p in pts if p.right == "P"]

    # Smooth strike grid in rate space
    x_min = min(p.strike_rate for p in pts) - 0.10
    x_max = max(p.strike_rate for p in pts) + 0.10
    strike_grid = np.linspace(x_min, x_max, 400)

    # Model vols from fitted SABR smile
    sabr_vols_bps = smile.normal_vol(
        strike_grid,
        strike_space="rate",
        vol_units="bps",
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    # Smooth SABR curve
    ax.plot(
        strike_grid,
        sabr_vols_bps,
        color="black",
        lw=2,
        label="SABR fit",
    )

    # Market vols
    ax.scatter(
        [p.strike_rate for p in receiver_pts],
        [p.iv_normal_bps for p in receiver_pts],
        color="tab:blue",
        s=40,
        label="Receiver market vols",
    )
    ax.scatter(
        [p.strike_rate for p in payer_pts],
        [p.iv_normal_bps for p in payer_pts],
        color="tab:orange",
        s=40,
        label="Payer market vols",
    )

    ax.axvline(
        smile.params.forward_rate,
        color="gray",
        ls="--",
        lw=1,
        label="ATM",
    )

    for p in pts:
        ax.annotate(
            p.label.split("|")[-1],
            (p.strike_rate, p.iv_normal_bps),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=8,
        )

    ax.set_title(f"{smile.symbol} SABR Smile as of {smile.params.as_of}")
    ax.set_xlabel("Strike Rate")
    ax.set_ylabel("Normal Vol (bps)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.show()
