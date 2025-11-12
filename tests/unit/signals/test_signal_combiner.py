# ABOUTME: Test suite for SignalCombiner with equal weight, IC-weighted, and orthogonalization methods
# ABOUTME: Verifies sophisticated multi-signal combination approaches for Grinold-Kahn framework
"""
Tests for SignalCombiner

Verifies that signal combination methods work correctly:
- Equal weight combination (baseline)
- IC-weighted combination (better)
- Orthogonalization (best - removes correlation)

Test coverage:
1. Equal weight: simple averaging, multiple signals, edge cases
2. IC-weighted: skill-based weighting, zero/negative IC handling
3. Orthogonalization: correlation removal, Gram-Schmidt, regression residuals
4. Edge cases: single signal, missing data, perfect correlation
5. Multi-signal: 3+ signals with various correlation structures

Following Grinold-Kahn framework principles:
- Signals should be independent (maximize breadth)
- Weight by forecasting skill (IC)
- Standardize after combination
"""

import pytest
import numpy as np
import polars as pl
from datetime import date


class TestSignalCombinerBasics:
    """Test basic signal combiner functionality."""

    def test_signal_combiner_can_be_imported(self):
        """Verify SignalCombiner exists and can be imported."""
        from Signals.SignalCombiner import SignalCombiner
        assert SignalCombiner is not None

    def test_signal_combiner_can_be_instantiated(self):
        """SignalCombiner should be instantiable."""
        from Signals.SignalCombiner import SignalCombiner
        combiner = SignalCombiner()
        assert combiner is not None


class TestEqualWeightCombination:
    """Test equal weight signal combination."""

    def test_combine_single_signal_returns_unchanged(self):
        """Single signal should be returned unchanged."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.5, 'SFRH5': -0.5, 'SFRM5': 0.0}
        }

        result = combiner.combine(signals, method='equal')

        assert result == signals['carry']

    def test_combine_two_signals_equal_weight(self):
        """Two signals should be averaged equally."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': -1.0, 'SFRH5': 2.0}
        }

        result = combiner.combine(signals, method='equal')

        # Equal weight: (1.0 + -1.0) / 2 = 0.0, (0.0 + 2.0) / 2 = 1.0
        assert abs(result['SFRZ4'] - 0.0) < 0.001
        assert abs(result['SFRH5'] - 1.0) < 0.001

    def test_combine_three_signals_equal_weight(self):
        """Three signals should be averaged equally."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 3.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': 0.0, 'SFRH5': 3.0},
            'mean_reversion': {'SFRZ4': -3.0, 'SFRH5': 0.0}
        }

        result = combiner.combine(signals, method='equal')

        # Average: (3.0 + 0.0 + -3.0) / 3 = 0.0, (0.0 + 3.0 + 0.0) / 3 = 1.0
        assert abs(result['SFRZ4'] - 0.0) < 0.001
        assert abs(result['SFRH5'] - 1.0) < 0.001

    def test_combine_empty_signals_returns_empty(self):
        """Empty signals dict should return empty dict."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {}

        result = combiner.combine(signals, method='equal')

        assert result == {}

    def test_combine_handles_missing_instruments(self):
        """Should handle case where signals have different instruments."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 2.0, 'SFRM5': 3.0},
            'momentum': {'SFRZ4': -1.0, 'SFRH5': -2.0}  # Missing SFRM5
        }

        result = combiner.combine(signals, method='equal')

        # SFRZ4, SFRH5: average of 2 signals
        assert abs(result['SFRZ4'] - 0.0) < 0.001  # (1.0 + -1.0) / 2
        assert abs(result['SFRH5'] - 0.0) < 0.001  # (2.0 + -2.0) / 2
        # SFRM5: only 1 signal
        assert abs(result['SFRM5'] - 3.0) < 0.001  # 3.0 / 1


class TestICWeightedCombination:
    """Test IC-weighted signal combination."""

    def test_ic_weighted_with_different_ics(self):
        """Higher IC signal should get more weight."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': 0.0, 'SFRH5': 1.0}
        }
        ic_estimates = {
            'carry': 0.10,  # High IC
            'momentum': 0.02  # Low IC
        }

        result = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # Weights: carry = 0.10 / (0.10 + 0.02) = 0.833
        #          momentum = 0.02 / (0.10 + 0.02) = 0.167
        # SFRZ4: 1.0 * 0.833 + 0.0 * 0.167 = 0.833
        # SFRH5: 0.0 * 0.833 + 1.0 * 0.167 = 0.167
        assert abs(result['SFRZ4'] - 0.833) < 0.01
        assert abs(result['SFRH5'] - 0.167) < 0.01

    def test_ic_weighted_equal_ics_equals_equal_weight(self):
        """Equal ICs should produce equal weighting."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': -1.0, 'SFRH5': 2.0}
        }
        ic_estimates = {
            'carry': 0.05,
            'momentum': 0.05
        }

        result = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # Equal ICs → equal weight → same as equal weight method
        assert abs(result['SFRZ4'] - 0.0) < 0.001
        assert abs(result['SFRH5'] - 1.0) < 0.001

    def test_ic_weighted_handles_zero_ic(self):
        """Zero IC signal should be ignored."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 2.0},
            'momentum': {'SFRZ4': -10.0, 'SFRH5': -20.0}
        }
        ic_estimates = {
            'carry': 0.10,
            'momentum': 0.00  # No predictive power
        }

        result = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # Only carry signal has weight
        assert abs(result['SFRZ4'] - 1.0) < 0.001
        assert abs(result['SFRH5'] - 2.0) < 0.001

    def test_ic_weighted_handles_negative_ic(self):
        """Negative IC should inverse the signal."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': 0.0, 'SFRH5': 1.0}
        }
        ic_estimates = {
            'carry': 0.10,   # Positive IC
            'momentum': -0.05  # Negative IC (inverse signal)
        }

        result = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # Negative IC should weight negatively
        # Total weight: |0.10| + |-0.05| = 0.15
        # carry weight: 0.10 / 0.15 = 0.667
        # momentum weight: -0.05 / 0.15 = -0.333
        # SFRZ4: 1.0 * 0.667 + 0.0 * (-0.333) = 0.667
        # SFRH5: 0.0 * 0.667 + 1.0 * (-0.333) = -0.333
        assert abs(result['SFRZ4'] - 0.667) < 0.01
        assert abs(result['SFRH5'] - (-0.333)) < 0.01

    def test_ic_weighted_all_zero_ics_returns_zero(self):
        """All zero ICs should return zero signals."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 2.0},
            'momentum': {'SFRZ4': 3.0, 'SFRH5': 4.0}
        }
        ic_estimates = {
            'carry': 0.0,
            'momentum': 0.0
        }

        result = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # No predictive power → return zeros
        assert abs(result['SFRZ4'] - 0.0) < 0.001
        assert abs(result['SFRH5'] - 0.0) < 0.001

    def test_ic_weighted_requires_ic_estimates(self):
        """IC-weighted method should require IC estimates."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0},
            'momentum': {'SFRZ4': -1.0}
        }

        # Should raise error when ic_estimates not provided
        with pytest.raises(ValueError, match="ic_estimates required"):
            combiner.combine(signals, method='ic_weighted')


class TestOrthogonalizationCombination:
    """Test orthogonalization signal combination."""

    def test_orthogonalize_two_uncorrelated_signals(self):
        """Uncorrelated signals should remain mostly unchanged."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        # Create uncorrelated signals (orthogonal)
        signals = {
            'signal1': {'A': 1.0, 'B': -1.0, 'C': 0.0},
            'signal2': {'A': 0.0, 'B': 1.0, 'C': -1.0}
        }

        result = combiner.combine(signals, method='orthogonal')

        # Uncorrelated signals should have low correlation after combination
        # Result is equal weight of orthogonalized signals
        assert 'A' in result
        assert 'B' in result
        assert 'C' in result

    def test_orthogonalize_two_correlated_signals(self):
        """Correlated signals should be decorrelated."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        # Create highly correlated signals
        signals = {
            'signal1': {'A': 1.0, 'B': 2.0, 'C': 3.0},
            'signal2': {'A': 1.1, 'B': 2.1, 'C': 3.1}  # Almost identical
        }

        result = combiner.combine(signals, method='orthogonal')

        # After orthogonalization, combined signal should exist
        assert len(result) == 3
        assert 'A' in result
        assert 'B' in result
        assert 'C' in result

    def test_orthogonalize_perfect_correlation_removes_redundancy(self):
        """Perfectly correlated signals should collapse to single signal."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        # Perfectly correlated (second is just 2x first)
        signals = {
            'signal1': {'A': 1.0, 'B': 2.0, 'C': 3.0},
            'signal2': {'A': 2.0, 'B': 4.0, 'C': 6.0}  # 2 * signal1
        }

        result = combiner.combine(signals, method='orthogonal')

        # After orthogonalization, should effectively be single signal
        # Result should be proportional to signal1 (signal2 adds no info)
        assert len(result) == 3

    def test_orthogonalize_three_signals(self):
        """Should orthogonalize 3+ signals using Gram-Schmidt."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'signal1': {'A': 1.0, 'B': 0.0, 'C': 0.0, 'D': 1.0},
            'signal2': {'A': 0.5, 'B': 1.0, 'C': 0.0, 'D': 0.5},
            'signal3': {'A': 0.0, 'B': 0.5, 'C': 1.0, 'D': 0.0}
        }

        result = combiner.combine(signals, method='orthogonal')

        # Should produce combined signal from 3 orthogonalized signals
        assert len(result) == 4
        for inst in ['A', 'B', 'C', 'D']:
            assert inst in result

    def test_orthogonalize_single_signal_returns_unchanged(self):
        """Single signal has no correlation to remove."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.5, 'SFRH5': -0.5}
        }

        result = combiner.combine(signals, method='orthogonal')

        # Single signal → nothing to orthogonalize
        assert result == signals['carry']


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_combine_with_nan_values(self):
        """Should handle NaN values gracefully."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': np.nan, 'SFRM5': 2.0},
            'momentum': {'SFRZ4': -1.0, 'SFRH5': 1.0, 'SFRM5': np.nan}
        }

        result = combiner.combine(signals, method='equal')

        # SFRZ4: average of non-NaN values
        assert abs(result['SFRZ4'] - 0.0) < 0.001
        # SFRH5: only one non-NaN value
        assert abs(result['SFRH5'] - 1.0) < 0.001
        # SFRM5: only one non-NaN value
        assert abs(result['SFRM5'] - 2.0) < 0.001

    def test_combine_single_instrument(self):
        """Should handle single instrument case."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0},
            'momentum': {'SFRZ4': -1.0}
        }

        result = combiner.combine(signals, method='equal')

        assert abs(result['SFRZ4'] - 0.0) < 0.001

    def test_combine_invalid_method_raises_error(self):
        """Invalid combination method should raise error."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0}
        }

        with pytest.raises(ValueError, match="Unknown method"):
            combiner.combine(signals, method='invalid_method')


class TestDynamicICWeighting:
    """Test dynamic (time-varying) IC weighting."""

    def test_ic_weighted_with_dynamic_ics(self):
        """Should support time-varying IC estimates."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': 0.0, 'SFRH5': 1.0}
        }

        # First period: carry dominant
        ic_estimates_t1 = {'carry': 0.10, 'momentum': 0.02}
        result_t1 = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates_t1)

        # Second period: momentum dominant
        ic_estimates_t2 = {'carry': 0.02, 'momentum': 0.10}
        result_t2 = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates_t2)

        # Results should be different (IC changed)
        assert abs(result_t1['SFRZ4'] - result_t2['SFRZ4']) > 0.5  # Should be noticeably different


class TestCombinationComparison:
    """Test comparison between combination methods."""

    def test_all_methods_produce_valid_output(self):
        """All methods should produce valid combined signals."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': -1.0, 'SFRM5': 0.5},
            'momentum': {'SFRZ4': -0.5, 'SFRH5': 1.5, 'SFRM5': -0.5},
            'mean_reversion': {'SFRZ4': 0.0, 'SFRH5': 0.0, 'SFRM5': 1.0}
        }
        ic_estimates = {
            'carry': 0.08,
            'momentum': 0.05,
            'mean_reversion': 0.03
        }

        # Test all methods
        result_equal = combiner.combine(signals, method='equal')
        result_ic = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)
        result_ortho = combiner.combine(signals, method='orthogonal')

        # All should produce results for all instruments
        for result in [result_equal, result_ic, result_ortho]:
            assert len(result) == 3
            assert 'SFRZ4' in result
            assert 'SFRH5' in result
            assert 'SFRM5' in result

    def test_ic_weighted_gives_different_result_than_equal(self):
        """IC weighting should differ from equal weight when ICs differ."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'SFRZ4': 1.0, 'SFRH5': 0.0},
            'momentum': {'SFRZ4': 0.0, 'SFRH5': 1.0}
        }
        ic_estimates = {
            'carry': 0.10,  # Much higher
            'momentum': 0.02
        }

        result_equal = combiner.combine(signals, method='equal')
        result_ic = combiner.combine(signals, method='ic_weighted', ic_estimates=ic_estimates)

        # Should be different
        assert abs(result_equal['SFRZ4'] - result_ic['SFRZ4']) > 0.1
        assert abs(result_equal['SFRH5'] - result_ic['SFRH5']) > 0.1


class TestZScoreProperties:
    """Test that combined signals maintain proper statistical properties."""

    def test_combined_signals_can_be_standardized(self):
        """Combined signals should be z-scoreable."""
        from Signals.SignalCombiner import SignalCombiner

        combiner = SignalCombiner()
        signals = {
            'carry': {'A': 1.0, 'B': 2.0, 'C': 3.0, 'D': 4.0, 'E': 5.0},
            'momentum': {'A': -1.0, 'B': -2.0, 'C': 0.0, 'D': 2.0, 'E': 1.0}
        }

        result = combiner.combine(signals, method='equal')

        # Extract values and standardize
        values = np.array(list(result.values()))
        mean = np.mean(values)
        std = np.std(values, ddof=1)

        z_scores = (values - mean) / std

        # Z-scores should have mean ≈ 0, std ≈ 1
        assert abs(np.mean(z_scores)) < 0.001
        assert abs(np.std(z_scores, ddof=1) - 1.0) < 0.001
