"""Matplotlib views for fly-vs-vol snapshots and history.

Palette discipline: one data hue (blue) for densities/bars, one accent (orange)
for reference markers (entry, heuristic), gray for zero/quantile guides. One
axis per panel; history uses small multiples on a shared x.
"""
from __future__ import annotations

from typing import Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from RVUtils.FlyVsVol._types import FlySnapshot
from RVUtils.FlyVsVol.coupling import comonotone_grid

__all__ = ["plot_fly_distribution", "plot_move_table", "plot_history_panel"]

_DATA = "#1f77b4"
_ACCENT = "#ff7f0e"
_GUIDE = "#7f7f7f"


def _style(ax: plt.Axes) -> None:
    ax.grid(True, alpha=0.25, linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def plot_fly_distribution(
    snapshot: FlySnapshot, *, entry_bp: Optional[float] = None, ax: Optional[plt.Axes] = None
) -> plt.Axes:
    """Histogram of the comonotone fly settlement ``phi`` with entry + quantiles."""
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    rates = comonotone_grid(snapshot.legs, n=20001)
    phi = (2 * rates[:, 1] - rates[:, 0] - rates[:, 2]) * 100.0
    lo, hi = np.percentile(phi, [0.5, 99.5])
    ax.hist(phi, bins=np.linspace(lo, hi, 80), density=True,
            color=_DATA, alpha=0.85, edgecolor="white", linewidth=0.3)
    q = snapshot.comonotone.phi_quantiles_bp
    for p in (5, 50, 95):
        ax.axvline(q[p], color=_GUIDE, linewidth=0.9, linestyle=":", zorder=3)
        ax.annotate(f"p{p}", (q[p], ax.get_ylim()[1] * 0.97), fontsize=8,
                    color=_GUIDE, ha="left", va="top", rotation=90)
    entry = snapshot.fly_bp if entry_bp is None else entry_bp
    ax.axvline(entry, color=_ACCENT, linewidth=1.6,
               label=f"fly entry {entry:+.1f}bp")
    ax.axvline(snapshot.fly_median_path_bp, color=_ACCENT, linewidth=1.1,
               linestyle="--",
               label=f"median-path fly {snapshot.fly_median_path_bp:+.1f}bp")
    ax.set_xlabel("fly settlement (bp)")
    ax.set_ylabel("density")
    ax.set_title(
        f"{snapshot.fly.label}  phi distribution (comonotone)"
        + (f"  as of {snapshot.as_of}" if snapshot.as_of else "")
    )
    ax.legend(frameon=False, fontsize=9)
    _style(ax)
    return ax


def plot_move_table(snapshot: FlySnapshot, *, ax: Optional[plt.Axes] = None) -> plt.Axes:
    """P(N1 - N2 = j) bars vs the fly/25 heuristic annotation."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 4.5))
    table = {j: p for j, p in sorted(snapshot.comonotone.dn_table.items())
             if p >= 0.002}
    js = list(table.keys())
    ax.bar(js, [table[j] for j in js], color=_DATA, width=0.72)
    for j, p in table.items():
        if p >= 0.02:
            ax.annotate(f"{p:.0%}", (j, p), ha="center", va="bottom", fontsize=8)
    c = snapshot.comonotone
    ax.set_title(
        f"{snapshot.fly.label}  P(N1-N2=j) | heuristic fly/25={snapshot.heuristic_prob:+.2f}"
        f", model prob-delta={c.prob_delta:+.2f}"
    )
    ax.set_xlabel("extra 25bp moves in window 1 vs window 2 (j)")
    ax.set_ylabel("probability")
    ax.set_xticks(js)
    _style(ax)
    return ax


def plot_history_panel(
    history: pd.DataFrame,
    label: str,
    *,
    cols: Sequence[str] = ("fly_bp", "fly_median_path_bp", "tail_rent_bp", "heuristic_gap"),
    figsize=(14, 9),
) -> plt.Figure:
    """Small-multiple time series of screener metrics for one triple.

    ``fly_bp`` and ``fly_median_path_bp`` share the first panel; every other
    column gets its own panel (z-score columns included if present in ``cols``).
    """
    sub = history[history["label"] == label].sort_values("as_of")
    if sub.empty:
        raise ValueError(f"no history rows for label {label!r}")
    overlay = [c for c in ("fly_bp", "fly_median_path_bp") if c in cols]
    singles = [c for c in cols if c not in overlay]
    n_panels = (1 if overlay else 0) + len(singles)
    fig, axes = plt.subplots(n_panels, 1, figsize=figsize, sharex=True, squeeze=False)
    axes = axes[:, 0]
    i = 0
    if overlay:
        ax = axes[0]
        ax.plot(sub["as_of"], sub[overlay[0]], color=_DATA, linewidth=1.4,
                label=overlay[0])
        if len(overlay) > 1:
            ax.plot(sub["as_of"], sub[overlay[1]], color=_ACCENT, linewidth=1.2,
                    linestyle="--", label=overlay[1])
        ax.axhline(0, color=_GUIDE, linewidth=0.8)
        ax.set_ylabel("bp")
        ax.legend(frameon=False, fontsize=9)
        _style(ax)
        i = 1
    for col in singles:
        ax = axes[i]
        ax.plot(sub["as_of"], sub[col], color=_DATA, linewidth=1.2)
        ax.axhline(0, color=_GUIDE, linewidth=0.8)
        if col.endswith("_z") or col.endswith("_z_full"):
            for lvl in (-2, 2):
                ax.axhline(lvl, color=_ACCENT, linewidth=0.8, linestyle=":")
        ax.set_ylabel(col)
        _style(ax)
        i += 1
    axes[-1].set_xlabel("date")
    fig.suptitle(f"{label} — fly-vs-vol history", y=0.995)
    fig.tight_layout()
    return fig
