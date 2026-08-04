# Citi Velocity timeseries via the Excel add-in (`citivelo_excel`)

**Date:** 2026-08-04
**Branch:** `feat/citivelo-excel-timeseries` (worktree `../ARBS-cve`)
**Status:** design — approved to write up, not yet implemented

## Problem

Citi Velocity rates data currently reaches ARBS only by hand: a human types
`=CVTSHIST(...)` into Excel, waits, and saves a workbook that
`MDP/IRSwaps/CITI_VELOCITY_INTRADAY` later parses off disk. That covers exactly one
product (USD SOFR OIS par rates) and requires manual work per pull.

We want programmatic access to the whole `RATES.*` namespace — swaps, treasuries,
the vol cube, invoice spreads, meeting-priced OIS, bonds — through the repo's normal
data-fetching pattern, so `notebooks/timeseries` can pull Velocity series the same
way it pulls everything else.

## Feasibility: what was proven, and how

All findings below come from a working proof of concept run against the live,
logged-in add-in (v1.7.27) on 2026-08-04. This section records evidence, not
expectations.

### The transport: COM into a logged-in Excel — works

Attaching to a running, authenticated Excel via `GetActiveObject("Excel.Application")`,
writing a `CVTSHIST` formula into a scratch workbook, polling the async cell, and
reading back the written block **works and is fast**. Verified pulls:

| Tag | Freq | Result |
|---|---|---|
| `RATES.OIS.USD_SOFR.PAR.10Y` + `.2Y` | DAILY / 1M | 22 rows, both tenors (10Y 4.22537, 2Y 4.05114 @ 2026-08-04) |
| `RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y` | DAILY / 1M | 22 rows |
| `RATES.TSY.TSY.OTR.10Y.YIELD` | **MI01** | **4,091** one-minute rows, 2026-08-01 → 08-04 |
| `CVMETADATA` on any tag | — | description, history start/end, last-5 update times |
| `CVLATEST` | — | live tick + timestamp |
| `CVSNAP` at `202608010900` | — | 4.31898 + snap timestamp |

`CVCURVE` and `CVCURVEBOND` are **entitled but not yet exercised** — the run that
would have verified them crashed Excel first (see below). They are in scope on the
strength of the entitlement log, and their block layout must be confirmed during
implementation rather than assumed to match `CVTSHIST`.

Cold calls settle in ~0.6–0.9 s; warm calls are instant. Many tags batch into one
call (the existing 44-tenor curve export is a single `CVTSHIST`).

### Why the transport must be COM, not HTTP

The add-in is a thin client over documented REST endpoints
(`ExcelConfiguration.json` maps every UDF to one). Calling them directly was
attempted and rejected on evidence:

- `chartingbe/rest/data/v2` requires `auth={yyyyMMddHHmmss}{64-hex}`, regenerated
  per request and signed client-side inside `Citi.Velocity.Web.dll`.
- The signing material lives in `session\portal`, which is **DPAPI-sealed with
  secondary entropy** — `CryptUnprotectData` fails with error 13 even as the same
  user.
- The add-in's cookies are not in the WinINet jar
  (`InternetGetCookieExW` returns empty for the domain).

Reproducing that auth means reversing a bank's request signer, which is fragile and
breaks on every add-in update. **The add-in is the sanctioned client; we drive it
rather than impersonate it.**

### Why the bridge cannot (yet) be crash-isolated

Three ways to get an Excel that is *not* the user's were tried:

1. **`DispatchEx` (`/automation -Embedding`)** — the XLL loads (`RegisterXLL` returns
   true, "Add In successfully loaded") but **UDFs never register**. Registration is
   gated on `CustomRibbon.onLoad` → portal session resume → entitlements, and the
   ribbon never loads in an automation instance. `CVTSHIST` stays `#NAME?`.
2. **Launch `EXCEL.EXE <book>` normally** — Excel is single-instance; the workbook
   opens *inside the user's process*. No isolation.
3. **`EXCEL.EXE /x <book>`** — a genuinely separate process (confirmed: distinct PID,
   only our workbook). `onLoad` fires, but the login taskpane never appears and UDFs
   never register, while the user's session is live. Untested with the user's Excel
   closed.

**Conclusion: v1 attaches to the user's Excel.** Isolation stays an open question
(see Open Questions).

### The crash mode — the single most important constraint

During probing, the add-in threw
`System.AccessViolationException: Attempted to read or write protected memory` from
`ExcelRegistration..ctor (line 54) --> CVMETADATA` and **took the entire Excel
process down**, including the user's open workbook (which auto-recovered).

The trigger was writing successive UDF formulas at spacing narrower than the blocks
they expand into, so the add-in's `CvFunction_*` output regions overlapped.

**A second crash then invalidated the first mitigation.** A follow-up run using
"one request per fresh worksheet, delete the sheet after reading" *also* killed
Excel:

```
ERROR | Citi.Excel.ExcelAsyncUtilWrapper | Error while Action …!$A$1-1x2-ExcessClr
```

When a UDF resolves, the add-in **queues follow-up actions against the cells it
wrote** — `ExcessClr`, `Format`, `AutoFit` — and logs `Action complete for
<addr>-<rows>x<cols>-<action>` when each finishes. Deleting the sheet before those
drain pulls the target out from under them → `AccessViolation` → process death.

So there are **two** distinct crash triggers, and the second one is the mitigation
naively proposed for the first:

1. writing a block that overlaps an existing `CvFunction_*` region;
2. clearing or deleting a region while the add-in's queued post-write actions
   against it are still outstanding.

The correct discipline is therefore **generous spacing plus delayed teardown**:
never write into a region that overlaps a live one, and never tear a region down
until its queued actions have drained. Since v1 shares the user's process, **a bug
in our writer can destroy the user's unsaved work** — this is a correctness
requirement, not a nicety.

### Output layout and error semantics (verified)

A resolved `CVTSHIST` at anchor `X1` produces:

```
X1        the formula text (as a string)
X2:Z2     header row: 'Date' | '<tag> - CLOSE' | ...
X3:Z…     data rows, newest first
```

The exact extent is also published as a defined name
`CvFunction_<row>_<col>`, e.g. `=Sheet1!$C$1:$D$1,Sheet1!$B$2:$D$24` — the second
area is the header+data block. This is the reliable extractor; `CurrentRegion` is a
fallback.

Error behaviour differs by function and **must be handled differently**:

- `CVTSHIST` **degrades per column**: a bad tag yields the literal string
  `Bad tag: <tag>` in that column's first data cell, other tags in the same call
  return normally. Verified with a mixed-validity call.
- `CVMETADATA` usually degrades per row
  (`Error: Invalid Tag / No data available. Tag = …`), but **some tags hard-fail the
  entire batch to `#VALUE!`** — `RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y` does this even
  alone. A batch returning `#VALUE!` must be bisected, not discarded.
- Pending async values arrive as COM ints: `#GETTING_DATA` = `-2146826245`,
  `#N/A` = `-2146826246`. A poller that treats "non-empty" as "done" reads a
  sentinel as data — the first PoC did exactly this.
- Dates come back **either** as Excel serials (`46238.0`) **or** as
  `pywintypes.datetime`, depending on the number format the add-in applied. Parsers
  must accept both.

### Tag families verified live

Valid: `RATES.OIS.<CCY>_<INDEX>.PAR.<tenor>` (USD_SOFR, GBP_SONIA, CAD_CORRA,
AUD_AONIA, CHF_SARON), `.FWD.<exp>.<tenor>`, `RATES.OIS_MEETING.USD.<yyyy>.<yyyymmdd>`,
`RATES.INVOICESPREAD.USD.<tenor>`,
`RATES.OIS_INVOICESPREAD.USD_SOFR_FRONTMONTH.<tenor>`,
`RATES.TSY.TSY.OTR.<tenor>.{YIELD,PRICE}` (description carries the ISIN),
`RATES.VOL.<CCY>.ATM_RFR.NORMAL.ANNUAL.<exp>.<tenor>`,
`RATES.VOL.<CCY>.OTM_RFR.NORMALABSOLUTE.ANNUAL.OTM_{,M}<bp>.<exp>.<tenor>` (USD, EUR),
`RATES.BONDS.BY_COUNTRY.…`, `RATES.CURVE.…` via `CVCURVE`/`CVCURVEBOND`.

Rejected: `EUR_ESTR` and `JPY_TONA` return "No data available" — the correct index
tokens for those currencies are unknown and must be discovered, not guessed. This is
precisely why builders are validated against `CVMETADATA` rather than assumed.

### Catalog

There is **no tag catalog on disk**, and the endpoints the add-in uses to populate
its TagBrowser (`chartingbe/rest/feed/DataExplorerFeed6/dag/SERIES`, `.../CURVE`,
`relval/marketdatanamemap`) sit behind the same auth wall. Full coverage is therefore
delivered as **grammar + curated builders + `CVMETADATA` validation**, not as
auto-enumeration.

## Design

Four units under `MDP/CitiVelocityExcel/`, each usable and testable alone.

### 1. `com_client.py` — `CitiVelocityExcelClient`

Owns the COM bridge and nothing else.

- **Connect:** `GetActiveObject("Excel.Application")`. If absent, raise a single
  actionable error: *"No running Excel with the Citi Velocity add-in. Open Excel and
  sign in to Velocity."* Never spawns Excel (spawned instances do not authenticate).
- **Readiness probe:** `=CVTODAY()`; `#NAME?` means the add-in is loaded but not
  signed in — distinct error message from "no Excel".
- **Write isolation (the crash mitigation) — addresses both observed triggers:**
  - one dedicated scratch **workbook**, created on connect, closed on exit;
  - requests are **serialised** through a lock; no concurrent writes;
  - **no-overlap:** each request gets its own anchor on a sheet, placed below the
    furthest extent any previous block reached, with a wide margin. A request is
    never written into, or adjacent to, a region that is still live;
  - **delayed teardown:** after the block is read, the sheet/region is *not* cleared
    or deleted immediately. Teardown waits for the add-in's queued post-write actions
    (`ExcessClr`, `Format`, `AutoFit`) to drain, then happens at workbook close.
    Deleting a sheet with outstanding actions is itself a crash trigger;
  - the workbook is never saved, and the user's workbooks are never touched;
  - liveness is checked before and after each call, and a `com_error` raises a clear
    "Excel died mid-request" rather than triggering a retry storm.
- **Read:** resolve the `CvFunction_<r>_<c>` defined name for the extent
  (`CurrentRegion` fallback), poll past `#GETTING_DATA`/`#N/A` with timeout, then
  parse: drop formula row, take row 2 as headers, coerce the date column (serial *or*
  datetime), coerce values to float, map `Bad tag: …` cells to a per-tag failure.
- **API:** `fetch_timeseries(tags, freq, period=None, start=None, end=None,
  price_point="CLOSE") -> dict[tag, pd.Series]`, plus `latest()`, `snapshot()`,
  `metadata()`, `curve()`, `curve_bond()`.
- **Batching:** tags are chunked into one `CVTSHIST` per chunk (chunk size a tunable,
  default sized to the proven 44-tag curve export). `CVMETADATA` batches **bisect on
  `#VALUE!`** to isolate a poison tag rather than losing the batch.

### 2. `tags.py` — grammar and curated builders

- Pass-through: any string starting `RATES.` is accepted unchanged, so nothing in the
  namespace is out of reach.
- Typed builders per verified family: `ois_par`, `ois_fwd`, `swap_spread`,
  `invoice_spread`, `invoice_spread_frontmonth`, `treasury_otr`, `vol_atm`, `vol_otm`,
  `meeting_priced`, `bonds_by_country`. Each returns canonical tag strings.
- `validate(tags) -> dict[tag, Metadata | error]` round-trips through `CVMETADATA`
  (with bisect), so a builder's output can always be checked before a large pull.
  Builders are **verified against this**, never assumed correct — the `EUR_ESTR` /
  `JPY_TONA` misses are the standing reminder.

### 3. `cache.py` — incremental parquet store

- Keyed `(tag, freq, price_point)`, one parquet per key under a
  `reference_data_cache`-style tree, mirroring the layout already used elsewhere in
  the repo.
- On read: serve cached rows, fetch only the missing head/tail, merge, dedupe on
  timestamp, keep last.
- `CVMETADATA`'s **history start date** bounds how far back a full backfill can go, so
  the cache knows when it already holds everything available.
- Intraday (`MI01`) and daily are separate keys — never mixed.

### 4. `source.py` — `CitiVelocityExcelSource`

MDP source registered as **`citivelo_excel`**, exposing `get_data(request)` and
`bulk_get_data(request)` over cached-then-live tag frames, so it slots into the same
dispatch the timeseries notebooks already use. Distinct from the existing curve-building
`citivelo` source in `IRSwapsMDP` (that one builds rateslib curves from a saved
workbook; this one fetches arbitrary series live).

### Data flow

```
notebook / TB
  -> CitiVelocityExcelSource.get_data({"tags": [...], "freq": "DAILY", ...})
       -> cache.py           (hit? serve; partial? compute missing span)
            -> CitiVelocityExcelClient.fetch_timeseries(missing span)
                 -> scratch sheet -> =CVTSHIST(...) -> poll -> read block -> parse
            -> merge + persist parquet
  <- tidy DataFrame, DatetimeIndex ascending, one column per tag
```

### Error handling

| Condition | Behaviour |
|---|---|
| No Excel running | Raise with instruction to open Excel and sign in |
| Excel running, not signed in (`#NAME?`) | Distinct raise; do not retry |
| Bad tag in `CVTSHIST` | That tag's column marked failed; other tags still returned |
| `#VALUE!` from `CVMETADATA` batch | Bisect to isolate the poison tag |
| Async never settles within timeout | Raise with the tag list and elapsed time |
| `com_error` mid-request (Excel died) | Raise immediately; never retry into a dead process |
| Solver/parse anomaly | Raise — no silent NaN columns (repo precedent: `_assert_risk_populated`) |

### Testing

- **Hermetic unit tests** inject a fake COM object that records written formulas and
  replays canned `CurrentRegion` tuples. Covers: sentinel polling, serial-vs-datetime
  dates, `Bad tag:` per-column failure, `#VALUE!` bisect, cache merge/dedupe, every
  tag builder. No Excel required.
- **Mutation check** (per repo practice): the parser tests must fail when the sentinel
  handling is reverted to the naive "non-empty means done" predicate that the first
  PoC got wrong.
- **One `integration`-marked test** hits real Excel and self-skips when no
  authenticated add-in is present — same shape as
  `tests/test_citi_velocity_intraday_curve.py`.
- Fast gate: `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`.

### Deliverable notebook

`notebooks/timeseries/citivelo_excel.ipynb` — pulls a swap curve, a vol-cube slice,
and an intraday UST series; shows builders, validation, and cache reuse.

## Scope

Scope is not a preference — it is fixed by entitlements. The add-in logs exactly what
this user may call:

```
Registering functions: CVCURVE, CVCURVEBOND, CVLATEST, CVMETADATA, CVNOW,
                       CVSNAP, CVSTREAM, CVTICK, CVTODAY, CVTSHIST

User does not meet entitlement requirements for functions:
  CVCALCDERIVATIVES, CVDCAPFLOOR, CVDCASH, CVDCMSCAPFLOOR, CVDFRA, CVDINFLSWAP,
  CVDMIDCURVE, CVDSINGLELOOKSPREADOPTION, CVDSWAP, CVDSWAPTION, CVLADDER,
  CVSCENARIOANALYSIS, CVTAG, CVPORTFOLIOLIST, CVPORTFOLIOFILTER,
  CVPSNAPSHOTCONSTITUENTS, CVGETPORTSCOOBY, CVGETPORTDATESSCOOBY,
  CVGETPORTLISTSCOOBY, CVSAVEPORTSCOOBY, CVLATESTSCOOBY, CVSNAPSCOOBY,
  CVTSHISTSCOOBY
```

**In v1:** timeseries (`CVTSHIST`), snapshot (`CVSNAP`), latest (`CVLATEST`),
metadata (`CVMETADATA`), curves (`CVCURVE`, `CVCURVEBOND`) — i.e. every entitled
fetch function. `CVNOW`/`CVTODAY`/`CVTICK` are trivial helpers used only as
readiness probes.

**Out of v1, because they are not entitled at all:** the `CVD*` derivative pricers,
`CVCALCDERIVATIVES` (raptor), `CVLADDER`, `CVSCENARIOANALYSIS`, and every portfolio /
`*SCOOBY` function. These cannot be built against even if wanted — calling them
returns an entitlement failure, not data.

**Out of v1 by choice:** streaming (`CVSTREAM`) — entitled, but an RTD push model
needing a live event loop rather than a request/response fetch.

## Open questions

1. **Crash isolation — now the top priority, not a nicety.** Excel was crashed twice
   during design probing, each time taking the user's open workbook down with it.
   Does a `/x` instance authenticate when the user's Excel is *closed*? If yes, the
   bridge runs in a sacrificial process and this whole risk class disappears. This
   should be settled **before** implementation begins, since a positive answer
   simplifies the write-discipline requirements considerably. Requires the user to
   close their Excel briefly.
2. **Correct index tokens** for EUR/JPY/other OIS curves — to be discovered via
   `CVMETADATA` probing, then encoded in the builders.
3. **`SWAP_SPREAD` tenor domain** — `10Y` hard-fails while `1Y` is used by the add-in's
   own saved functions; the valid set needs mapping.
4. **Batch ceiling** for `CVTSHIST` tags per call — 44 is proven, the true limit is
   unknown.

## Risks

- **Shared-process crash** (above). Mitigated by write isolation; not eliminated.
- **Add-in updates** (Squirrel auto-update is enabled) may change UDF signatures or the
  output layout. The parser keys off the published `CvFunction_*` name and the header
  row rather than fixed offsets, which is the most stable contract available.
- **Requires a human-logged-in Excel** — this cannot run on a headless scheduler. That
  is inherent to the auth model, and matches how Velocity data already reaches the repo.
- **Entitlements** bound coverage: tags outside the user's entitlement return
  "No data available" and are indistinguishable from nonexistent tags.
