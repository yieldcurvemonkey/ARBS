# Futures Value & Structure Maps Design

**Phase**: 3.2-3.3
**Date**: 2025-11-10
**Purpose**: Design the priceable resolution layer for futures backtesting

---

## Overview

Following the IRSwap adapter pattern, we need:
1. **FuturesStructureFunctionMap**: Converts FuturesQuery → List[priceable objects]
2. **FuturesValueFunctionMap**: Calculates metrics (DV01, NPV, carry, etc.)
3. **FuturesProductAdapter**: Registers the futures product with the backtesting engine

---

## 1. FuturesStructureFunctionMap

### Purpose
Convert a FuturesQuery into a list of priceable futures contracts.

### Interface
```python
class FuturesStructureFunctionMap(BaseStructureFunctionMap[FuturesStructure, _FuturesGenericObject]):
    def __init__(self, curve: _IRSwapGenericCurve):
        # curve.build_stirf() can create STIR futures

    def _create_map(self) -> Dict[FuturesStructure, Callable]:
        return {
            FuturesStructure.OUTRIGHT: self._build_outright,
            FuturesStructure.CALENDAR: self._build_calendar,
            FuturesStructure.PACK: self._build_pack,
            FuturesStructure.BUNDLE: self._build_bundle,
            FuturesStructure.BASIS: self._build_basis,
        }
```

### Structure Builders

#### OUTRIGHT
**Input**: FuturesQuery(contract="SFRZ4", quantity=1.0)
**Output**: [STIRFuture("SFRZ4")]
**Logic**:
- Parse contract code (SFRZ4 → SFR, Z, 4)
- Calculate expiry (third Wednesday of Dec 2024)
- Call `curve.build_stirf(effective_date=..., maturity_date=...)`
- Set quantity, multiplier, tick_size from CONTRACT_SPECS

#### CALENDAR
**Input**: FuturesQuery(front_contract="SFRZ4", back_contract="SFRH5", quantity=1.0)
**Output**: [STIRFuture("SFRZ4"), STIRFuture("SFRH5")]
**Risk Weights**: [+1, -1] (buy front, sell back)
**Logic**:
- Build front contract with quantity
- Build back contract with quantity (negated for spread)
- Return both as list

#### PACK
**Input**: FuturesQuery(contract="SFRZ4", pack_color="RED", quantity=1.0)
**Output**: [STIRFuture("SFRM5"), STIRFuture("SFRU5"), STIRFuture("SFRZ5"), STIRFuture("SFRH6")]
**Risk Weights**: [+0.25, +0.25, +0.25, +0.25] (equal weighted)
**Logic**:
- Get base contract (SFRZ4)
- Get pack offset from color (RED = 1, so skip first contract)
- Generate 4 consecutive contracts starting from offset
- Build each with quantity/4 (equal weighted pack)

#### BUNDLE
**Input**: FuturesQuery(bundle_start_contract="SFRZ4", quantity=1.0)
**Output**: List of 8 consecutive contracts
**Risk Weights**: [+0.125, +0.125, ...] (8 equal weights)
**Logic**:
- Similar to PACK but 8 contracts instead of 4

#### BASIS
**Input**: FuturesQuery(contract="SFRZ4", swap_tenor="3M", quantity=1.0)
**Output**: [STIRFuture("SFRZ4"), IRS(tenor="3M", effective=...)]
**Risk Weights**: [+1, -1] (long futures, short swap)
**Logic**:
- Build futures contract
- Build matched-maturity swap (effective = futures expiry - 3M)
- Return as hybrid package

---

## 2. FuturesValueFunctionMap

### Purpose
Calculate metrics for futures positions.

### Priority Order (Based on Trader Requirements)

**Tier 1 (Essential - Implement First)**
1. PRICE - Futures price (e.g., 94.50)
2. IMPLIED_RATE - 100 - Price (e.g., 5.50%)
3. NPV - Mark-to-market in dollars
4. DV01 - Dollar value of 1bp move ($25 per contract for SFR)

**Tier 2 (Important - Implement Second)**
5. CARRY - Expected carry over period
6. MARGIN - Initial + variation margin

**Tier 3 (Advanced - Implement Later)**
7. BASIS - Futures vs swap (requires swap curve)
8. CONVEXITY_ADJ - Futures-FRA convexity (~1bp/quarter)
9. GAMMA - Second-order sensitivity

### Implementation

```python
class FuturesValueFunctionMap(BaseValueFunctionMap[FuturesValue, float]):
    def __init__(
        self,
        curve: _IRSwapGenericCurve,
        package: List[_FuturesGenericObject],
        risk_weights: List[float],
    ):
        super().__init__(FuturesValue, curve=curve, package=package, risk_weights=risk_weights)

    def _create_map(self) -> Dict[FuturesValue, Callable[..., float]]:
        return {
            FuturesValue.PRICE: self._price,
            FuturesValue.IMPLIED_RATE: self._implied_rate,
            FuturesValue.NPV: self._npv,
            FuturesValue.DV01: self._dv01,
            FuturesValue.CARRY: self._carry,
            FuturesValue.MARGIN: self._margin,
            FuturesValue.BASIS: self._basis,
            FuturesValue.CONVEXITY_ADJ: self._convexity_adj,
            FuturesValue.GAMMA: self._gamma,
        }
```

### Calculation Details

#### PRICE
**Formula**: Direct from curve/pricer
**For Packs**: Average of 4 contract prices, rounded to tick
**For Calendars**: Front price - Back price
**For Outrights**: Single contract price

**Implementation**:
```python
def _price(self, **kwargs) -> float:
    curve = kwargs["curve"]
    package = kwargs["package"]
    risk_weights = kwargs["risk_weights"]

    if len(package) == 1:
        # Outright: just return price
        return curve.price(package[0])  # or curve.fixed_rate()?

    elif len(package) == 4:
        # Pack: average of 4 prices, rounded to tick
        prices = [curve.price(fut) for fut in package]
        avg_price = sum(prices) / 4

        # Round to tick if requested
        if kwargs.get("round_pack_to_tick", True):
            tick = kwargs.get("pack_tick", 0.0025)
            from decimal import Decimal, ROUND_HALF_UP
            q = Decimal(str(tick))
            avg_price = float((Decimal(str(avg_price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)

        return avg_price

    elif len(package) == 2:
        # Calendar: front - back (weighted sum)
        return sum(rw * curve.price(fut) for rw, fut in zip(risk_weights, package))

    else:
        # Generic weighted sum
        return sum(rw * curve.price(fut) for rw, fut in zip(risk_weights, package))
```

#### IMPLIED_RATE
**Formula**: 100 - Price
**Units**: Percent (e.g., 5.50 for 5.50%)

```python
def _implied_rate(self, **kwargs) -> float:
    price = self._price(**kwargs)
    return 100.0 - price
```

#### NPV
**Formula**: Sum of contract NPVs
**For Futures**: (Current Price - Entry Price) × Multiplier × Quantity
**Units**: Dollars

**Note**: For backtesting, we need to track entry price separately.
For now, calculate NPV relative to curve's fair price.

```python
def _npv(self, **kwargs) -> float:
    curve = kwargs["curve"]
    package = kwargs["package"]

    # Sum NPVs across all contracts in package
    # NPV for futures = variation margin accumulated
    return sum(curve.npv(fut) for fut in package)
```

#### DV01
**Formula**: Change in NPV for 1bp rate move
**For SOFR**: $25 per contract per bp
**Formula**: Multiplier × Quantity / 10000

```python
def _dv01(self, **kwargs) -> float:
    curve = kwargs["curve"]
    package = kwargs["package"]

    # For futures, DV01 is straightforward:
    # Each contract has fixed DV01 based on multiplier
    # SFR: $2500 * 0.01 / 100 = $25 per bp

    total_dv01 = 0.0
    for fut in package:
        multiplier = getattr(fut, 'multiplier', 2500.0)
        quantity = getattr(fut, 'quantity', 1.0)
        # DV01 = multiplier * 1bp = multiplier * 0.0001
        # But we want per 1bp, so: multiplier / 100 / 100
        # Actually for SOFR: $2500 per bp move in rate
        # 1bp = 0.01%, so $2500 * 0.01 = $25
        contract_dv01 = multiplier * 0.01  # $25 for SFR
        total_dv01 += contract_dv01 * abs(quantity)

    return total_dv01
```

**Wait, let me recalculate**:
- SOFR futures: $2500 multiplier
- 1bp rate change = 0.01 price change (since price = 100 - rate)
- P&L from 1bp = 0.01 × $2500 = $25

So DV01 = multiplier / 100 = $2500 / 100 = $25 ✓

#### CARRY
**Formula**: Expected P&L from time decay over horizon
**Assumptions**: No rate changes, curve stays static
**Formula**: (Forward Price at t+horizon) - (Current Price) × Multiplier × Quantity

For futures, carry is zero if you hold to settlement (mark-to-market daily).
Real "carry" is the cost of financing the margin.

```python
def _carry(self, **kwargs) -> float:
    assert "horizon" in kwargs, "Need horizon (e.g., '1M') for carry calculation"

    curve = kwargs["curve"]
    package = kwargs["package"]
    horizon = kwargs["horizon"]

    # For futures, carry calculation:
    # If holding over horizon with static curve, what's the expected P&L?
    # This is complex - requires rolling the curve forward

    # Simplified: return sum of carry_bps_running * DV01
    carry_bps = sum(curve.carry_bps_running(fut, horizon) for fut in package)
    dv01 = self._dv01(**kwargs)
    return carry_bps * dv01 / 100.0  # Convert bps to dollars
```

#### MARGIN
**Formula**: Initial margin + variation margin
**Initial Margin**: ~3% of contract value
**Variation Margin**: Daily price change × multiplier × quantity

```python
def _margin(self, **kwargs) -> float:
    curve = kwargs["curve"]
    package = kwargs["package"]

    margin_type = kwargs.get("margin_type", "initial")  # "initial" or "variation"

    total_margin = 0.0

    for fut in package:
        price = curve.price(fut)  # Current price
        multiplier = getattr(fut, 'multiplier', 2500.0)
        quantity = abs(getattr(fut, 'quantity', 1.0))

        contract_value = price * multiplier * quantity

        if margin_type == "initial":
            # Initial margin: ~3% of contract value
            initial_rate = kwargs.get("initial_margin_rate", 0.03)
            total_margin += contract_value * initial_rate

        elif margin_type == "variation":
            # Variation margin: price change since last mark
            prev_price = kwargs.get("prev_price", price)  # Need previous price
            price_change = price - prev_price
            total_margin += price_change * multiplier * quantity

    return total_margin
```

#### BASIS
**Formula**: Futures implied rate - Swap rate (in bps)
**Only for BASIS structure**

```python
def _basis(self, **kwargs) -> float:
    assert len(kwargs["package"]) >= 1, "Need at least 1 futures contract for basis"

    curve = kwargs["curve"]
    package = kwargs["package"]

    # If package has both futures and swap (BASIS structure):
    # Calculate (Futures Implied Rate) - (Swap Rate)

    # Simplified: if package is pure futures, compare to matched swap
    # Full implementation needs hybrid package support

    futures_rate = self._implied_rate(**kwargs)

    # Need to build matched-maturity swap and get its rate
    # This is complex - defer to BASIS structure implementation

    return 0.0  # Placeholder
```

#### CONVEXITY_ADJ
**Formula**: Futures implied rate - FRA/Swap rate
**Typical**: ~1bp per quarter
**Implementation**: Similar to IRSwapValue._convexity_adjustment()

Defer to later phase - requires swap curve comparison.

---

## 3. Integration with Existing Infrastructure

### Using Existing STIR Futures Support

The codebase already has:
- `_IRSwapGenericCurve.build_stirf()` - builds STIR futures
- RatesLib backend: `rl.STIRFuture` - STIR futures object
- Convexity adjustment calculation in IRSwapValue

**Strategy**: Reuse existing infrastructure rather than rebuild.

### Contract Code Parsing

Already implemented in `FuturesQuery.py`:
- `parse_futures_contract(contract)` - parses SFRZ4 → {prefix, month, year}
- `get_contract_expiry(contract)` - calculates IMM date
- `get_next_imm_contract(contract)` - rolls to next quarter
- `get_contract_chain(contract, count)` - generates consecutive contracts

### Backend Support

**RatesLib** (preferred):
- Supports `rl.STIRFuture` natively
- Can build SOFR futures curves
- Convexity adjustments

**QuantLib** (fallback):
- Has Eurodollar futures support (may need adaptation for SOFR)

---

## 4. TDD Implementation Plan

### Test File: `tests/unit/test_futures_value_map.py`

**Phase 1: Basic Value Calculations**
1. Test PRICE calculation for outright
2. Test IMPLIED_RATE calculation (100 - price)
3. Test NPV calculation
4. Test DV01 calculation ($25 per contract for SFR)

**Phase 2: Structure-Specific Values**
5. Test PRICE for pack (average of 4, rounded)
6. Test PRICE for calendar (front - back)
7. Test DV01 for pack (sum of 4 contracts)
8. Test DV01 for calendar (net DV01)

**Phase 3: Advanced Calculations**
9. Test CARRY calculation with horizon
10. Test MARGIN calculation (initial + variation)

**Phase 4: Basis and Convexity**
11. Test BASIS calculation (futures vs swap)
12. Test CONVEXITY_ADJ calculation

### Test File: `tests/unit/test_futures_structure_map.py`

**Phase 1: Simple Structures**
1. Test OUTRIGHT structure builder
2. Test contract parsing and expiry calculation
3. Test multiplier and tick_size lookup

**Phase 2: Spread Structures**
4. Test CALENDAR structure builder (2 contracts)
5. Test risk weights for calendar [+1, -1]

**Phase 3: Pack/Bundle**
6. Test PACK structure builder (4 contracts)
7. Test pack color offsets (WHITE=0, RED=1, etc.)
8. Test BUNDLE structure builder (8 contracts)

**Phase 4: Hybrid**
9. Test BASIS structure builder (futures + swap)

---

## 5. Mock Pricer Requirements

For testing without real curves, we need a mock pricer that can:

1. **Return consistent prices**:
   - `price(fut)` → 94.50 (or hash-based for different contracts)
   - `npv(fut)` → float (MTM value)

2. **Support STIR futures**:
   - `build_stirf(effective_date, maturity_date, ...)` → mock futures object

3. **Calculate sensitivities**:
   - `dv01(fut)` → $25.0 for SFR
   - `carry_bps_running(fut, horizon)` → float

**Extend existing MockCurve from conftest.py**:
```python
class MockFuturesCurve(MockCurve):
    def price(self, fut):
        # Return consistent price for testing
        contract = getattr(fut, 'contract', 'SFRZ4')
        base_price = 94.50
        # Vary by contract for realism
        month_offset = ord(contract[-2]) % 4  # H, M, U, Z
        return base_price + month_offset * 0.25

    def build_stirf(self, **kwargs):
        # Return mock STIR future object
        return MockSTIRFuture(**kwargs)
```

---

## 6. Success Criteria

**Phase 3.2-3.3 is complete when**:

1. ✅ FuturesValueFunctionMap implements all Tier 1 metrics (PRICE, IMPLIED_RATE, NPV, DV01)
2. ✅ FuturesStructureFunctionMap handles OUTRIGHT, CALENDAR, PACK structures
3. ✅ All structure builders return correct number of contracts with correct risk weights
4. ✅ DV01 calculation returns $25 per contract for SFR
5. ✅ Pack pricing correctly averages and rounds to tick
6. ✅ Calendar pricing correctly calculates spreads
7. ✅ 30+ unit tests passing (structure tests + value tests)
8. ✅ Can price a full backtest scenario (e.g., RED pack vs GREEN pack steepener)

**Deferred to later phases**:
- Carry and roll-down (needs curve rolling logic)
- Basis calculation (needs swap curve comparison)
- Convexity adjustments (complex, low priority)
- Margin calculations (needs position tracking)

---

## 7. File Structure

```
Query/
  Futures/
    __init__.py                 # Existing
    FuturesQuery.py            # Existing
    FuturesStructure.py        # Existing
    FuturesValue.py            # Existing
    FuturesStructureFunctionMap.py  # NEW
    FuturesValueFunctionMap.py      # NEW
    adapter.py                      # NEW
    _FuturesGenericObject.py        # NEW (type alias/protocol)

tests/
  unit/
    test_futures_query.py      # Existing (21 tests)
    test_futures_structure_map.py  # NEW
    test_futures_value_map.py      # NEW
```

---

## 8. Next Steps

1. Create `_FuturesGenericObject.py` (type alias for STIR futures)
2. Implement `FuturesStructureFunctionMap` with TDD (start with OUTRIGHT)
3. Implement `FuturesValueFunctionMap` with TDD (start with PRICE, IMPLIED_RATE)
4. Create `FuturesProductAdapter`
5. Integration test: Full backtest scenario with multiple structures
6. Commit and push to feature branch
