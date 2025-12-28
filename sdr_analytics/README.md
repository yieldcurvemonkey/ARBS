# SDR Analytics Suite

## Comprehensive Analytics for US Interest Rate Swaps Trading Desk

This suite provides a complete set of analytics tools for analyzing SDR (Swap Data Repository) trade data from CFTC for US interest rate derivatives.

## Notebooks

### 1. `01_sdr_trade_flow_analysis.ipynb`
**Trade Flow Analysis** - Comprehensive analysis of SDR trade flows
- Volume analysis (trade counts and notional)
- Product distribution (OIS, Fixed-Float, Basis, etc.)
- Tenor bucketing and distribution
- Venue analysis (SEF vs Off-Facility)
- Block trade analytics
- Clearing status breakdown

### 2. `02_intraday_curve_pricing.ipynb`
**Intraday Curve Building & Pricing** - Real-time curve construction and trade pricing
- SOFR curve building from live market data
- SDR trade mark-to-market against the curve
- Rich/cheap analysis (traded rate vs fair value)
- Risk analytics (PV01, NPV calculations)
- Rate evolution tracking

### 3. `03_market_microstructure.ipynb`
**Market Microstructure Analysis** - Deep dive into market structure
- Trade size distribution and percentiles
- Block trade threshold analysis
- SEF market share and competition
- Execution latency analysis
- Package trade patterns
- Liquidity metrics (inter-trade times, volume profiles)

### 4. `04_tenor_rate_analytics.ipynb`
**Tenor & Rate Distribution** - Detailed tenor and rate analysis
- Detailed tenor distribution
- Fixed rate distribution by tenor
- Benchmark tenor analysis (2Y, 5Y, 10Y, 30Y)
- Intraday rate evolution
- Forward start analysis
- Curve spread calculations (2s10s, 5s30s, etc.)

### 5. `05_trading_patterns.ipynb`
**Trading Activity Patterns** - Time-series pattern analysis
- Intraday trading profiles
- Day-of-week effects
- Trade clustering and burst detection
- Volume-weighted time analysis
- Cross-tenor correlation
- Daily activity summaries

### 6. `06_realtime_monitoring.ipynb`
**Real-Time Monitoring Dashboard** - Live trade monitoring
- Session statistics
- Recent trades feed
- Large trade alerts
- Rate monitor by tenor
- Volume tracker
- Auto-refresh capability

## Utilities

### `sdr_utils.py`
Shared utility functions for all notebooks:
- Tenor bucketing functions
- Data preprocessing
- Volume and rate statistics
- Large trade identification
- Curve spread calculations
- Export functions

## Quick Start

```python
# Import the SDR data builder
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.SDRDataBuilder import SDRDataBuilder

# Initialize
cache_path = "/tmp/sdr_cache"
sdr = SDRDataBuilder(cache_path=cache_path, show_tqdm=True)

# Fetch trades
import datetime
import pytz
NY_tz = pytz.timezone("America/New_York")

start = NY_tz.localize(datetime.datetime(2025, 12, 19, 7, 0))
end = NY_tz.localize(datetime.datetime(2025, 12, 19, 17, 0))

df = sdr.grab_sdr_trades(
    start_timestamp=start,
    end_timestamp=end,
    agency="CFTC",
    asset_class="RATES"
)
```

## Using Shared Utilities

```python
from sdr_utils import preprocess_sdr_data, calculate_volume_stats

# Preprocess data
df_processed = preprocess_sdr_data(df)

# Calculate statistics
stats = calculate_volume_stats(df_processed, groupby_col="Tenor_Bucket")
```

## Dependencies

- pandas
- numpy
- plotly
- matplotlib
- rateslib
- QuantLib
- pytz
- scipy

## Data Source

SDR data is fetched from DTCC (Depository Trust & Clearing Corporation) via the PDData API. The `SDRDataBuilder` class handles:
- Historical data fetching with caching
- Intraday data fetching
- Automatic date range handling
- Data deduplication and sorting

## Key Metrics Tracked

### Volume Metrics
- Trade count
- Total notional
- Average/median trade size
- Block trade percentage

### Rate Metrics
- Average/median rates by tenor
- Intraday high/low ranges
- Curve spreads

### Microstructure Metrics
- SEF vs Off-Facility split
- Dissemination latency
- Inter-trade times
- Trading velocity

### Risk Metrics
- PV01 by tenor
- NPV calculations
- Rich/cheap analysis

## Notes

- All times are in New York timezone unless otherwise specified
- Notional amounts are in USD
- Rates are displayed as percentages
- Block trade threshold follows CFTC definitions
