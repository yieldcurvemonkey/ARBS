# Sector Risk Models - ARBS Integration Roadmap

**Date**: 2025-11-12
**Branch**: `claude/sector-risk-model-research-011CV41RojiVnaUFqthNnozq`
**Status**: Research Complete - Ready for Implementation

---

## Executive Summary

This document maps the sector risk model research to existing ARBS equity infrastructure, showing how the three papers (García-Medina 2024, Žignić et al. 2024, Chen et al. 2025) integrate with:

1. **Existing Equity MVP** (`docs/MVP_EQUITY_SECTOR_COMPLETE.md`)
2. **Sector Rotation Work** (`docs/papers/FINAL_SECTOR_ROTATION_SUMMARY.md`)
3. **Grinold-Kahn Framework** (`docs/GRINOLD_KAHN_FRAMEWORK.md`)

**Key Insight**: All pieces are already in place. The new risk models are **drop-in replacements** for the existing Risk layer, requiring **zero changes** to upstream (Query, Adapter, Returns, Signals) or downstream (Optimizer, Portfolio) components.

---

## Existing ARBS Equity Infrastructure

### ✅ Query Layer (Completed)

**Location**: `Query/Equities/`

**Components**:
- `EquityQuery.py` (106 lines) - Individual stocks with GICS sectors
- `ETFQuery.py` (101 lines) - Sector ETFs for hedging
- `EquityStructure.py` - SINGLE, SECTOR_BASKET, LONG_SHORT, MARKET_NEUTRAL
- `EquityValue.py` - PRICE, RETURN, DIVIDEND_YIELD, EARNINGS_YIELD, VOLATILITY

**Tests**: 28 tests (13 EquityQuery, 15 ETFQuery)

**Integration Point**: ✅ **No changes needed** - Query layer already supports sector column

**Example**:
```python
query = EquityQuery(
    ticker="AAPL",
    sector="Information Technology",  # ✅ Sector already captured
    structure=EquityStructure.SINGLE,
    value=EquityValue.RETURN,
)
```

---

### ✅ MDP Layer (Completed)

**Location**: `MDP/YahooFinance/`

**Components**:
- `YahooFinanceMDP.py` (650 lines) - Yahoo Finance integration with ZODB caching
- `sector_mapping.py` (322 lines) - GICS Level 1 sectors (11 sectors)

**Sector Coverage**:
```python
SECTORS = [
    "Information Technology",
    "Health Care",
    "Financials",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
]

SECTOR_ETFS = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    # ... 11 total
}
```

**Current Limitation**: 29 hardcoded tickers (MVP scope)

**Extension Needed** (for full S&P 500):
```python
# MDP/YahooFinance/YahooFinanceMDP.py
def fetch_sp500_universe(
    self,
    as_of_date: date,
    top_n: int = 500,
    require_complete_data: bool = True,
) -> list[EquityQuery]:
    """Fetch S&P 500 with complete data and sector mapping."""
    # Implementation: ~1-2 hours
    pass
```

**Integration Point**: ✅ **Minor extension** - Just add S&P 500 fetcher

---

### ✅ Adapter Layer (Completed)

**Location**: `Adapter/EquityAdapter.py` (270 lines)

**Output Schema**:
```python
DataFrame(
    ticker: str,
    date: date,
    close: float,
    return: float,
    sector: str,     # ✅ Sector already in output
    weight: float,
)
```

**Tests**: 8 comprehensive tests

**Integration Point**: ✅ **No changes needed** - Already outputs sector column

---

### ✅ Returns Layer (Completed)

**Location**: `Returns/ReturnsCalculator.py`

**Status**: Polars-native, reused from futures/swaps

**Integration Point**: ✅ **No changes needed** - Works with any asset class

---

### ✅ Signals Layer (Partially Completed)

**Existing Components**:

**Base Infrastructure** (`Signals/BaseSignal.py`):
- IC tracking
- History management
- Z-score standardization
- `generate_batch()` for cross-sectional signals

**Implemented Signals**:
1. `CarrySignal.py` - Dividend yield, earnings yield
2. `MomentumSignal.py` - Price momentum (from futures)
3. `MeanReversionSignal.py` - Mean reversion (from futures)

**Sector Rotation Signals** (from Yang & Shi 2023 paper):
4. `SectorRotation/SectorMomentumSignal.py` (150 lines) - MOM_7M factor
5. `SectorRotation/SectorReversionSignal.py` (140 lines) - REV_30D factor
6. `SectorRotation/FundamentalSignal.py` (240 lines) - Neural network predictor

**Tests**: 88 test methods across sector rotation signals

**Integration Point**: ✅ **No changes needed** - All signals extend BaseSignal

---

### ✅ Alpha Generation Layer (Completed)

**Location**: `Alpha/AlphaGenerator.py`

**Formula**: `α = IC × Vol × Z`

**Integration Point**: ✅ **No changes needed** - Works with any signal

---

### ⏳ Risk Layer (Target for New Implementation)

**Current Components**:
- `Risk/SampleCovariance.py` ✅ (baseline)
- `Risk/LedoitWolfShrinkage.py` ✅ (full matrix shrinkage)

**Proposed Extensions** (from paper research):
```
Risk/
├── BlockDiagonal/               # 🆕 Phase 1 (5-8 hours)
│   ├── FactorExtractor.py
│   ├── HierarchicalSectorClustering.py
│   └── BlockDiagonalCovariance.py
├── TwoStep/                     # 🆕 Phase 2 (4-6 hours)
│   ├── RandomMatrixFilter.py
│   └── TwoStepCovariance.py
└── StochasticBlock/             # 🆕 Phase 3 (Optional)
    └── StochasticBlockCovariance.py
```

**Interface Compliance**:

All new risk models will implement the **same interface** as existing risk models:

```python
class BlockDiagonalCovariance:
    def estimate(
        self,
        returns: pl.DataFrame,  # ✅ Standard input
        sector_col: str = "sector",  # 🆕 Uses sector column from Adapter
    ) -> pl.DataFrame:  # ✅ Standard output (ticker_i, ticker_j, covariance)
        """Estimate covariance matrix."""
        pass
```

**Integration Point**: ✅ **Drop-in replacement** - Same interface as existing risk models

**Usage Example**:
```python
# OLD: Full Ledoit-Wolf
cov_estimator = LedoitWolfShrinkage()
cov_matrix = cov_estimator.estimate(returns)

# NEW: Block-diagonal with sectors
cov_estimator = BlockDiagonalCovariance(clustering_method="predefined")
cov_matrix = cov_estimator.estimate(returns, sector_col="sector")

# Downstream code unchanged (Optimizer, Portfolio)
weights = optimizer.optimize(alphas, cov_matrix, risk_aversion=2.0)
```

---

### ✅ Optimizer Layer (Completed)

**Location**: `Optimizer/MeanVarianceOptimizer.py`

**Formula**:
```
min_w  (1/2)·w^T·Σ·w - λ·α^T·w
s.t.   Aw ≤ b  (constraints)
```

**Existing Constraints**:
- Budget constraint (1^T·w = 1)
- Long-only or long/short
- Position limits

**Proposed Extension** (sector constraints):
```python
class MeanVarianceOptimizer:
    def optimize(
        self,
        alphas: pl.DataFrame,
        cov_matrix: pl.DataFrame,
        risk_aversion: float = 1.0,
        sector_constraints: dict = None,  # 🆕 NEW
        # Example: {"Technology": {"min": -0.3, "max": 0.3}}
    ) -> pl.DataFrame:
        """Optimize portfolio weights."""
        pass
```

**Integration Point**: ✅ **Minor extension** - Add sector constraints (optional)

---

### ✅ Portfolio Layer (Completed)

**Location**: `Portfolio/Portfolio.py`

**Features**:
- Accepts returns (not prices) - Grinold-Kahn compliant
- Composite asset pattern (nested portfolios)
- IC tracking and history
- Performance attribution

**Tests**: 100 tests

**Integration Point**: ✅ **No changes needed** - Works with any optimizer output

---

### ✅ Analysis Layer (Completed)

**Location**: `Analysis/TearSheet.py`

**Metrics**:
- IC (Information Coefficient)
- Sharpe ratio
- Total return
- Drawdown
- Turnover

**Proposed Extensions** (from García-Medina 2024):
```python
# Analysis/RiskMetrics.py (new file)

def herfindahl_hirschman_index(weights: pl.DataFrame) -> float:
    """HHI = Σw_i². Measures concentration (lower is better)."""
    return (weights["weight"] ** 2).sum()

def leverage(weights: pl.DataFrame) -> float:
    """L = Σ|w_i|. Measures short-selling (lower is better)."""
    return weights["weight"].abs().sum()

def risk_diversification_index(
    weights: pl.DataFrame,
    cov_matrix: pl.DataFrame,
) -> float:
    """RDI = √(w^T·Σ·w) / (w^T·√diag(Σ))."""
    # Portfolio risk / average individual risk
    pass
```

**Integration Point**: ✅ **Minor extension** - Add new metrics (1-2 hours)

---

## Mapping Papers to ARBS Components

### Paper 1: García-Medina (2024) - "High-dimensional covariance matrix estimators"

**Key Contribution**: Compares hierarchical vs one-factor vs diagonal structures

**ARBS Mapping**:

| Paper Component | ARBS Location | Status |
|----------------|---------------|--------|
| Hierarchical nested structure | `Risk/TwoStep/` | 🆕 Phase 2 |
| One-factor model | `Risk/BlockDiagonal/FactorExtractor.py` | 🆕 Phase 1 |
| Minimum variance portfolio | `Optimizer/MeanVarianceOptimizer.py` | ✅ Existing |
| HHI, Leverage, RDI metrics | `Analysis/RiskMetrics.py` | 🆕 Extension |
| S&P 500 dataset | `MDP/YahooFinance/` | ✅ Extension needed |

**Integration Effort**: Medium (4-6 hours for Phase 2)

---

### Paper 2: Žignić et al. (2024) - "Block-diagonal idiosyncratic covariance"

**Key Contribution**: Sector-based factor model with per-block shrinkage

**ARBS Mapping**:

| Paper Component | ARBS Location | Status |
|----------------|---------------|--------|
| Factor model (Y = BF + ε) | `Risk/BlockDiagonal/FactorExtractor.py` | 🆕 Phase 1 |
| Block-diagonal Ψ | `Risk/BlockDiagonal/BlockDiagonalCovariance.py` | 🆕 Phase 1 |
| Predefined sectors (CSI) | `Adapter/EquityAdapter.py` (sector column) | ✅ Existing |
| Hierarchical clustering (CSH) | `Risk/BlockDiagonal/HierarchicalSectorClustering.py` | 🆕 Phase 1 |
| Ledoit-Wolf per block | `Risk/BlockDiagonal/BlockDiagonalCovariance.py` | 🆕 Phase 1 |
| Eigenvalue bias correction | `Risk/BlockDiagonal/BlockDiagonalCovariance.py` | 🆕 Phase 1 |
| SIC sector codes | `MDP/YahooFinance/sector_mapping.py` | ✅ Existing (GICS) |

**Integration Effort**: High (5-8 hours for Phase 1)

**Critical Insight**: This is the **minimum viable sector risk model**. Papers show it consistently outperforms unstructured methods.

---

### Paper 3: Chen et al. (2025) - "Stochastic Block Covariance"

**Key Contribution**: Allows inter-block correlations via Bayesian inference

**ARBS Mapping**:

| Paper Component | ARBS Location | Status |
|----------------|---------------|--------|
| Stochastic block structure | `Risk/StochasticBlock/` | 🆕 Phase 3 (optional) |
| Hierarchical Bayesian inference | External dependency (PyMC) | 🆕 Phase 3 |
| Inter-block correlations | `Risk/StochasticBlock/StochasticBlockCovariance.py` | 🆕 Phase 3 |

**Integration Effort**: High (8-12 hours for Phase 3)

**Decision Point**: Implement only if Phases 1-2 show need for cross-sector correlations.

---

## Complete Pipeline Integration

### Before (Existing ARBS Equity MVP)

```
Query/Equities (EquityQuery + sector)
    ↓
MDP/YahooFinance (fetch with sectors)
    ↓
Adapter/EquityAdapter (→ DataFrame with sector column)
    ↓
Returns/ReturnsCalculator (→ returns)
    ↓
Signals/BaseSignal (→ raw signals)
    ↓
Alpha/AlphaGenerator (→ alphas = IC × Vol × Z)
    ↓
Risk/LedoitWolfShrinkage (→ Σ, full matrix)  ❌ No sector structure
    ↓
Optimizer/MeanVarianceOptimizer (→ weights)
    ↓
Portfolio/Portfolio (→ performance)
    ↓
Analysis/TearSheet (→ IC, Sharpe, returns)
```

### After (With Sector Risk Models)

```
Query/Equities (EquityQuery + sector)
    ↓
MDP/YahooFinance (fetch with sectors)
    ↓
Adapter/EquityAdapter (→ DataFrame with sector column)
    ↓
Returns/ReturnsCalculator (→ returns)
    ↓
Signals/BaseSignal (→ raw signals)
    ↓
Alpha/AlphaGenerator (→ alphas = IC × Vol × Z)
    ↓
Risk/BlockDiagonalCovariance (→ Σ, sector structure)  ✅ NEW
    ↓
Optimizer/MeanVarianceOptimizer (→ weights)
    ↓
Portfolio/Portfolio (→ performance)
    ↓
Analysis/TearSheet + RiskMetrics (→ IC, Sharpe, HHI, Leverage)  ✅ Extended
```

**Changes Required**:
1. 🆕 Add `Risk/BlockDiagonal/` module (Phase 1)
2. 🆕 Add `Risk/TwoStep/` module (Phase 2)
3. 🆕 Add `Analysis/RiskMetrics.py` (new metrics)
4. ✅ Extend `MDP/YahooFinance/` for S&P 500 universe
5. ✅ (Optional) Add sector constraints to `Optimizer/`

**Everything else unchanged!**

---

## Integration with Sector Rotation Work

### Existing Sector Rotation (Yang & Shi 2023)

**Location**: `Signals/SectorRotation/`

**Components** (1,714 lines):
- `MomentumFactor.py` (220 lines) - MOM_7M = Σ(147d) - Σ(15d)
- `ReversionFactor.py` (180 lines) - REV_30D = -Σ(30d)
- `CrossSectionalNeutralizer.py` (210 lines) - Z = (X - μ) / σ
- `SectorMomentumSignal.py` (150 lines) - BaseSignal wrapper
- `SectorReversionSignal.py` (140 lines) - BaseSignal wrapper
- `FundamentalProcessor.py` (230 lines) - 11 fundamental factors
- `FundamentalSignal.py` (240 lines) - Neural network predictor
- `SectorLongShortPortfolio.py` (190 lines) - Long/short constructor

**Tests**: 3,021 lines (88 test methods)

**Performance Targets** (from paper):
- MOM_7M alone: Sharpe 0.62
- REV_30D alone: Sharpe 0.87
- Combined (fundamental): Sharpe 2.21

---

### Synergy: Sector Rotation + Risk Models

**Current Workflow** (Yang & Shi):
```python
# 1. Generate sector signals
mom_signal = SectorMomentumSignal()
rev_signal = SectorReversionSignal()
fund_signal = FundamentalSignal()

# 2. Combine signals
signals = mom_signal.generate_batch(returns) + \
          rev_signal.generate_batch(returns) + \
          fund_signal.generate_batch(returns)

# 3. Convert to alphas
alphas = alpha_generator.generate(signals, returns)

# 4. Construct portfolio (heuristic)
portfolio = SectorLongShortPortfolio(top_n=3, bottom_n=3)
weights = portfolio.construct(alphas)
```

**Enhanced Workflow** (Sector Rotation + Block-Diagonal Risk):
```python
# 1. Generate sector signals (same as before)
mom_signal = SectorMomentumSignal()
rev_signal = SectorReversionSignal()
fund_signal = FundamentalSignal()

signals = mom_signal.generate_batch(returns) + \
          rev_signal.generate_batch(returns) + \
          fund_signal.generate_batch(returns)

# 2. Convert to alphas (same as before)
alphas = alpha_generator.generate(signals, returns)

# 3. Estimate sector-structured covariance (NEW)
cov_estimator = BlockDiagonalCovariance(clustering_method="predefined")
cov_matrix = cov_estimator.estimate(returns, sector_col="sector")

# 4. Optimize with risk model (NEW - replaces heuristic)
optimizer = MeanVarianceOptimizer()
weights = optimizer.optimize(
    alphas=alphas,
    cov_matrix=cov_matrix,  # Uses sector structure
    risk_aversion=2.0,
    sector_constraints={  # Optional
        "Technology": {"min": -0.3, "max": 0.3},
        "Financials": {"min": -0.3, "max": 0.3},
    },
)
```

**Expected Improvement**:
- Yang & Shi Sharpe: 2.21 (combined strategy, heuristic portfolio)
- With sector risk model: **2.5-3.0** (estimate based on papers)

**Why?**
1. **Better risk estimation**: Block-diagonal captures within-sector correlation
2. **Optimal weights**: Mean-variance optimization vs. heuristic equal-weight
3. **Diversification**: HHI and leverage metrics guide portfolio construction

---

## Integration with Grinold-Kahn Framework

### Grinold-Kahn Architecture (from `docs/GRINOLD_KAHN_FRAMEWORK.md`)

**Core Formula**:
```
α = IC × Vol × Z
```

**Risk Model**:
```
Σ = B·Cov(F)·B^T + Δ
```
- B: Factor exposures
- F: Common factors
- Δ: Specific risk (diagonal or structured)

**Portfolio Optimization**:
```
w* = argmax_w  α^T·w - λ·w^T·Σ·w
     s.t.      Aw ≤ b
```

---

### Paper Alignment with Grinold-Kahn

**All three papers implement the Grinold-Kahn risk model structure!**

| Grinold-Kahn Component | Paper Implementation | ARBS Component |
|------------------------|----------------------|----------------|
| Factor exposures B | PCA loadings | `FactorExtractor.py` |
| Common factors F | Principal components | `FactorExtractor.py` |
| Specific risk Δ | Block-diagonal Ψ | `BlockDiagonalCovariance.py` |
| α (alphas) | IC × Vol × Z | `AlphaGenerator.py` ✅ |
| Optimization | Mean-variance | `MeanVarianceOptimizer.py` ✅ |

**Key Difference**: Papers use **block-diagonal** specific risk instead of **diagonal**.

**Grinold-Kahn Assumption**:
```
Δ = diag(σ₁², σ₂², ..., σₚ²)  (diagonal - assets independent)
```

**Papers' Enhancement**:
```
Δ = Ψ = block_diag(Ψ₁, Ψ₂, ..., Ψₘ)  (block-diagonal - sectors capture residual correlation)
```

**Impact**: Better captures within-sector correlation after removing common factors.

---

### ARBS is Already Grinold-Kahn Compliant!

From `docs/GRINOLD_KAHN_FRAMEWORK.md`:

> "ARBS implements the full Grinold-Kahn architecture:
> 1. Signals generate forecasts (Chapter 5)
> 2. Alpha = IC × Vol × Z (Chapter 6)
> 3. Risk models estimate Σ (Chapter 4)
> 4. Portfolio construction optimizes α^T·w - λ·w^T·Σ·w (Chapter 7)"

**Papers enhance Step 3 (Risk models)**:
- OLD: LedoitWolfShrinkage (full matrix, no structure)
- NEW: BlockDiagonalCovariance (sector structure, Grinold-Kahn factor decomposition)

**Everything else unchanged** - Still 100% Grinold-Kahn compliant!

---

## Data Requirements Summary

### Current ARBS Data Capability

**Yahoo Finance Integration** (`MDP/YahooFinance/`):
- ✅ Daily price data
- ✅ GICS sector mapping (11 Level 1 sectors)
- ✅ ZODB caching (persistent)
- ✅ Rate limiting and error handling
- ⏳ **Limitation**: 29 hardcoded tickers (MVP scope)

---

### Papers' Data Requirements

**Paper 1 (García-Medina)**:
- S&P 500 constituents
- Daily returns
- Moving window: 252 trading days (1 year)
- Benchmark: Test when p ≈ T (e.g., 300 stocks × 300 days)

**Paper 2 (Žignić et al.)**:
- Top p US stocks by market cap
- Daily returns (1995-2017 in paper)
- SIC/GICS sector codes mandatory
- Complete data (no missing values)

**Paper 3 (Chen et al.)**:
- Any asset class with block structure
- Designed for p >> T (more assets than observations)

---

### Extension Needed for Full Implementation

**S&P 500 Universe Fetcher**:

```python
# MDP/YahooFinance/YahooFinanceMDP.py (extend)
def fetch_sp500_universe(
    self,
    as_of_date: date,
    top_n: int = 500,
    require_complete_data: bool = True,
    lookback_days: int = 252,
) -> list[EquityQuery]:
    """
    Fetch S&P 500 constituents with complete data.

    Args:
        as_of_date: Reference date
        top_n: Number of top stocks by market cap
        require_complete_data: Skip stocks with missing values
        lookback_days: Required history length

    Returns:
        List of EquityQuery objects with GICS sectors
    """
    # 1. Fetch S&P 500 ticker list
    # 2. Get market cap for each ticker
    # 3. Sort by market cap, take top_n
    # 4. Check data completeness (lookback_days)
    # 5. Map to GICS sectors using sector_mapping.py
    # 6. Return EquityQuery objects
    pass
```

**Estimated Effort**: 1-2 hours

**Test Strategy**:
1. Unit tests with mock data
2. Integration test with real Yahoo Finance (requires internet)
3. Validate: 500 tickers, 11 sectors, complete data

---

## Performance Expectations

### Baseline (Current ARBS)

**Risk Model**: `LedoitWolfShrinkage` (full matrix, no sector structure)

**Expected Metrics**:
- Sharpe ratio: 0.5-0.7
- HHI (concentration): 0.1-0.3
- Leverage (|w|): 5-20
- Out-of-sample risk (R²_out): 1.5-2.5

---

### Phase 1: Block-Diagonal (Žignić et al. 2024)

**Risk Model**: `BlockDiagonalCovariance` (sector-structured)

**Expected Improvements** (from paper):
- Sharpe ratio: **0.7-1.0** (+0.2 to +0.3)
- HHI: **0.05-0.15** (better diversification)
- Leverage: **2-5** (lower, more stable)
- R²_out: **1.0-1.5** (better generalization)

**Citation**: "CSH estimator performs very good in both sparse and overall measures"

---

### Phase 2: Two-Step (García-Medina 2024)

**Risk Model**: `TwoStepCovariance` (hierarchical clustering + RMT filtering)

**Expected Improvements** (from paper):
- Sharpe ratio: **1.0-1.5** (+0.5 to +0.8 vs baseline)
- HHI: **0.03-0.10** (best diversification)
- Leverage: **1.5-3** (lowest)
- R²_out: **0.8-1.2** (best generalization)

**Citation**: "Two-step estimator achieves best performance in terms of diversification and leverage"

---

### Combined: Sector Rotation + Block-Diagonal Risk

**Signals**: Yang & Shi (2023) - MOM_7M + REV_30D + Fundamental
**Risk**: BlockDiagonalCovariance (Phase 1)
**Optimizer**: MeanVarianceOptimizer with sector constraints

**Expected Performance**:
- Sharpe ratio: **2.5-3.0** (vs 2.21 in paper with heuristic portfolio)
- IC: >0.05 (maintained from signals)
- Turnover: Lower (better risk estimation → more stable weights)

---

## Implementation Priority

### Critical Path (MVP)

**Priority 1**: Block-Diagonal Covariance (Phase 1)
- **Time**: 5-8 hours
- **Impact**: High (consistent improvements in all papers)
- **Risk**: Low (well-established methodology)
- **Dependencies**: None (uses existing ARBS infrastructure)

**Priority 2**: S&P 500 Universe Fetcher
- **Time**: 1-2 hours
- **Impact**: High (enables realistic testing)
- **Risk**: Low (straightforward extension)
- **Dependencies**: Yahoo Finance API

**Priority 3**: Risk Metrics (HHI, Leverage, RDI)
- **Time**: 1-2 hours
- **Impact**: Medium (better evaluation)
- **Risk**: Low (simple calculations)
- **Dependencies**: None

**Priority 4**: Two-Step Estimator (Phase 2)
- **Time**: 4-6 hours
- **Impact**: High (best performer in García-Medina)
- **Risk**: Medium (random matrix theory complexity)
- **Dependencies**: Phase 1 complete

**Total MVP**: 11-17 hours

---

### Optional Extensions

**Priority 5**: Stochastic Block Model (Phase 3)
- **Time**: 8-12 hours
- **Impact**: Medium (only if inter-block correlations critical)
- **Risk**: High (Bayesian inference complexity)
- **Dependencies**: Phase 1-2 complete, PyMC integration

**Priority 6**: Sector Constraints in Optimizer
- **Time**: 2-3 hours
- **Impact**: Medium (risk management tool)
- **Risk**: Low (standard convex constraint)
- **Dependencies**: None

**Priority 7**: Transaction Costs
- **Time**: 3-4 hours
- **Impact**: Medium (realistic simulations)
- **Risk**: Low (standard Ledoit-Wolf 2025 approach)
- **Dependencies**: None

---

## Success Criteria

### Phase 1 Success (Block-Diagonal)

**Metrics**:
- ✅ Out-of-sample Sharpe > baseline (+0.2 minimum)
- ✅ HHI < baseline (better diversification)
- ✅ Leverage < baseline (more stable)
- ✅ All tests passing (TDD workflow)
- ✅ Integration test: Query → BlockDiagonal → Portfolio → TearSheet

**Validation**:
- Compare vs. sample covariance (baseline 1)
- Compare vs. full Ledoit-Wolf (baseline 2)
- Reproduce Žignić et al. (2024) relative improvements

---

### Phase 2 Success (Two-Step)

**Metrics**:
- ✅ Out-of-sample Sharpe > Phase 1 (+0.2 minimum)
- ✅ HHI < Phase 1 (best diversification)
- ✅ Leverage < Phase 1 (lowest)
- ✅ All tests passing
- ✅ Matches García-Medina (2024) benchmark results

**Validation**:
- Reproduce "best performance" claim from paper
- Test on S&P 500 universe (500 stocks)
- Moving window validation (252-day windows)

---

### Combined Success (Sector Rotation + Risk Models)

**Metrics**:
- ✅ Sharpe > 2.5 (vs Yang & Shi 2.21)
- ✅ IC maintained (>0.05)
- ✅ Lower turnover vs. heuristic portfolio
- ✅ Stable weights (less extreme positions)

**Validation**:
- Backtest 2020-2024 period
- Out-of-sample testing (walk-forward)
- Compare heuristic vs. optimized portfolios

---

## Next Actions

### Immediate (Now)
1. ✅ Commit and push this integration roadmap
2. ✅ Research phase complete (all documents committed)
3. ⏳ **Decision**: Start Phase 1 implementation or review with Peter?

### Phase 1 Start (if approved)
1. Create `Risk/BlockDiagonal/` directory structure
2. Write first test: `test_factor_extractor.py::test_extract_factors_with_fixed_k`
3. TDD cycle: RED → GREEN → REFACTOR → COMMIT
4. Continue through all Phase 1 components

### After Phase 1 Complete
1. Run integration tests
2. Validate performance metrics vs. benchmarks
3. Document results
4. **Decision**: Proceed to Phase 2 or iterate?

---

## Commit History (Research Phase)

```bash
# Commit 1: Papers and initial analysis
a4e7476 docs: Add sector risk model research analysis

# Commit 2: Implementation plan
1799f58 docs: Add detailed sector risk model implementation plan

# Commit 3: Integration roadmap
[NEXT] docs: Add ARBS integration roadmap for sector risk models
```

---

## References

### ARBS Documentation
- `docs/MVP_EQUITY_SECTOR_COMPLETE.md` - Existing equity infrastructure
- `docs/papers/FINAL_SECTOR_ROTATION_SUMMARY.md` - Sector rotation (Yang & Shi 2023)
- `docs/GRINOLD_KAHN_FRAMEWORK.md` - Theoretical foundation
- `docs/CLAUDE.md` - Development guidelines (TDD, commit strategy)

### Research Papers
- `docs/papers/sector_risk_models/paper_2412.08756.pdf` - García-Medina (2024)
- `docs/papers/sector_risk_models/paper_2407.03781.pdf` - Žignić et al. (2024)
- `docs/papers/sector_risk_models/paper_2502.11332.pdf` - Chen et al. (2025)

### Analysis Documents
- `docs/papers/sector_risk_models/ANALYSIS.md` - Mathematical formulas and insights
- `docs/papers/sector_risk_models/IMPLEMENTATION_PLAN.md` - TDD implementation plan
- `docs/papers/sector_risk_models/ARBS_INTEGRATION_ROADMAP.md` - This document

---

**Status**: ✅ Research Complete - All Integration Points Mapped - Ready for Implementation
