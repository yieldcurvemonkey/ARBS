"""An interactive trade dashboard for any book this repo produces.

One figure, five stacked panels on a shared time axis, dark, with a crosshair
that tracks the cursor across all of them. Every marker is one trade and carries
its whole record in the tooltip -- what triggered it, which way it went, how long
it was held, why it ended, and what it paid gross and net.

Three things this is built to make visible, because a static equity curve hides
all of them.

**Which trades the line is made of.** A cumulative curve that ends positive can
be one enormous winner and forty small losers. Panel 2 is the per-trade bar,
coloured by how the trade ended, so the shape of the distribution sits directly
under the shape of the curve.

**When the strategy was not trading.** Event books are sparse -- tens of trades
over years -- so the x axis is mostly empty. Markers rather than a dense line
keep the sparsity honest instead of letting interpolation imply continuous
exposure.

**What ended the trade.** A strategy that takes its target and one that mostly
times out are different businesses at the same mean, so the exit reason is the
colour axis throughout. Where a book has no exit reason, any categorical column
can take that role -- ``colour_col``.

The summary panel is computed from the same frame that draws the curve, so a
number in the table and a point on the line cannot disagree.

Sources
-------
``to_book`` normalises three shapes onto one canonical frame, and every entry
point takes any of them:

* a **trade log DataFrame** -- ``pnl_bp`` plus a timestamp, which is what the
  closed-form event studies produce (``econ_release_fade``, the FOMC speaker
  books). Column names are auto-detected and can be overridden.
* a **QueryDrivenBacktest** -- the closed-position log is walked by
  ``BT.query_tearsheet.closed_trade_frame`` and the P&L is in currency, not
  basis points, so every axis label and every summary row follows the book's
  own unit rather than assuming bp.
* a **QueryBacktestTearSheet / QueryBacktestAnalytics** -- the same, one hop up.

**On a QueryDrivenBacktest, read the two curves.** ``realized_pnl`` in the
closed log is the PRICE leg only: coupons and financing are realised during the
hold and never appear there, and open positions are not in it at all. So when a
backtest is passed, ``mtm_history`` -- the engine's own cumulative total -- is
drawn alongside as a dotted overlay and the terminal gap between them is stated
on the figure. A closed-log curve that sits far from the total is not a bug in
either; it is carry and open MTM, and it is the difference between a strategy's
price leg and its P&L.

The plotly renderer is deliberately NOT pinned here. Pinning is a global
mutation and a library has no business doing it at import; notebooks that need
``plotly_mimetype+notebook_connected`` set it themselves.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

import plotly.graph_objects as go
from plotly.subplots import make_subplots

BG = "#0e1117"
PANEL = "#161a23"
GRID = "#2a3040"
FG = "#d8dee9"
MUTED = "#7b8394"

#: exit reason -> colour. Green takes profit, red stops, amber runs out of clock.
REASON_COLOUR = {
    "target": "#3ddc84", "stop": "#ff5c5c", "trail": "#ff9f43",
    "time_stop": "#f6c744", "eod": "#9b8cff", "no_path": MUTED,
}

#: for a colour axis that is not an exit reason -- roles, speakers, products.
CATEGORICAL = ["#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744",
               "#40c4aa", "#e879f9", "#94a3b8", "#fb923c"]

#: canonical column names. A frame carrying these in ``attrs["book"]`` is
#: already normalised and passes through ``to_book`` untouched.
_T, _PNL, _GROSS, _COST = "_t", "_pnl", "_gross", "_cost"
_LABEL, _SIDE, _REASON, _HOLD, _SIGNAL = "_label", "_side", "_reason", "_hold", "_signal"

_TIME_COLS = ("release_ts", "entry_ts", "opened_at", "closed_at", "timestamp")
_PNL_COLS = ("pnl_bp", "pnl", "realized_pnl", "net_bp")
_GROSS_COLS = ("pnl_bp_gross", "gross_realized_pnl", "gross_bp")
_COST_COLS = ("cost_bp", "fee_allocated", "cost")
_LABEL_COLS = ("release", "lead_title", "query_label", "product", "speaker",
               "structure", "symbol")
_SIDE_COLS = ("side", "direction", "direction_label")
_SIGNAL_COLS = ("z", "move_bp", "surprise", "bucket", "signal")
_COLOUR_COLS = ("exit_reason",)


def _pick(df: pd.DataFrame, *names: str) -> Optional[str]:
    """First of ``names`` that is actually a column."""
    for n in names:
        if n in df.columns:
            return n
    return None


def _is_backtest(obj: Any) -> bool:
    """Duck-typed, so importing this module never drags in the engine."""
    return hasattr(obj, "mtm_history") and hasattr(obj, "portfolio")


def _unit_for(col: Optional[str], override: Optional[str]) -> str:
    if override is not None:
        return override
    if col and (col.endswith("_bp") or col in {"move_bp", "net_bp"}):
        return "bp"
    return ""


def _u(unit: str) -> str:
    """' bp' or '' -- so a currency book does not read 'net  / trade'."""
    return f" {unit}" if unit else ""


# ===========================================================================
# Normalisation
# ===========================================================================
def to_book(source: Any, *, time_col: Optional[str] = None,
            pnl_col: Optional[str] = None, unit: Optional[str] = None,
            signal_col: Optional[str] = None, colour_col: Optional[str] = None,
            label_col: Optional[str] = None, side_col: Optional[str] = None,
            size_metric: Optional[str] = None) -> pd.DataFrame:
    """Any supported book -> the canonical frame every panel is drawn from.

    The returned frame keeps its original columns and adds the canonical ones,
    so a caller can still group by whatever the study called things. Metadata
    that is not per-trade (the unit, the names behind the signal and colour
    axes, the engine's own equity curve) rides in ``.attrs``.
    """
    if isinstance(source, pd.DataFrame):
        if source.attrs.get("book"):
            return source
        return _book_from_frame(source, time_col=time_col, pnl_col=pnl_col,
                                unit=unit, signal_col=signal_col,
                                colour_col=colour_col, label_col=label_col,
                                side_col=side_col)

    # a tearsheet or an analytics bundle -> the backtest inside it
    bt = source
    for attr in ("analytics", "backtest"):
        if not _is_backtest(bt) and hasattr(bt, attr):
            bt = getattr(bt, attr)
    if not _is_backtest(bt):
        raise TypeError(
            f"cannot read a book out of {type(source).__name__}. Pass a trade-log "
            "DataFrame, a QueryDrivenBacktest, or a QueryBacktestTearSheet.")

    # Lazy: BT.query_tearsheet imports the engine, which imports the MDP stack.
    # A notebook plotting a closed-form book should not pay for that.
    from BT.query_tearsheet import closed_trade_frame

    closed = closed_trade_frame(bt, size_metric=size_metric)
    if closed.empty:
        book = _book_from_frame(pd.DataFrame({"closed_at": [], "realized_pnl": []}),
                                unit=unit or "")
    else:
        book = _book_from_frame(
            closed,
            time_col=time_col or "closed_at",
            pnl_col=pnl_col or "realized_pnl",
            unit=unit or "",                       # currency, not basis points
            signal_col=signal_col,
            colour_col=colour_col or "exit_reason",
            label_col=label_col or "query_label",
            side_col=side_col or "direction")
    book.attrs["source"] = "QueryDrivenBacktest"
    mtm = getattr(bt, "mtm_history", None)
    if mtm:
        book.attrs["mtm"] = pd.Series(dict(mtm), dtype=float).sort_index()
    name = getattr(getattr(bt, "strategy", None), "name", None)
    if name:
        book.attrs["name"] = str(name)
    return book


def _book_from_frame(df: pd.DataFrame, *, time_col=None, pnl_col=None, unit=None,
                     signal_col=None, colour_col=None, label_col=None,
                     side_col=None) -> pd.DataFrame:
    d = df.copy()
    tcol = time_col or _pick(d, *_TIME_COLS)
    pcol = pnl_col or _pick(d, *_PNL_COLS)
    if tcol is None or pcol is None:
        raise KeyError(
            f"need a timestamp and a P&L column; looked for {_TIME_COLS} and "
            f"{_PNL_COLS}, found {list(d.columns)[:12]}. Pass time_col=/pnl_col=.")

    d[_T] = pd.to_datetime(d[tcol], utc=True)
    d = d.sort_values(_T).reset_index(drop=True)
    d[_PNL] = pd.to_numeric(d[pcol], errors="coerce").astype(float)
    d = d[np.isfinite(d[_PNL])].reset_index(drop=True)

    gcol = _pick(d, *_GROSS_COLS)
    ccol = _pick(d, *_COST_COLS)
    d[_GROSS] = pd.to_numeric(d[gcol], errors="coerce") if gcol else np.nan
    d[_COST] = pd.to_numeric(d[ccol], errors="coerce") if ccol else np.nan

    lcol = label_col or _pick(d, *_LABEL_COLS)
    d[_LABEL] = d[lcol].astype(str) if lcol else "-"

    scol = side_col or _pick(d, *_SIDE_COLS)
    if scol and pd.api.types.is_numeric_dtype(d[scol]):
        d[_SIDE] = np.where(d[scol] > 0, "LONG", np.where(d[scol] < 0, "SHORT", "FLAT"))
    elif scol:
        d[_SIDE] = d[scol].astype(str)
    else:
        d[_SIDE] = "-"

    rcol = colour_col if colour_col is not None else _pick(d, *_COLOUR_COLS)
    if rcol and rcol not in d.columns:
        raise KeyError(f"colour_col {rcol!r} is not a column; have {list(d.columns)[:12]}")
    d[_REASON] = d[rcol].astype(str) if rcol else "-"

    # hold: minutes if the book measures in minutes, days if it measures in days,
    # otherwise derived from the two timestamps. The unit travels with the value
    # so the tooltip never says "after 3 min" about a three-day position.
    hold_unit = ""
    if "hold_min" in d.columns:
        d[_HOLD], hold_unit = pd.to_numeric(d["hold_min"], errors="coerce"), "min"
    elif "holding_period_days" in d.columns:
        d[_HOLD], hold_unit = pd.to_numeric(d["holding_period_days"], errors="coerce"), "d"
    elif {"opened_at", "closed_at"} <= set(d.columns):
        delta = pd.to_datetime(d["closed_at"], utc=True) - pd.to_datetime(d["opened_at"], utc=True)
        d[_HOLD], hold_unit = delta.dt.total_seconds() / 60.0, "min"
    else:
        d[_HOLD] = np.nan

    sig = signal_col if signal_col is not None else _pick(d, *_SIGNAL_COLS)
    if sig and sig not in d.columns:
        raise KeyError(f"signal_col {sig!r} is not a column; have {list(d.columns)[:12]}")
    d[_SIGNAL] = pd.to_numeric(d[sig], errors="coerce") if sig else np.nan

    d.attrs.update({
        "book": True,
        "unit": _unit_for(pcol, unit),
        "signal_name": sig,
        "colour_name": rcol,
        "label_name": lcol,
        "hold_unit": hold_unit,
        "time_name": tcol,
        "has_gross": gcol is not None,
        "has_cost": ccol is not None,
        "source": "frame",
    })
    return d


# ===========================================================================
# Numbers
# ===========================================================================
def summary_stats(source: Any, *, span_years: Optional[float] = None,
                  **kw: Any) -> pd.DataFrame:
    """Every headline number for a book, from the book itself.

    ``span_years`` annualises. It is left to the caller because a book of 41
    event-driven trades has no natural frequency, and inventing one is how a
    Sharpe of 0.3 per trade becomes a Sharpe of 3.
    """
    d = to_book(source, **kw)
    unit = d.attrs.get("unit", "")
    p = d[_PNL].to_numpy(float) if len(d) else np.array([])
    if not len(p):
        return pd.DataFrame(columns=["metric", "value"])
    wins, losses = p[p > 0], p[p <= 0]
    sd = p.std(ddof=1) if len(p) > 1 else 0.0
    eq = np.cumsum(p)
    dd = eq - np.maximum.accumulate(eq)

    # longest run of winners, and of losers
    def _streak(mask):
        best = cur = 0
        for v in mask:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return best

    srt = float(p.mean() / sd) if sd > 0 else 0.0
    hold_unit = d.attrs.get("hold_unit", "")
    rows = [
        ("trades", f"{len(p):,}"),
        (f"net{_u(unit)} / trade", f"{p.mean():+.4f}"),
        (f"gross{_u(unit)} / trade",
         f"{d[_GROSS].mean():+.4f}" if d.attrs.get("has_gross") else "-"),
        (f"cost{_u(unit)} / trade",
         f"{d[_COST].mean():.4f}" if d.attrs.get("has_cost") else "-"),
        (f"total net{_u(unit)}", f"{p.sum():+.2f}"),
        ("hit rate", f"{(p > 0).mean() * 100:.1f}%"),
        ("avg win / avg loss", f"{wins.mean():+.3f} / {losses.mean():+.3f}"
         if len(wins) and len(losses) else "-"),
        ("payoff ratio", f"{wins.mean() / abs(losses.mean()):.3f}"
         if len(wins) and len(losses) and losses.mean() != 0 else "-"),
        ("Sharpe / trade", f"{srt:.4f}"),
        ("t-statistic", f"{p.mean() / (sd / np.sqrt(len(p))):.2f}" if sd > 0 else "-"),
        ("best / worst trade", f"{p.max():+.3f} / {p.min():+.3f}"),
        (f"max drawdown ({unit})" if unit else "max drawdown", f"{dd.min():.2f}"),
        ("longest win / loss run", f"{_streak(p > 0)} / {_streak(p <= 0)}"),
        (f"avg hold ({hold_unit})" if hold_unit else "avg hold",
         f"{d[_HOLD].mean():.1f}" if np.isfinite(d[_HOLD]).any() else "-"),
    ]
    if span_years and span_years > 0:
        rows.append(("trades / year", f"{len(p) / span_years:.1f}"))
        rows.append(("annualised Sharpe", f"{srt * np.sqrt(len(p) / span_years):.4f}"))
    cname = d.attrs.get("colour_name")
    if cname:
        mix = d[_REASON].value_counts(normalize=True)
        rows.append((f"{cname} mix" if cname != "exit_reason" else "exit mix",
                     "  ".join(f"{k} {v*100:.0f}%" for k, v in mix.items())))
    return pd.DataFrame(rows, columns=["metric", "value"])


def _colours(reason: pd.Series) -> list:
    """Known exit reasons keep their meaning; anything else gets a stable slot."""
    vals = [str(r) for r in reason]
    unknown = [v for v in dict.fromkeys(vals) if v not in REASON_COLOUR]
    extra = {v: CATEGORICAL[i % len(CATEGORICAL)] for i, v in enumerate(unknown)}
    if unknown == ["-"]:
        extra = {"-": MUTED}
    return [REASON_COLOUR.get(v, extra.get(v, MUTED)) for v in vals]


# ===========================================================================
# The figure
# ===========================================================================
def trade_dashboard(source: Any, *, title: str = "book",
                    span_years: Optional[float] = None,
                    signal_col: Optional[str] = None,
                    colour_col: Optional[str] = None,
                    bar_width: Optional[Any] = None,
                    height: int = 1080, **kw: Any) -> go.Figure:
    """The whole book as one interactive figure.

    ``signal_col`` is the column that triggered the trade -- ``z`` for the
    consensus books, ``bucket`` for the FOMC speaker books. It is auto-detected
    when not given, and drives both the fourth panel and the tooltip. A book
    with no signal gets P&L by group in that panel instead, because an empty
    axis reads as "no relationship" rather than "nothing was measured".

    ``bar_width`` sets the per-trade bar width explicitly, in milliseconds on a
    date axis. Left alone, plotly sizes bars from the SMALLEST gap between two
    trades, so a book with two speeches in one afternoon draws all five hundred
    of its bars one pixel wide and the colour axis stops being legible. Sparse
    books do not need it; dense ones do, and the caller knows which it has --
    ``(t.max() - t.min()) / min(len(book), 400)`` is the usual choice.
    """
    d = to_book(source, signal_col=signal_col, colour_col=colour_col, **kw)
    if d.empty:
        return go.Figure(layout=dict(template="plotly_dark",
                                     title=f"{title} -- no trades"))

    unit = d.attrs.get("unit", "")
    uu = _u(unit)
    signal_col = d.attrs.get("signal_name")
    hold_unit = d.attrs.get("hold_unit", "")
    ts = d[_T].dt.tz_convert("America/New_York")
    reason = d[_REASON]
    colours = _colours(reason)

    net = d[_PNL].to_numpy(float)
    eq = np.cumsum(net)
    dd = eq - np.maximum.accumulate(eq)
    gross = np.cumsum(d[_GROSS].to_numpy(float)) if d.attrs.get("has_gross") else None

    # ---- the tooltip: the entire trade record, one row per line -----------
    def _s(col, nd=3):
        v = d[col]
        return (v.round(nd).astype(str) if pd.api.types.is_numeric_dtype(v)
                else v.astype(str))

    second = _pick(d, "surprise", "d_rate_bp", "size_value")
    custom = np.column_stack([
        ts.dt.strftime("%Y-%m-%d %H:%M ET"),
        d[_LABEL].astype(str).str.slice(0, 42),
        (d["symbol"].astype(str) if "symbol" in d.columns else np.array(["-"] * len(d))),
        d[_SIDE].astype(str),
        (_s(_SIGNAL) if signal_col else ["-"] * len(d)),
        (_s(second) if second else ["-"] * len(d)),
        reason.astype(str),
        (d[_HOLD].round(0).astype(str) if hold_unit else ["-"] * len(d)),
        (d[_GROSS].round(4).astype(str) if d.attrs.get("has_gross") else ["-"] * len(d)),
        np.round(net, 4).astype(str),
        np.round(eq, 3).astype(str),
    ])
    HOVER = ("<b>%{customdata[0]}</b><br>"
             "%{customdata[1]}  ·  %{customdata[2]}  ·  <b>%{customdata[3]}</b><br>"
             f"{signal_col or 'signal'}: %{{customdata[4]}}   {second or 'secondary'}: "
             "%{customdata[5]}<br>"
             "exit: <b>%{customdata[6]}</b> after %{customdata[7]} " + hold_unit + "<br>"
             f"gross %{{customdata[8]}}{uu}   <b>net %{{customdata[9]}}{uu}</b><br>"
             f"cumulative %{{customdata[10]}}{uu}<extra></extra>")

    panel4 = (f"signal ({signal_col}) against realised net{uu}" if signal_col
              else f"net{uu} by {d.attrs.get('label_name') or 'group'}")
    cname = d.attrs.get("colour_name")
    panel2 = (f"per-trade net{uu}, coloured by how the trade ended"
              if cname in (None, "exit_reason")
              else f"per-trade net{uu}, coloured by {cname}")
    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035,
        row_heights=[0.32, 0.19, 0.14, 0.17, 0.18],
        specs=[[{}], [{}], [{}], [{}], [{"type": "table"}]],
        subplot_titles=(f"cumulative net{uu} — every marker is one trade",
                        panel2,
                        f"drawdown from peak ({unit})" if unit else "drawdown from peak",
                        panel4, "summary"))

    # ---- 1. equity ---------------------------------------------------------
    if gross is not None:
        fig.add_trace(go.Scatter(x=ts, y=gross, name="gross", mode="lines",
                                 line=dict(color=MUTED, width=1.2, dash="dot"),
                                 hoverinfo="skip"), row=1, col=1)
    fig.add_trace(go.Scatter(x=ts, y=eq, name="net", mode="lines+markers",
                             line=dict(color="#4dabf7", width=2),
                             marker=dict(size=8, color=colours,
                                         line=dict(width=1, color="#0e1117")),
                             customdata=custom, hovertemplate=HOVER),
                  row=1, col=1)
    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=1, col=1)

    # The engine's own total, when there is one. It includes carry and open
    # positions; the closed log does not. Where they part company, that gap IS
    # the answer to "why does my trade list not add up to my equity curve".
    mtm = d.attrs.get("mtm")
    if mtm is not None and len(mtm):
        m = mtm.copy()
        m.index = pd.to_datetime(m.index, utc=True).tz_convert("America/New_York")
        fig.add_trace(go.Scatter(x=m.index, y=m.to_numpy(float),
                                 name="total P&L (incl. carry & open)", mode="lines",
                                 line=dict(color="#f6c744", width=1.4, dash="dash"),
                                 hovertemplate="total %{y:,.0f}<extra></extra>"),
                      row=1, col=1)
        gap = float(m.iloc[-1]) - float(eq[-1])
        if abs(gap) > 0.01 * max(abs(float(m.iloc[-1])), 1.0):
            fig.add_annotation(
                row=1, col=1, x=m.index[-1], y=float(m.iloc[-1]), xanchor="right",
                text=(f"closed log {eq[-1]:,.0f} vs total {float(m.iloc[-1]):,.0f}"
                      f"  ·  gap {gap:+,.0f} = carry + open MTM"),
                showarrow=False, yshift=14, font=dict(color="#f6c744", size=10))

    # ---- 2. per-trade bars, split so the legend explains the colours -------
    cmap = dict(zip([str(r) for r in reason], colours))
    bw = {} if bar_width is None else {"width": bar_width}
    for r in pd.unique(reason.astype(str)):
        m_ = (reason.astype(str) == r).to_numpy()
        fig.add_trace(go.Bar(x=ts[m_], y=net[m_], name=str(r),
                             marker_color=cmap.get(str(r), MUTED),
                             customdata=custom[m_], hovertemplate=HOVER, **bw),
                      row=2, col=1)
    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=2, col=1)

    # ---- 3. drawdown -------------------------------------------------------
    fig.add_trace(go.Scatter(x=ts, y=dd, name="drawdown", mode="lines",
                             line=dict(color="#ff5c5c", width=1.4),
                             fill="tozeroy", fillcolor="rgba(255,92,92,0.18)",
                             hovertemplate=f"drawdown %{{y:.3f}}{uu}<extra></extra>"),
                  row=3, col=1)

    # ---- 4. signal vs outcome, or the group mix ---------------------------
    if signal_col:
        fig.add_trace(go.Scatter(x=ts, y=d[_SIGNAL], name=signal_col, mode="markers",
                                 marker=dict(size=9, color=net, colorscale="RdYlGn",
                                             cmid=0, line=dict(width=1, color="#0e1117"),
                                             colorbar=dict(title=f"net{uu}", len=0.16,
                                                           y=0.30, thickness=10)),
                                 customdata=custom, hovertemplate=HOVER),
                      row=4, col=1)
        fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=4, col=1)
    else:
        grp = d.groupby(_LABEL)[_PNL].agg(["sum", "size"]).sort_values("sum")
        fig.add_trace(go.Bar(x=grp.index.astype(str), y=grp["sum"], name="by group",
                             marker_color=["#3ddc84" if v > 0 else "#ff5c5c"
                                           for v in grp["sum"]],
                             customdata=np.column_stack([grp["size"]]),
                             hovertemplate=("<b>%{x}</b><br>%{customdata[0]} trades"
                                            f"<br>total %{{y:.3f}}{uu}<extra></extra>")),
                      row=4, col=1)
        fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=4, col=1)

    # ---- 5. summary --------------------------------------------------------
    s = summary_stats(d, span_years=span_years)
    fig.add_trace(go.Table(
        columnwidth=[34, 66],
        header=dict(values=["<b>metric</b>", "<b>value</b>"],
                    fill_color=PANEL, font=dict(color=FG, size=11),
                    align="left", line_color=GRID),
        cells=dict(values=[s["metric"], s["value"]],
                   fill_color=[[BG, PANEL] * (len(s) // 2 + 1)],
                   font=dict(color=FG, size=11), align="left",
                   height=20, line_color=GRID)), row=5, col=1)

    # ---- crosshair ---------------------------------------------------------
    # spikemode "across" draws the vertical through EVERY panel, which is the
    # point: it lines a trade up against its own drawdown and its own signal.
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikecolor=MUTED, spikethickness=1, spikedash="dot",
                     showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(showspikes=True, spikemode="toaxis", spikesnap="cursor",
                     spikecolor=MUTED, spikethickness=1, spikedash="dot",
                     showgrid=True, gridcolor=GRID, zeroline=False)

    fig.update_layout(
        template="plotly_dark", height=height,
        title=dict(text=(f"<b>{title}</b>   ·   {len(d)} trades   ·   "
                         f"net {net.mean():+.4f}{uu}/trade   ·   "
                         f"hit {(net > 0).mean()*100:.1f}%   ·   "
                         f"total {net.sum():+.2f}{uu}"), x=0.01, font=dict(size=15)),
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=FG, size=11),
        hovermode="closest", hoverdistance=30,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(color=FG, size=11)),
        legend=dict(orientation="h", y=1.045, x=0.28, bgcolor="rgba(0,0,0,0)"),
        bargap=0.55, margin=dict(l=60, r=30, t=90, b=40),
    )
    fig.update_yaxes(title_text=f"cum{uu}" if unit else "cum", row=1, col=1)
    fig.update_yaxes(title_text=unit or "pnl", row=2, col=1)
    fig.update_yaxes(title_text=unit or "pnl", row=3, col=1)
    fig.update_yaxes(title_text=signal_col if signal_col else (unit or "pnl"), row=4, col=1)
    for a in fig.layout.annotations[:4]:
        a.update(x=0.005, xanchor="left", font=dict(size=11, color=MUTED))
    return fig


def compare_curves(books: Mapping[str, Any], *, title: str = "comparison",
                   height: int = 520, **kw: Any) -> go.Figure:
    """Several books on one pair of axes -- cumulative, and their drawdowns.

    Written for the direction fork (fade against momentum against the flip) and
    for real against placebo, where the interesting quantity is the gap between
    two curves rather than the level of either.
    """
    # The books are normalised first, because the unit is a property of the
    # books and the panel titles have to carry it -- "drawdown (bp)" over a
    # currency P&L is worse than no label at all.
    norm = [(name, to_book(src, **kw)) for name, src in books.items() if src is not None]
    norm = [(name, d) for name, d in norm if not d.empty]
    unit = norm[0][1].attrs.get("unit", "") if norm else ""
    uu = _u(unit)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        row_heights=[0.66, 0.34],
                        subplot_titles=(f"cumulative net{uu}",
                                        f"drawdown ({unit})" if unit else "drawdown"))
    palette = ["#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744"]
    for i, (name, d) in enumerate(norm):
        t = d[_T].dt.tz_convert("America/New_York")
        eq = d[_PNL].cumsum().to_numpy()
        c = palette[i % len(palette)]
        fig.add_trace(go.Scatter(x=t, y=eq, name=str(name), mode="lines+markers",
                                 line=dict(color=c, width=2), marker=dict(size=5),
                                 hovertemplate=(f"<b>{name}</b><br>%{{x|%Y-%m-%d}}<br>"
                                                f"cum %{{y:.3f}}{uu}<extra></extra>")),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=t, y=eq - np.maximum.accumulate(eq),
                                 name=f"{name} dd", mode="lines",
                                 line=dict(color=c, width=1, dash="dot"),
                                 showlegend=False, hoverinfo="skip"), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=1, col=1)
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikecolor=MUTED, spikethickness=1, spikedash="dot",
                     showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor=BG,
                      plot_bgcolor=BG, font=dict(color=FG, size=11),
                      hovermode="x unified",
                      hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID),
                      title=dict(text=f"<b>{title}</b>", x=0.01, font=dict(size=14)),
                      legend=dict(orientation="h", y=1.10, x=0.25,
                                  bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=60, r=30, t=80, b=40))
    for a in fig.layout.annotations:
        a.update(x=0.005, xanchor="left", font=dict(size=11, color=MUTED))
    return fig
