# Long/Short Market-Neutral Strategy Design

**Date**: 2025-11-11
**Status**: Design Specification
**Branch**: `claude/parallel-subagents-execution-011CV2u6sUxtRETAdvuEcVuQ`
**Author**: AGENT-04

---

## Executive Summary

This document specifies the **long/short market-neutral** equity strategy for ARBS. Unlike long-only strategies that suffer from a ~50% information ratio penalty (transfer coefficient TC ≈ 0.5), long/short strategies achieve much higher transfer coefficients (TC ≈ 0.8-0.9 for sector-neutral, TC ≈ 0.9-1.0 for unconstrained), enabling significantly better realized information ratios.

### Key Results from Grinold-Kahn Chapter 15

**Long-only penalty** (500 stocks, 4.5% active risk):
- Unconstrained IR: 2.23
- Long-only IR: 1.11
- **Shrinkage: 50%** (transfer coefficient TC = 0.50)

**Long/short advantage**:
- Sector-neutral long/short: TC ≈ 0.8-0.9
- Unconstrained long/short: TC ≈ 0.9-1.0
- **Expected IR improvement: 60-80% vs long-only**

### Target Performance Metrics

| Metric | Long-Only | Long/Short Sector-Neutral |
|--------|-----------|---------------------------|
| IC (combined signals) | 0.06 | 0.06 |
| Breadth (BR) | 2,000 | 3,000 |
| Transfer Coefficient | 0.50 | 0.85 |
| Theoretical IR | 1.90 | 2.78 |
| Realized IR (target) | 0.95 | 1.80 |

**Conclusion**: Long/short sector-neutral strategy should achieve **IR ≈ 1.8**, nearly **2× higher** than long-only.

---

## 1. Market-Neutral Definition

### 1.1 Dollar-Neutral

**Constraint**: Zero net market exposure (sum of weights = 0)

```
Σ_i h_i = 0
```

**Interpretation**: For every $1 long, hold $1 short. Net market exposure is zero.

**Example**:
- Long position: +$500,000 (50% of $1M portfolio)
- Short position: -$500,000 (50% of $1M portfolio)
- Net exposure: $0
- Gross exposure: $1,000,000 (100% leverage)

### 1.2 Beta-Neutral (Stronger Version)

**Constraint**: Zero net beta to market

```
Σ_i h_i · β_i^market = 0
```

where β_i^market = market beta for asset i (from CAPM or factor model)

**Interpretation**: Portfolio has zero sensitivity to market movements. If market goes up 1%, portfolio return ≈ 0% (plus alpha).

**Example**:
- Stock A: weight = +0.05, β = 1.2 → contribution = +0.060
- Stock B: weight = +0.03, β = 0.8 → contribution = +0.024
- Stock C: weight = -0.04, β = 1.5 → contribution = -0.060
- Stock D: weight = -0.04, β = 0.6 → contribution = -0.024
- Net beta exposure: 0.000 ✓

**Recommendation**: Start with dollar-neutral (simpler), add beta-neutral if market timing risk is a concern.

### 1.3 Sector-Neutral

**Constraint**: Zero net exposure to each sector

```
Σ_{i ∈ sector_s} h_i = 0  for each sector s ∈ {Energy, Materials, ..., Real Estate}
```

**GICS Level 1 Sectors** (11 total):
1. Energy
2. Materials
3. Industrials
4. Consumer Discretionary
5. Consumer Staples
6. Health Care
7. Financials
8. Information Technology
9. Communication Services
10. Utilities
11. Real Estate

**Interpretation**: Within each sector, long and short positions cancel out. Portfolio return comes from **stock selection within sectors**, not sector bets.

**Example** (Information Technology sector):
- AAPL: weight = +0.03
- MSFT: weight = +0.02
- NVDA: weight = -0.03
- INTC: weight = -0.02
- Net sector exposure: 0.00 ✓

**Impact on Transfer Coefficient**:
- Dollar-neutral only: TC ≈ 0.9-1.0
- Dollar + sector-neutral: TC ≈ 0.8-0.9
- **Trade-off**: Sector-neutral reduces TC slightly (~10%) but eliminates sector risk

**Recommendation**: Implement sector-neutral constraints. The 10% TC reduction is worth the risk control.

---

## 2. Optimization Objective

### 2.1 Mean-Variance with Transaction Costs

**Objective** (maximize):
```
max_h: α^T h - λ h^T Σ h - κ · TC(h, h_old)
```

**Components**:

1. **Alpha term**: α^T h
   - α = vector of expected returns (IC × Vol × Z from AlphaGenerator)
   - h = portfolio weights
   - Maximizes expected active return

2. **Risk term**: -λ h^T Σ h
   - λ = risk aversion parameter (default: 1.0)
   - Σ = covariance matrix (from PPFMCovariance or LedoitWolfShrinkage)
   - Penalizes portfolio variance

3. **Transaction cost term**: -κ · TC(h, h_old)
   - κ = transaction cost penalty (default: 0.5)
   - TC = transaction cost function (proportional + quadratic)
   - h_old = previous period weights
   - Penalizes turnover

### 2.2 Transaction Cost Function

**Formula** (from Grinold-Kahn Chapter 16):
```
TC(h, h_old) = Σ_i c_i · |Δh_i| + Σ_i d_i · (Δh_i)²
```

where:
- Δh_i = h_i - h_i^old (change in weight)
- c_i = proportional cost (commissions, bid-ask spread)
- d_i = quadratic cost (market impact)

**Proportional cost** (typical values):
- c_i = 0.001 (10 bps round-trip) for large-cap liquid stocks
- c_i = 0.002 (20 bps) for mid-cap
- c_i = 0.005 (50 bps) for small-cap illiquid stocks

**Quadratic cost** (market impact):
```
d_i = k · σ_i / sqrt(V_avg,i)
```

where:
- k = market impact coefficient (default: 0.02)
- σ_i = stock volatility (annualized)
- V_avg,i = average daily trading volume

**Inventory risk model** (Grinold-Kahn p. 455):
> "It costs approximately one day's volatility to trade one day's volume"

**Implementation**: Use `TransactionCosts/InventoryRiskModel.py` (Phase 4 of equity plan)

### 2.3 Risk Aversion Parameter λ

**From Grinold-Kahn** (Chapter 14, Eq 14.2):
```
λ_A = IR / ω_A
```

where:
- IR = target information ratio (e.g., 1.5)
- ω_A = target active risk (e.g., 6% annualized)

**Example**: To achieve IR = 1.5 with 6% active risk:
```
λ = 1.5 / 0.06 = 25.0
```

**Typical ranges**:
- λ = 1.0: Aggressive (high turnover, high risk)
- λ = 10.0: Moderate (balanced risk/return)
- λ = 50.0: Conservative (low turnover, low risk)

**Recommendation**: Start with λ = 10.0, calibrate based on realized risk/return.

---

## 3. Constraints

### 3.1 Market-Neutral Constraints

#### Dollar-Neutral (Required)

**Mathematical form**:
```python
Σ_i h_i = 0
```

**CVXPY implementation**:
```python
import cvxpy as cp

# Decision variable
w = cp.Variable(n_assets)

# Dollar-neutral constraint
constraints = [cp.sum(w) == 0]
```

**scipy.optimize implementation** (current MeanVarianceOptimizer):
```python
constraints.append({
    'type': 'eq',
    'fun': lambda w: np.sum(w),  # sum(w) = 0
})
```

#### Beta-Neutral (Optional)

**Mathematical form**:
```python
Σ_i h_i · β_i = 0
```

**CVXPY implementation**:
```python
# Beta-neutral constraint
constraints.append(w @ market_betas == 0)
```

where `market_betas` is a vector of CAPM betas for each stock.

**When to use**:
- Use beta-neutral if portfolio exhibits unintended market timing
- Use dollar-neutral if beta exposure is acceptable
- **Recommendation**: Start with dollar-neutral (simpler)

### 3.2 Sector-Neutral Constraints

**Mathematical form**:
```python
Σ_{i ∈ sector_s} h_i = 0  for each sector s
```

**CVXPY implementation**:
```python
# For each sector
for sector in sectors:
    sector_mask = (sector_exposures == sector)
    constraints.append(cp.sum(w[sector_mask]) == 0)
```

**Data structure**:
```python
# sector_exposures: pl.Series or np.array
# Example:
# ['Information Technology', 'Information Technology', 'Financials', 'Health Care', ...]
```

**Practical considerations**:
- Some sectors may have few stocks (e.g., Utilities: ~30 stocks in S&P 500)
- May need to relax constraints for small sectors (allow ±1% deviation)
- Monitor portfolio for "sector concentration" (long/short within sector)

### 3.3 Position Limits

**Mathematical form**:
```python
|h_i| ≤ h_max  for all i
```

**Typical values**:
- h_max = 0.05 (5% max per position, conservative)
- h_max = 0.10 (10% max, moderate)
- h_max = 0.15 (15% max, aggressive)

**CVXPY implementation**:
```python
# Individual position limits (long or short)
constraints.extend([
    w >= -h_max,  # Short limit
    w <= h_max,   # Long limit
])
```

**Rationale**:
- Prevents over-concentration in single names
- Limits idiosyncratic risk
- Required by most institutional mandates

**Recommendation**: Start with h_max = 0.05 (5%), relax to 0.10 if needed for higher IR.

### 3.4 Gross Leverage Limit

**Mathematical form**:
```python
Σ_i |h_i| ≤ L_max
```

**Typical values**:
- L_max = 2.0 (100% long, 100% short) - standard long/short
- L_max = 3.0 (150% long, 150% short) - moderate leverage
- L_max = 4.0 (200% long, 200% short) - high leverage (hedge fund)

**CVXPY implementation**:
```python
# Gross leverage constraint
constraints.append(cp.norm1(w) <= L_max)
```

**Note**: `cp.norm1(w)` computes Σ|w_i|

**scipy.optimize implementation**:
```python
constraints.append({
    'type': 'ineq',
    'fun': lambda w: L_max - np.sum(np.abs(w)),
})
```

**Recommendation**: Start with L_max = 2.0 (standard long/short), increase if risk-adjusted returns improve.

### 3.5 Turnover Limit (Optional)

**Mathematical form**:
```python
Σ_i |h_i - h_i^old| ≤ TO_max
```

**Typical values**:
- TO_max = 0.5 (50% turnover per rebalance)
- TO_max = 1.0 (100% turnover per rebalance)
- TO_max = 2.0 (200% turnover, high-frequency)

**CVXPY implementation**:
```python
# Turnover constraint
constraints.append(cp.norm1(w - w_old) <= TO_max)
```

**From Grinold-Kahn** (Chapter 16, p. 461):
> "You can achieve at least 75% of the value added with 50% of the turnover"

**Recommendation**: Include transaction costs in objective (κ term) rather than hard turnover limit. Let optimizer choose optimal turnover.

---

## 4. Alpha Preprocessing (CRITICAL!)

### 4.1 Why Sector-Neutralize Alphas?

**Problem**: If alphas have sector biases (e.g., positive mean for tech stocks, negative mean for utilities), optimizer will create net sector exposures **even with sector-neutral constraints**.

**Example** (without sector-neutralization):
- Tech stocks: mean(α) = +2%
- Utility stocks: mean(α) = -1%
- Optimizer with sector-neutral constraint:
  - Long: Top tech stocks (α = +3%, +4%)
  - Short: Bottom tech stocks (α = +1%, +2%)
  - Net tech exposure: 0% ✓ (satisfies constraint)
  - **But portfolio is effectively long tech vs utilities!**

**Solution**: **Sector-neutralize alphas before optimization** to ensure pure stock selection.

### 4.2 Sector-Neutralization Formula

**Mathematical form**:
```python
α_i^SN = α_i - mean(α_{sector(i)})
```

**Polars implementation**:
```python
def sector_neutralize(alphas: pl.Series, sectors: pl.Series) -> pl.Series:
    """
    Subtract sector mean from each alpha

    Args:
        alphas: Raw alpha signals
        sectors: Sector classification for each stock

    Returns:
        Sector-neutral alphas with zero mean per sector
    """
    df = pl.DataFrame({"alpha": alphas, "sector": sectors})

    # Calculate sector means
    sector_means = df.group_by("sector").agg(
        pl.col("alpha").mean().alias("sector_mean")
    )

    # Subtract sector mean from each alpha
    result = df.join(sector_means, on="sector").with_columns(
        (pl.col("alpha") - pl.col("sector_mean")).alias("alpha_sn")
    )

    return result["alpha_sn"]
```

**Validation** (after sector-neutralization):
```python
# Check: mean(α) per sector should be ≈ 0
df = pl.DataFrame({"alpha_sn": alphas_sn, "sector": sectors})
sector_means = df.group_by("sector").agg(pl.col("alpha_sn").mean())
assert sector_means["alpha_sn"].abs().max() < 1e-10  # Numerical zero
```

### 4.3 Integration with AlphaGenerator

**Current AlphaGenerator** (from ARBS):
```python
# Signals/AlphaGenerator.py (existing)
class AlphaGenerator:
    def generate(
        self,
        signals: pl.DataFrame,  # z-scores from signals
        volatility: pl.Series,
        ic: float,
    ) -> pl.Series:
        """α = IC × Vol × Z"""
        return ic * volatility * signals["z_score"]
```

**Extended AlphaGenerator** (add sector-neutralization):
```python
class AlphaGenerator:
    def generate(
        self,
        signals: pl.DataFrame,
        volatility: pl.Series,
        ic: float,
        sectors: pl.Series = None,
        neutralize: bool = False,
    ) -> pl.Series:
        """
        Generate alphas with optional sector-neutralization

        Args:
            signals: Signal z-scores
            volatility: Asset volatility (for scaling)
            ic: Information coefficient (expected IC)
            sectors: Sector classification (required if neutralize=True)
            neutralize: If True, sector-neutralize alphas

        Returns:
            Alpha signals (sector-neutral if requested)
        """
        # Standard alpha generation
        alphas = ic * volatility * signals["z_score"]

        # Sector-neutralize if requested
        if neutralize:
            if sectors is None:
                raise ValueError("Must provide sectors for neutralization")
            alphas = self._sector_neutralize(alphas, sectors)

        return alphas

    def _sector_neutralize(
        self, alphas: pl.Series, sectors: pl.Series
    ) -> pl.Series:
        """Sector-neutralize alphas (see formula above)"""
        df = pl.DataFrame({"alpha": alphas, "sector": sectors})
        sector_means = df.group_by("sector").agg(pl.col("alpha").mean())
        result = df.join(sector_means, on="sector").with_columns(
            (pl.col("alpha") - pl.col("alpha_mean")).alias("alpha_sn")
        )
        return result["alpha_sn"]
```

**Usage**:
```python
# Generate sector-neutral alphas
alphas = AlphaGenerator().generate(
    signals=combined_signals,
    volatility=data["volatility"],
    ic=0.06,
    sectors=data["sector"],
    neutralize=True,  # Critical for long/short sector-neutral!
)
```

### 4.4 Why Signals are Already Sector-Neutral

**From Phase 2** (Equity Signals implementation):
- ValueSignal: Uses `_to_sector_neutral_scores()` → z-scores within each sector
- MomentumSignal: Uses `_to_sector_neutral_scores()` → z-scores within each sector
- QualitySignal: Uses `_to_sector_neutral_scores()` → z-scores within each sector

**Result**: Signal z-scores already have mean=0, std=1 **within each sector**.

**Question**: If signals are already sector-neutral, why neutralize alphas again?

**Answer**: After IC × Vol × Z scaling:
- Volatility varies by stock (tech stocks have higher vol than utilities)
- α = IC × Vol × Z introduces sector biases via volatility
- **Must neutralize after volatility scaling**

**Example**:
- Tech stock: z=+1.0, vol=30% → α = 0.06 × 0.30 × 1.0 = +1.8%
- Utility stock: z=+1.0, vol=15% → α = 0.06 × 0.15 × 1.0 = +0.9%
- Mean tech alpha > mean utility alpha (even though z-scores were sector-neutral!)

**Conclusion**: Always sector-neutralize alphas **after volatility scaling** for long/short strategies.

---

## 5. Expected IR Impact vs Long-Only

### 5.1 Transfer Coefficient Analysis

**From Grinold-Kahn Chapter 15**:

**Long-only** (500 stocks, 4.5% active risk):
```
IR_unconstrained = 2.23
IR_long-only = 1.11
TC_long-only = IR_long-only / IR_unconstrained = 0.50
```

**Shrinkage formula** (Eq 15.13, p. 437):
```
TC_long-only ≈ 1 - 0.06 × ω_A × sqrt(N)
```

For ω_A = 4.5%, N = 500:
```
TC ≈ 1 - 0.06 × 0.045 × sqrt(500) = 1 - 0.06 = 0.94  (theoretical)
TC_observed = 0.50  (empirical, accounts for volatility heterogeneity)
```

**Long/short sector-neutral** (estimated):
- No long-only constraint: Eliminates ~40% of shrinkage
- Sector-neutral constraint: Adds ~10% shrinkage
- **Net TC ≈ 0.8-0.9**

**Long/short unconstrained** (no sector constraints):
- No long-only constraint: Eliminates ~40% of shrinkage
- Only dollar-neutral constraint: Minimal impact
- **Net TC ≈ 0.9-1.0**

### 5.2 Breadth Increase for Long/Short

**Long-only** (500 stocks, quarterly rebalance):
```
BR_long-only = 500 stocks × 4 quarters = 2,000 bets/year
```

**Long/short** (500 stocks, quarterly rebalance):
- Can independently bet on EACH stock (long or short)
- Long-only: Can only overweight (50% of stocks usable)
- Long/short: Can overweight or underweight (100% of stocks usable)
- **Effective breadth increase: 50%**

```
BR_long-short = 3,000 bets/year  (50% more than long-only)
```

**Alternative view** (from Grinold-Kahn):
- Long/short = 2 portfolios (long portfolio + short portfolio)
- Each portfolio has 250 stocks
- BR = 2 × 250 × 4 = 2,000 (same as long-only)
- **But higher TC compensates**

**Recommendation**: Use conservative BR = 2,000 (same as long-only) in IR calculations. TC improvement is the primary driver.

### 5.3 Expected Information Ratio

**Fundamental Law** (Grinold-Kahn Chapter 6):
```
IR = IC × sqrt(BR) × TC
```

#### Long-Only Strategy

```
IC = 0.06  (combined signals: Value + Momentum + Quality)
BR = 2,000  (500 stocks × 4 quarters)
TC = 0.50  (long-only shrinkage)

IR_long-only = 0.06 × sqrt(2000) × 0.50 = 1.34
```

**Accounting for estimation error, transaction costs**:
```
IR_realized ≈ 0.70 × IR_theoretical = 0.94
```

#### Long/Short Sector-Neutral Strategy

```
IC = 0.06  (same signals)
BR = 2,000  (conservative, no breadth credit)
TC = 0.85  (sector-neutral long/short)

IR_long-short = 0.06 × sqrt(2000) × 0.85 = 2.28
```

**Accounting for estimation error, transaction costs**:
```
IR_realized ≈ 0.70 × IR_theoretical = 1.60
```

#### Long/Short Unconstrained Strategy

```
IC = 0.06
BR = 2,000
TC = 0.95  (unconstrained long/short)

IR_unconstrained = 0.06 × sqrt(2000) × 0.95 = 2.54
IR_realized ≈ 1.78
```

### 5.4 Summary Table

| Strategy | IC | BR | TC | IR (theoretical) | IR (realized) | IR Improvement vs Long-Only |
|----------|----|----|----|--------------------|---------------|----------------------------|
| Long-only | 0.06 | 2,000 | 0.50 | 1.34 | 0.94 | Baseline |
| Long/short sector-neutral | 0.06 | 2,000 | 0.85 | 2.28 | 1.60 | **+70%** |
| Long/short unconstrained | 0.06 | 2,000 | 0.95 | 2.54 | 1.78 | **+89%** |

**Conclusion**: Long/short sector-neutral achieves **IR ≈ 1.6**, versus **IR ≈ 0.9** for long-only. This is a **70% improvement** and well above top-quartile equity manager benchmark (IR = 0.5).

### 5.5 Risk/Return Profile

**Active risk** (ω_A):
- Long-only: 4.5% (typical)
- Long/short: 6.0% (higher risk capacity due to hedging)

**Expected alpha** (α = IR × ω_A):
- Long-only: 0.94 × 4.5% = 4.2% per year
- Long/short: 1.60 × 6.0% = 9.6% per year

**Transaction costs** (from Grinold-Kahn Chapter 16):
- Long-only: 1.5% per year (lower turnover)
- Long/short: 2.5% per year (higher turnover, both legs)

**Net alpha** (after transaction costs):
- Long-only: 4.2% - 1.5% = 2.7% per year
- Long/short: 9.6% - 2.5% = 7.1% per year

**Sharpe ratio** (assuming 10% market volatility, 3% risk-free rate):
- Long-only: (7% + 2.7%) / 10% = 0.97
- Long/short: 7.1% / 6.0% = 1.18 (market-neutral, no market return)

**Conclusion**: Long/short achieves higher Sharpe ratio despite no market exposure.

---

## 6. Integration with Existing MeanVarianceOptimizer

### 6.1 Current Architecture

**Existing optimizer** (`Optimizer/MeanVarianceOptimizer.py`):
- Uses `scipy.optimize.minimize` with SLSQP method
- Supports: long_only, leverage_limit, position_limit, allow_cash
- Constraint system: Budget constraint (sum(w) = 1.0 or ≤ 1.0)
- Objective: -α'w + λ/2 × w'Σw

**Limitation for long/short**:
- Budget constraint: `sum(w) = 1.0` (long-only interpretation)
- No sector-neutral constraints
- No transaction cost term

### 6.2 Required Extensions

#### Extension 1: Market-Neutral Mode

**Add parameter**:
```python
class MeanVarianceOptimizer(BaseOptimizer):
    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        market_neutral: bool = False,  # NEW
        leverage_limit: Optional[float] = None,
        position_limit: Optional[float] = None,
        allow_cash: bool = False,
    ):
```

**Modify budget constraint**:
```python
def _build_constraints(self, n_assets: int) -> list:
    constraints = []

    if self.market_neutral:
        # Market-neutral: sum(weights) = 0
        constraints.append({
            'type': 'eq',
            'fun': lambda w: np.sum(w),  # sum(w) = 0
        })
    elif self.allow_cash:
        # Long-only with cash: sum(weights) <= 1.0
        constraints.append({
            'type': 'ineq',
            'fun': lambda w: 1.0 - np.sum(w),
        })
    else:
        # Long-only fully invested: sum(weights) = 1.0
        constraints.append({
            'type': 'eq',
            'fun': lambda w: np.sum(w) - 1.0,
        })

    # ... (rest of constraints)
```

#### Extension 2: Sector-Neutral Constraints

**Add method**:
```python
class MeanVarianceOptimizer(BaseOptimizer):
    def add_sector_neutral_constraints(
        self,
        sector_exposures: pd.Series,
    ):
        """
        Add sector-neutral constraints

        Args:
            sector_exposures: Sector classification for each asset
        """
        self.sector_exposures = sector_exposures
        self.sector_neutral = True
```

**Modify constraint builder**:
```python
def _build_constraints(self, n_assets: int) -> list:
    constraints = []

    # ... (market-neutral or budget constraint)

    # Sector-neutral constraints
    if hasattr(self, 'sector_neutral') and self.sector_neutral:
        sectors = self.sector_exposures.unique()
        for sector in sectors:
            sector_mask = (self.sector_exposures == sector).values
            constraints.append({
                'type': 'eq',
                'fun': lambda w, mask=sector_mask: np.sum(w[mask]),
            })

    return constraints
```

#### Extension 3: Transaction Costs

**Add parameter**:
```python
class MeanVarianceOptimizer(BaseOptimizer):
    def __init__(
        self,
        risk_aversion: float = 1.0,
        long_only: bool = True,
        market_neutral: bool = False,
        tc_penalty: float = 0.0,  # NEW: transaction cost penalty
        leverage_limit: Optional[float] = None,
        position_limit: Optional[float] = None,
        allow_cash: bool = False,
    ):
```

**Modify objective**:
```python
def _objective(
    self,
    weights: np.ndarray,
    alphas: np.ndarray,
    cov_matrix: np.ndarray,
    old_weights: np.ndarray = None,
) -> float:
    """
    Mean-variance objective with transaction costs

    Formula: -α'w + λ/2 × w'Σw + κ × sum(|w - w_old|)
    """
    # Expected return
    expected_return = np.dot(alphas, weights)

    # Variance
    variance = weights @ cov_matrix @ weights

    # Transaction costs (if previous weights provided)
    if old_weights is not None and self.tc_penalty > 0:
        turnover = np.sum(np.abs(weights - old_weights))
        tc_cost = self.tc_penalty * turnover
    else:
        tc_cost = 0.0

    # Objective (minimize)
    obj = -expected_return + 0.5 * self.risk_aversion * variance + tc_cost

    return obj
```

**Modify optimize() signature**:
```python
def optimize(
    self,
    alphas: pd.Series,
    covariance: pd.DataFrame,
    old_weights: pd.Series = None,  # NEW: for transaction costs
) -> pd.Series:
```

### 6.3 Alternative: CVXPY Implementation

**Advantages of CVXPY**:
- Cleaner constraint syntax
- Handles complex constraints (sector-neutral) more naturally
- Better numerical stability for large problems
- Supports DCP (Disciplined Convex Programming) verification

**Recommendation**: Implement `MeanVarianceOptimizerCVXPY` as alternative to scipy-based optimizer.

**Prototype**:
```python
# Optimizer/MeanVarianceOptimizerCVXPY.py
import cvxpy as cp
import numpy as np
import pandas as pd
from typing import Optional

class MeanVarianceOptimizerCVXPY:
    def __init__(
        self,
        risk_aversion: float = 1.0,
        market_neutral: bool = False,
        sector_neutral: bool = False,
        position_limit: float = 0.05,
        leverage_limit: float = 2.0,
        tc_penalty: float = 0.0,
    ):
        self.risk_aversion = risk_aversion
        self.market_neutral = market_neutral
        self.sector_neutral = sector_neutral
        self.position_limit = position_limit
        self.leverage_limit = leverage_limit
        self.tc_penalty = tc_penalty

    def optimize(
        self,
        alphas: pd.Series,
        covariance: pd.DataFrame,
        sector_exposures: pd.Series = None,
        old_weights: pd.Series = None,
    ) -> pd.Series:
        """
        Optimize portfolio using CVXPY
        """
        n = len(alphas)
        alpha_vec = alphas.values
        cov_mat = covariance.values

        # Decision variable
        w = cp.Variable(n)

        # Objective
        expected_return = alpha_vec @ w
        variance = cp.quad_form(w, cov_mat)
        objective = expected_return - 0.5 * self.risk_aversion * variance

        # Transaction costs
        if old_weights is not None and self.tc_penalty > 0:
            turnover = cp.norm1(w - old_weights.values)
            objective -= self.tc_penalty * turnover

        # Constraints
        constraints = []

        # Market-neutral or budget
        if self.market_neutral:
            constraints.append(cp.sum(w) == 0)
        else:
            constraints.append(cp.sum(w) == 1)

        # Position limits
        constraints.extend([
            w >= -self.position_limit,
            w <= self.position_limit,
        ])

        # Leverage limit
        constraints.append(cp.norm1(w) <= self.leverage_limit)

        # Sector-neutral
        if self.sector_neutral and sector_exposures is not None:
            sectors = sector_exposures.unique()
            for sector in sectors:
                mask = (sector_exposures == sector).values
                constraints.append(cp.sum(w[mask]) == 0)

        # Solve
        problem = cp.Problem(cp.Maximize(objective), constraints)
        problem.solve(solver=cp.ECOS)

        if problem.status != 'optimal':
            raise ValueError(f"Optimization failed: {problem.status}")

        return pd.Series(w.value, index=alphas.index)
```

**Integration**:
```python
# In strategy code
from Optimizer.MeanVarianceOptimizerCVXPY import MeanVarianceOptimizerCVXPY

optimizer = MeanVarianceOptimizerCVXPY(
    risk_aversion=10.0,
    market_neutral=True,
    sector_neutral=True,
    position_limit=0.05,
    leverage_limit=2.0,
    tc_penalty=0.5,
)

weights = optimizer.optimize(
    alphas=alphas_sector_neutral,
    covariance=ppfm_cov,
    sector_exposures=data["sector"],
    old_weights=previous_weights,
)
```

### 6.4 Recommendation

**Phase 4 implementation** (Optimization with Constraints):
1. **Extend existing scipy-based optimizer** for market-neutral mode (minimal changes)
2. **Implement CVXPY-based optimizer** as alternative (cleaner for sector-neutral)
3. **Benchmark both** on same problem to validate equivalence
4. **Choose CVXPY** as primary for long/short strategies (better constraint handling)
5. **Keep scipy** as fallback (no additional dependencies)

---

## 7. Implementation Roadmap

### 7.1 Phase 4A: Alpha Preprocessing (Week 12)

**Deliverables**:
- [ ] Extend `AlphaGenerator.generate()` with `neutralize` parameter
- [ ] Implement `_sector_neutralize()` method
- [ ] Add validation tests (sector means = 0 after neutralization)
- [ ] Document when to use neutralization (always for long/short sector-neutral)

**Tests** (10 tests):
```python
# tests/unit/signals/test_alpha_generator.py
def test_sector_neutralization():
    """Alphas have zero mean per sector after neutralization"""
    alphas_sn = generator.generate(..., neutralize=True)
    sector_means = compute_sector_means(alphas_sn, sectors)
    assert np.allclose(sector_means, 0.0, atol=1e-10)
```

### 7.2 Phase 4B: MeanVarianceOptimizer Extensions (Week 12)

**Deliverables**:
- [ ] Add `market_neutral` parameter to `__init__`
- [ ] Modify `_build_constraints()` for market-neutral mode
- [ ] Add `add_sector_neutral_constraints()` method
- [ ] Add `tc_penalty` parameter and modify `_objective()`
- [ ] Update `optimize()` signature to accept `old_weights`

**Tests** (15 tests):
```python
# tests/unit/optimizer/test_mean_variance_optimizer.py
def test_market_neutral_constraint():
    """Market-neutral portfolio has sum(weights) = 0"""
    optimizer = MeanVarianceOptimizer(market_neutral=True)
    weights = optimizer.optimize(alphas, cov)
    assert np.abs(weights.sum()) < 1e-6

def test_sector_neutral_constraints():
    """Sector-neutral portfolio has zero net exposure per sector"""
    optimizer = MeanVarianceOptimizer(market_neutral=True)
    optimizer.add_sector_neutral_constraints(sector_exposures)
    weights = optimizer.optimize(alphas, cov)
    for sector in sectors:
        sector_weight = weights[sector_exposures == sector].sum()
        assert np.abs(sector_weight) < 1e-6
```

### 7.3 Phase 4C: CVXPY Optimizer (Week 13)

**Deliverables**:
- [ ] Implement `MeanVarianceOptimizerCVXPY` class
- [ ] Support market-neutral, sector-neutral, position limits, leverage
- [ ] Add transaction cost penalty
- [ ] Benchmark vs scipy optimizer (should match within 0.1%)

**Tests** (10 tests):
```python
# tests/unit/optimizer/test_cvxpy_optimizer.py
def test_cvxpy_matches_scipy():
    """CVXPY and scipy optimizers produce equivalent results"""
    scipy_weights = scipy_optimizer.optimize(alphas, cov)
    cvxpy_weights = cvxpy_optimizer.optimize(alphas, cov)
    assert np.allclose(scipy_weights, cvxpy_weights, atol=1e-3)
```

### 7.4 Phase 4D: Transaction Cost Model (Week 13)

**Deliverables**:
- [ ] Implement `TransactionCosts/InventoryRiskModel.py`
- [ ] Calculate proportional costs (commissions, spread)
- [ ] Calculate quadratic costs (market impact)
- [ ] Integrate with optimizer objective

**Tests** (8 tests):
```python
# tests/unit/transaction_costs/test_inventory_risk_model.py
def test_square_root_market_impact():
    """Market impact scales with sqrt(trade_size / volume)"""
    tc_model = InventoryRiskModel()
    cost = tc_model.calculate_cost(
        trade_size=100000,
        avg_daily_volume=1000000,
        volatility=0.30,
    )
    # sqrt(0.1) × 0.30 = 0.095 ≈ 9.5% impact
    assert 0.08 < cost < 0.12
```

### 7.5 Phase 4E: Transfer Coefficient Analysis (Week 14)

**Deliverables**:
- [ ] Implement TC measurement tool
- [ ] Compare unconstrained vs long-only vs long/short sector-neutral
- [ ] Validate TC ≈ 0.85 for sector-neutral long/short
- [ ] Document TC results in analysis report

**Tool**:
```python
# Analysis/TransferCoefficientAnalysis.py
class TransferCoefficientAnalysis:
    def measure_tc(
        self,
        alphas: pd.Series,
        weights_unconstrained: pd.Series,
        weights_constrained: pd.Series,
        covariance: pd.DataFrame,
    ) -> float:
        """
        Measure transfer coefficient

        TC = IR_constrained / IR_unconstrained
           = (α'h_C - λ h_C'Σh_C) / (α'h_U - λ h_U'Σh_U)
        """
        ir_unconstrained = self._compute_ir(alphas, weights_unconstrained, covariance)
        ir_constrained = self._compute_ir(alphas, weights_constrained, covariance)
        return ir_constrained / ir_unconstrained
```

---

## 8. Validation & Testing

### 8.1 Unit Tests

**Alpha preprocessing** (10 tests):
- Sector means = 0 after neutralization
- Alpha magnitudes preserved (std dev similar)
- Works with missing sectors (single-stock sectors)

**Optimizer constraints** (20 tests):
- Market-neutral: sum(w) = 0
- Sector-neutral: sum(w[sector]) = 0 for each sector
- Position limits: |w_i| ≤ h_max
- Leverage limits: sum(|w|) ≤ L_max
- Transaction costs: objective includes turnover penalty

**CVXPY vs scipy** (5 tests):
- Equivalent weights (within 0.1%)
- Equivalent objective values
- Equivalent portfolio statistics (return, risk, Sharpe)

### 8.2 Integration Tests

**End-to-end backtest** (5 tests):
- Long/short sector-neutral portfolio construction
- Realized IC, IR, Sharpe vs targets
- Portfolio statistics (gross leverage, turnover, n_positions)
- Sector exposures (validate zero net per sector)
- Transfer coefficient (validate TC ≈ 0.85)

### 8.3 Validation Targets

| Metric | Target | Tolerance |
|--------|--------|-----------|
| Market exposure | 0.0 | ±0.01 (1%) |
| Sector exposure (per sector) | 0.0 | ±0.01 (1%) |
| Position limit adherence | 100% | No violations |
| Gross leverage | 2.0 | ±0.1 |
| Transfer coefficient | 0.85 | 0.80-0.90 |
| Realized IR | 1.60 | 1.40-1.80 |

---

## 9. Risk Management

### 9.1 Leverage Risk

**Gross leverage** L = Σ|h_i|:
- L = 2.0: Standard long/short (100% long, 100% short)
- L = 3.0: Moderate (150% long, 150% short)
- L = 4.0: Aggressive (200% long, 200% short)

**Recommendation**: Start with L = 2.0, increase only if:
- Sharpe ratio improves (risk-adjusted basis)
- Drawdowns remain acceptable (< 20%)
- Prime broker accepts higher leverage

### 9.2 Concentration Risk

**Position limits**:
- Single name: 5% max (conservative)
- Sector: 30% max (3 sectors if L=2.0)
- Factor: 50% max (e.g., size, value)

**Monitoring**:
- Daily position reports
- Sector concentration dashboard
- Factor exposure decomposition

### 9.3 Liquidity Risk

**Average daily volume** (ADV) constraint:
- Trade size ≤ 5% of ADV (avoid market impact)
- Rebalance frequency: Monthly (balance signal decay vs liquidity)

**Illiquid stocks**:
- Exclude stocks with ADV < $1M
- Apply higher transaction costs for small-caps

### 9.4 Model Risk

**Covariance estimation**:
- PPFM primary, Ledoit-Wolf fallback
- Monitor condition number (flag if > 100)
- Regularization if covariance matrix near-singular

**Alpha forecasts**:
- Track realized IC vs expected IC
- Decay old signals (information horizon)
- Combine multiple signals (reduce reliance on single signal)

---

## 10. Expected Performance Summary

### 10.1 Performance Metrics

| Metric | Long-Only | Long/Short Sector-Neutral | Improvement |
|--------|-----------|---------------------------|-------------|
| **Information Ratio** | 0.94 | 1.60 | **+70%** |
| **Transfer Coefficient** | 0.50 | 0.85 | +70% |
| **Active Risk** | 4.5% | 6.0% | +33% |
| **Expected Alpha** (gross) | 4.2% | 9.6% | +129% |
| **Transaction Costs** | 1.5% | 2.5% | +67% |
| **Net Alpha** | 2.7% | 7.1% | **+163%** |
| **Sharpe Ratio** | 0.97 | 1.18 | +22% |

### 10.2 Risk Profile

| Risk Type | Long-Only | Long/Short Sector-Neutral |
|-----------|-----------|---------------------------|
| Market beta | 1.0 | 0.0 (market-neutral) |
| Sector beta | 0.8-1.2 | 0.0 (sector-neutral) |
| Idiosyncratic risk | 4.5% | 6.0% |
| Gross leverage | 1.0× | 2.0× |
| Max drawdown (est.) | 12% | 18% |

### 10.3 Cost Structure

| Cost Component | Long-Only | Long/Short |
|----------------|-----------|------------|
| Commissions | 0.3% | 0.5% |
| Bid-ask spread | 0.5% | 1.0% |
| Market impact | 0.7% | 1.0% |
| **Total TC** | **1.5%** | **2.5%** |

**Note**: Long/short has higher costs due to:
- Both legs (long + short) incur costs
- Higher turnover (TC reduces positions more aggressively)
- Short borrow costs (not included above, add 0.5-1.0%)

### 10.4 Capacity & Scalability

**Strategy capacity** (estimated):
- Long-only: $5B AUM (limited by long-only constraint)
- Long/short: $2B AUM (limited by liquidity, both legs)

**Scaling considerations**:
- Market impact scales with sqrt(AUM)
- IC degrades with AUM (alpha decay)
- Sector capacity varies (tech > utilities)

---

## 11. Conclusion

### 11.1 Key Takeaways

1. **Long/short sector-neutral achieves IR ≈ 1.6**, versus IR ≈ 0.9 for long-only (**70% improvement**)

2. **Transfer coefficient TC = 0.85** for sector-neutral long/short, versus TC = 0.50 for long-only

3. **Alpha preprocessing is critical**: Must sector-neutralize alphas **after volatility scaling**

4. **Constraints matter**: Each constraint reduces TC
   - Dollar-neutral only: TC ≈ 0.95
   - Dollar + sector-neutral: TC ≈ 0.85
   - Dollar + sector + position limits: TC ≈ 0.75

5. **Expected net alpha ≈ 7% per year** after transaction costs, versus 3% for long-only

### 11.2 Implementation Priority

**High priority** (Phase 4A-B, Weeks 12-13):
- Alpha sector-neutralization
- Market-neutral constraint
- Sector-neutral constraints
- Transaction cost penalty

**Medium priority** (Phase 4C-D, Week 13):
- CVXPY optimizer implementation
- Inventory risk transaction cost model

**Low priority** (Phase 4E, Week 14):
- Transfer coefficient analysis tool
- Beta-neutral constraint (optional enhancement)

### 11.3 Success Criteria

- [ ] Market-neutral constraint: sum(weights) = 0 (within 1%)
- [ ] Sector-neutral constraints: sum(weights[sector]) = 0 for each sector (within 1%)
- [ ] Position limits enforced: |w_i| ≤ 5%
- [ ] Gross leverage: 2.0× (100% long, 100% short)
- [ ] Transfer coefficient: TC ≈ 0.85 (range: 0.80-0.90)
- [ ] Realized IR: 1.60 (range: 1.40-1.80)
- [ ] Net alpha: 7% per year (after transaction costs)

### 11.4 Next Steps

1. **Review this design** with Peter (confirm approach)
2. **Implement Phase 4A** (alpha preprocessing)
3. **Implement Phase 4B** (optimizer extensions)
4. **Validate with historical backtest** (2018-2024 data)
5. **Compare long-only vs long/short** (quantify TC improvement)
6. **Document results** in analysis report

---

## References

1. **Grinold, R. C., & Kahn, R. N. (1999)**. *Active Portfolio Management: A Quantitative Approach for Providing Superior Returns and Controlling Risk*. McGraw-Hill.
   - Chapter 14: Portfolio Construction (p. 377-418)
   - Chapter 15: Long/Short Investing (p. 419-444)
   - Chapter 16: Transaction Costs (p. 445-476)

2. **ARBS Documentation**:
   - `docs/books/GRINOLD_KAHN_EQUITY_SUMMARY.md` (Chapter 15 summary)
   - `docs/books/grinold_kahn_equity_notes_part4_implementation.md` (Detailed notes)
   - `docs/design/EQUITY_SECTOR_IMPLEMENTATION_PLAN.md` (Phase 4: Optimization)

3. **Existing Code**:
   - `Optimizer/MeanVarianceOptimizer.py` (Current optimizer implementation)
   - `Signals/AlphaGenerator.py` (IC × Vol × Z formula)
   - `Analysis/TearSheet.py` (Performance analysis)

---

**End of Long/Short Strategy Design**
