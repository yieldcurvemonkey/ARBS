# Spread MDPs & EventContractsMDP Design

**Date:** 2026-03-15
**Status:** Approved

## Overview

Six new MDPs with full query/structure/value/TB support:
1. **SpreadMDP** — Generic composable base class
2. **IRSwapSpreadsMDP** — Swap-vs-benchmark spreads
3. **IRBasisSwapsMDP** — SOFR vs OIS/Fed Funds basis (BARCHART_STIRF-RL)
4. **IRClearingHouseBasisSwapsMDP** — LCH vs CME clearing house basis (GS Quant)
5. **STIRConvexityAdjustmentMDP** — Empirical (STIRT vs Eris) + analytical (HW1F)
6. **EventContractsMDP** — Kalshi & Polymarket event contracts

## Architecture: Composable SpreadMDP Pattern

### SpreadMDP Base

```python
class SpreadMDP(MarketDataProvider):
    """Wraps two MDPs, returns a SpreadPricer holding both underlying pricers."""
    def __init__(self, mdp_a: MarketDataProvider, mdp_b: MarketDataProvider,
                 request_splitter: Callable[[dict], Tuple[dict, dict]], source: str, **kwargs):
        super().__init__(source=source, **kwargs)
        self.mdp_a = mdp_a
        self.mdp_b = mdp_b
        self.request_splitter = request_splitter

    def get_pricer(self, request: dict) -> SpreadPricer:
        req_a, req_b = self.request_splitter(request)
        pricer_a = self.mdp_a.get_pricer(req_a)
        pricer_b = self.mdp_b.get_pricer(req_b)
        return SpreadPricer(pricer_a, pricer_b, meta_data={...})
```

### SpreadPricer

```python
class SpreadPricer:
    """Holds two pricers. Delegates fair_rate/npv/pv01 to each leg."""
    def __init__(self, pricer_a, pricer_b, meta_data: dict):
        self.pricer_a = pricer_a  # _IRSwapGenericCurve or similar
        self.pricer_b = pricer_b
        self._meta_data = meta_data

    @property
    def meta_data(self) -> dict:
        return self._meta_data
```

## Concrete MDPs

### IRSwapSpreadsMDP

Generic swap-vs-benchmark spreads using two IRSwapsMDP instances with different curve names or sources.

- **Request:** `{curve_a: str, curve_b: str, source_a: str, source_b: str, timestamp: ...}`
- **request_splitter:** maps to `{curve_name: curve_a, timestamp}` and `{curve_name: curve_b, timestamp}`
- Does NOT break IRSwapValue.MMSS (single-curve computation unchanged)

### IRBasisSwapsMDP

SOFR vs OIS/Fed Funds basis. Both legs from BARCHART_STIRF-RL, different curve names.

- **Default config:** `mdp_a = IRSwapsMDP("BARCHART_STIRF-RL")`, `mdp_b = IRSwapsMDP("BARCHART_STIRF-RL")`
- **Request:** `{curve_a: "USD-SOFR-1D-Q12STIRT", curve_b: "USD-FEDFUNDS-...", timestamp: ...}`

### IRClearingHouseBasisSwapsMDP

LCH vs CME clearing house basis from GS Quant IR_SWAP_RATES_V1_STANDARD dataset.

- **Source:** `GSQUANT-RL` for both legs
- **gs_quant_fetcher.py:** Parses coverage Excel to find matching assetIds for `{ccy} Swap {index} ... {tenor} {clearing_house} Cleared`
- **Request:** `{tenor: "5Y", index: "SOFR", clearing_house_a: "LCH", clearing_house_b: "CME", timestamp: ...}`
- Fetches both timeseries from GS `Dataset("IR_SWAP_RATES_V1_STANDARD")`, computes difference in bps

### STIRConvexityAdjustmentMDP

Two modes:

**Empirical (default):** SpreadMDP wrapping:
- `mdp_a = IRSwapsMDP("BARCHART_STIRF-RL")` — futures-implied (no convexity)
- `mdp_b = IRSwapsMDP("ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")` — swap curve (with convexity)
- Spread = rate_a - rate_b = observed convexity adjustment

**Analytical (HW1F):**
- `hw1f_model.py` calibrates Hull-White 1-factor model (mean reversion `a`, volatility `sigma`)
- Computes theoretical cvx adjustment: `(sigma^2 / 2a^2) * (1 - e^(-a*T1)) * (1 - e^(-a*T2))`
- Exposed via `STIRConvexityAdjustmentValue.CVX_ADJ_HW1F`

### EventContractsMDP

Standalone MDP (not a spread). Two sources: `KALSHI`, `POLYMARKET`.

- **kalshi_fetcher.py:** REST API client for Kalshi historical data
  - Endpoint: `GET /trade-api/v2/series/{ticker}/events/{event_ticker}/markets`
  - Historical: CSV downloads from docs.kalshi.com
- **polymarket_fetcher.py:** REST API client for Polymarket
  - Endpoint: `GET /prices-history` with market param
- **EventContractPricer:** Wraps fetched contract data, exposes price/probability

## Query Layer

### SpreadQuery (for all spread MDPs)

```python
@dataclass(frozen=True)
class SpreadQuery(BaseQuery):
    product: str = "IRSPREAD"  # or "IRBASIS", "IRCHBASIS", "STIRCVX"
    structure: SpreadStructure = SpreadStructure.OUTRIGHT
    value: SpreadValue = SpreadValue.SPREAD_BPS
    tenor: Optional[str] = None
    # Delegates to IRSwapQuery internally for each leg
```

### SpreadStructure

```python
class SpreadStructure(Enum):
    OUTRIGHT = auto()  # Single spread point
    CURVE = auto()     # Spread of spreads (e.g., 2Y basis vs 10Y basis)
    FLY = auto()       # 3-point spread structure
```

### SpreadValue

```python
class SpreadValue(Enum):
    SPREAD_BPS = auto()       # (rate_a - rate_b) * 10000
    SPREAD_RATE = auto()      # rate_a - rate_b
    LEG_A_RATE = auto()
    LEG_B_RATE = auto()
    PV01 = auto()
    NPV = auto()
    CVX_ADJ_EMPIRICAL = auto()  # STIRConvexityAdjustment only
    CVX_ADJ_HW1F = auto()      # STIRConvexityAdjustment only
```

### EventContractQuery

```python
@dataclass(frozen=True)
class EventContractQuery(BaseQuery):
    product: str = "EVENT"
    structure: EventContractStructure = EventContractStructure.OUTRIGHT
    value: EventContractValue = EventContractValue.PRICE
    ticker: Optional[str] = None       # e.g., "KXBTC-26MAR15"
    market_slug: Optional[str] = None  # Polymarket slug
```

### EventContractValue

```python
class EventContractValue(Enum):
    PRICE = auto()
    PROBABILITY = auto()
    VOLUME = auto()
    OPEN_INTEREST = auto()
```

## Product Adapters

| Product key | Adapter | Registered by |
|-------------|---------|---------------|
| `IRSPREAD` | SpreadProductAdapter | `Query/Spreads/adapter.py` |
| `IRBASIS` | SpreadProductAdapter (reused) | same file |
| `IRCHBASIS` | SpreadProductAdapter (reused) | same file |
| `STIRCVX` | SpreadProductAdapter (reused) | same file |
| `EVENT` | EventContractProductAdapter | `Query/EventContracts/adapter.py` |

The SpreadProductAdapter delegates `build_structure_map` and `build_value_map` to SpreadStructureFunctionMap and SpreadValueFunctionMap, which internally use IRSwapQuery to resolve each leg.

## File Structure

```
MDP/
  Spreads/
    SpreadMDP.py
    SpreadPricer.py
  IRSwapSpreads/
    IRSwapSpreadsMDP.py        # existing dir, populate empty stub
  IRBasisSwaps/
    IRBasisSwapsMDP.py
  IRClearingHouseBasisSwaps/
    IRClearingHouseBasisSwapsMDP.py
    gs_quant_fetcher.py
  STIRConvexityAdjustment/
    STIRConvexityAdjustmentMDP.py
    hw1f_model.py
  EventContracts/
    EventContractsMDP.py
    kalshi_fetcher.py
    polymarket_fetcher.py

Query/
  Spreads/
    SpreadQuery.py
    SpreadStructure.py
    SpreadValue.py
    adapter.py
  EventContracts/
    EventContractQuery.py
    EventContractStructure.py
    EventContractValue.py
    adapter.py
```

## TB Integration

All new MDPs plug into the existing backtester engine via:
1. `BaseQuery.build_mdp_request(now)` -> MDP.get_pricer(request)
2. `resolve_package(pricer_or_curve)` -> (package, risk_weights) via product adapter
3. `build_value_map(pricer_or_curve, package, risk_weights)` -> ValueFunctionMap
4. `apply(value)` -> metric

No changes needed to the backtester engine itself.

## Compatibility

- **IRSwapValue.MMSS** unchanged — single-curve matched-maturity swap spread
- **IRSwapValue.CVX_ADJ** unchanged — existing single-package convexity computation
- **MultiProductMDP** can route to new MDPs by adding entries to its product dict
- Existing IRSwapQuery arithmetic (`+`, `-`, `*`) works with SpreadQuery via BaseQuery
