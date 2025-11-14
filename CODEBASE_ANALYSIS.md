# ARBS Codebase Analysis

## Executive Summary

This document provides a comprehensive analysis of the ARBS (Algorithmic Relative-value Backtesting System) codebase structure, architecture, and data flow.

**Status**: 1038/1046 tests passing (99.2%)
**Architecture**: Returns-first Grinold-Kahn compliant design
**Primary Language**: Python with Polars for data processing

---

## Abstract Source Tree

```
ARBS/
├── Core Strategy Modules
│   ├── Signals/                    # Alpha signal generation
│   │   ├── Base/                   # BaseSignal interface
│   │   ├── Futures/                # Futures-specific signals
│   │   │   ├── CarrySignal         # Carry-based alpha
│   │   │   ├── MomentumSignal      # Trend-following alpha
│   │   │   └── MeanReversionSignal # Mean reversion alpha
│   │   ├── SectorRotation/         # Sector rotation strategies
│   │   │   ├── FundamentalSignal   # Fundamental factors
│   │   │   ├── MomentumFactor      # Sector momentum
│   │   │   └── ReversionFactor     # Sector mean reversion
│   │   ├── Utils/                  # Signal utilities
│   │   │   └── FeatureEngineering  # Feature transformation
│   │   └── SignalCombiner          # Multi-signal combination
│   │
│   ├── Risk/                        # Risk modeling and estimation
│   │   ├── Base/                    # BaseCovarianceEstimator
│   │   ├── Covariance/              # Covariance estimation
│   │   │   ├── SampleCovariance     # Standard sample covariance
│   │   │   ├── LedoitWolfShrinkage  # Shrinkage estimator
│   │   │   ├── OAShrinkage          # Oracle approximation shrinkage
│   │   │   ├── ConstantCorrelation  # Constant correlation model
│   │   │   ├── DiagonalCovariance   # Diagonal model
│   │   │   ├── IdentityCovariance   # Identity model
│   │   │   ├── CorrelationClustering # Correlation-based clustering
│   │   │   └── SectorBased/         # Sector-aware models
│   │   │       ├── BaseSectorCovarianceEstimator
│   │   │       ├── BlockDiagonal/   # Block diagonal structure
│   │   │       ├── StochasticBlock/ # Stochastic block model
│   │   │       └── TwoStep/         # Two-step estimation
│   │   ├── Returns/                 # Returns calculation
│   │   │   └── ReturnsCalculator    # Standardized returns pipeline
│   │   └── Volatility/              # Volatility forecasting
│   │       ├── VolatilityEstimator  # Vol estimation interface
│   │       ├── RealizedVolatility   # Historical vol
│   │       ├── EWMAVolatility       # Exponential weighting
│   │       ├── GARCHVolatility      # GARCH(1,1) model
│   │       └── VolatilityRatio      # Cross-sectional vol ratio
│   │
│   ├── Optimizer/                   # Portfolio optimization
│   │   ├── Base/                    # BaseOptimizer interface
│   │   ├── MeanVarianceOptimizer    # Markowitz (1952) optimizer
│   │   ├── CVaRMeanVarianceOptimizer # CVaR-constrained optimizer
│   │   └── ClusterAwareMeanVarianceOptimizer # Cluster-aware optimization
│   │
│   └── AlphaGenerator              # Grinold-Kahn alpha scaling (IC × Vol × Z)
│
├── Data Layer
│   ├── Query/                       # Asset query interfaces
│   │   ├── Base/                    # BaseQuery
│   │   ├── Futures/                 # FuturesQuery
│   │   ├── IRSwaps/                 # IR Swaps query
│   │   │   └── backends/            # QuantLib, rateslib, dp
│   │   ├── FixedRateBonds/          # Bond query
│   │   │   └── backends/            # QuantLib, rateslib
│   │   ├── Equities/                # Equity query
│   │   └── Currencies/              # FX query
│   │
│   ├── MDP/                         # Market data providers
│   │   ├── MarketDataProvider       # Base MDP interface
│   │   ├── YahooFinance/            # Yahoo Finance integration
│   │   ├── IRSwaps/                 # Swap data providers
│   │   │   ├── CME_NY_EOD_LIVE/     # CME end-of-day
│   │   │   ├── SDR_INTRADAY/        # Intraday swap data
│   │   │   └── GSQUANT/             # Goldman Sachs data
│   │   ├── FixedRateBonds/          # Bond data providers
│   │   │   ├── FEDINVEST/           # US Treasury data
│   │   │   ├── WEBULL/              # Webull data
│   │   │   ├── WSJ/                 # Wall Street Journal
│   │   │   └── PUBLICDOTCOM/        # Public.com data
│   │   └── IRSwapSpreads/           # Swap spread data
│   │
│   └── Adapter/                     # Query → DataFrame bridge
│       ├── Base/                    # BaseAdapter
│       ├── FuturesAdapter           # Futures data adapter
│       └── EquityAdapter            # Equity data adapter
│
├── Asset Abstraction
│   ├── Asset/                       # Asset hierarchy
│   │   ├── Base/                    # Base Asset class
│   │   ├── PriceFuture              # Price-based futures
│   │   ├── RollableFuture           # Auto-rolling futures
│   │   ├── Position                 # Single position
│   │   ├── Portfolio                # Standard portfolio (composite Asset)
│   │   └── GrinoldKahnPortfolio     # Grinold-Kahn compliant portfolio
│   │
│   └── BT/                          # Legacy backtesting (deprecated)
│       ├── accounting               # Position accounting
│       └── data_handler             # Data management
│
├── Strategy Framework
│   ├── Backtest/                    # Generic backtest engine
│   │   ├── Base/                    # BaseBacktest
│   │   └── Backtest                 # Unified backtest (query + DataFrame workflows)
│   │
│   └── Strategies/                  # Strategy configuration system
│       ├── Config/                  # YAML configuration parser
│       │   └── StrategyConfig       # Strategy config schema
│       ├── Factory/                 # Component factories
│       │   ├── StrategyFactory      # Main strategy factory
│       │   ├── AlphaFactory         # Alpha generator factory
│       │   ├── SignalFactory        # Signal factory
│       │   └── CovarianceFactory    # Risk model factory
│       └── Registry/                # Pre-built templates
│           └── StrategyRegistry     # Template registry
│
├── Analysis & Utilities
│   ├── Analysis/                    # Performance analysis
│   │   └── TearSheet                # Comprehensive performance metrics
│   │
│   ├── RVUtils/                     # Relative value utilities
│   │   ├── Interpolation/           # Curve interpolation
│   │   │   ├── NelsonSiegel         # Nelson-Siegel model
│   │   │   ├── NelsonSiegelSvensson # Extended NS model
│   │   │   ├── DieboldLi            # Diebold-Li model
│   │   │   ├── BjorkChristensen     # Bjork-Christensen model
│   │   │   ├── MonotoneConvex       # Monotone convex splines
│   │   │   ├── MonoSpline           # Monotone splines
│   │   │   ├── SmithWilson          # Smith-Wilson extrapolation
│   │   │   └── MLESM                # MLE state-space model
│   │   ├── mean_reversion           # Mean reversion utilities
│   │   ├── regression               # Regression tools
│   │   └── seasonality_utils        # Seasonality analysis
│   │
│   └── Caching/                     # Data caching layer
│       ├── ZODBCacheMixin           # ZODB-based caching
│       └── timeseries_cache         # Timeseries cache
│
├── Configuration
│   ├── config/                      # Runtime configuration
│   │   └── strategies/              # Strategy YAML files
│   ├── strategies/                  # Strategy definitions
│   │   └── examples/                # Example strategies
│   └── definitions/                 # System definitions
│
└── Development & Testing
    ├── tests/                       # Test suite (1046 tests)
    │   ├── unit/                    # Unit tests
    │   │   ├── adapter/             # Adapter tests
    │   │   ├── asset/               # Asset tests
    │   │   ├── backtest/            # Backtest tests
    │   │   ├── optimizer/           # Optimizer tests
    │   │   ├── query/               # Query tests
    │   │   ├── risk/                # Risk model tests
    │   │   ├── signals/             # Signal tests
    │   │   └── strategies/          # Strategy tests
    │   ├── integration/             # Integration tests
    │   └── validation/              # Real-data validation
    │
    ├── examples/                    # Usage examples
    ├── notebooks/                   # Jupyter notebooks
    ├── docs/                        # Documentation
    │   ├── books/                   # Book notes (Grinold-Kahn)
    │   ├── design/                  # Design documents
    │   ├── guides/                  # User guides
    │   ├── papers/                  # Research papers
    │   ├── references/              # Reference materials
    │   └── research/                # Research notes
    │
    └── scripts/                     # Utility scripts
```

---

## Architecture Diagrams

### 1. Core Data Flow (Returns-First Design)

```mermaid
graph TD
    %% Data Sources
    MDP[Market Data Provider] --> Query[Query Layer]
    Query --> |MockFuture objects| Adapter[Adapter Layer]

    %% Alternative Entry Point
    ExternalData[External DataFrame] -.-> |Direct entry| Returns

    %% Returns Pipeline
    Adapter --> |Price DataFrame| Returns[ReturnsCalculator]
    Returns --> |Standardized Returns Matrix| Vol[VolatilityEstimator]

    %% Signal Generation
    Vol --> |Volatility Forecasts| Signal[Signal Layer]
    Returns --> |Returns for IC calc| Signal
    Signal --> |Raw Signals Z-scores| Alpha[AlphaGenerator]

    %% Alpha Scaling
    Vol --> |σ forecasts| Alpha
    Signal --> |IC estimates| Alpha
    Alpha --> |Scaled Alphas = IC × σ × Z| Risk

    %% Risk & Optimization
    Returns --> |Covariance input| Risk[Risk Models]
    Risk --> |Covariance Matrix Σ| Opt[Optimizer]
    Alpha --> |Expected Returns μ| Opt
    Opt --> |Portfolio Weights w| Portfolio[Portfolio]

    %% Portfolio Construction
    Returns --> |Asset Returns| Portfolio
    Portfolio --> |Composite Asset| Analysis[TearSheet]

    %% Performance Analysis
    Analysis --> |IC, Sharpe, Returns| Result[BacktestResult]

    style MDP fill:#e1f5ff
    style Query fill:#e1f5ff
    style Adapter fill:#e1f5ff
    style Returns fill:#fff4e1
    style Vol fill:#fff4e1
    style Signal fill:#e8f5e9
    style Alpha fill:#e8f5e9
    style Risk fill:#fce4ec
    style Opt fill:#fce4ec
    style Portfolio fill:#f3e5f5
    style Analysis fill:#f3e5f5
    style Result fill:#f3e5f5
    style ExternalData fill:#e1f5ff,stroke-dasharray: 5 5
```

### 2. Signal Architecture

```mermaid
graph TB
    %% Base Layer
    BaseSignal[BaseSignal<br/>Abstract Interface]

    %% Single Signals
    BaseSignal --> Carry[CarrySignal<br/>Carry-based alpha]
    BaseSignal --> Momentum[MomentumSignal<br/>Trend following]
    BaseSignal --> MeanRev[MeanReversionSignal<br/>Mean reversion]
    BaseSignal --> Fundamental[FundamentalSignal<br/>Sector fundamentals]

    %% Signal Processing
    Carry --> Features[FeatureEngineering<br/>Winsorization, Standardization]
    Momentum --> Features
    MeanRev --> Features
    Fundamental --> Features

    %% Multi-Signal
    Features --> Combiner[SignalCombiner<br/>Equal/IC-weighted]

    %% Alpha Generation
    Combiner --> AlphaGen[AlphaGenerator<br/>IC × Vol × Z scaling]

    %% Outputs
    AlphaGen --> RawSignals[Raw Signals<br/>Z-scores]
    AlphaGen --> ScaledAlphas[Scaled Alphas<br/>Expected Returns]

    style BaseSignal fill:#e3f2fd
    style Carry fill:#bbdefb
    style Momentum fill:#bbdefb
    style MeanRev fill:#bbdefb
    style Fundamental fill:#bbdefb
    style Features fill:#fff9c4
    style Combiner fill:#c8e6c9
    style AlphaGen fill:#c8e6c9
    style RawSignals fill:#f8bbd0
    style ScaledAlphas fill:#f8bbd0
```

### 3. Risk Model Hierarchy

```mermaid
graph TD
    %% Base Layer
    Base[BaseCovarianceEstimator<br/>fit, estimate, validate]

    %% Standard Models
    Base --> Sample[SampleCovariance<br/>Standard sample cov]
    Base --> Ledoit[LedoitWolfShrinkage<br/>Shrinkage to diagonal]
    Base --> OA[OAShrinkage<br/>Oracle approximation]
    Base --> ConstCorr[ConstantCorrelation<br/>Uniform correlation]
    Base --> Diag[DiagonalCovariance<br/>Uncorrelated assets]
    Base --> Identity[IdentityCovariance<br/>Unit variance]

    %% Advanced Models
    Base --> CorCluster[CorrelationClustering<br/>Cluster-based structure]
    Base --> BaseSector[BaseSectorCovariance<br/>Sector-aware base]

    %% Sector Models
    BaseSector --> BlockDiag[BlockDiagonalCovariance<br/>Cluster blocks]
    BaseSector --> Stochastic[StochasticBlockCovariance<br/>Probability-based blocks]
    BaseSector --> TwoStep[TwoStepCovariance<br/>Within + Between sectors]

    %% Factory
    Factory[CovarianceFactory<br/>Registry-based creation] -.-> Base

    %% Output
    Sample --> CovMatrix[Covariance Matrix Σ]
    Ledoit --> CovMatrix
    OA --> CovMatrix
    ConstCorr --> CovMatrix
    Diag --> CovMatrix
    Identity --> CovMatrix
    CorCluster --> CovMatrix
    BlockDiag --> CovMatrix
    Stochastic --> CovMatrix
    TwoStep --> CovMatrix

    style Base fill:#e1f5fe
    style Sample fill:#b3e5fc
    style Ledoit fill:#b3e5fc
    style OA fill:#b3e5fc
    style ConstCorr fill:#b3e5fc
    style Diag fill:#b3e5fc
    style Identity fill:#b3e5fc
    style CorCluster fill:#81d4fa
    style BaseSector fill:#81d4fa
    style BlockDiag fill:#4fc3f7
    style Stochastic fill:#4fc3f7
    style TwoStep fill:#4fc3f7
    style Factory fill:#fff9c4
    style CovMatrix fill:#c8e6c9
```

### 4. Backtest Workflows

```mermaid
graph LR
    %% Entry Points
    QueryBased[Query-Based<br/>Futures, Swaps] --> Backtest[Generic Backtest]
    DataFrameBased[DataFrame-Based<br/>Equities, ETFs] --> Backtest

    %% Component Injection
    Backtest --> Components{Component<br/>Configuration}

    %% Components
    Components --> MDP[MarketDataProvider<br/>optional]
    Components --> Adapter[Adapter<br/>optional]
    Components --> Signals[Signals<br/>single or list]
    Components --> Combiner[SignalCombiner<br/>auto-created if multiple]
    Components --> Risk[Risk Model<br/>default: LedoitWolf]
    Components --> Opt[Optimizer<br/>default: MeanVariance]

    %% Execution
    MDP --> Execute[execute]
    Adapter --> Execute
    Signals --> Execute
    Combiner --> Execute
    Risk --> Execute
    Opt --> Execute

    %% Results
    Execute --> Analysis[TearSheet<br/>Performance Analysis]
    Analysis --> Result[BacktestResult<br/>IC, Sharpe, Returns]

    style QueryBased fill:#e1f5ff
    style DataFrameBased fill:#e1f5ff
    style Backtest fill:#fff4e1
    style Components fill:#fff9c4
    style MDP fill:#e8f5e9
    style Adapter fill:#e8f5e9
    style Signals fill:#e8f5e9
    style Combiner fill:#e8f5e9
    style Risk fill:#fce4ec
    style Opt fill:#fce4ec
    style Execute fill:#f3e5f5
    style Analysis fill:#f3e5f5
    style Result fill:#c8e6c9
```

### 5. Strategy Factory System

```mermaid
graph TD
    %% YAML Config
    YAML[YAML Strategy Config] --> Parser[StrategyConfig Parser]

    %% Validation
    Parser --> Validation{Schema<br/>Validation}
    Validation --> |Valid| Factory[StrategyFactory]
    Validation --> |Invalid| Error[ConfigurationError]

    %% Component Factories
    Factory --> AlphaF[AlphaFactory<br/>Create IC estimator]
    Factory --> SignalF[SignalFactory<br/>Create signals]
    Factory --> CovF[CovarianceFactory<br/>Create risk model]
    Factory --> OptF[OptimizerFactory<br/>Create optimizer]

    %% Template Registry
    Registry[StrategyRegistry<br/>Pre-built templates] -.-> Parser

    %% Component Creation
    AlphaF --> Alpha[AlphaGenerator]
    SignalF --> Sig[Signal instances]
    CovF --> Cov[CovarianceEstimator]
    OptF --> Optimizer[Optimizer]

    %% Strategy Assembly
    Alpha --> Strategy[Complete Strategy]
    Sig --> Strategy
    Cov --> Strategy
    Optimizer --> Strategy

    %% Execution
    Strategy --> Backtest[Backtest.run]

    style YAML fill:#e1f5ff
    style Parser fill:#fff4e1
    style Validation fill:#fff9c4
    style Factory fill:#e8f5e9
    style AlphaF fill:#c8e6c9
    style SignalF fill:#c8e6c9
    style CovF fill:#c8e6c9
    style OptF fill:#c8e6c9
    style Registry fill:#f3e5f5
    style Alpha fill:#fce4ec
    style Sig fill:#fce4ec
    style Cov fill:#fce4ec
    style Optimizer fill:#fce4ec
    style Strategy fill:#c5cae9
    style Backtest fill:#9fa8da
    style Error fill:#ffcdd2
```

### 6. Asset Hierarchy (Composite Pattern)

```mermaid
graph TD
    %% Base
    Asset[Asset<br/>Abstract Base Class<br/>get_return, get_positions]

    %% Concrete Assets
    Asset --> PriceFuture[PriceFuture<br/>Price-based returns<br/>r = Δ P / P]
    Asset --> Rollable[RollableFuture<br/>Auto-rolling futures<br/>Handles contract transitions]
    Asset --> Position[Position<br/>Single asset position<br/>w × r calculation]

    %% Composite Assets
    Asset --> Portfolio[Portfolio<br/>Composite asset<br/>Σ w_i × r_i]
    Asset --> GKPortfolio[GrinoldKahnPortfolio<br/>Returns-first portfolio<br/>Grinold-Kahn compliant]

    %% Nesting
    Portfolio --> |can contain| Asset
    GKPortfolio --> |can contain| Asset

    %% Returns Calculation
    PriceFuture --> Returns[Returns Series]
    Rollable --> Returns
    Position --> Returns
    Portfolio --> Returns
    GKPortfolio --> Returns

    style Asset fill:#e1f5fe
    style PriceFuture fill:#b3e5fc
    style Rollable fill:#b3e5fc
    style Position fill:#b3e5fc
    style Portfolio fill:#81d4fa
    style GKPortfolio fill:#81d4fa
    style Returns fill:#c8e6c9
```

---

## Module Dependencies

### Critical Paths

1. **Data Ingestion**:
   ```
   MDP → Query → Adapter → ReturnsCalculator
   ```

2. **Signal Generation**:
   ```
   ReturnsCalculator → VolatilityEstimator → Signal → AlphaGenerator
   ```

3. **Risk Estimation**:
   ```
   ReturnsCalculator → CovarianceEstimator → Optimizer
   ```

4. **Portfolio Construction**:
   ```
   Optimizer → Portfolio → TearSheet → BacktestResult
   ```

### Key Interfaces

| Interface | Implementers | Purpose |
|-----------|--------------|---------|
| `BaseSignal` | CarrySignal, MomentumSignal, MeanReversionSignal, FundamentalSignal | Signal generation |
| `BaseCovarianceEstimator` | 10+ implementations | Risk modeling |
| `BaseOptimizer` | MeanVarianceOptimizer, CVaROptimizer, ClusterAwareOptimizer | Portfolio optimization |
| `Asset` | PriceFuture, RollableFuture, Position, Portfolio, GrinoldKahnPortfolio | Return calculation |
| `BaseAdapter` | FuturesAdapter, EquityAdapter | Data format translation |

---

## Design Patterns

### 1. **Composite Pattern** (Asset Hierarchy)
   - `Asset` is both leaf and composite
   - `Portfolio` and `GrinoldKahnPortfolio` contain other Assets
   - Enables nested portfolio construction

### 2. **Strategy Pattern** (Signals, Risk Models, Optimizers)
   - Interchangeable algorithms via base interfaces
   - Easy to add new signal types or risk models

### 3. **Factory Pattern** (Strategy Factory System)
   - `StrategyFactory` creates complete strategies from config
   - Component-specific factories for signals, risk models, optimizers

### 4. **Registry Pattern** (StrategyRegistry)
   - Pre-built strategy templates
   - Extensible without code modification

### 5. **Adapter Pattern** (Data Adapters)
   - Translates Query results to standardized DataFrame format
   - Bridges different data sources

### 6. **Dependency Injection** (Generic Backtest)
   - Components injected into backtest
   - Enables testing and flexibility

---

## Naming Issues Identified

### Files requiring cleanup:

1. **Optimizer/MeanVarianceOptimizer.py**: Remove "Minimal/Maximal" temporal references
2. **Optimizer/__init__.py**: Remove "minimal" references
3. **Strategies/Registry/StrategyRegistry.py**: Rename "Simple Carry Strategy" → "Carry Strategy"
4. **Strategies/Registry/StrategyRegistry.py**: Rename "Simple Momentum Strategy" → "Momentum Strategy"
5. **Strategies/Config/StrategyConfig.py**: Update example names
6. **Strategies/Factory/StrategyFactory.py**: Update example names
7. **Asset/PriceFuture.py**: Reduce "simple" usage in documentation
8. **Asset/GrinoldKahnPortfolio.py**: Remove "Minimal" from examples
9. **Asset/Portfolio.py**: Remove "Simple portfolio" from examples

### Violations of CLAUDE.md naming rules:
- ❌ "Simple" in strategy names (relative complexity)
- ❌ "Minimal" in phase descriptions (temporal context)
- ✅ "simple returns" vs "log returns" (standard terminology - keep)

---

## Test Coverage Summary

| Module | Tests | Status |
|--------|-------|--------|
| Query | 44 | ✅ Passing |
| Signals | 187 | ⚠️ 6 failing (sector rotation) |
| Risk | 100 | ⚠️ 2 failing (OAS, VolRatio) |
| Optimizer | 40 | ✅ Passing |
| Adapter | 8 | ✅ Passing |
| Backtest | 30 | ✅ Passing |
| Asset | 100+ | ✅ Passing |
| Strategies | 80 | ✅ Passing |
| Integration | 8 | ✅ Passing |
| **Total** | **1046** | **1038 passing (99.2%)** |

---

## Recommended Improvements

### 1. **Module Organization**
   - ✅ Already well-organized by domain
   - ✅ Clear separation of concerns
   - ✅ Consistent naming conventions (except issues identified)

### 2. **Architecture**
   - ✅ Returns-first design is correct (Grinold-Kahn compliant)
   - ✅ Composite Asset pattern enables powerful composition
   - ✅ Generic Backtest unifies workflows
   - ✅ Factory system enables extension without modification

### 3. **Simplification Opportunities**
   - Consider consolidating BT/ into Backtest/ (BT appears deprecated)
   - Consider merging TB/ utilities into RVUtils/ or Analysis/
   - Could reduce MDP provider implementations (15+ providers)

### 4. **Documentation**
   - Good ABOUTME headers in most files
   - Architecture documentation in CLAUDE.md is comprehensive
   - Could benefit from API reference docs (auto-generated from docstrings)

### 5. **Test Organization**
   - Excellent test coverage (99.2%)
   - Clear separation: unit / integration / validation
   - Remaining failures are edge cases, not architectural issues

---

## Conclusions

**Strengths:**
1. ✅ Clean, modular architecture with clear separation of concerns
2. ✅ Grinold-Kahn compliance (returns-first, IC × Vol × Z scaling)
3. ✅ Excellent test coverage (1038/1046 passing)
4. ✅ Extensible via factory pattern and dependency injection
5. ✅ No pandas dependencies in production code (Polars migration complete)

**Issues:**
1. ⚠️ Naming violations: "Simple" and "Minimal" usage (9 files)
2. ⚠️ 8 test failures remaining (6 sector rotation, 2 risk models)
3. ⚠️ Some legacy code (BT/, TB/) that may be deprecated

**Action Items:**
1. Clean up "Simple" and "Minimal" naming violations
2. Fix remaining 8 test failures
3. Consider deprecating/removing BT/ and TB/ if not in use
4. Document deprecation path for any legacy code

---

*Generated: 2025-11-14*
*Total Modules Analyzed: 150+*
*Total Tests: 1046 (1038 passing, 8 failing)*
