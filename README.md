# Awesome Rates Backtesting System (ARBS)

A modular research codebase for building yield curves, pricing interest rate derivative, and running event- or query-driven backtests. The design mirrors “adapter”-style patterns so the backtester is **product-agnostic** while product-specific logic lives behind adapters.

---

## TL;DR

- **Backtesting engines**
  - `EventDrivenBacktest` (general instruments, hedging, P&L, risk hooks)
  - `QueryDrivenBacktest` (product-agnostic queries → package resolution → valuation)
- **Market data providers (MDP)**
  - Turn a `{curve_name, timestamp, ...}` request into a concrete **pricer/curve object**
- **Product adapters**
  - Map a product (e.g., IRS) to its **Structure** builders (outrights, curves, flies) and **Value** metrics (NPV, PV01, carry/roll)
- **Curve backends**
  - QuantLib & RatesLib wrappers with curve definition maps
- **Persistent caching**
  - ZODB-backed caches for large time-grid pricing runs

---

## Development Environment Setup

### Clean VM Installation (Recommended)

This setup ensures a reproducible environment from scratch on a fresh VM:

```bash
# 1. Verify Python version (3.11+ required)
python --version  # Should show Python 3.11.x or later

# 2. Clone repository
git clone https://github.com/pfin/ARBS.git
cd ARBS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify installation by running tests
python -m pytest tests/unit/ -v

# 5. Expected result: 1038+ tests passing (99.2% pass rate)
```

### Dependency Notes

**Core Dependencies**:
- Python 3.11+ (tested on 3.11.14)
- numpy, scipy, polars (data processing)
- QuantLib, rateslib (curve building and pricing)
- ZODB, BTrees (persistent caching)
- pytest (testing framework)

**Known Installation Issues**:
- If `multitasking` (yfinance dependency) fails to build, this is a known setuptools compatibility issue
- Most core functionality will work without yfinance (only impacts Yahoo Finance MDP)
- See `INSTALLATION_STATUS.md` for detailed diagnosis if installation fails

**Verification**:
```bash
# Quick smoke test
python -c "import numpy, polars, scipy, QuantLib, rateslib; print('Core deps OK')"

# Full test suite
python -m pytest tests/unit/ -v --tb=short

# Check test coverage
python -m pytest tests/unit/ --cov=. --cov-report=term-missing
```

### Virtual Environment (Optional but Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Quick Start

### 1) Environment

**Prerequisites**:
- Python 3.11+ (see Development Environment Setup above)
- All dependencies installed via `pip install -r requirements.txt`

Some data builders (e.g., CME/fixings/SDR) may require credentials or local files. See MDP/IRSwaps/* modules

### 2) First run (Query-driven backtest)

#### See also [this](https://github.com/yieldcurvemonkey/ARBS/blob/main/month_end_irswaps_backtest.ipynb) notebook

```py
import datetime as dt
from BT.data_handler import TimeGrid
from BT.query_strategy import QueryStrategy
from BT.triggers import Trigger, TriggerRequirements
from BT.query_actions import AddQueryAction
from BT.query_engine import QueryDrivenBacktest
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Build a time grid (EOD steps across a month)
dates = [dt.datetime(2025, 9, d) for d in range(2, 31)]
grid = TimeGrid(dates)

# Define a query: 5Y par rate on USD-SOFR-1D curve
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000},  # optional; used by many values
)

# Simple trigger that always fires (demo)
class AlwaysOn(TriggerRequirements):
    def has_triggered(self, state, backtest=None):
        from BT.event import TriggerInfo
        return TriggerInfo(True, info={})

strategy = QueryStrategy(
    name="Demo",
    triggers=[Trigger(AlwaysOn(), actions=[AddQueryAction(query=q)])],
)

# MDP: choose a source that can resolve {curve_name,timestamp}
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

# Results
print(bt.mtm_history)           # dict[datetime -> portfolio MTM]
print(bt.realized_pnl_history)  # realized P&L over time (unwinds only)
```

## Repository Layout

```txt
BT/                    # Backtesting engines, strategies, triggers, orders, portfolios
Caching/               # ZODB-based persistent cache + codecs/utilities
definitions/           # Product/curve definitions (e.g., IRS curve metadata)
docs/                  # Documentation, references, research papers, books
MDP/                   # Market Data Providers and curve builders (CME EOD, SDR, GSQuant/RatesLib)
Query/                 # Product-agnostic BaseQuery + adapters + product-specific (IRS) structures/values/backends
TB/                    # Toolboxes/utilities for batch/query runs over time grids
utils/                 # Misc utilities (e.g., QuantLib date bridges)
```

## Documentation Guide

The `docs/` directory contains theoretical foundations, design documents, and research references. Use these resources during development to ensure implementations align with quantitative finance best practices.

### Core References

**[Grinold-Kahn Active Portfolio Management](docs/references/Grinold-Kahn-Active-Portfolio-Management.md)** (PDF: `docs/books/`)
- **Foundational text** for ARBS architecture
- Use when: Implementing signals, risk models, optimizers, or performance analysis
- Key topics: Fundamental Law (IR = IC × √N), alpha scaling, covariance estimation, mean-variance optimization
- Cross-references to ARBS code for each concept

### Design Documents

**Architecture & Design**:
- `GRINOLD_KAHN_FRAMEWORK.md` - High-level framework alignment
- `GRINOLD_KAHN_IMPLEMENTATION_GAP_ANALYSIS.md` - Missing components vs. book
- `GRINOLD_KAHN_DETAILED_SPECS.md` - Detailed specifications
- `RETURNS_VS_PRICES_ANALYSIS.md` - Why returns-first design
- `ASSET_ABSTRACTION_DESIGN.md` - Asset/Portfolio hierarchy
- `COMPOSABLE_PORTFOLIO_ARCHITECTURE.md` - Nested portfolio patterns

**Component-Specific**:
- `ALPHA_GENERATOR.md` - IC × Vol × Z formula implementation
- `VOLATILITY_ESTIMATOR.md` - Volatility forecasting methods
- `RETURNS_CALCULATOR.md` - Returns calculation pipeline
- `TEAR_SHEET.md` - Performance analysis metrics
- `SIGNAL_COMBINATION_METHODS.md` - Multi-signal strategies

**Strategy Development**:
- `USER_GUIDE_STRATEGY_CREATION.md` - How to create new strategies
- `STRATEGY_MODULARIZATION_DESIGN.md` - Factory pattern for strategies
- `ADDING_CUSTOM_COMPONENTS.md` - Extending the system

### When to Use Documentation

**Before Implementation**:
1. **Check Grinold-Kahn reference** - Verify theoretical correctness
2. **Review design docs** - Understand existing patterns
3. **Check gap analysis** - See if component already planned

**During Development**:
1. **Reference formulas** - Use exact specifications from Grinold-Kahn
2. **Follow patterns** - Match existing architecture (returns-first, etc.)
3. **Cross-reference code** - Use file paths in reference docs

**During Testing**:
1. **Validate against theory** - Check if results match expected behavior
2. **Performance metrics** - Use tearsheet definitions from docs
3. **Integration** - Verify components work together per design docs

**When Stuck**:
1. **Gap analysis** - Check if problem already documented
2. **Design docs** - See if solution already specified
3. **Grinold-Kahn** - Consult theoretical foundation

### Improving Documentation

As you work:
- **Update cross-references** when adding new files
- **Document design decisions** in relevant design docs
- **Add worked examples** to component docs
- **Keep gap analysis current** as features are implemented
- **Update Grinold-Kahn cross-references** for new components

The documentation is **living**—improve it as you learn.

---

## Architecture

The system is layered so that **product-agnostic orchestration** stays separate from **product-specific logic**. Backtests operate on a time grid, pull a pricer/curve from a Market Data Provider (MDP), and evaluate *queries* that know how to turn “what to value” into concrete priceables plus the right value metrics.

- **Backtest Engines** (Event-Driven, Query-Driven): own the run loop, time, orders, positions, and P&L.
- **Queries** (Product-agnostic): describe *what* to value (e.g., “USD-SOFR 5Y rate”) without hard-coding pricing details.
- **Product Adapters**: map queries to product structures (outrights, curves, flies) and value calculations (NPV, PV01, rate).
- **MDP (Market Data Providers)**: resolve `{curve_name, timestamp, source}` into concrete **pricers/curves** (QuantLib or RatesLib).
- **Caching** (ZODB): persist expensive curve/pricer and valuation artifacts across large time grids.

### Data Flow (at each time step)

1. **Strategy → Orders**  
   Triggers fire and produce orders (add queries, scale, unwind, hedge).

2. **Query → MDP Request**  
   The query injects the timestamp policy and emits a provider-specific request.

3. **MDP → Pricer/Curve**  
   The MDP returns a pricer/curve object wired to calendars, indices, fixings, and discounting.

4. **Query → Package Resolution**  
   Using the product adapter’s *Structure Map*, the query builds a package (list of priceables + weights).

5. **Value Evaluation**  
   The query’s *Value Map* computes one or more metrics (e.g., RATE, NPV, PV01). The engine picks a default MTM metric.

6. **Portfolio Accounting**  
   Positions are updated (open/scale/unwind). MTM and realized P&L histories are recorded.

---

## Product-Agnostic Queries

A `BaseQuery` answers:
- **What**: structure type (OUTRIGHT, CURVE, FLY, …), tenor(s), curve, risk weight, tags.
- **How** (indirectly): by delegating to the **product adapter** for structure resolution and value computation.

Key responsibilities:
- `build_mdp_request(now)`: convert time and curve ID into an MDP-specific request.
- `resolve_package(pricer_or_curve)`: call the product adapter’s Structure Map to build priceables + weights.
- `build_value_map(...)`: pick the value functions for the requested metrics.
- `default_mtm_value_id()`: which metric to treat as MTM (e.g., NPV or RATE).

The query object is also the *label* and *risk weight* carrier, enabling readable output and composability.

---

## Product Adapters (IRS)

The IRS adapter provides two registries:

- **Structure Map**  
  Translates (`OUTRIGHT`, `CURVE`, `FLY`, etc.) + parameters → concrete list of instruments and weights.  
  Examples:
  - OUTRIGHT: single vanilla IRS with notional scaled by `bpv`/risk weight.
  - CURVE: ladder of IRS of different maturities.
  - FLY: weighted long/short combination across tenors.

- **Value Map**  
  Functions to compute:
  - **RATE/Par Rate**, **NPV**, **PV01/BPV**, **Carry/Roll**, **Basis** (if relevant).
  - Optional decomposition hooks (e.g., curve vs. spread legs if implemented by the backend).

Adapters isolate product details so the engine and queries remain generic and testable.

---

## Backtesting Engines

### Query-Driven Backtest
Purpose-built for `BaseQuery`:
- Freezes a **resolved package** at trade time (so structure/weights are historically consistent).
- At each step: obtains a pricer, computes the query’s **default MTM** over all open positions, and updates histories.
- Supports **unwinds** (predicate-based), realizing P&L and removing matched positions.
- Maintains:
  - `mtm_history[datetime]`
  - `realized_pnl_history[datetime]`
  - `portfolio` of `ResolvedQueryPosition` objects

### Event-Driven Backtest
A general engine with orders on concrete instruments:
- Strategies emit orders (enter/exit/scale/hedge).
- A **risk function** can measure exposure vs. the current pricer and a **HedgeAction** can build offsetting instruments.
- Tracks a simpler `Portfolio` of instruments and marks to market each step.

---

## Portfolios

- **QueryPortfolio**  
  Holds `ResolvedQueryPosition`:
  - `opened_at`, `source_query`, `package`, `weights`, labels/tags
  - removal by predicate/tag for unwinds
- **Portfolio** (Event-Driven)  
  Holds concrete instruments (often IRS) with basic accounting helpers.

Both versions log changes for transparent audit trails.

---

## Triggers & Actions

- **Triggers** decide *when* to act:
  - Time-based (date hits), periodic, or conditional (risk/level).
- **Actions** decide *what* to do:
  - `AddQueryAction`, `AddScaledQueryAction`
  - `UnwindPositionsAction` (by tag/predicate; optional transaction cost)
  - Event-driven: `HedgeAction` using a `risk_fn` to compute hedge sizes

Common patterns:
- Declarative strategies: wire triggers + actions; no engine internals leaked into strategy code.
- Composability: multiple triggers per strategy; multiple actions per trigger.

---

## Market Data Providers (MDP)

**Contract:** `get_pricer(request) -> pricer_or_curve`

Supported sources (illustrative):
- **CME_NY_EOD_LIVE (QuantLib)**  
  EOD discount curves with calendar alignment and fixings; returns a QL-based pricer/index bundle.

- **SDR_INTRADAY (RatesLib)**  
  Rebuilds OIS/STIR curve families from SDR or local stores; returns RL curve/pricer objects.

- **GSQUANT_RL**  
  RatesLib reconstruction of GSQuant-style recipes (module stubs available; extend as needed).

MDPs are the single entry point for historical/point-in-time curve construction. They encapsulate calendars, instruments, compounding conventions, and fixing stores.

---

## Curve Backends

- **QuantLib (QL)**  
  - Curve definitions & builders map repo “curve names” (e.g., `USD-SOFR-1D`) to pillar sets, day counts, and calendars.
  - Provides IRS indices, par rate solvers, and valuation functions.

- **RatesLib (RL)**  
  - Alternative curve engine for the same curve families (STIR/OIS).  
  - Used for rapid prototyping and SDR-driven intraday reconstructions.

Backends are swappable as long as the pricer/curve interface exposed by the MDP remains consistent.

---

## Persistent Caching (ZODB)

For large time-grids and expensive builds:
- **`ZODBCacheMixin`** provides:
  - File-storage with safe locking
  - Object graphs via BTrees
  - Reference counting & batched writes
- Typical cache keys:
  - MDP request signature (source, curve name, timestamp)
  - Query signature (structure/value params)
  - Derived tables (e.g., time-grid pivots)

**Tip:** Use the toolbox utilities for bulk runs to maximize cache reuse.

---

## Key Modules (by Role)

- **Backtesting**
  - `BT/query_engine.py` — `QueryDrivenBacktest`
  - `BT/generic_engine.py` — `EventDrivenBacktest`
  - `BT/triggers.py` — trigger requirements & glue
  - `BT/query_actions.py` — add/scale/unwind actions
  - `BT/query_strategy.py` / `BT/strategy.py` — compose triggers → orders

- **Queries & Adapters**
  - `Query/Base/BaseQuery.py` — product-agnostic query API
  - `Query/Base/product_adapter.py` — adapter base & registry
  - `Query/IRSwaps/adapter.py` — IRS structure/value maps
  - `Query/IRSwaps/IRSwapQuery.py` — user-facing IRS query

- **MDP & Curves**
  - `MDP/MarketDataProvider.py` — abstract interface
  - `MDP/IRSwaps/IRSwapsMDP.py` — IRS MDP sources (QL/RL)
  - `definitions/IRSwaps.py` — curve metadata, calendars, conventions
  - Backends:
    - `Query/IRSwaps/backends/quantlib/*`
    - `Query/IRSwaps/backends/rateslib/*`

- **Caching & Tooling**
  - `Caching/ZODBCacheMixin.py`, `Caching/CodecMapping.py`
  - `TB/IRSwapsTB.py`, `TB/utils.py`

---

## Example: Query-Driven Workflow

```python
# 1) Define time grid
grid = TimeGrid([...datetimes...])

# 2) Create strategy (triggers → AddQueryAction/UnwindPositionsAction)
strategy = QueryStrategy(name="Demo", triggers=[...])

# 3) Pick an MDP (curve source)
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")

# 4) Run
bt = QueryDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
bt.run()

# 5) Inspect
bt.mtm_history
bt.realized_pnl_history
bt.portfolio  # ResolvedQueryPosition entries
```

## Example: Event-Driven Hedging

```py
def risk_fn(portfolio, pricer):
    # Compute DV01 or key-rate vector from current portfolio against the pricer
    return {"dv01": ...}

strategy = Strategy(
    triggers=[
        DateTrigger(..., actions=[
            EnterInstrumentAction(...),
            HedgeAction(risk_fn=risk_fn, hedge_instrument_factory=...),
        ])
    ]
)
engine = EventDrivenBacktest(time_grid=grid, mdp=mdp, strategy=strategy)
engine.run()
```

---

## Extending the System

This section shows how to add **new products**, **new curve sources**, and **new value metrics** without touching the core engines.

### 1) Add a New Product (e.g., Swaptions)

**Goal:** Teach the system how to resolve structures (what to build) and compute values (what to report).

1. **Create a Product Adapter**
   - File: `Query/<Product>/adapter.py`
   - Implement:
     - `StructureMap`: OUTRIGHT, SPREAD, CURVE, FLY, … → `[priceables, weights]`
     - `ValueMap`: RATE, NPV, PV01, Carry/Roll, Greeks, …
   - Register adapter:
     ```python
     from Query.Base.product_adapter import register_product
     register_product("Swaptions", SwaptionAdapter())
     ```

2. **Define the Product Query**
   - File: `Query/<Product>/<Product>Query.py`
   - Subclass `BaseQuery`:
     - Add parameters (tenors, expiries, strikes, tags, bpv/risk weights).
     - Implement any convenience helpers and labels.
     - Optionally override `default_mtm_value_id()`.

3. **Provide Backends (if needed)**
   - `Query/<Product>/backends/quantlib/*` (QL builders/pricers)
   - `Query/<Product>/backends/rateslib/*` (RL builders/pricers)

4. **Wire Metadata**
   - `definitions/<Product>.py` for calendars, day-count, compounding, etc.

5. **Test**
   - Unit tests for `StructureMap`, `ValueMap`, and query round-trips.
   - Golden-file tests for MTM determinism across time grids.

> **Rule of thumb:** Adapters are the only place where product-specific knowledge lives. Engines and strategies should remain product-agnostic.

---

### 2) Add a New Curve Source (MDP)

**Goal:** Resolve `{source, curve_name, timestamp}` into a concrete pricer/curve.

1. **Implement/Extend `MarketDataProvider`**
   - File: `MDP/<Domain>/<Domain>MDP.py`
   - Recognize a new `source` string (e.g., `"SDR_INTRADAY-v2"`).
   - Build the backend pricer:
     - Calendars, indices, fixings
     - Pillar instruments and bootstrap rules
     - Discounting/forecast curves

2. **Stabilize the Request Contract**
   - `get_pricer(request) -> pricer_or_curve`
   - Ensure consistent attributes across backends (e.g., `par_rate(tenor)`, `npv(legs)`, `pv01(tenor)`).

3. **Caching**
   - Include **recipe hashes** and **data version** in the cache key to avoid mixing artifacts across curve versions.

4. **Validation**
   - Smoke-test a small time grid.
   - Compare par rates vs. a reference (tolerance gates).
   - Check fixing coverage for historic dates.

---

### 3) Add a New Value Metric

1. **Extend the Enum**
   - File: `Query/<Product>/<Product>Value.py`
   - Add a new metric (e.g., `KRD_2Y`, `CR01`, `Theta`).

2. **Implement Calculation**
   - In the product `ValueMap`, add a function that consumes:
     - `pricer_or_curve`
     - the resolved package (instruments + weights)
     - optional context (bpv, bump size, roll horizon)

3. **Expose in Queries**
   - Allow users to request the new value via query parameters or helper methods.
   - Update `default_mtm_value_id()` if the new metric should be the default mark.

---

### 4) Integrate with the Toolbox

- For large historical runs, prefer `TB/<Product>TB.py` utilities:
  - Batch evaluation over `TimeGrid`
  - Concurrency where safe (thread/process pools)
  - On-disk ZODB persistence to amortize bootstraps and valuations
- Emit tidy DataFrames (long format) for downstream analysis and plotting.

---

## Troubleshooting

### Calendars & Fixings
- **Symptom:** Valuation errors or missing fixings.  
  **Fix:** Align the **timestamp policy** (trade vs. close) with the curve’s business calendar; backfill/attach fixings for historical dates.

### Determinism
- **Symptom:** Re-running yields different MTM.  
  **Fix:** Ensure the **package is frozen at trade time**. Put all recipe knobs (pillars, day-counts, compounding, smoothing) into the cache key.

### QuantLib / RatesLib Mismatch
- **Symptom:** Backend-to-backend rate drift.  
  **Fix:** Compare conventions (day-count, compounding, float index, accrual calendars) and bootstrap settings. Add a **tolerance test** per tenor.

### Cache Invalidation
- **Symptom:** Stale curves after recipe changes.  
  **Fix:** Bump the cache namespace or add a **recipe hash** component to keys. Occasionally `pack` ZODB stores to reclaim disk.

### Performance
- **Tip:** Use **bulk build** paths in MDP, enable **BTrees** for large maps, and prefer **vectorized** price calls where the backend allows.
- **Tip:** Constrain `TimeGrid` to required dates only; avoid minute-level grids unless truly necessary.

### Common Install Issues
- **QuantLib wheels:** Prefer conda-forge or platform wheels.  
- **C/C++ builds:** Align compiler/Boost versions; clear stale build artifacts.

---

## Notes & Conventions

- **Labels & Risk Weights:** Queries carry human-readable labels; arithmetic on queries preserves labels and applies risk weights (`bpv`) consistently.
- **Default MTM:** Products should choose an intuitive default (e.g., IRS → NPV or Par RATE). Keep it stable across versions.
- **Time Policy:** Be explicit (`asof="NY 16:00 close"` vs. `asof="trade_ts"`); mix-ups cause silent mis-marks.
- **Testing:** 
  - Unit tests for structure/value maps
  - Golden MTM for determinism
  - Backend parity checks with narrow tolerances
- **Logging:** Backtests and portfolios should log all adds/unwinds with timestamps, tags, and computed MTM/PNL deltas for auditability.
