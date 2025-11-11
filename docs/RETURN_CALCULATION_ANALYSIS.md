# Return Calculation Analysis

**Document Status**: Analysis Complete
**Date Written**: 2025-11-11
**Implementation Status**: Phase 1 Complete (Returns infrastructure, AlphaGenerator, VolatilityEstimator)
**Last Updated**: 2025-11-11

---

## Current Implementation Review

Location: `Backtest/MinimalBacktest.py` lines 156-172

```python
# Calculate returns if we have previous prices
if previous_prices is not None and previous_weights is not None:
    # Align prices
    common_contracts = list(set(prices.index) & set(previous_prices.index))
    if len(common_contracts) > 0:
        ret = {}
        for c in common_contracts:
            if previous_prices[c] > 0:
                ret[c] = (prices[c] - previous_prices[c]) / previous_prices[c]
        returns = pd.Series(ret)
        return_history.append(returns)

        # Calculate portfolio return
        common_in_weights = list(set(common_contracts) & set(previous_weights.index))
        if len(common_in_weights) > 0:
            port_ret = sum(previous_weights[c] * returns.get(c, 0.0) for c in common_in_weights)
            all_returns.append({'date': as_of, 'return': port_ret})
```

## Identified Flaws

### ✅ Flaw 1: Timing Logic is Correct

**Analysis**: The code uses `previous_weights * current_returns`, which is correct for backtesting:
1. At t-1: We set weights `w_{t-1}` based on signals
2. From t-1 to t: Prices change, generating returns `r_t`
3. At t: Our P&L is `w_{t-1}' × r_t`

**Status**: **NOT A FLAW** - timing logic is correct.

### ⚠️ Flaw 2: Silent Zero Returns for Missing Contracts

**Code**: `returns.get(c, 0.0)`

**Problem**: If a contract is in `previous_weights` but not in `returns`, it silently gets 0.0 return.

**Scenarios**:
- Contract expired between t-1 and t → Should handle roll or liquidation
- Data missing for contract → Should raise warning
- Price is NaN or invalid → Currently skipped silently

**Impact**: Hidden errors, incorrect P&L if positions aren't properly closed

**Fix**:
```python
# Explicit handling of missing returns
for c in previous_weights.index:
    if c not in returns:
        logger.warning(f"No return for contract {c} at {as_of} - using 0.0")
        returns[c] = 0.0
```

### 🔴 Flaw 3: No Handling of Contract Universe Changes

**Problem**: Universe changes between periods are not explicitly managed.

**Case 1: New contract appears**
- Contract Z not in t-1, appears at t
- No previous price → No return calculated (correct)
- No previous weight → No P&L impact (correct)
- **Status**: Handled correctly by intersection

**Case 2: Old contract disappears**
- Contract X in t-1, gone at t
- Had weight at t-1: `w_{t-1,X} > 0`
- No price at t → No return → **P&L not calculated**
- **Status**: **FLAW** - we're missing P&L from expired positions

**Example**:
```
t-1: Hold SFRZ4 with weight 0.25 at price 95.00
t:   SFRZ4 expired (not in universe), switched to SFRH5
     → Return for SFRZ4 not calculated
     → Position silently disappears
     → P&L is WRONG
```

**Impact**: Incorrect total returns, especially for futures with expirations

**Fix**: Track contract lifecycle explicitly:
```python
# Check for positions in expired contracts
for c in previous_weights.index:
    if c not in prices.index:
        # Contract disappeared - need to handle roll or liquidation
        if c in previous_prices.index:
            # We had a price last period, now it's gone
            # Assume liquidated at last known price (or 0 for expired)
            logger.warning(f"Contract {c} disappeared at {as_of} - marking as expired")
            returns[c] = -1.0  # Total loss if expired worthless
```

### 🔴 Flaw 4: No Explicit Contract Roll Handling

**Problem**: Futures contracts roll to next expiry, but current code doesn't handle this.

**Current behavior**:
- SFRZ4 expires Dec 15
- On Dec 16: SFRZ4 not in universe, SFRH5 is
- Weight in SFRZ4 silently becomes 0
- No explicit roll transaction

**Correct behavior should**:
1. Detect when contract is near expiry
2. Close position in front contract (SFRZ4)
3. Open position in next contract (SFRH5)
4. Calculate P&L from roll: `(P_next - P_front) / P_front`

**Impact**:
- Missing roll costs (bid-ask spread)
- Incorrect P&L attribution
- Can't measure roll yield accurately

**Fix**: Explicit roll management:
```python
def handle_roll(contract, roll_date, next_contract, positions):
    """Handle rolling from one contract to next."""
    if as_of >= roll_date:
        # Close front contract
        pnl_close = calculate_return(contract, positions[contract])
        # Open next contract        positions[next_contract] = positions.pop(contract)
        # Record roll transaction        return pnl_close
```

### 🔴 Flaw 5: Assumes Price-Based Returns for All Assets

**Code**: `ret[c] = (prices[c] - previous_prices[c]) / previous_prices[c]`

**Problem**: This formula assumes:
- Assets are quoted as prices (not yields)
- $1 invested returns (P_t - P_{t-1}) / P_{t-1}
- No DV01 or notional adjustments needed

**Doesn't work for**:
1. **Yield-quoted instruments**: Bond futures, swap rates
   - 10Y bond: price goes DOWN when yield goes UP
   - Need to invert: `ret = -(yield_t - yield_{t-1}) * DV01`

2. **Fixed income with DV01**:
   - $1 change in price has different $ impact depending on DV01
   - Return = `(price_t - price_{t-1}) * DV01 / notional`

3. **Different notional sizes**:
   - E-mini SPX future: $50 per point
   - Crude oil future: $1000 per barrel
   - Need notional adjustment

**Impact**: Can't backtest mixed portfolios with different asset types

**Fix**: Abstract return calculation per asset type (see Flaw 6)

### 🔴 Flaw 6: No Abstraction - Violates Open/Closed Principle

**Problem**: Return calculation is hardcoded in backtest loop. To add new asset types, we'd need to modify the backtest code.

**Violates**: Open/Closed Principle (open for extension, closed for modification)

**Current**:
```python
# Hardcoded in backtest
ret[c] = (prices[c] - previous_prices[c]) / previous_prices[c]
```

**Proposed**: Abstract Asset interface
```python
class Asset(ABC):
    @abstractmethod
    def calculate_return(self, prev_price, curr_price) -> float:
        """Calculate return from price change."""
        pass

class PriceFuture(Asset):
    def calculate_return(self, prev_price, curr_price) -> float:
        return (curr_price - prev_price) / prev_price if prev_price > 0 else 0.0

class YieldInstrument(Asset):
    def __init__(self, dv01):
        self.dv01 = dv01

    def calculate_return(self, prev_yield, curr_yield) -> float:
        # Return = -(yield change) * DV01 / 100
        return -(curr_yield - prev_yield) * self.dv01 / 100
```

**Benefits**:
- Add new asset types without modifying backtest
- Each asset encapsulates its own return logic
- Type-safe with proper abstractions
- Testable in isolation

## Proposed Solution: Asset Abstraction

### Design Principles

1. **Polymorphism**: Each asset type knows how to calculate its own return
2. **Composition**: Backtest composes Asset objects, doesn't hardcode logic
3. **Extensibility**: New asset types added without changing backtest
4. **Testability**: Each Asset class has isolated unit tests

### Proposed Architecture

```
Asset (ABC)
├── calculate_return(prev_price, curr_price) -> float
├── get_identifier() -> str
└── handle_corporate_actions(date) -> Optional[AssetTransition]

PriceFuture(Asset)
├── Simple futures with price-based returns
└── Examples: SPX, Crude Oil, SOFR futures

YieldInstrument(Asset)
├── Instruments quoted in yield with DV01
├── calculate_return uses DV01 * yield change
└── Examples: Bond futures, swaps

RollableFuture(Asset)
├── Futures that roll to next expiry
├── Tracks: current contract + next contract + roll date
├── handle_corporate_actions() detects roll and returns AssetTransition
└── Examples: ES, ZN (quarterly rolls)

Swap(Asset)
├── Interest rate swaps with DV01 and notional
└── May have resets, flows, etc.
```

### Implementation Strategy

**Phase 1: Extract current logic into PriceFuture**
- Create Asset base class
- Implement PriceFuture with current return logic
- Refactor backtest to use PriceFuture.calculate_return()
- Tests pass with no behavior change

**Phase 2: Add explicit roll handling**
- Implement RollableFuture with roll logic
- Add AssetTransition for roll events
- Track rolls separately in backtest

**Phase 3: Add other asset types**
- Implement YieldInstrument
- Implement Swap
- Backtest supports mixed portfolios

## Recommendations

### Immediate (MVP+)
1. ✅ Add warning for missing returns (Flaw 2)
2. 🔴 Fix universe change handling (Flaw 3) - **CRITICAL**
3. 🔴 Add explicit roll detection (Flaw 4) - **CRITICAL**

### Near-term
4. 🟡 Extract PriceFuture abstraction (Flaw 6) - **Important for extensibility**
5. 🟡 Implement RollableFuture - **Important for accurate futures P&L**

### Long-term (MAXIMAL)
6. ⚪ Add YieldInstrument for bonds/swaps
7. ⚪ Add Swap with flows and resets

## Test Coverage Needed

### Current MVP Tests
- ✅ Basic return calculation (prices don't change much)
- ✅ Portfolio return (weighted sum)
- ❌ Contract disappears mid-backtest
- ❌ Contract appears mid-backtest
- ❌ Contract rolls
- ❌ Position held through expiry

### Proposed Tests
```python
def test_contract_expires_during_backtest():
    """Contract in portfolio at t-1 expires before t."""
    # Should handle P&L correctly or raise clear error

def test_contract_rolls_to_next():
    """Contract rolls from SFRZ4 to SFRH5."""
    # Should track roll transaction and P&L

def test_mixed_asset_types():
    """Portfolio with futures + swaps."""
    # Each calculates returns correctly
```

## Conclusion

**Current state**: MVP return calculation works for simple cases (stable universe, no rolls, price-based assets)

**Critical flaws for futures backtesting**:
1. Contract expiries not handled (Flaw 3) → **Incorrect P&L**
2. Rolls not tracked (Flaw 4) → **Missing transactions**

**Recommended path**:
1. Fix Flaws 3 & 4 immediately (required for accurate futures backtest)
2. Add Asset abstraction (Flaw 6) for extensibility
3. Implement RollableFuture for proper roll handling

This will make the system **robust for real futures backtesting**.

---

## Implementation Status (Updated 2025-11-11)

### Completed
- ✅ ReturnsCalculator (16 tests)
- ✅ VolatilityEstimator (18 tests)
- ✅ AlphaGenerator (16 tests)
- ✅ TearSheet (19 tests)
- ✅ Portfolio.calculate_return() refactored to accept returns
- ✅ MinimalBacktest uses ReturnsCalculator and AlphaGenerator
- ✅ Basic return calculation from prices (Flaw 1 - timing correct)

### Remaining
- [ ] Silent zero returns warning (Flaw 2)
- [ ] Contract universe change handling (Flaw 3) - **CRITICAL**
- [ ] Explicit contract roll handling (Flaw 4) - **CRITICAL**
- [ ] Asset abstraction for different instrument types (Flaw 6)
- [ ] RollableFuture implementation
- [ ] YieldInstrument support for bonds/swaps

Total: 346 tests passing
