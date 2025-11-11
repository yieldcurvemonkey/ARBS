# Deep Declarative Risk Budgeting Portfolios (2025)

**Authors**: Manuel Parra-Diaz, Carlos Castro-Iragorri
**Date**: April 29, 2025
**Source**: arXiv:2504.19980v1 [q-fin.PM]

## Overview

This paper introduces a robust end-to-end deep learning framework for risk budgeting portfolio optimization that reduces sensitivity to neural network initialization while maintaining performance. The framework uses a bounded softmax layer to ensure numerical stability.

## Risk Parity/Budgeting Formulation

### Mathematical Framework

**Portfolio Risk** (volatility):
```
σ(w) = √(w⊤Σw)
```
where:
- w = (w₁, w₂, ..., wₙ)⊤ is the vector of portfolio weights
- Σ ∈ ℝⁿˣⁿ is the covariance matrix of asset returns

**Marginal Risk Contribution** of asset i:
```
∂σ(w)/∂wᵢ = (Σw)ᵢ/σ(w)
```

**Total Risk Contribution** of asset i:
```
RCᵢ(w) = wᵢ · ∂σ(w)/∂wᵢ = wᵢ(Σw)ᵢ/σ(w)
```

### Risk Budgeting Problem

**Risk Budget Vector**: b = (b₁, b₂, ..., bₙ)⊤ where:
- Each bᵢ ≥ 0
- 1⊤b = 1 (budgets sum to one)
- Represents target proportions of total portfolio risk each asset should contribute

**Optimization Constraint**:
```
RCᵢ(w)/σ(w) = bᵢ  for i = 1, 2, ..., n

⟺  wᵢ(Σw)ᵢ = bᵢw⊤Σw  for i = 1, 2, ..., n
```
Subject to: 1⊤w = 1

**Risk Parity Special Case**: When all bᵢ = 1/n, the problem reduces to the well-known risk parity portfolio where each asset contributes equally to total risk.

### Convex Reformulation (Richard & Roncalli, 2019)

The classical risk budgeting problem is non-convex, but can be reformulated as:

```
y* = arg min_y (1/2)y⊤Σy - Σⁿⱼ₌₁ bⱼ ln(yⱼ)
subject to: y ≥ 0
```

**Optimal Portfolio Weights**:
```
w*ᵢ = y*ᵢ / Σⁿⱼ₌₁ y*ⱼ
```

Note: The quadratic form (1/2)y⊤Σy is used instead of √(y⊤Σy) for computational efficiency. Since both are monotonic, they yield the same optimal solutions.

## Comparison with Mean-Variance Optimization (MVO)

### Plug-In Approach (Classical Two-Step Process)

**Traditional Framework**:
1. **Prediction Stage**: Estimate parameters θ = (μ, Σ) from historical data D using procedure P
   - θ̂ = P(D)  (e.g., maximum likelihood estimation)
2. **Optimization Stage**: Plug estimates into objective function
   - w* = arg min_w U(w; θ̂)

**Risk Budgeting Plug-In**:
```
w* = arg min_w U(w; b, Σ)
where U(w; b, Σ) = Σⁿᵢ₌₁ [wᵢ(Σw)ᵢ - bᵢw⊤Σw]²
```

### Key Differences: Risk Budgeting vs MVO

| Aspect | Mean-Variance Optimization | Risk Budgeting |
|--------|---------------------------|----------------|
| **Objective** | Maximize return, minimize variance | Allocate risk according to budgets |
| **Parameters Required** | Expected returns (μ) AND covariance (Σ) | Only covariance (Σ) and risk budgets (b) |
| **Return Estimates** | Required - most unstable parameter | Not required |
| **Optimization Type** | Quadratic programming | Non-convex (but has convex reformulation) |
| **Stability** | Highly sensitive to return estimates | More stable (no return estimation) |
| **Bias-Variance** | Low variance, high bias | Better balanced |
| **Solution Uniqueness** | Unique solution | Unique only when all bᵢ > 0 |

### Criticisms of Classical MVO (from paper)

1. **Parameter Sensitivity**: "The ill-posed problem is recurrent in the 'predict then optimize' strategy where generally the optimal weights are instable and non-unique, meaning that small variation in the inputs that are plugged-in to the optimization problem can generate important source of instability in the end-results"

2. **Bias-Variance Tradeoff**: "One common critique of classical frameworks, such as Markowitz's theory, is that they often yield low-variance but highly biased results"

3. **Return Estimation Problem**: Expected returns are notoriously difficult to estimate accurately and are the primary source of instability in MVO

### End-to-End Framework Advantages

The paper's end-to-end framework integrates prediction and optimization, addressing limitations of both approaches:

**Loss Function Options**:
1. **Sharpe Ratio**: RSR(w) = -E[rw]/σw
   - Creates duality: convex layer minimizes variance, neural network maximizes returns
   - Balances risk-return tradeoff

2. **Cumulative Return**: RCR(w) = -∏ᵀₜ₌₁(1 + rwₜ)
   - Focuses purely on returns
   - More sensitive to market conditions

**Key Insight**: "We found this loss function gives a dual formulation aligned with the nature of risk budgeting, where the convex optimization layer minimizes portfolio variance, while the neural network seeks to maximize expected returns."

## ARBS Relevance: Risk Budgeting as Alternative to Mean-Variance

### Why Risk Budgeting Matters for ARBS

**1. Eliminates Return Forecasting Dependency**
- ARBS (like MVO) requires alpha forecasts (expected returns)
- Risk budgeting only requires covariance estimates
- Covariance is more stable to estimate than returns
- Can serve as **risk-aware benchmark** that doesn't depend on alpha quality

**2. Risk Allocation Framework**
- Explicit control over risk contributions
- Can implement **risk constraints** directly
- Aligns with risk management objectives
- Useful for **comparing against alpha-based strategies**

**3. Stability Properties**
- More robust to estimation error than MVO
- Unique solution when all risk budgets are strictly positive
- Less prone to extreme/concentrated positions
- Better out-of-sample performance in uncertain environments

**4. Benchmark Role**
From the paper's empirical results:
- Risk parity used as performance benchmark
- End-to-end risk budgeting "consistently outperforms the risk parity benchmark"
- Provides **baseline for measuring alpha value-add**

### Practical Implications for ARBS

**When Risk Budgeting Makes Sense**:
- When alpha signals are weak or uncertain
- As a **null hypothesis** (what returns would look like with no alpha?)
- For **risk model validation** (does our covariance estimate make sense?)
- As **fallback strategy** when alpha forecasts unavailable
- For **pure risk management** without return forecasting

**Integration Possibilities**:
1. **Hybrid Approach**: Combine alpha signals with risk budgeting constraints
   ```
   Objective: Maximize w⊤α (alpha exposure)
   Subject to: Risk contribution constraints from budgeting framework
   ```

2. **Performance Attribution**:
   - Compare ARBS portfolio vs risk parity portfolio
   - Isolate **alpha contribution** from **risk allocation effect**
   - Measure if alpha forecasts justify deviation from risk parity

3. **Risk Budgeting as Regularizer**:
   - Use risk parity weights as prior
   - Penalize deviations when alpha confidence is low
   - Automatically reduces to risk parity when alphas → 0

### Key Takeaway for ARBS

**Risk budgeting provides a principled alternative framework that**:
- Doesn't require return forecasts (only risk model)
- Can serve as benchmark for alpha-based strategies
- Offers stability advantages over mean-variance
- Suggests **risk parity as natural null portfolio** to beat
- Can be combined with alpha signals for hybrid approaches

The paper demonstrates that even simple risk allocation rules can be competitive with or outperform mean-variance optimization, especially when return estimates are noisy—a key consideration for ARBS strategy evaluation.

## Technical Innovation: Bounded Softmax Layer

### Problem with Standard Softmax
- Risk budgeting optimization requires all bᵢ > 0 for unique solution
- Standard softmax can produce near-zero budgets (e.g., 10⁻⁶)
- Causes numerical instability and non-unique solutions
- Violates diversification principles

### Bounded Softmax Solution

**Optimization Formulation**:
```
minimize_b  Σⁿⱼ₌₁ bᵢln(bᵢ) - x⊤b
subject to: 1⊤b = 1
            0 < b < 1
            b ≥ u  (lower bound constraint)
```

**Closed-Form Solution**:
Let A = {i ∈ {1,2,...,n} : e^xᵢ/Σⁿⱼ₌₁e^xⱼ ≥ u} with k = #(A)

```
bᵢ(x) = { (e^xᵢ/Σⱼ∈ₐe^xⱼ) · (1 - (n-k)u)  if i ∈ A
        { u                                 if i ∉ A
```

### Stability Results

**Dispersion Reduction (measured by range statistic)**:

In-Sample Period:
- Sharpe Ratio model: Maximum dispersion reduced from 10.19% → **1.91%**
- Cumulative Return model: Maximum dispersion reduced from 20.07% → **1.71%**

Out-of-Sample Period:
- Sharpe Ratio model: Maximum dispersion reduced from 11.32% → **0.87%**
- Cumulative Return model: Maximum dispersion reduced from 11.52% → **0.0183%**

**Key Result**: "70% to 100% more reliable (lower dispersion) than without this layer"

## References & Further Reading

**Core Risk Budgeting Papers**:
- Roncalli, T. (2013). *Introduction to risk parity and budgeting*. CRC Press.
- Richard, J.-C. and Roncalli, T. (2019). "Constrained risk budgeting portfolios: Theory, algorithms, applications & puzzles"

**End-to-End Portfolio Optimization**:
- Uysal et al. (2024). "End-to-end risk budgeting portfolio optimization with neural networks"
- Butler and Kwon (2022). "Data-driven integration of norm-penalized mean-variance portfolios"
- Anis and Kwon (2025). "End-to-end, decision-based, cardinality-constrained portfolio optimization"

**Stability & Robustness**:
- Brodie et al. (2009). "Sparse and stable markowitz portfolios" (L1 regularization)
- Georgantas et al. (2024). "Robust optimization approaches for portfolio selection: a comparative analysis"
- Costa and Iyengar (2023). "Distributionally robust end-to-end portfolio construction"

## Implementation Notes

**Framework Architecture**:
1. Input layer (asset features)
2. Hidden layer (Leaky ReLU activation)
3. **Bounded softmax layer** (risk budget estimation)
4. CvxPyLayer (risk budgeting optimization solver)
5. Output layer (portfolio weights)

**Hyperparameters Tested**:
- Hidden neurons: {7, 16, 32}
- Learning rate: {0.05, 0.1, 0.5, 1.0, 5.0, ..., 400} (includes "aggressive" rates ≥ 1.0)
- Training steps: {5, 10, 15, 20, 25, 30}

**Best Models**:
- Sharpe Ratio: 7 neurons, learning rate 10, 5 training steps
- Cumulative Return: 16 neurons, higher training steps required

**Key Finding**: Lower bound constraint on risk budgets ensures:
- Better-conditioned optimization problem
- Reduced overfitting to specific asset groups
- Meaningful diversification maintained
- Global convergence independent of initialization
