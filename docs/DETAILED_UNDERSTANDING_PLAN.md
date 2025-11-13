# Detailed Understanding Plan: Cross-Asset Portfolio Construction

**Date**: 2025-11-13
**Status**: Framework Synthesis

---

## Core Understanding

### Central Thesis

**Cross-asset portfolio construction follows identical mathematical structures across equity sectors and global macro currencies.**

The key insight: **Sectors ARE currencies** from a factor decomposition perspective.

```
Equity Domain              Global Macro Domain
─────────────             ──────────────────
Market (SPY)          →   Global rates (Fed policy)
Sector (Tech)         →   Currency (USD)
Stock (AAPL)          →   Tenor point (USD 10Y)
Sector ETF (XLK)      →   Currency index
```

### Mathematical Foundation

**Factor Decomposition** (identical structure):

```
Equity:  r_stock,t = β_market·r_market,t + β_sector·r_sector,t + ε_t
Macro:   r_tenor,t = β_global·r_global,t + β_currency·r_currency,t + ε_t
```

Where:
- β_market / β_global = exposure to systematic factor
- β_sector / β_currency = exposure to intermediate factor
- ε = idiosyncratic component

**Covariance Structure** (block-diagonal with off-diagonal correlations):

```
Σ = [
    [Σ_sector1,  ρ₁₂·Σ₁₂,    ρ₁₃·Σ₁₃,    ...]
    [ρ₁₂·Σ₁₂,    Σ_sector2,  ρ₂₃·Σ₂₃,    ...]
    [ρ₁₃·Σ₁₃,    ρ₂₃·Σ₂₃,    Σ_sector3,  ...]
    ...
]
```

Properties:
- Strong within-sector/currency correlation (ρ ≈ 0.85-0.95)
- Moderate cross-sector/currency correlation (ρ ≈ 0.40-0.70)
- Pure block-diagonal is too restrictive (EUR/CHF ≠ 0)

### Portfolio Constraints: The Core Problem

**Equity formulation**:
> "You cannot short every sector against SPY simultaneously."

**Macro formulation**:
> "You cannot short the 5Y on a 2-5-10 butterfly in every currency."

**Mathematical constraint**:
```
For correlation cluster C with tickers T_C:
    sum_{i ∈ T_C} I(|w_i| > ε) ≤ max_positions_per_cluster

Where:
    I(·) = indicator function
    w_i = weight in asset i
    ε = minimum position threshold (e.g., 0.01)
```

**Why this matters**:
- High correlation → similar returns
- Multiple positions in same cluster → concentration risk
- Loss amplification during drawdowns
- Reduced effective diversification

### Three-Layer Architecture

**Layer 1: Signal Generation**

```
Raw signals → Cross-sectional normalization → Scaled alphas
```

Components:
- **Momentum/Carry**: Trend-following (12-month for equity, forward-spot for macro)
- **Mean Reversion**: Relative value (sector vs SPY, butterfly vs fair value)
- **Fundamental/Quality**: Economic factors (P/E for equity, real rates for macro)

Formula: α = IC × Vol × Z (Grinold-Kahn 1999)
- IC = information coefficient (signal quality)
- Vol = volatility forecast (risk scaling)
- Z = standardized signal (z-score)

**Layer 2: Risk Modeling**

```
Returns → Covariance estimation → Correlation clustering
```

Three approaches:
1. **Block-diagonal** (Žignić et al. 2024)
   - Sectors independent
   - Σ = B·Cov(F)·B^T + block_diag(Ψ₁, ..., Ψₘ)
   - Best for equity sectors

2. **Two-step** (García-Medina et al. 2024)
   - Hierarchical clustering + RMT filtering
   - Discovers structure automatically
   - Best out-of-sample performance

3. **Stochastic block** (Chen et al. 2025)
   - Σ = α·BlockDiag + (1-α)·FullCov
   - Allows cross-sector/currency correlations
   - Best for macro (EUR/CHF correlation ≠ 0)

**Layer 3: Portfolio Construction**

```
Alphas + Covariance + Constraints → Optimal weights
```

Optimization:
```
maximize: α^T · w
subject to:
    w^T · Σ · w ≤ risk_budget           (risk constraint)
    sum(w) = 0                          (dollar-neutral)
    sum(|w|) ≤ gross_leverage           (leverage limit)
    cluster_constraint(w, C) ≤ max_pos  (NEW: correlation clustering)
```

### Volatility Arbitrage Extension

**Core insight**: When correlation is high, IV/RV ratios should converge.

**Mathematical relationship**:
```
For assets A, B with correlation ρ:
    When ρ → 1: IV_A/RV_A ≈ IV_B/RV_B

Signal = (IV_B/RV_B - IV_A/RV_A) × ρ
```

**Trading logic**:
1. Calculate realized vol: RV = std(returns) × √252
2. Get implied vol from options: IV
3. Calculate ratios: IV/RV per asset
4. For pairs with ρ > 0.85:
   - Compute spread: IV/RV_B - IV/RV_A
   - Z-score the spread (lookback=60)
   - When |z| > 2: sell rich vol, buy cheap vol

**Risk decomposition**:
```
P&L = spread_pnl + vol_arb_pnl + correlation_pnl

Where:
    spread_pnl = positions × (spread_end - spread_start)
    vol_arb_pnl = vega × (IV_RV_end - IV_RV_start)
    correlation_pnl = cross_gamma × (ρ_end - ρ_start)
```

---

## Current Implementation Status

### What We Have (✅)

#### 1. Sector Rotation Signals (100%)
**Path**: `Signals/SectorRotation/`

**Components**:
- `SectorMomentumSignal`: 12-month momentum
- `SectorReversionSignal`: Mean reversion vs sector mean
- `FundamentalSignal`: P/E, P/B, ROE factors
- `CrossSectionalNeutralizer`: Z-score normalization
- `SectorLongShortPortfolio`: Top-N/bottom-N selection

**Quality**: Production-ready
- Follows Grinold-Kahn framework
- Comprehensive tests (156 tests passing)
- Proper cross-sectional normalization
- Dollar-neutral enforcement

**Translation to macro**: Direct
```python
# Equity
SectorMomentumSignal(lookback=252)  # 12-month momentum

# Macro
CurrencyCarrySignal(lookback=60)  # 3-month carry
```

#### 2. Sector-Based Covariance (100%)
**Path**: `Risk/Covariance/SectorBased/`

**Three implementations**:
- `BlockDiagonalCovariance`: Pure block structure
- `TwoStepCovariance`: Clustering + RMT filtering
- `StochasticBlockCovariance`: Flexible α-blending

**Quality**: Production-ready
- Common base class `SectorBasedCovarianceEstimator`
- 80 tests passing
- Handles predefined or discovered clusters
- Positive definiteness guaranteed

**Applicability**: Works as-is for macro
- Sectors → Currencies (string substitution)
- Stocks → Tenor points (string substitution)
- No code changes needed

#### 3. Alpha Generation (100%)
**Path**: `Signals/AlphaGenerator.py`

**Formula**: α = IC × Vol × Z

**Quality**: Production-ready
- 16 tests passing
- Proper scaling
- Multi-signal combination

**Applicability**: Universal (equities, macro, any asset class)

#### 4. Mean-Variance Optimization (80%)
**Path**: `Optimizer/MeanVarianceOptimizer.py`

**Features**:
- Quadratic programming (CVXPY)
- Risk budget constraints
- Leverage limits
- Long/short constraints

**Quality**: Good
- 18 tests passing
- Fast convergence (< 1s for 50 assets)

**Gap**: No correlation cluster constraints

#### 5. Portfolio Tracking (100%)
**Path**: `Asset/Portfolio.py`

**Features**:
- Composite asset pattern
- Returns-first design (Grinold-Kahn compliant)
- Nested portfolio support
- Performance attribution

**Quality**: Excellent
- 100 tests passing
- Supports hierarchical composition

### What We Don't Have (❌)

#### 1. Correlation Cluster Constraints (**CRITICAL**)

**Problem**: Optimizer doesn't limit positions per correlation cluster.

**Current behavior** (broken):
```python
# Signals for EUR, CHF, GBP butterflies (all ~0.90 correlated)
signals = {"EUR_fly": 2.5, "CHF_fly": 2.3, "GBP_fly": 2.1}

# Optimizer selects all three (concentrated bet)
weights = optimizer.optimize(signals, cov_matrix)
→ {"EUR_fly": -100k, "CHF_fly": -100k, "GBP_fly": -100k}
# Total exposure to same trade: -300k (highly correlated)
```

**Needed behavior**:
```python
# Add cluster constraint
clusters = {"EUR_bloc": ["EUR_fly", "CHF_fly"], "Sterling": ["GBP_fly"]}

weights = optimizer.optimize(
    signals, cov_matrix,
    correlation_clusters=clusters,
    max_per_cluster=2
)
→ {"EUR_fly": -100k, "CHF_fly": 0, "GBP_fly": -50k}
# Respects cluster limit (max 2 positions in EUR_bloc)
```

**Implementation path**:
1. Add `get_correlation_clusters()` to `SectorBasedCovarianceEstimator`
2. Create `ClusterAwareMeanVarianceOptimizer`
3. Add CVXPY constraints for cluster limits

**Effort**: 1-1.5 weeks
**Priority**: **CRITICAL**

#### 2. Volatility Ratio Tracking (**HIGH**)

**Problem**: No IV/RV ratio calculation.

**Missing components**:
```python
# Calculate ratios
class VolatilityRatioCalculator:
    def calculate(self, returns, implied_vols):
        RV = returns.std() * sqrt(252)
        return implied_vols / RV

# Generate signals
class CorrelationVolatilitySignal(BaseSignal):
    def calculate(self, vol_ratios, correlation_matrix):
        # Signal = (IV_RV_B - IV_RV_A) × ρ
        pass
```

**Implementation path**: See `docs/research/CORRELATION_VOLATILITY_ARBITRAGE.md`

**Effort**: 2-3 weeks (needs options data)
**Priority**: **HIGH**

#### 3. Cross-Currency Basis Signals (**MEDIUM**)

**Problem**: Only intra-currency trades (USD 2s5s10s).

**Missing**: Cross-currency pairs (EUR 5Y vs USD 5Y)

**Implementation path**:
```python
class CrossCurrencyBasisSignal(BaseSignal):
    def calculate(self, returns, correlation_matrix):
        # For EUR_5Y vs USD_5Y with ρ > 0.75
        # Calculate basis spread
        # Mean reversion signal
        pass
```

**Effort**: 1-2 weeks
**Priority**: **MEDIUM**

#### 4. Dynamic Clustering (**LOW**)

**Problem**: Static correlation clusters (don't adapt to regime changes).

**Example**:
- Normal: EUR/CHF ρ = 0.85
- Crisis: EUR/CHF ρ = 0.98

**Implementation path**: Rolling window cluster detection

**Effort**: 1 week
**Priority**: **LOW**

---

## Research Questions to Answer

### 1. Cross-Asset Factor Models

**Questions**:
- What is the 2025 consensus on unified cross-asset risk models?
- Do practitioners use block-diagonal, hierarchical, or full covariance?
- How do they handle cross-sector/currency correlations?
- What are the latest advances in factor decomposition?

**Search terms**:
- "cross-asset portfolio construction 2025"
- "unified risk model multi-asset 2025"
- "hierarchical covariance estimation 2025"

### 2. Correlation-Aware Optimization

**Questions**:
- How do practitioners enforce correlation clustering constraints?
- What methods exist for dynamic cluster detection?
- What are the latest advances in constrained portfolio optimization?
- How do they handle regime-dependent correlations?

**Search terms**:
- "correlation clustering portfolio optimization 2025"
- "regime-dependent covariance 2025"
- "constrained mean-variance optimization 2025"

### 3. Sector Rotation & Currency Carry

**Questions**:
- What is the state-of-the-art in sector rotation (2025)?
- How does it compare to currency carry strategies?
- What signals are most effective (momentum, value, quality)?
- What risk adjustments are standard?

**Search terms**:
- "sector rotation strategies 2025"
- "currency carry trade risk models 2025"
- "cross-sectional equity factors 2025"

### 4. Volatility Dispersion Trading

**Questions**:
- What is the latest research on IV/RV ratio arbitrage?
- How do practitioners implement vol dispersion strategies?
- What are the typical Sharpe ratios and ICs?
- How do they manage correlation risk?

**Search terms**:
- "volatility dispersion trading 2025"
- "implied realized volatility arbitrage 2025"
- "correlation trading strategies 2025"

### 5. Block Covariance Estimation

**Questions**:
- What are the latest methods for sector-based covariance?
- How does random matrix theory (RMT) improve estimation?
- What is consensus on shrinkage vs clustering approaches?
- How do practitioners detect optimal number of clusters?

**Search terms**:
- "block covariance estimation 2025"
- "random matrix theory portfolio 2025"
- "sector covariance shrinkage 2025"

---

## Expected Gaps & Differences

### Where We Likely Lead

1. **Unified architecture**: Single codebase for equity + macro
   - Most firms have separate systems
   - We can transfer insights between asset classes

2. **Polars-native**: Modern data pipeline
   - Most research uses pandas or R
   - We have performance advantage

3. **Comprehensive testing**: 582 tests
   - Most academic code lacks tests
   - We have production-ready infrastructure

### Where We Likely Lag

1. **Correlation cluster constraints**: Not implemented
   - This is likely standard in 2025 research
   - Critical gap

2. **Machine learning signals**: No ML yet
   - 2025 research probably uses neural networks
   - We use classical factors (momentum, carry)

3. **High-frequency data**: We use daily
   - 2025 research might use intraday
   - We're focused on daily/weekly rebalancing

4. **Transaction costs**: Not modeled yet
   - 2025 research likely has sophisticated cost models
   - We need proportional + quadratic impact

### Where We Might Differ (Intentionally)

1. **Simplicity over complexity**: Heuristic top-N/bottom-N
   - We avoid over-optimization
   - Academic research often over-fits

2. **TDD approach**: Test-driven development
   - Academic code often skips tests
   - We prioritize correctness

3. **Returns-first design**: Portfolio accepts returns not prices
   - Some implementations use prices
   - We follow Grinold-Kahn strictly

---

## Implementation Strategy After Research

### Step 1: Consensus Alignment

After gathering research, identify **consensus best practices**:
- Standard correlation clustering methods
- Accepted shrinkage techniques
- Typical constraint formulations
- Benchmark Sharpe ratios and ICs

**Action**: Implement consensus approaches first.

### Step 2: Novel Contributions

Identify where our approach differs:
- Unified equity/macro architecture
- Returns-first portfolio design
- Heuristic simplicity vs optimization complexity

**Action**: Document differences, justify with tests.

### Step 3: Orthogonalization

Break implementation into independent tasks:
1. Correlation cluster detection (no dependencies)
2. Cluster-aware optimizer (depends on #1)
3. Volatility ratio calculator (independent)
4. Vol dispersion signal (depends on #3)
5. Currency translation layer (independent)
6. Cross-currency basis signals (depends on #5)

**Tasks with no dependencies can run in parallel.**

### Step 4: Parallel Execution

Launch subagents for orthogonal tasks:
- **Agent 1**: Implement correlation clustering
- **Agent 2**: Implement volatility ratio calculator
- **Agent 3**: Research consensus on optimization constraints
- **Agent 4**: Create currency translation layer
- **Agent 5**: Benchmark against academic results

**Coordination**: Merge results after parallel execution completes.

---

## Success Criteria

### Research Phase

**Success = Clear answers to**:
1. What is 2025 consensus on cross-asset risk models?
2. How do practitioners handle correlation clustering?
3. What are typical performance benchmarks (Sharpe, IC)?
4. Where do we differ from state-of-the-art?

**Deliverable**: Comprehensive research summary document.

### Implementation Phase

**Success = Production-ready code with**:
1. Correlation cluster constraints working (tests passing)
2. Volatility ratio tracking implemented
3. Currency translation layer functional
4. Backtest achieves target metrics:
   - Sharpe > 0.7 (equity sectors)
   - Sharpe > 0.6 (global macro)
   - IC > 0.10 (equity), IC > 0.08 (macro)

**Deliverable**: End-to-end working strategies.

### Validation Phase

**Success = Academic validation**:
1. Our results match published benchmarks
2. Our methods align with 2025 consensus (where appropriate)
3. Our differences are justified and tested
4. Performance is robust out-of-sample

**Deliverable**: Validation report comparing to research.

---

## Next Steps

1. **Research gathering** (1-2 days)
   - Search arXiv, SSRN for 2025, 2024, 2023 papers
   - Focus on cross-asset, correlation clustering, vol dispersion
   - Weight toward 2025 (most recent)

2. **Gap analysis** (1 day)
   - Compare our implementation to research consensus
   - Identify what we're missing
   - Identify where we differ (and why)

3. **Task orthogonalization** (0.5 days)
   - Break down implementation into independent chunks
   - Identify dependencies
   - Plan parallel execution

4. **Parallel implementation** (1-2 weeks)
   - Launch subagents for orthogonal tasks
   - Monitor progress
   - Merge results

5. **Validation** (1 week)
   - Backtest on real data
   - Compare to academic benchmarks
   - Document results

---

**Status**: Understanding plan complete. Ready for research gathering phase.
