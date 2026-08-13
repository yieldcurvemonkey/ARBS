"""RVUtils.BookViz — the column mapping, the statistics, and the figures.

The property worth pinning hardest is that a **marked equity series is drawn as given and never
re-derived from the trade ledger**. For an unfinanced book the two agree and the distinction looks
academic; for a financed one they differ by the carry, and a dashboard that quietly re-summed the
trades would contradict the engine that produced the number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.BookViz import (BookSpec, book_dashboard, book_stats, compare_books, curve_of,
                             equity_stats, resolve_spec)


@pytest.fixture
def bp_book() -> pd.DataFrame:
    """An econ-release-fade shaped ledger: bp, release_ts, exit_reason."""
    n = 12
    idx = pd.date_range("2024-01-03", periods=n, freq="21D", tz="UTC")
    rng = np.random.default_rng(7)
    return pd.DataFrame({
        "release_ts": idx,
        "pnl_bp": rng.normal(0.2, 1.0, n).round(4),
        "pnl_bp_gross": rng.normal(0.5, 1.0, n).round(4),
        "cost_bp": np.full(n, 0.3),
        "exit_reason": ["target", "stop", "time_stop"] * 4,
        "z": rng.normal(0, 1.5, n).round(3),
        "hold_min": rng.integers(5, 120, n),
        "release": ["CPI"] * n,
    })


@pytest.fixture
def usd_book() -> pd.DataFrame:
    """A QueryDrivenBacktest closed log: dollars, closed_at, no exit_reason."""
    n = 8
    idx = pd.date_range("2025-01-06", periods=n, freq="14D", tz="UTC")
    rng = np.random.default_rng(3)
    return pd.DataFrame({
        "closed_at": idx,
        "realized_pnl": rng.normal(50_000, 200_000, n).round(2),
        "gross_realized_pnl": rng.normal(60_000, 200_000, n).round(2),
        "fee_allocated": np.full(n, 40_000.0),
        "holding_period_days": rng.integers(2, 30, n).astype(float),
        "fly_id": [f"fly{i}" for i in range(n)],
    })


# ------------------------------------------------------------------ spec
def test_spec_infers_the_bp_vocabulary(bp_book):
    s = resolve_spec(bp_book)
    assert (s.pnl, s.time, s.category, s.signal) == ("pnl_bp", "release_ts", "exit_reason", "z")
    assert s.gross == "pnl_bp_gross" and s.cost == "cost_bp"


def test_spec_infers_the_qdb_vocabulary(usd_book):
    s = resolve_spec(usd_book)
    assert (s.pnl, s.time) == ("realized_pnl", "closed_at")
    assert s.category is None          # a QDB closed log has no exit_reason
    assert s.hold == "holding_period_days"
    assert s.label == "fly_id"


def test_an_explicit_spec_field_wins_over_inference(bp_book):
    s = resolve_spec(bp_book, BookSpec(pnl="pnl_bp_gross"))
    assert s.pnl == "pnl_bp_gross"
    assert s.time == "release_ts"      # the rest still inferred


def test_a_frame_with_no_pnl_column_raises_rather_than_guessing():
    df = pd.DataFrame({"when": pd.date_range("2025-01-01", periods=3, tz="UTC"), "x": [1, 2, 3]})
    with pytest.raises(ValueError, match="no P&L column"):
        resolve_spec(df)


def test_a_frame_with_no_time_column_raises(bp_book):
    with pytest.raises(ValueError, match="no time column"):
        resolve_spec(bp_book.drop(columns=["release_ts"]))


def test_units_drive_formatting_not_magnitude():
    """The properties, not a rounding artifact: bp is signed, currency is grouped and unsigned."""
    bp, usd = BookSpec(unit="bp", precision=4), BookSpec(unit="USD", precision=0)
    assert not bp.is_currency and usd.is_currency

    assert bp.fmt(1.23456) == "+1.2346"      # signed, 4dp
    assert bp.fmt(-1.0).startswith("-")

    got = usd.fmt(1_234_567.0)
    assert "," in got, got                   # grouped
    assert not got.startswith("+"), got      # a dollar figure is not signed like a spread
    assert got.startswith("1,234,567"), got


def test_a_currency_spec_never_formats_more_than_two_decimals():
    """`precision` is a bp concept; four decimals of a dollar is noise, so currency clamps to 2."""
    assert BookSpec(unit="USD", precision=6).fmt(12.3456789) == "12.35"


# ----------------------------------------------------------------- stats
def test_book_stats_reports_trade_count_and_hit_rate(bp_book):
    s = book_stats(bp_book).set_index("metric")["value"]
    assert s["trades"] == "12"
    p = bp_book["pnl_bp"].to_numpy()
    assert s["hit rate"] == f"{(p > 0).mean() * 100:.1f}%"


def test_book_stats_does_not_annualise_without_span_years(bp_book):
    s = book_stats(bp_book).set_index("metric")["value"]
    assert "annualised Sharpe (per-trade basis)" not in s.index
    s2 = book_stats(bp_book, span_years=2.0).set_index("metric")["value"]
    assert "annualised Sharpe (per-trade basis)" in s2.index


def test_book_stats_surfaces_the_gap_between_equity_and_the_trade_sum(usd_book):
    """The row that stops a financed book being read as its price leg.

    Trades sum to X; the engine's marked curve ends somewhere else. The difference is carry, and
    it must be stated rather than left for the reader to notice.
    """
    eq = pd.Series(np.linspace(0, 431_444, 60),
                   index=pd.date_range("2025-01-01", periods=60, freq="B", tz="UTC"))
    s = book_stats(usd_book, spec=BookSpec(unit="USD", precision=0), equity=eq).set_index("metric")["value"]
    assert "equity - Σ trades" in s.index
    gap = float(s["equity - Σ trades"].replace(",", ""))
    assert gap == pytest.approx(431_444 - usd_book["realized_pnl"].sum(), rel=1e-6)


def test_book_stats_on_an_empty_frame_is_empty_not_an_exception():
    assert book_stats(pd.DataFrame()).empty


def test_equity_stats_needs_two_points():
    one = pd.Series([1.0], index=pd.to_datetime(["2025-01-01"], utc=True))
    assert equity_stats(one).empty


# --------------------------------------------------------------- curves
def test_curve_of_cumulates_a_ledger_but_not_a_series(usd_book):
    """A Series is already cumulative. Re-summing it plots a quantity with no meaning."""
    led = curve_of(usd_book)
    assert led.iloc[-1] == pytest.approx(usd_book["realized_pnl"].sum())

    eq = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2025-01-01", periods=3, tz="UTC"))
    got = curve_of(eq)
    assert got.tolist() == [1.0, 2.0, 3.0]          # NOT [1, 3, 6]


# --------------------------------------------------------------- figures
def test_dashboard_builds_for_a_bp_ledger(bp_book):
    fig = book_dashboard(bp_book, title="cpi", span_years=1.0)
    assert len(fig.data) > 0
    assert "cpi" in fig.layout.title.text


def test_dashboard_builds_for_a_usd_ledger_with_no_category(usd_book):
    fig = book_dashboard(usd_book, title="gss", spec=BookSpec(unit="USD", precision=0))
    assert len(fig.data) > 0


def test_dashboard_draws_the_marked_equity_and_does_not_replace_it_with_the_trade_sum(usd_book):
    """The property the module exists for."""
    eq = pd.Series(np.linspace(0.0, 431_444.0, 40),
                   index=pd.date_range("2025-01-06", periods=40, freq="5D", tz="UTC"))
    fig = book_dashboard(usd_book, spec=BookSpec(unit="USD", precision=0), equity=eq)

    marked = [t for t in fig.data if getattr(t, "name", None) == "marked equity"]
    assert len(marked) == 1, "the engine's own curve must be drawn"
    assert marked[0].y[-1] == pytest.approx(431_444.0)
    assert marked[0].y[-1] != pytest.approx(usd_book["realized_pnl"].sum())

    # and the trade sum is still shown, so the gap is visible rather than hidden
    assert any(getattr(t, "name", None) == "Σ trades" for t in fig.data)


def test_dashboard_adds_a_component_panel_when_asked(usd_book):
    idx = pd.date_range("2025-01-06", periods=20, freq="7D", tz="UTC")
    comps = {"price": pd.Series(np.linspace(0, 7_917_373, 20), index=idx),
             "financing": pd.Series(np.linspace(0, -7_500_000, 20), index=idx)}
    fig = book_dashboard(usd_book, spec=BookSpec(unit="USD", precision=0), components=comps)
    names = {getattr(t, "name", None) for t in fig.data}
    assert {"price", "financing"} <= names


def test_dashboard_with_only_an_equity_series_and_no_trades():
    eq = pd.Series(np.linspace(0, 5000, 50),
                   index=pd.date_range("2025-01-01", periods=50, freq="B", tz="UTC"))
    fig = book_dashboard(None, equity=eq, spec=BookSpec(unit="USD"), title="equity only")
    assert any(getattr(t, "name", None) == "marked equity" for t in fig.data)


def test_dashboard_on_nothing_returns_a_figure_not_an_exception():
    fig = book_dashboard(None)
    assert fig is not None and "nothing to plot" in fig.layout.title.text


def test_compare_books_accepts_ledgers_and_series_together(bp_book, usd_book):
    eq = pd.Series(np.linspace(0, 1000, 30),
                   index=pd.date_range("2025-01-01", periods=30, freq="B", tz="UTC"))
    fig = compare_books({"ledger": usd_book, "marked": eq}, unit="USD")
    names = {getattr(t, "name", None) for t in fig.data}
    assert {"ledger", "marked"} <= names


def test_compare_books_skips_empty_and_unmappable_books(usd_book):
    fig = compare_books({"good": usd_book, "empty": pd.DataFrame(),
                         "none": None, "junk": pd.DataFrame({"a": [1, 2]})}, unit="USD")
    names = {getattr(t, "name", None) for t in fig.data}
    assert "good" in names and "junk" not in names
