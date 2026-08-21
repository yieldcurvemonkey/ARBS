<!-- Verbatim return of a preflight investigation agent, 2026-08-20/21.
     Measured on this machine; see the report's own probe list. Kept as
     research evidence, not as a design document. -->

# Preflight scout: the convexity-adjustment plumbing map

# SOFR Convexity-Adjustment Plumbing Map — ARBS-cvx2 (`feat/convexity-rv2` @ 61fa6d1a)

All paths absolute. Every number below is either MEASURED (command shown) or explicitly marked "not measured".

---

## 0. MEASURED: probe results

### 0.1 Where the caches live (0 network)
Script `.../scratchpad/probe_paths.py`, run as `ARBS_SUPABASE_ENABLED=0 C:/Users/chris/anaconda3/envs/stir/python.exe probe_paths.py` from `C:/Users/chris/clee/ARBS-cvx2`:

```
CurveStore base_dir : C:\Users\chris\AppData\Local\ARBS\Cache\curve_store      (ABSOLUTE - shared, warm)
diskcache dump      : C:\Users\chris\AppData\Local\ARBS\Cache\diskcache\dump   (ABSOLUTE - shared, warm)
ARBS_CACHE_DIR      : None
cwd                 : C:\Users\chris\clee\ARBS-cvx2
./data/ts exists    : C:\Users\chris\clee\ARBS-cvx2\data\ts   False            (cwd-RELATIVE - COLD in this worktree)
```
`ComputedTimeseriesStore(base_dir="./data/ts")` — `TB/IRSwapsTB.py:494,520-526`. **Landmine: the DuckDB computed-TS layer is cold in every worktree; only the CurveStore + diskcache carry over.**

### 0.2 CurveStore asset coverage (`ls` on `.../curve_store/raw/asset=*`)
```
USD-SOFR-1D-Q16STIRT       n=201    2024-01-02 .. 2026-08-20   (NO 2026-03 partitions)
USD-SOFR-1D-Q12STIRT       n=2065   2018-06-01 .. 2026-08-20
USD-SOFR-1D                n=1583   2020-06-22 .. 2026-08-19
USD-SOFR-1D-CITIVELOEXCEL  n=5511   2005-01-03 .. 2026-08-14   (EOD)
USD-SOFR-1D-CITIVELOEXCELMIN n=1543 2021-09-14 .. 2026-08-19   (MINUTE)
USD-SOFR-1D-RLBASIC        n=1421   2020-07-01 .. 2026-08-19
USD-SOFR-1D-CITIVELO       n=930    2023-01-02 .. 2026-07-24
USD-SOFR-1D-ERISLIVE       n=2      2026-07-23 .. 2026-07-24
```
2026-08-19 minute partition of `USD-SOFR-1D-CITIVELOEXCELMIN`: **1,077 rows, 05:00Z → 23:16Z**, columns `timestamp_utc, timestamp_local, trading_date, session_minute, curve_name, cfg_hash, reference_key, interpolation, source_variant, node_dates, discount_factors, spline_knots`.

### 0.3 The futures tape on disk (sqlite read of the 8 FanoutCache shards)
`STIRFuturePricer_Cache` = **22,604,514 entries**. Key grammar is `f"{ts_iso}-{ticker}-{src}"` (`MDP/STIRFutures/STIRFutureMDP.py:1072`). Two disjoint namespaces:

| src suffix | ticker form | resolution | newest key measured |
|---|---|---|---|
| `BARCHART_STIRF-RL` | `ZQH21`, `SR3H27` | EOD `17:00` NY + sporadic intraday (`2026-08-19T07:42:00-05:00`) | — |
| `BARCHART_TOS_LIVE_STIRF-RL` | `SR1/SR3/ZQ` Globex | **every minute** | `2026-08-20T21:00:00+00:00-SR3Z26-BARCHART_TOS_LIVE_STIRF-RL` |

`SR3H27` on 2026-08-19: **1,386 minute keys, 00:00 → 23:59 CT**. Counts: 2026-08-19 → 56,750 keys; 2026-08-20 → 39,449.

**Landmine (measured):** the minute SR3 tape is keyed under `BARCHART_TOS_LIVE_STIRF-RL`. `_get_cached_request_key` appends `src` (`STIRFutureMDP.py:1018,1072`), so an intraday request made under `source="BARCHART_STIRF-RL"` **cannot see it** and will fetch. My probe had to try both namespaces and fell through to the TOS-live one.

### 0.4 THE MEASUREMENT: an intraday CVX_ADJ, 0 network
Script `.../scratchpad/probe_cvx.py`. Swap leg from `IRSwapsMDP(source="CITIVELO_EXCEL")` under `SnapshotPolicy.strict(minutes=5, on_miss="raise")`; futures leg read straight out of the FanoutCache; value through **the identical inner loop as `sfr_cvx_adj`** (`IRSwapQuery` → `resolve_package(is_for_timeseries=True)` → `build_value_map` → `apply(CVX_ADJ, sfr=[...])`, i.e. `TB/IRSwapsTB.py:1555-1559`). All outbound HTTP monkeypatched to raise.

```
requested instant : 2026-08-19 15:00:00-04:00  (= 19:00Z)
curve build       : 0.470 s
curve meta        : mode=intraday  from_curve_store=True  asset=USD-SOFR-1D-CITIVELOEXCELMIN
                    timestamp=2026-08-19 15:00:00-04:00  reference_date=2026-08-19
front SR3         : U26 ; WHITES = [U26, Z26, H27, M27]
prices @ 2026-08-19T14:00:00-05:00 (BARCHART_TOS_LIVE_STIRF-RL)
   SR3U26 96.2175  SR3Z26 96.07  SR3H27 95.98  SR3M27 95.935

single front contract   swap 2026-09-16 -> 2026-12-16 : CVX_ADJ = -0.136742 bp
WHITES pack (default)   swap 2026-09-16 -> 2027-09-15 : CVX_ADJ = -5.813509 bp
WHITES pack (round_pack_to_tick=False)                : CVX_ADJ = -5.876009 bp
network attempts blocked: 0
```
`SnapshotPolicy.strict(on_miss="raise")` is the load-bearing proof that no live Excel/COM build ran — the HTTP blocker would not have caught COM.

**NOT reproduced:** the notebook's stored anchor `6.28942097885013` (2026-03-10 17:00 NY, `IMM_H29xIMM_Z29`, Q16STIRT vs ERIS-NOJUMPS). `USD-SOFR-1D-Q16STIRT` has **no 2026-03 partitions** (0.2 above), so that cell requires a live `BARCHART_STIRF-RL` build — the rule-3 fetch storm. Not run; call count not measured.

### 0.5 MEASURED DEFECT: CVX_ADJ's swap leg is ANNUAL/ANNUAL, and the compounding gap exceeds the CA
Script `.../scratchpad/probe_cvx2.py`, same 0-network setup, two independent instants:

```
INTRADAY 2026-08-19 15:00 ET      window 2026-09-16 -> 2027-09-15
  pack avg price 96.050625 -> rate 3.949375 %
  swap par (spec usd_irs, ANNUAL/ANNUAL) = 4.008135 %
  swap par (matched Q/Q)                 = 3.947470 %
  annual-vs-quarterly gap                = 6.0665 bp
  CVX_ADJ (shipped default)              = -5.813509 bp
  CA if the swap leg were Q/Q            = +0.190513 bp

EOD 2026-08-14 (date object)      window 2026-09-16 -> 2027-09-15
  annual-vs-quarterly gap                = 6.0472 bp
  CVX_ADJ (shipped default)              = -5.612387 bp
  CVX_ADJ (round_pack_to_tick=False)     = -5.487387 bp
  CA if the swap leg were Q/Q            = +0.559839 bp
network attempts blocked: 0
```
Mechanism, by code: `_convexity_adjustment` (`Query/IRSwaps/IRSwapValue.py:226-228`) calls `curve.fair_rate(swap_obj)` on a swap built by `RLIRSwapCurve.build_irswap` with `spec=curve_def["ReferenceRate"]` (`Query/IRSwaps/backends/rateslib/RLIRSwapCurve.py:307`), and `RATESLIB_CURVE_DEFINITIONS["USD-SOFR-1D"]["ReferenceRate"] == "usd_irs"` (`.../rl_curve_definitions_map.py:10`) — annual fixed for >2y. `RVUtils/ConvexityRV/strat2_sofr_convexity.py:618-656` documents exactly this and routes around it via `curve_ops.matched_forward_swap_rate(..., frequency="Q", leg2_frequency="Q")`; its docstring names "~3.8bp", I measure **6.05-6.07 bp** on this curve/window.

**Consequence:** the shipped `CVX_ADJ` *level* is dominated by a compounding artefact of the same sign every day (−5.8 bp reported vs +0.19 bp on identical inputs with a matched Q/Q leg). Day-on-day *changes* are far less affected. `IRSwapValue.CVX_ADJ` sits under a literal `# TODO` (`IRSwapValue.py:35`). **Any intraday extension must either fix the swap-leg frequency or inherit this knowingly.**

Also measured: `pack_tick` rounding moves the answer by **0.0625 bp** (intraday) / **0.125 bp** (EOD) — default is `True` in `IRSwapValue.py:195`, while `Strat2Config.round_pack_price_to_tick=False` (`strat2_sofr_convexity.py:408-411`) because unrounded tied out to Citi at corr 0.968.

### 0.6 Existing intraday IRSwapsTB evidence
`diskcache/dump/IRSwapsTB_v2_BARCHART_STIRF-RL` (len=179) holds rows like:
```
'v2|USD-SOFR-1D-Q12STIRT|1773336600000000000|b8ba4f9a...' ->
  (datetime(2026,3,12,7,30, tz=America/Chicago), 'USD-SOFR-1D fomc_dec26 OUTRIGHT RATE', 3.4165047825559314)
```
i.e. **30-minute intraday IRS values already flow through `IRSwapsTB` → `IRSwapsMDP(BARCHART_STIRF-RL)` today**, keyed by epoch-ns. `IRSwapsTB_v2_STIRCVX_EMPIRICAL` exists but is **len=0**.

---

## 1. `Query/IRSwaps/IRSwapValue.py`

### `IRSwapValue` enum — 11-47
`RATE, PV01, DV01, GAMMA_01, NPV, NOTIONAL, CARRY_BPS_RUNNING, ROLL_BPS_RUNNING, CARRY_AND_ROLL_BPS_RUNNING, SPREADOVER, MMSS, SPREADOVER_CARRY_ADJUSTED, MMSS_CARRY_ADJUSTED, SPREADOVER_ROLL_ADJUSTED, MMSS_ROLL_ADJUSTED, SPREADOVER_CR_ADJUSTED, MMSS_CR_ADJUSTED, PAR_PAR_ASW, TRUE_ASW, PROCEEDS_ASW, MARKET_ASW, CVX_ADJ (36), CVX_ADJ_EMPIRICAL (37), ROLL_ADJ_DIFFERENCE, ROLL_ADJ_RATIO, ROLL_ADJ_CALENDAR_WEIGHT, CITIVELO_SWAP_SPREAD`.
Only `RATE, PV01, DV01, GAMMA_01, NPV, NOTIONAL, CARRY*, ROLL*, CVX_ADJ, CVX_ADJ_EMPIRICAL, CITIVELO_SWAP_SPREAD` are wired in `_create_map` (120-134). `auto()` renumbering warning at 41-45 — **do not insert a new member mid-enum**.

### `_convexity_adjustment` — 176-228 (`CVX_ADJ`)
Reads from the merged kwargs dict (`BaseValueFunctionMap.apply` merges `common_kwargs` = `{curve, package, risk_weights}` with `**extra_kwargs`, `Query/Base/BaseValue.py:21-27`):

| kwarg | required | line | supplied by |
|---|---|---|---|
| `package` | yes, **len==1** | 177 | `q.resolve_package()` via `build_value_map` |
| `curve` | yes | 224 | `build_value_map(pricer_or_curve=...)` |
| `sfr` | **yes**, `List[rl.STIRFuture]` | 178, 184, 193 | **ONLY `TB/IRSwapsTB.py:1559` and `:1613`** |
| `pack_tick` | no, default `0.0025` | 194 | nobody |
| `round_pack_to_tick` | no, default `True` | 195 | nobody |
| `risk_weights` | present but **unused** | — | — |

Asserts: `len(package)==1` (177, "convexity not supported for packages!"), `"sfr" in kwargs` (178), `all(type(p)==rl.STIRFuture for p in sfr)` (184), `all(type(p)==rl.IRS for p in package)` (185 — **rateslib backend only**; a `QLIRSwapCurve` package raises). The two `ql.IMM.isIMMdate` asserts are commented out (182-183).

Body:
- `_as_percent` (197-199): `x*100 if abs(x)<1 else x` — a **magnitude heuristic**, not a unit contract. A fixed_rate of exactly 1.0% would be left as 1.0; sub-1% rates get scaled. Latent for a ZIRP/negative regime.
- `_safe_fixed_rate_percent` (201-209): `sfr.fixed_rate`, then `.real`, then `.iloc[-1]`.
- `leg_prices = [100 - r]`, `avg_price = mean` (211-213).
- Rounding (215-221): only when `len(leg_prices) >= 2`. `Decimal(avg/pack_tick).quantize(ROUND_HALF_UP)*pack_tick`, then quantize to `0.0001`. **A single-contract CA is never rounded**, regardless of the flag.
- Return (226-228): `(implied_fut_yield_pct - swap_yield_pct) * 100.0` → **bp, futures-minus-swap**.

### `_convexity_adjustment_empirical` — 360-375 (`CVX_ADJ_EMPIRICAL`)
Requires `curve.pricer_a` / `curve.pricer_b` (362-364, raises `TypeError` otherwise) — i.e. a `SpreadPricer`. Applies `_swap_structure_sign_mapper` to `risk_weights`, returns `sum(rw_i * (a.fair_rate - b.fair_rate)) * 10_000`. **No `sfr`, no futures, works for multi-leg packages.**

---

## 2. `Query/IRSwaps/IRSwapQuery.py`

Frozen dataclass fields (126-142): `structure, value, tenor, effective_date, maturity_date, is_mms, curve, structure_kwargs, value_kwargs, risk_weight, _curve_name`; inherits `market_request`, `mdp_time_key` (default `"timestamp"`, `Query/Base/BaseQuery.py:64`), `name/tags/meta`.

`structure_kwargs` recognised downstream (`IRSwapStructure.py:191-375`): `tenor, effective_date, maturity_date, fixed_rate, notional, bpv, is_for_timeseries, front_/belly_/back_ {tenor, effective_date, maturity_date, fixed_rate, notional}, tenors, risk_weights`. Aliased in `__post_init__` (150-160): `coupon→fixed_rate`, `front_coupon→front_fixed_rate`, `belly_coupon|mid_coupon→mid_fixed_rate`, `back_coupon→back_fixed_rate`. Structure auto-detected from slash count (231-256).

**The one existing intraday hook — 260-279.** The method the task called `is_cvx_empirical` is:
```python
def _uses_empirical_convexity_adjustment(self) -> bool:      # 260-261
    return self.value == IRSwapValue.CVX_ADJ_EMPIRICAL
def _structure_pricer_or_curve(self, pricer_or_curve):        # 263-266
    if self._uses_empirical_convexity_adjustment() and hasattr(pricer_or_curve, "pricer_a"):
        return pricer_or_curve.pricer_a
    return pricer_or_curve
def build_mdp_request(self, now):                             # 268-279
    if not self._uses_empirical_convexity_adjustment():
        return super().build_mdp_request(now)                 # <- DATE-TRUNCATES
    req = dict(self.market_request or {}); ...
    req[self.mdp_time_key] = now                              # <- FULL DATETIME
```
`BaseQuery.build_mdp_request` (`Query/Base/BaseQuery.py:69-85`) injects `_request_date(now)` → `now.date()` (12-21) unless `market_request[mdp_time_key] == "now"`, in which case `_request_datetime(now)` (24-33). **So today, `CVX_ADJ_EMPIRICAL` is the only value that gets an intraday instant through `build_mdp_request`, and `CVX_ADJ` is not.** Confirmed by `tests/test_stir_convexity_adjustment_mdp.py:213-215` (`assert request["timestamp"] == now`, a `datetime`).

Landmines in this file:
- **`_uses_empirical_convexity_adjustment` uses `==`**, so a *list-valued* `value` containing `CVX_ADJ_EMPIRICAL` compares `False`. The unwrap and the datetime only happen after `return_query()` expansion (299-323).
- **`return_query()` (305-320) rebuilds the query WITHOUT `value_kwargs`.** Any per-value kwargs on a list-valued query are silently dropped.
- `resolve_query` (397-553): at **514** and **547** it does `getattr(self.curve, "meta_data", {}).get("timestamp", ref_dt)` — but `self.curve` is `Optional[str]` (field at 134). The attribute never exists, so this **always** falls back to `ref_dt`. Dead code that looks like an instant-propagation mechanism and is not one.
- 540: `skw.setdefault("bpv", 1)` on any tenor-driven query.

---

## 3. `Query/IRSwaps/IRSwapStructure.py`

Full enum (39-43): **`OUTRIGHT, CURVE, FLY, SPREAD`**. Map (58-64): `SPREAD` aliases `_build_outright`.

**No structure builds a futures pack leg.** `_leg` (97-151) only ever calls `curve.build_irswap(...)`. The `IMM_` grammar is here: `_to_dt` (66-95) accepts `IMM_<n>` (ordinal from ref date) and `IMM_<code>` (e.g. `IMM_H29`, 4-digit year normalised at 85-86); `_leg` (112-118) splits `"IMM_H29xIMM_Z29"` on `x` into effective/maturity. That is the notebook's tenor form. A futures leg is therefore **structurally absent from the Query layer** — it exists only as the `sfr` kwarg injected at value-time.

---

## 4. `TB/IRSwapsTB.py` — the `CVX_ADJ` timeseries path (the pattern to reuse)

### Signature — 1252-1260
```python
def sfr_cvx_adj(self, items: list[str], start: DateLike, end: DateLike, *,
                ignore_cache: bool = False, use_globex: bool = False) -> pd.DataFrame
```
Not reachable from `get_timeseries`; a separate public method. Curve is **hard-coded** `"USD-SOFR-1D"` (1269). `leg_prefix = "/SR3" if use_globex else "SFR"` (1272).

### Symbol grammar — 1274-1345
| pattern | meaning | ranks |
|---|---|---|
| `^[FGHJKMNQUVXZ]\d{2}$` (`H29`) | absolute IMM contract | — |
| `^SFR(\d{1,2})$` (`SFR1`..`SFR24`) | constant-maturity rank | `[n]` |
| `WHITES/REDS/GREENS/BLUES/GOLDS/SILVERS` | 4-contract pack | `(1,4)…(21,24)` |
| `^BUNDLE(\d+)$` | 16-contract bundle | `1+4(b-1) … +15` |

`_structure_tag` (1305-1312) → `OUTRIGHT`/`PACKS`/`BUNDLES`; `_col_name` (1314-1315) = `f"{curve} {label} {tag} CVX_ADJ"`.

### Contract picking — 1317-1329
`_front_imm_code(d)` calls `get_short_end_curve_tickers(as_of=d, first_n_sr1=0, first_n_sr3=1, use_globex=...)` (`MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/tos.py:214-246` — **pure date math, offline-safe**, IMM-cutoff roll). `_imm_code_from_date_rank(d, n)` walks `rl.next_imm` n-1 times from the front. Swap window = `get_imm(codes[0])` → `next_imm(get_imm(codes[-1]))` (1390-1392, 1591-1592).

### Where the pricer comes from — 1507-1516
```python
curve_by_day: dict[datetime.date, object] = {}
def _get_curve_for_day(day: datetime.date):
    ch = self.mdp._get_curve(curve_name=curve, timestamp=day)   # 1514, day is a DATE
```
**Keyed by `datetime.date`, calls the private `_get_curve` directly** (bypasses `get_pricer`/`get_data`, so `request.pop` semantics and `bulk_get_data` batching are skipped).

### Prices — 1492-1498
`get_barchart_timeseries(start, end, interval=None, tickers=sorted(needed_tickers), use_globex=...)` — `interval=None` means **daily settles** (`stir_curve_building_utils.py:650+`, raw `requests`, **network, no cache**).

### The value call — 1547-1567 (IMM) / 1577-1620 (packs/bundles)
```python
pkg, rws = q.resolve_package(pricer_or_curve=ch, is_for_timeseries=True)
vmap     = q.build_value_map(pricer_or_curve=ch, package=pkg, risk_weights=rws)
_, rl_sfr = build_rl_stirf(ticker=leg, curve_id=ch.id(), price=float(price), use_globex=use_globex)
cvx = float(vmap.apply(value=IRSwapValue.CVX_ADJ, **{"sfr": [rl_sfr]}))     # 1559 / 1613
```
`build_rl_stirf` (`stir_curve_building_utils.py:499-529`): `rl.STIRFuture(effective=get_imm(code), termination=next_imm(...), spec="usd_stir", curves=curve_id, price=price)`. **Line 521: `**rate_fixings_kwargs(fixings)` is COMMENTED OUT for the SFR branch** (the SER branch at 511 keeps it) — irrelevant while only `fixed_rate` is read, but a trap for anyone who later prices the STIRFuture off the curve mid-accrual.

### Caching / dates
- Grid: `start/end.normalize()` then `ql_cal_date_range(ql.UnitedStates(GovernmentBond), start, end)` at default `freq="1b"` (1350-1352) → **business DAYS only**. (`BT/misc.py:9-34` does accept `freq`, `open_time`, `close_time`, `cme_session=True` — an intraday grid is available, just not used here.)
- Cache: the **legacy mapping/diskcache** (`_cache_key`, 1403, 1565, 1618), *not* `ComputedTimeseriesStore`. `_cache_key` (539-542) = `f"{_CACHE_VERSION}|{curve_name}|{_dt_to_epoch_ns(d)}|{_query_fingerprint(q)}"` — **already instant-resolution**.
- Write gate: `if not _is_today(ts)` (1564, 1617) with `_is_today` at 231-241 — an intraday series for *today* is computed but never persisted.
- Every per-date body is wrapped in bare `except Exception: pass` (1566-1567, 1619-1620) — failures are invisible holes.

### The generic route, for contrast — 792-868, 1130-1145, 170-204
- `get_timeseries(start, end, queries, *, n_jobs, ignore_cache, ignore_cache_miss, freq, timestamps, _prefetched_ts_rows_by_symbol)`.
- Intraday = `timestamps` given, or `start`/`end` both `datetime` **and** `freq` set (845). `start.tzinfo is not None` asserted (847); explicit `timestamps` must all be tz-aware or it raises (856-865) — **copy this contract verbatim**.
- 942: `if need_read_symbols and not use_intraday_cache:` — the batched DuckDB read is **skipped entirely for intraday**; only per-point reads remain.
- 1130-1145: builds `{"curve_name", "n_jobs", "timestamps": [ref_points], "ignore_cache"}` and calls `self.mdp.bulk_get_data(...)` with the **raw tz-aware ref points**. It never goes through `build_mdp_request`, so the date-truncation of §2 does not bite here.
- `_build_row_for_query` (170-204) merges `structure_kwargs` **and** `value_kwargs` into `vmap.apply` (176-185, 203). So `value_kwargs` *is* a working transport for extra CVX kwargs on the generic route — but not for `sfr`, which must be rebuilt per instant.
- `_query_fingerprint` (55-73) includes `value_kwargs` only when non-empty (back-compat). Adding a kwarg therefore silently changes the cache symbol.

---

## 5. `MDP/IRSwaps/IRSwapsMDP.py` — sources and the intraday parameter

**The intraday ask is `request["timestamp"]` typed as a `datetime.datetime`.** `get_data` (1984-1991) `pop`s `curve_name` and `timestamp` and forwards the rest as `kwargs` to `_get_curve(curve_name, timestamp, kwargs)` (1993-1995), typed `Union[datetime.datetime, datetime.date, Literal["live"]]`. `get_pricer` (1924-1928) just wraps `get_data`. Batch: `bulk_get_data(request)` with `request["timestamps"]` (3781-3800).

Source branches in `_get_curve`:

| source token | line | timestamp accepted | intraday? |
|---|---|---|---|
| `CME_NY_EOD_LIVE-QL_BASIC` | 2013 | `date` or `"live"` (assert 2021) | no |
| `CME_NY_EOD_LIVE-RL_BASIC` | 2056 | date | no |
| `ERIS_EOD_LIVE-RL_BASIC` | 2088 | date; CurveStore fast path 2107-2115 | no |
| `ERIS_EOD_LIVE-RL_BASIC-NOJUMPS` | 2136 | **silently `.date()`-truncates a datetime at 2142-2143**, then asserts date | **no — this is the notebook's `source_b`** |
| `ERIS_EOD_LIVE-QL_BASIC[-NOJUMPS]` | 2180 / 2241 | date | no |
| `SDR_INTRADAY-RL_*` (13 variants, incl. `..._SOFR_MT_Q12/Q16/MISC`, `..._STIR_Q12X8/Q13X10/Q12X9/Q12X12`, `..._MTV2_Q12X11`) | 2286-2604 | **asserts `type(timestamp) == datetime.datetime` or `"live"`** | **yes**, per-instant, cached in `_RLCurveCache` |
| `SDR_3PM_EOD-RL_USD_SOFR_MTV2_Q12X11` | 2605 | asserts `date` | no |
| `GSQUANT-RL*` | 2630 | date via `_to_gsquant_eod_date` | no |
| **`BARCHART_STIRF-RL`** | 2667-2709 | `_to_barchart_stirf_timestamp` **preserves a datetime** | **yes** (see below) |
| `CITIVELO` / `CITI_VELO` / `CITIVELOCITY` (old workbook) | 2711-2760 | datetime, `method="asof"` default (2718) | yes, from `USD-SOFR-1D-CITIVELO` store |
| `ERIS_LIVE_INTRADAY` | 2762-2773 | datetime, `method="asof"` | yes (store has **2 days**) |
| **`CITIVELO_EXCEL[-RL/-QL]`** (tokens at 38-41) | 2775-2782 → `_build_citivelo_excel_curve` 2787 | `"live"` / `datetime` / `date` | **yes** |

### `BARCHART_STIRF-RL` intraday, in code
- `_to_barchart_stirf_timestamp` (1748-1765): `"live"`→`"live"`; `pd.Timestamp`→`datetime`; **naive `datetime` localised to America/New_York, aware `datetime` returned unchanged**; a `date` → NY **17:00**. So a datetime survives end-to-end.
- `_validate_barchart_stirf_request_timestamp` (866-885) → `builder._trading_date_for_timestamp` (`BARCHART_STIRF/rl.py:2615-2620`: Chicago, `hour>=17` rolls to next day) → business-day check.
- Tier-0 CurveStore fast path (2678-2692) → `_load_barchart_stirf_curve_store_point` (1372-1402) → `store.read_raw_nodes(resolved_curve_name, timestamps_utc=[rl_timestamp])` — **exact-instant match**, no lag tolerance.
- `local_kwargs["ignore_cache_miss"]=True` → **returns `None` instead of building** (2693-2694). This is the safety gate for a bounded probe.
- Otherwise `builder.build_curve(...)` (`BARCHART_STIRF/rl.py:2799+`): `_normalize_timestamp` asserts tz-aware and not-in-future (2600-2603); daily bundle cache keyed by `ts.isoformat()`; bulk auto-prime per **CME session** with `cache_full_intraday_fetch=True`. **Cold instant = the rule-3 fetch storm.**

### `CITIVELO_EXCEL` intraday, in code (`_build_citivelo_excel_curve`, 2787-2964)
- Mode resolved by `CITIVELO_EXCEL/timestamps.resolve_request(timestamp)` (2855-2858), **never by `isinstance`** — the comment at 2846-2853 explains why (`pd.Timestamp ⊂ datetime ⊂ date`).
- `mode=="intraday"` → `_load_citivelo_excel_minute_store_point` (2866-2871 → 3163+), asset `f"{curve_name}-CITIVELOEXCELMIN"` (3207).
- `mode=="eod"` → `_load_citivelo_excel_curve_store_point` (2872-2877 → 2966-3013), asset from `warm.asset_for(curve_name)` = `-CITIVELOEXCEL`.
- Store eligibility (2841-2845): rl backend, and none of `force_refresh` / `ignore_cache` / `no_curve_store`.
- On a store miss it **falls through to a live Excel COM build** (2899-2912) unless `policy.on_miss=="raise"` (2879-2897).
- Minute selection window is `(0, -1, +1)` local days, **order is part of the contract** (3241-3260: both selection rules break ties positionally-first).

### `snapshot_policy` (`MDP/IRSwaps/CITIVELO_EXCEL/snapshot_policy.py`)
- Must be a `SnapshotPolicy` instance, one spelling only (`policy_from_kwargs` 287-305, `TypeError` otherwise).
- `SnapshotPolicy.legacy()` (120-122) = **nearest in EITHER direction, unbounded lag, `None` on miss** → this is the "no lag tolerance" memory line: the *default* has no tolerance *bound* at all and can serve a FUTURE snapshot.
- `SnapshotPolicy.strict(minutes=1.0, allow_future=False, on_miss="raise")` (125-131) = backward-only, bounded, loud.
- Guards: `_assert_policy_compatible` (3070-3095) rejects policy + store-bypass flags and policy + `ql` backend; `_assert_policy_mode` (3097-3135) refuses non-intraday modes under a policy. **Exact midnight resolves to EOD** (3101-3105, 3224-3238) — ask for `00:00:01` to mean the instant.
- Rejected early for the wrong source: `_get_curve` 2004-2011 raises if `snapshot_policy` is set and the source is not a `CITIVELO_EXCEL*` token.

---

## 6. `MDP/STIRFutures/STIRFutureMDP.py`

Sources accepted (1019-1021): `WEBULL_STIRF-RL`, `BARCHART_STIRF-RL`, `BARCHART_TOS_LIVE_STIRF-RL`, `SCHWAB_APP_STIRF-RL`. Anything else → `NotImplementedError`.

Request (`get_data`, 1329-1347): `{"symbols"|"tickers": [...], "timestamp": DateLike, "show_tqdm", "force_refresh", "cache_full_intraday_fetch"}`. Bulk: `get_bulk_data` / `bulk_get_data` with `"timestamps"` (1351-1465), `max_workers` default 8, optional `primed_session_data`.

Routing (1023-1027):
```python
want_eod              = isinstance(timestamp, date) and not isinstance(timestamp, datetime)
use_live              = src in {BARCHART_TOS_LIVE_STIRF-RL, SCHWAB_APP_STIRF-RL} and _should_use_live_quotes(timestamp)
read_cache            = not force_refresh and not use_live          # <-- live BYPASSES the cache
use_barchart_intraday = src != WEBULL and not want_eod and not use_live
floor_req_to_minute   = cache_full_intraday_fetch and use_barchart_intraday
```
`_should_use_live_quotes` (179-189): `"live"`, or a `date` equal to today, or a `datetime` **within ±15 minutes of now**. Fetch (1132-1149): live → `_fetch_tos_live_quotes`; else `_fetch_barchart_timeseries(interval = None if want_eod else 1)` — **1-minute bars for any historical intraday instant**. `_as_datetime` (89-101): naive → NY; a `date` → NY 17:00.

Cache key `f"{ts_key}-{ticker}-{src}"` (1072); `_cache_ts_iso` (1037-1045) converts to **UTC** when `use_barchart_intraday`, and floors to the minute when `floor_req_to_minute`. Probe keys are tried in order (1057-1066) `[requested, UTC-floored, UTC-exact, local-exact, local-floored]`. Cached value is the arg dict; `_build_pricer_from_args` (590-645) reads `price` and **fails closed if SOFR fixings are unavailable** (611-631).

---

## 7. `MDP/STIRConvexityAdjustment/`

`STIRConvexityAdjustmentMDP.py` (51 lines):
- `_cvx_request_splitter` (6-13): `curve_name_a = request.get("curve_name_a", f"{curve_name}-Q12STIRT")`, `curve_name_b = request.get("curve_name_b", curve_name)`, **both get the same `timestamp`**.
- Class (16-51): a `SpreadMDP` with `source="STIRCVX_EMPIRICAL"`, defaults `source_a="BARCHART_STIRF-RL"`, `source_b="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS"`. `_mdp_a`/`_mdp_b` injectable for tests.
- **Intraday-blocking fact:** `source_b`'s branch (`IRSwapsMDP.py:2136-2145`) silently `.date()`s the datetime. So `STIRConvexityAdjustmentMDP` with default sources gives you an **intraday leg A against an EOD leg B** — with no error and no metadata saying so.

`hw1f_model.py` (22 lines): `hw1f_convexity_adjustment(a, sigma, T1, T2) = (σ²/2a²)(1-e^{-aT1})(1-e^{-aT2})`, raises for `a<=0`, returns **rate terms (×10⁴ for bp)**. **Grep across the repo shows it is referenced only from `tests/test_stir_convexity_adjustment_mdp.py:17,27,32` — it is wired to nothing.** (`Query/Spreads/SpreadValue.py:12` declares `CVX_ADJ_HW1F` and `Query/Spreads/adapter.py:120` maps it to `self._cvx_adj_hw1f`; that is the Spreads product, not IRS.)

`tests/test_stir_convexity_adjustment_mdp.py`: HW1F unit tests (16-34); construction/`SpreadPricer` (111-127); **196-225** end-to-end `CVX_ADJ_EMPIRICAL` on `tenor="IMM_Z27xIMM_H28"` with `market_request={"curve_name_a","curve_name_b"}` and `assert request["timestamp"] == now` (a full `datetime`) → 20.0 bp from a 40bp-vs-38bp stub; **228-251** the same through `TB/TimeseriesBuilder.get_timeseries(mdps={"IRS": mdp})`.

`notebooks/pricers/sfr_convexity_pricer.ipynb` cell 1 (the only usage example): `STIRConvexityAdjustmentMDP(source_a="BARCHART_STIRF-RL", source_b="ERIS_EOD_LIVE-RL_BASIC-NOJUMPS")`, `eod = NY.localize(datetime(2026,3,10,17,0))`, `IRSwapQuery(tenor="IMM_H29xIMM_Z29", value=CVX_ADJ_EMPIRICAL, market_request={"curve_name_a":"USD-SOFR-1D-Q16STIRT","curve_name_b":"USD-SOFR-1D"})`, then `build_mdp_request` → `get_pricer` → `resolve_package` → `build_value_map` → `apply`. Stored output **6.28942097885013**. Cell 2 is empty.

---

## 8. Intraday verdict per source (the four asked for)

| source | intraday? | proof |
|---|---|---|
| **`CITIVELO_EXCEL`** | **YES — MEASURED** | probe_cvx.py: 2026-08-19 15:00 ET, `mode=intraday`, `from_curve_store=True`, `asset=USD-SOFR-1D-CITIVELOEXCELMIN`, 0.47 s, `SnapshotPolicy.strict(minutes=5, on_miss="raise")`, 0 HTTP. Code: `IRSwapsMDP.py:2846-2871` → `3163-3268`. Warm to 2026-08-19, 1,077 min/day. |
| **Citi minute store** | same thing — the `-CITIVELOEXCELMIN` asset **is** the CITIVELO_EXCEL intraday path. Selection rules in `snapshot_policy.select_snapshot`; default policy is nearest-either-direction/unbounded. | as above |
| **`BARCHART_STIRF-RL`** | **YES by code**, not measured end-to-end here | datetime preserved (`IRSwapsMDP.py:1748-1765`); exact-instant store read (`1372-1402`); per-timestamp curve cache + session priming (`BARCHART_STIRF/rl.py:2799+`). Corroborated: `IRSwapsTB_v2_BARCHART_STIRF-RL` holds **30-min intraday RATE rows on 2026-03-12** vs `USD-SOFR-1D-Q12STIRT`; the pricer cache holds a `2026-08-19T07:42:00-05:00` SR3 snapshot. **Warm instant = 0 network; cold instant = the rule-3 storm.** |
| **`BARCHART_TOS_LIVE_STIRF-RL`** (futures only) | **YES for the futures leg, MEASURED as warm** | `_should_use_live_quotes` ±15 min (`STIRFutureMDP.py:179-189`); outside that window it serves barchart **1-minute bars** (`1137`). Cache holds every minute of 2026-08-19 for SR1/SR3/ZQ, newest key `2026-08-20T21:00:00+00:00`. **It is not a curve source** — no `IRSwapsMDP` branch reads it. |
| (bonus) `SDR_INTRADAY-RL_*` | YES, `assert type(timestamp)==datetime` | `IRSwapsMDP.py:2286-2604` |
| (bonus) `ERIS_LIVE_INTRADAY` | YES, but store has **2 days** | `2762-2773` |
| (bonus) `ERIS_EOD_LIVE-RL_BASIC-NOJUMPS` | **NO — silently truncates** | `2142-2143` |

---

## 9. DESIGN

### (i) An intraday-capable SFR CA pricer object
**New file: `RVUtils/ConvexityRV/ca_pricer.py`** (or `MDP/STIRConvexityAdjustment/sfr_ca_pricer.py` if it should be MDP-shaped). One object that resolves *both* legs at one instant and returns a CA, so the instant is stated once.

```python
@dataclass(frozen=True)
class SFRCAConfig:
    curve_name: str = "USD-SOFR-1D"
    swap_source: str = "CITIVELO_EXCEL"          # or BARCHART_STIRF-RL
    futures_source: str = "BARCHART_TOS_LIVE_STIRF-RL"
    snapshot_policy: SnapshotPolicy = SnapshotPolicy.strict(minutes=1, on_miss="raise")
    use_globex: bool = True
    pack_tick: float = 0.0025
    round_pack_to_tick: bool = False             # match strat2, NOT IRSwapValue's default
    swap_leg_frequency: str | None = "Q"         # None = spec default (today's behaviour)
    max_futures_lag: timedelta = timedelta(minutes=1)

class SFRConvexityPricer:
    def __init__(self, cfg): ...
    def at(self, instant: datetime, label: str) -> CAResult: ...
    def series(self, instants: Sequence[datetime], labels) -> pd.DataFrame: ...
```
Required behaviour:
1. **One tz-aware instant, refused if naive** — reuse the wording at `TB/IRSwapsTB.py:856-865`.
2. **Swap leg**: `IRSwapsMDP(source=cfg.swap_source).get_pricer({"curve_name", "timestamp": instant, "snapshot_policy": cfg.snapshot_policy})`. Read back `curve.meta_data["timestamp"]` and record the **signed lag** on the result. For `BARCHART_STIRF-RL` there is no policy object; gate with `store.read_raw_nodes(..., timestamps_utc=[ts])` / `ignore_cache_miss=True` before ever letting `build_curve` run.
3. **Futures leg**: `STIRFutureMDP(source=cfg.futures_source).get_pricer({"symbols": [...], "timestamp": instant, "cache_full_intraday_fetch": True})`. Record each leg's served stamp and reject if `|requested - served| > cfg.max_futures_lag`. **Do not assume `BARCHART_STIRF-RL` sees the minute tape — it does not (§0.3).**
4. **Contract resolution** at the instant's *local trading date* (`_trading_date_for_timestamp`, Chicago 17:00 roll), via `get_short_end_curve_tickers` (offline) + `rl.get_imm/next_imm` — lift `_imm_code_from_date_rank`/`_ranks_for_label` out of `sfr_cvx_adj` into a shared module so the TB and the pricer cannot drift.
5. **Value**: build one `rl.STIRFuture` per contract with `build_rl_stirf(curve_id=curve.id(), price=...)`, then `vmap.apply(CVX_ADJ, sfr=[...], pack_tick=..., round_pack_to_tick=...)`.
6. **Return a `CAResult`**, not a float: `ca_bp, swap_rate_pct, pack_price, pack_rate_pct, swap_leg_frequency, curve_instant, curve_lag_s, futures_instant, futures_lag_s, contracts, n_priced, rounded`. The single biggest weakness of the current path is that a float carries no evidence of *which two instants* it compared.

### (ii) `IRSwapQuery` / `IRSwapValue.CVX_ADJ` support for an intraday timestamp
Three edits, all small:

**(a) `Query/IRSwaps/IRSwapQuery.py:260-279` — generalise the exemption.**
```python
_INTRADAY_INSTANT_VALUES = frozenset({IRSwapValue.CVX_ADJ_EMPIRICAL, IRSwapValue.CVX_ADJ})

def _wants_instant_mdp_request(self) -> bool:
    vals = self.value if isinstance(self.value, (list, tuple)) else [self.value]
    return any(v in _INTRADAY_INSTANT_VALUES for v in vals)
```
Use it in `build_mdp_request` **and** keep `_uses_empirical_convexity_adjustment` separate for the `pricer_a` unwrap (they answer different questions). Fixing the `==` to a membership test also repairs the list-valued-`value` case.

**(b) `Query/IRSwaps/IRSwapValue.py:176-228` — make the swap leg explicit and stop the 6 bp bleed.**
Accept two new optional kwargs, threaded through `value_kwargs` (which `_build_row_for_query` already forwards, `TB/IRSwapsTB.py:182-185,203`):
- `swap_frequency` / `swap_leg2_frequency` (default `None` = today's `usd_irs` behaviour, so no shipped number moves silently). When set, price the swap through `RVUtils/ConvexityRV/curve_ops.matched_forward_swap_rate(curve, eff, mat, frequency=..., leg2_frequency=...)` instead of `curve.fair_rate`.
- Emit the chosen frequency into the result metadata / column name so a Q/Q series and an annual series can never be concatenated.

Also worth doing while in there: replace the `_as_percent` magnitude heuristic (197-199) with an explicit unit contract, and make `round_pack_to_tick` apply to the 1-contract case too (or document that it cannot).

**(c) `sfr` transport.** `sfr` must stay a runtime object — an `rl.STIRFuture` is bound to a curve id and a price. Do **not** try to serialise it into `value_kwargs` (it would poison `_query_fingerprint`, `TB/IRSwapsTB.py:55-73`). Instead add a *declarative* spec that the TB/pricer resolves:
```python
value_kwargs={"sfr_spec": {"label": "WHITES", "use_globex": True, "source": "BARCHART_TOS_LIVE_STIRF-RL"}}
```
and have the caller (TB route, §iii) turn `sfr_spec` → `sfr` before `apply`. The spec is JSON-canonicalisable, so the fingerprint stays stable and correct.

### (iii) A TimeseriesBuilder path producing an intraday CA series
**New method `TB/IRSwapsTB.sfr_cvx_adj_intraday(...)`, modelled on `sfr_cvx_adj` (1252-1635), not a modification of it** — the EOD method has 179 cached rows' worth of key/column semantics to preserve.

```python
def sfr_cvx_adj_intraday(self, items, start, end, *, freq="1T", timestamps=None,
                         curve="USD-SOFR-1D", use_globex=True,
                         futures_source="BARCHART_TOS_LIVE_STIRF-RL",
                         snapshot_policy=SnapshotPolicy.strict(minutes=1),
                         swap_frequency="Q", round_pack_to_tick=False,
                         ignore_cache=False) -> pd.DataFrame
```
Point-by-point deltas from the EOD method:

1. **Grid** — replace `start.normalize()` + `ql_cal_date_range(..., freq="1b")` (1350-1352) with `self._build_reference_points(start, end, freq=freq, timestamps=timestamps)` (`TB/BaseTimeseriesTB.py:54-67`), plus the tz-aware assertion and the naive-timestamp refusal copied from `TB/IRSwapsTB.py:845-865`. If a session-bounded grid is wanted, `ql_cal_date_range` already supports `open_time`/`close_time`/`cme_session=True` (`BT/misc.py:16-23`).
2. **Curve cache** — `curve_by_day: dict[date, ...]` (1507-1516) becomes `curve_by_instant: dict[datetime, ...]`, and `self.mdp._get_curve(curve_name, timestamp=day)` becomes `self.mdp.get_pricer({"curve_name": curve, "timestamp": instant, "snapshot_policy": policy})`. Better: hoist to one `self.mdp.bulk_get_data({"curve_name": curve, "timestamps": instants})` per chunk, the way the generic route does at 1130-1145 — one call instead of N.
3. **Prices** — `get_barchart_timeseries(interval=None)` (1492-1498) is EOD-only. Replace with `STIRFutureMDP(source=futures_source).bulk_get_data(timestamps=instants, symbols=tickers, cache_full_intraday_fetch=True)`, which reads the warm minute cache. Keep a per-instant `price_by(instant, ticker)` map and **drop the point** (recording why) when any pack leg is missing or stale, rather than `except: pass`.
4. **Contract set** — recompute per *instant's trading date* (Chicago 17:00 roll), not per calendar date, so the 17:00-24:00 CT session gets the next day's front contract. The EOD method's `_imm_code_from_date_rank(ts.date(), r)` (1390, 1580) would be off by one contract for the evening session on a roll day.
5. **Caching** — `_cache_key` (539-542) is already epoch-ns and needs no change. The `_is_today` write gate (1564, 1617) must go: for an intraday series *every* point on the current day is skipped, which is exactly the data an intraday run is producing. Replace with "write if the served instant is more than N minutes old". Consider moving to `self._computed_ts_store.append_many_rows(..., intraday=True)` (the pattern at 1240-1242) — but note `./data/ts` is cwd-relative and cold in a worktree (§0.1).
6. **Column names** — `_col_name` (1314-1315) must encode the swap-leg frequency and the futures source, e.g. `f"{curve} {label} {tag} CVX_ADJ Q/Q"`, so an annual-leg and a Q/Q-leg series cannot silently share a column.
7. **Result rows** must carry the two lags. Two columns (`curve_lag_s`, `futures_lag_s`) alongside the value, or the CA is unfalsifiable.

---

## 10. Landmine list (every one measured or line-cited)

**Correctness of the number**
1. **`CVX_ADJ`'s swap leg is annual/annual `usd_irs`; the annual-vs-quarterly gap is 6.05-6.07 bp, larger than the CA itself.** MEASURED (§0.5). `IRSwapValue.py:226-228` + `RLIRSwapCurve.py:307` + `rl_curve_definitions_map.py:10`; `strat2_sofr_convexity.py:618-656` routes around it. Shipped −5.81 bp vs Q/Q-matched +0.19 bp on identical inputs.
2. `pack_tick` rounding defaults **`True`** (`IRSwapValue.py:195`) but `Strat2Config.round_pack_price_to_tick=False` (`strat2:408-411`, "unrounded tied out to Citi at corr 0.968"). MEASURED difference: 0.0625 bp intraday, 0.125 bp EOD.
3. Rounding only fires for `len(leg_prices) >= 2` (`IRSwapValue.py:217`) — a 1-contract CA is never rounded regardless of the flag.
4. `_as_percent` (`IRSwapValue.py:197-199`) is a `abs(x) < 1` magnitude heuristic, not a unit contract.
5. `CVX_ADJ` compares an **arithmetic mean of futures rates** to a **single par swap over the whole window**. That is not a like-for-like even after fixing the frequency; strat2 acknowledges the same construction.
6. `IRSwapValue.CVX_ADJ` and `CVX_ADJ_EMPIRICAL` are both filed under a literal `# TODO` (`IRSwapValue.py:35`).
7. `MDP/STIRConvexityAdjustment/hw1f_model.py` is **wired to nothing** — referenced only by tests.

**Time / instant handling**
8. `IRSwapQuery.build_mdp_request` **date-truncates** for every value except `CVX_ADJ_EMPIRICAL` (`IRSwapQuery.py:268-279`; `BaseQuery.py:12-21,69-85`). `CVX_ADJ` therefore cannot get an instant through that route today.
9. That exemption is `self.value == ...` — a **list-valued `value`** containing `CVX_ADJ_EMPIRICAL` misses it until `return_query()` expands (`IRSwapQuery.py:299-323`).
10. `STIRConvexityAdjustmentMDP`'s default `source_b` (`ERIS_EOD_LIVE-RL_BASIC-NOJUMPS`) **silently `.date()`s a datetime** (`IRSwapsMDP.py:2142-2143`). An "intraday" empirical CA is leg A intraday vs leg B at the close, with no warning.
11. **Exact midnight resolves to END OF DAY**, not to the instant (`IRSwapsMDP.py:3101-3105, 3224-3238`). Ask for `00:00:01`.
12. `SnapshotPolicy.legacy()` — the default — is **nearest in either direction, unbounded**, so it can serve a curve stamped *after* the request (`snapshot_policy.py:93-106,120-122`). Research callers must pass `.strict(...)`.
13. The minute-store day window is `(0, -1, +1)` and **the order is load-bearing** (ties break positionally-first, `IRSwapsMDP.py:3241-3260`).
14. `IRSwapsTB.get_timeseries` **refuses naive datetimes** in `timestamps=` (856-865) but the underlying MDPs localise naive to NY (`IRSwapsMDP.py:1758-1759`, `STIRFutureMDP.py:92-95`) — two different contracts, so never bypass the TB gate.
15. `IRSwapQuery.resolve_query` lines **514 and 547** read `getattr(self.curve, "meta_data", {})` where `self.curve` is a **string**. Always falls back to `ref_dt`. Dead code that reads as instant propagation.
16. `sfr_cvx_adj`'s contract picking uses the **calendar** date (`_imm_code_from_date_rank(ts.date(), r)`, 1390/1580) while barchart's session rolls at **17:00 Chicago** (`BARCHART_STIRF/rl.py:2615-2620`). Off by one contract for the evening session on roll days.

**Data plumbing / caches**
17. **The minute SR3 tape is keyed under `BARCHART_TOS_LIVE_STIRF-RL` and is invisible to `BARCHART_STIRF-RL` lookups** (`STIRFutureMDP.py:1018,1072`). MEASURED (§0.3): my probe had to fall through namespaces.
18. `read_cache = not force_refresh and not use_live` (`STIRFutureMDP.py:1025`) — a request within ±15 min of now **always bypasses the cache and fetches**.
19. `get_barchart_timeseries(interval=None)` (`IRSwapsTB.py:1495`) is **daily settles and does no caching** — it is raw `requests`. This is the network stage of `sfr_cvx_adj`.
20. `IRSwapsTB.sfr_cvx_adj` writes only when `not _is_today(ts)` (1564, 1617) — an intraday run for today persists nothing.
21. Intraday **skips the batched DuckDB read** entirely (`IRSwapsTB.py:942`), so intraday is per-point I/O.
22. `ComputedTimeseriesStore(base_dir="./data/ts")` is **cwd-relative** (`IRSwapsTB.py:494`) → cold in every worktree; `CurveStore` and diskcache are absolute and shared. MEASURED (§0.1).
23. `_query_fingerprint` includes `value_kwargs` **only when non-empty** (`IRSwapsTB.py:68-71`) — adding a kwarg changes the cache symbol.
24. `return_query()` **drops `value_kwargs`** (`IRSwapQuery.py:305-320`).
25. Every per-date body in `sfr_cvx_adj` is `except Exception: pass` (1566-1567, 1619-1620); missing points make the frame **shorter, with no NaN** (same contract noted at `IRSwapsTB.py:1163-1166`).
26. `build_rl_stirf`'s SFR branch has `**rate_fixings_kwargs(fixings)` **commented out** (`stir_curve_building_utils.py:521`) — harmless while only `fixed_rate` is read, fatal if anyone prices that STIRFuture mid-accrual.
27. `CVX_ADJ` asserts `rl.IRS`/`rl.STIRFuture` (`IRSwapValue.py:184-185`) — **QuantLib-backed curves (`CITIVELO_EXCEL-QL`, `CME_NY_EOD_LIVE-QL_BASIC`) cannot be used at all.**
28. `snapshot_policy` + `force_refresh`/`ignore_cache`/`no_curve_store` is a hard `ValueError`, and `snapshot_policy` + a ql backend likewise (`IRSwapsMDP.py:3070-3095`).
29. A cold `BARCHART_STIRF-RL` instant runs `builder.build_curve` → per-session priming of 13-20 instruments = the rule-3 fetch storm. Gate with `ignore_cache_miss=True` (returns `None`, `IRSwapsMDP.py:2693-2694`) or a direct `store.read_raw_nodes` probe (`1394-1398`).
30. `USD-SOFR-1D-Q16STIRT` has **only 201 warmed days** and **no 2026-03 partitions** — the notebook's `6.28942097885013` cannot be re-derived offline. `USD-SOFR-1D-ERISLIVE` has **2 days**. MEASURED (§0.2).

---

## 11. Files to touch

| file | what |
|---|---|
| `C:/Users/chris/clee/ARBS-cvx2/Query/IRSwaps/IRSwapValue.py` | `_convexity_adjustment` (176-228): add `swap_frequency`/`swap_leg2_frequency`; fix `_as_percent`; make rounding well-defined for 1 contract |
| `C:/Users/chris/clee/ARBS-cvx2/Query/IRSwaps/IRSwapQuery.py` | 260-279: generalise `_uses_empirical_convexity_adjustment` → `_wants_instant_mdp_request` over a value SET; 305-320: carry `value_kwargs` through `return_query`; 514/547: delete or fix the dead `self.curve.meta_data` lookup |
| `C:/Users/chris/clee/ARBS-cvx2/TB/IRSwapsTB.py` | new `sfr_cvx_adj_intraday` beside 1252-1635; hoist the symbol grammar (1274-1345) into a shared module; per-instant curve cache; `STIRFutureMDP` prices instead of `get_barchart_timeseries`; drop the `_is_today` write gate for intraday |
| **new** `RVUtils/ConvexityRV/ca_pricer.py` | `SFRConvexityPricer` / `SFRCAConfig` / `CAResult` (§9(i)) |
| `C:/Users/chris/clee/ARBS-cvx2/MDP/STIRConvexityAdjustment/STIRConvexityAdjustmentMDP.py` | refuse (or loudly annotate) an intraday timestamp when a leg's source is EOD-only; default `source_b` to something intraday-capable |
| `C:/Users/chris/clee/ARBS-cvx2/MDP/IRSwaps/IRSwapsMDP.py` | 2136-2145: raise instead of silently `.date()`-truncating for `ERIS_*-NOJUMPS` |
| `C:/Users/chris/clee/ARBS-cvx2/tests/test_stir_convexity_adjustment_mdp.py` | add: intraday instant survives `build_mdp_request` for `CVX_ADJ`; `swap_frequency="Q"` changes the number by ~6 bp on a fixed stub; a naive datetime is refused |

Scratch probes (kept, all 0-network): `C:/Users/chris/AppData/Local/Temp/claude/C--Users-chris-clee-ARBS/f3c71cad-b780-41e9-8455-68991655ae55/scratchpad/{probe_paths,probe_cache2,probe_cache3,probe_keys,probe_keys2,probe_avail,probe_cvx,probe_cvx2}.py`
