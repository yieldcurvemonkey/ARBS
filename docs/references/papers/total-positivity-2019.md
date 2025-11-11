# ABOUTME: Mathematical reference for total positivity covariance estimation in portfolio selection
# ABOUTME: Extracted from Agrawal, Roy, Uhler (2019) - arXiv:1909.04222v2

# Covariance Matrix Estimation under Total Positivity for Portfolio Selection

## Paper Metadata

- **Title**: Covariance Matrix Estimation under Total Positivity for Portfolio Selection
- **Authors**: Raj Agrawal, Uma Roy, Caroline Uhler
- **Affiliations**: MIT (CSAIL, LIDS, IDSS)
- **arXiv ID**: arXiv:1909.04222v2 [stat.AP]
- **Date**: December 29, 2020
- **Venue**: Submitted to Elsevier

## Abstract

Selecting the optimal Markowitz portfolio depends on estimating the covariance matrix of the returns of N assets from T periods of historical data. Problematically, N is typically of the same order as T, which makes the sample covariance matrix estimator perform poorly, both empirically and theoretically. While various other general purpose covariance matrix estimators have been introduced in the financial economics and statistics literature for dealing with the high dimensionality of this problem, this paper proposes an estimator that exploits the fact that assets are typically positively dependent. This is achieved by imposing that the joint distribution of returns be multivariate totally positive of order 2 (MTP2). This constraint on the covariance matrix not only enforces positive dependence among the assets, but also regularizes the covariance matrix, leading to desirable statistical properties such as sparsity. Based on stock-market data spanning thirty years, the paper shows that estimating the covariance matrix under MTP2 outperforms previous state-of-the-art methods including shrinkage estimators and factor models.

## Total Positivity: Definition and Properties

### Definition 3.1: MTP2 (Multivariate Totally Positive of Order 2)

A distribution on $\mathcal{X} \subseteq \mathbb{R}^M$ is **multivariate totally positive of order 2** (MTP2) if its density function $p$ satisfies:

$$p(x)p(y) \leq p(x \wedge y)p(x \vee y) \quad \text{for all } x, y \in \mathcal{X}$$

where $\wedge, \vee$ denote the coordinate-wise minimum and maximum, respectively.

### Key Properties

1. **MTP2 is a strong form of positive dependence** that implies most other known forms including positive association
2. **Equivalent to log-supermodularity** when $p(x)$ is strictly positive
3. **Connection to economics**: Log-supermodularity has a long history in complementarity and comparative statics theory

### Characterization for Gaussian Distributions

For a multivariate Gaussian distribution with mean $\mu$ and positive definite covariance matrix $\Sigma$:

$$\text{Distribution is MTP}_2 \iff (\Sigma^{-1})_{ij} \leq 0 \text{ for all } i \neq j$$

A precision matrix $K := \Sigma^{-1}$ satisfying this condition is called a **symmetric M-matrix**, which implies:
- All correlations are non-negative
- All partial correlations are non-negative

### Practical Observation

Less than 0.001% of randomly sampled 5×5 correlation matrices satisfy the MTP2 constraint, yet empirical stock market data frequently exhibits this structure.

## Maximum Likelihood Estimation under MTP2

### Log-Likelihood Function

Given data $\mathcal{D} := \{r_t\}_{t=1}^T \stackrel{\text{i.i.d.}}{\sim} \mathcal{N}(0, K)$, the log-likelihood function is:

$$\mathcal{L}(K; \mathcal{D}) = \log \det K - \text{trace}(KS)$$

where $S \in \mathbb{R}^{N \times N}$ is the sample covariance matrix.

### MLE under MTP2 Constraint (Equation 5)

$$\hat{K} = \arg\max_{K \succeq 0} \log \det K - \text{trace}(KS) \quad \text{subject to} \quad K_{ij} \leq 0 \quad \forall i \neq j$$

### Remarkable Properties

1. **Existence**: The MLE exists with probability 1 when $T \geq 2$ for **any dimension** $N$ (even when $N \gg T$)
2. **Convexity**: The optimization problem is convex
3. **Sparsity**: The MTP2 covariance matrix estimator is usually sparse without requiring tuning parameters
4. **Efficient computation**: Coordinate-descent algorithms available
5. **Regularization**: The MTP2 constraint adds considerable regularization

### Comparison with Unconstrained MLE

Without MTP2 constraint:
- MLE is $S^{-1}$ when $N \leq T$
- MLE does not exist when $N \geq T$ (log-likelihood unbounded above)

With MTP2 constraint:
- MLE exists for any $N$ when $T \geq 2$
- Provides automatic regularization

## Extension to Heavy-Tailed Distributions

### Transelliptical Distributions

A random vector $X$ follows a **transelliptical distribution** if there exist monotonically increasing functions $f_i, i = 1, \ldots, M$, such that $(f_1(X_1), \cdots, f_M(X_M))$ follows an elliptical distribution with density:

$$g((x - \mu)^T \Sigma_f^{-1} (x - \mu))$$

### Theorem 3.3: Necessary Condition for Transelliptical MTP2

If $(X_1, \cdots, X_M)$ is MTP2 and transelliptical, then $\Sigma_f^{-1}$ is an M-matrix.

**Important**: For transelliptical distributions (unlike Gaussian), M-matrix condition is necessary but **not sufficient** for MTP2.

### Kendall's Tau Extension

For heavy-tailed returns data, replace sample covariance matrix $S$ with **Kendall's tau correlation matrix** $S_\tau$:

$$(S_\tau)_{ij} := \sin\left(\frac{\pi}{2}\hat{\tau}_{ij}\right)$$

where:

$$\hat{\tau}_{ij} := \frac{1}{\binom{T}{2}} \sum_{1 \leq t \leq t' \leq T} \text{sign}(X_{it} - X_{it'}) \text{sign}(X_{jt} - X_{jt'})$$

Then solve the same MLE problem with $S_\tau$ instead of $S$.

## Portfolio Selection Applications

### Global Minimum Variance Portfolio (Equation 2)

$$\min_{w \in \mathbb{R}^N} w^T \Sigma_t^* w \quad \text{subject to} \quad \sum_{i=1}^N w_i = 1$$

Analytical solution with estimated covariance $\hat{\Sigma}_t$:

$$\hat{w} := \frac{\hat{\Sigma}_t^{-1} \mathbf{1}}{\mathbf{1}^T \hat{\Sigma}_t^{-1} \mathbf{1}}$$

### Full Markowitz Portfolio (Equation 1)

$$\min_{w \in \mathbb{R}^N} w^T \Sigma_t^* w \quad \text{subject to} \quad w^T \mu_t^* = R \quad \text{and} \quad \sum_{i=1}^N w_i = 1$$

where:
- $\mu_t^*$ = true expected returns
- $\Sigma_t^*$ = true covariance matrix
- $R$ = desired expected return level

### Performance Metrics

1. **Out-of-sample standard deviation**: $\sigma_{\text{OOS}} = \sqrt{\frac{1}{H}\sum_{h=1}^H (r_h^M)^2} \times \sqrt{12}$ (annualized)
2. **Sharpe ratio**: $\text{SR} = \frac{\text{E}[r - r_f]}{\text{Std}[r - r_f]}$ where $r_f$ is risk-free rate
3. **Information ratio**: $\text{IR} = \frac{\text{E}[r]}{\text{Std}[r]}$

## Connection to Latent Tree Models and Factor Models

### Theorem 3.2: MTP2 for Latent Trees

Let $X \in \mathbb{R}^M$ follow a multivariate Gaussian distribution that factorizes according to a tree. If $\text{Cov}(X) \geq 0$, then $X$ is MTP2 and any marginal of $X$ is MTP2.

### Capital Asset Pricing Model (CAPM)

The CAPM is a single-factor model where return of stock $i$ is:

$$r_i = r_f + \beta_i(r_m - r_f) + u_i$$

where:
- $r_f$ = risk-free rate
- $r_m$ = market return
- $\beta_i \in \mathbb{R}$ = market beta
- $u_i$ = uncorrelated idiosyncratic error

When all $\beta_i$ are positive (typical in practice), CAPM implies MTP2.

### Motivation

- Over 97% of entries in sample covariance matrix of 1000 assets (daily returns 1980-2015) are positive
- MTP2 provides structure-free approach that:
  - Is more flexible than latent tree models
  - Avoids NP-hard structure learning
  - Computationally efficient (convex optimization)

## Empirical Results Summary

### Dataset
- **Source**: Center for Research in Security Prices (CRSP) daily stock returns
- **Period**: 1975-2015 (30 years)
- **Exchanges**: NYSE, AMEX, NASDAQ
- **Portfolio sizes**: $N \in \{100, 200, 500\}$
- **Sample sizes**: Varied $T$ such that $N/T \in \{1/2, 1, 2, 4\}$ plus $T = 1260$ (5 years)
- **Out-of-sample period**: 360 months (01/08/1986 to 12/02/2015)

### Methods Compared

1. **1/N**: Equally weighted portfolio (baseline)
2. **LS**: Linear shrinkage
3. **NLS**: Non-linear shrinkage
4. **AFM-LS**: Approximate factor model with 5 Fama-French factors + linear shrinkage
5. **AFM-NLS**: Approximate factor model + non-linear shrinkage
6. **POET (k=3,5)**: Principal Orthogonal complEmenT with 3 or 5 components
7. **GLASSO**: Graphical lasso
8. **CLIME**: Constrained L1-minimization for Inverse Matrix Estimation
9. **CLIME-KT**: CLIME with Kendall's tau
10. **MTP2**: Proposed method
11. **MTP2-KT**: Proposed method with Kendall's tau

### Key Findings

#### Global Minimum Variance Portfolio (Table 1)

**Best performers** (lowest out-of-sample standard deviation):
- MTP2 consistently competitive across all settings
- Non-linear shrinkage (NLS) performs well
- POET (k=3) performs well

**Example results** for $N=100$, $T=1260$:
- MTP2: 12.087% (tied best)
- MTP2-KT: 12.087% (tied best)
- NLS: 12.122%
- 1/N baseline: 18.724%

#### Full Markowitz Portfolio with Momentum Signal (Table 2)

**Best performers** (highest Sharpe ratio):
- **MTP2 dominates**: Best or near-best for almost all $(N, T)$ combinations
- MTP2-KT provides further improvement for $N \in \{100, 200\}$

**Example results** for $N=500$, $T=250$:
- MTP2-KT: 0.779 (best)
- MTP2: 0.755
- POET (k=5): 0.664
- 1/N baseline: 0.599

### Statistical Significance

The ordering between estimators remains relatively consistent when:
- Varying out-of-sample period length (60 to 360 months)
- Using 5-year moving average vs. cumulative average
- This indicates robustness of results

## Advantages of MTP2 Estimator

### Theoretical Advantages

1. **Regularization without tuning**: MTP2 constraint provides automatic regularization
2. **Existence guarantee**: MLE exists for any $N$ when $T \geq 2$
3. **Positive definiteness**: Guaranteed by construction
4. **Sparsity**: Automatic sparsity without L1 penalties
5. **Convex optimization**: Efficient coordinate-descent algorithms
6. **Structure exploitation**: Leverages positive dependence common in financial data

### Practical Advantages

1. **Superior out-of-sample performance**: Outperforms state-of-the-art methods
2. **Robust across dimensions**: Works well for various $(N, T)$ ratios
3. **Heavy-tail robustness**: Kendall's tau extension handles non-Gaussian returns
4. **No hyperparameter tuning**: Unlike graphical lasso, CLIME (except when relaxing constraint)
5. **Interpretability**: M-matrix structure implies positive partial correlations

### Comparison with Other Methods

| Method | Tuning Parameter | Handles $N > T$ | Guaranteed PD | Structure Assumed |
|--------|-----------------|----------------|---------------|-------------------|
| Sample Cov | None | No | No ($N > T$) | None |
| Linear Shrinkage | Yes | No | Yes | Well-conditioned |
| Factor Models | K factors | Yes | Yes | Low-rank + structure |
| POET | K, threshold | Yes | Not always | Sparse + low-rank |
| Graphical Lasso | λ (L1 penalty) | Yes | Yes | Sparse precision |
| CLIME | λ | Yes ($T \geq N$) | Not guaranteed | Sparse precision |
| **MTP2** | **None** | **Yes** | **Yes** | **Positive dependence** |

## ARBS Relevance: Potential Future Risk Model

### Current ARBS Risk Models

The ARBS system currently implements:
1. **SampleCovariance**: Basic sample covariance matrix
2. **LedoitWolfShrinkage**: Linear shrinkage toward identity matrix
3. **IdentityCovariance**: Diagonal identity matrix
4. **ConstantCorrelationCovariance**: Constant off-diagonal correlation

### Potential MTP2CovarianceEstimator

A future `MTP2CovarianceEstimator` class could be added to ARBS as:

```python
class MTP2CovarianceEstimator(CovarianceEstimator):
    """
    Maximum likelihood covariance estimator under MTP2 constraint.

    Solves: max log det K - trace(KS) subject to K_ij <= 0 for i != j

    Properties:
    - Enforces positive dependence (all correlations, partial correlations >= 0)
    - Exists for any N when T >= 2
    - Automatic regularization and sparsity
    - No hyperparameters to tune
    - Convex optimization problem
    """
```

### Implementation Considerations

1. **Algorithm**: Coordinate-descent (Slawski & Hein 2014)
2. **Extension**: Kendall's tau for heavy-tailed returns
3. **Validation**: Test on futures/swaps returns data
4. **Integration**: Fits naturally into ARBS pluggable risk model system

### When to Use MTP2 in ARBS

**Good fit when**:
- Assets are positively dependent (typical for financial instruments)
- High-dimensional setting ($N$ close to or exceeds $T$)
- Want automatic regularization without tuning
- Need guaranteed positive definiteness
- Sample covariance matrix performs poorly

**May not fit when**:
- Assets have negative correlations (short positions, hedge portfolios)
- Need to model complex conditional independence structure
- Factor structure is known and strong

### Future Enhancements

1. **Dynamic MTP2**: Time-varying covariance under MTP2 constraint
2. **Relaxed MTP2**: Lagrange multiplier to penalize (not enforce) constraint
3. **Sensitivity analysis**: Test robustness to MTP2 assumption
4. **Sector structure**: Combine with latent tree/factor models
5. **Transaction costs**: Integration with DV01 constraints and impact costs

## Computational Details

### Optimization Problem Structure

The MTP2 MLE is a convex optimization problem:

$$\begin{align}
\max_{K} \quad & \log \det K - \text{trace}(KS) \\
\text{subject to} \quad & K \succeq 0 \\
& K_{ij} \leq 0 \quad \forall i \neq j
\end{align}$$

### Solution Algorithm

**Coordinate-descent method** (Lauritzen et al. 2019a, Slawski & Hein 2014):
1. Initialize $K^{(0)}$
2. For each iteration:
   - Update each row (or column) of $K$ while fixing others
   - Enforce M-matrix constraint
   - Check convergence
3. Return $\hat{K}$, then $\hat{\Sigma} = \hat{K}^{-1}$

### Computational Complexity

- Comparable to graphical lasso
- Efficient for moderate dimensions ($N \sim 100-500$)
- Scales better than full matrix inversion for large sparse problems

## Key Mathematical Results

### Existence Theorem (Lauritzen et al. 2019a)

The MTP2 MLE in Eq. (5) exists with probability 1 when $T \geq 2$ for any dimension $N$.

**Implication**: Unlike sample covariance (needs $T > N$), MTP2 estimator well-defined even in extreme high-dimensional settings.

### Sparsity Property (Lauritzen et al. 2019a, Corollary 2.9)

The MTP2 covariance matrix estimator is usually sparse, reducing intrinsic dimensionality from $O(N^2)$ to fewer effective parameters.

### Connection to Graphical Models

A sparse precision matrix $K$ corresponds to a sparse undirected graphical model where:
- Zero entries $K_{ij} = 0$ indicate conditional independence
- MTP2 constraint: non-zero off-diagonal entries must be non-positive

## Future Research Directions

From the paper's conclusion:

1. **Theoretical analysis**: Properties of MTP2-KT estimator for heavy-tailed distributions
2. **Dynamic extension**: Time-varying MTP2 covariance matrices
3. **Spectrum analysis**: Study eigenvalue distribution of M-matrices in high dimensions
4. **Combination with shrinkage**: Potential further performance gains
5. **Sensitivity analysis**: Relaxed MTP2 with Lagrange multiplier for assumption testing

## References

Key citations from the paper:

- **Fortuin et al. (1971)**: Original MTP2 definition
- **Karlin & Rinott (1980a,b, 1983)**: M-matrix characterization
- **Bølviken (1982)**: Symmetric M-matrices
- **Lauritzen et al. (2019a,b)**: MTP2 in graphical models, MLE existence
- **Slawski & Hein (2014)**: Coordinate-descent algorithm
- **Ledoit & Wolf (2004, 2012)**: Shrinkage estimators
- **Fan et al. (2013)**: POET estimator
- **Liu et al. (2012)**: CLIME and Kendall's tau
- **Barber & Kolar (2018)**: Transelliptical distributions

## Implementation Notes

### Available Code

- GitHub: https://github.com/uhlerlab/MTP2-finance
- Matlab implementation by Slawski & Hein (2014)
- All empirical evaluation code and data available

### Dependencies for ARBS Integration

Would require:
- Convex optimization library (e.g., CVXPY)
- Or custom coordinate-descent implementation
- Kendall's tau computation (scipy.stats.kendalltau)

### Testing Requirements

Before adding to ARBS:
1. Verify performance on futures/swaps data
2. Compare with existing LedoitWolfShrinkage
3. Test computational efficiency for ARBS scales
4. Validate positive dependence assumption for futures markets
5. TDD: Write tests first, then implement

---

**Status**: Potential future enhancement for ARBS risk model system. Not required for current MVP, but strong empirical evidence suggests value for portfolio optimization in high-dimensional settings with positive asset dependence.
