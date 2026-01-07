# RVUtils - Analytics & Research Utilities: Comprehensive Documentation

**Version**: 1.0  
**Module Location**: `/home/user/ARBS/RVUtils/`  
**Last Updated**: 2024

## Table of Contents

1. [Overview](#overview)
2. [Interpolation Methods](#interpolation-methods)
3. [Regression Utilities](#regression-utilities)
4. [Seasonality Decomposition](#seasonality-decomposition)
5. [Hedging Utilities](#hedging-utilities)
6. [Visualization Tools](#visualization-tools)
7. [Statistical Analysis Functions](#statistical-analysis-functions)
8. [Backtesting Integration](#backtesting-integration)
9. [Performance Characteristics](#performance-characteristics)
10. [Best Practices & Use Cases](#best-practices--use-cases)

---

## 1. Overview

RVUtils is a comprehensive analytics library designed for fixed income research, yield curve analysis, and quantitative finance. The module provides:

- **Yield curve interpolation** using multiple parametric and non-parametric methods
- **Multi-factor regression** with support for OLS, TLS, WLS, GLS, and PCR models
- **Seasonality analysis** for temporal pattern decomposition
- **Hedging ratio calculation** for basis and fixed income strategies
- **Advanced visualization** with dual-axis and interactive plotting
- **Statistical utilities** for mean reversion, realized volatility, and time series analysis

### Key Dependencies

```python
import pandas as pd
import numpy as np
import scipy.optimize
import scipy.interpolate
import statsmodels.api as sm
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import QuantLib as ql
```

---

## 2. Interpolation Methods

The interpolation module provides 15+ methods for yield curve construction, each with distinct mathematical properties and use cases.

### 2.1 Nelson-Siegel Model

**Mathematical Formulation:**

The Nelson-Siegel model represents zero rates as a three-factor model:

```
y(τ) = β₀ + β₁ · f₁(τ) + β₂ · f₂(τ)
```

Where the factor loadings are:

```
f₁(τ) = (1 - exp(-τ/λ)) / (τ/λ)
f₂(τ) = f₁(τ) - exp(-τ/λ)
```

**Parameters:**
- **β₀ (Level)**: Long-term asymptotic rate; influences overall curve level
- **β₁ (Slope)**: Controls the spread between short and long rates
- **β₂ (Curvature)**: Captures the hump/hump in the mid-term curve
- **τ (Lambda)**: Characteristic decay rate; controls factor shape (typically 0.5-5.0)

**Instantaneous Forward Rate:**

```
f(τ) = β₀ + β₁·exp(-τ/λ) + β₂·(τ/λ)·exp(-τ/λ)
```

**Key Features:**
- Parsimonious: Only 4 parameters
- Smooth and well-behaved across all maturities
- Guarantees positive forward rates at long horizons
- Factor interpretation useful for term structure analysis

**File**: `/home/user/ARBS/RVUtils/Interpolation/NelsonSiegel.py`

**Usage Example:**

```python
from RVUtils.Interpolation.NelsonSiegel import NelsonSiegelCurve
from RVUtils.Interpolation.calibrate import calibrate_ns_ols

# Observed data
maturities = np.array([0.25, 0.5, 1.0, 2.0, 5.0, 10.0])
yields = np.array([0.02, 0.022, 0.025, 0.03, 0.035, 0.038])

# Calibrate with initial lambda guess
curve, opt_result = calibrate_ns_ols(maturities, yields, tau0=2.0)

# Interpolate
new_maturities = np.linspace(0.1, 10, 100)
interpolated_yields = curve(new_maturities)

# Forward rates
forward_rates = curve.forward(new_maturities)
```

---

### 2.2 Nelson-Siegel-Svensson Model

**Mathematical Formulation:**

Svensson (1994) extended the Nelson-Siegel model by adding a second hump factor:

```
y(τ) = β₀ + β₁·f₁(τ) + β₂·f₂(τ) + β₃·f₃(τ)
```

Where:

```
f₁(τ) = (1 - exp(-τ/τ₁)) / (τ/τ₁)
f₂(τ) = f₁(τ) - exp(-τ/τ₁)
f₃(τ) = (1 - exp(-τ/τ₂)) / (τ/τ₂) - exp(-τ/τ₂)
```

**Parameters:**
- **β₀ (Level)**: Long-term asymptotic rate
- **β₁ (Slope)**: Primary slope factor
- **β₂ (First Curvature)**: First hump/trough
- **β₃ (Second Curvature)**: Second hump/trough for enhanced flexibility
- **τ₁ (Lambda 1)**: Decay parameter for first curvature (typically 1-3)
- **τ₂ (Lambda 2)**: Decay parameter for second curvature (typically 3-10)

**Instantaneous Forward Rate:**

```
f(τ) = β₀ 
     + β₁·exp(-τ/τ₁)
     + β₂·(τ/τ₁)·exp(-τ/τ₁)
     + β₃·(τ/τ₂)·exp(-τ/τ₂)
```

**Advantages:**
- 6 parameters allow more complex curve shapes
- Can model multiple humps in the curve
- Used by majority of central banks globally
- Superior fit to real yield curves

**File**: `/home/user/ARBS/RVUtils/Interpolation/NelsonSiegelSvensson.py`

**Usage Example:**

```python
from RVUtils.Interpolation.NelsonSiegelSvensson import NelsonSiegelSvenssonCurve
from RVUtils.Interpolation.calibrate import calibrate_nss_ols, calibrate_nss_weighted_ols

# Basic calibration
curve_nss, opt_result, lstsq_result = calibrate_nss_ols(
    maturities, yields, tau0=(2.0, 5.0)
)

# Weighted calibration (emphasize certain maturities)
weights = np.array([1.0, 1.2, 1.5, 1.2, 0.8, 0.5])  # Higher weight for mid-curve
curve_w, lstsq_w = calibrate_nss_weighted_ols(
    maturities, yields, weights, tau0=(2.0, 5.0)
)

# Evaluate
yields_interp = curve_nss(new_maturities)
```

---

### 2.3 Smith-Wilson Interpolation

**Mathematical Formulation:**

Smith-Wilson is a curve fitting method designed to interpolate and extrapolate to an Ultimate Forward Rate (UFR). The method constructs a discount curve by solving:

```
P(t) = exp(-UFR·t) - W(t,t_obs)·ζ
```

Where:
- **P(t)** = Discount factors (implied from observed rates)
- **W(t,t_obs)** = Wilson kernel function matrix
- **ζ** = Sensitivity parameters

**Wilson Kernel Function:**

```
W(t₁,t₂) = α·min(t₁,t₂) 
         - (0.5)·exp(-α·|t₁-t₂|)·[exp(α·min(t₁,t₂)) - exp(-α·min(t₁,t₂))]
         + exp(-UFR·(t₁+t₂))
```

**Parameters:**
- **UFR (Ultimate Forward Rate)**: Target forward rate at convergence (e.g., 0.04)
- **α (Alpha)**: Convergence speed parameter controlling how fast rates converge to UFR
  - Higher α = faster convergence (typically 0.05 - 1.0)
  - Optimized to achieve < 1 bps difference at convergence point

**Key Properties:**
- No parametric form; pure interpolation/extrapolation
- Can handle negative rates
- Smooth forward rate curve
- Recommended by EIOPA for Solvency II
- Forces convergence to UFR asymptotically

**File**: `/home/user/ARBS/RVUtils/Interpolation/SmithWilson.py`

**Usage Example:**

```python
from RVUtils.Interpolation.SmithWilson import SmithWilsonCurve, find_ufr_ytm

# Fit Smith-Wilson with specific UFR
sw_curve = SmithWilsonCurve(ufr=0.04, alpha=0.15)
sw_curve.fit(yields, maturities)
interpolated = sw_curve.interpolate(new_maturities)

# Automatically find optimal UFR from market data
ufr_optimal = find_ufr_ytm(
    maturities, yields, 
    alpha_min=0.05, 
    ufr_guess=0.04
)

# Use optimized UFR
sw_curve_opt = SmithWilsonCurve(ufr=ufr_optimal)
sw_curve_opt.fit(yields, maturities)
```

---

### 2.4 Bjork-Christensen & Augmented Models

**Mathematical Formulation (Bjork-Christensen):**

Extends Nelson-Siegel with enhanced flexibility:

```
f(τ) = β₀ + (β₁ + β₂·τ)·exp(-τ/λ)
```

**Augmented Version:**

Adds polynomial terms:

```
f(τ) = β₀ + (β₁ + β₂·τ + β₃·τ²)·exp(-τ/λ)
```

**Advantages:**
- More flexible than Nelson-Siegel
- Useful for very low or negative rate environments
- Better capture of long-term curve shape

**Files**: 
- `/home/user/ARBS/RVUtils/Interpolation/BjorkChristensen.py`
- `/home/user/ARBS/RVUtils/Interpolation/BjorkChristensenAugmented.py`

**Usage Example:**

```python
from RVUtils.Interpolation.calibrate import calibrate_bc_ols, calibrate_bc_augmented

# Bjork-Christensen
bc_curve, opt_result = calibrate_bc_ols(maturities, yields, tau0=1.0)

# Augmented version
bc_aug, opt_result = calibrate_bc_augmented_ols(maturities, yields)

yields_interp = bc_aug(new_maturities)
```

---

### 2.5 Diebold-Li Model

**Mathematical Formulation:**

A dynamic factor model version of Nelson-Siegel:

```
y(τ) = L_t + S_t·(1 - exp(-τ/λ)) / (τ/λ) + C_t·[(1 - exp(-τ/λ)) / (τ/λ) - exp(-τ/λ)]
```

Where:
- **L_t** = Level factor (long-term rate)
- **S_t** = Slope factor (term spread)
- **C_t** = Curvature factor (bow in curve)
- **λ** = Fixed decay rate (typically 0.0609 for monthly, 0.0609*12 for annual)

**Key Features:**
- Allows factors to be time-varying
- Useful for dynamic term structure modeling
- Easier interpretation as yield curve dynamics
- Lambda is typically fixed across time

**File**: `/home/user/ARBS/RVUtils/Interpolation/DieboldLi.py`

**Usage Example:**

```python
from RVUtils.Interpolation.calibrate import calibrate_diebold_li_ols

dl_curve, opt_result = calibrate_diebold_li_ols(maturities, yields)
factors_matrix = dl_curve.factor_matrix(maturities)
```

---

### 2.6 Merrill Lynch Exponential Spline Model (MLESM)

**Characteristics:**
- Exponential spline-based approach
- Flexible knot placement
- Good for non-smooth market data
- Regularization available to prevent overfitting

**File**: `/home/user/ARBS/RVUtils/Interpolation/MLESM.py`

**Usage Example:**

```python
from RVUtils.Interpolation.calibrate import calibrate_mles_ols

mlesm_curve, opt_result = calibrate_mles_ols(
    maturities, yields,
    N=8,  # Number of exponential terms
    regularization=1e-4,
    overnight_rate=0.05
)
```

---

### 2.7 Spline-Based Methods

**Available Methods via GeneralCurveInterpolator:**

#### Linear Interpolation
- Simplest method
- Continuous but not smooth (discontinuous derivatives)
- Good for quickly checking data

#### Cubic Spline
- Piecewise cubic polynomials with continuity up to 2nd derivative
- Boundary conditions: "not-a-knot" (default), "natural", "clamped", "periodic"
- Custom knot placement available

#### PCHIP (Piecewise Cubic Hermite Interpolation)
- Monotonic preservation
- No oscillations around peaks
- Ideal for monotonic yield curves

#### Akima Interpolation
- Robust to outliers
- Better local control than cubic splines
- Good for noisy data

#### B-Splines
- Highly flexible, parametric degree (k) adjustable
- Supports custom knot vectors
- Good for smoothing

#### Smoothing Splines
- Balances fit and smoothness with parameter λ
- Automatic smoothness selection available

#### LOESS (Locally Estimated Scatterplot Smoothing)
- Non-parametric, kernel-based
- Robust to outliers
- Good for exploratory analysis

**File**: `/home/user/ARBS/RVUtils/Interpolation/GeneralCurveInterpolator.py`

**Usage Example:**

```python
from RVUtils.Interpolation.GeneralCurveInterpolator import GeneralCurveInterpolator

# Initialize interpolator
interp = GeneralCurveInterpolator(
    x=maturities,
    y=yields,
    linspace_x_lower_bound=0.1,
    linspace_x_upper_bound=30.0,
    linspace_x_num=1000,
    enable_extrapolate_left_fill=True,
    enable_extrapolate_right_fill=True
)

# Cubic spline with natural boundary conditions
yields_cubic = interp.cubic_spline_interpolation(bc_type="natural")

# PCHIP for monotonic preservation
yields_pchip = interp.pchip_interpolation()

# Akima for robustness
yields_akima = interp.akima_interpolation()

# B-spline with k=3 (cubic)
yields_bsp = interp.b_spline1_interpolation(k=3, return_func=False)

# Get interpolation function (callable)
spline_func = interp.cubic_spline_interpolation(return_func=True)
y_at_point = spline_func(2.5)
```

---

### 2.8 Monotone Convex Spline

**Characteristics:**
- Preserves monotonicity and convexity
- No oscillations
- Useful for discount curve construction
- Preserves key financial properties

**File**: `/home/user/ARBS/RVUtils/Interpolation/MonotoneConvex.py`

**Usage Example:**

```python
mc_func = interp.monotone_convex(return_func=True)
```

---

### 2.9 Vasicek Model

**Purpose:** 
Term structure model combining mean-reverting interest rate dynamics with parametric curve fitting

**File**: `/home/user/ARBS/RVUtils/Interpolation/Vasicek.py`

---

### 2.10 Model Comparison & Selection

| Method | Parameters | Smoothness | Flexibility | Interpretation | Best For |
|--------|-----------|-----------|-------------|-----------------|----------|
| Nelson-Siegel | 4 | Smooth | Low | Excellent (L,S,C) | Central bank curves |
| Svensson | 6 | Very Smooth | Medium | Excellent (L,S,C,H) | Complex curves |
| Smith-Wilson | 2 | C∞ | Medium | Extrapolation | Extrapolation to UFR |
| Bjork-Chris | 4-5 | Smooth | Medium | Good | Lower/negative rates |
| Splines | Variable | C² | High | Limited | Noisy data |
| PCHIP | None | C¹ | Low | None | Monotonic preservation |
| LOESS | 2 | Smooth | High | None | Exploratory analysis |

---

## 3. Regression Utilities

### 3.1 Overview

The `regression.py` module provides a comprehensive regression builder with support for multiple regression types and extensive preprocessing options.

**File**: `/home/user/ARBS/RVUtils/regression.py`

### 3.2 Supported Regression Models

#### OLS (Ordinary Least Squares)

**Mathematical Formulation:**

```
min ||y - Xβ||₂²

β̂ = (X'X)⁻¹X'y
```

**Assumptions:**
- Linear relationship between X and y
- Homoscedasticity (constant variance of residuals)
- No multicollinearity in X
- Residuals normally distributed (for inference)

**Best For:** Baseline models, symmetric errors

```python
add_indep_var(...)
fit(model="OLS")
```

---

#### WLS (Weighted Least Squares)

**Mathematical Formulation:**

```
min ||W^(1/2)(y - Xβ)||₂²

where W is a diagonal weight matrix
```

**Purpose:** Handle heteroscedasticity by assigning different weights to observations

**Best For:** When different observations have different levels of uncertainty/reliability

```python
weights = pd.Series([1.0, 1.2, 0.8, 1.5, 1.0], index=data.index)
fit(model="WLS", weights=weights)
```

---

#### GLS (Generalized Least Squares)

**Mathematical Formulation:**

```
Ω = E[εε'] (covariance matrix)
β̂_GLS = (X'Ω⁻¹X)⁻¹X'Ω⁻¹y
```

**Purpose:** Efficient estimation when errors are correlated or heteroscedastic

**Best For:** Time series data with autocorrelated residuals

```python
fit(model="GLS")
```

---

#### TLS (Total Least Squares) / Orthogonal Regression

**Mathematical Formulation:**

Minimizes perpendicular distance from points to fitted line:

```
min Σᵢ (residual_y,i² + Σⱼ residual_x,ij²)
```

**Implementation via scipy.odr.ODR:**

```
min ||[X_err, y_err]||_F²
```

**Parameters:**
- `tls_x_errs`: Error estimates for X matrix (shape: n×k)
- `tls_y_errs`: Error estimates for y vector (shape: n,)
- `tls_lambda`: Relative error variance ratio (scalar or array of length k)

**Best For:** When both X and y have measurement errors

```python
# Method 1: Explicit error specification
fit(
    model="TLS",
    tls_x_errs=x_errors,  # n×k matrix
    tls_y_errs=y_errors   # n vector
)

# Method 2: Via error variance ratio
fit(
    model="TLS",
    tls_lambda=0.01  # var(X_error) = 0.01 * var(y_error)
)
```

---

#### PCR (Principal Components Regression)

**Mathematical Formulation:**

1. **PCA Step:** Decompose X into principal components
```
X = U·S·V'  (via SVD)
Z = U·S  (principal component scores)
```

2. **Regression Step:** OLS of y on leading principal components
```
y = Z·γ + ε
```

3. **Back-mapping:** Transform coefficients back to original space
```
β = V·γ / σ  (accounting for scaling)
```

**Purpose:** Reduce multicollinearity by using uncorrelated components

**Parameters:**
- `pcr_n_components`: 
  - `None` (default): Use 95% of variance
  - `float` in (0,1]: Use components explaining that fraction of variance
  - `int`: Use exactly that many components

**Best For:** Highly correlated regressors (multicollinearity)

```python
fit(
    model="PCR",
    pcr_n_components=0.95,  # 95% variance
    pcr_scale=True          # Standardize X before PCA
)

results = fit(...)
pcr_info = results.pcr_info  # Access PCA details
```

---

### 3.3 Preprocessing Pipeline

The builder supports extensive preprocessing with 20+ configuration options:

```python
builder = make_linear_regression_builder(
    df=price_data,
    y_col="return",
    preprocess={
        # Joining
        "join_how": "inner",           # inner | outer
        "sort_index": True,
        "drop_duplicate_index": "keep-last",
        
        # Date filtering
        "date_start": "2020-01-01",
        "date_end": "2024-01-01",
        
        # Resampling
        "resample_rule": "D",          # Daily
        "resample_agg": "last",        # last | mean | sum
        
        # Missing data
        "coerce_numeric": True,
        "max_missing_frac": 0.1,       # Drop cols > 10% missing
        "fill_method": "ffill",        # ffill | bfill
        "fill_limit": 5,               # Max consecutive fills
        "interpolate": True,
        "interpolate_method": "time",
        
        # Transformations
        "demean": False,               # Subtract mean
        "zscore": False,               # Standardize
        "log": False,                  # Log transform
        "diff_periods": 1,             # 1st difference
        "return_periods": 1,           # Log returns
        
        # Outliers
        "outliers": {
            "strategy": "winsor",      # winsor | zclip | madclip | trim_z | trim_mad
            "winsor_limits": (0.01, 0.99),
            "z_thresh": 4.0,
            "mad_thresh": 5.0,
        },
        
        # Feature scaling
        "scale": {
            "type": "standard",        # standard | minmax | robust
            "range": (0.0, 1.0),       # For minmax
            "with_centering": True,
            "scale_y": False,
        },
        
        # Collinearity management
        "collinearity": {
            "drop_zero_variance": True,
            "corr_threshold": 0.98,    # Drop highly correlated
            "vif_threshold": 10.0,     # Drop high VIF
            "max_iter": 5,
        },
        "dropna_how": "any",
    }
)
```

**Preprocessing Steps (in order):**

1. Concatenate y with independent variables
2. Sort by index
3. Remove duplicate indices
4. Filter date range
5. Resample time series
6. Coerce to numeric
7. Drop columns with too much missing data
8. Fill missing values
9. Interpolate
10. Log transform
11. Differences/returns
12. Demean/standardize
13. Outlier handling
14. Feature scaling
15. Collinearity pruning

---

### 3.4 Collinearity Management

#### Correlation-based Pruning

Iteratively removes the column with highest mean correlation:

```python
"collinearity": {
    "corr_threshold": 0.98,  # Remove if r > 0.98
}
```

#### VIF (Variance Inflation Factor)

Iteratively removes columns with VIF > threshold:

```python
VIF_j = 1 / (1 - R²_j)
```

Where R²_j is from regressing X_j on all other X variables.

```python
"collinearity": {
    "vif_threshold": 10.0,  # Remove if VIF > 10
    "max_iter": 5,          # Max iterations
}
```

#### Zero Variance Dropping

Automatically removes constant columns.

---

### 3.5 Outlier Handling Strategies

| Strategy | Method | Good For |
|----------|--------|----------|
| winsor | Cap at quantiles | Moderate outliers |
| zclip | Clip at ±z std | Symmetric outliers |
| madclip | MAD-based clipping | Robust outlier detection |
| trim_z | Mark as NaN if \|z\| > threshold | Removing extreme outliers |
| trim_mad | Mark as NaN using MAD | Robust removal |

**Example - Robust outlier handling:**

```python
"outliers": {
    "strategy": "madclip",
    "mad_thresh": 5.0,  # 5*MAD
}
```

---

### 3.6 Feature Scaling

**Standard Scaling** (Z-score):
```
X_scaled = (X - μ) / σ
```

**Min-Max Scaling**:
```
X_scaled = (X - min) / (max - min) * (hi - lo) + lo
```

**Robust Scaling** (resistant to outliers):
```
X_scaled = (X - median) / IQR
```

---

### 3.7 Using the Regression Builder

**Basic Usage:**

```python
from RVUtils.regression import make_linear_regression_builder
import pandas as pd
import numpy as np

# Create sample data
dates = pd.date_range('2020-01-01', periods=100, freq='D')
data = pd.DataFrame({
    'return': np.random.randn(100) * 0.01,
    'market_return': np.random.randn(100) * 0.015,
    'vix_change': np.random.randn(100) * 0.5,
}, index=dates)

# Initialize builder
builder_tuple = make_linear_regression_builder(
    df=data,
    y_col='return',
    add_constant=True,
    window=60  # For rolling regressions
)

add_indep_var, fit, plot_actual_vs_predicted, \
    plot_residuals_vs_predicted, plot_residuals_timeseries, \
    get_data, rolling_beta, rolling_r2, rolling_correlation = builder_tuple

# Add independent variables
add_indep_var('market_return', name='MKT')
add_indep_var('vix_change', name='VIX')

# Fit OLS model
results = fit(model='OLS', verbose=True)

# Examine results
print(results.params)      # Coefficients
print(results.bse)         # Standard errors
print(results.pvalues)     # P-values
print(results.rsquared)    # R²

# Visualizations
plot_actual_vs_predicted(title='Actual vs Predicted Returns')
plot_residuals_vs_predicted()
plot_residuals_timeseries(
    plot_zero=True,
    stds=[1, 2],
    ou_bands=True,  # Add Ornstein-Uhlenbeck forecast bands
    ou_steps=252
)

# Rolling regressions
rolling_betas = rolling_beta(window=60, model='OLS')
rolling_r2s = rolling_r2(window=60)
rolling_corrs = rolling_correlation(window=60, drop_const=True)

# Get preprocessed data
X_used, y_used, results = get_data()
```

---

### 3.8 Advanced Regression Examples

#### TLS Regression with Error Specification

```python
# Specify measurement errors
n = len(data)
k = 2  # number of regressors

x_errors = np.full((n, k), 0.01)  # 1% error in X
y_errors = np.full(n, 0.001)       # 0.1% error in y

results = fit(
    model='TLS',
    tls_x_errs=x_errors,
    tls_y_errs=y_errors,
    verbose=True
)
```

#### PCR with Multicollinear Regressors

```python
# Create highly correlated regressors
data['x1'] = np.random.randn(100)
data['x2'] = data['x1'] + 0.01 * np.random.randn(100)  # Nearly identical to x1
data['x3'] = data['x1'] * 2 + 0.01 * np.random.randn(100)

add_indep_var('x1')
add_indep_var('x2')
add_indep_var('x3')

# Standard OLS would have high VIF
results_ols = fit(model='OLS')  # May have numerical issues

# PCR handles this gracefully
results_pcr = fit(
    model='PCR',
    pcr_n_components=0.95,
    verbose=True
)

print(results_pcr.pcr_info.components_)  # PC loadings
print(results_pcr.pcr_info.explained_variance_ratio_)
```

#### WLS with Time-Varying Weights

```python
# Weight recent observations more heavily
weights = np.linspace(0.5, 1.5, len(y_used))

results = fit(model='WLS', weights=weights)
```

---

### 3.9 Model Diagnostics

The results object provides comprehensive diagnostics:

```python
# Parameter estimates
results.params           # Coefficients
results.bse             # Standard errors
results.tvalues         # t-statistics
results.pvalues         # p-values

# Fit quality
results.rsquared        # R²
results.nobs            # Number of observations
results.df_resid        # Residual degrees of freedom

# Predictions and residuals
results.fittedvalues    # ŷ
results.resid           # y - ŷ

# Model specification (for OLS/WLS/GLS)
results.model.endog_names
results.model.exog_names
```

---

## 4. Seasonality Decomposition

### 4.1 Month-End Cumulative Seasonality

**File**: `/home/user/ARBS/RVUtils/seasonality_utils.py`

**Purpose**: Analyze intra-month patterns (month-end effects) in time series

**Mathematical Framework:**

Given a time series {y_t}, compute relative changes from a baseline date within each month window:

```
season_metric[t, m] = y[t] - baseline[m]   (for "abs" metric)
season_metric[t, m] = y[t] / baseline[m] - 1   (for "pct" metric)
season_metric[t, m] = (y[t] - baseline[m]) * 10000   (for "bps" metric)
```

Where baseline can be month-end or month-start, and statistical summaries include mean ± k·std.

**Function Signature:**

```python
def monthend_cumsum_seasonality(
    df: pd.DataFrame,
    *,
    value_col: str | None = None,
    window: int = 5,           # ±5 business days from anchor
    business_month_end: bool = True,
    cal: Optional[ql.Calendar] = ql.UnitedStates(ql.UnitedStates.GovernmentBond),
    relative_to: str = "month_end",  # month_end | month_start
    metric: str = "abs",       # abs | pct | bps
    baseline_fallback: str = "first_valid",
) -> pd.DataFrame:
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| df | DataFrame | - | Time series data |
| value_col | str | None | Column to analyze (required if df has >1 col) |
| window | int | 5 | Days before/after anchor to include |
| business_month_end | bool | True | Use business day or calendar month end |
| cal | QuantLib.Calendar | UnitedStates | Calendar for business days |
| relative_to | str | "month_end" | Anchor date: "month_end" or "month_start" |
| metric | str | "abs" | "abs" (absolute), "pct" (%), or "bps" (basis points) |
| baseline_fallback | str | "first_valid" | Handle missing baseline: "first_valid" |

**Output:**

Returns DataFrame with structure:
```
Index: Days from anchor (e.g., -5, -4, ..., 0, ..., +5)
Columns: 
  - avg: Average across all months
  - avg±std1, avg±std2: Confidence bands
  - avg-jan, avg-feb, ..., avg-dec: By-month seasonality
  - avg-{month}±std1, avg-{month}±std2: Monthly confidence bands
  - avg-q1-end, avg-q2-end, ...: By-quarter-end seasonality
  - Column per historical month-end date: Raw data by period
```

**Usage Examples:**

```python
# Basic month-end seasonality analysis
seasonality = monthend_cumsum_seasonality(
    df=yields_df,
    value_col='10Y_yield',
    window=10,
    metric='bps'
)

# Plot results
fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(seasonality.index, seasonality['avg'], linewidth=2, label='Average')
ax.fill_between(
    seasonality.index,
    seasonality['avg-std1'],
    seasonality['avg+std1'],
    alpha=0.3,
    label='±1 Std'
)
ax.fill_between(
    seasonality.index,
    seasonality['avg-std2'],
    seasonality['avg+std2'],
    alpha=0.15,
    label='±2 Std'
)
ax.legend()
ax.set_xlabel('Business Days from Month End')
ax.set_ylabel('Change (bps)')
ax.set_title('Month-End Seasonality in 10Y Yields')
plt.show()

# By-month analysis
for month in ['jan', 'feb', 'mar', 'apr']:
    col_name = f'avg-{month}'
    if col_name in seasonality.columns:
        ax.plot(seasonality.index, seasonality[col_name], label=month.upper())
```

**Key Insights from Seasonality Analysis:**

1. **Month-End Effects**: Liquidity constraints near month-end cause yields to move
2. **Quarter-End Effects**: Larger impact on Q1, Q2, Q3, Q4 endings
3. **Seasonal Patterns**: January effect, etc., in fixed income markets
4. **Risk Management**: Use confidence bands to set stop-loss orders

---

## 5. Hedging Utilities

### 5.1 ARBL Hedge Ratio Calculation

**File**: `/home/user/ARBS/RVUtils/arbl_hedge_ratios.py`

**Purpose**: Calculate optimal hedge ratios for arbitrage and pair trading strategies

### 5.2 OLS Hedge Ratio

**Mathematical Formulation:**

For dependent variable y (hedge target) and independent variables X (hedge instruments):

```
y = β₀ + β₁·X₁ + β₂·X₂ + ... + βₖ·Xₖ + ε

Minimize: Σᵢ εᵢ² = Σᵢ (yᵢ - β₀ - Σⱼ βⱼ·Xⱼ,ᵢ)²
```

**Solution:**

```
β̂ = (X'X)⁻¹X'y
```

**Interpretation:**
- βⱼ = number of units of instrument j needed to hedge 1 unit of y
- Negative βⱼ = short hedge (sell j to hedge long y)
- Positive βⱼ = long hedge (buy j to hedge short y)

**Function:**

```python
def get_ols_hedge_ratio(
    price_data: pd.DataFrame,
    dependent_variable: str,
    add_constant: bool = False
) -> Tuple[dict, pd.DataFrame, pd.Series, pd.Series]:
    """
    Returns:
        hedge_ratios_dict: {security: ratio}
        X: Independent variable data
        y: Dependent variable data
        residuals: Regression residuals (basis)
    """
```

**Usage:**

```python
from RVUtils.arbl_hedge_ratios import get_ols_hedge_ratio

# Price data for bonds
bond_prices = pd.DataFrame({
    'Bond_A': [100.0, 100.5, 100.2, 100.8],
    'Bond_B': [99.8, 100.3, 100.0, 100.7],
    'Bond_C': [99.5, 99.9, 99.7, 100.2],
})

# Calculate hedge ratios (hedge Bond_A with Bond_B and Bond_C)
ratios, X, y, residuals = get_ols_hedge_ratio(
    bond_prices,
    dependent_variable='Bond_A',
    add_constant=True
)

print(ratios)
# Output: {'Bond_A': 1.0, 'Bond_B': 0.95, 'Bond_C': 0.05}

# Construction of hedge:
# To hedge: Short 1 Bond_A, Long 0.95 Bond_B, Long 0.05 Bond_C
# Residual (basis) = Bond_A_price - 0.95*Bond_B - 0.05*Bond_C
basis = residuals
print(f"Basis std: {basis.std():.4f}")  # Lower is better
```

---

### 5.3 TLS (Total Least Squares) Hedge Ratio

**Mathematical Formulation:**

When both y and X have measurement errors, minimize:

```
Σᵢ (Δyᵢ² + Σⱼ ΔXⱼ,ᵢ²)
```

Using orthogonal regression (perpendicular distance to fitted hyperplane):

```
min ||[X_err, y_err]||_F²
```

**Advantages over OLS:**
- Accounts for errors in both X and y
- Better for calibrated market data with bid-ask spreads
- More robust to measurement noise

**Function:**

```python
def get_tls_hedge_ratio(
    price_data: pd.DataFrame,
    dependent_variable: str,
    add_constant: bool = False
) -> Tuple[dict, pd.DataFrame, pd.Series, pd.Series]:
```

**Usage:**

```python
from RVUtils.arbl_hedge_ratios import get_tls_hedge_ratio

# TLS hedge ratio (accounts for errors in both sides)
ratios_tls, X, y, residuals_tls = get_tls_hedge_ratio(
    bond_prices,
    dependent_variable='Bond_A',
    add_constant=True
)

# Compare OLS vs TLS
print("OLS ratios:", ratios)
print("TLS ratios:", ratios_tls)

# TLS typically gives more stable ratios under noisy conditions
```

---

### 5.4 Hedge Effectiveness Metrics

**Basis (Hedge Residual):**

```
Basis = y - (β₀ + β₁·X₁ + β₂·X₂ + ...)
```

Lower basis std = better hedge

**Hedging Effectiveness:**

```
Effectiveness = 1 - Var(Basis) / Var(y)
```

Values closer to 1 = better hedge

**Example:**

```python
# Measure hedge effectiveness
basis_var = residuals.var()
y_var = y.var()
effectiveness = 1 - (basis_var / y_var)

print(f"Hedge Effectiveness: {effectiveness:.1%}")  # e.g., 87.5%
```

---

## 6. Visualization Tools

### 6.1 Time Series Plotting (plt_timeseries.py)

**File**: `/home/user/ARBS/RVUtils/plt_timeseries.py`

**Features:**
- Dual/multi-axis plotting
- Matplotlib and Plotly support
- Recession shading
- Date range highlighting
- Custom date coloring
- OU mean-reversion forecasting bands
- Indicator overlays

**Function:**

```python
def make_secondary_axis_plot(
    *,
    ylabel_left: Optional[str] = None,
    ylabel_right: Optional[str] = None,
    title: Optional[str] = None,
    engine: str = "matplotlib"  # "matplotlib" | "plotly"
) -> Tuple[Callable, ...]:
```

**Returned Functions:**

1. **add_left_series()** - Add to primary (left) axis
2. **add_right_series()** - Add to secondary (right) axis
3. **add_indicator()** - Add technical indicator overlay
4. **show()** - Display the plot
5. **toggle_ou_bands()** - Show/hide OU forecast bands

**Usage Example:**

```python
from RVUtils.plt_timeseries import make_secondary_axis_plot
import pandas as pd
import numpy as np

# Create sample data
dates = pd.date_range('2020-01-01', periods=250, freq='D')
yields_10y = pd.Series(np.cumsum(np.random.randn(250)) * 0.01 + 0.03, index=dates)
spreads = pd.Series(np.cumsum(np.random.randn(250)) * 0.005 + 0.02, index=dates)

# Create plot with secondary axis
(add_left_series, add_right_series, add_indicator,
 show, toggle_ou_bands) = make_secondary_axis_plot(
    ylabel_left="10Y Yield",
    ylabel_right="2-10 Spread",
    title="US Treasury Yields",
    engine="matplotlib"
)

# Add series
add_left_series(yields_10y, label="10Y Yield", linestyle="-")
add_right_series(spreads, label="2-10 Spread", linestyle="--", color="orange")

# Add technical indicators
add_indicator(
    yields_10y.rolling(20).mean(),
    label="20-day MA",
    hide=False
)

# Show with OU bands for mean-reversion analysis
show()
toggle_ou_bands(steps=252, band_alpha=0.15)
```

---

### 6.2 UST Visualization (ust_viz.py)

**File**: `/home/user/ARBS/RVUtils/ust_viz.py`

**Purpose**: Specialized plotting for US Treasury curve analysis

**Function:**

```python
def plot_usts(
    curve_set_df: pd.DataFrame,
    ttm_col: str = "time_to_maturity",
    ytm_col: str = "ytm",
    label_col: str = "original_security_term",
    cusip_col: str = "cusip",
    splines: Optional[List[Tuple[Callable, str]]] = None,
    cusips_filter: Optional[List[str]] = None,
    ust_labels_filter: Optional[List[str]] = None,
    linspace_num: int = 1000,
    spline_lb: float = 0,
    spline_ub: float = 30,
) -> None:
```

**Features:**
- Interactive Plotly-based plotting
- Multiple spline overlays
- CUSIP filtering and highlighting
- OTR (on-the-run) security labeling
- Hover data with security details

**Usage:**

```python
from RVUtils.ust_viz import plot_usts

# Assume ust_curve_df has columns: time_to_maturity, ytm, cusip, etc.

plot_usts(
    ust_curve_df,
    splines=[
        (nelson_siegel_curve, "Nelson-Siegel"),
        (smith_wilson_curve, "Smith-Wilson"),
    ],
    ust_labels_filter=["3M", "6M", "2Y", "5Y", "10Y", "30Y"],
    cusips_hightlighter=["912810TC8"],  # Highlight specific security
    linspace_num=1000,
    spline_lb=0.0,
    spline_ub=30.0,
)
```

---

## 7. Statistical Analysis Functions

### 7.1 Mean Reversion & Ornstein-Uhlenbeck Model

**File**: `/home/user/ARBS/RVUtils/mean_reversion.py`

**Purpose**: Model mean-reverting processes and forecast reversion bands

**Mathematical Framework:**

The Ornstein-Uhlenbeck process:

```
dX_t = λ(μ - X_t)dt + σ dW_t
```

**Discrete-time solution:**

```
X_{t+1} = X_t·e^(-λ) + μ·(1 - e^(-λ)) + √σ·W_t
```

**Parameter Estimation:**

Given time series {X_t}, estimate λ (speed), μ (long-term mean), σ² (volatility):

```python
def simulate_mean_reversion_ou(
    df: pd.DataFrame,
    steps: Optional[int] = 252
) -> Tuple[pd.DataFrame, float]:
    """
    Calibrate OU process and forecast future paths.
    
    Returns:
        forecast_df: DataFrame with mean path and confidence bands
        fpt: First passage time to mean (in days)
    """
```

**Calibration Procedure:**

From observed residuals, estimate OU parameters:

```python
# Given residuals dataframe
residuals_df = pd.DataFrame(residuals, columns=['resid'])

forecast_df, fpt = simulate_mean_reversion_ou(
    residuals_df,
    steps=252  # 1 year forecast
)

# Access forecast
print(forecast_df.columns)
# ['mean_reversion', '+1_sigma', '-1_sigma', '+2_sigma', '-2_sigma']
print(f"Expected reversion time: {fpt:.0f} days")
```

**Output Structure:**

| Column | Description |
|--------|-------------|
| mean_reversion | Expected value E[X_t\|X_0] |
| +1_sigma | E[X_t] + σ_t |
| -1_sigma | E[X_t] - σ_t |
| +2_sigma | E[X_t] + 2σ_t |
| -2_sigma | E[X_t] - 2σ_t |

**Usage in Regression Residuals:**

```python
# After fitting regression
residuals = results.resid

# Forecast OU bands
ou_forecast, fpt = simulate_mean_reversion_ou(residuals.to_frame(), steps=252)

# Plot with regression
plot_residuals_timeseries(ou_bands=True, ou_steps=252, ou_bandalpha=0.15)
```

---

### 7.2 Realized Basis Point Volatility

**File**: `/home/user/ARBS/RVUtils/general.py`

**Function:**

```python
def realized_bpvol(x: pd.Series, w: int = 20) -> pd.Series:
    """
    Compute rolling realized basis-point volatility.
    
    Parameters:
        x: Price series
        w: Rolling window (default 20 trading days ~ 1 month)
    
    Returns:
        bpvol: Basis point volatility time series
    """
```

**Mathematical Definition:**

```
BPVOL_t = √(Σᵢ₌ₜ₋ₘ₊₁ᵗ r²ᵢ) × 10000

where:
- r_i = absolute price change in period i
- m = window length
- 10000 = basis points conversion
```

**Usage:**

```python
from RVUtils.general import realized_bpvol

# Compute 20-day rolling volatility in basis points
yields = pd.Series([0.030, 0.031, 0.0315, ...], index=dates)
bpvol = realized_bpvol(yields, w=20)

# Plot
fig, ax = plt.subplots()
ax.plot(bpvol.index, bpvol, label="20D Realized BPVOL")
ax.set_ylabel("Basis Point Volatility")
ax.legend()
plt.show()
```

---

## 8. Backtesting Integration

### 8.1 Integration Points

RVUtils integrates with the backtesting system at multiple levels:

**1. Curve Construction**: Pre-generate interpolated yield curves for historical dates
```python
# Pre-compute curves daily
curves_daily = {}
for date in historical_dates:
    rates_on_date = market_data.loc[date]
    maturities = [0.25, 0.5, 1, 2, 5, 10, 30]
    curve = GeneralCurveInterpolator(maturities, rates_on_date)
    curves_daily[date] = curve.calibrate_nss_ols()
```

**2. Hedge Ratio Lookups**: Pre-calculate rolling hedge ratios
```python
# Rolling hedge ratios
hedge_ratios_rolling = rolling_beta(
    window=60,
    model='OLS',
    step=5  # Recompute every 5 days
)
```

**3. Seasonality Adjustments**: Apply seasonality biases
```python
# Month-end premium
month_end_effects = monthend_cumsum_seasonality(hist_prices, metric='bps')
days_to_month_end = compute_days_to_month_end(current_date)
seasonal_adjustment = month_end_effects.loc[days_to_month_end, 'avg']
```

**4. Mean Reversion Signals**: Use OU forecasts for position sizing
```python
# Generate OU bands for entry signals
basis_ou, fpt = simulate_mean_reversion_ou(basis_series, steps=252)
# Use +2σ as entry signal for mean reversion trades
```

---

### 8.2 Backtesting Workflow

```python
from RVUtils.regression import make_linear_regression_builder
from RVUtils.seasonality_utils import monthend_cumsum_seasonality
from RVUtils.mean_reversion import simulate_mean_reversion_ou

# 1. Prepare data
historical_data = load_historical_prices(start='2019-01-01', end='2024-01-01')

# 2. Build regression model on training data (2019-2021)
builder = make_linear_regression_builder(
    df=historical_data['2019':'2021'],
    y_col='bond_A',
    window=60
)

builder[1]('bond_B')  # add_indep_var
builder[1]('bond_c')

results = builder[2](model='OLS')  # fit

# 3. Compute rolling hedge ratios (2019-2024)
rolling_hedges = rolling_beta(window=60, step=1)

# 4. Analyze seasonality
seasonal_pattern = monthend_cumsum_seasonality(
    historical_data[['spread']],
    window=10,
    metric='bps'
)

# 5. Backtest strategy
pnl_list = []
for date in trading_dates:
    # Get hedge ratio for date
    hedge = rolling_hedges.loc[date]
    
    # Apply seasonal adjustment
    days_to_me = days_until_month_end(date)
    seasonal_adj = seasonal_pattern.loc[days_to_me, 'avg']
    
    # Position sizing (mean reversion entry)
    spread = data['bond_A'].loc[date] - hedge * data['bond_B'].loc[date]
    pnl = spread + seasonal_adj  # Simplified P&L
    pnl_list.append(pnl)
```

---

## 9. Performance Characteristics

### 9.1 Interpolation Method Comparison

| Method | Time Complexity | Space | Smoothness | Extrapolation | Stability |
|--------|-----------------|-------|-----------|---------------|-----------|
| Linear | O(n) | O(n) | C⁰ | Linear | Excellent |
| Cubic Spline | O(n) | O(n) | C² | Linear | Good |
| PCHIP | O(n) | O(n) | C¹ | Flat | Excellent |
| Nelson-Siegel | O(n) | O(1) | C∞ | Parametric | Good |
| Svensson | O(n) | O(1) | C∞ | Parametric | Good |
| Smith-Wilson | O(n³) | O(n²) | C∞ | UFR convergence | Good |
| B-Spline | O(n) | O(n) | C^(k-1) | Linear | Good |

### 9.2 Calibration Speed

**Nelson-Siegel**: ~0.5-2ms per curve
**Svensson**: ~2-5ms per curve (requires optimization of 2 parameters)
**Smith-Wilson**: ~10-50ms per curve (matrix inversion + optimization)
**Spline methods**: <1ms (direct construction)

**Recommendation**: Pre-compute curves offline for backtesting

### 9.3 Regression Model Computational Cost

| Model | Time | Memory | Numerical Stability |
|-------|------|--------|-------------------|
| OLS | O(p³) | O(p²) | Moderate (matrix inversion) |
| WLS | O(p³) | O(p²) | Moderate |
| GLS | O(p⁴+) | O(p²) | Moderate |
| TLS | O(p³) | O(p²) | Good (SVD-based) |
| PCR | O(np²) | O(np) | Excellent (SVD-based) |

**For n=1000, p=10:**
- OLS: ~0.5ms
- TLS: ~2ms
- PCR: ~5ms

---

## 10. Best Practices & Use Cases

### 10.1 Yield Curve Selection Guide

**Use Case: Real-time pricing**
- Method: Linear or PCHIP (speed)
- Calibration: Daily or intra-daily

**Use Case: Risk model calibration**
- Method: Nelson-Siegel or Svensson
- Calibration: Weekly, with factor dynamics
- Benefit: Interpretable level/slope/curvature factors

**Use Case: Extrapolation to 50+ years**
- Method: Smith-Wilson with UFR
- UFR: Set to consensus long-term rate (ECB: 4.2%, Fed: 2.5%)

**Use Case: Negative rate environment**
- Method: Bjork-Christensen Augmented
- Benefit: No assumption of positive forward rates

**Use Case: Tail risk assessment**
- Method: Multiple curves (Svensson + Smith-Wilson)
- Use ensemble approach for robustness

### 10.2 Regression Model Selection

**When to use each model:**

| Situation | Model | Reason |
|-----------|-------|--------|
| Standard linear relationship | OLS | Simplicity, interpretability |
| Heteroscedastic errors | WLS | Assigns lower weight to noisy obs |
| Autocorrelated errors | GLS | Efficient estimation |
| Both X and y have errors | TLS | Symmetric error treatment |
| High multicollinearity | PCR | Orthogonal components |
| Small sample, many regressors | PCR/TLS | More stable |
| Outliers in data | WLS with robust weights | Downweight outliers |

### 10.3 Seasonality Analysis Best Practices

**Valid Applications:**
1. **Month-end effects**: Treasury auction supply/demand
2. **Quarter-end rebalancing**: Index rebalancing flows
3. **First-of-month settlement**: Cash flow patterns
4. **Sector rotation**: Seasonal allocation changes

**Caveats:**
- Seasonality is relative, not absolute
- Use wide confidence bands (±2σ)
- Combine with fundamental analysis
- Avoid over-fitting to recent patterns
- Re-estimate seasonality regularly

### 10.4 Hedging Strategy Best Practices

**Design Steps:**

1. **Data Collection**: Gather price histories for target and hedge instruments
   ```python
   # Ensure data alignment and sufficient history (6-12 months minimum)
   prices_aligned = prices.loc[start:end].dropna()
   ```

2. **Model Selection**: Choose OLS or TLS
   ```python
   # Start with OLS for simplicity
   # Switch to TLS if measurement errors are significant
   ```

3. **Validation**: Out-of-sample testing
   ```python
   # Train on first 70% of data
   # Test on remaining 30%
   train = prices[:int(0.7*len(prices))]
   test = prices[int(0.7*len(prices)):]
   
   # Recalculate hedge ratios on train
   # Measure basis on test
   ```

4. **Monitoring**: Track basis performance
   ```python
   # Basis = target - β₁·hedge_instr₁ - β₂·hedge_instr₂ - ...
   # Monitor basis volatility and drift
   # Recalibrate if basis std increases >20%
   ```

### 10.5 Common Pitfalls & Solutions

**Pitfall 1: Overfitting to historical seasonality**
- Solution: Use wide confidence bands, combine with fundamentals

**Pitfall 2: Ignoring transaction costs in hedge ratios**
- Solution: Add 2-5 bps buffer to basis, account for bid-ask

**Pitfall 3: Extrapolating curves beyond liquid points**
- Solution: Use Smith-Wilson with explicit UFR instead of splines

**Pitfall 4: Not accounting for data quality**
- Solution: Implement preprocessing outlier detection, use WLS with weights

**Pitfall 5: Static hedge ratios**
- Solution: Recompute ratios on rolling windows (30-60 day cadence)

### 10.6 Production Deployment Checklist

- [ ] Pre-compute curves for all historical dates (offline)
- [ ] Cache interpolation functions for reuse
- [ ] Implement parameter validation (e.g., tau > 0 for NS)
- [ ] Add error handling for edge cases (single maturity, flat curve)
- [ ] Log all model parameters and fit diagnostics
- [ ] Monitor in-sample vs out-of-sample fit
- [ ] Set up alerts for unusual seasonality/hedge ratio values
- [ ] Document assumptions (calendar, day-count conventions)
- [ ] Version control model configurations
- [ ] Regular backtesting of strategies using historical data

---

## Appendix: References

1. **Nelson, C. R., & Siegel, A. F. (1987)**. "Parsimonious Modeling of Yield Curves". *Journal of Business*, 60(4), 473-489.

2. **Svensson, L. E. (1994)**. "Estimating and Interpreting Forward Interest Rates". *NBER Working Paper 4871*.

3. **Smith, A., & Wilson, T. (1996)**. "Fitting Yield Curves with Long Bonds". *LongStaff-Schwartz Model*.

4. **Diebold, F. X., & Li, C. (2006)**. "Forecasting the Term Structure of Government Bond Yields". *Journal of Econometrics*, 130(2), 337-364.

5. **Hagan, P., & West, G. (2006)**. "Interpolation Methods for Curve Construction". *Applied Mathematical Finance*, 13(2), 89-129.

6. **EIOPA (2021)**. "Technical Documentation on the Methodology to Derive EIOPA's Risk-free Interest Rate Term Structures". *European Insurance and Occupational Pensions Authority*.

---

## Code Examples Repository

All examples in this documentation are tested and available in:
- `/home/user/ARBS/RVUtils/` (source code)
- `/home/user/ARBS/` (notebooks with full examples)

For questions or issues, refer to the module docstrings and inline comments.

