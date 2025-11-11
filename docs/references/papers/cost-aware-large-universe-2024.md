# Cost-Aware Portfolios in a Large Universe of Assets

## Paper Metadata

- **Title**: Cost-aware Portfolios in a Large Universe of Assets
- **Authors**: Qingliang Fan¹, Marcelo C. Medeiros², Hanming Yang³, Songshan Yang³
  - ¹The Chinese University of Hong Kong
  - ²The University of Illinois at Urbana Champaign
  - ³Renmin University of China
- **arXiv ID**: arXiv:2412.11575v2 [stat.ME]
- **Publication Date**: 20 Aug 2025
- **Keywords**: High-dimensional Portfolio Optimization, Mean-variance Model, Optimal Rebalancing, Transaction Costs

## Abstract

This paper proposes a finite-horizon (multi-period) mean-variance portfolio estimator, in which rebalancing decisions are based on current information about asset returns and transaction costs. The novelty of this study stems from integrating transaction costs into the decision process within a high-dimensional portfolio setting, where the number of assets exceeds the sample size. We define the optimal cost-aware portfolio and propose novel models for its construction and rebalancing. Our approach incorporates a nonconvex penalty and explicitly accounts for both proportional and quadratic transaction costs. We establish that the estimators derived from the proposed construction and rebalancing models, as well as the corresponding in-sample and out-of-sample Sharpe ratio estimators, consistently converge to those of the optimal cost-aware portfolio. Monte Carlo simulations and empirical studies using S&P 500 and Russell 2000 stocks show the satisfactory performance of the proposed portfolio and highlight the importance of incorporating transaction costs during rebalancing.

## Key Formulas

### 1. Classical Mean-Variance Framework

**Markowitz (1952) Single-Period Problem:**

$$w^* = \arg\min_w w^\top\Sigma w - \gamma w^\top \mu$$

subject to $\sum_{i=1}^p w_i = 1$

where:
- $w$ is the weight vector of assets
- $\gamma$ is the inverse of risk aversion parameter
- $\mu = (\mu_1, \ldots, \mu_p)^\top$ is the mean vector of excess returns
- $\Sigma$ is the covariance matrix of excess returns

**Solution:** $w^* = c_1\Sigma^{-1}\mu - c_2\Sigma^{-1}1$, where $c_1$ and $c_2$ depend only on $\Sigma$ and $\mu$.

### 2. Transaction Cost Models

**Quadratic Transaction Costs:**

$$C_1(w) = (\beta \odot w)^\top w$$

where:
- $\beta = (\beta_1, \ldots, \beta_p)^\top$, $\beta_j > 0$ is the cost parameter
- Unit transaction cost of asset $j$ is a linear function of trading size with slope $\beta_j$
- $\odot$ denotes element-wise multiplication

**For rebalancing stage ($t \geq 2$):**

$$C_t(w) = [\beta \odot (w_t - w_{t-1}^+)]^\top(w_t - w_{t-1}^+)$$

where $\delta_t := w_t - w_{t-1}^+$ is the weight difference vector.

**Proportional Transaction Costs:**

$$C_1(w) = \|\alpha \odot w\|_1$$

where $\alpha = (\alpha_1, \ldots, \alpha_p)^\top$, $\alpha_j > 0$ is the cost parameter.

**For rebalancing stage ($t \geq 2$):**

$$C_t(w) = \|\alpha \odot (w_t - w_{t-1}^+)\|_1$$

**Pre-rebalancing weight:** $w_{t-1}^+ = (f_n \circ f_{n-1} \circ \cdots \circ f_1)(w_{t-1})$, where

$$f_i(w) := \frac{w \odot (1 + R_{(t-2)n+i})}{1 + w^\top R_{(t-2)n+i}}$$

### 3. Optimal Cost-Aware Portfolio

**First Portfolio Construction Stage ($t=1$):**

$$w_1^* := \arg\min_{w\in\mathbb{R}^p} w^\top\Sigma_1 w - \gamma w^\top \mu_1 + C_1(w)$$

subject to $w^\top 1 = 1$, $\|w\|_0 \leq s_0$

**Explicit Solution (Quadratic Costs):**

$$w_{A_1}^* = \frac{1}{2}\tilde{\Sigma}_{A_1,A_1}^{-1}\left(\gamma\mu_{A_1} + \frac{2 - \gamma 1^\top \tilde{\Sigma}_{A_1,A_1}^{-1}\mu_{A_1}}{1^\top \tilde{\Sigma}_{A_1,A_1}^{-1}1}1\right)$$

where $\tilde{\Sigma}_1 = \Sigma_1 + B$ with $B = \text{diag}(\beta_1, \ldots, \beta_p)$, and $w_{A_1^c}^* = 0$.

**Explicit Solution (Proportional Costs):**

$$w_{A_1}^* = \frac{1}{2}\Sigma_{A_1,A_1}^{-1}\left(\gamma\mu_{A_1} - \alpha \odot g_{A_1} + \frac{2 - \gamma 1^\top \Sigma_{A_1,A_1}^{-1}\mu_{A_1} + 1^\top \Sigma_{A_1,A_1}^{-1}(\alpha \odot g_{A_1})}{1^\top \Sigma_{A_1,A_1}^{-1}1}1\right)$$

where $g := \partial\|w_1\|_1/\partial w_1$ is the vector of sub-derivatives.

**Reallocation Stage ($t \geq 2$):**

$$\delta_t^* := \arg\min_{\delta\in\mathbb{R}^p} \delta^\top\Sigma_t\delta + 2w_{t-1}^{+\top}\Sigma_t\delta_t - \gamma\delta^\top\mu_t + C_t(\delta)$$

subject to $\delta^\top 1 = 0$, $\|\delta\|_0 \leq s_0$

**Explicit Solution (Quadratic Costs):**

$$\delta_{A_t}^* = \frac{1}{2}\tilde{\Sigma}_{A_t,A_t}^{-1}\left(\gamma\mu_{A_t} - 2(\Sigma_t w_{t-1}^+)_{A_t} + \frac{2 - \gamma 1^\top \tilde{\Sigma}_{A_t,A_t}^{-1}\mu_{A_t}}{1^\top \tilde{\Sigma}_{A_t,A_t}^{-1}1}1\right)$$

### 4. Cost-Aware Portfolio Estimator with SCAD Penalty (CAPE-S)

**First Portfolio Construction:**

$$\hat{w}_1 := \arg\min_{w_1\in\mathbb{R}^p} w_1^\top \hat{\Sigma}_1 w_1 - \gamma w_1^\top \hat{\mu}_1 + C_1(w_1) + P_\lambda(w_1)$$

subject to $w_1^\top 1 = 1$

where $P_\lambda(w_1) = \sum_{j=1}^p P_\lambda(w_{t,j})$ is SCAD penalty.

**SCAD Penalty Derivative:**

$$P_\lambda'(|\tau|) = \lambda\left\{I(|\tau| \leq \lambda) + \frac{(a\lambda - |\tau|)_+}{(a-1)\lambda}I(|\tau| > \lambda)\right\}$$

for some $a > 2$, and $P_\lambda'(0+) = \lambda$.

**Reallocation Stage:**

$$\hat{\delta}_t := \arg\min_{\delta_t\in\mathbb{R}^p} \delta_t^\top \hat{\Sigma}_t\delta_t + 2w_{t-1}^{+\top}\hat{\Sigma}_t\delta_t - \gamma\delta^\top\hat{\mu}_t + C_t(\delta_t) + P_\lambda(\delta_t)$$

subject to $\delta_t^\top 1 = 0$

### 5. Local Linear Approximation (LLA) Algorithm

**Initialization:** $\hat{w}_1^{(0)} = \hat{w}_1^{\text{initial}}$ (typically CAPE-L/Lasso solution)

**Adaptive weights:**

$$\hat{\theta}^{(0)} = \left(P_\lambda'(|\hat{w}_{1,1}^{(0)}|), \ldots, P_\lambda'(|\hat{w}_{1,p}^{(0)}|)\right)^\top$$

**Iteration step:**

$$\hat{w}_1^{(l)} = \min_{w\in\mathbb{R}^p, w^\top 1=1} \mathcal{L}_{n,1}(w) + \sum_j \hat{\theta}_j^{(l-1)} \cdot |w_j|$$

where $\mathcal{L}_{n,1}(w) = w^\top\hat{\Sigma}_1 w - \gamma w^\top\hat{\mu}_1 + C_1(w)$.

**Result:** Converges to oracle estimator in 2 iterations under mild conditions.

## Covariance Estimation for Large Dimensions

### Linear Shrinkage Estimator (LSE)

Based on Ledoit and Wolf (2004), provides well-conditioned estimates when $p$ comparable to or exceeds $n$.

**Properties:**
- Satisfies Assumption (A2): $\Pr(\|\hat{\Sigma}_t - \Sigma_t\|_{\max} \leq M_2\sqrt{\log p/n}) \geq 1 - O(p^{-c_2})$
- Satisfies RSC condition (A3): $\forall \Delta \in \mathbb{R}^p$, $\Delta^\top\hat{\Sigma}_t\Delta \geq v\|\Delta\|_2^2 - \tau\sqrt{\log p/n}\|\Delta\|_1$

### Nonlinear Shrinkage Estimator (NLSE)

Based on Ledoit and Wolf (2020):
- Analytical nonlinear shrinkage of eigenvalues
- Satisfies RSC condition (A3)
- May not satisfy (A2) but performs well empirically

### Sample Covariance Matrix

Under sub-Gaussian assumptions, satisfies both (A2) and (A3) when $\log p < n$.

## Theoretical Results

### Convergence Rates

**Theorem 1 (Quadratic Costs, Construction Stage):**

Under Assumptions (A1)-(A3) and $\|\beta\|_\infty \ll 1/C_1$:

$$\|\hat{w}_1^{\text{LLA},\beta} - w_1^*\|_\infty = O\left(\sqrt{\frac{\log k}{n}}\right)$$

with probability at least $1 - c_1k^{-c_2}$ for all $k \in [s_1, p]$.

**Theorem 2 (Quadratic Costs, Rebalancing Stage):**

If $\|w_{t-1}^+\|_1 < C_0$ or $\|w_{t-1,Q}^+\|_1 \leq C_0$ with $w_{t-1,Q^c}^+ = 0$:

$$\|\hat{\delta}_t^{\text{LLA},\beta} - \delta_t^*\|_\infty = O\left(\sqrt{\frac{\log k}{n}}\right)$$

**Theorem 3 (Proportional Costs, Construction Stage):**

Under $\|\alpha\|_\infty \leq C\sqrt{\log p/n}$:

$$\|\hat{w}_1^{\text{LLA},\alpha} - w_1^*\|_\infty = O\left(\sqrt{\frac{\log k}{n}}\right)$$

**Corollary 1 (Sharpe Ratio Consistency):**

If $s_1\sqrt{\log s_1/n} = o(1)$:
- In-sample Sharpe ratio: $\left|\frac{(\hat{w}_1^{\text{LLA}})^\top\hat{\mu}_1}{\sqrt{(\hat{w}_1^{\text{LLA}})^\top\hat{\Sigma}_1\hat{w}_1}} - \frac{(w_1^*)^\top\mu_1}{\sqrt{(w_1^*)^\top\Sigma_1 w_1}}\right| = o_p(1)$
- Out-of-sample Sharpe ratio: Similar result for period 2

### Assumptions

**(A1) Support Set Conditions:**

$$\|\Sigma_{A_t,A_t}^{-1}r\|_\infty < C_1, \quad \forall r \in \{-1,0,1\}^{s_t}$$
$$|||\Sigma_{A_t^c,A_t}|||_\infty < C_2$$
$$0 < \lambda_{\min}(\Sigma_{A_t,A_t}) \leq \lambda_{\max}(\Sigma_{A_t,A_t}) < \infty$$

**(A2) Estimation Error Bounds:**

$$\Pr(\|\hat{\mu}_t - \mu_t\|_\infty \leq M_1\sqrt{\log p/n}) \geq 1 - O(p^{-c_1})$$
$$\Pr(\|\hat{\Sigma}_t - \Sigma_t\|_{\max} \leq M_2\sqrt{\log p/n}) \geq 1 - O(p^{-c_2})$$

**(A3) Restricted Strong Convexity (RSC):**

$$\forall \Delta \in \mathbb{R}^p, \quad \Delta^\top\hat{\Sigma}_t\Delta \geq v\|\Delta\|_2^2 - \tau\sqrt{\frac{\log p}{n}}\|\Delta\|_1$$

where $v > 0$, $\tau \geq 0$, and $t = 1,2,\ldots,m$.

## Empirical Results

### Data
- **S&P 500**: 457 stocks, 2017-2020
- **Russell 2000**: 935 stocks, 2017-2020
- **Rebalancing frequency**: Annual (251 trading days)
- **Transaction costs**: Asset-specific based on bid-ask spreads (Hasbrouck 2009)

### Performance Metrics

**S&P 500 (Quadratic Costs):**
- Overall Sharpe Ratio: **0.915** (best among all methods)
- Average turnover: ~4-7% (vs. 18% for MV)
- Average transaction cost: 0.5-2.3% (vs. 2.5-13.8% for MV)

**Russell 2000 (Quadratic Costs):**
- Overall Sharpe Ratio: **1.170** (best among all methods)
- Stage S2 Sharpe: **2.745** (highest single-period performance)
- Consistently lowest turnover (~1.3-1.6%) among active strategies

### Key Findings

1. **Cost Efficiency**: CAPE-S achieves 70-85% reduction in transaction costs vs. standard MV
2. **Stability**: Low turnover indicates stable allocations (3-7% vs. 15-35% for benchmarks)
3. **Risk-Adjusted Performance**: Highest Sharpe ratios across both universes and cost structures
4. **Robustness**: Performs well in both large-cap (S&P 500) and small-cap (Russell 2000) universes
5. **Crisis Performance**: Strong relative performance during 2018 correction and 2020 COVID crash

## ARBS Relevance

### Application to Futures/Swaps

1. **High-Dimensional Setting**: Framework explicitly designed for $p > n$ scenarios
   - Futures markets: 50-100+ contracts across asset classes
   - Swaps: 20-50+ tenors per curve × multiple curves

2. **Transaction Cost Modeling**:
   - **Proportional costs**: Bid-offer spreads in liquid markets
   - **Quadratic costs**: Market impact for larger positions
   - Asset-specific cost parameters: $\beta_j$ or $\alpha_j$ per instrument

3. **Multi-Period Rebalancing**:
   - Natural fit for systematic futures/swaps strategies
   - Accounts for current positions in rebalancing decisions
   - Weight drift from mark-to-market captured via $w_{t-1}^+$

4. **Covariance Estimation**:
   - Ledoit-Wolf shrinkage handles correlation structure well
   - Critical for fixed income where curves are highly correlated
   - RSC condition ensures numerical stability

5. **Implementation Considerations**:
   - SCAD penalty promotes sparsity (concentrated positions)
   - LLA algorithm computationally efficient (2 iterations)
   - Explicit solutions available for oracle problems

### Practical Adaptations for ARBS

**Transaction Cost Calibration:**
- Futures: Use bid-offer spreads from exchange data
- Swaps: Combine dealer quotes with market depth estimates
- Quadratic parameter: $\beta_j = 2\alpha_j^2$ (suggested scaling)

**Covariance Models:**
- Consider factor structures (level, slope, curvature)
- Apply shrinkage to factor covariance matrix
- Ledoit-Wolf 2020 nonlinear shrinkage recommended

**Rebalancing Frequency:**
- Higher for liquid futures (daily/weekly feasible)
- Lower for OTC swaps (monthly/quarterly typical)
- Cost-benefit tradeoff guided by $C_t(\delta)$ term

**Position Constraints:**
- Add DV01 constraints: $\sum_j \text{DV01}_j w_j \leq L$
- Leverage constraints: $\sum_j |w_j| \leq K$
- Long-only if required: $w_j \geq 0$ (though not natural for rates)

## References

- Markowitz, H. (1952). Portfolio selection. *The Journal of Finance*, 7(1), 77-91.
- Ledoit, O. and Wolf, M. (2004). A well-conditioned estimator for large-dimensional covariance matrices. *Journal of Multivariate Analysis*, 88(2), 365-411.
- Ledoit, O. and Wolf, M. (2020). Analytical nonlinear shrinkage of large-dimensional covariance matrices. *The Annals of Statistics*, 48(5), 3043-3065.
- Fan, J. and Li, R. (2001). Variable selection via nonconcave penalized likelihood and its oracle properties. *JASA*, 96(456), 1348-1360.
- Zou, H. and Li, R. (2008). One-step sparse estimates in nonconcave penalized likelihood models. *The Annals of Statistics*, 36(4), 1509-1533.
- Hautsch, N. and Voigt, S. (2019). Large-scale portfolio allocation under transaction costs and model uncertainty. *Journal of Econometrics*, 212(1), 221-240.
- Hasbrouck, J. (2009). Trading costs and returns for US equities: Estimating effective costs from daily data. *The Journal of Finance*, 64(3), 1445-1477.

## Implementation Notes

### Algorithm Complexity
- LLA iteration: $O(p^2)$ per iteration (dominated by quadratic program)
- Total iterations: 2 (convergence guarantee)
- Overall: $O(p^2)$ for sparse portfolios

### Numerical Stability
- Use Cholesky decomposition for $\hat{\Sigma}_t$
- Check condition number before inversion
- Apply shrinkage if $\lambda_{\min}(\hat{\Sigma}_t)$ too small

### Hyperparameter Selection
- $\lambda$ (SCAD): Choose to maximize in-sample Sharpe ratio
- $a$ (SCAD): Set to 3.7 (standard)
- $\gamma$ (risk aversion): Set to 1/3 (moderate risk tolerance)
- Transaction costs: Calibrate from market data

### Extensions
- **Cardinality constraints**: L0 penalty approximation
- **DV01 limits**: Linear constraint on $\sum_j \text{DV01}_j w_j$
- **Sector constraints**: Group-wise constraints on weights
- **Time-varying costs**: Update $\alpha_t$, $\beta_t$ dynamically
