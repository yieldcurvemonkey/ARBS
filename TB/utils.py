import datetime
import logging
import re
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # Keep for compatibility
import polars as pl
import plotly.graph_objects as go
import tqdm
from scipy.stats import tstd, zscore

DateLike = Union[datetime.date, datetime.datetime]


def _to_utc_naive(dt: DateLike) -> datetime.datetime:
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime(dt.year, dt.month, dt.day)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt  # naive UTC


def _dt_to_epoch_ns(dt: DateLike) -> int:
    dtu = _to_utc_naive(dt)
    return int(dtu.timestamp() * 1_000_000_000)


def _canonicalize_value(v):
    if isinstance(v, (datetime.date, datetime.datetime)):
        return _to_utc_naive(v).isoformat()
    if isinstance(v, Enum):  # IRSwapValue is an Enumhttps://open.spotify.com/show/7vsf2QkL0P9Ac7dp3HyUg3
        return v.name
    if isinstance(v, (list, tuple)):
        return [_canonicalize_value(x) for x in v]
    if isinstance(v, dict):
        # sort keys to ensure determinism
        return {k: _canonicalize_value(v[k]) for k in sorted(v.keys())}
    return v  # numbers/strings/None


def make_secondary_axis_plot_v1(*, ylabel_left=None, ylabel_right=None, title=None):
    """
    Returns: plot, fig, ax_left, ax_right, legend

    plot(series, *, label=None, which='auto'|'left'|'right', **kwargs)
      - series: pandas.Series (index is x, values are y)
      - default label is series.name (tuple names are joined)
      - 'auto' → first call -> left y-axis, subsequent calls -> right y-axis
    legend(loc='best', **kwargs)
    """
    fig, ax_left = plt.subplots()
    ax_right = ax_left.twinx()

    if title:
        ax_left.set_title(title)
    if ylabel_left:
        ax_left.set_ylabel(ylabel_left)
    if ylabel_right:
        ax_right.set_ylabel(ylabel_right)

    # Shared color cycle across BOTH axes
    colors = plt.rcParams.get("axes.prop_cycle", None)
    colors = (colors.by_key().get("color", []) if colors is not None else []) or [f"C{i}" for i in range(10)]

    state = {
        "left_lines": [],
        "right_lines": [],
        "first_done": False,
        "color_idx": 0,
        "left_color": None,
        "right_color": None,
    }

    def _next_color():
        c = colors[state["color_idx"] % len(colors)]
        state["color_idx"] += 1
        return c

    def _stringify_name(n):
        if n is None:
            return "series"
        if isinstance(n, tuple):
            return " ".join(map(str, n))
        return str(n)

    def plot(series: Union[pd.Series, pl.Series], *, label=None, which="auto", **kwargs):
        if not isinstance(series, (pd.Series, pl.Series)):
            raise TypeError("plot() expects a pandas or polars Series")

        # Convert polars Series to pandas for plotting compatibility
        if isinstance(series, pl.Series):
            series = series.to_pandas()

        # decide axis
        target = ax_left if (which == "left" or (which == "auto" and not state["first_done"])) else ax_right

        # default label from series name
        if label is None:
            label = _stringify_name(series.name)

        # ensure different colors across calls unless user specifies one
        if "color" not in kwargs:
            kwargs["color"] = _next_color()

        (line,) = target.plot(series.index, series.values, label=label, **kwargs)

        # remember for legend
        (state["left_lines"] if target is ax_left else state["right_lines"]).append(line)
        state["first_done"] = True

        # color ticks/labels to the first line on each side
        if target is ax_left and state["left_color"] is None:
            state["left_color"] = line.get_color()
            ax_left.tick_params(axis="y", labelcolor=state["left_color"])
            if ylabel_left:
                ax_left.yaxis.label.set_color(state["left_color"])
        if target is ax_right and state["right_color"] is None:
            state["right_color"] = line.get_color()
            ax_right.tick_params(axis="y", labelcolor=state["right_color"])
            if ylabel_right:
                ax_right.yaxis.label.set_color(state["right_color"])

        return line

    def legend(loc="best", **kwargs):
        handles = state["left_lines"] + state["right_lines"]
        labels = [h.get_label() for h in handles]
        ax_left.legend(handles, labels, loc=loc, **kwargs)

    return plot, fig, ax_left, ax_right, legend


def make_secondary_axis_plot_v2(*, ylabel_left=None, ylabel_right=None, title=None):
    """
    Returns: plot, fig, ax_left, ax_right, legend

    plot(series, *, label=None, which='auto'|'left'|'right', **kwargs)
      - series: pandas.Series (index is x, values are y)
      - default label is series.name (tuple names are joined)
      - 'left'  → plot on the primary left y-axis
      - 'right' or 'auto' → plot on a NEW secondary y-axis (each call makes a new one)

    legend(loc='best', valfmt='{:.2f}', show_date=False, sep=' — ', **kwargs)
      - valfmt: format string for latest value
      - show_date: include the timestamp of the latest observation
      - sep: separator between base label and value snippet
    """
    fig, ax_left = plt.subplots()
    fig.subplots_adjust(right=0.75)

    if title:
        ax_left.set_title(title)
    if ylabel_left:
        ax_left.set_ylabel(ylabel_left)

    colors = plt.rcParams.get("axes.prop_cycle", None)
    colors = (colors.by_key().get("color", []) if colors is not None else []) or [f"C{i}" for i in range(10)]

    state = {
        "left_lines": [],
        "right_lines": [],
        "right_axes": [],
        "color_idx": 0,
        "left_color": None,
        "series_meta": [],  # list of dicts: {line, label, last_dt, last_val}
    }

    def _next_color():
        c = colors[state["color_idx"] % len(colors)]
        state["color_idx"] += 1
        return c

    def _stringify_name(n):
        if n is None:
            return "series"
        if isinstance(n, tuple):
            return " ".join(map(str, n))
        return str(n)

    def _fmt_dt(ts):
        if not isinstance(ts, datetime.datetime):
            ts = datetime.datetime.fromisoformat(str(ts)) if isinstance(ts, str) else ts
        return ts.strftime("%Y-%m-%d") if ts.time() == datetime.time(0, 0, 0) else ts.isoformat(sep=" ")

    def _new_right_axis():
        idx = len(state["right_axes"])
        ax = ax_left.twinx()
        ax.set_frame_on(True)
        ax.patch.set_visible(False)
        offset = 1.0 + 0.10 * idx
        ax.spines["right"].set_position(("axes", offset))
        ax.spines["right"].set_zorder(10 + idx)
        state["right_axes"].append(ax)
        return ax

    def plot(series: Union[pd.Series, pl.Series], *, label=None, which="left", **kwargs):
        if not isinstance(series, (pd.Series, pl.Series)):
            raise TypeError("plot() expects a pandas or polars Series")

        # Convert polars Series to pandas for plotting compatibility
        if isinstance(series, pl.Series):
            series = series.to_pandas()

        if label is None:
            label = _stringify_name(series.name)

        target = ax_left if which == "left" else _new_right_axis()

        if "color" not in kwargs:
            kwargs["color"] = _next_color()

        (line,) = target.plot(series.index, series.values, label=label, **kwargs)

        # capture most recent non-NaN
        s_valid = series.dropna()
        if len(s_valid) > 0:
            last_dt = s_valid.index[-1]
            last_val = s_valid.iloc[-1]
        else:
            last_dt, last_val = None, np.nan

        state["series_meta"].append({"line": line, "label": label, "last_dt": last_dt, "last_val": last_val})

        if target is ax_left:
            state["left_lines"].append(line)
            if state["left_color"] is None:
                state["left_color"] = line.get_color()
                ax_left.tick_params(axis="y", labelcolor=state["left_color"])
                ax_left.set_ylabel(ylabel_left or label, color=state["left_color"])
        else:
            state["right_lines"].append(line)
            target.tick_params(axis="y", labelcolor=line.get_color())
            target.set_ylabel(ylabel_right or label, color=line.get_color())

        return line

    def legend(loc="best", valfmt="{:.2f}", show_date=False, sep=" — ", **kwargs):
        # order handles left→right to match plotting order
        handles = state["left_lines"] + state["right_lines"]
        # map lines to meta for quick lookup
        meta_map = {m["line"]: m for m in state["series_meta"]}

        labels = []
        for h in handles:
            m = meta_map.get(h, None)
            base = h.get_label()
            if m is None:
                labels.append(base)
                continue
            lv = m["last_val"]
            try:
                lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
            except Exception:
                lv_text = str(lv)
            if show_date and m["last_dt"] is not None:
                lbl = f"{base}{sep}{lv_text} @ {_fmt_dt(m['last_dt'])}"
            else:
                lbl = f"{base}{sep}{lv_text}"
            labels.append(lbl)

        ax_left.legend(handles, labels, loc=loc, **kwargs)

    ax_right = None
    return plot, fig, ax_left, ax_right, legend


def timeseries_df_plotter(
    df: Union[pd.DataFrame, pl.DataFrame],
    cols_to_plot: List[str],
    cols_to_plot_raxis: Optional[List[str]] = None,
    use_plotly: Optional[bool] = False,
    custom_title: Optional[str] = None,
    yaxis_title: Optional[str] = None,
    yaxis_title_r: Optional[str] = None,
    stds: Optional[Dict[str, Tuple[List[int], DateLike]]] = {},
    plot_zscores: Optional[bool] = False,
    entry_date: Optional[DateLike] = None,
    entry_level: Optional[float] = None,
):
    # Convert polars DataFrame to pandas for plotting compatibility
    if isinstance(df, pl.DataFrame):
        df = df.to_pandas()

    assert isinstance(df.index, pd.DatetimeIndex), "The DataFrame must have a DatetimeIndex"

    def _tz_label(ts: datetime.datetime) -> str:
        # Prefer DST-aware abbreviation like 'EST'/'EDT'; fall back to UTC offset.
        # Convert to datetime if needed
        if not isinstance(ts, datetime.datetime):
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()
            else:
                ts = datetime.datetime.fromisoformat(str(ts))

        name = ts.tzname()
        if name:
            return name
        off = ts.utcoffset()
        if off is None:
            return ""
        total_min = int(off.total_seconds() // 60)
        sign = "+" if total_min >= 0 else "-"
        hh, mm = divmod(abs(total_min), 60)
        return f"UTC{sign}{hh:02d}:{mm:02d}"

    df = df.copy()
    tz_aware = getattr(df.index, "tz", None) is not None
    if tz_aware:
        tz_text = [_tz_label(x) for x in df.index]
        hover_template = "%{x|%Y-%m-%d %H:%M:%S} %{text}<br>%{y}<extra></extra>"
    else:
        tz_text = None
        hover_template = "%{x|%Y-%m-%d %H:%M:%S}<br>%{y}<extra></extra>"

    if use_plotly:
        fig = go.Figure()
        for tenor in cols_to_plot:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[tenor] if not plot_zscores else zscore(df[tenor]),
                    mode="lines",
                    name=f"{tenor} (lhs)" if not plot_zscores else f"{tenor} Z-Score (lhs)",
                    yaxis="y1",
                    hovertemplate=hover_template,
                    **({"text": tz_text} if tz_aware else {}),
                )
            )
        if cols_to_plot_raxis:
            for tenor in cols_to_plot_raxis:
                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=df[tenor] if not plot_zscores else zscore(df[tenor]),
                        mode="lines",
                        name=f"{tenor} (rhs)" if not plot_zscores else f"{tenor} Z-Score (rhs)",
                        yaxis="y2",
                        **({"text": tz_text} if tz_aware else {}),
                    )
                )

        fig.update_layout(
            title=(
                custom_title
                or (
                    f"{", ".join(cols_to_plot)} (lhs) & {", ".join(cols_to_plot_raxis)} (rhs) Timeseries {"Z-Scores" if plot_zscores else ""}"
                    if cols_to_plot_raxis
                    else f"{", ".join(cols_to_plot)} Timeseries {"Z-Scores" if plot_zscores else ""}"
                )
            ),
            xaxis_title="Date",
            yaxis=dict(title=yaxis_title if yaxis_title else ", ".join(cols_to_plot), side="left"),
            yaxis2=dict(
                title=yaxis_title_r if yaxis_title_r else ", ".join(cols_to_plot_raxis) if cols_to_plot_raxis else None,
                overlaying="y",
                side="right",
            ),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, title="Tenors"),
            template="plotly_dark",
            font=dict(size=11),
            height=750,
            newshape=dict(line=dict(color="red")),  # set the default drawing color to red
        )

        fig.update_xaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikemode="across", showgrid=True)
        fig.update_yaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikethickness=0.5, showgrid=True)
        fig.show(
            config={
                "modeBarButtonsToAdd": [
                    "drawline",
                    "drawopenpath",
                    "drawclosedpath",
                    "drawcircle",
                    "drawrect",
                    "eraseshape",
                ]
            }
        )
    else:
        df = df.copy()
        date_col = df.index
        df = df.reset_index(drop=True)
        df["Date"] = date_col

        unique_colors = plt.cm.tab10.colors
        i = 0
        fig, ax_left = plt.subplots()

        lns = []
        for tenor in cols_to_plot:
            lns += ax_left.plot(
                df["Date"],
                df[tenor],
                label=f"{tenor} (lhs)\nMost Recent: {df["Date"].iloc[-1].date()}, {np.round(df[tenor].iloc[-1], 3)}",
                color=unique_colors[i],
            )
            i += 1

            if tenor in stds.keys():
                ex_post_date = max(df["Date"])
                if isinstance(stds[tenor], tuple):
                    ex_post_date = stds[tenor][1]

                level_std = tstd(df[df["Date"] <= ex_post_date][tenor])
                level_mean = np.mean(df[df["Date"] <= ex_post_date][tenor])
                lns += ax_left.plot(
                    df[df["Date"] <= ex_post_date]["Date"],
                    [level_mean] * len(df[df["Date"] <= ex_post_date]["Date"]),
                    linestyle="--",
                    color="red",
                    label=f"Mean: {level_mean}",
                )

                std_vals = stds[tenor][0] if isinstance(stds[tenor], tuple) else stds[tenor]
                for std in std_vals:
                    curr_std_level = level_mean + (level_std * std)
                    curr_std_level_opp = level_mean + (level_std * std * -1)
                    curr = ax_left.plot(
                        df[df["Date"] <= ex_post_date]["Date"],
                        [curr_std_level] * len(df[df["Date"] <= ex_post_date]["Date"]),
                        linestyle="--",
                        label=f"± {std} STD: {np.round(curr_std_level, 3)}, {np.round(curr_std_level_opp, 3)}",
                        color="red",
                        alpha=0.75,
                    )
                    lns += curr
                    ax_left.plot(
                        df[df["Date"] <= ex_post_date]["Date"],
                        [curr_std_level_opp] * len(df[df["Date"] <= ex_post_date]["Date"]),
                        linestyle="--",
                        color=curr[0].get_color(),
                        alpha=0.75,
                    )

        ax_left.set_ylabel(yaxis_title if yaxis_title else ", ".join(cols_to_plot))
        ax_left.tick_params(axis="y")

        if cols_to_plot_raxis:
            ax_right = ax_left.twinx()
            for tenor in cols_to_plot_raxis:
                lns += ax_right.plot(
                    df["Date"],
                    df[tenor],
                    label=f"{tenor} (lhs)\nMost Recent: {df["Date"].iloc[-1].date()}, {np.round(df[tenor].iloc[-1], 3)}",
                    color=unique_colors[i],
                )
                i += 1

                if tenor in stds.keys():
                    level_std = tstd(df[tenor])
                    level_mean = np.mean(df[tenor])
                    lns += ax_right.plot(df["Date"], [level_mean] * len(df["Date"]), linestyle="--", color="red", label=f"Mean: {level_mean}")

                    for std in stds[tenor]:
                        curr_std_level = level_mean + (level_std * std)
                        curr_std_level_opp = level_mean + (level_std * std * -1)
                        curr = ax_right.plot(
                            df["Date"],
                            [curr_std_level] * len(df["Date"]),
                            linestyle="--",
                            label=f"±{std} std: {np.round(curr_std_level, 3)}, {np.round(curr_std_level_opp, 3)}",
                            color="red",
                            alpha=0.75,
                        )
                        lns += curr
                        ax_right.plot(
                            df["Date"],
                            [curr_std_level_opp] * len(df["Date"]),
                            linestyle="--",
                            color=curr[0].get_color(),
                            alpha=0.75,
                        )

            ax_right.set_ylabel(yaxis_title_r if yaxis_title_r else ", ".join(cols_to_plot_raxis))
            ax_right.tick_params(axis="y")

        locator = mdates.AutoDateLocator(minticks=3, maxticks=15)
        formatter = mdates.DateFormatter("%Y-%m-%d")
        ax_left.xaxis.set_major_locator(locator)
        ax_left.xaxis.set_major_formatter(formatter)
        ax_left.set_xlabel("Date")
        ax_left.set_xticks(ax_left.get_xticks(), ax_left.get_xticklabels(), rotation=25, ha="right")

        labs = [l.get_label() for l in lns]
        ax_left.legend(lns, labs, loc=(0, 0))
        if custom_title:
            plt.title(custom_title)
        else:
            plt.title(
                f"{' '.join(cols_to_plot)} (lhs) & {' '.join(cols_to_plot_raxis)} (rhs) Timeseries" if cols_to_plot_raxis else f"{' '.join(cols_to_plot)} Timeseries"
            )
        ax_left.grid(True)
        plt.xticks(rotation=25)
        fig.tight_layout()

        if entry_date and entry_level:
            plt.axvline(entry_date, label=f"Entry: {entry_date}, {entry_level}", c="r", linestyle="--", alpha=0.7)
            plt.axhline(entry_level, c="r", linestyle="--", alpha=0.7)
        elif entry_level:
            plt.axhline(entry_level, c="r", linestyle="--", alpha=0.7)

        plt.show()
