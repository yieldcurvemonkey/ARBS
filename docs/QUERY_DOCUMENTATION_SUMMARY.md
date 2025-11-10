# Query Module Documentation - Complete Summary

## Overview

Comprehensive technical documentation for the ARBS Query module has been created. The documentation covers the product-agnostic query system that enables backtesting with pluggable products (IRSwaps, FixedRateBonds, and extensible for others).

## Documents Created

### 1. QUERY_MODULE_COMPREHENSIVE_GUIDE.md (2,399 lines)

**Primary comprehensive reference covering all aspects:**

#### Contents:
1. **Overview & Architecture** (diagrams, philosophy, core components)
2. **BaseQuery Abstract Interface** (fields, methods, contracts, arithmetic operations)
3. **Product Adapter Pattern & Registration** (abstract interface, registry mechanism, IRSProductAdapter example)
4. **Structure Maps & Value Maps** (converting specs to priceables, computing metrics)
5. **Generic Interfaces: Pricable & Pricer** (marker interfaces, product-specific extensions)
6. **IRSwaps Implementation** (IRSwapQuery, Structure/Value enums, usage examples)
7. **FixedRateBonds Implementation** (analogous structure to IRSwaps)
8. **Backend Abstraction Layer** (QuantLib vs RatesLib wrappers, definitions maps)
9. **Query Resolution Pipeline** (complete workflow from user code to valued positions)
10. **Extension Guide: Adding New Products** (step-by-step swaption example)
11. **API Reference** (comprehensive class/method reference)

**Best for:**
- Understanding the complete system architecture
- Deep dives into how components work
- Creating new products (detailed swaption walkthrough)
- API specifications
- Backend abstraction details

### 2. QUERY_QUICK_REFERENCE.md

**Quick lookup guide for common tasks:**

#### Sections:
- **File Structure** - Visual directory tree with annotations
- **Key Concepts** - 5 core concepts with visual flows
- **Common Operations** - Code examples for typical usage
- **Integration with Backtester** - Standard valuation loop
- **Extending with New Product** - Checklist of tasks
- **Troubleshooting** - Common errors and solutions

**Best for:**
- Quick lookups during development
- Copy-paste code examples
- Checklist for extending the system
- Debugging common issues

### 3. This Summary Document

Overview of all documentation created and what each covers.

## Key Topics Documented

### 1. BaseQuery Abstract Interface & Its Contract

**Coverage:**
- Frozen dataclass design with product-agnostic fields
- Core fields: product, structure_id, structure_kwargs, value_id/value_ids, market_request
- Key methods: build_mdp_request(), resolve_package(), build_value_map()
- Abstract methods each subclass must implement
- Convenience methods: signature(), default_mtm_value_id()
- Arithmetic operations for composing spreads and flies
- Examples of single outright, curve spreads, and fly spreads

**Document:** Comprehensive Guide, Section 2

### 2. Product Adapter Pattern & Registration System

**Coverage:**
- Abstract ProductAdapter base class
- Three key abstract methods: build_structure_map(), build_value_map(), edit_query()
- Registry mechanism: _ADAPTERS dict, register_product(), get_adapter()
- Self-registration pattern on module import
- Example: IRSProductAdapter with MMS alias resolution
- Example: FRBProductAdapter

**Document:** Comprehensive Guide, Section 3 + Quick Reference, Section 2

### 3. Structure Map & Value Map Concepts

**Coverage:**

**Structure Maps:**
- Purpose: Convert high-level specs (enum + params) to concrete instruments
- BaseStructureFunctionMap generic base class
- apply() method merges common_kwargs with builder_kwargs
- IRSwaps: _build_outright(), _build_curve(), _build_fly()
- _build_spreadable() helper for risk-weighted multi-leg structures
- Linear solve for notional distribution using PV01 values

**Value Maps:**
- Purpose: Compute metrics on instrument packages
- BaseValueFunctionMap generic base class
- apply() method delegates to enum-specific calculator
- IRSwaps: RATE, NPV, PV01, DV01, GAMMA, NOTIONAL, CARRY, ROLL, etc.
- FixedRateBonds: YTM, CLEAN_PRICE, DIRTY_PRICE, NPV, PV01, DV01, DURATION, CONVEXITY

**Documents:** 
- Comprehensive Guide, Section 4
- Quick Reference, Sections 3-4

### 4. IRSwaps Implementation (Query, Structure, Value, Adapter)

**Coverage:**

**IRSwapQuery:**
- User-facing fields: structure, value, tenor, effective_date, maturity_date, is_mms, curve
- Auto-filling of BaseQuery fields in __post_init__()
- return_query() for expanding multi-value queries
- col_name() and eval_expression() for display/analysis
- Arithmetic operations returning IRSwapQuery (not List)

**IRSwapStructure Enum:**
- OUTRIGHT: Single swap
- CURVE: 2-leg spread
- FLY: 3-leg spread  
- SPREAD: Alias for OUTRIGHT

**IRSwapValue Enum:**
- RATE: Fair swap rate in basis points
- NPV: Mark-to-market PnL
- PV01: Basis point value
- DV01: Dollar value of 1bp
- GAMMA_01: Second-order sensitivity
- NOTIONAL: Total notional with signs
- CARRY_BPS_RUNNING, ROLL_BPS_RUNNING, etc.

**IRSwapStructureFunctionMap:**
- Builds outright, curve (2-leg), and fly (3-leg) structures
- _build_spreadable() solves for risk-weighted notionals
- Handles tenor parsing and explicit date specification
- Supports forward swaps via "3Mx10Y" syntax

**IRSwapValueFunctionMap:**
- Computes all metrics by summing across package
- Handles multi-leg spread metrics (fair rate weighted by risk_weights)
- Supports horizon-dependent metrics (carry, rolldown)

**IRSProductAdapter:**
- Builds IRSwapStructureFunctionMap and IRSwapValueFunctionMap
- edit_query() handles MMS alias resolution (CT2, O3, Ox5, MMYY[-OI])

**Documents:** 
- Comprehensive Guide, Sections 2, 3, 4, 6
- Quick Reference, Sections 1, 3, 5

### 5. FixedRateBonds Implementation

**Coverage:**

**FixedRateBondQuery:**
- Similar to IRSwapQuery but for bonds
- Fields: structure, value, cusip, curve
- Auto-filling of BaseQuery fields

**FixedRateBondStructure Enum:**
- OUTRIGHT: Single bond
- CURVE: 2-bond spread
- FLY: 3-bond spread

**FixedRateBondValue Enum:**
- YTM: Yield to maturity
- CLEAN_PRICE, DIRTY_PRICE: Price metrics
- NPV: Mark-to-market PnL
- PV01, DV01: Sensitivity metrics
- MOD_DURATION, CONVEXITY: Duration-based metrics

**FixedRateBondStructureFunctionMap:**
- Works with pricer dict (one pricer per bond/CUSIP)
- Builds outright, curve, and fly structures
- Solves for notionals using PV01 values

**FixedRateBondValueFunctionMap:**
- Computes YTM, prices, NPV, PV01, DV01, duration, convexity
- Similar pattern to IRSwaps but tailored for bonds

**FRBProductAdapter:**
- Builds structure and value maps
- Minimal edit_query (placeholder)

**Documents:**
- Comprehensive Guide, Section 7
- Quick Reference, Section 6

### 6. Generic Interfaces (Pricable, Pricer)

**Coverage:**

**_GenericPricable:**
- Marker interface (intentionally minimal)
- Subclassed by _IRSwapGenericObject and _FixedRateBondGenericPricable
- Allows polymorphic handling of any instrument type

**_GenericPricer:**
- Abstract contract with three key methods:
  - npv(instrument) -> float
  - build_pricable(**kwargs) -> _GenericPricable
  - resolve_pricable(priceable, risk_weight) -> _GenericPricable
- Generic[_GP] for type safety

**_IRSwapGenericObject:**
- Abstract methods for swap properties: effective_date, maturity_date, fixed_rate, nominal
- Abstract methods for valuations: fair_rate, npv, pv01, dv01, gamma
- Abstract methods for greeks: carry_bps_running, roll_bps_running, etc.

**_IRSwapGenericCurve:**
- Pricer for swaps (curve-based valuation)
- Methods for: id, reference_date, calendar, calendar_advance, handle, index, meta
- Accessor methods delegating to swap objects
- Valuation methods (npv, pv01, dv01, gamma, carry, roll)
- Instrument building (build_irswap, build_stirf)

**_FixedRateBondGenericPricable:**
- Similar to _IRSwapGenericObject but for bonds
- Properties: effective_date, maturity_date, coupon, nominal, ytm
- Valuations: dirty_price, clean_price, npv, accured, pv01
- Greeks: mod_duration, convexity

**_FixedRateBondGenericPricer:**
- Pricer for bonds
- Methods for: id, reference_date, calendar, calendar_advance, meta
- Properties: issue_date, maturity_date, coupon, notional
- Valuations: ytm, dirty_price, clean_price, npv, accured, pv01
- Methods: build_pricable, resolve_pricable

**Documents:**
- Comprehensive Guide, Section 5
- Quick Reference, Section 5

### 7. Backend Abstraction (QuantLib vs RatesLib)

**Coverage:**

**Philosophy:**
- Two independent pricing libraries wrapped behind generic interfaces
- Backtester completely unaware of backend choice
- Swappable without changing query logic

**QuantLib Backend (IRSwaps):**
- QLIRSwapCurve wraps ql.YieldTermStructureHandle
- ql_pricer module with calc_fair_rate, calc_npv, calc_pv01, etc.
- ql_curve_definitions_map with curve specs (calendar, day count, business convention)
- utils.py for datetime conversions

**RatesLib Backend (IRSwaps):**
- RLIRSwapCurve wraps rl.Curve
- Direct delegation to rateslib objects for computations
- rl_curve_definitions_map with specs in rateslib format
- Similar interface, different underlying implementation

**QuantLib Backend (Bonds):**
- QLFixedRateBondPricer wraps bond specifications
- build_schedule() creates ql.Schedule
- ytm, clean_price, dirty_price, npv via QL computation
- ql_frb_definitions_map with bond specs

**RatesLib Backend (Bonds):**
- RLFixedRateBondPricer wraps RL-compatible specs
- build_schedule() creates rl.Schedule
- Similar interface to QL version

**Definitions Maps:**
- Centralized configuration for each backend
- Calendar, business convention, day count, frequency, etc.
- Enables swapping backends without code changes

**Documents:**
- Comprehensive Guide, Section 8
- Quick Reference, Section 5

### 8. Query Resolution Mechanism

**Coverage:**

**Complete Workflow:**
1. User creates query (IRSwapQuery, FixedRateBondQuery)
2. At each timestep, backtester calls build_mdp_request(now)
3. Gets pricer/curve from MDP
4. Optionally edits query via adapter.edit_query()
5. Resolves structure via adapter.build_structure_map()
6. Applies structure map to get (package, weights)
7. Builds value map via adapter.build_value_map()
8. Applies value map to compute metrics

**Data Flows:**
- Building structure maps: store pricer/curve in common_kwargs, later merge with params
- Resolving structures: builder functions receive merged kwargs, return (priceables, weights)
- Computing values: value functions receive package + weights, aggregate results

**Example Traces:**
- Single swap: tenor="10Y", notional=1M → ([swap], [1.0]) → NPV
- Curve spread: front="2Y", back="10Y", bpv=10k → solves notionals → ([swap1, swap2], [1.0, 1.0])
- Fly spread: 3-leg structure with risk_weights=[1, -2, 1]

**Documents:**
- Comprehensive Guide, Section 9
- Quick Reference, Section 1

### 9. Package Resolution Mechanism (Concepts)

**Coverage:**

**Structure Resolution:**
- Converts high-level specifications into concrete instruments
- Structure enum + parameters → builder function
- Builder returns (List[Priceable], List[float])

**Risk-Weighted Notional Solving:**
- For spreads/flies, often only one leg notional or bpv is specified
- Linear solver uses PV01 values to distribute notionals
- Ensures: risk_weight[i] = notional[i] / bpv[i]

**Query Editing:**
- Optional pre-processing step via adapter.edit_query()
- Example: Resolve UST aliases (CT2) to CUSIPs and maturity dates
- Normalizes query before structure resolution

**Documents:**
- Comprehensive Guide, Section 4 (Structure Maps)
- Quick Reference, Sections 3, 7

### 10. Complete API Reference

**Coverage:**

**BaseQuery:**
- All fields with types and purposes
- All methods with signatures and descriptions
- Abstract methods each subclass must implement

**IRSwapQuery:**
- Fields table with defaults and notes
- IRSwapStructure enum values
- IRSwapValue enum values

**FixedRateBondQuery:**
- Fields table
- Structure and value enum values

**ProductAdapter:**
- Methods with signatures and purposes
- Registry functions (register_product, get_adapter)

**BaseStructureFunctionMap:**
- Abstract methods and apply() signature

**BaseValueFunctionMap:**
- Abstract methods and apply() signature

**_IRSwapGenericCurve:**
- Complete method listing with signatures

**_IRSwapGenericObject:**
- Complete method listing with signatures

**_FixedRateBondGenericPricer:**
- Method listing

**_FixedRateBondGenericPricable:**
- Method listing

**Backend Implementations:**
- QLIRSwapCurve constructor and key methods
- RLIRSwapCurve constructor and key methods
- QLFixedRateBondPricer constructor
- RLFixedRateBondPricer constructor

**Document:** Comprehensive Guide, Section 11

## How to Extend for New Products

**Full walkthrough included for adding Swaptions:**
- Step 1: Define Structure & Value Enums
- Step 2: Define Generic Pricable & Pricer Interfaces
- Step 3: Define Query Class
- Step 4: Implement Structure Map
- Step 5: Implement Value Map
- Step 6: Implement Product Adapter
- Step 7: Implement Backend Wrappers (QuantLib + RatesLib)
- Step 8: Usage example

**Checklist in Quick Reference**

**Document:** Comprehensive Guide, Section 10

## Code Coverage

**Base Layer (6 files):**
- BaseQuery.py - Product-agnostic query interface
- BaseStructure.py - Generic structure map base
- BaseValue.py - Generic value map base
- _GenericPricable.py - Marker interface
- _GenericPricer.py - Minimal pricer contract
- product_adapter.py - Adapter registry

**IRSwaps (8 core files + backends):**
- IRSwapQuery.py - User-facing query
- IRSwapStructure.py - Structure enum & builder
- IRSwapValue.py - Value enum & calculator
- adapter.py - Product adapter
- _IRSwapGenericObject.py - Instrument contract
- _IRSwapGenericCurve.py - Pricer contract
- 2 backend implementations (QL + RL)

**FixedRateBonds (8 core files + backends):**
- FixedRateBondQuery.py - User-facing query
- FixedRateBondStructure.py - Structure enum & builder
- FixedRateBondValue.py - Value enum & calculator
- adapter.py - Product adapter
- _FixedRateBondGenericPricable.py - Instrument contract
- _FixedRateBondGenericPricer.py - Pricer contract
- 2 backend implementations (QL + RL)

**Total analyzed: 32+ files with complete understanding of architecture and implementation patterns**

## Key Architectural Insights Documented

1. **Product Agnosticism via Adapter Pattern**
   - Backtester doesn't know about specific products
   - Each product self-registers via ProductAdapter

2. **Structure/Value Decoupling**
   - Separate concern: what to build vs. how to value it
   - Enables flexible composition and swapping

3. **Backend Flexibility**
   - Generic interfaces allow QuantLib ↔ RatesLib swaps
   - Definitions maps centralize backend-specific config

4. **Risk-Weighted Multi-Leg Structures**
   - Linear algebra solver for notional distribution
   - Enables intuitive spread/fly construction

5. **Type Safety Through Frozen Dataclasses**
   - Immutability by design
   - Clear data contracts

6. **Extensibility**
   - Well-defined patterns for adding new products
   - ~1000 LOC per product following the pattern

## Documents Statistics

- **Comprehensive Guide:** 2,399 lines
- **Quick Reference:** ~400 lines
- **Summary (this document):** This file

Total: 2,800+ lines of documentation

## Usage Notes

**For learning the system:**
1. Start with Quick Reference, Section "Key Concepts"
2. Read Comprehensive Guide Section 2 (BaseQuery)
3. Read Comprehensive Guide Section 3 (Adapter Pattern)
4. Deep dive into Section 9 (Query Resolution Pipeline)

**For implementing a feature:**
1. Check Quick Reference for code examples
2. Look up specific classes in API Reference
3. Reference the extension guide for new products

**For debugging:**
1. Check Quick Reference troubleshooting section
2. Trace through Section 9 (Query Resolution)
3. Look at specific backend implementation in Section 8

## Related Files

- All source code in `/home/user/ARBS/Query/`
- Documentation in `/home/user/ARBS/docs/`
  - `QUERY_MODULE_COMPREHENSIVE_GUIDE.md` (main reference)
  - `QUERY_QUICK_REFERENCE.md` (quick lookup)
  - `QUERY_DOCUMENTATION_SUMMARY.md` (this file)

