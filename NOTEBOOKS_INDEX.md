# ARBS Jupyter Notebooks - Quick Index

## Overview

This is a quick reference index for the 11 Jupyter notebooks in the ARBS project. Each notebook demonstrates specific fixed income analysis and trading techniques.

**Total Documentation**: 2,240 lines in NOTEBOOKS_COMPREHENSIVE_GUIDE.md

---

## Notebook Summary Table

| # | Notebook | Purpose | Level | Time | Key Output |
|---|----------|---------|-------|------|------------|
| 1 | **curve_builds.ipynb** | Curve construction and inspection | Intermediate | 30m | Curve objects, asset swap spreads |
| 2 | **timeseries_builder.ipynb** | Historical data collection | Intermediate | 2-4h | Time series DataFrame, statistics |
| 3 | **sfr_cvx.ipynb** | STIR convexity analysis | Advanced | 1h | CVX adjustment values, risk decomp |
| 4 | **intraday_swaps.ipynb** | High-frequency rate data | Advanced | 1-2h | Minute-level rate series |
| 5 | **usts_rv.ipynb** | Treasury curve analysis | Intermediate | 2-3h | Bond curves, spreads, volatility |
| 6 | **fomc_pricer.ipynb** | FOMC-dated swap pricing | Advanced | 1.5h | Meeting-dated rates, risk vectors |
| 7 | **medium_term_swap_pricer.ipynb** | Multi-instrument curve building | Advanced | 1h | Term structure, pricing objects |
| 8 | **month_end_irswaps_backtest.ipynb** | Seasonality backtest | Advanced | 2-3h | Strategy PnL, performance metrics |
| 9 | **curve_risk_model.ipynb** | Curve risk framework | Advanced | 1.5h | Greeks, key rate durations |
| 10 | **simple_irswaps_backtest.ipynb** | Basic backtest framework | Intermediate | 1h | Trade-level PnL, visualization |
| 11 | **fomc_fly_backtest.ipynb** | FOMC strategy backtest | Advanced | 3-4h | Dynamic strategy PnL |

---

## Learning Path Recommendations

### Path 1: Foundations (Beginner)
1. Start: **curve_builds.ipynb** - Learn curve basics
2. Then: **simple_irswaps_backtest.ipynb** - Basic backtesting
3. Then: **timeseries_builder.ipynb** - Data collection
4. Then: Read NOTEBOOKS_COMPREHENSIVE_GUIDE.md sections 1-5

**Total Time**: 3-4 hours

### Path 2: Advanced Analytics (Intermediate)
1. Prerequisites: Complete Path 1
2. **usts_rv.ipynb** - Treasury analysis
3. **sfr_cvx.ipynb** - STIR analysis
4. **intraday_swaps.ipynb** - High-frequency data
5. **curve_risk_model.ipynb** - Risk measurement

**Total Time**: 6-8 hours

### Path 3: Strategy Development (Advanced)
1. Prerequisites: Complete Paths 1 & 2
2. **fomc_pricer.ipynb** - Pricing framework
3. **medium_term_swap_pricer.ipynb** - Complex curves
4. **month_end_irswaps_backtest.ipynb** - Seasonality strategy
5. **fomc_fly_backtest.ipynb** - Sophisticated strategy

**Total Time**: 8-10 hours

---

## Notebook Catalog by Category

### Foundations (2)
- **curve_builds.ipynb**: Curve construction from multiple sources
- **simple_irswaps_backtest.ipynb**: Basic backtesting framework

### Data & Collection (2)
- **timeseries_builder.ipynb**: Multi-product historical data
- **intraday_swaps.ipynb**: Minute-level rate collection

### Analytics (3)
- **usts_rv.ipynb**: Treasury curves and volatility
- **sfr_cvx.ipynb**: STIR futures convexity
- **curve_risk_model.ipynb**: Portfolio Greeks and risk

### Pricing (2)
- **fomc_pricer.ipynb**: FOMC-dated instruments
- **medium_term_swap_pricer.ipynb**: Multi-instrument curves

### Backtesting/Strategies (2)
- **month_end_irswaps_backtest.ipynb**: Month-end seasonality
- **fomc_fly_backtest.ipynb**: FOMC meeting strategy

---

## Key Concepts by Notebook

### curve_builds.ipynb
- Curve data providers (CME, ERIS, SDR)
- Asset swap pricing
- Bond-swap spreads (MMSS)
- Multiple pricing backends (QuantLib, rateslib)

### timeseries_builder.ipynb
- TimeseriesBuilder class usage
- Multi-query collection
- Realized volatility
- Regression analysis (OLS, TLS, Deming)
- Seasonality patterns

### sfr_cvx.ipynb
- STIR futures contracts (Z25, H26, M26...)
- Convexity adjustment calculations
- Basis point value (BPV)
- Contract specifications

### intraday_swaps.ipynb
- Timezone-aware timestamps
- Business day filtering
- Parallelized data collection
- Minute-level data handling

### usts_rv.ipynb
- Treasury curve construction
- Multiple data sources (WSJ, ERIS, Webull)
- Futures basis analysis
- Curve fitting and interpolation
- Visualization techniques

### fomc_pricer.ipynb
- FOMC meeting dates
- OIS swap pricing between meetings
- Expected policy rate moves
- Risk basis functions
- Portfolio Greeks

### medium_term_swap_pricer.ipynb
- STIR futures integration
- Forward curve construction
- Multi-tenor pricing
- Risk decomposition

### month_end_irswaps_backtest.ipynb
- Calendar-based trading logic
- Seasonality exploitation
- Trigger-based entry/exit
- Mark-to-market tracking

### curve_risk_model.ipynb
- Key rate durations (KRD)
- Basis function decomposition
- Portfolio delta calculation
- Risk reporting

### simple_irswaps_backtest.ipynb
- Basic backtest structure
- Trade entry/exit mechanics
- Daily MtM calculation
- PnL visualization

### fomc_fly_backtest.ipynb
- Carry signal generation
- Dynamic entry/exit logic
- FOMC-aware positioning
- Complex strategy implementation

---

## Data Sources Reference

| Source | Provider | Notebooks | Description |
|--------|----------|-----------|-------------|
| CME_NY_EOD | CME | curve_builds, simple_irswaps, month_end | CME futures and daily rates |
| ERIS_EOD | ERIS | usts_rv, curve_risk_model | ERIS end-of-day curves |
| SDR_INTRADAY | ERIS | intraday_swaps, fomc_pricer | Swap Data Repository data |
| WSJ | Financial | usts_rv, timeseries_builder | Wall Street Journal treasuries |
| Webull | Webull | usts_rv | Futures prices via Webull |
| GSQUANT | Goldman Sachs | timeseries_builder | GS Quant econometric data |

---

## ARBS Module Usage

### MDP (Market Data Provider)
Used in: All notebooks
```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
curve = mdp._get_curve(curve_name="USD-SOFR-1D", timestamp="live")
```

### Query
Used in: All pricing notebooks
```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y")
pkg, rws = q.resolve_package(pricer_or_curve=curve)
```

### TB (Timeseries Builder)
Used in: Data collection notebooks
```python
from TB.IRSwapsTB import IRSwapsTB
tb = IRSwapsTB(mdp=mdp)
df = tb.get_timeseries(start=date1, end=date2, queries=[q])
```

### BT (Backtester)
Used in: Backtest notebooks
```python
from BT.query_engine import QueryDrivenBacktest
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)
bt.run()
```

---

## Common Code Patterns

### Pattern: Get Curve
```python
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
mdp = IRSwapsMDP(source="SOURCE_NAME")
curve = mdp._get_curve(curve_name="CURVE_NAME", timestamp=ts)
```

### Pattern: Build Query
```python
from Query.IRSwaps.IRSwapQuery import IRSwapQuery
q = IRSwapQuery(
    curve="CURVE_NAME",
    tenor="10Y",  # or use structure for CURVE/FLY
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.RATE,
    structure_kwargs={"bpv": 1}
)
```

### Pattern: Resolve and Price
```python
pkg, rws = q.resolve_package(pricer_or_curve=curve)
vmap = q.build_value_map(pricer_or_curve=curve, package=pkg, risk_weights=rws)
result = vmap.apply(value=IRSwapValue.RATE)
```

### Pattern: Collect Timeseries
```python
from TB.TimeseriesBuilder import TimeseriesBuilder
df = tb.get_timeseries(
    start=date_start,
    end=date_end,
    queries=[q1, q2, q3],
    n_jobs=8  # Parallel workers
)
```

### Pattern: Run Backtest
```python
from BT.query_engine import QueryDrivenBacktest
strategy = QueryStrategy(name="MyStrategy", triggers=triggers)
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)
bt.run()
mtm = pd.Series(bt.mtm_history)
```

---

## Troubleshooting Quick Links

See NOTEBOOKS_COMPREHENSIVE_GUIDE.md section "Troubleshooting" for:
- No data available errors
- NaN handling
- Slow collection issues
- Connection timeouts
- Curve building failures
- Debugging strategies

---

## Next Steps

1. **New users**: Start with learning path recommendations above
2. **Experienced users**: Jump to specific notebooks for reference
3. **Deep dive**: Read full NOTEBOOKS_COMPREHENSIVE_GUIDE.md
4. **Questions**: Check troubleshooting section
5. **Customize**: Use notebooks as templates for your analysis

---

## File Structure

```
ARBS/
├── curve_builds.ipynb                          # Foundations
├── timeseries_builder.ipynb                    # Data collection
├── sfr_cvx.ipynb                               # STIR analysis
├── intraday_swaps.ipynb                        # Intraday data
├── usts_rv.ipynb                               # Treasury analysis
├── fomc_pricer.ipynb                           # FOMC pricing
├── medium_term_swap_pricer.ipynb              # Multi-instrument curves
├── month_end_irswaps_backtest.ipynb           # Seasonality strategy
├── curve_risk_model.ipynb                      # Risk framework
├── simple_irswaps_backtest.ipynb              # Basic backtest
├── fomc_fly_backtest.ipynb                     # Complex strategy
│
├── NOTEBOOKS_COMPREHENSIVE_GUIDE.md            # This file (2,240 lines)
├── NOTEBOOKS_INDEX.md                          # Quick reference (this file)
│
├── MDP/                                        # Market Data Providers
│   ├── IRSwaps/
│   └── FixedRateBonds/
├── Query/                                      # Instrument queries
│   ├── IRSwaps/
│   └── FixedRateBonds/
├── TB/                                         # Timeseries builders
│   ├── IRSwapsTB.py
│   └── FixedRateBondsTB.py
└── BT/                                         # Backtesting
    ├── query_engine.py
    └── triggers.py
```

---

## Key Takeaways

1. **Modular Architecture**: Each notebook focuses on specific task
2. **Query-Driven**: Declarative instrument specification
3. **Multi-Source**: Support for diverse data providers
4. **Scalable**: Parallelization for large date ranges
5. **Comprehensive**: Coverage from basics to sophisticated strategies

---

## Version & Updates

- **Last Updated**: November 2025
- **ARBS Version**: Current development
- **Total Notebooks**: 11
- **Documentation Lines**: 2,240+
- **Code Examples**: 150+

---

For detailed information on each notebook, see **NOTEBOOKS_COMPREHENSIVE_GUIDE.md**

