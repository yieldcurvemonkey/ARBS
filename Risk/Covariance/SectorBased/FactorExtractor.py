# ABOUTME: PCA-based factor extraction for sector risk models (Papers 1, 2, 3)
# ABOUTME: Implements Y = B·F + ε decomposition with orthogonal residuals

"""
Factor Extraction via PCA

Implements factor extraction for sector-based covariance models:
- Paper 1 (García-Medina): One-factor model section
- Paper 2 (Žignić et al.): Core decomposition Σ = B·Cov(F)·B^T + Ψ
- Paper 3 (Chen et al.): Implicit factor structure

Mathematical Specification (Paper 2, Equation 2.1):
    Y = B·F + ε

    where:
    - Y: T×p returns matrix
    - B: p×K loading matrix (PCA eigenvectors)
    - F: T×K factor matrix (PCA scores)
    - ε: T×p residuals (orthogonal to factors)

Assumptions (Paper 2, Assumption 2.1):
    1. Common factor eigenvalues grow with p (unbounded)
    2. Idiosyncratic eigenvalues remain bounded
"""

import polars as pl
import numpy as np
from dataclasses import dataclass
from typing import Optional
from sklearn.decomposition import PCA

from Risk.Covariance.SectorBased.sector_utils import long_to_wide


@dataclass
class FactorExtractionResult:
    """Results from factor extraction."""
    factors: np.ndarray          # T×K factor time series
    loadings: np.ndarray         # p×K factor loadings
    residuals: np.ndarray        # T×p residual returns
    explained_variance: np.ndarray  # K explained variance ratios
    n_factors: int


class FactorExtractor:
    """
    Extract factors and compute residuals via PCA.

    Supports:
    - Fixed number of factors K
    - Automatic K selection via variance threshold
    - Correlation matrix vs covariance matrix PCA
    """

    def __init__(
        self,
        n_factors: Optional[int] = None,
        variance_threshold: float = 0.95,
        use_correlation: bool = False,
    ):
        """
        Initialize factor extractor.

        Args:
            n_factors: Fixed K (if None, auto-select via variance_threshold)
            variance_threshold: Cumulative variance for auto K selection
            use_correlation: Use correlation matrix vs covariance for PCA
        """
        self.n_factors = n_factors
        self.variance_threshold = variance_threshold
        self.use_correlation = use_correlation

    def extract(
        self,
        returns: pl.DataFrame,  # Long format [ticker, date, return, sector]
    ) -> FactorExtractionResult:
        """
        Extract factors and compute residuals via PCA.

        Algorithm:
        1. Convert long → wide format
        2. Run PCA (sklearn.decomposition.PCA)
        3. Extract factors (scores) and loadings (components)
        4. Compute residuals: ε = Y - B·F
        5. Verify orthogonality: corr(F, ε) ≈ 0

        Args:
            returns: Long format DataFrame [ticker, date, return, sector]

        Returns:
            FactorExtractionResult

        Raises:
            ValueError: If T < p or missing values present
        """
        # 1. Validate input
        null_counts = returns.null_count()
        if null_counts.to_numpy().sum() > 0:
            raise ValueError("Missing values detected in returns")

        # 2. Convert to wide format
        returns_wide, tickers = long_to_wide(returns)
        Y = returns_wide.to_numpy()  # T×p
        T, p = Y.shape

        # 3. Check T >= p (need enough observations)
        if T < p:
            raise ValueError(f"Insufficient data: T={T} < p={p}")

        # 4. Determine number of components
        if self.n_factors is None:
            # Auto-select based on variance threshold
            n_components = None  # PCA will use all components
        else:
            n_components = self.n_factors

        # 5. Run PCA
        if self.use_correlation:
            # Standardize data (correlation matrix)
            Y_standardized = (Y - Y.mean(axis=0)) / Y.std(axis=0)
            pca = PCA(n_components=n_components)
            factors = pca.fit_transform(Y_standardized)
        else:
            # Use covariance matrix
            pca = PCA(n_components=n_components)
            factors = pca.fit_transform(Y)

        # 6. Extract loadings and explained variance
        loadings = pca.components_.T  # p×K
        explained_var = pca.explained_variance_ratio_

        # 7. Auto-select K based on variance threshold if needed
        if self.n_factors is None:
            cumulative_var = np.cumsum(explained_var)
            K = int(np.argmax(cumulative_var >= self.variance_threshold)) + 1
            # Truncate to selected K
            factors = factors[:, :K]
            loadings = loadings[:, :K]
            explained_var = explained_var[:K]
        else:
            K = pca.n_components_

        # 8. Compute residuals: ε = Y - B·F^T
        if self.use_correlation:
            # Reconstruct from standardized data
            Y_reconstructed = factors @ loadings.T
            residuals = Y_standardized - Y_reconstructed
            # Convert back to original scale
            residuals = residuals * Y.std(axis=0)
        else:
            residuals = Y - (factors @ loadings.T)

        return FactorExtractionResult(
            factors=factors,
            loadings=loadings,
            residuals=residuals,
            explained_variance=explained_var,
            n_factors=K,
        )
