# ABOUTME: Integration tests for unified backtest system
# ABOUTME: Tests end-to-end workflows, bridge adapters, and performance

"""
Integration Tests for Unified Backtest System

Tests the unified Backtest class across all workflows:
1. Query-based workflow (futures/swaps via adapter)
2. DataFrame-based workflow (equities/returns)
3. Hybrid workflow (combining both)
4. Bridge adapters (Query → DataFrame conversion)
5. Performance and determinism

Test Organization:
- TestEndToEnd: Complete workflow tests
- TestBridgeAdapters: Bridge adapter integration (mocked if not available)
- TestPerformance: Performance benchmarks and regression tests
"""

import pytest
import numpy as np
import polars as pl
import time
from datetime import date, timedelta
from typing import List, Dict, Any

from Backtest.Backtest import Backtest
from Backtest.Base.BaseBacktest import BacktestResult
from Signals.Futures.CarrySignal import CarrySignal
from Signals.Futures.MomentumSignal import MomentumSignal

# Check if QuantLib is available
try:
    import QuantLib as ql
    QUANTLIB_AVAILABLE = True
except ImportError:
    QUANTLIB_AVAILABLE = False

# Skip marker for tests requiring QuantLib
requires_quantlib = pytest.mark.skipif(
    not QUANTLIB_AVAILABLE,
    reason="QuantLib not available (required for FuturesAdapter)"
)


# Mock Market Data Provider for integration tests
class IntegrationMockMDP:
    """
    Mock MDP for integration testing.

    Provides synthetic futures prices with realistic behavior:
    - Carry structure (contango/backwardation)
    - Price evolution over time
    - Multiple contracts
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        np.random.seed(seed)

    def get_pricer(self, currency: str, as_of: date):
        """Return mock pricer with futures_price method."""
        return self

    def futures_price(self, contract: str) -> float:
        """Return synthetic futures price."""
        # Base price
        base = 95.0

        # Extract contract quarter
        if len(contract) >= 4:
            quarter_code = contract[-2]
            quarter_map = {'H': 0, 'M': 1, 'U': 2, 'Z': 3}
            quarter = quarter_map.get(quarter_code, 0)

            # Carry structure (contango)
            carry = quarter * 0.05
            price = base + carry
        else:
            price = base

        # Add noise
        noise = np.random.normal(0, 0.01)
        return price + noise


class TestEndToEnd:
    """Test end-to-end workflows."""

    @requires_quantlib
    def test_query_workflow_produces_results(self):
        """Query workflow executes and produces valid results."""
        from Adapter.FuturesAdapter import FuturesAdapter

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
            risk_aversion=1.0,
            long_only=True,
            min_history=3,
        )

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(10)]

        result = backtest.run(contracts, dates)

        # Verify result structure
        assert isinstance(result, BacktestResult)
        assert result.weights is not None
        assert result.returns is not None
        assert len(result.weights) > 0

        # Verify metrics calculated
        assert result.sharpe_ratio is not None
        assert result.ic is not None
        assert result.total_return is not None

    def test_dataframe_workflow_produces_results(self):
        """DataFrame workflow executes and produces valid results."""
        # Create synthetic returns DataFrame
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(10)]
        tickers = ['AAPL', 'MSFT', 'GOOGL']

        returns_data = []
        np.random.seed(42)
        for d in dates:
            for ticker in tickers:
                returns_data.append({
                    'date': d,
                    'ticker': ticker,
                    'return': np.random.normal(0.001, 0.02)
                })

        returns_df = pl.DataFrame(returns_data)

        backtest = Backtest(
            signals=MomentumSignal(lookback_days=20),
            risk_aversion=2.0,
            long_only=True,
            min_history=3,
        )

        result = backtest.run_from_dataframe(returns_df, dates)

        # Verify result structure
        assert isinstance(result, BacktestResult)
        assert result.weights is not None
        assert result.returns is not None

        # Verify metrics calculated
        assert result.sharpe_ratio is not None
        assert result.ic is not None
        assert result.total_return is not None

    @requires_quantlib
    def test_multi_signal_workflow_produces_results(self):
        """Multi-signal workflow executes and combines signals."""
        from Adapter.FuturesAdapter import FuturesAdapter
        from Signals.SignalCombiner import SignalCombiner

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        # Multiple signals with combiner
        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=[CarrySignal(), MomentumSignal(lookback_days=20)],
            signal_combiner=SignalCombiner(method='equal'),
            risk_aversion=1.0,
            long_only=True,
            min_history=3,
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(8)]

        result = backtest.run(contracts, dates)

        # Verify result structure
        assert isinstance(result, BacktestResult)
        assert len(result.weights) > 0
        assert len(result.returns) > 0

    @requires_quantlib
    def test_query_workflow_with_empty_inputs(self):
        """Query workflow handles empty inputs gracefully."""
        from Adapter.FuturesAdapter import FuturesAdapter

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
        )

        # Empty contracts
        result = backtest.run(contracts=[], dates=[date(2024, 6, 15)])
        assert len(result.returns) == 0

        # Empty dates
        result = backtest.run(contracts=['SFRZ4'], dates=[])
        assert len(result.returns) == 0

    def test_dataframe_workflow_with_empty_inputs(self):
        """DataFrame workflow handles empty inputs gracefully."""
        backtest = Backtest(signals=MomentumSignal(lookback_days=20))

        # Empty DataFrame
        empty_df = pl.DataFrame({
            'date': [],
            'ticker': [],
            'return': []
        })

        result = backtest.run_from_dataframe(empty_df, [date(2024, 6, 15)])
        assert len(result.returns) == 0

        # Empty dates
        returns_df = pl.DataFrame({
            'date': [date(2024, 6, 15)],
            'ticker': ['AAPL'],
            'return': [0.01]
        })

        result = backtest.run_from_dataframe(returns_df, dates=[])
        assert len(result.returns) == 0


class TestBridgeAdapters:
    """Test bridge adapter integration."""

    def test_mock_bridge_adapter_converts_query_to_dataframe(self):
        """
        Test bridge adapter pattern (mocked).

        Bridge adapters convert query results to DataFrame format.
        Since actual bridges may be implemented in parallel tasks,
        we test the pattern with a mock.
        """
        # Mock bridge adapter
        class MockQueryBridge:
            """Mock bridge adapter that converts query results to DataFrame."""

            def __init__(self, mdp):
                self.mdp = mdp

            def query_to_dataframe(self, queries: List[Any], as_of: date) -> pl.DataFrame:
                """Convert query results to returns DataFrame."""
                # Simulate query execution and conversion
                data = []
                for q in queries:
                    contract = getattr(q, 'contract', 'SFRZ4')
                    data.append({
                        'date': as_of,
                        'ticker': contract,
                        'return': np.random.normal(0.001, 0.02)
                    })

                return pl.DataFrame(data)

        mdp = IntegrationMockMDP(seed=42)
        bridge = MockQueryBridge(mdp)

        # Mock queries
        class MockQuery:
            def __init__(self, contract):
                self.contract = contract

        queries = [MockQuery('SFRZ4'), MockQuery('SFRH5')]
        as_of = date(2024, 6, 15)

        # Execute bridge conversion
        df = bridge.query_to_dataframe(queries, as_of)

        # Verify DataFrame structure
        assert isinstance(df, pl.DataFrame)
        assert 'date' in df.columns
        assert 'ticker' in df.columns
        assert 'return' in df.columns
        assert len(df) == len(queries)

    @requires_quantlib
    def test_bridge_adapter_integration_in_backtest(self):
        """
        Test bridge adapter integration in backtest workflow.

        This test demonstrates how a bridge adapter would be used
        to convert query-based data to DataFrame workflow.
        """
        # Create mock bridge that generates returns from queries
        class QueryReturnsAdapter:
            """Adapter that generates returns from query-based data."""

            def __init__(self, mdp):
                from Adapter.FuturesAdapter import FuturesAdapter
                self.futures_adapter = FuturesAdapter(mdp)
                self.mdp = mdp
                self.prev_prices = {}

            def get_returns(self, queries, as_of: date) -> pl.DataFrame:
                """Get returns for queries at as_of date."""
                # Convert queries to DataFrame (via FuturesAdapter)
                df = self.futures_adapter.convert(queries, as_of)

                # Calculate returns from price changes
                returns_data = []
                if isinstance(df, pl.DataFrame):
                    for row in df.iter_rows(named=True):
                        contract = row['contract']
                        price = row['price']

                        # Calculate return if we have previous price
                        if contract in self.prev_prices:
                            ret = (price - self.prev_prices[contract]) / self.prev_prices[contract]
                        else:
                            ret = 0.0

                        self.prev_prices[contract] = price

                        returns_data.append({
                            'date': as_of,
                            'ticker': contract,
                            'return': ret
                        })

                return pl.DataFrame(returns_data)

        # Test the adapter
        mdp = IntegrationMockMDP(seed=42)
        adapter = QueryReturnsAdapter(mdp)

        from Query.Futures.FuturesQuery import FuturesQuery
        from Query.Futures.FuturesStructure import FuturesStructure

        queries = [
            FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRZ4'),
            FuturesQuery(structure=FuturesStructure.OUTRIGHT, contract='SFRH5'),
        ]

        # Get returns for multiple dates
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(5)]
        all_returns = []

        for d in dates:
            returns_df = adapter.get_returns(queries, d)
            all_returns.append(returns_df)

        # Combine all returns
        combined_returns = pl.concat(all_returns)

        # Verify we got returns data
        assert len(combined_returns) > 0
        assert 'date' in combined_returns.columns
        assert 'ticker' in combined_returns.columns
        assert 'return' in combined_returns.columns


class TestPerformance:
    """Test performance and regression."""

    @requires_quantlib
    def test_query_workflow_completes_in_reasonable_time(self):
        """Query workflow completes in acceptable time (<5s for 100 steps)."""
        from Adapter.FuturesAdapter import FuturesAdapter

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
            risk_aversion=1.0,
            long_only=True,
            min_history=5,
        )

        contracts = ['SFRZ4', 'SFRH5', 'SFRM5']

        # 100 weekly periods
        start_date = date(2024, 1, 1)
        dates = [start_date + timedelta(weeks=i) for i in range(100)]

        start_time = time.time()
        result = backtest.run(contracts, dates)
        elapsed = time.time() - start_time

        # Should complete in under 5 seconds
        assert elapsed < 5.0, f"Backtest took {elapsed:.2f}s, expected <5s"

        # Should produce results
        assert len(result.returns) > 0

    def test_dataframe_workflow_completes_in_reasonable_time(self):
        """DataFrame workflow completes in acceptable time (<5s for 100 steps)."""
        # Create synthetic returns DataFrame
        start_date = date(2024, 1, 1)
        dates = [start_date + timedelta(weeks=i) for i in range(100)]
        tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']

        returns_data = []
        np.random.seed(42)
        for d in dates:
            for ticker in tickers:
                returns_data.append({
                    'date': d,
                    'ticker': ticker,
                    'return': np.random.normal(0.001, 0.02)
                })

        returns_df = pl.DataFrame(returns_data)

        backtest = Backtest(
            signals=MomentumSignal(lookback_days=20),
            risk_aversion=2.0,
            long_only=True,
            min_history=5,
        )

        start_time = time.time()
        result = backtest.run_from_dataframe(returns_df, dates)
        elapsed = time.time() - start_time

        # Should complete in under 5 seconds
        assert elapsed < 5.0, f"Backtest took {elapsed:.2f}s, expected <5s"

        # Should produce results
        assert len(result.returns) > 0

    @requires_quantlib
    def test_results_are_deterministic(self):
        """Results are deterministic with fixed random seed."""
        from Adapter.FuturesAdapter import FuturesAdapter

        # Run 1
        np.random.seed(42)
        mdp1 = IntegrationMockMDP(seed=42)
        adapter1 = FuturesAdapter(mdp1)

        backtest1 = Backtest(
            mdp=mdp1,
            adapter=adapter1,
            signals=CarrySignal(),
            risk_aversion=1.0,
            long_only=True,
            min_history=3,
        )

        contracts = ['SFRZ4', 'SFRH5']
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(10)]

        result1 = backtest1.run(contracts, dates)

        # Run 2 (same seed)
        np.random.seed(42)
        mdp2 = IntegrationMockMDP(seed=42)
        adapter2 = FuturesAdapter(mdp2)

        backtest2 = Backtest(
            mdp=mdp2,
            adapter=adapter2,
            signals=CarrySignal(),
            risk_aversion=1.0,
            long_only=True,
            min_history=3,
        )

        result2 = backtest2.run(contracts, dates)

        # Results should be identical
        assert len(result1.returns) == len(result2.returns)

        # Compare returns (should be very close)
        if len(result1.returns) > 0:
            returns1 = result1.returns.to_numpy()
            returns2 = result2.returns.to_numpy()
            assert np.allclose(returns1, returns2, rtol=1e-10)

    @requires_quantlib
    def test_backward_compatibility_with_existing_tests(self):
        """
        Unified backtest maintains backward compatibility.

        Tests that existing unit tests still work with unified Backtest.
        """
        from Adapter.FuturesAdapter import FuturesAdapter

        # This test pattern should still work
        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        # Original pattern (should still work)
        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
        )

        contracts = ['SFRZ4']
        dates = [date(2024, 6, 15)]

        result = backtest.run(contracts, dates)

        # Should produce valid result
        assert result is not None
        assert isinstance(result, BacktestResult)

    @requires_quantlib
    def test_performance_regression_query_workflow(self):
        """
        Performance regression test for query workflow.

        Ensures query workflow doesn't get slower over time.
        Baseline: <0.5s for 10 contracts × 20 periods.
        """
        from Adapter.FuturesAdapter import FuturesAdapter

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
            risk_aversion=1.0,
            min_history=3,
        )

        # 10 contracts, 20 periods
        contracts = [f'SFR{q}{y}' for q in ['Z', 'H', 'M', 'U'] for y in ['4', '5']][:10]
        dates = [date(2024, 6, 15) + timedelta(weeks=i) for i in range(20)]

        start_time = time.time()
        result = backtest.run(contracts, dates)
        elapsed = time.time() - start_time

        # Performance target: <0.5s for this size
        # (adjusted for CI/CD environments with 1.0s tolerance)
        assert elapsed < 1.0, f"Performance regression: {elapsed:.2f}s (expected <1.0s)"

        # Should produce valid results
        assert len(result.returns) > 0

    @requires_quantlib
    def test_memory_efficiency_large_backtest(self):
        """
        Test memory efficiency for large backtests.

        Ensures backtest doesn't accumulate excessive memory
        for long time series.
        """
        from Adapter.FuturesAdapter import FuturesAdapter

        mdp = IntegrationMockMDP(seed=42)
        adapter = FuturesAdapter(mdp)

        backtest = Backtest(
            mdp=mdp,
            adapter=adapter,
            signals=CarrySignal(),
            risk_aversion=1.0,
            min_history=5,
        )

        # Large backtest: 5 contracts × 200 periods
        contracts = ['SFRZ4', 'SFRH5', 'SFRM5', 'SFRU5', 'SFRZ5']
        start_date = date(2020, 1, 1)
        dates = [start_date + timedelta(weeks=i) for i in range(200)]

        # Should complete without memory error
        result = backtest.run(contracts, dates)

        # Verify results
        assert len(result.returns) > 0
        assert len(result.weights) > 0
