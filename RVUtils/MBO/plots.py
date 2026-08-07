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
    "plot_spread_distribution",
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
    ax.set_title(title)
    if subtitle:
        ax.text(0.0, 1.02, subtitle, transform=ax.transAxes, color=MUTED,
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
    ax=None,
    annotate_minutes: Mapping[int, str] = (),
    smooth: int = 5,
):
    """Message rate through the session, one line per instrument.

    ``annotate_minutes`` marks scheduled events by minute-of-day; the caller
    supplies the label, because a spike in the message rate says *something
    happened*, not what.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 4.4))
    labels = dict(labels or {})
    x = minute_frame.index.to_numpy() / 60.0
    for i, c in enumerate(columns):
        y = minute_frame[c].astype(float)
        if smooth > 1:
            y = y.rolling(smooth, center=True, min_periods=1).mean()
        col = series_color(i)
        name = labels.get(c, str(c))
        ax.plot(x, y.to_numpy(), color=col, label=name, lw=1.8)
        j = int(np.nanargmax(y.to_numpy()))
        ax.annotate(name, (x[j], y.to_numpy()[j]), textcoords="offset points",
                    xytext=(6, 4), color=col, fontsize=9, fontweight="600")
    for minute, text in dict(annotate_minutes).items():
        ax.axvline(minute / 60.0, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)
        ax.text(minute / 60.0 + 0.08, ax.get_ylim()[1] * 0.96, text,
                color=INK_2, fontsize=9, va="top")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2), [f"{h:02d}" for h in range(0, 25, 2)])
    ax.legend(loc="upper left", ncols=min(4, len(columns)))
    _finish(ax, "Message rate through the session",
            "messages per minute, 5-minute centred mean; snapshot records excluded",
            "messages / minute", "hour (UTC)")
    return ax


# --------------------------------------------------------------------------- #
# 2. book explorer
# --------------------------------------------------------------------------- #

def plot_depth_heatmap(depth: dict, trades: Optional[pd.DataFrame] = None,
                       ax=None, max_levels: int = 10, log_size: bool = True,
                       title: str = "Resting size by price"):
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
            ax.legend(loc="upper left")
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax.grid(visible=False)
    _finish(ax, title, "book state sampled on the grid, no look-ahead", "price")
    return ax


def plot_top_of_book(tob: pd.DataFrame, trades: Optional[pd.DataFrame] = None,
                     ax=None, session: Optional[Sequence] = None,
                     title: str = "Top of book"):
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
    ax.legend(loc="upper left", ncols=3)
    _finish(ax, title, "step from the last packet boundary at which the touch changed", "price")
    return ax


# --------------------------------------------------------------------------- #
# 3. cost
# --------------------------------------------------------------------------- #

def plot_spread_distribution(spreads_bp: Mapping[str, np.ndarray], ax=None,
                             weights: Optional[Mapping[str, np.ndarray]] = None,
                             xmax: Optional[float] = None):
    """Time-weighted CDF of the quoted spread, one line per instrument."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8.5, 4.6))
    for i, (name, v) in enumerate(spreads_bp.items()):
        v = np.asarray(v, dtype=float)
        w = np.ones_like(v) if weights is None else np.asarray(weights[name], dtype=float)
        ok = np.isfinite(v) & np.isfinite(w) & (w > 0)
        v, w = v[ok], w[ok]
        if v.size == 0:
            continue
        o = np.argsort(v)
        v, w = v[o], w[o]
        cdf = np.cumsum(w) / w.sum()
        col = series_color(i)
        ax.step(v, cdf, where="post", color=col, lw=1.8, label=name)
        j = int(np.searchsorted(cdf, 0.5))
        if j < v.size:
            ax.annotate(f"{name}  {v[j]:.2f}bp", (v[j], 0.5), textcoords="offset points",
                        xytext=(8, -2), color=col, fontsize=9, fontweight="600")
    ax.axhline(0.5, color=MUTED, lw=1.0, ls=(0, (4, 3)), zorder=1)
    if xmax:
        ax.set_xlim(0, xmax)
    ax.set_ylim(0, 1.02)
    ax.legend(loc="lower right")
    _finish(ax, "Quoted spread, time-weighted CDF",
            "share of session time at or below a given spread",
            "share of session time", "quoted spread (bp of the structure)")
    return ax


def plot_cost_comparison(cost: pd.DataFrame, ax=None, assumption_label: str = "legged assumption",
                         sort_by: str = "cost_ratio", top: int = 16):
    """Listed round trip against the legged assumption, one row per structure.

    A dot-and-rule form rather than paired bars: the comparison is between two
    values on one scale, and the gap is the quantity of interest.
    """
    d = cost.dropna(subset=["listed_roundtrip_bp"]).sort_values(sort_by).head(top)
    if ax is None:
        _, ax = plt.subplots(figsize=(9.5, 0.42 * len(d) + 2.0))
    y = np.arange(len(d))
    lo = d["listed_roundtrip_bp"].to_numpy()
    hi = d["legged_roundtrip_bp"].to_numpy()
    for yi, a, b in zip(y, lo, hi):
        ax.plot([a, b], [yi, yi], color=GRID, lw=3.0, solid_capstyle="round", zorder=2)
    ax.scatter(hi, y, s=54, color=SERIES[1], zorder=4, label=assumption_label)
    ax.scatter(lo, y, s=54, color=SERIES[0], zorder=5, label="listed book, round trip")
    for yi, a in zip(y, lo):
        ax.text(a, yi + 0.30, f"{a:.2f}", color=SERIES[0], fontsize=8.5, ha="center")
    ax.set_yticks(y, d["symbol"])
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", ncols=2)
    _finish(ax, "Round-trip cost: crossing the listed book versus legging it",
            "bp of the structure; $25 per bp per lot", xlabel="round-trip cost (bp)")
    return ax


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
    ax.legend(loc="upper right", ncols=2)
    _finish(ax, title, "quoted spread of the structure", "spread (bp)")

    ax2 = axes[1]
    if "volume" in profile:
        w = (profile.index[1] - profile.index[0]) if len(profile.index) > 1 else pd.Timedelta("5min")
        ax2.bar(profile.index, profile["volume"], width=w * 0.86, color=SERIES[2], zorder=3)
    ax2.set_ylabel("lots")
    ax2.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax2.set_xlabel("time (UTC)")
    return fig, axes


# --------------------------------------------------------------------------- #
# 4. listed vs implied
# --------------------------------------------------------------------------- #

def plot_listed_vs_implied(cmp_frame: pd.DataFrame, title: str = "Listed book vs its legs"):
    """Two panels: the two books' mids and widths, then the basis between them."""
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 6.8), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1], "hspace": 0.16})
    d = cmp_frame
    ax = axes[0]
    ax.fill_between(d.index, d["implied_bid"], d["implied_ask"], color=SERIES[1],
                    alpha=0.20, linewidth=0, label="leg-implied bid/ask")
    ax.fill_between(d.index, d["listed_bid"], d["listed_ask"], color=SERIES[0],
                    alpha=0.34, linewidth=0, label="listed bid/ask")
    ax.plot(d.index, d["listed_mid"], color=SERIES[0], lw=1.5, label="listed mid")
    ax.plot(d.index, d["implied_mid"], color=SERIES[1], lw=1.2, ls=(0, (5, 3)),
            label="leg-implied mid")
    ax.legend(loc="upper left", ncols=2)
    _finish(ax, title, "price of the structure", "price")

    ax2 = axes[1]
    ax2.axhline(0, color=BASELINE, lw=1.0)
    ax2.plot(d.index, d["basis_bp"], color=SERIES[6], lw=1.4)
    ax2.set_ylabel("listed - implied (bp)")
    ax2.xaxis.set_major_formatter(mpl.dates.DateFormatter("%H:%M", tz="UTC"))
    ax2.set_xlabel("time (UTC)")
    return fig, axes
