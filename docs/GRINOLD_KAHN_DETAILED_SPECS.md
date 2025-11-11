# Grinold-Kahn Framework: Complete Technical Specifications

**Purpose**: Comprehensive 3-layer specification (Business → Math → Code)

**Focus**: Alpha generation, covariance estimation for highly correlated assets (fixed income, sectors)

**Date**: 2025-11-10

---

# PART I: BUSINESS LOGIC SPECIFICATIONS

## 1. Business Problem Statement

### Context
Fixed income portfolios (rates swaps, futures, bonds) face unique challenges:
- **High correlation** within asset class (rates move together)
- **Limited diversification** (correlation = 0.8-0.99 across curve)
- **Factor structure** (3 factors explain >99% of variance)
- **Constraints** (DV01 limits, position limits, turnover costs)

### Objective
Maximize risk-adjusted returns (Sharpe ratio) while respecting risk limits.

### Key Constraint
For highly correlated assets, naive equal-weighting fails:
- Small estimation errors in covariance → large portfolio errors
- Risk concentrates in unintended bets
- Need robust optimization techniques

---

## 2. Trading Workflow

### Phase 1: Signal Generation (Daily)

**Input**: Market data (prices, rates, volumes) as of close

**Process**:
1. Calculate raw signals for each instrument
   - Carry: Expected return from holding
   - Roll-Down: Expected return from curve shape
   - Momentum: Recent price trends
   - Mean Reversion: Deviation from equilibrium
   - Value: Cheap/rich vs fundamentals

2. Standardize signals to z-scores
   - Mean = 0, StdDev = 1
   - Cross-sectional or time-series normalization
   - Winsorize outliers (cap at ±3σ)

3. Combine signals
   - Weighted average (if IC known)
   - Equal weight (if IC unknown)
   - Ensemble methods (machine learning)

**Output**: Alpha vector α[N×1] = expected excess returns

**Frequency**: Daily (after market close)

**Validation**: IC ∈ [0.03, 0.15] for viable signal

---

### Phase 2: Risk Estimation (Weekly/Monthly)

**Input**: Historical returns (past 1-3 years)

**Process**:
1. Clean returns data
   - Remove outliers (>5σ events)
   - Adjust for corporate actions
   - Fill missing data (forward fill, interpolation)

2. Estimate covariance matrix
   - Method selection based on N vs T:
     - If T >> N (many dates, few assets): Sample covariance
     - If T ≈ N (limited history): Shrinkage (Ledoit-Wolf)
     - Always: Consider factor models (PCA, risk factors)

3. Validate covariance
   - Check positive definite
   - Eigenvalue decomposition (no negative eigenvalues)
   - Condition number < 100 (well-conditioned)

**Output**: Covariance matrix Σ[N×N]

**Frequency**: Weekly (rolling window) or Monthly (stability)

**Validation**:
- Largest eigenvalue captures 80-90% (level factor)
- Top 3 eigenvalues capture >99% (level, slope, curve)

---

### Phase 3: Portfolio Optimization (Rebalance Days)

**Input**: Alphas α, Covariance Σ, Current Portfolio w_old

**Process**:
1. Set up optimization problem
   - Objective: Maximize utility = α'w - (λ/2)w'Σw
   - Constraints:
     - Sum(w) = 1 (fully invested) or = 0 (dollar neutral)
     - |DV01'w| ≤ DV01_limit (interest rate risk)
     - ||w||₁ ≤ gross_limit (gross exposure)
     - |w[i]| ≤ w_max (individual position limits)
     - ||w - w_old||₁ ≤ turnover_limit (trading costs)

2. Solve optimization
   - Quadratic program (QP solver: CVXOPT, OSQP)
   - If infeasible: relax constraints iteratively
   - If multiple solutions: choose minimum turnover

3. Generate trades
   - target_w = optimal weights
   - trades = target_w - w_old
   - Round to lot sizes (futures contracts are integers)
   - Check market hours, liquidity

**Output**: Trade list (instrument, quantity, direction)

**Frequency**: Monthly (low turnover) or Weekly (high turnover)

**Validation**:
- Expected Sharpe > 1.0 (before costs)
- Turnover < 200% annually (after costs)
- Max position < 20% (concentration risk)

---

### Phase 4: Execution & Monitoring (Continuous)

**Execution**:
- Submit orders to broker API
- Use limit orders (avoid market impact)
- Monitor fills, adjust orders
- Track slippage vs expected

**Monitoring** (Real-time):
- P&L vs expected (alpha capture)
- Risk vs limits (DV01, VaR, exposure)
- Signal decay (IC degradation over time)
- Correlation breakdown (factor stability)

**Performance Attribution** (Monthly):
- Decompose returns:
  - Alpha (skill-based)
  - Factor exposures (systematic)
  - Specific risk (idiosyncratic)
  - Transaction costs
  - Timing (rebalance vs continuous)

---

## 3. Risk Management

### Limits

**Market Risk**:
- DV01 limit: ±$500k per $100M capital
- Gross exposure: ≤ 150% (1.5× leverage)
- Net exposure: ±20% (near market-neutral)
- VaR (99%, 1-day): ≤ 2% of capital

**Concentration Risk**:
- Max single position: 20%
- Max sector (e.g., front-end rates): 40%
- Max correlated cluster: 50%

**Liquidity Risk**:
- Only trade top 80% liquid instruments
- Min daily volume: 100× position size
- Max position as % of volume: 5%

### Stop-Loss Rules

**Position Level**:
- If position loss > 2× expected (2σ event): reduce 50%
- If position loss > 3× expected (3σ event): close 100%

**Portfolio Level**:
- If daily loss > 1% of capital: freeze new trades
- If drawdown > 5%: reduce gross exposure by 25%
- If drawdown > 10%: close all positions, review strategy

**Signal Level**:
- If IC < 0 for 3 consecutive months: disable signal
- If IC < 0.02 for 6 months: redesign signal

---

## 4. Business Metrics

### Signal Quality (Measured Monthly)

- **IC (Information Coefficient)**: Corr(forecast, actual)
  - Target: IC > 0.05
  - Good: IC > 0.10
  - Excellent: IC > 0.15

- **Hit Rate**: % of profitable positions
  - Random: 50%
  - Target: >52%
  - Good: >55%

- **Signal Decay**: IC vs holding period
  - Fast decay (IC halves in 5 days): High frequency
  - Slow decay (IC halves in 30 days): Medium frequency

### Portfolio Performance (Measured Annually)

- **Sharpe Ratio**: (Return - RFR) / StdDev
  - Target: > 1.0
  - Good: > 1.5
  - Excellent: > 2.0

- **Information Ratio**: Excess Return / Tracking Error
  - Target: > 0.5
  - Good: > 0.75
  - Excellent: > 1.0

- **Max Drawdown**: Peak-to-trough loss
  - Target: < 10%
  - Good: < 5%
  - Excellent: < 3%

- **Calmar Ratio**: Ann Return / Max Drawdown
  - Target: > 1.0
  - Good: > 2.0

### Operational Metrics

- **Turnover**: Annual position churn
  - Target: < 200%
  - Good: < 100%

- **Transaction Costs**: As % of gross return
  - Target: < 20% of gross return
  - Good: < 10%

- **Capacity**: Max AUM before alpha decay
  - Estimate: 10× daily traded volume
  - Monitor: Slippage vs position size

---

## 5. Highly Correlated Assets: Special Considerations

### Problem: Multicollinearity

When assets are highly correlated (ρ > 0.9):
- Covariance matrix is near-singular
- Small estimation errors → large weight changes
- Optimization becomes unstable
- Risk concentrates in eigenvector noise

### Solution 1: Regularization

**Ridge Regularization**: Add penalty for large weights
```
minimize: α'w - (λ/2)w'Σw + (γ/2)||w||₂²
```
Effect: Shrinks weights toward zero, reduces extreme positions

**Lasso Regularization**: Penalty for number of positions
```
minimize: α'w - (λ/2)w'Σw + γ||w||₁
```
Effect: Creates sparse portfolios (few positions)

### Solution 2: Factor Models

Instead of N×N covariance, use K-factor model (K << N):

**Returns decomposition**:
```
r[i] = B[i,:]' × f + ε[i]
```
Where:
- f[K×1] = common factors (level, slope, curve)
- B[N×K] = factor loadings
- ε[i] = idiosyncratic return

**Covariance reduction**:
```
Σ = B × Σ_f × B' + Diag(σ_ε²)
```
Reduces from N(N+1)/2 parameters to K(K+1)/2 + N parameters

For N=50 assets:
- Full covariance: 1,275 parameters
- 3-factor model: 6 + 50 = 56 parameters (23× reduction!)

### Solution 3: Hierarchical Clustering

Group correlated assets into clusters, optimize within then across clusters:

1. **Cluster**: Group assets by correlation (>0.95)
2. **Within-cluster optimization**: Equal weight or IC-weighted
3. **Across-cluster optimization**: Treat each cluster as one asset
4. **Rebalance**: Scale cluster weights to individual positions

Effect: Reduces dimension, improves stability

---

## 6. Sector/Fixed Income Specific Logic

### Fixed Income (Rates)

**Factor Structure**:
- Factor 1 (85%): Level (parallel shift)
- Factor 2 (10%): Slope (steepening/flattening)
- Factor 3 (4%): Curvature (butterfly)

**Optimization Strategy**:
- Optimize exposure to 3 factors, not 50 instruments
- Then map factor weights → instrument weights via factor loadings

**Example**:
```
Target: Long slope (steepener), neutral level & curve
Implementation: +1 × 10Y swap, -1 × 2Y swap (duration-neutral)
```

### Equity Sectors

**Factor Structure**:
- Factor 1 (60%): Market (SPY beta)
- Factor 2-10 (35%): Sector factors (Tech, Financials, Healthcare)
- Residual (5%): Stock-specific

**Optimization Strategy**:
- Neutralize market beta (β = 0)
- Bet on sector relative value
- Limit stock-specific risk (diversify within sector)

---

# PART II: MATHEMATICAL SPECIFICATIONS

## 1. Fundamental Law of Active Management

### Derivation

**Setup**:
- N independent bets per year
- Each bet has skill IC (Information Coefficient)
- Each bet contributes to portfolio return

**Single Bet**:
```
Return[i] = IC × σ × Z[i] + noise
```
Where:
- IC = correlation(forecast, actual)
- σ = volatility
- Z[i] = standardized forecast (z-score)

**Portfolio of N Bets**:
```
Total Skill = IC × √N
```
Because:
- N independent bets → variance adds
- Standard error ∝ 1/√N
- Information Ratio scales as √N

**Information Ratio**:
```
IR = (E[R_p] - R_f) / σ(R_p - R_f)
   = IC × √BR

Where BR = Breadth = number of independent bets per year
```

**Proof**:
```
Given:
- α[i] = IC × σ[i] × score[i]  (forecasted excess return)
- w[i] = weight of asset i
- Σ = covariance matrix

Portfolio excess return:
R_p = Σ w[i] × α[i] + noise

E[R_p] = Σ w[i] × E[α[i]]
       = IC × Σ w[i] × σ[i] × E[score[i]]
       = IC × σ_p × (if scores are independent)

Var(R_p) = σ_p²

Therefore:
IR = E[R_p] / σ_p
   = IC × √BR  (if BR independent bets)
```

**Key Insight**: To double IR, you can:
- Double IC (twice as skilled) - very hard!
- Quadruple breadth (4× bets) - more feasible
- Combination: 1.4× IC, 2× breadth → 2× IR

---

## 2. Information Coefficient (IC)

### Definition

IC = Correlation(Forecasted Return, Actual Return)

### Calculation Methods

**Pearson IC** (parametric):
```
IC_pearson = Cov(α, r) / (σ(α) × σ(r))
            = Σ (α[i] - ᾱ) × (r[i] - ȓ) / √(Σ(α[i]-ᾱ)² × Σ(r[i]-ȓ)²)
```
Pros: Sensitive to magnitude
Cons: Affected by outliers

**Spearman IC** (non-parametric):
```
IC_spearman = 1 - (6 × Σ d[i]²) / (N × (N² - 1))

Where d[i] = rank_α[i] - rank_r[i]
```
Pros: Robust to outliers
Cons: Only uses rank information

### IC Over Time

**Rolling IC** (measures consistency):
```
IC_t = Corr(α_t, r_{t+1})  computed each period

Rolling avg: IC̄ = (1/T) × Σ IC_t
Rolling std: σ(IC) = √((1/T) × Σ (IC_t - IC̄)²)

t-stat = IC̄ / (σ(IC) / √T)
```

**IC Decay** (signal half-life):
```
IC(h) = IC(0) × exp(-λ × h)

Where:
h = holding period (days)
λ = decay rate
Half-life = ln(2) / λ

Example: If IC(1day) = 0.10, IC(5days) = 0.05
Then λ = ln(2)/5 ≈ 0.14
```

### Statistical Significance

**T-test**: Is IC significantly > 0?
```
H0: IC = 0
H1: IC > 0

t = IC × √(N-2) / √(1-IC²)
t ~ Student-t(N-2) under H0

Reject H0 if t > t_critical
```

**Rule of Thumb**:
- For N=252 (1 year daily), need IC > 0.13 for 95% confidence
- For N=60 (5 years monthly), need IC > 0.26 for 95% confidence

---

## 3. Covariance Matrix Estimation

### Problem Statement

Given: Returns matrix R[T×N] (T observations, N assets)
Goal: Estimate Σ[N×N] = E[(r - μ)(r - μ)']

### Method 1: Sample Covariance

**Formula**:
```
Σ̂_sample = (1/(T-1)) × Σ_t (r_t - μ̂)(r_t - μ̂)'
           = (1/(T-1)) × R' × R  (if demeaned)
```

**Properties**:
- Unbiased: E[Σ̂] = Σ
- Consistent: Σ̂ → Σ as T → ∞
- Efficient: Minimum variance estimator (if normal)

**Problems**:
- Requires T >> N (else singular, unstable)
- Noisy when T ≈ N
- Eigenvalue spread too large (overstates extremes)

**When to Use**: T > 5N (e.g., 5 years daily for 250 assets)

---

### Method 2: EWMA (Exponentially Weighted Moving Average)

**Motivation**: Give more weight to recent observations

**Recursive Formula**:
```
Σ_t = λ × Σ_{t-1} + (1-λ) × r_t × r_t'

Where:
λ = decay factor (typically 0.94-0.97)
1-λ = weight on today's squared return
```

**Halflife Parametrization**:
```
λ = 0.5^(1/HL)

Examples:
HL = 60 days → λ = 0.988
HL = 30 days → λ = 0.977
HL = 10 days → λ = 0.933
```

**Properties**:
- Adaptive to regime changes
- Reduces effective T (less stable in stable regimes)
- Still requires initialization (use sample cov for first window)

**When to Use**: Volatile markets, frequent regime changes

**Implementation**:
```python
def ewma_cov(returns, halflife=60):
    λ = 0.5 ** (1/halflife)
    weights = np.array([(1-λ) * λ**i for i in range(len(returns))][::-1])
    weights /= weights.sum()  # Normalize

    r_centered = returns - returns.mean(axis=0)
    Σ = r_centered.T @ np.diag(weights) @ r_centered
    return Σ
```

---

### Method 3: Shrinkage (Ledoit-Wolf)

**Motivation**: Shrink noisy sample covariance toward structured target

**Formula**:
```
Σ̂_shrink = δ × F + (1-δ) × S

Where:
δ = shrinkage intensity (0 ≤ δ ≤ 1)
F = target matrix (structured, low-rank)
S = sample covariance
```

**Target Choices**:
- **Constant Correlation**: F = σ² × (ρ × 11' + (1-ρ) × I)
- **Diagonal**: F = Diag(S) (no correlation)
- **Single-Index**: F = β × σ_m² × β' + Diag(σ_ε²)

**Optimal Shrinkage** (Ledoit-Wolf, 2004):
```
δ* = min(1, κ̂ / T)

Where:
κ̂ = Σ Var(s_ij) / Σ (s_ij - f_ij)²
   = estimation error / target distance
```

**Properties**:
- Reduces eigenvalue spread (condition number)
- Improves out-of-sample performance
- Works even when T < N (shrink more)

**When to Use**: Limited data (T < 2N), high dimension

---

### Method 4: Factor Models

**Motivation**: Exploit low-rank structure

**Model**:
```
r[i] = α[i] + Σ_k β[i,k] × f[k] + ε[i]

Where:
f[k] = common factors (level, slope, curve)
β[i,k] = loading of asset i on factor k
ε[i] = idiosyncratic (asset-specific) return
```

**Covariance Decomposition**:
```
Σ = B × Σ_f × B' + Diag(σ_ε²)

Where:
B[N×K] = factor loadings
Σ_f[K×K] = factor covariance
σ_ε²[N×1] = idiosyncratic variances
```

**Estimation**:
1. Estimate factors: f = PCA(R) or predefined (macro factors)
2. Estimate loadings: β = regress(r[i], f)
3. Estimate factor cov: Σ_f = Cov(f)
4. Estimate idiosyncratic: σ_ε² = Var(r - Bf)

**Advantages**:
- Reduces parameters: N² → K² + NK + N
- More stable (estimates K factors, not N² covariances)
- Interpretable (economic factors)

**For Fixed Income (K=3 factors)**:
```
Factor 1: Level = average rate change across tenors
Factor 2: Slope = long rate - short rate
Factor 3: Curvature = 2×mid - short - long

Loadings (example for 2Y, 5Y, 10Y swaps):
        Level  Slope  Curve
2Y      1.0   -0.8    0.3
5Y      1.0    0.0   -0.4
10Y     1.0    0.8    0.3
```

**When to Use**: N > 20, clear factor structure

---

### Method 5: Robust Covariance

**Motivation**: Sample covariance is sensitive to outliers

**MCD (Minimum Covariance Determinant)**:
```
Find subset of h observations (h ≈ 0.75×T)
that minimizes |Σ̂_subset|

Then:
Σ̂_MCD = rescaled covariance of that subset
```

**Properties**:
- Robust to 25% outliers
- Downweights extreme returns
- Computationally expensive (combinatorial)

**When to Use**: Fat-tailed returns, known outliers

---

## 4. Portfolio Optimization

### Mean-Variance Optimization

**Objective**: Maximize Sharpe ratio (or utility)

**Problem Formulation**:
```
maximize    w'α - (λ/2) × w'Σw
subject to  Σ w[i] = 1          (fully invested)
            w[i] ≥ 0            (long-only) OR
            Σ |w[i]| ≤ g_max    (gross exposure)
            DV01'w ≤ dv01_limit (risk constraint)
            |w[i]| ≤ w_max      (position limits)
```

**Lagrangian**:
```
L = w'α - (λ/2)w'Σw + μ(Σw - 1) + Σν[i](w[i] - w_max) + ...
```

**First-Order Conditions** (unconstrained):
```
∂L/∂w = α - λΣw + μ1 + ν = 0

Solution:
w* = (1/λ) × Σ^(-1) × (α - μ1 - ν)
```

**Closed-Form** (no constraints except Σw=1):
```
w* = (Σ^(-1) α) / (1'Σ^(-1)α)
```

**Risk Aversion Parameter λ**:
```
λ = 1 / risk_tolerance

Interpretation:
- λ → 0: Risk-neutral (maximize expected return)
- λ → ∞: Risk-averse (minimize variance)
- λ = 1: Equal weight on return and risk

Typical: λ ∈ [1, 10]
```

---

### Constrained Optimization (QP Formulation)

**Standard Form**:
```
minimize    (1/2) × x'Px + q'x
subject to  Gx ≤ h   (inequality)
            Ax = b   (equality)
```

**Mapping to Portfolio**:
```
x = w (weights)
P = λΣ (scaled covariance)
q = -α (negative alpha, since we minimize)

Equality: A = 1' (all ones), b = 1 (sum to 1)
Inequality: G = [I; -I], h = [w_max; -w_min] (bounds)
```

**Solvers**:
- **CVXOPT** (Python): General-purpose convex optimizer
- **OSQP** (Python/C): Operator Splitting QP (very fast)
- **quadprog** (R): Classic QP solver
- **MOSEK** (Commercial): High-performance

**Complexity**:
- **Time**: O(N³) for dense, O(N) for sparse (if diagonal P)
- **Space**: O(N²) for dense Σ

---

### Robust Optimization

**Motivation**: Alphas and covariance have estimation error

**Worst-Case Optimization**:
```
maximize    min_(α∈U_α, Σ∈U_Σ) [w'α - (λ/2)w'Σw]

Where:
U_α = {α: ||α - α̂|| ≤ ε_α}
U_Σ = {Σ: ||Σ - Σ̂|| ≤ ε_Σ}
```

**Reformulation** (for ellipsoidal uncertainty):
```
maximize    w'α̂ - ε_α||w|| - (λ/2)w'(Σ̂ + ε_Σ I)w
```

Effect: Adds regularization, shrinks extreme weights

**Black-Litterman** (Bayesian approach):
```
Prior: Market equilibrium (α_eq = λ × Σ × w_market)
Views: Analyst forecasts (P'α = q ± ε)
Posterior: α_BL = [(τΣ)^(-1) + P'Ω^(-1)P]^(-1) × [(τΣ)^(-1)α_eq + P'Ω^(-1)q]

Where:
τ = confidence in prior (typically 0.025)
Ω = confidence in views (diagonal)
```

---

### Transaction Cost Model

**Objective with Costs**:
```
maximize    w'α - (λ/2)w'Σw - c(w, w_old)

Where c(w, w_old) = transaction cost function
```

**Cost Models**:

**Linear**: `c = κ × Σ |w[i] - w_old[i]|`
- κ = cost per unit turnover (bps)
- Simple, conservative

**Quadratic** (market impact): `c = κ × Σ (w[i] - w_old[i])² / V[i]`
- V[i] = volume/liquidity of asset i
- Penalizes large trades more

**Piecewise Linear**:
```
c = Σ (κ_1|Δw[i]|  if |Δw[i]| < threshold
       κ_2|Δw[i]|  otherwise)
```
- κ_1 < κ_2 (higher cost for large trades)

**Effect**: Reduces turnover, stabilizes portfolio

---

## 5. Covariance for Highly Correlated Assets

### Problem: Ill-Conditioned Matrix

**Definition**: Condition number = λ_max / λ_min

**For Correlated Assets**:
- If all correlations ≈ 0.95:
  - λ_min ≈ (1 - 0.95) × λ_max = 0.05 × λ_max
  - Condition number ≈ 20 (borderline)
- If all correlations ≈ 0.99:
  - Condition number ≈ 100 (poorly conditioned)
  - Small changes in data → large changes in Σ^(-1)

**Impact on Optimization**:
```
w* = Σ^(-1) α

If Σ is ill-conditioned:
- Small errors in α or Σ → huge errors in w*
- Weights become extreme (+1000%, -900%)
- Optimization is unstable
```

### Solution 1: Regularized Inverse

**Ridge Inverse** (Tikh onov):
```
Σ_reg = Σ + δI

w* = Σ_reg^(-1) α = (Σ + δI)^(-1) α
```

**Effect**:
- Adds δ to all eigenvalues (shifts spectrum)
- Reduces condition number: κ_new ≈ (λ_max + δ) / (λ_min + δ)
- Shrinks weights toward zero

**Choosing δ**:
- Small δ: Less shrinkage (closer to original)
- Large δ: More shrinkage (more conservative)
- Optimal: δ = λ_min / 10 (reduces condition number by 10×)

**Cross-Validation**:
```
for δ in [0.001, 0.01, 0.1]:
    w_δ = (Σ + δI)^(-1) α
    Sharpe_out_of_sample[δ] = backtest(w_δ)

δ* = argmax Sharpe_out_of_sample
```

---

### Solution 2: Factor Model Covariance

**Motivation**: Correlated assets share common factors

**Factor Decomposition**:
```
Σ = B Σ_f B' + Diag(σ_ε²)

Inverse:
Σ^(-1) = Ψ^(-1) - Ψ^(-1) B (Σ_f^(-1) + B'Ψ^(-1)B)^(-1) B'Ψ^(-1)

Where Ψ = Diag(σ_ε²) (idiosyncratic variances)
```

**Sherman-Morrison-Woodbury** formula:
```
(Σ + BΣ_f B')^(-1) = Σ^(-1) - Σ^(-1)B(Σ_f^(-1) + B'Σ^(-1)B)^(-1)B'Σ^(-1)
```

**Advantages**:
- Inverts K×K instead of N×N (much faster if K << N)
- More stable (factors less noisy than individual assets)
- Interpretable (factor exposures)

**For Fixed Income** (K=3):
```
Factors: Level, Slope, Curvature
Loadings B: [N×3] matrix

Instead of inverting 50×50 Σ (2,500 terms),
Invert 3×3 Σ_f (9 terms) + 50×3 operations
```

---

### Solution 3: Shrinkage Toward Equal Weight

**For Correlated Assets**: Eigenvalues cluster near mean

**Shrinkage Target**:
```
F = σ̄² × [(ρ̄ × 11') + (1 - ρ̄) × I]

Where:
σ̄² = mean variance
ρ̄ = mean pairwise correlation
```

**This target**:
- Assumes all assets have same variance
- Assumes all pairs have same correlation
- Perfect for highly correlated assets!

**Shrunk Covariance**:
```
Σ̂ = (1-δ) × Σ_sample + δ × F
```

**Effect**: Reduces noise, stabilizes inverse

---

### Solution 4: Hierarchical Risk Parity (HRP)

**Motivation**: Diversify across correlation clusters

**Algorithm**:
1. **Hierarchical Clustering**: Group assets by correlation
   - Distance = 1 - |ρ[i,j]|
   - Linkage: Single, Complete, or Ward

2. **Recursive Bisection**:
   - Split tree into left and right subtrees
   - Allocate weight to each subtree inversely proportional to cluster variance
   - Recurse within each subtree

3. **Leaf Weights**: Final allocation to individual assets

**Example** (3 assets: A, B, C):
```
Correlation:
A-B: 0.95 (very high)
A-C: 0.30
B-C: 0.25

Clustering:
(A, B) form cluster 1 (correlated)
C is cluster 2 (distinct)

Allocation:
Var(cluster1) = 1.0
Var(cluster2) = 1.5

w_cluster1 = 1.5 / (1.0 + 1.5) = 0.6
w_cluster2 = 1.0 / (1.0 + 1.5) = 0.4

Within cluster1:
w_A = 0.6 × 0.5 = 0.3 (equal weight within)
w_B = 0.6 × 0.5 = 0.3

Final: w = [0.3, 0.3, 0.4]
```

**Properties**:
- No matrix inversion (avoids ill-conditioning)
- Diversifies across clusters (not within)
- Stable, intuitive

---

# PART III: CODE SPECIFICATIONS

## 1. System Architecture

### Module Structure
```
ARBS/
  Signals/
    Base/
      BaseSignal.py         # Abstract signal interface
      SignalCombiner.py     # Combine multiple signals
    Carry/
      CarrySignal.py        # Implement carry signal
    RollDown/
      RollDownSignal.py     # Roll-down signal
    Momentum/
      MomentumSignal.py     # Trend following
    MeanReversion/
      MeanReversionSignal.py  # Contrarian signal

  Risk/
    Covariance/
      Base/
        CovarianceEstimator.py  # Abstract interface
      Sample/
        SampleCovariance.py     # Classic estimator
      EWMA/
        EWMACovariance.py       # Exponential weighting
      Shrinkage/
        LedoitWolf.py           # Ledoit-Wolf shrinkage
      FactorModel/
        FactorCovariance.py     # PCA-based
        ThreeFactorRates.py     # Level, slope, curve
    Volatility/
      RealizedVol.py            # Historical volatility
      GARCHVol.py               # GARCH(1,1)

  Portfolio/
    Optimizer/
      Base/
        BaseOptimizer.py        # Abstract interface
      MeanVariance/
        MVOptimizer.py          # Classic Markowitz
      Robust/
        RobustOptimizer.py      # With uncertainty sets
      BlackLitterman/
        BLOptimizer.py          # Bayesian views
    Constraints/
      DV01Constraint.py         # Interest rate risk
      PositionLimitConstraint.py  # Max position size
      TurnoverConstraint.py     # Transaction costs

  Backtest/
    Strategies/
      GrinoldKahnStrategy.py    # Main strategy
    Engine/
      QuantBacktest.py          # Backtest runner
    Attribution/
      PerformanceAttribution.py # Decompose returns
```

---

## 2. Data Structures

### Signal Output
```python
@dataclass
class SignalOutput:
    """Output from a signal calculation."""
    as_of: date
    scores: Dict[str, float]  # instrument -> z-score
    raw_values: Dict[str, float]  # instrument -> raw signal
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_alpha(self, ic: float, volatilities: Dict[str, float]) -> Dict[str, float]:
        """Convert z-scores to expected returns (alphas)."""
        return {
            instrument: ic * volatilities[instrument] * score
            for instrument, score in self.scores.items()
        }
```

### Covariance Output
```python
@dataclass
class CovarianceOutput:
    """Output from covariance estimation."""
    as_of: date
    covariance: np.ndarray  # N×N matrix
    instruments: List[str]  # Order of instruments
    method: str  # "sample", "ewma", "shrinkage", "factor"
    condition_number: float
    eigenvalues: np.ndarray
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_well_conditioned(self, threshold: float = 100.0) -> bool:
        """Check if matrix is numerically stable."""
        return self.condition_number < threshold
```

### Optimization Output
```python
@dataclass
class OptimizationOutput:
    """Output from portfolio optimization."""
    as_of: date
    weights: Dict[str, float]  # instrument -> weight
    expected_return: float
    expected_risk: float  # StdDev
    expected_sharpe: float
    turnover: float  # From previous weights
    constraints_satisfied: bool
    solver_status: str  # "optimal", "suboptimal", "infeasible"
    iterations: int
    solve_time: float  # seconds
```

---

## 3. Base Classes

### BaseSignal
```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import date
import pandas as pd

class BaseSignal(ABC):
    """
    Abstract base class for all alpha signals.

    Signals generate forecasts (z-scores) for each instrument.
    Signals should be:
    - Stationary (mean 0, stddev 1)
    - Independent across instruments (or account for correlation)
    - Predictive (IC > 0)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize signal with configuration.

        Args:
            config: Signal-specific parameters
                - lookback: Historical window (days)
                - universe: List of instruments
                - normalization: "cross_sectional" or "time_series"
        """
        self.config = config
        self.lookback = config.get("lookback", 252)
        self.universe = config.get("universe", [])
        self.normalization = config.get("normalization", "cross_sectional")

    @abstractmethod
    def calculate_raw(
        self,
        market_data: pd.DataFrame,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Calculate raw signal values.

        Args:
            market_data: Historical prices/rates
            as_of: Calculation date

        Returns:
            Dict mapping instrument -> raw signal value
        """
        pass

    def calculate(
        self,
        market_data: pd.DataFrame,
        as_of: date,
    ) -> SignalOutput:
        """
        Calculate standardized signal (z-scores).

        Args:
            market_data: Historical prices/rates
            as_of: Calculation date

        Returns:
            SignalOutput with z-scores
        """
        # Get raw values
        raw_values = self.calculate_raw(market_data, as_of)

        # Standardize
        if self.normalization == "cross_sectional":
            scores = self._cross_sectional_normalize(raw_values)
        elif self.normalization == "time_series":
            scores = self._time_series_normalize(raw_values, market_data, as_of)
        else:
            raise ValueError(f"Unknown normalization: {self.normalization}")

        # Winsorize outliers
        scores = self._winsorize(scores, threshold=3.0)

        return SignalOutput(
            as_of=as_of,
            scores=scores,
            raw_values=raw_values,
            metadata={"signal_name": self.__class__.__name__},
        )

    def _cross_sectional_normalize(
        self,
        values: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Normalize values to z-scores across instruments.

        Mean = 0, StdDev = 1 across cross-section.
        """
        vals = list(values.values())
        mean = np.mean(vals)
        std = np.std(vals)

        if std == 0:
            return {k: 0.0 for k in values}

        return {k: (v - mean) / std for k, v in values.items()}

    def _time_series_normalize(
        self,
        values: Dict[str, float],
        market_data: pd.DataFrame,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Normalize each instrument's value by its own history.

        Z-score = (value - historical_mean) / historical_std
        """
        scores = {}
        for instrument, value in values.items():
            # Get historical values for this instrument
            hist = self._get_historical_signal(market_data, instrument, as_of, self.lookback)

            if len(hist) < 20:  # Need minimum history
                scores[instrument] = 0.0
                continue

            mean = hist.mean()
            std = hist.std()

            if std == 0:
                scores[instrument] = 0.0
            else:
                scores[instrument] = (value - mean) / std

        return scores

    def _winsorize(
        self,
        scores: Dict[str, float],
        threshold: float = 3.0,
    ) -> Dict[str, float]:
        """
        Cap extreme values at ±threshold standard deviations.

        Reduces impact of outliers.
        """
        return {
            k: max(min(v, threshold), -threshold)
            for k, v in scores.items()
        }

    @abstractmethod
    def backtest(
        self,
        market_data: pd.DataFrame,
        start: date,
        end: date,
    ) -> Dict[str, Any]:
        """
        Backtest signal performance.

        Returns:
            Dict with metrics: IC, hit_rate, sharpe, etc.
        """
        pass
```

---

### CarrySignal Implementation
```python
class CarrySignal(BaseSignal):
    """
    Carry signal for fixed income.

    Carry = Expected return from holding, assuming no rate changes.

    For swaps: Forward rate - Spot rate
    For futures: Calendar spread (back - front) / days to roll
    """

    def calculate_raw(
        self,
        market_data: pd.DataFrame,
        as_of: date,
    ) -> Dict[str, float]:
        """
        Calculate carry for each instrument.

        Args:
            market_data: DataFrame with columns:
                - date
                - instrument
                - rate (for swaps) or price (for futures)
                - maturity_date
                - forward_rate (if available)

        Returns:
            Dict mapping instrument -> carry (bps)
        """
        carry_values = {}

        for instrument in self.universe:
            # Get instrument data
            inst_data = market_data[
                (market_data["date"] == as_of) &
                (market_data["instrument"] == instrument)
            ]

            if inst_data.empty:
                carry_values[instrument] = 0.0
                continue

            # Check instrument type
            if "swap" in instrument.lower() or "irs" in instrument.lower():
                carry = self._swap_carry(inst_data, market_data, as_of)
            elif "sfr" in instrument.lower() or "fut" in instrument.lower():
                carry = self._futures_carry(inst_data, market_data, as_of)
            else:
                carry = 0.0

            carry_values[instrument] = carry

        return carry_values

    def _swap_carry(
        self,
        inst_data: pd.DataFrame,
        market_data: pd.DataFrame,
        as_of: date,
    ) -> float:
        """
        Calculate swap carry: (forward_rate - spot_rate) × DV01

        Carry = P&L from time decay only.
        """
        spot_rate = inst_data.iloc[0]["rate"]
        forward_rate = inst_data.iloc[0].get("forward_rate", None)

        if forward_rate is None:
            # Estimate forward from curve shape
            maturity = inst_data.iloc[0]["maturity_date"]
            horizon = self.config.get("carry_horizon", "1M")
            forward_rate = self._estimate_forward_rate(
                market_data, as_of, maturity, horizon
            )

        # Carry in bps = (forward - spot) × 10000
        carry_bps = (forward_rate - spot_rate) * 10000

        return carry_bps

    def _futures_carry(
        self,
        inst_data: pd.DataFrame,
        market_data: pd.DataFrame,
        as_of: date,
    ) -> float:
        """
        Calculate futures carry: Calendar spread / days to roll

        Carry = Expected return from rolling position forward.
        """
        contract = inst_data.iloc[0]["instrument"]
        current_price = inst_data.iloc[0]["price"]

        # Get next contract (for rolling)
        next_contract = self._get_next_contract(contract)
        next_data = market_data[
            (market_data["date"] == as_of) &
            (market_data["instrument"] == next_contract)
        ]

        if next_data.empty:
            return 0.0

        next_price = next_data.iloc[0]["price"]

        # Calendar spread (contango = positive, backwardation = negative)
        calendar_spread = next_price - current_price

        # Days until roll
        expiry = inst_data.iloc[0]["maturity_date"]
        roll_date = expiry - timedelta(days=5)  # Roll 5 days before expiry
        days_to_roll = (roll_date - as_of).days

        if days_to_roll <= 0:
            return 0.0

        # Annualized carry in bps
        carry_bps_daily = (calendar_spread / days_to_roll) * 10000
        carry_bps_annual = carry_bps_daily * 252

        return carry_bps_annual

    def backtest(
        self,
        market_data: pd.DataFrame,
        start: date,
        end: date,
    ) -> Dict[str, Any]:
        """
        Backtest carry signal.

        Returns:
            IC, hit_rate, turnover, Sharpe
        """
        # Calculate signal each date
        dates = pd.date_range(start, end, freq='B')  # Business days
        signals = []
        returns = []

        for as_of in dates:
            signal = self.calculate(market_data, as_of)
            signals.append(signal.scores)

            # Get next period returns
            next_date = as_of + timedelta(days=21)  # ~1 month
            period_returns = self._calculate_returns(
                market_data, as_of, next_date
            )
            returns.append(period_returns)

        # Calculate IC (correlation of signal with next period return)
        ic = self._calculate_ic(signals, returns)

        # Hit rate (% of positive signal → positive return)
        hit_rate = self._calculate_hit_rate(signals, returns)

        # Sharpe ratio (if traded this signal)
        sharpe = self._calculate_sharpe(signals, returns)

        return {
            "ic": ic,
            "hit_rate": hit_rate,
            "sharpe": sharpe,
            "num_observations": len(signals),
        }

    def _calculate_ic(
        self,
        signals: List[Dict[str, float]],
        returns: List[Dict[str, float]],
    ) -> float:
        """Calculate Information Coefficient (Spearman rank correlation)."""
        from scipy.stats import spearmanr

        # Flatten to vectors
        sig_flat = []
        ret_flat = []

        for sig, ret in zip(signals, returns):
            for instrument in sig.keys():
                if instrument in ret:
                    sig_flat.append(sig[instrument])
                    ret_flat.append(ret[instrument])

        if len(sig_flat) < 10:
            return 0.0

        ic, pvalue = spearmanr(sig_flat, ret_flat)
        return ic
```

This is comprehensive! Continue in next message with covariance estimators and optimizers...
