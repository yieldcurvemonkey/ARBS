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

### Bonds are a two-step mechanism, not a tag family

`RATES.BOND` has **zero children** in the DAG — bonds are not enumerated there,
because the ISIN universe is far too large for a browse tree. They are reached in
two steps:

1. **`CVCURVEBOND` is the universe.** A curve tag
   `RATES.BONDS.BY_COUNTRY.<CTRY>.<CCY>.ASSET_TYPE_<TYPE>.<MEASURE>.<yyyymmdd>`
   returns a grid of `Date | ISIN | Description | <measure>`, e.g. 349 rows for
   `USA.USD.ASSET_TYPE_GOVT`, with descriptions like `T 1.25 08/15/2031`.
   Note `RATES.BONDS` (plural) is a **separate curve namespace** — it is not one of
   the 33 timeseries families.
2. **`RATES.BOND.<ISIN>.<value>` is the timeseries** for one bond.

Universe (probed 2026-08-04): **2,162 distinct ISINs** over 18 countries and three
asset types — `GOVT`, `AGENCY`, `COVERED`. `CORP`, `MUNI`, `SUPRA`, `SSA`, `TIPS`,
`INFL`, `ILB`, `SOVEREIGN`, `QUASI` all return nothing, as do `CAN` and `AUS`
entirely. Largest: USA GOVT 349, JPN GOVT 326, FRA AGENCY 192, CHN GOVT 189,
ITA GOVT 122, DEU COVERED 121.

**Value vocabulary is 8**, established by probing rather than taken from the desk's
measure catalogue:

```
PRICE  YIELD  SPREAD_TSY  ASW_4_USD  ASW_4_JPY  OAS  DURATION  DV01
```

The measure catalogue supplied by the desk (`MARKET_DATA` / `REFERENCE_DATA`,
43 entries) is **not** the tag vocabulary and must not be used as one:

- every `REFERENCE_DATA` field (`SEDOL`, `RIC`, `ISSUERNAME`,
  `MATURITYDATEYYYYMMDD`, …) is rejected as a tag — reference data is static and
  not served as a timeseries;
- `DOLLAR_DURATION` is the catalogue's name but the tag is **`DV01`**;
- `YIELD_WORST`, `YIELD_NEXT`, `ZSPREAD`, `CAS`, `CONVEXITY`, `ASW`, `ASW_4_EUR`,
  `ASW_4_GBP`, `ASW_4_CHF` are recognised but empty — and empty on agency paper
  too, so this is not a "straight Treasury has no call" artefact;
- `OAS` needs a window longer than 1W to show data, so a short-window probe alone
  would have wrongly discarded it.

The two surfaces disagree, which the builders must respect: `CVCURVEBOND` accepts
`YIELD PRICE SPREAD_TSY ASW_4_USD OAS DURATION` but **not** `DV01` or `ZSPREAD`,
while `DV01` *is* a valid per-bond timeseries value.

**`ASW_4_<CCY>` is a sparse cross-currency matrix, not the bond's own currency.**
A bund carries `ASW_4_USD/GBP/CHF/AUD` but **not** `ASW_4_EUR`; a gilt carries
`ASW_4_EUR/GBP/AUD`; a Treasury carries `ASW_4_USD/JPY`. There is no derivable
rule — which legs are populated must be discovered per bond. `ASW_4_AUD` and `CAS`
(the latter populated on CNY/KRW paper) were missed entirely by a first sweep that
sampled only USD instruments; sampling one bond per currency is the minimum for
this family.

Exhaustive validation of 2,162 ISINs × 8 values gave **12,570 valid tags**:

| value | coverage |
|---|---|
| `PRICE` / `YIELD` / `DURATION` | 97% |
| `SPREAD_TSY` | 83% |
| `DV01` | 77% |
| `OAS` | 65% |
| `ASW_4_USD` | 50% |
| `ASW_4_JPY` | 15% (≈ the JGB universe) |

Zero tags were rejected — every ISIN × value combination is either populated or
empty, never invalid, so the tag grammar itself is confirmed.

### Operational hazard: never kill a probe mid-flight

Killing a COM client while Excel is serving a call can wedge Excel's OLE server:
the process stays alive, idle and responsive to the UI, but every automation bind
fails (`GetObject` returns an object exposing no properties; `Application.Workbooks`
raises `AttributeError`). Clearing win32com's `gen_py` cache does not help.

Restarting Excel does restore the add-in, but **the login is slow — about 13
minutes** between `CustomRibbon.onLoad` and
`User session resumed → Registering functions`. Nothing is logged in between, so
the instance looks permanently stuck. Four launch paths were tried (`DispatchEx`,
`Start-Process`, shell/`explorer.exe`, forced foreground activation) and every one
was wrongly written off as failed before the login landed; the shell-launched
instance signed in on its own at the 13-minute mark.

Practical rules:

- a readiness poll must wait **≥15 minutes** before concluding the add-in is dead;
- polling COM every couple of seconds during startup is counter-productive — the
  login runs through `ExcelAsyncUtil.QueueAsMacro` and needs Excel idle;
- a harvest/validation run must be allowed to finish or be stopped through its own
  checkpointing, never `Stop-Process` — that is what wedges the OLE server in the
  first place, and the recovery costs ~15 minutes.

### Intraday capability is per-family, and not uniform

`Velocity_Charting_Intraday_Tags.xlsx` (supplied by the desk) maps tag regex →
intraday capability. This is a hard constraint on what a fetcher can ask for, so the
cache layer must key on it rather than assume every family supports every frequency:

| family | finest freq | intraday OHLC | EOD OHLC | streaming |
|---|---|---|---|---|
| `RATES.OIS.*` | **SE10** (10-second) | no | no | yes |
| `RATES.TSY.OTR.*` | **SE10** | no | no | yes |
| `RATES.FUTURES.*` | MI01 | **yes** | **yes** | yes |
| `RATES.SWAP.*PAR/FWD` | MI01 | no | no | yes |
| `RATES.SOV.*OTR` | MI01 | no | no | yes |
| `RATES.VOL.USD.ATM.NORMAL.ANNUAL.*` | MI01 | no | no | yes |
| `RATES.SWAP.*SWAP_SPREAD/CURVES/BFLY`, `RATES.SOV.*CURVES/BFLY`, `RATES.VOL…DAILY` | MI01 | no | no | **no** |

Two consequences: `PricePoint="OHLC"` is only meaningful for `RATES.FUTURES` in the
rates complex, and only `RATES.OIS` / `RATES.TSY.OTR` go finer than one minute. Note
this workbook describes *intraday* capability — it is not a substitute for the
catalog harvest, which is what enumerates the tags themselves.

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

### Catalog — solved by harvesting the Function Builder, not by guessing

There is no tag catalog on disk, and the endpoints that populate the add-in's
TagBrowser (`chartingbe/rest/feed/DataExplorerFeed6/dag/SERIES`, `.../CURVE`,
`relval/marketdatanamemap`) sit behind the same auth wall. The first version of this
spec therefore proposed "grammar + curated builders + guessing". **That approach was
tried and is provably insufficient.**

Generate-and-test over plausible token spellings found 14 OIS currencies but got the
two biggest ones wrong and missed six curves outright. The real identifiers, from the
add-in itself:

| guessed | actual |
|---|---|
| `EUR_ESTR` / `EUR_ESTER` / `EUR_EONIA` | **`EUR_EUROSTR`** (and `EUR_EONIA`, stale) |
| `USD_FEDFUNDS` / `USD_FF` | **`USD_FEDFUND`** |
| — | **`JPY_TONAR_JSCC`**, **`JPY_TONAR_LCH`** (CCP-qualified) |
| — | **`DKK_TNDKK`**, **`MXN_T_FONDEO`** |
| sub-types PAR/FWD/SWAP_SPREAD | + **`ROLL_CARRY`**, **`BFLY`**, **`CURVES`** |

No amount of further guessing closes that gap, and a builder that silently emits
wrong tags is worse than none.

**The Function Builder's DATA BROWSER exposes the whole DAG through UI Automation.**
Its window (`HwndWrapper[FullTrustSandbox…]`, title `Function Builder`) contains a
category `List`; selecting a node materialises the next level as a further `List`.
Walking that tree yields the authoritative catalog — it is by construction the same
tree the add-in accepts.

`RATES` has **33 families**:

```
OIS  OIS_MEETING  OIS_INVOICESPREAD  INVOICESPREAD  SWAP_LIBOR  SWAP_INTERNAL
TSY  SOV  SSA  SSA_CS  BOND  VOL  MIDCURVES  SPREAD_OPTIONS  FUTURES
BASIS_SWAPS  XCCY_SWAP  XCCY_OIS_SWAP  XCCY_SWAP_IUO  XCCY_OIS_SWAP_IUO
XCCY_BASIS_INTERNAL  FRA  FRA_OIS  INFLATION  MONEY_MARKETS  REPO  BENCH_RATES
MBS  AGENCY_INVENTORY  FLOWS  FORECAST  POS_MON  LIQUIDITY_IDX
```

with e.g. `OIS` → 20 curves, `SWAP_LIBOR` → 46 currencies, `XCCY_SWAP` → 23,
`VOL` → 11, `FUTURES` → 13 exchange-qualified contracts (`XCBT_TY`, `XCME_ED`,
`XEUR_RX`, …), `BASIS_SWAPS` → 6 named bases (`SOFR_FEDFUND_BASIS`,
`EUROSTR_EURIBOR_BASIS`, `3S1S_BASIS`, …).

**The catalog is a grammar, not a tag list.** Walking to every leaf was attempted
and abandoned on evidence:

- `RATES.XCCY_OIS_SWAP` is `ccy1 → ccy2 → SPOT → tenor → {BASE_LEG, SPREAD_LEG} →
  BASIS_SPREAD` — one leaf per node, so ~20,000 UI selections at ~8s to enumerate
  a grammar that is just *tenor × leg*. `RATES.MBS` is the same trap over coupons.
- Switching the walk from breadth-first to depth-first did **not** help (8.1s/node
  vs 7.0): the cost is UIA tree traversal, not path re-descent.
- `RATES.VOL` is ~23,000 tags for USD alone and ~250,000 across 11 currencies.
  Validating that many at 15 tags per ~2s call is ~9 hours.

Exhaustive enumeration is therefore neither affordable nor needed. What a notebook
actually does is ask for *one* series; the library generates that tag from the
grammar and `CVTSHIST` answers in under a second. So the catalog stores **structure
+ per-branch grammar**, and validation happens on demand.

**Grammar must be per-branch, never pooled per level.** Pooling `RATES.VOL`'s
level-4 vocabulary gives `[1M, 1Y, 3M, 6M, BLACK, NORMAL, NORMALABSOLUTE,
FWDPREMIUM, NORMALSKEW]` — expiries and vol conventions mixed, because each measure
has its own shape. Generating from the pooled vocabulary produced 2,163 VOL tags of
which **zero** were valid. Per-branch shapes fixed it:

```
VOL.<ccy>.ATM       {NORMAL,BLACK,PREMIUM,FWDPREMIUM} x {DAILY,ANNUAL} x expiry x tenor
VOL.<ccy>.ATM_RFR   {NORMAL,BLACK,PREMIUM,FWDPREMIUM} x {ANNUAL}       x expiry x tenor
VOL.<ccy>.OTM_RFR   {PREMIUM,NORMALABSOLUTE,NORMALSKEW,RISK_REVERSAL} x [ANNUAL] x OTM_* x expiry x tenor
VOL.<ccy>.VOL_RATIO {1M,3M,6M,1Y} x expiry x tenor            <- one level shallower
MIDCURVES.<ccy>     {OPT_PAY,OPT_REC,OPT_STR} x {PRICE,VOL} x expiry x <1Y1Y>
SPREAD_OPTIONS.<ccy>{OPT_CAP,...}             x {PRICE,VOL} x expiry x <2Y5Y>
```

Depth varies *within* a family and even between conventions of one measure:
`ATM.NORMAL` carries a `DAILY|ANNUAL` basis level while `ATM.BLACK`, `ATM.PREMIUM`
and `ATM.FWDPREMIUM` go straight to expiry. Any generator must treat the shape as
branch-local and confirm with `CVTSHIST`.

**The generator must be path-consistent, not level-consistent.** Storing "the
vocabulary at each level" and sampling one entry per level produces combinations
that exist on no real path — e.g. `OTM_RFR` at level 0 with `BLACK`/`DAILY` below,
which only exist under `ATM`. That scored 17% on VOL while scoring 100% on
`XCCY_OIS_SWAP` purely because the latter is homogeneous. The correct rule is
recursive and keeps every tag on a recorded path:

```
tags(N) = for each option O of N:
             if N/O was recorded  -> seg(O) + "." + tags(N/O)
             else                 -> seg(O) + "." + tags(first recorded child)
```

Unexpanded siblings inherit the shape of the sibling that was expanded — the
working assumption below the fan-out depth.

Final validation of 1,546 path-consistent tags: **94% shape-correct**.

| family | valid | empty | failed | shape-ok |
|---|---|---|---|---|
| `XCCY_OIS_SWAP` | 1,097 | 0 | 0 | **100%** |
| `INFLATION` | 153 | 31 | 0 | **100%** |
| `VOL` | 100 | 75 | 90 | 66% |

`RATES.XCCY_OIS_SWAP` resolves to
`<ccy1>.<ccy2>.<fwd>.<tenor>.{BASE_LEG,SPREAD_LEG}.BASIS_SPREAD` — seven segments.

**Legacy non-RFR vol branches are deprecated.** Split by measure, every `_RFR`
variant is **100% shape-correct with zero failures** (`ATM_RFR`, `OTM_RFR`,
`REALIZED_RFR`, `VOL_RATIO_RFR`), while their legacy twins `ATM`, `OTM`,
`REALIZED`, `VOL_RATIO` account for all 90 failures and return no data. Builders
must default to `_RFR`; the whole of VOL's residual 34% is these dead branches.

Harvest mechanics that matter:

- **Breadth-first with a depth cap.** Depth-first starves: `RATES.MBS` is a coupon ×
  coupon × coupon cross product and consumed the entire budget before reaching any
  other family.
- **Cross-product subtrees are recorded but not expanded.** `BFLY`, `CURVES` and
  `ROLL_CARRY` draw their legs from the same tenor axis as `PAR`, so they are
  generated, not enumerated.
- **Stale-read guard is mandatory.** After selecting a node the child `List` briefly
  still holds the *previous* node's children — `RATES.SPREAD_OPTIONS` was recorded
  with `RATES.REPO.*` children before this was caught. Children are always named
  `<parent>.<something>`, so the harvester waits for that prefix invariant to hold
  and retries otherwise. Without the guard the catalog is silently wrong.
- Selection uses the UIA **SelectionItem pattern**, not mouse clicks: the Function
  Builder window is positioned off-screen (negative Y), so coordinate clicks fail.
- Incremental selection: selecting level N leaves 0..N-1 selected, so walking
  siblings costs one select rather than re-descending from the root.

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

### 2. `catalog.py` + `catalog_harvest.py` — the tag universe

- `catalog_harvest.py` walks the Function Builder DATA BROWSER over UI Automation
  (breadth-first, depth-capped, stale-read guarded — see above) and writes a
  catalog JSON. This is an **occasional offline refresh**, not a runtime dependency:
  it needs the Function Builder open, takes minutes, and its output is committed.
- `catalog.py` loads that catalog and exposes it: `families()`, `children(node)`,
  `search(pattern)`, `tenors(node)`. Builders are **derived from the catalog**
  rather than hand-written, so they cannot drift from what the add-in accepts.
- Pass-through remains: any `RATES.*` string is accepted unchanged, so a tag newer
  than the catalog is never blocked.
- `validate(tags)` confirms a tag list against the live add-in before a large pull —
  and it uses **`CVTSHIST`, not `CVMETADATA`** (below).

### 2b. Validation must go through `CVTSHIST`

`CVMETADATA` is not a sound validator. It returns a hard `#VALUE!` for tags that
exist and serve data but carry no metadata: it reported **zero** valid tenors for
`RATES.OIS.USD_SOFR.SWAP_SPREAD`, hard-failing on exactly the liquid ones
(1M 3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 20Y 30Y). `CVTSHIST` serves all eleven. Trusting
`CVMETADATA` would have silently dropped a whole family.

`CVTSHIST` is the right validator on every count: it is the path we actually fetch
through, it degrades per column (`Bad tag: <tag>` in that column's first data cell)
rather than poisoning the batch, and it validates many tags per call.

`CVMETADATA` stays useful for what it is good at — description, history start/end,
last-update times — with bisect-on-`#VALUE!` to isolate a poison tag.

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
