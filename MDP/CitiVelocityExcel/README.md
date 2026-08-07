# Citi Velocity as an ARBS market-data source

Drives the Citi Velocity **Excel add-in** over COM to fetch the whole `RATES.*`
namespace, and builds swap curves, swaption cubes, bonds, inflation curves and
cross-currency curves from those quotes in **both rateslib and QuantLib**.

Distinct from the existing `citivelo` source in `MDP/IRSwaps/IRSwapsMDP.py`, which
builds one rateslib USD-SOFR curve from a hand-saved workbook and is pinned by 930
warmed CurveStore partitions and the dealer-ladder study. Nothing here changes it.
The new MDP source string is **`citivelo_excel`**.

---

## Source schema

| Layer | Module | What it does |
|---|---|---|
| Transport | `com_client.py` | Attaches to a running, signed-in Excel; writes `CV*` formulas into a scratch workbook; polls; reads the measured block extent |
| Parsing | `block_parser.py` | Pure parsers for the blocks the add-in writes. No COM, fully testable |
| Vocabulary | `catalog.py`, `tags.py` | The harvested `RATES.*` grammar (2,517 nodes, 33 families) and typed builders derived from it |
| Cache | `cache.py` | Incremental parquet store keyed `(tag, freq, price_point)`; serves cached rows, fetches only the missing span |
| Quotes | `quotes.py` | Cached-then-live tag reader. A fully-cached read never touches Excel |
| MDP | `source.py`, `mdp.py`, `pricer.py` | `citivelo_excel` source (frames) and `CitiVelocityMDP.get_pricer` (a snapshot that builds models on demand) |
| Analytics | `curves/ vol/ bonds/ inflation/ xccy/ options/` | rateslib + QuantLib construction from Citi quotes |
| Query | `Query/CitiVelocity/` | Product `CITIVELO`: outright / curve / fly / spread / condor over tags |
| Timeseries | `TB/CitiVelocityTB.py` | Tag fast path with a proven-equivalent repricing fallback |
| Test support | `testing.py` | A faithful fake of the Excel COM surface |

### Coverage

| Family | Tags | Built into |
|---|---|---|
| `RATES.OIS.<ccy>_<idx>.{PAR,FWD,SWAP_SPREAD,CURVES,BFLY,ROLL_CARRY}` | 20 RFR curves x 44 tenors | rateslib `Curve`+`Solver`, QuantLib `OISRateHelper` bootstrap |
| `RATES.VOL.<ccy>.{ATM_RFR,OTM_RFR,REALIZED_RFR,VOL_RATIO_RFR}` | expiry x tenor x strike offset | **one** `CitiVeloSwaptionCube` over four backends - `rl.IRSplineCube`+`IRSCall`, `PPSplineF64`+Bachelier, `ql.Swaption`+`BachelierSwaptionEngine`, and the QuantLib SABR variant - reachable as `IRSwaptionMDP(source="CITIVELO-QL"\|"CITIVELO-RL")` |
| `RATES.BOND.<ISIN>.<value>` + `CVCURVEBOND` universe | 2,162 ISINs, 16,288 validated tags | rateslib + QuantLib `FixedRateBond`, `BondFunctions`, par-par ASW |
| `RATES.INFLATION.{INDEX,SWAP,INF_CARRY,SWAPTION}` | 17 indices | rateslib index `Curve`+`ZCIS`, QuantLib `PiecewiseZeroInflation` |
| `RATES.XCCY_OIS_SWAP.<a>.<b>.<fwd>.<tenor>.<leg>.BASIS_SPREAD` | 1,097 validated | rateslib `XCS`+`FXForwards` collateral solve; QuantLib explicit cashflows |
| `RATES.SPREAD_OPTIONS`, `RATES.MIDCURVES` | single-look CMS spread, midcurves | closed-form Bachelier + Hagan convexity |
| `RATES.SWAP_LIBOR` | 46 currencies | quotes only - grammar confirmed 2026-08-05, **no local repricing** (IBOR legs) |

---

## How the artefact is built

1. **Connect.** `CitiVelocityExcelClient.connect()` enumerates the Running Object
   Table, probes each candidate with `=CVTODAY()` and keeps the first that answers.
   It never spawns Excel.
2. **Write.** Each request gets an anchor below every live region, with a wide gap.
3. **Poll.** The anchor is read until it stops being a pending sentinel.
4. **Measure.** The extent comes from the add-in's own `CvFunction_<r>_<c>` defined
   name; `CurrentRegion` is only a fallback.
5. **Parse.** Header located by content, dates coerced from serial *or* datetime,
   `Bad tag:` mapped to a per-tag failure.
6. **Cache.** Merged into parquet keyed `(tag, freq, price_point)`.
7. **Build.** Curves, cubes and bonds are stripped locally from those quotes.

---

## Usage

```python
from MDP.CitiVelocityExcel import CitiVelocityExcelClient
from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.mdp import CitiVelocityMDP
from Query.CitiVelocity import CitiVeloQuery, CitiVeloStructure, CitiVeloValue
from TB.CitiVelocityTB import CitiVelocityTB

# --- raw series -----------------------------------------------------------
with CitiVelocityExcelClient.connect() as client:
    grid = client.fetch_frame(T.ois_par_grid("EUR_EUROSTR"), "DAILY", period="1Y")
    ust = client.fetch_frame([T.tsy_otr("10Y")], "MI01", period="2D")

# --- structures through the timeseries builder ----------------------------
tb = CitiVelocityTB(CitiVelocityMDP())
frame = tb.get_timeseries(
    date(2024, 1, 1), date(2026, 8, 1),
    [
        CitiVeloQuery(citi_index="USD_SOFR", tenor="10Y"),
        CitiVeloQuery(citi_index="USD_SOFR", structure=CitiVeloStructure.FLY,
                      structure_kwargs={"front_tenor": "2Y", "belly_tenor": "5Y",
                                        "back_tenor": "10Y"}),
        CitiVeloQuery(currency="USD", expiry="1Y", tenor="10Y", family="VOL"),
    ],
)

# --- a locally-stripped curve, and the proof it agrees with the quote -----
pricer = CitiVelocityMDP().get_pricer({"timestamp": "live", "citi_index": "USD_SOFR"})
rlc = pricer.rl_curve()          # rateslib Curve + Solver
qlc = pricer.ql_curve()          # QuantLib bootstrapped term structure

tb.assert_fast_path_matches(
    date(2026, 7, 1), date(2026, 8, 1),
    [CitiVeloQuery(citi_index="USD_SOFR", tenor="10Y")],
    model_value=CitiVeloValue.RL_RATE, tol=0.01,
)

# --- the swaption cube: ONE object, ATM and every OTM offset --------------
cube = pricer.swaption_cube("USD")                 # rateslib native by default
k = cube.forward("1Y", "10Y") + 25e-4              # Citi's +25bp node
cube.normal_vol("1Y", "10Y", offset_bp=25)         # 84.5553 bp
cube.price("1Y", "10Y", k, right="payer")          # 1,767,324
cube.with_backend("ql").price("1Y", "10Y", k)      # 1,767,324 - same object, QuantLib

# --- or through the repo's own swaption product ---------------------------
from MDP.IRSwaptions.IRSwaptionMDP import IRSwaptionMDP
from Query.IRSwaptions import IRSwaptionQuery, IRSwaptionStructure, IRSwaptionValue

swpt = IRSwaptionMDP(source="CITIVELO-QL", curve_source="ERIS_EOD_LIVE-QL_BASIC")
ctx = swpt.get_pricer({"curve_name": "USD-SOFR-1D", "timestamp": date(2026, 8, 6)})
q = IRSwaptionQuery(curve="USD-SOFR-1D", shorthand="1Yx10Y", strike="ATMF+25",
                    structure=IRSwaptionStructure.PAYER, value=IRSwaptionValue.NVOL)
# ... resolve_query / resolve_package / build_value_map -> 84.55 bp
```

---

## The one swaption cube

`MDP/CitiVelocityExcel/vol/swaption_cube.py` — **`CitiVeloSwaptionCube`**. One
object, one API, ATM **and every OTM offset**, over four backends and two
libraries.

| backend | what it is | what only it gives you |
|---|---|---|
| `rl-native` (default) | `rl.IRSplineCube` + `rl.IRSCall` | AD risk back to the curve and vol nodes; calibratable in a `rateslib.Solver` |
| `rl-hand` | `PPSplineF64` + `Query.Base.bachelier` | works on every supported rateslib, including 2.1.x, which has no IR vol at all |
| `ql` | `ql.Swaption` + `ql.BachelierSwaptionEngine` | the QuantLib stack, and a `SwaptionVolatilityStructureHandle` any QuantLib engine accepts |
| `ql-sabr` | the same over `ql.SabrSwaptionVolatilityCube` | a smooth arbitrage-free fit — and it does **not** reproduce its own nodes |

`with_backend("ql")` hands back a sibling on the same cube data and the same
curves, built once and cached, so switching library costs nothing and compares
like for like.

### What this replaced

Four objects, three of them pricers, no two with the same API — and three
consequences that were measured rather than assumed:

- **`NativeSwaptionCube` was unreachable from the MDP.** `rl_vol_cube()` called
  `build_rl_vol_cube(...)` with no `backend=`, and routed its own `**kwargs` to
  the cube's *axis* arguments, so there was no way to ask for it. Every cube the
  MDP or `Query/CitiVelocity` produced was the hand-built one.
- **The "QuantLib premium" was not a QuantLib price.** `ql_option_premium` took
  the QuantLib cube's vol but the *rateslib* cube's forward, annuity and time to
  expiry and evaluated Bachelier by hand — and divided an already-decimal forward
  and strike by 100 while leaving the vol in decimals. A Bachelier price depends
  on `(K − F)` measured in units of `σ√T`, so that scaled the moneyness by 100.
  At the money `K == F` and the error vanished, which is why it survived. **Every
  OTM premium it returned was wrong.**
- **None of it reached the repo's own swaption product**, which already carries
  13 structures, 20 value metrics, a strike grammar and a backtest handler.

### Reachable through the MDP / Query seams

```python
# the Citi Velocity MDP
pricer.swaption_cube("USD", backend="auto")

# the repo's swaption product - every structure and value metric, on Citi's cube
IRSwaptionMDP(source="CITIVELO-QL")     # ql.Swaption + BachelierSwaptionEngine
IRSwaptionMDP(source="CITIVELO-RL")     # rateslib, through ENGINE_FACTORIES["RL"]
```

`CITIVELO` joins `GSQUANT`, `MONKEYCUBE` and `GSQUANT_MC_ENHANCED` in
`VOL_PROVIDERS`; `RL` is the second entry ever in `ENGINE_FACTORIES`. Both
widenings are additive and the three existing providers are untouched — the
registry was always this permissive (`tests/test_ir_swaption_mdp.py` registers an
engine factory returning a bare `object()`), it just had one engine in it.

Three latent defects surfaced while wiring it, all fixed:

- the `handle()`/`index()` gate could not tell a rateslib curve from a QuantLib
  one (both define both), so the wrong types flowed into a QuantLib engine and
  failed inside SWIG. It now checks what came *out*, per engine.
- `curve.daycounter()` returns `None` on the rateslib backend — the stub on
  `_IRSwapGenericCurve` makes `hasattr` true, so the `ql.Actual365Fixed()`
  fallback was unreachable.
- the vol provider's exceptions were swallowed whole, so a provider that raised
  surfaced as a bare `KeyError` on the requested date. It logs the cause now, and
  the engine/curve check runs *before* the provider so it cannot be swallowed.

`premium_override` is **not** supported on `-RL` and says so: the QuantLib path
inverts the supplied premium through `ql.Swaption.impliedVolatility`, and matching
that would mean a second inverter and a silently different model.

### The check that can fail

A vol → cube → vol round trip is a **tautology**. Every interpolator here is exact
at its own data sites, so reading a node back out and comparing it with the quote
scores 2.8e-14 bp and cannot see a wrong annuity, schedule, day count, discounting
convention or strike/forward misalignment.

`vol/spot_check.py` closes the loop: it prices the actual swaption at
`forward + offset/1e4`, inverts the premium with
`RVUtils/ImpliedDistribution/_bachelier.py::bachelier_implied_vol` — a
pure-Python bisection over `scipy.stats.norm`, the **only** implied-vol solver in
the repo with no QuantLib in it — and compares against Citi's quote. It also
**crosses the annuities**: the QuantLib premium is inverted with rateslib's
`(F, A, T)` and vice versa, because a backend's own annuity cancels exactly out of
its own inversion (and `NativeSwaptionCube.annuity` is itself backed out of that
same ATM premium).

Mutation-verified in `tests/test_citivelo_swaption_spot_check.py` against a
**real** recorded cube, five ways: shift one node 1 bp, transpose two tenor
slices, perturb one forward, scale one annuity by 1%, swap payer for receiver. The
last two exist because the first three only move the volatility the pricer reads.

```bash
conda run -n stir python MDP/CitiVelocityExcel/harvest/verify_live.py --spot-check
```

---

## Notes

Everything below cost real debugging time. None of it is speculative.

**It requires a human-logged-in Excel.** No headless path exists: UDF registration
is gated on `CustomRibbon.onLoad` -> portal session -> entitlements, and spawned
instances never register. After an Excel restart the login takes **~13 minutes**
and logs nothing in between, so a readiness poll must wait 15 minutes before
concluding failure.

**Two ways to kill Excel, and the second is the naive fix for the first.**
(1) Writing a block that overlaps a live `CvFunction_*` region raises
`AccessViolationException` and takes the whole process down. (2) Clearing or
deleting a region while the add-in's queued `ExcessClr`/`Format`/`AutoFit` actions
are outstanding does the same. The client therefore uses generous spacing, a cursor
advanced by the block's **measured** extent, and never clears or deletes anything.
Never `Stop-Process` a client mid-call - that wedges the OLE server.

**Velocity supplies quotes only.** The `CVD*` pricers, `CVCALCDERIVATIVES`,
`CVLADDER`, `CVSCENARIOANALYSIS` and every portfolio function are not entitled.
Every curve, cube and bond analytic here is ours.

**One minute is the finest historical granularity for every family.** The desk's
intraday workbook advertises `SE10`, but that is the streaming feed; `CVTSHIST`
rejects it. Frequencies are exactly `MI01 MI10 HOURLY DAILY WEEKLY MONTHLY`.

**`CVMETADATA` is not a validator.** It reports zero valid tenors for the whole
`SWAP_SPREAD` family while `CVTSHIST` serves all eleven. Validate through
`CVTSHIST`, and always run known-good control tags first - two validators in the
design session produced confident wrong numbers and controls are what caught them.

**Pending cells are COM ints.** `#GETTING_DATA` is `-2146826245`. Treating
"non-empty" as "done" reads the sentinel as a price.

**Locate the header row by content.** `CurrentRegion` absorbs adjacent cells and
shifts every row; a hardcoded index reads the formula row.

**The catalog is a grammar, not a tag list**, and generation must be
*path-consistent*. Pooling `RATES.VOL`'s per-level vocabulary produced 2,163 tags
of which zero were valid. Depth varies per branch: `ATM.NORMAL` carries a
`DAILY|ANNUAL` level, `ATM.BLACK` does not. Negative strike offsets are spelled
`OTM_M25` under `NORMALABSOLUTE` and `OTM_N25` under `PREMIUM`.

**Vol branches default to `_RFR`.** All four legacy twins (`ATM`, `OTM`,
`REALIZED`, `VOL_RATIO`) account for every VOL shape failure and return no data.

**QuantLib `volSpreads` row order is optionTenors OUTER, swapTenors INNER.** Both
layouts have the same number of rows, so QuantLib constructs either without
complaint and the wrong one silently misprices by up to ~4.85 bp.
`vol.assert_vol_spread_ordering` is the check, and
`tests/test_citivelo_vol_cube.py` mutation-tests it.

### The wire's timezone, measured 2026-08-07

**Citi Velocity timestamps are `America/New_York` wall clock and they observe US
daylight saving.** This was unknown until now - `format_bound` emitted naive
stamps and nothing recorded what zone they were in.

`CVNOW()` matching the local clock is *not* the evidence, because this machine is
itself in ET and cannot separate exchange time from machine-local. The decisive
measurement is that **`EUR_EUROSTR`'s session is fixed in Frankfurt but its stamps
move with US DST**: hourly stamps read `02:00-13:59` on 2026-03-05/06 and
`03:00-14:59` on 2026-03-09/11 - the same 08:00-20:00 CET either side of the
**2026-03-08 US** spring-forward, not Europe's (2026-03-29). No fixed UTC offset
can produce that, and neither can London time. Corroborated on three more
currencies whose sessions are unambiguous locally: `JPY_TONAR` 19:00-06:59 ET =
08:00-19:59 JST, `AUD_AONIA` 18:00-05:59 ET = 08:00-19:59 AEST, `GBP_SONIA`
03:00-14:59 ET = 08:00-19:59 London.

The **request** side is the same zone: a `CVSNAP` at `2026-08-06 10:30` returned
`4.23287`, exactly the `MI01` row stamped 10:30.

Machine-local remains unruled-out on a machine in ET, so the zone is a named
constant overridable with `CITIVELO_EXCEL_WIRE_TZ`.

A consequence worth knowing: an Asia/Pacific **session straddles two ET dates**.
`JPY_TONAR` runs 19:00 ET through 06:59 ET the next day as one continuous block
(the 23:59 print and the following 00:00 print are the same number) and belongs to
Citi's `DAILY` row for the **later** date. Dating an intraday snapshot by its ET
calendar date builds a JPY/AUD/NZD curve one business day early.

### What each `CV*` function actually returns, measured 2026-08-07

| function | result |
|---|---|
| `CVTSHIST` intraday bounds | `yyyyMMddHHmm` **is honoured** - a 10:00-11:00 request returned exactly 61 rows. Previously inferred, now measured |
| `CVTSHIST` `HOURLY` + relative `period=` | **returns no block at all**, instantly. `HOURLY` with explicit bounds works |
| `CVTSHIST` `MI01` freshness | newest row was **1 minute old** at 10:47 ET |
| `CVLATEST` | serves - a bare column, one row per tag, 5 dp - with **no timestamp** |
| `CVSNAP` | serves the right value (cross-checked to the digit against `MI01`) with **no timestamp** |
| `CVSTREAM` | a live RTD-style cell: full double precision (`4.23909408453934` vs `CVLATEST`'s `4.23919`) and **the value changed between two reads 20 s apart** |

Because none of the point-read functions carries a stamp, none of them can tell a
curve that stopped ticking four hours ago from one that ticked a second ago - and
two of the twenty OIS curves have stopped (`EUR_EONIA` since 2025-08-15;
`JPY_TONAR_JSCC` serves EOD only). `CVSTREAM` is the right primitive for a polling
**daemon**, not for a request/response path.

### Serving these curves through `IRSwapsMDP`

`MDP/IRSwaps/CITIVELO_EXCEL/` wraps all twenty as an `IRSwapsMDP` source under the
token **`CITIVELO_EXCEL`** (`-RL` default, `-QL`), in EOD / intraday / live modes
with timezone-aware timestamps. See
`docs/superpowers/specs/2026-08-07-citivelo-excel-irswaps-source.md`.

### Verified live, 2026-08-05

`harvest/verify_live.py` ran against the signed-in add-in in 6 `CV*` calls and
settled the facts the hermetic suite structurally cannot:

| Question | Answer |
|---|---|
| Unit of `ATM_RFR.NORMAL` on the wire | **basis points** - `1Y10Y` served `80.9518`. `served_unit="bp"` is correct |
| 44-tenor par grid in one call | **yes** - 44 tags, 1 `CVTSHIST`, 23 rows x 44 columns, zero per-tag failures |
| Explicit `start=`/`end=` bounds | **honoured** - `yyyyMMdd` returned exactly the 11 requested days |
| `RATES.SWAP_LIBOR` serves | **yes, per currency** - EUR/AUD/INR valid, GBP/JPY empty (RFR migration) |
| `SWAP_SPREAD` vs `CVMETADATA` | **11/11 tenors serve** through `CVTSHIST`, confirming `CVMETADATA` is unsound |
| Curve stripped from real quotes | rateslib reprices its 44 inputs to **1.4e-03 bp**; rateslib vs QuantLib 10Yx10Y forward gap **1.7e-04 bp** |
| Fast path vs repricing, live | 10y quote `4.210550` vs repriced `4.210550` - **0.0000 bp** |

Reference quotes at 2026-08-05: 2Y 4.04128, 5Y 4.04945, 10Y 4.21055, 30Y 4.42447.

### Known limits

- `RATES.SWAP_LIBOR` has **no local repricing path**: its legs are IBOR-indexed,
  so the OIS conventions would be the wrong ones. Use the published quote.
  Coverage is per currency - validate the ones you need.
- `RATES.SPREAD_OPTIONS` and `RATES.MIDCURVES` were harvested only to the measure
  level; the expiry and pair/underlying levels are the desk's documented shape.
- Six OIS currencies (DKK, ILS, MXN, SGD, THB, ZAR) have market-standard rather
  than library-supplied conventions, flagged `provenance="market_standard"`.
  MXN Fondeo's 28-day roll is approximated as monthly - treat MXN as indicative.
- Only USD's vol axes were walked; a non-USD skew cube is shape-inferred and warns.
- AUD, DKK, KRW, NOK and SEK have no `_RFR` vol branch in the catalog at all.
- `PREMIUM` and `FWDPREMIUM` still carry a **declared** unit - nothing has ever
  fetched one. `OTM_RFR.NORMALABSOLUTE` no longer does: all twelve USD offsets
  (`+/-10, 25, 50, 75, 100, 200`) were fetched live on 2026-08-07 with zero
  per-tag failures and priced through both libraries, and a skew declared in the
  wrong unit could not survive that. `NORMALSKEW` remains coded, untagged and
  untested - the catalog walk never recorded its strike-offset level.
- Bond, inflation, cross-currency and options numbers have **not** been checked
  against a Citi quote. They are internal consistency between two independent
  implementations on synthetic inputs. The highest-value next step is to fetch
  `YIELD`/`PRICE`/`DURATION`/`DV01` for ~20 bonds across countries and reconcile.

---

## Tests

```bash
# hermetic - no Excel, no network, no database
conda run -n stir python -m pytest tests/test_citivelo_excel_client.py tests/test_citivelo_excel_cache.py \
  tests/test_citivelo_catalog.py tests/test_citivelo_curves.py tests/test_citivelo_vol_cube.py \
  tests/test_citivelo_native_vol_cube.py tests/test_citivelo_swaption_spot_check.py \
  tests/test_citivelo_swaption_provider.py \
  tests/test_citivelo_bonds.py tests/test_citivelo_inflation.py tests/test_citivelo_xccy.py \
  tests/test_citivelo_options.py tests/test_citivelo_timeseries.py -q

# the repo fast gate
conda run -n stir python -m pytest tests -m "not slow and not network and not db"

# live, against a signed-in Excel. Opt-in, and it drives the USER'S OWN process.
set CITIVELO_EXCEL_LIVE_TESTS=1
conda run -n stir python -m pytest tests/test_citivelo_excel_integration.py -m integration -q

# live probes, also against the user's own Excel. Bounded: ~8 CV* calls each.
conda run -n stir python MDP/CitiVelocityExcel/harvest/verify_live.py               # the wire
conda run -n stir python MDP/CitiVelocityExcel/harvest/verify_live.py --vol-compare # backend vs backend
conda run -n stir python MDP/CitiVelocityExcel/harvest/verify_live.py --spot-check  # price -> invert -> quote
```

`test_citivelo_swaption_spot_check.py` and `test_citivelo_swaption_provider.py`
are hermetic but run on **real** Citi quotes: `harvest/snapshots/` holds a
recorded capture (USD 2026-08-06, 260 tags, zero per-tag failures, the 44-tenor
par grid and six published forwards) and `vol/live_snapshot.py` reads it back
through the ordinary `cube_from_quotes` path. Re-record with
`verify_live.py --spot-check --save-snapshot NAME.json`. A synthetic smile has no
wing flattening and no kink, and the mutations are only convincing against one
that does.

They are **slow for unit tests** - together they add roughly 8 minutes to the
fast gate, because they build and price thousands of real swaptions across two
libraries rather than asserting on a fixture. That is the cost of a check that
can fail; the grids are already trimmed to the corners where the conventions
differ (`1Y`/`10Y` expiries against `2Y`/`30Y` tails). Two tests in the provider
file are marked `network` and stay out of the gate: they drive `CITIVELO-QL` and
`CITIVELO-RL` on real `IRSwapsMDP` curve sources rather than injected ones.

Each analytics package also ships a `_smoke.py` that prints its numbers:

```bash
conda run -n stir python MDP/CitiVelocityExcel/curves/_smoke.py
conda run -n stir python MDP/CitiVelocityExcel/vol/_smoke.py
```

---

## rateslib 2.1.1 -> 2.7.1

Done to get `IRSabrCube`/`IRSplineCube`. Those first appear in **2.7.0**; the
source-available licence notice first appears in **2.6.0**, so there is no version
with the cubes and without it. (This is personal infrastructure, so the
non-commercial terms are fine.)

### Nothing broke, and that was measured on numbers

`scripts/rateslib_upgrade_baseline.py` dumps **918 numbers** from the repo's real
objects - curve nodes, par reprices, IRS fair rates and PV01s, STIR rates, bond
metrics, every calendar and day count, the whole spec table, inflation
breakevens, the xccy solve - and diffs them across the upgrade. A green test
suite is a weaker claim: a signature change that silently alters a schedule still
passes any assertion that only checks a curve came back.

| section | max absolute change |
|---|---|
| `scheduling_and_calendars` (15 calendars, tenor arithmetic, day counts) | **0** |
| `fixed_rate_bonds` | **0** |
| `spec_table` | 0 numerically |
| `rl_irswap_curve_wrapper` (IRS fair rates, PV01) | 2.3e-13 |
| `stir_futures` (rates) | 8.8e-14 |
| `citivelo_intraday_curve` | 6.2e-13 |
| `citivelo_xccy` | 2.6e-12 |

0 values missing, 0 added. Everything above is floating-point noise.

### The migration: 38 call sites, all mechanical

| change | sites |
|---|---|
| `obj.__dict__["kwargs"][...]` reach-through -> `.kwargs.leg1[...]` / `.leg1.schedule.*` | 17 |
| `leg2_fixings=` -> `leg2_rate_fixings=` | 10 |
| `analytic_delta(curve=)` / positional -> `(curves=)` | 7 |
| `instrument.kwargs["x"]` -> `.kwargs.leg1["x"]` | 5 |
| `leg2_method_param=` removed | 2 |
| `rl.defaults.calendars` removed -> `get_calendar` | 1 |

Two traps in there. The `leg2_fixings` rename: rateslib suggests
`leg2_fx_fixings`, which is the MTM FX reset series, a completely different
thing. And the `__dict__["kwargs"]` reach-through: the `["kwargs"]` form raises
`KeyError`, but the `.get("kwargs", {}).get(...)` variant returns `None`
**silently** and only surfaces later as `float(None)` somewhere unrelated. Two of
those seventeen were production STIR/SDR curve builders. Schedule fields moved as
well: `effective`/`termination` are now on `leg1.schedule`, while
`fixed_rate`/`notional` stay in `kwargs.leg1`.

`tests/test_rateslib_27_migration.py` greps the whole repo to make sure the
reach-through form cannot come back.

### Three behaviour changes worth knowing

**STIR futures BPV moved, and 2.7 is right.** `usd_stir`/`eur_stir`/`gbp_stir`
changed convention from `act360`/`act365f` to `actacticma`. The future's *rate* is
unchanged, but `analytic_delta` went from `-25.2778` to exactly `-25.0` - the
exchange-defined $25/bp for a 3M SOFR contract. Anything sizing off STIR DV01
moves ~1.1% and becomes correct. `RLSTIRFuturePricer.pv01()` also had to change:
2.7 made the curve argument mandatory, and since a future carries no discounting
a DF==1 curve reproduces the old value exactly (verified: identical against a
flat and a steeply-discounting curve).

**UK gilt stub flipped** `shortfront` -> `longfront`, which changes the coupon
schedule without moving a yield-based metric.

**`ex_div` became a signed business-day string** (`1` -> `'-1b'`). Cosmetic -
accrued is identical either side of the ex-div boundary.

All three are pinned by `tests/test_rateslib_27_migration.py`.

### A safety regression the upgrade introduced, and the fix

**`solver.result['status'] == 'SUCCESS'` is no longer sufficient.** Measured: a
par grid with a -5000% front quote returns `status='SUCCESS'` from a curve that
misprices its own calibration swaps by **4.9e+05 bp**. Under 2.1.1 the same input
reported `FAILURE` and every builder in this repo refuses on that status.

`build_rl_ois_curve` now asks the solved curve to reprice the quotes it was built
from and raises if it cannot (`max_reprice_error_bp`, default 1.0 bp; the worst
real residual is ~2e-3 bp). Costs 17.5 ms on a 44-tenor grid, ~8.8% of the build.

**This affects every other rateslib curve builder in the repo** - the SDR STIR
builders, BARCHART_STIRF, the Eris and GSQuant paths - which all still gate on
the status alone. They were not changed here because that is outside this work's
scope, but they carry the same exposure.

### What the upgrade gained beyond the vol cubes

**MXN is now modelled properly.** rateslib 2.7 added `mxn_irs` with
`frequency="28d"` and a `mex` calendar. MXN Fondeo's 28-day roll was previously
approximated as monthly and flagged "indicative only"; the rateslib leg now rolls
on the traded schedule (verified: 28-day gaps after the front stub, repricing to
1.1e-04 bp). It moved from `provenance="market_standard"` to `"rateslib_spec"`,
leaving five approximate currencies rather than six.

QuantLib spells the same schedule `EveryFourthWeek` (4W), so `_QL_FREQUENCY` maps
`"28d"` onto it and **both backends roll on the same dates**. Without that entry
the QuantLib MXN builder raises `No QuantLib frequency for rateslib letter '28d'`
- which it did between the upgrade commit and this one.

### The native IR vol cube, and the swaptions that go with it

rateslib 2.7 ships `IRSplineCube`, `IRSabrCube` **and a full swaption suite** -
`IRSCall`, `IRSPut`, `IRSStraddle`, `IRSStrangle`, `IRSRiskReversal`. They are
wired up in `MDP/CitiVelocityExcel/vol/rl_native_cube.py` as
`NativeSwaptionCube`, which is now one of the four backends behind
`CitiVeloSwaptionCube` (see **The one swaption cube** below):

```python
build_citivelo_swaption_cube(cube=cube, rl_curve=rlc, ql_curve=qlc, backend="rl-native")
build_rl_vol_cube(cube=cube, rl_curve=curve, backend="native")   # the old entry point, unchanged
```

**The strike axis is signed BASIS POINTS from the ATM forward** -
`strikes=[-50, -25, 0, 25, 50]` - and the `parameters` are normal vol in basis
points. Both are exactly Citi's own convention, so a `SwaptionCubeData` maps on
with no transformation at all. An earlier revision of this file passed the strike
axis in percent; it builds without error, round-trips the ATM node exactly and
misprices the wings by up to 5x. `assert_native_cube_round_trips` is
mutation-tested against that mistake, a transposed parameter block, and a single
0.01bp nudge.

**Why `build_rl_vol_cube` still defaults to the hand-built cube.** Not accuracy -
the two agree on live Citi quotes to 1.7e-10 on price and 1.6e-05 on vega. It is
that rateslib labels IR vol Beta, and the live reconciliation found a real defect
in it (next section). The native path is the better one for *risk*: it carries AD
back to the curve and vol nodes and can sit in a `Solver`, which the `PPSplineF64`
cube cannot - which is why `CitiVeloSwaptionCube`'s `backend="auto"`, and
therefore everything reached through the MDP, prefers it.

### rateslib times the option from the CURVE, and its analytic vega pays for it

Found on live Citi quotes on 2026-08-06, reproduced exactly offline, pinned by
`test_analytic_vega_is_wrong_when_the_curve_starts_after_the_cube`.

When the curve's first node is not the cube's `eval_date`, rateslib computes
`analytic_greeks()['vega_usd']` at a time to expiry measured from the **curve**,
while the premium uses the cube's eval date. The premium stays correct - it
matches the hand-built backend to 1e-15 - but the analytic vega comes back low by
`sqrt(T'/T) * phi(d')/phi(d)`. For a one-day gap on a 1Y expiry that is **0.137%
at the money and 0.34% at the 100bp wings**, and nothing raises.

Two defences:

- `NativeSwaptionCube.vega()` central-differences its own `price()` over a
  +/-0.5bp shift of the cube (both shifted cubes built once and cached), so it is
  consistent with the premium by construction. Live worst-case agreement with the
  hand-built backend went from 3.7e-03 to 1.6e-05 when this replaced `vega_usd`.
- the constructor warns when `cube.as_of` and the curve's first node disagree,
  naming the size of the error - because `greeks()` still returns rateslib's raw
  dict and someone will read `vega_usd` out of it.

Pass `vega(..., analytic=True)` to get rateslib's value; it is exact and faster
**when the dates line up**.

### What the live comparison settled

`verify_live.py --vol-compare` (5 `CV*` calls) reconciles both backends on a real
USD cube. On 2026-08-06:

| check | result |
|---|---|
| both backends reproduce Citi's quoted vol | 2.8e-14 bp (float noise) - no transformation applied |
| the two backends agree on price | 1.7e-10 relative, 0.0003 currency units on 100m |
| the two backends agree on vega | 1.6e-05 relative (central-difference truncation) |
| **our ATM forward vs Citi's published `RATES.OIS.USD_SOFR.FWD.<e>.<t>`** | **worst gap 0.286 bp over six points** |

That last row is the one the cube cannot check itself. Citi measures its strike
offsets from *its* forward; we measure them from ours, and a gap there slides the
whole smile along the strike axis without changing a single node vol. It is now
measured rather than assumed: **the strike axis is anchored where Citi anchors
it.**

The first three rows, however, are **not a check on the numbers**. Every
interpolator here is exact at its data sites, so "reproduces the quoted vol"
reports float noise no matter what the annuity, schedule or day count is doing.
That is what `--spot-check` exists for.

### What the SPOT CHECK settled

`verify_live.py --spot-check`, 2026-08-06 USD, **8 `CV*` calls, 1040 priced
nodes** - 5 expiries x 4 tenors x (ATM + all twelve OTM offsets) x payer and
receiver x both backends. Every premium was inverted back to a volatility with a
pure-Python bisection and compared against Citi's quote.

| check | result |
|---|---|
| implied vol vs quote, inverted with the pricing backend's own `(F, A, T)` | **3.0e-04 bp** worst |
| implied vol vs quote, inverted with the OTHER library's `(F, A, T)` | **0.213 bp** worst |
| put-call parity, `PV(payer) - PV(receiver)` vs `N.A.(F-K)` | 5.5e-14 relative |
| rateslib premium vs QuantLib premium at the same node | 3.3e-05 relative |
| premium monotone in strike | **0 violations** over 1040 nodes |
| QuantLib `atmStrike` vs the underlying's own par rate | 0.0017 bp |
| our forward vs one computed off the curve by an independent path | 0.094 bp |
| **our forward vs Citi's published `RATES.OIS.USD_SOFR.FWD.<e>.<t>`** | **0.256 bp** worst over six points, identical on both backends |

Reading those two error rows:

- The **self-inverted** residual is 3e-9 bp on the rateslib backends (an
  arithmetic identity) and 3e-4 bp on QuantLib. All of the QuantLib residual is
  the `atmStrike` row: its engine reads the vol at `atmStrike + spread` while the
  strike is measured from the swaption's own par rate, and the residual is that
  0.0018 bp gap times the local smile slope. Annuity and time to expiry were
  measured **identical** to 1e-16 and 4e-10.
- The **cross-inverted** residual is entirely 3M x 30Y at +/-200 bp, where a 3-month
  option 200 bp in the money has almost no vega (`phi(3.45) ~ 0.001`), so a
  3.5e-04 bp forward difference between the two bootstrapped curves has to be
  absorbed by a large volatility move. Hand both libraries the **same** curve -
  `build_ql_mirror_curve` puts the rateslib nodes into a `ql.DiscountCurve`, both
  log-linear on discount factors - and it collapses to 3.0e-04 bp, because the
  two then agree on the forward to **2e-12 bp** and on the annuity to **7e-16**
  relative. rateslib's `IRSCall` underlying and QuantLib's `MakeOIS` are the same
  swap: same schedule, same roll, same fixed-leg day count, same payment lag,
  same discounting.

Per-node output lands in `harvest/spot_check_live.parquet`, and the report prints
a table of `(expiry, tenor)` against every strike offset with ATM in the `0.0`
column, plus summaries by expiry, by tenor and by offset. A max alone hides a
corner, and in this case the corner (`3M x 30Y`, deep wings) is the whole story:
every other cell in the 20 x 13 grid is at or below 2e-04 bp.

### Re-run on Citi's OWN curve — the residual does not move

Once `IRSwapsMDP(source="citivelo_excel_rl")` (PR #394) could serve Citi's warmed
SOFR curve for 2026-08-06 — asset `USD-SOFR-1D-CITIVELOEXCEL`, 45 nodes spanning
exactly 50.0 years, tied out to Citi's own quotes — the obvious question was
whether the 0.256 bp forward residual was curve provenance. **It is not.**

| curve | worst \|our forward − Citi's published FWD\| |
|---|---|
| Citi's own warmed CurveStore curve | **0.2558 bp** |
| our rateslib bootstrap of Citi's par grid | **0.2558 bp** |
| our QuantLib bootstrap of the same grid | **0.2558 bp** |

The three agree with each other on every forward to **< 0.0001 bp**. So the
residual is not the curve, and two things it *is* fell out of asking:

**One point does the damage, and it is the only one that has to be interpolated.**
Citi's par grid is annual to 20Y then 25/30/35/40/45/50, so a `1Yx30Y` — which
matures at ~31Y — is the only one of the six published points that does not land
on a pillar. It sits in the widest gap in the grid (30Y→35Y) and it is the worst
by 3x:

| point | matures | pillar gap | width | error |
|---|---|---|---|---|
| 1Yx30Y | 31Y | 30Y – 35Y | **5Y** | **−0.2558 bp** |
| 1Yx2Y | 3Y | on pillar | 0 | +0.0903 bp |
| 5Yx2Y | 7Y | on pillar | 0 | −0.0885 bp |
| 5Yx10Y | 15Y | on pillar | 0 | −0.0806 bp |
| 1Yx10Y | 11Y | on pillar | 0 | +0.0215 bp |
| 5Yx30Y | 35Y | on pillar | 0 | −0.0086 bp |

This is **not** a coverage or extrapolation problem — the curve carries nodes to
50Y and the far corner of the cube (10Y x 30Y) matures at 40Y, well inside it.
Citi publishes its `FWD` tag off its own internal curve; any curve rebuilt from
the 44-tenor par *projection* of that curve must interpolate 30Y→35Y, and 31Y is
where that costs the most.

**At 5Y expiries the forward-START convention is worth ~0.09 bp.** Two rules exist
for the same "5Yx10Y forward": the swaption's (`MF(as_of + 5Y)` then + settlement
lag, which is where its underlying actually starts) and `MakeOIS`'s
(`(spot + 5Y)` adjusted FOLLOWING, which `curves/forward_rate` uses). At 1Y
expiries they coincide; at 5Y they do not, and **Citi's tag matches the MakeOIS
rule**:

| point | swaption rule − Citi | MakeOIS rule − Citi |
|---|---|---|
| 5Yx10Y | −0.0806 bp | **+0.0005 bp** |
| 5Yx2Y | −0.0885 bp | **+0.0053 bp** |

That does not make the swaption rule wrong — a swaption's underlying does start a
settlement lag after the option expires — but it does mean Citi's published `FWD`
is not the forward of the swap the swaption exercises into, and the two should not
be expected to agree to better than ~0.09 bp at longer expiries.

What is left after both: **≤ 0.09 bp at 1Y expiries, unexplained**, where the two
conventions agree and the points sit on pillars.

### The same run, both libraries, on that one curve

Handing rateslib the Citi curve and QuantLib a node-for-node mirror of it
(`build_ql_mirror_curve`) — so the comparison is of the swaption and not of two
curve builders — over 1040 priced nodes:

| metric | two independent bootstraps | Citi's curve, mirrored |
|---|---|---|
| implied vs quoted, cross-inverted | 0.211 bp | **2.98e-04 bp** |
| implied vs quoted, self-inverted | 3.0e-04 bp | 2.98e-04 bp |
| put-call parity | 4.2e-14 | 2.3e-14 |
| rateslib vs QuantLib premium | 3.3e-05 | 3.3e-05 |
| monotonicity violations | 0 | 0 |

The cross-inverted error falls by ~700x and lands exactly on the self-inverted
one, which settles the earlier reading: **the 0.211 bp was the curve bootstrap,
not the swaption.** The rl-vs-QuantLib premium difference does *not* move, because
it is the `atmStrike` anchor (0.0017 bp) and not the curve.

All five `DEFAULT_TOLERANCES` — calibrated on the bootstrapped curve — still pass
on Citi's, with room:

```
backend_price_rel      3.268e-05  <= 1e-04
implied_vol_cross_bp   2.977e-04  <= 0.5
implied_vol_self_bp    2.977e-04  <= 1e-03
parity_rel             2.345e-14  <= 1e-09
vol_anchor_gap_bp      1.736e-03  <= 0.05
```

**One operational caveat.** The CurveStore fast path is gated on
`not ignore_cache`, so `IRSwaptionMDP(..., curve_source="citivelo_excel_rl")`
with `ignore_cache=True` bypasses the store and rebuilds from the quotes layer —
which is cached-then-**live**, i.e. it can reach for Excel on a cold tag cache.
Both paths produced an identical 1Yx10Y forward (4.321999%), so it is a
provenance and etiquette question, not a numerical one.

**Everything in that run has to be one observation date.** The par grid and the
`FWD` series publish before the OTM skew does, so on any given morning
`grid.iloc[-1]` is a day ahead of the last date the cube is simultaneous on. Two
separate cross-date reads were found and fixed while producing the table above:
building the curve off the grid's last row put an 08-06 cube on an 08-07 curve,
and taking `FWD.dropna().iloc[-1]` compared our 08-06 forward with Citi's 08-07
one - which read **4.222 bp** and looked exactly like a broken anchor until both
sides were pinned to the cube's own date, where it reads 0.256 bp. `--spot-check`
now selects the cube's date on both, prints `SAME DAY` or names the gap, and drops
a forward tag rather than compare it across dates.
