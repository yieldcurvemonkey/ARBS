# ABOUTME: Mathematical reference for portfolio optimization with quadratic transaction costs
# ABOUTME: Extracts key formulas, solution methods, and empirical results from Chen et al. (2019)

# Portfolio Optimization with Quadratic Transaction Costs

## Paper Metadata

**Title**: A Note on Portfolio Optimization with Quadratic Transaction Costs

**Authors**: Pierre Chen, Edmond Lezmi, Thierry Roncalli, Jiali Xu
**Affiliation**: Quantitative Research, Amundi Asset Management, Paris
**Date**: November 2019
**arXiv ID**: arXiv:2001.01612v1 [q-fin.PM]
**Publication Date**: 6 January 2020
**Keywords**: Portfolio allocation, mean-variance optimization, transaction cost, quadratic programming, alternating direction method of multipliers
**JEL Classification**: C61, G11

## Abstract

In this short note, we consider mean-variance optimized portfolios with transaction costs. We show that introducing quadratic transaction costs makes the optimization problem more difficult than using linear transaction costs. The reason lies in the specification of the budget constraint, which is no longer linear. We provide numerical algorithms for solving this issue and illustrate how transaction costs may considerably impact the expected returns of optimized portfolios.

## Key Contributions

1. **Complexity**: Quadratic transaction costs create a non-linear budget constraint, transforming the problem from standard QP to QCQP (quadratically constrained quadratic program)
2. **Solution Method**: ADMM (Alternating Direction Method of Multipliers) framework provides efficient numerical solution
3. **Empirical Impact**: Transaction costs significantly reduce efficient frontier returns, especially for large portfolio rebalancing

## Transaction Cost Models

### Linear Transaction Costs

The traditional approach assumes fixed bid-ask spreads. Transaction cost for asset $i$ is:

```latex
C_i(w | \tilde{w}) = \begin{cases}
c_i^- \cdot (\tilde{w}_i - w_i) & \text{if } w_i < \tilde{w}_i \\
0 & \text{if } w_i = \tilde{w}_i \\
c_i^+ \cdot (w_i - \tilde{w}_i) & \text{if } w_i > \tilde{w}_i
\end{cases}
```

Where:
- $\tilde{w}$ = current portfolio weights
- $w$ = target portfolio weights
- $c_i^-$ = bid transaction cost (selling)
- $c_i^+$ = ask transaction cost (buying)

**Total cost**: $C(w | \tilde{w}) = \sum_{i=1}^n C_i(w | \tilde{w})$

### Quadratic Transaction Costs

More realistic model where unit transaction cost is linear in trading size:

```latex
c_i(w | \tilde{w}) = \begin{cases}
c_i^- + \delta_i^- \cdot (\tilde{w}_i - w_i) & \text{if } w_i < \tilde{w}_i \\
0 & \text{if } w_i = \tilde{w}_i \\
c_i^+ + \delta_i^+ \cdot (w_i - \tilde{w}_i) & \text{if } w_i > \tilde{w}_i
\end{cases}
```

**Total cost for asset** $i$:

```latex
C_i(w | \tilde{w}) = \begin{cases}
c_i^- \cdot (\tilde{w}_i - w_i) + \delta_i^- \cdot (\tilde{w}_i - w_i)^2 & \text{if } w_i < \tilde{w}_i \\
0 & \text{if } w_i = \tilde{w}_i \\
c_i^+ \cdot (w_i - \tilde{w}_i) + \delta_i^+ \cdot (w_i - \tilde{w}_i)^2 & \text{if } w_i > \tilde{w}_i
\end{cases}
```

Parameters:
- $c_i^-, c_i^+$ = fixed cost components (bps)
- $\delta_i^-, \delta_i^+$ = quadratic cost coefficients (market impact)

**Economic Interpretation**: Unit cost increases with trade size, capturing market impact and liquidity effects (Lecesne & Roncoroni 2019a, 2019b).

## Mean-Variance Optimization Framework

### Without Transaction Costs

Standard Markowitz (1952) problem:

```latex
w^* = \arg\min \frac{1}{2} w^\top \Sigma w - \gamma w^\top \mu
```

Subject to:
```latex
\mathbf{1}_n^\top w = 1 \\
\mathbf{0}_n \leq w \leq \mathbf{1}_n
```

Where:
- $\mu$ = expected returns vector
- $\Sigma$ = covariance matrix
- $\gamma$ = risk aversion parameter

### With Transaction Costs

Net return accounting for costs:

```latex
R(w | \tilde{w}) = R(w) - C(w | \tilde{w})
```

**Modified budget constraint** (key difficulty):

```latex
\mathbf{1}_n^\top w + C(w | \tilde{w}) = 1
```

The wealth must cover both the new portfolio AND transaction costs.

**Optimization problem**:

```latex
w^* = \arg\min \frac{1}{2} w^\top \Sigma w - \gamma (w^\top \mu - C(w | \tilde{w}))
```

Subject to:
```latex
\mathbf{1}_n^\top w + C(w | \tilde{w}) = 1 \\
\mathbf{0}_n \leq w \leq \mathbf{1}_n
```

## Linear Transaction Costs: Augmented QP Solution

### Variable Augmentation

Introduce auxiliary variables:
- $\Delta w_i^- = \max(\tilde{w}_i - w_i, 0)$ = amount sold
- $\Delta w_i^+ = \max(w_i - \tilde{w}_i, 0)$ = amount bought

**Properties**:
- $\Delta w_i^- \cdot \Delta w_i^+ = 0$ (cannot buy and sell simultaneously)
- $w_i = \tilde{w}_i + \Delta w_i^+ - \Delta w_i^-$

### Augmented QP Formulation

Let $x = (w, \Delta w^-, \Delta w^+)$ be the $3n$-dimensional augmented variable.

```latex
x^* = \arg\min \frac{1}{2} x^\top Q x - x^\top R
```

Subject to:
```latex
Ax = B \\
x^- \leq x \leq x^+
```

**Matrices**:

```latex
Q = \begin{pmatrix}
\Sigma & \mathbf{0}_{n,n} & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & \mathbf{0}_{n,n} & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & \mathbf{0}_{n,n} & \mathbf{0}_{n,n}
\end{pmatrix}, \quad
R = \gamma \begin{pmatrix}
\mu \\
-c^- \\
-c^+
\end{pmatrix}
```

```latex
A = \begin{pmatrix}
\mathbf{1}_n^\top & (c^-)^\top & (c^+)^\top \\
I_n & I_n & -I_n
\end{pmatrix}, \quad
B = \begin{pmatrix}
1 \\
\tilde{w}
\end{pmatrix}
```

```latex
x^- = \mathbf{0}_{3n}, \quad
x^+ = \begin{pmatrix}
\mathbf{1}_n \\
\tilde{w} \\
\mathbf{1}_n - \tilde{w}
\end{pmatrix}
```

**Solution**: Standard QP solver (Scherer 2007, Roncalli 2013)

## Quadratic Transaction Costs: QCQP Problem

### The Non-Linear Budget Constraint

With quadratic costs, the budget constraint becomes:

```latex
\underbrace{\mathbf{1}_n^\top w + \Delta w^{-\top} c^- + \Delta w^{+\top} c^+}_{\text{Linear term}} +
\underbrace{\Delta w^{-\top} \Delta^- \Delta w^- + \Delta w^{+\top} \Delta^+ \Delta w^+}_{\text{Quadratic term}} = 1
```

Where $\Delta^- = \text{diag}(\delta_1^-, \ldots, \delta_n^-)$ and $\Delta^+ = \text{diag}(\delta_1^+, \ldots, \delta_n^+)$.

### QCQP Formulation

```latex
x^* = \arg\min \frac{1}{2} x^\top Q x - x^\top R
```

Subject to:
```latex
A_1 x + x^\top C_1 x = B_1 \quad \text{(quadratic budget constraint)} \\
A_2 x = B_2 \quad \text{(linear constraints)} \\
x^- \leq x \leq x^+
```

**Matrices**:

```latex
Q = \begin{pmatrix}
\Sigma & \mathbf{0}_{n,n} & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & 2\gamma\Delta^- & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & \mathbf{0}_{n,n} & 2\gamma\Delta^+
\end{pmatrix}, \quad
C_1 = \begin{pmatrix}
\mathbf{0}_{n,n} & \mathbf{0}_{n,n} & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & \Delta^- & \mathbf{0}_{n,n} \\
\mathbf{0}_{n,n} & \mathbf{0}_{n,n} & \Delta^+
\end{pmatrix}
```

**Complexity**: QCQP is NP-hard in general. The non-convex quadratic equality constraint makes standard QP solvers inapplicable.

## ADMM Solution Method

### ADMM Framework

Reformulate as consensus problem (Gabay & Mercier 1976, Boyd et al. 2011):

```latex
\{x^*, y^*\} = \arg\min_{(x,y)} f_x(x) + f_y(y)
```

Subject to:
```latex
x - y = \mathbf{0}_n
```

Where:
- $f_x(x) = \frac{1}{2} x^\top Q x - x^\top R + \mathbb{1}_{\Omega_x}(x)$
- $f_y(y) = \mathbb{1}_{\Omega_y}(y)$
- $\Omega_x = \{x \in [0,1]^n : A_2 x = B_2, x^- \leq x \leq x^+\}$
- $\Omega_y = \{y \in [0,1]^n : A_1 y + y^\top C_1 y = B_1\}$

### ADMM Algorithm

Initialize $y^{(0)}, u^{(0)}$, set penalty parameter $\varphi > 0$. Iterate:

**1. x-update (QP problem)**:

```latex
x^{(k+1)} = \arg\min_x \left\{ \frac{1}{2} x^\top (Q + \varphi I_{3n}) x - x^\top (R + \varphi(y^{(k)} - u^{(k)})) \right\}
```

Subject to:
```latex
A_2 x = B_2 \\
x^- \leq x \leq x^+
```

**2. y-update (QCQP projection)**:

```latex
y^{(k+1)} = \arg\min_y \frac{1}{2} \|y - v_y^{(k+1)}\|_2^2
```

Subject to:
```latex
y \in \Omega_y
```

Where $v_y^{(k+1)} = x^{(k+1)} + u^{(k)}$.

**3. u-update (dual variable)**:

```latex
u^{(k+1)} = u^{(k)} + x^{(k+1)} - y^{(k+1)}
```

### y-Update Solution

**Case 1**: Constant coefficients $\delta_i^- = \delta^-$ and $\delta_i^+ = \delta^+$

The KKT conditions reduce to a **quintic equation** in $\lambda$:

```latex
\alpha_5 \lambda^5 + \alpha_4 \lambda^4 + \alpha_3 \lambda^3 + \alpha_2 \lambda^2 + \alpha_1 \lambda + \alpha_0 = 0
```

**Computational cost**: $O(5^3) = O(125)$ to find roots, versus $O((3n+1)^3)$ for Newton-Raphson.

Once $\lambda^*$ is found, the solution is:

```latex
w_i = v_i - \lambda^* \\
\Delta w_i^- = \frac{\Delta v_i^- - \lambda^* c_i^-}{1 + 2\lambda^* \delta^-} \\
\Delta w_i^+ = \frac{\Delta v_i^+ - \lambda^* c_i^+}{1 + 2\lambda^* \delta^+}
```

**Case 2**: Asset-specific coefficients $\delta_i^- \neq \delta_j^-$ and $\delta_i^+ \neq \delta_j^+$

Polynomial equation becomes degree $2n+1$. Alternative: Use interior-point method with Park & Boyd (2017) heuristics for non-convex QCQP.

**Key insight** (Park & Boyd 2017): The function is **monotone decreasing**, guaranteeing a unique root. Use **bisection method** to solve:

```latex
\sum_{i=1}^n (v_i - \lambda) + \sum_{i=1}^n \frac{c_i^- (\Delta v_i^- - \lambda c_i^-)}{1 + 2\lambda \delta_i^-} +
\sum_{i=1}^n \frac{c_i^+ (\Delta v_i^+ - \lambda c_i^+)}{1 + 2\lambda \delta_i^+} +
\sum_{i=1}^n \frac{\delta_i^- (\Delta v_i^- - \lambda c_i^-)^2}{(1 + 2\lambda \delta_i^-)^2} +
\sum_{i=1}^n \frac{\delta_i^+ (\Delta v_i^+ - \lambda c_i^+)^2}{(1 + 2\lambda \delta_i^+)^2} - 1 = 0
```

## Efficient Frontier with Transaction Costs

### Net Expected Return

**Key issue**: With transaction costs, $\sum_{i=1}^n w_i^* < 1$ (wealth reduced by costs).

**Incorrect approach**: Plot $(\sigma(w^*), \mu(w^*))$ - misleading because portfolio notional is reduced.

**Correct approach**: Normalize and adjust for costs:

```latex
\bar{w}^* = \frac{w^*}{\sum_{i=1}^n w_i^*}
```

**Net expected return**:

```latex
\mu_{\text{net}}(\bar{w}^*) = \mu(\bar{w}^*) - C(w^* | \tilde{w})
```

**Efficient frontier**: Plot $(\sigma(\bar{w}^*), \mu_{\text{net}}(\bar{w}^*))$

### Cumulative Impact

Transaction costs are paid at **each rebalancing**. For $K$ rebalancing events per year:

```latex
\text{Annual cost} \approx K \cdot C(w^* | \tilde{w})
```

**Example** (from paper): With 5 rebalancing events, cumulative costs can reduce annual returns by 1-3%, even with modest per-trade costs.

## Empirical Results (Paper Example)

### Test Universe

- **Assets**: 7 assets with $\mu_i = \sigma_i$ ranging from 1% to 10%
- **Correlation**: Constant 25% between all pairs
- **Initial portfolio**: 50% Asset 1, 50% Asset 2
- **Target**: Increase volatility from 2% to 4%

### Parameter Scenarios

**Realistic case**:
- $c^- = 20$ bps, $c^+ = 10$ bps (linear)
- $\delta^- = \delta^+ = 0$ (no quadratic component)

**High cost case**:
- $c^- = 2\%$, $c^+ = 1\%$ (linear)
- $\delta^- = 5\%$, $\delta^+ = 5\%$ (quadratic)

### Key Findings

1. **Portfolio Differences**: Optimal portfolios differ significantly between no-cost, linear-cost, and quadratic-cost cases
2. **Turnover Reduction**: Quadratic costs induce lower turnover than linear costs
3. **Asset Selection**: With quadratic costs, optimizer selects high-return assets to compensate for costs
4. **Efficient Frontier Impact**:
   - Linear costs: Modest shift down from Markowitz frontier
   - Quadratic costs: Severe degradation, efficient frontier peaks and declines
5. **Rebalancing Limits**: With quadratic costs, aggressive rebalancing becomes suboptimal beyond certain volatility threshold

### Comparison Table (from paper)

Rebalancing from 2% to 4% volatility:

| Portfolio | $w_{\text{MVO}}^*$ | $w_{\text{LC}}^*$ | $w_{\text{QC}}^*$ |
|-----------|-------------------|-------------------|-------------------|
| Asset 1   | 0.01              | 0.00              | 6.70              |
| Asset 2   | 0.08              | 14.52             | 10.84             |
| Asset 7   | 19.22             | 26.74             | 29.13             |
| $C_{\text{LC}}$ | 1.58%       | 0.98%             | 0.94%             |
| $C_{\text{QC}}$ | 2.52%       | 1.63%             | 1.49%             |
| $\mu_{\text{net}}^{\text{LC}}$ | 4.50% | 4.88%   | 4.79%             |
| $\mu_{\text{net}}^{\text{QC}}$ | 3.56% | 4.23%   | 4.24%             |

**Interpretation**: Quadratic costs reduce net return by ~0.6% versus linear costs, demonstrating material economic impact.

## ARBS Integration (Future Enhancement)

### Current ARBS Architecture

ARBS currently implements **zero transaction costs** in `MeanVarianceOptimizer`:

```
src/arbs/optimize/optimizer.py:
  - minimize: (1/2) * w^T * Σ * w - γ * w^T * μ
  - No cost terms in objective
  - No cost-adjusted budget constraint
```

### Proposed Enhancement

**Phase 1**: Linear transaction costs
- Add `transaction_costs` parameter to `MeanVarianceOptimizer`
- Implement augmented QP formulation (Section 3.1)
- Use existing CVXPY/scipy QP solver

**Phase 2**: Quadratic transaction costs
- Implement ADMM algorithm (Section 4.2)
- Add `QuadraticTransactionCosts` class with $c^{\pm}, \delta^{\pm}$ parameters
- Integrate bisection method for y-update

**Phase 3**: Realistic backtesting
- Multi-period rebalancing with cumulative costs
- Turnover constraints based on cost parameters
- IC analysis with and without transaction costs

### Research Questions for ARBS

1. **Signal Decay vs. Costs**: When does signal decay justify rebalancing despite costs?
2. **Optimal Rebalancing Frequency**: Trade-off between signal freshness and cost accumulation
3. **Cost Calibration**: Estimate $\delta^{\pm}$ parameters from futures market data (bid-ask, market impact)
4. **Carry Signal Robustness**: Does carry signal remain predictive after realistic transaction costs?

### Implementation Considerations

**Numerical stability**:
- ADMM convergence: Monitor primal/dual residuals
- Bisection bounds: Use asset bounds to bracket $\lambda^*$
- Singular covariance: Add small ridge penalty

**Performance**:
- x-update: Sparse QP solver for large portfolios
- y-update: Vectorized bisection for all assets simultaneously
- Caching: Reuse Cholesky factorization across ADMM iterations

**Testing**:
- Unit tests: Verify ADMM recovers QP solution when $\delta = 0$
- Integration tests: Match paper examples (Table 1)
- Property tests: Check budget constraint satisfaction, weight bounds

## References

**Primary Reference**:
- Chen, P., Lezmi, E., Roncalli, T., & Xu, J. (2019). A Note on Portfolio Optimization with Quadratic Transaction Costs. arXiv:2001.01612v1 [q-fin.PM].

**Foundation**:
- Markowitz, H. (1952). Portfolio Selection. *Journal of Finance*, 7(1), 77-91.
- Scherer, B. (2007). *Portfolio Construction & Risk Budgeting* (3rd ed.). Risk Books.

**ADMM Algorithm**:
- Gabay, D., & Mercier, B. (1976). A Dual Algorithm for the Solution of Nonlinear Variational Problems via Finite Element Approximation. *Computers & Mathematics with Applications*, 2(1), 17-40.
- Boyd, S., Parikh, N., Chu, E., Peleato, B., & Eckstein, J. (2011). Distributed Optimization and Statistical Learning via the Alternating Direction Method of Multipliers. *Foundations and Trends in Machine Learning*, 3(1), 1-122.

**QCQP Methods**:
- Park, J., & Boyd, S. (2017). General Heuristics for Nonconvex Quadratically Constrained Quadratic Programming. arXiv:1703.07870.

**Market Impact Models**:
- Lecesne, L., & Roncoroni, A. (2019a). Optimal Allocation in the S&P 600 Under Size-driven Illiquidity. *ESSEC Working Paper*.
- Lecesne, L., & Roncoroni, A. (2019b). How Should Funds Decisions and Performances React to Size-Driven Liquidity Friction. *ESSEC Working Paper*.

**ARBS Architecture**:
- Perrin, S., & Roncalli, T. (2019). Machine Learning Algorithms and Portfolio Optimization. In Jurczenko, E. (Ed.), *Machine Learning in Asset Management*. ISTE Press – Elsevier.
- Roncalli, T. (2013). *Introduction to Risk Parity and Budgeting*. Chapman and Hall/CRC Financial Mathematics Series.

## Cross-References

**Related ARBS Documentation**:
- `/home/user/ARBS/docs/architecture/optimizer.md` - Mean-variance optimizer implementation
- `/home/user/ARBS/docs/architecture/risk-models.md` - Covariance estimation methods
- `/home/user/ARBS/src/arbs/optimize/optimizer.py` - Current optimizer without transaction costs

**Future Enhancements**:
- Transaction cost estimation from bid-ask spreads
- Multi-period optimization with path-dependent costs
- Turnover constraints and cardinality penalties
- DV01 limits for fixed income portfolios
