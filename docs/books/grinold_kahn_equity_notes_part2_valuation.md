# Part 2: Expected Returns and Valuation - Equity Implementation Notes

**Source**: Grinold & Kahn (1999), Chapters 7-9, Pages 173-260
**Date**: 2025-11-11
**Purpose**: Extract equity-specific insights for ARBS sector portfolio extension

---

## Chapter 7: Arbitrage Pricing Theory (APT)

### Core APT Theory

**Main Result**: Expected excess returns are determined by factor exposures:
```
E{r_n} = Σ_k X_{n,k} · m_k                    (Eq 7.2)
```
where:
- `X_{n,k}` = exposure of stock n to factor k (known at t=0)
- `m_k` = factor forecast for factor k (the hard part!)
- Factors can be fundamental, technical, or macro

**APT vs CAPM**:
- CAPM: Single factor (market beta), E{r_n} = β_n · f_M
- APT: Multiple factors, more flexible
- CAPM is special case of APT with K=1, X_{n,1} = β_n

**Key Insight**: APT is "arbitrary" - doesn't specify:
1. What the factors are
2. How to calculate exposures X_{n,k}
3. What factor forecasts m_k should be

This flexibility is both strength (can use domain knowledge) and weakness (no recipe).

### Factor Model Structure

**Returns decomposition**:
```
r_n = Σ_k X_{n,k} · b_k + u_n                 (Eq 7.1)
```
where:
- `b_k` = factor return (realized)
- `u_n` = specific (idiosyncratic) return

**Covariance structure**:
```
V = X · F · X^T + Δ
```
where:
- `V` = N×N asset covariance matrix
- `X` = N×K factor exposure matrix
- `F` = K×K factor covariance matrix
- `Δ` = N×N diagonal specific risk matrix

### Qualified APT Models

**Technical requirement** (Proposition 1, Appendix):
A factor model is "qualified" if portfolio Q (max Sharpe ratio) is **diversified** with respect to the factor model.

**Practical guideline** (Table 7.3):
- Any factor model that explains 99%+ of risk in diversified portfolios qualifies
- BARRA U.S. Equity model: 99.82% for Russell 3000 (only 0.18% unexplained)
- **Implication**: Many reasonable factor models will work!

**Example**: S&P 500 vs MMI (20 stocks)
- S&P 500: 99.7% variance explained
- MMI: 97.5% variance explained
- Both qualify as APT models

### Factor Types and Examples

#### Structural Model 1: Given Exposures, Estimate Factor Returns (BARRA-style)

**Example factors** (Table 7.1, Major Market Index Dec 1992):
1. **Earnings Growth**: IBES consensus + realized growth (standardized)
2. **Bond Beta**: Sensitivity to government bond returns
3. **Size**: log(market capitalization), standardized
4. **Return on Equity**: earnings/book, standardized
5. **Industry**: Chemical, Energy, Financial Services, etc.

**Standardization**: For comparability across factors:
```
X_{n,k} = [Raw_k - μ_k] / σ_k
```
- Average exposure = 0
- ~66% of stocks have exposures in [-1, +1]
- ~95% have exposures in [-2, +2]

**Factor forecasts example** (Dec 1992):
- Growth: m_growth = +2.0% (growth stocks outperform)
- Bond beta: m_bond = +2.5% (rate-sensitive stocks do well)
- Size: m_size = -1.5% (small stocks outperform)
- ROE: m_ROE = 0.0% (neutral)
- Chemical industry: m_chem = +8.0%

**APT forecast for stock n**:
```
E{r_n} = Σ_k X_{n,k} · m_k + industry_forecast
```

**Example**: Dow Chemical
- Exposures: growth=-0.64, bond=-0.92, size=0.48, ROE=0.22
- Industry: Chemical
- APT forecast: (-0.64)(2.0) + (-0.92)(2.5) + (0.48)(-1.5) + (0.22)(0.0) + 8.0 = 3.70%
- vs CAPM forecast: β·f_M = 6.78%
- Residual APT alpha: 3.70% - 6.78% = -3.08%

#### Structural Model 2: Given Factor Returns, Estimate Exposures

**Factor returns**: Observable market data
- NYSE value-weighted index (set X_{n,NYSE} = 1 for all)
- Gold index
- Government bond index
- Foreign currency basket
- Commodity basket

**Estimation**: Time-series regression
```
r_n(t) - r_NYSE(t) = Σ_k X_{n,k} · b_k(t) + ε_n(t)
```
Regression coefficients = factor exposures X_{n,k}

**Assumption**: Exposures stable over time (can forecast future using historical regression)

#### Statistical Model 1: Principal Components Analysis

**Procedure**:
1. Observe N stocks over T months (e.g., 500 stocks × 200 months)
2. Calculate N×N covariance matrix
3. Extract K principal components (typically K=10-20 explains 90%+ variance)
4. PC returns = factors b_k
5. PC loadings = exposures X_{n,k}

**Limitation**: Factors are abstract ("Dick", "Jane", "Spot")
- Hard to forecast m_k (only option: historical average)
- No economic intuition

### Factor Forecasts: The Hard Part

**Challenge**: Need 10× more skill to forecast 10 factors vs 1000 stocks for same IR!
- Fundamental Law: IR = IC × √BR
- 10 factors: need IC_factor
- 1000 stocks: need IC_stock
- Same IR requires: IC_factor = 10 · IC_stock

**Approaches**:

1. **Historical average**: m_k = average of past factor returns b_k(t)
   - Assumes stationarity
   - Haugen-Baker (1996): 12-month trailing average
   - Works if factor relationships stable

2. **Economic intuition** (for structural models):
   - Bond beta → forecast interest rates
   - Growth factor → outlook for growth stocks
   - Sector factors → sector rotation strategy
   - **Key**: Link factors to forecastable quantities

3. **Opportunistic approach**:
   - Start with factors you CAN forecast (e.g., interest rates, commodities)
   - Add industry factors to capture residual risk
   - "Build from strengths"

### Implications for Active Management

**APT flexibility = opportunity**:
- CAPM: single consensus expected return (no alpha possible if everyone agrees)
- APT: multiple factors → multiple forecasts → independent sources of alpha
- Different managers can have different factor forecasts

**Additivity** (from Ch 6, Fundamental Law):
```
IR_total^2 = Σ_k IR_k^2
```
Can combine:
- Stock selection within sectors
- Sector rotation
- Market timing
- Currency (for international)

**Investment style**: APT encourages eclectic approach
- Use any independent information source
- Don't limit to single style (growth, value, etc.)

---

## Chapter 8: Valuation in Theory

### Modern Valuation Theory

**Central premise**: Stock value = expected future cash flows, risk-adjusted

**Certain cash flows** (bonds):
```
p(0) = Σ_t cf(t) / (1 + i_F)^t              (Eq 8.1)
```

**Uncertain cash flows** (stocks):
Cannot simply use E{cf(t)} - this **overvalues** the stock!
Need risk adjustment.

### Risk-Adjusted Expectations

**Valuation formula**:
```
p(0) = Σ_t E*{cf(t)} / (1 + i_F)^t          (Eq 8.9)
```
where E* is risk-adjusted expectation.

**Risk adjustment via value multipliers**:
```
E*{cf(t)} = Σ_s π(t,s) · υ(t,s) · cf(t,s)
```
where:
- `π(t,s)` = true probability of state s at time t
- `υ(t,s)` = value multiplier (risk adjustment)
- `π*(t,s) = π(t,s) · υ(t,s)` = risk-adjusted probability

**Properties of υ(t,s)**:
- υ(t,s) > 0 (positive)
- E{υ(t)} = 1 (unbiased on average)
- Proportional to return on portfolio S (min 2nd moment portfolio)
- Function of portfolio Q return (max Sharpe ratio)

**Covariance interpretation**:
```
E*{cf(t)} = E{cf(t)} + Cov{cf(t), υ(t)}     (Eq 8.13)
```
Covariance term is typically **negative** → reduces value below expectation

**Example** (p.206):
- Stock: p(0) = 50
- Outcomes: cf(1/12,1) = 49 (prob 0.5), cf(1/12,2) = 53 (prob 0.5)
- E{cf} = 51
- Risk-free rate: i_F = 6% annual
- Value multipliers: υ(1) = 1.38, υ(2) = 0.62
- Risk-adjusted probs: π*(1) = 0.69, π*(2) = 0.31
- E*{cf} = 0.69×49 + 0.31×53 = 50.24
- p(0) = 50.24 / 1.00487 = 50 ✓

**Intuition**: 
- υ(t,s) > 1 in bad states (market down) → amplify bad-state cash flows
- υ(t,s) < 1 in good states (market up) → discount good-state cash flows
- Marginal dollar worth more when cash flows scarce

### Connection to CAPM and APT

**Portfolio Q** (from Ch 2,7):
- Fully invested portfolio with max Sharpe ratio: (E{r_Q} / σ_Q)
- For CAPM: Q = market portfolio
- For APT: Q exists if any qualified factor model exists

**Value multiplier formula** (Proposition 2, p.219):
```
υ = 1 - κ_Q · (r_Q - f_Q)                   (Eq 8A.26)
```
where:
- `κ_Q = 1 / (1 + i_F + f_Q)` ≈ 1 / (1.06 + 0.06) ≈ 0.89
- `r_Q` = excess return on portfolio Q
- `f_Q` = expected excess return on Q

**Reasonable values**: κ_Q ∈ [1.5, 2.0]
- If κ_Q = 1.75, then υ < 0 only if r_Q > f_Q + 0.57
- For f_Q = 6% annual, need r_Q > 63% (>3σ event, very rare)

**Expected return formula** (p.208):
```
E{r} = i_F + Cov{R, υ} / Var{υ}             (Eq 8.16)
```
This is equivalent to CAPM/APT!

**Risk-neutral pricing** (p.214):
Under risk-adjusted probabilities π*, all stocks have expected return = i_F:
```
E*{R} = 1 + i_F
```

### Valuation and Misvaluation

**If market price ≠ fair value**:

Define:
```
κ = [p(0,fitted) - p(0,market)] / p(0,market)     (Eq 8.19)
γ = persistence parameter ∈ [0,1]                   (Eq 8.20)
```

Then:
```
α = (1 - γ)(1 + i_F) · κ                           (Eq 8.22)
```

**Interpretation**:
- `κ` = % mispricing (positive = undervalued)
- `γ` = 0: "fast idea" - mispricing disappears immediately
- `γ` = 1: "slow idea" - mispricing persists forever (α=0, no benefit!)
- Half-life of mispricing: τ = -0.69 / ln(γ) years

**Table 8.1: Alphas for different (κ, γ) combinations** (i_F = 6%):

| κ ↓ \ γ → | 0.0    | 0.2    | 0.4    | 0.6    | 0.8    |
|-----------|--------|--------|--------|--------|--------|
| 1%        | 1.06%  | 0.85%  | 0.63%  | 0.42%  | 0.21%  |
| 5%        | 5.30%  | 4.20%  | 3.12%  | 2.06%  | 1.02%  |
| 10%       | 10.60% | 8.31%  | 6.12%  | 4.00%  | 1.96%  |
| 25%       | 26.50% | 20.19% | 14.45% | 9.22%  | 4.42%  |
| 50%       | 53.00% | 38.55% | 26.50% | 16.31% | 7.57%  |

**Example**: 10% undervalued stock, half-life 2 years
- γ = exp(-0.69/2) = 0.71
- α = (1-0.71)(1.06)(0.10) = 3.07%

---

## Chapter 9: Valuation in Practice

### Modigliani-Miller Principles (Corporate Finance Foundation)

**Key results** (Nobel Prize-winning):
1. **Dividend policy irrelevant**: "Pay now or pay later" - scheduling doesn't affect total value
2. **Financing policy irrelevant**: Debt vs equity mix doesn't affect total firm value (ignoring taxes)

**Implication**: Value created by **operations**, not financial engineering

**Firm decomposition**:
```
Equity Value = Operational Value + Financial Value
```
where:
- Operational value = PV of operating cash flows (revenue - costs - capex)
- Financial value = capital surplus - debt

**Warning**: Accounting data (EPS, book, ratios) can be manipulated via dividend/debt policy!

### Dividend Discount Model (DDM)

#### Basic Theory

**Williams (1938)**: Stock value = PV of future dividends
```
p(0) = Σ_t d(t) / (1 + i_F)^t               (Eq 9.3)
```

**Constant-growth model** (Gordon-Shapiro):
```
p(0) = d(1) / (y - g)                        (Eq 9.5)
```
where:
- `d(1)` = next year's dividend
- `y` = required return = i_F + β·f_B (equity cost of capital)
- `g` = constant growth rate

**Alternative derivation**: Total return split
```
R = d/p + ξ                                  (Eq 9.6)
```
where:
- `d/p` = dividend yield
- `ξ` = capital appreciation (uncertain)
- `g = E{ξ}` = expected capital appreciation

Taking expectations:
```
i_F + f = d/p + g
```
Solving for p:
```
p = d / (i_F + f - g)                        (Eq 9.8)
```

#### Growth Modeling

**Reinvestment model**:
```
e(t+1) = e(t) + ρ · I(t)                     (Eq 9.12)
```
where:
- `e(t)` = earnings at time t
- `I(t) = (1-κ)·e(t)` = reinvested earnings
- `κ` = payout ratio
- `ρ` = return on reinvested capital (ROE)

**Growth rate**:
```
g = (1 - κ) · ρ                              (Eq 9.14)
```

**Connection to ROE**:
If b(t) = book value, and e(t) = ρ·b(t-1), then:
- Book grows at rate g
- ρ = ROE = e(t) / b(t-1)

#### DDM-Based Alphas

**From excess return decomposition**:
```
α = d/p + g - β·f_B                          (Eq 9.19)
```

**Golden Rule of DDM**: "g in, g out"
- Each 1% increase in g adds 1% to α
- Alphas are ONLY as good as growth forecasts!
- Garbage in → garbage out

**Implied growth rate** (assumes α = 0):
```
g_implied = i_F + β·f_B - d/p                (Eq 9.20)
```

#### Example: Major Market Index (Dec 1992, Table 9.1)

Parameters: i_F = 3.1%, f_B = 6%

| Stock          | Yield | Beta | g_implied |
|----------------|-------|------|-----------|
| Disney         | 0.5%  | 1.24 | 10.04%    |
| Coca-Cola      | 1.3%  | 1.00 | 7.80%     |
| GE             | 2.9%  | 1.31 | 8.06%     |
| Exxon          | 4.7%  | 0.47 | 1.22%     |
| Chevron        | 4.7%  | 0.45 | 1.10%     |
| IBM            | 9.6%  | 0.64 | **-2.66%** |

**Observations**:
- High-growth stocks (Disney, tech): low yield, high β → high g_implied
- Mature stocks (Exxon, Chevron): high yield, low β → low g_implied
- IBM: very high yield → negative implied growth (distressed)

#### Dealing with Unrealistic Growth Forecasts

**Problem**: Analyst growth forecasts often too optimistic (Wall Street bullishness)

**Solution 1: Sector Normalization** (Eq 9.22):
```
g_modified = g_implied,sector + (σ_implied,sector / σ_forecast,sector) · (g_forecast - μ_forecast,sector)
```

**Procedure**:
1. Group stocks by sector
2. Calculate implied growth rates g_implied for each stock
3. Calculate μ_implied, σ_implied within sector
4. Calculate μ_forecast, σ_forecast from analyst estimates
5. Transform: scale to match implied moments

**Example: MMI Stocks** (Table 9.2, 5-year historical EPS growth):

| Stock          | Raw g  | Modified g | Alpha  |
|----------------|--------|------------|--------|
| AT&T           | -19.2% | 2.21%      | -4.05% |
| Eastman Kodak  | -37.5% | -0.86%     | -2.66% |
| Merck          | +23.0% | 9.30%      | +1.96% |
| P&G            | +23.3% | 9.35%      | +2.29% |
| Philip Morris  | +22.9% | 9.29%      | +3.77% |

Result: μ = 5.54%, σ = 3.09% (vs raw: μ = 0.58%, σ = 18.4%)

**Caveat**: May remove sector timing information (pushes sector alphas to 0)

**Solution 2: Skill-Based Adjustment** (from Ch 10):
```
g_modified = g_implied + c · (g_forecast - g_implied)
```
where c ∝ IC (information coefficient of growth forecasts)
- High IC → large c → trust forecast more
- Low IC → small c → stick close to implied

**Solution 3: Three-Stage DDM**:
- Stage 1 (0 → T1): Use analyst forecast g_IN
- Stage 2 (T1 → T2): Linear interpolation
- Stage 3 (T2+): Use equilibrium growth g_EQ

**Three-stage formula**:
```
g(t) = g_IN + (t - T1) · (g_EQ - g_IN) / (T2 - T1)   for T1 ≤ t ≤ T2
κ(t) = κ_0 + (t - T1) · (κ_EQ - κ_0) / (T2 - T1)     for T1 ≤ t ≤ T2

EPS(t) = EPS(1) · Π_{s=1}^{t-1} [1 + g(s)]
d(t) = κ(t) · EPS(t)

p(T2) = d(T2+1) / (y_EQ - g_EQ)
p(0) = [Σ_{t=1}^{T2} d(t)/(1+y)^t] + p(T2)/(1+y)^T2
```

**Reality check** (Fig 9.3, 9.4):
- α ≈ 0.54 · (g_IN - 12.62%)
- α ≈ 0.30 per $0.20 in EPS forecast
- Golden rule still applies! (just dampened by equilibrium assumption)

#### Converting DDM to Alpha Forecasts

**Mode 1: Internal Rate of Return** (assumes persistent mispricing):
```
α_n = y_n - i_F - β_n · f_B                  (Eq 9.27)
```
where y_n = IRR solving:
```
p(0) = Σ_t d_n(t) / (1 + y_n)^t
```

**Interpretation**: Misvaluation persists → continue earning excess return

**Mode 2: Net Present Value** (assumes mispricing disappears in 1 year):
```
α_n ≈ [p_fitted - p_market] / p_market       (Eq 9.34)
```
where p_fitted = fair value using y_n = i_F + β_n · f_B

**Interpretation**: Market corrects to fair value within horizon

**Choice**: Depends on horizon and belief about market efficiency
- Fast ideas: Use NPV mode (γ ≈ 0)
- Slow ideas: Use IRR mode (γ closer to 1)

### Comparative Valuation

#### Motivation from Accounting

**Clean surplus equation**:
```
b(t) = b(t-1) + e(t) - d(t)                  (Eq 9.37)
```

**Exceptional earnings**:
```
e*(t) = e(t) - y · b(t-1)                    (Eq 9.38)
```

**Persistence**:
```
e*(t+1) = δ · e*(t),  δ < 1                  (Eq 9.39)
```

**Result** (Ohlson 1989):
```
p(0) = b(0) + Σ_t δ^t · e*(1) / (1+y)^t
     = [1/(1-δ)] · e(1)/(1+y) + [1 - y/((1-δ)(1+y))] · b(0)   (Eq 9.41)
```

**Simplified**: Price is linear combination of earnings and book!

#### General Approach

**Cross-sectional regression**:
```
p_n = Σ_k c_k · A_{n,k} + ε_n               (Eq 9.43)
```
where A_{n,k} = attributes:
- Earnings (forward, trailing)
- Book value
- Sales
- Cash flow
- Dividends
- Debt
- etc.

**Alpha forecast**:
```
α_n ≈ [p_fitted - p_market] / p_market       (Eq 9.44)
```

**Arbitrage interpretation**:
- Group 1: Overvalued (p_market > p_fitted)
- Group 2: Undervalued (p_market < p_fitted)
- Construct portfolios with identical attributes
- OV and UV are "identical" but priced differently → arbitrage!

#### Implementation

**Sector-by-sector**:
Fit separate models for:
- Banks (use loans, deposits, credit quality)
- Utilities (use rate base, allowed ROE)
- Industrials (use sales, margins, capex)
- Mining (use reserves, commodity prices)

**Pooled regression**:
- Cross-sectional + time-series
- More data, assumes coefficients stable over time

**GLS vs OLS**:
- GLS: Weight by market cap
- OLS: Equal weight
- Both work; GLS reduces small-stock influence

**Warnings**:
1. **Missing factors**: If omit important attribute (e.g., brand value), may identify as mispricing
2. **Time-varying**: Coefficients may drift → need to re-estimate frequently
3. **Outliers**: Pull in extremes to ±3σ

### Returns-Based Analysis

#### Direct Approach

**Residual return model**:
```
θ_n(t) = Σ_k A_{n,k}(t-1) · b_k(t) + ε_n(t)  (Eq 9.45)
```

**Ensure benchmark-neutral**:
```
A_n,k = Z_n,k - β_n · Z_B,k
```
Then Σ_n w_{B,n} · A_n,k = 0

**Excess return model** (APT-like):
```
r_n(t) = Σ_k X_{n,k}(t-1) · b_k(t) + u_n(t)  (Eq 9.46)
```
where X includes:
- Attributes (value, growth, momentum, quality)
- Risk controls (beta, sector, size)

#### Signal Types

**Type 1: Consistent signals** (always expect b_k > 0):
- Momentum: 12-month return
- Earnings surprise: (actual - consensus) / price
- Low P/E, low P/B (value)
- DDM alpha forecasts

**Type 2: Thematic signals** (forecast sign and magnitude of b_k):
- Growth vs value
- Small vs large cap
- Sector rotation
- Interest rate sensitivity

**Example**: BARRA Success factor (momentum)
- Usually b_success > 0
- Except January: b_success < 0 (tax-loss selling, window dressing)
- Need to forecast factor return, not just assume positive

#### Risk Control

**Problem**: Need to separate benchmark from residual returns

**Approach 1: Beta factor**:
```
r_n(t) = β_n · b_beta(t) + Σ_k A_n,k · b_k(t) + ε_n(t)
```
where:
- b_beta picks up benchmark return
- Other factors benchmark-neutral

**Approach 2: Sector/industry factors**:
```
r_n(t) = Σ_j S_{n,j} · b_j(t) + Σ_k A_n,k · b_k(t) + ε_n(t)
```
where:
- S_{n,j} = 1 if stock n in sector j, else 0
- Sector returns absorb benchmark
- Attributes adjusted: A_n,k = Z_n,k - β_n · Z_B,k

**Aggregation property** (Eq 9.47):
```
r_B(t) = Σ_k X_B,k · b_k(t)
```
Ensures consistency: benchmark return explained by model

#### Factor Portfolios

**In GLS regression**: b_k(t) = return on factor portfolio with:
- Unit exposure to factor k: X_{P,k} = 1
- Zero exposure to other factors: X_{P,j} = 0 for j ≠ k
- Minimum variance

**Tradeable**: Can construct this portfolio at start of period using exposures X_n,k(t-1)

#### Popular Equity Factors (Merrill Lynch Survey)

From practitioner surveys, commonly used factors include:

**Valuation**:
- P/E ratio (low = value)
- P/B ratio
- P/S ratio
- P/CF ratio
- Dividend yield

**Quality**:
- ROE (return on equity)
- Debt/equity ratio
- EPS variability (low = stable)

**Growth**:
- Projected EPS growth
- Historical EPS growth
- Sales growth

**Momentum**:
- Relative strength (6-12 month return)
- EPS momentum
- Earnings estimate revisions

**Earnings**:
- EPS surprise (actual vs consensus)
- EPS torpedo (large negative surprise)
- Estimate dispersion (disagreement)
- Rating revisions (upgrades/downgrades)

**Other**:
- Size (market cap)
- Beta
- Duration (interest rate sensitivity)
- Neglect (analyst coverage)
- Foreign exposure
- Low price

**Typical portfolio**: 5-7 factors combined

---

## Application to ARBS

### Current ARBS Architecture

```
Query Layer:      FuturesQuery → MockFuture objects
        ↓
Adapter Layer:    FuturesAdapter → DataFrame (returns, metadata)
        ↓
Returns:          ReturnsCalculator → standardized returns matrix
        ↓
Volatility:       VolatilityEstimator → volatility forecasts
        ↓
Signals:          CarrySignal, MomentumSignal, etc. → raw signals (z-scores)
        ↓
Alpha:            AlphaGenerator → scaled alphas (IC × Vol × Z)
        ↓
Risk:             LedoitWolfShrinkage → covariance matrix Σ
        ↓
Optimizer:        MeanVarianceOptimizer → portfolio weights
        ↓
Portfolio:        Portfolio(returns) → composite asset
        ↓
Analysis:         TearSheet → IC/Sharpe/returns analysis
```

### Extensions for Equities

#### 1. Enhanced Signals Layer

**New signal types needed**:

```python
# Valuation-based signals
class DDMSignal(BaseSignal):
    """Dividend discount model alpha: α = d/p + g - β·f_B"""
    pass

class ComparativeValuationSignal(BaseSignal):
    """Cross-sectional regression: α = (p_fitted - p_market) / p_market"""
    pass

# Fundamental signals
class ValueSignal(BaseSignal):
    """Low P/E, P/B, P/S → positive alpha"""
    pass

class QualitySignal(BaseSignal):
    """High ROE, low debt, stable earnings → positive alpha"""
    pass

class GrowthSignal(BaseSignal):
    """EPS growth, sales growth → positive alpha"""
    pass

# Earnings signals
class EarningsSurpriseSignal(BaseSignal):
    """(Actual - consensus) / price → alpha"""
    pass

class EstimateRevisionSignal(BaseSignal):
    """Change in analyst estimates → alpha"""
    pass

# Multi-factor signals (APT-style)
class FactorSignal(BaseSignal):
    """Linear combination: α = Σ_k X_{n,k} · m_k"""
    pass
```

**Signal combination**:
```python
class SignalCombiner:
    """Combine multiple signals weighted by IC_k"""
    
    def combine(self, signals: List[BaseSignal], weights: List[float]) -> DataFrame:
        # α_combined = Σ_k IC_k · α_k / Σ_k IC_k
        alphas = [sig.calculate() for sig in signals]
        return np.average(alphas, weights=weights, axis=0)
```

#### 2. Factor Models in Risk Layer

**Current**: Returns-based covariance
- SampleCovariance
- LedoitWolfShrinkage

**Add**: Factor-based covariance (APT structure)

```python
class FactorCovariance:
    """
    APT-style covariance: V = X · F · X^T + Δ
    
    where:
    - X: N × K factor exposure matrix
    - F: K × K factor covariance
    - Δ: N × N diagonal specific risk
    """
    
    def __init__(self, factors: List[str]):
        """
        factors: ['sector_energy', 'sector_tech', 'value', 'growth', 'size', 'momentum']
        """
        self.factors = factors
    
    def calculate(self, exposures: DataFrame, returns: DataFrame) -> np.ndarray:
        """
        Args:
            exposures: N × K, factor exposures at start of period
            returns: N × T, historical returns
        
        Returns:
            V: N × N covariance matrix
        """
        # Estimate factor covariance F from historical factor returns
        F = self._estimate_factor_covariance(returns, exposures)
        
        # Estimate specific risk Δ from residuals
        delta = self._estimate_specific_risk(returns, exposures, F)
        
        # V = X @ F @ X.T + diag(delta)
        X = exposures.values
        return X @ F @ X.T + np.diag(delta)
    
    def _estimate_factor_covariance(self, returns, exposures):
        """
        For each period t:
        1. Regress returns on exposures → factor returns b(t)
        2. Cov{b(t)} = F
        """
        # GLS regression to get factor returns
        factor_returns = []
        for t in range(returns.shape[1]):
            r_t = returns.iloc[:, t]
            X_t = exposures.iloc[:, :]
            # b(t) = (X^T X)^{-1} X^T r(t)
            b_t = np.linalg.lstsq(X_t, r_t, rcond=None)[0]
            factor_returns.append(b_t)
        
        factor_returns = np.array(factor_returns)
        F = np.cov(factor_returns, rowvar=False)
        return F
    
    def _estimate_specific_risk(self, returns, exposures, F):
        """
        Specific return: u(t) = r(t) - X · b(t)
        Specific risk: Δ = diag(Var{u})
        """
        # Calculate factor returns for each period
        factor_returns = []
        for t in range(returns.shape[1]):
            r_t = returns.iloc[:, t]
            X_t = exposures.iloc[:, :]
            b_t = np.linalg.lstsq(X_t, r_t, rcond=None)[0]
            factor_returns.append(b_t)
        
        factor_returns = np.array(factor_returns)
        
        # Calculate specific returns
        X = exposures.values
        specific_returns = returns.values - X @ factor_returns.T
        
        # Diagonal specific variance
        delta = np.var(specific_returns, axis=1)
        return delta
```

**Hybrid approach** (combine factor + Ledoit-Wolf):
```python
class HybridCovariance:
    """
    Factor model with shrinkage:
    V = λ · (X F X^T + Δ) + (1-λ) · V_sample
    """
    pass
```

#### 3. Expected Returns Construction

**APT approach**:
```python
class APTExpectedReturns:
    """
    Construct expected returns from factor exposures and forecasts
    E{r_n} = Σ_k X_{n,k} · m_k
    """
    
    def __init__(self, factor_forecasts: Dict[str, float]):
        """
        factor_forecasts: {
            'sector_energy': 0.05,
            'sector_tech': 0.08,
            'value': 0.03,
            'growth': 0.02,
            'size': -0.01,
            'momentum': 0.04
        }
        """
        self.factor_forecasts = factor_forecasts
    
    def calculate(self, exposures: DataFrame) -> Series:
        """
        Args:
            exposures: N × K factor exposures
        
        Returns:
            expected_returns: N × 1
        """
        m = np.array([self.factor_forecasts[f] for f in exposures.columns])
        X = exposures.values
        expected_returns = X @ m
        return pd.Series(expected_returns, index=exposures.index)
```

**Factor forecast sources**:
1. Historical average: `m_k = mean(b_k(t))`
2. Macro model: Link to interest rates, GDP, inflation
3. Extrapolation: Moving average, EWMA
4. Market timing: Forecast based on indicators

#### 4. Valuation-Based Alpha Generation

**Integrate DDM with existing alpha framework**:

```python
class ValuationAlphaGenerator:
    """
    Generate alphas from valuation models (DDM, comparative)
    """
    
    def calculate_ddm_alpha(self, data: DataFrame) -> Series:
        """
        α = d/p + g - β·f_B
        
        Args:
            data: DataFrame with columns:
                - dividend_yield (d/p)
                - growth_forecast (g)
                - beta
                - market_premium (f_B)
        
        Returns:
            alpha: Series of DDM alphas
        """
        alpha = (
            data['dividend_yield'] + 
            data['growth_forecast'] - 
            data['beta'] * data['market_premium']
        )
        return alpha
    
    def calculate_comparative_alpha(self, data: DataFrame, sector: str) -> Series:
        """
        Cross-sectional regression within sector
        α = (p_fitted - p_market) / p_market
        
        Args:
            data: DataFrame with:
                - price
                - earnings
                - book_value
                - sales
                - cash_flow
        
        Returns:
            alpha: Series of comparative valuation alphas
        """
        # Fit regression: price ~ c1*earnings + c2*book + c3*sales + c4*cf
        sector_data = data[data['sector'] == sector]
        
        X = sector_data[['earnings', 'book_value', 'sales', 'cash_flow']]
        y = sector_data['price']
        
        # OLS regression
        from sklearn.linear_model import LinearRegression
        model = LinearRegression()
        model.fit(X, y)
        
        # Fitted prices
        p_fitted = model.predict(X)
        p_market = sector_data['price'].values
        
        # Alpha = pricing error
        alpha = (p_fitted - p_market) / p_market
        
        return pd.Series(alpha, index=sector_data.index)
    
    def blend_alphas(self, ddm_alpha: Series, comp_alpha: Series, 
                     ic_ddm: float, ic_comp: float) -> Series:
        """
        Combine DDM and comparative alphas weighted by IC
        α = (ic_ddm · α_ddm + ic_comp · α_comp) / (ic_ddm + ic_comp)
        """
        total_ic = ic_ddm + ic_comp
        blended = (ic_ddm * ddm_alpha + ic_comp * comp_alpha) / total_ic
        return blended
```

**Integration with Grinold-Kahn alpha scaling**:
```python
# Current ARBS approach
alpha = IC * volatility * z_score

# With valuation signals
alpha_valuation = ValuationAlphaGenerator().calculate()
alpha_momentum = MomentumSignal().calculate()
alpha_carry = CarrySignal().calculate()

# Blend using IC weights
alpha_combined = (
    IC_val * alpha_valuation +
    IC_mom * alpha_momentum +
    IC_car * alpha_carry
) / (IC_val + IC_mom + IC_car)

# Final scaling
alpha_final = volatility * alpha_combined
```

#### 5. Data Requirements

**For Yahoo Finance integration** (via `yfinance`):

```python
import yfinance as yf

# Price and return data
ticker = yf.Ticker("AAPL")
hist = ticker.history(period="5y")  # OHLCV data

# Fundamental data
info = ticker.info
dividend_yield = info['dividendYield']  # Annual dividend yield
beta = info['beta']  # 5-year monthly beta
market_cap = info['marketCap']  # Size factor
pe_ratio = info['trailingPE']  # Valuation
pb_ratio = info['priceToBook']
roe = info['returnOnEquity']  # Quality
debt_to_equity = info['debtToEquity']

# Analyst estimates (for growth)
estimates = ticker.analyst_price_target
growth_estimates = ticker.earnings_estimates

# Sector classification
sector = info['sector']  # GICS sector (11 sectors)
industry = info['industry']  # GICS industry (24 groups)
```

**Data pipeline**:
```python
class EquityDataAdapter:
    """
    Adapt Yahoo Finance data to ARBS format
    """
    
    def fetch_data(self, tickers: List[str]) -> DataFrame:
        """
        Fetch all required data for equity backtesting
        """
        data = []
        for ticker in tickers:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period="5y")
            
            # Calculate returns
            returns = hist['Close'].pct_change()
            
            # Fundamental data
            data.append({
                'ticker': ticker,
                'returns': returns,
                'price': info.get('currentPrice'),
                'dividend_yield': info.get('dividendYield', 0),
                'beta': info.get('beta', 1.0),
                'market_cap': info.get('marketCap'),
                'pe_ratio': info.get('trailingPE'),
                'pb_ratio': info.get('priceToBook'),
                'roe': info.get('returnOnEquity'),
                'sector': info.get('sector'),
                'industry': info.get('industry')
            })
        
        return pd.DataFrame(data)
    
    def calculate_factor_exposures(self, data: DataFrame) -> DataFrame:
        """
        Convert raw data to factor exposures (standardized)
        """
        exposures = {}
        
        # Sector exposures (dummy variables)
        sectors = pd.get_dummies(data['sector'], prefix='sector')
        exposures.update(sectors.to_dict('list'))
        
        # Style factors (standardized)
        for factor in ['pe_ratio', 'pb_ratio', 'roe', 'market_cap']:
            if factor in data.columns:
                # Standardize: (x - μ) / σ
                mean = data[factor].mean()
                std = data[factor].std()
                exposures[factor] = [(x - mean) / std for x in data[factor]]
        
        return pd.DataFrame(exposures, index=data['ticker'])
```

### Link to PPFM Paper (Multi-Sector Portfolio Optimization)

**PPFM paper**: "Portfolio optimization with sector-specific covariance matrices"
- Motivated by different correlation structures across sectors
- Sector covariance: V_sector = within-sector correlation higher than cross-sector

**Connection to APT**:
- APT factors = sectors + styles (value, growth, size, etc.)
- Factor covariance F captures sector-sector correlations
- Specific risk Δ captures stock-stock correlations within sector

**PPFM structure**:
```
V = Σ_s Σ_t Cov(sector_s, sector_t) + within-sector covariance
```

**APT structure**:
```
V = X_sectors · F_sectors · X_sectors^T  +  X_styles · F_styles · X_styles^T  +  Δ
    └─────────── sector component ──────┘    └────── style component ──────┘    └─ specific ─┘
```

**Implementation**:
```python
class MultiSectorCovariance:
    """
    PPFM-style covariance with sector structure
    """
    
    def __init__(self, sectors: List[str]):
        self.sectors = sectors
    
    def calculate(self, returns: DataFrame, sector_map: Dict) -> np.ndarray:
        """
        Two-level covariance:
        1. Between-sector: F_sectors (K_s × K_s)
        2. Within-sector: Δ_sector (diagonal or small blocks)
        """
        # Partition stocks by sector
        sector_returns = {}
        for sector in self.sectors:
            tickers = [t for t, s in sector_map.items() if s == sector]
            sector_returns[sector] = returns[tickers]
        
        # Calculate sector-level returns (equal-weighted or cap-weighted)
        sector_level_returns = pd.DataFrame({
            s: r.mean(axis=1) for s, r in sector_returns.items()
        })
        
        # Between-sector covariance
        F_sectors = sector_level_returns.cov()
        
        # Within-sector covariance (residual)
        delta = {}
        for sector, r in sector_returns.items():
            sector_mean = sector_level_returns[sector]
            residuals = r.sub(sector_mean, axis=0)
            delta[sector] = residuals.cov()
        
        # Assemble full covariance
        # V[i,j] = F_sectors[s_i, s_j] if s_i != s_j
        #        = F_sectors[s_i, s_i] + Δ_s_i[i,j] if s_i == s_j
        
        # (Implementation details omitted for brevity)
        return V
```

### Implementation Roadmap

**Phase 1: Single-Stock DDM Signal** (1-2 weeks)
- Implement `DDMSignal` class
- Data: dividend yield, beta, growth forecast from Yahoo Finance
- Alpha: α = d/p + g - β·f_B
- Test on small universe (e.g., 50 stocks)
- Measure IC vs realized returns

**Phase 2: Comparative Valuation Signal** (2-3 weeks)
- Implement `ComparativeValuationSignal`
- Sector-by-sector cross-sectional regression
- Attributes: earnings, book, sales, cash flow
- Alpha: (p_fitted - p_market) / p_market
- Test on 100-200 stocks across multiple sectors

**Phase 3: Factor-Based Risk Model** (3-4 weeks)
- Implement `FactorCovariance` class
- Factor definitions: 11 GICS sectors + 4 style factors
  - Sectors: Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, 
    Healthcare, Financials, IT, Telecom, Utilities, Real Estate
  - Styles: Value (low P/B), Growth (high EPS growth), Momentum (12m return), Size (log cap)
- Covariance: V = X · F · X^T + Δ
- Compare to Ledoit-Wolf (returns-based)

**Phase 4: Multi-Signal Integration** (2-3 weeks)
- Combine DDM + Comparative + Momentum signals
- Weight by IC: α_combined = Σ_k IC_k · α_k / Σ_k IC_k
- Test signal complementarity (correlation of signals)
- Optimize signal weights via cross-validation

**Phase 5: Sector Optimization** (2-3 weeks)
- Integrate with PPFM paper methodology
- Sector-level allocation + stock selection within sectors
- Hierarchical optimization:
  1. Sector weights (top-down)
  2. Stock weights within sectors (bottom-up)
- Compare to single-level optimization

**Phase 6: Live Backtesting System** (4-5 weeks)
- End-to-end equity backtesting pipeline
- Data: Yahoo Finance → adapter → returns → signals → alpha → risk → optimizer → portfolio
- Rebalancing: monthly/quarterly
- Transaction costs: proportional (bps per trade)
- Performance analysis: TearSheet with IC, Sharpe, turnover

### Open Questions

#### 1. Growth Forecasts

**Problem**: Most critical input for DDM, but hard to get reliable forecasts

**Options**:
1. **Analyst estimates** (yfinance):
   - `ticker.earnings_estimates` has forward EPS
   - Calculate g from EPS(t+1)/EPS(t) - 1
   - Pro: Professional forecasts
   - Con: Often too optimistic, limited coverage

2. **Historical growth**:
   - g = mean(EPS growth over last 5 years)
   - Pro: Observable, available for all stocks
   - Con: Past ≠ future, ignores turning points

3. **Implied growth**:
   - g = i_F + β·f_B - d/p (assume α=0)
   - Use as baseline, adjust slightly with analyst estimates
   - Pro: Market consensus embedded
   - Con: Assumes efficient pricing

**Recommendation**: Hybrid approach
```python
g = 0.5 * g_implied + 0.3 * g_analyst + 0.2 * g_historical
```
Adjust weights based on backtested IC

#### 2. Factor Definitions

**Sector factors**:
- GICS Level 1: 11 sectors (broad)
- GICS Level 2: 24 industry groups (more granular)
- GICS Level 3: 69 industries (very detailed)

**Choice**: Start with 11 sectors (Level 1)
- Sufficient diversification
- More stable correlations
- Easier to forecast sector returns

**Style factors**:

| Factor    | Definition                               | Rationale                |
|-----------|------------------------------------------|--------------------------|
| Value     | 1 / P_B (book-to-price)                  | Fama-French value factor |
| Growth    | 5-year EPS growth forecast               | Growth premium           |
| Momentum  | 12-month total return (skip 1 month)     | Jegadeesh-Titman         |
| Size      | log(market cap)                          | Small-cap premium        |
| Quality   | ROE × (1 - debt/equity)                  | Profitability + safety   |
| Volatility| σ(daily returns, 60 days)                | Low-vol anomaly          |

**Standardization**: All factors standardized to mean=0, std=1 across universe

#### 3. Risk Model Choice

**Option A: Factor model** (APT structure)
```
V = X · F · X^T + Δ
```
- Pro: Interpretable, connects to theory
- Pro: Reduces parameters (N² → N·K + K² + N)
- Con: Need to define factors
- Con: Model risk if factors wrong

**Option B: Statistical covariance** (Ledoit-Wolf)
```
V = λ · V_sample + (1-λ) · V_target
```
- Pro: No need to define factors
- Pro: Works with any return data
- Con: Less interpretable
- Con: Still N² parameters (large N = slow)

**Option C: Hybrid**
```
V = λ · (X · F · X^T + Δ) + (1-λ) · V_sample
```
- Combines strengths of both
- Factor structure + empirical adjustment

**Recommendation**: Start with Option B (Ledoit-Wolf) for MVP
- Already implemented in ARBS
- Add Option A (factor model) in Phase 3
- Compare performance, interpretability

#### 4. Alpha Scaling

**Current ARBS**: Single signal, α = IC × Vol × Z

**Multiple signals**: How to combine?

**Option 1: IC-weighted average**
```
α_combined = Σ_k (IC_k · α_k) / Σ_k IC_k
```
Simple, theoretically sound (Fundamental Law additivity)

**Option 2: Regression-based**
```
α_combined = Σ_k w_k · α_k
```
where w_k from:
```
max Σ_t r_B(t) · [Σ_k w_k · α_k(t-1)] - λ · Σ_k w_k²
```
Optimizes historical performance (may overfit)

**Option 3: Hierarchical**
```
α = α_valuation + α_momentum + α_carry
```
where each component scaled separately:
```
α_valuation = IC_val × Vol × Z_val
α_momentum = IC_mom × Vol × Z_mom
α_carry = IC_car × Vol × Z_car
```
Maintains individual signal identities

**Recommendation**: Start with Option 1 (IC-weighted)
- Transparent
- Consistent with Fundamental Law
- Easy to interpret IC contribution

#### 5. Rebalancing Frequency

**Considerations**:
- **Fundamental signals** (DDM, comparative): slow-moving → monthly/quarterly
- **Momentum signals**: medium-term → monthly
- **High-frequency signals**: not available for most equities (no futures/swaps market microstructure)

**Transaction costs**:
- Equities: ~5-10 bps per trade (vs <1 bps for futures)
- Turnover penalty: α_net = α_gross - TC × turnover

**Optimal frequency**:
```
Sharpe_net = √(f) · Sharpe_annual - TC · √(f) · turnover_per_period
```
Maximize over f:
```
f_opt = (Sharpe_annual / (2 · TC · turnover))²
```

For typical values:
- Sharpe_annual = 1.0
- TC = 10 bps = 0.001
- Turnover per month = 50%

f_opt ≈ (1.0 / (2 × 0.001 × 0.5))² = 1,000,000 / 12 ≈ monthly

**Recommendation**: Monthly rebalancing for equity portfolios
- Balances signal decay vs transaction costs
- Standard industry practice
- Can use quarterly for slower strategies (value/quality)

### Success Metrics

**Phase 1-2 (Signals)**:
- IC (Information Coefficient) > 0.03 (respectable)
- IC_DDM, IC_comparative independently measured
- t-stat of IC > 2.0 (statistically significant)

**Phase 3 (Risk Model)**:
- Factor model explains >95% of diversified portfolio variance
- Specific risk Δ_ii < 0.3 for typical stock
- Risk forecast accuracy: realized vol within 20% of forecast

**Phase 4 (Multi-Signal)**:
- Combined IC > max(IC_k) (signals complement, not substitute)
- Correlation(α_DDM, α_momentum) < 0.5 (diversity)
- Transfer coefficient > 0.7 (optimizer uses alphas effectively)

**Phase 5-6 (Full System)**:
- Information Ratio > 0.5 (top quartile)
- Sharpe ratio > 1.0 after costs
- Turnover < 100% per year
- Max drawdown < 20%

---

## Summary and Next Steps

### Key Takeaways from Chapters 7-9

1. **APT provides flexible multi-factor framework**
   - Sectors + styles = equity factor model
   - Factor forecasts harder than factor definitions
   - Many reasonable models qualify

2. **Valuation theory connects prices to expected returns**
   - Risk-adjusted cash flows (Ch 8 theory)
   - Mispricing → alpha if market corrects (γ parameter)
   - Persistence matters: fast ideas (γ≈0) vs slow ideas (γ≈1)

3. **Practical valuation methods**
   - DDM: Golden Rule "g in, g out" - growth forecasts critical
   - Comparative: Cross-sectional pricing of attributes
   - Returns-based: Direct modeling of residual returns

4. **ARBS already has strong foundation**
   - Grinold-Kahn architecture (IC × Vol × Z)
   - Returns-first design
   - Extensible signal framework

5. **Equity extension is natural evolution**
   - Signals: Add valuation (DDM, comparative) + fundamental (value, quality, growth)
   - Risk: Add factor model option (APT structure)
   - Alpha: Blend multiple signals via IC weighting

### Immediate Next Steps

1. **Create proof-of-concept DDM signal** (1 week)
   - 10-20 stocks, simple data
   - Measure IC vs realized returns
   - Validate formula: α = d/p + g - β·f_B

2. **Test growth forecast approaches** (1 week)
   - Compare: implied, analyst, historical, hybrid
   - Measure IC of each
   - Choose best for Phase 2

3. **Design factor model architecture** (1 week)
   - Finalize factor list (11 sectors + 4-6 styles)
   - Exposure calculation methodology
   - Covariance estimation approach

4. **Commit this document** (now!)
   - Captures detailed synthesis of Chapters 7-9
   - Reference for implementation decisions
   - Living document: update as we learn

---

## References

- Grinold, R.C. and Kahn, R.N. (1999). *Active Portfolio Management*, McGraw-Hill, Chapters 7-9.
- Ross, S.A. (1976). "The Arbitrage Theory of Capital Asset Pricing." *Journal of Economic Theory*, 13, 341-360.
- Fama, E.F. and French, K.R. (1992). "The Cross-Section of Expected Stock Returns." *Journal of Finance*, 67(2), 427-465.
- Haugen, R.A. and Baker, N.L. (1996). "Commonality in the Determinants of Expected Stock Returns." *Journal of Financial Economics*, 41(3), 401-439.
- Williams, J.B. (1938). *The Theory of Investment Value*, Harvard University Press.
- Gordon, M.J. and Shapiro, E. (1956). "Capital Equipment Analysis: The Required Rate of Profit." *Management Science*, 3(1), 102-110.
- Ohlson, J.A. (1995). "Earnings, Book Values, and Dividends in Equity Valuation." *Contemporary Accounting Research*, 11(2), 661-687.
- Modigliani, F. and Miller, M.H. (1958). "The Cost of Capital, Corporation Finance and the Theory of Investment." *American Economic Review*, 48(3), 261-297.

