# ARBS Source Code - Quick Reference Guide

**Last Updated:** November 10, 2025
**Total Files:** 121 Python files, 28,342 lines of code

---

## Key Files at a Glance

### Critical Entry Points

| File | Lines | Purpose |
|------|-------|---------|
| `fomc_fly_backtest.py` | 197 | FOMC butterfly backtest script |
| `definitions/IRSwaps.py` | 159 | Curve definitions (20+ curves) |
| `BT/query_engine.py` | 194 | Main backtesting loop |
| `MDP/IRSwaps/IRSwapsMDP.py` | 878 | Swap data provider |
| `MDP/FixedRateBonds/FixedRateBondsMDP.py` | 1215 | Bond data provider |
| `TB/TimeseriesBuilder.py` | 361 | Results aggregation |

### Base Classes (Must Understand)

| File | Purpose |
|------|---------|
| `Query/Base/BaseQuery.py` | Abstract query interface |
| `MDP/MarketDataProvider.py` | Abstract MDP interface |
| `BT/query_strategy.py` | Abstract strategy interface |

### Largest/Most Complex Modules

| File | Lines | Complexity |
|------|-------|-----------|
| `RVUtils/regression.py` | 1286 | High - Statistical models |
| `RVUtils/plt_timeseries.py` | 1223 | High - Plotting engine |
| `MDP/FixedRateBonds/WEBULL/WebullFintechFetcher.py` | 1337 | High - Web scraping |
| `MDP/FixedRateBonds/FixedRateBondsMDP.py` | 1215 | High - Multi-source coordination |
| `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py` | 1049 | High - Curve building |

---

## Module Summary Table

```
┌─────────────────────┬──────┬────────────────────────────────────────┐
│ Module              │Files │ Purpose                                │
├─────────────────────┼──────┼────────────────────────────────────────┤
│ definitions/        │  2   │ Product/curve static definitions       │
│ Query/Base/         │  6   │ Abstract base classes                  │
│ Query/IRSwaps/      │  7   │ IR swap query & pricing                │
│ Query/FixedRateBonds│  7   │ Bond query & pricing                   │
│ MDP/IRSwaps/        │ 40   │ Swap data fetching/curve building      │
│ MDP/FixedRateBonds/ │  7   │ Bond data fetching                     │
│ BT/                 │ 15   │ Backtesting engine & components        │
│ TB/                 │  4   │ Timeseries building & aggregation      │
│ Caching/            │  4   │ Caching layer (ZODB, multi-backend)    │
│ RVUtils/            │ 18   │ Analysis & visualization tools         │
│ utils/              │  2   │ General utilities                      │
├─────────────────────┼──────┼────────────────────────────────────────┤
│ TOTAL               │121   │                                        │
└─────────────────────┴──────┴────────────────────────────────────────┘
```

---

## Import Path Cheat Sheet

### Running a Backtest

```python
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from definitions.IRSwaps import CURVE_DEFINITIONS

# Create strategy, mdp, and backtest
bt = QueryDrivenBacktest(time_grid=..., mdp=..., strategy=...)
results = bt.run()
```

### Building a Query

```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
from Query.IRSwaps.IRSwapStructure import IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Create a 2Y10Y fly
query = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    value=[IRSwapValue.NPV, IRSwapValue.PV01],
    structure_kwargs={
        'near_tenor': '2Y',
        'mid_tenor': '10Y',
        'far_tenor': '30Y',
    },
    market_request={'curve_name': 'USD-SOFR-1D', 'timestamp': 'live'}
)
```

### Accessing Curves

```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

# Create swap MDP
mdp = IRSwapsMDP(source='CME_NY_EOD_LIVE-ql_basic')

# Get pricer for a date
request = {
    'curve_name': 'USD-SOFR-1D',
    'timestamp': datetime.date(2024, 1, 15)
}
curve = mdp.get_pricer(request)
```

### Bond Queries

```python
from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

# Create bond query
query = FixedRateBondQuery(
    cusip='912810RX8',  # 10Y UST
    value=FixedRateBondValue.YTM,
    curve='WEBULL'  # Data source
)
```

---

## Key Enums and Constants

### IRSwapStructure
```
OUTRIGHT        - Single swap
CURVE           - Curve position (calendar spread)
FLY             - Butterfly (3-leg)
STIR_FLY        - STIR fly (SOFR futures vs OIS)
CURVE_FLY       - Curve + fly combo
STAGGERED_CURVE - Staggered calendar spreads
...
```

### IRSwapValue
```
NPV      - Net present value
PV01     - Price value of 1bp move
DV01     - Dollar value of 1bp
CS01     - Carry and scarcity value
Basis    - Cash vs futures basis
Swap_NPV - Swap component NPV
...
```

### FixedRateBondValue
```
Price     - Clean price
YTM       - Yield to maturity
Duration  - Modified duration
Convexity - Convexity
OAS       - Option-adjusted spread
...
```

### Data Sources
```
CME_NY_EOD_LIVE-ql_basic      - CME with QuantLib
CME_NY_EOD_LIVE-rl_basic      - CME with RatesLib
SDR_INTRADAY-RL               - SEC SDR with RatesLib
ERIS_EOD_LIVE-RL_BASIC        - ERIS pricing
GSQUANT-RL                    - Goldman Sachs Quant
```

---

## File Dependency Quick Map

```
fomc_fly_backtest.py
  ├─ BT/query_engine.py (QueryDrivenBacktest)
  ├─ BT/query_strategy.py (QueryStrategy)
  ├─ MDP/IRSwaps/IRSwapsMDP.py (IRSwapsMDP)
  ├─ Query/IRSwaps/IRSwapQuery.py (IRSwapQuery)
  └─ definitions/IRSwaps.py (CURVE_DEFINITIONS)

BT/query_engine.py
  ├─ Query/Base/BaseQuery.py (abstract)
  ├─ MDP/MarketDataProvider.py (abstract)
  ├─ BT/query_portfolio.py (portfolio tracking)
  ├─ BT/execution_engine.py (execution)
  └─ TB/TimeseriesBuilder.py (results)

MDP/IRSwaps/IRSwapsMDP.py
  ├─ MDP/IRSwaps/CME_NY_EOD_LIVE/ (fetchers)
  ├─ MDP/IRSwaps/SDR_INTRADAY/ (builders)
  ├─ Query/IRSwaps/backends/ (pricers)
  └─ Caching/ (result cache)

Query/IRSwaps/IRSwapQuery.py
  ├─ Query/Base/BaseQuery.py (abstract)
  ├─ Query/IRSwaps/IRSwapStructure.py (structures)
  ├─ Query/IRSwaps/IRSwapValue.py (metrics)
  └─ Query/IRSwaps/adapter.py (adapter)

TB/TimeseriesBuilder.py
  ├─ Query/Base/BaseQuery.py
  ├─ TB/IRSwapsTB.py
  ├─ TB/FixedRateBondsTB.py
  ├─ Caching/timeseries_cache.py
  └─ RVUtils/ (analysis)
```

---

## Common Workflows

### 1. Running FOMC Butterfly Backtest

```bash
# Terminal
python fomc_fly_backtest.py

# Or in notebook
%run fomc_fly_backtest.py
```

### 2. Building Custom Strategy

```python
# Create strategy class
class MyStrategy(QueryStrategy):
    def get_orders(self, now):
        # Return list of QueryOrder objects
        if condition:
            return [AddQueryAction(query)]
        else:
            return []

# Create backtest
bt = QueryDrivenBacktest(
    time_grid=time_grid,
    mdp=IRSwapsMDP(source='CME_NY_EOD_LIVE-ql_basic'),
    strategy=MyStrategy()
)

# Run
results_df = bt.run()
```

### 3. Analyzing Curve Data

```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from definitions.IRSwaps import CURVE_DEFINITIONS

mdp = IRSwapsMDP(source='SDR_INTRADAY-RL')

# Get curve at specific date/time
curve = mdp.get_pricer({
    'curve_name': 'USD-SOFR-1D',
    'timestamp': datetime.datetime(2024, 1, 15, 15, 0)
})

# Inspect curve
print(curve.nodes)    # Tenors
print(curve.rates)    # Rates at tenors
```

### 4. Timeseries Analysis with RVUtils

```python
from RVUtils.plt_timeseries import plot_timeseries
from RVUtils.regression import run_regression
from RVUtils.Interpolation import NelsonSiegelSvensson

# Plot
plot_timeseries(df, columns=['NPV', 'PV01'])

# Regress
results = run_regression(df['NPV'], df[['SOFR', 'OIS']])

# Interpolate curve
nss = NelsonSiegelSvensson()
nss.fit(tenors, rates)
interpolated = nss.interpolate(new_tenors)
```

---

## Common Errors & Solutions

### Error: "No module named 'Query'"
**Solution:** Run from project root; Python path needs ARBS/ directory

### Error: "IRSwapsMDP could not build curve"
**Solution:** Check curve_name in request; must be in CURVE_DEFINITIONS

### Error: "get_pricer returned None"
**Solution:** Check data source availability; may need to add fetcher

### Error: "product adapter not found"
**Solution:** Ensure adapter.py exists; check product_adapter.py registry

### Error: "Cache miss - building curve takes long"
**Solution:** Normal for first run; curves are cached after; use ZODB for persistent cache

---

## Performance Tips

1. **Reuse MDP instances** - Don't recreate per timestep
2. **Enable caching** - Curves cached by request signature
3. **Use persistent cache** - ZODB for multi-run analysis
4. **Parallel curves** - SDR_INTRADAY supports parallel builders
5. **Batch data fetching** - Fetchers cache results
6. **Profile code** - Use `%timeit` in notebooks

---

## Directory Navigation

### To add a new curve:
1. Add definition to `definitions/IRSwaps.py`
2. Create fetcher in `MDP/IRSwaps/CME_NY_EOD_LIVE/` (or appropriate source)
3. Register in `IRSwapsMDP._get_curve()` method
4. Test with `IRSwapQuery`

### To add a new bond source:
1. Create fetcher in `MDP/FixedRateBonds/[SOURCE]/`
2. Register in `FixedRateBondsMDP` routing
3. Test with `FixedRateBondQuery`

### To add analysis tool:
1. Create module in `RVUtils/`
2. Import in notebooks
3. Use with backtesting results

---

## Data Files & Caches

```
MDP/IRSwaps/
  ├─ fixings_cache/           SOFR fixings cache
  │   └─ USD-SOFR-1D_fixings/
  │
  └─ SDR_INTRADAY/
      └─ rl_curve_utils/
          └─ _RLCurveCache   Cached curves

MDP/FixedRateBonds/
  └─ reference_data_cache/    UST reference data
      └─ ust_reference_data/
          └─ fiscaldata/      Daily snapshots

Caching/                       ZODB persistent store
```

---

## Testing/Debugging Commands

```python
# Check curve definitions
from definitions.IRSwaps import CURVE_DEFINITIONS
print(list(CURVE_DEFINITIONS.keys()))

# Test MDP
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
mdp = IRSwapsMDP()
curve = mdp.get_pricer({'curve_name': 'USD-SOFR-1D', 'timestamp': 'live'})
print(f"Curve nodes: {curve.nodes}")

# Test query
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
q = IRSwapQuery(structure='OUTRIGHT', value='NPV')
print(f"Query: {q.signature()}")

# Test backtest engine
from BT.query_engine import QueryDrivenBacktest
bt = QueryDrivenBacktest(...)
# Single timestep
bt.run(end_date=datetime.date(2024, 1, 15))
```

---

## Quick Stats

- **Total Lines:** 28,342
- **Total Files:** 121
- **Largest File:** regression.py (1,286 lines)
- **Average File Size:** 234 lines
- **Packages:** 11 major modules
- **Data Sources:** 8 sources (CME, FRED, SDR, ERIS, Barchart, Webull, WSJ, FedInvest)
- **Pricing Engines:** 2 (QuantLib, RatesLib)
- **Curve Models:** 10+ interpolation methods
- **Strategies:** Extensible via QueryStrategy ABC
- **Analysis Tools:** 18 RVUtils files

---

## Key Abbreviations

| Abbr | Meaning |
|------|---------|
| MDP | Market Data Provider |
| IRS | Interest Rate Swap |
| FRB | Fixed Rate Bond |
| SOFR | Secured Overnight Financing Rate |
| OIS | Overnight Index Swap |
| CME | Chicago Mercantile Exchange |
| SDR | Swap Data Repository |
| ERIS | Eris Exchange |
| FRED | Federal Reserve Economic Data |
| QL | QuantLib |
| RL | RatesLib |
| NPV | Net Present Value |
| PV01 | Price Value of 1 Basis Point |
| DV01 | Dollar Value of 1 Basis Point |
| CS01 | Carry and Scarcity Value |
| OAS | Option-Adjusted Spread |
| YTM | Yield to Maturity |
| TB | Timeseries Builder |
| BT | Backtesting |
| ZODB | Zope Object Database |

---

## Resources

- **Main README:** `/home/user/ARBS/README.md`
- **Installation:** `/home/user/ARBS/INSTALLATION_AND_SETUP_GUIDE.md`
- **Examples:** Jupyter notebooks in root directory
- **Architecture Diagrams:** `/home/user/ARBS/SOURCE_CODE_ARCHITECTURE_DIAGRAMS.md`
- **Detailed Tree:** `/home/user/ARBS/SOURCE_CODE_TREE_VISUALIZATION.md`

---

Generated: November 10, 2025 | Complete source code mapping of ARBS project

