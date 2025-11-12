# ABOUTME: Tests for Bai-Ng Information Criterion (K selection)
# ABOUTME: Verifies IC minimization selects reasonable number of factors

"""
Tests for BaiNgIC (Bai-Ng Information Criterion)

Based on Bai & Ng (2002) and Žignić et al. (2024) Section 3.1:
    IC(K) = log(V(K)) + K·g(p,T)

    where:
    - V(K): Sum of squared residuals with K factors
    - g(p,T) = (p+T)/(p·T)·log((p·T)/(p+T))
    - Select K* = argmin_K IC(K)
"""

import pytest
import numpy as np
import polars as pl

from Risk.Covariance.SectorBased.BlockDiagonal.BaiNgIC import BaiNgIC


class TestBaiNgICBasicFunctionality:
    """Test basic BaiNgIC functionality."""

    def test_initialization(self):
        """Test BaiNgIC initialization with default parameters."""
        ic = BaiNgIC()
        assert ic.k_max == 10

        ic_custom = BaiNgIC(k_max=15)
        assert ic_custom.k_max == 15

    def test_select_num_factors_with_synthetic_data(self):
        """Test K selection on synthetic data with known structure."""
        # Generate synthetic data with K=3 true factors
        np.random.seed(42)
        T, p = 100, 20
        K_true = 3

        # Generate true factors
        F = np.random.randn(T, K_true)

        # Generate loadings
        B = np.random.randn(p, K_true) * 2.0

        # Generate idiosyncratic noise (low variance)
        epsilon = np.random.randn(T, p) * 0.1

        # Returns: Y = B·F^T + ε
        Y = F @ B.T + epsilon

        # Convert to polars DataFrame (long format)
        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        # Run BaiNgIC
        ic = BaiNgIC(k_max=10)
        K_selected = ic.select_num_factors(returns_df)

        # Should select K close to true K=3
        assert isinstance(K_selected, int)
        assert K_selected >= 1
        assert K_selected <= 10
        # Allow some flexibility (2-5 is reasonable given noise)
        assert 2 <= K_selected <= 5

    def test_selects_reasonable_k_on_synthetic_data(self):
        """Test that BaiNgIC selects reasonable K on synthetic factor model."""
        # Generate data with K=5 strong factors
        np.random.seed(123)
        T, p = 200, 30
        K_true = 5

        # Strong factors with declining variance
        factor_vars = np.array([10.0, 5.0, 3.0, 2.0, 1.5])
        F = np.random.randn(T, K_true) * np.sqrt(factor_vars)

        # Loadings
        B = np.random.randn(p, K_true) * 1.5

        # Weak idiosyncratic component
        epsilon = np.random.randn(T, p) * 0.5

        # Returns
        Y = F @ B.T + epsilon

        # Convert to DataFrame
        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        # Run BaiNgIC
        ic = BaiNgIC(k_max=15)
        K_selected = ic.select_num_factors(returns_df)

        # Should select K close to 5
        assert 3 <= K_selected <= 7


class TestBaiNgICCurveProperties:
    """Test IC curve properties (should be U-shaped)."""

    def test_ic_decreases_then_increases(self):
        """Test that IC curve is U-shaped: decreases then increases."""
        # Generate synthetic data
        np.random.seed(999)
        T, p = 150, 25
        K_true = 4

        # Generate factor model data
        F = np.random.randn(T, K_true) * 3.0
        B = np.random.randn(p, K_true) * 2.0
        epsilon = np.random.randn(T, p) * 0.3
        Y = F @ B.T + epsilon

        # Convert to DataFrame
        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        # Get IC values for different K
        ic_estimator = BaiNgIC(k_max=12)

        # Access internal method to get IC curve
        # (We'll need to add a method to expose this)
        K_selected = ic_estimator.select_num_factors(returns_df)

        # Verify IC values were computed
        assert hasattr(ic_estimator, 'ic_values_')
        ic_values = ic_estimator.ic_values_

        # Check that IC curve has a minimum (not monotone)
        min_idx = np.argmin(ic_values)
        assert min_idx > 0, "IC should not be minimized at K=1"
        assert min_idx < len(ic_values) - 1, "IC should not be minimized at K_max"

        # Check U-shape: values before min are decreasing
        for i in range(min_idx):
            if i > 0:
                assert ic_values[i] <= ic_values[i-1], \
                    f"IC should decrease before minimum at K={min_idx+1}"


class TestBaiNgICEdgeCases:
    """Test edge cases and error handling."""

    def test_single_factor_case(self):
        """Test that K=1 is valid selection."""
        # Generate data with single dominant factor
        np.random.seed(555)
        T, p = 100, 15

        # One very strong factor
        F = np.random.randn(T, 1) * 10.0
        B = np.random.randn(p, 1) * 3.0
        epsilon = np.random.randn(T, p) * 0.1
        Y = F @ B.T + epsilon

        # Convert to DataFrame
        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        ic = BaiNgIC(k_max=10)
        K_selected = ic.select_num_factors(returns_df)

        # Should select K=1 or K=2
        assert K_selected in [1, 2]

    def test_handles_small_sample(self):
        """Test behavior with small T (T ~ p)."""
        np.random.seed(777)
        T, p = 30, 25  # T only slightly larger than p
        K_true = 3

        F = np.random.randn(T, K_true)
        B = np.random.randn(p, K_true)
        epsilon = np.random.randn(T, p) * 0.5
        Y = F @ B.T + epsilon

        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        ic = BaiNgIC(k_max=8)
        K_selected = ic.select_num_factors(returns_df)

        # Should return reasonable value
        assert 1 <= K_selected <= 8

    def test_k_max_constraint(self):
        """Test that K_max constraint is respected."""
        np.random.seed(888)
        T, p = 100, 20

        # Generate random data
        Y = np.random.randn(T, p)

        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        # Test with k_max=3
        ic = BaiNgIC(k_max=3)
        K_selected = ic.select_num_factors(returns_df)

        assert K_selected <= 3

    def test_raises_on_insufficient_data(self):
        """Test error handling when T < minimum required."""
        # Create very small dataset (T < 10)
        T, p = 5, 10
        Y = np.random.randn(T, p)

        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        ic = BaiNgIC(k_max=5)

        with pytest.raises(ValueError, match="Insufficient"):
            ic.select_num_factors(returns_df)


class TestBaiNgICIntegration:
    """Integration tests with realistic data patterns."""

    def test_with_heteroskedastic_noise(self):
        """Test robustness to heteroskedastic idiosyncratic component."""
        np.random.seed(321)
        T, p = 150, 30
        K_true = 4

        # Factor model
        F = np.random.randn(T, K_true) * 2.0
        B = np.random.randn(p, K_true) * 1.5

        # Heteroskedastic noise (varying variance across assets)
        noise_std = np.random.uniform(0.1, 1.0, size=p)
        epsilon = np.random.randn(T, p) * noise_std

        Y = F @ B.T + epsilon

        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        ic = BaiNgIC(k_max=12)
        K_selected = ic.select_num_factors(returns_df)

        # Should still identify reasonable K
        assert 2 <= K_selected <= 8

    def test_reproducibility(self):
        """Test that results are deterministic."""
        np.random.seed(456)
        T, p = 100, 20
        Y = np.random.randn(T, p)

        dates = pl.date_range(
            start=pl.datetime(2020, 1, 1),
            end=pl.datetime(2020, 1, 1) + pl.duration(days=T-1),
            interval="1d",
            eager=True,
        )

        data = []
        for i in range(p):
            for t in range(T):
                data.append({
                    "ticker": f"ASSET_{i:02d}",
                    "date": dates[t],
                    "return": Y[t, i],
                })

        returns_df = pl.DataFrame(data)

        # Run twice
        ic1 = BaiNgIC(k_max=10)
        K1 = ic1.select_num_factors(returns_df)

        ic2 = BaiNgIC(k_max=10)
        K2 = ic2.select_num_factors(returns_df)

        assert K1 == K2
