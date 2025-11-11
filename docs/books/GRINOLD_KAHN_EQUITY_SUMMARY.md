# Grinold-Kahn Active Portfolio Management: Executive Summary for ARBS Equity Extension

**Document**: Executive summary of "Active Portfolio Management" (Grinold & Kahn, 1999)
**Purpose**: Guide ARBS extension from futures/swaps to equity sector portfolios
**Date**: 2025-11-11
**Status**: Complete synthesis of all 17 chapters

---

## Overview

This document synthesizes the entire Grinold-Kahn book (621 pages, 17 chapters) with specific focus on extending ARBS to equities. All 4 parts have been read and detailed notes created:

- **Part 1**: Foundations (Chapters 2-6) → `grinold_kahn_equity_notes_part1_foundations.md` (728 lines)
- **Part 2**: Valuation (Chapters 7-9) → `grinold_kahn_equity_notes_part2_valuation.md` (1477 lines)
- **Part 3**: Forecasting (Chapters 10-13) → `grinold_kahn_equity_notes_part3_forecasting.md` (1616 lines)
- **Part 4**: Implementation (Chapters 14-17) → `grinold_kahn_equity_notes_part4_implementation.md` (1072 lines)

**Total**: 4,893 lines of detailed analysis

---

## Critical Insight: ARBS is Already Grinold-Kahn Compliant

**Key realization**: ARBS was built on Grinold-Kahn equity principles, then applied to futures/swaps. We're now bringing it back to its native domain (equities).

### What ARBS Already Has (Equity-Ready)

✅ **Returns-first design**: `ReturnsCalculator` → fundamental to equity factor models
✅ **IC × Vol × Z formula**: `AlphaGenerator` → optimal alpha scaling (Chapter 5)
✅ **Risk models**: `LedoitWolfShrinkage`, `SampleCovariance` → work for any asset class
✅ **Portfolio optimization**: `MeanVarianceOptimizer` → Markowitz/Grinold-Kahn
✅ **Performance analysis**: `TearSheet` → IC, Sharpe, returns decomposition
✅ **Signal framework**: `BaseSignal`, `SignalCombiner` → ready for equity signals

### What Needs Extension for Equities

🆕 **Query layer**: `EquityQuery`, `EquityAdapter` → S&P 500 / Russell 3000 data
🆕 **Factor models**: 52 industries + 13 styles (Chapter 3)
🆕 **Equity signals**: Value, Quality, Earnings Surprise (Chapters 8-11)
🆕 **Constraints**: Long-only, sector-neutral, position limits (Chapter 14)
🆕 **Transaction costs**: Market impact model (Chapter 16)
🆕 **Attribution**: Factor decomposition (Chapter 17)

---

## Part 1: Foundations (Chapters 2-6)

### Chapter 2: CAPM

**Core formula**:
```
E{r_n} = r_F + β_n · f_B
```

**Equity implications**:
- Benchmark = S&P 500 (not "cash" like futures)
- β computed from fundamental factors (not just regression)
- Consensus returns = what everyone expects (CAPM equilibrium)

**ARBS connection**: Already have this via `Portfolio` tracking benchmark

### Chapter 3: Risk

**Multi-factor model** (critical for equities):
```
r_n = Σ_k X_{n,k} · b_k + u_n
```

**65-factor structure**:
- **52 industries**: Banks, Software, Oil&Gas, Pharma, Retail, etc.
- **13 styles**: Size, Value, Momentum, Growth, Volatility, Leverage, Dividend Yield, etc.

**Covariance decomposition**:
```
V = X · F · X^T + Δ
```
- X: N×K exposures (500 stocks × 65 factors)
- F: K×K factor covariance (65 × 65)
- Δ: N×N specific risk (diagonal!)

**ARBS connection**:
- Need `EquityFactorModel` class
- `LedoitWolfShrinkage` can estimate F matrix
- Much more efficient than full 500×500 covariance

**Data**: 500² = 250,000 parameters → 500×65 + 65² + 500 = 37,225 (93% reduction!)

### Chapter 4: Benchmarks and Value Added

**Active return**:
```
r_A = r_P - r_B
```

**Tracking error** (active risk):
```
ω_A = sqrt(Var(r_P - r_B))
```

**Information Ratio**:
```
IR = α / ω_A = (excess return) / (tracking error)
```

**Equity benchmarks**:
- Large cap: S&P 500
- Mid cap: S&P 400
- Small cap: Russell 2000
- Broad: Russell 3000

**Typical values** (Chapter 5):
- Top quartile manager: **IR = 0.5**
- Median active risk: **4.5%**
- Top quartile alpha: **2.25%** (= 0.5 × 4.5%)

**ARBS connection**: `Portfolio` already handles benchmarks, just need equity-specific ones

### Chapter 5: Information Ratio

**Fundamental Law of Active Management**:
```
IR = IC × sqrt(BR)
```

- **IC**: Information Coefficient (correlation between forecast and realized)
- **BR**: Breadth (independent bets per year)

**Equity vs Futures breadth**:

| Asset Class | Universe | Rebalance | BR | IC (typical) | IR (achievable) |
|-------------|----------|-----------|-----|--------------|-----------------|
| Equities | 500 stocks | Quarterly | 2,000 | 0.03 | 1.34 |
| Futures | 20 contracts | Monthly | 240 | 0.10 | 1.55 |

**Key insight**: Equities have **8× more breadth**, but **3× lower IC per bet**. Still achieves similar IR!

**ARBS connection**: Already have `AlphaGenerator` computing IC × Vol × Z

### Chapter 6: Fundamental Law

**Refined formula**:
```
IR = IC × sqrt(BR) × TC
```

where TC = transfer coefficient (portfolio implementation efficiency)

**Transfer coefficient**:
- Unconstrained optimization: TC = 1.0
- Long-only constraint: TC ≈ 0.5-0.7 (Chapter 15)
- Position limits: TC ≈ 0.8-0.9

**Reality check**:
- World-class IC = 0.05 (hard to achieve!)
- Even 52.9% directional accuracy → IC = 0.058
- **Need sufficient breadth** to compensate for low IC

**ARBS connection**: No change needed, but validates our IC calculation approach

---

## Part 2: Expected Returns and Valuation (Chapters 7-9)

### Chapter 7: Arbitrage Pricing Theory (APT)

**Multi-factor expected return**:
```
E{r_n} = Σ_k X_{n,k} · m_k
```

**APT vs CAPM**:
- CAPM: One factor (market), specified equilibrium
- APT: K factors (flexible), no equilibrium assumption
- APT more powerful but requires **forecasting factor returns m_k**

**Factor types**:
1. **Fundamental**: Industries (52), styles (13)
2. **Macro**: GDP growth, inflation, interest rates
3. **Statistical**: PCA factors (interpretation unclear)

**Key challenge**: Forecasting m_k requires **10× more skill** than forecasting individual stocks
- Stock IC = 0.03 reasonable
- Factor IC = 0.30 extremely rare

**ARBS connection**:
- Sectors = primary APT factors
- PPFM paper does multi-sector factor modeling
- Natural fit with existing architecture

### Chapter 8: Valuation in Theory

**Risk-adjusted discounting**:
```
p(0) = Σ_t E*{cf(t)} / (1 + i_F)^t
```

**Mispricing → alpha**:
```
α = (1 - γ) · (1 + i_F) · κ
```

where:
- κ = % mispricing (10% undervalued → κ = 0.10)
- γ = persistence (0 = fast idea, 1 = no benefit)

**Example**: Stock 10% undervalued, 2-year half-life
```
γ = 0.5^(1/2) = 0.707
α = (1 - 0.707) · 1.05 · 0.10 = 3.07% per year
```

**ARBS connection**: Valuation models convert to expected returns (alphas)

### Chapter 9: Valuation in Practice

**Three approaches**:

#### 1. Dividend Discount Model (DDM)
```
α = d/p + g - β · f_B
```

**Golden Rule**: "g in, g out" - alpha quality = growth forecast quality

**Growth model**:
```
g = (1 - payout_ratio) × ROE
```

**3-stage model**:
1. Near-term: Analyst estimates (1-2 years)
2. Transition: Fade to industry average (3-5 years)
3. Long-term: Perpetual growth = GDP + inflation (2-3%)

#### 2. Comparative Valuation
```
p_fitted = Σ_k c_k · A_{n,k}
α ≈ (p_fitted - p_market) / p_market
```

**Price stocks by attributes**:
- Earnings (P/E ratio)
- Book value (P/B ratio)
- Sales (P/S ratio)
- Cash flow (P/CF ratio)

**Sector-by-sector** to ensure comparability

#### 3. Returns-Based Analysis
```
r_n(t) = Σ_k X_{n,k}(t-1) · b_k(t) + u_n(t)
```

**Popular factors**:
- **Value**: Low P/E, low P/B, high dividend yield
- **Momentum**: 12-month return (skip last month)
- **Quality**: High ROE, low debt, stable earnings
- **Size**: Market cap (small cap premium)
- **Volatility**: Low beta, low idiosyncratic risk

**ARBS connection**: These become `Signals/Equities/` modules

---

## Part 3: Information Processing (Chapters 10-13)

### Chapter 10: Forecasting Basics

**Core alpha formula**:
```
α_n = ω_n · IC · score_n
```

where:
- ω_n = volatility (annualized std dev)
- IC = information coefficient (skill)
- score_n = standardized forecast (z-score)

**Standardization**:
```
score_n = (forecast_n - mean) / std_dev
```

**IC benchmarks**:
- 0.05 = good
- 0.10 = great
- 0.15 = world-class (very rare)

**ARBS connection**: Already have this in `AlphaGenerator.py`!

### Chapter 11: Advanced Forecasting

**Key insight**: Most equity signals DON'T need volatility scaling
```
α_n = IC · score_n  (not ω_n · IC · score_n)
```

**Why?** Cross-sectional signals already account for volatility differences through ranking

**Signal types**:
- **Cross-sectional**: Rank within universe (typical for equities)
- **Time-series**: Compare to own history (typical for futures)

**Factor forecasting**: If forecasting one factor, forecast correlated factors too
- Example: Forecast tech sector → also forecast communication services

**ARBS connection**: Add `to_cross_sectional_scores()` method to `BaseSignal`

### Chapter 12: Information Analysis

**Six evaluation procedures**:
1. Quintile portfolios (long top 20%, short bottom 20%)
2. Factor portfolios (regress returns on scores)
3. Controlled factor portfolios (neutralize other factors)
4. Information analysis (IC, IR, t-stats)
5. Event studies (earnings announcements, analyst revisions)
6. Performance attribution (factor decomposition)

**IC measurement**:
```
IC = correlation(forecast, realized_return)
```

**Statistical significance**:
```
t = IC · sqrt(N_stocks - 2) / sqrt(1 - IC²)
```

Need **N ≥ 30** stocks for reliable IC estimate

**Data mining warning**: 20 random trials → 64% false positive rate!

**ARBS connection**: Already have IC calculation, add factor-controlled analysis

### Chapter 13: Information Horizon

**Information decay**:
```
IC(h) = IC(0) · exp(-λ · h)
```

where λ = decay rate, h = horizon

**Typical horizons**:
- Momentum: 3-6 months
- Value: 12-24 months
- Quality: 24+ months

**Optimal rebalancing**: Balance signal decay vs transaction costs
- High frequency (daily): Max signal value, high costs
- Low frequency (annual): Low costs, stale signals
- **Sweet spot for equities: Monthly**

**ARBS connection**: Add `information_horizon` parameter to signals

---

## Part 4: Implementation (Chapters 14-17)

### Chapter 14: Portfolio Construction

**Alpha preprocessing** (critical!):
1. **Scale**: Multiply by expected IC
2. **Trim**: Cap extreme values (±3 sigma)
3. **Neutralize**: Remove unwanted exposures (benchmark, industry, factors)

**Neutralization**:
```
α_neutral = α - (β · α_benchmark + α_industry + Σ_k X_k · α_factor_k)
```

**Optimization methods**:
- Screens (quintiles): IR = 0.86
- Stratification: IR = 1.27
- **Quadratic programming: IR = 1.88** (winner!)

**Constraints**:
- Long-only: `h_i ≥ 0`
- Sector-neutral: `Σ_{i ∈ sector} (h_i - h_Bi) = 0`
- Position limits: `|h_i - h_Bi| ≤ 0.05`
- Turnover: `Σ |h_i - h_i^old| ≤ TO_max`

**ARBS connection**: Add `Optimizer/constraints/` module

### Chapter 15: Long/Short Investing

**CRITICAL FINDING**: Long-only constraint **cuts IR by ~50%**!

**Shrinkage analysis** (Table 15.2):
- 500 stocks, 4.5% active risk
- Unconstrained: IR = 2.23
- Long-only: IR = 1.11 (50% reduction!)
- Transfer coefficient TC = 0.50

**Size bias**: Long-only portfolios have incidental **-0.65 sigma size exposure**
- Can cost ~100 bps/year
- Solution: Neutralize size factor explicitly

**When long-only hurts most**:
- Large universe (more stocks → worse)
- High active risk (more aggressive → worse)
- Low asset volatility (less room to maneuver)

**ARBS connection**: Add `LongOnlyConstraint` with impact analysis

### Chapter 16: Transaction Costs

**Inventory risk model**:
```
TC_i = c · σ_i · sqrt(V_trade,i / V_avg,i) + commission
```

**Square root law** (Loeb 1983): Market impact ∝ sqrt(volume)

**Rule of thumb**: Costs ~1 day's volatility to trade 1 day's volume

**Empirical data** (Table 16.1):
- 1% of volume: 1.0% TC (full day's vol)
- 5% of volume: 2.2% TC (2.2× scaling)
- 10% of volume: 3.2% TC (3.2× scaling)
- 25% of volume: 5.0% TC (5× scaling)

**Turnover optimization**: Can achieve **75% of value-added with 50% of turnover**!

**ARBS connection**: Add `TransactionCosts/InventoryRiskModel.py`

### Chapter 17: Performance Attribution

**Statistical challenge**: Need **16 years** to prove top-quartile skill (IR=0.5) at 95% confidence

**t-statistic**:
```
t = IR · sqrt(N_years)
```

**Factor decomposition**:
```
r_A = Σ_k β_k · f_k + Σ_n w_n · u_n
```

- First term: Systematic factor bets
- Second term: Specific stock selection

**Best/worst analysis**: Identify which factor bets paid off vs intended

**ARBS connection**: Already have `TearSheet`, extend with factor decomposition

---

## Equity Implementation Roadmap

### Phase 1: Data Infrastructure (2-3 weeks)

1. **Query layer**:
   - `Query/Equities/EquityQuery.py`
   - `Query/Equities/EquityStructure.py` (SINGLE, SECTOR_BASKET, LONG_SHORT)
   - `Query/Equities/EquityValue.py` (PRICE, RETURN, DIVIDEND_YIELD)

2. **Data provider**:
   - `MDP/YahooFinance/YahooFinanceMDP.py`
   - Fetch: prices, dividends, splits, fundamentals
   - Sector classification: GICS Level 1 (11 sectors)

3. **Adapter**:
   - `Adapter/EquityAdapter.py`
   - Convert queries → Polars DataFrame
   - Format: (ticker, sector, returns, fundamentals, market_cap)

### Phase 2: Signals (3-4 weeks)

1. **Value signals**:
   - `Signals/Equities/ValueSignal.py` (E/P, B/P, CF/P)
   - Expected IC: 0.03-0.04

2. **Momentum signals**:
   - `Signals/Equities/MomentumSignal.py` (12-month return, skip last month)
   - Expected IC: 0.04-0.06

3. **Quality signals**:
   - `Signals/Equities/QualitySignal.py` (ROE, debt/equity, earnings stability)
   - Expected IC: 0.02-0.03

4. **Signal combination**:
   - Extend `SignalCombiner` for cross-sectional signals
   - IC-weighted blending

### Phase 3: Risk Models (3-4 weeks)

1. **Factor model**:
   - `Risk/FactorModel/EquityFactorModel.py`
   - 52 industries + 13 styles
   - Covariance: V = X·F·X^T + Δ

2. **Multi-sector covariance**:
   - `Risk/Covariance/PPFMCovariance.py`
   - Implement paper's projection-penalized approach
   - Learn sector relatedness (λ parameter)

3. **Integration**:
   - Add to `risk_model_factory.py`
   - Fallback logic: PPFM → LedoitWolf → Sample

### Phase 4: Optimization (2-3 weeks)

1. **Constraints**:
   - `Optimizer/constraints/LongOnly.py`
   - `Optimizer/constraints/SectorNeutral.py`
   - `Optimizer/constraints/PositionLimit.py`
   - `Optimizer/constraints/TurnoverLimit.py`

2. **Alpha preprocessing**:
   - `Optimizer/AlphaNeutralizer.py`
   - Scale, trim, neutralize

3. **Transaction costs**:
   - `TransactionCosts/InventoryRiskModel.py`
   - Square-root market impact

### Phase 5: Analysis (2-3 weeks)

1. **Performance attribution**:
   - `Analysis/FactorAttribution.py`
   - Decompose returns by factor + selection

2. **Extended tearsheet**:
   - Add factor decomposition
   - Best/worst analysis
   - Turnover/cost analysis

### Phase 6: Backtesting (2-3 weeks)

1. **End-to-end integration**:
   - `examples/run_equity_sector_backtest.py`
   - Tech vs Finance sector rotation

2. **Validation**:
   - Paper replication (PPFM)
   - IC/IR targets vs realized
   - Performance benchmarks

**Total timeline**: ~18-22 weeks (4.5-5.5 months)

---

## Key Metrics & Targets

### Information Ratio Targets

| Strategy | IC | BR | IR (theoretical) | IR (achievable w/ TC=0.7) |
|----------|-----|-----|------------------|---------------------------|
| Single signal (value) | 0.03 | 2,000 | 1.34 | 0.94 |
| Two signals (value+momentum) | 0.045 | 2,000 | 2.01 | 1.41 |
| Three signals (value+momentum+quality) | 0.055 | 2,000 | 2.46 | 1.72 |

**Benchmark**: Top quartile equity manager = **IR 0.5**, we should target **IR 1.0+**

### Risk Targets

| Parameter | Conservative | Moderate | Aggressive |
|-----------|--------------|----------|------------|
| Active risk (ω_A) | 3% | 6% | 10% |
| Position limit | ±3% | ±5% | ±10% |
| Turnover (annual) | 100% | 200% | 400% |
| Number of stocks | 100 | 250 | 500 |

### Signal IC Expectations

| Signal Type | Expected IC | Horizon | Source |
|-------------|-------------|---------|--------|
| Value (E/P, B/P) | 0.03-0.04 | 12-24 months | Chapter 9 |
| Momentum (12M) | 0.04-0.06 | 3-6 months | Chapter 11 |
| Quality (ROE) | 0.02-0.03 | 24+ months | Chapter 9 |
| Earnings surprise | 0.05-0.08 | 1-3 months | Chapter 12 |
| Dividend yield | 0.02-0.03 | 12-24 months | Chapter 9 |

### Transaction Cost Estimates

| Trade size (% daily volume) | Market impact (% of stock volatility) |
|-----------------------------|---------------------------------------|
| 1% | 1.0% |
| 5% | 2.2% |
| 10% | 3.2% |
| 25% | 5.0% |

**Rule**: Keep trades <5% of daily volume to minimize impact

---

## Architecture Mapping: Book → ARBS

### Existing ARBS Components (No Changes Needed)

| Grinold-Kahn Concept | ARBS Implementation | Status |
|----------------------|---------------------|--------|
| Returns-first design | `ReturnsCalculator` | ✅ Works as-is |
| IC × Vol × Z | `AlphaGenerator` | ✅ Works as-is |
| Covariance estimation | `LedoitWolfShrinkage` | ✅ Works as-is |
| Mean-variance optimization | `MeanVarianceOptimizer` | ✅ Works as-is |
| Portfolio construction | `Portfolio` (composite asset) | ✅ Works as-is |
| Performance analysis | `TearSheet` | ✅ Works as-is |
| Signal framework | `BaseSignal`, `SignalCombiner` | ✅ Works as-is |

### New Components Needed

| Grinold-Kahn Concept | ARBS Extension | Priority |
|----------------------|----------------|----------|
| Equity queries | `Query/Equities/` | HIGH |
| Yahoo Finance data | `MDP/YahooFinance/` | HIGH |
| Equity adapter | `Adapter/EquityAdapter.py` | HIGH |
| Factor model (65 factors) | `Risk/FactorModel/` | HIGH |
| Value signals | `Signals/Equities/ValueSignal.py` | HIGH |
| Momentum signals | `Signals/Equities/MomentumSignal.py` | HIGH |
| Quality signals | `Signals/Equities/QualitySignal.py` | MEDIUM |
| Constraints | `Optimizer/constraints/` | HIGH |
| Alpha neutralization | `Optimizer/AlphaNeutralizer.py` | MEDIUM |
| Transaction costs | `TransactionCosts/` | MEDIUM |
| Factor attribution | `Analysis/FactorAttribution.py` | LOW |
| Multi-sector covariance | `Risk/Covariance/PPFMCovariance.py` | MEDIUM |

---

## Connection to PPFM Paper

**Paper**: "Adaptive Multi-task Learning for Multi-sector Portfolio Optimization"

**Key insight**: Sectors = APT factors with hierarchical structure

**Grinold-Kahn APT** (Chapter 7):
```
E{r_n} = Σ_k X_{n,k} · m_k
```

**PPFM approach**: Learn sector relatedness via projection penalty
```
L = Σ_m [fit_error_m] + λ Σ_{m,m'} ||P^(m) - P^(m')||_F^2
```

**Natural integration**:
- GICS sectors = primary factors
- Styles (value, momentum, quality) = secondary factors
- PPFM covariance estimation
- Grinold-Kahn alpha generation

**Architecture**:
```
EquityQuery → YahooFinanceMDP → EquityAdapter
    ↓
ReturnsCalculator (returns matrix)
    ↓
Signals (Value, Momentum, Quality) → AlphaGenerator (IC × Vol × Z)
    ↓
PPFMCovariance (multi-sector risk model)
    ↓
MeanVarianceOptimizer (with constraints)
    ↓
Portfolio (composite asset)
    ↓
TearSheet (performance + factor attribution)
```

---

## Polars Migration Note

**CRITICAL**: All equity code must be **Polars-native from day 1**

- Do NOT write pandas code then migrate
- Use `pl.DataFrame`, `pl.Series`, `pl.Expr` throughout
- API differences:
  - `df.apply()` → `df.map()` or `df.with_columns()`
  - `df.fillna()` → `df.fill_null()`
  - `df.groupby()` → `df.groupby()` (similar but not identical)
  - No MultiIndex support (use `explode()` + `pivot()`)

**Test strategy**: Run small examples (10 stocks, 1 year) before scaling

---

## Open Questions

1. **Universe selection**: S&P 500 (500 stocks) or Russell 3000 (3000 stocks)?
   - Recommendation: Start with S&P 500 MVP, expand to Russell 3000 later

2. **Rebalancing frequency**: Monthly, quarterly, or dynamic?
   - Recommendation: Monthly (balance signal decay vs transaction costs)

3. **Constraints**: Long-only or long/short?
   - Recommendation: Both (long-only for institutional, long/short for hedge fund)

4. **Factor model**: 65 factors (52 industries + 13 styles) or simpler (11 sectors + 6 styles)?
   - Recommendation: Start simple (11 sectors + 6 styles), expand if needed

5. **Transaction cost data**: Where to get empirical market impact data?
   - Recommendation: Start with theoretical model (square-root law), refine with execution data

6. **Fundamental data**: Yahoo Finance sufficient or need Bloomberg/FactSet?
   - Recommendation: Yahoo Finance for MVP (free), Bloomberg for production

7. **Sector classification**: GICS or SIC?
   - Recommendation: GICS (Yahoo Finance native, 11 sectors, matches paper)

8. **Cross-validation**: How to tune PPFM λ parameter?
   - Recommendation: 5-fold walk-forward CV, grid search λ ∈ [0, 10]

---

## Next Steps

1. **Review this summary** with Peter
2. **Create knowledge graph** (visual diagram of concepts → code mapping)
3. **Update GRINOLD_KAHN_FRAMEWORK.md** with equity implementation details
4. **Revise equity sector plan** based on book insights
5. **Start Phase 1 implementation** (Query + Adapter + Yahoo Finance)

---

## References

- **Book**: Grinold, R. C., & Kahn, R. N. (1999). *Active Portfolio Management: A Quantitative Approach for Providing Superior Returns and Controlling Risk*. McGraw-Hill.
- **Paper**: "Adaptive Multi-task Learning for Multi-sector Portfolio Optimization" (arXiv:2507.16433)
- **Detailed notes**:
  - `grinold_kahn_equity_notes_part1_foundations.md` (728 lines)
  - `grinold_kahn_equity_notes_part2_valuation.md` (1477 lines)
  - `grinold_kahn_equity_notes_part3_forecasting.md` (1616 lines)
  - `grinold_kahn_equity_notes_part4_implementation.md` (1072 lines)

---

**End of Executive Summary**
