# Prompt — implement Citi Velocity MDP objects

Paste the block below into a fresh Claude Code session started in `C:\Users\chris\clee\ARBS`.

---

Build the Citi Velocity Excel add-in into a full first-class market-data source in
ARBS: swap curves for every currency, swaption vol cubes, bonds, inflation and
cross-currency — in **both rateslib and QuantLib** — exposed through the repo's
`Query` + `Structure` + `MDP` + `TimeseriesBuilder` patterns.

This is a large, comprehensive build. Do not deliver a thin slice.

## Start here — read before writing code

Prior session output is on branch `feat/citivelo-excel-timeseries`
(worktree `../ARBS-cve`), 5 commits:

- `docs/superpowers/specs/2026-08-04-citivelo-excel-timeseries-design.md` — the
  design spec. **Read it fully.** It records every failure mode found the hard way.
- `MDP/CitiVelocityExcel/catalog/*.json` — the harvested tag catalog: a 2,101-node
  structural walk of all 33 `RATES.*` families, per-family grammar, per-branch
  shapes, the bond ISIN universe and 16,288 validated bond tags.
- `MDP/CitiVelocityExcel/harvest/*.py` — the COM bridge (`cv_probe.py`), the UI
  Automation catalog harvesters, and the validators.

Read these repo patterns before designing anything:

- `MDP/MarketDataProvider.py`, `Query/Base/BaseQuery.py`, `TB/BaseTimeseriesTB.py`
- `../ARBS-ladder/MDP/IRSwaps` — swap MDP + RL/QL curve builders (`CITI_VELO` there
  is an empty placeholder; that is the slot this work fills)
- `../ARBS-ladder/MDP/FixedRateBonds` — bond MDP patterns
- `../ARBS-ladder/MDP/IRSwaptions` — existing QuantLib swaption cube implementations
- `MDP/IRSwaps/CITI_VELOCITY_INTRADAY` — the *old* manual flow (parses a
  hand-saved workbook). This work replaces it with a live programmatic path.

Environment: `conda run -n stir`. Fast gate:
`conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.

## Honest starting state — read this carefully

**A data fetcher does not exist yet. You must write it first.**
`cv_probe.Prober.probe_tshist()` returns `{status, sample, rows}` — a validity
verdict plus a single cell. It never returns a timeseries. There is no cache, no
MDP source, no Query, no TB integration, no curve construction.

What *is* proven: the COM mechanism works. `poc_attach.py`-style code read full
blocks (a 4,091-row one-minute UST series, a 22-row daily swap series, multi-tag
blocks). Promote that into a real fetcher.

**Velocity supplies quotes only.** The `CVD*` pricers, `CVCALCDERIVATIVES`,
`CVLADDER`, `CVSCENARIOANALYSIS` and every portfolio function are **not entitled**
— calling them returns an entitlement failure, not data. Entitled functions are
exactly: `CVTSHIST CVSNAP CVLATEST CVMETADATA CVCURVE CVCURVEBOND CVSTREAM CVTICK
CVNOW CVTODAY`. So all curve stripping, cube construction and bond analytics must
be built in rateslib/QuantLib from Citi quotes. That is the bulk of the work.

## Non-negotiable constraints

1. **Requires a human-logged-in Excel.** No headless path exists: the login is
   gated on `CustomRibbon.onLoad` → portal session → entitlements, and spawned
   instances never register the UDFs. After an Excel restart the login takes
   **~13 minutes**, logging nothing in between. Readiness polls must wait ≥15 min
   before declaring failure, and must not hammer COM during startup (the login
   runs via `ExcelAsyncUtil.QueueAsMacro` and needs Excel idle).
2. **Excel is a single shared mutable resource — the user's own session.**
   Serialize every access behind one lock. Never touch their workbooks; work only
   in a scratch workbook you create.
3. **Three ways to destroy their Excel, all observed:**
   - writing a block that overlaps a live `CvFunction_*` region → `AccessViolation`;
   - clearing/deleting a region while the add-in's queued `ExcessClr`/`Format`/
     `AutoFit` actions are outstanding → `AccessViolation` (this is the naive fix
     for the first one — do not do it);
   - `Stop-Process` on a COM client mid-call → wedged OLE server, ~15 min recovery.
   Discipline: generous spacing, cursor advanced by the block's **measured**
   extent, delayed teardown, and runs that stop via their own checkpointing.
4. **Parsing gotchas that silently corrupt results** (all cost real debugging time):
   - pending async cells arrive as COM ints: `#GETTING_DATA` = `-2146826245`,
     `#N/A` = `-2146826246`. Treating "non-empty" as "done" reads the sentinel as data.
   - `CurrentRegion` absorbs adjacent cells, shifting every row. **Locate the header
     row by content (`row[0] == "Date"`), never by index.**
   - dates come back as Excel serials *or* `pywintypes.datetime` depending on the
     number format the add-in applied — accept both.
   - `CVTSHIST` degrades per column (`Bad tag: <tag>` in that column's first data
     cell); `CVMETADATA` can hard-fail a whole batch to `#VALUE!` and needs bisect.
   - **`CVMETADATA` is not a sound validator** — it reports zero valid tenors for
     `SWAP_SPREAD` while `CVTSHIST` serves all 11. Validate through `CVTSHIST`.
   - Excel-busy surfaces as `AttributeError` on `Application.Workbooks` from
     win32com dynamic dispatch; retry it. `GetActiveObject` can return a zombie —
     enumerate the ROT and pick an instance that actually works.

## Deliverable 1 — the fetcher (`MDP/CitiVelocityExcel/`)

`com_client.py` — promote the PoC into a real client:

- `fetch_timeseries(tags, freq, period=None, start=None, end=None, price_point="CLOSE") -> dict[tag, pd.Series]`
  batching many tags per `CVTSHIST` call (44 proven in one call), returning **full
  history**, with per-tag failure surfaced rather than swallowed.
- `snapshot()`, `latest()`, `metadata()`, `curve()`, `curve_bond()`.
- Connection: attach to the running authenticated Excel; never spawn. Distinguish
  "no Excel" from "Excel running but not signed in" (`#NAME?`) with actionable errors.

`cache.py` — incremental parquet store keyed `(tag, freq, price_point)` under a
`reference_data_cache`-style tree. Serve cached rows, fetch only the missing span,
merge and dedupe. `CVMETADATA` gives each tag's history start date, so the cache
knows when it already holds everything. Intraday and daily are separate keys.

`catalog.py` — load the harvested catalog; `families()`, `children()`, `search()`,
`tenors()`. **The catalog is a grammar, not a tag list** — exhaustive enumeration
is infeasible (`VOL` alone is ~250k tags). Generate the tag you want, validate on
demand. Generation must be **path-consistent**: shape varies per branch and even
between conventions of one measure (`ATM.NORMAL` has a `DAILY|ANNUAL` level;
`ATM.BLACK` does not). Pooling vocabulary per level produces tags on no real path.

`tags.py` — typed builders derived from the catalog, not hand-written. Default to
`_RFR` vol branches: every legacy non-RFR branch (`ATM`, `OTM`, `REALIZED`,
`VOL_RATIO`) is dead, while all four `_RFR` twins are 100% shape-correct.

## Deliverable 2 — curves and cubes, rateslib **and** QuantLib

**Swap curves — every currency.** `RATES.OIS.<ccy>_<idx>.PAR.<tenor>` gives 20
validated RFR curves × 44 tenors. Real identifiers are not guessable — they include
`EUR_EUROSTR` (not ESTR), `USD_FEDFUND` (singular), `JPY_TONAR_JSCC` and
`JPY_TONAR_LCH` (CCP-split), `DKK_TNDKK`, `MXN_T_FONDEO`. `EUR_EONIA` exists but is
stale (~1y). Also expose `SWAP_SPREAD` (11 liquid tenors: 1M 3M 6M 1Y 2Y 3Y 5Y 7Y
10Y 20Y 30Y), `FWD`, `ROLL_CARRY`, `CURVES`, `BFLY`.

**`RATES.SWAP_LIBOR` — 46 currencies, unverified.** Its shape has *not* been
confirmed. Probe it first with `harvest/probe_shape2.py` + `validate_shapes3.py`
before building anything on it. Non-RFR/EM currency coverage depends on it.

Build rateslib `Curve`/`Solver` and QuantLib term structures from the par grid,
following the existing RL builders in `../ARBS-ladder/MDP/IRSwaps`.

**Swaption cube.** `VOL.<ccy>.ATM_RFR.{NORMAL,BLACK,PREMIUM,FWDPREMIUM}.ANNUAL.<expiry>.<tenor>`
and `OTM_RFR.{PREMIUM,NORMALABSOLUTE,NORMALSKEW,RISK_REVERSAL}.OTM_{N,}<bp>.<expiry>.<tenor>`
— already expiry × tenor × strike-offset, i.e. a ready-made cube.

- rateslib: `IRSabrCube`, `IRSplineCube` — see
  https://rateslib.com/py/en/2.7.x/api/rateslib.volatility.IRSabrCube.html ,
  `.../IRSplineCube.html` , `.../c_ir_smile.html` , `.../z_ir_vol_risks.html`
- QuantLib: follow `../ARBS-ladder/MDP/IRSwaptions`. **Gotcha:**
  `ql.InterpolatedSwaptionVolatilityCube` takes `volSpreads` as a 2-D matrix with
  rows ordered **optionTenors outer, swapTenors inner** — 1y2y, 1y10y, 1y30y,
  10y2y, … Confirmed against SWPM. Assert this ordering in a test; getting it
  wrong silently misprices.

**Bonds.** Two-step, not a tag family: `CVCURVEBOND(
"RATES.BONDS.BY_COUNTRY.<CTRY>.<CCY>.ASSET_TYPE_<TYPE>.<MEASURE>.<yyyymmdd>")`
returns `Date | ISIN | Description | measure` — the universe (2,162 ISINs, 18
countries, `GOVT`/`AGENCY`/`COVERED`). Then `RATES.BOND.<ISIN>.<value>` is the
per-bond timeseries. Values: `PRICE YIELD SPREAD_TSY ASW_4_{USD,EUR,GBP,CHF,JPY,AUD}
OAS DURATION DV01 CAS` — `ASW_4_<CCY>` is a **sparse cross-currency matrix**, not
the bond's own currency. The desk's 43-entry measure catalogue is *not* the tag
vocabulary: all `REFERENCE_DATA` fields are rejected, `DOLLAR_DURATION` is really
`DV01`, and `CVCURVEBOND` accepts `OAS` but not `DV01` while `DV01` is a valid
per-bond value. Bonds appear to be **EOD-only** (absent from the intraday map) —
verify. Wire into rateslib `FixedRateBond` and QuantLib `FixedRateBond`/
`BondFunctions`, following `../ARBS-ladder/MDP/FixedRateBonds`.

**Inflation.** `RATES.INFLATION.{INDEX,INF_CARRY,SWAP,SWAPTION}.*`, 100%
shape-valid.
- rateslib: https://rateslib.com/py/en/2.7.x/z_inflation_indexes.html ,
  `.../z_index_bonds_and_fixings.html`
- QuantLib: https://www.quantlibguide.com/Inflation%20indexes%20and%20curves.html ,
  https://www.implementingquantlib.com/2024/05/inflation-curves.html

**Cross-currency.** `XCCY_OIS_SWAP.<ccy1>.<ccy2>.<fwd>.<tenor>.{BASE_LEG,SPREAD_LEG}.BASIS_SPREAD`
— validated 1,097/1,097.
- rateslib `XCS` + `FXForwards`: https://rateslib.com/py/en/2.7.x/e_multicurrency.html ,
  `.../z_reverse_xcs.html` , `.../z_non_deliverable_irs_xcs.html` ,
  https://rateslib.com/py/en/1.5.x/z_eurusd_surface.html
- QuantLib has no native XCS instrument; build cashflows per
  https://www.quantlibguide.com/Cross-currency%20swaps.html and
  https://implementingquantlib.substack.com/p/cross-currency-curve-bootstrapping

**Single-look CMS spread options.** `RATES.SPREAD_OPTIONS.<ccy>.OPT_CAP.{PRICE,VOL}.<expiry>.<pair>`
(pairs like `2Y5Y`, `5Y10Y`, `10Y30Y`). A single-look option is on the difference of
two forward CMS rates at one expiry — not a strip, unlike a CMS spread cap/floor.
See https://www.quantlib.org/slides/qlws14/miemiec.pdf . `MIDCURVES` is the
analogous `{OPT_PAY,OPT_REC,OPT_STR}.{PRICE,VOL}.<expiry>.<1Y1Y-style underlying>`.

## Deliverable 3 — Query + Structure, and a fast-path TimeseriesBuilder

Follow the existing pattern exactly: `Query/<Product>/…Query.py`, `…Structure.py`,
`…Value.py`, `adapter.py`, registered via `Query/Base/product_adapter.py`. Queries
must compose (outright / curve / fly) and resolve through `StructureMap` +
`ValueMap` like `Query/IRSwaps`.

**The TB optimisation is a hard requirement.** `BaseTimeseriesTB` prices every
query at every timestep via `MDP.get_pricer` — for Velocity that is pathological,
because most queries *are already a tag*. Implement a Citi-specific TB that:

- resolves each query to a tag where one exists (e.g. a 10y par rate, a swap
  spread, a vol point, a bond yield) and pulls the **whole series in one
  `CVTSHIST` call**, batching tags across queries — no curve build, no repricing;
- falls back to the normal build-and-price path only for queries with no direct
  tag (bootstrapped curves, cube interpolation, structures Citi does not publish);
- keeps both paths behind one interface so a notebook does not choose;
- **proves equivalence**: a test asserting the fast path and the repricing path
  agree to tolerance on the same query. Without that the optimisation is a
  silent-divergence risk.

## Testing

- Hermetic unit tests inject a fake COM object recording formulas and replaying
  canned `CurrentRegion` tuples: sentinel polling, header-by-content, serial-vs-
  datetime dates, `Bad tag:` per column, `#VALUE!` bisect, cache merge, tag
  builders, QL cube row ordering. No Excel required.
- **Mutation-check the parser tests**: revert the sentinel handling to the naive
  "non-empty means done" predicate and confirm the tests fail. They passed against
  a broken parser once already.
- Every validator must run **known-good control tags first and refuse to report if
  the controls fail**. Two validators in the prior session produced confident
  wrong numbers (0/1673 and "13% fetchable") and controls are what caught them.
- One `integration`-marked test hitting real Excel, self-skipping when no
  authenticated add-in is present — mirror `tests/test_citi_velocity_intraday_curve.py`.

## Working rules

- New git worktree, short sibling path; never write in the primary checkout.
- Ask before long unattended harvests; they need Excel held open and can take hours.
- Report honestly: if a family's shape is unverified, say so rather than shipping
  generated tags that look plausible. A builder that silently emits wrong tags is
  worse than no builder.
