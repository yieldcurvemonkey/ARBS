# ABOUTME: Test suite for portfolio risk metrics (HHI, Leverage, RDI)
# ABOUTME: Verifies concentration, short-selling magnitude, and diversification measures
"""
Tests for Risk Metrics

Implements metrics from Paper 1 (Equations 7-9, page 4):
- HHI: Herfindahl-Hirschman Index (concentration)
- Leverage: Short-selling magnitude
- RDI: Risk Diversification Index

Business Requirements:
1. HHI ∈ [1/p, 1]: Lower is better (more diversified)
2. Leverage ≥ 1: 1.0 = long-only, 2.0 = fully hedged, >2.0 = leveraged
3. RDI: Lower is better (more diversified)
"""

import pytest
import numpy as np


class TestHerfindahlHirschmanIndex:
    """Test HHI concentration metric."""

    def test_hhi_ranges_from_1_p_to_1(self):
        """HHI should range from 1/p (equal weight) to 1 (single asset)."""
        from Analysis.RiskMetrics import herfindahl_hirschman_index

        p = 10

        # Minimum: Equal weights (1/p each)
        equal_weights = np.ones(p) / p
        hhi_min = herfindahl_hirschman_index(equal_weights)
        assert np.isclose(hhi_min, 1/p)

        # Maximum: Single asset (all weight in one)
        single_asset = np.zeros(p)
        single_asset[0] = 1.0
        hhi_max = herfindahl_hirschman_index(single_asset)
        assert np.isclose(hhi_max, 1.0)

        # Intermediate: Some concentration
        concentrated = np.array([0.5, 0.3, 0.2] + [0.0] * 7)
        hhi_mid = herfindahl_hirschman_index(concentrated)
        assert 1/p < hhi_mid < 1.0

    def test_hhi_equal_weight_is_1_over_p(self):
        """Equal-weighted portfolio should have HHI = 1/p."""
        from Analysis.RiskMetrics import herfindahl_hirschman_index

        for p in [5, 10, 20, 50]:
            equal_weights = np.ones(p) / p
            hhi = herfindahl_hirschman_index(equal_weights)
            assert np.isclose(hhi, 1/p)

    def test_hhi_single_asset_is_one(self):
        """Single-asset portfolio should have HHI = 1."""
        from Analysis.RiskMetrics import herfindahl_hirschman_index

        for p in [5, 10, 20]:
            single_asset = np.zeros(p)
            single_asset[0] = 1.0
            hhi = herfindahl_hirschman_index(single_asset)
            assert np.isclose(hhi, 1.0)

    def test_hhi_handles_negative_weights(self):
        """HHI should work with negative weights (short positions)."""
        from Analysis.RiskMetrics import herfindahl_hirschman_index

        # Long-short portfolio
        weights = np.array([0.6, 0.4, -0.3, -0.2, 0.5])
        # HHI = 0.6² + 0.4² + (-0.3)² + (-0.2)² + 0.5² = 0.36 + 0.16 + 0.09 + 0.04 + 0.25 = 0.90
        hhi = herfindahl_hirschman_index(weights)
        assert np.isclose(hhi, 0.90)


class TestLeverage:
    """Test leverage metric (short-selling magnitude)."""

    def test_leverage_equals_1_for_long_only(self):
        """Long-only portfolio should have leverage = 1."""
        from Analysis.RiskMetrics import leverage

        # Equal-weighted long-only
        weights = np.array([0.2, 0.3, 0.5])
        lev = leverage(weights)
        assert np.isclose(lev, 1.0)

        # Single asset
        weights = np.array([1.0, 0.0, 0.0])
        lev = leverage(weights)
        assert np.isclose(lev, 1.0)

    def test_leverage_equals_2_for_long_short_equal_weight(self):
        """Fully hedged long-short portfolio should have leverage = 2."""
        from Analysis.RiskMetrics import leverage

        # Equal long and short: +1.0 long, -1.0 short
        weights = np.array([0.5, 0.5, -0.5, -0.5])
        # |0.5| + |0.5| + |-0.5| + |-0.5| = 2.0
        lev = leverage(weights)
        assert np.isclose(lev, 2.0)

    def test_leverage_greater_than_2_for_leveraged(self):
        """Leveraged portfolio should have leverage > 2."""
        from Analysis.RiskMetrics import leverage

        # Over-leveraged: 150% long, 50% short
        weights = np.array([0.75, 0.75, -0.25, -0.25])
        # |0.75| + |0.75| + |-0.25| + |-0.25| = 2.0
        # Wait, this is exactly 2.0. Let me use a different example.

        # Over-leveraged: 200% long, 100% short
        weights = np.array([1.0, 1.0, -0.5, -0.5])
        # |1.0| + |1.0| + |-0.5| + |-0.5| = 3.0
        lev = leverage(weights)
        assert np.isclose(lev, 3.0)
        assert lev > 2.0

    def test_leverage_handles_zero_weights(self):
        """Leverage should handle zero weights correctly."""
        from Analysis.RiskMetrics import leverage

        weights = np.array([0.5, 0.5, 0.0, 0.0])
        lev = leverage(weights)
        assert np.isclose(lev, 1.0)


class TestRiskDiversificationIndex:
    """Test RDI diversification metric."""

    def test_rdi_for_uncorrelated_assets(self):
        """RDI for uncorrelated equal-variance assets should be 1/√p."""
        from Analysis.RiskMetrics import risk_diversification_index

        p = 10

        # Equal weights
        weights = np.ones(p) / p

        # Uncorrelated with equal variance
        cov_matrix = np.eye(p)

        rdi = risk_diversification_index(weights, cov_matrix)

        # Portfolio variance: w^T Σ w = (1/p)^2 * p = 1/p
        # Portfolio std: √(1/p)
        # Average individual std: w^T √diag(Σ) = (1/p) * p * 1 = 1
        # RDI = √(1/p) / 1 = 1/√p
        expected_rdi = 1 / np.sqrt(p)
        assert np.isclose(rdi, expected_rdi)

    def test_rdi_for_perfectly_correlated_assets(self):
        """RDI for perfectly correlated assets should be 1 (no diversification)."""
        from Analysis.RiskMetrics import risk_diversification_index

        p = 10

        # Equal weights
        weights = np.ones(p) / p

        # Perfectly correlated with equal variance
        cov_matrix = np.ones((p, p))

        rdi = risk_diversification_index(weights, cov_matrix)

        # Portfolio variance: w^T Σ w = (1/p)^2 * p * p = 1
        # Portfolio std: 1
        # Average individual std: w^T √diag(Σ) = (1/p) * p * 1 = 1
        # RDI = 1 / 1 = 1
        assert np.isclose(rdi, 1.0)

    def test_rdi_decreases_with_diversification(self):
        """RDI should decrease as portfolio becomes more diversified."""
        from Analysis.RiskMetrics import risk_diversification_index

        p = 5

        # Create covariance matrix with some correlation
        std = np.ones(p)
        corr_matrix = np.eye(p) + 0.5 * (np.ones((p, p)) - np.eye(p))
        cov_matrix = np.outer(std, std) * corr_matrix

        # Concentrated portfolio (most weight in one asset)
        concentrated = np.array([0.7, 0.1, 0.1, 0.05, 0.05])
        rdi_concentrated = risk_diversification_index(concentrated, cov_matrix)

        # Diversified portfolio (equal weights)
        diversified = np.ones(p) / p
        rdi_diversified = risk_diversification_index(diversified, cov_matrix)

        # Diversified should have lower RDI
        assert rdi_diversified < rdi_concentrated

    def test_rdi_handles_different_variances(self):
        """RDI should handle assets with different variances."""
        from Analysis.RiskMetrics import risk_diversification_index

        # Two assets with different variances
        weights = np.array([0.6, 0.4])
        cov_matrix = np.array([
            [1.0, 0.0],
            [0.0, 4.0]
        ])

        rdi = risk_diversification_index(weights, cov_matrix)

        # Portfolio variance: 0.6² * 1 + 0.4² * 4 = 0.36 + 0.64 = 1.0
        # Portfolio std: 1.0
        # Average individual std: 0.6 * 1 + 0.4 * 2 = 0.6 + 0.8 = 1.4
        # RDI = 1.0 / 1.4 ≈ 0.714
        expected_rdi = 1.0 / 1.4
        assert np.isclose(rdi, expected_rdi)


class TestRiskMetricsIntegration:
    """Test that risk metrics work together."""

    def test_all_metrics_on_same_portfolio(self):
        """All metrics should produce reasonable values for a typical portfolio."""
        from Analysis.RiskMetrics import (
            herfindahl_hirschman_index,
            leverage,
            risk_diversification_index,
        )

        # Typical long-short portfolio
        weights = np.array([0.3, 0.3, 0.2, 0.2, -0.2, -0.3, -0.1, -0.4])
        p = len(weights)

        # Typical covariance matrix
        np.random.seed(42)
        corr_matrix = np.eye(p) + 0.3 * (np.ones((p, p)) - np.eye(p))
        std = np.ones(p)
        cov_matrix = np.outer(std, std) * corr_matrix

        # Calculate all metrics
        hhi = herfindahl_hirschman_index(weights)
        lev = leverage(weights)
        rdi = risk_diversification_index(weights, cov_matrix)

        # Verify reasonable ranges
        assert 1/p <= hhi <= 1.0
        assert lev >= 1.0
        assert rdi > 0

        # This portfolio has shorts, so leverage > 1
        assert lev > 1.0
