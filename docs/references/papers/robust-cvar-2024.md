# Portfolio Optimization with Robust Covariance and CVaR Constraints

**Author**: Qiqin Zhou (Cornell University)
**Source**: `/home/user/ARBS/docs/papers/advanced/robust-cvar-2024.pdf`
**Relevance**: Downside risk management, robust covariance estimation, tail risk constraints

## Executive Summary

This paper explores robust covariance estimators and CVaR (Conditional Value-at-Risk) constraints for portfolio optimization. Key finding: **robust covariance methods outperform benchmarks in bull markets but fail during extreme events (COVID-19)**. Adding CVaR constraints significantly improves tail risk management, reducing maximum drawdown by 4-9% compared to unconstrained portfolios.

**Key Result**: Gerber covariance with MAD + one CVaR constraint (α=95%, β=5%) achieved:
- 40.45% annual return
- 1.45 Sharpe ratio
- 22.90% max drawdown (vs 30.50% without CVaR)

## 1. Conditional Value-at-Risk (CVaR) Constraints

### 1.1 Motivation and Definition

**Problem**: Traditional Markowitz mean-variance optimization pays little attention to controlling extreme risks. After the 2008 financial crisis, tail risk measures became critical.

**CVaR Definition** (Rockafellar & Uryasev, 2000):
- VaR estimates the minimum loss at a given probability/quantile
- **CVaR = expected loss given that loss exceeds the VaR threshold**
- Calculated as weighted average of losses in the tail of the return distribution
- More coherent and sub-additive than VaR

**Why CVaR > VaR**: Alexander & Baptista (2004) showed CVaR constraints are more effective than VaR constraints for controlling risk for slightly risk-averse agents.

### 1.2 Mathematical Formulation

**Minimum Variance with CVaR Constraint**:

```
min_{w,l} w^T V w + λ ||w - w₀||₁

s.t. w^T 1_N = 1
     l + (1/(1-α)) Σ_{ω∈Ω} P(ω) max(loss(w,ω) - l, 0) ≤ β
```

Where:
- `w`: portfolio weight vector
- `V`: estimated covariance matrix (N×N)
- `λ`: transaction cost parameter (50 bps)
- `w₀`: weights at beginning of rebalance period
- `α`: confidence level (e.g., 0.95 = 95%)
- `β`: CVaR threshold (e.g., 0.05 = 5% max expected loss in tail)
- `l`: VaR level (optimization variable)
- `loss(w,ω)`: portfolio loss in scenario ω, sampled from historical returns

**Sample Space**: Uses historical return samples as Ω with probability P(ω) = 1/T for each observation.

### 1.3 Implementation: One vs Two CVaR Constraints

**Scenario 1: Single CVaR Constraint**
- α₁ = 0.95, β₁ = 0.05 (95% confidence, max 5% loss in tail)
- Uses 400 weekly samples for estimation
- Results: **9% reduction in max drawdown** compared to unconstrained (30% → 21%)

**Scenario 2: Two CVaR Constraints**
- α₁ = 0.95, β₁ = 0.05 (95% confidence)
- α₂ = 0.99, β₂ = 0.08 (99% confidence, max 8% loss in extreme tail)
- Results: Additional 2% reduction in drawdown (21% → 19%)
- **Conclusion**: One CVaR constraint is usually adequate; second constraint provides diminishing returns

### 1.4 Empirical Performance Results

**Test Period**: Dec 2018 - Dec 2021 (includes COVID-19 crash)
**Universe**: Top 5 stocks in each of 11 S&P 500 sectors (55 total)
**Rebalancing**: Weekly

| Portfolio | Ann Return | Ann Vol | Max DD | Sharpe | Sortino |
|-----------|-----------|---------|--------|--------|---------|
| **No CVaR Constraint** |
| Market | 31.91% | 23.16% | 25.59% | 1.10 | - |
| Gerber_Mad | 39.03% | 23.06% | 30.50% | 1.25 | - |
| **One CVaR (α=95%, β=5%)** |
| Gerber_Mad | 40.45% | 20.01% | 22.90% | 1.45 | 1.54 |
| Ledoit | 34.44% | 20.25% | 21.92% | 1.29 | 1.35 |
| **Two CVaR (α₁=95%, β₁=5%; α₂=99%, β₂=8%)** |
| Gerber_Mad | 35.90% | 18.75% | 21.19% | 1.42 | 1.55 |
| Ledoit | 29.64% | 18.85% | 20.09% | 1.24 | 1.34 |

**Key Observations**:
1. CVaR reduces max drawdown by 4-9% vs market
2. CVaR reduces volatility by 3% on average
3. Sharpe ratio improves by 0.2+ with CVaR
4. **Sortino ratio > Sharpe ratio**: Confirms downside risk is better controlled than upside
5. Transaction costs increase slightly (turnover: 8% → 14-16%)

### 1.5 Weight Concentration During Tail Events

**Interesting Finding**: During March 2020 (COVID crash), CVaR portfolios concentrated 30%+ weight in Clorox (CLX). This indicates:
- CVaR constraint forces optimizer to find defensive positions
- May reduce diversification during extreme events
- Trade-off between tail risk control and concentration risk

## 2. Robust Covariance Estimation Methods

### 2.1 The Instability Problem

**Core Issue**: Sample covariance matrix V̂ produces unstable optimal weights ω* where small input changes cause large weight changes. This instability has two sources:

1. **Noise instability**: Financial data contains outliers and measurement noise
2. **Signal instability**: High correlations between assets cause covariance matrix V to be near-singular, making V⁻¹ unstable

### 2.2 Ledoit-Wolf Shrinkage Covariance

**Approach**: Shrink sample covariance toward a more stable structure.

**Formula**:
```
Σ_shrink = δF + (1-δ)S
```

Where:
- `S`: sample covariance matrix
- `F`: structured target (constant correlation model)
- `δ`: shrinkage intensity (0 to 1)

**Constant Correlation Model**:
```
f_ii = s_ii  (keep individual variances)
f_ij = ρ̄ √(s_ii × s_jj)  (shrink correlations to average)

ρ̄ = (2/(N(N-1))) Σᵢ Σⱼ>ᵢ ρ_ij
```

**Optimal Shrinkage δ* (Ledoit & Wolf 2004)**:
Minimizes Frobenius norm between true covariance and estimator:
```
δ* = κ = (π - ρ) / γ
```
Where π, ρ, γ are functions of asymptotic variances and covariances of matrix entries.

**Empirical Observation**: During COVID-19 (March 2020), optimal δ → 1, meaning the estimator completely abandoned historical samples in favor of the stable structure. This may be too conservative.

### 2.3 Gerber Robust Covariance

**Motivation**: Standard covariance relies on product-moments, which are sensitive to outliers. Financial data has many outliers that distort correlations.

**Key Innovation**: Only count co-movements that exceed a threshold, ignoring:
- Small movements (noise)
- Extreme outliers (don't let magnitude dominate)

**Gerber Statistic for Asset Pair (i,j)**:

Define co-movement indicator at time t:
```
m_ij(t) = {
  +1  if r_ti ≥ +H_i and r_tj ≥ +H_j  (both exceed upper threshold)
  +1  if r_ti ≤ -H_i and r_tj ≤ -H_j  (both exceed lower threshold)
  -1  if r_ti ≥ +H_i and r_tj ≤ -H_j  (opposite directions)
  -1  if r_ti ≤ -H_i and r_tj ≥ +H_j  (opposite directions)
   0  otherwise                        (no significant co-movement)
}
```

Where threshold: `H_k = c × s_k` (c is tuning parameter, s_k is scale measure)

**Gerber Statistic**:
```
g_ij = Σ_t m_ij(t) / Σ_t |m_ij(t)|
     = (n^c_ij - n^d_ij) / (n^c_ij + n^d_ij)
```

- `n^c_ij`: number of concordant pairs (same direction)
- `n^d_ij`: number of discordant pairs (opposite directions)

**Matrix Form**:
```
G = (N_CONC - N_DISC) ⊘ (N_CONC + N_DISC)

N_CONC = U^T U + D^T D  (concordant)
N_DISC = U^T D + D^T U  (discordant)

Σ_GS = diag(σ) G diag(σ)  (scale to covariance)
```

**Threshold Scale Options**:
1. Standard deviation (less robust)
2. **Median Absolute Deviation (MAD)** - more robust to outliers

```
MAD = median_i |y_i - median_j(y_j)|
σ̂ ≈ 1.4826 × MAD  (for normal distribution)
```

**Optimal Parameters** (from cross-validation):
- Gerber with MAD: c = 0.4
- Gerber with StdDev: c = 0.6

**Positive Definite Adjustment**: Gerber matrix not guaranteed to be positive definite. Paper uses optimization:

```
min_Σ (1/2) ||Σ̂ - Σ_Gerber||²_F

s.t. λ_min(Σ̂) > 0
     0.25 λ_max(Σ̂) ≤ λ_min(Σ̂)  (condition number control)
```

**Performance**: Gerber_Mad was the best performer, achieving highest Sharpe ratio (1.25 without CVaR, 1.45 with CVaR).

### 2.4 Nested Clustering Optimization (NCO)

**Motivation**: Even robust covariance estimators exhibit signal instability when assets are highly correlated. NCO prevents instability from spreading across the entire portfolio.

**Two-Step Approach**:

1. **De-noising**: Remove noise-driven eigenvalues using Marcenko-Pastur theory
2. **Clustering**: Partition assets into clusters to contain signal instability

#### Step 1: De-noising via Marcenko-Pastur Distribution

For random matrix X (T observations, N features) with variance σ², eigenvalues converge to:

```
f_λ(λ) = {
  (T/N) √((λ⁺-λ)(λ-λ⁻)) / (2πλσ²)  if λ ∈ [λ⁻, λ⁺]
  0                                   otherwise
}

λ⁺ = σ²(1 + √(N/T))²  (max expected eigenvalue)
λ⁻ = σ²(1 - √(N/T))²  (min expected eigenvalue)
```

**Procedure**:
1. Fit empirical eigenvalue distribution with Kernel Density Estimation
2. Compare to Marcenko-Pastur to find cutoff λ⁺
3. Set all eigenvalues below λ⁺ to their average:
   ```
   λ_j = (1/(N-i)) Σ_{k=i+1}^N λ_k  for j = i+1,...,N
   ```
   where i is position where λ_i > λ⁺ and λ_{i+1} ≤ λ⁺

4. Reconstruct: `C̃ = Q Λ̃ Q^T` then rescale diagonal to 1

#### Step 2: Clustering to Contain Signal Instability

**Why Clustering Helps**: When assets are highly correlated (|ρ| → 1), determinant |C| → 0 and top eigenvalue explodes, making C⁻¹ unstable. Clustering restricts this instability within subgroups.

**NCO Algorithm**:
```
Input: Sample covariance matrix V

1. Obtain de-noised covariance V̂ and correlation Ĉ
2. Cluster Ĉ into K groups using K-means
   - Choose K by maximizing Silhouette Coefficient Z-score
3. Intra-cluster optimization:
   - Run min-variance on each of K clusters
   - Get K×N weight matrix Ω_intra
4. Reduce covariance: V_reduced = Ω_intra^T V̂ Ω_intra (K×K matrix)
5. Inter-cluster optimization:
   - Run min-variance on K "funds"
   - Get Ω_inter ∈ R^K
6. Final weights: Ω_intra^T Ω_inter

Output: Optimal weights on N original assets
```

**Performance Results**:
- Annual return: 21.12% (lower than unconstrained)
- Annual volatility: 19.72% (lowest among all methods)
- Max drawdown: 24.51% (5% better than unconstrained ~30%)
- More diversified: No asset > 20% weight
- Trade-off: Higher turnover (25.13%)

**Conclusion**: NCO reduces tail risk and improves stability, but at cost of lower returns and higher turnover.

## 3. ARBS Relevance: Downside Risk Management

### 3.1 Direct Applications to ARBS

**Current ARBS Architecture Alignment**:
1. ✅ **Covariance Estimation**: ARBS uses LedoitWolfShrinkage (22 tests passing)
2. ✅ **Mean-Variance Optimization**: ARBS has MeanVarianceOptimizer (18 tests)
3. ❌ **CVaR Constraints**: Not currently implemented in ARBS
4. ❌ **Gerber Covariance**: Not currently implemented in ARBS
5. ❌ **NCO**: Not currently implemented in ARBS

**Recommended Integration Path**:

```python
# Extension 1: Add CVaR constraint to optimizer
class CVaRConstrainedOptimizer(BaseOptimizer):
    """
    Mean-variance optimizer with CVaR tail risk constraint.

    Parameters
    ----------
    alpha : float
        Confidence level for CVaR (e.g., 0.95)
    beta : float
        Maximum acceptable CVaR (e.g., 0.05 = 5% tail loss)
    historical_returns : pd.DataFrame
        Required for CVaR calculation (400+ samples recommended)
    """

# Extension 2: Add Gerber covariance estimator
class GerberCovariance(BaseCovariance):
    """
    Robust covariance using Gerber statistic.

    Parameters
    ----------
    threshold_multiplier : float
        Multiplier for threshold (c parameter), default 0.4 for MAD
    scale_method : {'mad', 'std'}
        Method for computing threshold scale
    positive_definite : bool
        Whether to apply PD optimization adjustment
    """

# Extension 3: Add Nested Clustering Optimization
class NestedClusteredOptimizer(BaseOptimizer):
    """
    NCO wrapper that applies de-noising and clustering.

    Wraps any base optimizer to apply NCO methodology.
    """
```

### 3.2 Key Lessons for ARBS Implementation

**1. One CVaR Constraint is Usually Sufficient**
- α = 0.95, β = 0.05 captures most tail risk
- Second constraint (α = 0.99) provides diminishing returns
- Keep it simple: one constraint avoids over-constraint

**2. Gerber Covariance with MAD Outperforms**
- More robust to outliers than sample or Ledoit covariance
- Use MAD instead of standard deviation for threshold
- Requires positive definite adjustment via SDP

**3. Transaction Cost Modeling is Critical**
- Paper uses L1 regularization: `λ ||w - w₀||₁` with λ = 50 bps
- ARBS should implement similar transaction cost penalties
- CVaR increases turnover 2x (8% → 16%), must account for costs

**4. Historical Sample Requirements**
- Standard covariance: 200 weekly samples (4 years)
- CVaR constraints: 400 weekly samples (8 years) recommended
- More samples needed for tail risk estimation

**5. Regime-Dependent Behavior**
- Robust covariance works well in bull markets (+8% excess return)
- **All methods fail in extreme bear markets** (COVID-19: 30% drawdown)
- CVaR constraints help but don't eliminate tail risk
- ARBS should not expect robust methods to prevent crashes

### 3.3 Open Questions for ARBS

**1. Futures vs Equities**:
- Paper tests on 55 S&P 500 large-cap stocks
- Do results generalize to futures markets?
- Futures may have different correlation structures

**2. Transaction Costs in Futures**:
- Paper uses 50 bps proportional costs
- Futures have different cost structure (commissions + slippage)
- May need to adjust λ parameter

**3. DV01 Constraints**:
- ARBS needs fixed income risk limits (not in paper)
- Can CVaR constraints substitute for DV01 limits?
- Probably need both: CVaR for tail risk, DV01 for duration risk

**4. Integration with Signal Pipeline**:
- Paper uses minimum variance (no alpha signals)
- ARBS uses: Signals → Alpha → Optimizer
- How to combine CVaR with alpha-driven optimization?
- Possible: `min -α^T w + w^T V w + CVaR_constraint`

### 3.4 Priority Ranking for ARBS Implementation

**High Priority** (MVP V2):
1. ✅ Already done: LedoitWolfShrinkage covariance
2. **CVaR constraints**: Most impactful for tail risk (9% drawdown reduction)
3. **Transaction cost L1 penalty**: Essential for realistic backtesting

**Medium Priority** (Post-MVP):
4. **Gerber covariance**: Incremental improvement over Ledoit (1.25 vs 1.12 Sharpe)
5. **Historical sample management**: Need 400+ samples for CVaR

**Low Priority** (Future Research):
6. **NCO**: Complex, high turnover, reduces returns (but more stable)
7. **Two CVaR constraints**: Diminishing returns vs one constraint

## 4. Mathematical Reference

### 4.1 CVaR Optimization (Rockafellar & Uryasev 2000)

**CVaR Definition**:
```
VaR_α(w) = inf{l : P(loss(w) ≤ l) ≥ α}

CVaR_α(w) = E[loss(w) | loss(w) ≥ VaR_α(w)]
```

**Computational Form**:
```
CVaR_α(w) = min_l { l + (1/(1-α)) E[max(loss(w) - l, 0)] }
```

**Discrete Sample Approximation**:
```
CVaR_α(w) ≈ l + (1/(1-α)) (1/T) Σ_{t=1}^T max(-r_t^T w - l, 0)
```

Where `r_t` is return vector at time t, `loss = -r^T w`

### 4.2 Condition Number and Instability

For correlation matrix C with high correlations:
```
C = [1   ρ]
    [ρ   1]

det(C) = 1 - ρ²
λ₁ = 1 + ρ
λ₂ = 1 - ρ

κ(C) = λ_max/λ_min = (1+ρ)/(1-ρ)
```

As ρ → 1:
- det(C) → 0 (near-singular)
- κ(C) → ∞ (ill-conditioned)
- C⁻¹ becomes unstable

This is why clustering helps: keeps high correlations within clusters, lower correlations between clusters.

## 5. Implementation Notes

### 5.1 Data Requirements

**Sample Sizes**:
- Minimum variance: 200 weekly observations (4 years)
- CVaR constraints: 400 weekly observations (8 years)
- Exponential weighting: α = 0.94 typical (similar to RiskMetrics)

**Cross-Validation**:
- 5-fold CV on training set (50% of data)
- Each fold: 25 weekly rebalances (~6 months)
- Metric: Sharpe ratio
- Tune: Ledoit δ, Gerber c parameter

### 5.2 Rebalancing Procedure

```
For each week t:
  1. Use rolling window of past 200 weeks (or 400 for CVaR)
  2. Estimate covariance matrix V_t
  3. Solve optimization with current weights w_{t-1}
  4. Get new weights w_t
  5. Calculate transaction cost: TC = λ ||w_t - w_{t-1}||₁
  6. Hold portfolio for 1 week
  7. Record realized return minus transaction cost
  8. Update weights due to price movement
  9. Remove any delisted stocks (charge liquidation fee)
```

### 5.3 Optimization Solver

**Convex Formulation**: All problems in paper are convex:
- Minimum variance: Quadratic program (QP)
- L1 penalty: Second-order cone program (SOCP)
- CVaR constraint: Linear program (LP) after auxiliary variable transformation

**Recommended Solvers**:
- CVXPY (Python): Handles all formulations
- MOSEK or GUROBI: Fast commercial solvers
- OSQP: Open-source QP solver for minimum variance

## 6. References

**Core Papers**:
1. **Rockafellar & Uryasev (2000)**: "Optimization of Conditional Value-at-Risk", Journal of Risk
2. **Ledoit & Wolf (2004)**: "Honey, I Shrunk the Sample Covariance Matrix", Journal of Portfolio Management
3. **Gerber et al. (2022)**: "The Gerber Statistic: A Robust Co-Movement Measure", Journal of Portfolio Management
4. **López de Prado (2019)**: "A Robust Estimator of the Efficient Frontier", SSRN 3469961
5. **Alexander & Baptista (2004)**: "A Comparison of VaR and CVaR Constraints", Management Science

**Supporting Literature**:
- Marcenko & Pastur (1967): Random matrix eigenvalue distribution
- Rousseeuw (1987): Silhouette Coefficient for clustering
- Kritzman et al. (2010): "In Defense of Optimization: The Fallacy of 1/N"

## 7. Conclusion

**What Works**:
- ✅ Robust covariance (Ledoit, Gerber) beats benchmark in normal markets
- ✅ CVaR constraints significantly reduce tail risk (9% drawdown improvement)
- ✅ One CVaR constraint is sufficient for most applications
- ✅ L1 regularization controls transaction costs effectively

**What Doesn't Work**:
- ❌ No method prevents extreme losses during black swans (COVID-19)
- ❌ Two CVaR constraints provide diminishing returns
- ❌ NCO improves stability but reduces returns and increases turnover

**For ARBS**:
Implement CVaR constraints as highest priority extension. Use existing LedoitWolf covariance, add CVaR tail risk constraint, and incorporate L1 transaction cost penalty. This provides best risk-adjusted returns with manageable implementation complexity.
