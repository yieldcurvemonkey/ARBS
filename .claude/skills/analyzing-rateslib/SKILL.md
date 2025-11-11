---
name: analyzing-rateslib
description: Work with interest rate curves, instruments, and risk calculations using the rateslib library. Use when pricing swaps, analyzing curve dynamics, calculating Greeks, or implementing relative value strategies. Includes dual number methodology.
---

# Analyzing Rateslib

**Purpose**: Use rateslib library for interest rate derivatives pricing, curve analysis, and risk calculations.

## When to Use

- Pricing interest rate swaps and derivatives
- Building and analyzing yield curves
- Calculating risk sensitivities (Greeks/DV01)
- Implementing relative value trading strategies
- Curve construction with various interpolation methods
- Forward rate calculations
- Basis risk analysis

## Core Concepts

### Yield Curves

**Discount Factors (DF)**:
- DF(t) = Present value of $1 received at time t
- DF(0) = 1 (by definition)
- Monotonically decreasing: DF(t1) > DF(t2) for t1 < t2

**Zero Rates**:
- Continuously compounded rate from today to time t
- r(t) = -ln(DF(t)) / t

**Forward Rates**:
- Implied rate between two future dates
- f(t1,t2) = (DF(t1)/DF(t2))^(1/(t2-t1)) - 1

### Dual Number Methodology

**What are Dual Numbers**:
- Extension of real numbers: x + ε·dx where ε² = 0
- Automatic differentiation technique
- Used by rateslib for efficient Greek calculations

**How Rateslib Uses Dual Numbers**:
```python
from rateslib import Curve, Dual

# Create curve with dual number node
curve = Curve(
    nodes={...},
    ad=1  # Enable automatic differentiation
)

# When you price an instrument:
npv = swap.npv(curve)  # Returns Dual(value, gradient)

# Extract sensitivities
value = npv.real      # NPV in currency
dv01 = npv.gradient   # Risk sensitivity
```

**Benefits**:
- One pricing call gets both value and all risks
- No bumping required (faster and more accurate)
- Automatic adjoint calculation
- Memory efficient for large portfolios

## Common Workflows

### Workflow 1: Build Curve from Market Data

```python
from rateslib import Curve, IRS
from datetime import datetime as dt

# Define curve with market instruments
curve = Curve(
    nodes={
        dt(2024,1,1): 1.0,  # Today's DF
        **{dt(2024+i,1,1): None for i in range(1,11)}  # Nodes to solve
    },
    interpolation="log_linear"  # or "linear", "cubic"
)

# Define market instruments
instruments = [
    IRS(dt(2024,1,1), "2Y", spec="USD_IRS"),
    IRS(dt(2024,1,1), "5Y", spec="USD_IRS"),
    IRS(dt(2024,1,1), "10Y", spec="USD_IRS"),
]

market_rates = [4.5, 4.3, 4.1]  # Mid rates in %

# Solve for curve
curve = Curve.from_instruments(
    instruments=instruments,
    rates=market_rates
)
```

### Workflow 2: Price Instrument with Risks

```python
from rateslib import IRS

# Define swap
swap = IRS(
    effective=dt(2024,1,1),
    termination="5Y",
    spec="USD_IRS",
    notional=10_000_000,
    fixed_rate=4.25
)

# Price with curve (dual numbers automatically enabled)
npv = swap.npv(curves=curve)
dv01 = swap.delta(curves=curve)  # DV01 by tenor

# Analyze result
print(f"NPV: {npv:,.2f}")
print(f"Total DV01: {sum(dv01.values()):,.2f}")
```

### Workflow 3: Daily Overnight Forwards

**Multiple Implementation Methods** (see skill: `expanding-then-compressing`):

```python
from rateslib import Curve
from pandas import date_range

dates = date_range("2024-01-01", "2025-01-01", freq="1D")

# Method 1: Direct calculation
forwards = [curve.rate(d, d+timedelta(days=1)) for d in dates]

# Method 2: Using forward rates
forwards = [curve.forward_rate(d) for d in dates]

# Method 3: Finite differences
dfs = [curve.df(d) for d in dates]
forwards = np.diff(np.log(dfs)) * 365

# Method 4: Analytical (if curve supports derivatives)
forwards = curve.forward_rates(dates)
```

### Workflow 4: Relative Value Analysis

**Compare instruments for mispricings**:

```python
# Build curves for different tenors/instruments
sofr_curve = Curve.from_instruments(sofr_instruments, sofr_rates)
libor_curve = Curve.from_instruments(libor_instruments, libor_rates)

# Price same swap on both curves
swap = IRS(dt(2024,1,1), "5Y", spec="USD_IRS")

sofr_npv = swap.npv(curves=sofr_curve)
libor_npv = swap.npv(curves=libor_curve)

basis = libor_npv - sofr_npv  # Relative value signal
```

## Curve Interpolation Methods

### Log-Linear (Default)
- Interpolates log(DF) linearly
- Natural for discount factors
- No arbitrage by construction
- **Use when**: Building curves from swap rates

### Linear
- Interpolates DF or rates linearly
- Simple and intuitive
- Can create forward rate spikes
- **Use when**: Simple analysis or debugging

### Cubic Spline
- Smooth interpolation
- Continuous first derivative
- Can oscillate between nodes
- **Use when**: Smooth forward curves needed

### Mixed Interpolation
- Different methods for different regions
- Short end: log-linear
- Long end: linear
- **Use when**: Combining liquid and illiquid regions

## Common Pitfalls

**Pitfall 1: Mismatched Conventions**
- Problem: Using wrong day count or business day convention
- Fix: Always specify `spec` parameter (e.g., "USD_IRS", "EUR_IRS")
- Rateslib specs handle conventions automatically

**Pitfall 2: Not Using Dual Numbers**
- Problem: Bumping curves manually for risk
- Fix: Let rateslib handle it - dual numbers are automatic
- Benefit: Faster, more accurate, less code

**Pitfall 3: Over-Fitting Curves**
- Problem: Too many nodes, curve oscillates
- Fix: Use only as many nodes as market instruments
- Principle: One node per market quote

**Pitfall 4: Ignoring Turn Dates**
- Problem: Curve doesn't respect year-end effects
- Fix: Add explicit nodes at turn dates (Dec 31, etc.)
- Impact: More accurate overnight forwards

## Integration with Other Skills

**Use with**:
- `expanding-then-compressing` - Try multiple interpolation methods, choose best
- `implementing-adjoint-ad` - Understand dual number mechanics
- `axiom-relative-value` - Apply rateslib for trading analysis
- `analyzing-with-mcts` - Evaluate curve construction approaches

## Checklist

- [ ] Market data sourced and validated
- [ ] Conventions verified (day count, calendar, frequency)
- [ ] Interpolation method chosen based on use case
- [ ] Curve nodes aligned with market instruments
- [ ] Turn dates added if analyzing overnight forwards
- [ ] Dual numbers enabled for risk calculations
- [ ] Results compared to market pricing where possible
- [ ] Sensitivities validated (hedge ratios make sense)

## Example Use Cases from Memory

### Daily Overnight Forwards Example
See expanding-then-compressing skill for full pattern:
- Expand: Try 4 different calculation methods
- Compress: Choose analytical method, configure via YAML

### Curve Construction Example
- Build SOFR curve from futures and swaps
- Add turn dates for year-end effects
- Compare log-linear vs cubic interpolation
- Use dual numbers for efficient DV01

## Related Skills

- `implementing-adjoint-ad` - Dual number mathematics
- `integrating-quantlib` - Alternative pricing library
- `axiom-relative-value` - Trading strategy implementation
- `expanding-then-compressing` - Try multiple approaches

## Advanced Topics

See resources in this skill folder:
- `advanced-1-curve-construction.md` - Complex curve building patterns
- `advanced-2-dual-numbers.md` - Deep dive into automatic differentiation
- `advanced-3-relative-value.md` - Trading strategy implementation
