# ARBS Market Data Provider (MDP) - Comprehensive Analysis

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [MarketDataProvider Abstract Interface](#marketdataprovider-abstract-interface)
4. [Data Sources](#data-sources)
5. [Curve Building Mechanisms](#curve-building-mechanisms)
6. [Backend Implementations: QuantLib vs RatesLib](#backend-implementations)
7. [Fixing and Reference Data Fetching](#fixing-and-reference-data-fetching)
8. [Historical vs Intraday Data Handling](#historical-vs-intraday-data-handling)
9. [Recipe Hashing and Determinism](#recipe-hashing-and-determinism)
10. [IRSwapsMDP Implementation](#irswapsmdp-implementation)
11. [FixedRateBondsMDP Implementation](#fixedrateboridsmdp-implementation)
12. [Data Fetching Utilities and Caching](#data-fetching-utilities-and-caching)
13. [Integration with Backtesting Engine](#integration-with-backtesting-engine)
14. [Adding New Data Sources](#adding-new-data-sources)

---

## Overview

The Market Data Provider (MDP) module is the core data layer of ARBS that bridges market data sources (CME, SDR, GSQUANT, etc.) with pricing engines. It abstracts away data source complexity and provides a unified interface for the backtesting engine to request pricers (curve objects or bond pricers) at specific timestamps.

**Key Design Principles:**
- **Generic Interface**: Type-parameterized `MarketDataProvider[_GP]` abstract base class
- **Caching-First**: Multi-level caching (ZODB for persistence, recipe hashing for determinism)
- **Dual Backends**: Support for both QuantLib (QL) and RatesLib (RL) curve implementations
- **Data Flow**: Raw market data → Curve/Bond objects → Pricer wrappers → Backtester

---

## Architecture

### Module Structure

```
MDP/
├── MarketDataProvider.py                    # Abstract base class
├── IRSwaps/                                 # IR Swaps data providers
│   ├── IRSwapsMDP.py                        # Main IR Swaps provider
│   ├── CME_NY_EOD_LIVE/                     # CME end-of-day data
│   │   ├── ql_basic/                        # QuantLib implementations
│   │   │   ├── CMEFetcherV2.py              # Async CME data fetcher
│   │   │   ├── ErisFuturesFetcher.py        # Eris futures fetcher
│   │   │   ├── FixingsFetcher.py            # SOFR/index fixings
│   │   │   └── BaseFetcher.py               # Base fetcher class
│   │   └── rl_basic/                        # RatesLib implementations
│   │       ├── CMEFetcherV2.py              # Async CME data fetcher (RL)
│   │       └── ErisFuturesFetcher.py        # Eris futures (RL)
│   ├── SDR_INTRADAY/                        # Intraday SDR swap data
│   │   ├── rl_curve_utils/
│   │   │   ├── _RLCurveCache.py             # RatesLib curve caching/recipes
│   │   │   ├── rl_usd_sofr_mt_*.py          # Medium-term curve builders
│   │   │   ├── rl_usd_sofr_stir_*.py        # STIR/OIS curve builders
│   │   │   ├── SDRDataBuilder.py            # SDR data extraction
│   │   │   └── tos.py                       # Time-of-snapshot utilities
│   │   └── rl_usd_sofr_mt_q*/               # Specific curve implementations
│   ├── GSQUANT/                             # GS Quant data feed
│   │   └── rl_basic/build.py                # GS Quant RL curve building
│   └── fixings_cache/                       # SOFR/index fixings cache
│       └── fixings_cache.py                 # Fixings fetching + caching
├── FixedRateBonds/                          # Fixed-rate bonds data providers
│   ├── FixedRateBondsMDP.py                 # Main bonds provider
│   ├── FEDINVEST/                           # FedInvest data source
│   ├── WSJ/                                 # WSJ bond quotes
│   ├── WEBULL/                              # Webull fintech data
│   ├── PUBLICDOTCOM/                        # Public.com data
│   └── reference_data_cache/                # Bond reference data
│       ├── ust_reference_data.py            # UST reference data mgmt
│       └── cme_tcf.py                       # CME Treasury futures
└── IRSwapSpreads/                           # IR Swap spreads (placeholder)
    └── SDR_WEBULL/
```

---

## MarketDataProvider Abstract Interface

### Base Class Definition

Located in `/home/user/ARBS/MDP/MarketDataProvider.py`:

```python
from abc import ABC, abstractmethod
from typing import Any, Generic
from Query.Base._GenericPricer import _GenericPricer
from Query.Base._GenericPricable import _GP

class MarketDataProvider(ABC, Generic[_GP]):
    """
    Abstract base class for market data providers that return a pricer.
    
    Each concrete provider turns a request (curve id, timestamp, etc.)
    into a concrete `_GenericPricer[_GP]` instance.
    """
    
    def __init__(self, source: str, **kwargs: Any):
        """
        Args:
            source: Data source identifier (e.g., "CME_NY_EOD_LIVE-QL_BASIC")
            **kwargs: Source-specific configuration options
        """
        self.source = source
        self.config = kwargs
    
    @abstractmethod
    def get_pricer(self, request: Any) -> _GP:
        """
        Main interface: convert a request dict into a pricer/curve object.
        
        Args:
            request: Dict typically containing:
                - curve_name: str (e.g., "USD-SOFR-1D")
                - timestamp: datetime.date | datetime.datetime | Literal["live"]
                - Additional source-specific keys
        
        Returns:
            A pricer object implementing _GenericPricer protocol
        
        Raises:
            RuntimeError: If curve/data cannot be built
            ValueError: If request is malformed
        """
        ...
    
    def get_data(self, request: Any) -> _GenericPricer[_GP]:
        """Deprecated: prefer `get_pricer` (backward compat alias)."""
        return self.get_pricer(request)
```

### Interface Contract

**What a Consumer Calls:**
```python
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-QL_BASIC")
request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": datetime.date(2024, 1, 15)
}
pricer = mdp.get_pricer(request)  # Returns QLIRSwapCurve or RLIRSwapCurve
```

**What an Implementation Provides:**
- Fetch raw market data from external sources (CME, SDR, FRED, etc.)
- Build discount/zero curves using QuantLib or RatesLib
- Inject reference-rate fixings
- Wrap curves in pricer objects
- Cache results for performance

---

## Data Sources

### 1. CME End-of-Day (CME_NY_EOD_LIVE)

**Purpose**: End-of-day interest rate swap quotes from CME clearinghouse

**Data Coverage**:
- Swap tenors: 2y, 3y, 4y, 5y, 6y, 7y, 8y, 9y, 10y, 12y, 15y, 20y, 25y, 30y
- Tenors via STIR futures: 3M, 6M (IMM contracts)
- Reference currencies: USD, EUR, GBP, JPY, CAD, CHF, NOK, HKD, AUD, SGD

**Curves Supported**:
- `USD-SOFR-1D` (SOFR OIS discounting)
- `USD-FEDFUNDS` (Fed Funds OIS)
- `USD-OIS` (OIS benchmark)
- Multi-currency variants (EUR-ESTR, JPY-TONAR, etc.)

**Implementation Paths**:
1. **QL_BASIC**: QuantLib-based (`MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/CMEFetcherV2.py`)
2. **RL_BASIC**: RatesLib-based (`MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/CMEFetcherV2.py`)

**Data Fetching Flow**:
```
CMEFetcherV2.build_ql_eod_curves() / build_rl_eod_curves()
    ↓
CMEFetcher (v1) [fetches swap quotes + FRED SOFR futures]
    ↓
ErisFuturesFetcher [fetches Eris SEF swap quotes as fallback]
    ↓
FixingsFetcher [fetches historical SOFR/SOFR fixings from FRED]
    ↓
Curve building (bootstrap via QL/RL)
```

---

### 2. SDR Intraday (SDR_INTRADAY-RL)

**Purpose**: High-frequency intraday swap quotes from SDR repositories (DTCC, CME)

**Data Coverage**:
- Multiple intraday snapshots per trading day
- SOFR swap rates at multiple contract expirations
- Multiple curve construction methodologies (Q12, Q16, MT, STIR, OIS)

**Available Builders**:
- `RL_USD_SOFR_MT_Q12`: Medium-term 12 quarterly contracts
- `RL_USD_SOFR_MT_Q16`: Medium-term 16 quarterly contracts
- `RL_USD_SOFR_MT_MISC`: Miscellaneous medium-term variant
- `RL_USD_SOFR_STIR_Q12X8`: Short-term STIR + quarterly blend
- `RL_USD_SOFR_STIR_Q12X12`: STIR extended to 12 quarters
- `RL_USD_OIS_STIR_Q12X9`: OIS STIR variant
- `RL_USD_SOFR_MTV2_Q12X11`: Medium-term V2 with 11 quarterly contracts

**Key Features**:
- **Time-of-snapshot caching**: Recipes hashed by timestamp + SOFR fixings
- **Parallel curve building**: Multiple timestamps in parallel via `rl_usd_sofr_mt_curve_bulk()`
- **Deterministic**: Same input → same curve (via recipe hashing)

**Implementation**: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/`

**Example Usage**:
```python
mdp = IRSwapsMDP(source="SDR_INTRADAY-RL_USD_SOFR_MT_Q12")
request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": datetime.datetime(2024, 1, 15, 14, 30, 0)  # 2:30 PM ET
}
pricer = mdp.get_pricer(request)
```

---

### 3. GSQUANT (GS Quant Data Feed)

**Purpose**: Bloomberg/GS Quant platform swap market data

**Data Coverage**:
- Daily EOD swap quotes
- Coverage: USD-SOFR-1D, USD-OIS, EUR-ESTR, JPY-TONAR

**Implementation**: `MDP/IRSwaps/GSQUANT/rl_basic/build.py`

**Authentication**:
```python
GsSession.use(
    client_id="<GS_CLIENT_ID>",
    client_secret="<GS_CLIENT_SECRET>",
    scopes=GsSession.Scopes.get_default()
)
```

**Data Fetch**:
- Uses `gs_quant.data.Dataset("IR_SWAP_RATES_V1_STANDARD")`
- Maps GS asset IDs to curve tenors
- Bootstraps RatesLib curves via rate solver

---

### 4. Eris SEF / CBOT Futures

**Purpose**: Supplementary swap quote and futures data when CME unavailable

**Data Sources**:
- Eris SEF (Swap Execution Facility) swap quotes
- CBOT Treasury futures (TY, US, etc.)
- Eris price feeds for SOFRs

**Implementation**: 
- `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/ErisFuturesFetcher.py` (QL)
- `MDP/IRSwaps/CME_NY_EOD_LIVE/rl_basic/ErisFuturesFetcher.py` (RL)

---

### 5. Fixed-Rate Bonds Data Sources

#### FedInvest (Fidelity Fixed Income Data)
- **Purpose**: End-of-day UST clean prices
- **Fetcher**: `MDP/FixedRateBonds/FEDINVEST/FedInvestFetcher.py`
- **Caching**: ZODB cache with key = (date, cusip)

#### WSJ (Wall Street Journal)
- **Purpose**: Live + intraday UST bond quotes (YTM)
- **Fetcher**: `MDP/FixedRateBonds/WSJ/WSJFetcher.py`
- **Data**: Live quotes + 3-day intraday history

#### Webull Fintech
- **Purpose**: Intraday bond quotes with fine timestamp resolution
- **Fetcher**: `MDP/FixedRateBonds/WEBULL/WebullFintechFetcher.py`
- **Use Case**: High-frequency intraday bond valuations

#### Public.com
- **Purpose**: Historical UST daily close data
- **Fetcher**: `MDP/FixedRateBonds/PUBLICDOTCOM/PublicDotcomDataFetcher.py`
- **Caching**: ZODB cache with linear interpolation for missing dates

#### Reference Data
- **Source**: FiscalData.treasury.gov API
- **Manager**: `MDP/FixedRateBonds/reference_data_cache/ust_reference_data.py`
- **Fields**: CUSIP, maturity, issue date, coupon, original-issue (OI) bucket, rank
- **Caching**: Dated directory structure (YYYY-MM-DD) with rolling 3-day retention

---

## Curve Building Mechanisms

### QuantLib-Based Curve Building

**Location**: `Query/IRSwaps/backends/quantlib/` (not in MDP, but used by MDPs)

**Process**:
1. **Fetch market quotes** (swap rates, futures prices)
2. **Convert to QL instruments**: `IborLeg`, `FixedRateLeg` → `VanillaSwap`
3. **Bootstrap discount curve**:
   - Start with overnight (O/N) rate
   - Iteratively solve for zero curve nodes
   - Use QL's built-in solvers (e.g., `CubicNaturalSpline` interpolation)
4. **Create pricer**:
   ```python
   ql_curve = ql.PiecewiseLogLinearDiscount(...)  # or other interpolation
   ql_curve_handle = ql.YieldTermStructureHandle(ql_curve)
   irswap_index = QUANTLIB_CURVE_DEFINITIONS[curve_name]["ReferenceRate"](ql_curve_handle)
   # Inject fixings
   irswap_index.addFixing(date, fixing_value)
   return QLIRSwapCurve(ql_curve_id, ql_curve_handle, ql_curve_index)
   ```

**Strengths**:
- Mature, battle-tested library
- Multiple interpolation algorithms
- Good documentation
- Standard in industry

**Limitations**:
- QL objects not JSON-serializable (harder to cache)
- Slower for bulk curve building

---

### RatesLib-Based Curve Building

**Location**: `Query/IRSwaps/backends/rateslib/` + MDP curve builders

**Process**:
1. **Fetch market data** (swap rates, futures)
2. **Convert to RL instruments**: 
   ```python
   rl.IRS(
       effective=datetime.date(...),
       termination=datetime.date(...),
       fixed_rate=rate_value,
       spec=RATESLIB_CURVE_DEFINITIONS[curve]["ReferenceRate"],
       curves=curve_id
   )
   ```
3. **Define curve skeleton**:
   ```python
   rl.Curve(
       nodes={datetime.date(...): 1.0, ...},  # pillar dates & discount factors
       id=curve_id,
       convention=day_counter,
       calendar=calendar_obj,
       interpolation="log_linear",
       t=[knot_dates],  # spline knots
       endpoints=("natural", "natural")  # boundary conditions
   )
   ```
4. **Solve curve**:
   ```python
   rl.Solver(
       curves=[rl_curve],
       instruments=[swap1, swap2, ...],
       s=[rate1, rate2, ...],  # market rates
       func_tol=1e-8,
       conv_tol=1e-8
   )
   ```
5. **Cache as JSON**:
   ```python
   rl_json = rl_curve.to_json()  # Fully serializable
   # Store in ZODB or file
   rl_curve_restored = rl.from_json(rl_json)
   ```

**Strengths**:
- JSON-serializable (excellent for caching)
- Faster bootstrapping
- Parallel-friendly
- Python-native

**Limitations**:
- Less mature than QuantLib
- Smaller community

---

### Key Differences: QL vs RL in MDP

| Aspect | QuantLib (QL) | RatesLib (RL) |
|--------|---------------|---------------|
| **Caching** | Pickled Python objects | JSON strings (via `.to_json()`) |
| **Serialization** | Heavy (full object graph) | Lightweight (JSON) |
| **Performance** | Slower for bulk builds | Faster |
| **Interpolation** | Many algorithms (LogLinear, CubicNatural, etc.) | Primarily log-linear |
| **Recipes** | Fixed for all QL curves | Parameterizable (Q12, Q16, STIR variants) |
| **Source** | CME only | CME + SDR + GSQUANT |

---

## Backend Implementations

### QuantLib Backend (QL)

**Main Paths**:
```
IRSwapsMDP.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": date})
    ↓ (if source == "CME_NY_EOD_LIVE-QL_BASIC")
    ↓
CMEFetcherV2.build_ql_eod_curves(curve, ql_day_count, ql_calendar, bdates)
    ↓
[Fetch CME swap quotes + SOFR futures + FRED data]
    ↓
[Bootstrap QL discount curve]
    ↓
Inject fixings via irswap_index.addFixing(date, fixing)
    ↓
Return QLIRSwapCurve(ql_curve_id, ql_curve_handle, ql_curve_index)
```

**Pricer Class**: `Query/IRSwaps/backends/quantlib/QLIRSwapCurve`
- Holds: `ql_curve_handle` (YieldTermStructureHandle), `ql_curve_index` (SwapIndex)
- Used by: Backtester to value IR swaps via QL's `Instrument.NPV()` method

---

### RatesLib Backend (RL)

**Main Paths**:
```
IRSwapsMDP.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": datetime | "live"})
    ↓ (if source.startswith("CME_NY_EOD_LIVE-RL"))
    ↓
CMEFetcherV2.build_rl_eod_curves(curve_id, curve, bdates)
    ↓
[Fetch CME swap quotes]
    ↓
[Solve RL curve: Solver([rl_curve], [instruments], rates)]
    ↓
rl_json = rl_curve.to_json()  # Serialize
    ↓
Return RLIRSwapCurve(rl_curve_id, rl_curve_handle, fixings=pd.Series, meta_data)
```

**Pricer Class**: `Query/IRSwaps/backends/rateslib/RLIRSwapCurve`
- Holds: `rl_curve_handle` (rateslib.Curve), `fixings` (pd.Series)
- Used by: Backtester to value swaps via RL's pricer interface

---

### Intraday SDR Curve Building (RatesLib only)

**Entry Point**: `IRSwapsMDP._get_curve()` for sources matching `"SDR_INTRADAY-RL_*"`

**Example Flow** (RL_USD_SOFR_MT_Q12):
```python
# Input: snap=datetime.datetime(...), sofr_fixings=pd.Series
# 1. Fetch SDR swap data for that timestamp
# 2. Use _RLCurveCache with recipe hash as cache key
# 3. If not cached: call rl_usd_sofr_mt_curve(snap, sofr_fixings, ...)
# 4. Curve builder:
#    - Selects Q12 quarterly contracts (next 12 quarterly periods)
#    - Blends with 3M/6M STIR (short-term smoothness)
#    - Applies FOMC date logic for front-end (future dates)
# 5. Return (timestamp, rl_curve_handle)
```

**Key Module**: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/`
- `rl_usd_sofr_mt_builder.py`: Medium-term curve builder (Q12, Q16, MTV2)
- `rl_usd_curve_stir_builder.py`: STIR-blended curves
- `SDRDataBuilder.py`: Extract SDR swap data from external feed
- `BarchartFetcher.py`: Barchart API for intraday snap fetching

---

## Fixing and Reference Data Fetching

### SOFR Fixings

**Location**: `MDP/IRSwaps/fixings_cache/fixings_cache.py`

**Function**: `_fetch_fixings(as_of_date, curve_name, force_refresh=False) -> pd.Series`

**Workflow**:
1. **Determine expected fix date**: T-1 USBD (last US business day before `as_of_date`)
2. **Check local cache**: 
   - Cache path: `~/.cache/arbs/MDP/IRSwaps/fixings_cache/{curve_name}_fixings/`
   - Dated directories: `YYYY-MM-DD/fixings.csv`
3. **Fallback to live fetch** (if cache miss or force_refresh):
   ```python
   FixingsFetcher().get_fixings(curve=curve_name)
   # or fallback: FixingsFetcher(fred_api_key="...").get_fixings(..., use_fred=True)
   ```
4. **Cache validation**: Only cache if T-1 USBD fixing is present (published)
5. **Cache cleanup**: Keep only 3 most recent dated directories

**Returned Series**:
```python
Index: datetime.index (normalized to date level)
Values: float (fixing rates, typically in basis points)
Name: "Fixing"
Index.name: curve_name (e.g., "USD-SOFR-1D")
```

**Usage in IRSwapsMDP**:
```python
fixings_series = _fetch_fixings(as_of_date=ref, curve_name=curve_name)
fixings_series = fixings_series[fixings_series.index.date < ref]  # Exclude future
for d, f in fixings_series.to_dict().items():
    irswap_index.addFixing(fixingDate=d, fixing=f, forceOverwrite=True)
```

---

### Bond Reference Data

**Location**: `MDP/FixedRateBonds/reference_data_cache/ust_reference_data.py`

**Function**: `update_reference_data(source="fiscaldata", force_refresh=False) -> pd.DataFrame`

**Data Source**: FiscalData.treasury.gov API (US Treasury data)

**Fields**:
- `cusip`: Bond identifier
- `maturity_date`: Bond maturity
- `issue_date`: Original issue date
- `cpn`: Coupon rate (%)
- `oi`: Original-issue bucket (e.g., "10-Year", "5-Year")
- `rank`: Age ranking within OI bucket (0 = most recent)

**Caching**:
```
MDP/FixedRateBonds/reference_data_cache/ust_reference_data/
├── fiscaldata/
│   ├── 2025-10-26/
│   │   └── [downloaded data]
│   ├── 2025-10-25/
│   └── 2025-10-24/
```

**Alias Resolution**:
- **Constant-Maturity Aliases**: `CT10` → Rank-0 10-year bond
- **OI-Level Aliases**: `O10` → Rank-1 (second-most recent) 10-year; `OOO20` → Rank-3 20-year
- **Ox Aliases**: `Ox1010` → Rank-1, 10-year
- **Monthly Aliases**: `0125` → January 2025 maturity; `0125-5` → January 2025, 5th OI bucket

**Example Resolution**:
```python
ref_df = update_reference_data(source="fiscaldata")
ref_df = ref_df[(ref_df["issue_date"] <= as_of) & (ref_df["maturity_date"] >= as_of)]
ref_df["rank"] = ref_df.groupby("oi")["issue_date"].rank(method="first", ascending=False) - 1

# Resolve alias "CT5" to rank-0 5-year bond
m_ct = re.match(r"^CT(\d+)$", "CT5")
tenor = int(m_ct.group(1))  # 5
oi = f"{tenor}-Year"  # "5-Year"
hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == 0)]
cusip = hit.iloc[0]["cusip"]
```

---

### CME Treasury Futures Conversion Factor (TCF)

**Location**: `MDP/FixedRateBonds/reference_data_cache/cme_tcf.py`

**Function**: `read_cme_tcf_with_headers(as_of=datetime.date)`

**Purpose**: Provides CME contract specs (notional, accrued interest, etc.) for US Treasury futures

**Usage**: Linked to bond-to-futures basis calculations

---

## Historical vs Intraday Data Handling

### Historical Data

**Definition**: EOD (end-of-day) data as of trading date close (typically 5 PM ET)

**Timestamp Type**: `datetime.date` (no time component)

**Data Sources**:
- CME EOD swaps (`CME_NY_EOD_LIVE` with `timestamp: datetime.date`)
- FedInvest for UST bonds (historical daily closes)
- GSQUANT for EOD swaps

**Request Example**:
```python
mdp = IRSwapsMDP(source="CME_NY_EOD_LIVE-QL_BASIC")
request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": datetime.date(2024, 1, 15)
}
```

**Caching Strategy**:
- Key = (timestamp, curve_name, curve_id)
- Storage = ZODB database (serialized curves/pricers)

---

### Intraday Data

**Definition**: Multiple snapshots within a trading day (e.g., every 15 min)

**Timestamp Type**: `datetime.datetime` (full date + time in UTC or NY TZ)

**Data Sources**:
- SDR_INTRADAY (snapshots from SDR repositories)
- WSJ intraday (last 3 days with 15-min resolution)
- Webull Fintech (fine granularity)

**Request Example**:
```python
mdp = IRSwapsMDP(source="SDR_INTRADAY-RL_USD_SOFR_MT_Q12")
request = {
    "curve_name": "USD-SOFR-1D",
    "timestamp": datetime.datetime(2024, 1, 15, 14, 30, 0)  # 2:30 PM ET
}
```

**Caching Strategy**:
- Key = recipe hash (snap timestamp + SOFR fixings content hash)
- Storage = ZODB, keyed by deterministic recipe
- Enables efficient deduplication: same inputs → same cache entry

**Special Handling**:

#### Time-of-Snapshot (TOS) Logic
Intraday curves account for FOMC announcement timing:
```python
# If snapshot before 8 AM ET on FOMC day, push out FOMC meeting 1 day
# (SOFR fixings not yet published for that date)
FIXINGS_TOL = 1  # days
cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
target_dt = (pd.Timestamp(ref) - (cbd * FIXINGS_TOL)).normalize()
if target_dt not in sofr_fixings.index:
    last_val = sofr_fixings.iloc[-1]
    sofr_fixings.loc[target_dt] = last_val  # Carry forward last fixing
```

#### Live Snapshot
```python
timestamp = "live"  # Special marker
# Handled as: datetime.datetime.now() (UTC or NY TZ depending on source)
# Curves rebuilt fresh (no cache lookup)
# Fixings: All up to yesterday EOD
```

---

## Recipe Hashing and Determinism

### Purpose

Ensure reproducibility: **same inputs → same cached output (deterministic curves)**

### Where It's Used

**Primarily**: SDR intraday curve building via `_RLCurveCache`

### Recipe Components

Located in `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/_RLCurveCache.py`:

```python
def _series_sha1(s: pd.Series) -> str:
    """Hash a time series to a 10-char SHA1 suffix."""
    ss = s.copy()
    ss.index = pd.to_datetime(ss.index)
    ss = ss.sort_index()
    # Format: YYYY-MM-DD=value with 12-digit precision
    parts = (f"{idx.date().isoformat()}={val:.12g}" for idx, val in ss.items())
    h = hashlib.sha1("\n".join(parts).encode()).hexdigest()
    return h[:10]

def _make_key(
    curve_id: str,
    snap: Union[datetime.date, datetime.datetime, List[...]],
    sofr_fixings: pd.Series,
    n_ser: int,       # # of SOFR STIR contracts
    n_sfr: int,       # # of short-dated swaps
    n_plus_fomc_years: int,  # FOMC extrapolation
) -> str:
    """
    Generate deterministic cache key.
    
    Example key:
    "SDR_INTRADAY__snap=2024-01-15T14:30:00__fx=a1b2c3d4e5__ser=8__sfr=2__fomc=2"
    """
    snap_norm = _normalize_snap(snap)
    fhash = _series_sha1(sofr_fixings)
    base = f"{curve_id}__snap={','.join(snap_norm)}__fx={fhash}__ser={n_ser}__sfr={n_sfr}__fomc={n_plus_fomc_years}"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", base)[:200]
```

### Determinism Guarantees

**Immutable Inputs**:
- Snapshot timestamp (normalized to ISO format)
- SOFR fixings series (content hash via SHA1)
- Curve methodology params (n_ser, n_sfr, n_plus_fomc_years)

**Always Produces Same Curve**:
- Input fixings are sorted
- Timestamps normalized
- Hash truncated consistently
- Cache lookups deterministic

**Example**:
```python
# Call 1
snap1 = datetime.datetime(2024, 1, 15, 14, 30, 0)
fixings1 = pd.Series({...})
curve1 = rl_usd_sofr_mt_curve(snap=snap1, sofr_fixings=fixings1, ...)

# Call 2 (same inputs)
snap2 = datetime.datetime(2024, 1, 15, 14, 30, 0)
fixings2 = fixings1.copy()
curve2 = rl_usd_sofr_mt_curve(snap=snap2, sofr_fixings=fixings2, ...)

# curve1 and curve2 have identical market data (pulled from cache, same key)
```

---

## IRSwapsMDP Implementation

### Class Definition

**Location**: `/home/user/ARBS/MDP/IRSwaps/IRSwapsMDP.py`

**Signature**:
```python
class IRSwapsMDP(MarketDataProvider[_GenericPricable]):
    def __init__(
        self,
        source: str = "CME_NY_EOD_LIVE-ql_basic",
        force_refresh_fixings: Optional[bool] = False,
        **kwargs: Any
    ):
        super().__init__(source, **kwargs)
        self.force_refresh_fixings = force_refresh_fixings
        # Initialize curve caches for RL-based sources
        if "SDR_INTRADAY-RL" in source.upper():
            self._rl_curve_cache = _RLCurveCache(cache_name="SDR_INTRADAY-RL_CURVE_CACHE")
```

### Supported Sources

| Source | Backend | Data | Timestamp | Bulk Support |
|--------|---------|------|-----------|--------------|
| `CME_NY_EOD_LIVE-QL_BASIC` | QL | CME | `datetime.date` | Yes |
| `CME_NY_EOD_LIVE-RL_BASIC` | RL | CME | `datetime.date` | Yes |
| `ERIS_EOD_LIVE-RL_BASIC` | RL | Eris | `datetime.date` | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_MT_Q12` | RL | SDR | `datetime.datetime` / "live" | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_MT_Q16` | RL | SDR | `datetime.datetime` / "live" | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_MT_MISC` | RL | SDR | `datetime.datetime` / "live" | Yes |
| `SDR_INTRADAY-RL_USD_SOFR_STIR_Q12X8` | RL | SDR | `datetime.datetime` / "live" | No |
| `SDR_INTRADAY-RL_USD_OIS_STIR_Q12X9` | RL | SDR | `datetime.datetime` | No |
| `GSQUANT-RL` | RL | GS Quant | `datetime.date` | No |
| `SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12X11` | RL | SDR @ 3PM | `datetime.date` | No |

### Main Methods

#### `get_pricer(request: dict) -> _IRSwapGenericCurve`

**Public API**: Wraps `get_data()` with error handling.

```python
def get_pricer(self, request: dict) -> _IRSwapGenericCurve:
    curve = self.get_data(request)
    if curve is None:
        raise RuntimeError(f"IRSwapsMDP could not build a curve for request: {request}")
    return curve
```

#### `get_data(request: dict) -> Optional[_IRSwapGenericCurve]`

**Dispatcher**: Extracts curve_name & timestamp, calls `_get_curve()`.

```python
def get_data(self, request: dict) -> Optional[_IRSwapGenericCurve]:
    curve_name = request.pop("curve_name")
    timestamp = request.pop("timestamp")
    if not curve_name or not timestamp:
        raise ValueError("Request must contain 'curve_name' and 'timestamp'.")
    return self._get_curve(curve_name, timestamp, kwargs=request)
```

#### `_get_curve(curve_name, timestamp, kwargs) -> _IRSwapGenericCurve`

**Core Router**: ~500 lines dispatching to appropriate builder based on `self.source`.

**Pseudo-code**:
```python
def _get_curve(self, curve_name: str, timestamp: ..., kwargs: dict) -> _IRSwapGenericCurve:
    # Assert timestamp is valid
    assert not QUANTLIB_CURVE_DEFINITIONS[curve_name]["Calendar"].isHoliday(timestamp_ql_date)
    
    if self.source == "CME_NY_EOD_LIVE-QL_BASIC":
        # 1. Instantiate CMEFetcherV2
        # 2. Call build_ql_eod_curves(curve, ql_day_count, ql_calendar, bdates=[timestamp])
        # 3. Extract QL curve from returned dict
        # 4. Create QL curve handle & swap index
        # 5. Fetch fixings and inject into index
        # 6. Return QLIRSwapCurve(...)
        
    elif self.source == "CME_NY_EOD_LIVE-RL_BASIC":
        # Similar, but: build_rl_eod_curves(...) → RatesLib curve
        
    elif self.source.startswith("SDR_INTRADAY-RL_USD_SOFR_MT_"):
        # 1. Fetch SOFR fixings
        # 2. Call rl_usd_sofr_mt_curve(snap=timestamp, sofr_fixings=..., cache=...)
        # 3. Handle FIXINGS_TOL for pre-8AM-FOMC timestamps
        # 4. Return RLIRSwapCurve(...)
        
    elif self.source == "GSQUANT-RL":
        # 1. Call _rl_curve_cache.get_gsquant_rl_basic(curve_id=curve_name, as_of=timestamp)
        # 2. Deserialize RL curve from JSON
        # 3. Return RLIRSwapCurve(...)
    
    else:
        raise NotImplementedError(f"Curve Build '{self.source}' does not exist")
```

#### `bulk_get_data(request: dict) -> Dict[Union[date, datetime], _IRSwapGenericCurve]`

**Purpose**: Fetch curves for multiple timestamps in parallel.

**Parameters**:
- `curve_name`: str
- `timestamps`: List[Union[date, datetime, Literal["live"]]]
- `ignore_cache`: bool (default False)
- `n_jobs`: int (default 1, number of worker threads)

**Deduplication**:
```python
seen: set = set()
timestamps: List = []
for t in timestamps_in:
    if t == datetime.date.today():
        t = "live"
    key = ("live",) if t == "live" else ("dt", t) if isinstance(t, datetime.datetime) else ("d", t)
    if key not in seen:
        seen.add(key)
        timestamps.append(t)
```

**Parallel Execution** (RL MT curves only):
```python
built_curves = rl_usd_sofr_mt_curve_bulk(
    base_curve_id="SDR_INTRADAY-RL_USD_SOFR_MT_Q12",
    snaps=datetime_snaps,
    sofr_fixings=full_fixings_series,
    cache=self._rl_curve_cache,
    max_workers=n_jobs,
    force_refresh=ignore_cache
)
# Returns: Dict[datetime, rl.Curve]
```

**Fallback** (non-parallel-supported sources):
```python
for t in timestamps:
    out[t] = self.get_data({"curve_name": curve_name, "timestamp": t, **request})
```

---

## FixedRateBondsMDP Implementation

### Class Definition

**Location**: `/home/user/ARBS/MDP/FixedRateBonds/FixedRateBondsMDP.py`

**Signature**:
```python
class FixedRateBondsMDP(MarketDataProvider[_GenericPricable], ZODBCacheMixin):
    def __init__(self, source: str = "USTS_FEDINVEST_WSJ_LIVE-QL", **kwargs: Any):
        # Initialize ZODB cache for pricers
        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False
        
        if source == "USTS_FEDINVEST_WSJ_LIVE-QL":
            from MDP.FixedRateBonds.FEDINVEST.FedInvestFetcher import FedInvestDataFetcher
            self.fi = FedInvestDataFetcher()
```

### Supported Sources

| Source | Bonds Source | Quotes | QL/RL | Live | Intraday | Bulk |
|--------|--------------|--------|-------|------|----------|------|
| `USTS_FEDINVEST_WSJ_LIVE-QL` | FedInvest (EOD) + WSJ | YTM | QL | Yes | Yes (3D) | Yes |
| `USTS_WEBULL_WSJ_LIVE-RL` | Webull + WSJ | YTM | RL | Yes | Yes | Yes |
| `USTS_PUBLICDOTCOM_WSJ_LIVE-QL` | Public.com (hist) | YTM | QL | Yes | Yes | No |

### Main Methods

#### `get_pricer(request: dict) -> Dict[str, _FixedRateBondGenericPricer]`

**Returns**: Dict mapping original symbols to bond pricers.

```python
def get_pricer(self, request: dict) -> Dict[str, _FixedRateBondGenericPricer]:
    pricers = self.get_data(request)
    if pricers is None:
        raise RuntimeError(f"FixedRateBondsMDP could not build pricer(s) for {request}")
    return pricers
```

#### `get_data(request: dict) -> Optional[Dict[str, _FixedRateBondGenericPricer]]`

**Request Fields**:
- `cusips`: Union[str, List[str]] — symbols or CUSIPs to fetch
- `timestamp`: Union[date, datetime, Literal["live"]]

**Calls**: `_get_multi_pricers()`

#### `_get_multi_pricers(cusips, timestamp, kwargs) -> Dict[str, _FixedRateBondGenericPricer]`

**Flow**:
1. **Expand aliases**: `CT5` → CUSIP, `O10` → CUSIP, `0125` → CUSIP
2. **Load reference data**: UST maturity/coupon/issue dates (as-of timestamp)
3. **Route by source & timestamp**:

**QL Path** (USTS_FEDINVEST_WSJ_LIVE-QL):
- **Live**: Fetch WSJ live quotes → `QLFixedRateBondPricer(ytm=...)`
- **Intraday (WSJ buffer)**: Fetch WSJ intraday timeseries → find nearest to 3 PM ET
- **Historical**: Fetch FedInvest EOD clean price → Compute YTM → `QLFixedRateBondPricer(clean_price=...)`

**RL Path** (USTS_WEBULL_WSJ_LIVE-RL):
- **Live**: Fetch WSJ live quotes → `RLFixedRateBondPricer(ytm=...)`
- **Intraday**: Fetch Webull intraday → batch-load full day window → cache all snapshots → extract request timestamp
- **Caching**: ZODB cache with key = (timestamp, cusip, source) stores pricer args dict

**Alias Handling**:
```python
def _resolve_aliases_bulk(symbols: List[str], timestamp, ref_df: pd.DataFrame) -> (OrderedDict, Dict):
    alias_to_cusip: OrderedDict[str, str] = OrderedDict()
    meta_by_cusip: Dict[str, dict] = {}
    
    for raw in symbols:
        alias = raw.strip()
        
        # Constant-maturity alias (CT5, CT10, etc.)
        m_ct = re.match(r"^CT(\d+)$", alias, re.IGNORECASE)
        if m_ct:
            tenor = int(m_ct.group(1))
            oi = f"{tenor}-Year"
            hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == 0)]
            if not hit.empty:
                cusip = str(hit.iloc[0]["cusip"])
        
        # OI-level alias (O10, OO10, OOO10, etc.)
        m_o = re.match(r"^(O{1,3})(\d+)$", alias, re.IGNORECASE)
        if m_o:
            rank = len(m_o.group(1))  # O=rank 1, OO=rank 2, OOO=rank 3
            tenor = int(m_o.group(2))
            oi = f"{tenor}-Year"
            hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
            if not hit.empty:
                cusip = str(hit.iloc[0]["cusip"])
        
        # Ox alias (Ox1010, Ox2005, etc.)
        m_ox = re.match(r"^Ox(?P<rank>\d+)(?P<tenor>10|20|25|30|7|5|3|2)$", alias, re.IGNORECASE)
        if m_ox:
            rank = int(m_ox.group("rank"))
            tenor = int(m_ox.group("tenor"))
            oi = f"{tenor}-Year"
            hit = ref_df[(ref_df["oi"] == oi) & (ref_df["rank"] == rank)]
            if not hit.empty:
                cusip = str(hit.iloc[0]["cusip"])
        
        # Fall back: treat as direct CUSIP or monthly alias (0125, 0125-5)
        if "cusip" not in locals() or cusip is None:
            try:
                resolved = _alias_to_cusip(alias, ref_df)
                if resolved:
                    cusip = resolved
            except:
                cusip = alias  # Use original as fallback
        
        alias_to_cusip[raw] = cusip
        row = ref_df[ref_df["cusip"] == cusip]
        if not row.empty:
            meta_by_cusip[cusip] = row.iloc[0].to_dict()
    
    return alias_to_cusip, meta_by_cusip
```

#### `bulk_get_data(timestamps, cusips, show_tqdm, max_workers) -> Dict[timestamp, Dict[cusip, pricer]]`

**Purpose**: Fetch pricers for a grid of (timestamp, cusip) pairs.

**Strategy**:
1. Pre-fetch all reference data (async)
2. Per timestamp: resolve aliases → fetch quotes/prices → build pricers
3. Parallelize across timestamps (ThreadPoolExecutor)
4. For RL: batch-fetch Webull intraday window, cache all snapshots, extract exact request times

**Output Structure**:
```python
{
    datetime.date(2024, 1, 15): {
        "CT5": QLFixedRateBondPricer(...),
        "0125": QLFixedRateBondPricer(...),
    },
    datetime.date(2024, 1, 16): {
        "CT5": QLFixedRateBondPricer(...),
        "0125": QLFixedRateBondPricer(...),
    },
}
```

### Pricer Building

**From Cached Args**:
```python
@staticmethod
def _build_pricer_from_args(args: Dict, issue_date_key, maturity_date_key, cpn_key):
    if "ql_frb_id" in args:
        return QLFixedRateBondPricer(
            ql_frb_id=args["ql_frb_id"],
            reference_date=datetime.date.fromisoformat(args["reference_date"]),
            issue_date=datetime.date.fromisoformat(args["meta_data"][issue_date_key]),
            maturity_date=datetime.date.fromisoformat(args["meta_data"][maturity_date_key]),
            cpn=args["meta_data"][cpn_key],
            ytm=float(args.get("ytm")) or None,
            clean_price=float(args.get("clean_price")) or None,
            meta_data=args["meta_data"],
        )
    elif "rl_frb_id" in args:
        # Similar for RLFixedRateBondPricer
```

### Context Management

For thread-safe ZODB cache operations:

```python
def __open__(self):
    with self._open_lock:
        if self._open_count == 0:
            self._ensure_pricer_cache()
        self._open_count += 1
    return self

def __close__(self, *, commit: bool = True):
    with self._open_lock:
        if self._open_count <= 0:
            return
        self._open_count -= 1
        if self._open_count == 0:
            if commit:
                self.zodb_commit()
            self.close_zodb()
            self._cache_ready = False

# Usage:
with FixedRateBondsMDP() as mdp:
    pricers = mdp.bulk_get_data(timestamps=..., cusips=..., max_workers=8)
```

---

## Data Fetching Utilities and Caching

### ZODB Caching Mixin

**Location**: `Caching/ZODBCacheMixin.py`

**Purpose**: Persistent, thread-safe object storage using Zope Object Database.

**Key Methods**:
```python
class ZODBCacheMixin:
    def zodb_open_cache(
        self,
        cache_attr: str,           # Attribute name to store cache dict
        path: Optional[str] = None, # File path (default: ~/.cache/arbs/...)
        encode=None,               # Custom serializer
        decode=None,               # Custom deserializer
        force=False                # Force refresh from disk
    ) -> None:
        """Open a persistent ZODB dict at path and attach to self.cache_attr."""
    
    def zodb_commit(self) -> None:
        """Flush pending writes to disk."""
    
    def close_zodb(self) -> None:
        """Close connection and cleanup."""
    
    def batched(self):
        """Context manager: batch multiple writes, commit once."""
        # Usage:
        # with cache.batched():
        #     for k, v in items:
        #         cache[k] = v
```

**Storage Structure**:
```
~/.cache/arbs/
├── FixedRateBondPricer_Cache.fs  # ZODB file database
├── FixedRateBondPricer_Cache.lock
├── FixedRateBondPricer_Cache.tmp
├── SDR_INTRADAY-RL_CURVE_CACHE.fs
├── ...
```

### Fixings Cache

**Location**: `MDP/IRSwaps/fixings_cache/fixings_cache.py`

**Design**: Filesystem-based CSV cache with dated directories.

**Cache Key**: Curve name (e.g., "USD-SOFR-1D")

**Directory Structure**:
```
~/.cache/arbs/MDP/IRSwaps/fixings_cache/
└── USD-SOFR-1D_fixings/
    ├── 2024-01-15/
    │   └── fixings.csv  # Index: datetime, Columns: USD-SOFR-1D (values)
    ├── 2024-01-14/
    └── 2024-01-13/
```

**Cleanup**: Retains only 3 most recent dated directories.

**CSV Format**:
```csv
Date,Fixing
2024-01-12,5.375
2024-01-11,5.375
...
```

### CME/Eris Data Fetching

**Base Fetcher**: `MDP/IRSwaps/CME_NY_EOD_LIVE/ql_basic/BaseFetcher.py`

**Key Features**:
- **Async I/O**: Uses `asyncio` for parallel requests
- **Timeout Handling**: Configurable global timeout per request
- **Proxy Support**: Optional HTTP proxy for network restrictions
- **Verbosity Control**: Debug, info, warning, error logging levels

**Configuration**:
```python
from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.CMEFetcherV2 import CMEFetcherV2

fetcher = CMEFetcherV2(
    global_timeout=10,  # seconds
    proxies={"http": "http://proxy.example.com:8080", ...},
    debug_verbose=False,
    info_verbose=True,
    error_verbose=True,
)
```

### SDR Data Fetching

**Builder**: `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py`

**Steps**:
1. Query SDR repositories (DTCC, CME) for swap trades on date
2. Filter to specific contract tenors (e.g., 3M, 6M, 2Y, 5Y, ...)
3. Aggregate by tenor: weighted-average prices, last price, bid-ask mid
4. Return as DataFrame with tenor → rate mapping

**Data Sources**:
- DTCC SDR (primary)
- CME SDR (fallback)
- Barchart (additional futures data)

---

## Integration with Backtesting Engine

### Backtester Architecture

**Location**: `/home/user/ARBS/BT/`

**Entry Point**: `BT/query_engine.py` → `QueryDrivenBacktest`

### Data Flow

```
Backtest Loop (TimeGrid):
    ├─ t = next timestamp
    ├─ Strategy generates QueryOrders
    ├─ Order processing:
    │   ├─ Query.build_mdp_request(t)
    │   ├─ MDP.get_pricer(request) ← MDP here
    │   ├─ Query.resolve_package(pricer, structure_id)
    │   ├─ Query.build_value_map(pricer, package)
    │   └─ Portfolio MTM + PnL calc
    └─ Next timestep
```

### Query Interface

**Location**: `Query/Base/BaseQuery.py`

**Key Methods**:
```python
@dataclass(frozen=True)
class BaseQuery(ABC):
    product: str                       # "IRS", "Swaption", "Bond", etc.
    structure_id: Any                  # e.g., "OUTRIGHT", "FLY_2_5_10"
    structure_kwargs: Dict[str, Any]   # Tenor, strike, side, etc.
    value_id: Optional[Any]            # Default valuation metric
    market_request: Dict[str, Any]     # Template for MDP request
    
    def build_mdp_request(self, now: datetime.datetime) -> Dict[str, Any]:
        """
        Inject current timestamp into market_request.
        
        Rules:
        - If mdp_time_key missing: inject now.date()
        - If mdp_time_key == "now": inject full datetime
        - If mdp_time_key == "live": leave as-is
        """
        req = dict(self.market_request or {})
        if self.mdp_time_key not in req:
            req[self.mdp_time_key] = now.date()
        else:
            v = req[self.mdp_time_key]
            if v == "now":
                req[self.mdp_time_key] = now
        return req
```

### Example Usage in Backtest

**Building a Request**:
```python
# Query for a 5Y x 30Y flattener using SDR intraday curves
swap_query = SomeSwapQuery(
    product="IRS",
    structure_id="FLY",
    structure_kwargs={"tenor1": "5Y", "tenor2": "10Y", "tenor3": "30Y"},
    value_id="dv01",
    market_request={
        "curve_name": "USD-SOFR-1D",
        "timestamp": "now"  # Will be replaced by engine
    }
)

# At backtest time t:
t = datetime.datetime(2024, 1, 15, 10, 30, 0)
mdp = IRSwapsMDP(source="SDR_INTRADAY-RL_USD_SOFR_MT_Q12")
request = swap_query.build_mdp_request(t)
# request = {"curve_name": "USD-SOFR-1D", "timestamp": datetime.datetime(2024, 1, 15, 10, 30, 0)}

pricer = mdp.get_pricer(request)
# Returns: RLIRSwapCurve object

# Resolve to swaps and value:
package, weights = swap_query.resolve_package(pricer_or_curve=pricer)
value_map = swap_query.build_value_map(pricer_or_curve=pricer, package=package, risk_weights=weights)
dv01 = value_map.apply(value="dv01")
```

### Caching in Backtester

**Purpose**: Avoid refetching same pricer for multiple positions referencing same market date.

**Implementation** (`QueryDrivenBacktest`):
```python
def _pricer_for_request(self, req: Dict[str, Any]) -> Any:
    sig = repr(sorted(req.items()))  # Request signature
    hit = self._cache.get(("pricer", sig))
    if hit is not None:
        return hit
    pricer = self.mdp.get_pricer(req)
    self._cache[("pricer", sig)] = pricer
    return pricer

def _pricer_for_query(self, q: BaseQuery, now: datetime.datetime) -> Any:
    req = q.build_mdp_request(now)
    return self._pricer_for_request(req)
```

**Benefits**:
- Multiple swaps on same curve → fetch curve once
- Same curve on consecutive timesteps → cache hit

---

## Adding New Data Sources

### Step 1: Define Data Source Interface

Choose data provider type:

**Option A: EOD Source** (similar to CME_NY_EOD_LIVE)
```python
# File: MDP/IRSwaps/MyNewSource/ql_basic/MyFetcher.py
class MyFetcher(BaseFetcher):
    def build_ql_eod_curves(
        self,
        curve: str,
        type: Literal["Zero", "Df"],
        ql_day_count: ql.DayCounter,
        ql_calendar: ql.Calendar,
        bdates: List[datetime.date],
        **kwargs
    ) -> Dict[datetime.date, ql.YieldTermStructure]:
        """
        Fetch market data for bdates and bootstrap QL curves.
        
        Returns: {date: curve, ...}
        """
```

**Option B: Intraday Source** (similar to SDR_INTRADAY)
```python
# File: MDP/IRSwaps/MyNewSource/rl_curve_utils/my_curve_builder.py
def my_curve_builder(
    curve_id: str,
    snap: Union[datetime.datetime, List[datetime.datetime]],
    sofr_fixings: pd.Series,
    cache: Optional[_RLCurveCache] = None,
    force_refresh: bool = False,
) -> Tuple[datetime.datetime, rl.Curve]:
    """
    Build RL curve for snapshot(s).
    
    Returns: (timestamp_built, rl_curve_handle)
    """
```

### Step 2: Implement Data Fetching

```python
# Example: Fetch from REST API
import httpx

class MyFetcher(BaseFetcher):
    def fetch_swap_quotes(self, date: datetime.date, curve_name: str) -> pd.DataFrame:
        """
        Fetch swap rates from API for given date and curve.
        
        Returns DataFrame with columns: tenor (e.g., "2Y", "5Y", ...), rate (float)
        """
        async with httpx.AsyncClient(timeout=self.global_timeout) as client:
            url = f"https://api.example.com/swaps/{date.isoformat()}"
            resp = await client.get(url, params={"curve": curve_name})
            resp.raise_for_status()
            df = pd.DataFrame(resp.json())
            return df
```

### Step 3: Register in IRSwapsMDP

**File**: `MDP/IRSwaps/IRSwapsMDP.py`

```python
def _get_curve(self, curve_name, timestamp, kwargs):
    # ... existing code ...
    
    elif self.source.upper() in ["MY_NEW_SOURCE-RL_BASIC", "MY_NEW_SOURCE_RL_BASIC"]:
        from MDP.IRSwaps.MyNewSource.rl_basic.MyFetcher import MyFetcher
        from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve
        
        assert type(timestamp) == datetime.date, "MY_NEW_SOURCE requires datetime.date"
        
        fetcher = MyFetcher(**self.config)
        ts, rl_curve_handle = fetcher.build_rl_eod_curves(
            curve_id=f"{self.source}-{curve_name}-{timestamp}",
            curve=curve_name,
            bdates=[timestamp],
            **kwargs
        )
        
        fixings_series = _fetch_fixings(as_of_date=timestamp, curve_name=curve_name)
        fixings_series = fixings_series[fixings_series.index.date < timestamp] * 100
        
        return RLIRSwapCurve(
            rl_curve_id=curve_name,
            rl_curve_handle=rl_curve_handle,
            fixings=fixings_series,
            meta_data={"timestamp": ts, "id": f"{self.source}-{curve_name}-{timestamp}"}
        )
```

### Step 4: Add Bulk Support (Optional)

```python
def bulk_get_data(self, request: dict) -> Dict[date, _IRSwapGenericCurve]:
    # ... deduplication logic ...
    
    elif self.source.upper() in ["MY_NEW_SOURCE-RL_BASIC"]:
        fetcher = MyFetcher(**self.config)
        built = fetcher.build_rl_eod_curves(
            curve_id=f"{self.source}-{curve_name}",
            curve=curve_name,
            bdates=bdates,
            show_tqdm=show_tqdm,
            **request
        )
        
        for ref_date, rl_curve in built.items():
            fixings = _fetch_fixings(as_of_date=ref_date, curve_name=curve_name)
            fixings = fixings[fixings.index.date < ref_date] * 100
            out[ref_date] = RLIRSwapCurve(...)
        
        return out
```

### Step 5: Add Curve Definitions

**For QuantLib**:
```python
# File: Query/IRSwaps/backends/quantlib/ql_curve_definitions_map.py
QUANTLIB_CURVE_DEFINITIONS["MY-CURVE"] = {
    "Calendar": ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    "DayCounter": ql.Actual360(),
    "ReferenceRate": lambda h: ql.USDLiborIndex(ql.Period("3M"), h),
    # ... other specs
}
```

**For RatesLib**:
```python
# File: Query/IRSwaps/backends/rateslib/rl_curve_definitions_map.py
RATESLIB_CURVE_DEFINITIONS["MY-CURVE"] = {
    "Calendar": "us",
    "DayCounter": "ACT/360",
    "ReferenceRate": rl.SOFR,
    "BusinessConvention": "MF",
    # ... other specs
}
```

### Step 6: Test

```python
def test_my_new_source():
    mdp = IRSwapsMDP(source="MY_NEW_SOURCE-RL_BASIC")
    request = {
        "curve_name": "MY-CURVE",
        "timestamp": datetime.date(2024, 1, 15)
    }
    pricer = mdp.get_pricer(request)
    assert pricer is not None
    
    # Test bulk
    pricers = mdp.bulk_get_data({
        "curve_name": "MY-CURVE",
        "timestamps": [datetime.date(2024, 1, 15), datetime.date(2024, 1, 16)]
    })
    assert len(pricers) == 2
```

### Step 7: Document

Add to MDP module docstring:
```python
"""
Supported data sources:
    ...
    MY_NEW_SOURCE-RL_BASIC: Custom REST API feed
        - Source: https://api.example.com
        - Coverage: MY-CURVE
        - Timestamp: datetime.date (EOD)
        - Caching: ZODB
"""
```

---

## Performance Considerations

### Caching Best Practices

1. **Use Bulk Methods**: `bulk_get_data()` is faster than repeated `get_pricer()` calls.
2. **Deduplicate Timestamps**: Same date multiple times? Backtester caching handles it.
3. **Fixings Cache**: Automatically cached in `~/.cache/arbs/MDP/IRSwaps/fixings_cache/`.
4. **Recipe Hash**: Intraday curves cached by deterministic recipe key.

### Parallelization

- **IR Swaps**: RL MT curve builders support `n_jobs` parameter for parallel timestamp fetching.
- **Bonds**: `FixedRateBondsMDP.bulk_get_data()` uses ThreadPoolExecutor.
- **Async I/O**: CME/Eris fetchers use `asyncio` for concurrent requests.

### Memory

- **ZODB**: Off-loads to disk; memory footprint is minimal.
- **Fixings Series**: One small series per curve (kept in memory).
- **Curves**: QL curves are C++ objects; RL curves are Python dicts (JSON-like).

---

## Summary

The ARBS MDP module provides a production-grade abstraction over multiple market data sources:

1. **Generic Interface**: `MarketDataProvider[T]` with type-safe pricer returns.
2. **Multiple Sources**: CME EOD, SDR intraday, GSQUANT, Eris, WSJ, FedInvest, Webull, Public.com.
3. **Dual Backends**: QuantLib (mature) and RatesLib (fast, JSON-serializable).
4. **Intelligent Caching**: Recipe hashing for determinism, ZODB for persistence, fixings cache for data.
5. **Time-Aware**: Handles historical (date), intraday (datetime), and live queries.
6. **Integration**: Seamless backtester integration via `build_mdp_request()` hook.
7. **Extensibility**: Well-defined patterns for adding new sources and curves.

