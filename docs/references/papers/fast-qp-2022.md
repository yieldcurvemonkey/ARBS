# Fast Successive QP Algorithm for Mean-Variance Portfolio Optimization

**Paper**: A Fast Successive QP Algorithm for General Mean-Variance Portfolio Optimization
**Authors**: Shengjie Xiu, Xiwen Wang, and Daniel P. Palomar (HKUST)
**arXiv**: [arXiv:2212.06983v1 [eess.SP]](https://arxiv.org/abs/2212.06983) (14 Dec 2022)
**Published**: IEEE Transactions on Signal Processing (anticipated)

---

## Abstract

The mean and variance of portfolio returns are the standard quantities to measure the expected return and risk of a portfolio. Efficient portfolios that provide optimal trade-offs between mean and variance warrant consideration. To express a preference among these efficient portfolios, investors have put forward many mean-variance portfolio (MVP) formulations which date back to the classical Markowitz portfolio. However, most existing algorithms are highly specialized to particular formulations and cannot be generalized for broader applications. Therefore, a fast and unified algorithm would be extremely beneficial.

In this paper, we first introduce a general MVP problem formulation that can fit most existing cases by exploring their commonalities. Then, we propose a widely applicable and provably convergent successive quadratic programming algorithm (SCQP) for the general formulation. The proposed algorithm can be implemented based on only the QP solvers and thus is computationally efficient. In addition, a fast implementation is considered to accelerate the algorithm. The numerical results show that our proposed algorithm significantly outperforms the state-of-the-art ones in terms of convergence speed and scalability.

---

## General MVP Formulation

### Problem Statement

The general mean-variance portfolio problem is formulated as:

$$
\begin{aligned}
\min_{w} \quad & f(w) \triangleq F(x(w), y(w)) \\
\text{s.t.} \quad & x_i(w) \geq a_i, \quad i = 1,\ldots,p \\
& y_j(w) \leq b_j, \quad j = 1,\ldots,q \\
& w \in \mathcal{W}
\end{aligned} \qquad (\mathcal{P})
$$

where:

- **Portfolio weights**: $w \in \mathbb{R}^N$
- **Expected returns**: $x(w) = [x_1(w),\ldots,x_p(w)]^\top$ with $x_i(w) = w^\top \mu_i$
- **Risk measures**: $y(w) = [y_1(w),\ldots,y_q(w)]^\top$ with $y_j(w) = w^\top \Sigma_j w$
- **Objective function**: $F: \mathbb{R}^p \times \mathbb{R}^q \to \mathbb{R}$ (continuously differentiable, possibly nonconvex)
- **Mean-variance constraints**: Lower limits $a_i$ on returns, upper limits $b_j$ on risk
- **Feasible set**: $\mathcal{W} = \{w \geq 0, \mathbf{1}^\top w = 1\}$ (long-only + budget constraint)

**Compact constraint notation**:

$$
g(w) \triangleq \begin{bmatrix} g_x(w) \\ g_y(w) \end{bmatrix} \leq 0
$$

where:

$$
[g_x(w)]_i \triangleq a_i - x_i(w), \quad [g_y(w)]_j \triangleq y_j(w) - b_j
$$

### Key Assumption

**Assumption 1** (Rational risk-return trade-off): For each $x_i$ and $y_j$ that exists in $F$:

$$
\nabla_{x_i} F(x,y) < 0, \quad \nabla_{y_j} F(x,y) > 0
$$

This means higher expected return is always better, and more risk is always worse.

---

## Representative MVP Formulations

| Portfolio | $F(x(w), y(w))$ | $g(w) \leq 0$ | Problem Class |
|-----------|----------------|---------------|---------------|
| **Markowitz** | $-x(w) + \frac{\alpha}{2}y(w)$ | - | QP |
| **MSRP** | $-\frac{x(w) - r_f}{\sqrt{y(w)}}$ | - | FP |
| **MGSRP** | $-\frac{x(w) - r_f}{y(w)^\beta}$ | - | FP |
| **Worst-case robust GMRP** | $-x(w) + \alpha\sqrt{y(w)}$ | - | SOCP |
| **Expected utility** | $-U(x(w)) - \frac{1}{2}U''(x(w))y(w)$ | - | Depends on $U$ |
| **Kelly** | $-\log(1 + x(w)) + \frac{1}{2}\frac{y(w)}{(1+x(w))^2}$ | - | - |
| **Return-constrained** | $y(w)$ | $x(w) \geq a$ | QP |
| **Risk-constrained** | $-x(w)$ | $y(w) \leq b$ | QCQP |

### Example: Maximum Sharpe Ratio Portfolio (MSRP)

The Sharpe ratio evaluates expected excess return per unit of volatility:

$$
\text{Sharpe Ratio} = \frac{x(w) - r_f}{\sqrt{y(w)}}
$$

The MSRP objective is:

$$
F_{\text{SR}}(x(w), y(w)) = -\frac{x(w) - r_f}{\sqrt{y(w)}}
$$

or equivalently, the inverse Sharpe ratio:

$$
F_{\text{SR}}(x(w), y(w)) = \frac{\sqrt{y(w)}}{x(w) - r_f}
$$

### Example: Worst-case Robust GMRP

With uncertainty ellipsoid $\mathcal{U}_\mu = \{\mu = \hat{\mu} + \alpha \Sigma^{1/2}u \mid \|u\|_2 \leq 1\}$:

$$
F_{\text{WC}}(x(w), y(w)) = -x(w) + \alpha\sqrt{y(w)}
$$

### Example: Kelly Portfolio

Maximizes expected log return (growth-optimal):

$$
F_{\text{KL}}(x(w), y(w)) = -\log(1 + x(w)) + \frac{1}{2}\frac{y(w)}{(1+x(w))^2}
$$

using mean-variance approximation to $\mathbb{E}[U(w^\top r)]$.

---

## SCQP Algorithm

### Algorithmic Framework

The SCQP algorithm solves $\mathcal{P}$ via a sequence of **QP surrogate problems**:

$$
\min_{w \in \mathcal{W}} \quad -(\lambda_x + \eta_x)^\top x(w) + (\lambda_y + \eta_y)^\top y(w)
$$

where:

- $\lambda = [\lambda_x; \lambda_y] \geq 0$: weights characterizing mean-variance trade-off from $f$
- $\eta = [\eta_x; \eta_y] \geq 0$: weights controlling impact of constraints $g(w) \leq 0$

**Equivalence to standard QP form**:

$$
\min_{w \in \mathcal{W}} \quad -w^\top \bar{\mu} + \frac{1}{2}w^\top \bar{\Sigma}w
$$

where:

$$
\bar{\mu} = \sum_{i=1}^p (\lambda_{x,i} + \eta_{x,i})\mu_i, \quad \bar{\Sigma} = \sum_{j=1}^q 2(\lambda_{y,j} + \eta_{y,j})\Sigma_j
$$

### Double-Loop Structure

**Outer loop**: Updates $\lambda$ to handle objective function $f$
**Inner loop**: Updates $\eta$ to handle constraints $g(w) \leq 0$

---

## Algorithm 1: SCQP

**Input**: $k=0$, $w^0 \in \mathcal{K}$, $\eta^0 \geq 0$, step sizes $\{\alpha^l\}, \{\gamma^k\} \in (0,1]$

**Repeat** (outer loop):

1. **Update weights from objective**:
   $$
   \lambda_x^k = -\nabla_x F(x^k, y^k), \quad \lambda_y^k = \nabla_y F(x^k, y^k)
   $$

2. **If** $\mathcal{K} = \mathcal{W}$ (no mean-variance constraints):
   - Solve QP: $\hat{w}^k = \hat{w}(\lambda^k, 0)$

3. **Else** (mean-variance constraints present):

   Set $l = 0$

   **Repeat** (inner loop):
   - Solve QP: $\hat{w}^k = \hat{w}(\lambda^k, \eta^l)$
   - Update multipliers: $\eta^{l+1} = [\eta^l + \alpha^l g(\hat{w}^k)]_+$
   - $l \leftarrow l + 1$

   **Until** convergence

4. **Update iterate**:
   $$
   w^{k+1} = w^k + \gamma^k(\hat{w}^k - w^k)
   $$

5. $k \leftarrow k + 1$

**Until** convergence: $|w^{k+1} - w^k| \leq \epsilon$

**Output**: Stationary solution $w^{k+1}$ of $\mathcal{P}$

---

## Closed-Form Weight Updates

| Portfolio | $\lambda$ Updates |
|-----------|------------------|
| **Markowitz** | $\lambda_x \leftarrow 1$, $\lambda_y \leftarrow \alpha/2$ |
| **MSRP** | $\lambda_x \leftarrow 1$, $\lambda_y \leftarrow (x^k - r_f)/(2y^k)$ |
| **GMSRP** | $\lambda_x \leftarrow 1$, $\lambda_y \leftarrow \beta(x^k - r_f)/y^k$ |
| **Worst-case robust GMRP** | $\lambda_x \leftarrow 1$, $\lambda_y \leftarrow \alpha/(2\sqrt{y^k})$ |
| **Expected utility** | $\lambda_x \leftarrow U'(x^k) + U'''(x^k)y^k/2$, $\lambda_y \leftarrow -U''(x^k)/2$ |
| **Kelly** | $\lambda_x \leftarrow 1/(1+x^k) + y^k/(1+x^k)^3$, $\lambda_y \leftarrow 1/(2(1+x^k)^2)$ |

For constrained variants:

$$
\eta_x \leftarrow [\eta_x + \alpha(a - x(w^*))]_+, \quad \eta_y \leftarrow [\eta_y + \alpha(y(w^*) - b)]_+
$$

---

## Convergence Theory

### Inner Loop Convergence

**Proposition 2**: Under Assumption 1, suppose $\alpha^l$ is chosen according to **Armijo rule along the projection arc**, then the sequence $\{\hat{w}(\lambda^k, \eta^l)\}_{l=1}^\infty$ generated by the inner loop converges to the optimal solution of the surrogate problem.

**Armijo rule**: Select $\alpha^{\text{init}} > 0$, $\sigma, \beta \in (0,1)$, and choose $\alpha^l$ as the largest element in $\{\alpha^{\text{init}}\beta^j\}_{j=0,1,\ldots}$ satisfying:

$$
h(\eta^{l+1}; \lambda^k) - h(\eta^l; \lambda^k) \geq \sigma g(\hat{w}(\lambda^k, \eta^l))^\top (\eta^{l+1} - \eta^l)
$$

where $h$ is the Lagrangian dual function and:

$$
\eta^{l+1} = [\eta^l + \alpha^l g(\hat{w}(\lambda^k, \eta^l))]_+
$$

The gradient of the dual function is:

$$
\nabla h(\eta^l; \lambda^k) = g(\hat{w}(\lambda^k, \eta^l))
$$

### Outer Loop Convergence

**Assumption 3**:
- At least one $y_j(w)$ exists in $F$
- $f$ has Lipschitz continuous gradient on $\mathcal{K}$

**Proposition 3**: Under Assumptions 1 and 3, suppose $\gamma^k \in (0,1]$, $\gamma^k \to 0$, and $\sum_k \gamma^k = +\infty$. Then either:

1. Algorithm 1 converges in a finite number of iterations to a stationary solution of $\mathcal{P}$, or
2. Every limit point of the solution sequence $\{w^k\}_{k=1}^\infty$ is a stationary solution of $\mathcal{P}$

**Stationary condition**:

$$
(z - w^*)^\top \nabla f(w^*) \geq 0, \quad \forall z \in \mathcal{K}
$$

---

## Connection to Pareto Optimality

### Multiobjective Formulation

Portfolio selection can be viewed as a multiobjective optimization problem:

$$
\min_{w \in \mathcal{W}} \quad \{-x_1(w), \ldots, -x_p(w), y_1(w), \ldots, y_q(w)\}
$$

**Lemma 1**: Under Assumptions 1 and 2, every stationary solution of $\mathcal{P}$ is a **Pareto optimal solution** of the multiobjective problem.

**Assumption 2**: For each $x_i$ and $y_j$ that does not exist in $F$:

$$
x_i(w^*) = a_i, \quad y_j(w^*) = b_j
$$

(i.e., constraints are active for objectives not in the objective function)

### Weighting Method

The QP surrogate problem coincides with the **weighting method** for Pareto optimality:

$$
\min_{w \in \mathcal{W}} \quad -v_x^\top x(w) + v_y^\top y(w)
$$

where $v_x = \lambda_x + \eta_x$ and $v_y = \lambda_y + \eta_y$ are the weighting coefficients.

**Properties**:
1. Every Pareto optimal solution can be found by the weighting method with proper weights
2. The unique solution of the weighting problem is always Pareto optimal

**Key insight**: SCQP tracks the Pareto frontier by dynamically adjusting $\lambda$ and $\eta$, ensuring every point in the solution sequence $\{\hat{w}^k\}$ is Pareto optimal.

---

## Fast Implementation via Active-Set Strategy

### Sparsity Pattern on Pareto Frontier

Pareto optimal solutions are naturally **sparse** under long-only constraints because:

1. The long-only constraint acts like an $\ell_1$-norm penalty promoting sparsity
2. Portfolios concentrate on a small number of high-return assets
3. Sparsity pattern is **similar between neighboring portfolios**

This enables:
- **Dimension reduction**: Solve QP only on assets with $w_i > 0$
- **Warm starting**: Use previous solution to initialize next QP

### General QP Surrogate Problem

$$
\begin{aligned}
\min_{w \in \mathbb{R}^N} \quad & q(w) = c^\top w + \frac{1}{2}w^\top H w \\
\text{s.t.} \quad & A w = b \\
& l \leq w \leq u
\end{aligned}
$$

where $H \in \mathbb{S}^N_{++}$, $A \in \mathbb{R}^{M \times N}$, $b \in \mathbb{R}^M$, $l, u \in \mathbb{R}^N$.

For MVP: $A = \mathbf{1}^\top$, $b = 1$, $l = 0$, $u = +\infty$.

### Working Set Strategy

Define **working set** $\bar{L} \cup \bar{U}$ where $\bar{L} \cap \bar{U} = \emptyset$.

Solve **reduced problem**:

$$
\begin{aligned}
\min_{w \in \mathbb{R}^N} \quad & c^\top w + \frac{1}{2}w^\top H w \\
\text{s.t.} \quad & A w = b \\
& l_i \leq w_i \leq u_i, \quad i \notin \bar{L} \cup \bar{U} \\
& w_i = l_i, \quad i \in \bar{L} \\
& w_i = u_i, \quad i \in \bar{U}
\end{aligned}
$$

This is equivalent to solving the original problem **if and only if**:

$$
\beta_i^l \geq 0, \quad \forall i \in \bar{L}, \qquad \beta_i^u \geq 0, \quad \forall i \in \bar{U}
$$

where $\beta^l_i$ and $\beta^u_i$ are Lagrange multipliers for $w_i = l_i$ and $w_i = u_i$.

---

## Algorithm 2: New Active-Set Strategy

**Input**: Initial working set $\bar{L}^0 \cup \bar{U}^0$

**For** $k = 0, 1, 2, \ldots$:

1. **Solve reduced QP**: Compute $w^k$, $\beta^l$, $\beta^u$ given $\{\bar{L}^k, \bar{U}^k\}$

2. **Check optimality**:
   - **If** $\min(\beta^l) < 0$ or $\min(\beta^u) < 0$:
     - Remove violated constraints:
       $$
       \bar{L}^{k+1} = \bar{L}^k \setminus \{i \mid \beta^l_i < 0\}
       $$
       $$
       \bar{U}^{k+1} = \bar{U}^k \setminus \{i \mid \beta^u_i < 0\}
       $$
   - **Else**: Stop (optimal solution found)

**Output**: Optimal solution $w^k$

**Proposition 4**: The sequence $\{w^k\}$ generated by Algorithm 2 converges to the optimal solution within $|\bar{L}^0 \cup \bar{U}^0|$ iterations.

**Proof**: Each iteration decreases working set size by at least 1 and strictly decreases objective value. Minimum working set size is 0 (optimality), so convergence is guaranteed in finite steps.

### Warm Starting

For a **sequence of related QPs**, use the optimal working set of the previous QP as the initial guess for the next QP.

**Empirical performance**: Typically solves each QP in **less than 3 iterations** with warm starting.

---

## Computational Complexity

### Time Complexity Analysis

| Problem | Method | Empirical Time Complexity $O(N^c)$ |
|---------|--------|-----------------------------------|
| **Worst-case robust GMRP** | SCQP | $O(N^{1.155})$ |
| | MOSEK | $O(N^{1.691})$ |
| | ECOS | $O(N^{2.453})$ |
| | NLopt | $O(N^{3.134})$ |
| **Kelly portfolio** | SCQP | $O(N^{0.944})$ |
| | MM | $O(N^{1.620})$ |
| | NLopt | $O(N^{3.241})$ |
| **Risk-constrained** | SCQP | $O(N^{1.137})$ |
| | MOSEK | $O(N^{1.615})$ |
| | ECOS | $O(N^{2.365})$ |
| | NLopt | $O(N^{3.140})$ |
| **MSRP (constrained)** | SCQP | $O(N^{0.768})$ |
| | Dinkelbach | $O(N^{1.786})$ |
| | QT | $O(N^{1.853})$ |
| | NLopt | $O(N^{3.085})$ |

**Key observations**:

1. SCQP achieves **near-linear** or **sub-linear** empirical complexity
2. Standard QP solver complexity is $O(N^3)$ for a single problem
3. SCQP exploits sparsity via active-set strategy for massive speedup
4. Advantage increases with problem dimension $N$

### Speedup Factors

For $N = 400$ assets:

- **vs. MOSEK**: 4.7× to 8.7× faster
- **vs. ECOS**: 2.5× to 10× faster
- **vs. NLopt**: 10.5× to 100× faster
- **vs. MM**: 10× faster
- **vs. Dinkelbach/QT**: 5× to 10× faster

---

## Numerical Results Summary

### Test Setup

- **Data**: S&P 500 stocks, random subsets of size $N$
- **Period**: Random 5N-day windows from 2008-12-01 to 2018-12-01
- **Trials**: 20 independent realizations per configuration
- **Termination**: $|w^{k+1} - w^k| \leq 10^{-6}$ (or solver defaults for ECOS/MOSEK)
- **Implementation**: R 3.6.3, quadprog QP solver

### Convergence Speed

Typical convergence to gap $< 10^{-9}$:

- **SCQP**: 10-20 iterations (outer loop), <3 iterations per QP (inner loop with warm start)
- **Interior point (ECOS/MOSEK)**: 20-50 iterations
- **FP algorithms (Dinkelbach/QT)**: 30-100 iterations
- **MM**: 50-200 iterations
- **NLopt**: 100-500 iterations
- **Metaheuristics (DEoptim/GA)**: Often fail to converge in reasonable time

### Scalability

SCQP scales to **large portfolios** ($N > 400$) efficiently, while:

- Interior point methods struggle beyond $N = 200$
- Specialized methods (MM, Dinkelbach) are competitive but slower
- General nonlinear solvers become impractical for $N > 100$

---

## Connection to Existing Algorithms

SCQP **generalizes** several problem-specific algorithms:

### 1. Quadratic Transform for MSRP

The MSRP problem $\min -\frac{(x(w) - r_f)^2}{y(w)}$ has QT subproblem:

$$
\min_{w \in \mathcal{W}} \quad -\frac{2(x^k - r_f)}{y^k}(x(w) - r_f) + \frac{x^k - r_f}{y^k}{}^2 y(w)
$$

This **matches SCQP surrogate** with weights $\lambda_x = 1$, $\lambda_y = (x^k - r_f)/(2y^k)$ (after scaling).

### 2. Dinkelbach's Algorithm for MGSRP

For MGSRP with $\beta = 1$, Dinkelbach's algorithm solves:

$$
\min_{w \in \mathcal{W}} \quad -(x(w) - r_f) + \frac{x^k - r_f}{y^k} y(w)
$$

**Identical to SCQP surrogate** with the same weight updates.

### 3. MM for Worst-case Robust GMRP

MM constructs upper-bound problem:

$$
\min_{w \in \mathcal{W}} \quad -x(w) + \frac{\alpha}{2}\left(\frac{y(w)}{\sqrt{y^k}} + \sqrt{y^k}\right)
$$

**Matches SCQP surrogate** with $\lambda_x = 1$, $\lambda_y = \alpha/(2\sqrt{y^k})$.

**Conclusion**: SCQP is a **unified framework** that includes these specialized algorithms as special cases while being applicable to arbitrary MVP formulations.

---

## ARBS Integration and Relevance

### Optimizer Performance Improvements

1. **Mean-Variance Optimizer Enhancement**
   - Current: Direct QP solve of Markowitz problem
   - Enhancement: Use SCQP for constrained variants (return/risk constraints)
   - Benefit: ~5-10× speedup for large portfolios ($N > 100$)

2. **Multiple Signal Integration**
   - Current: Single covariance matrix $\Sigma$
   - Enhancement: Multiple estimates $\{\Sigma_1, \ldots, \Sigma_q\}$ from different regimes
   - Implementation: Use general formulation with $y(w) = [w^\top\Sigma_1w, \ldots, w^\top\Sigma_q w]$

3. **Robust Optimization**
   - Current: Point estimates of $\mu$, $\Sigma$
   - Enhancement: Worst-case robust formulation with uncertainty sets
   - Benefit: More stable portfolios under estimation error

4. **Sharpe Ratio Maximization**
   - Current: Not implemented
   - Enhancement: Add MSRP optimization via SCQP
   - Use case: Strategy selection and performance evaluation

### Implementation Priorities

**High priority**:
- [ ] Implement basic SCQP framework (Algorithm 1)
- [ ] Add active-set strategy for fast QP solving (Algorithm 2)
- [ ] Integrate with existing `MeanVarianceOptimizer`

**Medium priority**:
- [ ] Add MSRP optimization for strategy ranking
- [ ] Implement worst-case robust optimizer
- [ ] Support multiple covariance estimates

**Low priority**:
- [ ] Kelly portfolio optimization
- [ ] Expected utility portfolios
- [ ] Multi-period extensions

### Code Integration Points

```python
# Proposed class hierarchy
class SCQPOptimizer:
    """General successive QP optimizer for MVP problems."""

    def __init__(self, objective_fn, constraints, qp_solver='quadprog'):
        self.objective_fn = objective_fn  # F(x, y)
        self.constraints = constraints    # g(w) <= 0
        self.qp_solver = qp_solver

    def optimize(self, mu, Sigma, w0=None):
        """Run SCQP algorithm."""
        # Outer loop: update lambda
        # Inner loop: update eta (if constraints present)
        # Solve QP surrogates with active-set strategy

    def _solve_qp_surrogate(self, lambda_k, eta_l, working_set=None):
        """Solve single QP with warm starting."""
        # Use Algorithm 2 active-set strategy

class MaxSharpeOptimizer(SCQPOptimizer):
    """Maximum Sharpe ratio portfolio."""
    def __init__(self, rf=0.0):
        objective = lambda x, y: -(x - rf) / np.sqrt(y)
        super().__init__(objective, constraints=[])

class RobustOptimizer(SCQPOptimizer):
    """Worst-case robust portfolio."""
    def __init__(self, alpha=1.0):
        objective = lambda x, y: -x + alpha * np.sqrt(y)
        super().__init__(objective, constraints=[])
```

### Testing Strategy

1. **Unit tests**: Verify convergence on small problems ($N = 10-20$)
2. **Benchmark tests**: Compare against existing optimizers
3. **Scalability tests**: Test on large portfolios ($N = 100-500$)
4. **Integration tests**: Use in backtest pipeline with real data

### Performance Targets

Based on paper results, expected performance for $N = 100$ assets:

- **Solve time**: < 0.1 seconds (vs. 0.5-1.0s for interior point)
- **Iterations**: < 20 outer iterations, < 3 inner iterations per QP
- **Accuracy**: Objective gap < $10^{-6}$
- **Sparsity**: ~10-20 active positions (working set size ~80-90)

---

## Key Takeaways

1. **Unified framework**: SCQP solves diverse MVP formulations via simple QP surrogates
2. **Provable convergence**: Theoretical guarantees under mild assumptions
3. **Computational efficiency**: Near-linear empirical complexity via sparsity exploitation
4. **Practical speedup**: 5-100× faster than general solvers for $N > 100$
5. **Easy implementation**: Only requires QP solver (e.g., quadprog, OSQP)
6. **Pareto tracking**: Solution sequence stays on Pareto frontier
7. **Warm starting**: Neighboring QPs solved in ~3 iterations
8. **Scalability**: Handles $N > 400$ efficiently

## References

See original paper for complete references. Key citations:

- [1] Markowitz (1952): Original portfolio selection theory
- [13] Dinkelbach (1967): Fractional programming algorithm
- [14] Shen & Yu (2018): Quadratic transform for FP
- [16] Sun et al. (2016): MM algorithms for signal processing
- [22] Scutari et al. (2016): Successive convex approximation
- [34] Bertsekas (1999): Nonlinear programming fundamentals
- [38] Boyd & Vandenberghe (2004): Convex optimization

---

**Document version**: 1.0
**Last updated**: 2025-11-11
**Extracted by**: Claude (ARBS project)
