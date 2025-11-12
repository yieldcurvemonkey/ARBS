# Sector Risk Models - Implementation Plan for ARBS

**Date**: 2025-11-12
**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
**Papers**: García-Medina (2024), Žignić et al. (2024), Chen et al. (2025)
**Status**: Ready for TDD Implementation

---

## Overview

This document provides a detailed, step-by-step implementation plan for integrating sector-based risk models into the ARBS framework. All implementations will follow **strict TDD** (Test-Driven Development) methodology.

---

## Architecture Integration

### **Current ARBS Risk Layer**

```
Risk/
├── __init__.py
├── SampleCovariance.py          # ✅ Existing (baseline)
└── LedoitWolfShrinkage.py       # ✅ Existing (full matrix shrinkage)
```

### **Proposed Extension**

```
Risk/
├── __init__.py
├── SampleCovariance.py          # ✅ Existing
├── LedoitWolfShrinkage.py       # ✅ Existing
├── BlockDiagonal/               # 🆕 Phase 1 (5-8 hours)
│   ├── __init__.py
│   ├── BlockDiagonalCovariance.py
│   ├── HierarchicalSectorClustering.py
│   └── FactorExtractor.py
├── TwoStep/                     # 🆕 Phase 2 (4-6 hours)
│   ├── __init__.py
│   ├── TwoStepCovariance.py
│   └── RandomMatrixFilter.py
└── StochasticBlock/             # 🆕 Phase 3 (Optional, 8-12 hours)
    ├── __init__.py
    └── StochasticBlockCovariance.py
```

### **Test Structure**

```
tests/unit/risk/
├── test_sample_covariance.py         # ✅ Existing
├── test_ledoit_wolf_shrinkage.py     # ✅ Existing
├── block_diagonal/                    # 🆕 Phase 1
│   ├── test_block_diagonal_covariance.py
│   ├── test_hierarchical_sector_clustering.py
│   └── test_factor_extractor.py
├── two_step/                          # 🆕 Phase 2
│   ├── test_two_step_covariance.py
│   └── test_random_matrix_filter.py
└── stochastic_block/                  # 🆕 Phase 3
    └── test_stochastic_block_covariance.py
```

---

## Phase 1: Block-Diagonal Covariance (Priority 1)

**Goal**: Implement sector-based block-diagonal factor model from Žignić et al. (2024).

**Estimated Time**: 5-8 hours

---

### Component 1.1: FactorExtractor

**Purpose**: Extract common factors using PCA and compute residuals.

**File**: `Risk/BlockDiagonal/FactorExtractor.py`

**API Design**:

```python
# ABOUTME: Extracts common factors from returns using PCA
# ABOUTME: Computes residuals for block-diagonal covariance estimation

from dataclasses import dataclass
import polars as pl
import numpy as np
from typing import Optional, Tuple


@dataclass
class FactorExtractionResult:
    """Results from factor extraction."""

    factors: np.ndarray  # T×K factor time series
    loadings: np.ndarray  # p×K factor loadings
    residuals: np.ndarray  # T×p residual returns
    explained_variance: np.ndarray  # K explained variance ratios
    n_factors: int


class FactorExtractor:
    """
    Extracts common factors from asset returns using PCA.

    Based on Žignić et al. (2024) factor model:
        Y = B·F + ε

    Where:
        Y: T×p returns matrix
        B: p×K loading matrix
        F: T×K factor matrix
        ε: T×p residuals
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
            n_factors: Number of factors to extract (if None, use variance_threshold)
            variance_threshold: Cumulative variance explained threshold (default: 0.95)
            use_correlation: If True, use correlation matrix; if False, use covariance
        """
        self.n_factors = n_factors
        self.variance_threshold = variance_threshold
        self.use_correlation = use_correlation

    def extract(
        self,
        returns: pl.DataFrame,
        return_col: str = "return",
    ) -> FactorExtractionResult:
        """
        Extract factors and compute residuals.

        Args:
            returns: DataFrame with columns [ticker, date, return]
                     Must be in wide format (pivoted)
            return_col: Name of return column

        Returns:
            FactorExtractionResult with factors, loadings, residuals

        Raises:
            ValueError: If returns not in wide format or insufficient data
        """
        pass  # Implementation in TDD
```

**Test Specification** (`tests/unit/risk/block_diagonal/test_factor_extractor.py`):

```python
import pytest
import polars as pl
import numpy as np
from Risk.BlockDiagonal.FactorExtractor import FactorExtractor, FactorExtractionResult


class TestFactorExtractor:
    """Tests for FactorExtractor."""

    def test_extract_factors_with_fixed_k(self):
        """Test factor extraction with fixed number of factors."""
        # Setup: 3 assets, 100 days, 2 factors
        np.random.seed(42)
        factors = np.random.randn(100, 2)  # T×K
        loadings = np.random.randn(3, 2)  # p×K
        noise = np.random.randn(100, 3) * 0.1
        returns_matrix = factors @ loadings.T + noise  # T×p

        df = pl.DataFrame({
            "date": pl.date_range(start=pl.date(2024, 1, 1), periods=100, eager=True).repeat_by(3),
            "ticker": (["AAPL", "MSFT", "GOOGL"] * 100),
            "return": returns_matrix.flatten(order='F'),
        })

        # Execute
        extractor = FactorExtractor(n_factors=2)
        result = extractor.extract(df)

        # Verify
        assert isinstance(result, FactorExtractionResult)
        assert result.factors.shape == (100, 2)
        assert result.loadings.shape == (3, 2)
        assert result.residuals.shape == (100, 3)
        assert result.n_factors == 2
        assert len(result.explained_variance) == 2

    def test_extract_factors_with_variance_threshold(self):
        """Test automatic factor selection via variance threshold."""
        # Setup: 5 assets with strong first principal component
        np.random.seed(42)
        common_factor = np.random.randn(200, 1)
        loadings = np.ones((5, 1)) * 2.0  # Strong loading
        noise = np.random.randn(200, 5) * 0.1
        returns_matrix = common_factor @ loadings.T + noise

        df = pl.DataFrame({
            "date": pl.date_range(start=pl.date(2024, 1, 1), periods=200, eager=True).repeat_by(5),
            "ticker": (["A", "B", "C", "D", "E"] * 200),
            "return": returns_matrix.flatten(order='F'),
        })

        # Execute
        extractor = FactorExtractor(variance_threshold=0.90)
        result = extractor.extract(df)

        # Verify: Should select 1 factor (explains >90%)
        assert result.n_factors >= 1
        assert np.sum(result.explained_variance) >= 0.90

    def test_residuals_orthogonal_to_factors(self):
        """Test that residuals are orthogonal to extracted factors."""
        # Setup
        df = _create_synthetic_returns(n_assets=4, n_days=150, n_factors=2)

        # Execute
        extractor = FactorExtractor(n_factors=2)
        result = extractor.extract(df)

        # Verify: Residuals should be uncorrelated with factors
        correlation = np.corrcoef(result.factors.T, result.residuals.T)[:2, 2:]
        assert np.allclose(correlation, 0, atol=1e-6)

    def test_correlation_vs_covariance(self):
        """Test difference between correlation and covariance-based PCA."""
        # Setup: Assets with very different volatilities
        df = _create_returns_with_heterogeneous_vol()

        # Execute
        extractor_cov = FactorExtractor(n_factors=2, use_correlation=False)
        extractor_corr = FactorExtractor(n_factors=2, use_correlation=True)

        result_cov = extractor_cov.extract(df)
        result_corr = extractor_corr.extract(df)

        # Verify: Loadings should differ significantly
        assert not np.allclose(result_cov.loadings, result_corr.loadings)

    def test_raises_on_insufficient_data(self):
        """Test error when T < p (underdetermined system)."""
        # Setup: More assets than observations
        df = _create_synthetic_returns(n_assets=100, n_days=50, n_factors=2)

        # Execute & Verify
        extractor = FactorExtractor(n_factors=10)
        with pytest.raises(ValueError, match="Insufficient data"):
            extractor.extract(df)

    def test_handles_missing_values(self):
        """Test behavior with missing returns (should drop or impute)."""
        # Setup
        df = _create_synthetic_returns(n_assets=3, n_days=100, n_factors=2)
        df = df.with_columns(
            pl.when(pl.col("ticker") == "AAPL").then(None).otherwise(pl.col("return")).alias("return")
        )

        # Execute & Verify
        extractor = FactorExtractor(n_factors=2)
        with pytest.raises(ValueError, match="Missing values"):
            extractor.extract(df)


# Helper functions
def _create_synthetic_returns(n_assets: int, n_days: int, n_factors: int) -> pl.DataFrame:
    """Create synthetic returns with known factor structure."""
    pass


def _create_returns_with_heterogeneous_vol() -> pl.DataFrame:
    """Create returns with assets having very different volatilities."""
    pass
```

**Implementation Order (TDD)**:
1. Write test `test_extract_factors_with_fixed_k` → FAIL
2. Implement minimal PCA extraction → PASS
3. Write test `test_extract_factors_with_variance_threshold` → FAIL
4. Implement automatic K selection → PASS
5. Write test `test_residuals_orthogonal_to_factors` → FAIL
6. Fix residual computation → PASS
7. Continue for remaining tests...

---

### Component 1.2: HierarchicalSectorClustering

**Purpose**: Discover sector structure via hierarchical clustering (Žignić et al. 2024).

**File**: `Risk/BlockDiagonal/HierarchicalSectorClustering.py`

**API Design**:

```python
# ABOUTME: Hierarchical clustering for sector discovery from residual correlations
# ABOUTME: Implements adaptive thresholding from Žignić et al. (2024)

from dataclasses import dataclass
import polars as pl
import numpy as np
from typing import Optional, Literal


@dataclass
class ClusteringResult:
    """Results from hierarchical clustering."""

    cluster_assignments: dict[str, int]  # ticker → cluster_id
    n_clusters: int
    linkage_matrix: np.ndarray  # Hierarchical linkage
    cluster_quality: float  # Silhouette score or similar


class HierarchicalSectorClustering:
    """
    Discovers sector structure via hierarchical clustering.

    Based on Žignić et al. (2024):
        D_ij = (|S_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)

    Uses agglomerative clustering with cross-validation for optimal cluster count.
    """

    def __init__(
        self,
        linkage_method: Literal["ward", "average", "weighted"] = "ward",
        n_clusters: Optional[int] = None,
        max_clusters: int = 20,
        cv_folds: int = 5,
    ):
        """
        Initialize hierarchical clustering.

        Args:
            linkage_method: Clustering linkage method
            n_clusters: Fixed cluster count (if None, use cross-validation)
            max_clusters: Maximum clusters to consider in cross-validation
            cv_folds: Number of CV folds for cluster selection
        """
        self.linkage_method = linkage_method
        self.n_clusters = n_clusters
        self.max_clusters = max_clusters
        self.cv_folds = cv_folds

    def fit(
        self,
        residuals: np.ndarray,  # T×p residual matrix
        tickers: list[str],
    ) -> ClusteringResult:
        """
        Fit hierarchical clustering to residuals.

        Args:
            residuals: T×p matrix of residual returns
            tickers: List of p ticker symbols

        Returns:
            ClusteringResult with cluster assignments

        Raises:
            ValueError: If residuals shape doesn't match tickers
        """
        pass  # Implementation in TDD

    def fit_from_dataframe(
        self,
        residuals_df: pl.DataFrame,
        ticker_col: str = "ticker",
        residual_col: str = "residual",
    ) -> ClusteringResult:
        """
        Fit clustering from polars DataFrame.

        Args:
            residuals_df: DataFrame with [ticker, date, residual]
            ticker_col: Name of ticker column
            residual_col: Name of residual column

        Returns:
            ClusteringResult
        """
        pass  # Implementation in TDD
```

**Test Specification** (abbreviated):

```python
class TestHierarchicalSectorClustering:
    def test_clusters_correlated_assets_together(self):
        """Test that highly correlated assets are clustered together."""
        # Setup: 3 groups with high within-group correlation
        pass

    def test_automatic_cluster_selection(self):
        """Test cross-validation for optimal cluster count."""
        pass

    def test_adaptive_thresholding(self):
        """Test adaptive distance threshold from Žignić et al."""
        pass

    def test_different_linkage_methods(self):
        """Test ward vs average vs weighted linkage."""
        pass
```

---

### Component 1.3: BlockDiagonalCovariance

**Purpose**: Main estimator combining factor extraction and block-diagonal structure.

**File**: `Risk/BlockDiagonal/BlockDiagonalCovariance.py`

**API Design**:

```python
# ABOUTME: Block-diagonal covariance estimator with sector structure
# ABOUTME: Integrates factor extraction and per-block Ledoit-Wolf shrinkage

import polars as pl
import numpy as np
from typing import Optional, Literal
from Risk.BlockDiagonal.FactorExtractor import FactorExtractor
from Risk.BlockDiagonal.HierarchicalSectorClustering import HierarchicalSectorClustering


class BlockDiagonalCovariance:
    """
    Estimates covariance with sector-based block-diagonal structure.

    Based on Žignić et al. (2024):
        Σ = B·Cov(F)·B^T + Ψ

    Where Ψ has block structure:
        Ψ = block_diag(Ψ₁, Ψ₂, ..., Ψₘ)

    Each block corresponds to a sector/cluster.
    """

    def __init__(
        self,
        n_factors: Optional[int] = None,
        clustering_method: Literal["predefined", "hierarchical"] = "predefined",
        shrinkage_method: Literal["ledoit_wolf", "none"] = "ledoit_wolf",
        bias_correction: bool = True,
    ):
        """
        Initialize block-diagonal covariance estimator.

        Args:
            n_factors: Number of common factors (if None, auto-select)
            clustering_method: "predefined" (use sector column) or "hierarchical"
            shrinkage_method: Shrinkage applied to each block
            bias_correction: Apply eigenvalue bias correction when p > T
        """
        self.n_factors = n_factors
        self.clustering_method = clustering_method
        self.shrinkage_method = shrinkage_method
        self.bias_correction = bias_correction

        self.factor_extractor = FactorExtractor(n_factors=n_factors)
        self.clusterer = HierarchicalSectorClustering() if clustering_method == "hierarchical" else None

    def estimate(
        self,
        returns: pl.DataFrame,
        sector_col: Optional[str] = "sector",
    ) -> pl.DataFrame:
        """
        Estimate block-diagonal covariance matrix.

        Args:
            returns: DataFrame with columns [ticker, date, return, sector]
                     If clustering_method="hierarchical", sector_col is ignored
            sector_col: Name of sector column (for predefined clustering)

        Returns:
            Covariance matrix as DataFrame with columns [ticker_i, ticker_j, covariance]

        Raises:
            ValueError: If required columns missing or data insufficient
        """
        pass  # Implementation in TDD

    def _extract_factors(self, returns: pl.DataFrame) -> tuple:
        """Extract common factors and residuals."""
        pass

    def _cluster_residuals(self, residuals: np.ndarray, tickers: list[str], sectors: Optional[list[str]]) -> dict:
        """Cluster residuals by sector or hierarchy."""
        pass

    def _estimate_block_covariances(self, residuals: np.ndarray, clusters: dict) -> dict:
        """Estimate covariance for each block with shrinkage."""
        pass

    def _reconstruct_covariance(
        self,
        factor_loadings: np.ndarray,
        factor_cov: np.ndarray,
        block_covariances: dict,
        tickers: list[str],
    ) -> pl.DataFrame:
        """Reconstruct full covariance: Σ = B·Cov(F)·B^T + Ψ."""
        pass
```

**Test Specification** (abbreviated):

```python
class TestBlockDiagonalCovariance:
    def test_estimate_with_predefined_sectors(self):
        """Test estimation using predefined sector column."""
        pass

    def test_estimate_with_hierarchical_clustering(self):
        """Test estimation with automatic sector discovery."""
        pass

    def test_block_structure_preserved(self):
        """Test that off-block elements are dominated by factor component."""
        pass

    def test_positive_definite_output(self):
        """Test that output covariance is positive definite."""
        pass

    def test_ledoit_wolf_shrinkage_per_block(self):
        """Test that shrinkage is applied within each block."""
        pass

    def test_bias_correction_when_p_greater_than_t(self):
        """Test eigenvalue bias correction in high-dimensional regime."""
        pass

    def test_comparison_vs_full_ledoit_wolf(self):
        """Compare out-of-sample risk vs. full Ledoit-Wolf (should improve)."""
        pass
```

---

## Phase 2: Two-Step Estimator (Priority 2)

**Goal**: Implement García-Medina (2024) two-step estimator (best performer).

**Estimated Time**: 4-6 hours

---

### Component 2.1: RandomMatrixFilter

**Purpose**: Random matrix theory filtering (Marčenko-Pastur).

**File**: `Risk/TwoStep/RandomMatrixFilter.py`

**API Design**:

```python
# ABOUTME: Random matrix theory filtering for covariance eigenvalues
# ABOUTME: Implements Marčenko-Pastur threshold and eigenvalue cleaning

import numpy as np
from typing import Tuple


class RandomMatrixFilter:
    """
    Filters covariance eigenvalues using random matrix theory.

    Based on Marčenko-Pastur distribution:
        λ_± = σ²(1 ± √(p/T))²

    Eigenvalues below λ_+ are considered noise and filtered.
    """

    def __init__(
        self,
        filter_method: str = "marcenko_pastur",  # "marcenko_pastur" or "ycm"
        sigma_estimator: str = "median",  # "median" or "robust"
    ):
        """
        Initialize random matrix filter.

        Args:
            filter_method: Method for eigenvalue filtering
            sigma_estimator: How to estimate noise level σ²
        """
        self.filter_method = filter_method
        self.sigma_estimator = sigma_estimator

    def filter_eigenvalues(
        self,
        eigenvalues: np.ndarray,
        n_observations: int,
        n_assets: int,
    ) -> np.ndarray:
        """
        Filter eigenvalues using Marčenko-Pastur threshold.

        Args:
            eigenvalues: Array of eigenvalues (sorted descending)
            n_observations: Number of time observations (T)
            n_assets: Number of assets (p)

        Returns:
            Filtered eigenvalues

        Raises:
            ValueError: If n_observations < n_assets (ill-conditioned)
        """
        pass  # Implementation in TDD

    def clean_covariance(
        self,
        cov_matrix: np.ndarray,
        n_observations: int,
    ) -> np.ndarray:
        """
        Clean covariance matrix by filtering eigenvalues.

        Args:
            cov_matrix: p×p covariance matrix
            n_observations: Number of time observations (T)

        Returns:
            Cleaned covariance matrix (positive definite)
        """
        pass  # Implementation in TDD

    def _estimate_noise_level(self, eigenvalues: np.ndarray, n_observations: int, n_assets: int) -> float:
        """Estimate noise variance σ² from eigenvalue spectrum."""
        pass

    def _marcenko_pastur_threshold(self, sigma_sq: float, n_observations: int, n_assets: int) -> float:
        """Compute λ_+ threshold."""
        q = n_assets / n_observations
        return sigma_sq * (1 + np.sqrt(q)) ** 2
```

**Test Specification**:

```python
class TestRandomMatrixFilter:
    def test_marcenko_pastur_threshold_calculation(self):
        """Test λ_+ threshold computation."""
        pass

    def test_filters_noise_eigenvalues(self):
        """Test that small eigenvalues are filtered/replaced."""
        pass

    def test_preserves_signal_eigenvalues(self):
        """Test that large eigenvalues are preserved."""
        pass

    def test_output_positive_definite(self):
        """Test that filtered covariance is positive definite."""
        pass
```

---

### Component 2.2: TwoStepCovariance

**Purpose**: Combine hierarchical clustering + RMT filtering.

**File**: `Risk/TwoStep/TwoStepCovariance.py`

**API Design**:

```python
# ABOUTME: Two-step covariance estimator from García-Medina (2024)
# ABOUTME: Combines hierarchical clustering with random matrix filtering

import polars as pl
from Risk.BlockDiagonal.HierarchicalSectorClustering import HierarchicalSectorClustering
from Risk.TwoStep.RandomMatrixFilter import RandomMatrixFilter


class TwoStepCovariance:
    """
    Two-step covariance estimator (best performer from García-Medina 2024).

    Step 1: Hierarchical clustering (ALCA)
    Step 2: Random matrix filtering (YCM/MP) per cluster

    Achieves best diversification and leverage metrics.
    """

    def __init__(
        self,
        n_clusters: int = None,
        linkage_method: str = "ward",
        rmt_filter: bool = True,
    ):
        """
        Initialize two-step estimator.

        Args:
            n_clusters: Number of clusters (if None, use cross-validation)
            linkage_method: Hierarchical clustering linkage
            rmt_filter: Apply RMT filtering to each cluster
        """
        self.n_clusters = n_clusters
        self.linkage_method = linkage_method
        self.rmt_filter = rmt_filter

        self.clusterer = HierarchicalSectorClustering(
            linkage_method=linkage_method,
            n_clusters=n_clusters,
        )
        self.rmt_filter_obj = RandomMatrixFilter() if rmt_filter else None

    def estimate(
        self,
        returns: pl.DataFrame,
    ) -> pl.DataFrame:
        """
        Estimate covariance using two-step procedure.

        Args:
            returns: DataFrame with [ticker, date, return]

        Returns:
            Covariance matrix as DataFrame
        """
        pass  # Implementation in TDD
```

**Test Specification**:

```python
class TestTwoStepCovariance:
    def test_outperforms_block_diagonal(self):
        """Test that two-step achieves better out-of-sample risk than Phase 1."""
        pass

    def test_best_diversification_metrics(self):
        """Test HHI, leverage, RDI match García-Medina results."""
        pass
```

---

## Phase 3: Stochastic Block Model (Optional)

**Status**: Implement only if Phase 1-2 results show need for inter-block correlations.

**Estimated Time**: 8-12 hours

**Complexity**: Requires Bayesian inference (PyMC or custom MCMC).

---

## Phase 4: Integration & Testing

### Integration Tests

**File**: `tests/integration/test_sector_risk_models.py`

```python
class TestSectorRiskModelIntegration:
    """End-to-end tests for sector risk models in ARBS pipeline."""

    def test_end_to_end_equity_pipeline_with_block_diagonal(self):
        """
        Test full pipeline: Query → Adapter → Returns → BlockDiagonalCov → Optimizer → Portfolio.
        """
        # Setup
        queries = [
            EquityQuery(ticker="AAPL", sector="Technology"),
            EquityQuery(ticker="MSFT", sector="Technology"),
            EquityQuery(ticker="JPM", sector="Financials"),
            EquityQuery(ticker="BAC", sector="Financials"),
        ]

        mdp = YahooFinanceMDP()
        adapter = EquityAdapter(mdp)
        returns_calc = ReturnsCalculator()
        cov_estimator = BlockDiagonalCovariance(clustering_method="predefined")
        signal = CarrySignal()
        alpha_gen = AlphaGenerator()
        optimizer = MeanVarianceOptimizer()

        # Execute
        df = adapter.convert(queries, as_of_date=date(2024, 12, 31))
        returns = returns_calc.calculate(df)
        signals = signal.generate_batch(returns)
        alphas = alpha_gen.generate(signals, returns)
        cov_matrix = cov_estimator.estimate(returns, sector_col="sector")
        weights = optimizer.optimize(alphas, cov_matrix, risk_aversion=2.0)

        # Verify
        assert len(weights) == 4
        assert abs(weights["weight"].sum()) < 1e-6  # Market neutral
        assert weights["weight"].abs().sum() <= 2.0  # Leverage constraint

    def test_block_diagonal_improves_sharpe_vs_baseline(self):
        """
        Test that block-diagonal covariance improves out-of-sample Sharpe.
        """
        # Compare:
        # 1. Sample covariance
        # 2. Full Ledoit-Wolf
        # 3. Block-diagonal (predefined)
        # 4. Block-diagonal (hierarchical)

        # Expected: 1 < 2 < 3 ≤ 4
        pass

    def test_two_step_achieves_best_diversification(self):
        """
        Test that two-step estimator achieves best HHI, leverage, RDI.
        """
        # Compare all methods
        # Verify: Two-step has lowest HHI, lowest leverage
        pass
```

---

## Performance Benchmarks

### Success Criteria

Based on paper results, we expect:

**Sharpe Ratio** (out-of-sample):
- Sample covariance: 0.3-0.5 (baseline)
- Full Ledoit-Wolf: 0.5-0.7
- Block-diagonal: 0.7-1.0 ✅ **Target**
- Two-step: 1.0-1.5 ✅ **Stretch goal**

**Diversification (HHI)**:
- Sample covariance: 0.1-0.3
- Block-diagonal: 0.05-0.15 ✅ **Target** (lower is better)

**Leverage**:
- Sample covariance: 5-20
- Block-diagonal: 2-5 ✅ **Target** (lower is better)

**Out-of-Sample Risk (R²_out)**:
- Sample covariance: >2.0
- Block-diagonal: 1.0-1.5 ✅ **Target** (lower is better)

---

## TDD Workflow

### For Each Component

1. **Write test first** (RED phase)
   - Test should fail (component doesn't exist yet)
   - Test specifies expected behavior clearly

2. **Implement minimal code** (GREEN phase)
   - Write only enough code to pass the test
   - Don't add extra features

3. **Refactor** (REFACTOR phase)
   - Clean up code while keeping tests green
   - Extract helper functions
   - Improve naming

4. **Commit** after each green test
   - Commit message: `feat(risk): Add [component] - [test_name]`
   - Push frequently to avoid losing work

### Example TDD Cycle

```bash
# 1. RED: Write failing test
# tests/unit/risk/block_diagonal/test_factor_extractor.py
def test_extract_factors_with_fixed_k():
    # ... test code ...
    pass

# Run test → FAIL (FactorExtractor doesn't exist)
pytest tests/unit/risk/block_diagonal/test_factor_extractor.py::test_extract_factors_with_fixed_k -v

# 2. GREEN: Implement minimal code
# Risk/BlockDiagonal/FactorExtractor.py
class FactorExtractor:
    def extract(self, returns, return_col="return"):
        # Minimal implementation to pass test
        pass

# Run test → PASS
pytest tests/unit/risk/block_diagonal/test_factor_extractor.py::test_extract_factors_with_fixed_k -v

# 3. REFACTOR: Clean up
# ... improve code quality ...

# 4. COMMIT & PUSH
git add tests/unit/risk/block_diagonal/test_factor_extractor.py Risk/BlockDiagonal/FactorExtractor.py
git commit -m "feat(risk): Add FactorExtractor - test_extract_factors_with_fixed_k"
git push -u origin claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq
```

---

## Data Requirements

### Minimum Dataset for Testing

**S&P 500 Constituents** (recommendation):
- Top 100-500 stocks by market cap
- 252-500 trading days (1-2 years)
- GICS sector codes (11 Level 1 sectors)
- No missing values (complete data required)

**Yahoo Finance Coverage** (existing):
- ✅ Daily prices (via `yfinance`)
- ✅ GICS sector mapping (hardcoded for 29 tickers)
- ⏳ Need: Extend to top 500 by market cap

### Extension to YahooFinanceMDP

```python
# MDP/YahooFinance/YahooFinanceMDP.py (extend)
def fetch_sp500_universe(
    self,
    as_of_date: date,
    top_n: int = 500,
    require_complete_data: bool = True,
    lookback_days: int = 252,
) -> list[EquityQuery]:
    """
    Fetch S&P 500 constituents with complete data.

    Returns:
        List of EquityQuery objects with GICS sectors
    """
    # 1. Fetch S&P 500 tickers
    # 2. Filter by market cap (top_n)
    # 3. Check data completeness (no missing values in lookback window)
    # 4. Map to GICS sectors
    # 5. Return EquityQuery objects
    pass
```

---

## Timeline Estimate

### Phase 1: Block-Diagonal (5-8 hours)
- ✅ FactorExtractor: 2-3 hours
- ✅ HierarchicalSectorClustering: 2-3 hours
- ✅ BlockDiagonalCovariance: 2-3 hours
- ✅ Integration tests: 1 hour

### Phase 2: Two-Step (4-6 hours)
- ✅ RandomMatrixFilter: 2-3 hours
- ✅ TwoStepCovariance: 2-3 hours
- ✅ Performance benchmarks: 1 hour

### Phase 3: Stochastic Block (Optional, 8-12 hours)
- ⏳ Bayesian inference: 4-6 hours
- ⏳ StochasticBlockCovariance: 3-4 hours
- ⏳ Comparison tests: 1-2 hours

### Phase 4: Documentation & Examples (2-3 hours)
- Example scripts
- Usage documentation
- Performance report

**Total Estimate**: 11-17 hours (Phases 1-2), +8-12 hours (Phase 3 if needed)

---

## Commit Strategy

### Commit Frequency
- ✅ After each passing test (GREEN phase)
- ✅ After major refactoring
- ✅ After adding documentation
- ✅ At end of each session

### Commit Message Format
```
feat(risk): [Component] - [Feature/Test]

- Detailed description
- Test coverage
- Performance impact (if applicable)
```

**Examples**:
```
feat(risk): Add FactorExtractor with PCA

- Implements factor extraction using sklearn PCA
- Computes residuals orthogonal to factors
- Tests: 6 tests covering fixed K, auto K, orthogonality
- TDD workflow maintained

---

feat(risk): Add HierarchicalSectorClustering with adaptive thresholding

- Implements Žignić et al. (2024) distance matrix
- Agglomerative clustering with ward/average/weighted linkage
- Cross-validation for optimal cluster count
- Tests: 8 tests covering clustering quality and edge cases

---

feat(risk): Integrate BlockDiagonalCovariance end-to-end

- Full factor model + block-diagonal residual structure
- Per-block Ledoit-Wolf shrinkage
- Integration test: Query → BlockDiagonalCov → Portfolio
- Performance: Out-of-sample Sharpe +0.15 vs baseline
```

---

## Next Actions

### Immediate (Now)
1. ✅ Commit and push this implementation plan
2. ⏳ Begin Phase 1 Component 1.1 (FactorExtractor)
   - Write first test: `test_extract_factors_with_fixed_k`
   - Implement minimal code to pass
   - Refactor and commit

### After Phase 1 Complete
1. Performance validation against benchmarks
2. Document results and insights
3. Decision: Proceed to Phase 2 or iterate on Phase 1

### After Phase 2 Complete
1. Compare Phase 1 vs Phase 2 performance
2. Decision: Proceed to Phase 3 or declare MVP complete
3. Write example scripts and documentation

---

**Status**: ✅ Ready for TDD Implementation - Phase 1 Start
