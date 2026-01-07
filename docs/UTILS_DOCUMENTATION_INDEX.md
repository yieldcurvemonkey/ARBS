# ARBS Utils Module Documentation - Complete Index

## Documentation Files Created

1. **UTILS_MODULE_DOCUMENTATION.md** (1,744 lines, 50KB)
   - Comprehensive reference for all utility functions
   - Detailed parameter descriptions and examples
   - Error handling patterns
   - Best practices and usage guidelines
   - **Best for:** In-depth learning and reference

2. **UTILS_QUICK_REFERENCE.md** (500+ lines)
   - Quick lookup for common operations
   - Function signature index
   - Conversion tables
   - Real-world examples
   - Troubleshooting guide
   - **Best for:** Quick lookups during development

---

## Module Map

### Core Utils (`utils/`)

#### `ql_utils.py` (307 lines)
**Purpose:** QuantLib integration, date/tenor operations, business day calculations

**Key Functions:**
- Date Conversions (4 functions)
  - `ql_date_to_datetime()`, `ql_date_to_pydate()`
  - `datetime_to_ql_date()`
  - Bidirectional conversion between Python datetime and QL.Date

- Tenor Parsing (6 functions)
  - `tenor_to_ql_period()` - String tenor to QuantLib Period
  - `tenor_to_years()` - Tenor string to decimal years
  - `parse_tenor_string()` - Limited format parsing
  - `parse_frequency()` - Frequency string parsing
  - `month_to_label()` - Month count to tenor label
  - `period_to_string()` - Period to tenor string

- Period Conversion (4 functions)
  - `ql_period_to_years()` - Using day counter
  - `ql_period_to_months()` - With approximations
  - `period_to_months()` - Direct conversion
  - `tenor_from_dates()` - Date range to period

- Date Calculations (5 functions)
  - `difference_in_ymd()` - Year/month/day difference
  - `dates_to_string_tenor()` - Smart tenor inference
  - `get_bdates_between()` - All business days in range
  - `datetime_today_utc()` - Today at midnight UTC
  - `most_recent_business_day_ql()` - Find last BD
  - `most_recent_business_day_from_date()` - From reference date

**Configuration:**
- `DEFAULT_SWAP_TENORS` - 38 standard IR swap tenors

#### `misc.py` (65 lines)
**Purpose:** Data formatting and structure utilities

**Key Functions:**
- `human_format()` - Format numbers with SI/finance/IEC suffixes
  - Supports None/NaN/Inf handling
  - Multiple number systems (finance, si, iec, custom)
  - Precise rounding (half-up vs banker's)
  - Optional signed (+) prefix and unit appending

---

### Query-Specific Utils (`Query/IRSwaps/backends/quantlib/`)

#### `utils.py` (52 lines)
**Purpose:** Query-level QuantLib utility functions

**Key Functions:**
- `ql_date_to_datetime()` - Duplicate of main utils
- `ql_date_to_pydate()` - Duplicate of main utils
- `datetime_to_ql_date()` - Duplicate of main utils
- `most_recent_business_day_ql()` - Duplicate of main utils

**Note:** These are convenience imports for the Query module.

#### `ql_curve_building_utils.py` (202 lines)
**Purpose:** Yield curve construction and node extraction

**Key Functions:**
- Curve Construction (3 functions)
  - `build_ql_discount_curve()` - From discount factors
  - `build_piecewise_ql_discount_curve()` - From rate helpers
  - `build_ql_zero_curve()` - From zero rates

- Interpolation Algorithms (28 variants)
  - Discount curves: 8 interpolation types
  - Piecewise curves: 9 interpolation types
  - Zero curves: 9 interpolation types

- Node Extraction (4 functions)
  - `extract_fitted_curve_nodes()` - Fine-grained grid extraction
  - `get_nodes_dict()` - Flexible format extraction (TTM, ISO, datetime)
  - `build_discount_curve_from_nodes()` - Curve reconstruction
  - `get_fixings_dict()` - Historical fixing extraction

---

### Visualization Utils (`TB/utils.py`) (487 lines)
**Purpose:** Matplotlib and Plotly plotting utilities

**Key Functions:**
- Dual-Axis Plotting (2 versions)
  - `make_secondary_axis_plot_v1()` - Alternating axes
  - `make_secondary_axis_plot_v2()` - Independent right axes
  - Features: automatic color cycling, legend integration

- Comprehensive Timeseries Plotter
  - `timeseries_df_plotter()` - Matplotlib or Plotly
  - Features:
    - Dual-axis support
    - Statistical bands (mean ± N std)
    - Z-score normalization
    - Entry point visualization
    - Timezone-aware formatting

- Data Canonicalization (3 helper functions)
  - `_canonicalize_value()` - Convert to JSON-serializable form
  - `_to_utc_naive()` - Remove timezone info
  - `_dt_to_epoch_ns()` - Unix epoch in nanoseconds

---

### Caching Utils (`Caching/utils.py`) (66 lines)
**Purpose:** Configuration serialization and cache key generation

**Key Functions:**
- Configuration Hashing
  - `make_hashable()` - Recursive hashable conversion
  - `to_filename_key()` - Filesystem-safe config keys
  - Handles: dicts, lists, sets, callables, primitives

- Interpolation Serialization (2 functions)
  - `_encode_interp1d()` - scipy interp1d to JSON-compatible
  - `_decode_interp1d()` - JSON state back to interp1d
  - Handles API version differences

---

### Seasonality Utils (`RVUtils/seasonality_utils.py`) (150 lines)
**Purpose:** Month-end and quarter-end seasonality analysis

**Key Functions:**
- `monthend_cumsum_seasonality()` - Comprehensive seasonality analysis
  - Features:
    - Month-end anchor selection (calendar vs business)
    - Multiple metrics (absolute, percentage, basis points)
    - Standard deviation bands (±1σ, ±2σ)
    - Month-specific and quarter-end-specific patterns
    - Window configuration (±N days around anchor)

---

## Function Classification

### By Frequency of Use

#### Very Frequent (Used in multiple modules)
1. `datetime_to_ql_date()` - Core date conversion
2. `ql_date_to_datetime()` - Core date conversion
3. `tenor_to_ql_period()` - Tenor parsing
4. `human_format()` - Display formatting
5. `most_recent_business_day_ql()` - Date navigation

#### Frequent (Used in specific domains)
6. `build_ql_discount_curve()` - Curve building
7. `get_nodes_dict()` - Curve extraction
8. `get_bdates_between()` - Date ranges
9. `dates_to_string_tenor()` - Date interpretation
10. `timeseries_df_plotter()` - Backtesting reports

#### Periodic (Used for specific tasks)
11. `monthend_cumsum_seasonality()` - RV analysis
12. `tenor_to_years()` - Conversion
13. `difference_in_ymd()` - Date math
14. `make_secondary_axis_plot_v2()` - Multi-axis plots
15. `build_piecewise_ql_discount_curve()` - Market curve fitting

#### Specialized (Internal/helper)
16. `_encode_interp1d()`, `_decode_interp1d()` - Caching
17. `make_hashable()`, `to_filename_key()` - Config serialization
18. `_canonicalize_value()` - Data canonicalization
19. `tenor_from_dates()` - Period inference
20. `extract_fitted_curve_nodes()` - Curve analysis

---

## By Task Type

### Date and Time Operations
```
Converting dates (QL ↔ Python)      → ql_date_to_datetime, datetime_to_ql_date
Finding business days               → most_recent_business_day_ql, get_bdates_between
Calculating date differences         → difference_in_ymd
Converting to tenor                 → dates_to_string_tenor, tenor_from_dates
Current UTC date                    → datetime_today_utc
```

### Tenor and Period Operations
```
String to Period                    → tenor_to_ql_period, parse_tenor_string
String to Years                     → tenor_to_years
Period to String                    → period_to_string
Period to Months/Years              → ql_period_to_months, ql_period_to_years
Month count to Tenor                → month_to_label
```

### Financial Formatting
```
Human-readable numbers              → human_format (K, M, B, T, Q, binary)
```

### Yield Curve Operations
```
Build from discount factors         → build_ql_discount_curve
Build from market instruments       → build_piecewise_ql_discount_curve
Build from zero rates               → build_ql_zero_curve
Extract nodes (flexible)            → get_nodes_dict
Extract fine grid                   → extract_fitted_curve_nodes
Rebuild from nodes                  → build_discount_curve_from_nodes
Get historical fixings              → get_fixings_dict
```

### Visualization
```
Dual-axis plots (v1)                → make_secondary_axis_plot_v1
Dual-axis plots (v2 multi)          → make_secondary_axis_plot_v2
Comprehensive timeseries            → timeseries_df_plotter
```

### Data Serialization
```
Config to hashable                  → make_hashable
Config to filename key              → to_filename_key
Serialize interpolation             → _encode_interp1d
Deserialize interpolation           → _decode_interp1d
Canonicalize values                 → _canonicalize_value
```

### Seasonality Analysis
```
Month-end/quarter-end patterns      → monthend_cumsum_seasonality
```

---

## Dependencies by Module

### Core Dependencies
- **QuantLib** (ql_utils.py, Query utils, Caching/utils.py, RVUtils)
- **pandas** (All modules except misc.py)
- **numpy** (ql_curve_building_utils.py, TB/utils.py, RVUtils)
- **datetime** (stdlib, ql_utils.py, Query utils, TB/utils.py)

### Optional Dependencies
- **matplotlib** (TB/utils.py)
- **plotly** (TB/utils.py)
- **scipy** (Caching/utils.py interpolation)
- **decimal** (misc.py for rounding)
- **ujson** (Caching/utils.py for fast JSON)
- **zoneinfo** (ql_utils.py, TB/utils.py for timezone)

---

## Error Handling Summary

| Pattern | Usage | Returns |
|---------|-------|---------|
| `ValueError` | Invalid input (bad tenor, unsupported period unit) | Raises exception |
| `TypeError` | Wrong type for dict keys | Raises exception |
| Try-except with NaN | date_to_tenor operations | "NaN" string on error |
| Try-except with None | Curve node extraction | None on error |
| Silent handling | Edge cases (None, NaN, Inf in formatting) | String representation |

---

## Common Workflows

### Workflow 1: IR Swap Pricing
```
1. datetime → QL.Date (datetime_to_ql_date)
2. Tenor string → Period (tenor_to_ql_period)
3. Add period to date (QL.Date arithmetic)
4. Build discount curve (build_ql_discount_curve)
5. Calculate PV using curve.discount()
6. Format result (human_format)
```

### Workflow 2: Curve Analysis and Export
```
1. Load market swap rates
2. Build piecewise curve (build_piecewise_ql_discount_curve)
3. Extract nodes (get_nodes_dict)
4. Analyze/plot nodes
5. For caching: to_filename_key
```

### Workflow 3: Backtesting Report
```
1. Calculate daily PnL/metrics
2. Create DataFrame with DatetimeIndex
3. Plot with timeseries_df_plotter
4. Add statistical bands (stds parameter)
5. Mark entry points (entry_date, entry_level)
```

### Workflow 4: Seasonality Analysis
```
1. Load daily timeseries
2. monthend_cumsum_seasonality
3. Analyze output columns:
   - 'avg' for overall pattern
   - 'avg-{month}' for month specifics
   - 'avg-{q-end}' for quarter patterns
4. Plot results
```

### Workflow 5: Format for Display
```
1. Calculate financial quantities (notional, BPV, prices)
2. human_format with appropriate:
   - decimals (precision needed)
   - unit (bps, mm, etc.)
   - system (finance for standard, iec for bytes, etc.)
3. Display or log result
```

---

## Testing Strategy

### Unit Test Targets
- Date conversions (round-trip testing)
- Tenor parsing (valid/invalid inputs)
- Period conversions (consistency checks)
- Curve building (output validation)
- Formatting edge cases (None, NaN, Inf, 0)

### Integration Test Targets
- End-to-end IR swap pricing
- Curve extraction and rebuild
- Multi-tenor plotting
- Configuration serialization/deserialization

### Property-Based Tests
- Conversion consistency (A → B → A)
- Monotonicity (curve discounts)
- Unit preservation (tenor → years consistency)

---

## Best Practices

### 1. Always Validate Tenors
```python
valid = {'1D', '1W', '1M', '3M', '6M', '1Y', '2Y', '5Y', '10Y', '30Y'}
if tenor not in valid:
    raise ValueError(f"Invalid tenor: {tenor}")
```

### 2. Keep Date Representation Consistent
- Option A: Always datetime
- Option B: Always QL.Date
- Option C: Convert at boundaries

### 3. Handle Date Operation Failures
```python
tenor = dates_to_string_tenor(eff, exp)
if tenor == "NaN":
    # handle error
```

### 4. Always Enable Curve Extrapolation
```python
curve = build_ql_discount_curve(...)
# enableExtrapolation() is already called
```

### 5. Use Business Day Calendars
```python
cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
bd = most_recent_business_day_ql(cal)  # Not naive calendar
```

---

## Navigation Guide

| Need | Location |
|------|----------|
| Quick function lookup | UTILS_QUICK_REFERENCE.md |
| Detailed explanation with examples | UTILS_MODULE_DOCUMENTATION.md |
| Implementation details | Source files in /home/user/ARBS/ |
| Error patterns | UTILS_MODULE_DOCUMENTATION.md § Error Handling |
| Usage examples | UTILS_MODULE_DOCUMENTATION.md § Usage Examples |
| Real-world workflows | UTILS_QUICK_REFERENCE.md § Real-World Examples |

---

## Statistics

### Module Sizes
| Module | Lines | Estimated Uses |
|--------|-------|-----------------|
| ql_utils.py | 307 | 1000+ |
| misc.py | 65 | 500+ |
| Query utils.py | 52 | 100+ |
| ql_curve_building_utils.py | 202 | 200+ |
| TB/utils.py | 487 | 50+ |
| Caching/utils.py | 66 | 100+ |
| RVUtils/seasonality_utils.py | 150 | 20+ |
| **Total** | **1,329** | **~2,000+** |

### Function Counts
- Date/Time: 15 functions
- Tenor/Period: 10 functions
- Formatting: 1 function
- Curve Operations: 7 functions
- Plotting: 3 functions + helpers
- Serialization: 4 functions
- Seasonality: 1 function
- **Total: ~40+ exported functions**

### Documentation
- Main documentation: 1,744 lines
- Quick reference: 500+ lines
- This index: 400+ lines
- **Total: ~2,600 lines of documentation**

---

## Maintenance Notes

### Known Duplicates
- QuantLib conversion functions duplicated in:
  - `utils/ql_utils.py`
  - `Query/IRSwaps/backends/quantlib/utils.py`
  - Consider consolidating in future refactor

### API Compatibility
- `_encode_interp1d()` and `_decode_interp1d()` handle scipy version differences
- Curve extraction in `get_nodes_dict()` tries multiple fallback approaches

### Performance Notes
- `extract_fitted_curve_nodes()` evaluates curve at 10,000 points by default
- `get_bdates_between()` iterates day-by-day (could optimize with getBusinessDaysBetween)
- `monthend_cumsum_seasonality()` handles timezone-aware datetimes

---

## Related Documentation

- Caching Architecture: `/home/user/ARBS/CACHING_ARCHITECTURE_DIAGRAMS.md`
- Caching Module Analysis: `/home/user/ARBS/CACHING_MODULE_ANALYSIS.md`
- Query Module: Use alongside `Query/IRSwaps/` module docs

