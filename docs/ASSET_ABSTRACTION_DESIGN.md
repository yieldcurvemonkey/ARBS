# Asset Abstraction Design

## Objective

Design a polymorphic Asset hierarchy that:
1. Encapsulates return calculation for different asset types
2. Handles corporate actions (rolls, expirations, dividends)
3. Supports mixed portfolios (futures + swaps + bonds)
4. Follows Open/Closed Principle (extensible without modification)

## Core Abstraction

### Base Asset Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional, Dict, Any


@dataclass
class AssetTransition:
    """
    Represents a corporate action or lifecycle event.

    Examples:
    - Futures roll: SFRZ4 → SFRH5
    - Expiry: Contract expires worthless
    - Dividend: Stock pays dividend
    """
    event_type: str  # 'roll', 'expiry', 'dividend', etc.
    date: date
    from_asset: str  # Original asset identifier
    to_asset: Optional[str]  # New asset (if roll), None if expiry
    pnl_impact: float  # P&L from the transition
    metadata: Dict[str, Any]  # Additional event info


class Asset(ABC):
    """
    Abstract base class for all tradable assets.

    Each asset type encapsulates:
    - How to calculate returns from price changes
    - How to handle corporate actions (rolls, expiries)
    - Metadata (identifier, type, properties)

    Design principles:
    - Single Responsibility: Each asset knows only its own behavior
    - Open/Closed: New assets added without modifying backtest
    - Polymorphism: Backtest treats all assets uniformly via interface
    """

    @abstractmethod
    def get_identifier(self) -> str:
        """
        Return unique identifier for this asset.

        Examples:
        - Futures: 'SFRZ4', 'ESZ24'
        - Swaps: 'USD_IRS_10Y'
        - Bonds: 'UST_10Y_4.5_2034'
        """
        pass

    @abstractmethod
    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Calculate return from price change.

        Args:
            prev_price: Price at t-1
            curr_price: Price at t
            **kwargs: Asset-specific parameters (DV01, notional, etc.)

        Returns:
            Return as decimal (e.g., 0.01 for 1%)

        Examples:
        - Price future: (100 - 95) / 95 = 0.0526 (5.26%)
        - Yield instrument: -(5.5 - 5.0) * DV01 / notional
        """
        pass

    @abstractmethod
    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect if corporate action occurs on this date.

        Args:
            as_of: Current date
            market_data: Market data (prices, next contracts, etc.)

        Returns:
            AssetTransition if event occurs, None otherwise

        Examples:
        - RollableFuture: Returns AssetTransition if as_of >= roll_date
        - PriceFuture: Returns None (no transitions)
        - Swap: Returns AssetTransition if reset date
        """
        pass

    def get_asset_type(self) -> str:
        """Return asset type name."""
        return self.__class__.__name__
```

## Concrete Implementations

### 1. PriceFuture - Simple Futures

```python
class PriceFuture(Asset):
    """
    Simple futures contract with price-based returns.

    Used for:
    - SOFR futures (priced as 100 - rate)
    - Equity index futures (priced as index level)
    - Commodity futures (priced as $/unit)

    Return calculation:
    - r_t = (P_t - P_{t-1}) / P_{t-1}

    No corporate actions (doesn't roll automatically).
    """

    def __init__(self, contract: str):
        """
        Initialize price future.

        Args:
            contract: Contract identifier (e.g., 'SFRZ4')
        """
        self.contract = contract

    def get_identifier(self) -> str:
        return self.contract

    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Simple price return: (P_t - P_{t-1}) / P_{t-1}.

        Args:
            prev_price: Price at t-1
            curr_price: Price at t

        Returns:
            Return as decimal

        Example:
            prev_price = 95.00, curr_price = 95.10
            return = (95.10 - 95.00) / 95.00 = 0.001053 (0.11%)
        """
        if prev_price <= 0:
            return 0.0
        return (curr_price - prev_price) / prev_price

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        PriceFuture has no automatic transitions.

        Returns None (user must explicitly handle rolls if needed).
        """
        return None
```

### 2. RollableFuture - Auto-Rolling Futures

```python
class RollableFuture(Asset):
    """
    Futures contract that automatically rolls to next expiry.

    Used for:
    - Quarterly futures (ESZ4 → ESH5 → ESM5 → ...)
    - Monthly futures with defined roll schedule

    Tracks:
    - Current contract (e.g., SFRZ4)
    - Next contract (e.g., SFRH5)
    - Roll date (when to switch)

    On roll_date:
    - Closes position in current contract
    - Opens same position in next contract
    - Records P&L from roll spread
    """

    def __init__(
        self,
        current_contract: str,
        next_contract: str,
        roll_date: date,
        roll_days_before_expiry: int = 5
    ):
        """
        Initialize rollable future.

        Args:
            current_contract: Current front contract
            next_contract: Next contract to roll into
            roll_date: Date to execute roll
            roll_days_before_expiry: Roll N days before expiry
        """
        self.current_contract = current_contract
        self.next_contract = next_contract
        self.roll_date = roll_date
        self.roll_days_before_expiry = roll_days_before_expiry

    def get_identifier(self) -> str:
        return self.current_contract

    def calculate_return(
        self,
        prev_price: float,
        curr_price: float,
        **kwargs
    ) -> float:
        """
        Calculate return on current contract.

        Same as PriceFuture - simple price return.
        """
        if prev_price <= 0:
            return 0.0
        return (curr_price - prev_price) / prev_price

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect if we should roll to next contract.

        Args:
            as_of: Current date
            market_data: Must contain:
                - 'price': Price of current contract
                - 'next_price': Price of next contract

        Returns:
            AssetTransition describing the roll if as_of >= roll_date

        Example:
            as_of = 2024-12-10, roll_date = 2024-12-10
            current = SFRZ4 at 95.00, next = SFRH5 at 94.95
            → AssetTransition(
                event_type='roll',
                from_asset='SFRZ4',
                to_asset='SFRH5',
                pnl_impact=(94.95 - 95.00) / 95.00 = -0.000526
            )
        """
        if as_of < self.roll_date:
            return None

        # Roll occurring
        curr_price = market_data.get('price', 0.0)
        next_price = market_data.get('next_price', curr_price)

        # P&L from roll spread
        if curr_price > 0:
            roll_pnl = (next_price - curr_price) / curr_price
        else:
            roll_pnl = 0.0

        return AssetTransition(
            event_type='roll',
            date=as_of,
            from_asset=self.current_contract,
            to_asset=self.next_contract,
            pnl_impact=roll_pnl,
            metadata={
                'current_price': curr_price,
                'next_price': next_price,
                'roll_spread': next_price - curr_price
            }
        )
```

### 3. YieldInstrument - DV01-Based Assets

```python
class YieldInstrument(Asset):
    """
    Instrument quoted in yield with DV01 sensitivity.

    Used for:
    - Bond futures (ZN, ZB)
    - Interest rate swaps
    - Any yield-sensitive instrument

    Return calculation:
    - Return = -(Δyield) × DV01 / notional
    - Negative because price moves opposite to yield

    Example:
    - 10Y swap: DV01 = 8.5, notional = 100
    - Yield: 5.0% → 5.1% (up 10bp)
    - Return = -(0.10) × 8.5 / 100 = -0.0085 (-0.85%)
    """

    def __init__(
        self,
        identifier: str,
        dv01: float,
        notional: float = 100.0
    ):
        """
        Initialize yield instrument.

        Args:
            identifier: Asset identifier (e.g., 'USD_IRS_10Y')
            dv01: Dollar value of 1bp move (e.g., 8.5 for 10Y swap)
            notional: Notional amount (default 100)
        """
        self.identifier = identifier
        self.dv01 = dv01
        self.notional = notional

    def get_identifier(self) -> str:
        return self.identifier

    def calculate_return(
        self,
        prev_yield: float,
        curr_yield: float,
        **kwargs
    ) -> float:
        """
        Calculate return from yield change using DV01.

        Args:
            prev_yield: Yield at t-1 (in percent, e.g., 5.0 for 5%)
            curr_yield: Yield at t (in percent)

        Returns:
            Return as decimal

        Example:
            prev_yield = 5.0%, curr_yield = 5.1%
            Δyield = 0.1% = 10bp
            Return = -(10bp) × (DV01 / notional)
                   = -0.10 × (8.5 / 100)
                   = -0.0085 (-0.85%)
        """
        # Yield change in basis points
        yield_change_bp = (curr_yield - prev_yield) * 100

        # Return = -(yield change) * DV01 / notional
        # Negative because price moves opposite to yield
        return -(yield_change_bp * self.dv01 / self.notional) / 100

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Yield instruments typically don't have transitions.

        (Could add reset dates for swaps in future)
        """
        return None
```

## Integration with Backtest

### Current Backtest (Hardcoded)

```python
# In MinimalBacktest.py - BEFORE
for c in common_contracts:
    if previous_prices[c] > 0:
        ret[c] = (prices[c] - previous_prices[c]) / previous_prices[c]
```

### Refactored Backtest (Polymorphic)

```python
# In MinimalBacktest.py - AFTER
class MinimalBacktest:
    def __init__(self, mdp, risk_model, optimizer, assets: Dict[str, Asset]):
        """
        Args:
            assets: Map from contract identifier → Asset object
                    e.g., {'SFRZ4': PriceFuture('SFRZ4'),
                           'SFRH5': RollableFuture('SFRH5', 'SFRM5', roll_date)}
        """
        self.assets = assets
        # ... other init

    def calculate_returns(self, contracts, previous_prices, current_prices):
        """Calculate returns using Asset.calculate_return()."""
        returns = {}
        for c in contracts:
            asset = self.assets.get(c)
            if asset is None:
                # Fallback to default PriceFuture
                asset = PriceFuture(c)

            prev_price = previous_prices.get(c, 0.0)
            curr_price = current_prices.get(c, 0.0)

            returns[c] = asset.calculate_return(prev_price, curr_price)

        return returns

    def handle_transitions(self, as_of, market_data):
        """Check for corporate actions on current date."""
        transitions = []
        for contract, asset in self.assets.items():
            transition = asset.detect_transition(as_of, market_data)
            if transition:
                transitions.append(transition)
        return transitions
```

## Testing Strategy

### Unit Tests per Asset Type

```python
class TestPriceFuture:
    def test_calculate_return_price_increase(self):
        """Price increases from 95 to 96 → 1.05% return."""
        asset = PriceFuture('SFRZ4')
        ret = asset.calculate_return(prev_price=95.0, curr_price=96.0)
        assert abs(ret - 0.0105263) < 1e-6

    def test_no_transitions(self):
        """PriceFuture never triggers transitions."""
        asset = PriceFuture('SFRZ4')
        transition = asset.detect_transition(date(2024, 12, 1), {})
        assert transition is None


class TestRollableFuture:
    def test_roll_triggers_on_roll_date(self):
        """Roll transition triggers on roll_date."""
        asset = RollableFuture('SFRZ4', 'SFRH5', roll_date=date(2024, 12, 10))
        market_data = {'price': 95.0, 'next_price': 94.95}

        # Before roll date
        trans = asset.detect_transition(date(2024, 12, 9), market_data)
        assert trans is None

        # On roll date
        trans = asset.detect_transition(date(2024, 12, 10), market_data)
        assert trans is not None
        assert trans.event_type == 'roll'
        assert trans.from_asset == 'SFRZ4'
        assert trans.to_asset == 'SFRH5'
        assert abs(trans.pnl_impact - (-0.000526)) < 1e-5


class TestYieldInstrument:
    def test_yields_up_negative_return(self):
        """Yields up 10bp → negative return (DV01 loss)."""
        asset = YieldInstrument('USD_IRS_10Y', dv01=8.5, notional=100.0)
        ret = asset.calculate_return(prev_yield=5.0, curr_yield=5.1)
        expected = -(0.1 * 100) * 8.5 / 100 / 100  # -0.0085
        assert abs(ret - expected) < 1e-6
```

## Migration Path

### Phase 1: Extract PriceFuture (No Behavior Change)

1. Create `Asset/Base/Asset.py` with abstract base class
2. Create `Asset/PriceFuture.py`
3. Refactor `MinimalBacktest` to use `PriceFuture.calculate_return()`
4. All tests pass (behavior unchanged)

### Phase 2: Add RollableFuture (Handle Rolls)

1. Create `Asset/RollableFuture.py`
2. Add `detect_transition()` logic
3. Update backtest to call `handle_transitions()`
4. Add tests for roll handling

### Phase 3: Add YieldInstrument (Expand Asset Types)

1. Create `Asset/YieldInstrument.py`
2. Backtest now supports mixed portfolios
3. Add integration tests with futures + swaps

## Benefits

### Extensibility
- Add new asset types without modifying backtest
- Each asset encapsulates its own logic
- Open/Closed Principle satisfied

### Testability
- Each asset type has isolated unit tests
- Easy to test edge cases (expiries, rolls, DV01)
- Mock assets for backtest testing

### Clarity
- Return calculation logic lives with asset, not scattered in backtest
- Clear separation of concerns
- Self-documenting (YieldInstrument obviously uses DV01)

### Robustness
- Explicit transition handling (rolls, expiries)
- Type-safe (each asset validates its own data)
- No silent failures

## Conclusion

The Asset abstraction:
1. Fixes Flaw #6 (no abstraction)
2. Enables fixing Flaw #4 (roll handling) via RollableFuture
3. Enables fixing Flaw #5 (asset-type-specific returns) via polymorphism
4. Follows SOLID principles
5. Makes system extensible for future asset types

**Recommendation**: Implement in phases, starting with PriceFuture extraction to prove the pattern works, then add RollableFuture for roll handling.
