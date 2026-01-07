# ARBS Utilities Module - Comprehensive Documentation

## Table of Contents
1. [Overview](#overview)
2. [Module Structure](#module-structure)
3. [QuantLib Date Conversion Utilities](#quantlib-date-conversion-utilities)
4. [Formatting Helpers](#formatting-helpers)
5. [Time and Date Manipulation Functions](#time-and-date-manipulation-functions)
6. [Data Structure Utilities](#data-structure-utilities)
7. [Plotting and Visualization Utilities](#plotting-and-visualization-utilities)
8. [Curve Building Utilities](#curve-building-utilities)
9. [Seasonality Analysis Utilities](#seasonality-analysis-utilities)
10. [Configuration Utilities](#configuration-utilities)
11. [Error Handling Patterns](#error-handling-patterns)
12. [Common Utility Functions](#common-utility-functions)
13. [Usage Examples](#usage-examples)
14. [Dependencies](#dependencies)

---

## Overview

The ARBS utilities module provides reusable helper functions across the project for:
- **QuantLib Integration**: Converting between Python datetime and QuantLib date objects
- **Financial Data Formatting**: Human-readable formatting for financial quantities
- **Tenor/Period Manipulation**: Converting between different representations of fixed income tenors
- **Date Operations**: Business day calculations, calendar-aware date adjustments
- **Curve Building**: Constructing and extracting data from yield term structures
- **Visualization**: Matplotlib-based plotting with dual-axis support
- **Data Serialization**: Configuration/state serialization for caching
- **Seasonality Analysis**: Month-end and quarter-end seasonality calculations

**Key Locations:**
- Primary utilities: `/home/user/ARBS/utils/`
  - `ql_utils.py` - QuantLib integration and date/tenor operations
  - `misc.py` - Formatting and data structure utilities
- Domain-specific utilities:
  - `/home/user/ARBS/Query/IRSwaps/backends/quantlib/utils.py` - Query-specific QuantLib utilities
  - `/home/user/ARBS/Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` - Curve construction
  - `/home/user/ARBS/TB/utils.py` - Visualization and plotting utilities
  - `/home/user/ARBS/Caching/utils.py` - Cache key generation and serialization
  - `/home/user/ARBS/RVUtils/seasonality_utils.py` - Seasonality calculations

---

## Module Structure

### Directory Layout
```
/home/user/ARBS/
├── utils/                          # Core utilities
│   ├── ql_utils.py                # QuantLib integration
│   └── misc.py                    # Formatting & data structures
├── Query/IRSwaps/backends/quantlib/
│   ├── utils.py                   # Query-level QL utilities
│   └── ql_curve_building_utils.py # Curve building
├── TB/
│   └── utils.py                   # Visualization utilities
├── Caching/
│   └── utils.py                   # Cache serialization
└── RVUtils/
    └── seasonality_utils.py       # Seasonality analysis
```

---

## QuantLib Date Conversion Utilities

QuantLib uses its own `Date` class. The utilities provide seamless conversion between Python's standard datetime/date objects and QuantLib dates.

### Functions

#### `ql_date_to_datetime(ql_date: ql.Date) -> datetime`
Converts a QuantLib Date object to a Python datetime object (midnight).

**Location:** `utils/ql_utils.py` (line 41), `Query/IRSwaps/backends/quantlib/utils.py` (line 9)

**Parameters:**
- `ql_date` (ql.Date): QuantLib Date object to convert

**Returns:**
- `datetime`: Python datetime object at midnight on that date

**Example:**
```python
import QuantLib as ql
from utils.ql_utils import ql_date_to_datetime

ql_date = ql.Date(15, ql.January, 2024)
py_datetime = ql_date_to_datetime(ql_date)
# Returns: datetime(2024, 1, 15, 0, 0)
```

#### `ql_date_to_pydate(ql_date: ql.Date) -> date`
Converts a QuantLib Date to a Python date object.

**Location:** `utils/ql_utils.py` (line 44), `Query/IRSwaps/backends/quantlib/utils.py` (line 13)

**Parameters:**
- `ql_date` (ql.Date): QuantLib Date to convert

**Returns:**
- `date`: Python date object

**Example:**
```python
from utils.ql_utils import ql_date_to_pydate
from datetime import date

ql_date = ql.Date(15, ql.January, 2024)
py_date = ql_date_to_pydate(ql_date)
# Returns: date(2024, 1, 15)
```

#### `datetime_to_ql_date(dt: datetime) -> ql.Date`
Converts a Python datetime object to a QuantLib Date.

**Location:** `utils/ql_utils.py` (line 48), `Query/IRSwaps/backends/quantlib/utils.py` (line 17)

**Parameters:**
- `dt` (datetime): Python datetime object

**Returns:**
- `ql.Date`: QuantLib Date object

**Implementation Detail:**
The function maps Python month integers (1-12) to QuantLib month enums (January-December).

**Example:**
```python
from datetime import datetime
from utils.ql_utils import datetime_to_ql_date

py_dt = datetime(2024, 1, 15, 14, 30, 0)
ql_date = datetime_to_ql_date(py_dt)
# Returns: ql.Date(15, January, 2024)
# Note: Time component is ignored
```

#### `most_recent_business_day_ql(ql_calendar: ql.Calendar, tz: Optional[str] = "UTC", to_pydate: Optional[bool] = False)`
Returns the most recent business day from today (or specified timezone).

**Location:** `utils/ql_utils.py` (line 262), `Query/IRSwaps/backends/quantlib/utils.py` (line 40)

**Parameters:**
- `ql_calendar` (ql.Calendar): QuantLib calendar for business day rules
- `tz` (str): Timezone for "today" reference (default: "UTC")
- `to_pydate` (bool): Return as Python datetime if True, QuantLib Date if False

**Returns:**
- `ql.Date` or `datetime`: Most recent business day (walks backward if today is a holiday)

**Example:**
```python
from utils.ql_utils import most_recent_business_day_ql

# Get most recent business day in US government bond calendar
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
most_recent_bd = most_recent_business_day_ql(cal, tz="UTC", to_pydate=True)
```

#### `most_recent_business_day_from_date(input_date: datetime, ql_calendar: ql.Calendar, tz: str = "UTC", to_pydate: bool = True)`
Returns the most recent business day from a given date.

**Location:** `utils/ql_utils.py` (line 276)

**Parameters:**
- `input_date` (datetime): Reference date
- `ql_calendar` (ql.Calendar): Calendar for business day rules
- `tz` (str): Timezone for the input date
- `to_pydate` (bool): Return as Python datetime if True

**Returns:**
- `datetime` or `ql.Date`: Most recent business day from input date

**Example:**
```python
from datetime import datetime
from utils.ql_utils import most_recent_business_day_from_date

cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
date_to_check = datetime(2024, 1, 15)
bday = most_recent_business_day_from_date(date_to_check, cal)
```

---

## Formatting Helpers

### Functions

#### `human_format(n, decimals: int = 1, system: str = "finance", signed: bool = False, unit: str = "", strip_zeros: bool = True, rounding: str = "half_up") -> str`
Formats numbers into human-readable form with suffix (K, M, B, T, Q).

**Location:** `utils/misc.py` (line 6)

**Parameters:**
- `n` (float|None): Number to format
- `decimals` (int): Decimal places to show (default: 1)
- `system` (str|list): Numbering system
  - `"finance"`: ["", "k", "M", "B", "T", "Q"] with base 1000
  - `"si"`: SI units ["", "k", "M", "G", "T", "P", "E"] with base 1000
  - `"iec"`: Binary units ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei"] with base 1024
  - Custom list: User-provided suffix list
- `signed` (bool): Add "+" prefix for positive numbers
- `unit` (str): Unit string to append (e.g., "bps", "mm")
- `strip_zeros` (bool): Remove trailing zeros and decimal point
- `rounding` (str): `"half_up"` (default) or `"bankers"` rounding

**Returns:**
- `str`: Formatted number with suffix and optional unit

**Handles Edge Cases:**
- Returns string representation for None, NaN, and Inf values
- Uses Decimal arithmetic for precise "half up" rounding

**Examples:**
```python
from utils.misc import human_format

# Basic formatting
human_format(100000)                                  # "100k"
human_format(1523400, decimals=1)                   # "1.5M"
human_format(-9876, decimals=2)                     # "-9.88k"

# Different systems
human_format(1536, system="iec")                    # "1.5Ki"
human_format(1000000, system="si")                  # "1M"

# With units and flags
human_format(100000, unit="bps")                    # "100kbps"
human_format(500, signed=True)                      # "+500"
human_format(1.23450, strip_zeros=False, decimals=4)  # "1.2345"

# Custom suffix system
custom = ["", "thousand", "million"]
human_format(500000, system=custom)                 # "500thousand"
```

**Use Cases in ARBS:**
- Formatting BPV (basis point value) in IR Swap queries
- Formatting notional amounts and market data
- Creating human-readable report outputs

---

## Time and Date Manipulation Functions

### Tenor Conversion Functions

#### `tenor_to_ql_period(tenor: str) -> ql.Period`
Converts a tenor string to a QuantLib Period object.

**Location:** `utils/ql_utils.py` (line 71)

**Parameters:**
- `tenor` (str): Tenor string in format "[number][unit]"
  - Units: "D" (days), "W" (weeks), "M" (months), "Y" (years)
  - Examples: "1D", "3M", "5Y", "2W"

**Returns:**
- `ql.Period`: QuantLib period object

**Error Handling:**
- Raises `ValueError` if unit is not in ['D', 'W', 'M', 'Y']

**Example:**
```python
from utils.ql_utils import tenor_to_ql_period

period_3m = tenor_to_ql_period("3M")      # ql.Period(3, ql.Months)
period_5y = tenor_to_ql_period("5Y")      # ql.Period(5, ql.Years)
period_1w = tenor_to_ql_period("1W")      # ql.Period(1, ql.Weeks)
```

#### `tenor_to_years(tenor: str) -> float`
Converts a tenor string to years (fractional).

**Location:** `utils/ql_utils.py` (line 128)

**Parameters:**
- `tenor` (str): Tenor string with unit suffix

**Returns:**
- `float`: Fractional years
  - D: number / 360
  - W: number / 52
  - M: number / 12
  - Y: number

**Example:**
```python
from utils.ql_utils import tenor_to_years

tenor_to_years("3M")      # 0.25
tenor_to_years("6M")      # 0.5
tenor_to_years("2Y")      # 2.0
tenor_to_years("1W")      # 0.019... (1/52)
```

#### `parse_tenor_string(tenor_str: str) -> ql.Period`
Parses tenor strings containing only months or years.

**Location:** `utils/ql_utils.py` (line 253)

**Parameters:**
- `tenor_str` (str): Tenor string ending in "M" or "Y"

**Returns:**
- `ql.Period`: QuantLib period

**Supported Formats:**
- "3M", "12M" → ql.Period(n, ql.Months)
- "5Y", "10Y" → ql.Period(n, ql.Years)

**Example:**
```python
from utils.ql_utils import parse_tenor_string

period = parse_tenor_string("5Y")  # ql.Period(5, ql.Years)
```

#### `month_to_label(month: int) -> str`
Converts month count to tenor label.

**Location:** `utils/ql_utils.py` (line 87)

**Parameters:**
- `month` (int): Number of months

**Returns:**
- `str`: Formatted as "nM" if ≤12 months, else "nY" (years)

**Example:**
```python
from utils.ql_utils import month_to_label

month_to_label(6)       # "6M"
month_to_label(12)      # "12M"
month_to_label(24)      # "2Y"
month_to_label(36)      # "3Y"
```

### Period Conversion Functions

#### `ql_period_to_years(period: ql.Period, day_counter: ql.DayCounter, as_of: datetime) -> float`
Converts a QuantLib period to a year fraction based on a day counter and reference date.

**Location:** `utils/ql_utils.py` (line 91)

**Parameters:**
- `period` (ql.Period): QuantLib period
- `day_counter` (ql.DayCounter): Day counting convention (Actual/365, 30/360, etc.)
- `as_of` (datetime): Reference date for calculation

**Returns:**
- `float`: Year fraction following the day counter convention

**Example:**
```python
from utils.ql_utils import ql_period_to_years
from datetime import datetime

period = ql.Period(3, ql.Months)
day_counter = ql.Actual365Fixed()
ref_date = datetime(2024, 1, 15)
years = ql_period_to_years(period, day_counter, ref_date)
```

#### `ql_period_to_months(p: ql.Period) -> int`
Converts a QuantLib period to months (approximation for days/weeks).

**Location:** `utils/ql_utils.py` (line 96)

**Parameters:**
- `p` (ql.Period): QuantLib period

**Returns:**
- `int`: Approximate month count
  - Years: multiply by 12
  - Months: return as-is
  - Weeks: divide by 4.345 (1 month ≈ 4.345 weeks)
  - Days: divide by 30 (1 month ≈ 30 days)

**Example:**
```python
from utils.ql_utils import ql_period_to_months

ql_period_to_months(ql.Period(3, ql.Months))   # 3
ql_period_to_months(ql.Period(2, ql.Years))    # 24
ql_period_to_months(ql.Period(8, ql.Weeks))    # ~2
```

#### `period_to_months(period: ql.Period) -> float`
Converts QuantLib period (Months or Years) to integer months.

**Location:** `utils/ql_utils.py` (line 244)

**Parameters:**
- `period` (ql.Period): Period with units of Months or Years only

**Returns:**
- `float`: Month count

**Example:**
```python
from utils.ql_utils import period_to_months

period_to_months(ql.Period(12, ql.Months))   # 12
period_to_months(ql.Period(2, ql.Years))     # 24
```

#### `period_to_string(period: ql.Period) -> str`
Converts a QuantLib period to string representation.

**Location:** `utils/ql_utils.py` (line 235)

**Parameters:**
- `period` (ql.Period): QuantLib period with Months or Years units

**Returns:**
- `str`: Formatted as "nM" or "nY"

**Example:**
```python
from utils.ql_utils import period_to_string

period_to_string(ql.Period(5, ql.Months))    # "5M"
period_to_string(ql.Period(3, ql.Years))     # "3Y"
```

### Date Calculation Functions

#### `difference_in_ymd(start: ql.Date, end: ql.Date) -> Tuple[int, int, int]`
Calculates the difference between two dates in years, months, and days.

**Location:** `utils/ql_utils.py` (line 143)

**Parameters:**
- `start` (ql.Date): Start date
- `end` (ql.Date): End date

**Returns:**
- `Tuple[int, int, int]`: (years, months, days)

**Algorithm:**
- Calculates year/month/day differences
- Handles negative days by borrowing from the previous month
- Handles negative months by borrowing from the year

**Example:**
```python
from utils.ql_utils import difference_in_ymd

start = ql.Date(15, ql.January, 2020)
end = ql.Date(20, ql.April, 2023)
years, months, days = difference_in_ymd(start, end)
# Returns: (3, 3, 5) for 3 years, 3 months, 5 days
```

#### `dates_to_string_tenor(effective_date: datetime, expiration_date: datetime, cal: ql.Calendar) -> str`
Converts a date range to a tenor string with intelligent rounding.

**Location:** `utils/ql_utils.py` (line 167)

**Parameters:**
- `effective_date` (datetime): Start date
- `expiration_date` (datetime): End date
- `cal` (ql.Calendar): Calendar for business day adjustments (default: US Treasury)

**Returns:**
- `str`: Tenor string (e.g., "3M", "2Y3M", "5Y") or "0D"/"NaN"

**Rounding Rules:**
- Days > 15 → round up to an additional month
- Months >= 11 → round up to an additional year
- If no nonzero component → "0D"

**Error Handling:**
- Returns "NaN" on exception
- Auto-adjusts non-business days to following business day

**Example:**
```python
from utils.ql_utils import dates_to_string_tenor
from datetime import datetime

eff = datetime(2024, 1, 15)
exp = datetime(2024, 4, 20)
tenor = dates_to_string_tenor(eff, exp)
# Returns: "3M" (approximately 3 months)
```

#### `tenor_from_dates(start: ql.Date, end: ql.Date) -> ql.Period`
Converts two dates to a QuantLib Period.

**Location:** `utils/ql_utils.py` (line 290)

**Parameters:**
- `start` (ql.Date): Start date
- `end` (ql.Date): End date

**Returns:**
- `ql.Period`: Combined period (Years + Months, or Years, or Months, or 0D)

**Example:**
```python
from utils.ql_utils import tenor_from_dates

start = ql.Date(15, ql.January, 2024)
end = ql.Date(15, ql.April, 2027)
period = tenor_from_dates(start, end)
# Returns: Period(3, Years) + Period(3, Months)
```

#### `get_bdates_between(start_date: datetime, end_date: datetime, calendar: ql.Calendar) -> List[datetime]`
Returns all business days between two dates (inclusive).

**Location:** `utils/ql_utils.py` (line 214)

**Parameters:**
- `start_date` (datetime): Start date
- `end_date` (datetime): End date (inclusive)
- `calendar` (ql.Calendar): Calendar for business day rules

**Returns:**
- `List[datetime]`: All business dates in range

**Example:**
```python
from utils.ql_utils import get_bdates_between
from datetime import datetime

cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
start = datetime(2024, 1, 1)
end = datetime(2024, 1, 31)
bdays = get_bdates_between(start, end, cal)
# Returns list of business days in January 2024
```

#### `datetime_today_utc() -> datetime`
Returns today's date at midnight UTC.

**Location:** `utils/ql_utils.py` (line 225)

**Returns:**
- `datetime`: Today's date at 00:00 UTC

**Example:**
```python
from utils.ql_utils import datetime_today_utc

today = datetime_today_utc()
# Returns: datetime(2024, 1, 15, 0, 0) if today is Jan 15, 2024
```

### Frequency Parsing

#### `parse_frequency(frequency: str) -> Tuple[int, ql.TimeUnit]`
Parses frequency strings like "3M", "2Y" into number and unit.

**Location:** `utils/ql_utils.py` (line 112)

**Parameters:**
- `frequency` (str): Frequency string with embedded number and letter unit

**Returns:**
- `Tuple[int, ql.TimeUnit]`: (number, QL unit enum)
  - Y → ql.Years
  - M → ql.Months
  - D → ql.Days
  - W → ql.Weeks

**Example:**
```python
from utils.ql_utils import parse_frequency

num, unit = parse_frequency("3M")
# Returns: (3, ql.Months)

num, unit = parse_frequency("10Y")
# Returns: (10, ql.Years)
```

---

## Data Structure Utilities

### Configuration and Serialization

#### `make_hashable(x) -> hashable`
Converts nested structures (lists, dicts, sets, callables) to hashable tuples.

**Location:** `Caching/utils.py` (line 13)

**Parameters:**
- `x`: Any Python object

**Returns:**
- `hashable`: Recursively converted to tuples, with safe slug names for callables

**Handles:**
- Lists/Tuples → nested tuples
- Dicts → sorted tuple of (key, value) pairs
- Sets → sorted tuple of elements
- Callables → `module.qualname` slug
- Strings → ASCII-safe filename slug
- Primitives → returned as-is

**Example:**
```python
from Caching.utils import make_hashable

config = {
    "func": my_function,
    "params": [1, 2, 3],
    "nested": {"a": 1, "b": 2}
}
hashable_cfg = make_hashable(config)
# Converts to nested tuple structure suitable for hashing
```

#### `to_filename_key(cfg: dict, max_len: int = 120) -> str`
Converts a config dict to a filename-safe string key.

**Location:** `Caching/utils.py` (line 28)

**Parameters:**
- `cfg` (dict): Configuration dictionary
- `max_len` (int): Maximum filename length (default: 120)

**Returns:**
- `str`: Filename-safe slug
  - If ≤ max_len: JSON representation as slug
  - If > max_len: Truncated slug + SHA1 hash

**Example:**
```python
from Caching.utils import to_filename_key

config = {
    "model": "black_scholes",
    "spot": 100.0,
    "rate": 0.05
}
key = to_filename_key(config)
# Returns: "model_black_scholes_spot_100_rate_0_05" (or truncated with hash)
```

### Interpolation Functions

#### `_encode_interp1d(f: interp1d) -> Tuple[List[float], List[float], Dict[str, Any]]`
Serializes a scipy interpolation function to JSON-compatible format.

**Location:** `Caching/utils.py` (line 45)

**Parameters:**
- `f` (interp1d): scipy.interpolate.interp1d function

**Returns:**
- `Tuple`: (x_points, y_points, kwargs_dict)

**Handles API Drift:**
- Uses `_get()` helper to access both public and private attributes
- Works with different scipy versions

**Example:**
```python
from Caching.utils import _encode_interp1d
from scipy.interpolate import interp1d
import numpy as np

x = np.array([1, 2, 3, 4])
y = np.array([2, 4, 6, 8])
f = interp1d(x, y, kind='cubic')
x_pts, y_pts, kwargs = _encode_interp1d(f)
# Can now serialize to JSON/cache
```

#### `_decode_interp1d(state: Tuple[List[float], List[float], Dict]) -> interp1d`
Deserializes interpolation function state back to scipy interp1d.

**Location:** `Caching/utils.py` (line 59)

**Parameters:**
- `state`: Tuple from `_encode_interp1d()`

**Returns:**
- `interp1d`: Reconstructed scipy interpolation function

**Compatibility:**
- Handles old "spline" kind → converts to "cubic"

**Example:**
```python
from Caching.utils import _decode_interp1d

state = (x_pts, y_pts, kwargs)
f_restored = _decode_interp1d(state)
# Use f_restored(new_x_value) to interpolate
```

---

## Plotting and Visualization Utilities

### Secondary Axis Plotting Functions

The `TB/utils.py` module provides sophisticated plotting utilities for creating dual-axis plots in matplotlib and Plotly.

#### `make_secondary_axis_plot_v1(ylabel_left=None, ylabel_right=None, title=None)`
Creates a dual-axis plot where each subsequent series alternates axes.

**Location:** `TB/utils.py` (line 45)

**Returns:** `Tuple[plot_func, fig, ax_left, ax_right, legend_func]`

**Components:**
- `plot(series, *, label=None, which='auto'|'left'|'right', **kwargs)`
  - `series`: pandas.Series
  - `which='auto'`: First call uses left axis, subsequent calls use right axis
  - `which='left'`: Force left axis
  - `which='right'`: Force right axis
  
- `legend(loc='best', **kwargs)`: Creates combined legend from both axes

**Features:**
- Automatic color cycling across both axes
- Color-coded y-axis labels and ticks to match first line on each axis
- Shared color cycle

**Example:**
```python
from TB.utils import make_secondary_axis_plot_v1
import pandas as pd

plot, fig, ax_left, ax_right, legend = make_secondary_axis_plot_v1(
    ylabel_left="Rate (%)",
    ylabel_right="Price ($)",
    title="Yield and Price"
)

# Plot first series on left axis
plot(series1, label="10Y Yield")
# Plot second series on right axis automatically
plot(series2, label="10Y Price")

legend(loc='upper left')
plt.show()
```

#### `make_secondary_axis_plot_v2(ylabel_left=None, ylabel_right=None, title=None)`
Creates a dual-axis plot with independent right axes for each series.

**Location:** `TB/utils.py` (line 133)

**Returns:** `Tuple[plot_func, fig, ax_left, ax_right, legend_func]`

**Components:**
- `plot(series, *, label=None, which='left'|'right', **kwargs)`
  - Each call with `which='right'` creates a NEW independent right axis
  - Supports unlimited right-axis series
  
- `legend(loc='best', valfmt='{:.2f}', show_date=False, sep=' — ', **kwargs)`
  - `valfmt`: Format string for most recent value
  - `show_date`: Include timestamp of latest observation
  - `sep`: Separator between label and value

**Features:**
- Multiple right-axis support with offset positioning
- Latest value annotation in legend
- Date-aware timezone formatting
- Automatic frame positioning for multiple axes

**Example:**
```python
from TB.utils import make_secondary_axis_plot_v2
import pandas as pd

plot, fig, ax_left, ax_right, legend = make_secondary_axis_plot_v2(
    ylabel_left="Yield (%)",
    title="Multi-Tenor Yields"
)

plot(yields_2y, label="2Y", which='left')
plot(yields_5y, label="5Y", which='right')
plot(yields_10y, label="10Y", which='right')

legend(loc='best', valfmt='{:.3f}', show_date=True)
plt.show()
```

#### `timeseries_df_plotter(df, cols_to_plot, cols_to_plot_raxis=None, use_plotly=False, custom_title=None, yaxis_title=None, yaxis_title_r=None, stds=None, plot_zscores=False, entry_date=None, entry_level=None)`
Comprehensive timeseries plotting function for matplotlib or Plotly.

**Location:** `TB/utils.py` (line 261)

**Parameters:**
- `df` (pd.DataFrame): Must have DatetimeIndex
- `cols_to_plot` (List[str]): Columns for left y-axis
- `cols_to_plot_raxis` (List[str]): Columns for right y-axis
- `use_plotly` (bool): Use Plotly instead of matplotlib
- `custom_title` (str): Plot title
- `yaxis_title` (str): Left y-axis label
- `yaxis_title_r` (str): Right y-axis label
- `stds` (Dict[str, Union[List[int], Tuple[List[int], DateLike]]])`:
  - Column → list of standard deviations to plot
  - Or: Column → (std_list, reference_date) for ex-post calculation
  - Automatically plots mean and ±N std bands
- `plot_zscores` (bool): Normalize to z-scores
- `entry_date` (DateLike): Vertical line at entry point
- `entry_level` (float): Horizontal line at entry level

**Features (Matplotlib):**
- Dual-axis support with automatic date formatting
- Statistical bands (mean ± std deviations)
- Entry point visualization
- Automatic legend with latest values
- Grid and date tick locator

**Features (Plotly):**
- Interactive hover with timezone-aware formatting
- Drawing tools (lines, shapes, etc.)
- Spike lines for crosshair cursor
- Dark theme
- HTML export-ready

**Example:**
```python
from TB.utils import timeseries_df_plotter
import pandas as pd

# Create sample data
dates = pd.date_range('2023-01-01', periods=100, freq='D')
df = pd.DataFrame({
    '10Y': np.random.randn(100).cumsum(),
    '5Y': np.random.randn(100).cumsum(),
    'Spread': np.random.randn(100).cumsum()
}, index=dates)

# Plot with standard deviations
timeseries_df_plotter(
    df,
    cols_to_plot=['10Y', '5Y'],
    cols_to_plot_raxis=['Spread'],
    custom_title="Yield Curve Analysis",
    stds={'Spread': [1, 2]},  # ±1σ and ±2σ bands
    entry_date=dates[30],
    entry_level=0.5,
    use_plotly=False
)
```

### Data Canonicalization

#### `_canonicalize_value(v) -> hashable`
Converts Python objects to JSON-serializable canonical forms.

**Location:** `TB/utils.py` (line 32)

**Handles:**
- Dates/Datetimes → ISO format strings (UTC naive)
- Enums → enum.name string
- Lists/Tuples → recursively canonicalized
- Dicts → sorted keys, recursively canonicalized values
- Primitives → as-is

**Example:**
```python
from TB.utils import _canonicalize_value
from datetime import datetime
from enum import Enum

class Color(Enum):
    RED = 1
    BLUE = 2

value = {
    "date": datetime(2024, 1, 15, 12, 30),
    "color": Color.RED,
    "values": [1, 2, 3]
}
canonical = _canonicalize_value(value)
# Returns: {"color": "RED", "date": "2024-01-15T12:30:00", "values": [1, 2, 3]}
```

#### `_to_utc_naive(dt: DateLike) -> datetime`
Converts any date/datetime to UTC naive (removes timezone info).

**Location:** `TB/utils.py` (line 19)

**Parameters:**
- `dt`: Python date or datetime (with or without timezone)

**Returns:**
- `datetime`: UTC naive datetime (timezone removed)

#### `_dt_to_epoch_ns(dt: DateLike) -> int`
Converts datetime to Unix epoch in nanoseconds.

**Location:** `TB/utils.py` (line 27)

**Parameters:**
- `dt`: Date or datetime object

**Returns:**
- `int`: Nanoseconds since Unix epoch (1970-01-01 00:00:00 UTC)

---

## Curve Building Utilities

### Discount Curve Construction

#### `build_ql_discount_curve(datetime_series, discount_factor_series, ql_dc, ql_cal, interpolation_algo=None) -> ql.DiscountCurve`
Builds a QuantLib discount curve from points.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 11)

**Parameters:**
- `datetime_series` (pd.Series): Dates for curve points
- `discount_factor_series` (pd.Series): Corresponding discount factors
- `ql_dc` (ql.DayCounter): Day counter convention
- `ql_cal` (ql.Calendar): Calendar for settlement dates
- `interpolation_algo` (str): Interpolation method (default: "df_log_linear")

**Interpolation Algorithms:**
- `"df_log_linear"`: Log-linear discount curve
- `"df_mono_log_cubic"`: Monotonic log-cubic
- `"df_natural_cubic"`: Natural cubic
- `"df_kruger_log"`: Kruger log discount
- `"df_natural_log_cubic"`: Natural log cubic
- `"df_log_mixed_linear"`: Log mixed linear-cubic
- `"df_log_parabolic_cubic"`: Log parabolic cubic
- `"df_mono_log_parabolic_cubic"`: Monotonic log parabolic cubic

**Returns:**
- `ql.DiscountCurve`: Constructed curve with extrapolation enabled

**Error Handling:**
- Raises `ValueError` if interpolation algorithm not found

**Example:**
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_ql_discount_curve
import pandas as pd
import QuantLib as ql

dates = pd.Series([datetime(2024, 1, 15), datetime(2024, 4, 15), datetime(2025, 1, 15)])
dfs = pd.Series([0.99, 0.97, 0.95])
day_counter = ql.Actual365Fixed()
calendar = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

curve = build_ql_discount_curve(
    dates, dfs, day_counter, calendar,
    interpolation_algo="df_log_linear"
)
```

#### `build_piecewise_ql_discount_curve(swap_rate_helpers, ql_dc, ql_cal, settlement_day, interpolation_algo=None) -> ql.DiscountCurve`
Builds a piecewise discount curve from rate helpers (market instruments).

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 52)

**Parameters:**
- `swap_rate_helpers` (List[ql.RateHelper]): Market instrument helpers
- `ql_dc` (ql.DayCounter): Day counter
- `ql_cal` (ql.Calendar): Calendar
- `settlement_day` (int): Settlement lag in days
- `interpolation_algo` (str): Interpolation method (default: "pdf_log_linear")

**Interpolation Algorithms:**
- `"pdf_log_linear"`: PiecewiseLogLinearDiscount
- `"pdf_mono_log_cubic"`: PiecewiseLogCubicDiscount
- `"pdf_natural_cubic"`: PiecewiseNaturalCubicZero
- `"pdf_kruger_log"`: PiecewiseKrugerLogDiscount
- `"pdf_natural_log_cubic"`: PiecewiseNaturalLogCubicDiscount
- `"pdf_log_mixed_linear"`: PiecewiseLogMixedLinearCubicDiscount
- `"pdf_log_parabolic_cubic"`: PiecewiseLogParabolicCubicDiscount
- `"pdf_spline_cubic_discount"`: PiecewiseSplineCubicDiscount
- `"pdf_mono_log_parabolic_cubic"`: PiecewiseMonotonicLogParabolicCubicDiscount

**Returns:**
- `ql.DiscountCurve`: Fitted discount curve

**Example:**
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_piecewise_ql_discount_curve

curve = build_piecewise_ql_discount_curve(
    swap_rate_helpers,
    day_counter,
    calendar,
    settlement_day=2,
    interpolation_algo="pdf_log_linear"
)
```

#### `build_ql_zero_curve(datetime_series, zero_rate_series, ql_dc, ql_cal, interpolation_algo=None) -> ql.ZeroCurve`
Builds a zero (spot) curve from zero rates.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 92)

**Parameters:**
- `datetime_series` (pd.Series): Curve dates
- `zero_rate_series` (pd.Series): Zero rates (annual, as decimal)
- `ql_dc` (ql.DayCounter): Day counter
- `ql_cal` (ql.Calendar): Calendar
- `interpolation_algo` (str): Interpolation (default: "z_log_linear")

**Interpolation Algorithms:**
- `"z_linear"`: Linear interpolation
- `"z_log_linear"`: Log-linear
- `"z_cubic"`: Cubic
- `"z_natural_cubic"`: Natural cubic
- `"z_log_cubic"`: Log cubic
- `"z_monotonic_cubic"`: Monotonic cubic
- `"z_kruger"`: Kruger
- `"z_parabolic_cubic"`: Parabolic cubic
- `"z_monotonic_parabolic_cubic"`: Monotonic parabolic cubic

**Returns:**
- `ql.ZeroCurve`: Zero curve

**Example:**
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_ql_zero_curve

zero_curve = build_ql_zero_curve(
    dates, zero_rates, day_counter, calendar,
    interpolation_algo="z_log_linear"
)
```

### Curve Node Extraction

#### `extract_fitted_curve_nodes(fitted_curve, num_points=10000) -> Dict[datetime, float]`
Extracts discount factor nodes from a fitted curve across a fine grid.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 135)

**Parameters:**
- `fitted_curve` (ql.YieldTermStructure): Any term structure
- `num_points` (int): Grid points to extract (default: 10000)

**Returns:**
- `Dict[datetime, float]`: Date → discount factor mapping

**Method:**
- Uses numpy.linspace on serial numbers for uniform grid
- Evaluates curve at each point

#### `get_nodes_dict(ql_curve, to_ttm=False, to_iso=False) -> Dict`
Extracts curve nodes in flexible formats.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 143)

**Parameters:**
- `ql_curve`: QuantLib yield term structure or discount curve
- `to_ttm` (bool): Return time-to-maturity as key (uses day counter)
- `to_iso` (bool): Return ISO-format date strings

**Returns:**
- `Dict`: 
  - Keys: datetime, float (TTM), or ISO string
  - Values: discount factors

**Implementation:**
- Tries `.nodes()` first
- Falls back to `.dates()` and `.discounts()`
- Uses `extract_fitted_curve_nodes()` as last resort
- Returns None on exception

**Example:**
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import get_nodes_dict

# Default: datetime → discount factor
nodes = get_nodes_dict(curve)

# Time-to-maturity → discount factor
ttm_nodes = get_nodes_dict(curve, to_ttm=True)

# ISO date string → discount factor
iso_nodes = get_nodes_dict(curve, to_iso=True)
```

#### `build_discount_curve_from_nodes(ql_curve_nodes, ql_dc, ql_cal, interpolation_algo) -> ql.DiscountCurve`
Rebuilds a curve from previously extracted nodes.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 171)

**Parameters:**
- `ql_curve_nodes` (Dict): datetime/date → discount factor
- `ql_dc` (ql.DayCounter): Day counter
- `ql_cal` (ql.Calendar): Calendar
- `interpolation_algo` (str): Interpolation algorithm

**Returns:**
- `ql.DiscountCurve`: Reconstructed curve or None on error

**Handles:**
- datetime objects
- date objects
- ISO-format date strings (converted via pd.Timestamp)

#### `get_fixings_dict(swap_index) -> Dict[datetime, float]`
Extracts historical fixings from a QuantLib swap index.

**Location:** `Query/IRSwaps/backends/quantlib/ql_curve_building_utils.py` (line 199)

**Parameters:**
- `swap_index` (ql.SwapIndex): Swap index (e.g., SOFR, LIBOR)

**Returns:**
- `Dict[datetime, float]`: Date → fixing value (excludes NaN)

**Example:**
```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import get_fixings_dict

sofr_index = ql.SOFR()
fixings = get_fixings_dict(sofr_index)
# Returns dict of historical SOFR fixings
```

---

## Seasonality Analysis Utilities

#### `monthend_cumsum_seasonality(df, value_col=None, window=5, business_month_end=True, cal=None, relative_to="month_end", metric="abs", baseline_fallback="first_valid") -> pd.DataFrame`
Analyzes month-end and quarter-end seasonality patterns.

**Location:** `RVUtils/seasonality_utils.py` (line 6)

**Parameters:**
- `df` (pd.DataFrame): Input data (single or multi-column)
- `value_col` (str): Column to analyze (auto-detected if single column)
- `window` (int): Days before/after month-end anchor (default: 5)
- `business_month_end` (bool): Use calendar's business month-end, not calendar month-end
- `cal` (ql.Calendar): Calendar for month-end dates (default: US Treasury)
- `relative_to` (str): 
  - `"month_end"`: Anchor relative to month-end (0)
  - Other values: Anchor to different point (-window)
- `metric` (str):
  - `"abs"`: Absolute changes
  - `"pct"`: Percentage changes
  - `"bps"`: Basis points (× 10,000)
- `baseline_fallback` (str): How to fill missing baseline values

**Returns:**
- `pd.DataFrame`: 
  - Rows: Day index relative to month/quarter end (-window to +window)
  - Columns:
    - `"avg"`: Overall average across all months
    - `"avg±stdN"`: Average ± N standard deviations
    - `"avg-{month}"`: By-month averages (jan, feb, ..., dec)
    - `"avg-{qend}"`: Quarter-end averages (q1-end, q2-end, etc.)
    - Individual month/quarter columns with raw observations

**Features:**
- Automatic UTC normalization
- Handles duplicate indices (keeps last)
- Accounts for varying month lengths
- Standard deviation bands (±1σ, ±2σ)
- Month-specific and quarter-end-specific seasonality

**Example:**
```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality
import pandas as pd
import QuantLib as ql

# Sample data: daily closing prices
dates = pd.date_range('2020-01-01', periods=1000, freq='D')
prices = pd.DataFrame(100 + np.random.randn(1000).cumsum(), index=dates, columns=['price'])

# Analyze month-end seasonality
seasonality = monthend_cumsum_seasonality(
    prices,
    value_col='price',
    window=5,
    business_month_end=True,
    cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    relative_to='month_end',
    metric='abs'
)

# View results
print(seasonality)
# Rows: -5 to +5 (days relative to month-end)
# Columns: avg, avg±std1, avg±std2, avg-jan, avg-feb, ..., individual months
```

**Output Interpretation:**
- `avg` at row 0: Average change on the month-end day
- `avg-jan`: Seasonal pattern in January month-ends
- `avg-q1-end` (row 3): Seasonal pattern for quarter-end months (Mar, Jun, Sep, Dec)
- Helps identify month-end flows and quarter-end rebalancing effects

---

## Configuration Utilities

### Swap Tenor Configuration

#### `DEFAULT_SWAP_TENORS` (Constant)
Standard IR swap tenors used across the ARBS system.

**Location:** `utils/ql_utils.py` (line 8)

**Values:**
```python
[
    "1D", "1W", "2W", "3W",
    "1M", "2M", "3M", "4M", "5M", "6M", "9M", "12M",
    "18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y",
    "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y"
]
```

**Usage:**
```python
from utils.ql_utils import DEFAULT_SWAP_TENORS

for tenor in DEFAULT_SWAP_TENORS:
    # Process each standard tenor
    period = tenor_to_ql_period(tenor)
```

---

## Error Handling Patterns

The utilities implement consistent error handling patterns:

### 1. **ValueError for Invalid Inputs**

Used when function receives logically invalid parameters:

```python
# ql_utils.py - tenor_to_ql_period
def tenor_to_ql_period(tenor):
    unit = tenor[-1]
    value = int(tenor[:-1])
    if unit == "D":
        return ql.Period(value, ql.Days)
    # ...
    else:
        raise ValueError("Invalid tenor unit. Must be one of 'D', 'W', 'M', 'Y'.")
```

### 2. **Try-Except with Fallback Return**

Used for operations that might fail gracefully:

```python
# ql_utils.py - dates_to_string_tenor
def dates_to_string_tenor(effective_date, expiration_date, cal=...):
    try:
        # ... date conversion logic ...
        return tenor
    except Exception as e:
        return "NaN"
```

### 3. **Exception Logging and Silent Failure**

Used in curve extraction functions:

```python
# ql_curve_building_utils.py - get_nodes_dict
def get_nodes_dict(ql_curve, to_ttm=False, to_iso=False):
    try:
        # ... extraction logic ...
        return nodes_dict
    except Exception as e:
        print(f"Couldn't Extract Curve Nodes: {e}")
        return None
```

### 4. **Type-Specific Checks**

The `build_discount_curve_from_nodes` function validates date types:

```python
for k in ql_curve_nodes.keys():
    if isinstance(k, datetime) or isinstance(k, date):
        dates.append(k)
    elif isinstance(k, str):
        try:
            dates.append(pd.Timestamp(k))
        except Exception as e:
            raise ValueError(f"Bad date string {k!r}: {e}") from None
    else:
        raise TypeError(f"Unsupported key type {type(k)}: {k!r}")
```

### 5. **None Handling in Formatting**

The `human_format` function handles edge cases:

```python
def human_format(n, ...):
    if n is None or (isinstance(n, float) and (math.isnan(n) or math.isinf(n))):
        return str(n)  # Return string representation
    # ... normal formatting ...
```

---

## Common Utility Functions

### Function Usage Frequency in ARBS

**Most Used:**
1. `datetime_to_ql_date()` - Date object conversions
2. `tenor_to_ql_period()` - Tenor string parsing
3. `human_format()` - Financial quantity formatting
4. `most_recent_business_day_ql()` - Date navigation

**Frequently Used:**
5. `ql_date_to_datetime()` - Reverse date conversion
6. `dates_to_string_tenor()` - Date range to tenor
7. `get_nodes_dict()` - Curve node extraction
8. `build_ql_discount_curve()` - Curve construction

**Common in Specific Modules:**
- `monthend_cumsum_seasonality()` - RV analysis
- `timeseries_df_plotter()` - Backtesting reports
- `get_bdates_between()` - Date range operations
- `parse_tenor_string()` - Configuration parsing

### Cross-Module Dependencies

```
Query/IRSwaps/ 
  ├─ imports utils.misc.human_format
  └─ imports utils.ql_utils.datetime_to_ql_date

TB/
  ├─ imports utils.ql_utils.datetime_to_ql_date
  └─ uses TB.utils.timeseries_df_plotter internally

Query/IRSwaps/backends/quantlib/
  ├─ imports Query.IRSwaps.backends.quantlib.utils
  └─ imports Query.IRSwaps.backends.quantlib.ql_curve_building_utils

Caching/
  └─ uses Caching.utils for key generation

RVUtils/
  ├─ imports RVUtils.seasonality_utils
  └─ integrates with QuantLib calendars
```

---

## Usage Examples

### Example 1: Converting Dates and Creating Periods

```python
from datetime import datetime
from utils.ql_utils import (
    datetime_to_ql_date,
    ql_date_to_datetime,
    tenor_to_ql_period,
    tenor_from_dates
)
import QuantLib as ql

# Python datetime to QuantLib
py_date = datetime(2024, 3, 15, 10, 30)
ql_date = datetime_to_ql_date(py_date)
# Returns: ql.Date(15, March, 2024)

# QuantLib back to Python
back_to_py = ql_date_to_datetime(ql_date)
# Returns: datetime(2024, 3, 15, 0, 0)

# Parse tenor string
period = tenor_to_ql_period("5Y")  # ql.Period(5, Years)

# Calculate period between dates
start = datetime_to_ql_date(datetime(2024, 1, 15))
end = datetime_to_ql_date(datetime(2024, 4, 15))
period = tenor_from_dates(start, end)
```

### Example 2: Business Day Calculations

```python
from datetime import datetime, timedelta
from utils.ql_utils import (
    most_recent_business_day_ql,
    most_recent_business_day_from_date,
    get_bdates_between
)
import QuantLib as ql

cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)

# Most recent business day from today
last_bd = most_recent_business_day_ql(cal, tz="UTC", to_pydate=True)

# Most recent business day from a specific date
ref_date = datetime(2024, 1, 15)  # Could be a weekend
last_bd_from_ref = most_recent_business_day_from_date(ref_date, cal)

# All business days in a month
start = datetime(2024, 1, 1)
end = datetime(2024, 1, 31)
bdays = get_bdates_between(start, end, cal)
print(f"Business days in January 2024: {len(bdays)}")
```

### Example 3: Financial Formatting

```python
from utils.misc import human_format

# Format BPV (basis point value)
bpv = 12500  # $12,500 per basis point
formatted = human_format(bpv, decimals=1, unit="k/bp")
# Returns: "12.5k/bp"

# Format notional amount
notional = 50_000_000  # $50 million
formatted = human_format(notional, decimals=1, unit="mm")
# Returns: "50M" (50M * 1mm = 50Mmm)

# Format with custom system
price_in_cents = 10500
formatted = human_format(price_in_cents, system="iec")
# Returns: "10.3Ki"

# Signed values
change = 250
formatted = human_format(change, signed=True)
# Returns: "+250"
```

### Example 4: Building and Extracting Curves

```python
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import (
    build_ql_discount_curve,
    get_nodes_dict,
    extract_fitted_curve_nodes
)
import pandas as pd
import QuantLib as ql
from datetime import datetime

# Create sample curve data
dates = pd.Series([
    datetime(2024, 1, 15),
    datetime(2024, 4, 15),
    datetime(2024, 7, 15),
    datetime(2025, 1, 15),
])
discount_factors = pd.Series([0.9925, 0.9850, 0.9775, 0.9700])

# Build curve
dc = ql.Actual365Fixed()
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
curve = build_ql_discount_curve(
    dates, discount_factors, dc, cal,
    interpolation_algo="df_log_linear"
)

# Extract nodes for inspection
nodes = get_nodes_dict(curve, to_iso=False)
for date, df in nodes.items():
    print(f"  {date.date()}: {df:.6f}")

# Fine-grained extraction
fine_nodes = extract_fitted_curve_nodes(curve, num_points=100)
```

### Example 5: Tenor Conversions

```python
from utils.ql_utils import (
    tenor_to_years,
    tenor_to_ql_period,
    ql_period_to_months,
    period_to_string,
    parse_frequency
)

# Tenor to years (fractional)
years_3m = tenor_to_years("3M")      # 0.25
years_6m = tenor_to_years("6M")      # 0.5
years_2y = tenor_to_years("2Y")      # 2.0

# Tenor string to QuantLib period
period = tenor_to_ql_period("5Y3M")  # ql.Period(5, Years) + ql.Period(3, Months)

# Period to months
months = ql_period_to_months(period)  # Handles nested periods

# Period to string
tenor_str = period_to_string(ql.Period(5, ql.Years))  # "5Y"

# Parse frequency strings
num, unit = parse_frequency("3M")  # (3, ql.Months)
num, unit = parse_frequency("10Y")  # (10, ql.Years)
```

### Example 6: Dual-Axis Plotting

```python
from TB.utils import make_secondary_axis_plot_v2
import pandas as pd
import numpy as np

# Create sample yield data
dates = pd.date_range('2023-01-01', periods=250, freq='D')
yields_2y = pd.Series(
    3.5 + np.sin(np.arange(250) * 2 * np.pi / 250) * 0.5,
    index=dates,
    name='2Y Yield'
)
yields_10y = pd.Series(
    3.8 + np.cos(np.arange(250) * 2 * np.pi / 250) * 0.3,
    index=dates,
    name='10Y Yield'
)
spread = yields_10y - yields_2y
spread.name = '2-10 Spread'

# Create plot
plot, fig, ax_left, ax_right, legend = make_secondary_axis_plot_v2(
    ylabel_left="Yield (%)",
    ylabel_right="Spread (bps)",
    title="US Yield Curve Dynamics"
)

plot(yields_2y, which='left')
plot(yields_10y, which='left')
plot(spread * 100, which='right')  # Convert to bps

legend(loc='best', valfmt='{:.3f}%', show_date=True)
plt.show()
```

### Example 7: Seasonality Analysis

```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality
import pandas as pd
import numpy as np
import QuantLib as ql

# Create daily yield data for 5 years
dates = pd.date_range('2019-01-01', '2024-01-01', freq='D')
yields = pd.DataFrame(
    4.0 + np.random.randn(len(dates)).cumsum() * 0.01,
    index=dates,
    columns=['yield']
)

# Analyze month-end seasonality
seasonality = monthend_cumsum_seasonality(
    yields,
    window=5,
    business_month_end=True,
    cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    metric='bps'  # Show in basis points
)

# Display average pattern
print("Average Month-End Seasonality:")
print(seasonality[['avg', 'avg-std1', 'avg+std1']].round(2))

# Identify extreme months
print("\nJanuary Month-End Effect:")
jan_cols = [c for c in seasonality.columns if c.startswith('avg-jan')]
print(seasonality[jan_cols].round(2))
```

### Example 8: Configuration Key Generation

```python
from Caching.utils import to_filename_key, make_hashable

# Configuration that might be cached
config = {
    'model': 'black_scholes',
    'spot': 100.0,
    'volatility': 0.20,
    'rate': 0.05,
    'time_to_expiry': 1.0,
    'dividend_yield': 0.02
}

# Convert to hashable form
hashable_cfg = make_hashable(config)

# Generate filename key (safe for filesystem)
cache_key = to_filename_key(config, max_len=120)
print(f"Cache file: {cache_key}.pkl")  # Can be used as filename
```

### Example 9: Timeseries Analysis with Bands

```python
from TB.utils import timeseries_df_plotter
import pandas as pd
import numpy as np

# Create sample data with trend and noise
dates = pd.date_range('2023-01-01', periods=500, freq='D')
signal = pd.DataFrame({
    'spread_bps': 50 + np.cumsum(np.random.randn(500) * 2),
    'volume': 100 + np.cumsum(np.random.randn(500) * 5)
}, index=dates)

# Plot with standard deviation bands
timeseries_df_plotter(
    signal,
    cols_to_plot=['spread_bps'],
    cols_to_plot_raxis=['volume'],
    custom_title="Spread vs Volume",
    yaxis_title="Spread (bps)",
    yaxis_title_r="Volume (mm)",
    stds={'spread_bps': [1, 2]},  # ±1σ and ±2σ bands
    entry_date=dates[100],
    entry_level=50,
    use_plotly=False
)
```

---

## Dependencies

### Core Dependencies

| Module | Purpose | Used In |
|--------|---------|---------|
| `QuantLib` | Financial calculations, date operations | All QL utils |
| `pandas` | DataFrames, Series | All modules |
| `numpy` | Numerical operations | Curve extraction, seasonality |
| `datetime` | Python date/time | All date conversion |
| `zoneinfo` | Timezone handling | Business day calculations |

### Optional Dependencies

| Module | Purpose | Used In |
|--------|---------|---------|
| `matplotlib` | Plotting (v1) | TB/utils.py |
| `plotly` | Interactive plotting (v2) | TB/utils.py |
| `scipy` | Interpolation | Caching/utils.py |
| `decimal` | Precise rounding | misc.py |
| `ujson` | Fast JSON | Caching/utils.py |
| `tqdm` | Progress bars | TB/utils.py |

### Import Patterns

**Standard imports:**
```python
import QuantLib as ql
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Tuple
```

**Optional imports (with fallback):**
```python
try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
```

---

## Testing Utilities

### Unit Testing Examples

```python
# Test tenor conversion
def test_tenor_to_ql_period():
    from utils.ql_utils import tenor_to_ql_period
    
    period = tenor_to_ql_period("5Y")
    assert period.length() == 5
    assert period.units() == ql.Years
    
    with pytest.raises(ValueError):
        tenor_to_ql_period("5X")  # Invalid unit

# Test date conversion round-trip
def test_date_conversion_round_trip():
    from utils.ql_utils import datetime_to_ql_date, ql_date_to_datetime
    
    original = datetime(2024, 3, 15, 10, 30)
    ql_date = datetime_to_ql_date(original)
    result = ql_date_to_datetime(ql_date)
    
    assert result.year == 2024
    assert result.month == 3
    assert result.day == 15

# Test human format edge cases
def test_human_format_edge_cases():
    from utils.misc import human_format
    
    assert human_format(None) == 'None'
    assert human_format(float('nan')) == 'nan'
    assert human_format(float('inf')) == 'inf'
    assert human_format(0) == '0'
```

---

## Conclusion

The ARBS utilities module provides a comprehensive set of tools for:

1. **QuantLib Integration**: Seamless conversion between Python and QuantLib date/time objects
2. **Financial Formatting**: Human-readable formatting for financial quantities
3. **Tenor/Period Manipulation**: Flexible conversion between different tenor representations
4. **Date Operations**: Business day calculations and calendar-aware date handling
5. **Curve Building**: Construction and node extraction from yield term structures
6. **Visualization**: Sophisticated plotting with matplotlib and Plotly
7. **Data Serialization**: Hashable conversion and cache key generation
8. **Seasonality Analysis**: Month-end and quarter-end pattern analysis

These utilities are carefully designed with:
- **Consistent error handling**: ValueError for invalid inputs, try-except for edge cases
- **Flexible APIs**: Optional parameters with sensible defaults
- **Backward compatibility**: Multiple versions for different use cases
- **Type hints**: Clear parameter and return types
- **Documentation**: Docstrings and inline comments for complex logic

The module is widely used across ARBS for curve building, pricing, analysis, and reporting functionality.

