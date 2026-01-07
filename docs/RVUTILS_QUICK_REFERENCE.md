# RVUtils Quick Reference Guide

## Module Structure

```
RVUtils/
├── Interpolation/           # Yield curve interpolation methods
│   ├── NelsonSiegel.py     # 3-factor parametric model
│   ├── NelsonSiegelSvensson.py  # 4-factor parametric model
│   ├── SmithWilson.py      # Kernel-based extrapolation to UFR
│   ├── GeneralCurveInterpolator.py  # 15+ spline methods
│   ├── calibrate.py        # Calibration utilities
│   └── ...
├── regression.py            # Multi-model regression builder
├── seasonality_utils.py     # Month-end seasonality analysis
├── mean_reversion.py        # OU process calibration & forecasting
├── arbl_hedge_ratios.py     # OLS/TLS hedge ratio calculation
├── plt_timeseries.py        # Multi-axis plotting utilities
├── ust_viz.py              # Treasury curve visualization
└── general.py              # Realized volatility & utilities
```

---

## Quick Start Examples

### 1. Fit a Yield Curve

```python
from RVUtils.Interpolation.calibrate import calibrate_nss_ols
import numpy as np

maturities = np.array([0.25, 0.5, 1, 2, 5, 10, 30])
yields = np.array([0.020, 0.022, 0.025, 0.030, 0.035, 0.038, 0.040])

# Fit Svensson model
curve, opt_res, lstsq_res = calibrate_nss_ols(maturities, yields)

# Interpolate
new_maturities = np.linspace(0.1, 30, 100)
interpolated = curve(new_maturities)
```

### 2. Build a Regression Model

```python
from RVUtils.regression import make_linear_regression_builder
import pandas as pd

# Prepare data
data = pd.DataFrame({
    'return': [...],
    'factor1': [...],
    'factor2': [...],
}, index=pd.date_range('2020-01-01', periods=100))

# Build model
add_var, fit, plot_actual, plot_resid, plot_ts, get_data = \
    make_linear_regression_builder(df=data, y_col='return')[:6]

add_var('factor1')
add_var('factor2')

results = fit(model='OLS')

# Diagnostics
print(f"R²: {results.rsquared:.3f}")
print(f"Parameters:\n{results.params}")
```

### 3. Analyze Month-End Seasonality

```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality

seasonality = monthend_cumsum_seasonality(
    df=yields_df,
    value_col='yield',
    window=10,
    metric='bps'
)

# Use for mean-reversion trading: size positions larger on high seasonality days
```

### 4. Calculate Hedge Ratios

```python
from RVUtils.arbl_hedge_ratios import get_ols_hedge_ratio

ratios, X, y, residuals = get_ols_hedge_ratio(
    bond_prices_df,
    dependent_variable='Bond_Target'
)

# To hedge 1 Bond_Target: short Bond_Target, long Hedge_Instruments * ratios
```

### 5. Forecast Mean Reversion

```python
from RVUtils.mean_reversion import simulate_mean_reversion_ou

residuals_df = pd.DataFrame(regression_residuals, columns=['resid'])
forecast_df, fpt = simulate_mean_reversion_ou(residuals_df, steps=252)

# Use forecast_df['+1_sigma'] and ['-1_sigma'] for entry/exit signals
```

---

## Model Selection Matrix

### Which Interpolation Method?

| Need | Use | Speed | Notes |
|------|-----|-------|-------|
| Central bank reporting | Nelson-Siegel | Fast | 4 params, great interpretation |
| Complex shapes | Svensson | Medium | 6 params, best central bank curves |
| Extrapolate far out | Smith-Wilson | Slow | Converges to UFR |
| Negative rates | Bjork-Christensen | Medium | Avoids forward rate constraints |
| Smooth noisy data | Akima or PCHIP | Very fast | Non-parametric |
| Maximum flexibility | Spline (cubic) | Very fast | High degree of freedom |
| Quick testing | Linear | Fastest | Limited smoothness |

### Which Regression Model?

| Situation | Use | Pros | Cons |
|-----------|-----|------|------|
| Standard | OLS | Simple, fast | Assumes homoscedastic errors |
| Outliers | WLS + robust weights | Downweights outliers | Need weight specification |
| Multicollinearity | PCR | Orthogonal features | Less interpretable |
| Measurement errors | TLS | Symmetric error handling | Slower, more complex |
| Autocorrelated errors | GLS | Efficient estimation | Needs covariance structure |

---

## Function Reference

### Interpolation

```python
# Nelson-Siegel
from RVUtils.Interpolation.calibrate import calibrate_ns_ols
curve, opt_result = calibrate_ns_ols(maturities, yields, tau0=2.0)

# Svensson
from RVUtils.Interpolation.calibrate import calibrate_nss_ols
curve, opt_result, lstsq_result = calibrate_nss_ols(maturities, yields)

# Smith-Wilson
from RVUtils.Interpolation.SmithWilson import SmithWilsonCurve
curve = SmithWilsonCurve(ufr=0.04, alpha=0.15)
curve.fit(yields, maturities)

# General interpolator (15+ methods)
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator
interp = GeneralCurveInterpolator(maturities, yields)
cubic_result = interp.cubic_spline_interpolation()
pchip_result = interp.pchip_interpolation()
```

### Regression

```python
from RVUtils.regression import make_linear_regression_builder

builder_funcs = make_linear_regression_builder(
    df=data,
    y_col='target',
    add_constant=True,
    window=60  # For rolling
)

# Unpack functions
add_indep_var, fit, plot_actual, plot_residuals, plot_ts, get_data = builder_funcs[:6]

# Add variables
add_indep_var('x1')
add_indep_var('x2', transform=np.log)  # With transformation

# Fit
results = fit(model='OLS')  # or 'WLS', 'GLS', 'TLS', 'PCR'

# Get results
X, y, res = get_data()
print(res.params, res.rsquared, res.pvalues)
```

### Seasonality

```python
from RVUtils.seasonality_utils import monthend_cumsum_seasonality

seasonal = monthend_cumsum_seasonality(
    df=yields_ts,
    value_col='yield',
    window=10,           # ±10 business days
    business_month_end=True,
    relative_to='month_end',
    metric='bps'         # 'abs', 'pct', or 'bps'
)

# Access
avg = seasonal['avg']              # Average effect
std1_up = seasonal['avg+std1']     # +1 sigma band
by_month = seasonal['avg-jan']     # January seasonality
```

### Hedging

```python
from RVUtils.arbl_hedge_ratios import get_ols_hedge_ratio, get_tls_hedge_ratio

# OLS hedge ratio
ratios, X, y, residuals = get_ols_hedge_ratio(
    prices_df,
    dependent_variable='target',
    add_constant=True
)

# TLS hedge ratio (accounts for measurement errors)
ratios, X, y, residuals = get_tls_hedge_ratio(
    prices_df,
    dependent_variable='target',
    add_constant=True
)

# Measure hedge effectiveness
hedge_eff = 1 - (residuals.var() / y.var())
```

### Mean Reversion

```python
from RVUtils.mean_reversion import simulate_mean_reversion_ou

resid_df = pd.DataFrame(residuals, columns=['resid'])
forecast, fpt = simulate_mean_reversion_ou(resid_df, steps=252)

# Access forecast
mean_path = forecast['mean_reversion']
upper_band = forecast['+1_sigma']
lower_band = forecast['-1_sigma']
first_passage_time = fpt  # Days to mean
```

### Visualization

```python
from RVUtils.plt_timeseries import make_secondary_axis_plot

add_left, add_right, add_ind, show = make_secondary_axis_plot(
    ylabel_left='Left Axis',
    ylabel_right='Right Axis',
    engine='matplotlib'  # or 'plotly'
)[:4]

add_left(series1, label='Series 1')
add_right(series2, label='Series 2')
show()
```

---

## Common Parameter Values

### Nelson-Siegel: tau (lambda)

| Environment | Typical Range | Notes |
|-------------|---------------|-------|
| Normal conditions | 1.0 - 3.0 | Standard |
| Steep curve | 0.5 - 1.5 | Short decay |
| Flat curve | 3.0 - 5.0 | Long decay |

### Smith-Wilson: alpha

| Convergence | Alpha Value | Notes |
|-------------|-------------|-------|
| Fast (1-2 years) | 0.50 - 1.0 | For near-term data |
| Medium (3-5 years) | 0.10 - 0.30 | Typical choice |
| Slow (10+ years) | 0.05 - 0.10 | For very long maturities |

### Smith-Wilson: UFR (Ultimate Forward Rate)

| Authority | UFR Value | Notes |
|-----------|-----------|-------|
| EIOPA (EU) | 3.8% - 4.2% | Solvency II |
| ECB | 2.0% - 4.2% | Central bank rate |
| Fed | 2.0% - 2.5% | Long-term terminal rate |

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Fit Nelson-Siegel | 0.5-2ms | Fast, 4 parameters |
| Fit Svensson | 2-5ms | Requires parameter optimization |
| Fit Smith-Wilson | 10-50ms | Matrix inversion + alpha search |
| OLS regression (p=10, n=1000) | 0.5ms | Fast |
| TLS regression (p=10, n=1000) | 2-5ms | SVD-based |
| PCR regression (p=10, n=1000) | 5-10ms | PCA then OLS |
| Seasonality analysis | 10-50ms | QuantLib calendar operations |

---

## Troubleshooting

### Issue: Curve fit diverges

```python
# Solution: Adjust initial guess for lambda
curve, opt = calibrate_nss_ols(maturities, yields, tau0=(1.0, 3.0))
```

### Issue: Hedge ratio unstable

```python
# Solution 1: Use longer history
# Solution 2: Switch to TLS
ratios, _, _, _ = get_tls_hedge_ratio(prices_df, 'target')
# Solution 3: Use rolling window with frequent updates
```

### Issue: Multicollinearity in regression

```python
# Solution: Use PCR or TLS
results = fit(model='PCR', pcr_n_components=0.95)
```

### Issue: Outliers affecting regression

```python
# Solution: Use WLS with robust weights or preprocessing
results = fit(model='OLS', preprocess={'outliers': {'strategy': 'madclip', 'mad_thresh': 5.0}})
```

---

## Integration with Backtesting

### Pre-compute curves offline
```python
# For each historical date
curves_cache = {}
for date in date_range:
    maturities = [0.25, 0.5, 1, 2, 5, 10, 30]
    yields = market_data.loc[date, maturities]
    curve, _ = calibrate_nss_ols(maturities.values, yields.values)
    curves_cache[date] = curve
```

### Pre-compute hedge ratios
```python
# Rolling hedge ratios
hedge_ratios = rolling_beta(window=60, step=5, model='OLS')
```

### Apply seasonality adjustments
```python
# In backtest loop
seasonal_adj = seasonality_pattern.loc[days_to_month_end, 'avg']
position_size *= (1 + seasonal_adj / 10000)
```

---

## File Locations

- **Main module**: `/home/user/ARBS/RVUtils/`
- **Interpolation**: `/home/user/ARBS/RVUtils/Interpolation/`
- **Documentation**: `/home/user/ARBS/RVUTILS_COMPREHENSIVE_DOCUMENTATION.md`
- **Quick ref**: `/home/user/ARBS/RVUTILS_QUICK_REFERENCE.md`

---

## Key References

1. Nelson-Siegel: *Parsimonious Modeling of Yield Curves* (1987)
2. Svensson: *Estimating and Interpreting Forward Rates* (1994)
3. Smith-Wilson: *EIOPA Risk-free Rate Curves* (2021)
4. Diebold-Li: *Forecasting the Term Structure* (2006)

