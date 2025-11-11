# Strategy Modularization Design

**Design Document for YAML-Based Strategy Creation System**

Version: 1.0
Date: 2025-11-11
Author: Claude (Design Phase)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Notebook Analysis](#notebook-analysis)
3. [Strategy Taxonomy](#strategy-taxonomy)
4. [YAML Schema Design](#yaml-schema-design)
5. [Architecture Design](#architecture-design)
6. [Implementation Roadmap](#implementation-roadmap)
7. [Appendices](#appendices)

---

## Executive Summary

### Problem Statement

Currently, creating new trading strategies in ARBS requires writing custom Python code for each strategy. Users must:
- Manually configure queries, triggers, and actions
- Write boilerplate code for common patterns
- Understand low-level APIs (QueryDrivenBacktest, GrinoldKahnPortfolio)
- Duplicate logic across similar strategies

### Solution

Design a **modular strategy creation system** that:
1. **YAML Configuration**: Strategies defined in declarative YAML files
2. **Strategy Factory**: Automatic instantiation from config
3. **Strategy Registry**: Catalog of pre-built templates
4. **Dual-Mode Support**: Both query-based (event-driven) and signal-based (systematic) strategies
5. **Extensibility**: Custom signals/queries via Python plugins

### Key Benefits

- **Productivity**: Create new strategies in minutes, not hours
- **Consistency**: Standardized format across all strategies
- **Maintainability**: Easy to modify and version control
- **Learning Curve**: Beginners can start with templates
- **Flexibility**: Power users retain full programmatic control

### Design Philosophy

**User-Centric**: Optimize for ease of use while preserving power
**Backward Compatible**: Existing code continues to work
**Modular**: Compose strategies from reusable components
**Validated**: Catch errors early with schema validation

---

## Notebook Analysis

### Overview

Analyzed 5 production notebooks representing different strategy types:

1. **fomc_fly_backtest.ipynb** - Event-driven butterfly trades
2. **simple_irswaps_backtest.ipynb** - Basic IR swap strategies
3. **month_end_irswaps_backtest.ipynb** - Calendar-based seasonality
4. **sfr_cvx.ipynb** - Convexity analysis
5. **usts_rv.ipynb** - Relative value curve fitting

### Key Patterns Identified

#### 1. FOMC Butterfly Strategy (Event-Driven)

**Instruments**: IRSwap flies referenced to FOMC meeting dates
**Signal**: 2s5s10s carry > 0 (pay belly when carry positive)
**Entry**: When carry signal triggers
**Exit**: Either carry flips OR 1 business day before first leg expiry
**Rebalancing**: Event-driven (FOMC meetings)
**Risk**: -100,000 BPV per trade

**Pattern**:
```python
# Calculate carry signal
carry = compute_pay_belly_2s5s10s_carry(bt, now)

# Entry: carry > 0
if carry > 0:
    # Resolve FOMC-referenced fly
    fly = resolve_fomc_fly(now, [1, 2, 3])  # FOMC-i / FOMC-i+1 / FOMC-i+2

    # Exit: carry flips or leg expires
    exit_date = min(carry_flip_date, leg_expiry_date)

    # Create triggers
    entry_trigger = DateTrigger(entry_date, AddQueryAction(fomc_fly_query))
    exit_trigger = DateTrigger(exit_date, UnwindPositionsAction(tag))
```

**Key Abstractions Needed**:
- Event-driven date resolution (FOMC meetings)
- Dynamic exit conditions (signal flip OR structural expiry)
- Signal-based entry logic
- Tag-based position unwinding

---

#### 2. Month-End Seasonality (Calendar-Based)

**Instruments**: 1Yx2Y/1Yx5Y/1Yx10Y forward-starting fly
**Signal**: Calendar seasonality (month-end flows)
**Entry**: 3 business days before month-end
**Exit**: 3 business days after month-end
**Rebalancing**: Monthly cycle
**Risk**: -100,000 BPV

**Pattern**:
```python
# Generate monthly cycles
for year, month in month_iter(start, end):
    eom = last_business_day_of_month(year, month)
    entry = n_business_days_before(eom, 3)
    exit = nth_business_day_of_month(next_month, 3)

    # Create entry/exit triggers
    triggers.append(DateTrigger(entry, AddQueryAction(fly_query, tag)))
    triggers.append(DateTrigger(exit, UnwindPositionsAction(tag)))
```

**Key Abstractions Needed**:
- Business day calendar calculations
- Month-end date utilities
- Recurring cycle generation
- Paired entry/exit logic

---

#### 3. UST Relative Value (Curve Fitting)

**Instruments**: US Treasury bonds
**Signal**: MMSS (Minus-Minus Swap Spread) rich/cheap vs fitted curve
**Entry/Exit**: Continuous rebalancing when bonds deviate from fair value
**Analysis**: LOESS/BSpline curve fitting
**Rebalancing**: Daily or threshold-based

**Pattern**:
```python
# Fit curve to MMSS spreads
fitted_curve = fit_mmss_curve(clean_bonds, method='loess')

# Calculate rich/cheap
for bond in bonds:
    fair_mmss = fitted_curve(bond.ttm)
    actual_mmss = bond.mmss
    z_score = (actual_mmss - fair_mmss) / std

    # Signal: long cheap, short rich
    if z_score < -2.0:  # Cheap
        signal[bond] = +1.0
    elif z_score > +2.0:  # Rich
        signal[bond] = -1.0
```

**Key Abstractions Needed**:
- Curve fitting (LOESS, BSpline)
- Z-score calculations
- Rich/cheap thresholds
- Continuous rebalancing

---

#### 4. SFR Convexity (Analytical)

**Instruments**: SOFR futures (SFR)
**Value**: CVX_ADJ (convexity adjustment)
**Use Case**: Analysis more than backtesting

**Pattern**:
```python
# Calculate convexity adjustment
sfr_cvx = tb.sfr_cvx_adj(items=['sfr8', 'sfr12'], start, end)

# Plot time series
plot(sfr_cvx['USD-SOFR-1D SFR8 OUTRIGHT CVX_ADJ'])
```

**Key Abstractions Needed**:
- Time series builders
- Value calculations (beyond NPV)
- Analysis utilities

---

### Common Infrastructure Patterns

All notebooks share these common patterns:

```python
# 1. Market Data Provider
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

# 2. Time Grid
tg = TimeGrid(ql_cal_date_range(calendar, start, end))

# 3. Query Construction
query = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    curve="USD-SOFR-1D",
    structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y", "back_tenor": "10Y", "bpv": -100_000}
)

# 4. Trigger/Action Pattern
entry = DateTrigger(DateTriggerRequirements(dates=[date]), actions=[AddQueryAction(query)])
exit = DateTrigger(DateTriggerRequirements(dates=[date]), actions=[UnwindPositionsAction(tag)])

# 5. Strategy Assembly
strategy = QueryStrategy(name="...", triggers=[entry, exit, ...])

# 6. Backtest Execution
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)
bt.run()

# 7. Results Analysis
mtm = pd.Series(bt.mtm_history).sort_index()
```

---

## Strategy Taxonomy

### Overview

Strategies in ARBS fall into **two paradigms**:

1. **Query-Based Strategies** (Event-Driven)
   - Use QueryDrivenBacktest engine
   - Trigger-action pattern
   - Explicit entry/exit dates
   - Best for: Event-driven, calendar-based, structural trades

2. **Signal-Based Strategies** (Systematic)
   - Use GrinoldKahnPortfolio framework
   - Alpha generation via signals
   - Continuous optimization
   - Best for: Systematic alpha, multi-signal, portfolio construction

### Taxonomy Tree

```
Strategies
├── Query-Based (Event-Driven)
│   ├── Directional
│   │   ├── Carry Trades
│   │   ├── Curve Trades (steepeners, flatteners, flies)
│   │   └── Outright Positions
│   ├── Event-Driven
│   │   ├── FOMC Trades
│   │   ├── Auction Cycles
│   │   ├── Month-End Flows
│   │   └── Roll Trades
│   ├── Calendar-Based
│   │   ├── Seasonality
│   │   ├── Turn-of-Month
│   │   └── Quarter-End
│   └── Relative Value
│       ├── Curve Fitting
│       ├── Rich/Cheap
│       └── Cross-Asset Spreads
│
└── Signal-Based (Systematic)
    ├── Single-Signal
    │   ├── Carry
    │   ├── Momentum
    │   └── Mean Reversion
    ├── Multi-Signal
    │   ├── Combined (carry + momentum + mean reversion)
    │   ├── IC-Weighted
    │   └── Orthogonalized
    ├── Regime-Switching
    │   ├── Trending Regime
    │   ├── Ranging Regime
    │   └── Carry Regime
    └── Portfolio Construction
        ├── Risk Parity
        ├── Min Variance
        └── Max Sharpe
```

---

## YAML Schema Design

### Design Principles

1. **Declarative**: Specify WHAT, not HOW
2. **Hierarchical**: Nested structure mirrors code architecture
3. **Extensible**: Support custom components via plugins
4. **Validated**: JSON Schema for compile-time validation
5. **Readable**: Human-friendly syntax

### Core Schema

```yaml
# Top-level structure
strategy:
  name: string                    # Strategy identifier
  type: string                    # Strategy type (see taxonomy)
  description: string             # Human-readable description
  mode: "query" | "signal"        # Query-based or signal-based

# Universe definition
universe:
  asset_class: string             # "futures" | "swaps" | "bonds"
  instruments: [string]           # List of tickers or patterns
  source: string                  # Market data source (optional)

# For query-based strategies
queries:
  - name: string
    type: string                  # "outright" | "fly" | "curve" | "custom"
    config: object                # Query-specific configuration

# For signal-based strategies
signals:
  - name: string
    type: string                  # "carry" | "momentum" | "mean_reversion" | "custom"
    config: object                # Signal-specific configuration
    weight: float                 # Signal weight (optional)

# Alpha generation (signal-based only)
alpha:
  IC: float                       # Information Coefficient
  method: "static" | "dynamic"    # IC estimation method

# Risk model
risk:
  covariance: string              # "ledoit_wolf" | "sample" | "constant_correlation"
  volatility_target: float        # (optional) annualized vol target
  lookback: int                   # Historical window for estimation

# Optimizer (signal-based only)
optimizer:
  type: string                    # "mean_variance" | "risk_parity" | "min_variance"
  risk_aversion: float            # Lambda parameter
  constraints:
    long_only: bool
    max_position: float           # Max weight per instrument
    leverage: float               # Max gross leverage
    sector_limits: object         # (optional) sector exposure limits

# Execution
execution:
  rebalance_frequency: string     # "daily" | "weekly" | "monthly" | "event_driven"
  transaction_costs: float        # (optional) proportional cost
  calendar: string                # Business day calendar

# Entry/Exit rules (query-based)
entry:
  type: string                    # "date" | "signal" | "event" | "threshold"
  config: object                  # Rule-specific configuration

exit:
  type: string                    # "date" | "signal" | "stop_loss" | "take_profit"
  config: object

# Backtest configuration
backtest:
  start_date: string              # YYYY-MM-DD
  end_date: string                # YYYY-MM-DD
  initial_capital: float          # Starting capital
  currency: string                # Base currency (default: USD)
```

### Query Configuration Schema

```yaml
# Outright query
queries:
  - name: "10y_swap"
    type: "outright"
    config:
      curve: "USD-SOFR-1D"
      tenor: "10Y"
      bpv: 100000
      side: "receive"             # "receive" | "pay"

# Fly query
queries:
  - name: "2s5s10s_fly"
    type: "fly"
    config:
      curve: "USD-SOFR-1D"
      front_tenor: "2Y"
      belly_tenor: "5Y"
      back_tenor: "10Y"
      bpv: -100000
      side: "pay_belly"           # "pay_belly" | "receive_belly"

# Curve query
queries:
  - name: "2s10s_steepener"
    type: "curve"
    config:
      curve: "USD-SOFR-1D"
      front_tenor: "2Y"
      back_tenor: "10Y"
      bpv: 100000
      side: "steepener"           # "steepener" | "flattener"

# Forward-starting fly
queries:
  - name: "1yx_2y5y10y_fly"
    type: "fly"
    config:
      curve: "USD-SOFR-1D"
      front_tenor: "1Yx2Y"        # 1-year forward starting 2-year
      belly_tenor: "1Yx5Y"
      back_tenor: "1Yx10Y"
      bpv: -100000
```

### Signal Configuration Schema

```yaml
# Carry signal
signals:
  - name: "futures_carry"
    type: "carry"
    config:
      method: "calendar_spread"   # "calendar_spread" | "roll_yield"
      annualize: true
      standardize: true           # Z-score normalization
    weight: 1.0

# Momentum signal
signals:
  - name: "price_momentum"
    type: "momentum"
    config:
      lookback_days: 30
      method: "returns"           # "returns" | "regression"
      standardize: true
    weight: 1.0

# Mean reversion signal
signals:
  - name: "mean_reversion"
    type: "mean_reversion"
    config:
      lookback_days: 20
      method: "z_score"           # "z_score" | "bollinger"
      threshold: 2.0
      standardize: true
    weight: 1.0

# Custom signal (Python plugin)
signals:
  - name: "custom_macro"
    type: "custom"
    config:
      module: "strategies.custom.MacroSignal"
      class: "MacroSignal"
      params:
        indicators: ["GDP", "CPI", "UNEMPLOYMENT"]
    weight: 0.5
```

### Entry/Exit Rules Schema

```yaml
# Date-based entry/exit
entry:
  type: "date"
  config:
    dates: ["2025-01-15", "2025-02-15", "2025-03-15"]

exit:
  type: "date"
  config:
    dates: ["2025-02-01", "2025-03-01", "2025-04-01"]

# Signal-based entry
entry:
  type: "signal"
  config:
    signal: "carry"
    operator: ">"                 # ">", "<", ">=", "<=", "=="
    threshold: 0.0

# Event-based entry (FOMC)
entry:
  type: "event"
  config:
    event_calendar: "USD-FEDFUNDS"
    event_type: "meeting"
    offset_days: -1               # 1 day before meeting

# Calendar-based (month-end)
entry:
  type: "calendar"
  config:
    pattern: "month_end"
    offset_days: -3               # 3 days before month-end

exit:
  type: "calendar"
  config:
    pattern: "month_end"
    offset_days: 3                # 3 days after month-end

# Multi-condition exit (OR logic)
exit:
  type: "multi"
  operator: "any"                 # "any" (OR) | "all" (AND)
  conditions:
    - type: "signal"
      config:
        signal: "carry"
        operator: "<="
        threshold: 0.0
    - type: "date"
      config:
        dates: ["2025-12-15"]     # Leg expiry
    - type: "stop_loss"
      config:
        threshold: -0.02          # -2% loss
```

---

## Architecture Design

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Interface                            │
│  YAML Files  │  CLI  │  Python API  │  Jupyter Notebooks        │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Strategy Factory Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ ConfigParser │→ │StrategyFactory│→│StrategyBuilder│          │
│  │  (YAML)      │  │  (Registry)   │  │  (Fluent)    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Strategy Instantiation                         │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │  Query-Based         │  │  Signal-Based        │            │
│  │  ┌──────────────┐    │  │  ┌──────────────┐   │            │
│  │  │ QueryStrategy│    │  │  │GrinoldKahn   │   │            │
│  │  │ + Triggers   │    │  │  │Portfolio     │   │            │
│  │  │ + Actions    │    │  │  │              │   │            │
│  │  └──────────────┘    │  │  └──────────────┘   │            │
│  └──────────────────────┘  └──────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backtest Execution                          │
│  ┌──────────────────────┐  ┌──────────────────────┐            │
│  │QueryDrivenBacktest   │  │GK Backtest Framework │            │
│  └──────────────────────┘  └──────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

### Core Classes

#### 1. StrategyConfig

**Purpose**: Parse and validate YAML configuration
**Location**: `Strategies/Config/StrategyConfig.py`

```python
class StrategyConfig:
    """
    Parse and validate strategy YAML configuration.

    Validates against JSON Schema and provides typed access
    to configuration parameters.
    """

    def __init__(self, yaml_path: str):
        """Load YAML file and validate schema."""
        pass

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'StrategyConfig':
        """Create from dictionary (for programmatic use)."""
        pass

    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'StrategyConfig':
        """Create from YAML string."""
        pass

    def validate(self) -> List[str]:
        """Validate configuration, return list of errors."""
        pass

    # Typed accessors
    @property
    def strategy_name(self) -> str: pass

    @property
    def strategy_type(self) -> str: pass

    @property
    def mode(self) -> Literal['query', 'signal']: pass

    @property
    def universe(self) -> UniverseConfig: pass

    @property
    def queries(self) -> List[QueryConfig]: pass

    @property
    def signals(self) -> List[SignalConfig]: pass
```

#### 2. StrategyFactory

**Purpose**: Instantiate strategies from configuration
**Location**: `Strategies/Factory/StrategyFactory.py`

```python
class StrategyFactory:
    """
    Instantiate GrinoldKahnPortfolio or QueryStrategy from config.

    Handles both query-based and signal-based strategies.
    """

    def __init__(self, registry: Optional[StrategyRegistry] = None):
        """Initialize with optional custom registry."""
        self.registry = registry or StrategyRegistry()

    def create_from_yaml(self, yaml_path: str) -> Union[QueryStrategy, GrinoldKahnPortfolio]:
        """Create strategy from YAML file."""
        config = StrategyConfig(yaml_path)
        return self.create_from_config(config)

    def create_from_dict(self, config_dict: dict) -> Union[QueryStrategy, GrinoldKahnPortfolio]:
        """Create strategy from dictionary."""
        config = StrategyConfig.from_dict(config_dict)
        return self.create_from_config(config)

    def create_from_config(self, config: StrategyConfig) -> Union[QueryStrategy, GrinoldKahnPortfolio]:
        """Create strategy from StrategyConfig object."""
        if config.mode == 'query':
            return self._create_query_strategy(config)
        elif config.mode == 'signal':
            return self._create_signal_strategy(config)
        else:
            raise ValueError(f"Unknown mode: {config.mode}")

    def _create_query_strategy(self, config: StrategyConfig) -> QueryStrategy:
        """Create QueryStrategy with triggers and actions."""
        triggers = []

        for query_cfg in config.queries:
            # Build query object
            query = self._build_query(query_cfg)

            # Build entry trigger
            entry_trigger = self._build_trigger(config.entry, query, 'entry')
            triggers.append(entry_trigger)

            # Build exit trigger
            exit_trigger = self._build_trigger(config.exit, query, 'exit')
            triggers.append(exit_trigger)

        return QueryStrategy(name=config.strategy_name, triggers=triggers)

    def _create_signal_strategy(self, config: StrategyConfig) -> GrinoldKahnPortfolio:
        """Create GrinoldKahnPortfolio with signals and optimizer."""
        # Build signals
        signals = [self._build_signal(sig_cfg) for sig_cfg in config.signals]

        # Build alpha generator
        alpha_gen = AlphaGenerator(IC=config.alpha.IC)

        # Build risk model
        risk_model = self._build_risk_model(config.risk)

        # Build optimizer
        optimizer = self._build_optimizer(config.optimizer)

        return GrinoldKahnPortfolio(
            identifier=config.strategy_name,
            signals=signals,
            alpha_generator=alpha_gen,
            risk_model=risk_model,
            optimizer=optimizer,
            rebalance_frequency=config.execution.rebalance_frequency
        )

    def _build_query(self, query_cfg: QueryConfig) -> BaseQuery:
        """Build query object from configuration."""
        # Dispatch to appropriate query builder
        if query_cfg.type == 'outright':
            return self._build_outright_query(query_cfg)
        elif query_cfg.type == 'fly':
            return self._build_fly_query(query_cfg)
        elif query_cfg.type == 'curve':
            return self._build_curve_query(query_cfg)
        else:
            raise ValueError(f"Unknown query type: {query_cfg.type}")

    def _build_signal(self, signal_cfg: SignalConfig) -> BaseSignal:
        """Build signal object from configuration."""
        if signal_cfg.type == 'carry':
            return CarrySignal(
                standardize=signal_cfg.config.get('standardize', True)
            )
        elif signal_cfg.type == 'momentum':
            return MomentumSignal(
                lookback_days=signal_cfg.config['lookback_days'],
                standardize=signal_cfg.config.get('standardize', True)
            )
        elif signal_cfg.type == 'mean_reversion':
            return MeanReversionSignal(
                lookback_days=signal_cfg.config['lookback_days'],
                standardize=signal_cfg.config.get('standardize', True)
            )
        elif signal_cfg.type == 'custom':
            return self._load_custom_signal(signal_cfg)
        else:
            raise ValueError(f"Unknown signal type: {signal_cfg.type}")

    def _build_trigger(self, rule_cfg: RuleConfig, query: BaseQuery, action_type: str) -> Trigger:
        """Build trigger from entry/exit rule configuration."""
        # Dispatch based on rule type
        if rule_cfg.type == 'date':
            return self._build_date_trigger(rule_cfg, query, action_type)
        elif rule_cfg.type == 'signal':
            return self._build_signal_trigger(rule_cfg, query, action_type)
        elif rule_cfg.type == 'event':
            return self._build_event_trigger(rule_cfg, query, action_type)
        elif rule_cfg.type == 'calendar':
            return self._build_calendar_trigger(rule_cfg, query, action_type)
        else:
            raise ValueError(f"Unknown trigger type: {rule_cfg.type}")
```

#### 3. StrategyRegistry

**Purpose**: Catalog of pre-built strategy templates
**Location**: `Strategies/Registry/StrategyRegistry.py`

```python
class StrategyRegistry:
    """
    Catalog of pre-built strategy templates.

    Provides quick access to common strategy patterns.
    """

    def __init__(self):
        self._templates: Dict[str, dict] = {}
        self._load_builtin_templates()

    def _load_builtin_templates(self):
        """Load built-in strategy templates."""
        self._templates['carry_simple'] = {
            'strategy': {'name': 'Simple Carry', 'type': 'carry', 'mode': 'signal'},
            'signals': [{'type': 'carry', 'config': {'standardize': True}}],
            'alpha': {'IC': 0.05},
            # ... rest of config
        }

        self._templates['fomc_fly'] = {
            'strategy': {'name': 'FOMC Butterfly', 'type': 'event_driven', 'mode': 'query'},
            # ... FOMC fly config
        }

        # Add more templates

    def get_template(self, name: str) -> dict:
        """Get strategy template by name."""
        if name not in self._templates:
            raise KeyError(f"Template '{name}' not found")
        return self._templates[name].copy()

    def list_available(self) -> List[str]:
        """List all available template names."""
        return list(self._templates.keys())

    def register_template(self, name: str, template: dict):
        """Register custom template."""
        self._templates[name] = template

    def search(self, query: str) -> List[str]:
        """Search templates by keyword."""
        return [name for name in self._templates.keys() if query.lower() in name.lower()]
```

#### 4. StrategyBuilder (Fluent API)

**Purpose**: Programmatic strategy building with fluent interface
**Location**: `Strategies/Builder/StrategyBuilder.py`

```python
class StrategyBuilder:
    """
    Fluent API for programmatic strategy construction.

    Provides method chaining for readable strategy creation.
    """

    def __init__(self):
        self._config = {}

    def with_name(self, name: str) -> 'StrategyBuilder':
        """Set strategy name."""
        self._config['strategy'] = {'name': name}
        return self

    def with_universe(self, asset_class: str, instruments: List[str]) -> 'StrategyBuilder':
        """Set instrument universe."""
        self._config['universe'] = {'asset_class': asset_class, 'instruments': instruments}
        return self

    def add_signal(self, signal_type: str, **config) -> 'StrategyBuilder':
        """Add signal to strategy."""
        if 'signals' not in self._config:
            self._config['signals'] = []
        self._config['signals'].append({'type': signal_type, 'config': config})
        return self

    def with_alpha(self, IC: float) -> 'StrategyBuilder':
        """Set alpha configuration."""
        self._config['alpha'] = {'IC': IC}
        return self

    def with_risk_model(self, model: str, **config) -> 'StrategyBuilder':
        """Set risk model."""
        self._config['risk'] = {'covariance': model, **config}
        return self

    def with_optimizer(self, optimizer_type: str, **config) -> 'StrategyBuilder':
        """Set optimizer."""
        self._config['optimizer'] = {'type': optimizer_type, **config}
        return self

    def with_rebalancing(self, frequency: str) -> 'StrategyBuilder':
        """Set rebalancing frequency."""
        if 'execution' not in self._config:
            self._config['execution'] = {}
        self._config['execution']['rebalance_frequency'] = frequency
        return self

    def build(self) -> Union[QueryStrategy, GrinoldKahnPortfolio]:
        """Build strategy from accumulated configuration."""
        factory = StrategyFactory()
        return factory.create_from_dict(self._config)

    def to_yaml(self, filepath: str):
        """Export configuration to YAML file."""
        import yaml
        with open(filepath, 'w') as f:
            yaml.dump(self._config, f, default_flow_style=False)

# Usage:
strategy = (StrategyBuilder()
    .with_name('My Carry Strategy')
    .with_universe('futures', ['SFRZ4', 'SFRH5', 'SFRM5'])
    .add_signal('carry', standardize=True)
    .add_signal('momentum', lookback_days=30, standardize=True)
    .with_alpha(IC=0.05)
    .with_risk_model('ledoit_wolf')
    .with_optimizer('mean_variance', risk_aversion=1.0, long_only=True)
    .with_rebalancing('weekly')
    .build()
)
```

---

## Implementation Roadmap

### Phase 1: MVP (Weeks 1-2)

**Goal**: Basic YAML support for single-signal strategies

**Deliverables**:
1. `StrategyConfig` - YAML parser with basic validation
2. `StrategyFactory` - Support for simple signal-based strategies
3. JSON Schema for validation
4. Example YAML files:
   - Simple carry strategy
   - Simple momentum strategy

**Testing**:
- Unit tests for config parsing
- Integration tests for factory instantiation
- End-to-end test: YAML → Strategy → Backtest

**Success Criteria**:
- Can create GrinoldKahnPortfolio from YAML
- Produces same results as programmatic construction

---

### Phase 2: Multi-Signal Support (Week 3)

**Goal**: Support multi-signal strategies with signal combination

**Deliverables**:
1. Signal combination logic (equal weight, IC-weighted)
2. Multi-signal YAML examples
3. Signal weight configuration
4. `StrategyBuilder` fluent API

**Testing**:
- Multi-signal combination tests
- IC-weighted combination tests
- Builder API tests

**Success Criteria**:
- Can combine multiple signals
- Can weight signals by IC
- Fluent API produces equivalent YAML

---

### Phase 3: Query-Based Strategies (Week 4)

**Goal**: Support query-based (event-driven) strategies

**Deliverables**:
1. Query configuration builders
2. Trigger configuration builders
3. Entry/exit rule parsing
4. Event-driven examples (FOMC, month-end)

**Testing**:
- Query builder tests
- Trigger instantiation tests
- Event-driven backtest tests

**Success Criteria**:
- Can create QueryStrategy from YAML
- FOMC butterfly example works
- Month-end seasonality example works

---

### Phase 4: Advanced Features (Weeks 5-6)

**Goal**: Custom signals, constraints, transaction costs

**Deliverables**:
1. Custom signal plugin system
2. Optimizer constraints (long_only, max_position, leverage)
3. Transaction cost modeling
4. `StrategyRegistry` with templates

**Testing**:
- Custom signal loading tests
- Constraint enforcement tests
- Transaction cost impact tests
- Template instantiation tests

**Success Criteria**:
- Can load custom signals from Python modules
- Constraints are enforced in optimization
- Transaction costs reduce returns appropriately

---

### Phase 5: Polish & Documentation (Week 7)

**Goal**: Production-ready system with comprehensive docs

**Deliverables**:
1. Complete user documentation
2. Tutorial notebooks
3. Error handling and validation
4. CLI tool for strategy operations

**Testing**:
- Documentation examples all work
- Error messages are helpful
- CLI tool tested

**Success Criteria**:
- New user can create strategy in < 10 minutes
- All examples in docs work
- No breaking changes to existing code

---

## Appendices

### A. Complete YAML Example (Signal-Based)

See `strategies/examples/carry_strategy.yaml`

### B. Complete YAML Example (Query-Based)

See `strategies/examples/fomc_butterfly.yaml`

### C. JSON Schema

See `Strategies/Config/schema.json`

### D. Class Diagrams

```
┌─────────────────┐
│ StrategyConfig  │
├─────────────────┤
│ + yaml_path     │
│ + config_dict   │
├─────────────────┤
│ + validate()    │
│ + from_yaml()   │
│ + from_dict()   │
└─────────────────┘
         │
         │ used by
         ▼
┌─────────────────┐       ┌──────────────────┐
│StrategyFactory  │──────▶│StrategyRegistry  │
├─────────────────┤       ├──────────────────┤
│ + registry      │       │ + templates      │
├─────────────────┤       ├──────────────────┤
│ + create_*()    │       │ + get_template() │
│ + _build_*()    │       │ + list_*()       │
└─────────────────┘       └──────────────────┘
         │
         │ creates
         ▼
┌──────────────────────┐
│  QueryStrategy       │
│  GrinoldKahnPortfolio│
└──────────────────────┘
```

### E. Migration Path

**Existing Code**: No changes required
**New Code**: Use YAML configs
**Hybrid**: Mix YAML and programmatic construction

Example:
```python
# Load base strategy from YAML
strategy = StrategyFactory().create_from_yaml('base_carry.yaml')

# Customize programmatically
strategy.signals.append(CustomSignal())
strategy.optimizer.risk_aversion = 2.0

# Run backtest
bt = MinimalBacktest(strategy=strategy, ...)
bt.run()
```

---

**END OF DESIGN DOCUMENT**
