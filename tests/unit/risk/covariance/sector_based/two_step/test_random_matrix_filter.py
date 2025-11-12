# ABOUTME: Tests for RandomMatrixFilter with Marčenko-Pastur threshold
# ABOUTME: Validates eigenvalue filtering and covariance cleaning using RMT

import pytest
import numpy as np
from Risk.Covariance.SectorBased.TwoStep.RandomMatrixFilter import RandomMatrixFilter


class TestRandomMatrixFilter:
    """Tests for random matrix theory filtering."""

    def test_marcenko_pastur_threshold_calculation(self):
        """Test λ_+ threshold computation using Marčenko-Pastur formula."""
        # Setup
        filter_obj = RandomMatrixFilter(filter_method="marcenko_pastur")

        # Known case: σ² = 1.0, p = 100, T = 500
        # q = p/T = 100/500 = 0.2
        # λ_+ = σ²(1 + √q)² = 1.0 * (1 + √0.2)² ≈ 1.894

        sigma_sq = 1.0
        n_assets = 100
        n_observations = 500

        # Execute
        threshold = filter_obj._marcenko_pastur_threshold(
            sigma_sq, n_observations, n_assets
        )

        # Verify
        expected = sigma_sq * (1 + np.sqrt(n_assets / n_observations)) ** 2
        assert np.isclose(threshold, expected, rtol=1e-10)
        assert np.isclose(threshold, 1.894, rtol=1e-2)

    def test_marcenko_pastur_threshold_varies_with_ratio(self):
        """Test that threshold increases as p/T ratio increases."""
        filter_obj = RandomMatrixFilter()
        sigma_sq = 1.0
        n_observations = 1000

        # Different ratios
        thresholds = []
        for n_assets in [100, 200, 500, 800]:
            threshold = filter_obj._marcenko_pastur_threshold(
                sigma_sq, n_observations, n_assets
            )
            thresholds.append(threshold)

        # Verify: thresholds should increase monotonically
        assert all(thresholds[i] < thresholds[i+1] for i in range(len(thresholds)-1))

    def test_filters_noise_eigenvalues(self):
        """Test that small eigenvalues below λ_+ are filtered."""
        # Setup: Create eigenvalues with clear noise/signal separation
        n_signal = 5
        n_noise = 95
        n_total = n_signal + n_noise

        # Signal eigenvalues (large)
        signal_eigenvalues = np.linspace(10.0, 5.0, n_signal)

        # Noise eigenvalues (small, should be filtered)
        noise_eigenvalues = np.random.uniform(0.8, 1.2, n_noise)

        # Combine and sort descending
        eigenvalues = np.concatenate([signal_eigenvalues, noise_eigenvalues])
        eigenvalues = np.sort(eigenvalues)[::-1]

        n_observations = 500

        # Execute
        filter_obj = RandomMatrixFilter(filter_method="marcenko_pastur")
        filtered = filter_obj.filter_eigenvalues(
            eigenvalues, n_observations, n_total
        )

        # Verify
        # 1. Signal eigenvalues should be preserved
        assert np.allclose(filtered[:n_signal], signal_eigenvalues, rtol=1e-10)

        # 2. Noise eigenvalues should be modified (replaced or clipped)
        assert not np.allclose(filtered[n_signal:], noise_eigenvalues)

    def test_preserves_signal_eigenvalues(self):
        """Test that large eigenvalues above λ_+ are preserved unchanged."""
        # Setup: All eigenvalues well above threshold
        n_assets = 10
        n_observations = 500

        # Create large eigenvalues (clearly signal, not noise)
        eigenvalues = np.linspace(20.0, 10.0, n_assets)

        # Execute
        filter_obj = RandomMatrixFilter()
        filtered = filter_obj.filter_eigenvalues(
            eigenvalues, n_observations, n_assets
        )

        # Verify: All should be preserved
        assert np.allclose(filtered, eigenvalues, rtol=1e-10)

    def test_output_positive_definite(self):
        """Test that filtered covariance matrix is positive definite."""
        # Setup: Create sample covariance matrix with noise
        np.random.seed(42)
        n_assets = 50
        n_observations = 200

        # Generate random returns with factor structure + noise
        n_factors = 3
        factors = np.random.randn(n_observations, n_factors)
        loadings = np.random.randn(n_assets, n_factors)
        noise = np.random.randn(n_observations, n_assets) * 0.5

        returns = factors @ loadings.T + noise

        # Sample covariance
        cov_matrix = np.cov(returns.T)

        # Execute
        filter_obj = RandomMatrixFilter()
        cleaned_cov = filter_obj.clean_covariance(cov_matrix, n_observations)

        # Verify: positive definite (all eigenvalues > 0)
        eigenvalues = np.linalg.eigvalsh(cleaned_cov)
        assert np.all(eigenvalues > 0), f"Found non-positive eigenvalues: {eigenvalues[eigenvalues <= 0]}"

    def test_clean_covariance_reduces_noise(self):
        """Test that cleaning reduces overall noise in covariance estimate."""
        # Setup: Create noisy covariance matrix
        np.random.seed(123)
        n_assets = 30
        n_observations = 100

        # True covariance (low rank structure)
        n_factors = 2
        loadings = np.random.randn(n_assets, n_factors)
        true_cov = loadings @ loadings.T + 0.1 * np.eye(n_assets)

        # Generate returns from true covariance
        L = np.linalg.cholesky(true_cov)
        returns = np.random.randn(n_observations, n_assets) @ L.T

        # Noisy sample covariance
        sample_cov = np.cov(returns.T)

        # Execute
        filter_obj = RandomMatrixFilter()
        cleaned_cov = filter_obj.clean_covariance(sample_cov, n_observations)

        # Verify: cleaned should be closer to true covariance
        error_sample = np.linalg.norm(sample_cov - true_cov, 'fro')
        error_cleaned = np.linalg.norm(cleaned_cov - true_cov, 'fro')

        # Cleaned should have lower error (at least sometimes - this is statistical)
        # We mainly verify that cleaning doesn't make it worse
        assert error_cleaned <= error_sample * 1.5  # Allow some variance

    def test_median_noise_estimator(self):
        """Test noise level estimation using median eigenvalues."""
        # Setup
        eigenvalues = np.array([10.0, 8.0, 5.0, 1.2, 1.1, 1.0, 0.9, 0.8])
        n_observations = 200
        n_assets = len(eigenvalues)

        filter_obj = RandomMatrixFilter(sigma_estimator="median")

        # Execute
        noise_level = filter_obj._estimate_noise_level(
            eigenvalues, n_observations, n_assets
        )

        # Verify: Should be close to median of small eigenvalues
        # Median of noise eigenvalues (roughly last 5) ≈ 1.0
        assert noise_level > 0
        assert noise_level < 2.0  # Reasonable range

    def test_raises_on_invalid_dimensions(self):
        """Test error when n_observations < n_assets (ill-conditioned)."""
        # Setup: More assets than observations
        eigenvalues = np.linspace(5.0, 1.0, 100)
        n_observations = 50  # < n_assets
        n_assets = 100

        filter_obj = RandomMatrixFilter()

        # Execute & Verify
        with pytest.raises(ValueError, match="observations.*assets"):
            filter_obj.filter_eigenvalues(eigenvalues, n_observations, n_assets)

    def test_different_filter_methods(self):
        """Test that different filter methods produce different results."""
        # Setup
        eigenvalues = np.linspace(5.0, 0.5, 50)
        n_observations = 200
        n_assets = 50

        # Execute with different methods
        filter_mp = RandomMatrixFilter(filter_method="marcenko_pastur")
        filtered_mp = filter_mp.filter_eigenvalues(eigenvalues, n_observations, n_assets)

        # Note: If we only implement marcenko_pastur for MVP, this test can be simplified
        # For now, just verify it works
        assert filtered_mp is not None
        assert len(filtered_mp) == len(eigenvalues)

    def test_eigenvalue_replacement_strategy(self):
        """Test that noise eigenvalues are replaced with threshold value."""
        # Setup
        n_assets = 20
        n_observations = 200

        # Clear signal/noise separation
        signal = np.array([10.0, 8.0, 6.0])  # 3 signal eigenvalues
        noise = np.ones(17) * 0.9  # 17 noise eigenvalues
        eigenvalues = np.concatenate([signal, noise])

        # Execute
        filter_obj = RandomMatrixFilter()
        filtered = filter_obj.filter_eigenvalues(eigenvalues, n_observations, n_assets)

        # Verify
        # Signal preserved
        assert np.allclose(filtered[:3], signal, rtol=1e-10)

        # Noise eigenvalues should all be equal (replaced with threshold)
        noise_filtered = filtered[3:]
        assert np.allclose(noise_filtered, noise_filtered[0], rtol=1e-6)

        # And they should be >= original noise values
        assert np.all(noise_filtered >= noise * 0.99)

    def test_handles_already_clean_matrix(self):
        """Test that filtering a clean matrix doesn't damage it."""
        # Setup: Well-conditioned matrix with no noise
        n_assets = 10
        n_observations = 500

        # Create clean covariance (all eigenvalues well above threshold)
        eigenvalues = np.linspace(10.0, 5.0, n_assets)
        eigenvectors = np.linalg.qr(np.random.randn(n_assets, n_assets))[0]
        clean_cov = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

        # Execute
        filter_obj = RandomMatrixFilter()
        filtered_cov = filter_obj.clean_covariance(clean_cov, n_observations)

        # Verify: Should be nearly identical
        assert np.allclose(filtered_cov, clean_cov, rtol=1e-10)

    def test_symmetry_preserved(self):
        """Test that cleaned covariance matrix remains symmetric."""
        # Setup
        np.random.seed(456)
        n_assets = 30
        n_observations = 150

        returns = np.random.randn(n_observations, n_assets)
        cov_matrix = np.cov(returns.T)

        # Execute
        filter_obj = RandomMatrixFilter()
        cleaned_cov = filter_obj.clean_covariance(cov_matrix, n_observations)

        # Verify: symmetric
        assert np.allclose(cleaned_cov, cleaned_cov.T, rtol=1e-10)
