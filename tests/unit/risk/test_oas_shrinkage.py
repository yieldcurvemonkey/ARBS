# ABOUTME: Tests for OAS (Oracle Approximating Shrinkage) covariance estimator
# ABOUTME: Validates integration with sklearn.covariance.OAS and mathematical properties
"""
Tests for OAShrinkage covariance estimator.

Tests cover:
1. Basic functionality (fit, get_covariance)
2. Mathematical properties (symmetric, PSD)
3. Edge cases (single asset, perfect correlation)
4. Comparison with sample covariance
5. Factory integration
"""

import pytest
import numpy as np
import pandas as pd

from Risk.Covariance.OAShrinkage import OAShrinkage, SKLEARN_AVAILABLE
from Risk.risk_model_factory import RiskModelFactory


# Skip all tests if sklearn not available
pytestmark = pytest.mark.skipif(
    not SKLEARN_AVAILABLE,
    reason="sklearn not available"
)


# =============================================================================
# Helper Functions
# =============================================================================

def is_symmetric(matrix: np.ndarray, tol: float = 1e-10) -> bool:
    """Check if matrix is symmetric."""
    return np.allclose(matrix, matrix.T, atol=tol)


def is_positive_semidefinite(matrix: np.ndarray, tol: float = 1e-10) -> bool:
    """Check if matrix is positive semi-definite."""
    eigenvalues = np.linalg.eigvalsh(matrix)
    return np.all(eigenvalues >= -tol)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def simple_returns():
    """Well-conditioned returns (T=100, N=5)."""
    np.random.seed(42)
    T, N = 100, 5
    returns = pd.DataFrame(
        np.random.randn(T, N) * 0.01,
        columns=[f"Asset_{i}" for i in range(N)]
    )
    return returns


@pytest.fixture
def small_sample_returns():
    """Ill-conditioned returns (T=30, N=25)."""
    np.random.seed(42)
    T, N = 30, 25
    returns = pd.DataFrame(
        np.random.randn(T, N) * 0.01,
        columns=[f"Asset_{i}" for i in range(N)]
    )
    return returns


# =============================================================================
# Test Class 1: Basic Functionality
# =============================================================================

class TestOASBasics:
    """Test basic OAS functionality."""

    def test_can_import(self):
        """Verify OAShrinkage can be imported."""
        assert OAShrinkage is not None
        assert SKLEARN_AVAILABLE is True

    def test_instantiation(self):
        """Verify OAS can be instantiated."""
        estimator = OAShrinkage()
        assert estimator is not None
        assert estimator.handle_missing == 'drop'
        assert estimator.store_precision is False

    def test_fit_returns_matrix(self, simple_returns):
        """Verify fit() returns covariance matrix."""
        estimator = OAShrinkage()
        cov = estimator.fit(simple_returns)

        assert isinstance(cov, np.ndarray)
        assert cov.shape == (5, 5)

    def test_get_covariance(self, simple_returns):
        """Verify get_covariance() works after fit."""
        estimator = OAShrinkage()
        estimator.fit(simple_returns)

        cov = estimator.get_covariance()
        assert isinstance(cov, np.ndarray)
        assert cov.shape == (5, 5)

    def test_get_covariance_before_fit_raises(self):
        """Verify get_covariance() raises before fit()."""
        estimator = OAShrinkage()
        with pytest.raises(ValueError, match="Must call fit"):
            estimator.get_covariance()


# =============================================================================
# Test Class 2: Mathematical Properties
# =============================================================================

class TestOASMathematicalProperties:
    """Test mathematical properties of OAS covariance."""

    def test_symmetry(self, simple_returns):
        """Verify covariance matrix is symmetric."""
        estimator = OAShrinkage()
        cov = estimator.fit(simple_returns)

        assert is_symmetric(cov), "Covariance matrix must be symmetric"

    def test_positive_semidefinite(self, simple_returns):
        """Verify covariance matrix is PSD."""
        estimator = OAShrinkage()
        cov = estimator.fit(simple_returns)

        assert is_positive_semidefinite(cov), "Covariance matrix must be PSD"

    def test_diagonal_positive(self, simple_returns):
        """Verify diagonal elements (variances) are positive."""
        estimator = OAShrinkage()
        cov = estimator.fit(simple_returns)

        diag = np.diag(cov)
        assert np.all(diag > 0), "Variances must be positive"

    def test_invertible(self, simple_returns):
        """Verify covariance matrix is invertible."""
        estimator = OAShrinkage()
        cov = estimator.fit(simple_returns)

        det = np.linalg.det(cov)
        assert abs(det) > 1e-10, "Matrix should be invertible"

    def test_condition_number_reasonable(self, simple_returns):
        """Verify condition number is reasonable (< 100)."""
        estimator = OAShrinkage()
        estimator.fit(simple_returns)

        cond = estimator.condition_number()
        assert cond < 100, f"Condition number too high: {cond}"


# =============================================================================
# Test Class 3: Edge Cases
# =============================================================================

class TestOASEdgeCases:
    """Test OAS edge case handling."""

    def test_single_asset(self):
        """Test with single asset."""
        returns = pd.DataFrame({'Asset_0': np.random.randn(100) * 0.01})

        estimator = OAShrinkage()
        cov = estimator.fit(returns)

        assert cov.shape == (1, 1)
        assert cov[0, 0] > 0

    def test_two_assets(self):
        """Test with two assets (minimum correlation case)."""
        returns = pd.DataFrame({
            'Asset_0': np.random.randn(100) * 0.01,
            'Asset_1': np.random.randn(100) * 0.01,
        })

        estimator = OAShrinkage()
        cov = estimator.fit(returns)

        assert cov.shape == (2, 2)
        assert is_symmetric(cov)
        assert is_positive_semidefinite(cov)

    def test_small_sample_size(self, small_sample_returns):
        """Test with T < N (where OAS shines)."""
        estimator = OAShrinkage()
        cov = estimator.fit(small_sample_returns)

        # Should still be well-conditioned
        cond = estimator.condition_number()
        assert cond < 1000, f"OAS should improve conditioning, got {cond}"


# =============================================================================
# Test Class 4: Shrinkage Properties
# =============================================================================

class TestOASShrinkageProperties:
    """Test OAS shrinkage coefficient properties."""

    def test_shrinkage_coefficient_exists(self, simple_returns):
        """Verify shrinkage coefficient is computed."""
        estimator = OAShrinkage()
        estimator.fit(simple_returns)

        rho = estimator.get_shrinkage_coefficient()
        assert rho is not None
        assert 0 <= rho <= 1, f"Shrinkage ρ must be in [0,1], got {rho}"

    def test_shrinkage_coefficient_before_fit_raises(self):
        """Verify get_shrinkage_coefficient() raises before fit."""
        estimator = OAShrinkage()
        with pytest.raises(ValueError, match="Must call fit"):
            estimator.get_shrinkage_coefficient()

    def test_higher_shrinkage_for_small_samples(self):
        """Verify OAS uses more shrinkage when T/N is small."""
        # Well-conditioned case (T >> N)
        returns_large = pd.DataFrame(
            np.random.randn(500, 5) * 0.01,
            columns=[f"Asset_{i}" for i in range(5)]
        )

        # Ill-conditioned case (T ≈ N)
        returns_small = pd.DataFrame(
            np.random.randn(30, 25) * 0.01,
            columns=[f"Asset_{i}" for i in range(25)]
        )

        est_large = OAShrinkage()
        est_large.fit(returns_large)
        rho_large = est_large.get_shrinkage_coefficient()

        est_small = OAShrinkage()
        est_small.fit(returns_small)
        rho_small = est_small.get_shrinkage_coefficient()

        # Small sample should have higher shrinkage
        assert rho_small > rho_large, \
            f"Expected higher shrinkage for small sample: {rho_small} vs {rho_large}"


# =============================================================================
# Test Class 5: Comparison with Sample Covariance
# =============================================================================

class TestOASComparison:
    """Test OAS vs sample covariance."""

    def test_reduces_condition_number(self, small_sample_returns):
        """Verify OAS reduces condition number vs sample covariance."""
        # Sample covariance
        sample_cov = small_sample_returns.cov().values
        cond_sample = np.linalg.cond(sample_cov)

        # OAS
        estimator = OAShrinkage()
        estimator.fit(small_sample_returns)
        cond_oas = estimator.condition_number()

        assert cond_oas < cond_sample, \
            f"OAS should reduce condition number: {cond_oas} vs {cond_sample}"

    def test_shrinkage_toward_diagonal(self, simple_returns):
        """Verify OAS shrinks toward scaled identity."""
        estimator = OAShrinkage()
        estimator.fit(simple_returns)

        # OAS shrinks toward (tr(S)/N) * I
        # So off-diagonal correlations should be reduced vs sample
        sample_corr = simple_returns.corr().values
        oas_corr = estimator.get_correlation()

        # Average absolute off-diagonal correlation
        n = len(sample_corr)
        mask = ~np.eye(n, dtype=bool)

        avg_corr_sample = np.mean(np.abs(sample_corr[mask]))
        avg_corr_oas = np.mean(np.abs(oas_corr[mask]))

        # OAS should reduce correlations
        assert avg_corr_oas <= avg_corr_sample + 0.01, \
            "OAS should shrink off-diagonal correlations"


# =============================================================================
# Test Class 6: Factory Integration
# =============================================================================

class TestOASFactoryIntegration:
    """Test OAS integration with RiskModelFactory."""

    def test_can_register_in_factory(self):
        """Verify OAS can be registered in factory."""
        factory = RiskModelFactory()
        factory.register('oas', OAShrinkage)

        assert 'oas' in factory.list_models()

    def test_can_create_from_factory(self):
        """Verify OAS can be instantiated from factory."""
        factory = RiskModelFactory()
        factory.register('oas', OAShrinkage)

        estimator = factory.create('oas')
        assert isinstance(estimator, OAShrinkage)

    def test_can_create_with_parameters(self):
        """Verify OAS can be created with parameters."""
        factory = RiskModelFactory()
        factory.register('oas', OAShrinkage)

        estimator = factory.create('oas', store_precision=True)
        assert estimator.store_precision is True

    def test_factory_usage_end_to_end(self, simple_returns):
        """Test complete factory workflow."""
        # Setup factory
        factory = RiskModelFactory()
        factory.register('oas', OAShrinkage)

        # Create and fit
        estimator = factory.create('oas')
        cov = estimator.fit(simple_returns)

        # Verify results
        assert cov.shape == (5, 5)
        assert is_symmetric(cov)
        assert is_positive_semidefinite(cov)


# =============================================================================
# Test Class 7: Precision Matrix
# =============================================================================

class TestOASPrecision:
    """Test OAS precision matrix functionality."""

    def test_precision_without_storage(self, simple_returns):
        """Test precision matrix without store_precision."""
        estimator = OAShrinkage(store_precision=False)
        estimator.fit(simple_returns)

        precision = estimator.get_precision()

        # Precision should be inverse of covariance
        cov = estimator.get_covariance()
        identity = precision @ cov

        assert np.allclose(identity, np.eye(5), atol=1e-6)

    def test_precision_with_storage(self, simple_returns):
        """Test precision matrix with store_precision=True."""
        estimator = OAShrinkage(store_precision=True)
        estimator.fit(simple_returns)

        precision = estimator.get_precision()

        # Verify it's the inverse
        cov = estimator.get_covariance()
        identity = precision @ cov

        assert np.allclose(identity, np.eye(5), atol=1e-6)


# =============================================================================
# Test Class 8: String Representation
# =============================================================================

class TestOASRepr:
    """Test string representation."""

    def test_repr_before_fit(self):
        """Test __repr__ before fitting."""
        estimator = OAShrinkage()
        repr_str = repr(estimator)

        assert 'OAShrinkage' in repr_str
        assert 'not fitted' in repr_str

    def test_repr_after_fit(self, simple_returns):
        """Test __repr__ after fitting."""
        estimator = OAShrinkage()
        estimator.fit(simple_returns)
        repr_str = repr(estimator)

        assert 'OAShrinkage' in repr_str
        assert 'ρ=' in repr_str
        # Shrinkage coefficient should be shown
        rho = estimator.get_shrinkage_coefficient()
        assert f"{rho:.4f}" in repr_str
