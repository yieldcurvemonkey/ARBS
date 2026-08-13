"""Several books on one pair of axes, where the interesting quantity is the gap between curves.

Written originally for a direction fork (fade against momentum against the flip) and for real
against placebo. It generalises unchanged to a config sweep — the GSS variant set is exactly this
shape: one book per configuration, and the question is which curve separates, not the level of any
one of them.

Each book may be a trade ledger, a marked equity series, or both. Mixing them in one call is
allowed and is often what you want: a marked curve for the book you trust and a trade sum for the
one you are checking it against.
"""

from __future__ import annotations

from typing import Mapping, Optional, Union

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from RVUtils.BookViz.spec import BookSpec, resolve_spec
from RVUtils.BookViz.theme import BG, FG, GRID, MUTED, PANEL, SERIES_PALETTE

__all__ = ["compare_books", "curve_of"]

BookLike = Union[pd.DataFrame, pd.Series]


def curve_of(book: BookLike, *, spec: Optional[BookSpec] = None, tz: Optional[str] = None) -> pd.Series:
    """A cumulative curve from either a trade ledger or an already-marked equity series.

    A ``Series`` is taken as already cumulative and is NOT re-summed — re-cumulating an equity
    curve is a silent way to plot a quantity that has no meaning, and it looks plausible.
    """
    if isinstance(book, pd.Series):
        c = pd.to_numeric(book, errors="coerce").dropna()
        c.index = pd.to_datetime(c.index, utc=True)
        return c.tz_convert(tz).sort_index() if tz else c.sort_index()

    s = resolve_spec(book, spec)
    d = book.copy()
    t = pd.to_datetime(d[s.time], errors="coerce", utc=True)
    if tz or s.tz:
        t = t.dt.tz_convert(tz or s.tz)
    d = d.assign(_t=t).sort_values("_t")
    return pd.Series(pd.to_numeric(d[s.pnl], errors="coerce").fillna(0.0).cumsum().to_numpy(),
                     index=d["_t"])


def compare_books(
    books: Mapping[str, BookLike],
    *,
    title: str = "comparison",
    spec: Optional[BookSpec] = None,
    unit: Optional[str] = None,
    tz: Optional[str] = None,
    height: int = 560,
    show_drawdown: bool = True,
) -> go.Figure:
    """Cumulative curves and their drawdowns, one colour per book."""
    u = unit or (spec.axis_unit if spec else "bp")
    rows = 2 if show_drawdown else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        row_heights=[0.66, 0.34][:rows],
                        subplot_titles=[f"cumulative {u}", f"drawdown ({u})"][:rows])

    drawn = 0
    for i, (name, book) in enumerate(books.items()):
        if book is None or (hasattr(book, "empty") and book.empty):
            continue
        try:
            c = curve_of(book, spec=spec, tz=tz)
        except ValueError:
            continue
        if c.empty:
            continue
        colour = SERIES_PALETTE[drawn % len(SERIES_PALETTE)]
        drawn += 1
        is_sparse = len(c) <= 250
        fig.add_trace(go.Scatter(x=c.index, y=c.to_numpy(), name=str(name),
                                 mode="lines+markers" if is_sparse else "lines",
                                 line=dict(color=colour, width=2),
                                 marker=dict(size=5) if is_sparse else None,
                                 hovertemplate=(f"<b>{name}</b><br>%{{x|%Y-%m-%d}}<br>"
                                                f"cum %{{y:,.3f}} {u}<extra></extra>")),
                      row=1, col=1)
        if show_drawdown:
            fig.add_trace(go.Scatter(x=c.index, y=(c - c.cummax()).to_numpy(),
                                     name=f"{name} dd", mode="lines",
                                     line=dict(color=colour, width=1, dash="dot"),
                                     showlegend=False, hoverinfo="skip"), row=2, col=1)

    if not drawn:
        return go.Figure(layout=dict(template="plotly_dark", title=f"{title} — nothing to plot"))

    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=1, col=1)
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", spikecolor=MUTED,
                     spikethickness=1, spikedash="dot", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False)
    fig.update_layout(template="plotly_dark", height=height, paper_bgcolor=BG, plot_bgcolor=BG,
                      font=dict(color=FG, size=11), hovermode="x unified",
                      hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID),
                      title=dict(text=f"<b>{title}</b>", x=0.01, font=dict(size=14)),
                      legend=dict(orientation="h", y=1.10, x=0.22, bgcolor="rgba(0,0,0,0)"),
                      margin=dict(l=70, r=30, t=80, b=40))
    for a in fig.layout.annotations:
        a.update(x=0.005, xanchor="left", font=dict(size=11, color=MUTED))
    return fig
