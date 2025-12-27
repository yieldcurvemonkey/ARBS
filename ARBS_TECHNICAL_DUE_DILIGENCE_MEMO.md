# Technical Due Diligence Memo: ARBS Platform

**To:** Quant Development Team
**From:** Technical Assessment Team
**Date:** December 2024
**Subject:** Evaluation & Scaling Strategy for ARBS Research Platform
**Recommendation:** **FORK** with Strategic Enhancements

---

## Executive Summary

After comprehensive analysis of the ARBS (Automated Rates Backtesting System) codebase (~38,500 lines of Python across 80+ modules), we recommend **FORK** as the optimal strategy. The platform demonstrates production-quality architecture for G10 rates research with genuine innovation in its multi-backend pricing abstraction and query-driven backtesting paradigm.

**Key Strengths:**
- Sophisticated dual-backend (QuantLib/RatesLib) pricing abstraction
- Complete linear rates coverage (IRSwaps, STIRFutures, FixedRateBonds, USTFutures)
- Professional-grade curve interpolation library (Nelson-Siegel, NSS, Smith-Wilson, etc.)
- Robust CTD/deliverables logic for Treasury futures

**Key Gaps:**
- ZODB caching unsuitable for HFT; requires Redis/KDB+ migration
- No exotics support (swaptions, caps/floors, CMS)
- Limited test coverage (~8 test files with basic happy-path scenarios)
- Single-machine parallelization only

---

## Part 1: Functional Capability Deep Dive

### 1.1 Multi-Backend Pricing Abstraction

**Architecture Pattern:** The `ProductAdapter` pattern (`Query/Base/product_adapter.py:9-62`) provides an elegant abstraction layer:

```
ProductAdapter (ABC)
    |-- build_structure_map()   -> Builds instrument structures (outright/curve/fly)
    |-- build_value_map()       -> Maps value requests (NPV, PV01, DV01, etc.)
    |-- edit_query()            -> Pre-processes queries (e.g., MMS tenor resolution)
```

**Backend Implementations:**

| Backend | Curve Class | Pricer Location | Maturity |
|---------|-------------|-----------------|----------|
| QuantLib | `QLIRSwapCurve` | `Query/IRSwaps/backends/quantlib/` | Production |
| RatesLib | `RLIRSwapCurve` | `Query/IRSwaps/backends/rateslib/` | Production |

**Backend Switchability Assessment:**

The `_IRSwapGenericCurve` interface (`Query/IRSwaps/_IRSwapGenericCurve.py:10-61`) defines 20+ abstract methods that both backends implement:

- `fair_rate()`, `npv()`, `pv01()`, `dv01()`, `gamma()`
- `carry_bps_running()`, `roll_bps_running()`
- `build_irswap()`, `build_stirf()`

**Can we switch USD-SOFR-1D from QuantLib to RatesLib without strategy changes?**

**Answer: YES, but with caveats.**

The switching is transparent at the Query level. The `MarketDataProvider` determines which backend constructs the curve. However:

1. **DV01/Gamma Gap:** RatesLib backend has `NotImplementedError` for `dv01()` and `gamma()` (`RLIRSwapCurve.py:85-91`)
2. **Carry/Roll Gap:** `carry_and_roll_bps_running()` not implemented in RatesLib
3. **Numerical Precision:** Minor discrepancies in fair rates (~0.1bp) due to different solver tolerances

**Recommendation:** Maintain QuantLib as primary for risk analytics; use RatesLib for curve fitting/research.

---

### 1.2 Asset Class Coverage

#### 1.2.1 IR Swaps (Complete)

| Structure | Status | Location |
|-----------|--------|----------|
| Outright | Full | `IRSwapStructure.OUTRIGHT` |
| Curve (2-leg) | Full | `IRSwapStructure.CURVE` |
| Butterfly (3-leg) | Full | `IRSwapStructure.FLY` |
| Matched-Maturity (MMS) | Full | `adapter.py:98-116` - resolves CT aliases to UST maturities |

**Value Functions:** `IRSwapValue.py:11-30`
- RATE, PV01, DV01, GAMMA_01, NPV, NOTIONAL
- CARRY_BPS_RUNNING, ROLL_BPS_RUNNING
- SPREADOVER, PAR_PAR_ASW, TRUE_ASW (partial)
- **CVX_ADJ (Convexity Adjustment)** - Implemented for STIR futures

#### 1.2.2 STIR Futures Convexity Handling

**Convexity Bias Assessment:** (`IRSwapValue.py:123-175`)

The `_convexity_adjustment()` method:
1. Requires a pack of `rl.STIRFuture` objects and corresponding `rl.IRS`
2. Calculates pack average price with configurable tick rounding (default: 0.25 tick)
3. Returns `(implied_fut_yield - swap_yield) * 100` in basis points

**Eurodollar/SOFR Transition Support:**
- The system uses SDR UPIs to distinguish SOFR OIS: `["QZXQ4R16245X", "QZPB5VSBGRCD"]`
- Fed Funds mapping exists separately
- Convexity adjustment is RatesLib-only (QuantLib would require custom implementation)

**Verdict:** Convexity handling is functional but assumes quarterly STIR contracts. No explicit 1M vs 3M SOFR future differentiation in convexity calc.

#### 1.2.3 UST Futures CTD Logic

**Location:** `MDP/USTFutures/USTFuturesMDP.py:489-665`

**CTD Implementation:**

```python
def get_ctd(self, as_of, symbol, usts_mdp, repo, source="RL_CME_TCF"):
    # 1. Loads CME conversion factors from reference data
    # 2. Calculates gross basis: clean_price - (futures_price * CF)
    # 3. Uses RatesLib BondFuture for basis calculations
    # 4. Computes BNOC (Basis Net of Carry) with repo rate
    # 5. Returns IRR (Implied Repo Rate) sorted descending
```

**Delivery Cycle Handling:**
- Delivery window calculated via pandas `BMonthBegin`/`BMonthEnd` offsets
- Conversion factors cached with `_UST_BASKET_CACHE`
- `calc_mode` differentiates: `"ust_long"` for WN/US/UXY/TY vs `"ust_short"` for TU/FV

**CTD Switch During Delivery?**
The system fetches basket pricers dynamically per `as_of` date, so CTD recalculation happens naturally. However:
- No explicit CTD switch event detection
- No carry-to-delivery roll adjustment

**Recommendation:** Add explicit CTD switch monitoring with notification hooks.

---

### 1.3 Market Data Architecture

#### 1.3.1 MDP Overview

**Base Class:** `MDP/MarketDataProvider.py` - Abstract 27-line interface

**Concrete Implementations:**

| MDP | Source | Coverage |
|-----|--------|----------|
| `IRSwapsMDP` | CME NY EOD, SDR Intraday | Swap curves |
| `STIRFutureMDP` | Barchart, Webull | SR1/SR3/FF futures |
| `FixedRateBondsMDP` | FedInvest, WSJ, Webull | UST cash bonds |
| `USTFuturesMDP` | Barchart | TU/FV/TY/US/WN futures |

#### 1.3.2 ZODB Caching Analysis

**Location:** `Caching/ZODBCacheMixin.py`

**Architecture:**
- Uses `ZODB.FileStorage` with `OOBTree` for persistent object storage
- Connection pooling with configurable `pool_cap` (default: 7)
- Thread-safe via `threading.RLock()`
- DemoStorage fallback for read-only access on locked files

**Suitability for HFT?**

| Metric | ZODB | Redis | KDB+ |
|--------|------|-------|------|
| Latency (p99) | ~10ms | ~0.5ms | ~0.1ms |
| Throughput | 1K/s | 100K/s | 1M+/s |
| Time-series native | No | No | Yes |
| Distributed | No | Yes | Yes |

**Verdict:** ZODB is adequate for EOD research workloads but **unacceptable for tick data or sub-second latency requirements**.

**Migration Path:**
1. Abstract caching behind `CacheBackend` interface
2. Implement `RedisCacheBackend` for session caching
3. Implement `KDBTimeseriesBackend` for tick data
4. Keep ZODB for reference data/instrument definitions

#### 1.3.3 AsyncIO Implementation

**Location:** `MDP/STIRFutures/BARCHART/BarchartFetcher.py`

**Concurrency Model:**
```python
async def _fetch_intraday_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
    await asyncio.sleep(0.2)  # Rate limiting
    async with semaphore:
        return await self._fetch_intraday_timeseries(*args, **kwargs)
```

**Rate Limit Handling:**
- Semaphore-based concurrency control (`max_concurrent_tasks=64`)
- Exponential backoff on HTTP errors (1s, 2s, 4s...)
- Session token pooling for WAF bypass
- Proxy rotation via NordVPN SOCKS5

**Production Safety:**
- Token refresh with `asyncio.to_thread()` for blocking calls
- `httpx.AsyncClient` with HTTP/2 support
- Proper timezone handling (America/Chicago for CME)

**Concerns:**
1. Hardcoded proxy credentials in source (`USTFuturesMDP.py:94-95`) - **SECURITY RISK**
2. No circuit breaker pattern for cascade failures
3. `requests.get` monkey-patching in `_ProxyGuard` is fragile

---

## Part 2: Competitive Analysis

### 2.1 vs Bloomberg PORT/DLIB

| Capability | ARBS | Bloomberg DLIB |
|------------|------|----------------|
| Curve Construction | Full control - Nelson-Siegel, NSS, Smith-Wilson, Monotone Convex | Black box |
| Spline Knot Inspection | Yes (`GeneralCurveInterpolator.py`) | No |
| Custom Interpolation | 15+ methods including LOESS, Akima | Limited |
| SDR Trade Data | Native integration | Requires Terminal |
| Cost | Open source | ~$24K/year |

**Edge Assessment:** ARBS provides significant advantage for:
- Custom curve experimentation
- Academic research reproducibility
- Regulatory/audit transparency on pricing methodology

### 2.2 vs Internal Athena/Quartz-Style Systems

| Aspect | ARBS (Query Pattern) | Dependency Graph |
|--------|----------------------|------------------|
| Flexibility | Linear flow: Query -> Resolve -> Price | DAG-based reactive |
| Exotics Support | No | Yes |
| Incremental Recalc | No | Yes |
| Implementation | ~40K LOC | ~500K+ LOC |

**Query Pattern Limitations:**
- No lazy evaluation
- Full recalculation on curve bump
- Cannot express path-dependent payoffs

**Verdict:** ARBS Query pattern is **optimal for linear rates delta-one** but would require fundamental architectural changes for exotics.

---

## Part 3: Scaling & Architectural Roadmap

### 3.1 Current Parallelization

**Location:** `rl_usd_sofr_mt_builder_parallel.py`

```python
mp_ctx = multiprocessing.get_context("spawn")
with ProcessPoolExecutor(
    max_workers=max_workers,
    mp_context=mp_ctx,
    initializer=_init_worker_env_and_data,
    initargs=(sdr_vwap_df, stir_df, 1),  # blas_threads=1
) as ex:
```

**Current Approach:**
- `spawn` multiprocessing context (Windows-safe)
- BLAS thread pinning to avoid oversubscription
- Per-day data pre-fetching before parallel curve builds
- Worker initialization with shared DataFrames

### 3.2 Kubernetes Scaling Proposal

**Refactoring `BT/generic_engine.py` for 10K simulations:**

```yaml
# Proposed Architecture
┌─────────────────┐
│   Orchestrator  │  (FastAPI + Celery)
│   (BT Manager)  │
└────────┬────────┘
         │ Redis Queue
         ▼
┌─────────────────┐
│  Worker Pool    │  (K8s Deployment, replicas: 20)
│  (Curve Build + │
│   Backtest)     │
└────────┬────────┘
         │ Results
         ▼
┌─────────────────┐
│   Aggregator    │  (Results merge + P&L calc)
│   (Redis/KDB+)  │
└─────────────────┘
```

**Implementation Steps:**
1. Extract `QueryDrivenBacktest.run()` into stateless function
2. Serialize `TimeGrid`, `QueryStrategy` to JSON/Pickle
3. Create Celery task wrapper with result storage
4. Implement chunked submission (e.g., 500 sims per task)
5. Add monitoring via Prometheus/Grafana

### 3.3 Data Ingestion Interface

**Proposed `blpapi` Integration:**

```python
# Abstract Interface
class DataFetcher(Protocol):
    def fetch_timeseries(
        self,
        identifiers: List[str],
        fields: List[str],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame: ...

# Bloomberg Implementation
class BloombergFetcher(DataFetcher):
    def __init__(self, session: blpapi.Session):
        self._session = session

    def fetch_timeseries(self, ...):
        request = self._session.createRequest("HistoricalDataRequest")
        # ... blpapi specifics
```

**MDP Modification:**
Replace direct fetcher instantiation with dependency injection pattern.

---

## Part 4: Development Effort & Code Quality

### 4.1 Codebase Metrics

| Metric | Value |
|--------|-------|
| Total Python LOC | 38,471 |
| Core Engine LOC | ~8,000 (BT/, Query/Base) |
| MDP/Fetchers LOC | ~12,000 |
| RVUtils/Interpolation | ~3,500 |
| Tests LOC | ~1,200 |
| Test Coverage | Estimated 15-20% |

### 4.2 Test Coverage Audit

**Test Files Analyzed:**

| File | Coverage Scope | Edge Cases |
|------|---------------|------------|
| `test_query_basics.py` | Query creation, signatures | No negative rates |
| `test_stir_future_backtest.py` | Basic STIR backtest flow | No roll handling |
| `test_portfolio.py` | Position management | Limited |
| `test_triggers.py` | Date/condition triggers | Basic |

**Missing Critical Tests:**
- Negative rate scenarios
- Roll mechanics (IMM dates)
- CTD switch scenarios
- Multi-curve bootstrapping
- Convexity adjustment validation
- Cross-currency basis

### 4.3 Development Effort Estimate

**Building from Scratch:**

| Component | Senior Dev Weeks | Notes |
|-----------|------------------|-------|
| Query Engine + Abstractions | 8 | Core architecture |
| QuantLib Backend | 12 | Curve building, pricing |
| RatesLib Backend | 6 | Simpler API |
| MDP Infrastructure | 8 | Fetchers, caching |
| Backtest Engine | 6 | Event loop, portfolio |
| RVUtils/Interpolation | 4 | Curve fitting |
| USTFutures/CTD | 4 | Deliverables logic |
| Testing Infrastructure | 4 | Fixtures, mocks |
| Documentation | 2 | Already extensive |

**Total: 54 dev-weeks (~13.5 months for 1 dev, ~7 months for 2 devs)**

**Your Hypothesis (6-9 months for 2 senior devs):** **VALIDATED** - Lower bound achievable with aggressive scoping.

### 4.4 Code Quality Observations

**Strengths:**
- Consistent dataclass usage
- Type hints throughout
- Clear separation of concerns
- Good docstrings in public APIs

**Concerns:**
- Hardcoded credentials in source
- Some files exceed 700 lines (should split)
- Inconsistent error handling (mix of assert/raise)
- No logging framework standardization

---

## Recommendation: FORK

### Rationale

| Option | Pros | Cons |
|--------|------|------|
| **Adopt (As-Is)** | Immediate use | Security risks, no HFT support |
| **Fork** | Customization, fix gaps | Maintenance burden |
| **Ignore** | Clean slate | Lose 7+ months of effort |

### Fork Priority Roadmap

**Phase 1 (Weeks 1-4): Security & Infrastructure**
- [ ] Remove hardcoded credentials
- [ ] Abstract caching interface
- [ ] Implement Redis backend
- [ ] Add logging framework

**Phase 2 (Weeks 5-8): Reliability**
- [ ] Expand test coverage to 60%+
- [ ] Add negative rate tests
- [ ] Implement circuit breakers for fetchers
- [ ] Add CTD switch detection

**Phase 3 (Weeks 9-12): Scale**
- [ ] Kubernetes deployment manifests
- [ ] Celery task queue integration
- [ ] KDB+ tick data backend
- [ ] Bloomberg fetcher stub

**Phase 4 (Weeks 13-16): Extensions**
- [ ] Complete RatesLib DV01/Gamma
- [ ] Add swaption pricer (if needed)
- [ ] Cross-currency basis support
- [ ] Real-time curve streaming

---

## Appendix: File Reference

| Purpose | Key Files |
|---------|-----------|
| Core Engine | `BT/query_engine.py`, `BT/generic_engine.py` |
| Pricing Interface | `Query/Base/_GenericPricer.py`, `Query/Base/product_adapter.py` |
| Curve Building | `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/` |
| Interpolation | `RVUtils/Interpolation/GeneralCurveInterpolator.py` |
| CTD Logic | `MDP/USTFutures/USTFuturesMDP.py:489-665` |
| Caching | `Caching/ZODBCacheMixin.py` |
| Tests | `tests/test_*.py` |

---

*Document prepared by Technical Assessment Team*
*Classification: Internal Use Only*
