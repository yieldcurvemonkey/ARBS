# ABOUTME: US Treasury visualization utilities
# ABOUTME: Specialized plotting functions for Treasury curves and spreads
from datetime import datetime
from typing import Annotated, Callable, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objs as go
import seaborn as sns
from plotly.subplots import make_subplots
from scipy.interpolate import UnivariateSpline
from scipy.optimize import newton

sns.set_style("whitegrid", {"grid.linestyle": "--"})

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)


def plot_timeseries(
    df: pd.DataFrame,
    y_cols: List[str],
    x_col="Date",
    max_ticks=10,
    flip=False,
    custom_label_x=None,
    custom_label_y=None,
    custom_title=None,
    date_subset_range: Annotated[List[datetime], 2] | None = None,
    plot_recessions=False,
    bar_plot=False,
    dt_range_highlights: List[Tuple[datetime, datetime, str, str]] = None,
    ohlc=False,
    secondary_y_cols: Optional[List[str]] = None,
    html_path: Optional[str] = None,
):
    copy_df = df.copy()
    date_col = "Date"

    copy_df[date_col] = pd.to_datetime(copy_df[date_col])
    if date_subset_range:
        copy_df = copy_df[(copy_df[date_col] >= date_subset_range[0]) & (copy_df[date_col] <= date_subset_range[1])]
    if flip:
        copy_df = copy_df.iloc[::-1]

    if secondary_y_cols:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
    else:
        fig = go.Figure()

    colors = ["white"] + px.colors.qualitative.Plotly
    for i, y_col in enumerate(y_cols):
        if bar_plot:
            fig.add_trace(
                go.Bar(x=copy_df[x_col], y=copy_df[y_col], name=y_col, marker_color="black"),
                secondary_y=y_col in secondary_y_cols if secondary_y_cols else None,
            )
        elif ohlc:
            fig.add_trace(
                go.Ohlc(
                    x=df[f"Date"],
                    open=df[f"{y_col}_Open"],
                    high=df[f"{y_col}_High"],
                    low=df[f"{y_col}_Low"],
                    close=df[f"{y_col}_Close"],
                    name=y_col,
                    increasing_line_color=colors[i],
                    decreasing_line_color=colors[i],
                ),
                secondary_y=y_col in secondary_y_cols if secondary_y_cols else None,
            )
            fig.update(layout_xaxis_rangeslider_visible=False)
        else:
            fig.add_trace(
                go.Scatter(x=copy_df[x_col], y=copy_df[y_col], mode="lines", name=y_col),
                secondary_y=y_col in secondary_y_cols if secondary_y_cols else None,
            )

    if plot_recessions:
        recessions = [
            [datetime(1961, 4, 1), datetime(1961, 2, 1)],
            [datetime(1969, 12, 1), datetime(1970, 11, 1)],
            [datetime(1973, 11, 1), datetime(1975, 3, 1)],
            [datetime(1980, 1, 1), datetime(1980, 7, 1)],
            [datetime(1981, 7, 1), datetime(1982, 11, 1)],
            [datetime(1990, 7, 1), datetime(1991, 3, 1)],
            [datetime(2001, 3, 1), datetime(2001, 11, 1)],
            [datetime(2007, 12, 1), datetime(2009, 6, 1)],
            [datetime(2020, 2, 1), datetime(2020, 4, 1)],
        ]
        if date_subset_range:
            start_plot_range, end_plot_range = min(date_subset_range), max(date_subset_range)
        else:
            start_plot_range, end_plot_range = min(copy_df["Date"]), max(copy_df["Date"])

        for recession_dates in recessions:
            start_date, end_date = recession_dates
            if start_date <= end_plot_range and end_date >= start_plot_range:
                fig.add_vrect(
                    x0=start_date,
                    x1=end_date,
                    fillcolor="red",
                    opacity=0.3,
                    layer="below",
                    line_width=0,
                )

    if dt_range_highlights:
        for highlight_props in dt_range_highlights:
            start_date, end_date, color, title = highlight_props
            fig.add_vrect(
                x0=start_date,
                x1=end_date,
                fillcolor=color,
                opacity=0.3,
                layer="below",
                line_width=0,
                annotation_text=title,
                annotation_position="top left",
                annotation_textangle=90,
            )

    if secondary_y_cols:
        fig.update_yaxes(title=custom_label_y or ", ".join(secondary_y_cols), secondary_y=True)
        fig.update_yaxes(title=custom_label_y or ", ".join(list(set(y_cols) - set(secondary_y_cols))), secondary_y=False)
    else:
        fig.update_yaxes(title=custom_label_y or ", ".join(y_cols))
    fig.update_layout(
        xaxis_title=custom_label_x or x_col,
        xaxis=dict(nticks=max_ticks),
        title=custom_title or "Yield Plot",
        showlegend=True,
        template="plotly_dark",
        height=700,
    )
    fig.update_xaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikemode="across")
    fig.update_yaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikethickness=0.5)
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
    if html_path:
        fig.write_html(html_path)


def plot_usts(
    curve_set_df: pd.DataFrame,
    ttm_col: Optional[str] = "time_to_maturity",
    ytm_col: Optional[str] = "ytm",
    label_col: Optional[str] = "original_security_term",
    cusip_col: Optional[str] = "cusip",
    hover_data: Optional[List[str]] = None,
    title: Optional[str] = None,
    custom_x_axis: Optional[str] = "Time to Maturity",
    custom_y_axis: Optional[str] = "Yield to Maturity",
    splines: Optional[List[Tuple[Callable, str]]] = None,
    cusips_filter: Optional[List[str]] = None,
    ust_labels_filter: Optional[List[str]] = None,
    cusips_hightlighter: Optional[List[str]] = None,
    ust_labels_highlighter: Optional[List[Tuple[str, str] | str]] = None,
    linspace_num: Optional[int] = 1000,
    spline_lb: Optional[int] = 0,
    spline_ub: Optional[int] = 30,
    plot_height=1000,
    plot_width=None,
    ignore_otr=False,
):
    curve_set_df = curve_set_df.copy()

    if cusips_filter:
        curve_set_df = curve_set_df[curve_set_df[cusip_col].isin(cusips_filter)]
        cusips_filter_set = set(cusips_filter)
        cusips_in_df = set(curve_set_df[cusip_col].unique())
        cusips_not_in_df = cusips_filter_set - cusips_in_df
        print("CUSIPs not in Curveset df:", cusips_not_in_df)

    if ust_labels_filter:
        curve_set_df = curve_set_df[curve_set_df["ust_label"].isin(ust_labels_filter)]
        ust_labels_filter_set = set(ust_labels_filter)
        labels_in_df = set(curve_set_df["ust_label"].unique())
        labels_not_in_df = ust_labels_filter_set - labels_in_df
        print("Labels not in Curveset df:", labels_not_in_df)

    curve_set_df = curve_set_df.sort_values(by=label_col, key=lambda s: s.str.extract(r"^(\d+)")[0].astype(int))
    curve_set_df["plot_group"] = curve_set_df[label_col].astype(str)

    otr_mask = curve_set_df["rank"] == 0
    curve_set_df.loc[otr_mask, "plot_group"] = "OTR - " + curve_set_df.loc[otr_mask, "plot_group"]
    fig = px.scatter(curve_set_df[~otr_mask], x=ttm_col, y=ytm_col, color="plot_group", hover_data=hover_data)

    if not ignore_otr:
        curve_set_df.loc[otr_mask, label_col] = curve_set_df.loc[otr_mask, label_col].apply(lambda x: f"OTR - {x}")
        otr_fig = px.scatter(
            curve_set_df[otr_mask],
            x=ttm_col,
            y=ytm_col,
            color=label_col,
            hover_data=hover_data,
        )
        for trace in otr_fig.data:
            trace.update(
                marker=dict(
                    line=dict(color="white", width=2),
                )
            )
        fig.add_traces(otr_fig.data)

    if cusips_hightlighter:
        for cusip_tuple in cusips_hightlighter:
            if not isinstance(cusip_tuple, tuple):
                cusip = cusip_tuple
                label_color = "yellow"
            else:
                cusip, label_color = cusip_tuple

            if cusip not in curve_set_df[cusip_col].values:
                print(f"{cusip} not in Curveset df!")
                continue

            cusip_highlight_fig = px.scatter(
                curve_set_df[curve_set_df[cusip_col] == cusip],
                x=ttm_col,
                y=ytm_col,
                color=cusip_col,
                hover_data=hover_data,
            )
            for trace in cusip_highlight_fig.data:
                trace.update(
                    marker=dict(
                        line=dict(color=label_color, width=4),
                    )
                )
            fig.add_traces(cusip_highlight_fig.data)
        # else:
        #     cusip_highlight_mask = curve_set_df[cusip_col].isin(cusips_hightlighter)
        #     cusip_highlight_fig = px.scatter(
        #         curve_set_df[cusip_highlight_mask],
        #         x=ttm_col,
        #         y=ytm_col,
        #         color=cusip_col,
        #         hover_data=hover_data,
        #     )
        #     for trace in cusip_highlight_fig.data:
        #         trace.update(
        #             marker=dict(
        #                 line=dict(color="yellow", width=4),
        #             )
        #         )
        #     fig.add_traces(cusip_highlight_fig.data)

    if ust_labels_highlighter:
        if isinstance(ust_labels_highlighter[0], tuple):
            for label_tuple in ust_labels_highlighter:
                if not isinstance(label_tuple, tuple):
                    ust_label = label_tuple
                    label_color = "yellow"
                else:
                    ust_label, label_color = label_tuple

                if ust_label not in curve_set_df["ust_label"].values:
                    print(f"{ust_label} not in Curveset df!")
                    continue

                ust_labels_highlight_fig = px.scatter(
                    curve_set_df[curve_set_df["ust_label"] == ust_label],
                    x=ttm_col,
                    y=ytm_col,
                    color="ust_label",
                    hover_data=hover_data,
                )
                for trace in ust_labels_highlight_fig.data:
                    trace.update(
                        marker=dict(
                            line=dict(color=label_color, width=4),
                        )
                    )
                fig.add_traces(ust_labels_highlight_fig.data)
        else:
            ust_labels_highlight_mask = curve_set_df["ust_label"].isin(ust_labels_highlighter)
            ust_labels_highlight_fig = px.scatter(
                curve_set_df[ust_labels_highlight_mask],
                x=ttm_col,
                y=ytm_col,
                color="ust_label",
                hover_data=hover_data,
            )
            for trace in ust_labels_highlight_fig.data:
                trace.update(
                    marker=dict(
                        line=dict(color="yellow", width=4),
                    )
                )
            fig.add_traces(ust_labels_highlight_fig.data)

    if splines:
        ttm_linspace = np.linspace(spline_lb, spline_ub, linspace_num)
        for curve_tup in splines:
            if len(curve_tup) == 3:
                interp_func, label, spline_color = curve_tup
            else:
                interp_func, label = curve_tup
                spline_color = "white"

            fig.add_trace(
                go.Scatter(
                    x=ttm_linspace,
                    y=interp_func(ttm_linspace),
                    mode="lines",
                    name=label,
                    marker=dict(color=spline_color),
                )
            )

    fig.update_layout(
        xaxis_title=custom_x_axis,
        yaxis_title=custom_y_axis,
        title=title or "Yield Curve",
        showlegend=True,
        template="plotly_dark",
        height=plot_height,
        width=plot_width,
        legend_title_text=label_col,
        newshape={"line": {"color": "red"}},
    )
    fig.update_xaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikemode="across")
    fig.update_yaxes(
        showspikes=True,
        spikecolor="white",
        spikesnap="cursor",
        spikethickness=0.5,
    )
    fig.update_coloraxes(showscale=False)
    fig.show(
        config={
            "modeBarButtonsToAdd": [
                "drawline",
                "drawopenpath",
                "drawclosedpath",
                "drawcircle",
                "drawrect",
                "eraseshape",
            ],
        }
    )


def plot_usts_comparison(
    curve_set_df: pd.DataFrame,
    ttm_col: Optional[str] = "time_to_maturity",
    ytm_col: Optional[str] = "ytm",
    label_col: Optional[str] = "original_security_term",
    cusip_col: Optional[str] = "cusip",
    hover_data: Optional[List[str]] = None,
    title: Optional[str] = None,
    custom_x_axis: Optional[str] = None,
    custom_y_axis: Optional[str] = None,
    splines: Optional[List[Tuple[Callable, str]]] = None,
    cusips_filter: Optional[List[str]] = None,
    ust_labels_filter: Optional[List[str]] = None,
    cusips_hightlighter: Optional[List[str]] = None,
    ust_labels_highlighter: Optional[List[Tuple[str, str] | str]] = None,
    linspace_num: Optional[int] = 1000,
    spline_lb: Optional[int] = 0,
    spline_ub: Optional[int] = 30,
    plot_height=1000,
    plot_width=None,
    ignore_otr=False,
    fig: Optional[go.Figure] = None,
    opacity: float = 1.0,
    name_suffix: Optional[str] = None,
    color_discrete_map: Optional[Dict[str, str]] = None,
    return_color_map: bool = False,
    show: bool = True,
):
    from pandas.api.types import is_numeric_dtype as _isnum

    if custom_x_axis is None:
        custom_x_axis = ttm_col
    if custom_y_axis is None:
        custom_y_axis = ytm_col

    def _trim_zeros(s: str) -> str:
        return s.rstrip("0").rstrip(".") if "." in s else s

    def _human_num(x) -> str:
        if pd.isna(x):
            return "NA"
        try:
            xv = float(x)
        except Exception:
            return str(x)
        ax = abs(xv)
        if ax >= 1e12:
            return _trim_zeros(f"{xv/1e12:.3f}") + "Tn"
        if ax >= 1e9:
            return _trim_zeros(f"{xv/1e9:.3f}") + "Bn"
        if ax >= 1e6:
            return _trim_zeros(f"{xv/1e6:.3f}") + "Mn"
        if ax >= 1e3:
            return _trim_zeros(f"{xv/1e3:.3f}") + "K"
        return _trim_zeros(f"{xv:.3f}")

    def _uniq_key(base: str, taken: set[str]) -> str:
        """Ensure the hover key doesn't collide with df columns or other hover keys."""
        k = base
        i = 2
        while k in taken:
            k = f"{base} ({i})"
            i += 1
        return k

    def _make_hover_dict(sub: pd.DataFrame, cols: Optional[list[str]]):
        if not cols:
            return None
        taken = set(sub.columns)  # reserved names → force rename
        out = {}
        for c in cols:
            if c not in sub.columns:
                # Not a real column → can use as-is, but still avoid dup keys
                key = _uniq_key(str(c), taken | set(out.keys()))
            else:
                # Rename to avoid "Ambiguous input" (PX disallows same-name array + column)
                key = _uniq_key(f"{c} (h)", taken | set(out.keys()))

            s = sub[c] if c in sub.columns else pd.Series([None] * len(sub), index=sub.index)
            if _isnum(s):
                out[key] = s.map(_human_num)
            else:
                try:
                    out[key] = s.dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    out[key] = s.astype(str)
        return out

    curve_set_df = curve_set_df.copy()

    if cusips_filter:
        curve_set_df = curve_set_df[curve_set_df[cusip_col].isin(cusips_filter)]
        missing = set(cusips_filter) - set(curve_set_df[cusip_col].unique())
        if missing:
            print("CUSIPs not in Curveset df:", missing)

    if ust_labels_filter:
        curve_set_df = curve_set_df[curve_set_df["ust_label"].isin(ust_labels_filter)]
        missing = set(ust_labels_filter) - set(curve_set_df["ust_label"].unique())
        if missing:
            print("Labels not in Curveset df:", missing)

    curve_set_df = curve_set_df.sort_values(by=label_col, key=lambda s: s.str.extract(r"^(\d+)")[0].astype(int))
    curve_set_df["plot_group"] = curve_set_df[label_col].astype(str)
    otr_mask = curve_set_df["rank"] == 0
    curve_set_df.loc[otr_mask, "plot_group"] = "OTR - " + curve_set_df.loc[otr_mask, "plot_group"]

    base_fig = fig if fig is not None else go.Figure()

    non_otr_df = curve_set_df[~otr_mask]
    px_fig = px.scatter(
        non_otr_df,
        x=ttm_col,
        y=ytm_col,
        color="plot_group",
        hover_data=_make_hover_dict(non_otr_df, hover_data),
        color_discrete_map=color_discrete_map,
        opacity=opacity,
    )

    captured_color_map = {}
    for tr in px_fig.data:
        cat = tr.name
        col = getattr(getattr(tr, "marker", None), "color", None) or getattr(getattr(tr, "line", None), "color", None)
        if isinstance(cat, str) and col is not None and cat not in captured_color_map:
            captured_color_map[cat] = col

    for tr in px_fig.data:
        base_name = tr.name
        tr.opacity = opacity
        if name_suffix:
            tr.name = f"{base_name} [{name_suffix}]"
        tr.legendgroup = base_name
    base_fig.add_traces(px_fig.data)

    if not ignore_otr and otr_mask.any():
        curve_set_df.loc[otr_mask, label_col] = curve_set_df.loc[otr_mask, label_col].apply(lambda x: f"OTR - {x}")
        sub = curve_set_df[otr_mask]
        otr_fig = px.scatter(
            sub,
            x=ttm_col,
            y=ytm_col,
            color=label_col,
            hover_data=_make_hover_dict(sub, hover_data),
            color_discrete_map=color_discrete_map,
            opacity=opacity,
        )
        for tr in otr_fig.data:
            tr.opacity = opacity
            base_name = tr.name
            if name_suffix:
                tr.name = f"{base_name} [{name_suffix}]"
            tr.legendgroup = base_name
            tr.update(marker=dict(line=dict(color="white", width=2)))
        base_fig.add_traces(otr_fig.data)

    if cusips_hightlighter:
        for cusip_tuple in cusips_hightlighter:
            cusip, label_color = cusip_tuple if isinstance(cusip_tuple, tuple) else (cusip_tuple, "yellow")
            if cusip not in curve_set_df[cusip_col].values:
                print(f"{cusip} not in Curveset df!")
                continue
            sub = curve_set_df[curve_set_df[cusip_col] == cusip]
            hi_fig = px.scatter(
                sub,
                x=ttm_col,
                y=ytm_col,
                color=cusip_col,
                hover_data=_make_hover_dict(sub, hover_data),
                opacity=opacity,
            )
            for tr in hi_fig.data:
                tr.opacity = opacity
                base_name = tr.name
                if name_suffix:
                    tr.name = f"{base_name} [{name_suffix}]"
                tr.legendgroup = base_name
                tr.update(marker=dict(line=dict(color=label_color, width=4)))
            base_fig.add_traces(hi_fig.data)

    if ust_labels_highlighter:
        tuples = ust_labels_highlighter if isinstance(ust_labels_highlighter[0], tuple) else [(lab, "yellow") for lab in ust_labels_highlighter]
        for ust_label, label_color in tuples:
            if ust_label not in curve_set_df["ust_label"].values:
                print(f"{ust_label} not in Curveset df!")
                continue
            sub = curve_set_df[curve_set_df["ust_label"] == ust_label]
            lab_fig = px.scatter(
                sub,
                x=ttm_col,
                y=ytm_col,
                color="ust_label",
                hover_data=_make_hover_dict(sub, hover_data),
                opacity=opacity,
            )
            for tr in lab_fig.data:
                tr.opacity = opacity
                base_name = tr.name
                if name_suffix:
                    tr.name = f"{base_name} [{name_suffix}]"
                tr.legendgroup = base_name
                tr.update(marker=dict(line=dict(color=label_color, width=4)))
            base_fig.add_traces(lab_fig.data)

    if splines:
        ttm_linspace = np.linspace(spline_lb, spline_ub, linspace_num)
        for curve_tup in splines:
            if len(curve_tup) == 3:
                interp_func, s_label, spline_color = curve_tup
            else:
                interp_func, s_label = curve_tup
                spline_color = "white"
            sname = f"{s_label} [{name_suffix}]" if name_suffix else s_label
            base_fig.add_trace(
                go.Scatter(
                    x=ttm_linspace,
                    y=interp_func(ttm_linspace),
                    mode="lines",
                    name=sname,
                    marker=dict(color=spline_color),
                    line=dict(color=spline_color),
                    opacity=opacity,
                )
            )

    base_fig.update_layout(
        xaxis_title=custom_x_axis,
        yaxis_title=custom_y_axis,
        title=title or "Yield Curve",
        showlegend=True,
        template="plotly_dark",
        height=plot_height,
        width=plot_width,
        legend_title_text=label_col,
        newshape={"line": {"color": "red"}},
    )
    base_fig.update_xaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikemode="across", hoverformat=".3f")
    base_fig.update_yaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikethickness=0.5, hoverformat=".3f")
    base_fig.update_coloraxes(showscale=False)

    if show:
        base_fig.show(
            config={
                "modeBarButtonsToAdd": [
                    "drawline",
                    "drawopenpath",
                    "drawclosedpath",
                    "drawcircle",
                    "drawrect",
                    "eraseshape",
                ],
            }
        )

    return (base_fig, captured_color_map) if return_color_map else base_fig
