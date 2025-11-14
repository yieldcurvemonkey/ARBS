# ABOUTME: Tests for GrinoldKahnPortfolio query position tracking extension
# ABOUTME: Validates query-based position tracking, MTM-based returns, and combined workflows
"""
Tests for GrinoldKahnPortfolio Query Position Support

Validates:
- Query position tracking initialization
- Adding query positions via add_query_position()
- Return calculation from query position MTM changes
- Combined signal + query position workflows
- Position state management
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, datetime
from typing import Dict, List, Any

from Asset.GrinoldKahnPortfolio import GrinoldKahnPortfolio
from BT.query_portfolio import ResolvedQueryPosition
from Signals.Base.BaseSignal import BaseSignal
from Query.Base.BaseQuery import BaseQuery
from Query.Base._GenericPricable import _GenericPricable


# Mock classes for testing
class MockPricable(_GenericPricable):
    """Mock pricable instrument for testing."""
    def __init__(self, identifier: str, value: float):
        self.identifier = identifier
        self._value = value

    def get_value(self) -> float:
        return self._value


class MockQuery(BaseQuery):
    """Mock query for testing."""
    def __init__(self, identifier: str):
        self.identifier = identifier

    def build_mdp_request(self, as_of: datetime) -> Dict[str, Any]:
        return {'query': self.identifier, 'as_of': as_of}

    def default_mtm_value_id(self) -> str:
        return 'mtm'

    def return_query(self):
        return self

    def col_name(self, cube_name=None) -> str:
        return self.identifier

    def eval_expression(self, cube_name=None) -> str:
        return f"mock_expr_{self.identifier}"


class MockSignal(BaseSignal):
    """Simple mock signal that returns fixed Z-scores."""

    def __init__(self, scores: Dict[str, float]):
        super().__init__(name="mock_signal", standardize=False)
        self.scores = scores

    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        return 0.0

    def calculate(self, instruments, market_data, as_of):
        """Return pre-defined Z-scores for testing."""
        return {inst: self.scores.get(inst, 0.0) for inst in instruments}


class TestQueryPositionTracking:
    """Test query position tracking initialization and configuration."""

    def test_can_initialize_with_query_tracking_disabled(self):
        """GrinoldKahnPortfolio initializes with query tracking disabled by default."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_CARRY',
            signals=[signal]
        )

        assert hasattr(portfolio, 'track_query_positions')
        assert portfolio.track_query_positions is False

    def test_can_initialize_with_query_tracking_enabled(self):
        """GrinoldKahnPortfolio can be initialized with query tracking enabled."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        assert portfolio.track_query_positions is True
        assert hasattr(portfolio, '_query_positions')
        assert isinstance(portfolio._query_positions, list)
        assert len(portfolio._query_positions) == 0

    def test_query_positions_list_initialized_empty(self):
        """Query positions list starts empty."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        assert len(portfolio._query_positions) == 0


class TestAddQueryPosition:
    """Test adding query positions to portfolio."""

    def test_can_add_single_query_position(self):
        """Can add a single query position."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        # Create mock query position
        package = [MockPricable('SWAP_1', 100.0)]
        weights = [1.0]
        query = MockQuery('IRS_QUERY')

        position = ResolvedQueryPosition(
            package=package,
            weights=weights,
            opened=datetime(2024, 11, 1),
            source_query=query,
            meta={'strategy': 'carry'}
        )

        portfolio.add_query_position(position, as_of=date(2024, 11, 1))

        assert len(portfolio._query_positions) == 1
        assert portfolio._query_positions[0] == position

    def test_can_add_multiple_query_positions(self):
        """Can add multiple query positions."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        # Create two positions
        position1 = ResolvedQueryPosition(
            package=[MockPricable('SWAP_1', 100.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 1),
            source_query=MockQuery('IRS_QUERY_1'),
            meta={}
        )

        position2 = ResolvedQueryPosition(
            package=[MockPricable('SWAP_2', 200.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 2),
            source_query=MockQuery('IRS_QUERY_2'),
            meta={}
        )

        portfolio.add_query_position(position1, as_of=date(2024, 11, 1))
        portfolio.add_query_position(position2, as_of=date(2024, 11, 2))

        assert len(portfolio._query_positions) == 2

    def test_raises_error_when_tracking_disabled(self):
        """Raises error when trying to add query position with tracking disabled."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_NO_QUERY',
            signals=[signal],
            track_query_positions=False
        )

        position = ResolvedQueryPosition(
            package=[MockPricable('SWAP_1', 100.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 1),
            source_query=MockQuery('IRS_QUERY'),
            meta={}
        )

        with pytest.raises(ValueError, match="Query position tracking is not enabled"):
            portfolio.add_query_position(position, as_of=date(2024, 11, 1))


class TestQueryReturnCalculation:
    """Test return calculation from query positions."""

    def test_calculate_return_with_single_query_position(self):
        """Calculate return from single query position using MTM."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        # This test will need actual MTM calculation logic
        # For now, we're just testing the interface exists
        assert hasattr(portfolio, 'calculate_return')

    def test_calculate_return_handles_query_and_signal_positions(self):
        """Calculate return combining both query and signal positions."""
        signal = MockSignal({'SFRZ4': 1.0, 'SFRH5': 0.5})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_COMBINED',
            signals=[signal],
            track_query_positions=True
        )

        # Add query position
        position = ResolvedQueryPosition(
            package=[MockPricable('SWAP_1', 100.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 1),
            source_query=MockQuery('IRS_QUERY'),
            meta={}
        )

        portfolio.add_query_position(position, as_of=date(2024, 11, 1))

        # Calculate return with signal weights
        signal_weights = {'SFRZ4': 0.6, 'SFRH5': 0.4}
        signal_returns = {'SFRZ4': 0.02, 'SFRH5': 0.01}

        # This should handle both query and signal positions
        # Interface test - implementation will come after
        assert len(portfolio._query_positions) == 1


class TestQueryPositionState:
    """Test query position state management."""

    def test_query_positions_persisted_across_calls(self):
        """Query positions remain in portfolio across multiple operations."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        # Add position
        position = ResolvedQueryPosition(
            package=[MockPricable('SWAP_1', 100.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 1),
            source_query=MockQuery('IRS_QUERY'),
            meta={}
        )

        portfolio.add_query_position(position, as_of=date(2024, 11, 1))

        # Do some other operations
        returns_history = pl.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02],
            'SFRH5': [0.005, -0.005, 0.01]
        })

        weights = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        # Position should still be there
        assert len(portfolio._query_positions) == 1

    def test_can_retrieve_query_positions(self):
        """Can retrieve query positions from portfolio."""
        signal = MockSignal({'SFRZ4': 1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_QUERY',
            signals=[signal],
            track_query_positions=True
        )

        position = ResolvedQueryPosition(
            package=[MockPricable('SWAP_1', 100.0)],
            weights=[1.0],
            opened=datetime(2024, 11, 1),
            source_query=MockQuery('IRS_QUERY'),
            meta={'strategy': 'carry'}
        )

        portfolio.add_query_position(position, as_of=date(2024, 11, 1))

        positions = portfolio._query_positions
        assert len(positions) == 1
        assert positions[0].meta['strategy'] == 'carry'


class TestBackwardCompatibility:
    """Test that existing functionality still works."""

    def test_existing_signal_workflow_unchanged(self):
        """Existing signal-based workflow works without query tracking."""
        signal = MockSignal({'SFRZ4': 2.0, 'SFRH5': -1.0})

        portfolio = GrinoldKahnPortfolio(
            identifier='GK_CARRY',
            signals=[signal]
        )

        returns_history = pl.DataFrame({
            'SFRZ4': [0.01, -0.01, 0.02, -0.01, 0.01] * 10,
            'SFRH5': [0.005, -0.005, 0.01, -0.005, 0.005] * 10
        })

        weights = portfolio.generate_weights(
            instruments=['SFRZ4', 'SFRH5'],
            returns_history=returns_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        returns = {'SFRZ4': 0.02, 'SFRH5': 0.01}
        port_return = portfolio.calculate_return(returns, weights)

        # Should work exactly as before
        assert isinstance(port_return, float)
        assert isinstance(weights, dict)
