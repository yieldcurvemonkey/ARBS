"""One book as one interactive figure: stacked panels on a shared axis with a crosshair.

Generalised from ``notebooks/backtests/econ_release_fade/econ_fade_plotly.py``, which built this
shape for one study. The reasoning that motivated it holds for any book, so it is repeated here:

**Which trades the line is made of.** A cumulative curve that ends positive can be one enormous
winner and forty small losers. The per-trade bar sits directly under the curve, coloured by how
each trade ended, so the distribution and the path are read together.

**When the strategy was not trading.** Event-driven books are sparse — tens of trades over years —
so markers rather than a dense line keep the sparsity honest instead of letting interpolation
imply continuous exposure.

**What the exit actually did.** A book that takes its target and one that mostly times out are
different businesses at the same mean, so the exit category is the colour axis throughout.

Three things are general here that were not general there:

1. **Units.** bp or currency, carried on :class:`~RVUtils.BookViz.spec.BookSpec`, never guessed.
2. **The curve can be the engine's own marked series.** Pass ``equity=`` and the top panel draws
   *that*, with the trades placed on it. This is not cosmetic. For a financed book the cumulative
   sum of trade P&L is not the equity curve — the difference is carry — and a dashboard that
   silently re-derives the curve from the ledger will disagree with the engine that produced it.
   When both are supplied, both are drawn, because the gap between them is worth seeing.
3. **A component panel.** ``components=`` draws a P&L decomposition (price, coupons, financing,
   open mark) as lines on a shared axis, so a book whose gross result is dominated by one
   component says so on its face.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from RVUtils.BookViz.spec import BookSpec, resolve_spec
from RVUtils.BookViz.stats import book_stats
from RVUtils.BookViz.theme import (ACCENT, BG, FG, GRID, MUTED, NEG, PANEL,
                                   SERIES_PALETTE, category_colour)

__all__ = ["book_dashboard"]


def _times(df: pd.DataFrame, s: BookSpec) -> pd.Series:
    t = pd.to_datetime(df[s.time], errors="coerce", utc=True)
    if s.tz:
        t = t.dt.tz_convert(s.tz)
    return t


def _hover(df: pd.DataFrame, s: BookSpec, ts: pd.Series, net: np.ndarray, cum: np.ndarray):
    """The whole trade record, one row per line, so a marker answers every obvious question."""
    n = len(df)

    def col(name: Optional[str], fmt=None):
        if not name or name not in df.columns:
            return np.array(["-"] * n, dtype=object)
        v = df[name]
        if fmt is not None:
            return pd.to_numeric(v, errors="coerce").map(fmt).astype(object).to_numpy()
        return v.astype(str).to_numpy()

    num = lambda x: "-" if pd.isna(x) else s.fmt(float(x))  # noqa: E731

    parts = [
        ts.dt.strftime("%Y-%m-%d %H:%M").to_numpy(),
        col(s.label),
        col(s.category),
        col(s.signal, lambda x: "-" if pd.isna(x) else f"{x:.3f}"),
        col(s.hold, lambda x: "-" if pd.isna(x) else f"{x:.1f}"),
        col(s.gross, num),
        np.array([s.fmt(v) for v in net], dtype=object),
        np.array([s.fmt(v) for v in cum], dtype=object),
    ]
    tmpl = ("<b>%{customdata[0]}</b><br>"
            "%{customdata[1]}  ·  exit <b>%{customdata[2]}</b><br>"
            f"{s.signal or 'signal'}: %{{customdata[3]}}   hold: %{{customdata[4]}}<br>"
            f"gross %{{customdata[5]}} {s.axis_unit}   <b>net %{{customdata[6]}} {s.axis_unit}</b><br>"
            f"cumulative %{{customdata[7]}} {s.axis_unit}")
    for i, extra in enumerate(s.extra_hover or ()):
        parts.append(col(extra))
        tmpl += f"<br>{extra}: %{{customdata[{len(parts) - 1}]}}"
    return np.column_stack(parts), tmpl + "<extra></extra>"


def book_dashboard(
    df: Optional[pd.DataFrame],
    *,
    title: str = "book",
    spec: Optional[BookSpec] = None,
    equity: Optional[pd.Series] = None,
    components: Optional[Mapping[str, pd.Series]] = None,
    span_years: Optional[float] = None,
    height: int = 1120,
) -> go.Figure:
    """The whole book as one figure.

    Parameters
    ----------
    df
        Trade ledger, one row per closed trade. May be ``None`` when only ``equity`` is available.
    equity
        The engine's own marked series, indexed by time. Drawn as the curve when present.
    components
        ``{name: series}`` P&L decomposition, each indexed by time. Drawn as its own panel.
    span_years
        Required for any annualised statistic; nothing is annualised without it.
    """
    has_trades = df is not None and not df.empty
    if not has_trades and equity is None:
        return go.Figure(layout=dict(template="plotly_dark", title=f"{title} — nothing to plot"))

    s = resolve_spec(df, spec) if has_trades else (spec or BookSpec())

    if has_trades:
        d = df.copy()
        d[s.time] = _times(d, s)
        d = d.sort_values(s.time).reset_index(drop=True)
        ts = d[s.time]
        net = pd.to_numeric(d[s.pnl], errors="coerce").fillna(0.0).to_numpy(float)
        cum = np.cumsum(net)
        cats = d[s.category].astype(str) if s.category and s.category in d else pd.Series(["-"] * len(d))
        colours = [category_colour(c) for c in cats]
        custom, hovertmpl = _hover(d, s, ts, net, cum)
    else:
        d, ts, net, cum, cats, colours, custom, hovertmpl = (None,) * 8

    eq = None
    if equity is not None:
        eq = pd.to_numeric(pd.Series(equity), errors="coerce").dropna()
        eq.index = pd.to_datetime(eq.index, utc=True)
        if s.tz:
            eq.index = eq.index.tz_convert(s.tz)
        eq = eq.sort_index()

    rows = ["equity"]
    if has_trades:
        rows += ["per_trade"]
    rows += ["drawdown"]
    if components:
        rows += ["components"]
    if has_trades and s.signal:
        rows += ["signal"]
    rows += ["summary"]

    titles = {
        "equity": f"cumulative {s.axis_unit}" + ("  —  marked equity (solid) vs Σ trades (dashed)"
                                                 if (eq is not None and has_trades) else ""),
        "per_trade": f"per-trade net {s.axis_unit}, coloured by how the trade ended",
        "drawdown": f"drawdown from peak ({s.axis_unit})",
        "components": "P&L components",
        "signal": f"signal ({s.signal}) against realised net {s.axis_unit}",
        "summary": "summary",
    }
    weights = {"equity": 0.30, "per_trade": 0.16, "drawdown": 0.12,
               "components": 0.15, "signal": 0.15, "summary": 0.20}
    hs = np.array([weights[r] for r in rows], dtype=float)
    hs = hs / hs.sum()

    fig = make_subplots(
        rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.035,
        row_heights=list(hs),
        specs=[[{"type": "table"}] if r == "summary" else [{}] for r in rows],
        subplot_titles=[titles[r] for r in rows],
    )
    at = {r: i + 1 for i, r in enumerate(rows)}

    # ---- equity -----------------------------------------------------------
    if eq is not None:
        fig.add_trace(go.Scatter(x=eq.index, y=eq.to_numpy(), name="marked equity", mode="lines",
                                 line=dict(color=ACCENT, width=2),
                                 hovertemplate=f"%{{x|%Y-%m-%d}}<br>equity %{{y:,.2f}} {s.axis_unit}"
                                               "<extra></extra>"),
                      row=at["equity"], col=1)
    if has_trades:
        # When a marked curve exists the trade sum is drawn dashed BESIDE it rather than instead of
        # it: the gap between the two is the carry, and hiding it is what let a book be reported as
        # +7.9m when it made +0.4m.
        fig.add_trace(go.Scatter(
            x=ts, y=cum, name="Σ trades",
            mode="lines+markers" if eq is None else "lines",
            line=dict(color=(MUTED if eq is not None else ACCENT), width=1.4,
                      dash=("dash" if eq is not None else "solid")),
            marker=(dict(size=8, color=colours, line=dict(width=1, color=BG)) if eq is None else None),
            customdata=custom, hovertemplate=hovertmpl),
            row=at["equity"], col=1)
        if eq is not None:
            fig.add_trace(go.Scatter(x=ts, y=np.interp(ts.astype("int64"),
                                                       eq.index.astype("int64"), eq.to_numpy()),
                                     name="trades", mode="markers",
                                     marker=dict(size=8, color=colours,
                                                 line=dict(width=1, color=BG)),
                                     customdata=custom, hovertemplate=hovertmpl),
                          row=at["equity"], col=1)
    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=at["equity"], col=1)

    # ---- per-trade bars ----------------------------------------------------
    if has_trades:
        for r in pd.unique(cats):
            m = (cats == r).to_numpy()
            fig.add_trace(go.Bar(x=ts[m], y=net[m], name=str(r),
                                 marker_color=category_colour(r),
                                 customdata=custom[m], hovertemplate=hovertmpl),
                          row=at["per_trade"], col=1)
        fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=at["per_trade"], col=1)

    # ---- drawdown ----------------------------------------------------------
    dd_src = eq if eq is not None else (pd.Series(cum, index=ts) if has_trades else None)
    if dd_src is not None and len(dd_src):
        dd = dd_src - dd_src.cummax()
        fig.add_trace(go.Scatter(x=dd.index, y=dd.to_numpy(), name="drawdown", mode="lines",
                                 line=dict(color=NEG, width=1.4), fill="tozeroy",
                                 fillcolor="rgba(255,92,92,0.18)",
                                 hovertemplate=f"drawdown %{{y:,.2f}} {s.axis_unit}<extra></extra>"),
                      row=at["drawdown"], col=1)

    # ---- components --------------------------------------------------------
    if components:
        for i, (name, ser) in enumerate(components.items()):
            c = pd.to_numeric(pd.Series(ser), errors="coerce").dropna()
            if c.empty:
                continue
            c.index = pd.to_datetime(c.index, utc=True)
            if s.tz:
                c.index = c.index.tz_convert(s.tz)
            c = c.sort_index()
            fig.add_trace(go.Scatter(x=c.index, y=c.to_numpy(), name=str(name), mode="lines",
                                     line=dict(color=SERIES_PALETTE[i % len(SERIES_PALETTE)], width=1.6),
                                     hovertemplate=f"<b>{name}</b> %{{y:,.2f}} {s.axis_unit}<extra></extra>"),
                          row=at["components"], col=1)
        fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=at["components"], col=1)

    # ---- signal vs outcome -------------------------------------------------
    if has_trades and s.signal and "signal" in at:
        fig.add_trace(go.Scatter(x=ts, y=pd.to_numeric(d[s.signal], errors="coerce"),
                                 name=str(s.signal), mode="markers",
                                 marker=dict(size=9, color=net, colorscale="RdYlGn", cmid=0,
                                             line=dict(width=1, color=BG),
                                             colorbar=dict(title=f"net {s.axis_unit}", len=0.14,
                                                           y=0.28, thickness=10)),
                                 customdata=custom, hovertemplate=hovertmpl),
                      row=at["signal"], col=1)
        fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=at["signal"], col=1)

    # ---- summary -----------------------------------------------------------
    stats = (book_stats(d, spec=s, span_years=span_years, equity=eq) if has_trades
             else _equity_only_table(eq, s))
    fig.add_trace(go.Table(
        columnwidth=[38, 62],
        header=dict(values=["<b>metric</b>", "<b>value</b>"], fill_color=PANEL,
                    font=dict(color=FG, size=11), align="left", line_color=GRID),
        cells=dict(values=[stats["metric"], stats["value"]],
                   fill_color=[[BG, PANEL] * (len(stats) // 2 + 1)],
                   font=dict(color=FG, size=11), align="left", height=20, line_color=GRID)),
        row=at["summary"], col=1)

    # ---- crosshair across every panel --------------------------------------
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikecolor=MUTED,
                     spikethickness=1, spikedash="dot", showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_yaxes(showspikes=True, spikemode="toaxis", spikesnap="cursor", spikecolor=MUTED,
                     spikethickness=1, spikedash="dot", showgrid=True, gridcolor=GRID, zeroline=False)

    head = f"<b>{title}</b>"
    if has_trades:
        head += (f"   ·   {len(d)} trades   ·   net {s.fmt(net.mean())} {s.axis_unit}/trade"
                 f"   ·   hit {(net > 0).mean() * 100:.1f}%")
    if eq is not None and len(eq):
        head += f"   ·   end equity {s.fmt(float(eq.iloc[-1]))} {s.axis_unit}"

    fig.update_layout(
        template="plotly_dark", height=height,
        title=dict(text=head, x=0.01, font=dict(size=15)),
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=FG, size=11),
        hovermode="closest", hoverdistance=30,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(color=FG, size=11)),
        legend=dict(orientation="h", y=1.045, x=0.26, bgcolor="rgba(0,0,0,0)"),
        bargap=0.55, margin=dict(l=70, r=30, t=90, b=40),
    )
    for r in rows:
        if r != "summary":
            fig.update_yaxes(title_text=s.axis_unit, row=at[r], col=1)
    for a in fig.layout.annotations[:len(rows)]:
        a.update(x=0.005, xanchor="left", font=dict(size=11, color=MUTED))
    return fig


def _equity_only_table(eq: Optional[pd.Series], s: BookSpec) -> pd.DataFrame:
    from RVUtils.BookViz.stats import equity_stats

    if eq is None or eq.empty:
        return pd.DataFrame(columns=["metric", "value"])
    return equity_stats(eq, unit=s.axis_unit)
