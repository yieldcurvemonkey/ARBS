"""
Tests for Backtest query workflow support.

Tests ONLY the new query workflow functionality.
Existing signal workflow tests remain in test_backtest.py.
"""

import pytest
import polars as pl
import numpy as np
from datetime import date, datetime
from unittest.mock import Mock, MagicMock

from Backtest.Backtest import Backtest
from Query.Base.BaseQuery import BaseQuery
from MDP.MarketDataProvider import MarketDataProvider


class MockQuery(BaseQuery):
    """Mock query for testing."""

    def __init__(self, value_to_return=1.0):
        super().__init__()
        self.value_to_return = value_to_return

    def return_query(self):
        return self

    def col_name(self, cube_name=None):
        return "mock"

    def eval_expression(self, cube_name=None):
        return "mock"


class TestWorkflowDetection:
    """Test workflow detection logic."""

    def test_signal_only_detects_signal_workflow(self):
        """When only signals provided, detects signal workflow."""
        from Signals.Futures.CarrySignal import CarrySignal

        backtest = Backtest(signals=CarrySignal())

        assert backtest._workflow == 'signal'
        assert backtest.signals is not None
        assert len(backtest.queries) == 0  # queries is empty list, not None

    def test_query_only_detects_query_workflow(self):
        """When mdp + queries provided, detects query workflow."""
        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]

        backtest = Backtest(mdp=mdp, queries=queries)

        assert backtest._workflow == 'query'
        assert backtest.mdp is mdp
        assert backtest.queries == queries

    def test_both_detects_hybrid_workflow(self):
        """When both provided, detects hybrid workflow."""
        from Signals.Futures.CarrySignal import CarrySignal

        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]

        backtest = Backtest(
            mdp=mdp,
            queries=queries,
            signals=CarrySignal()
        )

        assert backtest._workflow == 'hybrid'

    def test_neither_raises_error(self):
        """When neither provided, raises ValueError."""
        with pytest.raises(ValueError, match="Must provide either signals or.*queries"):
            Backtest()


class TestQueryWorkflowConstruction:
    """Test query workflow initialization."""

    def test_accepts_queries_parameter(self):
        """Backtest accepts queries parameter."""
        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery(), MockQuery()]

        backtest = Backtest(mdp=mdp, queries=queries)

        assert backtest.queries == queries
        assert len(backtest.queries) == 2

    def test_accepts_triggers_parameter(self):
        """Backtest accepts triggers parameter."""
        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]
        triggers = [Mock(), Mock()]

        backtest = Backtest(mdp=mdp, queries=queries, triggers=triggers)

        assert backtest.triggers == triggers
        assert len(backtest.triggers) == 2

    def test_mdp_required_for_queries(self):
        """MDP required when using queries."""
        queries = [MockQuery()]

        with pytest.raises(ValueError, match="Must provide either signals or.*queries"):
            Backtest(queries=queries)


class TestQueryWorkflowExecution:
    """Test query-driven workflow execution."""

    def test_run_from_queries_method_exists(self):
        """run_from_queries() method exists."""
        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]

        backtest = Backtest(mdp=mdp, queries=queries)

        assert hasattr(backtest, 'run_from_queries')
        assert callable(backtest.run_from_queries)

    def test_run_routes_to_query_workflow(self):
        """run() routes to query workflow when appropriate."""
        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]

        backtest = Backtest(mdp=mdp, queries=queries)

        # Mock run_from_queries to verify it's called
        backtest.run_from_queries = Mock(return_value=Mock())

        time_grid = [date(2024, m, 1) for m in range(1, 4)]
        backtest.run(time_grid=time_grid)

        # Verify run_from_queries was called
        backtest.run_from_queries.assert_called_once()


class TestHybridWorkflow:
    """Test hybrid workflow (signals + queries)."""

    def test_hybrid_construction(self):
        """Hybrid workflow accepts both signals and queries."""
        from Signals.Futures.CarrySignal import CarrySignal

        mdp = Mock(spec=MarketDataProvider)
        queries = [MockQuery()]
        signal = CarrySignal()

        backtest = Backtest(
            mdp=mdp,
            queries=queries,
            signals=signal
        )

        assert backtest._workflow == 'hybrid'
        assert backtest.signals is not None
        assert backtest.queries is not None
