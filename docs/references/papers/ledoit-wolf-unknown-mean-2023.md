# ABOUTME: Mathematical reference for Ledoit-Wolf shrinkage with unknown mean (Oriol & Miot 2023)
# ABOUTME: Comprehensive extraction of formulas, theorems, and implementation guidance for ARBS covariance estimation

# Ledoit-Wolf Linear Shrinkage with Unknown Mean

**Authors**: Benoît Oriol, Alexandre Miot
**arXiv ID**: Not specified (published directly)
**Published**: February 2025
**Journal**: Journal of Multivariate Analysis 208 (2025) 105429
**DOI**: 10.1016/j.jmva.2025.105429
**URL**: https://doi.org/10.1016/j.jmva.2025.105429

## Abstract

This work addresses large dimensional covariance matrix estimation with unknown mean. The empirical covariance estimator fails when dimension and number of samples are proportional and tend to infinity, settings known as Kolmogorov asymptotics. When the mean is known, Ledoit and Wolf (2004) proposed a linear shrinkage estimator and proved its convergence under those asymptotics. To the best of our knowledge, no formal proof has been proposed when the mean is unknown.

To address this issue, we propose to extend the linear shrinkage and its convergence properties to translation-invariant estimators. We expose four estimators respecting those conditions, proving their properties. Finally, we show empirically that a new estimator we propose outperforms other standard estimators.

## Key Contributions

- **Theoretical Extension**: First formal proof of Ledoit-Wolf convergence when mean is unknown
- **Translation-Invariant Estimators**: Four distinct estimators with proven asymptotic properties
- **Empirical Comparison**: LW_u estimator outperforms sklearn implementation, especially when p > n
- **Unification**: Resolves discrepancy between Ledoit-Wolf recommendations and sklearn implementation

## Problem Setting

### Notation

- **Observation Matrix**: X_n ∈ ℝ^{p_n × n} of n iid observations on p_n dimensions
- **Covariance Decomposition**: Σ_n = Γ_n Λ_n Γ_n^T where Λ_n is diagonal, Γ_n is rotation matrix
- **Eigenvalues/Eigenvectors**: λ_i^n and γ_i^n for i = 1,...,p_n
- **Uncorrelated Variables**: Y_n = Γ_n^T X_n is p_n × n matrix of uncorrelated observations

### Frobenius Norm (Normalized)

```
||A_n|| = √(tr(A_n A_n^T) / p_n)
⟨A_n, B_n⟩_n = tr(A_n B_n^T) / p_n
```

**Note**: Dividing by p_n is non-standard but fixes ||I|| = 1 regardless of dimension.

## Mathematical Formulations

### 1. Empirical Covariance (Unknown Mean)

```
S_n = X̃_n X̃_n^T / (n - 1)
```

where `(X̃_n)_ik = (X_n)_ik - (1/n) Σ_{k'=1}^n (X_n)_ik'` (demeaned observations)

**ARBS Implementation**: Line 92 in `LedoitWolfShrinkage.py`
```python
self.sample_cov = returns_clean.cov().values  # pandas uses ddof=1 by default
```

### 2. Oracle Linear Shrinkage (Corollary 1)

**Optimization Problem**:
```
minimize_{ρ1, ρ2}  E[||Σ*_n - Σ_n||²_n]
s.t. Σ*_n = ρ1 I_{p_n} + ρ2 S_n
```

**Solution**:
```
Σ*_n = (β²_n / δ²_n) μ_n I_{p_n} + (α²_n / δ²_n) S_n

E[||Σ*_n - Σ_n||²_n] = (α²_n β²_n) / δ²_n
```

where the oracle parameters are defined in Definition 2.

### 3. Oracle Parameters (Definition 2)

```
μ_n = ⟨Σ_n, I_{p_n}⟩_n                  (average variance)
α²_n = ||Σ_n - μ_n I_{p_n}||²_n          (variance of eigenvalues)
β²_n = E[||S_n - Σ_n||²_n]               (estimation error)
δ²_n = E[||S_n - μ_n I_{p_n}||²_n]       (total deviation)
```

**Key Relationship** (Lemma 2.1 in Ledoit-Wolf 2004):
```
α²_n + β²_n = δ²_n
```

### 4. Estimation Error with Unknown Mean (Theorem 1)

```
lim_{n→∞} E[||S_n - Σ_n||²_n] - (p_n/n)(μ²_n + θ²_n) = 0
```

where `θ²_n = Var[1/p_n Σ_i (y_i1^n)²]` is bounded as n→∞.

**Interpretation**: When p_n ≈ n (Kolmogorov asymptotics), sample covariance fails to converge.

### 5. Estimators (Definition 3: LW_u - Proposed)

```
S*_n = (b²_{n,u} / d²_{n,u}) m_{n,u} I_{p_n} + (a²_{n,u} / d²_{n,u}) S_n
```

where:
- `m_{n,u} = ⟨S_n, I_{p_n}⟩_n` (estimated average variance)
- `d²_{n,u} = ||S_n - m_n I_{p_n}||²_n` (estimated total deviation)
- `b²_{n,u} = min((b²_n)+, d²_n)` (estimated error, thresholded)
- `a²_{n,u} = d²_n - b²_{n,u}` (estimated eigenvalue variance)

**ARBS Implementation**: Lines 103-106 in `LedoitWolfShrinkage.py`
```python
self.cov_matrix_ = (
    self.shrinkage_intensity * self.target_matrix +
    (1 - self.shrinkage_intensity) * self.sample_cov
)
```

**Mapping**:
- `shrinkage_intensity = δ = b²_{n,u} / d²_{n,u}` (shrinkage toward target)
- `target_matrix = F = m_n I` or constant correlation model
- `(1 - δ) = a²_{n,u} / d²_{n,u}` (weight on sample covariance)

### 6. Unbiased Estimator of β²_n (Lemma 9)

**Step 1**: Define intermediate estimator b̄²_n:
```
b̄²_n = (1/n²) Σ_{k=1}^n ||n/(n-1) x̃_{·k} x̃_{·k}^T - S_n||²_n
```

where `x̃_{·k} = x_{·k} - (1/n) Σ_{k'} x_{·k'}` (centered observations)

**Step 2**: Coefficients from Lemma 4:
```
γ_n = n(n-1) / (n² - 3n + 3)
λ_n = n²(n-2) / ((n-1)(n² - 3n + 3))
c_0 = 1/γ_n - 1/n - λ_n/(γ_n n²)
c_1 = λ_n / (γ_n n²)
c_2 = (p + 1) c_1
```

**Step 3**: Express V[m_n] from Lemma 8:
```
V[m_n] = (1/(1 - q_1 - q_2)) (q_0 β²_n + q_1 E[d²_n] - q_2 E[m²_n])
```

where:
```
q_0 = (n-2) / (p(n-1))
q_1 = 1 / (p(n-1))
q_2 = (p-1) / (p(n-1))
```

**Step 4**: Final unbiased estimator:
```
b²_n = (1/c^f_0) (b̄²_n - c^f_1 d²_n - c^f_2 m²_n)
```

where:
```
c^f_0 = c_0 + (c_1 - c_2) q_0 / (1 - q_1 - q_2)
c^f_1 = c_1 + (c_1 - c_2) q_1 / (1 - q_1 - q_2)
c^f_2 = c_2 - (c_1 - c_2) q_2 / (1 - q_1 - q_2)
```

**ARBS Implementation**: Lines 205-213 in `LedoitWolfShrinkage.py`
```python
# Calculate π̂: sum of asymptotic variances
pi_hat = 0.0
for t in range(T):
    r_t = returns_centered[t:t+1, :].T
    outer_t = r_t @ r_t.T
    diff = outer_t - sample_cov
    pi_hat += np.sum(diff ** 2)
pi_hat /= T ** 2
```

This is a simplified version; the full formula in Lemma 9 is more complex.

### 7. Alternative Estimators

#### LW_r (Ledoit-Wolf Recommended, Definition 4)

Used in Ledoit-Wolf (2020) documentation:

```
m_{n,r} = m_n
d²_{n,r} = d²_n
b²_{n,r} = min((1/(n-1)² Σ_k ||x̃_{·k} x̃_{·k}^T - S_n||²_n)+, d²_{n,r})
a²_{n,r} = d²_{n,r} - b²_{n,r}
```

**Key Difference**: Uses `1/(n-1)²` instead of `1/n²` in b̄²_n calculation.

#### LW_m (Natural Estimator, Definition 5)

Naturally emerges from theory:

```
m_{n,m} = m_n
d²_{n,m} = d²_n
b²_{n,m} = min((b̄²_n)+, d²_{n,m})
a²_{n,m} = d²_{n,m} - b²_{n,m}
```

Uses b̄²_n directly without adjustment.

#### LW_s (ScikitLearn 1.2.2, Definition 6)

Currently implemented in sklearn:

```
m_{n,s} = ((n-1)/n) m_n
d²_{n,s} = d²_n
b²_{n,s} = min((b̄²_n)+, d²_{n,s})
a²_{n,s} = ((n-1)/n) (d²_{n,s} - b²_{n,s})
S*_{n,s} = ((n-1)/n) S*_{n,m}
```

**Key Difference**: Applies (n-1)/n factor to mean and final estimator.

**Note**: Paper shows LW_u outperforms LW_s, especially when p > n.

## Convergence Theory

### Assumptions

**Assumption 1 (Kolmogorov Asymptotics)**:
```
∃ K_1 independent of n: p_n / n ≤ K_1
```

**Assumption 2 (Bounded 8th Moments)**:
```
∃ K_2: (1/p_n) Σ_i E[(ỹ_i1^n)^8] ≤ K_2
```

where `ỹ_i1^n = y_i1^n - E[y_i1^n]`

**Assumption 3 (Technical Condition)**:
```
lim_{n→∞} (p²_n / n) × (Σ_{(i,j,k,l)∈Q_n} [Cov(ỹ_i1^n ỹ_j1^n, ỹ_k1^n ỹ_l1^n)]²) / |Q_n| = 0
```

where Q_n is the set of all quadruples of four distinct integers in [1, p_n].

**Satisfied by**: Gaussian, elliptical distributions (including Student-t with ν > 8).

### Main Convergence Result (Theorem 2)

```
E[||S*_n - Σ*_n||²] → 0

E[||S*_n - Σ_n||²_n] - E[||Σ*_n - Σ_n||²_n] → 0
```

**Interpretation**: Estimator S*_n achieves same asymptotic loss as oracle Σ*_n.

### Optimality (Theorem 3 & 4)

**Theorem 3**: S*_n converges to Σ**_n (optimal with random coefficients):
```
||S*_n - Σ**_n|| →_{q.m.} 0
E[|||S*_n - Σ_n||²_n - ||Σ**_n - Σ_n||²_n|] → 0
```

**Theorem 4**: S*_n is asymptotically optimal among all linear combinations:
```
lim_{N→∞} inf_{n≥N} (E[||Σ̂_n - Σ_n||²_n] - E[||S*_n - Σ_n||²_n]) ≥ 0
```

for any sequence Σ̂_n = ρ_1 I_n + ρ_2 S_n.

### Convergence Rates

From Lemma 11:
```
E[|a²_{n,u} b²_{n,u} / d²_n - α²_n β²_n / δ²_n|] → 0
```

This provides asymptotic estimation of the optimal error.

## Oracle Formulas for Specific Distributions

### Gaussian Distribution (Lemma 12)

For X_{·,k} ~ N(0, Σ_n), k ∈ [1,n], n iid samples:

```
μ_n = ⟨Σ_n, I⟩_n
α²_n = ||Σ_n||²_n - μ²_n
β²_n = ((p+1)/(n-1)) μ²_n + (1/(n-1)) α²_n
δ²_n = α²_n + β²_n
```

### Student-t Distribution (Lemma 13)

For X_{·,k} ~ t_ν(0, Σ̃_n), k ∈ [1,n], with scale matrix Σ̃_n = ((ν-2)/ν) Σ_n and covariance V[X_n] = Σ_n:

```
μ_n = ⟨Σ_n, I⟩
α²_n = ||Σ_n||²_n - μ²_n
β²_n = (1/n)(ν/(ν-4) + 1/(n-1))(α²_n + (p+1)μ²_n) - (2p)/(n(ν-4)) μ²_n
δ²_n = α²_n + β²_n
```

**Requirements**: ν > 8 for Assumption 2; ν > 4 shown experimentally robust.

## Empirical Results Summary

### Experimental Setup

- **Monte Carlo**: 10,000 iterations
- **Distributions**: Gaussian, Student-t (ν = 10, 8.5, 4.5), mixed t-distributions
- **Covariance**: Fixed (Σ = I) and random (Wishart-normalized)
- **Concentration ratios**: c = p/n ∈ {0.25, 0.5, 1, 2, 4}

### Key Findings

1. **LW_u consistently outperforms others**, especially when p > n
2. **When c = 1**: All linear shrinkage estimators perform similarly
3. **When c > 1**: LW_u shows significant advantage (factor 2-10x improvement)
4. **When c < 0.5**: Differences are small; GIS (geometric-inverse shrinkage) slightly better
5. **Heavy tails (ν = 4.5)**: Linear shrinkage remains robust; GIS performance degrades
6. **ScikitLearn implementation (LW_s)**: Underperforms LW_u, contradicts Ledoit-Wolf recommendations

### Performance Comparison (c = 1, Gaussian, Σ = I)

Relative loss vs. LW_op (optimal):
- **LW_u**: ~2-3× LW_op (best linear shrinkage)
- **LW_s, LW_r, LW_m**: ~3-4× LW_op
- **GIS**: Not defined at c = 1
- **OAS**: ~5-6× LW_op (Gaussian-specific)
- **Sample Cov**: ~10-20× LW_op

### Computational Cost

All Ledoit-Wolf variants have similar O(N²T) complexity. Non-linear methods (GIS, analytical shrinkage) are 10-100× slower.

## ARBS Implementation Cross-Reference

### File: `/home/user/ARBS/Risk/Covariance/LedoitWolfShrinkage.py`

#### Shrinkage Formula (Lines 103-106)

**Paper**: Definition 3
```
S*_n = (b²_{n,u} / d²_{n,u}) m_{n,u} I_{p_n} + (a²_{n,u} / d²_{n,u}) S_n
```

**ARBS**:
```python
self.cov_matrix_ = (
    self.shrinkage_intensity * self.target_matrix +
    (1 - self.shrinkage_intensity) * self.sample_cov
)
```

**Mapping**:
- `shrinkage_intensity = δ = b²_n / d²_n`
- `target_matrix = F` (constant correlation or other target)
- Note: ARBS uses flexible target F, not just μI

#### Sample Covariance (Line 92)

**Paper**: Definition 1
```
S_n = X̃_n X̃_n^T / (n - 1)
```

**ARBS**:
```python
self.sample_cov = returns_clean.cov().values  # ddof=1 by default
```

#### Shrinkage Intensity Calculation (Lines 174-231)

**Paper**: Lemma 9 (complex formula with coefficients)

**ARBS**: Simplified version
```python
# π̂: asymptotic variance
pi_hat = (1/T²) Σ_t ||r_t r_t^T - S||²

# ρ̂: squared Frobenius norm of (S - F)
rho_hat = ||S - F||²

# δ = max(0, min(1, κ/T)) where κ = π̂/ρ̂
delta = max(0, min(1, pi_hat / (T * rho_hat)))
```

**Note**: This is the original Ledoit-Wolf (2004) formula for known mean. The unknown mean case (Lemma 9) requires more complex coefficients c^f_0, c^f_1, c^f_2.

#### Target Matrix Options

**Constant Correlation** (Lines 138-172):
```python
# Average correlation ρ̄
avg_corr = mean(off_diagonal(corr_matrix))

# Target: F_ij = ρ̄ σ_i σ_j for i≠j, σ_i² for i=j
```

**Paper**: This is mentioned as the Ledoit-Wolf default target but not extensively analyzed in the unknown mean paper.

### Improvements Needed in ARBS

1. **Update shrinkage intensity calculation** (Lines 174-231):
   - Current: Uses Ledoit-Wolf (2004) known-mean formula
   - Should: Implement Lemma 9 from Oriol-Miot (2023) for unknown mean
   - Impact: More accurate δ when p ≈ n

2. **Add LW_u estimator option**:
   - Current: Implements flexible target (constant correlation, diagonal, identity)
   - Should: Add `method='lw_u'` vs `method='lw_s'` parameter
   - Impact: 2-10× better performance when p > n

3. **Validate against oracle**:
   - Add Lemma 12 (Gaussian) and Lemma 13 (Student-t) oracle formulas for testing
   - Verify convergence properties match Theorem 2

## Implementation Checklist for ARBS

- [ ] **Critical**: Replace simplified shrinkage intensity with Lemma 9 formula
  - [ ] Implement coefficients c^f_0, c^f_1, c^f_2 from Lemma 4
  - [ ] Implement V[m_n] estimation from Lemma 8
  - [ ] Calculate b̄²_n from demeaned observations
  - [ ] Apply thresholding: b²_n = min((b²_n)+, d²_n)

- [ ] **Important**: Add estimator variants
  - [ ] Add `estimator='lw_u'` (recommended, default)
  - [ ] Add `estimator='lw_s'` (sklearn compatibility)
  - [ ] Add `estimator='lw_r'` (Ledoit-Wolf 2020 recommendation)
  - [ ] Add `estimator='lw_m'` (natural estimator)

- [ ] **Testing**: Add oracle tests
  - [ ] Test against Lemma 12 (Gaussian oracle)
  - [ ] Test against Lemma 13 (Student-t oracle)
  - [ ] Verify convergence with synthetic data (p/n varying)

- [ ] **Documentation**: Update docstrings
  - [ ] Reference Oriol-Miot (2023) for unknown mean
  - [ ] Reference Ledoit-Wolf (2004) for known mean
  - [ ] Explain when to use LW_u vs LW_s

## References

1. **Ledoit, O., & Wolf, M. (2004)**. "A well-conditioned estimator for large-dimensional covariance matrices." *Journal of Multivariate Analysis*, 88(2), 365-411.
   - Original shrinkage estimator with known mean
   - >5000 citations

2. **Oriol, B., & Miot, A. (2025)**. "Ledoit-Wolf linear shrinkage with unknown mean." *Journal of Multivariate Analysis*, 208, 105429.
   - Extension to unknown mean (this paper)
   - First formal convergence proof for unknown mean case

3. **Ledoit, O., & Wolf, M. (2020)**. "The power of (non-)linear shrinking: A review and guide to covariance matrix estimation." *Journal of Financial Econometrics*, 20(1), 187-218.
   - Review paper with implementation recommendations

4. **Ledoit, O., & Wolf, M. (2020)**. "Analytical nonlinear shrinkage of large-dimensional covariance matrices." *Annals of Statistics*, 48(5), 3043-3065.
   - Non-linear shrinkage (more complex, better performance)

## Conclusion

The Oriol-Miot (2023) paper provides the first rigorous theoretical foundation for Ledoit-Wolf shrinkage with unknown mean. Key takeaways:

1. **Four estimators** with proven convergence (LW_u, LW_r, LW_m, LW_s)
2. **LW_u is optimal** in finite samples, especially when p > n
3. **ScikitLearn implements LW_s**, which underperforms LW_u
4. **ARBS should update** to LW_u for better performance

The paper resolves theoretical gaps and provides practical guidance for practitioners using shrinkage estimators in high-dimensional settings.
