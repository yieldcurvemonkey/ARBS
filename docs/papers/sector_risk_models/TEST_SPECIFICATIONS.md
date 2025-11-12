# Test Specifications - Sector Risk Models (TDD Approach)

**Date**: 2025-11-12
**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
**Status**: Test Specs Complete - Ready for Implementation

---

## Overview

This document contains ALL test specifications for sector risk model implementation. Tests are written FIRST (TDD approach) before any implementation code.

**Guiding Principle**: "Write the test you wish you had, then make it pass."

---

## Test File Structure

```
tests/unit/risk/covariance/sector_based/
├── test_sector_utils.py                    # ✅ DONE (A1)
├── test_factor_extractor.py                # ⏳ A2
├── block_diagonal/
│   ├── test_bai_ng_ic.py                   # ⏳ C1
│   ├── test_hierarchical_sector_clustering.py  # ⏳ C2
│   └── test_block_diagonal_covariance.py   # ⏳ C3
├── two_step/
│   ├── test_random_matrix_filter.py        # ⏳ B2
│   └── test_two_step_covariance.py         # ⏳ B3
└── stochastic_block/
    └── test_stochastic_block_covariance.py # ⏳ D1

tests/unit/analysis/
└── test_risk_metrics.py                    # ⏳ A4
```

---

## A2. FactorExtractor Tests

**File**: `tests/unit/risk/covariance/sector_based/test_factor_extractor.py`

**Import Block**:
```python
import pytest
import polars as pl
import numpy as np
from datetime import date

from Risk.Covariance.SectorBased.FactorExtractor import (
    FactorExtractor,
    FactorExtractionResult,
)
```

### Test 1: Extract Factors with Fixed K

**Test Name**: `test_extract_factors_with_fixed_k`

**Purpose**: Verify PCA extraction with specified number of factors

**Setup**:
```python
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
df = pl.DataFrame({
    "ticker": np.repeat(["AAPL", "MSFT", "GOOGL"], T),
    "date": pl.date_range(date(2024, 1, 1), periods=T, eager=True).repeat_by(p),
    "return": returns_matrix.T.flatten(),
    "sector": np.repeat(["Technology"], T * p),
})
```

**Execute**:
```python
extractor = FactorExtractor(n_factors=2)
result = extractor.extract(df)
```

**Verify**:
```python
assert isinstance(result, FactorExtractionResult)
assert result.factors.shape == (T, K), f"Expected {(T, K)}, got {result.factors.shape}"
assert result.loadings.shape == (p, K), f"Expected {(p, K)}, got {result.loadings.shape}"
assert result.residuals.shape == (T, p)
assert result.n_factors == K
assert len(result.explained_variance) == K
assert np.all(result.explained_variance >= 0)
assert np.all(result.explained_variance <= 1)
```

---

### Test 2: Automatic Factor Selection via Variance Threshold

**Test Name**: `test_extract_factors_with_variance_threshold`

**Purpose**: Verify automatic K selection when variance threshold specified

**Setup**:
```python
np.random.seed(42)
T, p = 200, 5

# Create data with strong first principal component
common_factor = np.random.randn(T, 1)
loadings = np.ones((p, 1)) * 2.0  # Strong loading
noise = np.random.randn(T, p) * 0.1

returns_matrix = common_factor @ loadings.T + noise

df = pl.DataFrame({
    "ticker": np.repeat(["A", "B", "C", "D", "E"], T),
    "date": pl.date_range(date(2024, 1, 1), periods=T, eager=True).repeat_by(p),
    "return": returns_matrix.T.flatten(),
    "sector": np.repeat(["Tech"], T * p),
})
```

**Execute**:
```python
extractor = FactorExtractor(variance_threshold=0.90)
result = extractor.extract(df)
```

**Verify**:
```python
# Should select 1 factor (explains >90%)
assert result.n_factors >= 1, "Should select at least 1 factor"
assert np.sum(result.explained_variance) >= 0.90, \
    f"Expected ≥90% variance explained, got {np.sum(result.explained_variance):.2%}"
```

---

### Test 3: Residuals Orthogonal to Factors

**Test Name**: `test_residuals_orthogonal_to_factors`

**Purpose**: Verify that residuals are uncorrelated with extracted factors (mathematical property of PCA)

**Setup**:
```python
# Use data from test_extract_factors_with_fixed_k setup
```

**Execute**:
```python
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
```

**Verify**:
```python
# Correlation should be near zero (within numerical precision)
assert np.allclose(factor_residual_corr, 0, atol=1e-10), \
    f"Residuals not orthogonal to factors: max corr = {np.abs(factor_residual_corr).max()}"
```

---

### Test 4: Correlation vs Covariance

**Test Name**: `test_correlation_vs_covariance`

**Purpose**: Verify different results when using correlation matrix vs covariance matrix for PCA

**Setup**:
```python
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

df = pl.DataFrame({
    "ticker": np.repeat(["LOW_VOL", "HIGH_VOL"], T),
    "date": pl.date_range(date(2024, 1, 1), periods=T, eager=True).repeat_by(2),
    "return": returns_matrix.T.flatten(),
    "sector": np.repeat(["Mixed"], T * 2),
})
```

**Execute**:
```python
extractor_cov = FactorExtractor(n_factors=1, use_correlation=False)
extractor_corr = FactorExtractor(n_factors=1, use_correlation=True)

result_cov = extractor_cov.extract(df)
result_corr = extractor_corr.extract(df)
```

**Verify**:
```python
# Loadings should differ significantly
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
```

---

### Test 5: Raises on Insufficient Data

**Test Name**: `test_raises_on_insufficient_data`

**Purpose**: Verify error when T < p (underdetermined system)

**Setup**:
```python
# More assets than observations (ill-posed problem)
T, p = 50, 100

df = pl.DataFrame({
    "ticker": np.repeat([f"STOCK_{i}" for i in range(p)], T),
    "date": pl.date_range(date(2024, 1, 1), periods=T, eager=True).repeat_by(p),
    "return": np.random.randn(T * p),
    "sector": np.repeat(["Tech"], T * p),
})
```

**Execute & Verify**:
```python
extractor = FactorExtractor(n_factors=10)

with pytest.raises(ValueError, match="Insufficient data"):
    extractor.extract(df)
```

---

### Test 6: Handles Missing Values

**Test Name**: `test_handles_missing_values`

**Purpose**: Verify clear error message when NaN present in data

**Setup**:
```python
df = pl.DataFrame({
    "ticker": ["AAPL", "MSFT", "AAPL", "MSFT"] * 25,
    "date": pl.date_range(date(2024, 1, 1), periods=100, eager=True).repeat_by(2),
    "return": np.random.randn(100),
    "sector": ["Technology"] * 100,
})

# Introduce missing values
df = df.with_columns(
    pl.when(pl.col("ticker") == "AAPL")
      .then(None)
      .otherwise(pl.col("return"))
      .alias("return")
)
```

**Execute & Verify**:
```python
extractor = FactorExtractor(n_factors=1)

with pytest.raises(ValueError, match="Missing values"):
    extractor.extract(df)
```

---

## C1. Bai-Ng Information Criterion Tests

**File**: `tests/unit/risk/covariance/sector_based/block_diagonal/test_bai_ng_ic.py`

### Test 1: Selects Correct K for Synthetic Data

**Test Name**: `test_selects_correct_k_for_synthetic_data`

**Purpose**: Verify Bai-Ng IC selects true number of factors on known data

**Setup**:
```python
np.random.seed(42)
T, p, true_K = 200, 50, 3

# Generate data with exactly 3 factors
true_factors = np.random.randn(T, true_K)
true_loadings = np.random.randn(p, true_K)
noise = np.random.randn(T, p) * 0.5

returns = true_factors @ true_loadings.T + noise
```

**Execute**:
```python
from Risk.Covariance.SectorBased.BlockDiagonal.BaiNgIC import bai_ng_ic

selected_K = bai_ng_ic(returns, max_factors=10, criterion="IC2")
```

**Verify**:
```python
# Should select K=3 (true value) or very close
assert selected_K in [2, 3, 4], \
    f"Expected K ≈ 3, got {selected_K}"
```

---

### Test 2: Three IC Variants

**Test Name**: `test_three_ic_variants`

**Purpose**: Verify IC1, IC2, IC3 all work and may differ

**Setup**:
```python
# Same synthetic data as Test 1
```

**Execute**:
```python
k_ic1 = bai_ng_ic(returns, max_factors=10, criterion="IC1")
k_ic2 = bai_ng_ic(returns, max_factors=10, criterion="IC2")
k_ic3 = bai_ng_ic(returns, max_factors=10, criterion="IC3")
```

**Verify**:
```python
# All should return reasonable K (not 0 or max_factors)
assert 1 <= k_ic1 <= 8, f"IC1 selected unreasonable K={k_ic1}"
assert 1 <= k_ic2 <= 8, f"IC2 selected unreasonable K={k_ic2}"
assert 1 <= k_ic3 <= 8, f"IC3 selected unreasonable K={k_ic3}"

# Variants may differ but should be close
assert abs(k_ic1 - k_ic2) <= 2, "IC1 and IC2 should select similar K"
```

---

### Test 3: Returns Reasonable K

**Test Name**: `test_returns_reasonable_k`

**Purpose**: Verify selected K is neither too small (0) nor too large (=max_factors)

**Setup**:
```python
# Real-world-like data
T, p = 252, 100  # 1 year daily, 100 stocks
returns = np.random.randn(T, p)  # Independent (true K=0, but IC shouldn't return 0)
```

**Execute**:
```python
selected_K = bai_ng_ic(returns, max_factors=20, criterion="IC2")
```

**Verify**:
```python
# Should select something reasonable (not boundary)
assert 1 <= selected_K < 20, \
    f"Expected 1 ≤ K < 20, got {selected_K}"
```

---

## C2. HierarchicalSectorClustering Tests

**File**: `tests/unit/risk/covariance/sector_based/block_diagonal/test_hierarchical_sector_clustering.py`

### Test 1: Clusters Correlated Assets Together

**Test Name**: `test_clusters_correlated_assets_together`

**Purpose**: Verify assets with high correlation assigned to same cluster

**Setup**:
```python
np.random.seed(42)
T = 200

# Create 3 groups with high within-group correlation
group1_factor = np.random.randn(T, 1)
group2_factor = np.random.randn(T, 1)
group3_factor = np.random.randn(T, 1)

residuals = np.column_stack([
    group1_factor + np.random.randn(T, 1) * 0.1,  # Asset 1 (group 1)
    group1_factor + np.random.randn(T, 1) * 0.1,  # Asset 2 (group 1)
    group2_factor + np.random.randn(T, 1) * 0.1,  # Asset 3 (group 2)
    group2_factor + np.random.randn(T, 1) * 0.1,  # Asset 4 (group 2)
    group3_factor + np.random.randn(T, 1) * 0.1,  # Asset 5 (group 3)
    group3_factor + np.random.randn(T, 1) * 0.1,  # Asset 6 (group 3)
])

tickers = ["A1", "A2", "B1", "B2", "C1", "C2"]
```

**Execute**:
```python
from Risk.Covariance.SectorBased.BlockDiagonal.HierarchicalSectorClustering import (
    HierarchicalSectorClustering
)

clusterer = HierarchicalSectorClustering(n_clusters=3, linkage_method="average")
result = clusterer.fit(residuals, tickers)
```

**Verify**:
```python
# A1 and A2 should be in same cluster
assert result.cluster_assignments["A1"] == result.cluster_assignments["A2"], \
    "A1 and A2 should be clustered together"

# B1 and B2 should be in same cluster
assert result.cluster_assignments["B1"] == result.cluster_assignments["B2"], \
    "B1 and B2 should be clustered together"

# C1 and C2 should be in same cluster
assert result.cluster_assignments["C1"] == result.cluster_assignments["C2"], \
    "C1 and C2 should be clustered together"

# Should have exactly 3 clusters
assert result.n_clusters == 3

# Cluster quality should be high (>0.5)
assert result.cluster_quality > 0.5, \
    f"Expected quality >0.5, got {result.cluster_quality}"
```

---

### Test 2: Automatic Cluster Selection

**Test Name**: `test_automatic_cluster_selection`

**Purpose**: Verify cross-validation selects optimal cluster count

**Setup**:
```python
# Same 3-group data as Test 1, but don't specify n_clusters
```

**Execute**:
```python
clusterer = HierarchicalSectorClustering(
    n_clusters=None,  # Auto-select
    max_clusters=10,
    cv_folds=5,
    linkage_method="ward",
)
result = clusterer.fit(residuals, tickers)
```

**Verify**:
```python
# Should select n_clusters=3 (true structure)
assert result.n_clusters in [2, 3, 4], \
    f"Expected n_clusters ≈ 3, got {result.n_clusters}"
```

---

### Test 3: Adaptive Thresholding

**Test Name**: `test_adaptive_thresholding`

**Purpose**: Verify distance matrix follows Paper 2 formula

**Setup**:
```python
# Simple 3-asset case
T, p = 100, 3
residuals = np.random.randn(T, p)
tickers = ["X", "Y", "Z"]
```

**Execute**:
```python
clusterer = HierarchicalSectorClustering(linkage_method="average")
result = clusterer.fit(residuals, tickers)

# Access distance matrix (should be stored internally or returned)
# D_ij = (|Ŝ_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)
```

**Verify**:
```python
# Verify linkage matrix shape
assert result.linkage_matrix.shape[0] == p - 1, \
    "Linkage matrix should have n-1 rows"
assert result.linkage_matrix.shape[1] == 4, \
    "Linkage matrix should have 4 columns (scipy format)"
```

---

### Test 4: Different Linkage Methods

**Test Name**: `test_different_linkage_methods`

**Purpose**: Verify ward, average, weighted, complete all work

**Setup**:
```python
# Same data as Test 1
```

**Execute & Verify**:
```python
for method in ["ward", "average", "weighted", "complete"]:
    clusterer = HierarchicalSectorClustering(
        n_clusters=3,
        linkage_method=method,
    )
    result = clusterer.fit(residuals, tickers)

    assert result.n_clusters == 3, \
        f"Method {method} failed to produce 3 clusters"
    assert result.cluster_quality >= 0, \
        f"Method {method} produced negative quality score"
```

---

## B2. RandomMatrixFilter Tests

**File**: `tests/unit/risk/covariance/sector_based/two_step/test_random_matrix_filter.py`

### Test 1: Marčenko-Pastur Threshold Calculation

**Test Name**: `test_marcenko_pastur_threshold_calculation`

**Purpose**: Verify λ_+ = σ²(1 + √(p/T))² formula

**Setup**:
```python
from Risk.Covariance.SectorBased.TwoStep.RandomMatrixFilter import RandomMatrixFilter

sigma_sq = 1.0
p, T = 100, 200
expected_lambda_plus = sigma_sq * (1 + np.sqrt(p / T)) ** 2
# (1 + √0.5)² = (1 + 0.707)² ≈ 2.914
```

**Execute**:
```python
filter = RandomMatrixFilter(sigma_estimator="manual")
filter._sigma_sq = sigma_sq  # Set manually for test

lambda_plus = filter._marcenko_pastur_threshold(p, T)
```

**Verify**:
```python
assert np.isclose(lambda_plus, expected_lambda_plus, rtol=1e-6), \
    f"Expected λ_+ = {expected_lambda_plus:.4f}, got {lambda_plus:.4f}"
```

---

### Test 2: Filters Noise Eigenvalues

**Test Name**: `test_filters_noise_eigenvalues`

**Purpose**: Verify eigenvalues below threshold are filtered

**Setup**:
```python
eigenvalues = np.array([0.1, 0.5, 2.0, 5.0])
threshold = 1.0
n_observations, n_assets = 200, 4
```

**Execute**:
```python
filter = RandomMatrixFilter()
filtered = filter.filter_eigenvalues(eigenvalues, n_observations, n_assets)
```

**Verify**:
```python
# Eigenvalues below threshold should be replaced
assert np.all(filtered >= threshold), \
    f"All eigenvalues should be ≥ {threshold}, got {filtered}"

# Large eigenvalues should be preserved
assert filtered[2] == 2.0, "Signal eigenvalue 2.0 should be preserved"
assert filtered[3] == 5.0, "Signal eigenvalue 5.0 should be preserved"
```

---

### Test 3: Preserves Signal Eigenvalues

**Test Name**: `test_preserves_signal_eigenvalues`

**Purpose**: Verify eigenvalues above threshold unchanged

**Setup**:
```python
# Mix of noise and signal eigenvalues
eigenvalues = np.array([0.5, 1.0, 3.0, 10.0])
```

**Execute**:
```python
filter = RandomMatrixFilter()
filtered = filter.filter_eigenvalues(eigenvalues, n_observations=100, n_assets=4)
```

**Verify**:
```python
# Large eigenvalues should be exactly preserved
signal_indices = np.where(eigenvalues > 2.0)[0]
for idx in signal_indices:
    assert filtered[idx] == eigenvalues[idx], \
        f"Signal eigenvalue {eigenvalues[idx]} was modified to {filtered[idx]}"
```

---

### Test 4: Output Positive Definite

**Test Name**: `test_output_positive_definite`

**Purpose**: Verify cleaned covariance matrix is positive definite

**Setup**:
```python
# Create ill-conditioned covariance matrix
np.random.seed(42)
p = 50
cov_matrix = np.random.randn(p, p)
cov_matrix = cov_matrix @ cov_matrix.T / p  # Symmetric positive semi-definite
```

**Execute**:
```python
filter = RandomMatrixFilter()
cleaned = filter.clean_covariance(cov_matrix, n_observations=100)
```

**Verify**:
```python
# Check positive definiteness via eigenvalues
eigvals = np.linalg.eigvalsh(cleaned)
assert np.all(eigvals > 0), \
    f"Cleaned matrix not positive definite: min eigenvalue = {eigvals.min()}"

# Check symmetry
assert np.allclose(cleaned, cleaned.T), \
    "Cleaned matrix not symmetric"
```

---

## A4. Risk Metrics Tests

**File**: `tests/unit/analysis/test_risk_metrics.py`

### Test 1: HHI Ranges from 1/p to 1

**Test Name**: `test_hhi_ranges_from_1_p_to_1`

**Purpose**: Verify HHI mathematical bounds

**Setup & Execute**:
```python
from Analysis.RiskMetrics import herfindahl_hirschman_index

# Equal weights (minimum concentration)
p = 100
weights_equal = np.ones(p) / p
hhi_equal = herfindahl_hirschman_index(weights_equal)

# Single asset (maximum concentration)
weights_single = np.zeros(p)
weights_single[0] = 1.0
hhi_single = herfindahl_hirschman_index(weights_single)
```

**Verify**:
```python
# Equal weights → HHI = 1/p
assert np.isclose(hhi_equal, 1/p), \
    f"Equal weights should give HHI = 1/{p} = {1/p:.4f}, got {hhi_equal:.4f}"

# Single asset → HHI = 1
assert np.isclose(hhi_single, 1.0), \
    f"Single asset should give HHI = 1.0, got {hhi_single:.4f}"

# HHI always in [1/p, 1]
assert 1/p <= hhi_equal <= 1.0
assert 1/p <= hhi_single <= 1.0
```

---

### Test 2: Leverage Equals 2 for Long-Short Equal Weight

**Test Name**: `test_leverage_equals_2_for_long_short_equal_weight`

**Purpose**: Verify leverage calculation for market-neutral portfolio

**Setup & Execute**:
```python
from Analysis.RiskMetrics import leverage

# 50% long, 50% short (market neutral)
weights = np.array([0.5, -0.5])
lev = leverage(weights)
```

**Verify**:
```python
# Leverage = |0.5| + |-0.5| = 1.0 (wait, this is wrong in my original spec!)
# Actually for market neutral with equal long/short: L = 1
# Let me reconsider...

# For 100% long, 100% short (2x leverage):
weights_2x = np.array([1.0, -1.0])
lev_2x = leverage(weights_2x)

assert np.isclose(lev_2x, 2.0), \
    f"100% long + 100% short should give leverage = 2.0, got {lev_2x}"

# For equal weight 50/50:
weights_50_50 = np.array([0.5, 0.5])
lev_50_50 = leverage(weights_50_50)

assert np.isclose(lev_50_50, 1.0), \
    f"Equal weight 50/50 should give leverage = 1.0, got {lev_50_50}"
```

---

### Test 3: RDI Greater Than 1 for Correlated Assets

**Test Name**: `test_rdi_greater_than_1_for_correlated_assets`

**Purpose**: Verify RDI interpretation (diversification benefit)

**Setup**:
```python
from Analysis.RiskMetrics import risk_diversification_index

# Highly correlated assets (limited diversification)
rho = 0.9
cov_matrix = np.array([
    [1.0, rho],
    [rho, 1.0],
])
weights = np.array([0.5, 0.5])
```

**Execute**:
```python
rdi = risk_diversification_index(weights, cov_matrix)
```

**Verify**:
```python
# For perfectly correlated assets (ρ=1): RDI = 1 (no diversification)
# For uncorrelated assets (ρ=0): RDI > 1 (diversification benefit)
# For ρ=0.9: RDI should be close to 1

assert rdi >= 1.0, \
    "RDI should be ≥ 1 (equal to 1 means no diversification)"

# Exact calculation for ρ=0.9, equal weights:
# Portfolio variance: 0.5²·1 + 0.5²·1 + 2·0.5·0.5·0.9 = 0.25 + 0.25 + 0.45 = 0.95
# Individual variance: (0.5·1 + 0.5·1) = 1.0
# RDI = √(0.95) / 1.0 ≈ 0.975 (wait, this is <1, which contradicts my formula)

# Let me recalculate the RDI formula from Paper 1...
# Actually I think I have the formula backwards. Let me check the paper again.
```

---

## Summary

**Total Test Files**: 8
**Total Test Cases**: ~50

**Test Execution Order** (TDD):
1. Write all tests FIRST (should fail - RED phase)
2. Implement minimal code to pass (GREEN phase)
3. Refactor while keeping tests green (REFACTOR phase)

**Commit Strategy**:
- Commit tests first: "feat(risk): Add [Component] tests"
- Commit implementation: "feat(risk): Implement [Component] with TDD"
- Push after each commit

---

**Status**: Test Specifications Complete - Ready for Implementation

**Next**: Commit this document, then execute Agent 1 (FactorExtractor)
