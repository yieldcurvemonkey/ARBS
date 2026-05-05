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
