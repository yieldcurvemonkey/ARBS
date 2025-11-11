# TODO - MVP Backtesting System

## MVP Goal

**Build a minimal end-to-end backtest that measures correctly.**

- ✅ NOT required: Positive IC or profitable strategy
- ✅ Required: Accurate measurement of what actually happens
- If strategy loses money, that's fine - we measure it correctly

## Phase 1: Minimal Implementation (Current)

### ✅ Completed

- [x] Query Infrastructure (FuturesQuery, structures, value maps)
  - 44 tests passing
  - OUTRIGHT, CALENDAR, PACK, BUNDLE structures
  - PRICE, IMPLIED_RATE, NPV, DV01 calculations

- [x] Signals Module (BaseSignal, CarrySignal, IC)
  - 31 tests passing
  - Standardized alpha generation (z-scores)
  - IC calculation (Pearson, Spearman, significance)
  - Carry signal: annualized carry in bps/year

- [x] Risk Module (Covariance estimators)
  - 22 tests passing
  - SampleCovariance (baseline)
  - LedoitWolfShrinkage (industry standard, >5000 citations)
  - Comparison utilities

- [x] Optimizer Module (Mean-variance)
  - 18 tests passing
  - Markowitz 1952 implementation
  - Budget, leverage, position constraints
  - Scales to 50+ assets with Ledoit-Wolf

- [x] Adapter Module (Query → Signals bridge)
  - 8 tests passing
  - Converts FuturesQuery → signal-ready DataFrame
  - Extracts prices, next_prices, roll_dates
  - Handles calendar spreads

- [x] Minimal Backtest Loop
  - 12 tests passing
  - Complete Query→Adapter→Signals→Risk→Optimizer→Backtest pipeline
  - For each date:
    1. Generate signals (CarrySignal)
    2. Estimate covariance (LedoitWolfShrinkage)
    3. Optimize weights (MeanVarianceOptimizer)
    4. Track positions and P&L
  - Output: BacktestResult with returns, IC, Sharpe ratio, weights, prices

- [x] End-to-End Measurement
  - ✅ MVP COMPLETE!
  - End-to-end example: `examples/run_minimal_backtest.py`
  - Full pipeline executed successfully
  - IC, Sharpe, returns all calculated correctly
  - **Goal achieved**: System measures correctly regardless of profitability

## 🎉 MVP COMPLETE

**The minimal viable backtest is working end-to-end!**

All components integrated:
1. Query → FuturesQuery gets contract prices
2. Adapter → Converts to signal-ready format
3. Signals → CarrySignal generates alphas
4. Risk → LedoitWolfShrinkage estimates covariance
5. Optimizer → MeanVarianceOptimizer calculates weights
6. Backtest → Tracks positions and measures P&L

**Measurement philosophy achieved:**
- System measures accurately (not just when profitable)
- IC can be positive or negative (we measure it honestly)
- Sharpe can be positive or negative (we track it correctly)
- Returns tracked with proper position accounting

## Architecture V2: Returns-First Refactoring (COMPLETE)

**Goal: Align with Grinold-Kahn framework - alphas from returns, not prices**

### ✅ Completed (333 additional tests)

- [x] Returns Calculation
  - ReturnsCalculator (simple returns, log returns, period conversion)
  - Proper handling of NaN, zeros, negatives
  - 16 tests passing

- [x] Volatility Estimation
  - VolatilityEstimator (Realized, EWMA)
  - Standardized interface for multiple estimators
  - Annualization and scaling logic
  - 18 tests passing

- [x] Alpha Generation (Grinold-Kahn Compliant)
  - AlphaGenerator: IC × Vol × Z-score
  - Transform raw signals → expected returns
  - Proper dimensionality (bps/day or % return)
  - 16 tests passing

- [x] Portfolio Architecture
  - Portfolio as composite Asset (nested support)
  - Returns-first: calculates returns, not prices
  - Composition engine for weighted combinations
  - 100 tests passing

- [x] TearSheet Analysis
  - Comprehensive performance metrics
  - Risk-adjusted returns (Sharpe, Sortino, Calmar)
  - Drawdown analysis
  - 19 tests passing

- [x] Integration Testing
  - End-to-end returns flow validation
  - Cross-validation against MVP V1
  - Alpha generation pipeline tests
  - 8 tests passing

- [x] Additional Signals
  - MomentumSignal (trend-following)
  - MeanReversionSignal (statistical arbitrage)
  - SignalCombiner (multi-signal strategies)
  - 156 tests passing

**Architecture V2 Achievement:**
- System now generates alphas from returns (Grinold-Kahn compliant)
- Proper volatility scaling (IC × Vol × Z)
- Portfolio composition with nested assets
- Comprehensive performance analysis
- Multiple signal types implemented (Carry, Momentum, Mean Reversion)
- All tests passing (502 total)

### 📋 Future Enhancements (Not Required for MVP)

## Phase 2: Maximal Enhancements (Later)

### Transaction Costs
- Proportional costs (bps per trade)
- Quadratic impact costs (for large trades)
- Integrate into optimizer objective

### Risk Constraints
- DV01 limits (fixed income portfolios)
- Sector/factor exposure limits
- Volatility targeting

### Advanced Constraints
- Cardinality (L0 penalty - limit number of positions)
- Turnover constraints
- Holding period minimums

### Additional Signals (Beyond Current Implementation)
- Curve positioning signals (steepeners, flatteners, butterflies)
- Basis arbitrage (futures vs swaps)
- Volatility regime signals
- Advanced multi-factor combinations

### Advanced Covariance
- 3-factor PCA (for highly correlated assets)
- Nodewise regression (2025 research)
- Dynamic covariance (time-varying)

## Test Count: 502 passing ✅

### MVP V1 Components (169 tests)
- Futures: 44 tests
- Signals: 31 tests
- Risk: 22 tests
- Optimizer: 18 tests
- Adapter: 8 tests
- Backtest: 12 tests
- Other: 34 tests

### Architecture V2 Components (333 tests)
- Returns: 16 tests
- Volatility: 18 tests
- AlphaGenerator: 16 tests
- Portfolio: 100 tests
- TearSheet: 19 tests
- Integration: 8 tests
- Additional Signals: 156 tests (Momentum, Mean Reversion, Combiner)

## Architecture

### V1: Price-Based Flow (Original MVP)
```
Data Layer:         Query/Futures (MockFuture objects)
                         ↓
Adapter Layer:      Adapter/FuturesAdapter (DataFrame with prices)
                         ↓
Signal Layer:       Signals/Futures (CarrySignal → alphas)
                         ↓
Risk Layer:         Risk/Covariance (LedoitWolf → Σ)
                         ↓
Optimizer Layer:    Optimizer/MeanVariance (alphas + Σ → weights)
                         ↓
Backtest Layer:     Backtest/MinimalBacktest (track positions, P&L, IC)
                         ↓
                    BacktestResult (returns, IC, Sharpe, total return)
```

### V2: Returns-First Flow (Grinold-Kahn Compliant)
```
Data Layer:         Asset/Portfolio (prices or nested assets)
                         ↓
Returns Layer:      ReturnsCalculator (prices → returns)
                         ↓
Volatility Layer:   VolatilityEstimator (returns → realized/EWMA vol)
                         ↓
Signal Layer:       Raw signals (carry, momentum, etc.)
                         ↓
Alpha Layer:        AlphaGenerator (IC × Vol × Z → expected returns)
                         ↓
Risk Layer:         Risk/Covariance (returns → Σ)
                         ↓
Optimizer Layer:    Optimizer/MeanVariance (alphas + Σ → weights)
                         ↓
Portfolio Layer:    Portfolio composition (weighted assets)
                         ↓
Analysis Layer:     TearSheet (Sharpe, Sortino, Calmar, drawdowns)
```

## Key Principles

1. **Test-Driven Development (TDD)**
   - Design tests from business perspective first
   - Then implement to make tests pass
   - All modules have comprehensive test coverage

2. **Measure Correctly, Not Optimistically**
   - MVP goal is accurate measurement
   - Not required: positive IC or profits
   - If strategy loses money, we measure it accurately

3. **Minimal → Maximal**
   - Start with simplest working implementation
   - Add complexity only when needed
   - Each feature tested before moving forward

4. **Production Quality**
   - ABOUTME comments on all files
   - Type hints and docstrings
   - Error handling and edge cases
   - Clean git history with descriptive commits
