# ARBS STIR Futures (SOFR) Infrastructure Map

All paths absolute. Everything marked **[verified]** was run against the live repo/cache with `C:\Users\chris\anaconda3\envs\stir\python.exe` on 2026-08-14.

---

## 1. Daily SOFR futures settlement prices, historically

### Source and API

**Source = Barchart**, via `STIRFutureMDP(source="BARCHART_STIRF-RL")`. Note the class default is *not* Barchart:

`C:/Users/chris/clee/ARBS/MDP/STIRFutures/STIRFutureMDP.py:465`
```python
def __init__(self, source: str = "WEBULL_STIRF-RL", force_refresh_fixings: Optional[bool] = False, **kwargs: Any):
```
Accepted sources (`:1014`): `{"WEBULL_STIRF-RL", "BARCHART_STIRF-RL", "BARCHART_TOS_LIVE_STIRF-RL", "SCHWAB_APP_STIRF-RL"}`. Anything else → `NotImplementedError`.

Three public entry points (`:1321-1377`):
```python
def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:
def get_data(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:      # {"symbols": [...], "timestamp": date|datetime|"live"}
def get_bulk_data(self, request: Dict[str, Any]) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:  # {"symbols": [...], "timestamps": [...], "max_workers": 8}
def fetch_pricers_flat(self, symbols, timestamp, **kwargs) -> OrderedDict[str, _STIRFutureGenericPricer]   # :1304
```

**[verified] working call** (ran fully offline from cache):
```python
mdp = STIRFutureMDP(source="BARCHART_STIRF-RL")
snap = mdp.get_data({"symbols": ["SR3M26", ...], "timestamp": datetime.date(2026, 4, 28)})
p = snap["SR3M26"][0]
p.price()            # 96.34
p.fixed_rate()       # 3.66   (percent, = 100 - price)
p.effective_date()   # 2026-06-17
p.maturity_date()    # 2026-09-16
p.pv01(contracts=1)  # 25.0
p.meta()["openinterest"]
```
A **date** (not datetime) triggers the EOD path (`want_eod`, `:1018`); a datetime triggers the intraday path.

### On-disk cache path

`MDP/STIRFutures/STIRFutureMDP.py:514`
```python
cache_path = LayeredCacheMixin.default_cache_path("STIRFuturePricer_Cache")
```
resolving (via `Caching/DiskCacheMixin.py:47-67`, `platformdirs.user_cache_dir("ARBS", appauthor=False)`) to:

```
C:\Users\chris\AppData\Local\ARBS\Cache\diskcache\dump\STIRFuturePricer_Cache
```
An 8-shard `diskcache.FanoutCache`, 8 GB limit, LRU. **[verified] 22,298,644 keys.**

Key format (`:1067`): `f"{ts_key}-{ticker}-{src}"`. EOD rows are keyed at **17:00 America/New_York** because `_as_datetime(date)` localizes to 17:00 NY (`:100`). **[verified]** stored value shape:
```python
{'symbol': 'SR3M26', 'price': 96.34, 'timestamp': '2026-04-28T17:00:00-04:00', 'schema': 1}
# optional extra key: 'openinterest'
```

Second store — the *calibrated* Q12 futures curve (minute-level DF nodes, not raw prices):
```
C:\Users\chris\AppData\Local\ARBS\Cache\curve_store\raw\asset=USD-SOFR-1D-Q12STIRT\date=YYYY-MM-DD\<hash>.parquet
```
columns: `timestamp_utc, timestamp_local, trading_date, session_minute, curve_name, cfg_hash, reference_key, interpolation, source_variant(=BARCHART_STIRF), node_dates, discount_factors`.

### [verified] date coverage

| measure | count | min | max |
|---|---|---|---|
| EOD (17:00 NY) SR3 dates, `BARCHART_STIRF-RL` | 2070 | 2018-05-04 | 2026-08-07 |
| …of those, with the **full Q12** set cached | 1406 | 2018-05-04 | 2026-07-27 |
| SR3 dates at **any** timestamp (EOD ∪ intraday, both Barchart sources) | 2307 | 2018-05-04 | 2026-08-13 |
| …with the **full Q12** set | 1807 | 2018-05-04 | 2026-08-13 |
| calibrated `USD-SOFR-1D-Q12STIRT` curve-store dates | 2060 | 2018-06-01 | 2026-08-13 |

Full-Q12 (any-time) per year: 2018:167, 2019:252, 2020:253, 2021:271, 2022:253, 2023:224, **2024:56**, 2025:141, 2026:190. 2024 is the weak spot in the local cache; the *curve* store is essentially complete over the whole span.

Contracts per EOD date (SR3): min 1, median 18, max 28. Sample days **[verified]**:
- 2020-03-16 → 27 contracts, SR3Z19 … SR3M26 (98.44 … 99.565), monotone
- 2022-06-15 → 18 contracts, SR3H22 … SR3M26
- 2026-04-28 → 13 contracts, SR3H26 … SR3H29

### Is a continuous "Q12" curve available? — Yes, three ways

1. **Symbol-level**: `_next_contracts(as_of, prefix="SR3", count=12, valid_months=[3,6,9,12], cutoff_fn=_imm_cutoff)` (from `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/tos.py`). **[verified]** as of 2026-04-28 → `['SR3M26','SR3U26','SR3Z26','SR3H27','SR3M27','SR3U27','SR3Z27','SR3H28','SR3M28','SR3U28','SR3Z28','SR3H29']`.
2. **Rank aliases**: `SFRCM1`…`SFRCM12` resolve to the rank-n contract at each date (`_resolve_aliases_bulk`). This is exactly what the curve config uses.
3. **Rate panel (the constant-maturity path the repo actually uses)** — `C:/Users/chris/clee/ARBS/BT/signals/sfr_cal_spread_rv.py:341`:
```python
def load_rate_panel(config, start, end, *, curve_mdp=None, ts_builder=None,
                    freq: str = "nyc_eod", n_jobs: int = 12, show_tqdm: bool = True) -> pd.DataFrame:
    """Load EOD outright rates for Q12 SOFR contracts.  Returns DataFrame[dates x labels] with implied rates (%)."""
    queries = [UnifiedQuery(curve=config.curve, tenor=imm_tenor(rank), value=UnifiedValue.IRS_RATE)
               for rank in range(1, config.n_contracts + 1)]
    panel = ts_builder.get_timeseries(start=start, end=end, queries=queries, freq=freq, n_jobs=n_jobs,
                                      routers={"IRS": IRSwapsTB(curve_mdp, show_tqdm=show_tqdm)},
                                      ignore_cache_miss=True)
```
i.e. `IMM_NxIMM_{N+1}` swap rates off `USD-SOFR-1D-Q12STIRT` — constant maturity by construction, with `roll_adjust_panel` available for back-adjusting at roll boundaries.

The curve is defined at `C:/Users/chris/clee/ARBS/MDP/IRSwaps/BARCHART_STIRF/rl.py:1047`:
```python
"USD-SOFR-1D-Q12STIRT": {
    "fetch_pricers_func": self.stirf_mdp.get_data,
    "fetch_pricers_bulk_func": self.stirf_mdp.get_bulk_data,
    "instruments": ["SFRCM1", ..., "SFRCM13"],
    "reference_key": "USD-SOFR-1D",
    "max_tenor_from_timestamp_months": 39,
    "rl_irs_spec": "usd_irs_lt_2y",
    "stirf_target_weight": 1e6,
},
```
Also defined: `-Q16STIRT` (CM1..17), `-Q20STIRT` (CM1..21), `-Q12xM12STIRT`, `CAD-CORRA-Q8STIRT`. Built by `BARCHART_STIRF_CURVE.build_curve(curve_name, timestamp | [timestamps], kwargs, curve_only=True)` (`rl.py:2782`).

### Three caveats you must carry forward

1. **"EOD" is not the CME settle.** For a date request the code fetches Barchart **1-minute** bars for the whole Chicago day and picks the bar *nearest* the request instant (17:00 NY = 16:00 CT):
   ```python
   lookup_ts = _align_lookup_ts(series.index, ts_dt)
   pos = series.index.get_indexer([lookup_ts], method="nearest")
   ```
   (`STIRFutureMDP.py:1227-1229`). `_call` hardcodes `interval=1` even when `interval=None` is passed (`:807-819`). CME's official SR3 settlement is struck at 14:00 CT, so these are 16:00 CT marks, not settles. There is no `settle`/`settlement` string anywhere in `MDP/STIRFutures/BARCHART/BarchartFetcher.py` — the EOD OI path uses `merge_val_col="Open Interest"`, prices default to `"Close"`.
2. **The diskcache is demand-driven, not a complete archive.** A miss goes to the network (proxy-rotated Barchart). Coverage numbers above describe what is *already local*.
3. **`price_df = price_df.ffill().bfill()`** (`:1146`) before slicing, so a contract with no print on the day inherits a neighbouring value.

---

## 2. Contract code conventions

### Roots and aliases

`MDP/STIRFutures/STIRFutureMDP.py:41-71`
```python
_MONTHLY_STIR_ROOTS = {"SR1", "ZQ", "IJ", "JU"}
_IMM_STIR_ROOTS     = {"SR3", "RA", "EB", "RG", "IM", "TV", "J8", "T0", "IT", "J2"}
_ROOT_ALIAS_MAP = {"SFR": "SR3", "SER": "SR1", "FF": "ZQ", "SQ": "SR3", "SL": "SR1"}
_ROOT_TO_CURVE_MAP = {"SR1": "USD-SOFR-1D", "SR3": "USD-SOFR-1D", "ZQ": "USD-FEDFUNDS",
                      "RA": "EUR-ESTR", ..., "GE": "USD-SOFR-1D"}
```
- **SR3** = internal canonical root for 3M SOFR (CME Globex). **SFR** = the Bloomberg-style alias → normalized to SR3. **SQ** = the *Barchart* root for SR3; **SL** = Barchart root for SR1.
- **SR1 / SER** = 1M SOFR (monthly, `roll="som"`). **ZQ / FF** = Fed Funds. **GE** = Eurodollar (mapped to the SOFR curve *only* to resolve conventions and a $25 pv01 — there is an explicit `Do NOT use this mapping to value a Eurodollar position` warning at `:69`).
- Direction maps back out in `RLSTIRFuturePricer` (`backends/rateslib/RLSTIRFuturePricer.py:285`): `_CME_TO_BBG = {"SR3": "SFR", "SR1": "SER", "ZQ": "FF"}`, with `root()`, `bbg_root()`, `bbg_id()`.

`_to_barchart_symbol` / `_from_barchart_symbol` (`:115-140`) do `SR3↔SQ`, `SR1↔SL`.

### Month codes

`[FGHJKMNQUVXZ]` + 2-digit year, throughout. Quarterly IMM restricted to `H=3, M=6, U=9, Z=12`:
```python
_IMM_MONTH_MAP  = {"H": 3, "M": 6, "U": 9, "Z": 12}     # RVUtils/SFRConvexScreener/_carry_roll.py:30
_NEXT_IMM_CODE  = {"H": "M", "M": "U", "U": "Z", "Z": "H"}
```
A bare `"H26"` normalizes to `"SR3H26"` (`_normalize_symbol`, `:149`).

### Expiry / start / end derivation

`MDP/STIRFutures/STIRFutureMDP.py:314-347`
```python
if root in _MONTHLY_STIR_ROOTS:
    effective   = cme_code_effective_date(code)
    termination = first_business_day_next_month(pd.Timestamp(effective))
    stir = rl.STIRFuture(effective=effective, termination=termination,
                         spec=_ROOT_TO_STIR_SPEC.get(root, "usd_stir1"), roll="som", price=price)
    return norm, stir

effective   = rl.scheduling.get_imm(code=code)
termination = rl.scheduling.next_imm(effective)
spec = _ROOT_TO_STIR_SPEC.get(root, "usd_stir")
stir = rl.STIRFuture(effective=effective, termination=termination, spec=spec, price=price)
```
Dates are then read back out with `_extract_stir_effective_termination(temp_stir)` (`:375`) into the pricer. **[verified]** SR3M26 → eff 2026-06-17, mat 2026-09-16.

Rateslib spec selection (`RLSTIRFuturePricer.rl_spec`, `:312`): `ReferenceRate3` if root ∈ `{SR1, SER, SL}` (the `is_ser` flag), else `ReferenceRate2`, falling back to `ReferenceRate`, all looked up in `RATESLIB_CURVE_DEFINITIONS[curve]`.

Symbol → IMM swap tenor (`RVUtils/SFRConvexScreener/_carry_roll.py:34`):
```python
def sfr_to_imm_tenor(symbol: str) -> str:
    """Convert ``SFR{code}{yy}`` to an IMM-IMM swap tenor string.  Example: ``SFRZ26 → IMM_Z2026xIMM_H2027``."""
```

### Composite aliases **[verified]** (`_resolve_aliases_bulk`, as of 2026-04-28)

| alias | expands to |
|---|---|
| `whites` | `['SR3M26','SR3U26','SR3Z26','SR3H27']` |
| `reds` | `['SR3M27','SR3U27','SR3Z27','SR3H28']` |
| `greens` | `['SR3M28','SR3U28','SR3Z28','SR3H29']` |
| `2-Year` (`\d+[-\s]?(year|yr|y)s?`) | 8 contracts `SR3M26 … SR3H28` |
| `SFRCM1` / `CM1` / `SFRCM12` | `['SR3M26']` / `['SR3M26']` / `['SR3H29']` |
| `SERFFF26`, `SR1ZQF26`, `SLZQF26`, `FFSERF26` | `['SR1F26', 'ZQF26']` (SOFR–FedFunds spread, returned as a 2-element list) |
| `H26`, `SFRZ26`, `GEZ21` | `['SR3H26']`, `['SR3Z26']`, `['GEZ21']` |

Color order: `["whites","reds","greens","blues","golds","silvers","platinums"]` (`:226`).

---

## 3. Convexity-adjustment code

### 3a. `STIRConvexityAdjustmentMDP` — empirical futures-vs-swap CA

`C:/Users/chris/clee/ARBS/MDP/STIRConvexityAdjustment/STIRConvexityAdjustmentMDP.py` — a thin `SpreadMDP` subclass, **no model of its own**. It differences two OIS curves: one built from futures (no convexity) minus one built from swaps (with convexity).

```python
def _cvx_request_splitter(request):
    ts = request.get("timestamp")
    curve_name   = request.get("curve_name", "USD-SOFR-1D")
    curve_name_a = request.get("curve_name_a", f"{curve_name}-Q12STIRT")
    curve_name_b = request.get("curve_name_b", curve_name)
    return {"curve_name": curve_name_a, "timestamp": ts}, {"curve_name": curve_name_b, "timestamp": ts}

class STIRConvexityAdjustmentMDP(SpreadMDP):
    def __init__(self, source_a="BARCHART_STIRF-RL", source_b="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS", ...):
        ... super().__init__(mdp_a=IRSwapsMDP(source_a), mdp_b=IRSwapsMDP(source_b),
                             request_splitter=_cvx_request_splitter, source="STIRCVX_EMPIRICAL")
```
- **Inputs**: `{"curve_name", "curve_name_a", "curve_name_b", "timestamp"}`.
- **Output**: a `SpreadPricer(pricer_a, pricer_b)` (a container only — `MDP/Spreads/SpreadPricer.py`).
- **Consumed by** `Query/IRSwaps/IRSwapValue.py:361` `IRSwapValue.CVX_ADJ_EMPIRICAL`:
```python
return sum(risk_weights[i] * (pricer_a.fair_rate(sw) - pricer_b.fair_rate(sw))
           for i, sw in enumerate(package)) * 10_000.0
```
i.e. **(futures-curve rate − swap-curve rate) × 10 000 = bp**. Also exposed as `SpreadValue.CVX_ADJ_EMPIRICAL` (aliased to `_spread_bps` in `Query/Spreads/adapter.py:119`).

### 3b. `hw1f_model.py` — analytical HW1F CA

`C:/Users/chris/clee/ARBS/MDP/STIRConvexityAdjustment/hw1f_model.py` (the entire file is one function):
```python
def hw1f_convexity_adjustment(a: float, sigma: float, T1: float, T2: float) -> float:
    """CA = (sigma^2 / 2a^2) * (1 - e^(-a*T1)) * (1 - e^(-a*T2))
    Returns: Convexity adjustment in rate terms (multiply by 10000 for bps)"""
    if a <= 0:
        raise ValueError(f"Mean reversion 'a' must be positive, got {a}")
    return (sigma**2 / (2 * a**2)) * (1 - math.exp(-a * T1)) * (1 - math.exp(-a * T2))
```
It is **not wired in**. `SpreadValue.CVX_ADJ_HW1F` exists but `Query/Spreads/adapter.py:161` is:
```python
raise NotImplementedError("HW1F convexity adjustment requires hw1f_model — see STIRConvexityAdjustmentMDP")
```
Only `tests/test_stir_convexity_adjustment_mdp.py` calls the formula.

### 3c. `SFRConvexScreener` — **NOT a convexity adjuster**

Read this before using it. Despite the name, `RVUtils/SFRConvexScreener` computes nothing about futures-vs-swap convexity. Its own docstring (`__init__.py`):

> "Ranks 3M SOFR futures calendar spreads and butterflies by the **asymmetry of their option-implied payoff distributions**."

"Convex" here = a *linear* structure whose option-implied P&L distribution is asymmetric. Full pipeline (`screener.py:126` `build_snapshot(config, *, as_of)`):

1. **`_market_data.load_market_data`** → frozen `SFRMarketData(as_of, symbols, sr3_symbols, curve_handle, futures_df, price_panel, smiles, smile_asof_by_symbol, curve_asof, warnings)`. Four fetches:
   - universe: `_next_contracts(as_of, prefix="SR3", count=config.universe_size, valid_months=[3,6,9,12], cutoff_fn=_imm_cutoff)` then `SR3→SFR` renaming (all downstream keys are `SFR*`, all MDP calls use `SR3*`);
   - OIS curve `IRSwapsMDP(source="BARCHART_STIRF-RL").get_pricer({"curve_name": "USD-SOFR-1D-Q12STIRT", "timestamp": d})`;
   - futures snapshot `STIRFutureMDP(source=...).get_data({"symbols": sr3_symbols, "timestamp": as_of})` → `futures_df[price, rate, open_interest, volume, effective, maturity]`;
   - 60-day price panel via `get_bulk_data({"symbols", "timestamps": bdate_range, "max_workers": 8})`;
   - per-contract SABR smiles `STIRFutureOptionMDP(source="BARCHART_STIRFO-QL").fetch_sabr_smile({"symbol", "as_of", ...})`.
   All four use `_try_with_fallback(fn, as_of=..., max_fallback_days=5)`, walking back business days and appending a `stale_smile_asof=` warning.
2. **`_universe.enumerate_structures`** → `OUTRIGHT` (w=+1), `CALENDAR` (w=+1,−1) at `calendar_gaps=(1,2,4)`, `BUTTERFLY` (w=+1,−2,+1) at `fly_gaps=(1,2,4)`. IDs: `{sym}_OUTRIGHT`, `{f}_{b}_CAL_{gap}`, `{a}_{b}_{c}_FLY_1_-2_1`.
3. **`_distributions.extract_bl_marginals`** → Breeden–Litzenberger RND per contract from `RVUtils.ImpliedDistribution.SFRImpliedDistribution`. Two modes: default SABR+ghost-points hybrid, or `jpm_method=True` (JPM Tech Appendix A: `use_sabr_vols=False, sabr_extrapolation=False, raw_market_open_interest_min=100.0, raw_market_otm_only=True, smoothing_param=1e-4, spline_order=4, n_ghost_points=10, ghost_extension_bps=5.0, bin_width_bps=25.0`).
4. **Joint payoff PDFs**, three methods (`JointMethod`): `COMMON_STATE` (FOMC-path joint via `SFRImpliedDistribution.extract_joint` + `linear_combination_distribution(weights)`), `HISTORICAL_GAUSSIAN_COPULA` (eigen-repaired 60d correlation of daily *rate* changes, inverse-CDF through BL marginals, `n_simulations=100_000`, `random_seed=17`), `PERFECT_CORRELATION` (front-contract marginal × Σweights). Outrights bypass all three and use `payoff_pdf_outright` directly (method label `"marginal"`).
5. **`_metrics`** → `PayoffMetrics(mean_bp, std_bp, skew, excess_kurtosis, p_profit, ev_given_profit_bp, ev_given_loss_bp, asymmetry_ratio, percentiles_bp{p5,p25,p50,p75,p95}, tail_ratio)`. The central definition:
```python
upper = ev_pos * (len(pos)/n);  lower = abs(ev_neg * (len(neg)/n))
asym  = upper / lower if lower > 0 else float("inf")     # _metrics.py:60-62
tail  = abs(pcts["p95"]) / abs(pcts["p5"])
```
   → **asymmetry_ratio = probability-weighted gain mass ÷ probability-weighted loss mass.** `A > 1` ⇒ the as-enumerated long-rate leg has positive asymmetric edge; `A < 1` ⇒ flip (`StructureResult.direction()` → `"PAY X / RECEIVE 2x Y (long-rate fly)"` etc.).
6. **`_carry_roll`** → `carry_3m_bp = current_level_bp = 100 * Σ w_i·rate_i` (from `futures_df`, *not* a carry number despite the field name), and `rolldown_bp = Σ w_i · IRSwapValue.ROLL_BPS_RUNNING` per `sfr_to_imm_tenor(leg)` at `rolldown_horizon="1m"` (3m collapses the IMM-IMM schedule).
7. **`_ivrv`** → `iv_bp = bl.std_rate*100/sqrt(tte)` vs 21-day realized; **`_historical`** → forward 63-day realized structure P&L and its realized asymmetry.
8. **`_scoring.composite_score_series`** → cross-sectional z-scores of `(asymmetry, p_profit, ev_carry = mean_bp + carry, tail_ratio)` weighted `(0.4, 0.2, 0.3, 0.1)`; ranked descending.

Backtest side: `_backtest_cache.SnapshotCache` (pickle per `{as_of}_{sha256(config)[:12]}.pkl`), `_backtest_signals.BacktestSignal`, `_backtest_triggers.SFRScreenerBacktestConfig`, and `_backtest_query.structure_to_query` which maps each structure to an **`IRSwapQuery` on IMM tenors**, not a STIRFutureQuery.

`SFRConvexScreenerConfig` defaults worth knowing: `universe_size=12`, `curve_source="BARCHART_STIRF-RL"`, `curve_name="USD-SOFR-1D-Q12STIRT"`, `options_source="BARCHART_STIRFO-QL"`, `smile_strike_mode="listed"` (the docstring records that `delta_sparse` gave a fly asymmetry of 35.8 vs 0.97 on 2026-04-28 — do not switch it casually), `output_root="data/screener_results/sfr_convex_screener"`.

---

## 4. `Query/STIRFutures` — enums, structures, conventions

### Full enum members

`Query/STIRFutures/STIRFutureStructure.py:13`
```python
class STIRFutureStructure(Enum):
    OUTRIGHT = auto()
    CURVE    = auto()
    BASIS    = auto()
    FLY      = auto()

    SPREAD = CURVE      # alias — SPREAD *is* CURVE, same enum member
```
`Query/STIRFutures/STIRFutureValue.py:12`
```python
class STIRFutureValue(Enum):
    RATE = auto()
    NPV = auto()
    PRICE = auto()
    PV01 = auto()
    DV01 = auto()
    OPEN_INTEREST = auto()
```

### Expressing each structure — exact `structure_kwargs` (**[verified]** unless noted)

**OUTRIGHT** (`_build_outright`, accepts at most one of `contracts` / `notional` / `bpv`; defaults `notional=1_000_000` when none given):
```python
STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
                symbol="SR3M26", structure_kwargs={"contracts": 1})
# → PRICE 96.34, PV01 25.0, NPV 2408.5
STIRFutureQuery(..., symbol="SR3M26", structure_kwargs={"bpv": 1000.0})
# → PV01 1000.0, NPV 96340.0   (contracts = round(bpv / pv01_per_contract) = 40)
```
Other accepted keys: `effective_date`, `maturity_date`, `price`, `rate`, `is_ser`, `risk_weights` (scalar list of 1).

**PACK (4 contracts)** — via the "alias pack" branch of `_build_outright` (`:214-242`): pass a symbol the pricer dict does **not** contain while the dict holds >1 pricer, and every pricer becomes a leg.
```python
mdp.get_data({"symbols": ["whites"], "timestamp": d})     # → 4 pricers
STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
                symbol="whites",
                structure_kwargs={"contracts": 1, "risk_weights": [1.0, 1.0, 1.0, 1.0]})
# → 4 legs, rws [1,1,1,1], PRICE 385.39, PV01 100.0, NPV 9634.75
```
`risk_weights` defaults to `[1.0]*N` if omitted; length must equal N or `ValueError`.

**BUNDLE** — identical mechanism, `"2-Year"` / `"5-year"` / `"10Y"` aliases:
```python
STIRFutureQuery(structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
                symbol="2-Year", structure_kwargs={"contracts": 1})
# → 8 legs SR3M26..SR3H28, PRICE 771.135, PV01 200.0, NPV 19278.375
```

**SPREAD / CURVE**:
```python
STIRFutureQuery(structure=STIRFutureStructure.CURVE, value=STIRFutureValue.PRICE,
                structure_kwargs={"front_symbol": "SR3M26", "back_symbol": "SR3U26",
                                  "risk_weights": [1.0, -1.0], "contracts": 1})
# → PRICE -0.015, PV01 50.0, NPV -0.375
```
Also accepted: `symbols=[front, back]`, or `symbol="SR3M26/SR3U26"` / `"H26 v M26"` / `"H26-M26"` (`_split_curve_symbols`), plus per-leg prefixed keys `front_*` / `back_*` (`effective_date`, `maturity_date`, `price`, `rate`, `notional`, `contracts`), and constraint sizing `constrained_leg_index` (default 0) with exactly one of `constrained_contracts` / `constrained_bpv`. `risk_weights` defaults `[1.0, -1.0]`.

**BASIS** (same symbol, two curves):
```python
STIRFutureQuery(structure=STIRFutureStructure.BASIS, value=STIRFutureValue.PRICE, symbol="SR3M26",
                structure_kwargs={"front_curve": "USD-SOFR-1D-Q12STIRT", "back_curve": "USD-SOFR-1D"})
```
`__post_init__` asserts both `front_curve` and `back_curve`, then routes them into `market_request["front_curve_name"] / ["back_curve_name"]`. Leg keys resolve via `basis_front_key` / `basis_back_key`.

**BUTTERFLY — currently broken. [verified]**
```python
STIRFutureQuery(structure=STIRFutureStructure.FLY, value=STIRFutureValue.PRICE,
                structure_kwargs={"symbols": ["SR3M26","SR3U26","SR3Z26"],
                                  "risk_weights": [1.0, -2.0, 1.0], "contracts": 1})
# NameError: name 'kwargs' is not defined
```
Cause — `Query/STIRFutures/STIRFutureStructure.py:316-360`. The signature closes with `**_` but the body references `kwargs`:
```python
        constrained_bpv: Optional[float] = None,
        **_,                                              # <-- line 328
    ) -> ...:
        ...
        legs = [
            self._build_leg(**self._leg_kwargs(key=keys[0], prefix="front", is_ser=bool(is_ser), contracts=(contracts[0] if contracts else None), kwargs=kwargs)),   # line 356
            self._build_leg(**self._leg_kwargs(key=keys[1], prefix="belly", ..., kwargs=kwargs)),                                                                     # line 357
            self._build_leg(**self._leg_kwargs(key=keys[2], prefix="back",  ..., kwargs=kwargs)),                                                                     # line 358
        ]
```
Both entry paths (`symbols=[f,b,k]` and `front_symbol`/`belly_symbol`/`back_symbol`) hit line 356, so FLY is unusable. `_build_basis` has the **same defect by inspection** (`**_` at line 374, `kwargs=kwargs` at lines 402–404) — not run, but structurally identical. `_build_curve` is fine because its signature ends `**kwargs`.

The kwargs FLY *would* take: `symbols=[front, belly, back]` (preferred, doubles as pricer keys) or `front_symbol`/`belly_symbol`/`back_symbol`; `risk_weights` default `[1.0, -2.0, 1.0]`; `constrained_leg_index` default **1** (belly); one of `constrained_contracts`/`constrained_bpv`; per-leg `front_*`/`belly_*`/`back_*`.

**Working butterfly path the repo actually uses** — route through IMM swaps, not STIR futures (`RVUtils/SFRConvexScreener/_backtest_query.py:71`):
```python
IRSwapQuery(structure=IRSwapStructure.FLY, curve=curve,
            structure_kwargs={"front_tenor": sfr_to_imm_tenor(front.contract),
                              "belly_tenor": sfr_to_imm_tenor(belly.contract),
                              "back_tenor":  sfr_to_imm_tenor(back.contract),
                              "bpv": sign * float(bpv)}, tags=tags)
```
That file's own note: *"Calendars use `IRSwapStructure.CURVE`; the `SPREAD` enum value internally routes to the outright builder and cannot consume two-leg kwargs."*

### Other verified defects in this package

- **`STIRFutureValue.RATE` always raises.** `calc_spread_rate` calls `pr.fair_rate(pk)` (`STIRFutureValue.py:43`) but `RLSTIRFuturePricer.fair_rate(self)` takes no argument → `TypeError: RLSTIRFuturePricer.fair_rate() takes 1 positional argument but 2 were given`. **[verified]** on OUTRIGHT and CURVE. Use `PRICE` and convert (`rate = 100 - price`), which is what everything downstream does.
- **Duplicate dict key** (`STIRFutureValue.py:28-33`): `{1: (OUTRIGHT,1), 2: (CURVE,100), 2: (BASIS,100), 3: (FLY,100)}` — the second `2:` silently wins, so a 2-leg package always reports as `BASIS`. Scale factor is 100 either way.
- **3-leg slash symbol fails at construction. [verified]** `STIRFutureQuery(symbol="SR3M26/SR3U26/SR3Z26")` → `AssertionError: CURVE/SPREAD requires front/back symbols OR full front/back date pairs` (`STIRFutureQuery.py:134`) — `_split_curve_symbols` rejects two delimiters, so the FLY auto-detect at `:208` is never reached.
- **2-leg slash works but leaves `structure=OUTRIGHT`. [verified]** `STIRFutureQuery(symbol="SR3M26/SR3U26")` → `structure.name == 'OUTRIGHT'`, `structure_kwargs={'symbol': 'SR3M26/SR3U26', 'front_symbol': 'SR3M26', 'back_symbol': 'SR3U26', 'risk_weights': [1.0, -1.0]}`; because `explicit_multi_leg` is already True the `slash_count == 1` reassignment at `:204` is skipped. It still prices correctly via the pack branch: PRICE −0.015, PV01 50.0, NPV −0.375.

### Sign / BPV conventions

- Price↔rate: `rate = 100.0 - price` (percent), `fair_rate()` returns `rate/100` (decimal).
- **PV01 is per contract from rateslib analytic delta, sign-flipped**, with a mandatory unit discount curve for rateslib ≥2.7 (`RLSTIRFuturePricer.py:228-244`):
```python
return -float(self.build_stirf(contracts=..., notional=...)
              .analytic_delta(curves=_unit_discount_curve()).real)
```
  **[verified]** SR3 = **$25.00/bp/contract**; SR1 (SER) = **$41.67/bp/contract**. `DV01` is literally `pv01()`.
- Sizing: `bpv → contracts = int(round(bpv / pv01_per_contract))`; `notional → contracts = int(round(n / 1_000_000))` ("Standard STIR assumption: 1mm face per contract", `:417`).
- **`PRICE` and `NPV` apply `risk_weights`; `PV01` and `DV01` do NOT** (`STIRFutureValue.py:100-110`):
```python
def _pv01(self, **kwargs): return sum(_package_pv01(pr, pk) for pr, pk in zip(...))   # unweighted
def _price(self, **kwargs): return sum(float(rw) * _package_price(pr, pk) for rw, pr, pk in zip(...))
def _npv(self, **kwargs):   total += float(rw) * price * pv01
```
- **Double-sign trap with `constrained_bpv` on CURVE. [verified]** `_solve_contracts_from_risk_weights` puts the sign into the *contracts* (`contracts_i = alpha * rw_i / pv01_i`), and `_price`/`_npv` then apply `rw_i` *again*. With `{"risk_weights": [1,-1], "constrained_leg_index": 0, "constrained_bpv": 10000.0}` you get **PV01 = 0.0** (unweighted +10000 and −10000 cancel) and **NPV = 1,926,950** instead of −0.375. Size curve legs with explicit `front_contracts`/`back_contracts` instead.
- `_build_outright` flips the risk weight negative if `contracts < 0` or `notional < 0` (`:270-271`).
- `is_ser` is auto-set when `"SER"` appears in the symbol (`STIRFutureQuery.py:104`) or `"SR1"`/`"SER"` in the pricer id (`RLSTIRFuturePricer.build_stirf:382`).
- `OPEN_INTEREST` returns a scalar for one pricer, else a `{id: oi}` dict, skipping pricers with no `openinterest` meta. **[verified]** the pack returned only 3 of 4 legs.
- Column naming: `col_name()` → `"{curve} {sym} OUTRIGHT PRICE"`, `"{curve} {front}v{back} CURVE RATE 1.0/-1.0"`, `"{sym} BASIS {fc}~{bc} {val}"`. `__neg__`, `__mul__`, `__rmul__`, `__truediv__` all fold into `risk_weight`, and `eval_expression` emits `` f"{risk_weight} * `{col}`" ``.

---

## 5. PositionHandler for STIR futures — yes

`C:/Users/chris/clee/ARBS/Query/STIRFutures/position_handler.py`, registered as a side effect of importing `Query/STIRFutures/adapter.py` (which `STIRFutureQuery` imports at module load):
```python
register_product("STIRFUTURE", STIRFutureProductAdapter)
from BT.position_handler import register_handler
from Query.STIRFutures.position_handler import STIRFutureHandler
register_handler("STIRFUTURE", STIRFutureHandler)
```

```python
class STIRFutureHandler(PositionHandler):
    """STIR futures: PnL($) = (ΔPrice / 0.01) * PV01_quote($/bp)."""
    name = "stir_future"
    def supports(self, query): return query.product == "STIRFUTURE"
```

**Marking to market** (`value_position`, `:65-80`):
```python
entry_price  = float((position.meta or {}).get("entry_price", 0.0))
pr = pricer_provider(position.source_query)
q  = resolve_query(position.source_query, timestamp=now, pricer_or_curve=pr)
current_price = self._price(position, pr, q)          # vmap.apply(value=q.default_mtm_value_id())
dprice        = float(current_price - entry_price)     # price points
pv01_quote    = self._pv01_quote(position, pr, q)      # vmap.apply(value=STIRFutureValue.PV01)
return float((dprice / 0.01) * pv01_quote)
```
- The mark value id is **PRICE**, not NPV — `STIRFutureQuery.default_mtm_value_id` (`:360`):
  ```python
  # return STIRFutureValue.NPV
  return STIRFutureValue.PRICE
  ```
- `build_position` stores `entry_price` in `meta` alongside `handler`, and returns a `ResolvedQueryPosition(package, weights, opened, source_query, meta)`.
- **PV01 is recomputed at every valuation** (not frozen at entry), and it is the **unweighted** sum from `_pv01`. Observed consequence of that convention: a 1-lot 2-leg curve marks with `pv01_quote = 50.0`, i.e. $50 per bp of spread move where the economic exposure is $25/bp. Same for a 4-leg pack: $100/bp. Stated as observed, not audited.
- `dprice / 0.01` converts price points to bp (0.01 price point = 1 bp).

---

## 6. Pack rate / matched-maturity forward swap rate — it exists

**Named: `IRSwapsTB.sfr_cvx_adj`** — `C:/Users/chris/clee/ARBS/TB/IRSwapsTB.py:1175`
```python
def sfr_cvx_adj(self, items: list[str], start: DateLike, end: DateLike, *,
                ignore_cache: bool = False, use_globex: bool = False) -> pd.DataFrame:
```
built on **`IRSwapValue.CVX_ADJ`** — `C:/Users/chris/clee/ARBS/Query/IRSwaps/IRSwapValue.py:176-227`. This is the pack-rate-vs-matched-maturity-swap convexity adjustment, verbatim:
```python
def _convexity_adjustment(self, **kwargs: Any) -> float:
    assert len(kwargs["package"]) == 1, "convexity not supported for packages!"
    assert "sfr" in kwargs, "must pass in SFR object"
    ...
    sfrs: List[rl.STIRFuture] = kwargs["sfr"]
    pack_tick: float = float(kwargs.get("pack_tick", 0.0025))  # ¼ tick
    do_round: bool   = bool(kwargs.get("round_pack_to_tick", True))

    leg_rates_pct = [_safe_fixed_rate_percent(s) for s in sfrs]
    leg_prices    = [100.0 - r for r in leg_rates_pct]
    avg_price     = float(np.mean(leg_prices))

    if do_round and len(leg_prices) >= 2:
        q = Decimal(str(pack_tick))
        pack_avg_price = float((Decimal(str(avg_price)) / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)
        pack_avg_price = float(Decimal(str(pack_avg_price)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    else:
        pack_avg_price = avg_price

    implied_fut_yield_pct = 100.0 - pack_avg_price
    swap_yield_pct = _as_percent(float(curve.fair_rate(swap_obj)))
    return (implied_fut_yield_pct - swap_yield_pct) * 100.0     # bp
```
So: **pack rate = 100 − (mean of leg prices, rounded to ¼ tick = 0.0025, ROUND_HALF_UP)**, and the matched-maturity leg is a single `rl.IRS` spanning the same IMM window as the pack. `sfr_cvx_adj` builds that swap as (`TB/IRSwapsTB.py:1521-1528`):
```python
eff_dt = rl.get_imm(code=anchor_code)                    # first contract in the pack
mat_dt = rl.next_imm(rl.get_imm(code=end_code))          # IMM after the last contract
q = IRSwapQuery(curve=curve, effective_date=eff_dt.date(), maturity_date=mat_dt.date(),
                structure=IRSwapStructure.OUTRIGHT, structure_kwargs={"bpv": 1},
                value=IRSwapValue.CVX_ADJ)
...
cvx = float(vmap.apply(value=IRSwapValue.CVX_ADJ, **{"sfr": rl_sfrs}))
```
Label grammar accepted by `items` (`TB/IRSwapsTB.py:1200-1230`):
```python
PACK_MAP = {"WHITES": (1,4), "REDS": (5,8), "GREENS": (9,12),
            "BLUES": (13,16), "GOLDS": (17,20), "SILVERS": (21,24)}
_IMM_PAT    = r"^[FGHJKMNQUVXZ]\d{2}$"    # single contract, e.g. "H26"
_CM_PAT     = r"^SFR(\d{1,2})$"           # constant-maturity rank
_BUNDLE_PAT = r"^BUNDLE(\d+)$"            # BUNDLEn → ranks 1+4(n-1) .. +16 (a 4-year bundle)
```
Output columns: `f"{curve} {label} {PACKS|BUNDLES|OUTRIGHT} CVX_ADJ"`. Legs are built with `build_rl_stirf(ticker, curve_id, price, use_globex)` from `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/stir_curve_building_utils.py:499`.

Two other matched-maturity-forward helpers, both usable standalone:
- `_quarterly_imm_forward_rate(curve, *, effective_date, maturity_date)` — `MDP/IRSwaps/BARCHART_STIRF/rl.py:812`. Prices an `rl.IRS` on the futures-built curve using `curve_def["ReferenceRate"]`, returning the IMM×IMM forward rate. Paired with `_build_quarterly_imm_forward_pairs(reference_date, count=12)` and `_format_quarterly_imm_pair_label` → `IMM_M26xIMM_U26`, and plotted by `_plot_first_twelve_quarterly_imm_forwards`.
- `sfr_to_imm_tenor(symbol)` — `RVUtils/SFRConvexScreener/_carry_roll.py:34`. `SFRZ26 → IMM_Z2026xIMM_H2027`, the token consumed by `IRSwapQuery(tenor=...)`.

There is **no** function literally named `pack_rate` in the repo; `IRSwapValue._convexity_adjustment` is where the pack rate is computed.

---

## Adjacent components worth knowing

- `RVUtils/SFRRVLab/` — SR3 futures-vs-listed-options premium-native backtest stack. `structures.py` defines `DOLLARS_PER_BP = 25.0`, `Leg(kind='option'|'future', symbol, weight, right, strike_price)`, `Structure`, `MarkBook(quotes, contracts)`, `mark_structure`, `structure_delta`, `hedge_each_contract`, `hedged_path`, `package_contracts`, `round_trip_cost_bp`. Futures mark at `price_bp = (100 - forward_rate) * 100`; options at listed settle premium. `engine.run_backtest(cfg)` / `grid_search`, `panels.load_panels(path)`, `signals.*`, `stats.deflated_for_grid/verdict`. Its design premise: *"put-call parity and the conversion arb pin each surface's risk-neutral mean to its own futures settle, so there is no mean-level RV between the two markets."*
- `RVUtils/STIRRVScreener/screener.py` — Astor-Ridge-style unified ranking across the Q12 strip. `STIRRVScreenerConfig(source="BARCHART_STIRF-RL", curve="USD-SOFR-1D-Q12STIRT", n_contracts=12, zscore_window=65, ...)`, `build_snapshot(as_of, config, *, curve_mdp, ts_builder, show_tqdm)` → `STIRRVSnapshot` with `.to_dataframe()`, `.top_trades(n)`, `.by_type(t)`. Structures: `STRIP, SPD_{3,6,9,12}M, FLY_{3,6,9,12}M, DFLY_{3,6}M, CF_{3,6}M`. Adds `compute_forward_consistency(rates)` and `compute_fly_fwd_consistency(fly_ts, rates)` (belly vs interpolated wings, normalized by 20d fly vol). Ranking metric is risk-adjusted roll (roll/vol). Rate panel comes from `BT/signals/sfr_cal_spread_rv.load_rate_panel`.
- `MDP/IRSwaps/BARCHART_STIRF/risk.py` — `build_delta_risk_ladder(...)`, `build_basis_risk_ladder(...)`.
- `MDP/IRSwaps/BARCHART_STIRF/rl.py` — `BARCHART_STIRF_CURVE(LayeredCacheMixin)`, the Q12/Q16/Q20 curve builder; `build_curve`, `_build_stirf_nodes` (nodes at central-bank meeting end-dates, extended by pricer maturities only when the CB schedule doesn't reach the horizon), 3-tier caching (in-memory LRU → per-timestamp diskcache → daily bundles → parquet curve store), `calibration_executor in {"thread","process"}`, `build_rl_stirf_turn_flies`.
- Other STIR screeners not requested but present: `RVUtils/SFRKinkFadeScreener/`, `RVUtils/SR3ZQDistributionScreener/`, `RVUtils/STIRAsymmetricScreener/`, plus signals `BT/signals/sfr_kink_fade.py`, `BT/signals/sfr_cal_spread_rv.py`.

Scratch scripts used for verification live in
`C:\Users\chris\AppData\Local\Temp\claude\C--Users-chris-clee\fd598297-c759-4904-8a06-2f2d2a03d199\scratchpad\` (`scan_stir_cache.py`, `scan_eod.py`, `scan_q12.py`, `scan_any.py`, `probe_mdp.py`, `probe_query{,2,3}.py`, `dump_entry.py`, `dump_day.py`, `probe_curvestore.py`).