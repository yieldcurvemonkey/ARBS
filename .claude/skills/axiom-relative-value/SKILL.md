---
name: axiom-relative-value
description: Apply self-evident truth principles to relative value trading analysis. Use when analyzing rateslib and QuantLib for trading insights, identifying arbitrage opportunities, or understanding rate curve relationships.
---

# Axiom Relative Value

**Purpose**: Apply quantitative analysis and automatic differentiation to identify relative value trading opportunities.

## When to Use

- Identifying mispricings across related instruments
- Analyzing trading opportunities with real-time risk
- Comparing instruments for relative value
- Building mean-reversion strategies
- P&L attribution and risk decomposition
- Cross-asset arbitrage detection

## Core Trading Strategies

### 1. Treasury Basis Trading

**Concept**: Spread between Treasury futures and cheapest-to-deliver (CTD) cash bond.

**Analysis**:
```python
from rateslib import BondFuture, Bond, Curve

# Price futures and CTD
futures_price = 98.50
ctd_bond = Bond(...)
ctd_price = ctd_bond.npv(curve)
conversion_factor = 0.8123

# Calculate implied repo rate
implied_repo = calculate_implied_repo(
    futures_price,
    ctd_price,
    conversion_factor,
    days_to_delivery
)

# Compare to actual repo rate
actual_repo = 4.25  # From market
basis = implied_repo - actual_repo

# Trade signal: If basis > historical mean + 2std, sell basis
```

**P&L Attribution**:
```python
pnl_breakdown = {
    'futures_pnl': delta_futures * futures_price_change,
    'cash_pnl': delta_cash * ctd_price_change,
    'financing': notional * (actual_repo - entry_repo) * days/360,
    'carry': notional * coupon * days/360,
    'option_decay': gamma * 0.5 * futures_volatility_change
}

total_pnl = sum(pnl_breakdown.values())
```

### 2. Butterfly Strategies

**Concept**: DV01-neutral trades capturing curve shape changes.

**Construction**:
```python
from rateslib import IRS

# Define wings and body
short_swap = IRS(dt(2024,1,1), "2Y", spec="USD_IRS")
long_swap_1 = IRS(dt(2024,1,1), "5Y", spec="USD_IRS")
long_swap_2 = IRS(dt(2024,1,1), "10Y", spec="USD_IRS")

# Calculate DV01s (automatic with dual numbers)
dv01_2y = short_swap.delta(curve)
dv01_5y = long_swap_1.delta(curve)
dv01_10y = long_swap_2.delta(curve)

# DV01-neutral weights
belly_weight = 1.0
wing1_weight = -dv01_5y / (dv01_2y + dv01_10y) / 2
wing2_weight = -dv01_5y / (dv01_2y + dv01_10y) / 2

# Butterfly spread (in basis points)
fly_spread = (
    rate_5y * belly_weight +
    rate_2y * wing1_weight +
    rate_10y * wing2_weight
)

# Historical analysis
mean_fly = fly_spread_history.mean()
std_fly = fly_spread_history.std()
z_score = (fly_spread - mean_fly) / std_fly

# Trade signal: If z_score < -2, buy fly (curve expected to steepen belly)
```

**Carry and Roll**:
```python
# Today's butterfly
current_fly = calculate_butterfly(curve_today, "2Y", "5Y", "10Y")

# Tomorrow's butterfly assuming no curve change (roll)
rolled_curve = curve_today.shift(1, "days")
rolled_fly = calculate_butterfly(rolled_curve, "2Y", "5Y", "10Y")

carry_roll = rolled_fly - current_fly  # Daily P&L from passage of time
```

### 3. Fed Expectations Trading

**Concept**: Trade FOMC meeting outcomes via Fed Funds futures.

**Analysis**:
```python
from datetime import date

# Next FOMC meeting
meeting_date = date(2024, 9, 18)

# Current Fed Funds target range
current_lower = 5.00
current_upper = 5.25

# Fed Funds futures rate
futures_rate = 4.95

# Implied probabilities
implied_cuts = (current_lower - futures_rate) / 0.25  # Number of 25bp cuts priced

# If market prices 2.2 cuts but you expect only 1 cut
# Sell futures (receive higher rate)
expected_rate = current_lower - (1 * 0.25)  # 4.75%
mispricing = expected_rate - futures_rate  # 4.75 - 4.95 = -0.20%

# Trade construction
notional = 10_000_000
dv01_per_bp = notional * 30/360 * 0.01  # Simplified
expected_pnl = mispricing * 100 * dv01_per_bp  # -20 bps profit if right
```

### 4. Principal Component Analysis

**Concept**: Decompose curve movements into level, slope, curvature.

**Implementation**:
```python
import numpy as np
from sklearn.decomposition import PCA

# Historical rate changes (rows=days, cols=tenors)
rate_changes = np.array([...])  # Shape: (N_days, N_tenors)

# PCA
pca = PCA(n_components=3)
pca.fit(rate_changes)

# Components
level = pca.components_[0]      # PC1: Parallel shift
slope = pca.components_[1]      # PC2: 2s10s slope
curvature = pca.components_[2]  # PC3: Butterfly

# Current curve vs mean in PC space
current_projection = pca.transform([current_changes])[0]
historical_mean = pca.transform(rate_changes).mean(axis=0)

deviation = current_projection - historical_mean

# Trade signal: If slope deviation > 2 std, fade it (mean reversion)
if abs(deviation[1]) > 2 * slope_std:
    # Trade 2s10s steepener/flattener
```

### 5. Cross-Currency Basis

**Concept**: Arbitrage differences between FX forward markets and interest rate differentials.

**Analysis**:
```python
# Covered Interest Parity
# F/S = (1 + r_domestic * t) / (1 + r_foreign * t)

spot_fx = 1.0800  # EUR/USD
forward_fx = 1.0750  # 1 year forward
usd_rate = 0.0450
eur_rate = 0.0350

# Implied EUR rate from forward
implied_eur_rate = (spot_fx / forward_fx - 1 + usd_rate)
# = 1.0800/1.0750 - 1 + 0.045 = 0.00465 + 0.045 = 0.0496

# Basis
basis = implied_eur_rate - eur_rate  # 0.0496 - 0.0350 = 0.0146 (146 bps)

# If basis is wide:
# Borrow EUR at 3.5%, convert to USD at spot, lend USD at 4.5%
# Cover with forward at 1.0750
# Profit: 4.5% - (3.5% + forward_cost) = basis
```

### 6. Volatility Trading (Gamma & Vega)

**Concept**: Trade option gamma and vega exposures.

**Delta-Hedged Straddle**:
```python
# Long straddle at-the-money
strike = 100.0
call_price = 5.0
put_price = 5.0

# Greeks (from Black-Scholes or QuantLib)
call_delta = 0.50
put_delta = -0.50
combined_delta = 0.0  # Delta-neutral by construction

gamma = 0.05  # Same for call and put ATM
vega = 0.30

# Daily rehedging P&L
underlying_moves = [101, 99, 102, 98, ...]  # Daily prices

cumulative_pnl = 0
for price in underlying_moves:
    # Gamma profit from rehedging
    move = price - strike
    gamma_pnl = 0.5 * gamma * move**2

    # Theta decay
    theta = -0.10  # Per day
    theta_pnl = theta

    # Net daily P&L
    daily_pnl = gamma_pnl + theta_pnl
    cumulative_pnl += daily_pnl

# Trade profitable if realized vol > implied vol
```

## The Axiom Approach

**Self-Evident Truths in Trading**:

1. **Markets Mean-Revert**: Extreme deviations from historical norms tend to correct
2. **Arbitrage Gets Competed Away**: Free money disappears quickly
3. **Risk Must Be Real-Time**: Stale risk numbers cause blow-ups
4. **Complexity Requires Clarity**: Simple interfaces prevent errors

**Automatic Differentiation Philosophy**:

Every calculation should automatically provide:
- **Value**: The price or P&L
- **Derivatives**: All Greeks without bumping

```python
# Axiom ideal (conceptual)
result = strategy.analyze(market_data)

print(result.value)           # Trade P&L
print(result.derivatives)     # All sensitivities automatically
```

**Current Implementation** (using rateslib):
```python
from rateslib import Curve, IRS

# Build curve with AD enabled
curve = Curve.from_instruments(instruments, rates)

# Price swap (dual numbers automatic)
swap = IRS(...)
npv = swap.npv(curve)  # Returns Dual object

# Extract value and all sensitivities
value = npv.real
dv01_by_tenor = npv.gradient  # All curve point sensitivities
```

## Integration with Skills

**Use with**:
- `analyzing-rateslib` - Implementation of curve and instrument analysis
- `implementing-adjoint-ad` - Understanding the automatic differentiation
- `integrating-quantlib` - Complex instrument pricing
- `expanding-then-compressing` - Try multiple strategy implementations
- `analyzing-with-mcts` - Evaluate trading approaches

## Checklist

- [ ] Market data sourced and validated
- [ ] Historical statistics calculated (mean, std, z-scores)
- [ ] Risk sensitivities calculated automatically (using AD)
- [ ] Trade construction DV01-neutral or risk-weighted
- [ ] Entry and exit criteria defined
- [ ] Position sizing based on volatility and risk budget
- [ ] P&L attribution framework established
- [ ] Monitoring and alerts configured

## Common Pitfalls

**Pitfall 1: Ignoring Transaction Costs**
- Problem: Strategy looks profitable but bid-ask kills returns
- Fix: Include slippage, commissions, and financing costs

**Pitfall 2: Over-Fitting Historical Data**
- Problem: Strategy works perfectly in backtest, fails live
- Fix: Use out-of-sample testing and regime analysis

**Pitfall 3: Neglecting Risk**
- Problem: Small edge with huge position leads to blowup
- Fix: Size positions based on volatility and VaR

**Pitfall 4: Complexity Without Clarity**
- Problem: Strategy too complex to understand what went wrong
- Fix: Use simple interfaces even for complex strategies

## Related Skills

- `analyzing-rateslib` - Curve and instrument pricing
- `implementing-adjoint-ad` - Efficient Greeks calculation
- `integrating-quantlib` - Complex derivatives pricing
- `analyzing-with-mcts` - Strategy evaluation framework
- `evaluating-alpha-beta-gamma` - Multi-timeframe trade management

## Advanced Topics

See resources in this skill folder:
- `advanced-1-strategy-implementation.md` - Detailed strategy code
- `advanced-2-risk-management.md` - Position sizing and VaR
- `advanced-3-execution-tactics.md` - Trade entry and exit
- `advanced-4-pnl-attribution.md` - Decomposing trade returns
