# ARBS Technical Commands & Setup Guide

Extracted from `/home/peter/ARBS/CLAUDE.md` - All commands are copy-pasteable.

## Environment Setup

### Python Version Requirement
- **Minimum**: Python 3.12+ (tested with 3.12.9)
- README specifies 3.13 but 3.12+ is acceptable

### Initial Virtual Environment Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate environment (Linux/Mac)
source venv/bin/activate

# Activate environment (Windows)
venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

### Verify Installation

```bash
# Test basic imports and verify versions
python test_basic_workflow.py

# Expected output should show:
# ✓ numpy, pandas, QuantLib, rateslib versions
# ✓ Query creation and arithmetic
# ✓ MDP request building
# ✓ Curve definitions lookup
```

### Key Dependencies Installed
- **Pricing Engines**: QuantLib 1.39, rateslib 2.1.1
- **Data**: numpy 2.3.2, pandas 2.3.1, pyarrow 21.0.0
- **Persistence**: ZODB 6.0.1, BTrees 6.1, persistent 6.1.1
- **Network**: aiohttp 3.12.15, httpx 0.28.1, requests 2.32.4
- **Visualization**: matplotlib 3.10.5, plotly 6.3.0
- **Notebooks**: ipykernel 6.30.1, nest-asyncio 1.6.0

---

## Running Tests

### Quick Validation (No Market Data Required)

```bash
# Test query creation and arithmetic (runs in ~1 second)
python test_basic_workflow.py
```

### Full Integration Testing

Use Jupyter notebooks in repo root:
- `*_backtest.ipynb` - Backtest examples
- `*_pricer.ipynb` - Pricer examples

**Note**: Full backtests require market data sources (CME credentials, SDR files)

---

## Development Workflow Commands

### Interactive Development Setup

```bash
# Activate virtual environment first
source venv/bin/activate

# Run a backtest interactively
jupyter notebook month_end_irswaps_backtest.ipynb

# OR start Jupyter server and navigate to notebooks
jupyter notebook
```

### Quick Code Validation

```bash
# Test imports (useful after making changes)
python -c "
import sys
sys.path.insert(0, '.')
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
print('✓ Imports successful')
"
```

### Validate Curve Definitions

```bash
# Check available curves
python -c "
from definitions.IRSwaps import CURVE_DEFINITIONS
print(f'Available curves: {len(CURVE_DEFINITIONS)}')
print(list(CURVE_DEFINITIONS.keys())[:3])
"
```

### Add ARBS to Python Path

```bash
# Option 1: Set environment variable
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Option 2: Add to top of scripts
# import sys
# sys.path.insert(0, '.')
```

---

## Common Development Tasks

### Adding a New Curve Source

**Steps:**
1. Extend `MarketDataProvider` in `MDP/<Domain>/<Domain>MDP.py`
2. Add new source string recognition (e.g., `"SDR_INTRADAY-v2"`)
3. Implement `get_pricer(request)`:
   - Build calendars, indices, fixings
   - Bootstrap pillar instruments
   - Return pricer/curve with consistent interface
4. Add curve metadata to `definitions/IRSwaps.py`
5. Test with small time grid and compare par rates vs. reference

### Adding a New Value Metric

**Steps:**
1. Add enum value to `Query/<Product>/<Product>Value.py`
2. Implement calculation in product's `ValueMap` (`Query/<Product>/adapter.py`)
3. Function signature: `(pricer_or_curve, package, risk_weights, **context) -> float`
4. Update `default_mtm_value_id()` in query class if it should be default MTM

### Adding a New IRS Structure Type

**Steps:**
1. Add enum to `Query/IRSwaps/IRSwapStructure.py`
2. Implement builder in `Query/IRSwaps/adapter.py` Structure Map
3. Add validation to `IRSwapQuery.__post_init__()` for required kwargs
4. Test package resolution:
   ```bash
   python -c "
   from Query.IRSwaps.IRSwapQuery import IRSwapQuery
   query = IRSwapQuery(...)
   package = query.resolve_package(pricer_or_curve=pricer)
   print(package)
   "
   ```

---

## Troubleshooting Commands

### Missing Fixings Issue

**Symptom**: Valuation errors on historical dates

**Fix**: Backfill fixings in `MDP/IRSwaps/fixings_cache/` or attach to pricer. Check timestamp policy: trade time vs. close time

### Non-Deterministic MTM Issue

**Symptom**: Re-running backtest yields different P&L

**Root Cause**: Package not frozen at trade time, or cache key missing recipe details

**Fix**: Ensure `QueryDrivenBacktest` freezes package at `opened_at`; add recipe hash to cache key

### Calendar Misalignment Issue

**Symptom**: Settlement date mismatch between backends

**Fix**: Verify calendar string in `definitions/IRSwaps.py` matches backend convention
- QuantLib uses `"US Government Bond"`
- RatesLib uses `"nyc"` for USD

### Performance Issues

**Solutions**:
```bash
# Use toolbox utilities for bulk runs
# Use TB/<Product>TB.py

# Enable ZODB caching for repeated curve builds
# (see Caching/ZODBCacheMixin.py)

# Constrain time grids to necessary dates only

# Consider parallel processing in MDP curve builders
# (see rl_curve_utils/)
```

---

## Converting Notebooks to Scripts

```bash
# Convert notebook to Python script
jupyter nbconvert --to python notebook_name.ipynb

# Clean up for non-interactive execution
# Remove: get_ipython() calls, %magic commands, plt.show()
# Add: sys.path.insert(0, '.') for imports
```

**Note**: `month_end_irswaps_backtest.ipynb` successfully converts and runs to 99% completion (396/402 steps) before requiring CME data access.

---

## Important Files Reference

### Core Backtesting
- `/home/peter/ARBS/BT/query_engine.py` - Main backtesting loop for queries

### Query & Adapter Layer
- `/home/peter/ARBS/Query/Base/BaseQuery.py` - Abstract query interface
- `/home/peter/ARBS/Query/Base/product_adapter.py` - Adapter registry and base class
- `/home/peter/ARBS/Query/IRSwaps/adapter.py` - IRS structure/value maps
- `/home/peter/ARBS/Query/IRSwaps/IRSwapQuery.py` - User-facing IRS query builder
- `/home/peter/ARBS/Query/IRSwaps/IRSwapStructure.py` - Structure definitions
- `/home/peter/ARBS/Query/IRSwaps/IRSwapValue.py` - Value metric definitions

### Market Data
- `/home/peter/ARBS/MDP/IRSwaps/IRSwapsMDP.py` - IRS market data provider dispatcher
- `/home/peter/ARBS/definitions/IRSwaps.py` - Curve metadata and conventions (ALWAYS CHECK THIS)

### Backend Systems
- `/home/peter/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py` - QuantLib curve configs
- `/home/peter/ARBS/Query/IRSwaps/backends/quantlib/ql_pricer.py` - QuantLib IRS valuation
- `/home/peter/ARBS/Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py` - RatesLib curve recipes
- `/home/peter/ARBS/Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py` - RatesLib wrapper

### Caching & Utilities
- `/home/peter/ARBS/Caching/ZODBCacheMixin.py` - Persistent cache infrastructure
- `/home/peter/ARBS/TB/` - Toolbox utilities for bulk runs

### Jupyter Notebooks (Examples)
- `/home/peter/ARBS/month_end_irswaps_backtest.ipynb` - Full query-driven backtest walkthrough
- `/home/peter/ARBS/simple_irswaps_backtest.ipynb` - Minimal example
- `/home/peter/ARBS/curve_builds.ipynb` - Curve construction and validation
- `/home/peter/ARBS/fomc_fly_backtest.ipynb` - Event-driven strategy example

---

## Query-Driven Pattern Example

```python
from BT.query_engine import QueryDrivenBacktest
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Define what to value
q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    tenor="5Y",
    curve="USD-SOFR-1D",
    structure_kwargs={"bpv": 1_000_000}
)

# Query arithmetic is supported
fly = q_2y + q_5y - 2*q_3y  # Creates a fly structure
```

---

## Code Conventions

### Frozen Dataclasses
- `BaseQuery`, `IRSwapQuery`, etc. are **frozen** for hashability
- Modify using: `from dataclasses import replace`
- Usage: `replace(query, field=new_value)`

### Risk Weights vs. Notional
- `risk_weight` (query-level): Scalar multiplier for query arithmetic
- `bpv` (structure-level): Basis point value (PV01 target) for sizing
- `notional` (structure-level): Raw notional amount

### Labels and Signatures
- `Query.col_name()`: Human-readable label for DataFrames/plots
- `Query.signature()`: Stable identifier for portfolio keys/logging
- Format: `product=IRS|struct=OUTRIGHT|tenor=5Y|curve=USD-SOFR-1D`

---

## Testing Strategy

Since there's no formal test framework:

1. **Curve Builds**: Validate par rates against known reference (e.g., Bloomberg)
2. **Structure Resolution**: Check package weights sum correctly for flies/curves
3. **Value Calculations**: Compare NPV/PV01 across backends (QL vs. RL)
4. **Backtests**: Run on known periods with expected P&L ranges
5. **Golden Files**: Save MTM histories and diff on refactors

---

## Development Notes

- **No linter configured**: Manual code formatting required
- **No CI/CD**: Manual validation via notebooks
- **Git workflow**: Single branch (main), no PR process visible
- **Data sources**: Some require credentials (CME API, SDR files)
- **Backend Parity**: Both QuantLib and RatesLib should produce similar par rates within tolerance (~0.1-1bp)
