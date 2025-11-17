# Returns vs Prices - Mathematical Foundation

This document explains why ARBS uses returns as the primary data structure instead of prices.

---

## The Fundamental Issue

**Prices are levels (non-stationary), Returns are differences (stationary)**

This distinction is critical for proper portfolio mathematics.

## Why Prices Don't Work for Portfolio Math

### 1. Prices Are Non-Stationary

```
Price series: P_t = [95, 96, 97, 98, 99, 100, ...]
- Trends over time (upward drift)
- Mean changes over time (non-stationary)
- Variance grows with time
- Can't do meaningful statistics (mean, covariance) on levels
```

**Problem**: Covariance of prices doesn't make mathematical sense.
- Cov(P_A, P_B) depends on time period
- Not comparable across assets with different price levels
- Meaningless for portfolio optimization

### 2. Returns Are (More) Stationary

```
Return series: r_t = [(P_t - P_{t-1}) / P_{t-1}]
            = [0.0105, 0.0104, 0.0103, 0.0102, ...]
- Mean relatively stable over time
- Variance relatively stable
- Stationary (or close to it)
- Meaningful statistics possible
```

**Solution**: Covariance of returns is well-defined.
- Cov(r_A, r_B) is meaningful
- Comparable across assets
- Foundation for portfolio optimization

### 3. Aggregation Properties

**Prices don't aggregate**:
```
P_portfolio ≠ Σ w_i × P_i  (WRONG!)

Example:
- Asset A: $100, weight 50%
- Asset B: $200, weight 50%
- Portfolio "price" = 0.5×100 + 0.5×200 = $150 ???
- This is meaningless - can't combine prices across assets
```

**Returns DO aggregate**:
```
r_portfolio = Σ w_i × r_i  (CORRECT!)

Example:
- Asset A: return 5%, weight 50%
- Asset B: return 10%, weight 50%
- Portfolio return = 0.5×0.05 + 0.5×0.10 = 0.075 (7.5%)
- This is mathematically sound
```

## Grinold-Kahn Framework

### Core Equation

```
U(w) = α'w - (λ/2) × w'Σw

where:
- α = vector of expected RETURNS (alphas)
- Σ = covariance matrix of RETURNS
- w = portfolio weights
- λ = risk aversion
```

**Key insight**: Everything is in terms of RETURNS, not prices.

### Components

1. **Alphas (α)**: Expected excess returns
   - α_i = E[r_i] - r_f
   - Units: return (e.g., 0.01 = 1% expected return)
   - Not price changes in dollars

2. **Covariance (Σ)**: Covariance of returns
   - Σ_ij = Cov(r_i, r_j)
   - Units: return^2
   - Estimated from historical returns, not prices

3. **Portfolio Return**: Weighted sum of returns
   - r_portfolio = w'r
   - Units: return
   - NOT weighted sum of prices

### Information Ratio

```
IR = IC × sqrt(BR)

where:
- IC = Information Coefficient = Corr(α, r)
- BR = Breadth (number of independent bets)
```

**IC measures correlation between FORECASTED returns (α) and REALIZED returns (r)**
- Not correlation between price forecasts and realized prices
- Returns are the fundamental variable

## Current Design Flaws

### Flaw 1: Portfolio Works with Prices

```python
# Current (WRONG conceptually):
portfolio.calculate_return(
    prev_prices={'A': 95, 'B': 100},
    curr_prices={'A': 96, 'B': 101}
)
```

**Issues**:
1. Portfolio extracts prices, calculates returns internally
2. Repeats price→return conversion for each asset
3. Mixes concerns (portfolio should work with returns)
4. Inefficient (convert prices→returns multiple times)

### Flaw 2: Backtest Stores Prices, Not Returns

```python
# Current:
all_prices.append({'date': as_of, 'SFRZ4': 95.0, 'SFRH5': 94.9})
```

**Issues**:
1. Storing levels instead of differences
2. Have to convert to returns each time we need them
3. Covariance estimated from returns calculated from prices
4. Extra conversion step every time

## Correct Design

### Principle: Data Layer Converts Prices → Returns ONCE

```
Raw Data (prices) → Data Layer → Returns → All downstream components

Prices: P_t             [95.0, 96.0, 97.0, ...]
         ↓ (convert once)
Returns: r_t            [0.0105, 0.0104, ...]
         ↓
Alpha Generation        α_t (forecasted returns)
Risk Estimation         Σ (covariance of returns)
Optimization            w* = argmax(α'w - λ/2×w'Σw)
Portfolio P&L           r_portfolio = w'r
```

### Design 1: Portfolio Accepts Returns Directly

```python
class Portfolio(Asset):
    def calculate_return(self, returns: Dict[str, float]) -> float:
        """
        Calculate portfolio return from constituent returns.

        Args:
            returns: Map from asset ID → realized return

        Returns:
            Portfolio return as weighted sum

        Formula:
            r_portfolio = Σ w_i × r_i

        Example:
            >>> returns = {'SFRZ4': 0.0105, 'SFRH5': 0.0053}
            >>> port.calculate_return(returns)
            0.0084  # Weighted average
        """
        portfolio_return = 0.0
        for position in self.positions:
            asset_id = position.asset.get_identifier()
            asset_return = returns.get(asset_id, 0.0)
            weight = position.quantity
            portfolio_return += weight * asset_return
        return portfolio_return
```

**Benefits**:
1. Simple weighted sum (clear, efficient)
2. No price extraction needed
3. Works with return data directly
4. Matches Grinold-Kahn framework

### Design 2: Backtest Maintains Returns

```python
class Backtest:
    def run(self, contracts, dates):
        # Convert prices to returns ONCE at data layer
        for i, as_of in enumerate(dates):
            # Get prices from data source
            prices = self.get_prices(contracts, as_of)

            # Convert to returns (if we have previous prices)
            if previous_prices is not None:
                returns = {}
                for contract in contracts:
                    r = (prices[contract] - previous_prices[contract]) / previous_prices[contract]
                    returns[contract] = r

                # Store returns (not prices!)
                return_history.append(returns)

                # Calculate portfolio return directly from returns
                port_return = portfolio.calculate_return(returns)
                all_returns.append(port_return)

            previous_prices = prices

        # Estimate covariance from return history
        returns_df = pd.DataFrame(return_history)
        cov_matrix = self.risk_model.fit(returns_df)
```

**Benefits**:
1. Returns are fundamental data structure
2. Covariance estimated from returns directly
3. No repeated price→return conversions
4. Cleaner separation of concerns

## Return Types

### Percent Returns (Relative)

```
r_t = (P_t - P_{t-1}) / P_{t-1}

- Scale-free (works across different price levels)
- Additive for portfolio: r_portfolio = Σ w_i × r_i
- Standard in Grinold-Kahn
- Used for cross-sectional comparison
```

**Best for**: Portfolio optimization, alpha generation, IC calculation

### Log Returns

```
r_t = log(P_t / P_{t-1}) = log(P_t) - log(P_{t-1})

- Time-additive: r_0→t = Σ r_i
- Approximately equal to percent returns for small changes
- Better statistical properties (more normal)
```

**Best for**: Time-series analysis, volatility estimation

### Dollar Returns (Absolute)

```
r_t = P_t - P_{t-1}

- Not scale-free (depends on price level)
- NOT additive for portfolio
- Used for P&L accounting
```

**Best for**: Actual P&L calculation, accounting

### Recommendation

Use **percent returns** throughout system:
1. Data layer converts prices → percent returns
2. Portfolio aggregates percent returns
3. Covariance estimated from percent returns
4. Alphas expressed as percent returns
5. IC calculated from percent returns

Convert to dollar P&L only at final reporting stage.

## Implementation Plan

### Phase 1: Refactor Portfolio to Accept Returns

```python
# Old:
portfolio.calculate_return(prev_prices, curr_prices)

# New:
portfolio.calculate_return(returns)
```

Changes:
- Portfolio.calculate_return(returns: Dict[str, float]) → float
- Remove price extraction logic
- Simple weighted sum of returns

### Phase 2: Refactor Backtest to Work with Returns

```python
# Old:
all_prices.append({'date': as_of, **prices})
return_history calculated from prices each time

# New:
returns = self._calculate_returns(prices, previous_prices)
return_history.append(returns)
portfolio_return = portfolio.calculate_return(returns)
```

Changes:
- Convert prices → returns once per period
- Store returns (not prices)
- Pass returns to portfolio
- Covariance from returns directly

### Phase 3: Update Asset Interface

```python
class Asset(ABC):
    # Old:
    def calculate_return(self, prev_price: float, curr_price: float) -> float:
        pass

    # New (optional - might not need this):
    # Assets might not calculate their own returns
    # Returns come from external source (data layer)
```

**Question**: Should assets calculate returns at all?
- Current: Asset.calculate_return(prev, curr) calculates return from prices
- Alternative: Returns provided externally, Asset just identifies itself
- Grinold-Kahn: Returns are data inputs, not calculated by assets

### Phase 4: Separate Data Layer from Business Logic

```
Data Layer:          prices_t → returns_t
Signal Layer:        returns_t → alphas_t
Risk Layer:          returns_history → Σ
Optimization Layer:  alphas_t, Σ → w*
Execution Layer:     w*, returns_t → r_portfolio
```

Clear separation:
- Data layer owns price→return conversion
- Business logic works only with returns

## Mathematical Correctness

### Covariance of Returns

```
Σ = Cov(r)
Σ_ij = E[(r_i - μ_i)(r_j - μ_j)]

where r_i are RETURNS, not prices
```

**This is mathematically sound for:**
- Portfolio variance: σ²_portfolio = w'Σw
- Mean-variance optimization
- Risk decomposition

### Portfolio Return

```
r_portfolio = w'r = Σ w_i × r_i

where:
- r_i are asset RETURNS
- w_i are weights
- Result is portfolio RETURN
```

**Properties**:
- Linear in returns (correct)
- Weights sum to 1 (budget constraint)
- Return is scale-free (comparable across portfolios)

### Information Coefficient

```
IC = Corr(α, r)

where:
- α = forecasted returns
- r = realized returns
```

**Both must be returns** (not prices) for IC to be meaningful.

## Conclusion

**Current State**: Portfolio and backtest work with prices, converting to returns internally.

**Problem**: Violates Grinold-Kahn framework, inefficient, conceptually wrong.

**Solution**: Refactor to work with returns as fundamental data:
1. Data layer converts prices → returns ONCE
2. All downstream components work with returns
3. Portfolio simply aggregates returns
4. Covariance estimated from returns directly
5. Backtest tracks return history (not price history)

**Benefits**:
- Mathematically correct (stationary data)
- Efficient (convert once, not repeatedly)
- Clear separation of concerns
- Matches academic framework (Grinold-Kahn)
- Simpler code (no repeated conversions)

**Next Steps**:
1. Refactor Portfolio.calculate_return() to accept returns dict
2. Refactor MinimalBacktest to convert prices→returns once per period
3. Update tests to use returns instead of prices
4. Verify IC calculation uses returns (not prices)

---

## Current Implementation

The returns-first architecture is implemented throughout ARBS:

- ReturnsCalculator handles price-to-returns conversion (16 tests)
- VolatilityEstimator forecasts volatility from returns (18 tests)
- AlphaGenerator creates scaled alphas from signals (16 tests)
- TearSheet analyzes portfolio performance (19 tests)
- Portfolio.calculate_return() accepts returns directly
- Backtest uses ReturnsCalculator and AlphaGenerator
- Covariance estimation operates on returns
- IC calculation uses returns

Total: 582 tests in test suite
