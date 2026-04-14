# SDR Analytics Notebook Suite — Design Document

## Overview

A suite of 10 Jupyter notebooks + 1 shared Python module in `notebooks/sdr/` providing EOD and historical SDR analytics for a USD swaps market-making desk. Focused on linear swaps (SOFR OIS, FedFunds OIS) and basis products (SOFR-FF, CME-LCH, spreadovers).

**Constraints:**
- Time horizon: EOD cumulative + historical lookbacks (no intraday)
- Product scope: Linear swaps + basis (no swaptions/caps-floors)
- Integration: Full stack — SDRUtils + IRSwapsMDP + curve_store + TimeseriesBuilder

**Key methodology** (derived from ~800 Clarus FT articles, primarily Chris Barnes):
- DV01 over notional as primary volume metric
- Package-adjusted analytics (decompose curves/flies/spreadovers)
- Compression/reset-optimization separation from new-risk
- Block size regime awareness (Oct 2024 CFTC recalibration)
- Price dispersion as liquidity proxy

---

## Architecture

```
notebooks/sdr/
├── _sdr_common.py                # Shared data loading, classification, enrichment, viz defaults
├── 01_flow_decomposition.ipynb   # Package detection: outrights vs curves vs flies vs spreadovers
├── 02_volume_regime.ipynb        # DV01 by tenor vs rolling baselines, volume spike detection
├── 03_liquidity_scoring.ipynb    # Price dispersion, tick analysis, D2D vs D2C pricing
├── 04_spreadover_analytics.ipynb # Swap spread VWAP, counts, notional, Swapalypse detection
├── 05_sofr_ff_basis.ipynb        # SOFR-FedFunds split, basis swap volumes, regime detection
├── 06_cme_lch_basis.ipynb        # CCP identification, basis estimation, compression timing
├── 07_compression_analytics.ipynb# Compression vs new-risk, platform share, reset optimization
├── 08_block_cap_analysis.ipynb   # Block identification, capped notional, regime changes
├── 09_tenor_maturity.ipynb       # Curve risk distribution, forward-start, IMM/FOMC/MAC
└── 10_event_flow.ipynb           # FOMC/election/crisis event templates, volume spike detection
```

All notebooks import `_sdr_common.py` which wraps:
- `SDRUtils.products.usd.usd_swaps.USDSwapsModule.build_classification_dataframe()` for classification
- `SDRUtils.packages.curve.detect_curve_trades_df()` / `fly.detect_fly_trades_df()` for package detection
- `SDRUtils.core.lifecycle_v2` for lifecycle resolution
- `SDRUtils.analytics.seasonality` for event calendars
- `MDP.IRSwaps.IRSwapsMDP` for curve-based PV01 enrichment
- `Caching.curve_store` for historical curve snapshots

---

## Shared Module: `_sdr_common.py`

### Data Loading

```python
def load_classified_trades(
    start: datetime,
    end: datetime,
    cache_path: str = "C:/sdr_cache",
    curve_source: str = "ERIS_EOD_LIVE-RL_BASIC",
    detect_packages: bool = True,
) -> pd.DataFrame:
    """
    Load and classify SDR trades for a date range.
    
    Wraps USDSwapsModule.build_classification_dataframe() with:
    - Package detection (curve/fly/mms/spreadover) enabled by default
    - Parquet caching per execution date
    - Automatic DV01 and volume bucket enrichment
    
    Returns DataFrame with columns from USDLinearClassification:
        trade_id, execution_timestamp, effective_date, expiration_date,
        product_type, trade_label, notional, is_notional_capped, estimated_pv01,
        tenor_years, tenor_label, is_forward, forward_start_years, forward_label,
        fixed_rate, special_tenor_type, special_tenor_confidence,
        rate_index, linear_product_type, tenor_segment,
        package_type, package_id, package_legs
    """
```

### Enrichment Helpers

```python
def add_dv01_columns(df) -> pd.DataFrame:
    """Add dv01 = abs(estimated_pv01 * notional / 10_000) column."""

def add_volume_buckets(df) -> pd.DataFrame:
    """Add tenor_bucket column: 0-2Y, 2-5Y, 5-10Y, 10-20Y, 20-30Y, 30Y+."""

def add_execution_date(df) -> pd.DataFrame:
    """Add execution_date (date only) from execution_timestamp."""
```

### Filtering Helpers

```python
def filter_new_risk(df) -> pd.DataFrame:
    """Exclude compression and lifecycle corrections. Keep NEWT action_type only."""

def filter_outrights(df) -> pd.DataFrame:
    """Keep trades where package_type is None or OUTRIGHT."""

def filter_packages(df) -> pd.DataFrame:
    """Keep trades where package_type is CURVE, FLY, or other multi-leg."""

def filter_by_rate_index(df, index: RateIndex) -> pd.DataFrame:
    """Filter to specific rate index (SOFR, FED_FUNDS, etc.)."""

def filter_by_basis_type(df, basis: BasisType) -> pd.DataFrame:
    """Filter to specific basis type (SOFR_FF, SOFR_TENOR, etc.)."""

def filter_compression(df) -> pd.DataFrame:
    """Identify and return likely compression trades via lifecycle + heuristics."""

def filter_reset_optimization(df) -> pd.DataFrame:
    """Identify single-period / FRA-like reset optimization activity."""
```

### Visualization Constants

```python
TENOR_ORDER = ["1Y","2Y","3Y","4Y","5Y","7Y","10Y","12Y","15Y","20Y","25Y","30Y","40Y","50Y"]
TENOR_BUCKET_ORDER = ["0-2Y", "2-5Y", "5-10Y", "10-20Y", "20-30Y", "30Y+"]
PACKAGE_COLORS = {
    "OUTRIGHT": "#4C78A8", "CURVE": "#F58518", "FLY": "#E45756",
    "SPREADOVER": "#72B7B2", "MAC": "#54A24B", "COMPRESSION": "#BFBFBF",
}
RATE_INDEX_COLORS = {
    "SOFR": "#4C78A8", "FED_FUNDS": "#F58518", "SOFR_FF_BASIS": "#E45756",
}

def notebook_setup():
    """Standard notebook initialization: autoreload, matplotlib inline, figsize, style."""
```

---

## Notebook Details

### 01 — Flow Decomposition

**Purpose**: Decompose raw SDR trades into their true economic form. Answers "What actually traded?"

**Analytics**:
1. Trade type stacked bar (DV01): outrights / curves / flies / spreadovers / MAC / IMM / FOMC
2. Package decomposition table: leg tenors, net DV01, direction, timestamp per detected package
3. Rate index split: SOFR OIS / FedFunds OIS / basis. Pie chart + time series
4. Forward-start distribution: spot vs 1M/3M/6M/1Y+ by DV01 share
5. Special tenor breakdown: STANDARD / IMM / FOMC / MAC / MATCHED_MATURITY / INVOICE_SWAP
6. Daily summary table: total DV01, trade count, % packages, top 3 tenors

**Key APIs**: `detect_curve_trades_df()`, `detect_fly_trades_df()`, `USDLinearClassification.linear_product_type`

---

### 02 — Volume Regime

**Purpose**: Is the market busy or quiet relative to history? Detect volume spikes. Inspired by Barnes' "Just how bad are trading conditions right now?"

**Analytics**:
1. DV01 by tenor bucket time series (stacked area, daily)
2. Rolling baseline comparison: today vs 20d/60d/252d averages. Z-score per bucket. Flag >2σ
3. New-risk vs compression separation (two-panel stacked area)
4. Reset optimization filtering: flag single-period / FRA-like. Show clean vs raw volume
5. Weekday × month seasonality heatmap. IMM roll dates highlighted
6. Automated volume spike detection with event context

**Key APIs**: `filter_new_risk()`, `filter_compression()`, `filter_reset_optimization()`, `seasonality.get_fomc_dates()`

---

### 03 — Liquidity Scoring

**Purpose**: Is it cheap or expensive to trade right now? Price dispersion and tick analysis.

**Analytics**:
1. Price dispersion per benchmark tenor (2Y/5Y/10Y/30Y): σ(fixed_rate) in rolling 1-hour windows. Current vs historical percentile
2. Tick size distribution: rate deltas between consecutive same-tenor trades. Median tick over time
3. D2D vs D2C pricing: separate by `Platform identifier`. Compare distributions
4. Block vs non-block pricing: price impact estimation using `Block trade election indicator`
5. Liquidity heatmap: tenor × date colored by dispersion (red=wide, green=tight)
6. Composite liquidity score: weighted dispersion + tick + volume → single score per tenor

**Key fields**: `fixed_rate`, `Platform identifier`, `Block trade election indicator`, `execution_timestamp`

---

### 04 — Spreadover Analytics

**Purpose**: Swap spread flow intelligence. Spreadovers = dominant D2D product (~70% of interdealer flow). Barnes' "Swapalypse Now" framework.

**Analytics**:
1. Spreadover identification via `linear_product_type == SPREADOVER` + package matching
2. VWAP tracking: volume-weighted average rate per tenor, daily. Δ vs prior day + rolling avg
3. Trade count + notional time series by tenor. Flag "Swapalypse" events (>2σ volume)
4. Tenor distribution: which maturities dominate? DV01 pie + share shifts over time
5. Directional flow: net pay/receive via package leg analysis where detectable
6. Spreadover-to-outright ratio over time. Higher = more RV activity

**Key integration**: `IRSwapsMDP` for on-the-run UST maturities, `curve_store` for historical spread levels

---

### 05 — SOFR-FedFunds Basis

**Purpose**: SOFR vs FedFunds volume split and basis swap analytics. 53% volume growth to $14.4T. Monetary policy regime signal.

**Analytics**:
1. SOFR vs FedFunds OIS daily DV01 split. Time series + percentage
2. Basis swap volumes: `basis_type == SOFR_FF`, DV01 by tenor
3. Basis activity heatmap: DV01 by tenor × date
4. Spread level tracking: VWAP of `spread_bps` per tenor from `BasisSwapClassification`
5. Regime detection: rolling FF/total ratio. Highlight spikes (e.g., Q3 2024: 7%→24%)
6. FOMC overlay: basis volumes/spreads vs FOMC meeting dates

**Key APIs**: `BasisSwapClassification.basis_type`, `BasisSwapClassification.spread_bps`, `seasonality.get_fomc_dates()`

---

### 06 — CME-LCH Basis

**Purpose**: CCP basis tracking and compression timing. MVA-driven dealer axes.

**Analytics**:
1. CCP identification from `Cleared` + `Platform identifier` fields
2. Volume by CCP: DV01 time series. CME market share tracking (~2.6% current)
3. Price differential estimation: same-tenor/tight-window trades, CME vs LCH rates
4. CCP switch detection: offsetting trades at different CCPs (same notional/tenor, opposite direction)
5. Compression timing: volume spikes cross-referenced with compression calendars. Basis hedging T-1
6. Basis term structure: estimated CME-LCH spread across tenors, tracked over time

**Key fields**: `Cleared`, `Platform identifier`, `package_type`, `fixed_rate`

---

### 07 — Compression Analytics

**Purpose**: Separate compression from new risk. 1/3 of all SDR-reported trades are compression.

**Analytics**:
1. Compression identification: lifecycle events (TERM+NEWT pairs), action type patterns, platform signatures, notional rounding
2. Compression vs new-risk stacked area (daily DV01)
3. Platform market share: TradeWeb / OSTTRA / bilateral / Bloomberg. Track share shifts
4. Reset optimization detection: single-period swaps, FRA-like, weekday clustering. Quantify fraction
5. Compression-adjusted "clean" volume series — the metric that matters for flow analysis
6. Gross-to-net compression ratio over time. Higher = more portfolio optimization

**Key APIs**: `SDRUtils.core.lifecycle_v2.build_summary()`, lifecycle event chaining

---

### 08 — Block & Cap Analysis

**Purpose**: What can't we see? Block size regime changes affect data visibility. Oct 2024: +64% DV01 thresholds.

**Analytics**:
1. Block trade identification via `Block trade election indicator`. Count + DV01
2. Capped notional detection via `is_notional_capped`. Fraction of trades capped
3. Block size distribution: histogram by tenor. Overlay CFTC threshold lines
4. Regime change analysis: pre/post Oct 2024 comparison (block count, capped %, visible notional)
5. True volume estimation: apply ~30% uplift to block notionals (per Clarus research)
6. LNOF tracking: `Large notional off-facility swap election indicator`

**Key fields**: `Block trade election indicator`, `is_notional_capped`, `Large notional off-facility swap election indicator`

---

### 09 — Tenor & Maturity Profile

**Purpose**: Where on the curve is risk being put on? Identify benchmark tenors and structural shifts.

**Analytics**:
1. DV01 by tenor label (1Y→50Y bar chart). Concentration points
2. Tenor distribution time series: stacked area of DV01 share by bucket
3. Forward-start profile: spot vs forward distribution. Which tenors are most commonly forward-started?
4. IMM date activity: volume by IMM code (H/M/U/Z). Roll patterns around quarterly dates
5. FOMC-dated swaps: volume clustered around upcoming meetings
6. MAC swap tracking: activity by MAC tenor
7. Average life trend: DV01-weighted average tenor over time (policy-driven shifts)

**Key APIs**: `SDRUtils.core.tenors` (IMM/FOMC detection), `special_tenor_type`, `special_tenor_confidence`

---

### 10 — Event Flow Analysis

**Purpose**: Templates for flow analysis around FOMC, elections, crises. Based on Barnes' real-time monitoring methodology.

**Analytics**:
1. Event calendar setup: FOMC, quarter-end, month-end, IMM rolls from `seasonality` module
2. Pre/post event volume: average DV01 in T-5..T+5 window, normalized to baseline
3. Event-day tenor profile: does curve-point distribution shift around events?
4. Price dispersion around events: liquidity scoring applied to event windows
5. Historical case study template: parameterized — input event date, output full flow+liquidity analysis. Pre-built for: COVID (Mar 2020), SVB (Mar 2023), Swapalypse (Apr 2025), US Election (Nov 2024)
6. Cumulative DV01 tracker: running total through the day via execution timestamps

**Key APIs**: `SDRUtils.analytics.seasonality` (FOMC, month-end, quarter-end)

---

## Data Flow

```
DTCC pddata.dtcc.com
    │
    ▼
SDRDataBuilder.grab_sdr_trades()     ← fetch cumulative daily CSVs, cache as Parquet
    │
    ▼
USDSwapsModule.build_classification_dataframe()
    ├── classify_usd_swap_trade()    ← per-row: product type, tenor, forward, special tenor
    ├── classify_product_type()      ← UPI FISN → RateIndex, LinearProductType, BasisType
    ├── IRSwapQuery → PV01           ← curve-based risk estimation
    ├── detect_curve_trades_df()     ← curve package matching (time window + PV01 tolerance)
    ├── detect_fly_trades_df()       ← butterfly 3-leg matching
    └── lifecycle_v2.build_summary() ← chain NEWT→MODI/CORR→TERM events
    │
    ▼
_sdr_common.load_classified_trades()
    ├── add_dv01_columns()           ← DV01 = abs(pv01 * notional / 10000)
    ├── add_volume_buckets()         ← tenor bucket assignment
    └── add_execution_date()         ← date extraction
    │
    ▼
Individual Notebooks (01–10)
    └── Each applies domain-specific filters, aggregations, and visualizations
```

## Dependencies

- **SDRUtils**: classification, lifecycle, packages, seasonality, filters
- **MDP.IRSwaps.IRSwapsMDP**: curve source for PV01 enrichment
- **Caching.curve_store**: historical curve snapshots for spread analytics
- **TB.TimeseriesBuilder**: historical context and cross-referencing
- **Query.IRSwaps.IRSwapQuery**: swap pricing and PV01 calculation
- **pandas, numpy, matplotlib, seaborn**: data manipulation and visualization

## Build Sequence

1. `_sdr_common.py` — shared module (all notebooks depend on this)
2. `01_flow_decomposition.ipynb` — foundational analytics, validates classification pipeline
3. `02_volume_regime.ipynb` — builds on flow decomposition, adds baselines
4. `07_compression_analytics.ipynb` — needed for clean volume in other notebooks
5. `03_liquidity_scoring.ipynb` — standalone price analysis
6. `04_spreadover_analytics.ipynb` — depends on package detection working
7. `05_sofr_ff_basis.ipynb` — depends on rate_index/basis_type classification
8. `06_cme_lch_basis.ipynb` — depends on CCP identification
9. `08_block_cap_analysis.ipynb` — standalone block/cap analysis
10. `09_tenor_maturity.ipynb` — depends on special tenor classification
11. `10_event_flow.ipynb` — integrates concepts from multiple notebooks
