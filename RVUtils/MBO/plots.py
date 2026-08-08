"""Charts for the MBO explorer.

The palette is the validated categorical set (worst adjacent CVD dE 9.1, worst
adjacent normal-vision dE 19.6 on the light surface).  Three of its slots sit
below 3:1 contrast against that surface, so every chart here ships **visible
direct labels or a legend** -- identity is never carried by hue alone.

Two rules the charts do not break: a measure never gets a second y-axis (two
scales go in two stacked panels sharing an x), and colour follows the entity
rather than its rank, so filtering the series list never repaints the
survivors.
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from RVUtils.MBO.metrics import BP_PER_POINT

__all__ = [
    "GRID",
    "INK",
    "MUTED",
    "SEQ_BLUE",
    "SERIES",
    "SURFACE",
    "series_color",
    "theme",
    "plot_activity_by_kind",
    "plot_cost_comparison",
    "plot_depth_heatmap",
    "plot_intraday_message_rate",
    "plot_intraday_profile",
    "plot_listed_vs_implied",
    "plot_paired_dots",
    "plot_spread_time_share",
    "plot_top_of_book",
]

SERIES: Sequence[str] = (
    "#2a78d6",  # blue
    "#eb6834",  # orange
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#e87ba4",  # magenta
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
STATUS_CRITICAL = "#d03b3b"
STATUS_GOOD = "#0ca30c"

SEQ_BLUE = LinearSegmentedColormap.from_list(
    "seq_blue",
    ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
)

#: Scatter/heat forms use all pairs at once, where only the first three slots
#: clear the separation floors.  Past three, fold to "other" or facet.
ALL_PAIRS_SAFE = 3


def series_color(i: int) -> str:
    """Fixed-order hue for series ``i``.  Never cycled -- a 9th series is a design error."""
    if i >= len(SERIES):
        raise IndexError(
            f"series {i}: the palette has {len(SERIES)} slots and is not cycled. "
            "Fold the tail into 'other', or facet into small multiples."
        )
    return SERIES[i]


def theme() -> None:
    """Apply the chart chrome.  Call once per notebook."""
    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "DejaVu Sans", "sans-serif"],
            "font.size": 10,
            "text.color": INK,
            "axes.labelcolor": INK_2,
            "axes.edgecolor": BASELINE,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "600",
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2.0,
            "lines.solid_capstyle": "round",
            "figure.dpi": 110,
        }
    )


def _finish(ax, title: str, subtitle: str = "", ylabel: str = "", xlabel: str = "") -> None:
    """Title above a muted subtitle, with enough pad that they never overlap."""
    ax.set_title(title, pad=28 if subtitle else 12)
    if subtitle:
        ax.text(0.0, 1.012, subtitle, transform=ax.transAxes, color=MUTED,
                fontsize=9, va="bottom")
    if ylabel:
        ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel)


# --------------------------------------------------------------------------- #
# 1. map
# --------------------------------------------------------------------------- #

def plot_activity_by_kind(catalogue: pd.DataFrame, metric: str = "n_msgs",
                          ax=None, top: int = 12):
    """Horizontal bars: where the day's activity sits by instrument kind.

    One measure, one hue -- ranking is the encoding, so a categorical palette
    here would imply a distinction that is not in the data.
    """
    g = (
        catalogue.groupby("kind")
        .agg(n_instruments=("symbol", "size"), n_msgs=("n_msgs", "sum"),
             n_trades=("n_trades", "sum"), trade_volume=("trade_volume", "sum"))
        .sort_values(metric, ascending=True)
        .tail(top)
    )
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 0.42 * len(g) + 1.6))
    y = np.arange(len(g))
    v = g[metric].to_numpy(float)
    ax.barh(y, v, height=0.62, color=SERIES[0], zorder=3)
    ax.set_yticks(y, [f"{k}  ({n})" for k, n in zip(g.index, g["n_instruments"])])
    ax.xaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    for yi, vi in zip(y, v):
        ax.text(vi + v.max() * 0.012, yi, f"{vi:,.0f}", va="center",
                color=INK_2, fontsize=9)
    ax.set_xlim(0, v.max() * 1.16)
    ax.grid(axis="y", visible=False)
    _finish(ax, f"SR3 complex: {metric.replace('_', ' ')} by instrument kind",
            "instrument count in parentheses")
    return ax


def plot_intraday_message_rate(
    minute_frame: pd.DataFrame,
    columns: Sequence,
    labels: Optional[Mapping] = None,
    annotate_minutes: Mapping[int, str] = (),
    smooth: int = 5,
):
    """Message rate through the session, as small multiples.

    Deliberately faceted rather than overlaid: the busiest outright runs a
    hundred times the rate of a listed butterfly, so one shared y-axis flattens
    everything but the leader into a line along the bottom, and six overlaid
    series need six direct labels that then collide. Each panel keeps its own
    scale and carries its name and peak inside it.

    ``annotate_minutes`` marks scheduled events by minute of day; the caller
    supplies the label, because a spike in the message rate says *something
    happened*, not what.
    """
    labels = dict(labels or {})
    cols = list(columns)
    n = len(cols)
    fig, axes = plt.subplots(n, 1, figsize=(11, 1.15 * n + 1.4), sharex=True,
                             gridspec_kw={"hspace": 0.28})
    axes = np.atleast_1d(axes)
    x = minute_frame.index.to_numpy() / 60.0

    for i, (c, ax) in enumerate(zip(cols, axes)):
        y = minute_frame[c].astype(float)
        if smooth > 1:
            y = y.rolling(smooth, center=True, min_periods=1).mean()
        yv = y.to_numpy()
        col = series_color(i)
        ax.fill_between(x, 0, yv, color=col, alpha=0.22, linewidth=0)
        ax.plot(x, yv, color=col, lw=1.4)
        peak = float(np.nanmax(yv))
        ax.set_ylim(0, peak * 1.35 if peak > 0 else 1)
        ax.text(0.004, 0.94, labels.get(c, str(c)), transform=ax.transAxes,
                color=col, fontsize=9.5, fontweight="600", va="top")
        ax.text(0.996, 0.94, f"peak {peak:,.0f}/min", transform=ax.transAxes,
                color=MUTED, fontsize=8.5, va="top", ha="right")
        ax.set_yticks([])
        ax.grid(axis="y", visible=False)
        for minute in dict(annotate_minutes):
            ax.axvline(minute / 60.0, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)

    top, bottom = axes[0], axes[-1]
    for minute, text in dict(annotate_minutes).items():
        top.text(minute / 60.0 + 0.12, 1.02, text, transform=top.get_xaxis_transform(),
                 color=INK_2, fontsize=8.5, va="bottom")
    bottom.set_xlim(0, 24)
    bottom.set_xticks(range(0, 25, 2), [f"{h:02d}" for h in range(0, 25, 2)])
    bottom.set_xlabel("hour (UTC)")
    fig.suptitle("Message rate through the session", x=0.125, y=0.995,
                 ha="left", fontsize=12, fontweight="600", color=INK)
    fig.text(0.125, 0.962, "messages per minute, 5-minute centred mean; own scale "
             "per panel; snapshot records excluded", color=MUTED, fontsize=9)
    return fig, axes


# --------------------------------------------------------------------------- #
# 2. book explorer
# --------------------------------------------------------------------------- #

def plot_depth_heatmap(depth: dict, trades: Optional[pd.DataFrame] = None,
                       ax=None, max_levels: int = 10, log_size: bool = True,
                       title: str = "Resting size by price",
                       price_label: str = "price"):
    """Price x time heat of resting size, trades overlaid.

    Magnitude is one hue light-to-dark; the trade overlay is a reserved status
    colour with its own legend entry, so it can never read as "another level".
    """
    ts = pd.to_datetime(depth["ts"], utc=True)
    prices = np.concatenate([depth["bid_px"][:, :max_levels].ravel(),
                             depth["ask_px"][:, :max_levels].ravel()])
    prices = prices[np.isfinite(prices)]
    if prices.size == 0:
        raise ValueError("no depth to plot")
    uniq = np.unique(np.round(prices, 9))
    row_of = {p: i for i, p in enumerate(uniq)}

    grid = np.full((len(uniq), len(ts)), np.nan)
    for side in ("bid", "ask"):
        px, sz = depth[f"{side}_px"][:, :max_levels], depth[f"{side}_sz"][:, :max_levels]
        for lv in range(px.shape[1]):
            col = np.round(px[:, lv], 9)
            ok = np.isfinite(col)
            rows = np.array([row_of.get(p, -1) for p in col[ok]])
            good = rows >= 0
            grid[rows[good], np.flatnonzero(ok)[good]] = sz[ok, lv][good]

    show = np.log10(grid + 1.0) if log_size else grid
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 5.2))
    x = mpl.dates.date2num(ts)
    step = (uniq[1] - uniq[0]) if len(uniq) > 1 else 0.005
    im = ax.pcolormesh(x, uniq - step / 2, show, cmap=SEQ_BLUE, shading="auto",
                       linewidth=0, rasterized=True)
    cb = plt.colorbar(im, ax=ax, pad=0.012, fraction=0.03)
    cb.set_label("log10 resting lots" if log_size else "resting lots", color=INK_2)
    cb.outline.set_visible(False)

    if trades is not None and not trades.empty:
        tt = trades[(trades["ts_recv"] >= ts[0]) & (trades["ts_recv"] <= ts[-1])]
        if not tt.empty:
            ax.scatter(mpl.dates.date2num(tt["ts_recv"]), tt["price"],
                       s=np.clip(tt["size"].to_numpy(float) * 1.6, 9, 90),
                       facecolor="none", edgecolor=STATUS_CRITICAL, linewidth=1.1,
                       zorder=5, label=f"trade ({len(tt):,})")
            ax.legend(loc="lower left")
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax.grid(visible=False)
    _finish(ax, title, "book state sampled on the grid, no look-ahead", price_label)
    return ax


def plot_top_of_book(tob: pd.DataFrame, trades: Optional[pd.DataFrame] = None,
                     ax=None, session: Optional[Sequence] = None,
                     title: str = "Top of book", price_label: str = "price"):
    """Bid/ask as steps with the quoted band shaded, trades on top."""
    t = tob
    if session is not None:
        lo, hi = (pd.Timestamp(x, tz="UTC") for x in session)
        t = t[(t["ts_recv"] >= lo) & (t["ts_recv"] < hi)]
    if ax is None:
        _, ax = plt.subplots(figsize=(12, 4.6))
    x = t["ts_recv"]
    ax.fill_between(x, t["bid_px"], t["ask_px"], step="post",
                    color=SERIES[0], alpha=0.14, linewidth=0, zorder=2)
    ax.step(x, t["bid_px"], where="post", color=SERIES[0], lw=1.4, label="bid", zorder=3)
    ax.step(x, t["ask_px"], where="post", color=SERIES[1], lw=1.4, label="ask", zorder=3)
    if trades is not None and not trades.empty:
        tt = trades
        if session is not None:
            tt = tt[(tt["ts_recv"] >= x.iloc[0]) & (tt["ts_recv"] <= x.iloc[-1])]
        if not tt.empty:
            ax.scatter(tt["ts_recv"], tt["price"], s=np.clip(tt["size"] * 1.6, 10, 90),
                       facecolor="none", edgecolor=STATUS_CRITICAL, lw=1.1,
                       zorder=5, label=f"trade ({len(tt):,})")
    ax.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax.legend(loc="upper right", ncols=3)
    _finish(ax, title, "step from the last packet boundary at which the touch changed",
            price_label)
    return ax


# --------------------------------------------------------------------------- #
# 3. cost
# --------------------------------------------------------------------------- #

def plot_spread_time_share(shares: pd.DataFrame, ax=None,
                           title: str = "How much of the session sits at one tick"):
    """Share of session time by spread width in ticks, stacked.

    A CDF is the wrong form for this data: these markets are at one tick
    almost all the time, so every curve is a single step at the same x and the
    chart says nothing. What varies between instruments is the *tail* -- how
    often the market is two ticks or wider -- and a stacked share reads that
    directly.

    ``shares`` is instruments x width-bucket, values summing to 1 per row, with
    columns ordered narrow to wide.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 0.45 * len(shares) + 2.2))
    # ordinal ramp: darker is wider, and no step lighter than 250 on this surface
    ramp = ["#86b6ef", "#3987e5", "#184f95", "#0d366b"]
    y = np.arange(len(shares))
    left = np.zeros(len(shares))
    for j, colname in enumerate(shares.columns):
        v = shares[colname].to_numpy(float)
        ax.barh(y, v, left=left, height=0.62, color=ramp[j % len(ramp)],
                edgecolor=SURFACE, linewidth=2, label=str(colname), zorder=3)
        for yi, (l, w) in enumerate(zip(left, v)):
            if w > 0.06:
                ax.text(l + w / 2, yi, f"{w:.0%}", ha="center", va="center",
                        color="#ffffff" if j >= 1 else INK, fontsize=8.5,
                        fontweight="600")
        left += v
    ax.set_yticks(y, shares.index)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(mpl.ticker.PercentFormatter(1.0))
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.005), ncols=len(shares.columns))
    _finish(ax, title, "share of RTH at each quoted width, one-second grid",
            xlabel="share of session time")
    return ax


def plot_paired_dots(frame: pd.DataFrame, label_col: str, low_col: str, high_col: str,
                     low_label: str, high_label: str, title: str, subtitle: str = "",
                     xlabel: str = "", ax=None, fmt: str = "{:.2f}"):
    """Two values per row on one scale, joined by a rule.

    The right form whenever the *gap* between two comparable measures is the
    point.  A scatter of the two against each other is the wrong one here: when
    both take a handful of lattice values every marker lands on the same few
    coordinates and the labels pile into an unreadable heap.
    """
    d = frame.dropna(subset=[low_col, high_col])
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 0.42 * len(d) + 2.4))
    y = np.arange(len(d))
    lo = d[low_col].to_numpy(float)
    hi = d[high_col].to_numpy(float)
    span = float(max(hi.max(), lo.max()))
    for yi, a, b in zip(y, lo, hi):
        ax.plot([a, b], [yi, yi], color=GRID, lw=3.0, solid_capstyle="round", zorder=2)
    ax.scatter(hi, y, s=54, color=SERIES[1], zorder=4, label=high_label)
    ax.scatter(lo, y, s=54, color=SERIES[0], zorder=5, label=low_label)
    for yi, a, b in zip(y, lo, hi):
        ax.text(a - span * 0.012, yi, fmt.format(a), color=SERIES[0], fontsize=8.5,
                ha="right", va="center")
        ax.text(b + span * 0.012, yi, fmt.format(b), color=SERIES[1], fontsize=8.5,
                ha="left", va="center")
    ax.set_yticks(y, d[label_col])
    ax.set_xlim(-span * 0.10, span * 1.14)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", ncols=2, bbox_to_anchor=(1.0, 1.005))
    _finish(ax, title, subtitle, xlabel=xlabel)
    return ax


def plot_cost_comparison(cost: pd.DataFrame, ax=None, assumption_label: str = "legged assumption",
                         sort_by: str = "cost_ratio", top: int = 16):
    """Listed round trip against the legged assumption, one row per structure."""
    d = cost.dropna(subset=["listed_roundtrip_bp"]).sort_values(sort_by).head(top)
    return plot_paired_dots(
        d, "symbol", "listed_roundtrip_bp", "legged_roundtrip_bp",
        "listed book, round trip", assumption_label,
        "Round-trip cost: crossing the listed book versus legging it",
        "bp of the structure; $25 per bp per lot except bundles",
        "round-trip cost (bp)", ax=ax,
    )


def plot_intraday_profile(profile: pd.DataFrame, title: str = "Intraday profile"):
    """Spread and volume through the day in stacked panels sharing one x-axis.

    Two measures on different scales never share a y-axis; they get two panels.
    """
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1], "hspace": 0.16})
    ax = axes[0]
    ax.fill_between(profile.index, profile["spread_bp_p25"], profile["spread_bp_p75"],
                    color=SERIES[0], alpha=0.16, linewidth=0)
    ax.plot(profile.index, profile["spread_bp"], color=SERIES[0], lw=1.8, label="mean")
    ax.plot([], [], color=SERIES[0], alpha=0.32, lw=6, label="p25-p75")
    # A magnitude axis starts at zero: without it a market pinned at one tick all
    # day looks volatile, because the y-range collapses onto the rounding noise.
    ax.set_ylim(0, max(profile["spread_bp_p75"].max(), profile["spread_bp"].max()) * 1.25)
    ax.legend(loc="lower right", ncols=2, bbox_to_anchor=(1.0, 1.005))
    _finish(ax, title, "quoted spread of the structure", "spread (bp)")

    ax2 = axes[1]
    if "volume" in profile:
        step = ((profile.index[1] - profile.index[0]) if len(profile.index) > 1
                else pd.Timedelta("5min"))
        w = step.total_seconds() / 86400.0 * 0.86      # bar width is in days on a date axis
        ax2.bar(profile.index, profile["volume"], width=w, color=SERIES[2], zorder=3)
    ax2.set_ylabel("lots")
    ax2.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax2.set_xlabel("time (UTC)")
    return fig, axes


# --------------------------------------------------------------------------- #
# 4. listed vs implied
# --------------------------------------------------------------------------- #

def plot_listed_vs_implied(cmp_frame: pd.DataFrame, title: str = "Listed book vs its legs",
                           smooth: str = "5min"):
    """Three panels: the mids, the two widths, then the basis.

    The leg-implied bid/ask band is not drawn on the price panel. It flickers
    with every leg quote and, being several times wider, simply covers the
    listed band -- the comparison the chart exists to make. The widths get
    their own panel instead, which is where the difference actually lives.
    """
    fig, axes = plt.subplots(3, 1, figsize=(11.5, 8.0), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1.2, 1], "hspace": 0.18})
    d = cmp_frame
    ax = axes[0]
    ax.fill_between(d.index, d["listed_bid"], d["listed_ask"], color=SERIES[0],
                    alpha=0.35, linewidth=0, label="listed bid/ask")
    ax.plot(d.index, d["listed_mid"], color=SERIES[0], lw=1.6, label="listed mid")
    ax.plot(d.index, d["implied_mid"], color=SERIES[1], lw=1.2, ls=(0, (5, 3)),
            label="leg-implied mid")
    ax.legend(loc="upper right", ncols=3)
    _finish(ax, title, "price of the structure, basis points", "price (bp)")

    ax1 = axes[1]
    ls = d["listed_spread_bp"].rolling(smooth).mean() if smooth else d["listed_spread_bp"]
    isp = d["implied_spread_bp"].rolling(smooth).mean() if smooth else d["implied_spread_bp"]
    ax1.fill_between(d.index, ls, isp, color=SERIES[1], alpha=0.14, linewidth=0)
    ax1.plot(d.index, isp, color=SERIES[1], lw=1.6, label="leg-implied width")
    ax1.plot(d.index, ls, color=SERIES[0], lw=1.6, label="listed width")
    ax1.set_ylim(bottom=0)
    ax1.set_ylabel("quoted width (bp)")
    ax1.legend(loc="upper right", ncols=2)

    ax2 = axes[2]
    ax2.axhline(0, color=BASELINE, lw=1.0)
    ax2.plot(d.index, d["basis_bp"], color=SERIES[6], lw=1.0)
    ax2.set_ylabel("listed - implied (bp)")
    ax2.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax2.set_xlabel("time (UTC)")
    return fig, axes
