"""
Tests for TimeSeriesSignalMixin

Tests the common time-series signal functionality:
- calculate(): Batch signal generation
- _standardize_signals(): Z-score normalization
- _update_history(): History tracking
"""

import pytest
from datetime import date, timedelta
import numpy as np
import polars as pl

from Signals.Base.BaseSignal import BaseSignal
from Signals.Base.TimeSeriesSignalMixin import TimeSeriesSignalMixin


# Create a concrete test signal class that uses the mixin
class TestSignal(BaseSignal, TimeSeriesSignalMixin):
    """Test signal using TimeSeriesSignalMixin for testing."""

    def __init__(self, lookback_days=30, standardize=True, track_history=True):
        super().__init__(name="test_signal", standardize=standardize, track_history=track_history)
        self.lookback_days = lookback_days

    def _calculate_raw_signal(self, inst_data, market_data, as_of):
        """Simple raw signal: return the last price."""
        if inst_data is None or len(inst_data) == 0:
            return 0.0
        if 'price' not in inst_data.columns:
            return 0.0
        return float(inst_data['price'][-1])


# Mock market data provider
class MockMarketData:
    """Mock market data provider for testing."""

    def __init__(self, price_data):
        """
        Args:
            price_data: Dict mapping instrument → list of (date, price) tuples
        """
        self.price_data = price_data

    def get_price_history(self, instrument, start_date, end_date):
        """Return price history as Polars DataFrame."""
        if instrument not in self.price_data:
            raise ValueError(f"Instrument {instrument} not found")

        data = self.price_data[instrument]
        dates, prices = zip(*data)

        df = pl.DataFrame({
            'date': dates,
            'price': prices
        })

        return df.filter(
            (pl.col('date') >= start_date) & (pl.col('date') <= end_date)
        )


class TestTimeSeriesSignalMixin:
    """Tests for TimeSeriesSignalMixin functionality."""

    def test_calculate_batch(self):
        """Test calculate() with multiple instruments."""
        # Create mock data
        base_date = date(2024, 11, 1)
        price_data = {
            'INST1': [(base_date - timedelta(days=i), 100 + i) for i in range(60, -1, -1)],
            'INST2': [(base_date - timedelta(days=i), 200 + i) for i in range(60, -1, -1)],
            'INST3': [(base_date - timedelta(days=i), 50 + i) for i in range(60, -1, -1)],
        }
        mdp = MockMarketData(price_data)

        # Create signal and calculate
        signal = TestSignal(lookback_days=30, standardize=True)
        results = signal.calculate(['INST1', 'INST2', 'INST3'], mdp, base_date)

        # Verify results
        assert len(results) == 3
        assert 'INST1' in results
        assert 'INST2' in results
        assert 'INST3' in results

        # Results should be standardized (Z-scores)
        # Raw signals: 100, 200, 50
        # Mean: 116.67, Std: 76.38
        # Z-scores: -0.218, 1.091, -0.873 (approximately)
        assert abs(results['INST2']) > abs(results['INST1'])  # 200 is furthest from mean
        assert results['INST2'] > 0  # Above mean
        assert results['INST3'] < 0  # Below mean

    def test_calculate_single(self):
        """Test calculate() with single instrument (edge case)."""
        base_date = date(2024, 11, 1)
        price_data = {
            'INST1': [(base_date - timedelta(days=i), 100 + i) for i in range(60, -1, -1)],
        }
        mdp = MockMarketData(price_data)

        signal = TestSignal(lookback_days=30, standardize=True)
        results = signal.calculate(['INST1'], mdp, base_date)

        # Single instrument → BaseSignal returns raw signal (can't standardize one value)
        assert len(results) == 1
        assert abs(results['INST1'] - 100.0) < 0.01

    def test_calculate_with_error(self):
        """Test calculate() handles errors gracefully."""
        base_date = date(2024, 11, 1)
        price_data = {
            'INST1': [(base_date - timedelta(days=i), 100 + i) for i in range(60, -1, -1)],
            # INST2 missing (will cause error)
        }
        mdp = MockMarketData(price_data)

        signal = TestSignal(lookback_days=30, standardize=True)
        results = signal.calculate(['INST1', 'INST2'], mdp, base_date)

        # INST2 should be excluded, not included with 0.0
        assert len(results) == 1  # Only INST1
        assert 'INST1' in results
        assert 'INST2' not in results  # Excluded!

    def test_standardize_signals(self):
        """Test _standardize_signals() Z-score calculation."""
        signal = TestSignal()

        raw_signals = {
            'A': 100.0,
            'B': 110.0,
            'C': 90.0,
        }

        # Mean = 100, Std = 10
        # Z-scores: A=0, B=1, C=-1
        standardized = signal._standardize_signals(raw_signals)

        assert len(standardized) == 3
        assert abs(standardized['A'] - 0.0) < 0.01
        assert abs(standardized['B'] - 1.0) < 0.01
        assert abs(standardized['C'] - (-1.0)) < 0.01

    def test_standardize_single_instrument(self):
        """Test _standardize_signals() with single instrument."""
        signal = TestSignal()

        raw_signals = {'A': 100.0}
        standardized = signal._standardize_signals(raw_signals)

        # Single instrument → no cross-sectional info → return 0
        assert standardized['A'] == 0.0

    def test_standardize_no_variation(self):
        """Test _standardize_signals() when all signals are identical."""
        signal = TestSignal()

        raw_signals = {
            'A': 100.0,
            'B': 100.0,
            'C': 100.0,
        }

        standardized = signal._standardize_signals(raw_signals)

        # No variation → all return 0
        assert standardized['A'] == 0.0
        assert standardized['B'] == 0.0
        assert standardized['C'] == 0.0

    def test_update_history(self):
        """Test _update_history() signal tracking."""
        signal = TestSignal(track_history=True)

        as_of = date(2024, 11, 1)
        signals = {
            'A': 1.0,
            'B': -1.0,
            'C': 0.0,
        }

        signal._update_history(as_of, signals)

        # Verify history was stored
        assert signal.history is not None
        assert as_of in signal.history

        history_entry = signal.history[as_of]
        assert 'signals' in history_entry
        assert 'mean' in history_entry
        assert 'std' in history_entry

        # Verify values
        assert history_entry['signals'] == signals
        assert abs(history_entry['mean'] - 0.0) < 0.01  # Mean of 1, -1, 0
        assert history_entry['std'] > 0  # Non-zero std

    def test_standardize_false(self):
        """Test calculate() with standardize=False (raw signals)."""
        base_date = date(2024, 11, 1)
        price_data = {
            'INST1': [(base_date - timedelta(days=i), 100.0) for i in range(60, -1, -1)],
            'INST2': [(base_date - timedelta(days=i), 200.0) for i in range(60, -1, -1)],
        }
        mdp = MockMarketData(price_data)

        signal = TestSignal(lookback_days=30, standardize=False)
        results = signal.calculate(['INST1', 'INST2'], mdp, base_date)

        # Should return raw signals (last prices)
        assert abs(results['INST1'] - 100.0) < 0.01
        assert abs(results['INST2'] - 200.0) < 0.01
