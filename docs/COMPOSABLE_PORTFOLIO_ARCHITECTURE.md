# Composable Portfolio Architecture

## Objective

Design minimal building blocks that enable:
1. Atomic assets (futures, swaps, bonds)
2. Portfolios (combinations of assets)
3. Nested portfolios (portfolios of portfolios)
4. **Portfolio as Asset** - portfolios implement Asset interface

## Key Insight: Composite Pattern

A **Portfolio is an Asset** that contains other Assets. This enables:
- Uniform treatment: Portfolio and PriceFuture both implement Asset
- Composition: Portfolio can contain atomic assets OR other portfolios
- Recursive structure: Portfolio of portfolios of portfolios...
- Delegation: Portfolio.calculate_return() delegates to components

## Minimum Spanning Tree

```
Asset (Interface)
├── Atomic Assets (Leaf Nodes)
│   ├── PriceFuture
│   ├── RollableFuture
│   ├── YieldInstrument
│   └── [Future asset types]
│
└── Portfolio (Composite Node)
    ├── Contains: List[Position]
    ├── Position = (Asset, weight)
    ├── calculate_return() = Σ(weight_i × asset_i.calculate_return())
    └── Can nest: Portfolio contains Portfolio

Supporting Classes:
├── Position: Tracks holding in an asset
└── [Strategy, Optimizer, etc. already exist]
```

## Core Abstractions

### 1. Asset (Already Implemented)

```python
class Asset(ABC):
    """Base interface for all tradable things."""

    @abstractmethod
    def get_identifier(self) -> str:
        """Unique ID for this asset."""
        pass

    @abstractmethod
    def calculate_return(self, prev_price, curr_price, **kwargs) -> float:
        """Calculate return from price change."""
        pass

    @abstractmethod
    def detect_transition(self, as_of, market_data) -> Optional[AssetTransition]:
        """Detect corporate actions (rolls, expiries)."""
        pass
```

**Status:** ✅ Already implemented

### 2. Position (NEW - Building Block)

```python
@dataclass
class Position:
    """
    Represents a holding in an asset.

    A position is a (asset, quantity, entry_price) tuple that tracks:
    - What we own (asset)
    - How much we own (quantity)
    - What we paid (entry_price)
    - Current value (mark-to-market)

    Used by:
    - Portfolio: to track constituent holdings
    - Backtest: to track historical positions
    - Risk: to calculate portfolio risk metrics
    """
    asset: Asset
    quantity: float  # Number of units (can be fractional)
    entry_price: float  # Price we bought at (for P&L)
    entry_date: date  # When position was opened

    def market_value(self, current_price: float) -> float:
        """Current market value of position."""
        return self.quantity * current_price

    def pnl(self, current_price: float) -> float:
        """Realized P&L since entry."""
        return self.quantity * (current_price - self.entry_price)

    def pnl_percent(self, current_price: float) -> float:
        """P&L as percentage of entry value."""
        if self.entry_price <= 0:
            return 0.0
        return (current_price - self.entry_price) / self.entry_price
```

**Why needed:**
- Separates "what" (asset) from "how much" (quantity)
- Tracks entry price for P&L calculation
- Reusable across Portfolio and Backtest

### 3. Portfolio (NEW - Composite Asset)

```python
class Portfolio(Asset):
    """
    Composite asset containing multiple positions.

    Key insight: Portfolio implements Asset interface, so it can be used
    anywhere an Asset is expected. This enables:
    - Portfolio of futures
    - Portfolio of swaps
    - Portfolio of portfolios (nested)
    - Portfolio of (portfolios + futures)

    Return calculation:
    - Portfolio return = weighted average of constituent returns
    - Weights can be fixed or dynamic (rebalanced)

    Example 1: Fixed-weight portfolio
        Portfolio([
            Position(PriceFuture('SFRZ4'), weight=0.6),
            Position(PriceFuture('SFRH5'), weight=0.4)
        ])

    Example 2: Nested portfolio
        equity_port = Portfolio([
            Position(PriceFuture('ESZ4'), weight=0.5),
            Position(PriceFuture('NQZ4'), weight=0.5)
        ])
        fixed_income_port = Portfolio([
            Position(YieldInstrument('UST_10Y'), weight=0.7),
            Position(YieldInstrument('UST_2Y'), weight=0.3)
        ])
        balanced_port = Portfolio([
            Position(equity_port, weight=0.6),
            Position(fixed_income_port, weight=0.4)
        ])
    """

    def __init__(
        self,
        identifier: str,
        positions: List[Position],
        rebalance_frequency: Optional[str] = None
    ):
        """
        Initialize portfolio.

        Args:
            identifier: Portfolio name (e.g., 'BALANCED_60_40')
            positions: List of Position objects
            rebalance_frequency: 'daily', 'monthly', 'quarterly', None
        """
        self.identifier = identifier
        self.positions = positions
        self.rebalance_frequency = rebalance_frequency

        # Validate weights sum to 1.0 (or close)
        total_weight = sum(p.quantity for p in positions)
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"Weights sum to {total_weight}, not 1.0")

    def get_identifier(self) -> str:
        """Return portfolio identifier."""
        return self.identifier

    def calculate_return(
        self,
        prev_prices: Dict[str, float],
        curr_prices: Dict[str, float],
        **kwargs
    ) -> float:
        """
        Calculate portfolio return as weighted sum of constituent returns.

        Args:
            prev_prices: Map from asset ID → previous price
            curr_prices: Map from asset ID → current price

        Returns:
            Portfolio return as decimal

        Formula:
            r_portfolio = Σ(w_i × r_i)
            where r_i = asset_i.calculate_return(prev_price, curr_price)

        Example:
            Portfolio: 60% SFRZ4, 40% SFRH5
            SFRZ4: 95.0 → 96.0 (1.05% return)
            SFRH5: 94.0 → 94.5 (0.53% return)
            Portfolio return = 0.6 × 0.0105 + 0.4 × 0.0053 = 0.0084 (0.84%)
        """
        portfolio_return = 0.0

        for position in self.positions:
            asset = position.asset
            weight = position.quantity
            asset_id = asset.get_identifier()

            # Get prices (default to 0 if missing)
            prev_price = prev_prices.get(asset_id, 0.0)
            curr_price = curr_prices.get(asset_id, 0.0)

            # Calculate asset return
            asset_return = asset.calculate_return(prev_price, curr_price)

            # Add weighted contribution
            portfolio_return += weight * asset_return

        return portfolio_return

    def detect_transition(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> Optional[AssetTransition]:
        """
        Detect transitions in constituent assets.

        Returns first transition found (if any). For multiple transitions,
        caller should iterate over positions.

        Args:
            as_of: Current date
            market_data: Market data for all constituents

        Returns:
            AssetTransition from first constituent that has one, or None
        """
        for position in self.positions:
            asset = position.asset
            transition = asset.detect_transition(as_of, market_data)
            if transition:
                return transition
        return None

    def get_all_transitions(
        self,
        as_of: date,
        market_data: Dict[str, Any]
    ) -> List[AssetTransition]:
        """
        Get all transitions from all constituents.

        Unlike detect_transition() which returns first transition,
        this returns ALL transitions for the portfolio.

        Returns:
            List of AssetTransition objects (may be empty)
        """
        transitions = []
        for position in self.positions:
            asset = position.asset
            transition = asset.detect_transition(as_of, market_data)
            if transition:
                transitions.append(transition)
        return transitions

    def rebalance(
        self,
        new_weights: Dict[str, float],
        current_prices: Dict[str, float]
    ) -> List[AssetTransition]:
        """
        Rebalance portfolio to new weights.

        Generates AssetTransition objects for each weight change,
        allowing backtest to track transaction costs.

        Args:
            new_weights: Map from asset ID → new weight
            current_prices: Current prices for all assets

        Returns:
            List of AssetTransition objects representing trades
        """
        transitions = []

        for position in self.positions:
            asset_id = position.asset.get_identifier()
            old_weight = position.quantity
            new_weight = new_weights.get(asset_id, 0.0)

            if abs(new_weight - old_weight) > 1e-6:
                # Weight changed - record rebalance transition
                current_price = current_prices.get(asset_id, 0.0)
                transitions.append(AssetTransition(
                    event_type='rebalance',
                    date=date.today(),  # Would use actual date in real code
                    from_asset=asset_id,
                    to_asset=asset_id,
                    pnl_impact=0.0,  # P&L from rebalance calculated separately
                    metadata={
                        'old_weight': old_weight,
                        'new_weight': new_weight,
                        'turnover': abs(new_weight - old_weight),
                        'price': current_price
                    }
                ))

                # Update position weight
                position.quantity = new_weight

        return transitions
```

**Why this works:**
- Portfolio **IS-A** Asset (implements interface)
- Portfolio **HAS-A** list of Positions
- Each Position **HAS-A** Asset (which could be another Portfolio)
- Recursive composition enabled by polymorphism

## Usage Examples

### Example 1: Simple Futures Portfolio

```python
# Create atomic assets
sfrz4 = PriceFuture('SFRZ4')
sfrh5 = PriceFuture('SFRH5')
sfrm5 = PriceFuture('SFRM5')

# Create positions
positions = [
    Position(sfrz4, quantity=0.5, entry_price=95.0, entry_date=date(2024, 11, 1)),
    Position(sfrh5, quantity=0.3, entry_price=94.9, entry_date=date(2024, 11, 1)),
    Position(sfrm5, quantity=0.2, entry_price=94.8, entry_date=date(2024, 11, 1))
]

# Create portfolio
futures_port = Portfolio(
    identifier='SOFR_CARRY_PORTFOLIO',
    positions=positions
)

# Calculate return (Portfolio.calculate_return() delegates to constituents)
prev_prices = {'SFRZ4': 95.0, 'SFRH5': 94.9, 'SFRM5': 94.8}
curr_prices = {'SFRZ4': 95.5, 'SFRH5': 95.2, 'SFRM5': 95.0}

port_return = futures_port.calculate_return(prev_prices, curr_prices)
# = 0.5 × (95.5-95.0)/95.0 + 0.3 × (95.2-94.9)/94.9 + 0.2 × (95.0-94.8)/94.8
```

### Example 2: Nested Portfolios (Portfolio of Portfolios)

```python
# Level 1: Equity sub-portfolio
equity_port = Portfolio(
    identifier='EQUITY_PORTFOLIO',
    positions=[
        Position(PriceFuture('ESZ4'), 0.6, 4500.0, date(2024, 11, 1)),
        Position(PriceFuture('NQZ4'), 0.4, 15000.0, date(2024, 11, 1))
    ]
)

# Level 1: Fixed income sub-portfolio
fi_port = Portfolio(
    identifier='FIXED_INCOME_PORTFOLIO',
    positions=[
        Position(YieldInstrument('UST_10Y', dv01=8.5), 0.7, 4.5, date(2024, 11, 1)),
        Position(YieldInstrument('UST_2Y', dv01=1.9), 0.3, 4.8, date(2024, 11, 1))
    ]
)

# Level 2: Balanced portfolio (contains other portfolios!)
balanced_port = Portfolio(
    identifier='BALANCED_60_40',
    positions=[
        Position(equity_port, 0.6, 100.0, date(2024, 11, 1)),  # Portfolio as Asset
        Position(fi_port, 0.4, 100.0, date(2024, 11, 1))       # Portfolio as Asset
    ]
)

# Calculate return - automatically delegates to nested portfolios
# balanced_port.calculate_return() calls:
#   → equity_port.calculate_return() calls:
#       → ESZ4.calculate_return()
#       → NQZ4.calculate_return()
#   → fi_port.calculate_return() calls:
#       → UST_10Y.calculate_return()
#       → UST_2Y.calculate_return()
```

### Example 3: Rolling Futures Portfolio

```python
# Portfolio with auto-rolling futures
positions = [
    Position(
        RollableFuture('SFRZ4', 'SFRH5', roll_date=date(2024, 12, 10)),
        quantity=1.0,
        entry_price=95.0,
        entry_date=date(2024, 11, 1)
    )
]

rolling_port = Portfolio('AUTO_ROLL_PORTFOLIO', positions)

# On 2024-12-10, detect_transition() returns roll event
market_data = {'price': 95.0, 'next_price': 94.95}
transition = rolling_port.detect_transition(date(2024, 12, 10), market_data)
# → AssetTransition(event_type='roll', from_asset='SFRZ4', to_asset='SFRH5', ...)
```

## Benefits of This Architecture

### 1. Composability
- Build complex portfolios from simple parts
- Reuse existing assets and portfolios
- Nest arbitrarily deep: Portfolio → Portfolio → Portfolio → Asset

### 2. Polymorphism
- Portfolio and PriceFuture both implement Asset
- Code that works with Asset works with Portfolio
- Backtest doesn't care if it's holding futures or portfolios

### 3. Separation of Concerns
- Asset: knows how to calculate return
- Position: knows quantity and entry price
- Portfolio: knows how to combine positions
- Each class has single responsibility

### 4. Testability
- Test atomic assets in isolation (already done: 53 tests)
- Test Portfolio composition independently
- Test nested portfolios with mock assets

### 5. Extensibility
- Add new asset types without changing Portfolio
- Add new portfolio types (e.g., DynamicPortfolio with rebalancing)
- Add transaction costs at Portfolio level

## Implementation Phases

### Phase 1: Position (Foundation)
1. Create Position dataclass
2. Add tests for market_value(), pnl(), pnl_percent()
3. No dependencies - can implement standalone

### Phase 2: Portfolio (Composite)
1. Create Portfolio class implementing Asset
2. Implement calculate_return() with delegation
3. Add tests for simple portfolios (single level)
4. Integrate with existing PriceFuture and RollableFuture

### Phase 3: Nested Portfolios (Recursion)
1. Test Portfolio containing other Portfolios
2. Verify recursive return calculation
3. Test transition detection across levels

### Phase 4: Backtest Integration
1. Update MinimalBacktest to use Portfolio
2. Track positions over time
3. Handle rebalancing events

## Minimal Class Diagram

```
┌─────────────────────┐
│   Asset (ABC)       │  ← Interface
├─────────────────────┤
│ + get_identifier()  │
│ + calculate_return()│
│ + detect_transition()│
└─────────────────────┘
         △
         │ implements
         │
    ┌────┴────────────────────────┐
    │                             │
┌───┴────────────┐    ┌───────────┴─────┐
│ PriceFuture    │    │ Portfolio       │  ← Composite
├────────────────┤    ├─────────────────┤
│ - contract     │    │ - positions[]   │  ← Contains Positions
└────────────────┘    │ - identifier    │
                      └─────────────────┘
┌───────────────────┐          │
│ RollableFuture    │          │ contains
├───────────────────┤          ▼
│ - current         │   ┌─────────────┐
│ - next            │   │  Position   │  ← Building block
│ - roll_date       │   ├─────────────┤
└───────────────────┘   │ - asset     │  ← References Asset
                        │ - quantity  │
┌───────────────────┐   │ - entry_$   │
│ YieldInstrument   │   └─────────────┘
├───────────────────┤          │
│ - dv01            │          │ references
│ - notional        │          │
└───────────────────┘          ▼
                        (back to Asset)
```

## Test Strategy

### Position Tests (10-15 tests)
- Create position with asset, quantity, entry price
- Calculate market value
- Calculate P&L (absolute and percent)
- Edge cases (zero quantity, negative quantity, zero entry price)

### Portfolio Tests (20-25 tests)
- Create portfolio with multiple positions
- Calculate weighted return
- Weights sum to 1.0 validation
- Empty portfolio edge case
- Single-asset portfolio
- Detect transitions from constituents

### Nested Portfolio Tests (10-15 tests)
- Portfolio containing other portfolios
- Recursive return calculation (2 levels, 3 levels)
- Mixed nesting (portfolios + atomic assets)
- Transition detection across levels

### Integration Tests (5-10 tests)
- Backtest with Portfolio instead of individual assets
- Rebalancing events
- Transaction cost calculation on turnover

## Conclusion

The **minimum spanning tree** for composable portfolios requires just 3 classes:

1. **Asset** (interface) - ✅ Already implemented
2. **Position** (building block) - ⏳ Need to implement
3. **Portfolio** (composite) - ⏳ Need to implement

This minimal set enables:
- Atomic assets (PriceFuture, RollableFuture, YieldInstrument)
- Simple portfolios (weighted combination of assets)
- Nested portfolios (portfolios of portfolios)
- Arbitrary composition (portfolio trees of any depth)

The architecture follows SOLID principles:
- **S**ingle Responsibility: Each class has one job
- **O**pen/Closed: Add assets without modifying Portfolio
- **L**iskov Substitution: Portfolio is substitutable for Asset
- **I**nterface Segregation: Minimal Asset interface
- **D**ependency Inversion: Portfolio depends on Asset abstraction

Next steps: Implement Position and Portfolio with full TDD coverage.
