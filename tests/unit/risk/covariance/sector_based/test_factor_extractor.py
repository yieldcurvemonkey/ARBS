# ABOUTME: Tests for FactorExtractor (PCA-based factor extraction for sector risk models)
# ABOUTME: Validates factor extraction, residual orthogonality, and edge cases

import pytest
import polars as pl
import numpy as np
from datetime import date, timedelta

from Risk.Covariance.SectorBased.FactorExtractor import (
    FactorExtractor,
    FactorExtractionResult,
)


class TestFactorExtractor:
    """Test suite for FactorExtractor (PCA-based factor extraction)."""

    def test_extract_factors_with_fixed_k(self):
        """
        Test 1: Verify PCA extraction with specified number of factors.

        Creates synthetic data with known factor structure and verifies:
        - Correct shapes for factors (T×K), loadings (p×K), residuals (T×p)
        - n_factors matches requested K
        - Explained variance ratios are valid [0, 1]
        """
        # Create synthetic data with known factor structure
        np.random.seed(42)
        T, p, K = 100, 3, 2

        # True factors and loadings
        true_factors = np.random.randn(T, K)
        true_loadings = np.random.randn(p, K)
        noise = np.random.randn(T, p) * 0.1

        # Generate returns: Y = B·F + ε
        returns_matrix = true_factors @ true_loadings.T + noise

        # Convert to long format DataFrame
        tickers = ["AAPL", "MSFT", "GOOGL"]
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        df = pl.DataFrame({
            "ticker": np.repeat(tickers, T),
            "date": dates * p,
            "return": returns_matrix.T.flatten(),
            "sector": np.repeat(["Technology"], T * p),
        })

        # Execute
        extractor = FactorExtractor(n_factors=2)
        result = extractor.extract(df)

        # Verify
        assert isinstance(result, FactorExtractionResult)
        assert result.factors.shape == (T, K), f"Expected {(T, K)}, got {result.factors.shape}"
        assert result.loadings.shape == (p, K), f"Expected {(p, K)}, got {result.loadings.shape}"
        assert result.residuals.shape == (T, p)
        assert result.n_factors == K
        assert len(result.explained_variance) == K
        assert np.all(result.explained_variance >= 0)
        assert np.all(result.explained_variance <= 1)

    def test_extract_factors_with_variance_threshold(self):
        """
        Test 2: Verify automatic K selection via variance threshold.

        Creates data with strong first principal component (>90% variance) and
        verifies automatic selection of K based on cumulative variance threshold.
        """
        np.random.seed(42)
        T, p = 200, 5

        # Create data with strong first principal component
        common_factor = np.random.randn(T, 1)
        loadings = np.ones((p, 1)) * 2.0  # Strong loading
        noise = np.random.randn(T, p) * 0.1

        returns_matrix = common_factor @ loadings.T + noise

        tickers = ["A", "B", "C", "D", "E"]
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        df = pl.DataFrame({
            "ticker": np.repeat(tickers, T),
            "date": dates * p,
            "return": returns_matrix.T.flatten(),
            "sector": np.repeat(["Tech"], T * p),
        })

        # Execute
        extractor = FactorExtractor(variance_threshold=0.90)
        result = extractor.extract(df)

        # Verify: Should select at least 1 factor (explains >90%)
        assert result.n_factors >= 1, "Should select at least 1 factor"
        assert np.sum(result.explained_variance) >= 0.90, \
            f"Expected ≥90% variance explained, got {np.sum(result.explained_variance):.2%}"

    def test_residuals_orthogonal_to_factors(self):
        """
        Test 3: Verify residuals are orthogonal to factors (mathematical property of PCA).

        Computes correlation between factors and residuals and verifies
        it's approximately zero (within numerical precision 1e-10).
        """
        # Create synthetic data
        np.random.seed(42)
        T, p, K = 100, 3, 2

        true_factors = np.random.randn(T, K)
        true_loadings = np.random.randn(p, K)
        noise = np.random.randn(T, p) * 0.1

        returns_matrix = true_factors @ true_loadings.T + noise

        tickers = ["AAPL", "MSFT", "GOOGL"]
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        df = pl.DataFrame({
            "ticker": np.repeat(tickers, T),
            "date": dates * p,
            "return": returns_matrix.T.flatten(),
            "sector": np.repeat(["Technology"], T * p),
        })

        # Execute
        extractor = FactorExtractor(n_factors=2)
        result = extractor.extract(df)

        # Compute correlation between factors and residuals
        # factors: T×K, residuals: T×p → combined: T×(K+p)
        combined = np.hstack([result.factors, result.residuals])
        correlation = np.corrcoef(combined.T)

        # Extract factor-residual cross-correlations
        K = result.n_factors
        p = result.residuals.shape[1]
        factor_residual_corr = correlation[:K, K:]

        # Verify orthogonality
        assert np.allclose(factor_residual_corr, 0, atol=1e-10), \
            f"Residuals not orthogonal to factors: max corr = {np.abs(factor_residual_corr).max()}"

    def test_correlation_vs_covariance(self):
        """
        Test 4: Verify different results when using correlation vs covariance matrix.

        Creates data with heterogeneous volatilities and verifies:
        - Correlation-based PCA yields different loadings than covariance-based
        - High-vol asset dominates covariance PCA
        - Correlation PCA gives more balanced loadings
        """
        # Create data with heterogeneous volatilities
        np.random.seed(42)
        T = 150

        # Asset 1: low vol (σ=0.1)
        # Asset 2: high vol (σ=2.0)
        # Both driven by same factor
        factor = np.random.randn(T, 1)
        returns_matrix = np.column_stack([
            factor * 0.1 + np.random.randn(T, 1) * 0.05,  # Low vol
            factor * 2.0 + np.random.randn(T, 1) * 0.1,   # High vol
        ])

        tickers = ["LOW_VOL", "HIGH_VOL"]
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        df = pl.DataFrame({
            "ticker": np.repeat(tickers, T),
            "date": dates * 2,
            "return": returns_matrix.T.flatten(),
            "sector": np.repeat(["Mixed"], T * 2),
        })

        # Execute
        extractor_cov = FactorExtractor(n_factors=1, use_correlation=False)
        extractor_corr = FactorExtractor(n_factors=1, use_correlation=True)

        result_cov = extractor_cov.extract(df)
        result_corr = extractor_corr.extract(df)

        # Verify: Loadings should differ significantly
        assert not np.allclose(result_cov.loadings, result_corr.loadings), \
            "Correlation vs covariance PCA should yield different loadings"

        # High-vol asset should dominate covariance-based PCA
        assert np.abs(result_cov.loadings[1, 0]) > np.abs(result_cov.loadings[0, 0]), \
            "High-vol asset should have larger loading in covariance PCA"

        # Correlation-based PCA should give more balanced loadings
        loading_ratio_cov = np.abs(result_cov.loadings[1, 0]) / np.abs(result_cov.loadings[0, 0])
        loading_ratio_corr = np.abs(result_corr.loadings[1, 0]) / np.abs(result_corr.loadings[0, 0])
        assert loading_ratio_corr < loading_ratio_cov, \
            "Correlation PCA should have more balanced loadings"

    def test_raises_on_insufficient_data(self):
        """
        Test 5: Verify error when T < p (underdetermined system).

        Creates data with more assets than observations and verifies
        ValueError is raised with appropriate message.
        """
        # More assets than observations (ill-posed problem)
        T, p = 50, 100

        tickers = [f"STOCK_{i}" for i in range(p)]
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        df = pl.DataFrame({
            "ticker": np.repeat(tickers, T),
            "date": dates * p,
            "return": np.random.randn(T * p),
            "sector": np.repeat(["Tech"], T * p),
        })

        # Execute & Verify
        extractor = FactorExtractor(n_factors=10)

        with pytest.raises(ValueError, match="Insufficient data"):
            extractor.extract(df)

    def test_handles_missing_values(self):
        """
        Test 6: Verify clear error message when NaN present in data.

        Creates DataFrame with missing values and verifies ValueError
        is raised with clear message about missing data.
        """
        T = 100
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(T)]

        # Create DataFrame with correct shapes
        tickers = ["AAPL"] * T + ["MSFT"] * T
        all_dates = dates + dates

        df = pl.DataFrame({
            "ticker": tickers,
            "date": all_dates,
            "return": np.random.randn(T * 2),
            "sector": ["Technology"] * (T * 2),
        })

        # Introduce missing values
        df = df.with_columns(
            pl.when(pl.col("ticker") == "AAPL")
              .then(None)
              .otherwise(pl.col("return"))
              .alias("return")
        )

        # Execute & Verify
        extractor = FactorExtractor(n_factors=1)

        with pytest.raises(ValueError, match="Missing values"):
            extractor.extract(df)
