"""Tests for optimal OU entry/exit thresholds (spec B, Zeng-Lee 2014)."""
import numpy as np
import pytest

from RVUtils.mean_reversion import optimal_ou_thresholds


class TestOptimalOuThresholds:
    def test_zero_cost_gives_positive_threshold(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.0)
        assert a > 0, "Zero-cost entry threshold must be positive"
        assert np.isfinite(a)

    def test_higher_cost_widens_threshold(self):
        a_low, _ = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1)
        a_high, _ = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.5)
        assert a_high > a_low, "Higher cost should widen entry threshold"

    def test_long_only_exit_at_zero(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="long_only")
        assert b == pytest.approx(0.0), "Long-only exit should be at zero"
        assert a > 0

    def test_symmetric_exit_negative_of_entry(self):
        a, b = optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="symmetric")
        assert b == pytest.approx(-a), "Symmetric exit should be -a"
        assert a > 0

    def test_thresholds_finite_and_positive_entry(self):
        for cost in [0.0, 0.05, 0.2, 1.0]:
            for case in ["symmetric", "long_only"]:
                a, b = optimal_ou_thresholds(kappa=0.1, sigma=0.3, cost=cost, case=case)
                assert np.isfinite(a), f"a not finite for cost={cost}, case={case}"
                assert a > 0, f"a not positive for cost={cost}, case={case}"

    def test_invalid_case_raises(self):
        with pytest.raises(ValueError):
            optimal_ou_thresholds(kappa=0.05, sigma=0.2, cost=0.1, case="invalid")
