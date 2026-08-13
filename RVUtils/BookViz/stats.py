"""Headline numbers for a book, computed from the same frame that draws its curve.

A table and a chart that disagree is a bug the reader has to find; computing both from one frame
makes that impossible by construction.

Two deliberate refusals:

**Annualisation is the caller's.** A book of 34 event-driven trades has no natural frequency, and
inventing one is exactly how a Sharpe of 0.2 per trade becomes a Sharpe of 3. ``span_years`` is
required for any annualised row, and nothing is annualised without it.

**Per-trade statistics are labelled per-trade.** ``t_stat`` on a trade ledger tests whether the
mean trade differs from zero. It is not a statement about the strategy's risk-adjusted return and
is not comparable with a daily Sharpe, so the two never share a name here.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from RVUtils.BookViz.spec import BookSpec, resolve_spec

__all__ = ["book_stats", "equity_stats", "longest_streak"]


def longest_streak(mask) -> int:
    best = cur = 0
    for v in np.asarray(mask, dtype=bool):
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def book_stats(
    df: pd.DataFrame,
    *,
    spec: Optional[BookSpec] = None,
    span_years: Optional[float] = None,
    equity: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Every headline number for a trade ledger, as a two-column metric/value frame.

    ``equity`` is the engine's own marked series when there is one. Supplying it adds the rows
    that a trade ledger genuinely cannot answer — the daily Sharpe and the drawdown of the *book*
    rather than of the cumulative trade sum — and, more importantly, adds the reconciliation row.
    For a financed book those two are not the same number, and a summary that reports only one of
    them invites the reader to assume they are.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["metric", "value"])
    s = resolve_spec(df, spec)
    u = s.axis_unit

    p = pd.to_numeric(df[s.pnl], errors="coerce").to_numpy(float)
    p = p[np.isfinite(p)]
    if not len(p):
        return pd.DataFrame(columns=["metric", "value"])

    wins, losses = p[p > 0], p[p <= 0]
    sd = p.std(ddof=1) if len(p) > 1 else 0.0
    cum = np.cumsum(p)
    dd = cum - np.maximum.accumulate(cum)
    sharpe_per_trade = float(p.mean() / sd) if sd > 0 else 0.0

    rows = [
        ("trades", f"{len(p):,}"),
        (f"net {u} / trade", s.fmt(p.mean())),
    ]
    if s.gross:
        rows.append((f"gross {u} / trade", s.fmt(pd.to_numeric(df[s.gross], errors="coerce").mean())))
    if s.cost:
        rows.append((f"cost {u} / trade", s.fmt(pd.to_numeric(df[s.cost], errors="coerce").mean())))
    rows += [
        (f"total net {u} (trades)", s.fmt(p.sum())),
        ("hit rate", f"{(p > 0).mean() * 100:.1f}%"),
    ]
    if len(wins) and len(losses):
        rows.append(("avg win / avg loss", f"{s.fmt(wins.mean())} / {s.fmt(losses.mean())}"))
        if losses.mean() != 0:
            rows.append(("payoff ratio", f"{wins.mean() / abs(losses.mean()):.3f}"))
    rows += [
        ("Sharpe / trade", f"{sharpe_per_trade:.4f}"),
        ("t-stat (per trade)", f"{p.mean() / (sd / np.sqrt(len(p))):.2f}" if sd > 0 else "-"),
        ("best / worst trade", f"{s.fmt(p.max())} / {s.fmt(p.min())}"),
        (f"max drawdown ({u}, trades)", s.fmt(dd.min())),
        ("longest win / loss run", f"{longest_streak(p > 0)} / {longest_streak(p <= 0)}"),
    ]
    if s.hold:
        h = pd.to_numeric(df[s.hold], errors="coerce")
        rows.append((f"median hold ({s.hold})", f"{h.median():.1f}"))
    if span_years and span_years > 0:
        rows.append(("trades / year", f"{len(p) / span_years:.1f}"))
        rows.append(("annualised Sharpe (per-trade basis)",
                     f"{sharpe_per_trade * np.sqrt(len(p) / span_years):.4f}"))
    if s.category and s.category in df.columns:
        mix = df[s.category].astype(str).value_counts(normalize=True)
        rows.append(("exit mix", "  ".join(f"{k} {v*100:.0f}%" for k, v in mix.items())))

    if equity is not None and len(equity.dropna()) > 1:
        rows += _equity_rows(equity, s, trade_sum=float(p.sum()))

    return pd.DataFrame(rows, columns=["metric", "value"])


def _equity_rows(equity: pd.Series, s: BookSpec, *, trade_sum: float) -> list:
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    daily = eq.diff().dropna()
    out = [(f"end equity ({s.axis_unit})", s.fmt(float(eq.iloc[-1])))]
    if len(daily) > 5 and daily.std(ddof=1) > 0:
        out.append(("daily Sharpe (ann.)",
                    f"{daily.mean() / daily.std(ddof=1) * np.sqrt(252):.3f}"))
    ddc = eq - eq.cummax()
    out.append((f"max drawdown ({s.axis_unit}, marked)", s.fmt(float(ddc.min()))))
    # The row that stops a reader assuming the two agree. For an unfinanced book it is ~0; for a
    # financed one it is the carry, and it being large is information rather than an error.
    out.append(("equity - Σ trades", s.fmt(float(eq.iloc[-1]) - trade_sum)))
    return out


def equity_stats(equity: pd.Series, *, unit: str = "bp", periods_per_year: int = 252) -> pd.DataFrame:
    """Headline numbers for a marked equity series alone, with no trade ledger."""
    eq = pd.to_numeric(equity, errors="coerce").dropna()
    if len(eq) < 2:
        return pd.DataFrame(columns=["metric", "value"])
    d = eq.diff().dropna()
    dd = eq - eq.cummax()
    sharpe = float(d.mean() / d.std(ddof=1) * np.sqrt(periods_per_year)) if d.std(ddof=1) > 0 else 0.0
    rows = [
        ("marked periods", f"{len(eq):,}"),
        (f"end equity ({unit})", f"{eq.iloc[-1]:,.2f}"),
        (f"mean per period ({unit})", f"{d.mean():,.4f}"),
        ("Sharpe (ann.)", f"{sharpe:.3f}"),
        (f"max drawdown ({unit})", f"{dd.min():,.2f}"),
        ("worst period", f"{d.min():,.2f}"),
        ("best period", f"{d.max():,.2f}"),
        ("periods positive", f"{(d > 0).mean() * 100:.1f}%"),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])
