# Phase 3: Common Patterns Analysis

## Analysis Date
2025-11-12

## Overview
This document analyzes common patterns across the three sector-based covariance implementations to inform the design of a `SectorBasedCovarianceEstimator` abstract base class.

## Implementations Analyzed
1. **BlockDiagonalCovariance** (Paper 2: Žignić et al. 2024)
2. **TwoStepCovariance** (Paper 1: García-Medina et al. 2024)
3. **StochasticBlockCovariance** (Paper 3: Chen et al. 2025)

## Common Patterns

### 1. Inheritance Structure
- **Current**: All three inherit directly from `BaseCovarianceEstimator`
- **Shared**: All implement `fit()`, store `cov_matrix_`, `asset_names_`

### 2. Data Format Requirements
All three implementations:
- Accept long format: `[ticker, date, return, sector]`
- Use `sector_utils` functions: `validate_sector_data()`, `long_to_wide()`, `extract_sector_mapping()`, `group_tickers_by_sector()`
- Convert to wide format (T×N) for computation
- Store ticker ordering for result interpretation

### 3. Sector Assignment Strategy
All three support two modes:
- **Predefined**: Use sector column from input data
- **Discovered**: Use hierarchical clustering on returns/correlations

| Implementation | Predefined | Discovered | Default |
|---------------|------------|------------|---------|
| BlockDiagonal | ✅ | ✅ (hierarchical) | Predefined |
| TwoStep | ❌ | ✅ (hierarchical) | Discovered |
| StochasticBlock | ✅ | ✅ (hierarchical) | Predefined |

### 4. fit() Method Signature Variations

**BlockDiagonalCovariance:**
```python
def fit(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray
```

**TwoStepCovariance:**
```python
def fit(self, returns: pl.DataFrame) -> np.ndarray
```

**StochasticBlockCovariance:**
```python
def fit(self, returns: pl.DataFrame, sector_col: str = "sector") -> np.ndarray
```

### 5. Common Computational Pipeline

All three follow this high-level flow:
```
1. Validate input data
2. Handle missing data (via BaseCovarianceEstimator._handle_missing_data())
3. Convert long → wide format
4. Determine sector assignments (predefined or discovered)
5. Compute sector-based covariance structure
6. Ensure positive definiteness
7. Store result in self.cov_matrix_
8. Return covariance matrix
```

### 6. Sector-Specific Processing

**BlockDiagonalCovariance:**
- Extracts factors via PCA
- Computes per-block covariances with Ledoit-Wolf shrinkage
- Reconstructs: Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)

**TwoStepCovariance:**
- Hierarchical clustering (ALCA)
- RMT filtering per cluster (Marčenko-Pastur)
- Preserves cross-cluster correlations from sample covariance

**StochasticBlockCovariance:**
- Computes block-diagonal component with optional Ledoit-Wolf
- Computes full covariance
- Blends: Σ = α·BlockDiag + (1-α)·FullCov

### 7. Positive Definiteness Enforcement

All three ensure positive definiteness, but with variations:

**BlockDiagonal:**
```python
# Adds small diagonal regularization if min eigenvalue <= 0
min_eigenvalue = np.min(np.linalg.eigvalsh(full_cov))
if min_eigenvalue <= 0:
    full_cov += np.eye(p) * (abs(min_eigenvalue) + 1e-8)
```

**TwoStep:**
```python
# Relies on symmetry enforcement
cleaned_cov = (cleaned_cov + cleaned_cov.T) / 2
```

**StochasticBlock:**
```python
# Eigenvalue clipping: λᵢ → max(λᵢ, ε)
eigenvalues = np.maximum(eigenvalues, self.min_eigenvalue)
cov_matrix_pd = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
cov_matrix_pd = (cov_matrix_pd + cov_matrix_pd.T) / 2
```

### 8. Ledoit-Wolf Shrinkage

**BlockDiagonal** and **StochasticBlock** both implement Ledoit-Wolf shrinkage with constant correlation target, but with slightly different formulas.

**Common approach:**
1. Compute sample covariance
2. Target: constant correlation model
3. Compute shrinkage intensity via asymptotic variance
4. Blend: Σ = δ·Target + (1-δ)·Sample

### 9. Additional Methods

| Method | BlockDiagonal | TwoStep | StochasticBlock |
|--------|---------------|---------|-----------------|
| `get_clustering_result()` | ❌ | ✅ | ❌ |
| `get_block_structure()` | ❌ | ❌ | ✅ |
| `get_cross_sector_correlations()` | ❌ | ❌ | ✅ |

## Proposed SectorBasedCovarianceEstimator Design

### Location
`Risk/Covariance/SectorBased/BaseSectorCovarianceEstimator.py`

### Class Hierarchy
```
BaseCovarianceEstimator (existing)
    ↓
SectorBasedCovarianceEstimator (new abstract class)
    ↓
    ├── BlockDiagonalCovariance
    ├── TwoStepCovariance
    └── StochasticBlockCovariance
```

### Proposed Interface

```python
class SectorBasedCovarianceEstimator(BaseCovarianceEstimator):
    """
    Abstract base class for sector-based covariance estimators.

    Provides common functionality for models that exploit sector/cluster structure.
    """

    def __init__(
        self,
        clustering_method: Literal["predefined", "hierarchical"],
        handle_missing: str = "drop",
    ):
        super().__init__(handle_missing=handle_missing)
        self.clustering_method = clustering_method
        self.sector_mapping_: Optional[Dict[str, str]] = None

    @abstractmethod
    def fit(self, returns: pl.DataFrame, sector_col: Optional[str] = "sector") -> np.ndarray:
        """Fit the sector-based covariance model."""
        pass

    # === Common Utility Methods ===

    def _validate_sector_input(
        self,
        returns: pl.DataFrame,
        sector_col: Optional[str]
    ) -> None:
        """Validate input data for sector-based models."""
        pass

    def _convert_to_wide_format(
        self,
        returns: pl.DataFrame
    ) -> tuple[np.ndarray, list[str]]:
        """Convert long format to wide format (T×N)."""
        pass

    def _determine_sector_assignments(
        self,
        returns: np.ndarray,
        tickers: list[str],
        returns_long: pl.DataFrame,
        sector_col: Optional[str],
    ) -> Dict[str, str]:
        """Determine sector assignments (predefined or discovered)."""
        pass

    def _ensure_positive_definite(
        self,
        cov_matrix: np.ndarray,
        min_eigenvalue: float = 1e-8,
    ) -> np.ndarray:
        """Ensure covariance matrix is positive definite."""
        pass

    def get_sector_mapping(self) -> Dict[str, str]:
        """Get ticker → sector mapping after fit."""
        pass

    def get_sector_groups(self) -> Dict[str, List[str]]:
        """Get sector → list of tickers mapping."""
        pass
```

## Extraction Strategy

### Step 1: Create Abstract Base Class
- Define common interface
- Implement shared utility methods
- Add sector-specific state management

### Step 2: Refactor BlockDiagonalCovariance
- Inherit from `SectorBasedCovarianceEstimator`
- Remove duplicated code
- Use inherited utilities
- Run tests to ensure no regression

### Step 3: Refactor TwoStepCovariance
- Inherit from `SectorBasedCovarianceEstimator`
- Remove duplicated code
- Use inherited utilities
- Run tests to ensure no regression

### Step 4: Refactor StochasticBlockCovariance
- Inherit from `SectorBasedCovarianceEstimator`
- Remove duplicated code
- Use inherited utilities
- Run tests to ensure no regression

### Step 5: Verification
- Run all 92 tests
- Verify all pass
- Check for any behavioral changes

## Benefits

1. **DRY Principle**: Eliminate code duplication across three implementations
2. **Consistency**: Ensure all sector-based models follow same conventions
3. **Maintainability**: Bug fixes in common code benefit all implementations
4. **Extensibility**: Easier to add new sector-based models in future
5. **Documentation**: Centralized interface documentation

## Risks

1. **Over-abstraction**: Risk of creating too generic interface
2. **Test regression**: Must ensure all 92 tests still pass
3. **Interface constraints**: May limit future flexibility if poorly designed

## Mitigation

1. **Minimal abstraction**: Only extract truly common patterns
2. **TDD approach**: Run tests after each refactoring step
3. **Flexible design**: Use optional parameters and abstract methods appropriately
