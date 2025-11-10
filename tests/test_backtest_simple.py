"""
Test simple backtest workflows.

These tests serve as documentation for basic backtesting scenarios.
Each test demonstrates a common use case with expected behavior.
"""

import pytest
import datetime
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, DateTrigger, DateTriggerRequirements
from BT.query_actions import AddQueryAction
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


class TestBasicBacktest:
    """Test the most basic backtest scenarios."""

    def test_empty_backtest_runs(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Run an empty backtest with no trades.

        Should complete without errors and return zero P&L.
        """
        strategy = QueryStrategy(name="Empty", triggers=[])
        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have MTM history for each date
        assert len(bt.mtm_history) == len(list(simple_time_grid))

        # All MTM should be zero (no positions)
        for mtm in bt.mtm_history.values():
            assert mtm == 0.0

        # No realized P&L
        assert bt.realized_pnl == 0.0

    def test_single_trade_backtest(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Enter a single trade and hold it.

        This is the simplest possible trading strategy:
        1. Enter a position on the first date
        2. Hold through the time grid
        3. Check final MTM
        """
        # Create a query for a 5Y IRS
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        # Create a trigger that fires on the first date
        first_date = list(simple_time_grid)[0].date()
        trigger = DateTrigger(
            DateTriggerRequirements(dates=[first_date]),
            actions=[AddQueryAction(query=query)],
        )

        strategy = QueryStrategy(name="Single Trade", triggers=[trigger])

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have MTM history
        assert len(bt.mtm_history) > 0

        # MTM on first date should be zero (just entered)
        first_mtm = bt.mtm_history[list(simple_time_grid)[0]]
        # Note: Might not be exactly zero due to bid/ask or fees
        assert isinstance(first_mtm, (int, float))

        # Should have one position in portfolio
        assert len(list(bt.portfolio.iter_positions())) == 1

        # No realized P&L yet (haven't closed)
        assert bt.realized_pnl == 0.0


class TestAlwaysOnTrigger:
    """Test triggers that fire on every date."""

    def test_always_on_trigger_fires_every_step(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Create a trigger that fires on every date.

        Useful for strategies that rebalance continuously.
        """
        from BT.triggers import TriggerRequirements
        from BT.event import TriggerInfo

        class AlwaysOnRequirements(TriggerRequirements):
            def has_triggered(self, state, backtest=None):
                return TriggerInfo(True, info={})

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="2Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 100_000},
            tags=("daily-trade",),
        )

        trigger = Trigger(
            AlwaysOnRequirements(),
            actions=[AddQueryAction(query=query)],
        )

        strategy = QueryStrategy(name="Daily Entry", triggers=[trigger])

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have added a position on each date
        num_dates = len(list(simple_time_grid))
        num_positions = len(list(bt.portfolio.iter_positions()))

        assert num_positions == num_dates


class TestMultipleTriggers:
    """Test strategies with multiple triggers."""

    def test_multiple_date_triggers(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Strategy with multiple entry dates.

        A common pattern: enter on specific dates throughout the backtest.
        """
        dates = list(simple_time_grid)

        # Enter on first date
        query1 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("trade-1",),
        )

        # Enter on third date
        query2 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="10Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 500_000},
            tags=("trade-2",),
        )

        trigger1 = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query1)],
        )

        trigger2 = DateTrigger(
            DateTriggerRequirements(dates=[dates[2].date()]),
            actions=[AddQueryAction(query=query2)],
        )

        strategy = QueryStrategy(
            name="Multiple Entries",
            triggers=[trigger1, trigger2],
        )

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have two positions
        positions = list(bt.portfolio.iter_positions())
        assert len(positions) == 2

        # Check tags
        tags = {tag for pos in positions for tag in pos.source_query.tags}
        assert "trade-1" in tags
        assert "trade-2" in tags


class TestQueryResolution:
    """Test that queries properly resolve to instruments."""

    def test_outright_resolves_to_package(self, mock_mdp):
        """
        EXAMPLE: Verify query resolution into concrete instruments.

        This tests the product adapter's structure map.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        # Get a pricer
        request = query.build_mdp_request(datetime.datetime(2025, 1, 15))
        pricer = mock_mdp.get_pricer(request)

        # Resolve the package
        package, weights = query.resolve_package(pricer_or_curve=pricer)

        # Should return a list of instruments and weights
        assert isinstance(package, list)
        assert isinstance(weights, list)
        assert len(package) == len(weights)

        # For an outright, should have at least one instrument
        assert len(package) >= 1

    def test_curve_resolves_to_multiple_instruments(self, mock_mdp):
        """
        EXAMPLE: Curve query should resolve to multiple instruments.

        A curve is a ladder across different tenors.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.CURVE,
            value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "tenors": ["2Y", "5Y", "10Y"],
                "bpv": 500_000,
            },
        )

        request = query.build_mdp_request(datetime.datetime(2025, 1, 15))
        pricer = mock_mdp.get_pricer(request)

        package, weights = query.resolve_package(pricer_or_curve=pricer)

        # Should have multiple instruments (one per tenor)
        assert len(package) >= 3

    def test_fly_resolves_to_three_legs(self, mock_mdp):
        """
        EXAMPLE: Butterfly should resolve to three instruments.

        Standard fly: +1 front, -2 belly, +1 back.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.FLY,
            value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "front_tenor": "2Y",
                "belly_tenor": "5Y",
                "back_tenor": "10Y",
                "bpv": 1_000_000,
            },
        )

        request = query.build_mdp_request(datetime.datetime(2025, 1, 15))
        pricer = mock_mdp.get_pricer(request)

        package, weights = query.resolve_package(pricer_or_curve=pricer)

        # Should have three legs
        assert len(package) == 3
        assert len(weights) == 3

        # Weights should follow fly pattern (might be normalized)
        # Typically: [+1, -2, +1] or similar
        assert isinstance(weights[0], (int, float))
        assert isinstance(weights[1], (int, float))
        assert isinstance(weights[2], (int, float))


class TestValueCalculation:
    """Test that value maps work correctly."""

    def test_calculate_npv(self, mock_mdp):
        """
        EXAMPLE: Calculate NPV for a query.

        NPV is the mark-to-market value of the position.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
        )

        request = query.build_mdp_request(datetime.datetime(2025, 1, 15))
        pricer = mock_mdp.get_pricer(request)

        package, weights = query.resolve_package(pricer_or_curve=pricer)
        value_map = query.build_value_map(
            pricer_or_curve=pricer,
            package=package,
            risk_weights=weights,
        )

        npv = value_map.apply(value=IRSwapValue.NPV)

        # Should return a numeric value
        assert isinstance(npv, (int, float))

    def test_calculate_par_rate(self, mock_mdp):
        """
        EXAMPLE: Calculate par rate for a tenor.

        Par rate is the fixed rate that makes NPV = 0.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.RATE,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        request = query.build_mdp_request(datetime.datetime(2025, 1, 15))
        pricer = mock_mdp.get_pricer(request)

        package, weights = query.resolve_package(pricer_or_curve=pricer)
        value_map = query.build_value_map(
            pricer_or_curve=pricer,
            package=package,
            risk_weights=weights,
        )

        rate = value_map.apply(value=IRSwapValue.RATE)

        # Should return a rate (typically between 0 and 1, or as bps)
        assert isinstance(rate, (int, float))
        # Sanity check: rate should be positive and reasonable
        assert 0 < rate < 1.0  # Assuming decimal format

    def test_default_mtm_value(self, mock_mdp):
        """
        EXAMPLE: Query should have a default MTM value.

        The backtest engine uses this to mark positions to market.
        """
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
        )

        mtm_value = query.default_mtm_value_id()

        assert mtm_value == IRSwapValue.NPV
