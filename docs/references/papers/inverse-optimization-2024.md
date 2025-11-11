# Inverse Portfolio Optimization: Recovering Risk Preferences under Uncertainty

**Paper**: Cha et al. (2024) - "Inverse Portfolio Optimization with Synthetic Investor Data: Recovering Risk Preferences under Uncertainty"

**Source**: `/home/user/ARBS/docs/papers/risk-modeling/inverse-optimization-2024.pdf`

**ArXiv**: arXiv:2510.06986v2 [q-fin.GN] 13 Oct 2025

## Executive Summary

This paper develops an inverse optimization framework for recovering latent investor preferences (risk aversion, transaction costs, ESG orientation) from observed portfolio allocations. Key findings highly relevant to ARBS:

- **Transaction costs are highly identifiable** (MSE: 0.1040, Coverage: 100%)
- **Risk aversion is harder to recover** (MSE: 28.9870, Coverage: 0%)
- **Transaction cost shocks dominate volatility shocks** in welfare impact
- **Sublinear regret bounds** enable robust parameter calibration over time

---

## 1. Risk Aversion Parameter Recovery

### 1.1 Forward Problem Formulation

The mean-variance portfolio optimization with transaction costs:

```
max_{x∈X} f(x; μ, Σ, θ, c) = μ^T x - (θ/2) x^T Σx - c^T x

where:
- x ∈ R^n: portfolio weights
- X = {x ∈ R^n : 1^T x = 1, x ≥ 0}: feasible set
- θ: risk aversion parameter
- c: transaction cost vector
- μ: expected returns
- Σ: covariance matrix
```

### 1.2 Inverse Problem Formulation

Given observed portfolios {x_t}_{t=1}^T, recover (θ, c) by minimizing discrepancy:

```
min_{θ,c} L(θ,c) = Σ_{t=1}^T ||x_t - x*(μ_t, Σ_t, θ, c)||_2^2
```

### 1.3 Identifiability Conditions

**Theorem 3.1**: (θ, c) is uniquely identifiable if:

1. **Variation in Inputs**: {(μ_t, Σ_t)} span a sufficiently rich set
2. **Normalization**: θ ∈ [0, θ_max] or ||c||_2 = 1
3. **No Redundancy**: No two assets have identical (μ_i^t, Σ_{i,·}^t) for all t
4. **Distinct Active Sets**: At least two different active sets occur

### 1.4 Statistical Properties

**Proposition 3.1 (Consistency)**:
```
θ̂ →^p θ* as T → ∞
```
if {μ_t, Σ_t} are i.i.d. with compact support and identifiability holds.

**Empirical Results** (R=100 Monte Carlo trials):

| Parameter | Bias | Variance | MSE | Coverage (95%) |
|-----------|------|----------|-----|----------------|
| θ (Risk Aversion) | 4.3327 | 10.2152 | 28.9870 | 0.0% |
| c (Transaction Cost) | -0.2600 | 0.0364 | 0.1040 | 100% |
| η (ESG Penalty) | -0.1792 | 0.4580 | 0.4901 | 0.0% |

**Key Insight**: Risk aversion is difficult to recover with high bias and zero coverage. Transaction costs are highly identifiable with perfect coverage.

### 1.5 KKT Optimality Conditions

Interior solution (x* > 0):
```
x* = (1/θ) Σ^{-1} (μ - c - λ1)
```
with λ chosen to satisfy budget constraint 1^T x* = 1.

This shows θ appears as a scaling factor on the inverse covariance, making it harder to separate from estimation noise in Σ.

---

## 2. Transaction Cost Calibration

### 2.1 Linear Transaction Costs

Base specification:
```
cost(x) = c^T x
```

**Recovery Performance**:
- MSE: 0.1040 (lowest among all parameters)
- Bias: -0.2600 (modest)
- Coverage: 100% (perfect inferential reliability)

### 2.2 Nonlinear Transaction Costs Extension

Generalized convex costs:
```
φ(x) = Σ_{j=1}^n κ_j |x_j|^p,  p ≥ 1
```

- p = 1: Proportional (ℓ1) costs (sparsity-inducing)
- p = 2: Quadratic penalty (illiquidity/market impact)

**Lemma 3.1 (Robustness to Misspecification)**:

If true cost is φ(x) but estimated with linear c^T x, then:
```
||(θ̂,ĉ) - (θ*,c*)|| = O(ε)
```
where ε = sup_{x∈X} |φ(x) - c^T x|

### 2.3 Shock Analysis: Transaction Costs vs. Volatility

**Experimental Design**:
- Transaction cost shock: τ → 1.2τ (+20%)
- Volatility shock: Σ → 1.3Σ (+30%)

**Key Finding**: Transaction cost shocks dominate volatility shocks in welfare impact across all investor types (T1-T10).

**Real Data Validation** (SPY + EEM, 2007-2024):
- Consistent across 6 three-year blocks
- Holds during crises (2007-2009, 2019-2021, 2022-2024)
- Confirms synthetic results in real markets

### 2.4 Distributional Robustness

Robust forward problem with uncertainty set U:
```
max_{x∈X} min_{(μ,Σ)∈U} {μ^T x - (θ/2) x^T Σx - c^T x}

where U = {(μ,Σ) : ||μ-μ̄||_2 ≤ δ_μ, ||Σ-Σ̄||_F ≤ δ_Σ, Σ ⪰ 0}
```

**Proposition B.1**: (θ, c) remain identifiable under robustness if U is bounded, Σ̄ ≻ 0, and distinct active sets occur.

---

## 3. ARBS Relevance for Parameter Tuning

### 3.1 Direct Applications to ARBS

#### 3.1.1 Calibrating Risk Aversion from Execution Data

**Use Case**: Given historical portfolio allocations from ARBS optimizer, infer implicit risk aversion.

**Method**:
```python
# Pseudo-code for ARBS integration
observed_portfolios = arbs.get_historical_allocations()
estimated_params = inverse_optimize(
    portfolios=observed_portfolios,
    returns=historical_returns,
    covariance=estimated_covariance
)
risk_aversion = estimated_params['theta']
```

**Caveat**: Risk aversion has high MSE (28.99) and poor coverage (0%). Should be combined with domain knowledge or priors.

#### 3.1.2 Transaction Cost Estimation

**Use Case**: Estimate implicit transaction costs from observed portfolio turnover.

**Method**: Highly reliable (MSE: 0.104, Coverage: 100%)

```python
# Transaction costs are well-identified
transaction_costs = estimated_params['c']
# Use for:
# 1. Validating broker execution costs
# 2. Calibrating slippage models
# 3. Tuning rebalancing thresholds
```

#### 3.1.3 Parameter Validation and Drift Detection

**Dynamic Regret Framework**:

```
R_T = Σ_{t=1}^T [f(x*(θ_t^{true})) - f(x*(θ̂_t))]
```

**Theorem 3.2 (Dynamic Regret Bound)**:
```
R_T ≤ O(√T + D)
```
where D = Σ_{t=2}^T ||θ_t - θ_{t-1}|| is preference drift.

**ARBS Application**: Monitor parameter stability over time:
- If drift D is large → investor preferences changing
- If regret grows faster than √T → model misspecification

### 3.2 Workflow for ARBS Parameter Tuning

**Stage 1: Initial Calibration**
```
1. Collect T historical portfolio allocations from ARBS
2. Estimate (μ_t, Σ_t) for each period
3. Solve inverse optimization to recover (θ̂, ĉ, η̂)
4. Validate with bootstrap confidence intervals (B=200)
```

**Stage 2: Out-of-Sample Validation**
```
1. Hold out 20% of portfolios
2. Compute predictive regret on test set
3. If regret acceptable → use calibrated parameters
4. If regret high → investigate model misspecification
```

**Stage 3: Dynamic Monitoring**
```
1. Track cumulative regret R_T over time
2. Test if R_T/√T stabilizes (as theory predicts)
3. If R_T grows linearly → recalibrate parameters
4. Check for structural breaks in {θ_t}
```

### 3.3 Investor Heterogeneity

**Three Archetypes** (direct mapping to ARBS user profiles):

| Type | ρ (Risk Aversion) | τ (Txn Cost) | η (ESG) | ARBS Profile |
|------|-------------------|--------------|---------|--------------|
| Conservative | [5, 10] | ≈0 | 0 | Low volatility mandate |
| Neutral | [1, 3] | [0.1, 0.5] | 0 | Balanced growth |
| ESG-Oriented | [2, 4] | [0.1, 0.5] | [0.5, 2.0] | Sustainable investing |

**Recovery Accuracy by Type**:
- **Conservative**: Low variance but high bias (corner solutions)
- **Neutral**: Lowest MSE, best recovery performance
- **ESG-Oriented**: High variance due to parameter correlation

**ARBS Recommendation**: Calibration works best for moderate risk aversion (neutral investors). Extreme preferences require stronger priors.

### 3.4 Integration with Existing ARBS Risk Models

#### 3.4.1 Covariance Estimation

Paper uses factor model:
```
Σ = F F^T + Ψ

where:
- F ∈ R^{n×k}: factor loadings (k=3 systematic factors)
- Ψ = diag(σ_1^2, ..., σ_n^2): idiosyncratic variances
```

**ARBS has**:
- `IdentityCovariance`
- `ConstantCorrelationCovariance`

**Addition recommended**: `FactorModelCovariance` to match paper's setup.

#### 3.4.2 Alpha Generation

Paper's framework:
```
Optimal alpha scaling: α = IC × Vol × Z
```

**Current ARBS**:
- `CarrySignal`, `MomentumSignal`, `MeanReversionSignal`
- `AlphaGenerator` with IC × Vol × Z formula

**Inverse optimization complement**: Validate that realized alphas match intended scaling by comparing:
- Forward: α_t = IC × Vol_t × Z_t → x_t*
- Inverse: x_t^{observed} → (IC, Vol, Z) estimates

### 3.5 Practical Recommendations for ARBS

#### DO:
1. **Use inverse optimization for transaction cost calibration** (highly reliable)
2. **Monitor dynamic regret** to detect parameter drift
3. **Apply to moderate risk aversion regimes** (neutral investors)
4. **Bootstrap confidence intervals** (B=200) for uncertainty quantification
5. **Test robustness** to covariance estimation error (§3.5.2)

#### DON'T:
1. **Don't rely solely on risk aversion recovery** (high MSE, zero coverage)
2. **Don't assume static preferences** (track drift D over time)
3. **Don't ignore ESG parameter correlation** (η and θ interact)
4. **Don't skip identifiability checks** (need ≥2 distinct active sets)

---

## 4. Technical Details

### 4.1 Grid-Based Estimator

```python
# Conceptual implementation
def inverse_optimize(portfolios, returns, covariance):
    """
    Grid-based inverse optimization with provable regret.

    Args:
        portfolios: Observed allocations {x_t}
        returns: Expected returns {μ_t}
        covariance: Covariance matrices {Σ_t}

    Returns:
        Estimated parameters (θ, c, η) with regret bounds
    """
    # Parameter grid
    theta_grid = [1, 2, 3, 5, 7, 10]
    tau_grid = [0, 0.1, 0.3, 0.5]
    eta_grid = [0, 0.5, 1.0, 2.0]

    best_loss = float('inf')
    best_params = None

    for theta in theta_grid:
        for tau in tau_grid:
            for eta in eta_grid:
                # Solve forward problem for each (μ_t, Σ_t)
                predicted = [
                    solve_forward(mu, sigma, theta, tau, eta)
                    for mu, sigma in zip(returns, covariance)
                ]

                # Compute discrepancy
                loss = sum(
                    np.linalg.norm(x_obs - x_pred)**2
                    for x_obs, x_pred in zip(portfolios, predicted)
                )

                if loss < best_loss:
                    best_loss = loss
                    best_params = (theta, tau, eta)

    # Bootstrap confidence intervals
    ci = bootstrap_ci(portfolios, returns, covariance, best_params, B=200)

    return {
        'theta': best_params[0],
        'tau': best_params[1],
        'eta': best_params[2],
        'confidence_intervals': ci,
        'regret': best_loss
    }
```

### 4.2 Solver Configuration

**Forward Problem Solver** (from paper):
- Gurobi 11.0
- Feasibility tolerance: 10^{-8}
- Optimality gap: 10^{-9}

**Inverse Problem Solver**:
- CVXPY 1.4.2 with OSQP
- Warm-starts with randomized initialization
- Avoid local minima

### 4.3 Validation Protocol

**In-Sample/Out-of-Sample Split**:
- Training: 80% of portfolios for parameter recovery
- Testing: 20% held-out for predictive regret evaluation

**Bootstrap Resampling**:
- B = 200 resamples (could use B = 500 for higher precision)
- Percentile confidence intervals
- Coverage probability = P(θ^{true} ∈ CI_{0.95}(θ̂))

---

## 5. Key Equations for Implementation

### 5.1 Forward Problem

**Objective**:
```
max f(x) = μ^T x - (θ/2) x^T Σx - c^T x
s.t. 1^T x = 1, x ≥ 0
```

**KKT Conditions**:
```
∇_x L = μ - θΣx* - c - λ1 + ν = 0
1^T x* = 1
x* ≥ 0, ν ≥ 0, ν_i x_i* = 0 ∀i
```

### 5.2 Inverse Problem

**Empirical Loss**:
```
L_T(θ,c) = (1/T) Σ_{t=1}^T ||x_t - x*(μ_t, Σ_t, θ, c)||_2^2
```

**Population Loss**:
```
L(θ,c) = E[||x_t - x*(μ_t, Σ_t, θ, c)||_2^2]
```

**Convergence**: sup_{θ∈Θ} |L_T(θ) - L(θ)| →^p 0

### 5.3 Dynamic Regret

**Cumulative Regret**:
```
R_T = Σ_{t=1}^T [f(x*(θ_t^{true})) - f(x*(θ̂_t))]
```

**Bound**:
```
R_T ≤ C_1√T + C_2 D
```
where D = Σ_{t=2}^T ||θ_t - θ_{t-1}||

**Normalized Regret** (should stabilize):
```
R_T/√T → constant as T → ∞
```

---

## 6. Limitations and Future Work

### 6.1 Limitations

1. **High-dimensional assets**: Paper uses n=10, real portfolios may have n>100
2. **Synthetic data only**: Real-data illustration limited to 2 ETFs
3. **Mean-variance framework**: Doesn't handle CVaR or other risk measures
4. **No short-sale constraints**: All portfolios long-only
5. **Perfect observability**: Assumes (μ_t, Σ_t) known without error

### 6.2 Future Extensions

For ARBS integration:

1. **High-dimensional inverse optimization** with L1 regularization
2. **CVaR-based inverse recovery** (extends beyond variance)
3. **Integration with behavioral models** (loss aversion, prospect theory)
4. **Real portfolio data** from ARBS execution logs
5. **Distributional robustness** to covariance estimation error

---

## 7. References

**Primary Citation**:
```bibtex
@article{cha2024inverse,
  title={Inverse Portfolio Optimization with Synthetic Investor Data:
         Recovering Risk Preferences under Uncertainty},
  author={Cha, Jinho and Pham, Long and Vo, Thi Le Hoa and
          Cho, Jaeyoung and Lee, Jaejin},
  journal={arXiv preprint arXiv:2510.06986v2},
  year={2024}
}
```

**Related Theory**:
- Aswani et al. (2018): "Inverse optimization with noisy data", *Operations Research*
- Bertsimas et al. (2015): "Data-driven estimation in equilibrium using inverse optimization"
- Keshavarz et al. (2011): "Imputing a convex objective function"

**Portfolio Applications**:
- Bruni et al. (2017): "A mixed-integer linear programming model for the inverse portfolio problem"
- Cesarone et al. (2020): "Inverse optimization models for portfolio selection"
- Bertsimas et al. (2021): "Inverse optimization for financial portfolio models"

---

## 8. ARBS Integration Checklist

### Phase 1: Infrastructure
- [ ] Implement `InverseOptimizer` class in `arbs/optimization/`
- [ ] Add `FactorModelCovariance` to match paper's Σ = FF^T + Ψ
- [ ] Create `ParameterCalibration` utility for grid search
- [ ] Bootstrap confidence interval implementation

### Phase 2: Validation
- [ ] Generate synthetic portfolios using ARBS forward optimizer
- [ ] Recover parameters and compare to ground truth
- [ ] Compute MSE, bias, variance, coverage (reproduce Table 2)
- [ ] Test on 3 investor types: Conservative, Neutral, ESG-Oriented

### Phase 3: Production
- [ ] Load historical ARBS allocations
- [ ] Estimate (μ_t, Σ_t) from returns data
- [ ] Run inverse optimization with B=200 bootstrap
- [ ] Monitor dynamic regret R_T/√T over time
- [ ] Alert if parameters drift beyond threshold

### Phase 4: Extensions
- [ ] Nonlinear transaction costs φ(x) = Σ κ_j |x_j|^p
- [ ] Distributional robustness with uncertainty set U
- [ ] Multi-period optimization with rebalancing
- [ ] Integration with TearSheet analytics

---

## Appendix: Numerical Results Summary

**Table 2 (Reproduced)**: Parameter Recovery Performance

| Parameter | True Value | Bias | Variance | MSE | Coverage |
|-----------|------------|------|----------|-----|----------|
| ρ (Risk) | [1,10] | 4.33 | 10.22 | 28.99 | 0.0% |
| τ (Cost) | [0,0.5] | -0.26 | 0.04 | 0.10 | 100% |
| η (ESG) | [0,2] | -0.18 | 0.46 | 0.49 | 0.0% |

**Key Takeaway**: Only transaction costs achieve nominal coverage. Risk aversion and ESG penalties require additional structure (priors, factor restrictions) for reliable inference.

**Convergence Rate**: MSE(θ̂) = O(T^{-α}) with empirical α ≈ 0.5, matching stochastic approximation theory.

---

**Last Updated**: 2024-10-13 (paper publication date)
**ARBS Compatibility**: Requires implementation (Phase 1-4 checklist above)
**Priority**: High (transaction cost calibration), Medium (risk aversion validation)
