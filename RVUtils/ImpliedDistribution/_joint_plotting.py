"""Visualization helpers for the common-state joint strip distribution."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from scipy.ndimage import gaussian_filter

from RVUtils.ImpliedDistribution._joint_analytics import conditional_distribution, linear_combination_distribution
from RVUtils.ImpliedDistribution._types import JointDistributionComparison, JointDistributionSnapshot, ViewMetadata


def _title_with_meta(base: str, metadata: ViewMetadata, *, title: Optional[str] = None) -> str:
    prefix = title or base
    return f"{prefix}\n[{metadata.display_label()}]"


def _heatmap_ticks(values) -> list[str]:
    return [f"{float(v):.3f}%" for v in values]


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    threshold = float(q) * float(np.sum(weights))
    idx = int(np.searchsorted(cumulative, threshold, side="left"))
    idx = min(max(idx, 0), len(values) - 1)
    return float(values[idx])


def plot_joint_probability_heatmap(
    snapshot: JointDistributionSnapshot,
    symbol_x: str,
    symbol_y: str,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    annotate: bool = True,
    cmap: str = "Blues",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 6))
    view = snapshot.pair_joint_matrix(symbol_x, symbol_y)
    matrix = view.data
    data = matrix.to_numpy(dtype=float)
    im = ax.imshow(data, cmap=cmap, aspect="auto")
    ax.set_xticks(range(matrix.shape[1]))
    ax.set_xticklabels(_heatmap_ticks(matrix.columns), rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(matrix.shape[0]))
    ax.set_yticklabels(_heatmap_ticks(matrix.index), fontsize=8)
    ax.set_xlabel(str(symbol_y).upper())
    ax.set_ylabel(str(symbol_x).upper())
    ax.set_title(_title_with_meta(f"Joint Probability Heatmap: {symbol_x} vs {symbol_y}", view.metadata, title=title), fontsize=10)
    if annotate:
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                val = data[i, j]
                if val >= 0.005:
                    ax.text(j, i, f"{val:.1%}", ha="center", va="center", fontsize=7, fontweight="bold")
    plt.colorbar(im, ax=ax, label="Probability")
    return ax


def plot_joint_probability_change_heatmap(
    comparison: JointDistributionComparison,
    symbol_x: str,
    symbol_y: str,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    annotate: bool = True,
    cmap: str = "RdBu_r",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 6))
    view = comparison.pair_joint_delta(symbol_x, symbol_y)
    matrix = view.data
    data = matrix.to_numpy(dtype=float)
    vmax = max(float(np.max(np.abs(data))) if data.size else 0.0, 0.01)
    im = ax.imshow(data, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(matrix.shape[1]))
    ax.set_xticklabels(_heatmap_ticks(matrix.columns), rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(matrix.shape[0]))
    ax.set_yticklabels(_heatmap_ticks(matrix.index), fontsize=8)
    ax.set_xlabel(str(symbol_y).upper())
    ax.set_ylabel(str(symbol_x).upper())
    ax.set_title(_title_with_meta(f"Joint Probability Change: {symbol_x} vs {symbol_y}", view.metadata, title=title), fontsize=10)
    if annotate:
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                val = data[i, j]
                if abs(val) >= 0.005:
                    sign = "+" if val >= 0 else ""
                    ax.text(j, i, f"{sign}{val:.1%}", ha="center", va="center", fontsize=7, fontweight="bold")
    plt.colorbar(im, ax=ax, label="Δ Probability")
    return ax


def plot_conditional_distribution(
    snapshot: JointDistributionSnapshot,
    target_symbol: str,
    given_symbol: str,
    *,
    given_values=None,
    given_range: Optional[Tuple[float, float]] = None,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    color: str = "#1f77b4",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 4))
    view = conditional_distribution(
        snapshot,
        target_symbol=target_symbol,
        given_symbol=given_symbol,
        given_values=given_values,
        given_range=given_range,
    )
    payload = view.data
    df = payload["distribution"]
    ax.bar(df[str(target_symbol).upper()].astype(str), df["probability"] * 100.0, color=color, alpha=0.85)
    ax.set_ylabel("Probability (%)")
    ax.set_xlabel(str(target_symbol).upper())
    ax.set_title(_title_with_meta(f"{target_symbol} | {given_symbol} condition", view.metadata, title=title), fontsize=10)
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    selector = payload["selector"]
    ax.text(
        0.02,
        0.98,
        f"Cond mass={payload['conditioning_probability']:.1%}\n{selector}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", alpha=0.75),
    )
    ax.grid(True, axis="y", alpha=0.3)
    return ax


def plot_linear_combination_distribution(
    snapshot: JointDistributionSnapshot,
    *,
    weights: Dict[str, float],
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    color: str = "#ff7f0e",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 4))
    view = linear_combination_distribution(snapshot, weights=weights)
    df = view.data
    ax.bar(df["linear_combination"].astype(str), df["probability"] * 100.0, color=color, alpha=0.85)
    ax.set_ylabel("Probability (%)")
    ax.set_xlabel("Linear combination")
    ax.set_title(_title_with_meta("Linear-combination distribution", view.metadata, title=title), fontsize=10)
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(True, axis="y", alpha=0.3)
    return ax


def plot_empirical_copula(
    snapshot: JointDistributionSnapshot,
    symbol_x: str,
    symbol_y: str,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    cmap: str = "viridis",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 6))
    view = snapshot.empirical_copula(symbol_x, symbol_y)
    df = view.data
    sc = ax.scatter(df["u"], df["v"], c=df["weight"], cmap=cmap, s=50 + df["weight"] * 800, alpha=0.8, edgecolor="black", linewidth=0.3)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel(f"{str(symbol_x).upper()} pseudo-U")
    ax.set_ylabel(f"{str(symbol_y).upper()} pseudo-U")
    ax.set_title(_title_with_meta(f"Empirical Copula: {symbol_x} vs {symbol_y}", view.metadata, title=title), fontsize=10)
    ax.grid(True, alpha=0.3)
    plt.colorbar(sc, ax=ax, label="State weight")
    return ax


def plot_joint_contour(
    snapshot: JointDistributionSnapshot,
    symbol_x: str,
    symbol_y: str,
    *,
    ax: Optional[plt.Axes] = None,
    title: Optional[str] = None,
    smoothing_sigma: float = 0.75,
    cmap: str = "magma",
) -> plt.Axes:
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 6))
    view = snapshot.pair_joint_matrix(symbol_x, symbol_y)
    matrix = view.data
    data = matrix.to_numpy(dtype=float)
    if data.size == 0:
        ax.text(0.5, 0.5, "No joint mass", ha="center", va="center", transform=ax.transAxes)
        return ax
    smoothed = gaussian_filter(data, sigma=smoothing_sigma)
    x = np.arange(matrix.shape[1])
    y = np.arange(matrix.shape[0])
    contour = ax.contourf(x, y, smoothed, levels=12, cmap=cmap)
    ax.set_xticks(x)
    ax.set_xticklabels(_heatmap_ticks(matrix.columns), rotation=45, ha="right", fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels(_heatmap_ticks(matrix.index), fontsize=8)
    ax.set_xlabel(str(symbol_y).upper())
    ax.set_ylabel(str(symbol_x).upper())
    meta = snapshot.provenance.get("joint_contour", view.metadata)
    ax.set_title(_title_with_meta(f"Smoothed Joint Contour: {symbol_x} vs {symbol_y}", meta, title=title), fontsize=10)
    plt.colorbar(contour, ax=ax, label="Smoothed mass")
    return ax


def plot_joint_comparison_dashboard(
    comparison: JointDistributionComparison,
    symbol_x: str,
    symbol_y: str,
    *,
    spread_weights: Optional[Dict[str, float]] = None,
    figsize: Tuple[int, int] = (18, 14),
) -> plt.Figure:
    fig, axes = plt.subplots(3, 2, figsize=figsize)
    fig.suptitle(
        f"Joint Comparison Dashboard: {symbol_x} / {symbol_y}\n{comparison.date_before} → {comparison.date_after}",
        fontsize=14,
        fontweight="bold",
    )

    plot_joint_probability_heatmap(
        comparison.snapshot_after,
        symbol_x,
        symbol_y,
        ax=axes[0, 0],
        title=f"{comparison.date_after} joint heatmap",
    )
    plot_joint_probability_change_heatmap(
        comparison,
        symbol_x,
        symbol_y,
        ax=axes[0, 1],
        title=f"{comparison.date_before} → {comparison.date_after} joint delta",
    )

    x_idx_before = comparison.snapshot_before.symbol_index(symbol_x)
    x_before = comparison.snapshot_before.contract_rate_matrix[:, x_idx_before]
    w_before = comparison.snapshot_before.state_weights
    q75_before = _weighted_quantile(x_before, w_before, 0.75)

    cond_before = comparison.snapshot_before.conditional_distribution(
        target_symbol=symbol_y,
        given_symbol=symbol_x,
        given_range=(q75_before, float(np.max(x_before))),
    ).data
    cond_after = comparison.snapshot_after.conditional_distribution(
        target_symbol=symbol_y,
        given_symbol=symbol_x,
        given_range=(q75_before, float(np.max(comparison.snapshot_after.contract_rate_matrix[:, comparison.snapshot_after.symbol_index(symbol_x)]))),
    ).data
    ax = axes[1, 0]
    df_before = cond_before["distribution"].set_index(str(symbol_y).upper())["probability"]
    df_after = cond_after["distribution"].set_index(str(symbol_y).upper())["probability"]
    aligned = df_before.to_frame("before").join(df_after.rename("after"), how="outer").fillna(0.0)
    x_pos = np.arange(len(aligned.index))
    bar_w = 0.4
    ax.bar(x_pos - bar_w / 2, aligned["before"] * 100.0, bar_w, label=str(comparison.date_before), color="#1f77b4")
    ax.bar(x_pos + bar_w / 2, aligned["after"] * 100.0, bar_w, label=str(comparison.date_after), color="#d62728")
    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"{float(v):.3f}%" for v in aligned.index], rotation=45, ha="right", fontsize=8)
    ax.set_title(
        f"{symbol_y} | {symbol_x} upper-tail condition\n[{comparison.snapshot_after.provenance['conditional_distribution'].display_label()}]",
        fontsize=10,
    )
    ax.set_ylabel("Probability (%)")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)

    spread_weights = spread_weights or {str(symbol_y).upper(): 1.0, str(symbol_x).upper(): -1.0}
    spread_before = linear_combination_distribution(comparison.snapshot_before, weights=spread_weights).data.set_index("linear_combination")["probability"]
    spread_after = linear_combination_distribution(comparison.snapshot_after, weights=spread_weights).data.set_index("linear_combination")["probability"]
    ax = axes[1, 1]
    aligned_spread = spread_before.to_frame("before").join(spread_after.rename("after"), how="outer").fillna(0.0)
    x_pos = np.arange(len(aligned_spread.index))
    ax.plot(x_pos, aligned_spread["before"] * 100.0, marker="o", color="#1f77b4", label=str(comparison.date_before))
    ax.plot(x_pos, aligned_spread["after"] * 100.0, marker="s", color="#d62728", label=str(comparison.date_after))
    ax.set_xticks(x_pos)
    ax.set_xticklabels([f"{float(v):+.3f}" for v in aligned_spread.index], rotation=45, ha="right", fontsize=8)
    ax.set_title(
        f"Spread / linear combination\n[{comparison.snapshot_after.provenance['linear_combination_distribution'].display_label()}]",
        fontsize=10,
    )
    ax.set_ylabel("Probability (%)")
    ax.legend(fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)

    ax = axes[2, 0]
    copula_before = comparison.snapshot_before.empirical_copula(symbol_x, symbol_y).data
    copula_after = comparison.snapshot_after.empirical_copula(symbol_x, symbol_y).data
    ax.scatter(copula_before["u"], copula_before["v"], s=40 + copula_before["weight"] * 500, alpha=0.5, label=str(comparison.date_before), color="#1f77b4")
    ax.scatter(copula_after["u"], copula_after["v"], s=40 + copula_after["weight"] * 500, alpha=0.5, label=str(comparison.date_after), color="#d62728")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel(f"{str(symbol_x).upper()} pseudo-U")
    ax.set_ylabel(f"{str(symbol_y).upper()} pseudo-U")
    ax.set_title(
        f"Empirical copula comparison\n[{comparison.snapshot_after.provenance['empirical_copula'].display_label()}]",
        fontsize=10,
    )
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    ax = axes[2, 1]
    ax.axis("off")
    mean_delta = comparison.mean_vector_change().data
    corr_delta = comparison.correlation_change().data
    top_changes = comparison.top_pair_cell_changes(symbol_x, symbol_y, n=6).data
    summary_lines = [
        "Summary",
        f"Δ mean {symbol_x}: {mean_delta[str(symbol_x).upper()]:+.4f}%",
        f"Δ mean {symbol_y}: {mean_delta[str(symbol_y).upper()]:+.4f}%",
        f"Δ corr: {corr_delta.loc[str(symbol_x).upper(), str(symbol_y).upper()]:+.4f}",
        "",
        "Top cell changes",
    ]
    for _, row in top_changes.iterrows():
        summary_lines.append(
            f"({row[str(symbol_x).upper()]:.3f}%, {row[str(symbol_y).upper()]:.3f}%)  {row['delta_probability']:+.1%}"
        )
    ax.text(
        0.01,
        0.99,
        "\n".join(summary_lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        family="monospace",
    )

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig
