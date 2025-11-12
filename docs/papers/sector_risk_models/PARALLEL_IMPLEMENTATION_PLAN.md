# Parallel Implementation Plan - Sector Risk Models

**Date**: 2025-11-12
**Strategy**: Identify common vs. distinct components, implement in parallel

---

## Why Parallel Subagents?

By implementing all 3 approaches simultaneously, we will:
1. **Discover natural abstractions** - Common patterns emerge organically
2. **Avoid premature optimization** - See what's truly shared vs. specific
3. **Save time** - Parallelization reduces wall-clock time
4. **Better design** - Abstract base class informed by all 3 implementations

---

## Common Components (Shared by All 3 Papers)

### 1. **FactorExtractor** (PCA-based)
**Used by**: All 3 papers
**Formula**: Y = B·F + ε
- Extract K common factors via PCA
- Compute loadings matrix B (p×K)
- Compute residuals ε = Y - B·F

**Agent Task**: Implement FactorExtractor with TDD
**Estimated Time**: 2-3 hours
**Priority**: Critical (blocks all 3 approaches)

---

### 2. **Data Format Utilities** (sector_utils.py)
**Used by**: All 3 papers
**Functions**:
- ✅ validate_sector_data() - Already done
- ✅ long_to_wide() - Already done
- ✅ extract_sector_mapping() - Already done
- ✅ create_block_diagonal_matrix() - Already done

**Status**: ✅ Complete (148 lines + tests)

---

### 3. **Base Covariance Estimator Interface**
**Used by**: All 3 papers
**Existing**: `BaseCovarianceEstimator` (already in ARBS)
**Interface**:
- `fit(returns: pl.DataFrame) → np.ndarray`
- `get_covariance() → np.ndarray`
- `condition_number() → float`

**Note**: All 3 implementations must follow this interface

---

## Distinct Components (Paper-Specific)

### Paper 1: Žignić et al. (2024) - Block-Diagonal Factor Model

**Unique Components**:

#### A. **HierarchicalSectorClustering**
**Purpose**: Discover sector structure adaptively
**Formula**: D_ij = (|Ŝ_ij| / √(θ̂_ij·T^(-1)·log p))^(-1)
**Methods**:
- Adaptive thresholding distance
- Agglomerative clustering (ward/average/weighted)
- Cross-validation for cluster count

**Agent Task**: Implement HierarchicalSectorClustering with TDD
**Estimated Time**: 2-3 hours
**Dependency**: FactorExtractor (for residuals)

---

#### B. **BlockDiagonalCovariance**
**Purpose**: Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)
**Methods**:
- Per-block Ledoit-Wolf shrinkage
- Eigenvalue bias correction (when p > T)
- Two clustering modes: predefined sectors OR hierarchical

**Agent Task**: Implement BlockDiagonalCovariance with TDD
**Estimated Time**: 2-3 hours
**Dependencies**: FactorExtractor, HierarchicalSectorClustering

---

### Paper 2: García-Medina (2024) - Two-Step Hierarchical + RMT

**Unique Components**:

#### C. **RandomMatrixFilter**
**Purpose**: Filter noise eigenvalues using Marčenko-Pastur theory
**Formula**: λ_+ = σ²(1 + √(p/T))²
**Methods**:
- Marčenko-Pastur threshold calculation
- Eigenvalue cleaning (replace λ < λ_+ with λ_+)
- Noise level estimation (median or robust)

**Agent Task**: Implement RandomMatrixFilter with TDD
**Estimated Time**: 2-3 hours
**Dependency**: None (standalone)

---

#### D. **TwoStepCovariance**
**Purpose**: Combine hierarchical clustering (Step 1) + RMT filtering (Step 2)
**Methods**:
- Step 1: Cluster residuals hierarchically
- Step 2: Apply RMT filtering per cluster
- Best performance (García-Medina result)

**Agent Task**: Implement TwoStepCovariance with TDD
**Estimated Time**: 2 hours
**Dependencies**: HierarchicalSectorClustering, RandomMatrixFilter

---

### Paper 3: Chen et al. (2025) - Stochastic Block Model

**Unique Components**:

#### E. **StochasticBlockCovariance**
**Purpose**: Allow inter-block correlations via Bayesian inference
**Difference**: Ψ has OFF-diagonal blocks (not pure block-diagonal)
**Methods**:
- Hierarchical Bayesian priors
- MCMC sampling (PyMC or custom)
- Simultaneous block discovery + covariance estimation

**Agent Task**: Implement StochasticBlockCovariance with TDD
**Estimated Time**: 4-6 hours (more complex)
**Dependencies**: FactorExtractor, PyMC (optional)

---

## Parallelization Strategy

### **Phase 1: Common Components** (Sequential)

Run these first (they block everything):

1. ✅ **sector_utils.py** - DONE (148 lines)
2. **FactorExtractor** - CRITICAL (blocks all 3)

**Wall-Clock Time**: 2-3 hours

---

### **Phase 2: Parallel Implementation** (3 Agents in Parallel)

Launch 3 agents simultaneously:

#### **Agent 1: BlockDiagonal Implementation**
**Tasks**:
1. Implement HierarchicalSectorClustering (2-3 hours)
2. Implement BlockDiagonalCovariance (2-3 hours)
3. Integration tests (1 hour)

**Total Time**: 5-7 hours

---

#### **Agent 2: TwoStep Implementation**
**Tasks**:
1. Implement RandomMatrixFilter (2-3 hours)
2. Implement TwoStepCovariance (2 hours)
3. Integration tests (1 hour)

**Total Time**: 5-6 hours

**Note**: This agent can start immediately after Phase 1 (FactorExtractor done)

---

#### **Agent 3: StochasticBlock Implementation**
**Tasks**:
1. Research PyMC integration (1 hour)
2. Implement StochasticBlockCovariance (4-6 hours)
3. Integration tests (1 hour)

**Total Time**: 6-8 hours

**Note**: Most complex, may finish after Agents 1-2

---

### **Phase 3: Synthesis** (Sequential)

After all 3 agents complete:

1. **Abstract Base Class**
   - Extract common patterns from all 3 implementations
   - Create `SectorBasedCovarianceEstimator` (abstract class)
   - Refactor all 3 to inherit from it

2. **Performance Comparison**
   - Run all 3 on same dataset
   - Compare Sharpe, HHI, leverage, R²_out
   - Validate paper claims

3. **Documentation**
   - Usage examples for each approach
   - When to use which method
   - Performance benchmarks

**Total Time**: 3-4 hours

---

## Task Dependencies (DAG)

```
[sector_utils.py] ✅ DONE
        ↓
[FactorExtractor] ← CRITICAL PATH (blocks all 3)
        ↓
    ┌───┴───┬───────────┐
    ↓       ↓           ↓
 Agent 1  Agent 2    Agent 3
(BlockD) (TwoStep) (StochB)
    ↓       ↓           ↓
    └───┬───┴───────────┘
        ↓
   [Synthesis]
   - Abstract base class
   - Performance comparison
   - Documentation
```

---

## Total Timeline Estimate

**Sequential (no parallelization)**: 16-24 hours

**With Parallelization**:
- Phase 1 (sequential): 2-3 hours
- Phase 2 (parallel, max of 3 agents): 6-8 hours
- Phase 3 (synthesis): 3-4 hours
- **Total**: 11-15 hours wall-clock time

**Speedup**: ~1.5-2x faster

---

## Agent Task Breakdown

### **Task 1: FactorExtractor (Shared)**
**Agent**: general-purpose
**Input**: Implement FactorExtractor based on IMPLEMENTATION_PLAN.md
**Output**:
- `Risk/Covariance/SectorBased/FactorExtractor.py` (200-250 lines)
- `tests/unit/risk/covariance/sector_based/test_factor_extractor.py` (300-350 lines)
- All tests passing

---

### **Task 2: BlockDiagonal (Agent 1)**
**Agent**: general-purpose
**Input**: Implement BlockDiagonal components (HierarchicalSectorClustering + BlockDiagonalCovariance)
**Output**:
- `Risk/Covariance/SectorBased/BlockDiagonal/HierarchicalSectorClustering.py`
- `Risk/Covariance/SectorBased/BlockDiagonal/BlockDiagonalCovariance.py`
- Full test suite
- Integration tests

---

### **Task 3: TwoStep (Agent 2)**
**Agent**: general-purpose
**Input**: Implement TwoStep components (RandomMatrixFilter + TwoStepCovariance)
**Output**:
- `Risk/Covariance/SectorBased/TwoStep/RandomMatrixFilter.py`
- `Risk/Covariance/SectorBased/TwoStep/TwoStepCovariance.py`
- Full test suite
- Integration tests

---

### **Task 4: StochasticBlock (Agent 3)**
**Agent**: general-purpose
**Input**: Implement StochasticBlock components
**Output**:
- `Risk/Covariance/SectorBased/StochasticBlock/StochasticBlockCovariance.py`
- Full test suite
- PyMC integration OR custom MCMC
- Integration tests

---

## Expected Outcome

After all agents complete, we will have:

1. **3 Working Implementations**
   - BlockDiagonalCovariance (Žignić et al.)
   - TwoStepCovariance (García-Medina)
   - StochasticBlockCovariance (Chen et al.)

2. **Common Abstractions**
   - Abstract base class (informed by all 3)
   - Shared utilities (already done)
   - Consistent interfaces

3. **Comprehensive Tests**
   - Unit tests for each component
   - Integration tests for each approach
   - Performance comparison tests

4. **Performance Validation**
   - Reproduce paper results
   - Compare all 3 methods
   - Identify best use cases

---

## Success Criteria

### **Phase 1 Complete When**:
- ✅ FactorExtractor implemented with tests
- ✅ All FactorExtractor tests passing
- ✅ Committed and pushed

### **Phase 2 Complete When**:
- ✅ All 3 agents have completed their tasks
- ✅ All tests passing for each approach
- ✅ All code committed and pushed

### **Phase 3 Complete When**:
- ✅ Abstract base class extracted and implemented
- ✅ All 3 approaches refactored to use base class
- ✅ Performance comparison complete
- ✅ Documentation written
- ✅ Integration with ARBS validated

---

**Status**: Plan Complete - Ready to Launch Parallel Agents

**Next Action**: Implement FactorExtractor (Phase 1), then launch 3 agents in parallel (Phase 2)
