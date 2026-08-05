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
