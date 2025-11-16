# ARBS Component Dependency Map

**Date**: 2025-11-15
**Purpose**: Complete mapping of how all ARBS components connect and depend on each other

---

## High-Level Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│                    STRATEGY LAYER                            │
│  StrategyFactory → StrategyConfig → Template Registry        │
└─────────────────┬───────────────────────────────────────────┘
                  │ orchestrates
┌─────────────────▼───────────────────────────────────────────┐
│                  PORTFOLIO LAYER                             │
│  GrinoldKahnPortfolio → Backtest                            │
└─────────┬────────────────────────┬──────────────────────────┘
          │                        │
┌─────────▼────────┐    ┌──────────▼──────────┐
│  SIGNAL LAYER    │    │   RISK LAYER        │
│  BaseSignal      │    │  CovarianceEstimator│
│  AlphaGenerator  │    │  VolatilityEstimator│
└─────────┬────────┘    └──────────┬──────────┘
          │                        │
          └────────┬───────────────┘
                   │
        ┌──────────▼──────────────┐
        │   OPTIMIZER LAYER       │
        │  MeanVarianceOptimizer  │
        └──────────┬──────────────┘
                   │
        ┌──────────▼──────────────┐
        │   ADAPTER LAYER         │
        │  BaseAdapter            │
        └──────────┬──────────────┘
                   │
        ┌──────────▼──────────────┐
        │   QUERY LAYER           │
        │  BaseQuery              │
        └──────────┬──────────────┘
                   │
        ┌──────────▼──────────────┐
        │   MDP LAYER             │
        │  MarketDataProvider     │
        └─────────────────────────┘
```

---

## Component-by-Component Dependencies

### STRATEGY LAYER

**StrategyConfig** (`Strategies/Config/StrategyConfig.py`)
- **Imports FROM**:
  - `SignalFactory` (validates signal types exist)
  - `AlphaFactory` (validates IC methods exist)
  - `CovarianceFactory` (validates covariance methods exist)
- **Used BY**:
  - `StrategyFactory` (creates portfolios from config)
  - `StrategyRegistry` (template instantiation)

**SignalFactory** (`Strategies/Factory/SignalFactory.py`)
- **Imports FROM**:
  - `BaseSignal` (type constraint)
  - `CarrySignal`, `MomentumSignal`, `MeanReversionSignal` (default registry)
  - `StrategyConfig.SignalConfig` (configuration input)
- **Used BY**:
  - `StrategyFactory` (signal instantiation)
  - `StrategyConfig` (validation)

**AlphaFactory** (`Strategies/Factory/AlphaFactory.py`)
- **Imports FROM**:
  - `AlphaGenerator` (creates instances)
- **Used BY**:
  - `StrategyFactory` (alpha generator creation)
  - `StrategyConfig` (validation)

**CovarianceFactory** (`Strategies/Factory/CovarianceFactory.py`)
- **Imports FROM**:
  - `LedoitWolfShrinkage`, `SampleCovariance` (default registry)
  - `BlockDiagonalCovariance`, `TwoStepCovariance`, `StochasticBlockCovariance` (sector models)
- **Used BY**:
  - `StrategyFactory` (risk model creation)
  - `StrategyConfig` (validation)

**StrategyFactory** (`Strategies/Factory/StrategyFactory.py`)
- **Imports FROM**:
  - `StrategyConfig` (configuration parsing)
  - `SignalFactory`, `AlphaFactory`, `CovarianceFactory` (component creation)
  - `MeanVarianceOptimizer` (optimizer instantiation)
  - `GrinoldKahnPortfolio` (final portfolio creation)
- **Used BY**:
  - User code (creates complete strategies from YAML)
  - `StrategyRegistry` (template instantiation)

**StrategyRegistry** (`Strategies/Registry/StrategyRegistry.py`)
- **Imports FROM**:
  - `StrategyConfig` (template format)
  - `StrategyFactory` (strategy instantiation)
  - `GrinoldKahnPortfolio` (return type)
- **Used BY**:
  - User code (quick strategy creation)

---

### PORTFOLIO LAYER

**GrinoldKahnPortfolio** (`Asset/GrinoldKahnPortfolio.py`)
- **Imports FROM**:
  - `Asset` (base class - implements Asset interface)
  - `BaseSignal` (signal generation)
  - `AlphaGenerator` (signal → alpha conversion)
  - `LedoitWolfShrinkage` (default risk model)
  - `RealizedVolatility` (default volatility estimator)
  - `MeanVarianceOptimizer` (portfolio optimization)
  - `BT.query_portfolio.ResolvedQueryPosition` (query tracking)
- **Used BY**:
  - `StrategyFactory` (creates from config)
  - User backtest code

**Backtest** (`Backtest/Backtest.py`)
- **Imports FROM**:
  - `BaseBacktest` (base class)
  - `BaseSignal` (signal execution)
  - `AlphaGenerator` (alpha generation)
  - `LedoitWolfShrinkage` (default risk model)
  - `ReturnsCalculator` (price → returns)
  - `MeanVarianceOptimizer` (portfolio optimization)
  - `BaseQuery` (query-based workflow)
- **Used BY**:
  - User backtest code
  - Examples (`examples/run_backtest.py`)

**Portfolio** (`Asset/Portfolio.py`)
- **Imports FROM**:
  - `Asset` (base class - Composite Pattern)
  - `Position` (constituents)
  - `AssetTransition` (transition detection)
- **Used BY**:
  - Backtest engine (nested portfolios)

---

### SIGNAL LAYER

**BaseSignal** (`Signals/Base/BaseSignal.py`)
- **Imports FROM**:
  - `ABC` (abstract base class)
  - `Signals.Utils.IC.calculate_ic` (IC calculation)
- **Extended BY**:
  - `CarrySignal`, `MomentumSignal`, `MeanReversionSignal` (Futures/)
  - `MLPredictedReturnsSignal` (top-level)
  - `CurrencyCarrySignal` (top-level)
  - `CorrelationVolatilitySignal` (top-level)
  - `SectorMomentumSignal`, `SectorReversionSignal`, `FundamentalSignal` (SectorRotation/)
  - `QuerySignal` (Bridges/)

**AlphaGenerator** (`Signals/AlphaGenerator.py`)
- **Imports FROM**:
  - `VolatilityEstimator` (volatility forecasting)
  - `RealizedVolatility` (default volatility)
- **Used BY**:
  - `GrinoldKahnPortfolio` (alpha generation)
  - `Backtest` (alpha generation)
  - `AlphaFactory` (instantiation)

**SignalCombiner** (`Signals/SignalCombiner.py`)
- **Imports FROM**: None (standalone utility)
- **Used BY**:
  - `Backtest` (multi-signal strategies)
  - `GrinoldKahnPortfolio` (signal aggregation)

**Concrete Signals** (CarrySignal, MomentumSignal, etc.)
- **Imports FROM**:
  - `BaseSignal` (base class)
- **Used BY**:
  - `SignalFactory` (instantiation)
  - User code (direct instantiation)

**Sector Rotation Signals**
- **SectorMomentumSignal** imports `MomentumFactor`
- **SectorReversionSignal** imports `ReversionFactor`
- **FundamentalSignal** imports sklearn MLPClassifier
- **SectorLongShortPortfolio** constructs dollar-neutral weights

**QuerySignal** (`Signals/Bridges/QuerySignal.py`)
- **Imports FROM**:
  - `BaseSignal` (base class - Adapter Pattern)
  - `BaseQuery` (query execution)
  - `MarketDataProvider` (data fetching)
- **Used BY**:
  - Users bridging Query system to Signal system

---

### RISK LAYER

**BaseCovarianceEstimator** (`Risk/Base/BaseCovarianceEstimator.py`)
- **Imports FROM**: None (base class)
- **Extended BY**:
  - `SampleCovariance`, `LedoitWolfShrinkage`, `OAShrinkage` (top-level)
  - `ConstantCorrelationCovariance`, `DiagonalCovariance`, `IdentityCovariance` (top-level)
  - `SectorBasedCovarianceEstimator` (intermediate base)
    - `BlockDiagonalCovariance`, `StochasticBlockCovariance`, `TwoStepCovariance` (sector models)

**Covariance Estimators** (all extend BaseCovarianceEstimator)
- **LedoitWolfShrinkage**:
  - Used BY: GrinoldKahnPortfolio (default), Backtest (default), CovarianceFactory
- **SampleCovariance**:
  - Used BY: CovarianceFactory, comparison utilities
- **OAShrinkage**:
  - Imports FROM: sklearn.covariance.OAS
  - Used BY: CovarianceFactory
- **Sector Models**:
  - Import FROM: `sector_utils`, `FactorExtractor`, clustering utilities
  - Used BY: CovarianceFactory, sector-based strategies

**VolatilityEstimator** (`Risk/Volatility/VolatilityEstimator.py`)
- **Imports FROM**: None (base class)
- **Extended BY**:
  - `RealizedVolatility` (historical standard deviation)
  - `EWMAVolatility` (exponentially weighted)

**RealizedVolatility**
- **Used BY**:
  - `AlphaGenerator` (default volatility)
  - `GrinoldKahnPortfolio` (default volatility)

**ReturnsCalculator** (`Risk/Returns/ReturnsCalculator.py`)
- **Imports FROM**: None (standalone utility)
- **Used BY**:
  - `Backtest` (price → returns conversion)

---

### OPTIMIZER LAYER

**BaseOptimizer** (`Optimizer/Base/BaseOptimizer.py`)
- **Imports FROM**: None (base class)
- **Extended BY**:
  - `MeanVarianceOptimizer`
  - `CVaRMeanVarianceOptimizer` (extends MeanVarianceOptimizer)
  - `ClusterAwareMeanVarianceOptimizer` (extends MeanVarianceOptimizer)

**MeanVarianceOptimizer** (`Optimizer/MeanVarianceOptimizer.py`)
- **Imports FROM**:
  - `BaseOptimizer` (base class)
  - scipy.optimize (quadratic programming)
- **Used BY**:
  - `GrinoldKahnPortfolio` (default optimizer)
  - `Backtest` (default optimizer)
  - `StrategyFactory` (optimizer instantiation)

**CVaRMeanVarianceOptimizer**
- **Imports FROM**:
  - `MeanVarianceOptimizer` (base class)
  - cvxpy (CVaR constraint optimization)

**ClusterAwareMeanVarianceOptimizer**
- **Imports FROM**:
  - `MeanVarianceOptimizer` (base class)
  - cvxpy (cluster constraint optimization)

---

### ADAPTER LAYER

**BaseAdapter** (`Adapter/Base/BaseAdapter.py`)
- **Imports FROM**: None (base class)
- **Extended BY**:
  - `FuturesAdapter`
  - `EquityAdapter`

**FuturesAdapter** (`Adapter/FuturesAdapter.py`)
- **Imports FROM**:
  - `BaseAdapter` (base class)
  - `FuturesQuery`, `FuturesStructure`, `FuturesValue` (futures structures)
  - `get_next_imm_contract`, `get_contract_expiry` (contract utilities)
- **Used BY**:
  - `Backtest` (futures workflow)
  - `StrategyFactory` (futures strategies)

**EquityAdapter** (`Adapter/EquityAdapter.py`)
- **Imports FROM**:
  - `BaseAdapter` (base class)
  - `EquityQuery`, `ETFQuery`, `EquityValue` (equity structures)
- **Used BY**:
  - `Backtest` (equity workflow)

---

### QUERY LAYER

**BaseQuery** (`Query/Base/BaseQuery.py`)
- **Imports FROM**:
  - `_GenericPricable` (marker interface)
  - `product_adapter.get_adapter` (adapter resolution)
- **Extended BY**:
  - `FuturesQuery` (Query/Futures/)
  - `IRSwapQuery` (Query/IRSwaps/)
  - `FixedRateBondQuery` (Query/FixedRateBonds/)
  - `EquityQuery`, `ETFQuery` (Query/Equities/)
  - `CurrencyQuery` (Query/Currencies/)

**Product-Specific Queries**

**FuturesQuery** (`Query/Futures/FuturesQuery.py`)
- **Imports FROM**:
  - `BaseQuery` (base class)
  - `FuturesStructure`, `FuturesValue` (enums)
- **Used BY**:
  - `FuturesAdapter` (query → DataFrame transformation)
  - User backtest code

**IRSwapQuery** (`Query/IRSwaps/IRSwapQuery.py`)
- **Imports FROM**:
  - `BaseQuery` (base class)
  - `IRSwapStructure`, `IRSwapValue` (enums)
- **Used BY**:
  - User backtest code (swaps strategies)

**EquityQuery** (`Query/Equities/EquityQuery.py`)
- **Imports FROM**:
  - `BaseQuery` (base class)
  - `EquityStructure`, `EquityValue` (enums)
- **Used BY**:
  - `EquityAdapter` (query → DataFrame transformation)

**Product Adapters** (`Query/Base/product_adapter.py`)
- **Registers**:
  - `"futures"` → `FuturesProductAdapter`
  - `"irswaps"` → `IRSProductAdapter`
  - `"bonds"` → `FixedRateBondProductAdapter`
  - `"equities"` → `EquityProductAdapter`
- **Used BY**:
  - `BaseQuery` (adapter resolution)

**Structure/Value Function Maps**
- **FuturesStructureFunctionMap**: Maps FuturesStructure → builders
- **FuturesValueFunctionMap**: Maps FuturesValue → calculators
- **IRSwapStructureFunctionMap**: Maps IRSwapStructure → builders
- **IRSwapValueFunctionMap**: Maps IRSwapValue → calculators
- (Similar for Bonds, Equities, Currencies)

---

### MDP LAYER

**MarketDataProvider** (`MDP/MarketDataProvider.py`)
- **Imports FROM**:
  - `_GenericPricer`, `_GenericPricable` (generic interfaces)
- **Extended BY**:
  - `IRSwapsMDP`
  - `FixedRateBondsMDP`
  - `YahooFinanceMDP`

**IRSwapsMDP** (`MDP/IRSwaps/IRSwapsMDP.py`)
- **Imports FROM**:
  - `MarketDataProvider` (base class)
  - `_IRSwapGenericCurve` (curve interface)
  - Backend-specific: `QLIRSwapCurve` (QuantLib) or `RLIRSwapCurve` (rateslib)
- **Used BY**:
  - User code (swap curve fetching)
  - `QuerySignal` (MDP integration)

**FixedRateBondsMDP** (`MDP/FixedRateBonds/FixedRateBondsMDP.py`)
- **Imports FROM**:
  - `MarketDataProvider` (base class)
  - `_FixedRateBondGenericPricer` (bond pricer interface)
- **Used BY**:
  - User code (bond pricing)

**YahooFinanceMDP** (`MDP/YahooFinance/YahooFinanceMDP.py`)
- **Imports FROM**:
  - `MarketDataProvider` (base class)
  - yfinance (external data source)
- **Used BY**:
  - User code (equity data fetching)
  - `EquityAdapter` (data provision)

---

### ANALYSIS LAYER

**TearSheet** (`Analysis/TearSheet.py`)
- **Imports FROM**: None (standalone utility)
- **Used BY**:
  - User code (performance analysis)
  - Notebook examples

**RiskMetrics** (`Analysis/RiskMetrics.py`)
- **Imports FROM**: None (standalone utility)
- **Used BY**:
  - User code (HHI, leverage, RDI calculations)

---

## Dependency Graph Summary

### Import Dependencies (who imports whom)

**Most Imported (Core Abstractions)**:
1. `BaseSignal` ← 11 signal implementations
2. `BaseCovarianceEstimator` ← 9 covariance estimators
3. `BaseQuery` ← 5 query types
4. `MarketDataProvider` ← 3 MDP implementations
5. `BaseAdapter` ← 2 adapter implementations
6. `BaseOptimizer` ← 3 optimizer implementations

**Heavy Importers (Orchestrators)**:
1. `StrategyFactory` → 6 different components
2. `GrinoldKahnPortfolio` → 6 different components
3. `Backtest` → 6 different components
4. `StrategyConfig` → 3 factory classes

**Cross-Layer Dependencies**:
- Strategy → Signal, Risk, Optimizer, Portfolio
- Portfolio → Signal, Risk, Optimizer
- Backtest → Adapter, Signal, Risk, Optimizer, Query
- Adapter → Query
- Signal (QuerySignal) → Query, MDP
- Query → MDP (via ProductAdapter)

---

## Circular Dependency Risks

**Mitigated by Lazy Imports**:
1. CovarianceFactory uses lazy imports for sector models
2. Strategy layer uses config validation at runtime (not import time)
3. Query/MDP separation via ProductAdapter registry

**No Circular Dependencies Found** - Architecture properly layered

---

## Data Flow

### Query-Based Workflow (Futures/Swaps):
```
User Code
  → FuturesQuery/IRSwapQuery (request specification)
  → BaseQuery.build_mdp_request() (MDP request dict)
  → IRSwapsMDP.get_pricer() (curve fetching)
  → _IRSwapGenericCurve (curve object)
  → FuturesAdapter.convert() (DataFrame transformation)
  → BaseSignal.generate_batch() (signal generation)
  → AlphaGenerator.signals_to_alphas() (alpha scaling)
  → BaseCovarianceEstimator.fit() (risk estimation)
  → MeanVarianceOptimizer.optimize() (portfolio weights)
  → Backtest (performance measurement)
```

### DataFrame-Based Workflow (Equities):
```
User Code
  → YahooFinanceMDP.get_prices() (price fetching)
  → ReturnsCalculator.calculate_returns() (price → returns)
  → BaseSignal.generate_batch() (signal generation)
  → AlphaGenerator.signals_to_alphas() (alpha scaling)
  → BaseCovarianceEstimator.fit() (risk estimation)
  → MeanVarianceOptimizer.optimize() (portfolio weights)
  → Backtest.run_from_dataframe() (performance measurement)
```

### Strategy Factory Workflow:
```
User Code
  → StrategyRegistry.create_strategy() (template selection)
  → StrategyConfig.from_yaml() (YAML parsing + validation)
  → StrategyFactory.create_from_config() (orchestration)
    → SignalFactory.create_signals() (signal instantiation)
    → AlphaFactory.create_alpha_generator() (alpha instantiation)
    → CovarianceFactory.create_covariance_estimator() (risk instantiation)
    → MeanVarianceOptimizer.__init__() (optimizer instantiation)
  → GrinoldKahnPortfolio.__init__() (complete portfolio object)
```

---

## Extension Points

### Adding New Signals:
1. Extend `BaseSignal`
2. Implement `_calculate_raw_signal()`
3. Register via `SignalFactory.register_signal()`

### Adding New Risk Models:
1. Extend `BaseCovarianceEstimator`
2. Implement `fit()`
3. Register via `CovarianceFactory.register_covariance()`

### Adding New Optimizers:
1. Extend `BaseOptimizer`
2. Implement `optimize()`
3. (No factory registration yet - future enhancement)

### Adding New Products:
1. Create Query class extending `BaseQuery`
2. Create ProductAdapter extending `ProductAdapter`
3. Create MDP extending `MarketDataProvider`
4. Register via `register_product()`

---

## Component Coupling Analysis

### Tightly Coupled (Intentional):
- Signal ↔ AlphaGenerator (Grinold-Kahn framework)
- Portfolio ↔ Optimizer (mean-variance optimization)
- Query ↔ MDP (data fetching)

### Loosely Coupled (Good Design):
- Backtest ↔ Signals (dependency injection)
- Backtest ↔ Risk Models (dependency injection)
- Strategy Factory ↔ All Components (registry pattern)

### Independent (Utilities):
- TearSheet (standalone performance analysis)
- ReturnsCalculator (price → returns conversion)
- SignalCombiner (signal aggregation)
- RiskMetrics (portfolio metrics)

---

This dependency map provides a complete picture of how all 100+ ARBS files connect and interact, enabling informed architectural refactoring decisions.
