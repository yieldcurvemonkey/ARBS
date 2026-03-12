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
