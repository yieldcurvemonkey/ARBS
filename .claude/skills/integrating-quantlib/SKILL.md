---
name: integrating-quantlib
description: Use QuantLib for derivatives pricing, yield curve construction, and financial instrument valuation. Use when working with complex derivatives, calibrating models, or implementing quantitative finance workflows.
---

# Integrating QuantLib

**Purpose**: Use QuantLib C++ library (and Python bindings) for comprehensive derivatives pricing and risk analysis.

## When to Use

- Complex derivatives pricing (exotics, structured products)
- Model calibration (volatility surfaces, term structures)
- Monte Carlo simulations
- Need production-grade library with extensive validation
- Integration with existing C++ infrastructure
- Advanced features not in rateslib (options, volatility, etc.)

## Core Capabilities

### Yield Curve Construction

**QuantLib Approach**:
```python
import QuantLib as ql

# Set evaluation date
ql.Settings.instance().evaluationDate = ql.Date(1, 1, 2024)

# Define market instruments
depo_helpers = [
    ql.DepositRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate/100)),
        tenor,
        2,  # settlement days
        calendar,
        ql.Following,
        False,
        day_count
    )
    for tenor, rate in depo_data
]

swap_helpers = [
    ql.SwapRateHelper(
        ql.QuoteHandle(ql.SimpleQuote(rate/100)),
        tenor,
        calendar,
        ql.Annual,
        ql.Unadjusted,
        day_count,
        index
    )
    for tenor, rate in swap_data
]

# Build curve
curve = ql.PiecewiseLogCubicDiscount(
    settlement_date,
    depo_helpers + swap_helpers,
    day_count
)
curve.enableExtrapolation()
```

### Instrument Pricing

**Interest Rate Swap**:
```python
# Create fixed leg
fixed_schedule = ql.Schedule(
    effective_date,
    maturity_date,
    ql.Period(ql.Annual),
    calendar,
    ql.Unadjusted,
    ql.Unadjusted,
    ql.DateGeneration.Forward,
    False
)

fixed_leg = ql.FixedRateLeg(
    fixed_schedule,
    day_count,
    [notional],
    [fixed_rate]
)

# Create floating leg
float_schedule = ql.Schedule(
    effective_date,
    maturity_date,
    ql.Period(ql.Quarterly),
    calendar,
    ql.ModifiedFollowing,
    ql.ModifiedFollowing,
    ql.DateGeneration.Forward,
    False
)

float_leg = ql.IborLeg(
    [notional],
    float_schedule,
    index
)

# Create swap
swap = ql.Swap(fixed_leg, float_leg)

# Create pricing engine
engine = ql.DiscountingSwapEngine(
    ql.YieldTermStructureHandle(curve)
)
swap.setPricingEngine(engine)

# Get NPV and Greeks
npv = swap.NPV()
dv01 = swap.DV01()  # Requires bumping
```

### Volatility Surfaces

**Option Pricing with Vol Surface**:
```python
# Build volatility surface
strikes = [0.95, 1.00, 1.05, 1.10]
expiries = [ql.Period(3, ql.Months), ql.Period(6, ql.Months), ...]
vols = [[0.15, 0.14, ...], [...], ...]  # 2D array

vol_matrix = ql.Matrix(len(expiries), len(strikes))
for i, exp_vols in enumerate(vols):
    for j, vol in enumerate(exp_vols):
        vol_matrix[i][j] = vol

vol_surface = ql.BlackVarianceSurface(
    settlement_date,
    calendar,
    expiries,
    strikes,
    vol_matrix,
    day_count
)

# Use in option pricing
payoff = ql.PlainVanillaPayoff(ql.Option.Call, strike)
exercise = ql.EuropeanExercise(expiry_date)
option = ql.VanillaOption(payoff, exercise)

process = ql.BlackScholesMertonProcess(
    ql.QuoteHandle(spot_quote),
    ql.YieldTermStructureHandle(div_curve),
    ql.YieldTermStructureHandle(risk_free_curve),
    ql.BlackVolTermStructureHandle(vol_surface)
)

engine = ql.AnalyticEuropeanEngine(process)
option.setPricingEngine(engine)

price = option.NPV()
delta = option.delta()
vega = option.vega()
```

## QuantLib vs Rateslib

### When to Use QuantLib

**Advantages**:
- More instruments (options, exotics, credit, equity)
- Volatility surface handling
- Monte Carlo and PDE solvers
- Production-tested over 20+ years
- Extensive documentation and community

**Disadvantages**:
- Heavier library (slower compilation, larger binary)
- More verbose API
- Manual Greek calculation (no built-in AAD)
- Steeper learning curve

### When to Use Rateslib

**Advantages**:
- Modern Python-first design
- Built-in automatic differentiation (dual numbers)
- Faster for standard rates workflows
- Simpler API for swaps and curves
- Lightweight

**Disadvantages**:
- Limited to rates products
- Smaller community
- Less exotic instrument support
- Newer (less battle-tested)

**Recommendation**:
- Use rateslib for standard rates workflows (see skill: `analyzing-rateslib`)
- Use QuantLib for exotic derivatives, options, or model calibration
- Consider hybrid: rateslib for curves, QuantLib for complex pricing

## Common Workflows

### Workflow 1: Build Multi-Curve Framework

**Post-2008 requires separate projection and discounting curves**:

```python
# Discount curve (OIS)
ois_curve = ql.PiecewiseLogCubicDiscount(
    settlement_date,
    ois_helpers,
    day_count
)

# Projection curve (LIBOR)
libor_curve = ql.PiecewiseLogCubicDiscount(
    settlement_date,
    libor_helpers,
    day_count
)

# Create index with projection curve
libor_index = ql.USDLibor(
    ql.Period(3, ql.Months),
    ql.YieldTermStructureHandle(libor_curve)
)

# Price swap with separate curves
engine = ql.DiscountingSwapEngine(
    ql.YieldTermStructureHandle(ois_curve)  # Discount with OIS
)
# Floating leg projects from libor_curve via libor_index
```

### Workflow 2: Calculate Greeks via Bumping

**QuantLib requires manual bumping** (no AAD):

```python
def calculate_dv01(swap, curve, bump_size=1e-4):
    """Calculate DV01 by parallel shift"""
    original_npv = swap.NPV()

    # Bump curve up
    for helper in curve.instruments():
        quote = helper.quote()
        quote.setValue(quote.value() + bump_size)

    curve.recalculate()
    bumped_npv = swap.NPV()

    # Unbump
    for helper in curve.instruments():
        quote = helper.quote()
        quote.setValue(quote.value() - bump_size)

    curve.recalculate()

    dv01 = (bumped_npv - original_npv) / bump_size
    return dv01
```

**Limitation**: Must bump and reprice for each Greek
**Alternative**: Use rateslib for Greeks if possible (automatic via dual numbers)

### Workflow 3: Model Calibration

**Calibrate Hull-White model to swaption prices**:

```python
# Market swaption volatilities
swaption_helpers = [
    ql.SwaptionHelper(
        expiry,
        tenor,
        ql.QuoteHandle(ql.SimpleQuote(vol/100)),
        index,
        tenor,
        day_count,
        day_count,
        ql.YieldTermStructureHandle(curve),
        ql.BlackCalibrationHelper.RelativePriceError
    )
    for expiry, tenor, vol in swaption_data
]

# Create model
model = ql.HullWhite(ql.YieldTermStructureHandle(curve))

# Calibration engine
optimization = ql.LevenbergMarquardt()
end_criteria = ql.EndCriteria(1000, 100, 1e-8, 1e-8, 1e-8)

model.calibrate(
    swaption_helpers,
    optimization,
    end_criteria
)

# Extract calibrated parameters
a = model.params()[0]  # Mean reversion
sigma = model.params()[1]  # Volatility
```

## Integration Patterns

### Pattern 1: Rateslib for Curves, QuantLib for Pricing

```python
# Build curve with rateslib (simpler API, faster)
from rateslib import Curve
rl_curve = Curve.from_instruments(instruments, rates)

# Export curve to QuantLib format
def export_to_quantlib(rl_curve):
    dates = [...] # Extract from rateslib curve
    dfs = [rl_curve.df(d) for d in dates]

    # Create QuantLib curve
    ql_curve = ql.DiscountCurve(dates, dfs, day_count)
    return ql_curve

# Use QuantLib for complex pricing
ql_curve = export_to_quantlib(rl_curve)
option_price = price_with_quantlib(ql_curve, option_params)
```

### Pattern 2: QuantLib for Calibration, Rateslib for Greeks

```python
# Calibrate model with QuantLib
model = calibrate_hull_white(market_data)

# Generate scenarios with QuantLib
scenarios = generate_scenarios(model)

# Calculate Greeks with rateslib (faster AAD)
for scenario in scenarios:
    rl_curve = build_rateslib_curve(scenario)
    greeks = calculate_all_greeks(portfolio, rl_curve)  # Uses dual numbers
```

## Checklist

- [ ] QuantLib installed (pip install QuantLib-Python or build from source)
- [ ] Date conventions defined (calendar, day count)
- [ ] Market data sourced and validated
- [ ] Curve construction method chosen (piecewise, spline, etc.)
- [ ] Instruments defined with correct specifications
- [ ] Pricing engines selected and configured
- [ ] Greek calculation method determined (bump or alternative)
- [ ] Results validated against market or alternative pricer

## Common Pitfalls

**Pitfall 1: Global Evaluation Date**
- Problem: QuantLib uses global singleton for "today"
- Fix: Always set explicitly: `ql.Settings.instance().evaluationDate = date`

**Pitfall 2: Handle Lifetime**
- Problem: Python GC deletes objects while QuantLib still references them
- Fix: Keep references to Quote/Handle objects until pricing complete

**Pitfall 3: Calendar Mismatch**
- Problem: Using wrong calendar for instrument
- Fix: Verify calendar matches currency/market (UnitedStates vs TARGET)

**Pitfall 4: Forgetting recalculate()**
- Problem: Curve not updated after bumping quotes
- Fix: Call `curve.recalculate()` after changing inputs

## Integration with Other Skills

**Use with**:
- `analyzing-rateslib` - Compare approaches, hybrid workflows
- `implementing-adjoint-ad` - Understand QuantLib's AAD implementation
- `axiom-relative-value` - Price complex structures for trading
- `expanding-then-compressing` - Try QuantLib vs rateslib approaches

## Related Skills

- `analyzing-rateslib` - Alternative rates library
- `implementing-adjoint-ad` - Efficient Greeks calculation
- `axiom-relative-value` - Trading application

## Advanced Topics

See resources in this skill folder:
- `advanced-1-monte-carlo.md` - Monte Carlo pricing with QuantLib
- `advanced-2-model-calibration.md` - Detailed calibration workflows
- `advanced-3-exotic-derivatives.md` - Pricing complex structures
