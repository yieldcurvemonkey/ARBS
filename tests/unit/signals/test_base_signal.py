# ABOUTME: Test suite for BaseSignal abstract class
# ABOUTME: Verifies signal generation, z-score standardization, IC calculation, and metadata tracking
"""
Tests for BaseSignal

Verifies that the signal infrastructure works correctly:
- Signal generation returns standardized alphas (z-scores)
- IC calculation tracks predictive power
- Signal metadata is stored correctly

Test structure follows AlphaEval framework (2025):
- Predictive power (IC, Rank IC)
- Stability (IC time-series)
- Robustness (perturbations)
- Financial logic (interpretability)
- Diversity (correlation between signals)
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta


class TestBaseSignalBasics:
    """Test basic signal functionality."""

    def test_base_signal_can_be_imported(self):
        """Verify BaseSignal exists and can be imported."""
        from Signals.Base.BaseSignal import BaseSignal
        assert BaseSignal is not None

    def test_base_signal_is_abstract(self):
        """BaseSignal should be abstract and not instantiable."""
        from Signals.Base.BaseSignal import BaseSignal

        # Should raise TypeError when trying to instantiate abstract class
        with pytest.raises(TypeError):
            BaseSignal()


class TestSignalGeneration:
    """Test signal generation functionality."""

    def test_signal_generates_for_single_instrument(self):
        """Signal should generate alpha value for single instrument."""
        from Signals.Base.BaseSignal import BaseSignal

        # Create concrete signal for testing
        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                # Simple test signal: return price change
                return inst_data.iloc[0]["price"] - inst_data.iloc[-1]["price"]

        signal = TestSignal(name="test_signal")

        # Mock instrument data
        inst_data = pd.DataFrame({
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "price": [100.0, 101.0],
        })

        alpha = signal.generate(
            inst_data=inst_data,
            market_data=None,
            as_of=date(2025, 1, 2),
        )

        assert isinstance(alpha, float)

    def test_signal_generates_for_multiple_instruments(self):
        """Signal should generate alphas for multiple instruments."""
        from Signals.Base.BaseSignal import BaseSignal

        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                return inst_data.iloc[0]["price"] - inst_data.iloc[-1]["price"]

        signal = TestSignal(name="test_signal")

        # Mock data for 3 instruments
        inst_data_list = [
            pd.DataFrame({"date": [date(2025, 1, 1)], "price": [100.0]}),
            pd.DataFrame({"date": [date(2025, 1, 1)], "price": [200.0]}),
            pd.DataFrame({"date": [date(2025, 1, 1)], "price": [300.0]}),
        ]

        alphas = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=date(2025, 1, 1),
        )

        assert isinstance(alphas, np.ndarray)
        assert len(alphas) == 3


class TestSignalStandardization:
    """Test signal standardization (z-scores)."""

    def test_signal_returns_standardized_alphas(self):
        """Signals should return z-scored alphas (mean=0, std=1)."""
        from Signals.Base.BaseSignal import BaseSignal

        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                return inst_data.iloc[0]["value"]

        signal = TestSignal(name="test_signal", standardize=True)

        # Create data with known distribution
        inst_data_list = [
            pd.DataFrame({"value": [v]}) for v in [10, 20, 30, 40, 50]
        ]

        alphas = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=date(2025, 1, 1),
        )

        # Check z-score properties: mean ≈ 0, std ≈ 1
        assert abs(np.mean(alphas)) < 0.001
        assert abs(np.std(alphas, ddof=1) - 1.0) < 0.1

    def test_signal_can_skip_standardization(self):
        """Signals can optionally skip standardization."""
        from Signals.Base.BaseSignal import BaseSignal

        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                return inst_data.iloc[0]["value"]

        signal = TestSignal(name="test_signal", standardize=False)

        inst_data_list = [
            pd.DataFrame({"value": [10]}),
            pd.DataFrame({"value": [20]}),
        ]

        alphas = signal.generate_batch(
            inst_data_list=inst_data_list,
            market_data=None,
            as_of=date(2025, 1, 1),
        )

        # Should be raw values (not standardized)
        assert alphas[0] == 10.0
        assert alphas[1] == 20.0


class TestSignalMetadata:
    """Test signal metadata storage."""

    def test_signal_has_name(self):
        """Signal should store its name."""
        from Signals.Base.BaseSignal import BaseSignal

        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                return 1.0

        signal = TestSignal(name="momentum_signal")
        assert signal.name == "momentum_signal"

    def test_signal_tracks_generation_history(self):
        """Signal should track when it was last generated."""
        from Signals.Base.BaseSignal import BaseSignal

        class TestSignal(BaseSignal):
            def _calculate_raw_signal(self, inst_data, market_data, as_of):
                return 1.0

        signal = TestSignal(name="test")

        inst_data = pd.DataFrame({"value": [1.0]})
        as_of = date(2025, 1, 15)

        signal.generate(inst_data=inst_data, market_data=None, as_of=as_of)

        # Should track last generation date
        assert hasattr(signal, 'last_generated')
        assert signal.last_generated == as_of


class TestSignalICCalculation:
    """Test Information Coefficient calculation."""

    def test_ic_can_be_calculated(self):
        """Signal should calculate IC given forecasts and actuals."""
        from Signals.Utils.IC import calculate_ic

        # Perfect positive correlation: IC = 1.0
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        ic = calculate_ic(forecasts, actuals)

        assert abs(ic - 1.0) < 0.001

    def test_ic_detects_negative_correlation(self):
        """IC should be negative for inverse relationship."""
        from Signals.Utils.IC import calculate_ic

        # Perfect negative correlation: IC = -1.0
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([5.0, 4.0, 3.0, 2.0, 1.0])

        ic = calculate_ic(forecasts, actuals)

        assert ic < 0
        assert abs(ic - (-1.0)) < 0.001

    def test_ic_zero_for_no_correlation(self):
        """IC should be near zero for no relationship."""
        from Signals.Utils.IC import calculate_ic

        # No correlation
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([3.0, 3.0, 3.0, 3.0, 3.0])

        ic = calculate_ic(forecasts, actuals)

        # Should be near zero (exact zero depends on numerical precision)
        assert abs(ic) < 0.1


class TestRankIC:
    """Test Rank Information Coefficient (Spearman correlation)."""

    def test_rank_ic_can_be_calculated(self):
        """Rank IC should use rank correlation (Spearman)."""
        from Signals.Utils.IC import calculate_rank_ic

        # Perfect rank correlation
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([10.0, 20.0, 30.0, 40.0, 50.0])

        rank_ic = calculate_rank_ic(forecasts, actuals)

        assert abs(rank_ic - 1.0) < 0.001

    def test_rank_ic_robust_to_outliers(self):
        """Rank IC should be more robust than regular IC."""
        from Signals.Utils.IC import calculate_ic, calculate_rank_ic

        # With outlier in actuals
        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([1.0, 2.0, 3.0, 4.0, 1000.0])  # Last value is outlier

        ic = calculate_ic(forecasts, actuals)
        rank_ic = calculate_rank_ic(forecasts, actuals)

        # Rank IC should still be perfect (1.0) because ranks are preserved
        # Regular IC will be affected by outlier
        assert abs(rank_ic - 1.0) < 0.001
        assert ic < rank_ic  # Regular IC should be lower


class TestICStatisticalSignificance:
    """Test IC statistical significance."""

    def test_ic_significance_can_be_calculated(self):
        """Should calculate p-value for IC."""
        from Signals.Utils.IC import calculate_ic_significance

        forecasts = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        actuals = np.array([1.1, 2.2, 2.9, 4.1, 4.8])

        ic, p_value = calculate_ic_significance(forecasts, actuals)

        assert isinstance(ic, float)
        assert isinstance(p_value, float)
        assert 0 <= p_value <= 1.0

    def test_high_ic_is_significant(self):
        """High IC with enough samples should be statistically significant."""
        from Signals.Utils.IC import calculate_ic_significance

        # Generate correlated data with IC > 0.05
        np.random.seed(42)
        forecasts = np.random.randn(100)
        actuals = 0.3 * forecasts + 0.7 * np.random.randn(100)  # IC ≈ 0.3

        ic, p_value = calculate_ic_significance(forecasts, actuals)

        # Should be statistically significant (p < 0.05)
        assert abs(ic) > 0.05  # Good IC threshold
        assert p_value < 0.05  # Significant at 5% level


class TestICTimeSeries:
    """Test IC tracking over time."""

    def test_ic_time_series_tracks_stability(self):
        """Should track IC over rolling windows."""
        from Signals.Utils.IC import calculate_ic_time_series

        # Create time series of forecasts and actuals
        dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
        np.random.seed(42)

        forecasts = pd.Series(np.random.randn(100), index=dates)
        actuals = pd.Series(0.2 * forecasts + 0.8 * np.random.randn(100), index=dates)

        ic_series = calculate_ic_time_series(
            forecasts=forecasts,
            actuals=actuals,
            window=20,  # 20-day rolling window
        )

        assert isinstance(ic_series, pd.Series)
        assert len(ic_series) > 0
        assert ic_series.index[0] >= dates[19]  # First IC after 20 days

    def test_ic_decay_can_be_measured(self):
        """Should measure IC decay over time (signal halflife)."""
        from Signals.Utils.IC import calculate_ic_decay

        # Create signal with decaying IC
        dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
        np.random.seed(42)

        # IC decays exponentially
        days = np.arange(100)
        decay_factor = np.exp(-days / 20)  # Halflife = 20 days

        forecasts = pd.Series(np.random.randn(100), index=dates)
        actuals = pd.Series(
            decay_factor * forecasts + (1 - decay_factor) * np.random.randn(100),
            index=dates
        )

        halflife = calculate_ic_decay(forecasts=forecasts, actuals=actuals)

        assert isinstance(halflife, float)
        assert halflife > 0  # Should detect decay
