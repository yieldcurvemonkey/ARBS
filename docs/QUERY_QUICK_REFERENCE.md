# ARBS Query Module - Quick Reference Guide

## File Structure

```
Query/
├── Base/
│   ├── BaseQuery.py                    # Product-agnostic query interface
│   ├── BaseStructure.py                # Generic structure map base class
│   ├── BaseValue.py                    # Generic value map base class
│   ├── _GenericPricable.py             # Marker interface for instruments
│   ├── _GenericPricer.py               # Minimal pricer contract
│   └── product_adapter.py              # Adapter registry & abstract class
│
├── IRSwaps/
│   ├── IRSwapQuery.py                  # IRS query (user-facing)
│   ├── IRSwapStructure.py              # Structure enum + builder
│   ├── IRSwapValue.py                  # Value enum + calculator
│   ├── adapter.py                      # IRS product adapter
│   ├── _IRSwapGenericObject.py         # IRS instrument contract
│   ├── _IRSwapGenericCurve.py          # IRS pricer contract
│   ├── _CENTRAL_BANK_DATES.py          # Special date mappings
│   ├── _IRSwapGenericCurve.py          # Generic curve interface
│   ├── _IRSwapGenericObject.py         # Generic swap interface
│   └── backends/
│       ├── quantlib/
│       │   ├── QLIRSwapCurve.py        # QuantLib wrapper
│       │   ├── ql_pricer.py            # QL valuation funcs
│       │   ├── ql_curve_definitions_map.py
│       │   └── utils.py
│       └── rateslib/
│           ├── RLIRSwapCurve.py        # RatesLib wrapper
│           └── rl_curve_definitions_map.py
│
├── FixedRateBonds/
│   ├── FixedRateBondQuery.py           # FRB query (user-facing)
│   ├── FixedRateBondStructure.py       # Structure enum + builder
│   ├── FixedRateBondValue.py           # Value enum + calculator
│   ├── adapter.py                      # FRB product adapter
│   ├── _FixedRateBondGenericPricable.py # Bond contract
│   ├── _FixedRateBondGenericPricer.py  # Bond pricer contract
│   ├── _FixedRateBondGenericPricable.py
│   ├── _FixedRateBondGenericPricer.py
│   └── backends/
│       ├── quantlib/
│       │   ├── QLFixedRateBondPricer.py
│       │   └── ql_frb_definitions_map.py
│       └── rateslib/
│           ├── RLFixedRateBondPricer.py
│           └── rl_frb_definitions_map.py
```

## Key Concepts

### 1. BaseQuery - Product-Agnostic Entry Point

```python
# Everything is a query
query = IRSwapQuery(tenor="10Y", notional=1M, curve="USD-SOFR-1D")

# At each timestep, backtester:
req = query.build_mdp_request(now)          # → {"curve_name": ..., "timestamp": ...}
pricer = mdp.get_pricer(req)                # → QLIRSwapCurve or RLIRSwapCurve
package, weights = query.resolve_package(pricer)  # → ([swap], [1.0])
value_map = query.build_value_map(pricer, package, weights)
result = value_map.apply(IRSwapValue.NPV)   # → float (USD NPV)
```

### 2. Product Adapter Pattern

Each product registers itself once:

```python
# In Query/IRSwaps/adapter.py
class IRSProductAdapter(ProductAdapter):
    def build_structure_map(self, *, pricer_or_curve):
        return IRSwapStructureFunctionMap(curve=pricer_or_curve)
    
    def build_value_map(self, *, pricer_or_curve, package, risk_weights):
        return IRSwapValueFunctionMap(curve, package, risk_weights)
    
    def edit_query(self, *, q, pricer_or_curve):
        # Optional: resolve aliases, normalize specs, etc.
        return q

register_product("IRS", IRSProductAdapter)  # Self-register

# Backtester doesn't need to know this:
adapter_cls = get_adapter("IRS")  # → IRSProductAdapter
```

### 3. Structure Maps - Spec to Priceable

```
OUTRIGHT query:
  tenor="10Y", notional=1M
  ↓
  IRSwapStructureFunctionMap._build_outright(...)
  ↓
  curve.build_irswap(tenor="10Y", notional=1M)
  ↓
  [ql.VanillaSwap(...)]  # Backend-specific

CURVE (spread) query:
  front_tenor="2Y", back_tenor="10Y", bpv=10k
  ↓
  IRSwapStructureFunctionMap._build_curve(...)
  ↓
  Solve for notionals via: rw[i] = notional[i] / bpv[i]
  ↓
  [swap1, swap2] with notionals that give rw=[1, 1]
```

### 4. Value Maps - Package to Metrics

```
IRSwapValueFunctionMap stores:
  - curve (pricer)
  - package [swap1, swap2, ...]
  - risk_weights [1.0, -1.0, ...]

When apply(IRSwapValue.NPV) called:
  → _npv(**kwargs)
  → sum(curve.npv(s) for s in package)
  → returns float (USD)

When apply(IRSwapValue.PV01) called:
  → _pv01(**kwargs)
  → sum(curve.pv01(s) for s in package)
  → returns float (PV01 in USD)
```

### 5. Backend Abstraction

```
QLIRSwapCurve(ql.YieldTermStructureHandle)
  → fair_rate(swap) → ql_pricer.calc_fair_rate(...)
  → npv(swap) → ql_pricer.calc_npv(...)
  → pv01(swap) → ql_pricer.calc_pv01(...)

RLIRSwapCurve(rl.Curve)
  → fair_rate(swap) → swap.rate(curves=handle)
  → npv(swap) → swap.npv(curves=handle)
  → pv01(swap) → swap.analytic_delta(curve=handle)

Query layer doesn't care which backend is used!
```

## Common Operations

### Create Single Swap Query

```python
from Query.IRSwaps import IRSwapQuery, IRSwapStructure, IRSwapValue

q = IRSwapQuery(
    structure=IRSwapStructure.OUTRIGHT,
    tenor="10Y",
    value=IRSwapValue.RATE,
    notional=1_000_000,
    curve="USD-SOFR-1D",
)
```

### Create Curve Spread (2s10s)

```python
q = IRSwapQuery(
    structure=IRSwapStructure.CURVE,
    curve="USD-SOFR-1D",
    value=IRSwapValue.RATE,
    structure_kwargs={
        "front_tenor": "2Y",
        "back_tenor": "10Y",
        "bpv": 10_000,  # Constrain back leg
        "risk_weights": [1.0, 1.0],
    },
)
```

### Create Fly Spread (2s5s10s)

```python
q = IRSwapQuery(
    structure=IRSwapStructure.FLY,
    curve="USD-SOFR-1D",
    value=IRSwapValue.RATE,
    structure_kwargs={
        "front_tenor": "2Y",
        "belly_tenor": "5Y",
        "back_tenor": "10Y",
        "bpv": 10_000,
        "risk_weights": [1.0, -2.0, 1.0],  # Fly weights
    },
)
```

### Create Bond Query

```python
from Query.FixedRateBonds import FixedRateBondQuery, FixedRateBondStructure, FixedRateBondValue

q = FixedRateBondQuery(
    structure=FixedRateBondStructure.OUTRIGHT,
    cusip="912827XN6",  # 10-year UST
    value=FixedRateBondValue.YTM,
    curve="UST-DATA",
)
```

### Arithmetic on Queries

```python
# Single weights
q2y = IRSwapQuery(tenor="2Y", notional=1M, curve="USD-SOFR-1D")
q10y = IRSwapQuery(tenor="10Y", notional=1M, curve="USD-SOFR-1D")

# 2x long 2Y
weighted = q2y * 2

# Short 2Y
short = -q2y

# Curve spread (long 2Y, short 10Y)
curve = q2y - q10y

# Fly (long 2Y, short 5Y x2, long 10Y)
q5y = IRSwapQuery(tenor="5Y", notional=1M, curve="USD-SOFR-1D")
fly = q2y - q5y * 2 + q10y
```

### Multiple Value Metrics

```python
# Expand into separate queries
q = IRSwapQuery(
    tenor="10Y",
    value=[IRSwapValue.RATE, IRSwapValue.NPV, IRSwapValue.PV01],
    notional=1M,
    curve="USD-SOFR-1D",
)
queries = q.return_query()  # → [q_rate, q_npv, q_pv01]
```

## Integration with Backtester

```python
class Backtester:
    def value_query_at_time(self, query: BaseQuery, now: datetime):
        """Standard valuation loop."""
        # 1. Build MDP request
        mdp_req = query.build_mdp_request(now)
        
        # 2. Get pricer/curve from market data
        pricer = self.mdp.get_pricer(mdp_req)
        
        # 3. Optional: edit query (resolve aliases, etc.)
        query_edited = query._edited(pricer)
        
        # 4. Resolve structure
        package, weights = query_edited.resolve_package(pricer_or_curve=pricer)
        
        # 5. Build value map
        value_map = query_edited.build_value_map(
            pricer_or_curve=pricer,
            package=package,
            risk_weights=weights,
        )
        
        # 6. Compute metrics
        result = {}
        for value_id in [query_edited.default_mtm_value_id()] + list(query_edited.value_ids or []):
            if value_id is not None:
                result[value_id.name] = value_map.apply(value_id)
        
        return result
```

## Extending with New Product (Checklist)

- [ ] Define `XyzStructure` enum
- [ ] Define `XyzValue` enum
- [ ] Create `XyzQuery` dataclass (inherit `BaseQuery`)
- [ ] Create `_XyzGenericObject` interface (abstract methods for specs)
- [ ] Create `_XyzGenericPricer` interface
- [ ] Implement `XyzStructureFunctionMap(BaseStructureFunctionMap)`
- [ ] Implement `XyzValueFunctionMap(BaseValueFunctionMap)`
- [ ] Create `XyzProductAdapter(ProductAdapter)`
- [ ] Call `register_product("XYZ", XyzProductAdapter)`
- [ ] Implement `QLXyzPricer` wrapping QuantLib
- [ ] Implement `RLXyzPricer` wrapping RatesLib
- [ ] Implement `ql_xyz_definitions_map.py`
- [ ] Implement `rl_xyz_definitions_map.py`

## Troubleshooting

### "No ProductAdapter registered for product 'XYZ'"
→ Import the product module so `register_product()` is called

### "Structure 'CURVE' is not supported"
→ Implement `_build_curve()` in your `XyzStructureFunctionMap`

### "Value 'NPV' is not supported"
→ Add `IRSwapValue.NPV: self._npv` to `_create_map()`

### QuantLib vs RatesLib discrepancies
→ Check definitions map for curve specs (calendar, day count, frequency)

## Reference

See `QUERY_MODULE_COMPREHENSIVE_GUIDE.md` for:
- Full architecture explanation
- Complete API reference
- Detailed extension guide with swaption example
- Backend abstraction details
