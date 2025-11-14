# ABOUTME: Tests for SignalQuery bridge adapter
# ABOUTME: Validates conversion from BaseSignal to BaseQuery interface

import pytest
import polars as pl
import numpy as np
from datetime import date, datetime
from typing import List, Tuple

from Query.Bridges.SignalQuery import SignalQuery
from Query.Base._GenericPricable import _GenericPricable
from Signals.Base.BaseSignal import BaseSignal


# Mock signal for testing
class MockSignal(BaseSignal):
    """Simple signal that returns constant values for testing."""

    def __init__(self, value=1.0, standardize=False):
        super().__init__(name="MockSignal", standardize=standardize)
        self.value = value

    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        return self.value


# Mock pricable for testing
class MockPricable(_GenericPricable):
    """Simple pricable instrument for testing."""

    def __init__(self, ticker: str):
        self.ticker = ticker


# Test fixtures
@pytest.fixture
def mock_signal():
    """Create a mock signal for testing."""
    return MockSignal(value=1.5)


@pytest.fixture
def tickers():
    """Standard test tickers."""
    return ["AAPL", "GOOGL", "MSFT"]


@pytest.fixture
def default_position_builder():
    """Default position builder that creates simple positions."""
    def builder(ticker: str, signal_value: float) -> Tuple[List[_GenericPricable], List[float]]:
        # Create a single position with weight = signal_value
        return [MockPricable(ticker)], [signal_value]
    return builder


# Construction tests
class TestConstruction:
    """Test SignalQuery initialization."""

    def test_minimal_construction(self, mock_signal, tickers):
        """Test construction with minimal required arguments."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        assert query.signal is mock_signal
        assert query.tickers == tickers
        assert query.position_builder is not None  # Should have default
        assert query.product == "Signal"  # Default product type

    def test_custom_position_builder(self, mock_signal, tickers, default_position_builder):
        """Test construction with custom position builder."""
        query = SignalQuery(
            signal=mock_signal,
            tickers=tickers,
            position_builder=default_position_builder
        )

        assert query.position_builder is default_position_builder

    def test_construction_with_name(self, mock_signal, tickers):
        """Test construction with custom name."""
        query = SignalQuery(
            signal=mock_signal,
            tickers=tickers,
            name="MySignalQuery"
        )

        assert query.name == "MySignalQuery"

    def test_invalid_construction_no_signal(self, tickers):
        """Test that construction fails without signal."""
        with pytest.raises(ValueError, match="signal cannot be None"):
            SignalQuery(signal=None, tickers=tickers)

    def test_invalid_construction_no_tickers(self, mock_signal):
        """Test that construction fails without tickers."""
        with pytest.raises(ValueError, match="tickers cannot be empty"):
            SignalQuery(signal=mock_signal, tickers=[])


# Signal generation tests
class TestSignalGeneration:
    """Test signal generation functionality."""

    def test_generates_signals_for_all_tickers(self, tickers):
        """Test that signals are generated for all tickers."""
        signal = MockSignal(value=2.0, standardize=False)
        query = SignalQuery(signal=signal, tickers=tickers)

        # Generate signals (needs pricer_or_curve for resolve_package)
        signals = query._generate_signals(as_of=date(2025, 1, 15))

        assert len(signals) == len(tickers)
        assert all(sig == 2.0 for sig in signals)

    def test_signal_standardization(self, tickers):
        """Test that signals can be standardized."""
        # Create signal with varying values
        values = [1.0, 2.0, 3.0]

        class VaryingSignal(BaseSignal):
            def __init__(self):
                super().__init__(name="Varying", standardize=True)
                self.idx = 0

            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                val = values[self.idx % len(values)]
                self.idx += 1
                return val

        signal = VaryingSignal()
        query = SignalQuery(signal=signal, tickers=tickers)

        signals = query._generate_signals(as_of=date(2025, 1, 15))

        # Should be z-scored
        assert len(signals) == 3
        # Mean should be ~0, std should be ~1
        assert abs(np.mean(signals)) < 1e-10
        assert abs(np.std(signals, ddof=1) - 1.0) < 1e-10


# Position building tests
class TestPositionBuilding:
    """Test position building from signals."""

    def test_default_position_builder(self, mock_signal, tickers):
        """Test that default position builder creates valid positions."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        # Build positions for given signals
        signals = np.array([1.0, 0.5, -0.5])
        package, weights = query._build_positions(tickers, signals)

        assert len(package) == len(tickers)
        assert len(weights) == len(tickers)
        assert all(isinstance(p, _GenericPricable) for p in package)

    def test_custom_position_builder(self, mock_signal, tickers):
        """Test custom position builder."""
        def custom_builder(ticker, signal_value):
            # Create position with doubled weight
            return [MockPricable(ticker)], [signal_value * 2.0]

        query = SignalQuery(
            signal=mock_signal,
            tickers=tickers,
            position_builder=custom_builder
        )

        signals = np.array([1.0, 0.5, -0.5])
        package, weights = query._build_positions(tickers, signals)

        # Weights should be doubled
        assert weights[0] == 2.0
        assert weights[1] == 1.0
        assert weights[2] == -1.0

    def test_position_builder_with_multiple_instruments(self, mock_signal, tickers):
        """Test position builder that creates multiple instruments per ticker."""
        def multi_builder(ticker, signal_value):
            # Create two positions per ticker
            return (
                [MockPricable(f"{ticker}_1"), MockPricable(f"{ticker}_2")],
                [signal_value * 0.6, signal_value * 0.4]
            )

        query = SignalQuery(
            signal=mock_signal,
            tickers=tickers,
            position_builder=multi_builder
        )

        signals = np.array([1.0, 1.0, 1.0])
        package, weights = query._build_positions(tickers, signals)

        # Should have 2 instruments per ticker
        assert len(package) == len(tickers) * 2
        assert len(weights) == len(tickers) * 2


# Package resolution tests
class TestPackageResolution:
    """Test resolve_package implementation."""

    def test_resolve_package_basic(self, mock_signal, tickers):
        """Test basic package resolution."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        # Resolve package (pricer_or_curve can be None for signals)
        package, weights = query.resolve_package(pricer_or_curve=None)

        assert len(package) > 0
        assert len(weights) == len(package)
        assert all(isinstance(p, _GenericPricable) for p in package)

    def test_resolve_package_with_hints(self, mock_signal, tickers):
        """Test package resolution with hints."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        # Should accept hints even if not used
        package, weights = query.resolve_package(
            pricer_or_curve=None,
            as_of=date(2025, 1, 15),
            custom_param="value"
        )

        assert len(package) > 0

    def test_resolve_package_uses_current_date(self, tickers):
        """Test that resolve_package uses correct date for signal generation."""
        class DateTrackingSignal(BaseSignal):
            def __init__(self):
                super().__init__(name="DateTracker", standardize=False)
                self.last_date = None

            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                self.last_date = as_of
                return 1.0

        signal = DateTrackingSignal()
        query = SignalQuery(signal=signal, tickers=tickers)

        test_date = date(2025, 3, 15)
        query.resolve_package(pricer_or_curve=None, as_of=test_date)

        # Signal should have been called with correct date
        assert signal.last_date == test_date


# MDP request tests
class TestMDPRequest:
    """Test build_mdp_request implementation."""

    def test_build_mdp_request_returns_empty(self, mock_signal, tickers):
        """Test that signal-based queries return empty MDP request."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        mdp_request = query.build_mdp_request(now=datetime(2025, 1, 15))

        # Should return empty dict since signals don't need MDP
        assert mdp_request == {}

    def test_build_mdp_request_with_custom_market_request(self, mock_signal, tickers):
        """Test MDP request with custom market_request."""
        query = SignalQuery(
            signal=mock_signal,
            tickers=tickers,
            market_request={"data_source": "bloomberg"}
        )

        mdp_request = query.build_mdp_request(now=datetime(2025, 1, 15))

        # Should include custom request
        assert "data_source" in mdp_request


# Required BaseQuery methods tests
class TestRequiredMethods:
    """Test required BaseQuery interface methods."""

    def test_return_query(self, mock_signal, tickers):
        """Test return_query implementation."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        result = query.return_query()

        # Should return self or list of queries
        assert result is query or (isinstance(result, list) and query in result)

    def test_col_name(self, mock_signal, tickers):
        """Test col_name implementation."""
        query = SignalQuery(signal=mock_signal, tickers=tickers, name="TestQuery")

        col_name = query.col_name()

        assert isinstance(col_name, str)
        assert len(col_name) > 0

    def test_eval_expression(self, mock_signal, tickers):
        """Test eval_expression implementation."""
        query = SignalQuery(signal=mock_signal, tickers=tickers)

        expr = query.eval_expression()

        assert isinstance(expr, str)
        assert len(expr) > 0


# Integration tests
class TestIntegration:
    """Test integration with BT/QueryDrivenBacktest."""

    def test_can_be_used_as_query(self, mock_signal, tickers):
        """Test that SignalQuery can be used as a BaseQuery."""
        from Query.Base.BaseQuery import BaseQuery

        query = SignalQuery(signal=mock_signal, tickers=tickers)

        # Should be instance of BaseQuery
        assert isinstance(query, BaseQuery)

    def test_signature_generation(self, mock_signal, tickers):
        """Test that query generates valid signature."""
        query = SignalQuery(signal=mock_signal, tickers=tickers, name="TestSig")

        sig = query.signature()

        assert isinstance(sig, str)
        assert "Signal" in sig  # Should include product type

    def test_multiple_queries_can_be_combined(self, tickers):
        """Test that multiple SignalQuery instances can be combined."""
        signal1 = MockSignal(value=1.0)
        signal2 = MockSignal(value=2.0)

        query1 = SignalQuery(signal=signal1, tickers=tickers[:2])
        query2 = SignalQuery(signal=signal2, tickers=tickers[2:])

        # Should be able to create list of queries
        queries = [query1, query2]

        assert len(queries) == 2
        assert all(isinstance(q, SignalQuery) for q in queries)
