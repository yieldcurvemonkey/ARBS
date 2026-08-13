"""An interactive trade dashboard for any book this study produces.

One figure, five stacked panels on a shared time axis, dark, with a crosshair
that tracks the cursor across all of them. Every marker is one trade and carries
its whole record in the tooltip -- the release that triggered it, the surprise
and its z, which way the trade went, both prices, how long it was held, why it
ended, and what it paid gross and net.

Three things this is built to make visible, because a static equity curve hides
all of them.

**Which trades the line is made of.** A cumulative curve that ends positive can
be one enormous winner and forty small losers. Panel 2 is the per-trade bar,
coloured by how the trade ended, so the shape of the distribution sits directly
under the shape of the curve.

**When the strategy was not trading.** These books are event-driven and sparse --
tens of trades over seven years -- so the x axis is mostly empty. Markers rather
than a dense line, and a rug of signal triggers, keep the sparsity honest instead
of letting interpolation imply continuous exposure.

**What a level exit actually did.** ``exit_reason`` is the difference between a
strategy that takes its target and one that mostly times out, and those are
different businesses at the same mean. It is the colour axis throughout.

The summary panel is computed from the same frame that draws the curve, so a
number in the table and a point on the line cannot disagree.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

#: nbclient has no browser to negotiate with, so the renderer is pinned. The
#: mimetype bundle is what a saved .ipynb replays in Jupyter/VSCode; the
#: connected notebook renderer keeps plotly.js on a CDN rather than embedding
#: ~3MB of javascript into every notebook, every execution.
pio.renderers.default = "plotly_mimetype+notebook_connected"

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


def _pick(df: pd.DataFrame, *names: str) -> Optional[str]:
    """First of ``names`` that is actually a column."""
    for n in names:
        if n in df.columns:
            return n
    return None


def summary_stats(df: pd.DataFrame, *, span_years: Optional[float] = None) -> pd.DataFrame:
    """Every headline number for a book, from the book itself.

    ``span_years`` annualises. It is left to the caller because a book of 41
    event-driven trades has no natural frequency, and inventing one is how a
    Sharpe of 0.3 per trade becomes a Sharpe of 3.
    """
    p = df["pnl_bp"].to_numpy(float)
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
    rows = [
        ("trades", f"{len(p):,}"),
        ("net bp / trade", f"{p.mean():+.4f}"),
        ("gross bp / trade", f"{df['pnl_bp_gross'].mean():+.4f}"
         if "pnl_bp_gross" in df.columns else "-"),
        ("cost bp / trade", f"{df['cost_bp'].mean():.4f}" if "cost_bp" in df.columns else "-"),
        ("total net bp", f"{p.sum():+.2f}"),
        ("hit rate", f"{(p > 0).mean() * 100:.1f}%"),
        ("avg win / avg loss", f"{wins.mean():+.3f} / {losses.mean():+.3f}"
         if len(wins) and len(losses) else "-"),
        ("payoff ratio", f"{wins.mean() / abs(losses.mean()):.3f}"
         if len(wins) and len(losses) and losses.mean() != 0 else "-"),
        ("Sharpe / trade", f"{srt:.4f}"),
        ("t-statistic", f"{p.mean() / (sd / np.sqrt(len(p))):.2f}" if sd > 0 else "-"),
        ("best / worst trade", f"{p.max():+.3f} / {p.min():+.3f}"),
        ("max drawdown (bp)", f"{dd.min():.2f}"),
        ("longest win / loss run", f"{_streak(p > 0)} / {_streak(p <= 0)}"),
        ("avg hold (min)", f"{df['hold_min'].mean():.1f}" if "hold_min" in df.columns else "-"),
    ]
    if span_years and span_years > 0:
        rows.append(("trades / year", f"{len(p) / span_years:.1f}"))
        rows.append(("annualised Sharpe", f"{srt * np.sqrt(len(p) / span_years):.4f}"))
    if "exit_reason" in df.columns:
        mix = df["exit_reason"].value_counts(normalize=True)
        rows.append(("exit mix", "  ".join(f"{k} {v*100:.0f}%" for k, v in mix.items())))
    return pd.DataFrame(rows, columns=["metric", "value"])


def trade_dashboard(df: pd.DataFrame, *, title: str = "book",
                    span_years: Optional[float] = None,
                    signal_col: Optional[str] = None,
                    height: int = 1080) -> go.Figure:
    """The whole book as one interactive figure.

    ``signal_col`` is the column that triggered the trade -- ``z`` for the
    consensus books, ``move_bp`` for the move-based ones. It is auto-detected
    when not given, and drives both the rug and the signal-vs-P&L panel.
    """
    if df is None or df.empty:
        return go.Figure(layout=dict(template="plotly_dark",
                                     title=f"{title} -- no trades"))

    d = df.copy()
    tcol = _pick(d, "release_ts", "entry_ts", "opened_at")
    d[tcol] = pd.to_datetime(d[tcol], utc=True)
    d = d.sort_values(tcol).reset_index(drop=True)
    ts = d[tcol].dt.tz_convert("America/New_York")

    signal_col = signal_col or _pick(d, "z", "move_bp")
    reason = d["exit_reason"] if "exit_reason" in d.columns else pd.Series(["-"] * len(d))
    colours = [REASON_COLOUR.get(str(r), MUTED) for r in reason]

    net = d["pnl_bp"].to_numpy(float)
    eq = np.cumsum(net)
    dd = eq - np.maximum.accumulate(eq)
    gross = (np.cumsum(d["pnl_bp_gross"].to_numpy(float))
             if "pnl_bp_gross" in d.columns else None)

    # ---- the tooltip: the entire trade record, one row per line -----------
    rel = d["release"] if "release" in d.columns else (
        d["lead_title"] if "lead_title" in d.columns else pd.Series(["-"] * len(d)))
    custom = np.column_stack([
        ts.dt.strftime("%Y-%m-%d %H:%M ET"),
        rel.astype(str).str.slice(0, 42),
        d["symbol"].astype(str) if "symbol" in d.columns else np.array(["-"] * len(d)),
        np.where(d["side"] > 0, "LONG", "SHORT") if "side" in d.columns else ["-"] * len(d),
        (d[signal_col].round(3).astype(str) if signal_col else ["-"] * len(d)),
        (d["surprise"].round(3).astype(str) if "surprise" in d.columns else ["-"] * len(d)),
        reason.astype(str),
        (d["hold_min"].round(0).astype(str) if "hold_min" in d.columns else ["-"] * len(d)),
        (d["pnl_bp_gross"].round(4).astype(str) if "pnl_bp_gross" in d.columns else ["-"] * len(d)),
        np.round(net, 4).astype(str),
        np.round(eq, 3).astype(str),
    ])
    HOVER = ("<b>%{customdata[0]}</b><br>"
             "%{customdata[1]}  ·  %{customdata[2]}  ·  <b>%{customdata[3]}</b><br>"
             f"{signal_col or 'signal'}: %{{customdata[4]}}   surprise: %{{customdata[5]}}<br>"
             "exit: <b>%{customdata[6]}</b> after %{customdata[7]} min<br>"
             "gross %{customdata[8]} bp   <b>net %{customdata[9]} bp</b><br>"
             "cumulative %{customdata[10]} bp<extra></extra>")

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035,
        row_heights=[0.32, 0.19, 0.14, 0.17, 0.18],
        specs=[[{}], [{}], [{}], [{}], [{"type": "table"}]],
        subplot_titles=("cumulative net bp — every marker is one trade",
                        "per-trade net bp, coloured by how the trade ended",
                        "drawdown from peak (bp)",
                        f"signal ({signal_col}) against realised net bp",
                        "summary"))

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

    # ---- 2. per-trade bars, split so the legend explains the colours -------
    for r in pd.unique(reason.astype(str)):
        m = (reason.astype(str) == r).to_numpy()
        fig.add_trace(go.Bar(x=ts[m], y=net[m], name=str(r),
                             marker_color=REASON_COLOUR.get(str(r), MUTED),
                             customdata=custom[m], hovertemplate=HOVER),
                      row=2, col=1)
    fig.add_hline(y=0, line=dict(color=MUTED, width=1), row=2, col=1)

    # ---- 3. drawdown -------------------------------------------------------
    fig.add_trace(go.Scatter(x=ts, y=dd, name="drawdown", mode="lines",
                             line=dict(color="#ff5c5c", width=1.4),
                             fill="tozeroy", fillcolor="rgba(255,92,92,0.18)",
                             hovertemplate="drawdown %{y:.3f} bp<extra></extra>"),
                  row=3, col=1)

    # ---- 4. signal vs outcome ---------------------------------------------
    if signal_col:
        fig.add_trace(go.Scatter(x=ts, y=d[signal_col], name=signal_col, mode="markers",
                                 marker=dict(size=9, color=net, colorscale="RdYlGn",
                                             cmid=0, line=dict(width=1, color="#0e1117"),
                                             colorbar=dict(title="net bp", len=0.16,
                                                           y=0.30, thickness=10)),
                                 customdata=custom, hovertemplate=HOVER),
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
                         f"net {net.mean():+.4f} bp/trade   ·   "
                         f"hit {(net > 0).mean()*100:.1f}%   ·   "
                         f"total {net.sum():+.2f} bp"), x=0.01, font=dict(size=15)),
        paper_bgcolor=BG, plot_bgcolor=BG, font=dict(color=FG, size=11),
        hovermode="closest", hoverdistance=30,
        hoverlabel=dict(bgcolor=PANEL, bordercolor=GRID, font=dict(color=FG, size=11)),
        legend=dict(orientation="h", y=1.045, x=0.28, bgcolor="rgba(0,0,0,0)"),
        bargap=0.55, margin=dict(l=60, r=30, t=90, b=40),
    )
    fig.update_yaxes(title_text="cum bp", row=1, col=1)
    fig.update_yaxes(title_text="bp", row=2, col=1)
    fig.update_yaxes(title_text="bp", row=3, col=1)
    if signal_col:
        fig.update_yaxes(title_text=signal_col, row=4, col=1)
    for a in fig.layout.annotations[:4]:
        a.update(x=0.005, xanchor="left", font=dict(size=11, color=MUTED))
    return fig


def compare_curves(books: dict, *, title: str = "comparison",
                   height: int = 520) -> go.Figure:
    """Several books on one pair of axes -- cumulative, and their drawdowns.

    Written for the direction fork (fade against momentum against the flip) and
    for real against placebo, where the interesting quantity is the gap between
    two curves rather than the level of either.
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                        row_heights=[0.66, 0.34],
                        subplot_titles=("cumulative net bp", "drawdown (bp)"))
    palette = ["#4dabf7", "#3ddc84", "#ff9f43", "#ff5c5c", "#9b8cff", "#f6c744"]
    for i, (name, d) in enumerate(books.items()):
        if d is None or d.empty:
            continue
        tcol = _pick(d, "release_ts", "entry_ts", "opened_at")
        dd_ = d.copy()
        dd_[tcol] = pd.to_datetime(dd_[tcol], utc=True)
        dd_ = dd_.sort_values(tcol)
        t = dd_[tcol].dt.tz_convert("America/New_York")
        eq = dd_["pnl_bp"].cumsum().to_numpy()
        c = palette[i % len(palette)]
        fig.add_trace(go.Scatter(x=t, y=eq, name=str(name), mode="lines+markers",
                                 line=dict(color=c, width=2), marker=dict(size=5),
                                 hovertemplate=(f"<b>{name}</b><br>%{{x|%Y-%m-%d}}<br>"
                                                "cum %{y:.3f} bp<extra></extra>")),
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
