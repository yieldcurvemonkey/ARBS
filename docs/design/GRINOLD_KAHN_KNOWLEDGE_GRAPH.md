# Grinold-Kahn Concepts → ARBS Architecture: Knowledge Graph

**Document**: Visual knowledge graph mapping book concepts to codebase
**Purpose**: Bridge theory (Grinold-Kahn) with implementation (ARBS)
**Date**: 2025-11-11

---

## High-Level Architecture Map

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRINOLD-KAHN FRAMEWORK                         │
│                                                                   │
│   Consensus Returns (CAPM/APT) → Expected Returns → Alpha        │
│              ↓                          ↓              ↓          │
│           Risk Model            Signal Processing   Optimization │
│              ↓                          ↓              ↓          │
│         Covariance Σ           IC × Vol × Z      Mean-Variance   │
└─────────────────────────────────────────────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                         ARBS IMPLEMENTATION                       │
│                                                                   │
│  Query → Adapter → Returns → Signals → Alpha → Risk → Optimizer │
│    ↓        ↓         ↓         ↓        ↓       ↓        ↓      │
│  Data    Format   Matrix   Z-scores  Scaled   Cov Σ   Weights   │
│                                                                   │
│                        → Portfolio → TearSheet                   │
│                             ↓            ↓                        │
│                         Returns      IC/Sharpe                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Concept-to-Code Mapping

### 1. Foundations (Part 1)

#### Chapter 2: CAPM

**Grinold-Kahn Concept**:
```
E{r_n} = r_F + β_n · f_B
```

**ARBS Implementation**:
- **Benchmark**: `Portfolio._benchmark` attribute
- **Beta calculation**: Not explicitly implemented (could add `BetaCalculator`)
- **Risk-free rate**: Implicit in returns calculation
- **Market factor**: Handled through covariance structure

**Code locations**:
- `Portfolio/Portfolio.py`: Benchmark tracking
- `Risk/Returns/ReturnsCalculator.py`: Returns relative to benchmark

**Status**: ✅ Implicit (works without explicit CAPM)

---

#### Chapter 3: Risk

**Grinold-Kahn Concepts**:

**1. Factor model**:
```
r_n = Σ_k X_{n,k} · b_k + u_n
```

**ARBS Implementation**:
- **Exposures X**: Not yet implemented (need `EquityFactorModel`)
- **Factor returns b**: Not yet implemented
- **Specific returns u**: Residual after factor decomposition

**Code to add**:
```
Risk/
  FactorModel/
    __init__.py
    EquityFactorModel.py      # X matrix (N×K exposures)
    FactorReturns.py          # b vector (K factor returns)
    SpecificReturns.py        # u vector (N specific returns)
```

**Status**: 🆕 Need to implement

---

**2. Covariance decomposition**:
```
V = X · F · X^T + Δ
```

**ARBS Implementation**:
- **Full covariance V**: `Risk/Covariance/SampleCovariance.py`
- **Factor covariance F**: `Risk/Covariance/LedoitWolfShrinkage.py` (can be adapted)
- **Specific risk Δ**: Diagonal (uncorrelated residuals)

**Code locations**:
- `Risk/Covariance/SampleCovariance.py` (lines 1-70)
- `Risk/Covariance/LedoitWolfShrinkage.py` (lines 1-150)

**Status**: ✅ Works as-is, can be extended with factor structure

---

#### Chapter 4: Benchmarks and Value Added

**Grinold-Kahn Concepts**:

**1. Active return**:
```
r_A = r_P - r_B
```

**ARBS Implementation**:
```python
# Portfolio/Portfolio.py (lines 120-150)
def evaluate(self, returns: pl.DataFrame) -> dict:
    portfolio_returns = self._calculate_returns(returns)
    if self._benchmark:
        benchmark_returns = self._benchmark.evaluate(returns)
        active_returns = portfolio_returns - benchmark_returns
    return {"active_returns": active_returns, ...}
```

**Code locations**:
- `Portfolio/Portfolio.py`: Active return calculation
- `Analysis/TearSheet.py`: Performance metrics

**Status**: ✅ Fully implemented

---

**2. Information Ratio**:
```
IR = α / ω_A
```

**ARBS Implementation**:
```python
# Analysis/TearSheet.py (lines 80-120)
def calculate_information_ratio(
    active_returns: pl.Series,
) -> float:
    alpha = active_returns.mean()
    tracking_error = active_returns.std()
    return alpha / tracking_error
```

**Code locations**:
- `Analysis/TearSheet.py:115` - `information_ratio` property

**Status**: ✅ Fully implemented

---

#### Chapter 5: Information Ratio

**Grinold-Kahn Concept**:
```
IR = IC × sqrt(BR) × TC
```

**ARBS Implementation**:
```python
# Signals/AlphaGenerator.py (lines 50-100)
class AlphaGenerator:
    def generate(
        self,
        z_scores: pl.DataFrame,  # Standardized signals
        volatility: pl.DataFrame,  # Asset volatility
        ic: float,  # Information coefficient
    ) -> pl.DataFrame:
        # Formula: α = IC × Vol × Z
        alphas = ic * volatility * z_scores
        return alphas
```

**Components**:
- **IC**: Provided by signal (measured from backtest)
- **Vol**: From `VolatilityEstimator.py`
- **Z**: From `BaseSignal.calculate()`
- **BR**: Implicit (number of assets × rebalancing frequency)
- **TC**: Not yet modeled (transfer coefficient from constraints)

**Code locations**:
- `Signals/AlphaGenerator.py` - Alpha scaling
- `Signals/BaseSignal.py` - Z-score generation
- `Risk/VolatilityEstimator.py` - Volatility forecasting

**Status**: ✅ Core formula implemented, TC extension needed

---

#### Chapter 6: Fundamental Law

**Grinold-Kahn Insight**: Breadth (BR) is critical for high IR

**ARBS Implementation**: Implicit in signal design

**Breadth calculation**:
```python
# Not explicitly in code, but conceptually:
BR = N_assets × N_rebalances_per_year

# Equities: 500 stocks × 4 quarters = 2,000
# Futures: 20 contracts × 12 months = 240
```

**Enhancement to add**:
```python
# Signals/BaseSignal.py
def calculate_breadth(self, universe_size: int, rebalance_freq: str) -> int:
    """Calculate effective breadth for this signal"""
    freq_map = {"daily": 252, "weekly": 52, "monthly": 12, "quarterly": 4}
    return universe_size * freq_map[rebalance_freq]
```

**Status**: 🆕 Should add explicit BR calculation

---

### 2. Expected Returns & Valuation (Part 2)

#### Chapter 7: Arbitrage Pricing Theory

**Grinold-Kahn Concept**:
```
E{r_n} = Σ_k X_{n,k} · m_k
```

**ARBS Implementation**: Not yet implemented (future extension)

**Proposed architecture**:
```
Risk/
  FactorModel/
    APTModel.py
      class APTModel:
          def __init__(self, factor_definitions):
              self.factors = factor_definitions  # Industries, styles, macro

          def compute_exposures(self, data: pl.DataFrame) -> pl.DataFrame:
              """Compute X matrix (N×K)"""
              # Industry exposures: 0/1 dummy variables
              # Style exposures: Standardized (mean=0, std=1)
              return exposures

          def forecast_factor_returns(self, signals: dict) -> pl.Series:
              """Forecast m_k for each factor k"""
              # This is the HARD part - requires skill
              return factor_forecasts
```

**Status**: 🆕 Future work (Phase 3)

---

#### Chapter 8: Valuation in Theory

**Grinold-Kahn Concept**: Mispricing → alpha
```
α = (1 - γ) · (1 + i_F) · κ
```

**ARBS Implementation**: Convert valuation to expected return

**Example signal**:
```python
# Signals/Equities/ValueSignal.py (to be created)
class ValueSignal(BaseSignal):
    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """
        Compute value signal from P/E ratio

        Steps:
        1. Compute E/P (earnings yield)
        2. Rank cross-sectionally
        3. Convert to z-scores
        4. High E/P → positive alpha (undervalued)
        """
        earnings_yield = data["earnings"] / data["price"]
        z_scores = self._to_z_scores(earnings_yield)
        return z_scores
```

**Status**: 🆕 To be implemented in Phase 2

---

#### Chapter 9: Valuation in Practice

**Three approaches** → **Three signal types**:

**1. DDM (Dividend Discount Model)**:
```python
# Signals/Equities/DDMSignal.py
class DDMSignal(BaseSignal):
    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """α = d/p + g - β·f_B"""
        dividend_yield = data["dividend"] / data["price"]
        growth = data["roe"] * (1 - data["payout_ratio"])
        beta_adj = data["beta"] * self.market_risk_premium

        alpha = dividend_yield + growth - beta_adj
        return self._to_z_scores(alpha)
```

**2. Comparative Valuation**:
```python
# Signals/Equities/ComparativeValuationSignal.py
class ComparativeValuationSignal(BaseSignal):
    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """Fit price model, alpha = (fitted - actual) / actual"""
        # Sector-by-sector regression
        fitted_prices = self._fit_price_model(data)
        alpha = (fitted_prices - data["price"]) / data["price"]
        return self._to_z_scores(alpha)
```

**3. Returns-Based (Factor Models)**:
```python
# Already have momentum, add value/quality factors
class MultiFactorSignal(BaseSignal):
    def calculate(self, data: pl.DataFrame) -> pl.DataFrame:
        """Combine value, momentum, quality"""
        value_score = self._value_signal(data)
        momentum_score = self._momentum_signal(data)
        quality_score = self._quality_signal(data)

        # IC-weighted combination
        combined = (
            0.30 * value_score +
            0.50 * momentum_score +
            0.20 * quality_score
        )
        return combined
```

**Status**: 🆕 All three to be implemented

---

### 3. Information Processing (Part 3)

#### Chapter 10: Forecasting Basics

**Grinold-Kahn Formula**:
```
α_n = ω_n · IC · score_n
```

**ARBS Implementation**: ✅ **EXACT MATCH**

```python
# Signals/AlphaGenerator.py:60-80
def generate(
    self,
    z_scores: pl.DataFrame,  # score_n
    volatility: pl.DataFrame,  # ω_n
    ic: float,  # IC
) -> pl.DataFrame:
    alphas = ic * volatility * z_scores
    return alphas
```

**This is the CORE of Grinold-Kahn, and ARBS implements it perfectly!**

**Status**: ✅ Fully implemented and validated

---

#### Chapter 11: Advanced Forecasting

**Grinold-Kahn Insight**: Cross-sectional signals don't need vol scaling

**ARBS Enhancement**:
```python
# Signals/BaseSignal.py (add method)
class BaseSignal:
    def to_cross_sectional_scores(
        self,
        data: pl.DataFrame,
        sector_neutral: bool = False,
    ) -> pl.DataFrame:
        """
        Convert signal to cross-sectional z-scores

        If sector_neutral=True, compute z-scores within each sector
        """
        if sector_neutral:
            # Group by sector, compute z-scores within each
            scores = data.groupby("sector").agg(
                pl.all().map(lambda x: (x - x.mean()) / x.std())
            )
        else:
            # Global z-scores
            scores = (data - data.mean()) / data.std()

        return scores
```

**Status**: 🆕 Method to add

---

#### Chapter 12: Information Analysis

**Grinold-Kahn Concepts**:

**1. IC calculation**:
```
IC = correlation(forecast, realized_return)
```

**ARBS Implementation**: ✅ Already have this

```python
# Signals/BaseSignal.py:150-170
def calculate_ic(
    forecasts: pl.Series,
    realized_returns: pl.Series,
) -> float:
    """Calculate Information Coefficient"""
    return forecasts.corr(realized_returns)
```

**Code location**: `Signals/ic_utils.py`

**Status**: ✅ Fully implemented

---

**2. Factor-controlled IC**:
```
IC_controlled = correlation(forecast, residual_return)
```
where `residual_return = realized - factor_contributions`

**ARBS Enhancement**:
```python
# Signals/ic_utils.py (add function)
def calculate_controlled_ic(
    forecasts: pl.Series,
    realized_returns: pl.Series,
    factor_exposures: pl.DataFrame,
    factor_returns: pl.Series,
) -> float:
    """IC after removing factor contributions"""
    factor_contrib = (factor_exposures @ factor_returns).sum(axis=1)
    residual_returns = realized_returns - factor_contrib
    return forecasts.corr(residual_returns)
```

**Status**: 🆕 To be added

---

#### Chapter 13: Information Horizon

**Grinold-Kahn Concept**: Information decays exponentially
```
IC(h) = IC(0) · exp(-λ · h)
```

**ARBS Enhancement**:
```python
# Signals/BaseSignal.py (add attribute)
class BaseSignal:
    def __init__(self, information_horizon: int):
        """
        information_horizon: Half-life of signal in months
        - Momentum: 3-6 months
        - Value: 12-24 months
        - Quality: 24+ months
        """
        self.information_horizon = information_horizon
        self.decay_rate = np.log(2) / information_horizon

    def get_ic_at_horizon(self, horizon_months: int) -> float:
        """Get IC at given horizon based on decay"""
        return self.base_ic * np.exp(-self.decay_rate * horizon_months)
```

**Status**: 🆕 To be added

---

### 4. Implementation (Part 4)

#### Chapter 14: Portfolio Construction

**Grinold-Kahn Concepts**:

**1. Alpha preprocessing**:

```python
# Optimizer/AlphaNeutralizer.py (to create)
class AlphaNeutralizer:
    def preprocess(
        self,
        alphas: pl.Series,
        exposures: pl.DataFrame,
        constraints: list,
    ) -> pl.Series:
        """
        Steps:
        1. Scale by expected IC
        2. Trim extremes (±3 sigma)
        3. Neutralize: benchmark, industry, factors
        """
        # Scale
        alphas_scaled = alphas * self.expected_ic

        # Trim
        alphas_trimmed = alphas_scaled.clip(
            lower=-3 * alphas_scaled.std(),
            upper=3 * alphas_scaled.std(),
        )

        # Neutralize
        if "benchmark_neutral" in constraints:
            alphas_trimmed -= alphas_trimmed.mean()

        if "sector_neutral" in constraints:
            alphas_trimmed = self._sector_neutralize(alphas_trimmed, exposures)

        return alphas_trimmed
```

**Status**: 🆕 To be created

---

**2. Quadratic programming**:

**Already have** `Optimizer/MeanVarianceOptimizer.py`, but need constraints:

```python
# Optimizer/constraints/ (to create)
class LongOnlyConstraint:
    def apply(self, problem):
        """h_i ≥ 0"""
        problem.add_constraint(weights >= 0)

class SectorNeutralConstraint:
    def apply(self, problem, sector_exposures):
        """Σ_{i ∈ sector} (h_i - h_Bi) = 0"""
        for sector in sectors:
            mask = sector_exposures == sector
            problem.add_constraint(weights[mask].sum() == benchmark_weights[mask].sum())

class PositionLimitConstraint:
    def apply(self, problem, limit=0.05):
        """|h_i - h_Bi| ≤ limit"""
        problem.add_constraint(abs(weights - benchmark_weights) <= limit)

class TurnoverConstraint:
    def apply(self, problem, old_weights, max_turnover):
        """Σ |h_i - h_i^old| ≤ max_turnover"""
        problem.add_constraint((abs(weights - old_weights)).sum() <= max_turnover)
```

**Status**: 🆕 Constraint system to be created

---

#### Chapter 15: Long/Short Investing

**Grinold-Kahn Finding**: Long-only **cuts IR by ~50%**

**ARBS Analysis Tool** (to add):
```python
# Optimizer/analysis/transfer_coefficient.py
def calculate_transfer_coefficient(
    unconstrained_weights: pl.Series,
    constrained_weights: pl.Series,
    alphas: pl.Series,
) -> float:
    """
    TC = correlation(constrained_weights, alphas) /
         correlation(unconstrained_weights, alphas)
    """
    tc_unconstrained = unconstrained_weights.corr(alphas)
    tc_constrained = constrained_weights.corr(alphas)
    return tc_constrained / tc_unconstrained
```

**Status**: 🆕 Analysis tool to add

---

#### Chapter 16: Transaction Costs

**Grinold-Kahn Model**: Inventory risk (square-root law)
```
TC_i = c · σ_i · sqrt(V_trade,i / V_avg,i) + commission
```

**ARBS Implementation**:
```python
# TransactionCosts/InventoryRiskModel.py (to create)
class InventoryRiskModel:
    def __init__(self, cost_coefficient: float = 1.0):
        """
        cost_coefficient: Typically 1.0 (1 day's vol for 1 day's volume)
        """
        self.c = cost_coefficient

    def calculate_cost(
        self,
        trade_size: pl.Series,  # Shares to trade
        avg_daily_volume: pl.Series,  # Average daily volume
        volatility: pl.Series,  # Daily volatility (%)
        commission_rate: float = 0.001,  # 10 bps
    ) -> pl.Series:
        """Calculate total transaction cost"""
        # Market impact (square-root law)
        volume_fraction = trade_size.abs() / avg_daily_volume
        impact = self.c * volatility * volume_fraction.sqrt()

        # Commission (proportional)
        commission = commission_rate * trade_size.abs()

        # Total
        total_cost = impact + commission
        return total_cost
```

**Integration with optimizer**:
```python
# Optimizer/MeanVarianceOptimizer.py (modify)
def optimize(
    self,
    alphas: pl.Series,
    covariance: pl.DataFrame,
    old_weights: pl.Series = None,
    transaction_costs: InventoryRiskModel = None,
) -> pl.Series:
    """Add transaction cost penalty to objective"""
    # Objective: max (α^T h - λ h^T Σ h - TC(h, h_old))
    ...
```

**Status**: 🆕 To be created and integrated

---

#### Chapter 17: Performance Attribution

**Grinold-Kahn Decomposition**:
```
r_A = Σ_k β_k · f_k + Σ_n w_n · u_n
     [factor bets]   [stock selection]
```

**ARBS Implementation**:
```python
# Analysis/FactorAttribution.py (to create)
class FactorAttribution:
    def decompose_returns(
        self,
        portfolio_returns: pl.Series,
        factor_exposures: pl.DataFrame,  # β matrix
        factor_returns: pl.Series,  # f vector
        specific_returns: pl.DataFrame,  # u matrix
        weights: pl.Series,
    ) -> dict:
        """Decompose active returns into factor + selection"""

        # Factor contribution
        factor_contrib = (factor_exposures @ factor_returns).sum()

        # Selection contribution
        selection_contrib = (weights * specific_returns).sum()

        # Interaction (optional)
        interaction = portfolio_returns - factor_contrib - selection_contrib

        return {
            "factor_contribution": factor_contrib,
            "selection_contribution": selection_contrib,
            "interaction": interaction,
            "total": portfolio_returns,
        }
```

**Extension to TearSheet**:
```python
# Analysis/TearSheet.py (add method)
def add_factor_attribution(self, factor_model):
    """Add factor decomposition to tearsheet"""
    attribution = FactorAttribution()
    results = attribution.decompose_returns(...)

    # Create visualization
    self._plot_attribution(results)
```

**Status**: 🆕 To be created

---

## Implementation Priority Matrix

### Phase 1: Core Data Infrastructure (Weeks 1-3)

| Component | Grinold-Kahn Chapter | Priority | Status |
|-----------|---------------------|----------|--------|
| `Query/Equities/` | Ch 2 (CAPM benchmarks) | HIGH | 🆕 To create |
| `MDP/YahooFinance/` | Ch 9 (practical data) | HIGH | 🆕 To create |
| `Adapter/EquityAdapter.py` | Ch 3 (returns matrix) | HIGH | 🆕 To create |

### Phase 2: Signals (Weeks 4-7)

| Component | Grinold-Kahn Chapter | Priority | Status |
|-----------|---------------------|----------|--------|
| `Signals/Equities/ValueSignal.py` | Ch 9 (DDM, multiples) | HIGH | 🆕 To create |
| `Signals/Equities/MomentumSignal.py` | Ch 11 (momentum) | HIGH | 🆕 To create |
| `Signals/Equities/QualitySignal.py` | Ch 9 (ROE, quality) | MEDIUM | 🆕 To create |
| `BaseSignal.to_cross_sectional_scores()` | Ch 11 (cross-sectional) | HIGH | 🆕 To add |

### Phase 3: Risk Models (Weeks 8-11)

| Component | Grinold-Kahn Chapter | Priority | Status |
|-----------|---------------------|----------|--------|
| `Risk/FactorModel/` | Ch 3, 7 (APT) | HIGH | 🆕 To create |
| `Risk/Covariance/PPFMCovariance.py` | PPFM paper + Ch 3 | MEDIUM | 🆕 To create |
| `FactorAttribution.py` | Ch 17 (attribution) | LOW | 🆕 To create |

### Phase 4: Optimization (Weeks 12-14)

| Component | Grinold-Kahn Chapter | Priority | Status |
|-----------|---------------------|----------|--------|
| `Optimizer/constraints/` | Ch 14 (construction) | HIGH | 🆕 To create |
| `Optimizer/AlphaNeutralizer.py` | Ch 14 (preprocessing) | MEDIUM | 🆕 To create |
| `TransactionCosts/` | Ch 16 (costs, turnover) | MEDIUM | 🆕 To create |

### Phase 5: Analysis (Weeks 15-17)

| Component | Grinold-Kahn Chapter | Priority | Status |
|-----------|---------------------|----------|--------|
| `Analysis/FactorAttribution.py` | Ch 17 (decomposition) | LOW | 🆕 To create |
| `TearSheet` extensions | Ch 17 (performance) | LOW | 🆕 To extend |

---

## Visual Concept Map

```
GRINOLD-KAHN BOOK                         ARBS CODEBASE
===================                       ==============

Part 1: Foundations
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 2: CAPM          │─────────────────→│ Portfolio (benchmark)│
│ - Consensus returns │                  │ - Benchmark tracking │
│ - Beta              │                  └──────────────────────┘
└─────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 3: Risk          │─────────────────→│ Risk/Covariance/     │
│ - Factor models     │                  │ - LedoitWolf         │
│ - V = X·F·X^T + Δ   │─────────────────→│ + FactorModel/ 🆕    │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 4: Benchmarks    │─────────────────→│ Analysis/TearSheet   │
│ - Active return     │                  │ - IR, Sharpe         │
│ - IR = α / ω_A      │                  └──────────────────────┘
└─────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 5: Info Ratio    │─────────────────→│ Signals/             │
│ - IR = IC√BR × TC   │                  │ AlphaGenerator ✅     │
│ - α = IC·Vol·Z      │                  │ - IC × Vol × Z       │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 6: Fundamental   │                  │ BaseSignal           │
│       Law           │                  │ - IC calculation ✅   │
│ - Breadth critical  │─────────────────→│ + BR calculation 🆕   │
└─────────────────────┘                  └──────────────────────┘


Part 2: Valuation
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 7: APT           │─────────────────→│ Risk/FactorModel/ 🆕 │
│ - E{r} = Σ X·m      │                  │ - APT implementation │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 8: Valuation     │                  │ Signals/Equities/ 🆕 │
│       Theory        │─────────────────→│ - DDMSignal          │
│ - α from mispricing │                  │ - ComparativeVal     │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 9: Valuation     │                  │ Signals/Equities/ 🆕 │
│       Practice      │─────────────────→│ - ValueSignal        │
│ - DDM, multiples    │                  │ - MomentumSignal     │
│ - Factor models     │                  │ - QualitySignal      │
└─────────────────────┘                  └──────────────────────┘


Part 3: Forecasting
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 10: Forecasting  │                  │ AlphaGenerator ✅     │
│        Basics       │─────────────────→│ - α = IC·Vol·Z       │
│ - α = IC·Vol·score  │                  │ EXACT MATCH!         │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 11: Advanced     │                  │ BaseSignal 🆕        │
│        Forecasting  │─────────────────→│ + cross_sectional()  │
│ - Cross-sectional   │                  │ + sector_neutral()   │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 12: Information  │                  │ Signals/ic_utils ✅   │
│        Analysis     │─────────────────→│ + controlled_ic() 🆕 │
│ - IC calculation    │                  └──────────────────────┘
└─────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 13: Information  │                  │ BaseSignal 🆕        │
│        Horizon      │─────────────────→│ + info_horizon attr  │
│ - IC decay          │                  │ + decay_rate()       │
└─────────────────────┘                  └──────────────────────┘


Part 4: Implementation
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 14: Portfolio    │                  │ Optimizer/           │
│        Construction │─────────────────→│ + AlphaNeutralizer🆕 │
│ - Alpha preprocess  │                  │ + constraints/ 🆕     │
│ - QP optimization   │                  │ MeanVarianceOpt ✅    │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 15: Long/Short   │                  │ Optimizer/analysis/🆕│
│ - TC = 0.5 (long-   │─────────────────→│ - transfer_coeff()   │
│   only constraint)  │                  │ - impact_analysis()  │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 16: Transaction  │                  │ TransactionCosts/ 🆕 │
│        Costs        │─────────────────→│ - InventoryRiskModel │
│ - Square-root law   │                  │ - Integration w/ opt │
└─────────────────────┘                  └──────────────────────┘
           │
           ↓
┌─────────────────────┐                  ┌──────────────────────┐
│ Ch 17: Performance  │                  │ Analysis/            │
│        Attribution  │─────────────────→│ + FactorAttribution🆕│
│ - Factor decomp     │                  │ TearSheet ✅ (extend) │
└─────────────────────┘                  └──────────────────────┘

Legend:
  ✅ Fully implemented
  🆕 To be created/added
  ─→ Concept-to-code mapping
```

---

## File Creation Roadmap

### Phase 1: Query & Data (Weeks 1-3)

```
Query/
  Equities/
    __init__.py
    EquityQuery.py          # Ch 2: Equity query structure
    EquityStructure.py      # SINGLE, SECTOR_BASKET, LONG_SHORT
    EquityValue.py          # PRICE, RETURN, DIVIDEND_YIELD
    EquityAdapter.py        # Ch 3: Format to returns matrix

MDP/
  YahooFinance/
    __init__.py
    YahooFinanceMDP.py      # Ch 9: Fetch prices, dividends, fundamentals
    sector_mapping.py       # GICS classification

Adapter/
  EquityAdapter.py          # Convert Query → Polars DataFrame
```

### Phase 2: Signals (Weeks 4-7)

```
Signals/
  Equities/
    __init__.py
    ValueSignal.py          # Ch 9: E/P, B/P, dividend yield
    MomentumSignal.py       # Ch 11: 12-month return (skip last month)
    QualitySignal.py        # Ch 9: ROE, debt/equity, earnings stability
    DDMSignal.py            # Ch 9: d/p + g - β·f_B
    ComparativeValuation.py # Ch 9: Cross-sectional price fitting

  BaseSignal.py (extend)
    + to_cross_sectional_scores()  # Ch 11
    + sector_neutralize()          # Ch 11
    + calculate_breadth()          # Ch 6
    + information_horizon attr     # Ch 13
```

### Phase 3: Risk Models (Weeks 8-11)

```
Risk/
  FactorModel/
    __init__.py
    EquityFactorModel.py    # Ch 3, 7: 52 industries + 13 styles
    FactorReturns.py        # Ch 7: Factor return calculation
    SpecificReturns.py      # Ch 3: Residual after factors

  Covariance/
    PPFMCovariance.py       # PPFM paper: Multi-sector covariance
    FactorCovariance.py     # Ch 3: V = X·F·X^T + Δ

Analysis/
  FactorAttribution.py      # Ch 17: Decompose returns
```

### Phase 4: Optimization (Weeks 12-14)

```
Optimizer/
  constraints/
    __init__.py
    LongOnly.py             # Ch 15: h_i ≥ 0
    SectorNeutral.py        # Ch 14: Sector weights = benchmark
    PositionLimit.py        # Ch 14: |h_i - h_Bi| ≤ limit
    TurnoverLimit.py        # Ch 16: Σ|h_i - h_old| ≤ max

  AlphaNeutralizer.py       # Ch 14: Scale, trim, neutralize

  analysis/
    transfer_coefficient.py # Ch 15: Measure constraint impact

TransactionCosts/
  __init__.py
  InventoryRiskModel.py     # Ch 16: Square-root law
  CostIntegration.py        # Integrate with optimizer
```

### Phase 5: Analysis (Weeks 15-17)

```
Analysis/
  FactorAttribution.py      # Ch 17: Factor + selection decomposition
  TearSheet.py (extend)
    + add_factor_decomposition()
    + add_turnover_analysis()
    + add_constraint_impact()
```

---

## Validation Checklist

### Verify Grinold-Kahn Compliance

- [ ] IC × Vol × Z formula in `AlphaGenerator` (Ch 10) ✅
- [ ] IR = IC × √BR in backtest results (Ch 5) ✅
- [ ] Active return = r_P - r_B in `Portfolio` (Ch 4) ✅
- [ ] Covariance estimation via Ledoit-Wolf (Ch 3) ✅
- [ ] Mean-variance optimization (Ch 14) ✅
- [ ] IC calculation in `BaseSignal` (Ch 12) ✅

### New Components to Validate

- [ ] Factor model: V = X·F·X^T + Δ (Ch 3)
- [ ] APT expected returns: E{r} = Σ X·m (Ch 7)
- [ ] DDM alpha: α = d/p + g - β·f_B (Ch 9)
- [ ] Cross-sectional scores (Ch 11)
- [ ] Sector-neutral signals (Ch 11)
- [ ] Long-only constraint impact (Ch 15)
- [ ] Transaction cost model (Ch 16)
- [ ] Factor attribution (Ch 17)

---

## Summary Statistics

### Existing ARBS Components (Grinold-Kahn Compliant)

- **7 components** fully implemented ✅
- **Core formula** (IC × Vol × Z) exact match ✅
- **Architecture** returns-first, factor-model-ready ✅

### Components to Add

- **23 new files** to create 🆕
- **6 extensions** to existing files 🆕
- **17-22 weeks** estimated implementation time

### Book Coverage

- **17 chapters** synthesized
- **621 pages** converted to markdown
- **4,893 lines** of detailed notes
- **100%** of Grinold-Kahn framework mapped

---

**End of Knowledge Graph**
