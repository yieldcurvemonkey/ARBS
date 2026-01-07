# ARBS Utilities Module - Quick Reference Guide

## Module Locations

| Module | Location | Purpose |
|--------|----------|---------|
| **ql_utils.py** | `utils/ql_utils.py` | QuantLib integration & date/tenor operations |
| **misc.py** | `utils/misc.py` | Formatting utilities (human_format) |
| **Query QL utils** | `Query/IRSwaps/backends/quantlib/utils.py` | Query-level QuantLib functions |
| **Curve Building** | `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` | Curve construction & extraction |
| **TB utils** | `TB/utils.py` | Visualization & plotting utilities |
| **Caching utils** | `Caching/utils.py` | Cache key generation & serialization |
| **Seasonality** | `RVUtils/seasonality_utils.py` | Month-end/quarter-end seasonality |

---

## Most Used Functions

### Date Conversion (QuantLib ↔ Python)

```python
from utils.ql_utils import *
import QuantLib as ql
from datetime import datetime

# Python datetime ↔ QuantLib Date
ql_date = datetime_to_ql_date(datetime(2024, 1, 15))
py_date = ql_date_to_datetime(ql_date)
py_date_obj = ql_date_to_pydate(ql_date)

# Most recent business day
last_bd = most_recent_business_day_ql(ql.UnitedStates(), tz="UTC", to_pydate=True)
```

### Tenor Operations

```python
from utils.ql_utils import *

# String → QuantLib Period
period = tenor_to_ql_period("5Y")          # ql.Period(5, ql.Years)
period = parse_tenor_string("3M")          # ql.Period(3, ql.Months)

# String → Float (years)
years = tenor_to_years("6M")               # 0.5

# Period → String
tenor_str = period_to_string(period)       # "5Y"

# Period → Months
months = ql_period_to_months(period)       # Converts any unit to months
```

### Financial Formatting

```python
from utils.misc import human_format

# Basic usage
human_format(100000)                       # "100k"
human_format(1500000, decimals=1)         # "1.5M"
human_format(50000, unit="bps")           # "50kbps"

# Custom formatting
human_format(value, system="iec")         # Binary units (Ki, Mi, Gi)
human_format(value, signed=True)          # Include "+" for positive
```

### Business Day Calculations

```python
from utils.ql_utils import *
from datetime import datetime

cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

# Get all business days in range
bdays = get_bdates_between(
    datetime(2024, 1, 1),
    datetime(2024, 1, 31),
    cal
)

# Convert date range to tenor
tenor = dates_to_string_tenor(
    datetime(2024, 1, 15),
    datetime(2024, 4, 15),
    cal
)  # Returns "3M"
```

### Curve Operations

```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import *
import pandas as pd
import QuantLib as ql

# Build discount curve
dates = pd.Series([datetime(2024, 1, 15), datetime(2025, 1, 15)])
dfs = pd.Series([0.98, 0.96])
curve = build_ql_discount_curve(
    dates, dfs, ql.Actual365Fixed(), 
    ql.UnitedStates(),
    interpolation_algo="df_log_linear"
)

# Extract nodes
nodes = get_nodes_dict(curve, to_iso=False)  # datetime → discount factor

# Rebuild from nodes
new_curve = build_discount_curve_from_nodes(
    nodes, ql.Actual365Fixed(), ql.UnitedStates(), "df_log_linear"
)
```

### Visualization

```python
from TB.utils import make_secondary_axis_plot_v1, timeseries_df_plotter
import pandas as pd

# Simple dual-axis plot
plot, fig, ax_left, ax_right, legend = make_secondary_axis_plot_v1(
    ylabel_left="Yield (%)",
    ylabel_right="Price ($)",
    title="Bond Analysis"
)
plot(series1, label="10Y Yield")
plot(series2, label="Price", which='right')
legend()

# Advanced timeseries with statistical bands
timeseries_df_plotter(
    df,
    cols_to_plot=['yield_10y', 'yield_5y'],
    stds={'yield_10y': [1, 2]},  # ±1σ and ±2σ bands
    entry_date=datetime(2024, 1, 15),
    entry_level=4.5
)
```

### Seasonality Analysis

```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality
import pandas as pd
import QuantLib as ql

# Analyze month-end patterns
seasonality = monthend_cumsum_seasonality(
    df,                    # DataFrame with DatetimeIndex
    value_col='price',
    window=5,             # Days before/after month-end
    metric='bps',         # Show in basis points
    cal=ql.UnitedStates()
)

# Output columns include:
# - 'avg': average across all months
# - 'avg±std1', 'avg±std2': confidence bands
# - 'avg-jan', 'avg-feb', etc.: month-specific patterns
# - 'avg-q1-end', etc.: quarter-end patterns
```

---

## Error Handling Patterns

### ValueError for Invalid Input
```python
# These raise ValueError:
tenor_to_ql_period("5X")           # Invalid unit
parse_frequency("invalid")
period_to_months(ql.Period(7, ql.Days))  # Wrong unit type
```

### Try-Except with Fallback
```python
# Returns "NaN" on error
tenor = dates_to_string_tenor(eff_date, exp_date)  # "NaN" if exception
```

### None Return on Exception
```python
# Returns None if extraction fails
nodes = get_nodes_dict(curve)  # None if error during extraction
```

---

## Common Conversion Functions

### Tenor Conversions

| From | To | Function | Example |
|------|-----|----------|---------|
| String | QL.Period | `tenor_to_ql_period()` | "5Y" → Period(5, Years) |
| String | Float (years) | `tenor_to_years()` | "3M" → 0.25 |
| QL.Period | String | `period_to_string()` | Period(3, Months) → "3M" |
| QL.Period | Months | `ql_period_to_months()` | Any period → month count |
| QL.Period | Years | `ql_period_to_years()` | Any period → year fraction |
| Month count | String | `month_to_label()` | 6 → "6M", 24 → "2Y" |

### Date Conversions

| From | To | Function |
|------|-----|----------|
| datetime | QL.Date | `datetime_to_ql_date()` |
| QL.Date | datetime | `ql_date_to_datetime()` |
| QL.Date | date | `ql_date_to_pydate()` |
| Date range | Tenor string | `dates_to_string_tenor()` |
| Two QL.Dates | QL.Period | `tenor_from_dates()` |
| Two QL.Dates | (Y, M, D) | `difference_in_ymd()` |

---

## Configuration Constants

### Standard Swap Tenors

```python
from utils.ql_utils import DEFAULT_SWAP_TENORS

# Available tenors:
# 1D, 1W, 2W, 3W, 1M, 2M, 3M, 4M, 5M, 6M, 9M, 12M,
# 18M, 2Y, 3Y, 4Y, 5Y, 6Y, 7Y, 8Y, 9Y, 10Y,
# 12Y, 15Y, 20Y, 25Y, 30Y, 40Y, 50Y
```

---

## Interpolation Algorithms

### Discount Curve Types

| Algorithm | Type | Use Case |
|-----------|------|----------|
| `df_log_linear` | Log-linear | Default, smooth |
| `df_mono_log_cubic` | Monotonic | Ensures no negative forwards |
| `df_natural_cubic` | Cubic spline | Smooth curve |
| `df_kruger_log` | Kruger | Alternative monotonic |
| `df_log_mixed_linear` | Mixed | Hybrid approach |

### Piecewise Curve Types

| Algorithm | Type |
|-----------|------|
| `pdf_log_linear` | PiecewiseLogLinearDiscount |
| `pdf_mono_log_cubic` | PiecewiseLogCubicDiscount |
| `pdf_natural_cubic` | PiecewiseNaturalCubicZero |
| `pdf_spline_cubic_discount` | PiecewiseSplineCubicDiscount |

### Zero Curve Types

| Algorithm | Type |
|-----------|------|
| `z_linear` | Linear interpolation |
| `z_log_linear` | Log-linear |
| `z_cubic` | Cubic spline |
| `z_natural_cubic` | Natural cubic |

---

## Dependencies Summary

**Core (required):**
- QuantLib
- pandas
- numpy
- datetime (stdlib)

**Optional:**
- matplotlib (plotting v1)
- plotly (plotting v2)
- scipy (interpolation)
- decimal (precise rounding)

---

## Tips & Best Practices

### 1. Always Use Business Day Calendars
```python
# Good - respects holidays
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
last_bd = most_recent_business_day_ql(cal)

# Avoid - doesn't account for holidays
```

### 2. Tenor Validation
```python
# Validate tenor strings before use
valid_tenors = {'1D', '1W', '1M', '3M', '6M', '1Y', '2Y', '5Y', '10Y'}
if tenor not in valid_tenors:
    raise ValueError(f"Unsupported tenor: {tenor}")
```

### 3. Date Consistency
```python
# Keep consistent representation throughout
# Option 1: Always use datetime
# Option 2: Always use QL.Date
# Option 3: Convert at module boundaries only
```

### 4. Curve Extrapolation
```python
# All built curves have extrapolation enabled
curve = build_ql_discount_curve(...)
# Can now discount/forward beyond input dates
```

### 5. Error Handling
```python
# Always check for "NaN" returns from date operations
tenor = dates_to_string_tenor(eff, exp)
if tenor == "NaN":
    # Handle invalid date range
    pass

# Check for None returns from extraction
nodes = get_nodes_dict(curve)
if nodes is None:
    # Handle extraction failure
    pass
```

---

## Real-World Examples

### Example 1: Parse IR Swap Dates
```python
from utils.ql_utils import datetime_to_ql_date, tenor_to_ql_period, get_bdates_between
from datetime import datetime

trade_date = datetime(2024, 1, 15)
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

# Convert to QL
ql_trade = datetime_to_ql_date(trade_date)

# Add tenor to get maturity
tenor = tenor_to_ql_period("5Y")
maturity = ql_trade + tenor

# Get all intermediate coupons
accrual_dates = get_bdates_between(trade_date, maturity, cal)
```

### Example 2: Build Discounting Curve
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_ql_discount_curve

# From market data
tenors = ['ON', '1W', '1M', '3M', '6M', '1Y', '2Y', '5Y', '10Y']
dfs = [0.9999, 0.9998, 0.9995, 0.9990, 0.9980, 0.9960, 0.9920, 0.9800, 0.9600]

curve = build_ql_discount_curve(
    pd.Series(get_curve_dates(tenors)),
    pd.Series(dfs),
    ql.Actual365Fixed(),
    ql.UnitedStates(),
    interpolation_algo="df_log_linear"
)

# Use for pricing
pv = notional * curve.discount(maturity_date)
```

### Example 3: Analyze Month-End Effects
```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality

# Load daily yields
yields_df = pd.read_csv('yields.csv', index_col=0, parse_dates=True)

# Analyze
seasonality = monthend_cumsum_seasonality(
    yields_df,
    window=10,
    metric='bps'
)

# Plot results
seasonality[['avg', 'avg-std1', 'avg+std1']].plot(title='Month-End Effect')
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid tenor unit" | Check tenor format: "5Y", not "5-years" |
| QL.Date creation fails | Use `datetime_to_ql_date()` instead of direct construction |
| Curve extrapolation fails | Ensure `curve.enableExtrapolation()` is called |
| "NaN" from `dates_to_string_tenor` | Check dates are on business days |
| None from `get_nodes_dict` | Add error handling; curve may not support node extraction |
| Plot not showing | Call `plt.show()` at the end |

---

## Function Signature Index

```python
# Date conversions
def ql_date_to_datetime(ql_date: ql.Date) -> datetime
def ql_date_to_pydate(ql_date: ql.Date) -> date
def datetime_to_ql_date(dt: datetime) -> ql.Date

# Tenor parsing
def tenor_to_ql_period(tenor: str) -> ql.Period
def tenor_to_years(tenor: str) -> float
def parse_tenor_string(tenor_str: str) -> ql.Period
def period_to_string(period: ql.Period) -> str

# Period conversion
def ql_period_to_years(period: ql.Period, day_counter, as_of) -> float
def ql_period_to_months(p: ql.Period) -> int
def period_to_months(period: ql.Period) -> float

# Date calculations
def difference_in_ymd(start: ql.Date, end: ql.Date) -> Tuple[int, int, int]
def dates_to_string_tenor(eff_date, exp_date, cal) -> str
def tenor_from_dates(start: ql.Date, end: ql.Date) -> ql.Period
def get_bdates_between(start, end, calendar) -> List[datetime]

# Business days
def most_recent_business_day_ql(calendar, tz="UTC", to_pydate=False)
def most_recent_business_day_from_date(date, calendar, tz="UTC", to_pydate=True)
def datetime_today_utc() -> datetime

# Formatting
def human_format(n, decimals=1, system="finance", signed=False, unit="", strip_zeros=True, rounding="half_up") -> str

# Curve building
def build_ql_discount_curve(datetime_series, dfs, ql_dc, ql_cal, interpolation_algo=None) -> ql.DiscountCurve
def build_piecewise_ql_discount_curve(rate_helpers, ql_dc, ql_cal, settlement_day, interpolation_algo=None) -> ql.DiscountCurve
def build_ql_zero_curve(datetime_series, zero_rates, ql_dc, ql_cal, interpolation_algo=None) -> ql.ZeroCurve

# Curve extraction
def get_nodes_dict(ql_curve, to_ttm=False, to_iso=False) -> Dict
def extract_fitted_curve_nodes(fitted_curve, num_points=10000) -> Dict
def build_discount_curve_from_nodes(nodes_dict, ql_dc, ql_cal, interpolation_algo) -> ql.DiscountCurve
def get_fixings_dict(swap_index: ql.SwapIndex) -> Dict

# Plotting
def make_secondary_axis_plot_v1(ylabel_left=None, ylabel_right=None, title=None)
def make_secondary_axis_plot_v2(ylabel_left=None, ylabel_right=None, title=None)
def timeseries_df_plotter(df, cols_to_plot, cols_to_plot_raxis=None, use_plotly=False, ...)

# Seasonality
def monthend_cumsum_seasonality(df, value_col=None, window=5, business_month_end=True, cal=None, ...)
```

