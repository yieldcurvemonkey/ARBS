# ABOUTME: Integration tests for risk model system ensuring backward compatibility and factory integration
# ABOUTME: Validates all 5 risk models produce valid covariance matrices and work with optimizer
"""
Risk Model Integration Tests

Comprehensive integration tests ensuring:
1. Backward compatibility - existing import patterns still work
2. Factory integration - factory creates models correctly
3. Model validation - all 5 models produce valid covariance matrices
4. Optimizer integration - models work with mean-variance optimizer

Test Coverage:
- Direct imports (backward compatibility)
- Module-level imports (backward compatibility)
- Factory creation for all 5 models
- Covariance matrix validation (symmetric, PD, invertible)
- Integration with MeanVarianceOptimizer
- Comparison across different risk models

Risk Models Tested:
1. SampleCovariance - baseline unbiased estimator
2. LedoitWolfShrinkage - shrinkage to constant correlation
3. ConstantCorrelationCovariance - equal correlation assumption
4. DiagonalCovariance - zero correlations (independent assets)
5. IdentityCovariance - unit variance, zero correlations
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date


# =============================================================================
# Test 1: Backward Compatibility - Direct Imports
# =============================================================================

class TestBackwardCompatibilityDirectImports:
    """Verify existing code patterns with direct imports still work."""

    def test_import_sample_covariance_directly(self):
        """Can import SampleCovariance from Risk.Covariance."""
        from Risk.Covariance import SampleCovariance

        assert SampleCovariance is not None
        model = SampleCovariance()
        assert model is not None

    def test_import_ledoit_wolf_directly(self):
        """Can import LedoitWolfShrinkage from Risk.Covariance."""
        from Risk.Covariance import LedoitWolfShrinkage

        assert LedoitWolfShrinkage is not None
        model = LedoitWolfShrinkage()
        assert model is not None

    def test_import_constant_correlation_directly(self):
        """Can import ConstantCorrelationCovariance from Risk.Covariance."""
        from Risk.Covariance import ConstantCorrelationCovariance

        assert ConstantCorrelationCovariance is not None
        model = ConstantCorrelationCovariance()
        assert model is not None

    def test_import_diagonal_directly(self):
        """Can import DiagonalCovariance from Risk.Covariance."""
        from Risk.Covariance import DiagonalCovariance

        assert DiagonalCovariance is not None
        model = DiagonalCovariance()
        assert model is not None

    def test_import_identity_directly(self):
        """Can import IdentityCovariance from Risk.Covariance."""
        from Risk.Covariance import IdentityCovariance

        assert IdentityCovariance is not None
        model = IdentityCovariance()
        assert model is not None

    def test_use_sample_covariance_directly(self):
        """Verify SampleCovariance works with direct import."""
        from Risk.Covariance import SampleCovariance

        # Create mock returns
        np.random.seed(42)
        returns = pd.DataFrame({
            'A': np.random.randn(60) * 0.02,
            'B': np.random.randn(60) * 0.03,
            'C': np.random.randn(60) * 0.025,
        })

        # Fit model
        model = SampleCovariance()
        cov_matrix = model.fit(returns)

        # Verify output
        assert isinstance(cov_matrix, np.ndarray)
        assert cov_matrix.shape == (3, 3)

    def test_use_ledoit_wolf_directly(self):
        """Verify LedoitWolfShrinkage works with direct import."""
        from Risk.Covariance import LedoitWolfShrinkage

        # Create mock returns
        np.random.seed(42)
        returns = pd.DataFrame({
            'A': np.random.randn(60) * 0.02,
            'B': np.random.randn(60) * 0.03,
            'C': np.random.randn(60) * 0.025,
        })

        # Fit model
        model = LedoitWolfShrinkage()
        cov_matrix = model.fit(returns)

        # Verify output
        assert isinstance(cov_matrix, np.ndarray)
        assert cov_matrix.shape == (3, 3)


# =============================================================================
# Test 2: Backward Compatibility - Module-level Imports
# =============================================================================

class TestBackwardCompatibilityModuleImports:
    """Verify imports from Risk module still work."""

    def test_import_from_risk_module(self):
        """Can import covariance estimators from Risk module."""
        from Risk import (
            SampleCovariance,
            LedoitWolfShrinkage,
            ConstantCorrelationCovariance,
            DiagonalCovariance,
            IdentityCovariance,
        )

        assert SampleCovariance is not None
        assert LedoitWolfShrinkage is not None
        assert ConstantCorrelationCovariance is not None
        assert DiagonalCovariance is not None
        assert IdentityCovariance is not None

    def test_instantiate_from_risk_module(self):
        """Can instantiate models imported from Risk module."""
        from Risk import SampleCovariance, LedoitWolfShrinkage

        sample_cov = SampleCovariance()
        lw_cov = LedoitWolfShrinkage()

        assert sample_cov is not None
        assert lw_cov is not None

    def test_use_models_from_risk_module(self):
        """Verify models from Risk module produce correct results."""
        from Risk import SampleCovariance, LedoitWolfShrinkage

        # Create mock returns with higher N/T ratio to trigger shrinkage
        np.random.seed(42)
        returns = pd.DataFrame({
            'A': np.random.randn(30) * 0.02,
            'B': np.random.randn(30) * 0.03,
            'C': np.random.randn(30) * 0.025,
            'D': np.random.randn(30) * 0.028,
        })

        # Fit both models
        sample_cov = SampleCovariance()
        lw_cov = LedoitWolfShrinkage()

        sample_matrix = sample_cov.fit(returns)
        lw_matrix = lw_cov.fit(returns)

        # Both should produce valid matrices
        assert sample_matrix.shape == (4, 4)
        assert lw_matrix.shape == (4, 4)

        # With N=4, T=30, shrinkage should be applied
        # If shrinkage intensity > 0, matrices should differ
        shrinkage_intensity = lw_cov.get_shrinkage_intensity()
        if shrinkage_intensity > 0.001:
            assert not np.allclose(sample_matrix, lw_matrix)


# =============================================================================
# Test 3: Factory Integration
# =============================================================================

class TestFactoryIntegration:
    """Verify factory correctly creates all risk models."""

    def test_import_risk_model_factory(self):
        """Can import pre-configured risk_model_factory."""
        from Risk import risk_model_factory

        assert risk_model_factory is not None

    def test_factory_has_all_five_models(self):
        """Factory has all 5 risk models registered."""
        from Risk import risk_model_factory

        available_models = risk_model_factory.list_models()

        assert 'sample' in available_models
        assert 'ledoit_wolf' in available_models
        assert 'constant_correlation' in available_models
        assert 'diagonal' in available_models
        assert 'identity' in available_models

    def test_factory_create_sample_covariance(self):
        """Factory can create SampleCovariance."""
        from Risk import risk_model_factory, SampleCovariance

        model = risk_model_factory.create('sample')

        assert isinstance(model, SampleCovariance)

    def test_factory_create_ledoit_wolf(self):
        """Factory can create LedoitWolfShrinkage."""
        from Risk import risk_model_factory, LedoitWolfShrinkage

        model = risk_model_factory.create('ledoit_wolf')

        assert isinstance(model, LedoitWolfShrinkage)

    def test_factory_create_constant_correlation(self):
        """Factory can create ConstantCorrelationCovariance."""
        from Risk import risk_model_factory, ConstantCorrelationCovariance

        model = risk_model_factory.create('constant_correlation')

        assert isinstance(model, ConstantCorrelationCovariance)

    def test_factory_create_diagonal(self):
        """Factory can create DiagonalCovariance."""
        from Risk import risk_model_factory, DiagonalCovariance

        model = risk_model_factory.create('diagonal')

        assert isinstance(model, DiagonalCovariance)

    def test_factory_create_identity(self):
        """Factory can create IdentityCovariance."""
        from Risk import risk_model_factory, IdentityCovariance

        model = risk_model_factory.create('identity')

        assert isinstance(model, IdentityCovariance)

    def test_factory_models_identical_to_direct_imports(self):
        """Factory-created models identical to direct imports."""
        from Risk import risk_model_factory
        from Risk import SampleCovariance, LedoitWolfShrinkage

        # Create via factory
        factory_sample = risk_model_factory.create('sample')
        factory_lw = risk_model_factory.create('ledoit_wolf')

        # Create via direct import
        direct_sample = SampleCovariance()
        direct_lw = LedoitWolfShrinkage()

        # Both should be same type
        assert type(factory_sample) == type(direct_sample)
        assert type(factory_lw) == type(direct_lw)

        # Both should produce identical results
        np.random.seed(42)
        returns = pd.DataFrame({
            'A': np.random.randn(60) * 0.02,
            'B': np.random.randn(60) * 0.03,
        })

        factory_cov = factory_sample.fit(returns.copy())
        direct_cov = direct_sample.fit(returns.copy())

        assert np.allclose(factory_cov, direct_cov)


# =============================================================================
# Test 4: All Models Validation - Valid Covariance Matrices
# =============================================================================

@pytest.fixture
def mock_returns():
    """Create mock returns for testing."""
    np.random.seed(42)
    return pd.DataFrame({
        'SFRZ4': np.random.randn(60) * 0.10 / np.sqrt(252),
        'SFRH5': np.random.randn(60) * 0.12 / np.sqrt(252),
        'SFRM5': np.random.randn(60) * 0.08 / np.sqrt(252),
        'SFRU5': np.random.randn(60) * 0.09 / np.sqrt(252),
    })


class TestAllModelsValidation:
    """Validate all 5 risk models produce valid covariance matrices."""

    def test_sample_covariance_produces_valid_matrix(self, mock_returns):
        """SampleCovariance produces valid covariance matrix."""
        from Risk import SampleCovariance

        model = SampleCovariance()
        cov = model.fit(mock_returns)

        # Square matrix
        n = len(mock_returns.columns)
        assert cov.shape == (n, n)

        # Symmetric
        assert np.allclose(cov, cov.T)

        # Positive definite (all eigenvalues > 0)
        eigenvalues = np.linalg.eigvals(cov)
        assert all(eigenvalues > 0)

        # Invertible
        cov_inv = np.linalg.inv(cov)
        assert cov_inv is not None

    def test_ledoit_wolf_produces_valid_matrix(self, mock_returns):
        """LedoitWolfShrinkage produces valid covariance matrix."""
        from Risk import LedoitWolfShrinkage

        model = LedoitWolfShrinkage()
        cov = model.fit(mock_returns)

        # Square matrix
        n = len(mock_returns.columns)
        assert cov.shape == (n, n)

        # Symmetric
        assert np.allclose(cov, cov.T)

        # Positive definite
        eigenvalues = np.linalg.eigvals(cov)
        assert all(eigenvalues > 0)

        # Invertible
        cov_inv = np.linalg.inv(cov)
        assert cov_inv is not None

    def test_constant_correlation_produces_valid_matrix(self, mock_returns):
        """ConstantCorrelationCovariance produces valid covariance matrix."""
        from Risk import ConstantCorrelationCovariance

        model = ConstantCorrelationCovariance()
        cov = model.fit(mock_returns)

        # Square matrix
        n = len(mock_returns.columns)
        assert cov.shape == (n, n)

        # Symmetric
        assert np.allclose(cov, cov.T)

        # Positive definite
        eigenvalues = np.linalg.eigvals(cov)
        assert all(eigenvalues > 0)

        # Invertible
        cov_inv = np.linalg.inv(cov)
        assert cov_inv is not None

    def test_diagonal_produces_valid_matrix(self, mock_returns):
        """DiagonalCovariance produces valid covariance matrix."""
        from Risk import DiagonalCovariance

        model = DiagonalCovariance()
        cov = model.fit(mock_returns)

        # Square matrix
        n = len(mock_returns.columns)
        assert cov.shape == (n, n)

        # Symmetric (diagonal is always symmetric)
        assert np.allclose(cov, cov.T)

        # Positive definite
        eigenvalues = np.linalg.eigvals(cov)
        assert all(eigenvalues > 0)

        # Invertible
        cov_inv = np.linalg.inv(cov)
        assert cov_inv is not None

        # Off-diagonal should be zero
        off_diagonal = cov - np.diag(np.diag(cov))
        assert np.allclose(off_diagonal, 0)

    def test_identity_produces_valid_matrix(self, mock_returns):
        """IdentityCovariance produces valid covariance matrix."""
        from Risk import IdentityCovariance

        model = IdentityCovariance()
        cov = model.fit(mock_returns)

        # Square matrix
        n = len(mock_returns.columns)
        assert cov.shape == (n, n)

        # Symmetric
        assert np.allclose(cov, cov.T)

        # Positive definite
        eigenvalues = np.linalg.eigvals(cov)
        assert all(eigenvalues > 0)

        # Invertible
        cov_inv = np.linalg.inv(cov)
        assert cov_inv is not None

        # Should be scaled identity matrix (diagonal with equal values)
        # Σ = σ² × I where σ² = mean(var(returns))
        off_diagonal = cov - np.diag(np.diag(cov))
        assert np.allclose(off_diagonal, 0)  # Off-diagonal should be zero

        # All diagonal elements should be equal
        diagonal_values = np.diag(cov)
        assert np.allclose(diagonal_values, diagonal_values[0])

    def test_all_five_models_via_factory(self, mock_returns):
        """All 5 models via factory produce valid covariance matrices."""
        from Risk import risk_model_factory

        model_names = ['sample', 'ledoit_wolf', 'constant_correlation', 'diagonal', 'identity']

        for name in model_names:
            model = risk_model_factory.create(name)
            cov = model.fit(mock_returns.copy())

            # Valid shape
            n = len(mock_returns.columns)
            assert cov.shape == (n, n), f"{name} failed shape test"

            # Symmetric
            assert np.allclose(cov, cov.T), f"{name} failed symmetry test"

            # Positive definite
            eigenvalues = np.linalg.eigvals(cov)
            assert all(eigenvalues > 0), f"{name} failed PD test"

            # Invertible
            cov_inv = np.linalg.inv(cov)
            assert cov_inv is not None, f"{name} failed invertibility test"


# =============================================================================
# Test 5: Model Comparison - Different Correlation Structures
# =============================================================================

class TestModelComparison:
    """Compare outputs across different risk models."""

    def test_models_differ_in_correlation_structure(self, mock_returns):
        """Different models produce different correlation structures."""
        from Risk import (
            SampleCovariance,
            ConstantCorrelationCovariance,
            DiagonalCovariance,
        )

        # Fit all models
        sample = SampleCovariance().fit(mock_returns)
        const_corr = ConstantCorrelationCovariance().fit(mock_returns)
        diagonal = DiagonalCovariance().fit(mock_returns)

        # Convert to correlation matrices
        def cov_to_corr(cov):
            std = np.sqrt(np.diag(cov))
            return cov / np.outer(std, std)

        sample_corr = cov_to_corr(sample)
        const_corr_corr = cov_to_corr(const_corr)
        diagonal_corr = cov_to_corr(diagonal)

        # Constant correlation should have equal off-diagonals
        off_diag_values = const_corr_corr[np.triu_indices(4, k=1)]
        assert np.allclose(off_diag_values, off_diag_values[0])

        # Diagonal should have zero off-diagonals
        diagonal_off_diag = diagonal_corr - np.eye(4)
        assert np.allclose(diagonal_off_diag, 0)

        # Sample and constant correlation should differ
        assert not np.allclose(sample_corr, const_corr_corr)

        # Sample and diagonal should differ
        assert not np.allclose(sample_corr, diagonal_corr)

    def test_condition_numbers_vary_by_model(self, mock_returns):
        """Condition numbers differ across models (stability measure)."""
        from Risk import (
            SampleCovariance,
            DiagonalCovariance,
            IdentityCovariance,
        )

        # Fit models
        sample = SampleCovariance()
        diagonal = DiagonalCovariance()
        identity = IdentityCovariance()

        sample.fit(mock_returns)
        diagonal.fit(mock_returns)
        identity.fit(mock_returns)

        # Get condition numbers
        sample_cond = sample.condition_number()
        diagonal_cond = diagonal.condition_number()
        identity_cond = identity.condition_number()

        # All should be finite and positive
        assert sample_cond > 0 and np.isfinite(sample_cond)
        assert diagonal_cond > 0 and np.isfinite(diagonal_cond)
        assert identity_cond > 0 and np.isfinite(identity_cond)

        # Identity should have condition number = 1.0 (perfectly conditioned)
        assert np.isclose(identity_cond, 1.0)

        # Diagonal should have better condition than sample (no off-diagonal noise)
        assert diagonal_cond <= sample_cond


# =============================================================================
# Test 6: Integration with MeanVarianceOptimizer
# =============================================================================

class TestOptimizerIntegration:
    """Test risk models work with MeanVarianceOptimizer."""

    def test_sample_covariance_with_optimizer(self, mock_returns):
        """SampleCovariance works with optimizer."""
        from Risk import SampleCovariance
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Fit covariance
        risk_model = SampleCovariance()
        cov_matrix = risk_model.fit(mock_returns)

        # Create DataFrame for optimizer
        cov_df = pd.DataFrame(
            cov_matrix,
            index=mock_returns.columns,
            columns=mock_returns.columns
        )

        # Create alphas (mock signals)
        alphas = pd.Series([0.01, -0.005, 0.008, 0.002], index=mock_returns.columns)

        # Optimize
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        weights = optimizer.optimize(alphas, cov_df)

        # Verify valid weights
        assert len(weights) == len(mock_returns.columns)
        assert np.isclose(weights.sum(), 1.0)  # Budget constraint
        assert all(weights >= 0)  # Long-only

    def test_ledoit_wolf_with_optimizer(self, mock_returns):
        """LedoitWolfShrinkage works with optimizer."""
        from Risk import LedoitWolfShrinkage
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Fit covariance
        risk_model = LedoitWolfShrinkage()
        cov_matrix = risk_model.fit(mock_returns)

        # Create DataFrame
        cov_df = pd.DataFrame(
            cov_matrix,
            index=mock_returns.columns,
            columns=mock_returns.columns
        )

        # Create alphas
        alphas = pd.Series([0.01, -0.005, 0.008, 0.002], index=mock_returns.columns)

        # Optimize
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
        weights = optimizer.optimize(alphas, cov_df)

        # Verify valid weights
        assert len(weights) == len(mock_returns.columns)
        assert np.isclose(weights.sum(), 1.0)
        assert all(weights >= 0)

    def test_all_five_models_with_optimizer(self, mock_returns):
        """All 5 risk models work with optimizer."""
        from Risk import risk_model_factory
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        model_names = ['sample', 'ledoit_wolf', 'constant_correlation', 'diagonal', 'identity']
        alphas = pd.Series([0.01, -0.005, 0.008, 0.002], index=mock_returns.columns)

        for name in model_names:
            # Fit covariance
            model = risk_model_factory.create(name)
            cov_matrix = model.fit(mock_returns.copy())

            # Create DataFrame
            cov_df = pd.DataFrame(
                cov_matrix,
                index=mock_returns.columns,
                columns=mock_returns.columns
            )

            # Optimize
            optimizer = MeanVarianceOptimizer(risk_aversion=1.0, long_only=True)
            weights = optimizer.optimize(alphas, cov_df)

            # Verify valid weights
            assert len(weights) == len(mock_returns.columns), f"{name} failed"
            assert np.isclose(weights.sum(), 1.0), f"{name} failed budget constraint"
            assert all(weights >= 0), f"{name} failed long-only constraint"

    def test_different_models_produce_different_weights(self):
        """Different risk models produce different optimal weights."""
        from Risk import SampleCovariance, DiagonalCovariance
        from Optimizer.MeanVarianceOptimizer import MeanVarianceOptimizer

        # Create returns with positive correlation structure
        np.random.seed(123)
        T = 60
        factor = np.random.randn(T) * 0.01  # Common factor
        idiosync = np.random.randn(T, 4) * 0.005  # Idiosyncratic noise

        # Assets with positive correlation via common factor
        returns = pd.DataFrame({
            'A': factor + idiosync[:, 0],
            'B': factor + idiosync[:, 1],
            'C': factor + idiosync[:, 2],
            'D': factor + idiosync[:, 3],
        })

        # Balanced alphas (not dominated by single asset)
        alphas = pd.Series([0.003, 0.0025, 0.0028, 0.0027], index=returns.columns)

        # Optimize with SampleCovariance (captures correlations)
        sample_model = SampleCovariance()
        sample_cov = sample_model.fit(returns)
        sample_cov_df = pd.DataFrame(
            sample_cov,
            index=returns.columns,
            columns=returns.columns
        )
        optimizer = MeanVarianceOptimizer(risk_aversion=2.0, long_only=True)
        sample_weights = optimizer.optimize(alphas, sample_cov_df)

        # Optimize with DiagonalCovariance (ignores correlations)
        diagonal_model = DiagonalCovariance()
        diagonal_cov = diagonal_model.fit(returns)
        diagonal_cov_df = pd.DataFrame(
            diagonal_cov,
            index=returns.columns,
            columns=returns.columns
        )
        diagonal_weights = optimizer.optimize(alphas, diagonal_cov_df)

        # With correlation structure and balanced alphas, weights should differ
        # Diagonal ignores correlation → may over-diversify
        # Sample considers correlation → may concentrate more
        max_diff = np.max(np.abs(sample_weights.values - diagonal_weights.values))
        assert max_diff > 0.01  # At least 1% difference in some weight


# =============================================================================
# Test 7: No Breaking Changes to Existing API
# =============================================================================

class TestNoBreakingChanges:
    """Verify no breaking changes to existing API."""

    def test_fit_returns_numpy_array(self, mock_returns):
        """fit() returns numpy array (not DataFrame)."""
        from Risk import SampleCovariance

        model = SampleCovariance()
        result = model.fit(mock_returns)

        assert isinstance(result, np.ndarray)
        assert not isinstance(result, pd.DataFrame)

    def test_get_covariance_method_exists(self, mock_returns):
        """get_covariance() method still exists."""
        from Risk import SampleCovariance

        model = SampleCovariance()
        model.fit(mock_returns)

        cov = model.get_covariance()
        assert isinstance(cov, np.ndarray)

    def test_condition_number_method_exists(self, mock_returns):
        """condition_number() method still exists."""
        from Risk import SampleCovariance

        model = SampleCovariance()
        model.fit(mock_returns)

        cond_num = model.condition_number()
        assert isinstance(cond_num, float)
        assert cond_num > 0

    def test_compare_estimators_function_exists(self):
        """compare_estimators() utility function still exists."""
        from Risk.Covariance import compare_estimators

        assert compare_estimators is not None
        assert callable(compare_estimators)
