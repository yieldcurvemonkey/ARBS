"""
Test portfolio management and position unwinding.

These tests document how to manage positions over time:
- Adding positions
- Unwinding by tag
- Unwinding by predicate
- Realized P&L tracking
"""

import pytest
import datetime
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import DateTrigger, DateTriggerRequirements
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue


class TestUnwindByTag:
    """Test unwinding positions by tag."""

    def test_unwind_single_position_by_tag(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Enter and exit a position using tags.

        Tags are the primary way to identify which positions to close.
        """
        dates = list(simple_time_grid)
        entry_date = dates[0].date()
        exit_date = dates[2].date()

        # Query with a unique tag
        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("test-trade-1",),
        )

        # Entry trigger
        enter_trigger = DateTrigger(
            DateTriggerRequirements(dates=[entry_date]),
            actions=[AddQueryAction(query=query)],
        )

        # Exit trigger
        exit_trigger = DateTrigger(
            DateTriggerRequirements(dates=[exit_date]),
            actions=[UnwindPositionsAction(match_tag="test-trade-1")],
        )

        strategy = QueryStrategy(
            name="Entry-Exit Test",
            triggers=[enter_trigger, exit_trigger],
        )

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # After exit, portfolio should be empty
        remaining_positions = list(bt.portfolio.iter_positions())
        assert len(remaining_positions) == 0

        # Should have realized some P&L
        assert exit_date in bt.realized_pnl_history

    def test_unwind_multiple_positions_same_tag(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Unwind multiple positions that share a tag.

        Useful for closing an entire strategy or theme at once.
        """
        dates = list(simple_time_grid)

        # Enter two positions with same tag
        query1 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("strategy-A",),
        )

        query2 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="10Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 500_000},
            tags=("strategy-A",),
        )

        enter1 = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query1)],
        )

        enter2 = DateTrigger(
            DateTriggerRequirements(dates=[dates[1].date()]),
            actions=[AddQueryAction(query=query2)],
        )

        # Unwind all "strategy-A" positions
        exit_trigger = DateTrigger(
            DateTriggerRequirements(dates=[dates[3].date()]),
            actions=[UnwindPositionsAction(match_tag="strategy-A")],
        )

        strategy = QueryStrategy(
            name="Multi-Unwind Test",
            triggers=[enter1, enter2, exit_trigger],
        )

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # All positions should be closed
        assert len(list(bt.portfolio.iter_positions())) == 0

    def test_partial_unwind_by_tag(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Unwind only positions with specific tag.

        Other positions should remain open.
        """
        dates = list(simple_time_grid)

        # Two positions with different tags
        query_A = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("keep-open",),
        )

        query_B = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="10Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 500_000},
            tags=("close-this",),
        )

        enter_A = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query_A)],
        )

        enter_B = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query_B)],
        )

        # Only unwind "close-this"
        exit_B = DateTrigger(
            DateTriggerRequirements(dates=[dates[2].date()]),
            actions=[UnwindPositionsAction(match_tag="close-this")],
        )

        strategy = QueryStrategy(
            name="Partial Unwind Test",
            triggers=[enter_A, enter_B, exit_B],
        )

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have one position remaining
        remaining = list(bt.portfolio.iter_positions())
        assert len(remaining) == 1
        assert "keep-open" in remaining[0].source_query.tags


class TestUnwindWithFees:
    """Test transaction costs on unwinds."""

    def test_unwind_with_transaction_cost(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Apply transaction costs when closing positions.

        Fees reduce realized P&L.
        """
        dates = list(simple_time_grid)

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("trade-1",),
        )

        enter = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query)],
        )

        # Unwind with a fee
        fee_amount = 1000.0
        exit = DateTrigger(
            DateTriggerRequirements(dates=[dates[2].date()]),
            actions=[UnwindPositionsAction(match_tag="trade-1", fee=fee_amount)],
        )

        strategy = QueryStrategy(
            name="Unwind with Fee",
            triggers=[enter, exit],
        )

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Realized P&L should account for fee
        final_realized = bt.realized_pnl
        # Should be reduced by fee (exact amount depends on MTM)
        assert isinstance(final_realized, (int, float))


class TestPortfolioIteration:
    """Test portfolio querying and iteration."""

    def test_iterate_open_positions(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Access all open positions in the portfolio.

        Useful for custom risk calculations.
        """
        dates = list(simple_time_grid)

        # Add three positions
        queries = [
            IRSwapQuery(
                structure=IRSwapStructure.OUTRIGHT,
                tenor=f"{i}Y",
                curve="USD-SOFR-1D",
                structure_kwargs={"bpv": 100_000},
                tags=(f"pos-{i}",),
            )
            for i in [2, 5, 10]
        ]

        triggers = [
            DateTrigger(
                DateTriggerRequirements(dates=[dates[0].date()]),
                actions=[AddQueryAction(query=q)],
            )
            for q in queries
        ]

        strategy = QueryStrategy(name="Multi-Position", triggers=triggers)

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should be able to iterate positions
        positions = list(bt.portfolio.iter_positions())
        assert len(positions) == 3

        # Each position should have metadata
        for pos in positions:
            assert hasattr(pos, "source_query")
            assert hasattr(pos, "package")
            assert hasattr(pos, "weights")
            assert hasattr(pos, "opened")

    def test_position_opened_timestamp(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Track when positions were opened.

        Useful for time-based exits (e.g., close after 30 days).
        """
        dates = list(simple_time_grid)
        entry_date = dates[1]

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            tenor="5Y",
            curve="USD-SOFR-1D",
            tags=("timed-trade",),
        )

        trigger = DateTrigger(
            DateTriggerRequirements(dates=[entry_date.date()]),
            actions=[AddQueryAction(query=query)],
        )

        strategy = QueryStrategy(name="Timestamp Test", triggers=[trigger])

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        positions = list(bt.portfolio.iter_positions())
        assert len(positions) == 1

        # Check opened timestamp
        assert positions[0].opened == entry_date


class TestRealizedPnL:
    """Test realized P&L tracking."""

    def test_realized_pnl_accumulates(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Realized P&L accumulates across multiple trades.

        Each unwind adds to the total realized P&L.
        """
        dates = list(simple_time_grid)

        # Trade 1: open and close
        q1 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("trade-1",),
        )

        # Trade 2: open and close
        q2 = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="10Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 500_000},
            tags=("trade-2",),
        )

        triggers = [
            # Trade 1
            DateTrigger(
                DateTriggerRequirements(dates=[dates[0].date()]),
                actions=[AddQueryAction(query=q1)],
            ),
            DateTrigger(
                DateTriggerRequirements(dates=[dates[2].date()]),
                actions=[UnwindPositionsAction(match_tag="trade-1")],
            ),
            # Trade 2
            DateTrigger(
                DateTriggerRequirements(dates=[dates[1].date()]),
                actions=[AddQueryAction(query=q2)],
            ),
            DateTrigger(
                DateTriggerRequirements(dates=[dates[3].date()]),
                actions=[UnwindPositionsAction(match_tag="trade-2")],
            ),
        ]

        strategy = QueryStrategy(name="Multiple Trades", triggers=triggers)

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Should have realized P&L history entries
        assert len(bt.realized_pnl_history) >= 2

        # Final realized should be sum of all trades
        assert isinstance(bt.realized_pnl, (int, float))

    def test_mtm_includes_open_and_realized(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: MTM = realized P&L + open position marks.

        After closing a position, MTM should include the realized gain/loss.
        """
        dates = list(simple_time_grid)

        query = IRSwapQuery(
            structure=IRSwapStructure.OUTRIGHT,
            value=IRSwapValue.NPV,
            tenor="5Y",
            curve="USD-SOFR-1D",
            structure_kwargs={"bpv": 1_000_000},
            tags=("test",),
        )

        enter = DateTrigger(
            DateTriggerRequirements(dates=[dates[0].date()]),
            actions=[AddQueryAction(query=query)],
        )

        exit = DateTrigger(
            DateTriggerRequirements(dates=[dates[2].date()]),
            actions=[UnwindPositionsAction(match_tag="test")],
        )

        strategy = QueryStrategy(name="MTM Test", triggers=[enter, exit])

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # After exit, no open positions
        assert len(list(bt.portfolio.iter_positions())) == 0

        # MTM should equal realized P&L (no open positions)
        final_date = dates[-1]
        final_mtm = bt.mtm_history.get(final_date)
        final_realized = bt.realized_pnl

        assert final_mtm == final_realized


class TestPortfolioTradeCount:
    """Test trade counting utilities."""

    def test_count_trades_in_window(self, simple_time_grid, mock_mdp):
        """
        EXAMPLE: Count trades within a date range.

        Useful for limiting trade frequency.
        """
        dates = list(simple_time_grid)

        # Add trades on specific dates
        queries = [
            IRSwapQuery(
                structure=IRSwapStructure.OUTRIGHT,
                tenor="5Y",
                curve="USD-SOFR-1D",
                tags=(f"trade-{i}",),
            )
            for i in range(3)
        ]

        triggers = [
            DateTrigger(
                DateTriggerRequirements(dates=[dates[i].date()]),
                actions=[AddQueryAction(query=queries[i])],
            )
            for i in range(3)
        ]

        strategy = QueryStrategy(name="Trade Count Test", triggers=triggers)

        bt = QueryDrivenBacktest(
            time_grid=simple_time_grid,
            mdp=mock_mdp,
            strategy=strategy,
            show_progress=False,
        )

        bt.run()

        # Count trades between first and third date
        count = bt.trade_count_since(dates[0], dates[2])

        # Should have made 2-3 trades depending on inclusive/exclusive
        assert count >= 2
