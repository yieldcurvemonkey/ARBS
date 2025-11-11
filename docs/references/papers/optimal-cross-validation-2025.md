# Optimal Data Splitting for Holdout Cross-Validation in Large Covariance Matrix Estimation

**Authors**: Lamia Lamrani, Christian Bongiorno, Marc Potters
**Institution**: Université Paris-Saclay, CentraleSupélec; Capital Fund Management
**Date**: September 18, 2025
**Source**: `/home/user/ARBS/docs/papers/advanced/optimal-cross-validation-2025.pdf`

## Executive Summary

This paper provides analytical results for optimal train-test splitting in cross-validation for covariance matrix estimation. Key finding: **optimal split scales as √n** (square root of matrix dimension), not fixed percentages. Critical for ARBS: holdout method preserves temporal ordering and prevents data leakage from future to past.

---

## 1. Cross-Validation for Covariance Estimation

### 1.1 Core Problem

**High-dimensional regime**: When matrix dimension `n` is comparable to number of observations `t`, sample covariance estimator is inefficient.

**Aspect ratio**: `q = n/t` determines information loss:
- When `q = 0`: sample estimator = population covariance
- Larger `q` → larger estimation error

**Expected Frobenius error of sample covariance** (eq. 17):
```
E[||E - Σ||²_F] = q
```
where `E` is sample covariance, `Σ` is population covariance.

### 1.2 Cross-Validation Methods

**Two main approaches**:

1. **Holdout method** (single split):
   - Split data once into train (in-sample) and test (out-of-sample)
   - Use train eigenvectors with test eigenvalues
   - Can preserve temporal ordering

2. **k-fold CV** (multiple splits):
   - Partition into k folds
   - Average over k holdout estimations
   - Cannot preserve temporal ordering (future data contaminates past)

### 1.3 Holdout Estimator Definition

**Holdout estimator** (eq. 26):
```
Ξ^H = V_in * Diag(V_in^T * E_out * V_in) * V_in^T
```

where:
- `V_in` = eigenvectors of train sample covariance `E_in`
- `E_out` = test sample covariance
- `Diag(·)` = diagonal operator

**Key insight**: Use train eigenvectors (structural information) with test eigenvalues (validation).

---

## 2. Holdout Strategies and Optimal Splitting

### 2.1 General Holdout Error Formula

**Main result** - Expected Frobenius error (Proposition 3.1, eq. 42):

```
E[||Ξ^H - Σ||²_F] = (2/t_out - 1) * E[τ(Λ^O(V_in, Σ)²)] + E[τ(Σ²)]
```

where:
- `t_out` = number of test samples
- `Λ^O` = oracle eigenvalues (Ledoit-Péché formula)
- `τ(A) = (1/n) * Tr(A)` = normalized trace

**Interpretation**: Error depends on:
1. Oracle eigenvalue variance (how much shrinkage helps)
2. Population covariance variance
3. Train-test split ratio `2/t_out - 1`

### 2.2 White Inverse Wishart Case (Closed Form)

For **white inverse Wishart population** with parameters `(n, p)`, closed-form solution (Proposition 3.2, eq. 47):

```
E[||Ξ^H - Σ||²_F] = (2k/t - 1) * (p²/(p + kn/(kt-t)) + 1) + 1 + p
```

where `k = t/t_out` is train-test ratio.

### 2.3 Optimal Split Formula

**Optimal k that minimizes error** (Corollary 3.1, eq. 56):

```
k_opt = p * [2q + p(2 + 2p + q) + p*√(2q² + 2n(p+q)(p+p²+q))] / [2(p+q)(p+p²+q)]
```

**Asymptotic behavior** (eq. 57):
```
k_opt ~ √n * p / √(2(p+q)(p+p²+q))
```

**Key finding**: Optimal split **scales with square root of matrix dimension** `√n`, not constant percentage.

### 2.4 Convergence to Oracle Estimator

**Convergence result** (Corollary 3.2, eq. 58):

If `1 ≪ k ≪ n`, then in high-dimensional limit:
```
lim_{n→∞} E[||Ξ^H - Σ||²_F] = lim_{n→∞} E[||Ξ^O - Σ||²_F]
```

Holdout converges to oracle estimator error:
```
pq/(p+q)
```

which is **better than sample covariance error** `q` for any `p > 0`.

### 2.5 Practical Recommendations

**Traditional CV wisdom**: Use 10-30% for test set (fixed percentage)

**This paper's finding**: Optimal split depends on `√n`:
- For `n = 100`: different optimal split than `n = 1000`
- **Counterintuitive result**: Optimal `k ≈ 1.5` can mean test set is **twice as large** as train set

**Empirical observation** (Figure 2):
- Error has sharp minimum, not plateau
- Finite-sample effects create distinct optimal point
- Choice of split particularly important in practice

---

## 3. ARBS Backtesting Relevance

### 3.1 Temporal Ordering and Data Leakage

**Critical advantage of holdout over k-fold CV** (Section 2.2.2, page 2):

> "Differently from the k-fold and LOO CV, the holdout can **respect the causality of time series** if the train and test data are ordered and if the test data is chosen posterior to the train."

**Why this matters for ARBS**:
- Financial backtesting requires strict temporal ordering
- Cannot use future information to estimate past covariances
- k-fold CV inherently mixes temporal periods
- Holdout with sequential split preserves causality

### 3.2 Finance-Specific Considerations

**From conclusion** (Section 4, page 13):

> "This allows for the **prevention of data leakage from future eigenvectors to past eigenvectors**, a safeguard that is impossible to implement with k-fold CV but naturally achievable with the holdout method. We believe this feature is **particularly relevant in fields like finance**, where preventing data leakage from future information is crucial for reliable model validation."

**Application to ARBS**:
1. **Covariance estimation**: Critical for portfolio optimization in mean-variance framework
2. **Risk models**: Need accurate covariance without forward-looking bias
3. **Walk-forward validation**: Holdout naturally extends to walk-forward testing
4. **Non-stationary data**: Finance data is non-stationary; temporal holdout more appropriate

### 3.3 High-Dimensional Portfolio Context

**When applicable to ARBS**:
- Multi-asset futures portfolios (n assets, t observations)
- Typical regime: `n = 50-200` assets, `t = 500-2000` observations
- Aspect ratio `q = n/t` in range `[0.025, 0.4]`
- High-dimensional asymptotics become relevant

**Covariance estimation methods in ARBS**:
- Current: Ledoit-Wolf shrinkage (Linear shrinkage)
- This paper: Provides theoretical foundation for CV-based validation
- Could use: Holdout CV to tune shrinkage intensity `δ`

### 3.4 Implementation Strategy for ARBS

**Suggested workflow**:

1. **Expanding window setup**:
   ```
   Train period: t_start to t_split
   Test period: t_split to t_split + t_out
   ```

2. **Optimal split calculation**:
   - Compute `k_opt` based on `√n` scaling
   - For `n = 100`, `p ≈ 1`, `q = 0.2`: `k_opt ≈ 5-10`
   - Test period: `t_out = t/k_opt`

3. **Covariance estimation**:
   - Estimate covariance on train period with shrinkage
   - Validate on test period Frobenius error
   - Tune shrinkage parameter to minimize test error

4. **Walk-forward extension**:
   - Roll forward by `t_out` periods
   - Re-estimate with new train/test split
   - Maintains temporal ordering throughout

### 3.5 Connection to Existing ARBS Architecture

**Current ARBS risk models** (from CLAUDE.md):
- `SampleCovariance`: Baseline estimator
- `LedoitWolfShrinkage`: Linear shrinkage toward identity
- Could add: `HoldoutCVCovariance` using this paper's methodology

**Validation framework**:
```python
class HoldoutCVCovariance:
    """Cross-validated covariance estimator using optimal split.

    Based on: Lamrani et al. (2025) optimal holdout methodology
    """

    def __init__(self, shrinkage_method='ledoit_wolf'):
        self.shrinkage_method = shrinkage_method

    def compute_optimal_split(self, n: int, t: int) -> int:
        """Compute k_opt ~ sqrt(n) scaling."""
        # Implement eq. 56 or use simplified sqrt(n) heuristic
        pass

    def fit(self, returns: np.ndarray) -> np.ndarray:
        """Fit covariance with holdout validation.

        Args:
            returns: (t, n) array of asset returns

        Returns:
            Covariance matrix (n, n) optimized via holdout CV
        """
        n, t = returns.shape[1], returns.shape[0]
        k_opt = self.compute_optimal_split(n, t)
        t_out = int(t / k_opt)
        t_in = t - t_out

        # Train-test split (temporal ordering preserved)
        returns_train = returns[:t_in]
        returns_test = returns[t_in:]

        # Estimate on train, validate on test
        # ... (shrinkage parameter tuning)
```

---

## 4. Key Formulas Reference

### 4.1 Sample Covariance Error
```
E[||E - Σ||²_F] = q = n/t
```

### 4.2 Oracle Estimator Error (White Inverse Wishart)
```
E[||Ξ^O - Σ||²_F] = pq/(p+q)
```

### 4.3 Holdout Error (General)
```
E[||Ξ^H - Σ||²_F] = (2/t_out - 1) * E[τ(Λ^O²)] + E[τ(Σ²)]
```

### 4.4 Optimal Split Scaling
```
k_opt ~ c * √n
```
where `c` depends on `p`, `q` but optimal split **always scales with √n**.

### 4.5 Convergence Condition
Holdout → Oracle when:
```
1 ≪ k ≪ n
```

---

## 5. Practical Implications for ARBS

### 5.1 When to Use Holdout CV

**Use holdout CV for covariance when**:
1. **High-dimensional regime**: `n/t > 0.1` (aspect ratio meaningful)
2. **Temporal data**: Time series where ordering matters (all finance)
3. **Model selection**: Choosing shrinkage intensity or method
4. **Validation**: Testing covariance estimator out-of-sample

**Don't use if**:
1. **Low-dimensional**: `n ≪ t` (sample covariance sufficient)
2. **I.I.D. data**: No temporal structure (can use k-fold)
3. **Small datasets**: `t < 100` (insufficient data for split)

### 5.2 Parameter Guidelines

**For ARBS typical scale** (`n = 100`, `t = 1000`):

- **Aspect ratio**: `q = 0.1`
- **Optimal k**: `k_opt ≈ 5-10` (from √n scaling)
- **Test period**: `t_out = 100-200` observations
- **Train period**: `t_in = 800-900` observations

**Walk-forward frequency**:
- Re-estimate every `t_out/2` periods (50-100 days)
- Maintains overlap between train periods
- Reduces variance from single split

### 5.3 Comparison to Standard Practice

| Method | Split | Temporal Order | Theory |
|--------|-------|----------------|--------|
| Fixed 70/30 | Arbitrary constant | Optional | Heuristic |
| k-fold CV (k=10) | 90/10 repeated | **Violated** | Asymptotic |
| LOO CV | (t-1)/1 repeated | **Violated** | High variance |
| **Optimal holdout** | **k ~ √n dependent** | **Preserved** | **Finite-sample optimal** |

### 5.4 Covariance Cleaning Pipeline

**Recommended ARBS workflow**:

1. **Estimate**: Compute sample covariance on train period
2. **Clean**: Apply shrinkage (Ledoit-Wolf, RMT methods)
3. **Validate**: Check Frobenius error on test period
4. **Tune**: Adjust shrinkage intensity based on test error
5. **Deploy**: Use validated covariance for optimization
6. **Roll**: Advance window and repeat

**Error metric** (eq. 16):
```
||Ξ - Σ||²_F = τ((Ξ - Σ)²)
```

In practice, use test sample covariance as proxy for unknown Σ.

---

## 6. Theoretical Foundations

### 6.1 Random Matrix Theory Connection

**Key RMT concepts used**:

1. **Wishart distribution**: Sample covariance distribution under Gaussian data
2. **Inverse Wishart**: Population covariance prior (conjugate)
3. **Marcenko-Pastur law**: Limiting eigenvalue distribution
4. **Ledoit-Péché formula**: Oracle eigenvalues (eq. 21)

**Oracle estimator** (eq. 19):
```
Ξ^O(E, Σ) = V * Diag(V^T Σ V) * V^T
```

Uses sample eigenvectors `V` with "cleaned" eigenvalues.

### 6.2 Wick's Theorem Application

**Key technique** (Theorem 3.1, eq. 37):

For Gaussian data, moments of sample covariance reduce to products of population covariances via Wick's theorem:

```
E[x₁x₂...xᵣ] = Σ_{p∈P₂} ∏_{(i,j)} Cov(xᵢ, xⱼ)
```

Allows analytical derivation of holdout error formula.

### 6.3 Convergence Results

**Lam's theorem** (Theorem 2.2):

Under regularity conditions, holdout error converges to NLS error if:
```
t_in/t → 1 as t → ∞
t_out → ∞ as t → ∞
Σ_{t≥1} n/t_out^5 < ∞
```

**This paper's contribution**:
- Finite-sample formula (not just asymptotics)
- Explicit optimal split (not just convergence rate)
- White inverse Wishart closed form

---

## 7. Limitations and Extensions

### 7.1 Assumptions in Paper

**Required for closed-form solution**:
1. **Gaussian data**: Wick's theorem application
2. **White inverse Wishart population**: `Σ ~ Inv-Wishart(t*, (t*-n-1)·I)`
3. **High-dimensional limit**: `n, t → ∞` with `q = n/t` fixed
4. **Small p**: Population parameter `p ≪ n`

**ARBS reality check**:
- Financial returns: Not Gaussian (fat tails)
- Population covariance: Not white (correlations exist)
- Sample size: Large but finite (n=100, t=1000)

**Still useful because**:
- Provides theoretical guidance on split scaling
- Qualitative insights hold beyond specific assumptions
- Can validate empirically on financial data

### 7.2 Extensions for ARBS

**Future research directions**:

1. **Non-Gaussian noise**:
   - Use robust covariance estimators
   - Validate holdout methodology under fat tails

2. **Structured covariance**:
   - Factor models (Fama-French)
   - Block-diagonal structure (sector clustering)
   - Graph-based models

3. **Non-stationary data**:
   - Exponential weighting in train period
   - Time-varying optimal split
   - Adaptive window sizing

4. **Transaction costs**:
   - Covariance estimation error impacts turnover
   - Holdout validation with trading costs objective

### 7.3 Open Questions

**For ARBS implementation**:

1. **Multi-period optimization**:
   - Paper considers single-period covariance
   - Backtests need rolling window
   - How often to re-optimize split?

2. **Small-sample corrections**:
   - Formula assumes large n, t
   - What adjustments for n=50, t=500?

3. **Alternative error metrics**:
   - Frobenius norm: element-wise error
   - Portfolio variance: investor-relevant error
   - Sharpe ratio: ultimate performance metric

---

## 8. References and Further Reading

### 8.1 Core Citations

**Covariance estimation**:
- Ledoit & Péché (2011): Non-linear shrinkage theory
- Ledoit & Wolf (2012, 2017): Practical NLS implementation
- Bun et al. (2017): Random matrix theory tools

**Cross-validation**:
- Lam (2016): NERCOME estimator, convergence results
- Bartz (2016): k-fold CV for covariance
- Abadir et al. (2014): Design-free variance estimation

**Random matrix theory**:
- Potters & Bouchaud (2020): "A First Course in Random Matrix Theory"
- Laloux et al. (1999): Financial correlation matrices

### 8.2 Related ARBS Documentation

**See also**:
- `/home/user/ARBS/docs/references/papers/ledoit-wolf-shrinkage.md` (if exists)
- `/home/user/ARBS/docs/references/papers/random-matrix-theory-finance.md` (if exists)
- ARBS Risk Model documentation
- ARBS Covariance estimation module

---

## 9. Implementation Checklist for ARBS

### 9.1 Immediate Actions

- [ ] Verify current covariance estimation method (Ledoit-Wolf)
- [ ] Check aspect ratio `q = n/t` in typical ARBS backtest
- [ ] Compute optimal holdout split using `k ~ √n` heuristic
- [ ] Implement temporal train-test split (respect causality)

### 9.2 Validation Tasks

- [ ] Compare Ledoit-Wolf with holdout CV tuning
- [ ] Measure Frobenius error on test periods
- [ ] Check if `k_opt` formula applies to financial data
- [ ] Validate improvement in out-of-sample Sharpe ratio

### 9.3 Long-term Research

- [ ] Extend to non-Gaussian returns (robust covariance)
- [ ] Test on multiple asset universes (equities, futures, bonds)
- [ ] Compare walk-forward CV with fixed parameters
- [ ] Publish results in ARBS backtesting framework

---

## Summary for ARBS Development

**Key takeaway**: Optimal train-test split for covariance validation scales as **√n**, not fixed percentage.

**For ARBS portfolios** with 50-200 assets:
- **Traditional**: 80/20 or 70/30 split (arbitrary)
- **This paper**: `k ≈ 5-15` (depending on n), implying 85-95% train, 5-15% test
- **Critical feature**: Holdout preserves temporal ordering (prevents data leakage)

**Immediate value**:
1. Theoretical justification for walk-forward validation window sizing
2. Method to tune covariance shrinkage intensity out-of-sample
3. Prevents overfitting in risk model estimation

**Implementation priority**: Medium-High
- Core infrastructure exists (Ledoit-Wolf covariance)
- Extension to holdout CV is straightforward
- Could improve backtest reliability meaningfully

**Next steps**:
1. Implement `HoldoutCVCovariance` estimator
2. Add to risk model factory
3. Compare with current fixed Ledoit-Wolf in backtests
4. Measure impact on realized Sharpe ratios
