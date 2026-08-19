"""Figures for the olds-vs-currents switch study.

Colour follows the validated categorical palette from the ``dataviz`` reference instance.
Slots are assigned by IDENTITY and in fixed order, never cycled: price is always slot 1,
carry always slot 2, cost always slot 8 (red, because it is the term that kills the trade).
A filter that drops a series must not repaint the survivors.

Encoding choices, each by the job the data is doing:

* equity, cycle profile, cost curve -- magnitude/change over time -> line or bar, one axis.
  **Never a second y-axis.** Where two quantities of different scale need comparing
  (e.g. bp against a count) they get separate panels.
* league heatmap -- POLARITY (a Sharpe is good or bad about zero) -> diverging two-hue
  ramp with a NEUTRAL GREY midpoint, not a rainbow and not a hue at zero.
* specialness / premium magnitude -- one-directional -> single-hue sequential.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

# Validated categorical palette (light mode). Slots 1-3 clear the all-pairs CVD gate;
# beyond three, series are folded or faceted rather than cycled onto new hues.
PAL = {
    1: "#2a78d6",  # blue
    2: "#eb6834",  # orange
    3: "#1baf7a",  # aqua
    4: "#eda100",  # yellow
    5: "#e87ba4",  # magenta
    6: "#008300",  # green
    7: "#4a3aa7",  # violet
    8: "#e34948",  # red
}
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8a85"
GRID = "#e3e3df"
SURFACE = "#fcfcfb"

ROLE = {"price": PAL[1], "carry": PAL[2], "special": PAL[7], "cost": PAL[8], "net": INK}


def style():
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK2,
            "axes.titlesize": 11,
            "axes.titleweight": "semibold",
            "axes.titlecolor": INK,
            "axes.grid": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "text.color": INK,
            "font.size": 9,
            "legend.frameon": False,
            "lines.linewidth": 2.0,
            "figure.dpi": 120,
        }
    )
    return plt


def _bar_width_for_dates(idx, cap: int = 400) -> float:
    """matplotlib reads a bare int on a datetime axis as NANOSECONDS, collapsing every
    bar to zero width. House fix, same as BT/trade_dashboard."""
    idx = pd.DatetimeIndex(idx)
    if len(idx) < 2:
        return 1.0
    return (idx.max() - idx.min()).days / max(min(len(idx), cap), 1)


# --------------------------------------------------------------------------------------


def plot_equity(
    results: Dict[str, pd.Series],
    *,
    title: str = "Olds-vs-currents switch: cumulative P&L",
    ax=None,
    highlight: Optional[str] = None,
):
    """Equity curve(s) in BASIS POINTS of a DV01-matched position."""
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 4.2))
    for i, (name, eq) in enumerate(results.items(), start=1):
        is_hi = highlight is None or name == highlight
        ax.plot(
            eq.index, eq.values,
            color=PAL[min(i, 8)] if is_hi else MUTED,
            lw=2.0 if is_hi else 1.0,
            alpha=1.0 if is_hi else 0.45,
            label=name if is_hi or len(results) <= 4 else None,
            zorder=3 if is_hi else 1,
        )
    ax.axhline(0, color=MUTED, lw=1.0, zorder=2)
    ax.set_ylabel("cumulative P&L (bp)")
    ax.set_title(title)
    if len(results) >= 2:
        ax.legend(loc="upper left", ncol=2, fontsize=8)
    return ax


def plot_pnl_decomposition(decomp: pd.DataFrame, *, ax=None, title: str = "Where the P&L came from"):
    """Per-trade attribution. Horizontal bars: identity, not magnitude ordering."""
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(7.5, 3.2))
    d = decomp[decomp["component"] != "  of which specialness"]
    colors = []
    for c in d["component"]:
        key = ("price" if "price" in c else "carry" if "carry" in c
               else "cost" if "cost" in c else "net")
        colors.append(ROLE[key])
    y = np.arange(len(d))
    ax.barh(y, d["per_trade_bp"], color=colors, height=0.6)
    ax.set_yticks(y, d["component"])
    ax.invert_yaxis()
    ax.axvline(0, color=INK2, lw=1.0)
    ax.set_xlabel("bp per trade")
    ax.set_title(title)
    for yi, v in zip(y, d["per_trade_bp"]):
        ax.text(v, yi, f"  {v:+.3f}", va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=INK2)
    ax.grid(axis="y", visible=False)
    return ax


def plot_auction_cycle(profile: pd.DataFrame, *, ax=None, title: str = "Auction-cycle seasonality"):
    """Mean daily P&L by business day since the roll -- the MECHANISM clock.

    Two panels' worth of information on one axis would need two scales, so the count is
    conveyed by bar opacity rather than a second y-axis.
    """
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 3.4))
    if profile.empty:
        ax.text(0.5, 0.5, "no data", ha="center", va="center", transform=ax.transAxes)
        return ax
    n = profile["n"].values.astype(float)
    alpha = 0.25 + 0.75 * (n / n.max())
    # bar() rejects an ARRAY alpha; bake the per-bar alpha into RGBA colours instead.
    from matplotlib.colors import to_rgba

    cols = [
        to_rgba(ROLE["price"] if v >= 0 else ROLE["cost"], a)
        for v, a in zip(profile["mean_pnl_bp"], alpha)
    ]
    ax.bar(profile["cycle_day"], profile["mean_pnl_bp"], color=cols, width=0.85)
    ax.axhline(0, color=INK2, lw=1.0)
    ax.set_xlabel("business days since auction roll")
    ax.set_ylabel("mean P&L (bp/day)")
    ax.set_title(f"{title}  (bar opacity = number of observations)")
    return ax


def plot_cycle_cumulative(profile: pd.DataFrame, *, ax=None):
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 3.0))
    if profile.empty:
        return ax
    ax.plot(profile["cycle_day"], profile["cum_mean_pnl_bp"], color=PAL[1])
    ax.axhline(0, color=MUTED, lw=1.0)
    ax.set_xlabel("business days since auction roll")
    ax.set_ylabel("cumulative mean (bp)")
    ax.set_title("Cumulative mean P&L through the auction cycle")
    return ax


def plot_calendar_seasonality(seas: Dict[str, pd.DataFrame], *, fig=None):
    """Month-of-year, day-of-week and year. Sign is the message -> diverging colours."""
    plt = style()
    if fig is None:
        fig = plt.figure(figsize=(12, 6.5))
    specs = [
        ("month", "Month of year", ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]),
        ("dow", "Day of week", ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        ("year", "Year", None),
        ("dom", "Day of month", None),
    ]
    axes = fig.subplots(2, 2).ravel()
    for ax, (key, title, ticks) in zip(axes, specs):
        d = seas.get(key)
        if d is None or d.empty:
            ax.set_visible(False)
            continue
        x = d[key].values
        v = d["mean_bp_per_day"].values
        cols = [ROLE["price"] if u >= 0 else ROLE["cost"] for u in v]
        ax.bar(range(len(x)), v, color=cols, width=0.75)
        ax.axhline(0, color=INK2, lw=1.0)
        if ticks and len(ticks) == len(x):
            ax.set_xticks(range(len(x)), ticks, fontsize=8)
        else:
            step = max(1, len(x) // 12)
            ax.set_xticks(range(0, len(x), step), [str(u) for u in x[::step]],
                          fontsize=8, rotation=45)
        ax.set_title(title)
        ax.set_ylabel("bp/day")
    fig.suptitle("Calendar seasonality of daily P&L (blue = positive, red = negative)",
                 fontsize=11, color=INK)
    fig.tight_layout()
    return fig


def plot_league_heatmap(league: pd.DataFrame, *, value: str = "sharpe", ax=None,
                        title: Optional[str] = None):
    """tenor x pair. A Sharpe is POLARITY about zero -> diverging, neutral grey midpoint."""
    import matplotlib.colors as mcolors

    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(8.5, 4.2))
    piv = league.pivot_table(index="tenor", columns="pair", values=value, aggfunc="max")
    order = [c for c in ["CTvO", "CTvOO", "CTvOOO", "OvOO", "OvOOO", "OOvOOO"] if c in piv.columns]
    piv = piv[order] if order else piv

    # two hues + neutral grey at zero; never a hue at the midpoint
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "polarity", [ROLE["cost"], "#efeeea", ROLE["price"]]
    )
    lim = float(np.nanmax(np.abs(piv.values))) if piv.size else 1.0
    im = ax.imshow(piv.values, cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(piv.shape[1]), piv.columns, fontsize=8)
    ax.set_yticks(range(piv.shape[0]), [f"{int(t)}Y" for t in piv.index], fontsize=8)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7.5,
                        color=INK if abs(v) < lim * 0.6 else SURFACE)
    ax.grid(False)
    ax.set_title(title or f"Best {value} by tenor and rank pair")
    ax.figure.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label=value)
    return ax


def plot_spread_term_structure(ts_by_tenor: Dict[int, pd.DataFrame], *, ax=None):
    """Yield pickup over the on-the-run by rank. Magnitude -> single-hue sequential."""
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 3.6))
    tenors = sorted(ts_by_tenor)
    width = 0.8 / max(len(tenors), 1)
    shades = plt.get_cmap("Blues")(np.linspace(0.35, 0.9, len(tenors)))
    for i, (t, sh) in enumerate(zip(tenors, shades)):
        d = ts_by_tenor[t]
        if d is None or d.empty:
            continue
        x = np.arange(len(d)) + i * width - 0.4
        ax.bar(x, d["mean_pickup_bp"], width=width * 0.92, color=sh, label=f"{t}Y")
        ax.set_xticks(np.arange(len(d)), [f"rank {int(r)}" for r in d["rank"]], fontsize=8)
    ax.axhline(0, color=INK2, lw=1.0)
    ax.set_ylabel("mean yield pickup vs on-the-run (bp)")
    ax.set_title("What the trade is made of: yield pickup by rank")
    ax.legend(ncol=4, fontsize=8)
    return ax


def plot_cost_curve(curve: pd.DataFrame, *, ax=None, title: str = "Cost curve and break-even"):
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.plot(curve["cost_multiplier"], curve["net_bp_per_trade"], color=PAL[1], marker="o", ms=5)
    ax.axhline(0, color=INK2, lw=1.0)
    pos = curve[curve["net_bp_per_trade"] > 0]
    if not pos.empty and len(pos) < len(curve):
        be = float(pos["cost_multiplier"].max())
        ax.axvline(be, color=ROLE["cost"], lw=1.5, ls="--")
        ax.text(be, ax.get_ylim()[1], f" break-even ~{be:g}x ", va="top", fontsize=8,
                color=ROLE["cost"])
    ax.axvline(1.0, color=MUTED, lw=1.0, ls=":")
    ax.set_xlabel("multiple of the SR1170 cost assumption")
    ax.set_ylabel("net bp per trade")
    ax.set_title(title)
    return ax


def plot_specialness(panel: pd.DataFrame, *, ax=None, tenors: Sequence[int] = (2, 5, 10, 20, 30)):
    """Measured specialness by rank. Magnitude -> single hue."""
    plt = style()
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 3.4))
    d = panel[panel["has_actual_financing"]] if "has_actual_financing" in panel else panel
    g = d[d["tenor"].isin(tenors)].groupby(["tenor", "rank"])["special_actual_bp"].mean().unstack()
    shades = plt.get_cmap("Blues")(np.linspace(0.35, 0.9, g.shape[1]))
    x = np.arange(len(g))
    w = 0.8 / max(g.shape[1], 1)
    for j, (r, sh) in enumerate(zip(g.columns, shades)):
        ax.bar(x + j * w - 0.4, g[r].values, width=w * 0.92, color=sh, label=f"rank {int(r)}")
    ax.set_xticks(x, [f"{int(t)}Y" for t in g.index])
    ax.set_ylabel("mean specialness (bp)")
    ax.set_title("Financing: measured specialness by tenor and rank (JPM, 2016-2025)")
    ax.legend(ncol=4, fontsize=8)
    return ax
