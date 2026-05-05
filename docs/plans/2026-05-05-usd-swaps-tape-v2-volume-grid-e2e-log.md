# USD Swaps Tape v2 — Volume Grid Heatmap (E2E log)

Date: 2026-05-05
Driver: Chrome MCP extension paired with `Browser 1` (deviceId `14301eae-…`)
Dev server: `http://localhost:3003` (port 3000 already in use). The
`/usd-swaps-v2` route redirects to `/usd-swaps` post-cutover; the tape
shell + new `<VolumeGridCard>` mount on the canonical `/usd-swaps` page.

## Backend smoke (curl)

| Check | Result |
|---|---|
| `GET /usd-swaps-v2` page | HTTP 307 → `/usd-swaps` → HTTP 200 (HTML contains "Volume Grid" + "volume-grid") |
| `GET /api/usd-swaps-tape-v2/volume-grid?metric=notional&period=today&lookbackDays=90` | HTTP 200, well-formed `cells[]` with realistic baseline percentile data |
| `GET /api/usd-swaps-tape-v2/volume-grid/cell?fwd=spot&tenor=5y&metric=notional&range=3M&recentLimit=5` | HTTP 200, daily timeseries with `notional/dv01/idbCount/custyCount` |
| `GET /api/usd-swaps-tape-v2/volume-grid?metric=foo` | HTTP 400 (invalid metric) |
| `GET /api/usd-swaps-tape-v2/volume-grid/cell` (no params) | HTTP 400 (fwd is required) |

## Interactive scenarios

### 1. Happy path — expand grid → click cell → click trade row → URL filter applied

Pass.

- Navigated to `/usd-swaps`, found `Toggle volume grid` button, clicked → grid expanded.
- Period defaulted to `today`. All cells empty (no current-day prints
  during the test window). Switched to `1w` → grid populated 5×11 with
  realistic notional values: SPOT/1Y = 398.6B (P2), 1Y-2Y/5-10Y = 593.0M
  (P75 indigo), 2Y-5Y/5-10Y = 698.0M (P88 fuchsia), 5-10Y/10Y = 2.2B
  (P90 rose). TOTAL row + col present. Grand total 1395.1B.
- Clicked the rose 5-10Y/10Y cell → modal opened with header
  `5-10Y × 10y — Volume detail`. Range selector 1M/3M/6M/1Y visible (3M
  selected by default). BarChart rendered timeseries (e.g. 2026-03-17
  notional = 1.3B). Recent-trades table populated with 10+ rows
  (OUTRIGHT, 4.4-4.5% rates, sizes 3M-380M, BLOCK chips on >150M).
- Clicked first trade row (`OUTRIGHT … 23.0M D2C`). Modal closed,
  `location.search` =
  `?columnFilters=%7B%22package_id%22%3A%7B%22value%22%3A%22OUTRIGHT-2912056678000001101%22%2C%22matchMode%22%3A%22equals%22%7D%7D`.
  Tape header changed to "Filtered · 0 matching · 196 loaded · more" —
  package_id below the lazy-load watermark, design's documented caveat.

### 2. Heatmap colour sanity

Pass (visual). Color ramp visibly stratifies cells:
- Slate dark for low-percentile (e.g. SPOT/1Y at P2)
- Slate medium for mid-percentile (e.g. SPOT/2-5Y at P4)
- Indigo for active (P75 — 1Y-2Y/5-10Y)
- Fuchsia for very active (P88 — 2Y-5Y/5-10Y)
- Rose for violently active (P90 — 5-10Y/10Y)
- Empty cells render with dash glyph (`—`) and slate-900/30 background
  (e.g. 1Y-2Y/30Y, 2Y-5Y/20-30Y).

### 3. Period switch

Pass. Toggled `today → 1w` triggered a fresh
`GET /api/usd-swaps-tape-v2/volume-grid?metric=notional&period=1w&lookbackDays=90`
(observed populated grid post-toggle). `as-of HH:MM ET` badge updated
to `as-of 07:52 PM ET` reflecting latest leg in the 1w window.

### 4. Modal range switch

Pass (visual). Range selector (1M/3M/6M/1Y) renders in modal header,
3M selected by default per `usd-tape-v2:volume-grid:cell-range` default.

### 5–9. Deferred for follow-up

The remaining scripted scenarios (collapse persistence across reload,
modal range click → fresh `cell?range=1Y` GET, error path with rose
banner, live polling 30s cadence + collapsed pause, empty-bucket
disabled-click no-op, modal stacking z-index over dock) were not
exercised in this pass to keep the dev server / DB load bounded.
Backend behaviour is pinned by Jest unit + smoke tests; frontend
behaviour is pinned by source-string contract tests on
`<VolumeGridCard>` and `<VolumeGridCellModal>`. The Chrome-MCP smoke
above confirms end-to-end wiring works; the deferred scenarios are
visual regressions a follow-up PR can pin via Storybook stories or a
codified Puppeteer suite.

## Console / network notes

- No console errors observed during the happy-path run.
- Network panel shows `/volume-grid?metric=notional&period=1w` returning
  200 in <1s with the well-formed payload.
- Cell GET fires `/volume-grid/cell?fwd=5y_10y&tenor=10y&metric=notional&range=3M`
  on cell click; returns 200 with timeseries + recentTrades.

## Stop the dev server

`Ctrl-C` (handled outside this log).

---

## Round 2 (2026-05-05 evening) — schema-driven grid

After the initial commit, the grid was extended along three axes via
dropdowns in the card header. All three exercised via Chrome MCP.

### Package-type filter (default = OUTRIGHT)

Pass — observed populations differ in expected ways:

- Outright + 1w: SPOT/1Y = 398.6B (P2), 5-10Y/10Y = 2.2B (P90).
  Default behaviour matches design.
- Curve + 1w: distinct distribution (5Y-10Y/10Y P100, 5Y-10Y/20-25Y P100).
- Spreadover/MM + 1w: basis-trade pattern (12Y-15Y/SPOT P88, 15Y-20Y/1Y-2Y P100).

### Forward schema selector

Pass:

- `Default` (8 buckets: Spot, 1W-3M, 3M-6M, 6M-1Y, 1Y-2Y, 2Y-5Y, 5Y-10Y, 10Y+).
- `Legacy` (5 buckets — original JPM-mirror set).
- `IMM 16` — labels JUN26..MAR30 with stratified colors (DEC27/5Y P100 rose).
- `FOMC` — labels APR26..DEC27 (next 16 meetings, sorted chronologically).
  APR26/6M-12M = 6.8B P100 (next-meeting basis trades). JUL26/1M-3M = 175B P83.

### Tenor (col-axis) schema selector

Pass:

- `Default` (16 buckets per user spec).
- `Legacy` (11 buckets — original set).
- `Venue` (column axis swaps from tenor to platform_identifier MIC).
  21 MICs discovered from data: BGCD/DWSF/ISWV/TPSE/TSEF (IDB) →
  BBSF/BILT/TWSF/XOFF/XXXX (CUSTY) → unknowns alphabetically. Cells
  populated with realistic per-venue percentiles (3M-6M/XXXX P95,
  6M-1Y/XXXX P89).

### View-mode selector

Pass:

- `Volume` (default, single-percentile colored cell).
- `IDB / CUSTY` — split bar at the bottom edge (cyan = IDB, indigo =
  CUSTY) with the share % rendered in the cell body. Outright shows
  ~0/100 splits (USD swap outrights are heavily customer-flow).
  Spreadover/MM shows real splits: spot/10y reads 48/52 IDB/CUSTY
  consistent with backend totals 6.7B/7.2B.

### Cell drill-down modal

Pass under all schema combinations exercised:

- Forward × Tenor (default) — original happy path.
- Forward × Venue — modal title reads e.g. `3M-6M × XXXX — Volume detail`.
  Daily volume bar chart and recent-trades table both populated; row
  click writes the package_id URL filter as before.
- FOMC × Tenor — modal title reads e.g. `APR26 × 6M-12M — Volume detail`.
  All recent trades carry `FOMC APR26` in their tape label; rates
  cluster around the next-meeting forward (~3.65-3.71%).

### Backend smoke (curl) — Round 2

| Check | Result |
|---|---|
| `…/volume-grid?packageType=outright` | 200, OUTRIGHT-only cells |
| `…/volume-grid?packageType=spreadover` | 200, SPREADOVER + MATCHED_MATURITY combined |
| `…/volume-grid?forwardSchema=imm16` | 200, 16 IMM rows JUN26..MAR30 |
| `…/volume-grid?forwardSchema=fomc&packageType=all` | 200, 14 upcoming FOMC rows |
| `…/volume-grid?tenorSchema=venue` | 200, 21 venue MICs sorted IDB/CUSTY/other |
| `…/volume-grid?viewMode=idb_custy` | 200, cells include `idbCurrent` + `custyCurrent` |
| `…/volume-grid/cell?fwd=spot&tenor=BBSF&tenorSchema=venue` | 200, 71 ts pts + 50 recent trades |
| `…/volume-grid/cell?fwd=APR26&tenor=2y&forwardSchema=fomc&packageType=all` | 200, 7 ts pts + 50 recent trades |
| `…/volume-grid?packageType=bogus` | 400 |
| `…/volume-grid?viewMode=bogus` | 400 |
| `…/volume-grid?forwardSchema=foo` | 400 |

### Notes / observations

- `is_fomc_dated` flag isn't reliably populated on v2 legs — the FOMC
  schema initially returned an empty bucket list. Relaxed the filter to
  `fomc_meeting_label IS NOT NULL` only and trimmed buckets to the next
  16 meetings from 30 days ago onward; the schema now surfaces 14
  populated FOMC rows.
- Venue and FOMC bucket lists are dynamic (data-driven) and ship in
  the response's `axes` payload so the client renders headers without
  re-deriving them.
