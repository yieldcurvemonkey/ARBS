"""BT.trade_dashboard — the normaliser, and the promise that nothing moved.

The load-bearing test here is `test_econ_frame_is_byte_identical`: the module
this generalises is loaded from git as it was BEFORE the change and run side by
side on the same frame, and the two figures must agree as JSON. A dashboard that
"still works" is not the claim; the claim is that the econ-release notebooks
draw exactly what they drew.
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from BT.trade_dashboard import (
    REASON_COLOUR,
    compare_curves,
    summary_stats,
    to_book,
    trade_dashboard,
)

REPO = Path(__file__).resolve().parents[1]
ECON = REPO / "notebooks" / "backtests" / "econ_release_fade" / "econ_fade_plotly.py"


# ===========================================================================
# fixtures
# ===========================================================================
@pytest.fixture
def econ_frame() -> pd.DataFrame:
    """The econ-release fade's own trade-log schema, with every column it uses."""
    n = 12
    base = pd.Timestamp("2024-01-03 08:30", tz="America/New_York")
    rng = np.random.default_rng(7)
    reasons = ["target", "stop", "time_stop", "eod"]
    return pd.DataFrame({
        "release_ts": [base + pd.Timedelta(days=31 * i) for i in range(n)],
        "release": [f"CPI m/m {i}" for i in range(n)],
        "symbol": ["SR3Z24"] * n,
        # deliberately never 0: the pre-change module had no FLAT branch, so a
        # zero side is the one input on which the two cannot agree.
        "side": rng.choice([-1.0, 1.0], n),
        "z": rng.normal(0, 1.5, n).round(4),
        "surprise": rng.normal(0, 0.4, n).round(4),
        "exit_reason": [reasons[i % len(reasons)] for i in range(n)],
        "hold_min": rng.integers(5, 240, n).astype(float),
        "pnl_bp_gross": rng.normal(0.2, 1.1, n).round(4),
        "cost_bp": np.full(n, 0.25),
        "pnl_bp": rng.normal(0.0, 1.1, n).round(4),
    })


@pytest.fixture
def hawk_frame() -> pd.DataFrame:
    """The FOMC speaker book: no exit_reason, no side, a STRING direction."""
    n = 9
    base = pd.Timestamp("2024-02-05 09:00", tz="America/New_York")
    rng = np.random.default_rng(11)
    return pd.DataFrame({
        "opened_at": [base + pd.Timedelta(days=9 * i) for i in range(n)],
        "closed_at": [base + pd.Timedelta(days=9 * i, minutes=240) for i in range(n)],
        "speaker": ["Goolsbee", "Bostic", "Waller"] * 3,
        "role": ["President", "President", "Governor"] * 3,
        "structure": ["OUT_3"] * n,
        "symbol": ["SR3Z24"] * n,
        "bucket": rng.choice([-2, -1, 1, 2], n),
        "flip": rng.choice([-1.0, 1.0], n),
        "direction": ["hawk (short fut)", "dove (long fut)", "hawk, FADED (long fut)"] * 3,
        "d_rate_bp": rng.normal(0, 2.0, n).round(3),
        "pnl_bp_gross": rng.normal(0.5, 2.0, n).round(3),
        "pnl_bp": rng.normal(0.5, 2.0, n).round(3),
    })


def _load_pre_change_module():
    """econ_fade_plotly.py as it was before this change, straight out of git."""
    # bytes, decoded explicitly. text=True decodes with the LOCALE encoding,
    # which on Windows is cp1252 -- the module is full of "·" and "—", and a
    # mojibake control would fail the comparison on the harness's own bug.
    src = subprocess.run(
        ["git", "-C", str(REPO), "show",
         "main:notebooks/backtests/econ_release_fade/econ_fade_plotly.py"],
        capture_output=True, check=True).stdout.decode("utf-8")
    if "BT.trade_dashboard" in src:
        pytest.skip("main already carries the shim — no pre-change control to compare against")
    path = REPO / "tests" / "_econ_fade_plotly_pre.py"
    path.write_text(src, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location("econ_fade_plotly_pre", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        path.unlink(missing_ok=True)


def _comparable(fig: go.Figure) -> str:
    """Figure JSON as a canonical string.

    Serialised rather than compared as dicts: the trace payloads are numpy
    arrays, and `dict == dict` on those raises rather than answering. The uid
    and the (identical, enormous) template are dropped.
    """
    import json

    from plotly.utils import PlotlyJSONEncoder

    d = copy.deepcopy(fig.to_plotly_json())
    for tr in d.get("data", []):
        tr.pop("uid", None)
    d.get("layout", {}).pop("template", None)
    return json.dumps(d, sort_keys=True, cls=PlotlyJSONEncoder)


# ===========================================================================
# 1. the promise: the econ figure did not move
# ===========================================================================
def test_econ_frame_is_byte_identical(econ_frame):
    pre = _load_pre_change_module()
    a = pre.trade_dashboard(econ_frame, title="t", span_years=2.0, signal_col="z")
    b = trade_dashboard(econ_frame, title="t", span_years=2.0, signal_col="z")
    assert _comparable(a) == _comparable(b)


def test_econ_summary_is_byte_identical(econ_frame):
    pre = _load_pre_change_module()
    pd.testing.assert_frame_equal(
        pre.summary_stats(econ_frame, span_years=2.0),
        summary_stats(econ_frame, span_years=2.0))


def test_econ_compare_curves_is_byte_identical(econ_frame):
    pre = _load_pre_change_module()
    books = {"a": econ_frame, "b": econ_frame.assign(pnl_bp=-econ_frame.pnl_bp)}
    assert _comparable(pre.compare_curves(books, title="c")) == \
        _comparable(compare_curves(books, title="c"))


def test_shim_reexports_the_same_objects():
    spec = importlib.util.spec_from_file_location("econ_fade_plotly_shim", ECON)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    assert mod.trade_dashboard is trade_dashboard
    assert mod.compare_curves is compare_curves
    assert mod.REASON_COLOUR is REASON_COLOUR


# ===========================================================================
# 2. the normaliser
# ===========================================================================
def test_book_detects_the_econ_schema(econ_frame):
    b = to_book(econ_frame)
    assert b.attrs["unit"] == "bp"
    assert b.attrs["signal_name"] == "z"
    assert b.attrs["colour_name"] == "exit_reason"
    assert b.attrs["hold_unit"] == "min"
    assert b.attrs["time_name"] == "release_ts"
    assert b.attrs["has_gross"] and b.attrs["has_cost"]


def test_book_is_idempotent(econ_frame):
    b = to_book(econ_frame)
    assert to_book(b) is b


def test_book_does_not_mutate_its_input(econ_frame):
    before = econ_frame.copy(deep=True)
    to_book(econ_frame)
    pd.testing.assert_frame_equal(econ_frame, before)


def test_hawk_schema_needs_no_exit_reason_or_side(hawk_frame):
    b = to_book(hawk_frame, signal_col="bucket", colour_col="direction")
    assert b.attrs["signal_name"] == "bucket"
    assert b.attrs["colour_name"] == "direction"
    assert b.attrs["unit"] == "bp"
    # hold is derived from the two timestamps when the book does not carry one
    assert b.attrs["hold_unit"] == "min"
    assert np.allclose(b["_hold"], 240.0)
    fig = trade_dashboard(hawk_frame, title="hawk", signal_col="bucket",
                          colour_col="direction")
    assert isinstance(fig, go.Figure) and len(fig.data) > 3


def test_string_direction_is_not_read_as_a_number(hawk_frame):
    b = to_book(hawk_frame.drop(columns=["direction"]).assign(
        direction_label=["Long", "Short", "Flat"] * 3))
    assert set(b["_side"]) == {"Long", "Short", "Flat"}


def test_missing_signal_falls_back_to_a_group_panel(hawk_frame):
    d = hawk_frame.drop(columns=["bucket"])
    fig = trade_dashboard(d, title="no signal", signal_col=None, colour_col="direction")
    kinds = [type(t).__name__ for t in fig.data]
    assert "Bar" in kinds and "Table" in kinds


def test_an_unknown_column_name_raises_rather_than_drawing_nothing(econ_frame):
    with pytest.raises(KeyError):
        trade_dashboard(econ_frame, signal_col="not_a_column")
    with pytest.raises(KeyError):
        trade_dashboard(econ_frame, colour_col="not_a_column")


def test_a_frame_with_no_pnl_is_a_clear_error():
    with pytest.raises(KeyError):
        to_book(pd.DataFrame({"opened_at": [pd.Timestamp("2024-01-01")]}))


def test_empty_book_returns_a_figure_not_an_exception(econ_frame):
    fig = trade_dashboard(econ_frame.iloc[:0], title="none")
    assert isinstance(fig, go.Figure)


def test_unit_follows_the_pnl_column(hawk_frame):
    money = hawk_frame.rename(columns={"pnl_bp": "realized_pnl"}).drop(
        columns=["pnl_bp_gross"])
    assert to_book(money).attrs["unit"] == ""
    assert to_book(money, unit="$").attrs["unit"] == "$"
    s = summary_stats(money)
    assert "net / trade" in set(s["metric"])


def test_summary_matches_the_curve(econ_frame):
    s = summary_stats(econ_frame).set_index("metric")["value"]
    assert s["trades"] == f"{len(econ_frame):,}"
    assert s["total net bp"] == f"{econ_frame.pnl_bp.sum():+.2f}"
    assert s["net bp / trade"] == f"{econ_frame.pnl_bp.mean():+.4f}"


# ===========================================================================
# 3. the QueryDrivenBacktest pattern, on a real engine run
# ===========================================================================
def _sample_backtest(simple_time_grid, mock_mdp):
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    dates = list(simple_time_grid)
    q1 = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                     tenor="5Y", curve="USD-SOFR-1D",
                     structure_kwargs={"bpv": 1_000_000}, tags=("macro-rv",))
    q2 = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                     tenor="10Y", curve="USD-SOFR-1D",
                     structure_kwargs={"bpv": -500_000}, tags=("carry",))
    triggers = [
        DateTrigger(DateTriggerRequirements(dates=[dates[0].date()]),
                    actions=[AddQueryAction(query=q1)]),
        DateTrigger(DateTriggerRequirements(dates=[dates[1].date()]),
                    actions=[AddQueryAction(query=q2)]),
        DateTrigger(DateTriggerRequirements(dates=[dates[3].date()]),
                    actions=[UnwindPositionsAction(match_tag="macro-rv")]),
    ]
    bt = QueryDrivenBacktest(time_grid=simple_time_grid,
                             strategy=QueryStrategy(name="dashboard test",
                                                    triggers=triggers),
                             mdp=mock_mdp, show_progress=False)
    bt.run()
    return bt


def test_backtest_object_drives_the_dashboard(simple_time_grid, mock_mdp):
    bt = _sample_backtest(simple_time_grid, mock_mdp)
    b = to_book(bt)
    assert b.attrs["source"] == "QueryDrivenBacktest"
    assert b.attrs["unit"] == ""                      # currency, not basis points
    assert b.attrs["colour_name"] == "exit_reason"
    assert b.attrs["hold_unit"] == "d"
    assert b.attrs["name"] == "dashboard test"
    assert len(b) == len(bt.portfolio.closed_positions_log)
    # the closed log is the price leg; the engine's own total rides in attrs
    assert isinstance(b.attrs["mtm"], pd.Series) and len(b.attrs["mtm"])

    fig = trade_dashboard(bt, title="qdb")
    names = [t.name for t in fig.data]
    assert "total P&L (incl. carry & open)" in names, names
    assert "net" in names


def test_tearsheet_and_analytics_are_accepted(simple_time_grid, mock_mdp):
    from BT.query_tearsheet import QueryBacktestTearSheet

    bt = _sample_backtest(simple_time_grid, mock_mdp)
    sheet = QueryBacktestTearSheet.from_backtest(bt)
    for src in (sheet, sheet.analytics):
        b = to_book(src)
        assert b.attrs["source"] == "QueryDrivenBacktest"
        assert len(b) == len(bt.portfolio.closed_positions_log)


def test_closed_trade_frame_is_public_and_matches(simple_time_grid, mock_mdp):
    from BT.query_tearsheet import QueryBacktestTearSheet, closed_trade_frame

    bt = _sample_backtest(simple_time_grid, mock_mdp)
    direct = closed_trade_frame(bt)
    via = QueryBacktestTearSheet.from_backtest(bt).analytics.closed_trades
    assert list(direct.columns) == list(via.columns)
    assert len(direct) == len(via)


def test_tearsheet_exposes_the_dashboard_as_a_backend(simple_time_grid, mock_mdp):
    from BT.query_tearsheet import QueryBacktestTearSheet

    bt = _sample_backtest(simple_time_grid, mock_mdp)
    sheet = QueryBacktestTearSheet.from_backtest(bt)
    fig = sheet.plot(backend="dashboard")
    assert isinstance(fig, go.Figure)
    # the title defaults to the strategy's own name rather than "book"
    assert "dashboard test" in fig.layout.title.text
    with pytest.raises(ValueError, match="backend must be one of"):
        sheet.plot(backend="crayon")


def test_compare_curves_labels_follow_the_unit(hawk_frame):
    money = hawk_frame.rename(columns={"pnl_bp": "realized_pnl"}).drop(
        columns=["pnl_bp_gross"])
    bp_titles = [a.text for a in compare_curves({"a": hawk_frame}).layout.annotations]
    ccy_titles = [a.text for a in compare_curves({"a": money}).layout.annotations]
    assert "cumulative net bp" in bp_titles and "drawdown (bp)" in bp_titles
    assert "cumulative net" in ccy_titles and "drawdown" in ccy_titles
    assert "cumulative net bp" not in ccy_titles


def test_a_non_backtest_object_says_so():
    with pytest.raises(TypeError, match="cannot read a book"):
        to_book(object())
