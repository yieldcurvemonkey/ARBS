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
| `RATES.VOL.<ccy>.{ATM_RFR,OTM_RFR,REALIZED_RFR,VOL_RATIO_RFR}` | expiry x tenor x strike offset | QuantLib `InterpolatedSwaptionVolatilityCube` / `SabrSwaptionVolatilityCube`; a rateslib-primitive normal-vol cube |
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
- Only the ATM vol unit was measured. `PREMIUM`, `FWDPREMIUM` and the `OTM_RFR`
  skew branches still carry a declared unit - extend `verify_live.py` before
  trusting a skew cube.
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
  tests/test_citivelo_bonds.py tests/test_citivelo_inflation.py tests/test_citivelo_xccy.py \
  tests/test_citivelo_options.py tests/test_citivelo_timeseries.py -q

# the repo fast gate
conda run -n stir python -m pytest tests -m "not slow and not network and not db"

# live, against a signed-in Excel. Opt-in, and it drives the USER'S OWN process.
set CITIVELO_EXCEL_LIVE_TESTS=1
conda run -n stir python -m pytest tests/test_citivelo_excel_integration.py -m integration -q
```

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
`NativeSwaptionCube`, selectable with:

```python
build_rl_vol_cube(cube=cube, rl_curve=curve, backend="native")   # or "auto"
```

**The strike axis is signed BASIS POINTS from the ATM forward** -
`strikes=[-50, -25, 0, 25, 50]` - and the `parameters` are normal vol in basis
points. Both are exactly Citi's own convention, so a `SwaptionCubeData` maps on
with no transformation at all. An earlier revision of this file passed the strike
axis in percent; it builds without error, round-trips the ATM node exactly and
misprices the wings by up to 5x. `assert_native_cube_round_trips` is
mutation-tested against that mistake, a transposed parameter block, and a single
0.01bp nudge.

**Why the hand-built cube is still the default.** Not accuracy - the two agree on
live Citi quotes to 1.7e-10 on price and 1.6e-05 on vega. It is that rateslib
labels IR vol Beta, and the live reconciliation found a real defect in it (next
section). The native path is the better one for *risk*: it carries AD back to the
curve and vol nodes and can sit in a `Solver`, which the `PPSplineF64` cube
cannot.

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
