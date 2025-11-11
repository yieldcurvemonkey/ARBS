# Sector-Based Covariance for ARBS Futures/Swaps

**Created**: 2025-11-11
**Status**: Research → Implementation Planning

---

## The Mental Model

**Equity Long-Short** → **Futures/Swaps Portfolio**

| Equity Structure | ARBS Structure | Correlation Pattern |
|-----------------|----------------|---------------------|
| Sector (Tech, Healthcare, Energy) | Currency (USD, EUR, GBP, JPY) | Medium (30-60%) |
| Stock within sector | Maturity within currency (3M, 6M, 1Y, 2Y) | Very High (90%+) |
| Cross-sector stocks | Cross-currency same maturity | Low-Medium (20-50%) |

**Key Insight**: Each currency is like a sector. Instruments within a currency (different maturities) are highly correlated like stocks in the same sector.

---

## Papers Downloaded

### 1. **Adaptive Multi-task Learning for Multi-sector Portfolio Optimization**
- **File**: `docs/papers/multi_sector_portfolio_optimization_2507.16433.pdf` (436KB)
- **Authors**: Qingliang Fan, Ruike Wu, Yanrong Yang
- **arXiv**: 2507.16433 (July 2025)

**Key Method**: **Projection-Penalized Factor Model (PPFM)**
- Jointly performs factor analysis across multiple sectors
- Learns relatedness among principal temporal subspaces (factors)
- Improves both factor recovery AND portfolio optimization

**Why Relevant**:
- Handles multi-sector structure (like multi-currency)
- Quantifies relatedness between sectors (USD vs EUR correlation)
- Data-adaptive (doesn't assume fixed structure)

### 2. **Hierarchical Minimum Variance Portfolios**
- **File**: `docs/papers/hierarchical_minimum_variance_2503.12328.pdf` (1.1MB)
- **Author**: Gamal Mograby
- **arXiv**: 2503.12328 (March 2025)

**Key Method**: **Schur Complement Hierarchical Decomposition**
- Models covariance as hierarchical graph structure
- Recursive decomposition across hierarchical levels
- Inverts only small submatrices (efficient)

**Why Relevant**:
- Perfect for currency (top level) → maturity (bottom level) hierarchy
- Computationally efficient even with many instruments
- Preserves full covariance information

### 3. **Stochastic Block Covariance Matrix Estimation**
- **File**: `docs/papers/stochastic_block_covariance_2502.11332.pdf` (7.1MB)
- **Authors**: Yunran Chen, Surya T Tokdar, Jennifer M Groh
- **arXiv**: 2502.11332 (February 2025)

**Key Method**: **Hierarchical Bayesian Block Structure**
- Block structure with shared covariation within blocks
- Correlated covariation across blocks
- Simultaneously recovers latent blocks AND estimates covariance

**Why Relevant**:
- Theoretical foundation for block structures
- Can learn block assignments (which instruments cluster together)
- Goes beyond diagonal blocks (allows cross-block correlation)

---

## ARBS Structure Mapping

### Example Portfolio

**Currencies (4)**: USD, EUR, GBP, JPY
**Maturities (6)**: 3M, 6M, 1Y, 2Y, 5Y, 10Y
**Total Instruments**: 4 × 6 = 24 futures contracts

### Covariance Matrix Structure (24×24)

```
           USD              EUR              GBP              JPY
     3M 6M 1Y 2Y 5Y 10Y | 3M 6M 1Y 2Y 5Y 10Y | ...
USD  [  Within-USD block  ] [  USD-EUR  ] [  USD-GBP  ] [  USD-JPY  ]
3M   [  Very high (95%)  ] [  Med (40%)  ] ...
6M   [  correlations     ]
...

EUR  [  USD-EUR block    ] [  Within-EUR  ] ...
3M   [  Medium (40%)     ] [  High (95%)  ]
...
```

**Three Levels of Correlation**:
1. **Within-currency, adjacent maturities**: 95%+ (e.g., USD 3M vs USD 6M)
2. **Within-currency, distant maturities**: 85%+ (e.g., USD 3M vs USD 10Y)
3. **Cross-currency, same maturity**: 30-60% (e.g., USD 3M vs EUR 3M)

---

## Implementation Approaches

### Approach 1: Block-Diagonal with Ledoit-Wolf (Simple)

**Structure**:
```
Σ = Block-diag(Σ_USD, Σ_EUR, Σ_GBP, Σ_JPY) + ε_off-diagonal
```

**Method**:
1. Estimate each currency block separately using Ledoit-Wolf
2. Shrink off-diagonal cross-currency correlations toward zero
3. Combine into full matrix

**Pros**:
- Simple to implement (use existing LedoitWolf per block)
- Respects high within-currency correlation
- Computationally fast

**Cons**:
- Ignores cross-currency correlation structure
- Loses diversification benefits across currencies
- Not optimal for multi-currency portfolios

**Implementation Effort**: 2-3 days
**Code Location**: `Risk/Covariance/BlockDiagonalCovariance.py`

---

### Approach 2: Two-Level Hierarchical (Medium Complexity)

**Structure**:
```
Level 1: Currency-level factors (4 factors for 4 currencies)
Level 2: Maturity-level factors within each currency (2-3 factors each)
```

**Method** (Based on Mograby's hierarchical approach):
1. Extract currency-level principal components (level/slope/curvature per currency)
2. Model residual correlation within currency using 2-3 factors
3. Use Schur complement for efficient inversion

**Pros**:
- Captures both within and cross-currency structure
- Dimensionality reduction (24 → ~12 factors)
- Computationally efficient

**Cons**:
- More complex implementation
- Requires understanding of hierarchical decomposition
- May over-smooth if factor structure weak

**Implementation Effort**: 1-2 weeks
**Code Location**: `Risk/Covariance/HierarchicalCovariance.py`

---

### Approach 3: Multi-Task Factor Model (Complex, Optimal)

**Structure** (Based on Fan et al. PPFM):
```
For each currency c:
  r_c,t = B_c × f_c,t + ε_c,t  (factor model)

Learn: Relatedness between f_USD, f_EUR, f_GBP, f_JPY
```

**Method**:
1. Extract factors for each currency separately
2. Learn projection penalties that quantify cross-currency factor relatedness
3. Joint estimation improves both factor recovery and covariance

**Pros**:
- Theoretically optimal (paper shows empirical gains)
- Adaptive to data (learns currency relationships)
- Best out-of-sample performance

**Cons**:
- Complex implementation (projection-penalized PCA)
- Requires optimization framework (CVXPY or similar)
- Longer development time

**Implementation Effort**: 3-4 weeks
**Code Location**: `Risk/Covariance/MultiTaskFactorCovariance.py`

---

## Recommendation (Phased Approach)

### Phase 1: Validate the Mental Model (1-2 days)

**Goal**: Confirm ARBS data matches equity sector structure

**Tasks**:
1. Load real futures returns (USD/EUR/GBP STIR futures)
2. Calculate empirical correlation matrix
3. Verify:
   - Within-currency correlation: 85%+ ✓ or ✗
   - Cross-currency correlation: 30-60% ✓ or ✗
   - Block structure visible ✓ or ✗

**Deliverable**: `docs/research/arbs_correlation_structure.md` with heatmap

**Code**: Quick analysis script in `scripts/analyze_correlation_structure.py`

---

### Phase 2: Implement Block-Diagonal Baseline (2-3 days)

**Goal**: Simple improvement over full Ledoit-Wolf

**Tasks**:
1. Create `BlockDiagonalCovariance` class
2. Estimate each currency block with Ledoit-Wolf
3. Shrink cross-currency correlations
4. Test against current Ledoit-Wolf implementation

**Deliverable**: Working `BlockDiagonalCovariance.py` + tests

**Success Criteria**:
- Better condition number than LedoitWolf
- Lower out-of-sample variance for GMV portfolio
- Faster computation (parallel block estimation)

---

### Phase 3: Backtest Comparison (3-4 days)

**Goal**: Empirical validation on real strategies

**Tasks**:
1. Run existing carry strategy with:
   - Sample Covariance (baseline)
   - Ledoit-Wolf (current)
   - BlockDiagonal (new)
2. Compare:
   - Sharpe ratio
   - Turnover
   - Max drawdown
   - Condition number

**Deliverable**: `docs/research/block_diagonal_backtest_results.md`

**Decision Point**:
- If BlockDiagonal wins → ship it, done for MVP
- If no improvement → investigate why (may need Phase 4)

---

### Phase 4 (Optional): Hierarchical or Multi-Task

**Only if**:
- Block-diagonal shows promise but not enough
- Cross-currency correlations are significant (>50%)
- Team has bandwidth for complex implementation

**Timeline**: 2-4 weeks

---

## Expected Outcomes

### Hypothesis

**For STIR Futures** (like SOFR 3M, 6M, 1Y):
- Within-currency correlation: **~95%** (dominated by same rate level)
- Cross-currency correlation: **~40%** (all influenced by global rates)
- Block structure: **Clear and strong**

**Prediction**: Block-diagonal approach will provide:
- 20-30% better condition number vs full Ledoit-Wolf
- 10-15% lower out-of-sample variance
- 2-3× faster computation (parallel blocks)

### If Hypothesis is Wrong

**Scenario 1**: Cross-currency correlation is very high (>70%)
- **Action**: Block structure doesn't help, stick with full Ledoit-Wolf

**Scenario 2**: Within-currency correlation varies widely
- **Action**: Need adaptive blocks, move to Phase 4 (hierarchical)

**Scenario 3**: No clear block structure
- **Action**: Currency/maturity mental model wrong for this data
- **Fallback**: MTP2 (total positivity) or factor models

---

## Success Metrics

### For Block-Diagonal Implementation

1. **Condition Number**: κ(Σ) < 50 (currently ~80 with Ledoit-Wolf)
2. **Out-of-Sample Variance**: 10%+ reduction vs current
3. **Computation**: < 0.5 seconds for 24 instruments
4. **Backtest Sharpe**: Match or exceed current Ledoit-Wolf

### For Hierarchical Implementation (if pursued)

1. **Factor Interpretability**: Can we explain level/slope/curvature?
2. **Dimensionality Reduction**: 24 instruments → 8-12 factors
3. **Performance**: 15%+ improvement in out-of-sample metrics
4. **Generalization**: Works across different currency sets

---

## Implementation Priority

**Immediate** (This week):
1. ✅ Download papers (DONE)
2. Analyze ARBS correlation structure
3. Validate sector mental model

**Short-term** (Next 1-2 weeks):
4. Implement BlockDiagonalCovariance
5. Backtest comparison
6. Decision on Phase 4

**Medium-term** (If valuable):
7. Hierarchical or Multi-Task implementation
8. Production deployment
9. Documentation

---

## Code Structure

```
Risk/Covariance/
├── SampleCovariance.py              # Baseline
├── LedoitWolfShrinkage.py          # Current default
├── OAShrinkage.py                   # Small sample
├── BlockDiagonalCovariance.py      # NEW: Phase 2
├── HierarchicalCovariance.py       # NEW: Phase 4 (optional)
└── MultiTaskFactorCovariance.py    # NEW: Phase 4 (optional)

tests/unit/risk/
├── test_block_diagonal.py          # NEW
├── test_hierarchical.py            # NEW (if Phase 4)
└── test_covariance_comparison.py   # UPDATE: add new methods

docs/research/
├── SECTOR_COVARIANCE_PLAN.md       # This file
├── arbs_correlation_structure.md   # Phase 1 output
└── block_diagonal_backtest_results.md  # Phase 3 output
```

---

## References

1. **Fan, Q., Wu, R., & Yang, Y. (2025)**. "Adaptive Multi-task Learning for Multi-sector Portfolio Optimization." arXiv:2507.16433.
   - Multi-sector factor models with learned relatedness

2. **Mograby, G. (2025)**. "Hierarchical Minimum Variance Portfolios: A Theoretical and Algorithmic Approach." arXiv:2503.12328.
   - Hierarchical decomposition with Schur complement

3. **Chen, Y., Tokdar, S. T., & Groh, J. M. (2025)**. "Stochastic Block Covariance Matrix Estimation." arXiv:2502.11332.
   - Bayesian block structure estimation

---

## Next Steps

**For Peter to decide**:

1. Should we proceed with Phase 1 (validate structure) first?
2. Or jump straight to Phase 2 (implement BlockDiagonal)?
3. What's the priority: speed vs optimality?

**My recommendation**:
- Start with Phase 1 (2 days) to validate the mental model
- If confirmed, implement Phase 2 (3 days)
- Total: 1 week to working implementation
- Defer Phase 4 until we have empirical evidence it's needed
