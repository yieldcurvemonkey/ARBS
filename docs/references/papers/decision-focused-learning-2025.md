# Decision-Focused Learning for Covariance Estimation

**Paper**: Estimating Covariance for Global Minimum Variance Portfolio: A Decision-Focused Learning Approach
**Authors**: Kim, Tae, Lee (2025)
**Source**: `/home/user/ARBS/docs/papers/advanced/decision-focused-learning-2025.pdf`
**Relevance**: Objective-aligned risk estimation, covariance estimation for portfolio optimization

---

## Core Insight

**Key Finding**: Covariance matrices optimized for prediction accuracy (MSE) do not produce optimal portfolio decisions. Instead, covariance estimation should be directly optimized for the downstream decision objective.

### The Problem with Traditional Approaches

1. **Standard Estimators** (sample covariance, Ledoit-Wolf shrinkage, etc.) minimize Frobenius norm or MSE
2. **This creates a mismatch**: Good covariance prediction ≠ Good portfolio decisions
3. **Empirical Result**: MSE-trained models produce nearly equal-weighted portfolios (fail to capture decision-relevant structure)

---

## Decision-Focused Learning (DFL) Framework

### Methodology

Instead of the traditional "predict-then-optimize" approach:
```
Traditional: Minimize MSE(Σ̂, Σtrue) → Use Σ̂ for optimization
DFL: Minimize Regret(w*(Σ̂), w*(Σtrue)) directly
```

### Regret Loss Formulation

For Global Minimum Variance Portfolio (GMVP):

```
L(θ) = w*(Σ̂)ᵀ Σtrue w*(Σ̂) - w*(Σtrue)ᵀ Σtrue w*(Σtrue)

where w*(Σ) = Σ⁻¹1 / (1ᵀΣ⁻¹1)  [GMVP closed-form solution]
```

**Key Property**: This loss directly measures decision quality (realized portfolio variance) rather than parameter accuracy.

### Gradient Computation

End-to-end backpropagation through optimization layer:

```
dL/dθ = (dL/dw*) · (∂w*/∂Σ̂) · (∂Σ̂/∂θ)
```

Where:
- `dL/dw = 2 Σtrue w*(Σ̂)` [gradient w.r.t. portfolio weights]
- `∂w*/∂Σ̂` uses analytical derivatives of GMVP solution
- `∂Σ̂/∂θ` via automatic differentiation of neural network

---

## Theoretical Properties

### Σ-Invariant Structure (Proposition 1-3)

**Finding**: DFL gradients have principal components in low-dimensional subspaces:
- Direction 1: `w ⊗ (Σ⁻¹w)` - captures risk-adjusted portfolio structure
- Direction 2: `w ⊗ w` - emphasizes large absolute weights

**Interpretation**:
- DFL learns to focus on covariance features that directly impact portfolio weights
- Not all covariance elements are equally important for the decision
- Gradient structure reveals which correlations matter for risk minimization

---

## Empirical Results

### Performance Comparison

**Annualized Volatility** (49 Industry Portfolio, δin = 21 days):

| Method | δout=5 | δout=21 | δout=63 | δout=126 | δout=252 |
|--------|--------|---------|---------|----------|----------|
| Equal Weight | 14.89% | 15.50% | 15.97% | 16.11% | 17.72% |
| Historical | 12.49% | 13.82% | 14.71% | 14.66% | 14.16% |
| Ledoit-Wolf (Diag) | 12.21% | 13.34% | 14.07% | 14.16% | 14.01% |
| Ledoit-Wolf (CC) | 12.89% | 14.31% | 14.37% | 14.95% | 13.96% |
| OAS | 12.06% | 13.17% | 13.83% | 13.95% | 13.99% |
| **PFL (MSE)** | 14.87% | 15.49% | 15.95% | 16.07% | 17.73% |
| **DFL (Ours)** | **11.54%** | **12.19%** | **12.90%** | **12.87%** | **13.19%** |

**Key Observation**: PFL performs identically to equal-weight portfolio (fails completely), while DFL achieves lowest volatility across all horizons.

### Why PFL Fails

**Root Cause**: MSE training leads to:
1. Focus on large diagonal errors (variances)
2. Underfitting of off-diagonal terms (correlations)
3. Nearly uniform correlation estimates
4. Result: Approximately equal-weighted portfolio

**Evidence**: Figure 4 shows PFL portfolio weights nearly identical to 1/N allocation across all assets.

---

## Key Insights for ARBS

### 1. Objective-Aligned Risk Estimation

**Principle**: Risk models should be optimized for the specific portfolio objective, not general prediction accuracy.

**ARBS Application**:
- Don't use off-the-shelf covariance estimators
- Train risk models end-to-end with strategy objective
- For carry strategies: optimize covariance for carry-weighted portfolios
- For momentum: optimize for momentum-weighted allocations

### 2. What DFL Learns

**Empirical Findings**:

a) **Asset Selection Criteria**:
   - DFL systematically selects low-volatility assets for long positions
   - Table 3: 100% precision in top-3 asset selection by volatility (Dow 30)
   - Creates stable, consistent allocations over time

b) **Precision Matrix Structure**:
   - DFL produces block-structured precision matrices
   - Clear separation between high-weight and low-weight assets
   - Traditional estimators show no such structure

c) **Covariance Attribution**:
   - DFL focuses on minimizing variance/covariance for heavily-weighted assets
   - Exhibits balancing effect across long/short positions
   - Weaker control of short-position risk (area for improvement)

### 3. Practical Implementation

**Architecture**:
```
Returns[t-δin:t] → DLinear → L (lower triangular) → Σ̂ = LLᵀ
                                    ↓
                              GMVP Layer: w* = Σ̂⁻¹1 / (1ᵀΣ̂⁻¹1)
                                    ↓
                           Regret Loss: w*ᵀΣtrue w* - w*optᵀΣtrue w*opt
```

**Key Design Choices**:
- Predict lower-triangular matrix L, reconstruct Σ̂ = LLᵀ (ensures PSD)
- Truncated spectral reconstruction: retain eigenvalues λi ≥ ε·λmax
- Use analytical GMVP solution (not iterative optimization)
- Train with Adam optimizer, early stopping on validation regret

### 4. Comparison to Standard Approaches

| Approach | Objective | Result |
|----------|-----------|--------|
| Sample Covariance | Minimize sampling error | Noisy, unstable |
| Ledoit-Wolf | Minimize Frobenius norm | General-purpose, not decision-optimal |
| PFL (MSE) | Minimize MSE(Σ̂, Σtrue) | **Fails**: produces equal-weight portfolios |
| **DFL (Regret)** | Minimize portfolio variance | **Succeeds**: learns decision-relevant structure |

---

## ARBS Integration Recommendations

### 1. Risk Model Training

**Current Approach** (if using traditional estimators):
```python
# Traditional: Optimize for accuracy
Σ̂ = estimator.fit(returns)  # Ledoit-Wolf, sample cov, etc.
w = optimizer.solve(Σ̂, ...)
```

**DFL Approach**:
```python
# Decision-focused: Optimize for portfolio objective
def regret_loss(Σ̂, returns_true):
    w_pred = gmvp_weights(Σ̂)
    Σ_true = empirical_covariance(returns_true)
    w_opt = gmvp_weights(Σ_true)
    return w_pred.T @ Σ_true @ w_pred - w_opt.T @ Σ_true @ w_opt

# Train neural network to minimize regret
model.fit(X_train, y_train, loss=regret_loss)
```

### 2. Strategy-Specific Risk Models

**Key Insight**: Different strategies need different risk models.

**For ARBS**:
- **Carry Strategy**: Train covariance model with carry-weighted regret loss
- **Momentum Strategy**: Train with momentum-weighted regret loss
- **Signal Combination**: Train with combined alpha-weighted regret loss

**Generalized Regret Loss**:
```
L(θ) = w*α(Σ̂)ᵀ Σtrue w*α(Σ̂) - w*α(Σtrue)ᵀ Σtrue w*α(Σtrue)

where w*α = argmin wᵀΣw - λαᵀw  [mean-variance with alpha]
```

### 3. Integration with Existing Architecture

**ARBS Current Stack**:
```
Signals → AlphaGenerator → RiskModel → Optimizer → Weights
```

**Enhanced with DFL**:
```
Signals → AlphaGenerator → DFL-RiskModel → Optimizer → Weights
                              ↑                ↓
                              └─── Regret Loss ───┘
                                  (train end-to-end)
```

**Implementation**:
1. Keep existing signal generation and alpha scaling
2. Replace static covariance estimators with DFL-trained model
3. Train on historical data with strategy-specific regret loss
4. Retrain periodically (e.g., quarterly) with expanding window

### 4. What NOT to Use

**Avoid**:
- MSE-trained neural networks for covariance prediction
- Objectives that don't align with portfolio construction
- Pure prediction accuracy metrics (Frobenius norm, likelihood)

**Why**: Paper shows MSE-trained models completely fail for portfolio optimization, performing no better than naive 1/N allocation.

---

## Theoretical Implications

### 1. Parameter Uncertainty vs Decision Quality

**Classical View**: Better parameter estimates → Better decisions
**DFL View**: Decision-relevant parameters → Better decisions

**For ARBS**: Focus estimation effort on covariance components that matter for portfolio weights, not uniform accuracy across all parameters.

### 2. Gradient Structure

**Proposition 3 Result**: DFL gradients concentrate in subspaces spanned by:
- `w ⊗ (Σ⁻¹w)` - risk-parity-like structure
- `w ⊗ w` - emphasis on large positions

**Implication**: DFL naturally learns to:
- Balance risk across positions (risk-parity intuition)
- Focus on large absolute weights (concentration control)
- Ignore covariance elements that don't affect weights

### 3. Connection to Grinold-Kahn

**ARBS uses Grinold-Kahn framework**:
```
α = IC × Vol × Z  [alpha scaling]
w* = argmin wᵀΣw - λαᵀw  [portfolio optimization]
```

**DFL Extension**:
- Train Σ model to minimize realized tracking error or volatility
- Align risk estimation with alpha generation
- End-to-end training: Signals → Alpha → Risk → Portfolio

---

## Limitations and Caveats

### 1. Focus on Variance Only

**Paper Scope**: Only examines variance minimization (GMVP), not mean-variance optimization.

**For ARBS**: Need to extend to:
- Mean-variance objectives with alpha signals
- Constraints (position limits, leverage, sector exposure)
- Transaction costs and turnover control

### 2. Unconstrained Optimization

**Paper uses**: Analytical GMVP solution (unconstrained)
**ARBS needs**: Constrained optimization with practical limits

**Extension Required**: DFL with inequality constraints (harder to differentiate through)

### 3. Short Position Risk

**Paper Finding**: DFL shows weaker risk control on short positions (Figure 7, area ③)

**For ARBS**: May need additional mechanisms to manage short-side risk, especially for strategies with significant short exposure.

### 4. Computational Cost

**DFL requires**:
- Neural network training (hours to days)
- Backpropagation through optimization layer
- Repeated retraining as data expands

**ARBS consideration**: Balance computational cost vs. performance improvement.

---

## Experimental Details

### Data Setup
- **Universes**: 49 Industry portfolios, S&P 100, Dow 30
- **Period**: 2010-2024 (training: 2010-2018, validation: 2018-2021, test: 2021-2023)
- **Split**: 6:2:2 (train:val:test)

### Hyperparameters
- **Model**: DLinear (simple linear architecture)
- **Input window**: δin ∈ {5, 21, 63, 126, 252} days
- **Forecast horizon**: δout ∈ {5, 21, 63, 126, 252} days
- **Optimizer**: Adam
- **Learning rate**: 10⁻³ to 10⁻⁵ (grid search)
- **Batch size**: 16 to 64
- **Early stopping**: 7 epochs no improvement

### Evaluation
- **Primary metric**: Annualized realized volatility
- **Rebalancing**: Hold for δout days, then rebalance
- **Comparison**: Historical, Ledoit-Wolf, OAS, PFL, Equal-weight

---

## Implementation Checklist for ARBS

### Phase 1: Proof of Concept
- [ ] Implement DFL training for simple GMVP on single futures sector
- [ ] Compare realized volatility vs. Ledoit-Wolf and sample covariance
- [ ] Validate gradient computation through optimization layer
- [ ] Measure computational cost (training time, inference speed)

### Phase 2: Strategy Integration
- [ ] Extend regret loss to mean-variance with alpha signals
- [ ] Integrate with existing AlphaGenerator output
- [ ] Handle constraints (box constraints, leverage limits)
- [ ] Implement rolling retraining schedule

### Phase 3: Production
- [ ] Multi-asset class support (futures, swaps)
- [ ] Strategy-specific risk models (carry, momentum, mean reversion)
- [ ] Online learning / incremental updates
- [ ] Monitoring and performance attribution

---

## Related Concepts

### Prediction-Focused Learning (PFL)
Traditional ML approach: predict parameters accurately, then use for optimization.

### Decision-Focused Learning (DFL)
Modern approach: optimize parameters directly for decision quality.

### Regret Loss
Difference between decision performance with predicted vs. optimal parameters.

### Ledoit-Wolf Shrinkage
Classical covariance estimator shrinking sample covariance toward structured target.

### Oracle Approximating Shrinkage (OAS)
Data-driven shrinkage intensity selection.

---

## Key References from Paper

1. **Elmachtoub & Grigas (2022)**: "Smart Predict, then Optimize" - foundational DFL paper
2. **Ledoit & Wolf (2003, 2004)**: Shrinkage covariance estimation
3. **Markowitz (1952)**: Mean-variance optimization foundation
4. **DeMiguel, Garlappi, Uppal (2009)**: "Optimal versus naive diversification" - shows estimation error impact

---

## Citations for ARBS Documentation

When referencing this approach:

> Kim, J., Tae, I., & Lee, Y. (2025). Estimating Covariance for Global Minimum Variance Portfolio: A Decision-Focused Learning Approach. arXiv:2508.10776

Key quote:
> "Models optimized solely for MSE do not necessarily yield near-optimal investment decisions. Decision-focused learning directly incorporates the decision objective into the training loss."

---

## Summary for ARBS Team

**Bottom Line**:
1. **Traditional risk models optimize for prediction accuracy** - this is wrong for portfolio optimization
2. **DFL optimizes risk models for portfolio performance** - this is correct and achieves 15-20% volatility reduction
3. **For ARBS**: Implement DFL training for covariance matrices, aligned with specific strategy objectives
4. **Expected benefit**: More stable allocations, lower realized volatility, better risk-adjusted returns

**Next Steps**:
1. Implement regret loss for GMVP (simpler, no alpha)
2. Extend to mean-variance with ARBS alpha signals
3. Compare vs. current Ledoit-Wolf implementation
4. Measure impact on strategy Sharpe ratio and IC
