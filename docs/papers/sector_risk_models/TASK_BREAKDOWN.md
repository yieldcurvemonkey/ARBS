# Complete Task Breakdown - Sector Risk Models Implementation

**Date**: 2025-11-12
**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
**Status**: Planning Phase - No Code Written Yet

---

## Overview

This document provides a complete task breakdown for implementing all 3 sector-based risk model papers. Tasks are categorized as:
- **Common** (orthogonal, shared by multiple papers)
- **Paper-Specific** (unique to each paper)

Each task includes:
- Detailed specifications from papers
- Mathematical formulas
- Test specifications (TDD)
- Verification against PDFs
- Links for resumability

---

## Paper References

### Paper 1: García-Medina (2024) - arXiv:2412.08756
**File**: `/home/user/ARBS/docs/papers/sector_risk_models/paper_2412.08756.pdf` (18 MB)
**Title**: "High-dimensional covariance matrix estimators on simulated portfolios with complex structures"
**Key Contribution**: Two-step hierarchical + RMT (best performer)

### Paper 2: Žignić et al. (2024) - arXiv:2407.03781
**File**: `/home/user/ARBS/docs/papers/sector_risk_models/paper_2407.03781.pdf` (1.4 MB)
**Title**: "Block-diagonal idiosyncratic covariance estimation in high-dimensional factor models"
**Key Contribution**: Sector-based factor model (minimum viable)

### Paper 3: Chen et al. (2025) - arXiv:2502.11332
**File**: `/home/user/ARBS/docs/papers/sector_risk_models/paper_2502.11332.pdf` (7.1 MB)
**Title**: "Stochastic Block Covariance Matrix Estimation"
**Key Contribution**: Inter-block correlations via Bayesian inference

---

## Task Categories

### ✅ Category A: Common Orthogonal Tasks (Shared by All Papers)

These tasks are used by ALL 3 papers and can be implemented by separate agents in parallel.

#### **A1. Data Format Utilities**
**Status**: ✅ COMPLETE (already implemented)
**File**: `/home/user/ARBS/Risk/Covariance/SectorBased/sector_utils.py` (148 lines)
**Functions**:
- `validate_sector_data()`
- `long_to_wide()`
- `extract_sector_mapping()`
- `get_sectors_list()`
- `group_tickers_by_sector()`
- `create_block_diagonal_matrix()`

**Tests**: `/home/user/ARBS/tests/unit/risk/covariance/sector_based/test_sector_utils.py`

**Verified Against Papers**: ✅
- All 3 papers use [ticker, date, return, sector] format
- Block-diagonal construction used by Papers 1 & 2

---

#### **A2. Factor Extraction (PCA-Based)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/FactorExtractor.py`

**Used By**:
- Paper 1 (García-Medina): One-factor model section
- Paper 2 (Žignić et al.): Core decomposition `Σ = B·Cov(F)·B^T + Ψ`
- Paper 3 (Chen et al.): Implicit factor structure

**Mathematical Specification** (from Paper 2, page 3):
```
Factor Model: Y = B·F + ε

where:
- Y: T×p returns matrix
- B: p×K loading matrix (PCA components)
- F: T×K factor matrix (PCA scores)
- ε: T×p residuals

Assumptions (Paper 2, Assumption 2.1):
1. Common factor eigenvalues grow with p (unbounded)
2. Idiosyncratic eigenvalues remain bounded
```

**API Specification**:
```python
class FactorExtractor:
    def __init__(
        self,
        n_factors: Optional[int] = None,  # If None, auto-select via variance threshold
        variance_threshold: float = 0.95,  # Cumulative variance explained
        use_correlation: bool = False,     # If True, use corr matrix not cov
    ):
        pass

    def extract(
        self,
        returns: pl.DataFrame,  # Long format [ticker, date, return]
    ) -> FactorExtractionResult:
        """
        Extract factors and compute residuals.

        Returns:
            FactorExtractionResult(
                factors: np.ndarray,        # T×K
                loadings: np.ndarray,       # p×K
                residuals: np.ndarray,      # T×p
                explained_variance: np.ndarray,  # K
                n_factors: int,
            )
        """
        pass
```

**Test Specifications** (TDD - write these FIRST):
1. `test_extract_factors_with_fixed_k`
   - Input: 100 days × 3 assets, request K=2 factors
   - Verify: factors.shape == (100, 2), loadings.shape == (3, 2)

2. `test_extract_factors_with_variance_threshold`
   - Input: Synthetic data with strong first PC (explains >90%)
   - Verify: n_factors == 1

3. `test_residuals_orthogonal_to_factors`
   - Verify: np.corrcoef(factors.T, residuals.T)[:K, K:] ≈ 0

4. `test_correlation_vs_covariance`
   - Verify: Different loadings when use_correlation=True vs False

5. `test_raises_on_insufficient_data`
   - Input: T < p (underdetermined)
   - Verify: Raises ValueError

6. `test_handles_missing_values`
   - Input: DataFrame with NaN
   - Verify: Raises ValueError with clear message

**Verification Against PDFs**:
- ✅ Paper 2, Equation (2.1): Y = BF + ε
- ✅ Paper 2, Page 5: "PCA-based factor extraction"
- ✅ Paper 1, Section 3.A: "One-factor model" uses factor structure

**Agent**: `factorextractor-agent`
**Estimated Time**: 2-3 hours
**Dependencies**: None (uses numpy, polars, sklearn.decomposition.PCA)

---

#### **A3. Ledoit-Wolf Shrinkage (Per-Block)**
**Status**: ⏳ TO DO (extend existing)
**File**: Extend `/home/user/ARBS/Risk/Covariance/LedoitWolfShrinkage.py`

**Used By**:
- Paper 2 (Žignić et al.): Per-block shrinkage (Section 3.2)
- Paper 1 (García-Medina): Referenced as baseline

**Mathematical Specification** (from Paper 2, Equation 3.3):
```
Per-Block Shrinkage:
Ŝ^c_m = α_m·Ŝ^c_m + (1 - α_m)·S̃^c_m

where:
- Ŝ^c_m: Sample covariance of block m
- S̃^c_m: Shrinkage target (constant correlation)
- α_m: Ledoit-Wolf intensity for block m (data-driven)
```

**API Specification**:
```python
def apply_per_block_shrinkage(
    blocks: Dict[str, np.ndarray],  # sector → n_m × n_m covariance
    returns_by_block: Dict[str, np.ndarray],  # sector → T × n_m returns
    target: str = "constant_correlation",
) -> Dict[str, np.ndarray]:
    """
    Apply Ledoit-Wolf shrinkage to each block separately.

    Returns:
        Shrunk covariance blocks
    """
    pass
```

**Test Specifications**:
1. `test_per_block_shrinkage_reduces_condition_number`
2. `test_different_alpha_per_block`
3. `test_preserves_block_sizes`

**Verification Against PDFs**:
- ✅ Paper 2, Section 3.2: "Ledoit-Wolf shrinkage applied within each block"
- ✅ Paper 2, Algorithm 1: CSI/CSH estimators with per-block shrinkage

**Agent**: `shrinkage-extension-agent`
**Estimated Time**: 1-2 hours
**Dependencies**: Existing `LedoitWolfShrinkage.py`

---

#### **A4. Performance Metrics (HHI, Leverage, RDI)**
**Status**: ⏳ TO DO
**File**: `Analysis/RiskMetrics.py` (new file)

**Used By**:
- Paper 1 (García-Medina): All 3 metrics explicitly defined

**Mathematical Specification** (from Paper 1, Equations 7-9):
```
1. Herfindahl-Hirschman Index (concentration):
   HHI(w) = Σ(i=1 to p) w_i²

2. Leverage (short-selling magnitude):
   L(w) = Σ(i=1 to p) |w_i|

3. Risk Diversification Index:
   RDI(w) = √(w^T·Σ·w) / (w^T·√diag(Σ))
   (Portfolio risk / average individual risk)
```

**API Specification**:
```python
def herfindahl_hirschman_index(weights: np.ndarray) -> float:
    """HHI = Σw_i². Lower is better (less concentrated)."""
    pass

def leverage(weights: np.ndarray) -> float:
    """L = Σ|w_i|. Lower is better (less short-selling)."""
    pass

def risk_diversification_index(
    weights: np.ndarray,
    cov_matrix: np.ndarray,
) -> float:
    """RDI. Higher is better (more diversified)."""
    pass
```

**Test Specifications**:
1. `test_hhi_ranges_from_1_p_to_1`
2. `test_leverage_equals_2_for_long_short_equal_weight`
3. `test_rdi_greater_than_1_for_correlated_assets`

**Verification Against PDFs**:
- ✅ Paper 1, Page 4, Equations (7)-(9)

**Agent**: `metrics-agent`
**Estimated Time**: 1 hour
**Dependencies**: None

---

### 📋 Category B: Paper 1 Specific Tasks (García-Medina 2024)

#### **B1. Hierarchical Nested Structure Generator**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/TwoStep/HierarchicalNested.py`

**Mathematical Specification** (from Paper 1, Section III.A):
```
Hierarchical Nested Structure:
Σ = L·L^T

where L is lower triangular with nested pattern:
- Parameter γ = 0.1 controls hierarchy depth
- Used for multi-level sector hierarchies (GICS L1→L2→L3)
```

**Test Specifications**:
1. `test_generates_hierarchical_pattern`
2. `test_gamma_parameter_effect`

**Verification**: ✅ Paper 1, Section III.A, pages 3-4

**Agent**: Paper-1-agent (part of TwoStep implementation)
**Estimated Time**: 1 hour

---

#### **B2. Random Matrix Filter (Marčenko-Pastur)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/TwoStep/RandomMatrixFilter.py`

**Mathematical Specification** (from Paper 1, Equation 5):
```
Marčenko-Pastur Threshold:
λ_+ = σ²(1 + √(p/T))²

where:
- σ²: Noise variance (estimated from eigenvalue spectrum)
- p: Number of assets
- T: Number of observations

Filtering:
For each eigenvalue λ_i:
  λ_i^filtered = max(λ_i, λ_+)
```

**API Specification**:
```python
class RandomMatrixFilter:
    def __init__(
        self,
        filter_method: str = "marcenko_pastur",  # or "ycm"
        sigma_estimator: str = "median",         # or "robust"
    ):
        pass

    def filter_eigenvalues(
        self,
        eigenvalues: np.ndarray,
        n_observations: int,
        n_assets: int,
    ) -> np.ndarray:
        """Filter eigenvalues using Marčenko-Pastur threshold."""
        pass

    def clean_covariance(
        self,
        cov_matrix: np.ndarray,
        n_observations: int,
    ) -> np.ndarray:
        """Clean covariance matrix by filtering eigenvalues."""
        pass
```

**Test Specifications**:
1. `test_marcenko_pastur_threshold_calculation`
   - Input: σ²=1, p=100, T=200
   - Expected: λ_+ = (1 + √0.5)² ≈ 2.414

2. `test_filters_noise_eigenvalues`
   - Input: eigenvalues [0.1, 0.5, 2.0, 5.0], threshold=1.0
   - Expected: [1.0, 1.0, 2.0, 5.0]

3. `test_preserves_signal_eigenvalues`
   - Verify large eigenvalues unchanged

4. `test_output_positive_definite`

**Verification Against PDFs**:
- ✅ Paper 1, Section III.B: "Random Matrix Theory filtering"
- ✅ Paper 1, Equation (5): λ_+ formula
- ✅ Paper 1, Figure 2: Eigenvalue spectrum before/after filtering

**Agent**: Paper-1-agent
**Estimated Time**: 2-3 hours
**Dependencies**: None

---

#### **B3. TwoStepCovariance (Best Performer)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/TwoStep/TwoStepCovariance.py`

**Mathematical Specification** (from Paper 1, Section III.C):
```
Two-Step Procedure:
Ξ^(2s,ycm) := Ξ^ycm(Ξ^ALCA)

Step 1 (ALCA): Hierarchical clustering of assets
  - Distance matrix based on correlation
  - Agglomerative linkage

Step 2 (YCM): Random matrix filtering per cluster
  - Apply Marčenko-Pastur to each cluster separately
  - Reconstruct full covariance
```

**API Specification**:
```python
class TwoStepCovariance(BaseCovarianceEstimator):
    def __init__(
        self,
        n_clusters: Optional[int] = None,
        linkage_method: str = "ward",
        rmt_filter: bool = True,
    ):
        pass

    def fit(self, returns: pl.DataFrame) -> np.ndarray:
        """
        Estimate covariance using two-step procedure.

        Step 1: Hierarchical clustering
        Step 2: RMT filtering per cluster
        """
        pass
```

**Test Specifications**:
1. `test_two_step_procedure_executes`
2. `test_outperforms_block_diagonal`
3. `test_best_diversification_metrics`
4. `test_rmt_filter_toggle`

**Verification Against PDFs**:
- ✅ Paper 1, Section III.C: "Two-step estimator"
- ✅ Paper 1, Table I: Performance results showing "best HHI and leverage"

**Agent**: Paper-1-agent
**Estimated Time**: 2 hours
**Dependencies**: B2 (RandomMatrixFilter), Category C2 (HierarchicalSectorClustering)

---

### 📋 Category C: Paper 2 Specific Tasks (Žignić et al. 2024)

#### **C1. Bai-Ng Information Criterion**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/BlockDiagonal/BaiNgIC.py`

**Mathematical Specification** (from Paper 2, Section 3.1):
```
Bai-Ng Information Criterion for factor count K:

IC(K) = ln(V(K, F̂_K)) + K·g(T, p)

where:
- V(K, F̂_K): Sum of squared residuals with K factors
- g(T, p): Penalty function

Three variants:
- IC1: g(T, p) = (p+T)/(pT) · ln(pT/(p+T))
- IC2: g(T, p) = (p+T)/(pT) · ln(min(p, T))
- IC3: g(T, p) = ln(min(p, T))/(min(p, T))

Select: K* = argmin_K IC(K)
```

**API Specification**:
```python
def bai_ng_ic(
    returns: np.ndarray,  # T×p
    max_factors: int = 20,
    criterion: str = "IC2",  # "IC1", "IC2", or "IC3"
) -> int:
    """
    Select optimal number of factors using Bai-Ng IC.

    Returns:
        Optimal K
    """
    pass
```

**Test Specifications**:
1. `test_selects_correct_k_for_synthetic_data`
2. `test_three_ic_variants`
3. `test_returns_reasonable_k`

**Verification Against PDFs**:
- ✅ Paper 2, Section 3.1: "Factor count selection"
- ✅ Paper 2, Page 6: IC formula

**Agent**: Paper-2-agent
**Estimated Time**: 2 hours
**Dependencies**: None

---

#### **C2. HierarchicalSectorClustering (CSH Estimator)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/BlockDiagonal/HierarchicalSectorClustering.py`

**Mathematical Specification** (from Paper 2, Equation 3.2):
```
Adaptive Thresholding Distance:
D_ij = (|Ŝ_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)

where:
- Ŝ_ij: Sample correlation between assets i, j
- θ̂_ij: Estimated threshold
- T: Number of observations
- p: Number of assets

Agglomerative Clustering:
- Linkage: ward, average, weighted, complete
- Distance: D matrix

Cross-Validation for Optimal Clusters:
Err_φ* = (1/H)·Σ_h ||Ψ̂^c_train - Ŝ_test||²_F
```

**API Specification**:
```python
class HierarchicalSectorClustering:
    def __init__(
        self,
        linkage_method: Literal["ward", "average", "weighted", "complete"] = "ward",
        n_clusters: Optional[int] = None,  # If None, use cross-validation
        max_clusters: int = 20,
        cv_folds: int = 5,
    ):
        pass

    def fit(
        self,
        residuals: np.ndarray,  # T×p residual matrix
        tickers: list[str],
    ) -> ClusteringResult:
        """
        Fit hierarchical clustering to residuals.

        Returns:
            ClusteringResult(
                cluster_assignments: dict[str, int],
                n_clusters: int,
                linkage_matrix: np.ndarray,
                cluster_quality: float,  # Silhouette score
            )
        """
        pass
```

**Test Specifications**:
1. `test_clusters_correlated_assets_together`
   - Input: 3 groups with high within-group correlation
   - Verify: Assets in same group get same cluster

2. `test_automatic_cluster_selection`
   - Input: Data with clear 3-cluster structure, n_clusters=None
   - Verify: Selects n_clusters=3

3. `test_adaptive_thresholding`
   - Verify: Distance matrix follows Paper 2 formula

4. `test_different_linkage_methods`
   - Verify: ward, average, weighted, complete all work

5. `test_cross_validation_error`
   - Verify: CV error decreases as clusters approach true structure

**Verification Against PDFs**:
- ✅ Paper 2, Section 3.2: "CSH estimator with hierarchical clustering"
- ✅ Paper 2, Equation (3.2): Adaptive distance formula
- ✅ Paper 2, Algorithm 1: Complete CSH algorithm

**Agent**: Paper-2-agent
**Estimated Time**: 2-3 hours
**Dependencies**: A2 (FactorExtractor for residuals)

---

#### **C3. BlockDiagonalCovariance (CSI/CSH Estimators)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/BlockDiagonal/BlockDiagonalCovariance.py`

**Mathematical Specification** (from Paper 2, Equation 2.2):
```
Block-Diagonal Factor Model:
Σ = B·Cov(F)·B^T + Ψ

where Ψ has block structure:
Ψ = block_diag(Ψ₁, Ψ₂, ..., Ψₘ)

Each block Ψ_k is estimated separately with:
1. Per-block Ledoit-Wolf shrinkage
2. Eigenvalue bias correction when p > T:
   λ_i^s = max{λ̂_i - c·p/T, 0}
```

**API Specification**:
```python
class BlockDiagonalCovariance(BaseCovarianceEstimator):
    def __init__(
        self,
        n_factors: Optional[int] = None,  # If None, use Bai-Ng IC
        clustering_method: Literal["predefined", "hierarchical"] = "predefined",
        shrinkage_method: Literal["ledoit_wolf", "none"] = "ledoit_wolf",
        bias_correction: bool = True,
    ):
        pass

    def fit(
        self,
        returns: pl.DataFrame,  # Long format [ticker, date, return, sector]
        sector_col: str = "sector",
    ) -> np.ndarray:
        """
        Estimate block-diagonal covariance matrix.

        Algorithm:
        1. Extract factors: Y = B·F + ε
        2. Cluster residuals (predefined sectors OR hierarchical)
        3. Per-block Ledoit-Wolf shrinkage on ε
        4. Eigenvalue bias correction if p > T
        5. Reconstruct: Σ = B·Cov(F)·B^T + Ψ_block

        Returns:
            N×N positive definite covariance matrix
        """
        pass
```

**Test Specifications**:
1. `test_estimate_with_predefined_sectors`
2. `test_estimate_with_hierarchical_clustering`
3. `test_block_structure_preserved`
4. `test_positive_definite_output`
5. `test_ledoit_wolf_shrinkage_per_block`
6. `test_bias_correction_when_p_greater_than_t`
7. `test_comparison_vs_full_ledoit_wolf`

**Verification Against PDFs**:
- ✅ Paper 2, Section 2: "Factor model with block-diagonal idiosyncratic covariance"
- ✅ Paper 2, Equation (2.2): Σ = B·Cov(F)·B^T + Ψ
- ✅ Paper 2, Section 3.2: "Per-block shrinkage"
- ✅ Paper 2, Section 5: Empirical results showing "excellent Sharpe ratios"

**Agent**: Paper-2-agent
**Estimated Time**: 2-3 hours
**Dependencies**: A2 (FactorExtractor), A3 (per-block shrinkage), C1 (Bai-Ng IC), C2 (HierarchicalSectorClustering)

---

### 📋 Category D: Paper 3 Specific Tasks (Chen et al. 2025)

#### **D1. StochasticBlockCovariance (MVP Approach)**
**Status**: ⏳ TO DO
**File**: `Risk/Covariance/SectorBased/StochasticBlock/StochasticBlockCovariance.py`

**Mathematical Specification** (from Paper 3, Section 2.1):
```
Stochastic Block Model with Inter-Block Correlations:

Ψ = [Ψ₁₁   Ψ₁₂  ...  Ψ₁ₘ]
    [Ψ₂₁   Ψ₂₂  ...  Ψ₂ₘ]
    [...   ...   ⋱   ...]
    [Ψₘ₁   Ψₘ₂  ...  Ψₘₘ]

Key Difference vs BlockDiagonal:
- OFF-diagonal blocks Ψᵢⱼ (i≠j) are NON-ZERO
- Captures cross-sector correlations

MVP Implementation (simplified):
Ψ = α·BlockDiag + (1-α)·FullCov

where α ∈ [0,1] controls sparsity
```

**API Specification**:
```python
class StochasticBlockCovariance(BaseCovarianceEstimator):
    def __init__(
        self,
        n_factors: Optional[int] = None,
        allow_inter_block: bool = True,  # Key innovation
        alpha: Optional[float] = None,   # If None, auto-select
        discover_blocks: bool = False,   # Hierarchical clustering mode
        shrinkage_per_block: bool = True,
    ):
        pass

    def fit(
        self,
        returns: pl.DataFrame,
        sector_col: str = "sector",
    ) -> np.ndarray:
        """
        Estimate covariance with inter-block correlations.

        MVP Algorithm:
        1. Extract factors: Y = B·F + ε
        2. Group by sectors
        3. Compute block-diagonal component (α=1)
        4. Compute full covariance component (α=0)
        5. Blend: Ψ = α·BlockDiag + (1-α)·FullCov
        6. Reconstruct: Σ = B·Cov(F)·B^T + Ψ

        Returns:
            N×N positive definite covariance matrix
        """
        pass
```

**Test Specifications**:
1. `test_allows_inter_block_correlations`
   - Verify: Off-diagonal blocks are non-zero when allow_inter_block=True

2. `test_cross_sector_dependencies`
   - Input: Two sectors with known cross-correlation
   - Verify: Ψ₁₂ ≠ 0

3. `test_vs_block_diagonal`
   - Compare: StochasticBlock(α=1) should ≈ BlockDiagonal
   - Compare: StochasticBlock(α=0) should ≈ Full covariance

4. `test_positive_definite_output`

5. `test_alpha_parameter_effect`
   - Verify: Higher α → more block-diagonal (sparse)

6. `test_automatic_block_discovery`
   - When discover_blocks=True, use hierarchical clustering

**Verification Against PDFs**:
- ✅ Paper 3, Section 2.1: "Stochastic block structure"
- ✅ Paper 3, Figure 1: Illustration of inter-block correlations
- ✅ Paper 3, Section 3: "Hierarchical Bayesian estimation" (MVP simplifies this)

**Agent**: Paper-3-agent
**Estimated Time**: 2-3 hours (MVP), +4-6 hours (full Bayesian if needed)
**Dependencies**: A2 (FactorExtractor), A3 (per-block shrinkage)

**Note**: Full Bayesian with MCMC is optional (Phase 2 for Paper 3)

---

#### **D2. Hierarchical Bayesian Inference (Optional Phase 2)**
**Status**: ⏳ OPTIONAL (only if MVP shows limitations)
**File**: `Risk/Covariance/SectorBased/StochasticBlock/BayesianInference.py`

**Mathematical Specification** (from Paper 3, Section 3):
```
Hierarchical Bayesian Model:

Priors:
- Block membership: Dirichlet process
- Within-block covariance: Inverse-Wishart
- Cross-block correlations: Shrinkage priors

Posterior Sampling:
- MCMC (Gibbs sampler or HMC)
- Burn-in: 1000 samples
- Posterior: 1000 samples
- Convergence: Gelman-Rubin R̂ < 1.1
```

**Decision Point**: Implement only if MVP performance insufficient.

**Verification**: ✅ Paper 3, Section 3: "Hierarchical Bayesian method"

**Agent**: Paper-3-agent (Phase 2)
**Estimated Time**: 4-6 hours
**Dependencies**: D1 (MVP complete), PyMC or custom MCMC

---

## Task Dependency Graph (DAG)

```
[A1. Data Utils] ✅ DONE
      ↓
[A2. FactorExtractor] ← CRITICAL PATH (blocks all 3 papers)
      ↓
      ├─────────────────┬─────────────────┐
      ↓                 ↓                 ↓
  Paper 2           Paper 1           Paper 3
      ↓                 ↓                 ↓
[C1. Bai-Ng IC]   [B2. RMT Filter]  [D1. StochBlock MVP]
      ↓                 ↓                 ↓
[C2. HierCluster] [B3. TwoStep]     [D2. Bayesian OPTIONAL]
      ↓                 ↓
[C3. BlockDiag]       ↓
      ↓               ↓
      └───────┬───────┘
              ↓
      [A3. Per-Block
       Shrinkage]
              ↓
      [A4. Metrics]
              ↓
      [Integration
       Tests]
```

---

## Agent Assignments

### **Agent 1: FactorExtractor (Common - Critical Path)**
**Priority**: CRITICAL (blocks everything)
**Files**:
- `Risk/Covariance/SectorBased/FactorExtractor.py`
- `tests/unit/risk/covariance/sector_based/test_factor_extractor.py`

**Deliverables**:
- 6 tests written FIRST (TDD)
- Implementation passing all tests
- Commit after tests, commit after implementation
- Push both times

**Estimated Time**: 2-3 hours

---

### **Agent 2: Paper-1-Agent (García-Medina 2024)**
**Priority**: HIGH (best performer)
**Files**:
- `Risk/Covariance/SectorBased/TwoStep/RandomMatrixFilter.py`
- `Risk/Covariance/SectorBased/TwoStep/TwoStepCovariance.py`
- Tests for both

**Dependencies**:
- Wait for Agent 1 (FactorExtractor)
- Reuse HierarchicalSectorClustering from Agent 3

**Deliverables**:
- B2: RandomMatrixFilter (2-3 hours)
- B3: TwoStepCovariance (2 hours)
- All tests passing
- 4+ commits and pushes

**Estimated Time**: 4-5 hours

---

### **Agent 3: Paper-2-Agent (Žignić et al. 2024)**
**Priority**: HIGH (minimum viable)
**Files**:
- `Risk/Covariance/SectorBased/BlockDiagonal/BaiNgIC.py`
- `Risk/Covariance/SectorBased/BlockDiagonal/HierarchicalSectorClustering.py`
- `Risk/Covariance/SectorBased/BlockDiagonal/BlockDiagonalCovariance.py`
- Tests for all three

**Dependencies**:
- Wait for Agent 1 (FactorExtractor)

**Deliverables**:
- C1: Bai-Ng IC (2 hours)
- C2: HierarchicalSectorClustering (2-3 hours)
- C3: BlockDiagonalCovariance (2-3 hours)
- All tests passing
- 6+ commits and pushes

**Estimated Time**: 6-8 hours

---

### **Agent 4: Paper-3-Agent (Chen et al. 2025)**
**Priority**: MEDIUM (optional inter-block correlations)
**Files**:
- `Risk/Covariance/SectorBased/StochasticBlock/StochasticBlockCovariance.py`
- Tests

**Dependencies**:
- Wait for Agent 1 (FactorExtractor)
- Can reuse HierarchicalSectorClustering from Agent 3 if needed

**Deliverables**:
- D1: StochasticBlockCovariance MVP (2-3 hours)
- 6 tests passing
- D2: Full Bayesian (optional, +4-6 hours)
- 2+ commits and pushes

**Estimated Time**: 2-3 hours (MVP), +4-6 hours (full Bayesian)

---

### **Agent 5: Extensions-Agent (Common)**
**Priority**: LOW (can run in parallel with papers)
**Files**:
- Extend `Risk/Covariance/LedoitWolfShrinkage.py` for per-block
- `Analysis/RiskMetrics.py` (new)

**Dependencies**: None

**Deliverables**:
- A3: Per-block shrinkage extension (1-2 hours)
- A4: Metrics (HHI, Leverage, RDI) (1 hour)
- Tests for both
- 2+ commits and pushes

**Estimated Time**: 2-3 hours

---

## Execution Timeline

### **Phase 1: Critical Path (Sequential)**
**Duration**: 2-3 hours
1. Agent 1 implements FactorExtractor
2. Commit and push
3. All other agents now unblocked

### **Phase 2: Parallel Implementation**
**Duration**: 6-8 hours (wall-clock, agents run in parallel)
- Agent 2 (Paper 1): 4-5 hours
- Agent 3 (Paper 2): 6-8 hours (longest)
- Agent 4 (Paper 3): 2-3 hours (MVP)
- Agent 5 (Extensions): 2-3 hours

**Wall-Clock Time**: max(4-5, 6-8, 2-3, 2-3) = 6-8 hours

### **Phase 3: Integration & Synthesis (Sequential)**
**Duration**: 3-4 hours
1. Extract common abstractions
2. Create `SectorBasedCovarianceEstimator` abstract base class
3. Refactor all 3 to inherit
4. Performance comparison tests
5. Documentation

---

## Total Timeline

**Sequential**: ~16-24 hours
**Parallel**: ~11-15 hours wall-clock

**Savings**: ~1.5-2x speedup

---

## Verification Checklist

Before executing ANY code, verify:

- [ ] All formulas match PDF papers (equations cited)
- [ ] All test specifications written (TDD approach)
- [ ] Dependencies clearly identified
- [ ] Commit/push strategy documented
- [ ] Agent assignments orthogonal (no file conflicts)
- [ ] Resume points identified (links to sections)

---

## Resume Points (Links)

### For FactorExtractor (Agent 1):
- Formula: See Paper 2, Equation (2.1), page 3
- Tests: Section A2 above
- API: Section A2 above

### For Paper 1 (Agent 2):
- RMT Filter: Section B2 above
- TwoStep: Section B3 above
- Verification: Paper 1, Section III.B-C

### For Paper 2 (Agent 3):
- Bai-Ng IC: Section C1 above
- HierCluster: Section C2 above
- BlockDiag: Section C3 above
- Verification: Paper 2, Sections 2-3

### For Paper 3 (Agent 4):
- StochBlock MVP: Section D1 above
- Bayesian (optional): Section D2 above
- Verification: Paper 3, Sections 2-3

---

## Next Steps

1. ✅ Review this task breakdown
2. ✅ Verify against PDFs (all formulas checked)
3. ✅ Commit and push this plan
4. ⏳ Write test specifications for all agents
5. ⏳ Execute Agent 1 (FactorExtractor) - CRITICAL PATH
6. ⏳ Launch Agents 2-5 in parallel
7. ⏳ Integration and synthesis

**Status**: Plan Complete - Ready for Verification and Execution

**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
