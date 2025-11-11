# ABOUTME: Tests for MomentumSignal measuring price/rate trends for futures
# ABOUTME: Validates time-series momentum calculation, Z-score normalization, and edge cases
"""
Tests for MomentumSignal

Validates:
- Time-series momentum calculation (price change over lookback period)
- Z-score normalization across instruments
- Multiple lookback periods (short-term, medium-term, long-term)
- Edge cases: insufficient history, constant prices, missing data
"""

import pytest
import numpy as np
import polars as pl
from datetime import date, timedelta
from typing import Dict

from Signals.Futures.MomentumSignal import MomentumSignal
from Signals.Base.BaseSignal import BaseSignal


class TestMomentumSignalConstruction:
    """Test MomentumSignal construction and initialization."""

    def test_can_import(self):
        """Can import MomentumSignal."""
        assert MomentumSignal is not None

    def test_can_construct_with_defaults(self):
        """Can construct MomentumSignal with default parameters."""
        signal = MomentumSignal()

        assert signal.name == "futures_momentum"
        assert signal.standardize is True
        assert signal.lookback_days == 60  # Default lookback

    def test_can_construct_with_custom_params(self):
        """Can construct MomentumSignal with custom parameters."""
        signal = MomentumSignal(
            name="custom_momentum",
            lookback_days=30,
            standardize=False
        )

        assert signal.name == "custom_momentum"
        assert signal.lookback_days == 30
        assert signal.standardize is False

    def test_is_base_signal_subclass(self):
        """MomentumSignal should inherit from BaseSignal."""
        signal = MomentumSignal()
        assert isinstance(signal, BaseSignal)


class TestMomentumCalculation:
    """Test momentum calculation logic."""

    def test_positive_momentum_uptrend(self):
        """Positive momentum for uptrending prices."""
        signal = MomentumSignal(lookback_days=5, standardize=False)

        # Create uptrending price history
        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(10)]
        price_history = pl.DataFrame({
            'date': dates,
            'price': [95.0 + i * 0.1 for i in range(10)]  # Uptrend
        })

        inst_data = price_history
        raw_momentum = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 10)
        )

        # Momentum should be positive for uptrend
        assert raw_momentum > 0

    def test_negative_momentum_downtrend(self):
        """Negative momentum for downtrending prices."""
        signal = MomentumSignal(lookback_days=5, standardize=False)

        # Create downtrending price history
        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(10)]
        price_history = pl.DataFrame({
            'date': dates,
            'price': [95.0 - i * 0.1 for i in range(10)]  # Downtrend
        })

        inst_data = price_history
        raw_momentum = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 10)
        )

        # Momentum should be negative for downtrend
        assert raw_momentum < 0

    def test_zero_momentum_flat_prices(self):
        """Zero momentum for flat prices."""
        signal = MomentumSignal(lookback_days=5, standardize=False)

        # Create flat price history
        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(10)]
        price_history = pl.DataFrame({
            'date': dates,
            'price': [95.0] * 10  # Flat
        })

        inst_data = price_history
        raw_momentum = signal._calculate_raw_signal(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2024, 11, 10)
        )

        # Momentum should be zero for flat prices
        assert abs(raw_momentum) < 1e-10

    def test_lookback_period_affects_magnitude(self):
        """Longer lookback captures larger price changes."""
        # Create price history with steady trend
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(100)]
        price_history = pl.DataFrame({
            'date': dates,
            'price': [95.0 + i * 0.01 for i in range(100)]  # Linear trend
        })

        # Short lookback
        signal_short = MomentumSignal(lookback_days=10, standardize=False)
        momentum_short = signal_short._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 4, 10)
        )

        # Long lookback
        signal_long = MomentumSignal(lookback_days=50, standardize=False)
        momentum_long = signal_long._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 4, 10)
        )

        # Longer lookback should capture larger price change
        assert abs(momentum_long) > abs(momentum_short)


class TestMultiInstrumentMomentum:
    """Test momentum calculation across multiple instruments."""

    def test_calculate_momentum_multiple_instruments(self):
        """Calculate momentum for multiple instruments."""
        signal = MomentumSignal(lookback_days=10)

        # Mock market data with price histories
        class MockMDP:
            def get_price_history(self, instrument, start_date, end_date):
                if instrument == 'SFRZ4':
                    # Uptrend
                    dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                    return pl.DataFrame({
                        'date': dates,
                        'price': [95.0 + i * 0.05 for i in range(len(dates))]
                    })
                elif instrument == 'SFRH5':
                    # Downtrend
                    dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                    return pl.DataFrame({
                        'date': dates,
                        'price': [94.9 - i * 0.03 for i in range(len(dates))]
                    })
                return pl.DataFrame()

        mdp = MockMDP()
        instruments = ['SFRZ4', 'SFRH5']
        as_of = date(2024, 11, 15)

        signals = signal.calculate(instruments, mdp, as_of)

        # Check structure
        assert isinstance(signals, dict)
        assert 'SFRZ4' in signals
        assert 'SFRH5' in signals

        # SFRZ4 uptrend should have positive signal
        # SFRH5 downtrend should have negative signal
        assert signals['SFRZ4'] > signals['SFRH5']

    def test_standardization_produces_z_scores(self):
        """Standardization should produce Z-scores with mean~0, std~1."""
        signal = MomentumSignal(lookback_days=10, standardize=True)

        # Create diverse momentum across instruments
        class MockMDP:
            def get_price_history(self, instrument, start_date, end_date):
                dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                if instrument == 'A':
                    prices = [100.0 + i * 0.1 for i in range(len(dates))]  # Strong up
                elif instrument == 'B':
                    prices = [100.0 + i * 0.05 for i in range(len(dates))]  # Moderate up
                elif instrument == 'C':
                    prices = [100.0] * len(dates)  # Flat
                elif instrument == 'D':
                    prices = [100.0 - i * 0.05 for i in range(len(dates))]  # Moderate down
                else:  # 'E'
                    prices = [100.0 - i * 0.1 for i in range(len(dates))]  # Strong down

                return pl.DataFrame({'date': dates, 'price': prices})

        mdp = MockMDP()
        instruments = ['A', 'B', 'C', 'D', 'E']
        signals = signal.calculate(instruments, mdp, date(2024, 11, 15))

        # Check Z-score properties
        signal_values = list(signals.values())
        mean_signal = np.mean(signal_values)
        std_signal = np.std(signal_values, ddof=1)

        assert abs(mean_signal) < 0.1  # Mean should be close to 0
        assert abs(std_signal - 1.0) < 0.2  # Std should be close to 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_insufficient_history(self):
        """Handle insufficient price history gracefully."""
        signal = MomentumSignal(lookback_days=60, standardize=False)

        # Only 5 days of history (less than lookback)
        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(5)]
        price_history = pl.DataFrame({
            'date': dates,
            'price': [95.0 + i * 0.1 for i in range(5)]
        })

        # Should handle gracefully (return 0 or use available data)
        raw_momentum = signal._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 11, 5)
        )

        # Should not crash, return sensible value
        assert isinstance(raw_momentum, (int, float))

    def test_missing_price_data(self):
        """Handle missing price data."""
        signal = MomentumSignal(lookback_days=10, standardize=False)

        # Empty price history
        price_history = pl.DataFrame({'date': [], 'price': []})

        raw_momentum = signal._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 11, 15)
        )

        # Should return 0 for missing data
        assert raw_momentum == 0.0

    def test_single_price_point(self):
        """Handle single price point."""
        signal = MomentumSignal(lookback_days=10, standardize=False)

        price_history = pl.DataFrame({
            'date': [date(2024, 11, 1)],
            'price': [95.0]
        })

        raw_momentum = signal._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 11, 1)
        )

        # Should handle gracefully
        assert isinstance(raw_momentum, (int, float))


class TestMomentumMethods:
    """Test momentum calculation methods (simple return, log return, etc.)."""

    def test_simple_return_momentum(self):
        """Test momentum using simple returns."""
        signal = MomentumSignal(
            lookback_days=15,
            standardize=False,
            method='simple'
        )

        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(20)]
        # Price increases from 100 to 110 over 20 days
        price_history = pl.DataFrame({
            'date': dates,
            'price': [100.0 + i * 0.5 for i in range(20)]  # Steady uptrend
        })

        momentum = signal._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 11, 20)
        )

        # Should be positive (prices increased)
        # Price went from ~102.5 (day 5) to 109.5 (day 19) over 15 days
        assert momentum > 0

    def test_log_return_momentum(self):
        """Test momentum using log returns."""
        signal = MomentumSignal(
            lookback_days=15,
            standardize=False,
            method='log'
        )

        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(20)]
        # Price increases from 100 to 110 over 20 days
        price_history = pl.DataFrame({
            'date': dates,
            'price': [100.0 + i * 0.5 for i in range(20)]  # Steady uptrend
        })

        momentum = signal._calculate_raw_signal(
            inst_data=price_history,
            market_data=None,
            as_of=date(2024, 11, 20)
        )

        # Should be positive (prices increased)
        assert momentum > 0


class TestMomentumIntegration:
    """Integration tests with realistic scenarios."""

    def test_momentum_captures_trend_reversal(self):
        """Momentum should change sign with trend reversal."""
        signal = MomentumSignal(lookback_days=10, standardize=False)

        # Uptrend then downtrend
        dates = [date(2024, 11, 1) + timedelta(days=i) for i in range(30)]
        prices = [95.0 + i * 0.1 for i in range(15)] + [96.5 - i * 0.1 for i in range(15)]
        price_history = pl.DataFrame({'date': dates, 'price': prices})

        # Momentum at day 10 (during uptrend)
        momentum_up = signal._calculate_raw_signal(
            inst_data=price_history[:12],
            market_data=None,
            as_of=date(2024, 11, 12)
        )

        # Momentum at day 25 (during downtrend)
        momentum_down = signal._calculate_raw_signal(
            inst_data=price_history[:27],
            market_data=None,
            as_of=date(2024, 11, 27)
        )

        # Should capture trend change
        assert momentum_up > 0
        assert momentum_down < 0

    def test_different_lookback_periods_same_ranking(self):
        """Different lookback periods should agree on relative rankings."""
        # Create clear momentum differences
        class MockMDP:
            def get_price_history(self, instrument, start_date, end_date):
                dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
                if instrument == 'STRONG_UP':
                    prices = [100.0 + i * 0.2 for i in range(len(dates))]
                elif instrument == 'WEAK_UP':
                    prices = [100.0 + i * 0.05 for i in range(len(dates))]
                elif instrument == 'WEAK_DOWN':
                    prices = [100.0 - i * 0.05 for i in range(len(dates))]
                else:  # 'STRONG_DOWN'
                    prices = [100.0 - i * 0.2 for i in range(len(dates))]
                return pl.DataFrame({'date': dates, 'price': prices})

        mdp = MockMDP()
        instruments = ['STRONG_UP', 'WEAK_UP', 'WEAK_DOWN', 'STRONG_DOWN']

        # Short lookback
        signal_short = MomentumSignal(lookback_days=10)
        signals_short = signal_short.calculate(instruments, mdp, date(2024, 11, 20))

        # Long lookback
        signal_long = MomentumSignal(lookback_days=30)
        signals_long = signal_long.calculate(instruments, mdp, date(2024, 11, 20))

        # Rankings should be consistent
        ranking_short = sorted(signals_short.items(), key=lambda x: x[1], reverse=True)
        ranking_long = sorted(signals_long.items(), key=lambda x: x[1], reverse=True)

        # Order should be: STRONG_UP > WEAK_UP > WEAK_DOWN > STRONG_DOWN
        assert ranking_short[0][0] == ranking_long[0][0] == 'STRONG_UP'
        assert ranking_short[-1][0] == ranking_long[-1][0] == 'STRONG_DOWN'
