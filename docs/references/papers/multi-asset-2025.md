# Multi-Asset Mean-Variance Portfolio Selection using Reinforcement Learning

**Source**: Li, Y., Wu, Y., & Zhang, S. (2025). The Exploratory Multi-Asset Mean-Variance Portfolio Selection using Reinforcement Learning. arXiv:2505.07537v1

**Date**: May 12, 2025

**Relevance to ARBS**: Cross-asset risk modeling, covariance estimation, multi-curve portfolio allocation

---

## Executive Summary

This paper develops a Soft Actor-Critic (SAC) reinforcement learning algorithm for continuous-time multi-asset mean-variance portfolio optimization. Key innovation is **decoupled learning** of immediate factors (returns, covariance) vs long-term factors (average profitability), improving stability and accuracy in multi-asset contexts.

---

## Cross-Asset Risk Modeling

### Covariance Structure

The paper models the covariance matrix as:

```
Σ = DLD^T
```

Where:
- **D** = diag{σ^(1)(t), ..., σ^(n)(t)} - diagonal volatility matrix
- **L** = correlation coefficient matrix with ρ^(ij) ∈ [-1, 1]
- Time-dependent volatilities σ^(i)(t) for each asset

**Key insight**: "The correlation coefficients between risky assets are crucial factors differentiating multi-asset financial markets from single-asset ones" (p. 18)

### Covariance Estimation Methods

The paper reviews multiple approaches:

1. **Shrinkage Estimators** (Ledoit & Wolf 2003, 2004):
   - Linearly combine sample covariance with structured models
   - Balance low bias of sample estimation vs low variance of structural models
   - "Minimize mean squared error and enhance robustness in high-dimensional scenarios" (p. 2)

2. **Inverse Covariance Shrinkage** (Won et al. 2013, Shi et al. 2020):
   - Applied directly to portfolio optimization
   - Eigenvalue regularization without requiring matrix inversion
   - **Used in this paper's implementation** (Algorithm 3, line 8)

3. **Double Shrinkage** (Candelon et al. 2012):
   - First: Bayes-Stein shrinkage to covariance matrix
   - Second: Regularize portfolio toward equally-weighted benchmark
   - Reduces sampling error in small samples

### Robustness Testing

Tested across correlation levels: ρ^(12) = {0, 0.05, 0.10, 0.15}

**Result**: "In all the simulated financial markets, the relative errors of μ^(1) - r, μ^(2) - r and K(0,T) decrease in a consistent and stable manner" (p. 18)

---

## Asset Allocation Framework

### Optimal Portfolio Formula

```
Θ*_t = (τ/2γ - w)Σ^(-1)(μ - r)
```

**Three critical parameters**:

1. **μ - r ∈ R^(n×1)**: Excess expected return vector
2. **Σ^(-1) ∈ R^(n×n)**: Inverse covariance matrix
3. **K(0,T) ∈ R**: Average profitability over investment horizon

Where:
```
K(0,T) = (1/T) ∫_0^T (μ - r)^T Σ^(-1)(μ - r) ds
```

**Economic interpretation**: K(0,T) is the time-averaged squared Sharpe ratio of the multi-asset portfolio.

### Decomposition of Average Profitability

**Theorem 2.1**: When market is stationary (μ, Σ time-independent):

```
K(0,T) = [√K^(1)(0,T), ..., √K^(n)(0,T)] L^(-1) [√K^(1)(0,T), ..., √K^(n)(0,T)]^T
```

Where K^(i)(0,T) = (1/T)∫_0^T [(μ^(i)(s) - r)/σ^(i)(s)]^2 ds for each asset.

**Implication**: Multi-asset profitability explicitly depends on correlation structure L^(-1).

### Decoupled Learning Algorithm

**Key innovation**: Separate immediate vs long-term factors

**Immediate factors** (time-dependent, learned independently):
- μ^(i) - r for each asset i (Algorithm 1)
- Σ^(-1) via shrinkage (Shi et al. 2020)

**Long-term factor** (constant over horizon):
- K(0,T) learned jointly (Algorithm 2)

**Rationale**: "When learning long-term factors, we focus on exploring stable patterns embedded in macroeconomic trends and industry prospects, avoiding the interference of immediate factors, and thus improving the stability of the learning process." (p. 3)

---

## Relevance to ARBS Multi-Curve Strategies

### Applicable Concepts

1. **Multi-Curve Context**:
   - Framework handles n correlated assets naturally
   - Each "asset" could represent exposure to different curves (OIS, LIBOR, SOFR, etc.)
   - Correlation matrix L captures cross-curve relationships

2. **Time-Varying Parameters**:
   - Model supports μ(t), σ(t) that vary over time
   - Relevant for regime-dependent curve dynamics
   - Online learning adapts to changing market conditions

3. **High-Dimensional Robustness**:
   - Tested on 340 S&P500 components
   - Shrinkage techniques essential: "learning all parameters...simultaneously faces challenge. It leads to numerical instability" (p. 12)
   - Validates approach for multi-tenor, multi-curve portfolios

4. **Transaction Costs**:
   - Incorporates quadratic transaction costs (c = 3 in tests)
   - Turnover rate metric: TR ranges 0.09-0.11 for SAC vs 0.25+ for MLE
   - Lower turnover = lower costs in practice

### Performance Results (Real Markets)

Tested on DJI (29 assets), NASDAQ (57 assets), S&P500 (340 assets):

| Metric | SAC | Plug-in MLE | Buy-Hold | Index |
|--------|-----|-------------|----------|-------|
| Mean Return (340SP) | 4.40% | 1.12% | 1.29% | 1.10% |
| Sharpe Ratio | 1.44 | 0.51 | 1.04 | 0.91 |
| CEQ (annualized) | 34.51% | 5.74% | 13.03% | 10.94% |

**After transaction costs** (340SP):
- SAC: SR = 1.21, CEQ = 26.05%
- MLE: SR = -0.48, CEQ = -17.42%

**Key finding**: "SAC algorithm demonstrates higher precision in learning parameters compared to MLE" with "stable convergence pattern" (p. 17)

### Limitations for Fixed Income

Paper focuses on **equities**, not fixed income instruments. Key differences for swaps/futures:

1. **No DV01 constraints** - would be critical for fixed income
2. **No carry modeling** - carry is fundamental to curve trades
3. **Markowitz framework** - may not capture convexity, optionality
4. **Returns-based** - not curve-level (parallel shift, slope, curvature)

### Potential Adaptations for ARBS

To apply to multi-curve strategies:

1. **Asset definition**: Each "asset" = exposure to curve segment (e.g., 2y5y forward on OIS)
2. **Carry integration**: Modify μ^(i) to explicitly include carry + roll-down
3. **Curve factors**: Decompose returns into level/slope/curvature components
4. **DV01 budgeting**: Add constraint: Σ_i |DV01_i| ≤ DV01_max
5. **Basis risk**: Model Σ to capture cross-currency, cross-tenor basis

---

## Technical Implementation

### Algorithm Structure

**Algorithm 3**: Online SAC for Multi-Asset MV Portfolio

```
Every m time points:
  For each asset i:
    - Learn μ^(i) - r via Algorithm 1 (policy iteration)
  Combine: μ̂ - r = [φ_3^(1), ..., φ_3^(n)]^T
  Estimate Σ̂^(-1) via shrinkage (Shi et al. 2020)
  Learn K(0,T) via Algorithm 2 (given μ̂ - r, Σ̂^(-1))

Each time point t_j:
  Implement: Θ*_{t_j} = (φ_1/2γ - W_{t_j}) Σ̂^(-1)(μ̂ - r)
  Observe: W_{t_j+1}
```

**Hyperparameters**:
- Learning cycle: m = 5 days (1 week)
- Risk aversion: γ = 1.5
- Exploration weight: λ = 1
- Leverage bounds: Σ|θ^(i)|/W ∈ [-1, 2]

### Convergence Properties

**Theorem 3.2**: Policy iteration converges to optimal exploratory portfolio:

```
lim_{m→∞} P_m(t, θ) = P*(t, θ) = N((τ/2γ - w)Σ^(-1)(μ - r), (λ/2γ)e^{K(t,T)(T-t)}Σ^(-1))
```

**Empirical**: After 3000 learning episodes:
- Relative error μ^(1) - r: ~1%
- Relative error μ^(2) - r: ~3%
- Relative error K(0,T): ~4%

---

## Key Citations for ARBS

1. **Ledoit & Wolf (2003, 2004)**: Covariance shrinkage - essential for high-dimensional curve portfolios
2. **Shi et al. (2020)**: Eigenvalue regularization - used in this paper's Σ̂^(-1) estimation
3. **DeMiguel et al. (2007)**: 1/N portfolio benchmark - simple diversification often beats complex models
4. **Wang & Zhou (2020)**: SAC for continuous-time MV (single asset) - foundation for this paper

---

## Notation Reference

| Symbol | Meaning |
|--------|---------|
| n | Number of risky assets |
| μ^(i)(t) | Return rate of asset i at time t |
| σ^(i)(t) | Volatility of asset i at time t |
| ρ^(ij) | Correlation between assets i and j |
| Σ = DLD^T | Covariance matrix (D=diag vols, L=corr matrix) |
| K(t,T) | Average profitability from t to T |
| γ | Risk aversion coefficient |
| λ | Exploration weight (entropy regularization) |
| Θ_t | Portfolio allocation vector at time t |
| W_t | Discounted wealth at time t |

---

## Open Questions for ARBS Application

1. **Carry decomposition**: How to separate carry from expected price appreciation in μ^(i)?
2. **Curve representation**: Should each "asset" be a point on the curve, a curve segment, or a factor exposure?
3. **Cross-currency**: How does correlation matrix L change in multi-currency, multi-curve setting?
4. **Liquidity**: Paper ignores bid-ask spreads - critical for swap markets
5. **Model risk**: Mean-variance assumes Gaussian returns - swaps may have fat tails, skew

---

## Bottom Line

This paper provides a **scalable, stable framework for learning optimal allocations in high-dimensional, correlated asset universes**. The decoupled learning approach (separate immediate vs long-term factors) is the key innovation enabling multi-asset contexts (tested up to 340 assets).

**For ARBS**: The correlation-aware covariance modeling and shrinkage estimation techniques are directly applicable to multi-curve portfolios. However, adapting the framework would require:
- Curve-specific return decomposition (carry + roll + slope/curvature changes)
- DV01 and basis risk constraints
- Fixed income-appropriate risk models (vs equity-focused Markowitz)

The **empirical superiority over MLE** (especially after transaction costs) suggests RL-based approaches merit exploration for rates trading strategies.
