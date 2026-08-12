"""Interactive book visualisation — one dashboard shape that works for any ARBS backtest.

Generalised from ``notebooks/backtests/econ_release_fade/econ_fade_plotly.py``, which built a
five-panel interactive trade dashboard for one study and hard-wired three things to it: basis
points, ``exit_reason`` as the colour axis, and a cumulative sum of trades as the equity curve.

All three are now parameters. The third is the one that mattered: for a **financed** book the
cumulative sum of trade P&L is *not* the equity curve, and the difference is the carry. Passing
``equity=`` draws the engine's own marked series and places the trades on it, with the trade sum
shown dashed beside it so the gap is visible rather than assumed away.

Typical use::

    from RVUtils.BookViz import BookSpec, book_dashboard, compare_books

    # an econ-release-fade book: bp, exit_reason, cumsum of trades
    book_dashboard(trades, title="CPI fade", span_years=7.0)

    # a QueryDrivenBacktest book: dollars, engine-marked equity, component decomposition
    book_dashboard(
        res.closed,
        title="GSS butterfly",
        spec=BookSpec(unit="USD", precision=0, pnl="realized_pnl", time="closed_at"),
        equity=res.equity,
        components={"price": price_series, "coupons": coupon_series},
    )

    # a config sweep
    compare_books({name: r.equity for name, r in results.items()}, unit="USD")
"""

from RVUtils.BookViz.compare import compare_books, curve_of
from RVUtils.BookViz.dashboard import book_dashboard
from RVUtils.BookViz.spec import BookSpec, pick_column, resolve_spec
from RVUtils.BookViz.stats import book_stats, equity_stats, longest_streak
from RVUtils.BookViz.theme import (ACCENT, BG, CATEGORY_COLOURS, FG, GRID, MUTED, NEG, PANEL,
                                   POS, SERIES_PALETTE, WARN, category_colour,
                                   use_notebook_renderer)

__all__ = [
    "BookSpec", "resolve_spec", "pick_column",
    "book_stats", "equity_stats", "longest_streak",
    "book_dashboard", "compare_books", "curve_of",
    "use_notebook_renderer", "category_colour",
    "BG", "PANEL", "GRID", "FG", "MUTED", "ACCENT", "POS", "NEG", "WARN",
    "SERIES_PALETTE", "CATEGORY_COLOURS",
]
