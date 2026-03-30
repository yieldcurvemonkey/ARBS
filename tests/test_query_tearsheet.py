import datetime as dt
from dataclasses import replace
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import plotly.graph_objects as go
import pytest

from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.query_tearsheet import QueryBacktestTearSheet, create_query_backtest_tearsheet
from BT.triggers import DateTrigger, DateTriggerRequirements
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


def _build_sample_backtest(simple_time_grid, mock_mdp):
    dates = list(simple_time_grid)

    query_one = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.NPV,
        tenor="5Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"bpv": 1_000_000},
        tags=("macro-rv", "front-book"),
    )
    query_two = IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT,
        value=IRSwapValue.NPV,
        tenor="10Y",
        curve="USD-SOFR-1D",
        structure_kwargs={"bpv": -500_000},
        tags=("carry", "core-book"),
    )

    triggers = [
        DateTrigger(DateTriggerRequirements(dates=[dates[0].date()]), actions=[AddQueryAction(query=query_one)]),
        DateTrigger(DateTriggerRequirements(dates=[dates[1].date()]), actions=[AddQueryAction(query=query_two)]),
        DateTrigger(DateTriggerRequirements(dates=[dates[3].date()]), actions=[UnwindPositionsAction(match_tag="macro-rv")]),
    ]

    backtest = QueryDrivenBacktest(
        time_grid=simple_time_grid,
        strategy=QueryStrategy(name="Macro TearSheet Test", triggers=triggers),
        mdp=mock_mdp,
        show_progress=False,
    )
    backtest.run()
    return backtest


def _seed_trade_analytics_history(backtest, simple_time_grid):
    dates = list(simple_time_grid)
    base_closed = backtest.portfolio.closed_positions_log[0]
    open_position = next(iter(backtest.portfolio.iter_positions()))

    long_trade_one = replace(
        base_closed["position"],
        meta={**dict(base_closed["position"].meta or {}), "signal_direction": 1, "tags": ["macro-rv", "front-book"]},
    )
    long_trade_two = replace(
        open_position,
        opened=dates[1],
        meta={**dict(open_position.meta or {}), "signal_direction": 1, "tags": ["carry", "core-book"]},
    )
    short_trade = replace(
        open_position,
        opened=dates[0],
        meta={**dict(open_position.meta or {}), "signal_direction": -1, "tags": ["hedge", "defensive"]},
    )

    backtest.portfolio.closed_positions_log = [
        {
            "opened_at": dates[0],
            "closed_at": dates[2],
            "holding_period_steps": 2,
            "holding_period_days": 2.0,
            "realized_pnl": 120.0,
            "gross_realized_pnl": 125.0,
            "fee_allocated": 5.0,
            "position": long_trade_one,
            "source_query": long_trade_one.source_query,
            "position_meta": dict(long_trade_one.meta or {}),
            "exit_meta": {"action": "unwind", "reason": "target"},
            "handler_name": "generic",
        },
        {
            "opened_at": dates[1],
            "closed_at": dates[3],
            "holding_period_steps": 2,
            "holding_period_days": 2.0,
            "realized_pnl": 80.0,
            "gross_realized_pnl": 82.0,
            "fee_allocated": 2.0,
            "position": long_trade_two,
            "source_query": long_trade_two.source_query,
            "position_meta": dict(long_trade_two.meta or {}),
            "exit_meta": {"action": "unwind", "reason": "target"},
            "handler_name": "generic",
        },
        {
            "opened_at": dates[0],
            "closed_at": dates[4],
            "holding_period_steps": 4,
            "holding_period_days": 4.0,
            "realized_pnl": -120.0,
            "gross_realized_pnl": -118.0,
            "fee_allocated": 2.0,
            "position": short_trade,
            "source_query": short_trade.source_query,
            "position_meta": dict(short_trade.meta or {}),
            "exit_meta": {"action": "unwind", "reason": "stop"},
            "handler_name": "generic",
        },
    ]
    backtest.realized_pnl = 80.0
    backtest.realized_pnl_history = {
        dates[0]: 0.0,
        dates[2]: 120.0,
        dates[3]: 200.0,
        dates[4]: 80.0,
    }
    backtest.mtm_history = {
        dates[0]: 0.0,
        dates[1]: 40.0,
        dates[2]: 120.0,
        dates[3]: 210.0,
        dates[4]: 95.0,
    }
    return backtest


def test_query_tearsheet_builds_frames_and_engine_logs(simple_time_grid, mock_mdp):
    backtest = _build_sample_backtest(simple_time_grid, mock_mdp)

    assert len(backtest.position_history) == len(list(simple_time_grid))
    assert len(backtest.portfolio.unwind_log) == 1
    assert len(backtest.portfolio.closed_positions_log) == 1
    assert backtest.portfolio.closed_positions_log[0]["holding_period_steps"] == 3

    tearsheet = create_query_backtest_tearsheet(backtest, capital_base=5_000_000)
    analytics = tearsheet.analytics

    assert analytics.size_metric == "bpv"
    assert analytics.summary["entry_count"] == 2.0
    assert analytics.summary["exit_count"] == 1.0
    assert analytics.summary["closed_trade_count"] == 1
    assert analytics.summary["open_trade_count"] == 1
    assert analytics.position_counts["open_positions"].max() == 2.0
    assert len(analytics.closed_trades) == 1
    assert len(analytics.open_positions) == 1
    assert analytics.closed_trades.iloc[0]["product"] == "IRS"
    assert "IRS" in analytics.product_summary.index
    assert not analytics.tag_summary.empty


def test_query_tearsheet_builds_detailed_trade_analytics(simple_time_grid, mock_mdp):
    backtest = _seed_trade_analytics_history(_build_sample_backtest(simple_time_grid, mock_mdp), simple_time_grid)

    analytics = create_query_backtest_tearsheet(backtest, capital_base=5_000_000).analytics

    assert {"direction_label", "duration_bucket", "pnl_per_day", "pnl_per_size_unit"} <= set(analytics.closed_trades.columns)
    assert analytics.summary["winning_trade_count"] == 2
    assert analytics.summary["losing_trade_count"] == 1
    assert analytics.summary["median_holding_days"] == pytest.approx(2.0)
    assert analytics.summary["avg_holding_days"] == pytest.approx(8.0 / 3.0)
    assert analytics.summary["max_win_streak"] == 2
    assert analytics.summary["current_trade_streak"] == "Loss 1"
    assert analytics.summary["total_fees"] == pytest.approx(9.0)
    assert analytics.trade_summary_frame.loc[analytics.trade_summary_frame["Metric"] == "Median Hold Days", "Value"].iloc[0] == pytest.approx(2.0)
    assert analytics.holding_period_summary.loc["Winning Trades", "avg_days"] == pytest.approx(2.0)
    assert analytics.exit_reason_summary.loc["target", "closed_trades"] == pytest.approx(2.0)
    assert analytics.exit_reason_summary.loc["target", "realized_pnl"] == pytest.approx(200.0)
    assert analytics.direction_summary.loc["Long", "closed_trades"] == pytest.approx(2.0)
    assert analytics.direction_summary.loc["Short", "closed_trades"] == pytest.approx(1.0)
    assert analytics.duration_bucket_summary.loc["1-3D", "closed_trades"] == pytest.approx(2.0)
    assert analytics.duration_bucket_summary.loc["3-7D", "closed_trades"] == pytest.approx(1.0)


def test_query_tearsheet_renders_matplotlib_and_plotly(simple_time_grid, mock_mdp):
    backtest = _build_sample_backtest(simple_time_grid, mock_mdp)
    tearsheet = QueryBacktestTearSheet.from_backtest(backtest, capital_base=10_000_000)

    mpl_figure = tearsheet.plot_matplotlib(figsize=(14, 18))
    plotly_figure = tearsheet.plot_plotly(height=1200, width=900)

    assert mpl_figure is not None
    assert hasattr(mpl_figure, "axes")
    assert isinstance(plotly_figure, go.Figure)
    assert len(plotly_figure.data) > 0

    plt.close(mpl_figure)


def test_query_tearsheet_handles_empty_backtest(simple_time_grid, mock_mdp):
    backtest = QueryDrivenBacktest(
        time_grid=simple_time_grid,
        strategy=QueryStrategy(name="Empty TearSheet", triggers=[]),
        mdp=mock_mdp,
        show_progress=False,
    )
    backtest.run()

    tearsheet = QueryBacktestTearSheet.from_backtest(backtest)
    analytics = tearsheet.analytics

    assert analytics.summary["closed_trade_count"] == 0
    assert analytics.summary["open_trade_count"] == 0
    assert analytics.summary["total_pnl"] == 0.0
    assert analytics.closed_trades.empty
    assert analytics.open_positions.empty

    mpl_figure = tearsheet.plot_matplotlib(figsize=(12, 16))
    plotly_figure = tearsheet.plot_plotly(height=1000, width=800)

    assert mpl_figure is not None
    assert isinstance(plotly_figure, go.Figure)

    plt.close(mpl_figure)
