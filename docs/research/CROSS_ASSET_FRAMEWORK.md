# Cross-Asset Risk Framework: Equities ↔ Global Macro

**Date**: 2025-11-13
**Status**: Architectural Design

---

## Executive Summary

**Core Insight**: Equity sector rotation models and global macro currency trading share identical mathematical structures. The factor decomposition and risk management techniques developed for equity sectors can be directly applied to multi-currency fixed income portfolios.

**Key Equivalence**:
```
Equity Sector Model          Global Macro Model
──────────────────────       ──────────────────
Sector (Tech, Finance)   ↔   Currency (USD, EUR)
Stock (AAPL, NVDA)       ↔   Tenor Point (2Y, 10Y)
Sector ETF (XLK)         ↔   Currency Index
Intra-sector correlation ↔   Intra-currency correlation
Cross-sector correlation ↔   Cross-currency correlation
Sector beta              ↔   Currency factor
```

---

## Mathematical Foundation

### Factor Decomposition

**Equity model** (Grinold-Kahn 1999):
```
r_i,t = β_sector * r_sector,t + β_market * r_market,t + ε_i,t
```

Where:
- r_i,t = return of stock i at time t
- β_sector = exposure to sector factor
- β_market = exposure to market factor
- ε_i,t = idiosyncratic return

**Global macro equivalent**:
```
r_tenor,currency,t = β_currency * r_currency,t + β_global * r_global,t + ε_tenor,currency,t
```

Where:
- r_tenor,currency,t = return of a specific tenor point in a currency
- β_currency = exposure to currency-specific factor
- β_global = exposure to global rates factor (e.g., Fed policy)
- ε_tenor,currency,t = idiosyncratic return (curve positioning)

**Identical structure!** The same risk decomposition applies.

---

## Covariance Structure

### Block Diagonal Decomposition

**Equity sectors** (Žignić et al. 2024):
```
Σ_equity = [
    [Σ_Tech,     0,          0,        ...]
    [0,          Σ_Finance,  0,        ...]
    [0,          0,          Σ_Energy, ...]
    ...
]
```

Where:
- Σ_Tech = covariance among tech stocks (AAPL, MSFT, NVDA, ...)
- High correlation within blocks, low between blocks

**Global macro equivalent**:
```
Σ_macro = [
    [Σ_USD,  0,       0,      ...]
    [0,      Σ_EUR,   0,      ...]
    [0,      0,       Σ_GBP,  ...]
    ...
]
```

Where:
- Σ_USD = covariance among USD curve points (2Y, 5Y, 10Y, 30Y)
- High correlation within currency (same curve)
- Lower correlation across currencies

### Off-Diagonal Correlations

**Reality**: Pure block-diagonal is too restrictive.

**Stochastic Block Model** (Chen et al. 2025):
```
Σ_full = α * Σ_block_diagonal + (1-α) * Σ_full_covariance
```

Where α ∈ [0,1] controls sparsity.

**Critical for macro**: EUR and CHF correlate highly (ECB/SNB coordination), so cross-currency blocks cannot be zero.

**Example correlation matrix** (simplified):
```
           USD_2Y  USD_10Y  EUR_2Y  EUR_10Y
USD_2Y     1.00    0.85     0.60    0.50
USD_10Y    0.85    1.00     0.55    0.70
EUR_2Y     0.60    0.55     1.00    0.88
EUR_10Y    0.50    0.70     0.88    1.00
```

Within-currency correlations (0.85-0.88) > cross-currency (0.50-0.70).

---

## Portfolio Constraints

### The Selection Problem

**Equity sectors**: Mean reversion of sector vs SPY.
- Can't short EVERY sector simultaneously (they sum to SPY)
- Need to select which sectors to overweight/underweight

**Global macro**: Mean reversion of butterflies per currency.
- **Can't short the 5Y on 2-5-10 butterfly in EVERY currency**
- Correlations across currencies constrain trade selection

### Mathematical Formulation

**Constraint**: Limit concentration in correlated assets.

For a set of N highly correlated instruments (ρ > 0.85):
```
sum(|w_i| * I(|w_i| > threshold)) ≤ max_positions
```

Where:
- w_i = weight in asset i
- I(·) = indicator function
- max_positions = risk budget for this correlation cluster

**Example**:
- EUR/CHF 5Y butterflies: max 2 positions (cluster size = 3)
- USD/GBP 5Y butterflies: max 2 positions (cluster size = 3)
- Prevents over-concentration in same trade across currencies

---

## Implementation in ARBS

### Current Capabilities

✅ **Query Layer**: Supports both equities and futures
- `Query/Equities/EquityQuery.py`
- `Query/Futures/FuturesQuery.py`

✅ **Sector Rotation**: Fully implemented
- `Signals/SectorRotation/SectorMomentumSignal.py`
- `Signals/SectorRotation/SectorReversionSignal.py`
- `Signals/SectorRotation/CrossSectionalNeutralizer.py`

✅ **Sector-Based Covariance**: Three estimators
- `Risk/Covariance/SectorBased/BlockDiagonal/` (Žignić et al.)
- `Risk/Covariance/SectorBased/TwoStep/` (García-Medina et al.)
- `Risk/Covariance/SectorBased/StochasticBlock/` (Chen et al.)

✅ **Portfolio Construction**: Long/short with constraints
- `Signals/SectorRotation/SectorLongShortPortfolio.py`
- Supports n_long, n_short selection
- Dollar-neutral enforcement

### Implementation Gaps

❌ **Correlation cluster constraints in optimizer**
- Current: `MeanVarianceOptimizer` doesn't limit positions per cluster
- Needed: Add cluster-aware constraints

❌ **Volatility dispersion signals**
- Current: No IV/RV ratio tracking
- Needed: `CorrelationVolatilitySignal` (see `CORRELATION_VOLATILITY_ARBITRAGE.md`)

❌ **Cross-currency RV strategies**
- Current: Only intra-currency butterflies
- Needed: Cross-currency basis trades

❌ **Dynamic cluster detection**
- Current: Sectors are predefined
- Needed: Detect correlation clusters dynamically (time-varying)

---

## Detailed Mapping

### Level 1: Asset Hierarchy

| Equity | Global Macro | Description |
|--------|--------------|-------------|
| Market (SPY) | Global rates (Fed funds) | Top-level systematic factor |
| Sector (Tech) | Currency (USD) | Mid-level factor (regional/sector) |
| Stock (AAPL) | Tenor (USD 10Y) | Granular asset |

### Level 2: Factor Exposure

| Equity Beta | Macro Beta | Interpretation |
|-------------|------------|----------------|
| β_market = 1.2 | β_global = 1.1 | Asset moves 20% more than market |
| β_sector = 1.5 | β_currency = 1.4 | Asset moves 50% more than sector |
| β_size = -0.3 | β_carry = -0.2 | Negative exposure to size/carry factor |

### Level 3: Mean Reversion Strategies

| Equity Strategy | Macro Strategy | Logic |
|----------------|----------------|-------|
| Sector vs SPY mean reversion | Butterfly mean reversion | Relative value within hierarchy |
| Long Tech, Short Finance | Long EUR butterfly, Short USD butterfly | Cross-sectional positioning |
| Pairs trading (AAPL/MSFT) | Pairs trading (EUR 5Y / CHF 5Y) | Intra-sector/currency mean reversion |

### Level 4: Risk Management

| Equity Risk | Macro Risk | Implementation |
|-------------|-----------|----------------|
| Sector concentration limit | Currency concentration limit | Max positions per cluster |
| Market-neutral constraint | Duration-neutral constraint | Net exposure = 0 |
| Long/short leverage limit | Gross notional limit | Total exposure ≤ threshold |
| Factor risk decomposition | DV01 by currency | Attribution by factor |

---

## Concrete Example: Sector Rotation → Currency Rotation

### Equity Sector Rotation (Yang & Shi 2023)

**Universe**: 11 SPDR sector ETFs
- XLK (Tech), XLF (Finance), XLE (Energy), XLV (Healthcare), ...

**Signal**: Momentum + mean reversion
1. Calculate 12-month momentum per sector
2. Rank sectors by momentum
3. Long top 3, short bottom 3
4. Equal-weighted, dollar-neutral

**Risk model**: Block-diagonal covariance
- Tech stocks correlate highly (ρ ≈ 0.85)
- Cross-sector correlation lower (ρ ≈ 0.40)

**Result**: Sharpe 0.8, IC 0.15

### Global Macro Translation

**Universe**: 4 currencies × 4 tenors = 16 instruments
- USD (2Y, 5Y, 10Y, 30Y)
- EUR (2Y, 5Y, 10Y, 30Y)
- GBP (2Y, 5Y, 10Y, 30Y)
- JPY (2Y, 5Y, 10Y, 30Y)

**Signal**: Carry + mean reversion
1. Calculate carry per tenor (forward - spot)
2. Rank butterflies by carry
3. Long top 3 butterflies, short bottom 3
4. Equal-weighted, DV01-neutral

**Risk model**: Stochastic block covariance
- USD curve points correlate highly (ρ ≈ 0.88)
- Cross-currency same tenor moderate (ρ ≈ 0.60)
- Cross-currency different tenor low (ρ ≈ 0.35)

**Expected**: Similar Sharpe/IC as equity sector rotation

---

## Academic Support

### Equity Sector Research

1. **Žignić et al. (2024)**: "Eigenportfolios for varying risk aversion"
   - Block-diagonal covariance improves Sharpe by 15%
   - Factor model separates systematic vs idiosyncratic risk

2. **Yang & Shi (2023)**: "Sector rotation with machine learning"
   - Momentum + reversion signals → Sharpe 0.8
   - Top 3 / bottom 3 heuristic outperforms mean-variance

3. **García-Medina et al. (2024)**: "Hierarchical clustering of S&P 500"
   - Two-step covariance (clustering + RMT) → best out-of-sample
   - HHI (diversification) improves by 18%

### Fixed Income Research

1. **Litterman & Scheinkman (1991)**: "Common factors affecting bond returns"
   - Level, slope, curvature explain 98% of variance
   - Same structure as equity factor models

2. **Ilmanen (1995)**: "Time-varying expected returns in international bond markets"
   - Cross-country correlations driven by common global factor
   - Country-specific factors add 15-25% additional variance

3. **Brennan & Xia (2000)**: "Stochastic convenience yield and bond pricing"
   - Term structure mean reversion across currencies
   - Carry trades = sector rotation in global macro

### Cross-Asset Research

1. **Distaso, Mele & Vilkov (2020)**: "Cross-section without factors"
   - Correlation risk premium exists across asset classes
   - Average correlation explains cross-sectional returns

2. **Koijen et al. (2018)**: "A demand system approach to asset pricing"
   - Common demand shocks create cross-asset correlations
   - Flow-based factors work across equities, bonds, FX

---

## Implementation Plan

### Phase 1: Extend Current Framework

**Goal**: Make existing sector rotation code work for global macro.

**Tasks**:
1. Create `CurrencyQuery` analogous to `EquityQuery`
   - Currencies = sectors
   - Tenors = stocks
2. Adapt `SectorMomentumSignal` → `CurrencyCarrySignal`
   - Momentum → Carry
   - Same z-score normalization
3. Adapt `SectorLongShortPortfolio` → `CurrencyLongShortPortfolio`
   - Same top-N/bottom-N selection
   - DV01-neutral instead of dollar-neutral

**Deliverable**: Working currency rotation backtest.

### Phase 2: Add Correlation Constraints

**Goal**: Prevent over-concentration in correlated trades.

**Tasks**:
1. Implement correlation cluster detection
   - Extend `SectorBasedCovarianceEstimator`
   - Add `get_correlation_clusters()` method
2. Add cluster constraints to optimizer
   - Extend `MeanVarianceOptimizer`
   - Constraint: max_positions_per_cluster
3. Test on synthetic data
   - Verify constraints bind correctly
   - Check optimization still converges

**Deliverable**: Optimizer respects correlation structure.

### Phase 3: Volatility Dispersion

**Goal**: Trade IV/RV ratio convergence across correlated assets.

**Tasks**:
1. Implement `VolatilityRatioCalculator`
   - Calculate IV/RV per asset
   - Track time series
2. Implement `CorrelationVolatilitySignal`
   - Identify high-correlation pairs
   - Calculate spread z-scores
   - Generate signals
3. Backtest on equity sector ETFs
   - XLK, XLF, etc. with options data
   - Measure IC, Sharpe, turnover

**Deliverable**: Volatility dispersion strategy working.

### Phase 4: Cross-Currency RV

**Goal**: Trade relative value across currencies.

**Tasks**:
1. Implement cross-currency basis signals
   - EUR/USD 5Y vs EUR/GBP 5Y
   - Conditional on correlation > 0.75
2. Add cross-currency constraints
   - Max 2 trades per currency pair cluster
3. Backtest on historical data
   - Validate IC and Sharpe
   - Compare to single-currency strategies

**Deliverable**: Multi-currency RV portfolio.

### Phase 5: Dynamic Clustering

**Goal**: Adapt cluster structure as correlations change.

**Tasks**:
1. Implement time-varying cluster detection
   - Rolling window correlation
   - Adaptive cluster count
2. Update constraints dynamically
   - Rebalance cluster assignments monthly
3. Backtest adaptive vs static clusters
   - Measure improvement in risk-adjusted returns

**Deliverable**: Adaptive correlation-aware portfolio.

---

## Testing & Validation

### Synthetic Data Tests

**Goal**: Verify implementation correctness before using real data.

**Test 1**: Perfect block-diagonal
- 3 sectors, 5 stocks each, ρ_within = 0.95, ρ_across = 0.0
- Expected: Block-diagonal covariance
- Constraint should prevent > 3 positions in same sector

**Test 2**: Stochastic block
- 3 sectors, 5 stocks each, ρ_within = 0.90, ρ_across = 0.40
- Expected: Off-diagonal blocks non-zero
- Optimizer should still respect cluster constraints

**Test 3**: IV/RV convergence
- 2 correlated assets (ρ = 0.95)
- Divergent IV/RV ratios: asset A = 1.2, asset B = 1.5
- Expected: Signal to sell B vol, buy A vol

### Real Data Validation

**Equity test**:
- Universe: 11 SPDR sector ETFs (2015-2024)
- Signal: Momentum + mean reversion (Yang & Shi 2023)
- Risk: Block-diagonal covariance (Žignić et al. 2024)
- Target: Sharpe > 0.7, IC > 0.10

**Macro test**:
- Universe: USD, EUR, GBP curves (2Y, 5Y, 10Y, 30Y) (2015-2024)
- Signal: Carry + mean reversion
- Risk: Stochastic block covariance (Chen et al. 2025)
- Target: Sharpe > 0.6, IC > 0.08

---

## Key Risks & Mitigations

### Risk 1: Correlation Breakdown

**Problem**: Correlations change during crises, hedge fails.

**Example**: 2008 crisis, cross-currency correlations → 1.0 (flight to quality).

**Mitigation**:
- Monitor rolling correlation
- Reduce positions when correlation drops
- Add correlation regime detection

### Risk 2: IV/RV Ratio Persistence

**Problem**: Spread widens instead of converging.

**Example**: Equity vol stays elevated after shock (2020 COVID).

**Mitigation**:
- Add spread-widening stop-loss
- Monitor volga (convexity of vol exposure)
- Reduce size as spread exceeds 3σ

### Risk 3: Liquidity Asymmetry

**Problem**: Can't exit both legs of pair trade simultaneously.

**Example**: Macro: EUR options liquid, CHF options illiquid.

**Mitigation**:
- Weight by liquidity (ADV, bid-ask spread)
- Add execution cost model
- Reduce position size in illiquid pairs

### Risk 4: Regime Changes

**Problem**: Factor structure changes (e.g., sector rotation stops working).

**Example**: Tech bubble 2000, momentum reversed.

**Mitigation**:
- Combine multiple signals (momentum + value + quality)
- Monitor IC decay over time
- Implement adaptive signal weighting

---

## Success Metrics

### Performance Targets

| Metric | Equity Sector | Global Macro | Combined |
|--------|---------------|--------------|----------|
| **Sharpe Ratio** | > 0.7 | > 0.6 | > 0.8 |
| **Information Coefficient (IC)** | > 0.10 | > 0.08 | > 0.12 |
| **Turnover** | < 50% per month | < 30% per month | < 40% per month |
| **Max Drawdown** | < 20% | < 15% | < 18% |
| **Correlation to SPY** | < 0.3 | < 0.2 | < 0.25 |

### Risk Metrics

| Metric | Target | Explanation |
|--------|--------|-------------|
| **Cluster concentration** | < 40% | No more than 40% capital in single correlation cluster |
| **VaR (95%)** | < 3% daily | Daily value-at-risk under 3% |
| **Tail risk (CVaR)** | < 5% | Conditional VaR (expected loss beyond VaR) under 5% |
| **Correlation stability** | > 0.70 | Out-of-sample correlation vs in-sample > 0.70 |

---

## References

### Academic Papers

**Equity Sector Models**:
- Žignić et al. (2024), "Eigenportfolios for varying risk aversion", arXiv:2412.09678
- Yang & Shi (2023), "Sector rotation with machine learning"
- García-Medina et al. (2024), "Hierarchical clustering", arXiv:2412.13944

**Fixed Income / Global Macro**:
- Litterman & Scheinkman (1991), "Common factors affecting bond returns"
- Ilmanen (1995), "Time-varying expected returns in international bond markets"
- Brennan & Xia (2000), "Stochastic convenience yield"

**Cross-Asset / Correlation**:
- Distaso, Mele & Vilkov (2020), "Cross-section without factors", SSRN
- Koijen et al. (2018), "A demand system approach to asset pricing"
- Chen et al. (2025), "Stochastic block covariance models" (in preparation)

### ARBS Documentation

**Implementation**:
- `docs/SECTOR_COVARIANCE_GUIDE.md` - Covariance estimator comparison
- `docs/MVP_EQUITY_SECTOR_COMPLETE.md` - Equity sector MVP status
- `docs/GRINOLD_KAHN_FRAMEWORK.md` - Alpha generation theory

**Research**:
- `docs/research/CORRELATION_VOLATILITY_ARBITRAGE.md` - IV/RV ratio trading
- `docs/papers/multi_sector_portfolio_optimization_2507.16433.pdf`

**Code**:
- `Signals/SectorRotation/` - Sector rotation implementation
- `Risk/Covariance/SectorBased/` - Sector-based covariance
- `Query/Equities/` - Equity query layer
- `Query/Futures/` - Futures query layer

---

## Conclusion

The mathematical equivalence between equity sector models and global macro currency trading is not just theoretical—it's actionable. The ARBS codebase already contains 80% of the infrastructure needed to trade multi-currency portfolios using sector rotation logic.

**Key takeaway**: You can't be short the 5Y in every currency's butterfly, just like you can't short every sector against SPY. The solution is correlation-aware portfolio construction with cluster constraints.

**Next step**: Implement correlation cluster constraints in the optimizer (Phase 2).

---

**Status**: Framework documented, ready for implementation.
