# Part 3: Information Processing - Equity Implementation Notes

**Source**: Grinold & Kahn (1999), "Active Portfolio Management", Chapters 10-13
**Context**: Adapting forecasting methodology for ARBS equity signals

---

## Chapter 10: Forecasting Basics

### Core Forecasting Formula

**The fundamental result**: Refined forecasts have the form:
```
α = volatility · IC · score
```

Where:
- **α**: Exceptional return forecast (alpha)
- **volatility**: Asset volatility (ω)
- **IC**: Information coefficient (skill level, correlation between forecast and realized return)
- **score**: Standardized raw forecast (mean 0, std dev 1)

**Basic Forecasting Formula** (Eq 10.1):
```
E{r | g} = E{r} + Cov{r,g} · Var{g}^(-1) · (g - E{g})
```

Where:
- r = excess return vector
- g = raw forecast vector
- E{r} = naïve (consensus) forecast
- E{r | g} = informed expected return

**Refined forecast** (exceptional return):
```
φ = E{r | g} - E{r}
```

### Three Types of Forecasts

1. **Naïve forecast**: Consensus expected return (informationless)
   - For asset n: `E{rₙ} = βₙ · μB` (CAPM-style)
   - Historical averages are POOR alternatives (high sampling error)

2. **Raw forecast**: Manager's information in raw form
   - Earnings estimates, buy/sell recommendations, momentum scores
   - Various units and scales, not directly alphas

3. **Refined forecast**: Transformed via basic forecasting formula
   - Units of exceptional return
   - Adjusted for information content

### Standardization: The Score

**Time series score** (for one asset over time):
```
z = (g - E{g}) / σ(g)
```

**Properties**:
- Mean 0, standard deviation 1
- Distinguishes current forecast from historical average
- Controls for expectations

**Refined forecast becomes**:
```
φ = ω · IC · z
```

### Single Asset, Single Forecast: Binary Model Example

**Setup** (quarterly):
- Expected return: 1.5% per quarter (6% annual)
- Volatility: 9% per quarter (18% annual)
- Raw forecast: mean 2%, std dev 4%

**Return decomposition**:
```
r = 1.5 + Σ(i=1 to 81) θᵢ
```
where each θᵢ is ±1 with equal probability (81 units of uncertainty)

**Forecast decomposition**:
```
g = 2 + θ₁ + θ₂ + θ₃ + Σ(j=1 to 13) ηⱼ
```
- 3 signals (θᵢ shared with return)
- 13 noise elements (ηⱼ uncorrelated with return)

**IC calculation**:
```
IC = Cov{r,g} / (σ(r) · σ(g))
    = 3 / (9 · 4)
    = 0.0833
```

**Refined forecast**:
```
φ = 9% · 0.0833 · z = 0.75% · z
```

### Single Asset, Two Forecasts: Signal Combination

**Setup**: Two forecasts g and g' with:
- IC_g = 0.0833, IC_g' = 0.089
- Correlation ρ(g,g') determines optimal combination

**Refined forecast**:
```
φ = ω · (IC̃_g · z_g + IC̃_g' · z_g')
```

**Adjusted ICs** (accounting for correlation):
```
IC̃_g = (IC_g - ρ_gg' · IC_g') / (1 - ρ²_gg')

IC̃_g' = (IC_g' - ρ_gg' · IC_g) / (1 - ρ²_gg')
```

**Combined IC**:
```
IC_combined = √(IC²_g + IC²_g' + 2·ρ_gg'·IC_g·IC_g')
```

**Key insight**: If forecasts are uncorrelated (ρ = 0), simply add refined forecasts:
```
φ_combined = φ_g + φ_g'
```

### Practical Examples

#### Example: Stock Tip
- Stock volatility: 20%
- Source IC: 0.1 (great), 0.05 (good), 0.0 (worthless)
- Score: 1.0 (positive), 2.0 (very positive)

**Alpha table**:
| IC   | Score=1 | Score=2 |
|------|---------|---------|
| 0.10 | 2.0%    | 4.0%    |
| 0.05 | 1.0%    | 2.0%    |
| 0.00 | 0.0%    | 0.0%    |

#### Example: Buy/Sell Recommendations
- MMI stocks (Table 10.3)
- IC = 0.09
- Score: +1 (buy), -1 (sell)

**Result**: Higher volatility stocks get higher absolute alphas
- IBM (ω=30.32%): α = +2.73% (buy) or -2.73% (sell)
- 3M (ω=13.41%): α = +1.21% (buy) or -1.21% (sell)

**Why?** Optimizer must equalize risk-adjusted returns. Higher volatility → higher alpha needed.

#### Example: Fractiles/Quintiles
- Rank stocks 1-N by raw signal
- Group into quintiles/deciles
- Standardize: subtract mean, divide by std dev
- Apply ω · IC · z to each group

### Forecasting and Risk: Negligible Effect

**Key result**: Forecasts of return have almost no effect on risk forecasts.

**Volatility adjustment**:
```
σ_POST = σ_PRIOR · √(1 - IC²)
```

**Impact table** (σ_PRIOR = 18%):
| IC   | σ_POST |
|------|--------|
| 0.05 | 17.98% |
| 0.10 | 17.91% |
| 0.15 | 17.80% |
| 0.25 | 17.43% |

**Conclusion**: For typical ICs (0.05-0.15), ignore impact on risk forecasts. Focus on alpha.

### IC Benchmarks (from text)

**Guidelines** (equity-like signals):
- **Good forecaster**: IC = 0.05
- **Great forecaster**: IC = 0.10
- **World-class forecaster**: IC = 0.15
- **IC > 0.20**: Usually faulty backtest or insider trading

**Reality check**: Most equity signals have IC = 0.02 - 0.08 in practice.

---

## Chapter 11: Advanced Forecasting

### Multiple Assets: Cross-Sectional vs Time Series Scores

**The problem**: We have N stocks at one point in time. Do we need volatility scaling?

**Answer**: It depends on how signal volatility varies across stocks.

#### Case 1: Identical Time Series Signal Volatilities

If `σ(gₙ) = c₁` for all assets n, then:
```
z_TS,n = z_CS,n
```

**Time series scores = cross-sectional scores**. Use directly:
```
φₙ = ωₙ · IC · z_CS,n
```

#### Case 2: Signal Volatilities Proportional to Asset Volatilities

If `σ(gₙ) = c₂ · ωₙ` (signal more volatile for volatile stocks), then:
```
φₙ = c_g · IC · z_CS,n
```

**Cross-sectional scores already capture volatility**. Don't multiply by ωₙ again!

The constant c_g can vary by signal.

### Empirical Evidence: BARRA Equity Signals

**Study**: 6 U.S. equity signals, 1990-1995, ~1200 stocks

**Regression test**:
```
σ_TS(gₙ) = a + b · ωₙ + ε
```

**Results** (Table 11.1):
| Signal              | R² | t-stat |
|---------------------|-----|--------|
| DDM                 | 0.37| 19.3   |
| Estimate change     | 0.34| 18.0   |
| Estimate revision   | 0.31| 17.0   |
| Relative strength   | 0.72| 54.3   |
| Residual reversal   | 0.77| 62.2   |
| Sector momentum     | 0.01| -3.8   |

**Interpretation**:
- First 5 signals: Strong relationship → signal volatility ∝ stock volatility → **don't scale by ωₙ**
- Sector momentum: No relationship → **do scale by ωₙ**

**Performance test** (Table 11.2):
| Signal            | IR (IC·z_CS) | IR (ωₙ·IC·z_CS) |
|-------------------|--------------|-----------------|
| DDM               | 1.31         | 1.19            |
| Estimate change   | 1.92         | 1.87            |
| Estimate revision | 3.55         | 3.32            |
| Relative strength | 1.93         | 1.93            |
| Residual reversal | 2.51         | 2.18            |
| Sector momentum   | 1.91         | 2.10            |

**Conclusion**: Cross-sectional scores without volatility scaling perform better for most equity signals.

### Signal Descriptions (BARRA examples)

1. **DDM (Dividend Discount Model)**
   - Internal rate of return from 3-stage DDM
   - See Chapter 9 for details

2. **Estimate Change**
   - 1-month change in consensus annual earnings / current price
   - Captures analyst estimate momentum

3. **Estimate Revision**
   - Combines estimate change + 1-month return
   - Accounts for price already reflecting news

4. **Relative Strength (Momentum)**
   - 13-month return minus 1-month return
   - Long-term momentum, controls for short-term reversal

5. **Residual Reversal**
   - 1-month return, residual to industry/factors
   - Short-term mean reversion

6. **Sector Momentum**
   - 1-month cap-weighted sector return
   - All stocks in sector get same signal

### Factor Forecasts: Correlated Factors

**Problem**: You have signal g₁ to forecast factor b₁. What about other factors?

**Wrong approach**: Set E{bⱼ | g₁} = 0 for j ≠ 1

**Correct approach**: Use basic forecasting formula:
```
E{bⱼ | g₁} = Corr{bⱼ, b₁} · IC₁ · σ(bⱼ) · z_g₁
```

**Intuition**: If factors are correlated, signal about b₁ contains information about bⱼ.

**Example**: Book-to-price (B/P) signal in BARRA U.S. Equity Model (1990-1995)

| Strategy                          | IR   |
|-----------------------------------|------|
| A: Bet only on B/P                | 3.26 |
| B: Use B/P to bet on all factors  | 3.42 |
| C: Use B/P to bet on other factors| 1.57 |

**Result**: Strategy B (using correlated factors) improves IR. Even strategy C works!

### Uncertain Information Coefficients: Bayesian Shrinkage

**Problem**: IC estimates have sampling error. How to account for?

**Regression with prior**:
```
θ(t) = b · g(t) + ε_θ(t)    (data)
b = 0 + ε_b                 (prior)
```

**Adjusted coefficient** (Eq 11.31):
```
b' = b · T·IC² / (T·IC² + 1)
```

**Approximation** (for small IC²):
```
b' ≈ b · T·IC² / (T·IC² + 2)
```

**Shrinkage table** (Table 11.4):
| Months | IC=0.05 | IC=0.10 |
|--------|---------|---------|
| 36     | 0.08    | 0.26    |
| 60     | 0.13    | 0.38    |
| 90     | 0.18    | 0.47    |
| 120    | 0.23    | 0.55    |
| 240    | 0.38    | 0.71    |

**Interpretation**: Multiply naive IC by shrinkage factor.
- IC=0.10, 120 months: Adjust to IC'=0.055
- IC=0.05, 60 months: Adjust to IC'=0.0065

**Insight**: Even long backtests with good signals need substantial shrinkage!

---

## Chapter 12: Information Analysis

### Two-Step Process

**Step 1**: Turn predictions into portfolios
**Step 2**: Evaluate portfolio performance

### Step 1: Six Procedures for Building Portfolios

#### Procedure 1: Buy/Sell Lists
- Equal-weight or cap-weight buy group
- Equal-weight or cap-weight sell group
- Simple but doesn't control for other factors

#### Procedure 2: Scores/Quintiles
- Rank stocks by score
- Group into quintiles/deciles
- Equal-weight or cap-weight within groups
- Example: Book-to-price quintiles

#### Procedure 3: Alpha-Weighted
- Split into above/below average alpha
- Weight by distance from average
- Elaboration of Procedure 1

#### Procedure 4: Alpha Quintiles
- Rank by alpha
- Group into quintiles
- Weight within groups
- Elaboration of Procedure 2

#### Procedure 5: Factor Portfolio (RECOMMENDED)
**Constraints**:
- Long and short portfolios
- Equal value, equal beta
- Long portfolio: +1σ exposure to signal
- Minimize tracking error

**Optimization**:
```
min Var{h_long - h_short}
s.t. h^T · β = 0            (zero beta)
     h^T · e = 0            (zero net investment)
     h^T · signal = 1       (unit signal exposure)
```

**Advantage**: Isolates signal, controls for market/other factors

#### Procedure 6: Controlled Factor Portfolio (BEST)
Same as Procedure 5, but add controls:
```
h^T · X = 0   (zero exposure to risk model factors)
```

**Controls**:
- Industry/sector neutral
- Size neutral
- Other risk factors neutral

**Advantage**: Most precise isolation of signal information

**Recommendation**: Use Procedures 5 or 6 for rigorous information analysis.

### Step 2: Performance Evaluation

#### Basic Analysis
- Plot cumulative returns (long, short, net)
- Compare to benchmark
- Visual inspection for patterns

**Example**: Book-to-price quintiles (1988-1992)
- Early period: High B/P outperforms
- 1989-1990: Low B/P outperforms (growth > value)
- Full period: Lowest quintile wins

#### Regression Analysis
```
r_portfolio(t) = α + β · r_benchmark(t) + ε(t)
```

**Outputs**:
- α: Portfolio alpha (excess return)
- β: Portfolio beta (market exposure)
- t(α): t-statistic for alpha
- t(β): t-statistic for beta

**Significance**: |t| > 2 → 95% confidence (p < 0.05)

#### Information Ratio
```
IR = α / σ(α)
```

**Relationship to t-statistic**:
```
t = IR · √T
```
where T = years of observation

**Distinction**:
- t-statistic: Statistical significance
- IR: Economic significance (risk-adjusted value added)

**Example**: IR = 0.5 over 5 years
- t-statistic = 0.5 · √5 = 1.12 (not significant)
- But value added is still 0.5 IR!

#### Information Coefficient (IC)

**Definition**: Correlation between forecast and realized alpha
```
IC = Corr{forecast, realized_alpha}
```

**Range**: -1 to +1
- IC = 0: No information (noise)
- IC = 1: Perfect foresight (impossible)
- IC = 0.05-0.10: Typical for good equity signals

**Fundamental Law connection**:
```
IR = IC · √BR
```

**Example**: Book-to-price (1988-1992)
- IC = 0.01
- IR = 0.27
- Implied BR = (0.27/0.01)² = 729 independent bets/year

### Event Studies: Episodic Information

**When to use**: Information doesn't arrive regularly for all stocks
- Earnings announcements
- New CEO appointments
- Dividend changes
- Stock splits
- Insider transactions

**Setup**:
- Event occurs at different times for different stocks
- Description of event: d (0/1 or continuous)
- Conditioning variables: X (firm characteristics)
- Asset return after event: θ (residual return)

**Generic regression**:
```
θₙ(1,j) / ωₙ(1,j) = b₀ + Σ(k) bₖ · Xₙₖ + ε
```

**Analysis**:
- Standardized residual return as dependent variable
- Event description + conditioning variables as independent
- Coefficient bₖ measures information content
- IC = b₀ (if no conditioning variables)

**From event to alpha**:
```
α(0,j) = ωₙ(0,j) · (b₀ + Σbₖ·Xₙₖ)
```

**Consistent with**: α = volatility · IC · score

#### Connecting Event Studies to Cross-Sectional IR

**Model parameters**:
- p: Probability event occurs each day
- IC(1): 1-day IC after event
- γ: Decay constant (IC(j) = IC(1) · γʲ)
- Half-life: HL = log(0.5) / log(γ)
- J: Trading days per year
- N: Number of assets

**Annual IC**:
```
IC(J) = IC(1) · σ · (1 - γ^J) / (√J · (1 - γ))
```

**Information Ratio**:
```
IR = IC(J) · √(N · p · J)
```

**Effective breadth**:
```
N* = N · p · J / [1 + p · (1-γ)/(1-γ^J)]
```

**Insight**: Rare events (small p) reduce effective breadth substantially.

**Example**: New CEO appointments
- p = 1/(7·252) = 0.00056 (once per 7 years)
- Even with N=1000 stocks, N* << N

### Data Mining Pitfalls

**The problem**: Given enough trials, noise looks like signal

**Statistics**:
- 1 regression on random data: 5% chance of |t| > 2
- 20 regressions on random data: 64% chance of at least one |t| > 2

**Lottery analogy** (Evelyn Adams):
- Narrow perspective: 1 in 17 trillion (her winning twice)
- Broad perspective: 1 in 30 (someone winning twice)

**Investment research**: Same issue!
- Try 20 variants of a signal
- One will look significant by chance
- Narrow focus on "the one that worked" is data mining

#### Four Guidelines to Avoid Data Mining

1. **Intuition First**
   - Have economic rationale BEFORE testing
   - Don't let data drive hypothesis
   - Example: Book-to-price (value) has fundamental justification

2. **Restraint in Testing**
   - Map out variations before testing
   - Limit number of trials
   - Each variation reduces confidence

3. **Sensible Performance**
   - IR > 2 for public equity data is suspicious
   - IR > 3 signals likely error or overfitting
   - In efficient markets, public info shouldn't yield huge alphas

4. **Out-of-Sample Testing**
   - Tune on 1980-1985, test on 1986-1990
   - Train on odd months, test on even months
   - True signal works out-of-sample; noise doesn't

---

## Chapter 13: The Information Horizon

### Definition: Information Half-Life

**Information horizon** = Half-life of forecasting ability

**Measurement**: Implement strategy with increasing delay
- Delay 0: Full IR
- Delay 1 month: IR₁
- Delay 2 months: IR₂
- etc.

**Half-life**: Time for IR to drop to 50% of original
```
HL = time when IR_delay = 0.5 · IR₀
```

**Exponential decay model**:
```
IR_j = γʲ · IR₀
```
where γ = decay factor per period

**Half-life relationship**:
```
HL = log(0.5) / log(γ)
```

**Example**: 
- γ = 0.8 per month
- HL = log(0.5)/log(0.8) = 3.1 months

**Value-added half-life**:
- Value added ∝ IR²
- HL_value = 0.5 · HL_IR

### Macroanalysis: Combining Current and Lagged Strategies

**Setup**: Two managers
- Manager Now: IR = 1.5
- Manager Later: IR = 1.2 (1-month lag, γ = 0.8)
- Both: active risk = 4%

**Question**: Optimal mix?

**Answer**: Depends on correlation of active returns

**Optimal weight on Now**:
```
w_Now = (1 - γ·ρ) / (1 - ρ²)
```

**Resulting IR**:
```
IR* = IR₀ · √[(1 + γ² - 2γρ) / (1 - ρ²)]
```

**Key cases**:
- ρ = γ (0.8): No improvement, w_Now = 100%
- ρ < γ (0.7): Diversification benefit, w_Now = 81.5%, w_Later = 18.5%
- ρ > γ (0.85): Hedging benefit, w_Now = 118.5%, w_Later = -18.5%

**General result**: Optimal mix makes correlation between adjacent portfolios equal to decay factor γ.

### Microanalysis: Combining Current and Lagged Signals

#### Two-Period Shelf Life

**Setup**:
- Signals arrive monthly
- Each signal predicts next 2 months
- IC₁ = 0.15 (first month)
- IC₂ = 0.075 (second month)

**Combined forecast**:
```
α = ω · (IC̃₁ · z(0) + IC̃₂ · z(-Δt))
```

**Adjusted ICs**:
```
IC̃₁ = (IC₁ - ρ·IC₂) / (1 - ρ²)

IC̃₂ = (IC₂ - ρ·IC₁) / (1 - ρ²)
```

**Combined IC**:
```
IC_combined² = (IC₁² + IC₂² + 2ρ·IC₁·IC₂) / (1 + ρ²)
```

**Critical point**: ρ = IC₂/IC₁ = 0.5
- Below: Diversification (add lagged signal, IC̃₂ > 0)
- Above: Hedging (subtract lagged signal, IC̃₂ < 0)
- Equal: Ignore lagged signal (IC̃₂ = 0)

#### Settling Old Scores: Using Past Returns

**Intuition**: If α = 2% predicted, and θ = 2% realized, is forecast complete?

**Answer**: Not necessarily! Realized return may be coincidental.

**Method**: Include past return as additional predictor
```
α(0,Δt) = ω·IC₁·z(0) + ω·IC₂·z(-Δt) + adjustment·θ(-Δt,0)
```

**Settled score** (simplified):
```
z*(-Δt) = z(-Δt) - (IC₁/IC₂) · (θ(-Δt,0)/ω)
```

**Effect**: Adjusts lagged signal for information already realized in past return.

#### Gradual Decay Model

**IC decay**:
```
IC(j) = IC₁ · δʲ
```

**Half-life**:
```
HL = log(0.5) / log(δ)
```

**Example**: Monthly signals, HL = 3 months
- δ = 0.7937
- IC(1) = 0.10
- IC(2) = 0.079
- IC(3) = 0.063
- IC(4) = 0.050

**Optimal mixing**:
```
z*(t) = z(t) + δ·z*(t-1)
```

**Result**: Weighted average of innovations, correlation between adjacent signals = δ

**IC for varying horizons**:
```
IC(0,t) = IC₁ · σ(θ_Δt) · (1 - δ^(t/Δt)) / (σ(θ_t) · (1 - δ))
         = IC₁ · (1 - δ^(t/Δt)) / (√(t/Δt) · (1 - δ))
```

**Peak correlation**: At horizon ≈ 2 × half-life

---

## Application to ARBS Signals

### Current ARBS Architecture

**Signals implemented**:
1. **CarrySignal** (Signals/Futures/CarrySignal.py)
   - Futures-specific: carry = (forward - spot) / spot
   - Persistent signal (high horizon)

2. **MomentumSignal** (Signals/Futures/MomentumSignal.py)
   - 12-month return rank
   - Time-series momentum
   - Medium horizon

3. **MeanReversionSignal** (Signals/Futures/MeanReversionSignal.py)
   - Short-term reversal
   - Low horizon

4. **SignalCombiner** (Signals/signal_combiner.py)
   - Combines multiple signals
   - Already implements IC-weighted combination

### Extending for Equities: Key Differences

#### 1. Cross-Sectional vs Time-Series Signals

**Futures** (current):
- Time-series signals (compare to own history)
- Each future analyzed independently
- Momentum: Is this future trending?
- Mean reversion: Did this future move too much recently?

**Equities** (needed):
- Cross-sectional signals (compare to universe)
- Rank-based within universe
- Momentum: Is this stock in top quartile of momentum?
- Value: Is this stock in top decile of book-to-price?

**Implementation in BaseSignal.py**:
```python
class BaseSignal:
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        """Calculate raw signals"""
        pass
    
    def to_cross_sectional_scores(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Convert to cross-sectional scores (mean 0, std 1)"""
        # Subtract cross-sectional mean
        # Divide by cross-sectional std dev
        return (signals - signals.mean()) / signals.std()
    
    def to_time_series_scores(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Convert to time-series scores (mean 0, std 1)"""
        # For each asset, subtract time-series mean
        # Divide by time-series std dev
        return (signals - signals.mean(axis=0)) / signals.std(axis=0)
```

#### 2. Sector-Neutral Signals

**Why**: Control for sector/industry effects in equities

**Implementation**:
```python
class SectorNeutralSignal(BaseSignal):
    def __init__(self, base_signal: BaseSignal, sector_map: Dict[str, str]):
        self.base_signal = base_signal
        self.sector_map = sector_map
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Calculate base signal
        raw_signals = self.base_signal.calculate(returns)
        
        # Demean within each sector
        neutral_signals = raw_signals.copy()
        for sector in set(self.sector_map.values()):
            sector_tickers = [t for t, s in self.sector_map.items() if s == sector]
            sector_mean = raw_signals[sector_tickers].mean(axis=1)
            neutral_signals[sector_tickers] = (
                raw_signals[sector_tickers].sub(sector_mean, axis=0)
            )
        
        return neutral_signals
```

#### 3. Fundamental vs Technical Signals

**Technical** (already have):
- Momentum (price-based)
- Mean reversion (price-based)
- Relative strength

**Fundamental** (need for equities):
- Value: Book-to-price, earnings yield, P/E ratio
- Quality: ROE, ROA, debt-to-equity
- Growth: Earnings growth, revenue growth
- Estimate revisions: Analyst estimate changes

**Example Value Signal**:
```python
class ValueSignal(BaseSignal):
    """Book-to-price value signal"""
    
    def __init__(self, book_value_data: pd.DataFrame, price_data: pd.DataFrame):
        self.book_value = book_value_data
        self.price = price_data
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        """Calculate B/P ratio"""
        dates = returns.index
        tickers = returns.columns
        
        # Align data
        bv = self.book_value.reindex(dates, method='ffill')
        px = self.price.reindex(dates)
        
        # B/P ratio
        bp_ratio = bv / px
        
        # Cross-sectional scores
        return self.to_cross_sectional_scores(bp_ratio)
    
    def get_ic(self) -> float:
        """Expected IC for value signals"""
        return 0.03  # Typical for U.S. equities, monthly rebalancing
```

**Example Quality Signal**:
```python
class QualitySignal(BaseSignal):
    """ROE-based quality signal"""
    
    def __init__(self, roe_data: pd.DataFrame):
        self.roe = roe_data
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        """Calculate ROE quality scores"""
        dates = returns.index
        
        # Align data
        roe = self.roe.reindex(dates, method='ffill')
        
        # Cross-sectional scores
        return self.to_cross_sectional_scores(roe)
    
    def get_ic(self) -> float:
        """Expected IC for quality signals"""
        return 0.04  # Typical for U.S. equities, monthly rebalancing
```

### Signal Combination for Equities

**Approach**: Use existing SignalCombiner, but with equity-specific signals

**Example**: Momentum + Value + Quality composite

```python
from Signals.signal_combiner import SignalCombiner
from Signals.Equities.MomentumSignal import EquityMomentumSignal
from Signals.Equities.ValueSignal import ValueSignal
from Signals.Equities.QualitySignal import QualitySignal

# Define signals
momentum = EquityMomentumSignal(lookback=252)  # 12-month
value = ValueSignal(book_value_data, price_data)
quality = QualitySignal(roe_data)

# Combine with IC weights
combiner = SignalCombiner(
    signals=[momentum, value, quality],
    weights="ic"  # Weight by information coefficient
)

# Calculate composite signal
composite_signal = combiner.calculate(returns)

# Feed to AlphaGenerator
from Signals.alpha_generator import AlphaGenerator

alpha_gen = AlphaGenerator(
    volatility_forecast=vol_estimator,
    signal=combiner
)

alphas = alpha_gen.generate_alphas(returns)
```

### Volatility Scaling: Do We Need It?

**Evidence from Chapter 11**: Most equity signals DON'T need volatility scaling.

**Test for your signal**:
1. Calculate time-series volatility of signal for each stock
2. Regress against stock volatility: `σ_TS(g_n) ~ a + b · ω_n`
3. Check R²:
   - R² > 0.3: Signal volatility ∝ stock volatility → **Don't scale**
   - R² < 0.1: Signal volatility independent → **Do scale**

**Current AlphaGenerator.py**:
```python
class AlphaGenerator:
    def __init__(self, volatility_forecast, signal, scale_by_volatility=False):
        self.vol = volatility_forecast
        self.signal = signal
        self.scale_by_volatility = scale_by_volatility
    
    def generate_alphas(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Get volatility forecasts
        vol = self.vol.forecast(returns)
        
        # Get IC and scores
        ic = self.signal.get_ic()
        scores = self.signal.calculate(returns)
        
        # Alpha = IC · score (or vol · IC · score)
        if self.scale_by_volatility:
            alphas = vol * ic * scores
        else:
            # Cross-sectional: already captures volatility
            alphas = ic * scores  # Proportional to ω·IC·z
        
        return alphas
```

**Recommendation**: Default `scale_by_volatility=False` for equity signals.

### IC Estimation and Shrinkage

**Problem**: Backtest IC may overestimate true IC.

**Solution**: Apply Bayesian shrinkage (Chapter 11)

```python
def shrink_ic(ic_estimated: float, n_months: int) -> float:
    """
    Shrink IC estimate to account for sampling error.
    
    Args:
        ic_estimated: Estimated IC from backtest
        n_months: Number of months in backtest
    
    Returns:
        Shrunk IC estimate
    """
    T = n_months
    ic2 = ic_estimated ** 2
    
    # Shrinkage factor (Eq 11.32 approximation)
    shrinkage = (T * ic2) / (T * ic2 + 2)
    
    return ic_estimated * shrinkage

# Example
ic_backtest = 0.08  # From 60-month backtest
ic_shrunk = shrink_ic(ic_backtest, 60)
# ic_shrunk ≈ 0.0345 (substantial shrinkage!)
```

**Apply in signal definition**:
```python
class ValueSignal(BaseSignal):
    def get_ic(self) -> float:
        # Estimated from backtest: IC = 0.05, T = 120 months
        ic_raw = 0.05
        ic_shrunk = shrink_ic(ic_raw, 120)
        return ic_shrunk  # ≈ 0.023
```

### Information Horizon for Equities

**Question**: How long do equity signals persist?

**Typical horizons** (half-life for U.S. equities):
- Earnings surprise: 1-2 weeks (very short)
- Short-term reversal: 2-4 weeks
- Momentum: 3-6 months (medium)
- Value: 12-24 months (long)
- Quality: 24+ months (very long)

**Combining signals with different horizons**:
```python
class MultiHorizonCombiner(SignalCombiner):
    def __init__(self, signals, half_lives):
        """
        Args:
            signals: List of signal objects
            half_lives: List of half-lives (in months)
        """
        self.signals = signals
        self.half_lives = half_lives
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Calculate each signal
        signal_scores = [s.calculate(returns) for s in self.signals]
        
        # Weight by IC and horizon
        # Longer horizon → use lagged signals
        for i, (scores, hl) in enumerate(zip(signal_scores, self.half_lives)):
            if hl > 1:  # Multi-period horizon
                # Combine current and lagged
                decay = 0.5 ** (1 / hl)  # From HL to decay factor
                signal_scores[i] = self._combine_with_lags(scores, decay)
        
        # IC-weighted combination
        return self._combine_signals(signal_scores)
```

### Rebalancing Frequency

**Trade-off**: Information decay vs transaction costs

**Grinold-Kahn guidance**:
- Rebalance frequency should match information frequency
- Daily information → daily rebalancing
- Monthly information → monthly rebalancing

**For equities**:
- High transaction costs (vs futures)
- Most fundamental signals: monthly or quarterly updates
- Technical signals: daily updates, but consider costs

**Optimal frequency**:
```
f_optimal = √(IR² · α² / (2 · TC · ω²))
```

Where:
- f: Rebalancing frequency (times per year)
- IR: Information ratio
- α: Annual alpha
- TC: Proportional transaction cost
- ω: Volatility

**Example**: 
- IR = 0.5, α = 2%, ω = 20%, TC = 0.5% (50 bps)
- f_optimal = √(0.25 · 0.0004 / (2 · 0.005 · 0.04)) ≈ 1.6 times/year

**Recommendation**: For most equity strategies, monthly or quarterly rebalancing is optimal.

---

## Links to Existing ARBS Code

### 1. BaseSignal.py
**Location**: `Signals/BaseSignal.py`

**Current interface**:
```python
class BaseSignal:
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        """Calculate raw signal scores"""
        raise NotImplementedError
    
    def get_ic(self) -> float:
        """Return information coefficient"""
        raise NotImplementedError
```

**Enhancements needed**:
- Add `to_cross_sectional_scores()` method
- Add `sector_neutral` parameter
- Add `horizon` property (in months)

### 2. AlphaGenerator.py
**Location**: `Signals/alpha_generator.py`

**Current implementation**:
```python
class AlphaGenerator:
    def generate_alphas(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Get vol, IC, scores
        vol = self.volatility_estimator.forecast(returns)
        ic = self.signal.get_ic()
        scores = self.signal.calculate(returns)
        
        # α = vol · IC · score
        alphas = vol * ic * scores
        
        return alphas
```

**Already implements**: Core Grinold-Kahn formula ✓

**Enhancements**:
- Add `scale_by_volatility` parameter (for equity signals)
- Add IC shrinkage option
- Support multiple time horizons

### 3. SignalCombiner.py
**Location**: `Signals/signal_combiner.py`

**Current implementation**: Combines signals with various weighting schemes
- Equal weighting
- IC weighting
- Optimization-based

**Already implements**: Chapter 10/11 signal combination ✓

**Enhancements**:
- Account for signal correlations (Eq 10.21-10.22)
- Add lagged signal combination (Chapter 13)
- Sector-neutral combination

### 4. Signals/Futures/MomentumSignal.py
**Location**: `Signals/Futures/MomentumSignal.py`

**Current**: Time-series momentum for futures

**Equity version needed**:
```python
class EquityMomentumSignal(BaseSignal):
    """Cross-sectional momentum (relative strength) for equities"""
    
    def __init__(self, lookback=252, skip_recent=21):
        """
        Args:
            lookback: Lookback period in days (default 12 months)
            skip_recent: Skip recent days (default 1 month)
                        Controls for short-term reversal
        """
        self.lookback = lookback
        self.skip_recent = skip_recent
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Calculate cumulative returns
        cum_returns = (1 + returns).rolling(self.lookback).apply(
            lambda x: x.prod() - 1
        )
        
        # Skip recent returns (reversal control)
        if self.skip_recent > 0:
            recent_returns = (1 + returns).rolling(self.skip_recent).apply(
                lambda x: x.prod() - 1
            )
            cum_returns = cum_returns / (1 + recent_returns) - 1
        
        # Cross-sectional ranking
        return self.to_cross_sectional_scores(cum_returns)
    
    def get_ic(self) -> float:
        # Typical IC for 12-month momentum, U.S. equities
        return 0.04
```

### 5. VolatilityEstimator.py
**Location**: `Signals/volatility_estimator.py`

**Current**: Exponentially-weighted volatility forecasting

**For equities**: Works as-is ✓

**Enhancement**: Add cross-sectional shrinkage (Ledoit-Wolf) if needed

### 6. Risk/LedoitWolfShrinkage.py
**Location**: `Risk/LedoitWolfShrinkage.py`

**Current**: Shrinkage covariance estimator for portfolio optimization

**For equities**: Critical for large universes (100+ stocks)

**Note**: Futures/swaps have small universes (~20 assets), less critical

---

## Equity Signal Examples

### 1. Momentum Signal

**Formula**:
```
score_n = rank((r_n,t-12:t-1 - r_n,t-1)) / N
```

**Properties**:
- Lookback: 12 months (252 days)
- Skip: 1 month (21 days) to avoid reversal
- Cross-sectional rank
- Expected IC: 0.03-0.05
- Horizon: 3-6 months

**Implementation**:
```python
class EquityMomentumSignal(BaseSignal):
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # 12-month return
        ret_12m = (1 + returns).rolling(252).apply(np.prod) - 1
        
        # Skip recent month
        ret_1m = (1 + returns).rolling(21).apply(np.prod) - 1
        momentum = ret_12m / (1 + ret_1m) - 1
        
        # Cross-sectional rank scores
        return self.to_cross_sectional_scores(momentum)
```

### 2. Value Signal (Book-to-Price)

**Formula**:
```
score_n = rank(BookValue_n / Price_n) / N
```

**Properties**:
- Quarterly updated book value
- Current price
- Cross-sectional rank (high B/P = high score)
- Expected IC: 0.02-0.04
- Horizon: 12-24 months

**Implementation**:
```python
class BookToPriceSignal(BaseSignal):
    def __init__(self, book_value: pd.DataFrame):
        self.book_value = book_value  # Quarterly data
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Forward-fill book value (quarterly → daily)
        bv = self.book_value.reindex(returns.index, method='ffill')
        
        # Price from returns (reconstruct)
        price = (1 + returns).cumprod()
        
        # B/P ratio
        bp_ratio = bv / price
        
        # Cross-sectional rank scores
        return self.to_cross_sectional_scores(bp_ratio)
```

**Alternative**: Earnings yield (E/P)
```python
class EarningsYieldSignal(BaseSignal):
    def __init__(self, earnings: pd.DataFrame):
        self.earnings = earnings  # Trailing 12-month earnings
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # E/P ratio
        price = (1 + returns).cumprod()
        ep_ratio = self.earnings.reindex(returns.index, method='ffill') / price
        
        # Cross-sectional rank scores
        return self.to_cross_sectional_scores(ep_ratio)
```

### 3. Quality Signal (ROE)

**Formula**:
```
score_n = rank(ROE_n) / N
```

**Properties**:
- ROE = Net Income / Book Equity
- Quarterly updated
- Cross-sectional rank
- Expected IC: 0.03-0.06
- Horizon: 18-36 months (very persistent)

**Implementation**:
```python
class ROESignal(BaseSignal):
    def __init__(self, roe: pd.DataFrame):
        self.roe = roe  # Quarterly ROE data
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Forward-fill ROE (quarterly → daily)
        roe_daily = self.roe.reindex(returns.index, method='ffill')
        
        # Cross-sectional rank scores
        return self.to_cross_sectional_scores(roe_daily)
```

**Alternative**: Profitability composite
```python
class ProfitabilitySignal(BaseSignal):
    def __init__(self, roe: pd.DataFrame, roa: pd.DataFrame, margin: pd.DataFrame):
        self.roe = roe
        self.roa = roa  # Return on assets
        self.margin = margin  # Profit margin
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # Z-score each component
        roe_z = self.to_cross_sectional_scores(
            self.roe.reindex(returns.index, method='ffill')
        )
        roa_z = self.to_cross_sectional_scores(
            self.roa.reindex(returns.index, method='ffill')
        )
        margin_z = self.to_cross_sectional_scores(
            self.margin.reindex(returns.index, method='ffill')
        )
        
        # Equal-weight composite
        return (roe_z + roa_z + margin_z) / 3
```

### 4. Estimate Revision Signal

**Formula**:
```
score_n = (EPS_forecast_n,t - EPS_forecast_n,t-1) / Price_n,t
```

**Properties**:
- Monthly change in consensus EPS estimate
- Scaled by price
- Cross-sectional rank
- Expected IC: 0.05-0.08 (higher than other signals!)
- Horizon: 1-3 months (short)

**Implementation**:
```python
class EstimateRevisionSignal(BaseSignal):
    def __init__(self, eps_forecasts: pd.DataFrame):
        self.eps_forecasts = eps_forecasts  # Consensus EPS estimates
    
    def calculate(self, returns: pd.DataFrame) -> pd.DataFrame:
        # 1-month change in estimates
        eps_change = self.eps_forecasts.diff(21)  # 21 trading days
        
        # Price
        price = (1 + returns).cumprod()
        
        # Standardized surprise
        revision = eps_change / price
        
        # Cross-sectional rank scores
        return self.to_cross_sectional_scores(revision)
    
    def get_ic(self) -> float:
        # Estimate revision has higher IC than other signals
        return 0.06
```

### 5. Composite Alpha: Combining Signals

**Strategy**: Momentum + Value + Quality

```python
from Signals.signal_combiner import SignalCombiner

# Define component signals
momentum = EquityMomentumSignal(lookback=252, skip_recent=21)
value = BookToPriceSignal(book_value_data)
quality = ROESignal(roe_data)

# Combine with IC weighting
combiner = SignalCombiner(
    signals=[momentum, value, quality],
    weights="ic"  # Automatically weights by get_ic()
)

# Calculate composite signal
composite_scores = combiner.calculate(returns)

# Expected combined IC (uncorrelated signals)
ic_momentum = 0.04
ic_value = 0.03
ic_quality = 0.05
ic_combined = np.sqrt(ic_momentum**2 + ic_value**2 + ic_quality**2)
# ic_combined ≈ 0.071

# Feed to AlphaGenerator
alpha_gen = AlphaGenerator(
    volatility_forecast=vol_estimator,
    signal=combiner,
    scale_by_volatility=False  # Equity signals don't need scaling
)

alphas = alpha_gen.generate_alphas(returns)
```

**Expected performance**:
- IC: 0.07 (combined)
- Breadth: 50 stocks × 12 rebalances/year = 600
- IR = IC × √BR = 0.07 × √600 ≈ 1.7

---

## Open Questions

### 1. Which Equity Signals to Prioritize?

**Tier 1** (start here):
- Momentum (12-month relative strength)
- Value (book-to-price or earnings yield)
- Quality (ROE or profitability composite)

**Rationale**: Well-documented, robust, complementary

**Tier 2** (add later):
- Estimate revisions (requires analyst data)
- Short-term reversal
- Low volatility (quality variant)

### 2. Sector-Neutral vs Market-Neutral?

**Market-neutral**: Zero beta to market
- Easier to implement
- Lower risk
- Lower expected return

**Sector-neutral**: Zero exposure to each sector
- More conservative
- Controls for sector rotation
- May reduce signal strength

**Recommendation**: Start market-neutral, add sector controls if needed.

### 3. Daily vs Monthly Rebalancing?

**Trade-offs**:
| Frequency | Pros | Cons |
|-----------|------|------|
| Daily     | Capture short-horizon signals | High transaction costs |
| Weekly    | Balance costs and timeliness | Complex to implement |
| Monthly   | Low costs, matches data | Miss short-term opportunities |

**Data availability**:
- Fundamental data (B/P, ROE): Quarterly updates → monthly rebalance
- Technical data (momentum): Daily updates → daily/weekly possible

**Recommendation**: 
- Start with monthly rebalancing
- Measure signal half-lives
- Optimize frequency based on costs vs value added

### 4. Universe Selection?

**Options**:
- S&P 500 (large cap, liquid)
- Russell 1000 (large + mid cap)
- Russell 3000 (entire U.S. market)

**Considerations**:
- Smaller stocks: Higher alphas, higher costs
- Larger stocks: Lower alphas, more liquid
- ARBS focus: MVP first, so start narrow

**Recommendation**: S&P 500 or Russell 1000 for MVP.

### 5. Factor Model for Risk?

**Current ARBS**: Uses sample covariance with Ledoit-Wolf shrinkage

**For equities**: Could use factor model (BARRA, Fama-French)
- More stable covariance estimates
- Better for large universes (100+ stocks)
- Additional data requirements

**Recommendation**: Start with Ledoit-Wolf (already implemented), add factor models later if needed.

### 6. How to Handle Missing Data?

**Fundamental data**: Quarterly updates, reporting lags
- Forward-fill last known value
- Flag stale data (> 90 days old)

**Price data**: May have gaps
- Forward-fill for short gaps (< 5 days)
- Drop assets with longer gaps

**Example**:
```python
def prepare_fundamental_data(data: pd.DataFrame, max_age_days: int = 90) -> pd.DataFrame:
    """Prepare fundamental data with staleness checks"""
    # Forward fill
    filled = data.ffill()
    
    # Calculate staleness
    last_update = data.notna().apply(lambda x: x.index[x][-1] if x.any() else pd.NaT)
    staleness = (data.index[-1] - last_update).days
    
    # Mask stale data
    filled[staleness > max_age_days] = np.nan
    
    return filled
```

---

## Summary: Key Takeaways for ARBS

### 1. Core Formula is Universal
```
α = volatility · IC · score
```
Works for futures, swaps, AND equities. AlphaGenerator already implements this ✓

### 2. Cross-Sectional Scores for Equities

Most equity signals:
- Compare across stocks (not to own history)
- Don't need additional volatility scaling
- Signal volatility ∝ stock volatility automatically

**Action**: Add `scale_by_volatility=False` default for equity signals.

### 3. IC Ranges for Equities

**Realistic expectations**:
- Single signal: IC = 0.02 - 0.05
- Good signal: IC = 0.05 - 0.08
- Great signal: IC > 0.08
- Multiple signals combined: IC = 0.05 - 0.10

**Action**: Don't expect miracles. IC = 0.05 is good!

### 4. Signal Combination

Combining uncorrelated signals:
```
IC_combined = √(IC₁² + IC₂² + ... + IC_k²)
```

**Action**: SignalCombiner already supports this ✓

### 5. Shrinkage is Critical

Even 120-month backtests need shrinkage:
- IC = 0.10 backtest → IC ≈ 0.055 forward
- IC = 0.05 backtest → IC ≈ 0.023 forward

**Action**: Implement IC shrinkage in signal classes.

### 6. Information Horizon Matters

- Short horizon (reversal): Days to weeks
- Medium horizon (momentum): Months
- Long horizon (value): Years

**Action**: 
- Store `horizon` property in signals
- Use lagged signals for multi-period horizons
- Match rebalancing frequency to horizon

### 7. Data Mining is Easy

- 20 trials of noise → 64% chance of false positive
- Out-of-sample testing is mandatory
- IR > 2 for public equity data is suspicious

**Action**: 
- Document all signal variants tested
- Hold out test set
- Be skeptical of high ICs

### 8. Transaction Costs Matter

Equities have higher costs than futures:
- Proportional costs: 10-50 bps per trade
- Impact costs: Scale with trade size
- Optimal rebalancing: Monthly or quarterly

**Action**: Add transaction cost model to backtests.

---

## Next Steps for ARBS Equity Extension

### Phase 1: Core Infrastructure (MVP)
1. Create `Signals/Equities/` directory
2. Implement `EquityMomentumSignal`
3. Implement `BookToPriceSignal`
4. Implement `ROESignal`
5. Add `to_cross_sectional_scores()` to BaseSignal
6. Add IC shrinkage utility

### Phase 2: Signal Validation
1. Backtest each signal individually (S&P 500, 2000-2023)
2. Measure realized ICs
3. Calculate information horizons
4. Apply shrinkage to forward ICs

### Phase 3: Combination & Risk
1. Combine signals using SignalCombiner
2. Test Ledoit-Wolf covariance on equity universe
3. Build sector-neutral variants
4. Optimize rebalancing frequency

### Phase 4: Production
1. Add transaction cost model
2. Implement capacity constraints
3. Build equity tear sheets
4. Document equity strategy templates

---

**End of Part 3 Notes**
