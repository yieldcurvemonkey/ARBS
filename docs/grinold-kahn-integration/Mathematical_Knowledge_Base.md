# Enhanced Grinold-Kahn Mathematical Knowledge Base

**Created**: 2025-11-17
**Sources**: ARBS + IdeaHub Analysis
**Purpose**: Consolidated mathematical reference with corrections and enhancements

## 1. The Fundamental Law - Corrected Formulations

### 1.1 Basic Form
```
IR = IC × √BR
```

Where:
- **IR**: Information Ratio (risk-adjusted excess return)
- **IC**: Information Coefficient (correlation between forecast and outcome)
- **BR**: Breadth (number of independent decisions per period)

### 1.2 Extended Form with Transfer Coefficient
```
IR = IC × √BR × TC
```

Where:
- **TC**: Transfer Coefficient (how well skill translates to portfolio, ∈ [0,1])
- TC = 1.0 for unconstrained implementation
- TC < 1.0 due to constraints, costs, market frictions

### 1.3 IC Decay Formula (CORRECTED)

**INCORRECT** (Bug found in IdeaHub):
```
IC_effective = IC_0 × (1 - decay_rate)^(holding_period/2)
```

**CORRECT**:
```
IC_effective = IC_0 × (1 - decay_rate)^holding_period
```

**Alternative (Average IC over holding period)**:
```
IC_avg = IC_0 × [1 - (1 - decay_rate)^holding_period] / [holding_period × decay_rate]
```

**Numerical Example**:
- IC_0 = 0.05, decay_rate = 0.10, holding_period = 3 months
- Wrong: 0.05 × 0.90^1.5 = 0.0427
- Right: 0.05 × 0.90^3 = 0.0365
- **Impact**: 17% overestimation of effective IC

## 2. Alpha Generation Formula

### 2.1 Grinold-Kahn Alpha Scaling
```
α_i = IC × σ_i × z_i
```

Where:
- **α_i**: Expected return for asset i (in %)
- **IC**: Information coefficient (forecast skill)
- **σ_i**: Volatility of asset i (annualized)
- **z_i**: Standardized signal (z-score, dimensionless)

### 2.2 Why This Matters

**Without scaling**: Z-score of 2.0 → interpreted as 200% expected return (!)
**With scaling**: Z-score of 2.0 × IC(0.05) × Vol(10%) = 1% expected return

### 2.3 Dynamic IC Estimation Methods

**Method 1: Rolling Window**
```python
IC_t = Correlation(signals[t-window:t], returns[t-window+1:t+1])
```
- Simple but noisy with small windows
- Window typically 60-120 days

**Method 2: EWMA (Exponentially Weighted)**
```python
IC_t = λ × IC_{t-1} + (1-λ) × IC_observed_t
# where λ = exp(-log(2)/halflife)
```
- Adapts to regime changes
- Halflife typically 20-60 days

**Method 3: Regime-Dependent**
```python
IC_t = IC_high_vol if volatility_t > threshold else IC_low_vol
```
- Different IC for different market regimes
- Requires regime detection

## 3. Portfolio Optimization

### 3.1 Mean-Variance Objective
```
maximize: w'α - (λ/2) × w'Σw
```

Equivalently:
```
minimize: -w'α + (λ/2) × w'Σw
```

Where:
- **w**: Portfolio weights vector
- **α**: Expected returns (alphas) vector
- **Σ**: Covariance matrix
- **λ**: Risk aversion parameter

### 3.2 Optimal Weights (Unconstrained)
```
w* = (1/λ) × Σ^(-1) × α
```

This is the analytical solution when no constraints are present.

### 3.3 Risk Aversion Parameter Calibration

**Grinold-Kahn Rule**:
```
λ = 2 / target_volatility
```

**Example**:
- Target volatility = 10% annually
- λ = 2/0.10 = 20

### 3.4 Value Added Formula
```
VA = IR² / (4λ_R)
```

Where VA is the risk-adjusted value added by active management.

## 4. Covariance Estimation

### 4.1 Ledoit-Wolf Shrinkage (Corrected)
```
Σ̂ = δ × F + (1-δ) × S
```

Where:
- **S**: Sample covariance matrix
- **F**: Target matrix (structured prior)
- **δ**: Optimal shrinkage intensity

### 4.2 Optimal Shrinkage Intensity
```
δ* = min(1, κ̂/T)
```

Where:
```
κ̂ = (1/T²) × Σ[t=1 to T] ||y_t × y_t' - S||²_F
```

### 4.3 Per-Sector Shrinkage (Advanced)

From Žignić et al. (2024):
```
Σ̂_sector_m = α_m × S_m + (1-α_m) × F_m
```

Where each sector m gets its own shrinkage intensity α_m.

## 5. Transaction Costs

### 5.1 Linear + Square-Root Model
```
Cost = spread_cost + impact_cost × √(trade_size)
```

Where:
- **spread_cost**: Bid-ask spread (typically 5-20 bps)
- **impact_cost**: Market impact coefficient

### 5.2 Net Alpha for Shorts

For short positions, adjust alpha for borrowing costs:
```
α_net = α_gross - (borrow_rate + 2 × spread_cost)
```

Factor of 2 on spread accounts for round-trip.

### 5.3 Optimal Shorting Threshold

Don't short if costs consume too much alpha:
```
Short only if: α_net / |α_gross| > threshold (typically 0.20)
```

## 6. Performance Metrics

### 6.1 Information Ratio (Realized)
```
IR_realized = mean(r_active) / std(r_active)
```

Where r_active = portfolio returns - benchmark returns

### 6.2 Transfer Coefficient (Realized)
```
TC = IR_realized / IR_expected
    = IR_realized / (IC × √BR)
```

### 6.3 Breadth Calculation

**Time Series Breadth**:
```
BR = N_assets × N_rebalances_per_year
```

**Cross-Sectional Breadth**:
```
BR_effective = BR_raw × (1 - ρ̄²)
```

Where ρ̄ is average pairwise correlation of signals.

## 7. Monte Carlo Validation (CORRECTED)

### 7.1 Weight Normalization Bug

**INCORRECT**:
```python
weights = forecasts / br  # Does NOT normalize correctly
```

**CORRECT**:
```python
# For unit variance portfolio:
weights = forecasts / np.sqrt(np.sum(forecasts**2))

# For risk parity:
weights = (1/volatilities) / np.sum(1/volatilities)
```

### 7.2 Proper IR Simulation
```python
def simulate_ir(ic, br, n_periods):
    realized_returns = []
    for t in range(n_periods):
        # Generate BR independent forecasts
        forecasts = np.random.randn(br)
        true_returns = ic * forecasts + np.sqrt(1 - ic**2) * np.random.randn(br)

        # Normalize weights properly
        weights = forecasts / np.sqrt(np.sum(forecasts**2))

        # Portfolio return
        portfolio_return = np.sum(weights * true_returns)
        realized_returns.append(portfolio_return)

    return np.mean(realized_returns) / np.std(realized_returns)
```

## 8. Critical Implementation Checks

### 8.1 IC Validation
```python
# ALWAYS verify IC calculation
actual_ic = np.corrcoef(signals, returns)[0, 1]
expected_ic = model.get_ic()
assert abs(actual_ic - expected_ic) < tolerance, f"IC mismatch: {actual_ic} vs {expected_ic}"
```

### 8.2 Covariance Matrix Validation
```python
# Check positive definiteness
eigenvalues = np.linalg.eigvals(cov_matrix)
assert np.all(eigenvalues > 0), "Covariance matrix not positive definite"

# Check condition number
condition_number = np.linalg.cond(cov_matrix)
assert condition_number < 1000, f"Poorly conditioned: {condition_number}"
```

### 8.3 Portfolio Weight Validation
```python
# Budget constraint
assert abs(np.sum(weights) - 1.0) < 1e-6, "Weights don't sum to 1"

# Leverage constraint
assert np.sum(np.abs(weights)) <= leverage_limit, "Leverage exceeded"
```

## 9. Recent Research Enhancements (2023-2024)

### 9.1 Two-Step Covariance (García-Medina 2024)
1. Hierarchical clustering to find blocks
2. Random Matrix Theory filtering per block
3. **Result**: Best risk diversification, lowest concentration

### 9.2 Stochastic Block Model
- Allows non-zero correlations between sectors
- Critical for global macro (cross-currency effects)

### 9.3 MOM_7M Strategy (Yang & Shi 2023)
- Lookback: 7 months (147 trading days)
- Exclude recent 10% (15 days) to avoid reversal
- Target Sharpe: 0.62

## 10. Practical Rules of Thumb

### 10.1 IC Reference Values
- IC = 0.00: No skill
- IC = 0.02-0.05: Typical quant strategy
- IC = 0.05-0.10: Good strategy
- IC = 0.10-0.15: Excellent (rare)
- IC > 0.15: Check for lookahead bias

### 10.2 Breadth Guidelines
- Daily rebalancing: BR ≈ 250 × N_assets
- Weekly rebalancing: BR ≈ 52 × N_assets
- Monthly rebalancing: BR ≈ 12 × N_assets
- Reduce by (1 - ρ̄²) for correlated signals

### 10.3 Risk Aversion Settings
- Conservative: λ = 3-5
- Moderate: λ = 1-2
- Aggressive: λ = 0.5-1
- Market neutral: Use higher λ (5-10)

### 10.4 Transaction Cost Thresholds
- Don't trade if cost > 50% of alpha
- Don't short if cost > 80% of alpha
- Minimum alpha for trading: 10-20 bps

## 11. Common Pitfalls & Solutions

### 11.1 Pitfall: Using Prices Instead of Returns
**Problem**: Prices are non-stationary, invalidating statistics
**Solution**: ALWAYS convert to returns first

### 11.2 Pitfall: IC Estimation with Small Samples
**Problem**: Noisy IC with < 60 observations
**Solution**: Use shrinkage or longer history

### 11.3 Pitfall: Ignoring Transaction Costs
**Problem**: Backtest shows profit, live trading loses
**Solution**: Include realistic cost model (spread + impact)

### 11.4 Pitfall: Over-Optimistic Breadth
**Problem**: Assuming all bets are independent
**Solution**: Adjust for correlation: BR_eff = BR × (1 - ρ̄²)

## 12. Implementation Checklist

### Before Going Live
- [ ] IC validated on out-of-sample data
- [ ] Transaction costs included
- [ ] Covariance matrix is positive definite
- [ ] Weights sum to 1 (or target exposure)
- [ ] Risk limits enforced
- [ ] Decay formulas use correct exponents
- [ ] Monte Carlo uses proper normalization
- [ ] Silent failures have assertions
- [ ] Performance matches theoretical IR within 20%
- [ ] Sharpe ratio degradation from costs quantified

## References

### Core Texts
- Grinold & Kahn (1999): Active Portfolio Management, 2nd Edition
- Chapters 5-6: Fundamental Law
- Chapter 14: Portfolio Construction
- Chapter 15: Long/Short and Transaction Costs

### Recent Papers (2023-2024)
- García-Medina et al. (2024): Two-step covariance with RMT
- Žignić et al. (2024): Block-diagonal with per-sector shrinkage
- Yang & Shi (2023): MOM_7M sector momentum strategy

### Classic Papers
- Ledoit & Wolf (2004): Honey, I Shrunk the Sample Covariance Matrix
- Chen et al. (2010): Oracle Approximating Shrinkage
- Moskowitz et al. (2012): Time Series Momentum

## Summary

This enhanced knowledge base corrects critical errors found in common implementations:
1. IC decay formula (exponent error: 17% impact)
2. Monte Carlo normalization (biased IR estimates)
3. Missing IC validation (silent failures)
4. Transaction cost modeling (unrealistic backtests)

The integration of IdeaHub insights with ARBS creates a mathematically correct, practically grounded implementation of the Grinold-Kahn framework.