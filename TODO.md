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

### 🔄 In Progress

- [ ] Minimal Backtest Loop
  - Load historical data (or use mock data)
  - For each date:
    1. Generate signals (CarrySignal)
    2. Estimate covariance (LedoitWolfShrinkage)
    3. Optimize weights (MeanVarianceOptimizer)
    4. Track positions and P&L
  - Output: Returns time series, IC, Sharpe ratio

### 📋 Pending (Minimal)

- [ ] End-to-End Measurement
  - Run backtest on futures data
  - Calculate realized IC (may be negative, that's okay)
  - Calculate realized Sharpe (may be negative, that's okay)
  - **Goal**: Verify system works end-to-end with real numbers

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

### Additional Signals
- Momentum
- Mean reversion
- Volatility
- Multi-signal combination

### Advanced Covariance
- 3-factor PCA (for highly correlated assets)
- Nodewise regression (2025 research)
- Dynamic covariance (time-varying)

## Test Count: 157 passing

- Futures: 44 tests
- Signals: 31 tests
- Risk: 22 tests
- Optimizer: 18 tests
- Adapter: 8 tests
- Other: 34 tests

## Architecture

```
Data Layer:         Query/Futures (MockFuture objects)
                         ↓
Adapter Layer:      Adapter/FuturesAdapter (DataFrame)
                         ↓
Signal Layer:       Signals/Futures (CarrySignal → alphas)
                         ↓
Risk Layer:         Risk/Covariance (LedoitWolf → Σ)
                         ↓
Optimizer Layer:    Optimizer/MeanVariance (alphas + Σ → weights)
                         ↓
Backtest Layer:     (TODO) Track positions, calculate P&L, measure IC
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
