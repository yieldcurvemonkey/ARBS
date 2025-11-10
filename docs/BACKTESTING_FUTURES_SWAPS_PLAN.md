# Backtesting Improvements: Futures & Swaps
**Date:** 2025-11-10
**Approach:** Test-Driven Development (TDD)

## Executive Summary

This plan outlines improvements to the ARBS backtesting framework to:
1. Add comprehensive futures backtesting support
2. Enable mixed futures/swaps strategies
3. Maintain generic, extensible architecture
4. Follow TDD principles throughout

## Current State Analysis

### Strengths
- ✅ Production-ready IRS backtesting (`QueryDrivenBacktest`, `EventDrivenBacktest`)
- ✅ Clean product adapter pattern (IRS, FixedRateBonds)
- ✅ Rich trigger system (10+ trigger types)
- ✅ Multiple data sources (CME, SDR, Eris)
- ✅ ZODB caching infrastructure
- ✅ Backend abstraction (QuantLib, RatesLib)

### Gaps
- ❌ No futures product adapter (STIRFutures only used in curve building)
- ❌ No margin/settlement accounting
- ❌ No contract roll logic
- ❌ No formal test suite (no pytest files)
- ❌ No cross-product risk aggregation
- ❌ Limited documentation for futures patterns

## Design Principles

### 1. Generic Architecture
- Follow existing product adapter pattern
- Support any future product type (options, swaptions, etc.)
- Reuse common backtesting infrastructure
- Avoid product-specific code in core engine

### 2. TDD Approach
- Write tests before implementation
- Test pyramid: Unit → Integration → System
- Backend parity tests (QuantLib vs RatesLib)
- Golden file tests for determinism

### 3. Extensibility
- Pluggable margin models
- Configurable settlement conventions
- Generic roll strategies
- Custom value metrics per product

## Implementation Plan

### Phase 1: Test Infrastructure (Week 1)

#### 1.1 Setup Testing Framework
**Files to create:**
- `tests/conftest.py` - pytest fixtures
- `tests/unit/` - unit tests directory
- `tests/integration/` - integration tests directory
- `tests/golden/` - golden file tests directory
- `tests/fixtures/` - shared test data
- `pytest.ini` - pytest configuration

**Test fixtures needed:**
- Mock market data providers
- Sample curves (USD, EUR, JPY)
- Historical price data
- Reference portfolios

**TDD Steps:**
1. Write test for basic pytest setup
2. Implement pytest configuration
3. Write test for fixture loading
4. Implement common fixtures
5. Write test for golden file comparison
6. Implement golden file utilities

#### 1.2 Backtest Engine Tests
**Test coverage for existing engines:**
- `tests/unit/test_query_engine.py`
  - Portfolio initialization
  - Position tracking
  - MTM calculation
  - Realized P&L
  - Query unwinding

- `tests/unit/test_event_engine.py`
  - Trade execution
  - Risk function hooks
  - MDP integration

- `tests/unit/test_triggers.py`
  - All 10+ trigger types
  - Trigger composition (And, Not, Aggregate)
  - State persistence

- `tests/unit/test_actions.py`
  - Query actions (Add, Scale, Unwind)
  - Event actions

**TDD Steps:**
1. Write tests for each existing component
2. Fix any bugs discovered
3. Document expected behavior
4. Add golden files for regression testing

### Phase 2: Generic Backtesting Improvements (Week 1-2)

#### 2.1 Enhanced Portfolio Accounting
**Goal:** Support products with different settlement conventions

**New abstract base classes:**
```python
# BT/accounting.py

@dataclass
class SettlementConvention(ABC):
    """Abstract settlement convention"""
    @abstractmethod
    def calculate_cash_flows(self, position, t0, t1) -> List[CashFlow]:
        pass

@dataclass
class MarginConvention(ABC):
    """Abstract margin calculation"""
    @abstractmethod
    def initial_margin(self, position, pricer) -> float:
        pass

    @abstractmethod
    def variation_margin(self, position, pricer, prev_price) -> float:
        pass

@dataclass
class RollConvention(ABC):
    """Abstract roll strategy"""
    @abstractmethod
    def should_roll(self, position, current_date) -> bool:
        pass

    @abstractmethod
    def get_roll_target(self, position, current_date) -> Query:
        pass
```

**TDD Steps:**
1. Write tests for settlement conventions
   - Standard (T+2)
   - Daily (futures)
   - IMM dates (swaps)
2. Implement base classes
3. Write tests for margin conventions
   - No margin (swaps)
   - Daily variation margin (futures)
   - Initial + variation
4. Implement margin base classes
5. Write tests for roll conventions
   - Days to expiry
   - Front-to-front
   - Constant maturity
6. Implement roll base classes

#### 2.2 Enhanced Position Tracking
**Goal:** Track margin, settlement, and cash flows separately

**Extend existing classes:**
```python
# BT/query_portfolio.py

@dataclass
class ResolvedQueryPosition:
    # Existing fields...
    settlement_convention: SettlementConvention = None
    margin_convention: MarginConvention = None
    roll_convention: RollConvention = None

    # New tracking
    initial_margin: float = 0.0
    variation_margin_history: List[Tuple[datetime, float]] = field(default_factory=list)
    cash_flows: List[CashFlow] = field(default_factory=list)
    roll_history: List[Tuple[datetime, Query, Query]] = field(default_factory=list)
```

**TDD Steps:**
1. Write tests for position with margin tracking
2. Implement margin tracking in ResolvedQueryPosition
3. Write tests for cash flow tracking
4. Implement cash flow tracking
5. Write tests for roll tracking
6. Implement roll tracking

#### 2.3 Generic Risk Aggregation
**Goal:** Cross-product risk metrics

**New risk calculator:**
```python
# BT/risk.py

class PortfolioRisk:
    """Generic risk aggregation across products"""

    def calculate_dv01(self, portfolio, mdp) -> Dict[str, float]:
        """DV01 by currency"""
        pass

    def calculate_gamma(self, portfolio, mdp) -> float:
        """Cross-gamma"""
        pass

    def calculate_var(self, portfolio, mdp, confidence=0.95) -> float:
        """Value at Risk"""
        pass
```

**TDD Steps:**
1. Write tests for single-product risk (IRS only)
2. Implement IRS risk calculation
3. Write tests for multi-product risk (IRS + futures - mocked)
4. Implement generic risk aggregation
5. Write tests for currency bucketing
6. Implement currency-level risk

### Phase 3: Futures Product Adapter (Week 2-3)

#### 3.1 Futures Query Objects
**Files to create:**
- `Query/Futures/__init__.py`
- `Query/Futures/FuturesQuery.py`
- `Query/Futures/adapter.py`
- `Query/Futures/backends/__init__.py`
- `Query/Futures/backends/rateslib/RLFutures.py`

**Core structures:**
```python
# Query/Futures/FuturesQuery.py

class FuturesStructure(str, Enum):
    OUTRIGHT = "outright"           # Single contract
    CALENDAR = "calendar_spread"    # Front - Back
    PACK = "pack"                   # 4 consecutive contracts
    BUNDLE = "bundle"               # 8 consecutive contracts
    BASIS = "basis"                 # Future vs Swap

class FuturesValue(str, Enum):
    PRICE = "price"                 # Futures price
    NPV = "npv"                     # Mark-to-market
    DV01 = "dv01"                  # Dollar value of 1bp
    MARGIN = "margin"               # Margin requirement
    BASIS = "basis"                 # vs equivalent swap
    CONVEXITY_ADJ = "convexity_adj" # Futures-FRA adjustment
    IMPLIED_RATE = "implied_rate"   # 100 - price
    CARRY = "carry"                 # Roll-down

@dataclass(frozen=True)
class FuturesQuery(BaseQuery):
    contract: str                   # e.g., "EDZ4" (Eurodollar Dec 2024)
    product_type: str = "STIR"      # STIR, Bond, Commodity

    # Contract specs
    tick_size: float = 0.0025      # $6.25 per tick for ED
    multiplier: float = 2500       # $2500 per bp for ED
    expiry: Optional[date] = None   # Auto-resolved from contract code

    # For basis trades
    swap_tenor: Optional[str] = None  # "3M" for STIR basis
```

**TDD Steps:**
1. Write test for FuturesQuery creation
2. Implement FuturesQuery dataclass
3. Write test for contract code parsing (EDZ4 → Dec 2024)
4. Implement contract parsing logic
5. Write test for query arithmetic (spread, fly)
6. Implement __add__, __sub__, __mul__
7. Write test for validation (invalid contracts)
8. Implement validation

#### 3.2 Futures Structure Map
```python
# Query/Futures/adapter.py

class FuturesStructureMap(BaseStructureFunctionMap):

    def outright(self, query: FuturesQuery) -> List[Priceable]:
        """Single futures contract"""
        return [rl.STIRFuture(...)]

    def calendar_spread(self, query: FuturesQuery) -> List[Priceable]:
        """Near - Far spread"""
        front = rl.STIRFuture(...)  # query.contract
        back = rl.STIRFuture(...)   # next quarterly
        return [(front, 1.0), (back, -1.0)]

    def pack(self, query: FuturesQuery) -> List[Priceable]:
        """4 consecutive quarterly contracts"""
        contracts = [rl.STIRFuture(...) for _ in range(4)]
        return [(c, 0.25) for c in contracts]

    def bundle(self, query: FuturesQuery) -> List[Priceable]:
        """8 consecutive quarterly contracts"""
        contracts = [rl.STIRFuture(...) for _ in range(8)]
        return [(c, 0.125) for c in contracts]

    def basis(self, query: FuturesQuery) -> List[Priceable]:
        """Future vs equivalent swap"""
        future = rl.STIRFuture(...)
        # Construct matched-maturity swap
        swap = rl.IRS(...)
        return [(future, 1.0), (swap, -1.0)]
```

**TDD Steps:**
1. Write tests for outright structure (mocked STIRFuture)
2. Implement outright
3. Write tests for calendar spread (correct contracts, weights)
4. Implement calendar spread with contract resolution
5. Write tests for pack (4 contracts, equal weights)
6. Implement pack
7. Write tests for bundle
8. Implement bundle
9. Write tests for basis (future + swap)
10. Implement basis with swap construction

#### 3.3 Futures Value Map
```python
# Query/Futures/adapter.py

class FuturesValueMap(BaseValueFunctionMap):

    def price(self, package: List[Priceable], pricer) -> float:
        """Current futures price"""
        pass

    def npv(self, package: List[Priceable], pricer) -> float:
        """Mark-to-market in dollars"""
        pass

    def dv01(self, package: List[Priceable], pricer) -> float:
        """Dollar value of 1bp move"""
        pass

    def margin(self, package: List[Priceable], pricer) -> float:
        """Margin requirement (initial or maintenance)"""
        pass

    def basis(self, package: List[Priceable], pricer) -> float:
        """Futures vs swap basis in bps"""
        pass

    def convexity_adj(self, package: List[Priceable], pricer) -> float:
        """Convexity adjustment futures vs FRA"""
        pass

    def carry(self, package: List[Priceable], pricer) -> float:
        """Expected carry over roll period"""
        pass
```

**TDD Steps:**
1. Write tests for price calculation (mock pricer)
2. Implement price
3. Write tests for NPV (price × multiplier × quantity)
4. Implement NPV
5. Write tests for DV01 (bump price by 1bp)
6. Implement DV01 with finite differences
7. Write tests for margin (use CME SPAN-like formula)
8. Implement simple margin model
9. Write tests for basis (vs matched swap)
10. Implement basis calculation
11. Write tests for convexity adjustment
12. Implement convexity from RatesLib
13. Write tests for carry
14. Implement carry

#### 3.4 Futures MDP Integration
**Extend existing MDP:**
```python
# MDP/Futures/FuturesMDP.py

class FuturesMDP(MarketDataProvider):
    """Market data provider for futures"""

    def get_pricer(self, request: PricerRequest):
        """Returns pricer for futures at given date"""
        # Option 1: Use RatesLib STIRFuture with historical prices
        # Option 2: Build synthetic from CME settlement data
        # Option 3: Use existing Eris futures infrastructure
        pass
```

**TDD Steps:**
1. Write tests for MDP request/response
2. Implement basic FuturesMDP
3. Write tests for historical price lookup
4. Implement price history cache
5. Write tests for curve integration (discount curves from Eris)
6. Implement curve wiring
7. Write tests for missing data handling
8. Implement fallback logic

#### 3.5 Settlement and Margin Conventions for Futures
```python
# BT/accounting.py

class FuturesSettlement(SettlementConvention):
    """Daily mark-to-market settlement"""

    def calculate_cash_flows(self, position, t0, t1):
        # Daily variation margin
        prev_price = position.get_price(t0)
        curr_price = position.get_price(t1)
        vm = (curr_price - prev_price) * position.multiplier * position.quantity
        return [CashFlow(t1, vm, "variation_margin")]

class FuturesMargin(MarginConvention):
    """CME SPAN-style margin"""

    def initial_margin(self, position, pricer):
        # Simplified: X% of notional
        return abs(position.npv) * self.margin_rate

    def variation_margin(self, position, pricer, prev_price):
        # Daily settlement
        curr_price = pricer.price(position.package)
        return (curr_price - prev_price) * position.multiplier * position.quantity
```

**TDD Steps:**
1. Write tests for daily settlement
2. Implement FuturesSettlement
3. Write tests for initial margin
4. Implement initial margin calculation
5. Write tests for variation margin
6. Implement variation margin
7. Write tests for margin calls
8. Implement margin call logic in backtest engine

#### 3.6 Roll Convention for Futures
```python
# BT/accounting.py

class FuturesRoll(RollConvention):
    """Roll futures before expiry"""

    def __init__(self, days_before_expiry: int = 5):
        self.days_before_expiry = days_before_expiry

    def should_roll(self, position, current_date):
        expiry = position.package[0].expiry
        return (expiry - current_date).days <= self.days_before_expiry

    def get_roll_target(self, position, current_date):
        # Roll to next quarterly contract
        old_contract = position.query.contract
        new_contract = self._get_next_quarterly(old_contract)
        return position.query.replace(contract=new_contract)
```

**TDD Steps:**
1. Write tests for roll timing (5 days before expiry)
2. Implement should_roll
3. Write tests for next contract resolution (EDZ4 → EDH5)
4. Implement quarterly contract logic
5. Write tests for roll execution in backtest
6. Integrate roll into QueryDrivenBacktest
7. Write tests for roll P&L tracking
8. Implement roll P&L attribution

### Phase 4: Integration & Testing (Week 3-4)

#### 4.1 Backend Parity Tests
**Goal:** Ensure RatesLib futures match expected behavior

**Tests:**
- `tests/integration/test_futures_backend_parity.py`
  - Compare futures pricing across dates
  - Validate DV01 calculations
  - Check convexity adjustments
  - Verify basis calculations

**TDD Steps:**
1. Write tests comparing futures price to reference data
2. Debug any discrepancies
3. Write tests for Greeks (DV01, gamma)
4. Validate against market conventions
5. Write tests for edge cases (expiry, roll dates)
6. Document any backend limitations

#### 4.2 Cross-Product Strategy Tests
**Goal:** Validate mixed futures/swaps portfolios

**Test scenarios:**
- Futures curve + swap curve basis
- Pack vs swap butterfly
- Roll-adjusted carry strategies
- Cross-product hedging

**TDD Steps:**
1. Write test for simple futures + swap portfolio
2. Implement cross-product support in QueryDrivenBacktest
3. Write test for risk aggregation (combined DV01)
4. Implement cross-product risk calculation
5. Write test for basis trades (future vs swap)
6. Validate basis P&L attribution
7. Write test for hedging strategies
8. Implement hedge ratio calculation

#### 4.3 End-to-End Backtest Examples
**Example strategies to implement:**

1. **STIR Curve Steepener**
   - Long front pack, short back pack
   - Roll quarterly
   - Test period: 2020-2024

2. **Futures-Swap Basis**
   - Long futures, short matched swap when basis > threshold
   - Unwind when basis < threshold
   - Test period: 2019-2024

3. **FOMC Calendar Spread**
   - Long pre-FOMC contract, short post-FOMC
   - Enter 2 weeks before meeting
   - Exit at meeting

**TDD Steps:**
1. Write test for STIR curve backtest (expected trades)
2. Implement strategy with triggers/actions
3. Write test for P&L attribution (margin, carry, roll)
4. Validate attribution sums to total P&L
5. Write test for futures-swap basis backtest
6. Implement basis strategy
7. Write test for FOMC calendar spread
8. Implement FOMC strategy using existing trigger system

#### 4.4 Golden File Tests
**Goal:** Regression testing for determinism

**Process:**
1. Run backtests and save:
   - Final portfolio positions
   - MTM history
   - Realized P&L
   - Risk metrics over time
   - Trade history
2. Compare future runs to golden files
3. Flag any differences

**TDD Steps:**
1. Write test to generate golden files
2. Implement golden file serialization
3. Write test to compare against golden files
4. Implement comparison with tolerance
5. Write test for golden file versioning
6. Implement migration logic

#### 4.5 Performance Tests
**Benchmarks:**
- Backtest speed (trades/second)
- Memory usage (positions, history)
- Cache hit rates
- MDP lookup time

**TDD Steps:**
1. Write performance test fixture
2. Implement benchmarking utilities
3. Write test for acceptable performance (e.g., >100 trades/sec)
4. Profile slow paths
5. Write test for memory usage limits
6. Optimize if needed

### Phase 5: Documentation & Examples (Week 4)

#### 5.1 API Documentation
**Files to create:**
- `docs/futures_quickstart.md`
- `docs/margin_and_settlement.md`
- `docs/roll_strategies.md`
- `docs/cross_product_strategies.md`
- `docs/testing_guide.md`

#### 5.2 Example Notebooks
**Notebooks to create:**
- `examples/futures_curve_backtest.ipynb` - Pack/bundle strategies
- `examples/futures_swap_basis_backtest.ipynb` - Basis trades
- `examples/mixed_portfolio_backtest.ipynb` - Futures + swaps
- `examples/margin_tracking_example.ipynb` - VM/IM over time

#### 5.3 README Updates
- Add futures to product list
- Add TDD section
- Link to new documentation

### Phase 6: CI/CD & Maintenance (Week 4)

#### 6.1 GitHub Actions
**Workflows to create:**
```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run unit tests
        run: pytest tests/unit/
      - name: Run integration tests
        run: pytest tests/integration/
      - name: Check golden files
        run: pytest tests/golden/
      - name: Coverage report
        run: pytest --cov=BT --cov=Query
```

#### 6.2 Pre-commit Hooks
```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest-check
        name: pytest-check
        entry: pytest tests/unit/
        language: system
        pass_filenames: false
        always_run: true
```

## Success Criteria

### Functional Requirements
- [ ] Futures query objects support all structures (outright, calendar, pack, bundle, basis)
- [ ] Futures value map implements all metrics (price, NPV, DV01, margin, basis, carry)
- [ ] Margin tracking (initial + variation) works correctly
- [ ] Daily settlement cash flows calculated accurately
- [ ] Roll logic executes before expiry
- [ ] Cross-product portfolios (futures + swaps) supported
- [ ] Risk aggregation across products works

### Testing Requirements
- [ ] >90% code coverage for new code
- [ ] All backend parity tests pass
- [ ] Golden file tests pass (determinism)
- [ ] Performance tests meet benchmarks
- [ ] Example notebooks run without errors

### Documentation Requirements
- [ ] All public APIs documented
- [ ] Quickstart guide for futures
- [ ] At least 3 working example notebooks
- [ ] Testing guide for contributors

## Risk Mitigation

### Technical Risks
1. **Risk:** RatesLib STIRFuture behavior differs from expectations
   - **Mitigation:** Extensive backend parity tests, golden files

2. **Risk:** Performance degradation with many positions
   - **Mitigation:** Performance tests, profiling, caching

3. **Risk:** Margin calculations don't match real-world
   - **Mitigation:** Use CME SPAN methodology, validate against actual margin

### Schedule Risks
1. **Risk:** TDD slows initial development
   - **Mitigation:** Acceptable - tests prevent future bugs

2. **Risk:** Backend integration takes longer than expected
   - **Mitigation:** Start with mocked backends, implement real ones later

## Open Questions

1. **Margin Model:** Use simplified % of notional or implement full SPAN?
   - **Decision:** Start simple, make pluggable for future enhancement

2. **Futures Data Source:** Use existing Eris infrastructure or new source?
   - **Decision:** Leverage Eris fetchers, they're already production-ready

3. **Contract Specs:** Hardcode (ED, ZN, etc.) or load from config?
   - **Decision:** Config file for extensibility

4. **Roll Logic:** Execute as separate trade or replace position?
   - **Decision:** Separate trade for P&L attribution clarity

## Appendix: File Structure

```
ARBS/
├── BT/
│   ├── accounting.py          # NEW: Settlement, margin, roll conventions
│   ├── risk.py                # NEW: Cross-product risk
│   ├── query_engine.py        # UPDATED: Margin/settlement support
│   └── generic_engine.py      # UPDATED: Margin/settlement support
├── Query/
│   └── Futures/               # NEW: Futures product adapter
│       ├── __init__.py
│       ├── FuturesQuery.py
│       ├── adapter.py
│       └── backends/
│           └── rateslib/
│               └── RLFutures.py
├── MDP/
│   └── Futures/               # NEW: Futures market data
│       ├── __init__.py
│       └── FuturesMDP.py
├── tests/                     # NEW: Complete test suite
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   │   ├── test_futures_query.py
│   │   ├── test_futures_adapter.py
│   │   ├── test_accounting.py
│   │   ├── test_risk.py
│   │   ├── test_query_engine.py
│   │   └── test_triggers.py
│   ├── integration/
│   │   ├── test_backend_parity.py
│   │   ├── test_cross_product.py
│   │   └── test_mdp_integration.py
│   └── golden/
│       ├── test_golden_files.py
│       └── data/
├── examples/                  # NEW: Example notebooks
│   ├── futures_curve_backtest.ipynb
│   ├── futures_swap_basis_backtest.ipynb
│   └── mixed_portfolio_backtest.ipynb
├── docs/                      # NEW: Documentation
│   ├── BACKTESTING_FUTURES_SWAPS_PLAN.md
│   ├── futures_quickstart.md
│   ├── margin_and_settlement.md
│   ├── roll_strategies.md
│   └── testing_guide.md
└── .github/
    └── workflows/
        └── test.yml           # NEW: CI/CD
```

## Timeline Summary

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Test Infrastructure | pytest setup, fixtures, existing tests |
| 1-2 | Generic Improvements | Accounting, settlement, margin, roll, risk |
| 2-3 | Futures Adapter | Query, structure map, value map, MDP |
| 3-4 | Integration | Backend tests, cross-product, examples |
| 4 | Documentation | Guides, notebooks, README |
| 4 | CI/CD | GitHub Actions, pre-commit hooks |

**Total Duration:** 4 weeks (assuming 1 FTE)

## Next Steps

1. **Review & Approval:** Stakeholder review of this plan
2. **Environment Setup:** Install pytest, pytest-cov, pre-commit
3. **Phase 1 Kickoff:** Begin with test infrastructure
4. **Daily Standups:** Track progress, blockers
5. **Weekly Demos:** Show working features each Friday

---

**Plan Status:** ✅ Ready for Implementation
**Last Updated:** 2025-11-10
**Author:** Claude (Sonnet 4.5)
