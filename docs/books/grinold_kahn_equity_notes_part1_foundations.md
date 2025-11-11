# Part 1: Foundations - Equity Implementation Notes

**Source**: Active Portfolio Management (Grinold & Kahn, 1999), Chapters 2-6  
**Purpose**: Extract equity-specific concepts for ARBS system extension  
**Date**: 2025-11-11

---

## Overview: What's Different for Equities

ARBS currently implements Grinold-Kahn principles for futures/swaps. For equities, the key differences are:

1. **Benchmark structure**: S&P 500, Russell indices (vs futures roll curves)
2. **Risk decomposition**: Total = Systematic + Residual (systematic via beta to equity index)
3. **Breadth**: 500+ stocks × 4 quarters = 2000+ bets/year (vs 20 futures × 12 = 240)
4. **Alpha sources**: Multi-factor (value, momentum, quality) vs carry-based
5. **Risk models**: Industry + style factors (size, value, growth) vs term structure factors
6. **Business risk**: Institutional equity managers face different career risk (tracking error)

---

## Chapter 2: CAPM - Consensus Expected Returns

### Core Concepts

**Beta Separation (equity-agnostic, already in ARBS)**:
```
r_n = β_n · r_M + θ_n
```
- β_n = Cov{r_n, r_M} / Var{r_M}
- θ_n = residual return (uncorrelated with market)

**CAPM Result**:
- E{θ_n} = 0 for all assets
- E{r_n} = β_n · μ_M (expected excess return proportional to beta)

### Equity-Specific Applications

**1. Equity Benchmarks (NEW)**:
- US Large Cap: S&P 500, Russell 1000
- US Small Cap: Russell 2000
- US Value/Growth: Russell Value/Growth indices
- Different from futures where "benchmark" is cash or roll-optimized position

**2. Equity Betas**:
Table 2.1 (page 15) shows MMI constituent betas vs S&P 500:
- American Express: β = 1.21 (BARRA predicted: 1.14)
- AT&T: β = 0.96 (BARRA predicted: 0.69)
- Chevron: β = 0.46 (BARRA predicted: 0.66)
- Range: 0.46 to 1.30 for large-cap stocks

**Key insight**: Historical beta ≠ forward-looking beta. BARRA models use fundamental attributes to predict beta (more stable than 60-month regression).

**3. Characteristic Portfolios (Chapter 2 Appendix)**:
- Portfolio Q: highest Sharpe ratio (fully invested)
- Portfolio C: minimum variance (fully invested)
- Portfolio A: characteristic portfolio of alphas (zero beta, can have leverage)
- Portfolio B: benchmark itself

For equities:
- Q ≈ cap-weighted market (S&P 500)
- C has βC ≤ 1 (lower-risk stocks)
- All characteristic portfolios have β with respect to B

### Links to ARBS Architecture

**Current ARBS classes that extend to equities**:
- `FuturesQuery` → `EquityQuery` (query S&P 500 constituents)
- `FuturesAdapter` → `EquityAdapter` (returns matrix for 500+ stocks)
- `CarrySignal` → `ValueSignal`, `MomentumSignal` (equity factors)
- `ReturnsCalculator`: works identically
- `Portfolio`: works identically (returns-first design)

**NEW classes needed**:
- `EquityBenchmark`: encapsulate S&P 500, Russell indices
- `BetaCalculator`: compute equity betas (use BARRA-style fundamental beta)
- `EquityUniverse`: manage 500+ stock universe (vs 20 futures contracts)

---

## Chapter 3: Risk

### Core Concepts (equity-agnostic)

**Risk = Standard Deviation**:
- σ_P = Std{r_P} (annualized)
- Risks don't add: σ_P ≠ Σ w_n σ_n (diversification)
- Variance adds across time (if returns uncorrelated): σ_annual = σ_monthly × √12

**Residual Risk**:
```
r_n = β_n · r_B + θ_n
ω_P² = Var{θ_P}  (residual variance)
```

**Active Risk**:
```
r_PA = r_P - r_B  (active return)
ψ_P = Std{r_PA}  (active risk = tracking error)
```

### Equity-Specific: Structural Risk Models

**Multi-Factor Risk Model** (page 55, Eq 3.16):
```
r_n(t) = Σ_k X_n,k(t) · b_k(t) + u_n(t)
```
Where:
- X_n,k(t) = exposure of asset n to factor k (known at time t)
- b_k(t) = factor return for period [t, t+1]
- u_n(t) = specific return (idiosyncratic, uncorrelated across factors and stocks)

**Covariance Structure** (Eq 3.17):
```
V_n,m = Σ_k1 Σ_k2 X_n,k1 · F_k1,k2 · X_m,k2 + Δ_n,m
```
Where:
- F = K×K factor covariance matrix
- Δ = N×N diagonal matrix of specific variances

**Equity Factor Types**:

1. **Industry Factors** (Table 3.2, page 61-62):
   - 52 industries in BARRA US model (as of 1998)
   - Examples: Banks (8.47% of cap), Drugs (6.70%), Telephones (5.18%)
   - Exposures: X_n,industry ∈ {0, 1} (or fractional for conglomerates like GE)

2. **Risk Indices** (page 62-63):
   - **Volatility**: Recent vol, option-implied vol, beta
   - **Momentum**: 12-month return
   - **Size**: Log(market cap)
   - **Liquidity**: Share turnover
   - **Growth**: Earnings growth forecasts
   - **Value**: E/P, B/P, CF/P, D/P ratios
   - **Earnings Volatility**: Std of quarterly earnings
   - **Financial Leverage**: Debt/equity, interest rate sensitivity

3. **Exposure Standardization** (page 63):
```
X_n,k = (x_raw,n - mean(x_raw)) / std(x_raw)
```
- Mean = 0, Std = 1 across universe
- Example: GE has size exposure = 1.90 (large), Netscape = -1.57 (small)

**Empirical Risk Numbers** (Table 3.1, page 58):
Large US equities (1200 stocks), percentiles:
- Total Risk: 10th=20%, 50th=31%, 90th=51%
- Residual Risk: 10th=16%, 50th=25%, 90th=45%
- Beta: 10th=0.52, 50th=1.08, 90th=1.67

### Equity vs Futures Risk Models

| Aspect | Futures (ARBS current) | Equities (NEW) |
|--------|------------------------|----------------|
| Factors | Term structure (DV01 by tenor) | Industries + risk indices |
| N assets | ~20 contracts | ~500-2000 stocks |
| K factors | ~10-15 (curve points) | ~65 (52 industries + 13 indices) |
| Factor exposures | Continuous (DV01) | Mixed (0/1 for industries, standardized for indices) |
| Specific risk | Basis risk, roll yield | Idiosyncratic stock risk |
| Correlation structure | High (curve co-movement) | Lower (industry + style) |

### Links to ARBS Architecture

**Current ARBS Risk classes**:
- `SampleCovariance`: works for equities
- `LedoitWolfShrinkage`: works for equities
- `CovarianceEstimator` interface: extensible

**NEW classes needed**:
- `EquityFactorModel`: implement Eq 3.16 for equities
  - `IndustryFactors`: 52 industries
  - `RiskIndices`: size, value, momentum, etc.
  - `FactorExposureCalculator`: compute X matrix
  - `FactorReturnEstimator`: Fama-MacBeth regression (Eq 3A.4)
- `SpecificRiskModel`: estimate Δ matrix (Eq 3A.6)
- `MarginalRiskContribution`: ∂ω_P/∂h_n (Eq 3A.21)

**Key equation for portfolio construction** (already in ARBS):
```python
# Portfolio variance with factor model
variance = h.T @ X @ F @ X.T @ h + h.T @ Delta @ h
```

---

## Chapter 4: Benchmarks and Value Added

### Equity Benchmarks (NEW concept for ARBS)

**Benchmark Definition** (page 88-89):
- Benchmark = bogey = normal portfolio
- Institutional equity managers judged relative to benchmark
- Examples:
  - US Large Cap → S&P 500
  - US Small Cap → Russell 2000
  - US Value → Russell 1000 Value
  - International → MSCI EAFE

**Why Benchmarks Matter for Equities**:
1. Specialization: Manager focuses on subset of investable universe
2. Performance measurement: Active return = r_P - r_B
3. Risk control: Active risk = tracking error
4. Client communication: Clear mandate definition

### Components of Expected Return

**Decomposition** (Eq 4.7, page 91):
```
E{R_n} = i_F + β_n·μ_B + β_n·Δf_B + α_n
```
Where:
- i_F = risk-free rate (time premium)
- β_n·μ_B = risk premium (long-run benchmark excess return)
- β_n·Δf_B = exceptional benchmark return (tactical timing)
- α_n = alpha (expected residual return)

**Example** (Table 4.2, page 94): MMI stocks (Dec 1992)
- Risk-free rate = 3.16%
- S&P 500 expected excess return = 6.00%
- Coca-Cola: α=20.03%, β=1.00 → E{R}=29.19%
- IBM: α=-19.04%, β=0.64 → E{R}=-12.04%

Wide dispersion in alphas (±20%) typical for equity managers.

### Value Added Objective

**Active Management Objective** (Eq 4.15, page 101):
```
VA = β_PA·Δf_B - λ_BT·β_PA²·σ_B²   (benchmark timing)
   + α_P - λ_R·ω_P²                (stock selection)
```
Where:
- β_PA = active beta (β_P - 1)
- λ_BT = aversion to benchmark timing risk
- λ_R = aversion to residual risk (typically λ_R >> λ_BT >> λ_T)

**Key insight**: Institutional equity managers have λ_R ≈ 10-20× higher than λ_T (total risk aversion).

**Business Risk vs Investment Risk** (page 100):
- Benchmark risk (σ_B ≈ 20%) borne by client
- Residual risk (ω_P ≈ 2-6%) borne by manager (career risk)
- 20% → 21% total risk seems small
- But if 20% benchmark + 6.4% residual → career risk of poor performance

**Residual Risk Aversion** (typical values):
- λ_R = 0.05 (aggressive)
- λ_R = 0.10 (moderate)
- λ_R = 0.15 (restrained)

Example: With 20% benchmark risk, σ_B²=400, λ_R=0.10 implies:
- Cost of 4% residual risk = 0.10 × 16 = 1.6% alpha penalty
- Substantial given typical alphas of 1-3%

### Links to ARBS Architecture

**Current ARBS classes**:
- `AlphaGenerator`: implements α_n = IC × Vol_n × Z_n
- `MeanVarianceOptimizer`: works with value-added objective

**NEW classes needed**:
- `EquityBenchmark`:
  - `.returns`: benchmark return series
  - `.holdings`: benchmark weights (for S&P 500)
  - `.beta(returns)`: compute betas relative to benchmark
- `ValueAddedObjective`:
  - Separate λ_BT (benchmark timing) and λ_R (stock selection)
  - Default: λ_BT = λ_R (no timing), β_P = 1
- `ActiveRiskCalculator`:
  - ψ_P = Std{r_P - r_B}
  - Decompose into timing risk (β_PA·σ_B) and residual risk (ω_P)

---

## Chapter 5: Information Ratio

### Core Concepts (equity-agnostic, already in ARBS)

**Information Ratio**:
```
IR = α_P / ω_P  (expected residual return / residual risk)
```

**Ex Post** (achievement): realized α / realized ω
**Ex Ante** (opportunity): maximum achievable IR given alphas

**Empirical Distribution** (Table 5.1, page 114):
- 90th percentile: IR = 1.0 (exceptional)
- 75th percentile: IR = 0.5 (top quartile, "good")
- 50th percentile: IR = 0.0 (median)
- 25th percentile: IR = -0.5
- 10th percentile: IR = -1.0

**Top-quartile equity manager**: IR = 0.5 (target)

**Value Added** (Eq 5.12, page 124):
```
VA = IR² / (4·λ_R)
```
Example: IR=0.75, λ_R=0.10 → VA = 0.5625 / 0.40 = 1.41% per year

### Equity-Specific Empirical Data

**US Active Equity Mutual Funds** (Table 5.6, page 130):
Before fees:
- 90th %ile: IR = 1.33
- 75th %ile: IR = 0.78
- 50th %ile: IR = 0.32
- 25th %ile: IR = -0.08

After fees (-0.75% typical):
- 75th %ile: IR = 0.58 (top quartile after fees)
- 50th %ile: IR = 0.12

**US Active Equity Institutional Portfolios** (Table 5.6):
Before fees:
- 90th %ile: IR = 1.25
- 75th %ile: IR = 0.63
- 50th %ile: IR = -0.01
- 25th %ile: IR = -0.56

**Active Risk Levels** (Table 5.8, page 131):
US active equity investors:
- 90th %ile: ψ = 9.5-10%
- 75th %ile: ψ = 6.5-7%
- 50th %ile: ψ = 4.4-4.8%
- 25th %ile: ψ = 2.9-3.7%

**Optimal Aggressiveness** (Eq 5.10, page 123):
```
ω* = IR / (2·λ_R)
```

**Example combinations** (Table 5.3):
| IR | λ_R | ω* | VA |
|----|-----|----|----|
| 0.50 | 0.10 | 2.5% | 0.63% |
| 0.75 | 0.10 | 3.75% | 1.41% |
| 1.00 | 0.10 | 5.0% | 2.50% |

Median institutional equity manager: ω* ≈ 4.5%, suggests IR ≈ 0.6-0.9 (before fees).

### Characteristic Portfolio A (Appendix 5A)

**Portfolio A** = characteristic portfolio of alphas:
```
h_A = V^{-1}·α / (α^T·V^{-1}·α)
```

Properties:
- β_A = 0 (zero beta)
- α_A = 1 (unit alpha by construction)
- ω_A = 1/IR (residual risk inversely proportional to IR)
- IR_A = IR (maximum achievable)

**For equities**: Portfolio A typically has:
- Long positions in high-alpha stocks
- Short positions in low-alpha stocks (if allowed)
- No net market exposure (β=0)
- High turnover (alphas change frequently)

**Optimal Policy** (Eq 5A.26):
```
h_P* = β_P·h_B + (IR / 2λ_R)·h_A
```
Where β_P = 1 (no timing) for typical equity manager.

### Links to ARBS Architecture

**Current ARBS classes (work for equities)**:
- `TearSheet`: computes IR from backtest results
- `BacktestResult`: stores alpha, omega, IR
- `AlphaGenerator`: produces alpha forecasts

**Modifications needed**:
- `InformationRatioCalculator`:
  - Compute IR from alpha forecasts: IR = √(α^T·V^{-1}·α)
  - Scale alphas to target IR (multiply by IR_target / IR_current)
- `OptimalAggressiveness`:
  - Given IR and λ_R, compute ω* = IR / (2λ_R)
  - Compare to empirical distribution (Table 5.8)

**Key insight**: For equities with 500 stocks, even IC=0.02 can achieve IR=0.5+

---

## Chapter 6: Fundamental Law of Active Management

### The Fundamental Law

**Core Formula** (Eq 6.1, page 148):
```
IR ≈ IC × √BR
```
Where:
- IC = information coefficient (skill)
- BR = breadth (number of independent bets per year)

**IC Definition**: Correlation between forecasts and outcomes
```
IC = Corr{α_forecast, θ_realized}
```

**BR Definition**: Number of independent forecasts per year

### Equity-Specific Breadth

**Breadth Calculation**:
```
BR = N_stocks × forecasts_per_stock_per_year
```

**Examples**:

1. **US Large Cap Manager** (page 149):
   - Follows 200 stocks
   - Updates forecasts semi-annually (2× per year)
   - BR = 200 × 2 = 400
   - Needs IC = 0.025 to achieve IR = 0.50

2. **US Broad Market Manager**:
   - Follows 500 stocks (S&P 500)
   - Updates quarterly (4× per year)
   - BR = 500 × 4 = 2000
   - Needs IC = 0.011 to achieve IR = 0.50

3. **Market Timer** (page 149):
   - One bet (S&P 500 direction)
   - Quarterly updates (4× per year)
   - BR = 1 × 4 = 4
   - Needs IC = 0.25 to achieve IR = 0.50

**Key insight**: Equity stock selection has ~100-500× breadth advantage over market timing.

### Typical IC Levels for Equities

**Directional Accuracy** (Eq 6.6, page 154):
```
IC = 2 × (fraction_correct - 0.5)
```

Examples:
- 50.0% correct → IC = 0.00
- 52.9% correct → IC = 0.058
- 55.0% correct → IC = 0.10
- 60.0% correct → IC = 0.20

**Realistic IC for equity factors**:
- Value factors (E/P, B/P): IC ≈ 0.03-0.05
- Momentum (12-month return): IC ≈ 0.04-0.06
- Quality (ROE, earnings stability): IC ≈ 0.02-0.04
- Analyst recommendations: IC ≈ 0.02-0.03 (if fresh)

**Example** (page 152): 200 stocks, IC=0.0577, semi-annual:
- BR = 400
- IR = 0.0577 × √400 = 1.154 (exceptional!)
- But IC=0.0577 is only 52.9% directional accuracy
- "Small edge" can produce large IR with sufficient breadth

### Additivity

**Squared IR is additive** (Eq 6.7, page 154):
```
IR_total² = IR_1² + IR_2² + ... + IR_N²
```

**Multi-Factor Equity Example** (page 154-156):
Consider 400 stocks, 3 factors updated annually:

| Factor | IC | BR | IR |
|--------|----|----|-----|
| Value (E/P) | 0.03 | 400 | 0.60 |
| Momentum (12M) | 0.04 | 400 | 0.80 |
| Quality (ROE) | 0.02 | 400 | 0.40 |

Combined: IR = √(0.60² + 0.80² + 0.40²) = √1.00 = 1.00

**Across managers**: Sponsor hires 3 equity managers with IR = [0.75, 0.50, 0.30]:
```
IR_total = √(0.75² + 0.50² + 0.30²) = √0.905 = 0.95
```

### Independence Requirement

**Key assumption**: Forecasts must be independent.

**Violations** (page 158):
1. **Industry bets disguised as stock picks**: Recommend all banks → 1 bet, not 50
2. **Single factor repeated**: Recommend all high-E/P stocks → 1 bet
3. **Momentum repeated**: Rebalance monthly but update annually → 1 bet, not 12

**Test for independence**: Regress recommendations against factors:
```
recommendation_n = β_0 + Σ_k β_k · factor_k,n + ε_n
```
- Large R²: recommendations are factor bets (not independent)
- Use residuals ε_n for independent stock-specific forecasts

### Links to ARBS Architecture

**Current ARBS classes**:
- Signals framework: already supports multiple signals
- `SignalCombiner`: combines multiple signals

**NEW for equities**:
- `BreadthCalculator`:
  - Count independent forecasts: BR = effective_N_stocks × forecasts_per_year
  - Detect factor correlations to adjust BR
  - Example: If alphas are 70% driven by value factor → BR_effective = 0.3 × BR_nominal
- `InformationCoefficientEstimator`:
  - Estimate IC from historical forecasts vs realized returns
  - Separate IC by factor (value IC, momentum IC, etc.)
- `FundamentalLawValidator`:
  - Check IR_realized ≈ IC_estimated × √BR_counted
  - Flag if mismatch (suggests overfitting or dependence)

**Example ARBS equity config**:
```python
# Equity strategy with 3 factors
equity_strategy = {
    'universe': 'SP500',  # 500 stocks
    'signals': [
        {'type': 'value', 'IC': 0.03, 'weight': 0.4},
        {'type': 'momentum', 'IC': 0.04, 'weight': 0.4},
        {'type': 'quality', 'IC': 0.02, 'weight': 0.2}
    ],
    'rebalance_frequency': 'quarterly',  # 4× per year
    'BR': 500 * 4,  # 2000 independent bets
    'IR_target': 0.75,  # Top quartile
    'omega_target': 0.05  # 5% active risk
}

# Implied combined IC
IC_combined = 0.03²×0.4² + 0.04²×0.4² + 0.02²×0.2²  # weighted average
IR_predicted = IC_combined × sqrt(2000) ≈ 0.75
```

---

## Summary: Equity-Specific Extensions for ARBS

### 1. Data Layer (NEW)

**Classes to add**:
- `EquityUniverse`: Manage S&P 500, Russell indices
- `EquityQuery`: Query price, fundamental, factor data
- `EquityAdapter`: Convert to returns matrix (500×T)

**Data requirements**:
- Daily/weekly prices for 500+ stocks
- Fundamental data: E/P, B/P, ROE, debt/equity
- Factor exposures: size, value, momentum, quality

### 2. Risk Layer (EXTEND existing)

**NEW classes**:
- `EquityFactorModel(CovarianceEstimator)`:
  - Industry factors (52)
  - Risk indices (volatility, size, value, momentum, growth, leverage)
  - Specific risk estimation
- `FactorExposureCalculator`:
  - Compute X matrix (N_stocks × K_factors)
  - Standardize exposures (mean=0, std=1)
- `BetaCalculator`:
  - Compute equity betas to S&P 500
  - Use fundamental attributes (not just historical regression)

**Factor covariance** (F matrix):
- Estimate from monthly factor returns (Fama-MacBeth)
- 65×65 matrix for US equities (52 industries + 13 indices)

### 3. Signal Layer (EXTEND existing)

**NEW signal types for equities**:
- `ValueSignal`: E/P, B/P, CF/P, D/P ratios
- `MomentumSignal`: 12-month return (already exists!)
- `QualitySignal`: ROE, earnings stability, accruals
- `GrowthSignal`: Earnings growth, sales growth
- `SentimentSignal`: Analyst recommendations, short interest

**IC estimation** per signal:
- Historical: Corr{signal_t, return_t+1}
- Typical: IC = 0.02-0.05 for individual factors
- Combined: IR = √Σ(IC_k² × BR_k)

### 4. Alpha Layer (EXTEND existing)

**Equity-specific alpha generation**:
```python
# Current ARBS (works for equities!)
alpha_n = IC × Vol_n × Score_n

# For multi-factor equity:
alpha_n = Σ_k (IC_k × Vol_n × Score_k,n)
```

**Alpha scaling**:
- Target IR = 0.50 (top quartile) or 0.75 (exceptional)
- Scale factor = IR_target / IR_current
- Ensure α_B = 0 (benchmark-neutral)

### 5. Portfolio Layer (WORKS AS-IS!)

**Existing ARBS Portfolio class**:
- Returns-first design → perfect for equities
- Nested portfolios → sector sub-portfolios
- No changes needed!

**Optimizer modifications**:
- Add β constraint: h^T·β = 1 (market-neutral)
- Add sector neutrality: Σ_{n in sector} h_n = 0
- Add turnover constraint: Σ|Δh_n| ≤ τ

### 6. Backtest Layer (EXTEND existing)

**NEW for equities**:
- `EquityBacktest(MinimalBacktest)`:
  - Benchmark = S&P 500 (not cash)
  - Track active return (r_P - r_B)
  - Compute tracking error (ψ_P)
- `EquityTearSheet`:
  - Active return vs benchmark
  - Beta stability (β_P over time)
  - Sector attribution
  - Factor attribution (value, momentum, quality)

---

## Open Questions for ARBS Equity Extension

### 1. Benchmark Selection
- Default to S&P 500 for large-cap US equities?
- Support Russell 2000 for small-cap?
- Allow custom benchmarks (sector indices, factor indices)?

### 2. Factor Model
- Build full BARRA-style factor model (65 factors)?
- Start simpler: just size, value, momentum (3 factors)?
- Use external factor data (Fama-French, AQR) vs compute in-house?

### 3. Short Selling
- Allow shorts (long/short equity)?
- If yes, need to handle borrowing costs, margin requirements
- If no, optimize with h_n ≥ 0 constraint (reduces IR)

### 4. Transaction Costs
- Equity-specific: bid-ask spread (~5-20 bps), market impact (~10 bps per 1% ADV)
- Higher for small-cap, lower for large-cap
- Proportional model: TC_n = c_n × |Δh_n| (where c_n ≈ 10-50 bps)

### 5. Rebalancing Frequency
- Daily: high turnover, high costs
- Weekly: moderate turnover
- Monthly: lower turnover (typical for equity long-only)
- Quarterly: very low turnover (typical for factor strategies)

### 6. Universe Construction
- S&P 500: liquid, but excludes small-cap
- Russell 1000: broader, includes growth/value
- Russell 3000: very broad, includes small-cap (liquidity issues)
- Trade-off: breadth (more stocks) vs liquidity (tradability)

### 7. Data Requirements
- Price data: daily close prices
- Fundamental data: quarterly earnings, book value, debt
- Factor data: pre-computed (Fama-French) or compute from fundamentals?
- Survivorship bias: need delisted stocks for accurate backtest

---

## Next Steps

### Phase 1: Minimal Equity Extension (MVP)
1. Add `EquityQuery` and `EquityAdapter` (query S&P 500 constituents)
2. Reuse existing `ReturnsCalculator`, `SampleCovariance`
3. Add `ValueSignal` (E/P ratio) with IC=0.03
4. Add `MomentumSignal` (12-month return) with IC=0.04
5. Run backtest on S&P 500 (2010-2020)
6. Validate: IR ≈ IC × √BR = 0.036 × √(500×4) ≈ 1.6 (too high, need to check independence)

### Phase 2: Multi-Factor Risk Model
1. Implement `EquityFactorModel` with:
   - 10 industry factors (GICS Level 1)
   - 3 style factors (size, value, momentum)
2. Estimate factor covariance F (13×13)
3. Estimate specific risk Δ (500×500 diagonal)
4. Compare to `SampleCovariance` (validate factor model accuracy)

### Phase 3: Attribution and Analysis
1. Extend `TearSheet` with equity-specific metrics:
   - Sector attribution
   - Factor attribution (value, momentum, size)
   - Beta stability chart
2. Add `ActiveRiskDecomposition`:
   - Timing risk: β_PA × σ_B
   - Residual risk: ω_P
   - Factor risk: h^T·X·F·X^T·h
   - Specific risk: h^T·Δ·h

---

## References (Key Equations)

### Grinold-Kahn Core Formulas for Equities

1. **Return decomposition**: r_n = β_n·r_B + θ_n (Eq 2.1)
2. **Risk decomposition**: σ_P² = β_P²·σ_B² + ω_P² (Eq 3.4)
3. **Active risk**: ψ_P² = β_PA²·σ_B² + ω_P² (Eq 4.4)
4. **Factor model**: r_n = Σ_k X_n,k·b_k + u_n (Eq 3.16)
5. **Value added**: VA = α_P - λ_R·ω_P² (Eq 4.15)
6. **Information ratio**: IR = α_P / ω_P (Eq 5.4)
7. **Fundamental law**: IR = IC × √BR (Eq 6.1)
8. **Optimal aggressiveness**: ω* = IR / (2λ_R) (Eq 5.10)
9. **Alpha generation**: α_n = IC × Vol_n × Score_n (Chap 4-5)
10. **Characteristic portfolio A**: h_A = V^{-1}·α / (α^T·V^{-1}·α) (Eq 5A.1)

### Equity-Specific Parameters

- **Benchmark**: S&P 500, σ_B ≈ 16-20%
- **Active risk**: ψ_P ≈ 2-10%, median ≈ 4.5%
- **Information ratio**: Top quartile IR = 0.5, exceptional IR = 1.0
- **Breadth**: BR = 500-2000 for stock pickers
- **IC**: IC = 0.02-0.05 per factor
- **Risk aversion**: λ_R = 0.05-0.15
- **Rebalance**: Quarterly (4× per year) typical

---

**END OF PART 1 NOTES**
