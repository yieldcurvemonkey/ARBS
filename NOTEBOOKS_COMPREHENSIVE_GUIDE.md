# ARBS Jupyter Notebooks Comprehensive Guide

## Overview

This document provides comprehensive documentation for all Jupyter notebooks in the ARBS (Arbitrage Rate Based Systems) project. The notebooks demonstrate various aspects of fixed income analysis, from basic curve construction to sophisticated backtesting strategies.

**Project:** ARBS - Interest Rate Arbitrage Trading System
**Last Updated:** November 2025
**Scope:** 11 comprehensive notebooks covering curve construction, pricing, analysis, and backtesting

---

## Table of Contents

1. [Quick Start Guide](#quick-start-guide)
2. [Architecture Overview](#architecture-overview)
3. [Notebook Catalog](#notebook-catalog)
4. [Detailed Notebook Guides](#detailed-notebook-guides)
5. [Common Patterns and Best Practices](#common-patterns-and-best-practices)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start Guide

### Prerequisites

Before running any notebook, ensure you have installed:

```bash
# Core dependencies
pip install pandas numpy matplotlib plotly
pip install QuantLib rateslib
pip install gs-quant  # For Goldman Sachs data sources
pip install jupyter
```

### Running Your First Notebook

1. Start Jupyter:
   ```bash
   jupyter notebook
   ```

2. Navigate to any notebook (e.g., `curve_builds.ipynb`)

3. Execute cells sequentially - notebooks depend on proper initialization in early cells

4. Common initialization pattern in all notebooks:
   ```python
   %load_ext autoreload
   %autoreload 2
   import nest_asyncio
   nest_asyncio.apply()
   ```

### Key ARBS Modules

The notebooks use four main modules:

- **MDP (Market Data Provider)**: Fetches rates, bond data, futures prices
- **Query**: Builds and prices financial instruments
- **TB (Timeseries Builder)**: Collects historical data
- **BT (Backtester)**: Runs trading strategy simulations

---

## Architecture Overview

### Data Flow

```
Data Sources (CME, SDR, ERIS, WSJ)
    ↓
MDP Layer (IRSwapsMDP, FixedRateBondsMDP)
    ↓
Query Layer (IRSwapQuery, FixedRateBondQuery)
    ↓
Pricing Backends (QuantLib, rateslib)
    ↓
TB Layer (TimeseriesBuilder, IRSwapsTB)
    ↓
Analysis & Backtesting (BT Layer)
```

### Key Concepts

**Curves**: Interest rate curves represent the term structure of rates at a point in time
- USD-SOFR-1D: SOFR OIS overnight forwards curve
- USD-FEDFUNDS: Fed Funds OIS curve
- Built from STIR futures, OIS swaps, and other instruments

**Structures**: Different multi-leg instruments
- OUTRIGHT: Single IRS leg (pay/receive)
- CURVE: Two-leg spread (e.g., 2Y vs 10Y)
- FLY: Three-leg butterfly (e.g., 2Y/5Y/10Y)

**Values**: Different pricing/analytics metrics
- RATE: Swap rate/yield
- NPV: Net present value
- PV01: Price value of basis point
- CVX_ADJ: Convexity adjustment
- MMSS: Mid-market swap spread

---

## Notebook Catalog

| Notebook | Purpose | Difficulty | Category |
|----------|---------|-----------|----------|
| curve_builds.ipynb | Curve construction and inspection | Intermediate | Foundations |
| timeseries_builder.ipynb | Historical data collection | Intermediate | Data |
| sfr_cvx.ipynb | STIR futures analysis | Advanced | Analytics |
| intraday_swaps.ipynb | High-frequency rate collection | Advanced | Data |
| usts_rv.ipynb | Treasury curve analysis | Intermediate | Analytics |
| fomc_pricer.ipynb | FOMC-dated instrument pricing | Advanced | Pricing |
| medium_term_swap_pricer.ipynb | Multi-instrument curve building | Advanced | Pricing |
| month_end_irswaps_backtest.ipynb | Seasonality backtest | Advanced | Backtesting |
| curve_risk_model.ipynb | Curve risk framework | Advanced | Risk |
| simple_irswaps_backtest.ipynb | Basic backtest framework | Intermediate | Backtesting |
| fomc_fly_backtest.ipynb | FOMC strategy backtest | Advanced | Backtesting |

---

## Detailed Notebook Guides

---

# 1. curve_builds.ipynb

## Purpose and Learning Objectives

This notebook demonstrates foundational techniques for constructing, inspecting, and using interest rate curves in the ARBS framework. You will learn:

1. How to instantiate different curve data providers (MDPs)
2. Methods for fetching curves at different timestamps
3. Techniques for pricing instruments on curves
4. How to visualize curve structures
5. Integration of QuantLib and rateslib for advanced pricing

## Key Concepts Demonstrated

### Curve Sources
The notebook shows how to access curves from multiple sources:
- **CME_NY_EOD_LIVE-ql_basic**: CME end-of-day quotes via QuantLib
- **SDR_INTRADAY-rl_usd_sofr_mtv2_q12x11**: ERIS intraday SOFR curve via rateslib
- **ERIS_EOD_LIVE-RL_BASIC**: ERIS end-of-day curves via rateslib

### Core Pricing Techniques
- Asset swap pricing (bond vs swap spread)
- Mid-market swap spread (MMSS) calculations
- Basis point value (BPV) adjustments
- Query-based instrument construction

## Data Sources and Requirements

### Data Sources
- **CME**: Chicago Mercantile Exchange futures and rates
- **ERIS**: Electronic Regulatory Information System (SOFR fixing data)
- **SDR**: Swap Data Repository (swap transaction data)
- **WSJ**: Wall Street Journal treasury data

### Requirements
- Active internet connection for live data
- Access to configured data sources
- QuantLib 1.25+ for advanced pricing
- rateslib for modern curves

## Step-by-Step Walkthrough

### Section 1: Initialization and Setup
```python
# Load modules and configure environment
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapStructure
from Query.IRSwaps.IRSwapValue import IRSwapValue

# Create MDP instance
curve_mdp = IRSwapsMDP(source="SDR_INTRADAY-rl_usd_sofr_mtv2_q12x11")
```

**What it does**: Initializes the Market Data Provider with specified curve source. The source string indicates:
- Data source (SDR_INTRADAY, CME_NY_EOD_LIVE, ERIS_EOD_LIVE)
- Pricing backend (rl = rateslib, ql = QuantLib)
- Curve specification details (usd_sofr_mtv2_q12x11)

### Section 2: Fetching Curves
```python
# Get curve at specific timestamp
curve_handle = curve_mdp._get_curve(curve_name="USD-SOFR-1D", timestamp=ts)

# Timestamp options:
# - "live": Current market data
# - datetime.date(2025, 9, 25): Specific date
# - datetime with timezone: Specific time
```

**What it does**: Retrieves a curve object containing all necessary pricing information for the given timestamp. The returned handle contains both the curve mathematics and metadata.

### Section 3: Pricing Instruments
```python
# Create a query for a 10Y outright swap
outright_query = IRSwapQuery(
    curve="USD-SOFR-1D",
    tenor="10Y",
    structure=IRSwapStructure.OUTRIGHT,
    structure_kwargs={"bpv": 1}
)

# Resolve the pricing package
pkg, rws = outright_query.resolve_package(pricer_or_curve=curve_handle)

# Build value map
vmap = outright_query.build_value_map(
    pricer_or_curve=curve_handle,
    package=pkg,
    risk_weights=rws
)

# Get various metrics
rate = vmap.apply(value=IRSwapValue.RATE)  # Swap rate in %
npv = vmap.apply(value=IRSwapValue.NPV)    # Net present value
```

**What it does**: 
1. Defines what instrument to price (10Y SOFR swap)
2. Creates the pricing objects from the curve
3. Calculates various metrics from the objects

### Section 4: Asset Swap Analysis
```python
# Price a bond as an asset swap vs IRS
# Example: August 2055 bond (4.75% coupon)

# Step 1: Define QuantLib bond
schedule_aug55s = ql.Schedule(...)
aug55s = ql.FixedRateBond(...)

# Step 2: Set evaluation date
ql.Settings.instance().evaluationDate = ql.Date(...)

# Step 3: Create asset swap
asset_swap = ql.AssetSwap(
    pay_fixed,
    aug55s,
    bond_price,
    index,  # SOFR index
    spread=0.0
)

# Step 4: Price using curve
asset_swap.setPricingEngine(ql.DiscountingSwapEngine(swap_curve))
fair_spread = asset_swap.fairSpread() * 10_000  # in bps
```

**What it does**: 
- Calculates the fair spread at which an investor would be indifferent between owning the bond and receiving SOFR
- Reveals relative value of bonds vs swaps

### Section 5: Intraday Data Collection
```python
# Collect minute-level data across trading day
nycloses = ql_cal_date_range(
    ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    start=NY_tz.localize(datetime.datetime(2025, 1, 1, 7, 0)),
    end=NY_tz.localize(datetime.datetime(2025, 3, 1, 17, 0)),
)

# For each business day, collect intraday data
for close in nycloses:
    intraday = pd.date_range(
        start=NY_tz.localize(datetime.datetime(close.year, ...)),
        end=NY_tz.localize(datetime.datetime(close.year, ...)),
        freq="1min"
    )
    
    # Get timeseries
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y")
    df = tb.get_timeseries(timestamps=intraday, queries=[q], n_jobs=12)
```

**What it does**: 
- Systematically collects high-frequency swap rate data
- Useful for studying intraday volatility and correlations
- Parallelized with n_jobs for efficiency

## Results and Insights

### Key Findings
1. **Asset Swap Spreads**: Show relative value between bonds and swaps
   - Negative spreads indicate bonds are cheap vs swaps
   - Can signal trading opportunities

2. **Curve Shapes**: Different curve sources may show slightly different structures
   - SDR intraday: Most granular, changes frequently
   - CME EOD: Stable, official pricing
   - ERIS EOD: SOFR-specific, latest SOFR fixings incorporated

3. **Rate Levels**: SOFR curve typically trading 50-100bps wider than Fed Funds

## Code Examples and Techniques Used

### Technique 1: Multi-Source Curve Comparison
```python
# Compare curves from different sources
sources = [
    "CME_NY_EOD_LIVE-ql_basic",
    "ERIS_EOD_LIVE-RL_BASIC",
    "SDR_INTRADAY-rl_usd_sofr_mtv2_q12x11"
]

curves = {}
for source in sources:
    mdp = IRSwapsMDP(source=source)
    curves[source] = mdp._get_curve("USD-SOFR-1D", timestamp="live")
```

### Technique 2: Batch Query Processing
```python
# Process multiple tenors efficiently
tenors = ["1Y", "2Y", "5Y", "10Y", "20Y", "30Y"]

for tenor in tenors:
    q = IRSwapQuery(curve="USD-SOFR-1D", tenor=tenor)
    pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
    rate = pkg[0].rate()
    print(f"{tenor}: {rate.real:.3f}%")
```

### Technique 3: Historical Curve Snapshots
```python
# Get curves from multiple historical dates
dates = [datetime.date(2025, 9, 20), datetime.date(2025, 9, 21)]

historical_curves = mdp.bulk_get_data(
    request={
        "curve_name": "USD-SOFR-1D",
        "timestamps": dates
    }
)
```

## Integration with ARBS Modules

### MDP Usage
- Provides `_get_curve()` method to fetch curve handles
- Supports multiple sources via source string parameter
- Handles caching and data refresh logic

### Query Layer Usage
- `IRSwapQuery` builds instrument definitions
- Query can be parametrized by:
  - `curve`: Curve name
  - `tenor`: Single tenor (e.g., "5Y")
  - `structure`: OUTRIGHT, CURVE, FLY
  - `value`: What metric to calculate
  - `structure_kwargs`: Risk levels (bpv parameter)

### Pricing Backends
- **QuantLib**: For structured instruments (asset swaps, bonds)
- **rateslib**: For curve building and swaps

## How to Run Each Notebook

1. **Setup**: Ensure MDP sources are configured in your environment
2. **Execute top-to-bottom**: Notebooks build on previous cells
3. **Modify parameters**: Change dates, tenors, risk levels as needed
4. **Visualize**: Use matplotlib/plotly for inspection

```bash
# Launch Jupyter in ARBS directory
cd /home/user/ARBS
jupyter notebook curve_builds.ipynb
```

## Dependencies and Prerequisites

### Python Libraries
```
pandas>=1.3.0
numpy>=1.20.0
QuantLib>=1.25
rateslib>=0.10
plotly>=5.0
matplotlib>=3.3
pytz
```

### ARBS Modules
- MDP.IRSwaps.IRSwapsMDP
- Query.IRSwaps.IRSwapQuery
- Query.IRSwaps.IRSwapStructure
- Query.IRSwaps.IRSwapValue
- TB.IRSwapsTB
- utils.ql_utils

### External Data
- Market data feeds (CME, ERIS, SDR)
- QuantLib holiday calendars
- Rate fixings database

## Outputs and Visualizations

### Key Outputs
1. **Curve handles**: Mathematical curve objects with pricing methods
2. **Instrument packages**: RL/QL objects ready for pricing
3. **Metrics**: Rates, NPVs, spreads, Greeks

### Visualizations
1. **Curve shapes**: Plot 1D forwards or spot term structure
2. **Historical curves**: Compare curves across time
3. **Asset swap spreads**: Show bond-swap relative value

---

# 2. timeseries_builder.ipynb

## Purpose and Learning Objectives

This notebook demonstrates how to build comprehensive historical timeseries for financial analysis. You will learn:

1. How to collect multi-day historical rate data
2. Combining multiple data products (swaps, bonds, futures)
3. Calculating derived metrics (spreads, volatility, seasonality)
4. Regression analysis for hedging
5. Visualizing financial time series

## Key Concepts Demonstrated

### Multi-Product Integration
- Combines swap curves (USD-SOFR-1D)
- Treasury cash (CT bonds)
- Implied spreads (MMSS - mid-market swap spreads)
- Realized volatility

### Spread Analysis
- **CT5/CT30 CURVE MMSS**: 5Y-30Y swap spread in basis points
- **CT5 OUTRIGHT MMSS**: 5Y absolute swap spread level
- **Yield to Maturity (YTM)**: Bond yield curves

### Statistical Analysis
- Realized volatility calculation over windows
- Carry and roll-down metrics
- Correlation analysis
- Seasonality patterns

## Data Sources and Requirements

### Data Sources
- **ERIS_EOD_LIVE**: End-of-day SOFR curve data
- **USTS_FEDINVEST_WSJ_LIVE**: US Treasury from WSJ via ERIS
- **SDR_INTRADAY**: Swap transaction data from ERIS

### Time Periods Covered
```python
# Typical analysis periods:
start = datetime.date(2025, 1, 1)
end = datetime.date(2025, 10, 24)
# 293 business days of data
```

## Step-by-Step Walkthrough

### Section 1: Initialization and Data Source Setup
```python
# Initialize timeseries builder with multiple products
tb = TimeseriesBuilder(
    irswaps_tb=IRSwapsTB(mdp=IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")),
    fixedratebonds_tb=FixedRateBondsTB(mdp=FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")),
)
```

**What it does**: Creates a unified interface for collecting swap and bond data across the period

### Section 2: Multi-Query Collection
```python
# Define queries for multiple instruments
df = tb.get_timeseries(
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 24),
    queries=[
        # Swap curves at different structures
        IRSwapQuery(curve="USD-SOFR-1D", tenor="CT5/CT30", value=IRSwapValue.MMSS),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="CT5", value=IRSwapValue.MMSS),
        IRSwapQuery(curve="USD-SOFR-1D", tenor="CT30", value=IRSwapValue.MMSS),
        
        # Bond yields
        FixedRateBondQuery(cusip="CT30", value=FixedRateBondValue.YTM),
        FixedRateBondQuery(cusip="CT5/CT30", value=FixedRateBondValue.YTM),
    ],
    n_jobs=1,  # Number of parallel jobs
)
# Returns: DataFrame with date index and metric columns
```

**What it does**:
- Collects daily observations for specified queries
- Builds unified DataFrame indexed by date
- Returns clean, aligned data for analysis

### Section 3: Spread Analysis
```python
# Calculate derived spreads
df["2s5s10s_fly"] = (
    (df["CT5"] - df["CT2"]) - 
    (df["CT10"] - df["CT5"])
) * 100  # Convert to basis points

# Plot time series
from RVUtils.plt_timeseries import make_secondary_axis_plot

plot, fig, ax, ax2, legend = make_secondary_axis_plot()
plot(
    df["CT5/CT30 CURVE MMSS"],
    which="left",
    indicators=[
        {"kind": "last", "show_date": True},
        {"kind": "simple_avg", "label": "Long-run mean"},
        {"kind": "vol", "returns": "normal", "window": 120},
    ],
)
legend(show_date=True)
plt.show()
```

**What it does**:
- Creates derived metrics from base series
- Applies technical indicators (moving averages, volatility)
- Produces publication-quality plots

### Section 4: Realized Volatility Analysis
```python
import gs_quant.timeseries.econometrics as gsqtse

# Calculate rolling realized volatility
rv = gsqtse.volatility(
    x=df["USD-SOFR-1D CT5/CT30 CURVE MMSS"],
    w=60,  # 60-day window
    returns_type=gsqtse.Returns.ABSOLUTE
)

# Plot vol timeseries
plot(rv[rv.index > datetime.date(2025, 1, 1)])
```

**What it does**:
- Computes rolling volatility
- Identifies periods of elevated/suppressed volatility
- Can be used for hedging or position sizing

### Section 5: Regression Analysis for Hedging
```python
from RVUtils.regression import make_linear_regression_builder

# Set up regression analysis
add_x, fit, plot_avp, plot_resid, plot_resid_ts, get_data = make_linear_regression_builder(
    df=df,
    y_col="USD-SOFR-1D CT5/CT30 CURVE MMSS",
    date_color_bar=True,
    on_diff=True,
    add_constant=True,
)

# Add x variables
add_x("USD-SOFR-1D CT30 OUTRIGHT MMSS")

# Fit OLS and TLS models
res = fit(model="OLS")
plot_avp()  # Plot actual vs predicted

# Advanced: Deming regression with error weighting
X_used, y_used, _ = get_data()
X_no_const = X_used.drop(columns=["const"], errors="ignore")

# Calculate variable volatilities
def rvol_abs(s, w=60):
    v = gsqtse.volatility(x=s, w=w, returns_type=gsqtse.Returns.ABSOLUTE)
    return v.reindex(y_used.index).bfill().clip(lower=1e-8)

sx = np.column_stack([rvol_abs(X_no_const[c]).values for c in X_no_const.columns])
sy = rvol_abs(y_used).values

# Fit Total Least Squares (accounts for errors in both x and y)
res_deming = fit(model="TLS", tls_x_errs=sx, tls_y_errs=sy, verbose=True)
plot_avp()
```

**What it does**:
- Quantifies linear relationship between spreads
- Provides hedging ratios
- Accounts for measurement error (Deming regression)

### Section 6: Seasonality Analysis
```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality

# Analyze month-end seasonality patterns
seasonality_df = monthend_cumsum_seasonality(
    df.dropna(),
    window=10  # 10 days before/after month-end
)

# Plot seasonality with confidence bands
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=seasonality_df.index,
    y=seasonality_df["avg-nov"],
    mode="lines",
    name="November Template"
))

# Add std bands
fig.add_trace(go.Scatter(
    x=seasonality_df.index,
    y=seasonality_df["avg-nov+std1"],
    mode="lines",
    line=dict(width=0),
    showlegend=False
))
```

**What it does**:
- Identifies recurring patterns around calendar dates
- Measures consistency and strength of seasonality
- Useful for mean-reversion strategies

## Results and Insights

### Typical Findings
1. **Volatility Clustering**: Volatility tends to spike after FOMC announcements
2. **Seasonality**: Month-end often shows directional patterns
3. **Correlations**: Longer-dated spreads less correlated with daily moves
4. **Carry/Roll**: Systematic returns from carry and roll-down in curve structures

## Code Examples and Techniques Used

### Technique: Efficient Data Collection
```python
# Collect data in parallel
df = tb.get_timeseries(
    start=date_start,
    end=date_end,
    queries=query_list,
    n_jobs=8,  # 8 parallel workers
)
```

### Technique: Interpolation and Curve Fitting
```python
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator

# Fit smooth curve to scattered points
ttm = [1, 2, 3, 5, 7, 10, 20, 30]  # Time to maturity
ytm = [3.5, 3.6, 3.7, 3.8, 3.9, 4.0, 4.1, 4.2]

# B-spline interpolation
ytm_spline = GeneralCurveInterpolator(
    x=ttm,
    y=ytm
).b_spline_with_knots_interpolation(
    knots=[2, 3, 5, 7, 10, 20],
    k=3,
    return_func=True
)

# LOESS smoothing
ytm_loess = GeneralCurveInterpolator(
    x=ttm,
    y=ytm
).loess_interpolation(frac=0.15, it=50, return_func=True)
```

## Integration with ARBS Modules

### TimeseriesBuilder
- Central interface for multi-product data collection
- Handles alignment and synchronization
- Returns clean DataFrames

### IRSwapsTB and FixedRateBondsTB
- Specialized builders for each product
- Can be used independently

### RVUtils
- Statistical utilities for analysis
- Visualization helpers
- Regression builders

## How to Run

```bash
# Basic execution:
# 1. Modify start/end dates as needed
# 2. Run cells sequentially
# 3. Adjust n_jobs based on your CPU cores
# 4. Plots display inline in Jupyter

# For faster runs with cached data:
df = tb.get_timeseries(..., ignore_cache=False)
```

## Dependencies and Prerequisites

### Key Libraries
- pandas, numpy
- gs-quant (for econometric functions)
- plotly (for interactive charts)
- scikit-learn (implied by regression utilities)

### ARBS Dependencies
- TB.TimeseriesBuilder
- TB.IRSwapsTB, TB.FixedRateBondsTB
- Query.IRSwaps.IRSwapQuery, Query.FixedRateBonds.FixedRateBondQuery
- RVUtils.regression, RVUtils.seasonality_utils

## Outputs and Visualizations

### Primary Outputs
1. **Timeseries DataFrame**: Historical rates and spreads
2. **Regression Results**: Coefficients, R², residuals
3. **Seasonality Analysis**: Month-end patterns with confidence bands

### Key Visualizations
- Time series plots with multiple indicators
- Actual vs predicted (regression)
- Residual diagnostics
- Seasonality heatmaps

---

# 3. sfr_cvx.ipynb

## Purpose and Learning Objectives

This notebook focuses on analyzing STIR (Short-Term Interest Rate) futures convexity adjustments. You will learn:

1. How to price STIR futures (3-month contracts: Z25, H26, etc.)
2. Calculate convexity adjustments
3. Understand basis point value calculations
4. Risk decomposition across the curve

## Key Concepts Demonstrated

### STIR Futures Basics
- IMM codes: Z25 (December 2025), H26 (March 2026), M26 (June 2026)
- 3-month SOFR futures with $25 per basis point contract
- Contract specifications and pricing mechanics

### Convexity Adjustment
- The difference between forward rates and futures rates
- Due to daily mark-to-market of futures contracts
- Becomes important for pricing OIS swaps off curves with futures

## Data Sources and Requirements

### Data Sources
- **SOFR Fixings**: Historical SOFR rates
- **Futures Prices**: From barchart.com (WebullFintechFetcher)
- **Curves**: SOFR OIS curves for valuation

## Step-by-Step Walkthrough

### Section 1: Curve Setup
```python
# Get SOFR curve for CVX calculations
curve_mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-rl_basic")
curve_handle = curve_mdp._get_curve(curve_name="USD-SOFR-1D", timestamp="live")
```

### Section 2: STIR Futures Collection
```python
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import fetch_stir_market_data

# Fetch multiple STIR futures contracts
_, sfrs, _ = fetch_stir_market_data(
    curve_name="USD-SOFR-1D",
    snap_local="live",
    fixings=None,
    side="mid",
    include_serff=False,
    n_ser_contracts=0,  # SER contracts
    n_sfr_contracts=24,  # SFR contracts (SOFR futures)
    use_globex=False
)

# Returns dict like:
# sfrs = {
#     "SFR1": rl.STIRFuture(...),
#     "SFR2": rl.STIRFuture(...),
#     ...
# }
```

### Section 3: Convexity Adjustment Calculation
```python
# Query for SOFR swap with explicit CVX_ADJ value
outright_query = IRSwapQuery(
    curve="USD-SOFR-1D",
    effective_date=rl.get_imm(code="Z25").date(),
    maturity_date=rl.next_imm(rl.get_imm(code="Z25")).date(),
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.CVX_ADJ,
    structure_kwargs={"bpv": 1}
)

# Get package and value map
outright_pkg, outright_rws = outright_query.resolve_package(pricer_or_curve=curve_handle)
outright_vmap = outright_query.build_value_map(
    pricer_or_curve=curve_handle,
    package=outright_pkg,
    risk_weights=outright_rws
)

# Calculate CVX adjustment
cvx_adj_bps = outright_vmap.apply(
    value=IRSwapValue.CVX_ADJ,
    **{"sfr": [sfrs[f"SFR{imm_start}"]]}
)

print(f"CVX Adjustment: {cvx_adj_bps} bps")
```

### Section 4: Historical CVX Tracking
```python
# Build timeseries of CVX adjustments
sfr_cvx_df = tb.sfr_cvx_adj(
    items=["sfr8", "sfr12"],  # Which SFR contracts
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 10),
)

# Returns DataFrame with columns like:
# "USD-SOFR-1D SFR8 OUTRIGHT CVX_ADJ"
# "USD-SOFR-1D SFR12 OUTRIGHT CVX_ADJ"

# Visualize
plot, fig, ax, ax2, legend = make_secondary_axis_plot_v2(title="SFR CVX ADJ")
plot(sfr_cvx_df["USD-SOFR-1D SFR8 OUTRIGHT CVX_ADJ"])
```

## Results and Insights

### Typical CVX Levels
- **Early contracts**: 1-2 bps of CVX (daily mark-to-market cost)
- **Distant contracts**: 3-5 bps (compounding of rate uncertainty)
- **Reflects**: Market expectations of rate volatility and curve shape

### Risk Insights
- CVX changes with:
  - Volatility expectations
  - Curve shape (steeper curves = higher CVX)
  - Time horizon (longer = more CVX)

## Dependencies and Prerequisites

### Key Modules
- MDP.IRSwaps.IRSwapsMDP
- TB.IRSwapsTB
- Query.IRSwaps values with CVX_ADJ support
- rateslib for STIR futures
- WebullFintechFetcher for futures prices

## Outputs and Visualizations

### Outputs
- CVX adjustment values (in basis points)
- Time series of CVX across contracts
- Risk decomposition across portfolio

---

# 4. intraday_swaps.ipynb

## Purpose and Learning Objectives

This notebook demonstrates high-frequency rate data collection and analysis. Learn:

1. How to structure queries for minute-level data
2. Handling timezone-aware timestamps
3. Parallelized data collection across trading days
4. Analyzing intraday rate movements

## Key Concepts

### Intraday Data Collection
- Minute-level precision
- Timezone handling (NY_tz for US rates)
- Business day filtering using QuantLib calendars
- Parallelization for speed

### Data Organization
- Timestamps: 7:00 AM to 5:00 PM NY time typical
- Frequency: Every 1 minute
- Calendar: US Government Bond calendar

## Data Sources and Requirements

### Data Sources
- **SDR_INTRADAY**: Minute-level swap transaction data
- **US Business Days**: Government Bond calendar

## Step-by-Step Walkthrough

### Section 1: Setup for Intraday Collection
```python
# Initialize builder for intraday data
tb = IRSwapsTB(mdp=IRSwapsMDP(source="SDR_INTRADAY-rl_usd_sofr_mtv2_q12x11"))

# Helper function for calendar-aware date ranges
def ql_cal_date_range(ql_cal, start, end):
    """Generate business days within range"""
    assert start.tzinfo is not None, "must be tz aware!"
    
    pd_range = pd.date_range(start=start, end=end, freq="1b")
    return [d for d in pd_range 
            if ql_cal.isBusinessDay(ql.Date(d.day, d.month, d.year))]
```

### Section 2: Generate Intraday Timestamps
```python
# Create list of business days
nycloses = ql_cal_date_range(
    ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    start=NY_tz.localize(datetime.datetime(2025, 1, 1, 7, 0)),
    end=NY_tz.localize(datetime.datetime(2025, 3, 1, 17, 0)),
)

# For each day, create minute-level timestamps
all_intraday_timestamps = []
for close_date in nycloses:
    intraday = pd.date_range(
        start=NY_tz.localize(datetime.datetime(close_date.year, close_date.month, close_date.day, 7, 0)),
        end=NY_tz.localize(datetime.datetime(close_date.year, close_date.month, close_date.day, 17, 0)),
        freq="1min"
    )
    all_intraday_timestamps.extend(intraday)
```

### Section 3: Collect Intraday Data
```python
# Query definition
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="5Y")

# Collect data for all timestamps
df = tb.get_timeseries(
    start=None,  # Don't filter by start/end
    end=None,
    timestamps=all_intraday_timestamps,
    queries=[q],
    n_jobs=12  # 12 parallel workers
)

# Result: DataFrame with intraday rate observations
# Index: minute-level timestamps
# Columns: rates for each query
```

### Section 4: Intraday Analysis
```python
# Plot rate movements throughout day
plt.plot(df.index, df[q.col_name()])
plt.title(f"Intraday {q.col_name()}")
plt.show()

# Calculate intraday volatility
intraday_vol = df[q.col_name()].std()
print(f"Intraday volatility: {intraday_vol:.3f} bps")

# Identify peak hours
hourly = df.groupby(df.index.hour)[q.col_name()].std()
print(hourly)  # Volatility by hour
```

## Results and Insights

### Typical Findings
- **Morning**: Higher volatility (8-10 AM)
- **European Close**: Rate spike/drop (3-4 PM NY)
- **New York Close**: Final fixing (4-5 PM NY)
- **Bid-Ask**: Changes throughout day

## Dependencies and Prerequisites

### Key Modules
- TB.IRSwapsTB
- QuantLib calendars
- pytz for timezone handling

---

# 5. usts_rv.ipynb

## Purpose and Learning Objectives

Comprehensive US Treasury analysis including:

1. Multi-source Treasury curve construction
2. Curve comparison and evolution
3. Realized volatility tracking
4. Seasonality patterns in treasuries
5. Visualization of complex curve structures

## Key Concepts

### Treasury Data Sources
- **WSJ/ERIS**: Daily treasury yields
- **WebullFintechFetcher**: Treasury futures
- **Custom aliases**: CT2, CT5, CT10, CT30 for on-the-run treasuries

### Curve Analysis
- Curve shape evolution
- Spread dynamics
- Auction impact analysis
- Fly spreads (2Y-5Y-10Y, 5Y-10Y-30Y, etc.)

## Data Sources and Requirements

### Data Sources
- **USTS_WEBULL_WSJ_LIVE**: Via rateslib
- **USTS_FEDINVEST_WSJ_LIVE**: Via QuantLib
- **Futures**: TU, FV, TY, UXY, UB from WebullFintechFetcher

### Treasury Aliases
```
CT1, CT2, CT3, CT5, CT7, CT10, CT20, CT30
o2, o5, o10, o20, o30  (off-the-runs)
oo2, oo5, oo10, oo20, oo30  (further off-the-runs)
```

## Step-by-Step Walkthrough

### Section 1: Initialize Data Sources
```python
usts_mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
usts_tb = FixedRateBondsTB(usts_mdp)

swaps_mdp = IRSwapsMDP(source="SDR_INTRADAY_RL_USD_SOFR_MTV2_Q12X11")
swaps_tb = IRSwapsTB(swaps_mdp)
```

### Section 2: Intraday Treasury Collection
```python
# Generate minute-level timestamps for specific date
start = NY_tz.localize(datetime.datetime(2025, 10, 24, 7, 0))
end = NY_tz.localize(datetime.datetime(2025, 10, 24, 15, 0))

ts_range = ql_cal_date_range(
    ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    start=start,
    end=end,
    freq="1min"
)

# Collect bond data
usts_df = usts_tb.get_timeseries(
    start=None,
    end=None,
    timestamps=ts_range,
    queries=[
        FixedRateBondQuery(cusip="CT5/CT30"),
        # Additional queries...
    ],
)
```

### Section 3: Treasury Futures Integration
```python
from MDP.FixedRateBonds.WEBULL.WebullFintechFetcher import WebullFintechFetcher

# Fetch UST futures
ustf_df = WebullFintechFetcher(debug_verbose=True).eod_by_tickers(
    ["TU", "FV", "TY", "UXY", "UB"],
    start=datetime.date(2025, 1, 1),
    end=datetime.date(2025, 10, 24),
    one_df=True
)

# Build spread strategies
ustf_df["TUL"] = 5 * ustf_df["TU"] - ustf_df["UXY"]  # 5y-10y ladder
ustf_df["TUF"] = 12 * ustf_df["TU"] - 10 * ustf_df["FV"]  # Fly
```

### Section 4: Bond Reference Data Analysis
```python
# Get current issuance data
ref_df = usts_mdp.get_bond_reference_data(
    as_of_date=datetime.date(2025, 10, 24),
    kwargs={"append_free_float": True}
).drop(columns=["record_date"])

# Filter for liquid securities
ref_df = ref_df[ref_df["ttm"] >= 1]

# Get current prices
cusip_pricers = usts_mdp.get_pricer(
    request=dict(
        cusips=ref_df["cusip"].to_list(),
        timestamp="live",
        show_tqdm=True
    )
)

# Build market analytics
market_df = pd.DataFrame([
    {"cusip": c, "ytm": p.ytm()}
    for c, p in cusip_pricers.items()
])
```

### Section 5: Curve Interpolation
```python
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator

# Fit curves to scattered bond data
clean_df = market_df.dropna(subset=["ttm", "ytm"])

# B-spline fit
ytm_bspline = GeneralCurveInterpolator(
    x=clean_df["ttm"],
    y=clean_df["ytm"]
).b_spline_with_knots_interpolation(
    knots=[2, 3, 5, 7, 10, 20, 25],
    k=3,
    return_func=True
)

# LOESS smooth
ytm_loess = GeneralCurveInterpolator(
    x=clean_df["ttm"],
    y=clean_df["ytm"]
).loess_interpolation(frac=0.15, it=50, return_func=True)

# Evaluate at standard tenors
standard_ttm = [1, 2, 3, 5, 7, 10, 20, 30]
fitted_yields = [ytm_bspline(t) for t in standard_ttm]
```

### Section 6: Visualization and Comparison
```python
from RVUtils.ust_viz import plot_usts, plot_usts_comparison

# Plot current curve with spline
plot_usts(
    curve_set_df=market_df,
    ttm_col="ttm",
    ytm_col="ytm",
    label_col="oi",
    cusip_col="cusip",
    splines=[
        (ytm_loess, "LOESS Spline"),
        (ytm_bspline, "BSpline", "red")
    ],
    title=f"Cash Treasuries: {pricer.meta()['timestamp']}"
)

# Compare two dates
older_date = datetime.date(2025, 10, 17)
newer_date = datetime.date(2025, 10, 24)

# ... collect data for both dates ...

fig = plot_usts_comparison(
    curve_set_df=old_market_df,
    ...,
    opacity=0.5,
    name_suffix=str(older_date),
    show=False,
    return_color_map=True
)

fig = plot_usts_comparison(
    curve_set_df=new_market_df,
    ...,
    fig=fig,  # Add to existing
    opacity=1.0,
    name_suffix=str(newer_date),
    color_discrete_map=cmap
)
```

### Section 7: Seasonality Analysis
```python
seasonality_df = monthend_cumsum_seasonality(
    df.dropna(),
    window=25  # Days around month-end
)

# Visualize with month comparisons
fig = go.Figure()

# Add average template
fig.add_trace(go.Scatter(
    x=seasonality_df.index,
    y=seasonality_df["avg-nov"],
    mode="lines",
    name="November Template"
))

# Add historical months
for month in ["2024-11", "2023-11", "2022-11"]:
    fig.add_trace(go.Scatter(
        x=seasonality_df.index,
        y=seasonality_df[month],
        mode="lines",
        name=month
    ))
```

## Results and Insights

### Curve Observations
1. **Shape**: Usually upward sloping, occasionally inverted
2. **Steepness**: Reflects expectations of future policy
3. **Levels**: Follow Fed policy and inflation expectations

### Spread Dynamics
- 2s10s: Policy-sensitive, mean-reverts to ~100bps
- 5s30s: Less sensitive to short-term policy
- Fly spreads: Often mean-revert

## Integration with ARBS Modules

### FixedRateBondsMDP
- Provides bond pricing
- Manages reference data
- Handles multiple sources

### FixedRateBondsTB
- Collects historical bond data
- Manages queries

## Dependencies and Prerequisites

### Key Libraries
- rateslib (treasury pricing)
- QuantLib (legacy support)
- plotly (visualization)
- gs_quant (volatility calculations)

---

# 6. fomc_pricer.ipynb

## Purpose and Learning Objectives

Focus on pricing instruments around FOMC (Federal Open Market Committee) meeting dates:

1. Identify FOMC meeting dates automatically
2. Price OIS swaps between specific FOMC dates
3. Calculate expected policy rate moves
4. Risk decomposition using basis functions
5. Term structure of expectations

## Key Concepts

### FOMC-Dated OIS Swaps
- OIS swap that starts at one FOMC meeting, ends at next
- Rates reflect market expectations for average Fed Funds rate between meetings
- Narrower spreads = higher confidence in expectations

### Central Bank Dates
```python
from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

# Access FOMC meeting dates
fomc_dates = _CENTRAL_BANK_DATES["USD-FEDFUNDS"]
# Returns: {
#     "sep25": (datetime(2025, 9, 17), datetime(2025, 10, 29)),
#     "oct25": (datetime(2025, 10, 29), datetime(2025, 12, 10)),
#     ...
# }
```

## Data Sources and Requirements

### Data Sources
- **OIS Curves**: USD-FEDFUNDS curve from IRSwapsMDP
- **Meeting Dates**: Hard-coded in _CENTRAL_BANK_DATES

## Step-by-Step Walkthrough

### Section 1: Fetch OIS Curve
```python
# Choose OIS curve (not SOFR - different for FOMC dates)
stir_curve_mdp = IRSwapsMDP(source="SDR_INTRADAY-rl_usd_ois_stir_q12x12")
curve = "USD-FEDFUNDS"

live_curve = stir_curve_mdp._get_curve(
    curve_name=curve,
    timestamp="live"
)
```

### Section 2: Define FOMC-Dated OIS Swaps
```python
# FOMC meeting dates
fomc_dated_ois = {
    "oct25": (rl.dt(2025, 10, 29), rl.dt(2025, 12, 10)),
    "dec25": (rl.dt(2025, 12, 10), rl.dt(2026, 1, 28)),
    "jan26": (rl.dt(2026, 1, 28), rl.dt(2026, 3, 18)),
    # ... more meetings ...
}

def rl_fomc_swap(meeting, risk=None, notional=None, rl_irs_swap_kargs={}):
    """Create IRS between FOMC dates with specified risk"""
    assert risk is not None or notional is not None
    
    if risk is not None:
        # Calculate unit delta
        unit_delta = rl.IRS(
            effective=fomc_dated_ois[meeting][0],
            termination=fomc_dated_ois[meeting][1],
            spec="usd_irs_lt_2y",
            curves=live_curve.handle(),
            notional=1
        ).analytic_delta(live_curve.handle())
        
        notional = risk / unit_delta
    
    # Create IRS
    fomc_swap = rl.IRS(
        effective=fomc_dated_ois[meeting][0],
        termination=fomc_dated_ois[meeting][1],
        spec="usd_irs_lt_2y",
        curves=live_curve.handle(),
        notional=notional,
        **rl_irs_swap_kargs
    )
    return fomc_swap
```

### Section 3: Price FOMC Swaps
```python
# Price swaps between meetings
mid = 4.08  # Market mid level

for meeting in fomc_dated_ois.keys():
    fomc_swap = rl_fomc_swap(meeting=meeting, risk=1)
    rate = fomc_swap.rate().real
    carry_to_mid = (mid - rate) * 100  # Carry in bps
    print(f"{meeting}: {rate:.3f}, carry to mid: {carry_to_mid:.1f} bps")

# Output example:
# oct25, 3.889, 19.070 bps
# dec25, 3.718, 36.162 bps
# jan26, 3.620, 45.970 bps
```

### Section 4: Risk Decomposition
```python
# Define risk instruments for sensitivity analysis
# STIR futures
stir_imms = ["Z25", "H26", "M26", "U26", "Z26", "H27", "M27", "U27"]
stir_futures = {
    imm: rl.STIRFuture(
        effective=rl.scheduling.get_imm(code=imm),
        termination=rl.scheduling.next_imm(rl.scheduling.get_imm(code=imm)),
        spec="usd_stir",
        curves=live_curve.handle()
    )
    for imm in stir_imms
}

# OIS swaps
ois_tenors = ["3M", "6M", "1Y", "2Y"]
ois_swaps = {}
for tenor in ois_tenors:
    q = IRSwapQuery(curve=curve, tenor=tenor)
    pkg, _ = q.resolve_package(pricer_or_curve=live_curve)
    ois_swaps[tenor] = pkg[0]

# Create solver for risk analysis
rl_risk_instruments = stir_futures | ois_swaps
rl_risk_solver = rl.Solver(
    curves=[live_curve.handle()],
    instruments=rl_risk_instruments.values(),
    instrument_labels=rl_risk_instruments.keys(),
    s=[r.rate().real for r in rl_risk_instruments.values()],
    id=live_curve.id(),
    func_tol=1e-8,
    conv_tol=1e-10,
)
```

### Section 5: Portfolio Risk Analysis
```python
# Create a trade combining multiple FOMC swaps
z5z6 = rl.Portfolio([
    rl_fomc_swap(meeting="oct25", risk=-50_000),
    rl_fomc_swap(meeting="dec25", risk=100_000),
    rl_fomc_swap(meeting="jan26", risk=-50_000),
])

# Get delta across risk instruments
risk_table = z5z6.delta(solver=rl_risk_solver)
print(risk_table.style.format("{:_.0f}"))

# Shows exposure to each STIR contract and OIS tenor
```

## Results and Insights

### Typical Findings
- **Rate Curve**: Downward sloping between meetings (reflecting expected easing)
- **Carry**: Steeper curves = more carry to mid
- **Volatility**: Shorter-dated swaps more volatile
- **Risk Profile**: Exposure concentrated in nearest meetings

## Dependencies and Prerequisites

### Key Modules
- IRSwapsMDP (OIS curves)
- Query.IRSwaps._CENTRAL_BANK_DATES
- rateslib for OIS pricing

---

# 7. medium_term_swap_pricer.ipynb

## Purpose and Learning Objectives

Demonstrate building curves from multiple data sources and pricing medium-term swaps:

1. Integrate STIR futures with longer-dated instruments
2. Build forward rate curves
3. Price medium-term swaps (5Y, 10Y+)
4. Risk analysis for complex curves

## Key Concepts

### Multi-Instrument Curve Building
- Combines STIR futures (short-term)
- OIS swaps (medium-term)
- Longer swaps for calibration

### Spot Term Structure
- Forward rates at key tenors
- Interpolation between futures and swaps

## Step-by-Step Walkthrough

### Section 1: Curve Construction
```python
# Fetch intraday SOFR curve
curve_mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-rl_basic")
curve_handle = curve_mdp._get_curve(curve_name="USD-SOFR-1D", timestamp="live")
```

### Section 2: Risk Basis Functions
```python
# Define basis functions for risk decomposition
imms = ["Z25", "H26", "M26", "U26", "Z26", "H27", "M27", "U27"]
sfrs = {
    imm: rl.STIRFuture(
        effective=rl.scheduling.get_imm(code=imm),
        termination=rl.scheduling.next_imm(rl.scheduling.get_imm(code=imm)),
        spec="usd_stir",
        curves=curve_handle.handle()
    )
    for imm in imms
}

# Medium-term swaps
mt_tenors = ["5Y", "7Y", "10Y", "20Y", "30Y"]
mt_irs = {
    t: rl.IRS(...)
    for t in mt_tenors
}

# Risk solver
rl_risk_solver = rl.Solver(
    curves=[curve_handle.handle()],
    instruments=list(sfrs.values()) + list(mt_irs.values()),
    instrument_labels=list(sfrs.keys()) + mt_tenors,
    s=[...],  # Market rates
    id=curve_handle.id(),
)
```

### Section 3: Price Instruments
```python
# Price medium-term swap
q = IRSwapQuery(curve="USD-SOFR-1D", tenor="10Y")
pkg, rws = q.resolve_package(pricer_or_curve=curve_handle)

# Get metrics
rate = pkg[0].rate()
pv01 = pkg[0].fixedLegBPS()

# Risk vector
risk_vector = rl.Portfolio(pkg).delta(solver=rl_risk_solver)
```

## Dependencies and Prerequisites

### Key Modules
- IRSwapsMDP
- IRSwapQuery
- rateslib

---

# 8. month_end_irswaps_backtest.ipynb

## Purpose and Learning Objectives

Backtest a seasonality-based trading strategy exploiting month-end patterns:

1. Identify month-end seasonality effects
2. Automate trade entry based on calendar
3. Build backtesting infrastructure
4. Measure strategy performance

## Key Concepts

### Month-End Seasonality
- Observation: Certain spreads behave predictably around month-end
- Entry: 3 business days before month-end
- Exit: 3 business days after month-end
- Instrument: Fly spreads (e.g., 1Y x 2Y x 3Y fwd-starts)

### Backtesting Framework
- TimeGrid: Calendar of business days
- Triggers: Date-based entry/exit signals
- Actions: Add/unwind trades
- MtM tracking: Daily mark-to-market

## Step-by-Step Walkthrough

### Section 1: Define Trading Calendar
```python
import QuantLib as ql
from BT.misc import (
    ql_cal_date_range,
    _month_iter,
    _last_business_day_of_month,
    _n_business_days_before,
    _nth_business_day_of_month,
)

# Use government bond calendar
CAL = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

# Define seasonality window
days_pre_month_end = 3
days_after_month_end = 3

# Generate trading cycles
cycles = []
for y, m in _month_iter(start, end):
    eom_bd = _last_business_day_of_month(CAL, y, m)
    entry = _n_business_days_before(CAL, eom_bd, days_pre_month_end)
    
    # Exit in next month
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    exit_ = _nth_business_day_of_month(CAL, ny, nm, days_after_month_end)
    
    if entry >= start and exit_ <= end:
        tag = f"me-trade-{y:04d}{m:02d}"
        cycles.append((entry, exit_, tag))
```

### Section 2: Define Triggers
```python
from BT.triggers import DateTrigger, DateTriggerRequirements
from BT.query_actions import AddQueryAction, UnwindPositionsAction

triggers = []
for entry_date, exit_date, tag in cycles:
    # Entry: Create fly position
    q = IRSwapQuery(
        structure=IRSwapStructure.FLY,
        value=IRSwapValue.NPV,
        curve="USD-SOFR-1D",
        structure_kwargs={
            "front_tenor": "1Yx2Y",
            "belly_tenor": "1Yx5Y",
            "back_tenor": "1Yx10Y",
            "bpv": -100_000
        },
        tags=(tag,),  # Tag for tracking
    )
    
    enter = DateTrigger(
        DateTriggerRequirements(dates=[entry_date]),
        actions=[AddQueryAction(query=q)]
    )
    
    # Exit: Unwind position
    exit_ = DateTrigger(
        DateTriggerRequirements(dates=[exit_date]),
        actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]
    )
    
    triggers.extend([enter, exit_])
```

### Section 3: Run Backtest
```python
from BT.data_handler import TimeGrid
from BT.query_strategy import QueryStrategy
from BT.query_engine import QueryDrivenBacktest

# Create time grid for backtest period
tg = TimeGrid(
    ql_cal_date_range(
        ql_cal=CAL,
        start=min(d for d, _, _ in cycles),
        end=max(e for _, e, _ in cycles),
    )
)

# Create strategy
strategy = QueryStrategy(
    name="Month End Seasonality Backtest",
    triggers=triggers
)

# Run backtest
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)
bt.run()
```

### Section 4: Analyze Results
```python
# Extract MtM history
mtm = pd.Series(bt.mtm_history).sort_index()
final_pnl = float(mtm.iloc[-1])
print(f"Final MtM: {final_pnl:,.0f}")

# Plot
plt.figure()
plt.plot(mtm.index, mtm.values, label="MtM PnL")
plt.axhline(y=0, color='r', linestyle='--')
plt.legend()
plt.title(f"Month-End Fly: {risk_bpv}/bp | Entry EOM-{days_pre}BD | Exit EOM+{days_after}BD")
plt.show()

# Statistics
print(f"Max Drawdown: {mtm.min():,.0f}")
print(f"Sharpe Ratio: {mtm.mean() / mtm.std():,.2f}")
print(f"Win Rate: {(mtm > 0).sum() / len(mtm) * 100:.1f}%")
```

## Results and Insights

### Typical Findings
- **Positive Carry**: Month-end flywrit positive carry
- **Risk**: Fly basis can move significantly
- **Seasonality**: Effect varies month-to-month
- **Profitability**: Depends on market regime

## Dependencies and Prerequisites

### Key Modules
- BT.data_handler.TimeGrid
- BT.triggers, BT.query_actions
- BT.query_engine.QueryDrivenBacktest
- BT.query_strategy.QueryStrategy
- BT.misc (calendar utilities)

---

# 9. curve_risk_model.ipynb

## Purpose and Learning Objectives

Implement a comprehensive curve risk model for portfolio Greeks:

1. Build basis functions spanning the curve
2. Calculate key rate durations
3. Decompose portfolio risk
4. Analyze cross-curve sensitivities

## Key Concepts

### Risk Basis Functions
- Overnight forwards (1D)
- Short-term instruments (STIR futures)
- Medium-term (OIS swaps, IRS)
- Long-term (30Y swaps)

### Greeks Computed
- Delta: Sensitivity to parallel shifts
- Key Rate Durations: Sensitivity to specific points
- Gamma: Convexity risk
- Vega: Volatility risk (for swaptions)

## Step-by-Step Walkthrough

### Section 1: Setup Solver
```python
# Fetch curve
curve_mdp = IRSwapsMDP(source="ERIS_EOD_LIVE-RL_BASIC")
curve_handle = curve_mdp._get_curve(curve_name="USD-SOFR-1D", timestamp=date)

# Define instruments
instruments = {}

# STIR futures
for imm in imms:
    instruments[imm] = rl.STIRFuture(...)

# Spot swaps
for tenor in ["1Y", "2Y", "5Y", "10Y", "30Y"]:
    instruments[tenor] = rl.IRS(...)

# Create solver
solver = rl.Solver(
    curves=[curve_handle.handle()],
    instruments=instruments.values(),
    instrument_labels=instruments.keys(),
    s=[r.rate().real for r in instruments.values()],
    id=curve_handle.id(),
)
```

### Section 2: Calculate Portfolio Greeks
```python
# Create portfolio
portfolio = rl.Portfolio(portfolio_trades)

# Get deltas across all basis functions
risk_vector = portfolio.delta(solver=solver)
# Returns sensitivity to each basis instrument

# For more details on specific Greeks:
# risk_vector.loc["5Y"]  # Key rate duration to 5Y
```

### Section 3: Risk Reporting
```python
# Display risk
print(risk_vector.style.format("{:_.0f}"))

# Aggregate risk
total_delta = risk_vector.sum()
print(f"Total Delta: {total_delta:,.0f}")

# Find largest exposures
largest_risks = risk_vector.abs().nlargest(5)
print("Largest 5 exposures:")
print(largest_risks)
```

## Dependencies and Prerequisites

### Key Modules
- rateslib Solver
- IRSwapsMDP

---

# 10. simple_irswaps_backtest.ipynb

## Purpose and Learning Objectives

Basic backtesting framework for swap strategies:

1. Simple position tracking
2. Mark-to-market valuation
3. Trade entry/exit mechanics
4. Performance visualization

## Key Concepts

### Simple Backtest Flow
1. Start with empty portfolio
2. Enter trade on specific date
3. Track daily MtM
4. Exit on specified date
5. Plot PnL

## Step-by-Step Walkthrough

### Section 1: Define Trade
```python
trade_date = datetime.date(2025, 4, 2)

query = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    value=IRSwapValue.NPV,
    curve="USD-SOFR-1D",
    tenor="10Y",
    structure_kwargs={"bpv": 100_000},
)
```

### Section 2: Setup Backtest
```python
# Create trigger for entry
entry = DateTrigger(
    DateTriggerRequirements(dates=[trade_date]),
    actions=[AddQueryAction(query=query)]
)

# Create time grid
tg = TimeGrid(
    ql_cal_date_range(
        ql_cal=CAL,
        start=trade_date,
        end=datetime.date(2025, 10, 2),
    )
)

# Run backtest
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-ql_basic")
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp)
bt.run()
```

### Section 3: Analyze Results
```python
mtm = pd.Series(bt.mtm_history).sort_index()

plt.figure()
plt.plot(mtm.index, mtm.values)
plt.title(f"Backtest: {query.col_name()} | Entry: {trade_date}")
plt.show()
```

## Dependencies and Prerequisites

Same as month_end_irswaps_backtest.ipynb

---

# 11. fomc_fly_backtest.ipynb

## Purpose and Learning Objectives

Sophisticated backtesting with dynamic signals and FOMC awareness:

1. Detect FOMC meetings automatically
2. Generate carry signals
3. Dynamic entry/exit logic
4. Complex spread trading

## Key Concepts

### FOMC-Aware Trading
- Trade FOMC fly spreads
- Entry: When carry signal positive
- Exit: Either pre-FOMC or carry flips negative

### Carry Signal
- 2Y x 5Y x 10Y fly
- Calculate 3-month carry
- Long positive carry

## Step-by-Step Walkthrough

### Section 1: Setup
```python
bpv_per_trade = 100_000
horizon_period = "3m"  # 3-month carry horizon
fomc_fly = [1, 2, 3]  # FOMC meetings to use

start = datetime.date(2025, 1, 1)
end = datetime.date(2025, 10, 21)
```

### Section 2: Generate Carry Signals
```python
# Calculate historical carry
def compute_carry(bt, now):
    q_carry = IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve="USD-SOFR-1D",
        structure_kwargs={
            "front_tenor": "2Y",
            "belly_tenor": "5Y",
            "back_tenor": "10Y",
            "bpv": -100_000
        }
    )
    
    pricer_or_curve = bt._pricer_for_query(q_carry, now)
    pkg, rws = q_carry.resolve_package(pricer_or_curve=pricer_or_curve)
    vmap = q_carry.build_value_map(...)
    
    carry = vmap.apply(
        value=IRSwapValue.CARRY_BPS_RUNNING,
        **{"horizon": "3m"}
    )
    return carry

# Map carry over time
carry_map = {}
for d in daily:
    c = compute_carry(bt_boot, d)
    if c is not None:
        carry_map[d] = c
```

### Section 3: Create Episodes
```python
# Find periods where carry > 0
episodes = []
in_pos = False

for d in daily:
    sig = carry_map.get(d, float("nan")) > 0
    
    if (not in_pos) and sig:
        lbls = resolve_fomc_fly(d, fomc_fly, labels=True)
        if lbls is None:
            continue
        
        # Entry date
        entry_d = d
        
        # Exit: Min of pre-expiry or carry flip
        pre_expiry = pre_expiry_date(lbls[0])
        carry_flip = first_non_positive_after(d)
        
        exit_d = min([x for x in (pre_expiry, carry_flip) if x > d])
        
        episodes.append((entry_d, exit_d, tag))
        in_pos = True
```

### Section 4: Run Backtest
```python
# Create triggers from episodes
triggers = []
for entry_date, exit_date, tag in episodes:
    fly = resolve_fomc_fly(entry_date, fomc_fly, labels=True)
    
    q_fomc_fly = IRSwapQuery(
        structure=IRSwapStructure.FLY,
        value=IRSwapValue.NPV,
        curve="USD-SOFR-1D",
        structure_kwargs={
            "front_tenor": fly[0],
            "belly_tenor": fly[1],
            "back_tenor": fly[2],
            "bpv": bpv_per_trade,
        },
        tags=(tag,),
    )
    
    # ...add triggers...

# Run backtest
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)
bt.run()
```

### Section 5: Results
```python
mtm = pd.Series(bt.mtm_history).sort_index()
print(f"Final MTM: {float(mtm.iloc[-1]):,.0f}")

plt.figure()
plt.plot(mtm.index, mtm.values, label="MtM PnL")
plt.title(f"FOMC {fomc_fly[0]}/{fomc_fly[1]}/{fomc_fly[2]} Fly | Carry > 0")
plt.show()
```

## Results and Insights

### Strategy Performance
- **Win Rate**: Percentage of positive trades
- **PnL**: Total realized and unrealized
- **Volatility**: Standard deviation of daily returns
- **Sharpe**: Risk-adjusted returns

## Dependencies and Prerequisites

### Key Modules
- Query.IRSwaps._CENTRAL_BANK_DATES
- BT framework (triggers, strategies, backtester)
- FOMC date helpers

---

## Common Patterns and Best Practices

### Pattern 1: Curve Management

```python
# Always get curve at specific timestamp
curve = mdp._get_curve(curve_name, timestamp=ts)

# Check metadata
print(curve.meta())  # Shows timestamp, source, id

# Use curve.handle() to pass to rateslib
rl_curve = curve.handle()
```

### Pattern 2: Query Building

```python
# Always build queries with full parameters
q = IRSwapQuery(
    curve="USD-SOFR-1D",  # Required
    structure=IRSwapStructure.OUTRIGHT,  # Default
    value=IRSwapValue.RATE,  # Required
    tenor="10Y",  # For OUTRIGHT
    structure_kwargs={"bpv": 1},  # Required bpv parameter
)

# Resolve to get pricing objects
pkg, rws = q.resolve_package(pricer_or_curve=curve)
vmap = q.build_value_map(pricer_or_curve=curve, package=pkg, risk_weights=rws)

# Apply to get value
rate = vmap.apply(value=IRSwapValue.RATE)
```

### Pattern 3: Timeseries Collection

```python
# Prepare list of queries
queries = [...]

# Collect data
df = tb.get_timeseries(
    start=start_date,
    end=end_date,
    queries=queries,
    n_jobs=min(len(queries), cpu_count()),  # Parallelize
)

# Always handle NaN/missing
df = df.dropna()
```

### Pattern 4: Backtesting

```python
# 1. Define triggers with actions
triggers = [...]

# 2. Create strategy
strategy = QueryStrategy(name="MyStrategy", triggers=triggers)

# 3. Create backtest
bt = QueryDrivenBacktest(time_grid=tg, mdp=mdp, strategy=strategy)

# 4. Run
bt.run()

# 5. Analyze
mtm = pd.Series(bt.mtm_history).sort_index()
```

### Pattern 5: Risk Analysis

```python
# 1. Define basis instruments
instruments = {...}

# 2. Create solver
solver = rl.Solver(
    curves=[curve.handle()],
    instruments=instruments.values(),
    instrument_labels=instruments.keys(),
    s=[r.rate().real for r in instruments.values()],
    ...
)

# 3. Create portfolio
portfolio = rl.Portfolio(trades)

# 4. Get risk
risk_vector = portfolio.delta(solver=solver)
```

### Best Practices

1. **Always use timezone-aware datetimes** for anything with NY timestamps
2. **Parallelize data collection** with appropriate n_jobs
3. **Validate data** - check NaN, outliers, business day alignment
4. **Use curve metadata** for auditing (check timestamp, source, id)
5. **Cache results** when re-running analysis
6. **Document assumptions** in trader notes/comments
7. **Test on smaller date ranges** before full historical runs
8. **Monitor memory** for large timeseries collections
9. **Use try/except** for external data fetches
10. **Version control notebooks** with clear cell descriptions

---

## Troubleshooting

### Common Issues

#### Issue 1: "No data available for timestamp"
**Cause**: Data source doesn't have data for that date/time
**Solution**: 
- Check if it's a holiday (use QuantLib calendar)
- Verify data source has coverage
- Try nearby date

#### Issue 2: "NaN in calculation"
**Cause**: Missing data point in computation
**Solution**:
```python
# Clean data
df = df.dropna()

# Or forward fill
df = df.ffill()

# Or interpolate
df = df.interpolate()
```

#### Issue 3: Slow data collection
**Cause**: Sequential processing or network delays
**Solution**:
```python
# Increase parallelization
df = tb.get_timeseries(..., n_jobs=16)

# Reduce date range for testing
# Use query filtering to reduce load
```

#### Issue 4: "Connection timeout" from data sources
**Cause**: Network issues or service down
**Solution**:
```python
# Add retry logic
import time
for attempt in range(3):
    try:
        curve = mdp._get_curve(...)
        break
    except Exception as e:
        if attempt < 2:
            time.sleep(5)  # Wait and retry
        else:
            raise
```

#### Issue 5: "Curve building failed"
**Cause**: Insufficient instruments or poor data quality
**Solution**:
- Check that sufficient instruments provided
- Verify instrument inputs (prices, rates)
- Inspect solver error messages

### Debugging Tips

1. **Print metadata**: `print(curve.meta())`, `print(query.col_name())`
2. **Inspect packages**: `print(len(pkg))`, `print(type(pkg[0]))`
3. **Check shapes**: `print(df.shape)`, `print(df.info())`
4. **Look at samples**: `print(df.head())`, `print(df.tail())`
5. **Validate inputs**: `assert len(queries) > 0`, `assert start < end`
6. **Add logging**: 
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

---

## Performance Considerations

### Memory Usage
- Large timeseries can consume significant RAM
- Each query adds columns to result DataFrame
- Consider chunking by date for very large runs

### Computation Time
- Curve building: 0.1-1s per timestamp
- Query resolution: 10-100ms per query
- Parallelization with n_jobs can 4-8x speedup

### Data Fetching
- Network latency: 100-500ms per request
- Batch requests when possible
- Consider local caching

### Backtesting
- Daily loop with complex queries: hours for full history
- Use smaller date ranges for development
- Vectorize calculations where possible

---

## Next Steps

1. **Start with basics**: Run `curve_builds.ipynb` and `timeseries_builder.ipynb`
2. **Understand data**: Explore bond and swap data structures
3. **Learn pricing**: Study `fomc_pricer.ipynb` and `medium_term_swap_pricer.ipynb`
4. **Build strategies**: Implement backtests with `month_end_irswaps_backtest.ipynb`
5. **Analyze risk**: Use risk model from `curve_risk_model.ipynb`
6. **Iterate**: Modify strategies and parameters for your use cases

---

## Additional Resources

### Related Documentation
- CACHING_MODULE_ANALYSIS.md: Data caching architecture
- TB_MODULE_DOCUMENTATION.md: Timeseries builder details
- RVUTILS_COMPREHENSIVE_DOCUMENTATION.md: Analysis utilities

### Key Classes Reference

**MDP Classes**:
- `IRSwapsMDP`: Swap curve data provider
- `FixedRateBondsMDP`: Bond data provider

**Query Classes**:
- `IRSwapQuery`: Swap instrument definition
- `FixedRateBondQuery`: Bond instrument definition
- `IRSwapStructure`: OUTRIGHT, CURVE, FLY structures
- `IRSwapValue`: RATE, NPV, PV01, CVX_ADJ, MMSS values

**TB Classes**:
- `TimeseriesBuilder`: Multi-product data collection
- `IRSwapsTB`: Swap timeseries
- `FixedRateBondsTB`: Bond timeseries

**BT Classes**:
- `QueryDrivenBacktest`: Backtesting engine
- `QueryStrategy`: Strategy definition
- `DateTrigger`: Date-based events
- `AddQueryAction`, `UnwindPositionsAction`: Trade actions

---

## Conclusion

The ARBS notebook suite provides comprehensive tools for fixed income analysis, from foundational curve concepts to sophisticated trading strategy development. Each notebook builds on core ARBS principles:

1. **Modular Design**: Separate concerns (data, pricing, analysis)
2. **Query-Driven**: Declarative instrument definition
3. **Multi-Source**: Support for diverse data providers
4. **Production-Ready**: Suitable for live trading infrastructure

Use these notebooks as templates for your own analysis, adapting parameters and logic to your specific needs.

