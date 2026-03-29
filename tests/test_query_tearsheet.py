import datetime as dt
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import plotly.graph_objects as go

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
