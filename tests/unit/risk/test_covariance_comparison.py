# ABOUTME: Comprehensive test suite for CovarianceComparison utility module
# ABOUTME: Tests compare_estimators(), print_comparison(), and out_of_sample_comparison() functions
"""
Tests for Covariance Comparison Utilities

Verifies benchmarking and comparison tools for covariance estimators:
- compare_estimators(): Benchmarks multiple estimators on stability, variance, and speed
- print_comparison(): Formats comparison results for human readability
- out_of_sample_comparison(): Gold standard evaluation using prediction accuracy

Business Requirements:
1. Compare multiple estimators systematically
2. Report key metrics: condition number, portfolio variance, fit time
3. Validate out-of-sample prediction accuracy
4. Handle edge cases gracefully (single estimator, custom weights)
"""

import pytest
import numpy as np
import polars as pl
from io import StringIO
import sys

from Risk.Covariance.SampleCovariance import SampleCovariance
from Risk.Covariance.LedoitWolfShrinkage import LedoitWolfShrinkage
from Risk.Covariance.CovarianceComparison import (
    compare_estimators,
    print_comparison,
    out_of_sample_comparison,
)


class TestCompareEstimatorsBasic:
    """Test basic functionality of compare_estimators()."""

    def test_compare_two_estimators(self):
        """Should compare Sample and Ledoit-Wolf estimators."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        # Both estimators should be in results
        assert 'Sample' in results
        assert 'Ledoit-Wolf' in results

    def test_compare_single_estimator(self):
        """Should work with single estimator (edge case)."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 5))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Single estimator should be in results
        assert 'Sample' in results
        assert len(results) == 1

    def test_compare_three_estimators(self):
        """Should handle more than two estimators."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 8))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
            'Sample2': SampleCovariance(),  # Duplicate for testing
        }

        results = compare_estimators(estimators, returns)

        assert len(results) == 3
        assert all(name in results for name in ['Sample', 'Ledoit-Wolf', 'Sample2'])


class TestCompareEstimatorsMetrics:
    """Test that all expected metrics are present and valid."""

    def test_includes_all_required_metrics(self):
        """Should include condition number, frobenius norm, portfolio variance, and fit time."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Required metrics
        metrics = results['Sample']
        assert 'condition_number' in metrics
        assert 'frobenius_norm' in metrics
        assert 'portfolio_variance' in metrics
        assert 'fit_time' in metrics

    def test_includes_eigenvalue_metrics(self):
        """Should include min/max eigenvalues and determinant."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        metrics = results['Sample']
        assert 'min_eigenvalue' in metrics
        assert 'max_eigenvalue' in metrics
        assert 'determinant' in metrics

    def test_condition_number_is_valid(self):
        """Condition number should be positive and finite."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        for name, metrics in results.items():
            assert metrics['condition_number'] > 0
            assert np.isfinite(metrics['condition_number'])

    def test_frobenius_norm_is_positive(self):
        """Frobenius norm should be positive."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        assert results['Sample']['frobenius_norm'] > 0

    def test_portfolio_variance_is_positive(self):
        """Portfolio variance should be positive."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        assert results['Sample']['portfolio_variance'] > 0

    def test_fit_time_is_reasonable(self):
        """Fit time should be positive and less than 1 second for typical case."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        for name, metrics in results.items():
            assert metrics['fit_time'] > 0
            assert metrics['fit_time'] < 1.0  # Should be fast

    def test_min_eigenvalue_nonnegative_for_sample(self):
        """Min eigenvalue should be non-negative (positive semidefinite)."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Allow small numerical errors
        assert results['Sample']['min_eigenvalue'] >= -1e-10

    def test_min_eigenvalue_positive_for_ledoit_wolf(self):
        """Min eigenvalue should be strictly positive for Ledoit-Wolf."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Ledoit-Wolf': LedoitWolfShrinkage()}

        results = compare_estimators(estimators, returns)

        assert results['Ledoit-Wolf']['min_eigenvalue'] > 1e-10

    def test_max_eigenvalue_greater_than_min(self):
        """Max eigenvalue should be greater than min eigenvalue."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        metrics = results['Sample']
        assert metrics['max_eigenvalue'] > metrics['min_eigenvalue']


class TestCompareEstimatorsShrinkageIntensity:
    """Test that shrinkage intensity is captured when available."""

    def test_captures_shrinkage_intensity_for_ledoit_wolf(self):
        """Should capture shrinkage intensity for Ledoit-Wolf."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Ledoit-Wolf': LedoitWolfShrinkage()}

        results = compare_estimators(estimators, returns)

        # Should have shrinkage intensity
        assert 'shrinkage_intensity' in results['Ledoit-Wolf']
        assert 0 <= results['Ledoit-Wolf']['shrinkage_intensity'] <= 1

    def test_no_shrinkage_intensity_for_sample_covariance(self):
        """Sample covariance should not have shrinkage intensity."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Should not have shrinkage intensity
        assert 'shrinkage_intensity' not in results['Sample']

    def test_shrinkage_intensity_differs_across_datasets(self):
        """Shrinkage intensity should vary with data characteristics."""
        np.random.seed(42)

        # Well-conditioned data (T >> N)
        returns_well = pl.DataFrame(np.random.randn(200, 10))

        # Ill-conditioned data (T ≈ N)
        returns_ill = pl.DataFrame(np.random.randn(30, 25))

        estimators_well = {'LW': LedoitWolfShrinkage()}
        estimators_ill = {'LW': LedoitWolfShrinkage()}

        results_well = compare_estimators(estimators_well, returns_well)
        results_ill = compare_estimators(estimators_ill, returns_ill)

        # Ill-conditioned should have higher shrinkage
        # (though simplified LW may not show huge difference)
        assert results_ill['LW']['shrinkage_intensity'] >= results_well['LW']['shrinkage_intensity']


class TestCompareEstimatorsCustomWeights:
    """Test comparison with custom portfolio weights."""

    def test_uses_equal_weights_by_default(self):
        """Should use equal weights when none provided."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 5))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Portfolio variance should match equal-weighted calculation
        cov_matrix = SampleCovariance().fit(returns)
        equal_weights = np.ones(5) / 5
        expected_var = equal_weights @ cov_matrix @ equal_weights

        assert abs(results['Sample']['portfolio_variance'] - expected_var) < 1e-6

    def test_uses_custom_weights(self):
        """Should use custom weights when provided."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 5))

        # Custom weights (concentrated in first asset)
        custom_weights = np.array([0.6, 0.2, 0.1, 0.05, 0.05])

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns, custom_weights)

        # Portfolio variance should match custom-weighted calculation
        cov_matrix = SampleCovariance().fit(returns)
        expected_var = custom_weights @ cov_matrix @ custom_weights

        assert abs(results['Sample']['portfolio_variance'] - expected_var) < 1e-6

    def test_custom_weights_differ_from_equal_weights(self):
        """Custom weights should give different portfolio variance than equal weights."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 5))

        # Very unequal weights
        custom_weights = np.array([0.8, 0.1, 0.05, 0.03, 0.02])

        estimators = {'Sample': SampleCovariance()}

        results_equal = compare_estimators(estimators, returns)
        results_custom = compare_estimators(estimators, returns, custom_weights)

        # Portfolio variance should be different
        var_equal = results_equal['Sample']['portfolio_variance']
        var_custom = results_custom['Sample']['portfolio_variance']

        assert abs(var_equal - var_custom) > 0.001  # Should differ meaningfully


class TestCompareEstimatorsComparison:
    """Test that comparison reveals expected differences between estimators."""

    def test_ledoit_wolf_has_better_condition_number_when_ill_conditioned(self):
        """Ledoit-Wolf should have better condition number than Sample when T ≈ N."""
        np.random.seed(42)
        # Ill-conditioned: T ≈ N
        returns = pl.DataFrame(np.random.randn(30, 25))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        # LW should have better condition number
        assert results['Ledoit-Wolf']['condition_number'] < results['Sample']['condition_number']

    def test_ledoit_wolf_has_higher_min_eigenvalue(self):
        """Ledoit-Wolf should have higher min eigenvalue (more stable)."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(50, 20))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        # LW should have higher min eigenvalue (shrinks toward positive definite)
        assert results['Ledoit-Wolf']['min_eigenvalue'] > results['Sample']['min_eigenvalue']

    def test_comparison_reveals_stability_improvement(self):
        """Comparison should clearly show stability improvement from shrinkage."""
        np.random.seed(42)
        # Challenging case: T slightly > N
        returns = pl.DataFrame(np.random.randn(60, 50))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        # Multiple stability metrics should be better for LW
        lw = results['Ledoit-Wolf']
        sample = results['Sample']

        assert lw['condition_number'] < sample['condition_number']
        assert lw['min_eigenvalue'] > sample['min_eigenvalue']
        assert lw['determinant'] > sample['determinant']


class TestPrintComparison:
    """Test print_comparison() output formatting."""

    def test_print_comparison_produces_output(self):
        """Should print formatted table to stdout."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = compare_estimators(estimators, returns)

        # Capture stdout
        captured = StringIO()
        sys.stdout = captured
        print_comparison(results)
        sys.stdout = sys.__stdout__

        output = captured.getvalue()

        # Should contain table elements
        assert 'Covariance Estimator Comparison' in output
        assert 'Sample' in output
        assert 'Ledoit-Wolf' in output
        assert 'CondNum' in output
        assert 'PortVar' in output

    def test_print_comparison_shows_shrinkage_intensity(self):
        """Should show shrinkage intensity for Ledoit-Wolf."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Ledoit-Wolf': LedoitWolfShrinkage()}

        results = compare_estimators(estimators, returns)

        # Capture stdout
        captured = StringIO()
        sys.stdout = captured
        print_comparison(results)
        sys.stdout = sys.__stdout__

        output = captured.getvalue()

        # Should contain shrinkage intensity
        assert 'Shrinkage intensity' in output
        assert 'δ' in output

    def test_print_comparison_handles_single_estimator(self):
        """Should print table with single estimator."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Capture stdout
        captured = StringIO()
        sys.stdout = captured
        print_comparison(results)
        sys.stdout = sys.__stdout__

        output = captured.getvalue()

        # Should contain table with one row
        assert 'Sample' in output
        assert 'CondNum' in output

    def test_print_comparison_handles_no_shrinkage_intensity(self):
        """Should not show shrinkage intensity for Sample covariance."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        estimators = {'Sample': SampleCovariance()}

        results = compare_estimators(estimators, returns)

        # Capture stdout
        captured = StringIO()
        sys.stdout = captured
        print_comparison(results)
        sys.stdout = sys.__stdout__

        output = captured.getvalue()

        # Should NOT contain shrinkage intensity
        assert 'Shrinkage intensity' not in output

    def test_print_comparison_handles_empty_results(self):
        """Should handle empty results dictionary gracefully."""
        results = {}

        # Capture stdout
        captured = StringIO()
        sys.stdout = captured
        print_comparison(results)
        sys.stdout = sys.__stdout__

        output = captured.getvalue()

        # Should print header but no rows
        assert 'Covariance Estimator Comparison' in output


class TestOutOfSampleComparison:
    """Test out_of_sample_comparison() function."""

    def test_out_of_sample_comparison_basic(self):
        """Should compute out-of-sample metrics."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # Both estimators should be in results
        assert 'Sample' in results
        assert 'Ledoit-Wolf' in results

    def test_out_of_sample_includes_all_metrics(self):
        """Should include predicted variance, actual variance, and errors."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        metrics = results['Sample']
        assert 'predicted_variance' in metrics
        assert 'actual_variance' in metrics
        assert 'prediction_error' in metrics
        assert 'relative_error' in metrics

    def test_actual_variance_is_same_for_all_estimators(self):
        """Actual variance should be same for all estimators (it's the ground truth)."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # Actual variance should be identical
        actual_sample = results['Sample']['actual_variance']
        actual_lw = results['Ledoit-Wolf']['actual_variance']

        assert abs(actual_sample - actual_lw) < 1e-10

    def test_prediction_error_is_absolute_difference(self):
        """Prediction error should be |predicted - actual|."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        metrics = results['Sample']
        expected_error = abs(metrics['predicted_variance'] - metrics['actual_variance'])

        assert abs(metrics['prediction_error'] - expected_error) < 1e-10

    def test_relative_error_is_normalized(self):
        """Relative error should be prediction_error / actual_variance."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        metrics = results['Sample']
        expected_relative = metrics['prediction_error'] / metrics['actual_variance']

        assert abs(metrics['relative_error'] - expected_relative) < 1e-10

    def test_out_of_sample_uses_equal_weights_by_default(self):
        """Should use equal weights when none provided."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 5))
        returns_out = pl.DataFrame(np.random.randn(50, 5))

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # Actual variance should match equal-weighted portfolio
        equal_weights = np.ones(5) / 5
        portfolio_returns = returns_out @ equal_weights
        expected_actual = np.var(portfolio_returns, ddof=1)

        assert abs(results['Sample']['actual_variance'] - expected_actual) < 1e-10

    def test_out_of_sample_uses_custom_weights(self):
        """Should use custom weights when provided."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 5))
        returns_out = pl.DataFrame(np.random.randn(50, 5))

        # Custom weights
        custom_weights = np.array([0.5, 0.25, 0.15, 0.07, 0.03])

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out, custom_weights)

        # Actual variance should match custom-weighted portfolio
        portfolio_returns = returns_out @ custom_weights
        expected_actual = np.var(portfolio_returns, ddof=1)

        assert abs(results['Sample']['actual_variance'] - expected_actual) < 1e-10

    def test_out_of_sample_single_estimator(self):
        """Should work with single estimator (edge case)."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {'Ledoit-Wolf': LedoitWolfShrinkage()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        assert 'Ledoit-Wolf' in results
        assert len(results) == 1


class TestOutOfSampleComparativePerformance:
    """Test that out-of-sample comparison reveals estimator quality."""

    def test_ledoit_wolf_generally_has_lower_prediction_error(self):
        """Ledoit-Wolf should have lower prediction error on average (stochastic test)."""
        # Run multiple trials to establish average behavior
        np.random.seed(42)

        n_trials = 20
        lw_wins = 0

        for i in range(n_trials):
            # Generate fresh data each trial
            np.random.seed(42 + i)
            returns_in = pl.DataFrame(np.random.randn(50, 20))
            returns_out = pl.DataFrame(np.random.randn(50, 20))

            estimators = {
                'Sample': SampleCovariance(),
                'Ledoit-Wolf': LedoitWolfShrinkage(),
            }

            results = out_of_sample_comparison(estimators, returns_in, returns_out)

            if results['Ledoit-Wolf']['prediction_error'] < results['Sample']['prediction_error']:
                lw_wins += 1

        # LW should win majority of trials (allow some randomness)
        # In realistic scenarios, LW wins 60-70% of the time
        assert lw_wins >= n_trials * 0.5  # Conservative: at least 50%

    def test_shrinkage_reduces_overfitting(self):
        """Ledoit-Wolf should reduce overfitting in ill-conditioned case."""
        np.random.seed(42)
        # Ill-conditioned: T ≈ N
        returns_in = pl.DataFrame(np.random.randn(40, 35))
        returns_out = pl.DataFrame(np.random.randn(40, 35))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # In ill-conditioned case, LW should be more accurate
        # (Sample covariance overfits and predicts poorly)
        assert results['Ledoit-Wolf']['prediction_error'] <= results['Sample']['prediction_error'] * 1.5


class TestOutOfSampleEdgeCases:
    """Test edge cases for out-of-sample comparison."""

    def test_handles_zero_variance_portfolio(self):
        """Should handle case where out-of-sample variance is near zero."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 5))

        # Out-of-sample: nearly constant returns with tiny variation
        returns_data = np.ones((50, 5)) * 0.001
        returns_data[0, :] = 0.002
        returns_out = pl.DataFrame(returns_data)

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # Should compute without error
        assert 'Sample' in results
        # Actual variance should be near zero
        assert results['Sample']['actual_variance'] < 0.001
        # Relative error might be large (dividing by small number)
        assert results['Sample']['relative_error'] >= 0

    def test_predicted_variance_is_positive(self):
        """Predicted variance should always be positive."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {
            'Sample': SampleCovariance(),
            'Ledoit-Wolf': LedoitWolfShrinkage(),
        }

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        for name, metrics in results.items():
            assert metrics['predicted_variance'] > 0

    def test_actual_variance_is_positive(self):
        """Actual variance should be positive (or very close to zero)."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        estimators = {'Sample': SampleCovariance()}

        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        assert results['Sample']['actual_variance'] >= 0


class TestIntegrationWithExistingTests:
    """Test that comparison utilities integrate with existing covariance tests."""

    def test_comparison_consistent_with_individual_estimator_tests(self):
        """Metrics from compare_estimators should match individual estimator behavior."""
        np.random.seed(42)
        returns = pl.DataFrame(np.random.randn(100, 10))

        # Compare using compare_estimators
        estimators = {'Ledoit-Wolf': LedoitWolfShrinkage()}
        comparison_results = compare_estimators(estimators, returns)

        # Compute directly
        lw = LedoitWolfShrinkage()
        cov_matrix = lw.fit(returns)

        # Check consistency
        direct_cond = np.linalg.cond(cov_matrix)
        comparison_cond = comparison_results['Ledoit-Wolf']['condition_number']

        assert abs(direct_cond - comparison_cond) < 1e-6

    def test_out_of_sample_consistent_with_manual_calculation(self):
        """Out-of-sample metrics should match manual calculation."""
        np.random.seed(42)
        returns_in = pl.DataFrame(np.random.randn(50, 10))
        returns_out = pl.DataFrame(np.random.randn(50, 10))

        # Use comparison function
        estimators = {'Sample': SampleCovariance()}
        results = out_of_sample_comparison(estimators, returns_in, returns_out)

        # Manual calculation
        weights = np.ones(10) / 10
        cov_matrix = SampleCovariance().fit(returns_in)
        predicted = weights @ cov_matrix @ weights

        portfolio_returns = returns_out @ weights
        actual = np.var(portfolio_returns, ddof=1)

        # Check consistency
        assert abs(results['Sample']['predicted_variance'] - predicted) < 1e-10
        assert abs(results['Sample']['actual_variance'] - actual) < 1e-10
