# USD Swaps Tape v2 — Volume Grid Heatmap (Design)

Status: design — implementation plan to be authored separately.
Owner: tape v2 dashboard.
Date: 2026-05-05.

## Problem

Traders looking at `UsdSwapsTradeTape` see a row-by-row tape but no
market-wide overview of where notional and risk are concentrating
relative to history. The institutional reference (e.g. JPM USD Swap
Trading Volume report) summarises this as a forward × tenor grid of
volumes versus 1-week and 1-month averages. We want an equivalent
heatmap on top of the tape, with each cell drillable into a per-bucket
timeseries and a recent-trades list.

## Goals

1. Always-visible top-of-page card showing per-bucket volume vs
   lookback. Glanceable in <1 second.
2. Heatmap colour intensity reflects "how unusually active" each
   bucket is right now versus the lookback baseline.
3. Click any cell → modal with daily volume timeseries + the latest N
   trades in that bucket. Modal stacks above the tape and dock.
4. Both notional and DV01 surfaced. Toggle, not stacked grids.
5. Live: refreshes on its own schedule when expanded; pauses when
   collapsed.
6. Stylistically consistent with the rest of the tape v2 shell:
   slate-950 chrome, indigo accents, dense mono typography.

## Non-goals (v1)

- Cross-asset (only USD swaps via `arbs_usd_swap_tape_legs_v2`).
- Bucket boundary configuration UI. Boundaries are server-hardcoded
  and match the JPM report.
- Lookback length UI knob. Defaults are wired in; we'll add knobs
  only if traders ask.
- Re-fetching tape rows older than the lazy-load watermark when the
  modal's "recent trade" click targets a package that isn't in the
  loaded set. v1 falls back to applying a `package_id` URL filter
  and lets the trader clear it if needed.
- Storybook stories. (Mentioned as optional; can land later.)

## Data backbone

All aggregation runs against `arbs_usd_swap_tape_legs_v2`.

Mandatory filters per `SDRUtils/CLAUDE.md`:

- `contributes_to_flow = TRUE` — excludes compression, clearing β/γ,
  AFFL, null-fill MODI, VALU spam.
- Use `original_execution_timestamp` (fall back to
  `execution_timestamp`) as the time anchor.

Bucket fields:

- `forward_start_years` → forward bucket (rows).
- `tenor_years` → tenor bucket (columns).

Both are populated as part of the v2 enrichment pipeline.

## High-level architecture

Approach X (chosen) — dedicated grid route + CSS-grid heatmap +
existing-pattern PrimeReact `Dialog` for the drill-down. See
"Implementation approaches" below.

```
+--------------------------------------------------------------+
| UsdSwapsTradeTape (orchestrator)                             |
|   <VolumeGridCard>                  <-- new top-of-page card |
|     useVolumeGrid()  -> /api/.../volume-grid                 |
|     <VolumeGrid>                                             |
|       <VolumeGridCell> * (5 rows + Total) x (11 cols + Total)|
|         click -> setSelectedCell                             |
|     <VolumeGridCellModal>                                    |
|       useVolumeGridCell() -> /api/.../volume-grid/cell       |
|       <ComposedChart> + <RecentTradesTable>                  |
|         row click -> onSelectPackage(packageId)              |
|   <TradeTapeTable>                                           |
|   <AnalyticsPanel>                                           |
+--------------------------------------------------------------+
```

## File layout

New:

- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.ts`
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts`
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.test.ts`
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.test.ts`
- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts` — single source of truth for bucket boundaries + SQL CASE expressions + WHERE-clause builders.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx` — pure render, no fetch.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/buckets.ts` — client-facing labels + humanise map.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/colorRamp.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGrid.test.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/colorRamp.test.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useVolumeGrid.test.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__/UsdSwapsTradeTape.volumeGrid.test.tsx` — RTL integration test.

E2E validation is **interactive via the Chrome MCP extension**
(`mcp__Claude_in_Chrome__*` tools); no codified Puppeteer suite for
this feature. See the Testing → E2E section for the scripted
checklist.

Modified:

- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx` — mount `<VolumeGridCard>` at top of shell; thread `onSelectPackage`.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/index.ts` — re-export `useVolumeGrid` and `useVolumeGridCell`.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__` — additional spec file (no edit to existing specs).

## Backend §1 — `/api/usd-swaps-tape-v2/volume-grid`

Returns the matrix in a single SQL pass.

### Request

`GET /api/usd-swaps-tape-v2/volume-grid?metric=notional&period=today&lookbackDays=90`

| Param | Allowed | Default |
|---|---|---|
| `metric` | `notional` \| `dv01` | `notional` |
| `period` | `today` \| `1h` \| `24h` \| `1w` | `today` |
| `lookbackDays` | 1..365 | 90 (52*7=364 used implicitly when `period=1w`) |

### Bucket SQL (forward, rows)

```
CASE
  WHEN forward_start_years IS NULL OR forward_start_years < 0.083 THEN 'spot'
  WHEN forward_start_years <  1.0 THEN '6m_1y'
  WHEN forward_start_years <  2.0 THEN '1y_2y'
  WHEN forward_start_years <  5.0 THEN '2y_5y'
  WHEN forward_start_years < 10.0 THEN '5y_10y'
  ELSE 'fwd_other'
END AS fwd_bucket
```

### Bucket SQL (tenor, cols)

```
CASE
  WHEN tenor_years <  1.5 THEN '1y'
  WHEN tenor_years <  2.5 THEN '2y'
  WHEN tenor_years <  4.5 THEN '2_5y'
  WHEN tenor_years <  5.5 THEN '5y'
  WHEN tenor_years <  9.5 THEN '5_10y'
  WHEN tenor_years < 11.0 THEN '10y'
  WHEN tenor_years < 19.5 THEN '10_20y'
  WHEN tenor_years < 21.0 THEN '20y'
  WHEN tenor_years < 29.5 THEN '20_30y'
  WHEN tenor_years < 31.0 THEN '30y'
  ELSE '50y'
END AS tenor_bucket
```

`fwd_other` rows are filtered out before `SELECT` so the grid only
emits the five forward buckets in the JPM screenshot.

### Window definition by `period`

| period | current window | baseline window unit | baseline count |
|---|---|---|---|
| `today` | 00:00 ET → now | full prior day | last 90 trading days |
| `1h` | now − 1h → now | same hour-of-day on prior day | last 90 trading days |
| `24h` | now − 24h → now | rolling 24h ending at prior midnights | last 90 days |
| `1w` | now − 7d → now | rolling 7d shifted weekly | last 52 weeks |

For `today` the percentile is biased low pre-market (incomplete day vs
full prior days). The card header shows `as-of HH:MM ET` and the cell
tooltip notes the partial-day caveat.

### SQL shape

```
WITH legs AS (
  SELECT
    COALESCE(original_execution_timestamp, execution_timestamp) AS ts,
    forward_start_years,
    tenor_years,
    ABS(COALESCE(notional, 0)) AS gross_notional,
    ABS(COALESCE(risk, 0))     AS gross_dv01
  FROM arbs_usd_swap_tape_legs_v2
  WHERE COALESCE(contributes_to_flow, FALSE) = TRUE
    AND COALESCE(original_execution_timestamp, execution_timestamp)
        >= ($baseline_start)::timestamptz
),
bucketed AS (
  SELECT *,
    {fwd_case}   AS fwd_bucket,
    {tenor_case} AS tenor_bucket
  FROM legs
  WHERE {fwd_case} <> 'fwd_other'
),
windowed AS (
  SELECT *,
    CASE
      WHEN ts >= $current_start THEN 'current'
      WHEN ts >= $baseline_start THEN 'baseline'
      ELSE 'drop'
    END AS window_kind,
    -- For non-today periods, the baseline_window_id groups prior
    -- equivalent windows (1h slots, 24h slots, weekly slots).
    {window_id_expr} AS baseline_window_id
  FROM bucketed
  WHERE ts < $current_end
),
prior AS (
  SELECT fwd_bucket, tenor_bucket, baseline_window_id,
    SUM({metric_col}) AS window_value
  FROM windowed
  WHERE window_kind = 'baseline'
  GROUP BY fwd_bucket, tenor_bucket, baseline_window_id
),
prior_summary AS (
  SELECT fwd_bucket, tenor_bucket,
    array_agg(window_value ORDER BY window_value) AS prior_array,
    percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
    percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
    MIN(window_value) AS pmin,
    MAX(window_value) AS pmax,
    COUNT(*) AS n
  FROM prior
  GROUP BY fwd_bucket, tenor_bucket
),
current AS (
  SELECT fwd_bucket, tenor_bucket,
    SUM({metric_col}) AS current_value,
    COUNT(*) AS trade_count
  FROM windowed
  WHERE window_kind = 'current'
  GROUP BY fwd_bucket, tenor_bucket
)
SELECT
  COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
  COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
  COALESCE(c.current_value, 0)             AS current,
  COALESCE(c.trade_count, 0)               AS trade_count,
  p.prior_array,
  p.p25, p.p50, p.p75, p.pmin, p.pmax, COALESCE(p.n, 0) AS n
FROM current c
FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
```

### Server post-processing (TS)

For each row:

- Compute `percentile = countLessOrEqual(current, prior_array) / prior_array.length * 100` when `n > 0`, else `null`.
- Drop `prior_array` from response (only the 5-number summary ships).
- Compute row totals and column totals by summing `current` along the
  appropriate axis. Their percentile is computed against
  `array_sum_per_window` for that axis (separate aggregation in the SQL,
  omitted from the sketch above for brevity).

### Response

```ts
type VolumeGridResponse = {
  asOf: string                         // ISO of latest leg in current window
  metric: 'notional' | 'dv01'
  period: 'today' | '1h' | '24h' | '1w'
  cells: Array<{
    fwd: string
    tenor: string
    current: number
    tradeCount: number
    baseline: { p25: number; p50: number; p75: number; min: number; max: number; n: number }
    percentile: number | null
  }>
  totals: {
    rowTotals: Record<string, { current: number; percentile: number | null }>
    colTotals: Record<string, { current: number; percentile: number | null }>
    grand:     { current: number; percentile: number | null }
  }
}
```

### Caching

- Server LRU 60 s TTL keyed on `(metric, period, lookbackDays)`.
- ETag emitted; route honours `If-None-Match` (matches `analytics-timeseries`).
- `Cache-Control: private, max-age=60, must-revalidate`.

### Validation

- `metric` not in allowed set → 400.
- `period` not in allowed set → 400.
- `lookbackDays` non-numeric or out of range → 400.

## Backend §2 — `/api/usd-swaps-tape-v2/volume-grid/cell`

Drill-down for a single cell.

### Request

`GET /api/usd-swaps-tape-v2/volume-grid/cell?fwd=spot&tenor=5y&metric=notional&range=3M&recentLimit=50`

| Param | Allowed | Default |
|---|---|---|
| `fwd` | `spot`, `6m_1y`, `1y_2y`, `2y_5y`, `5y_10y` | required |
| `tenor` | `1y`, `2y`, `2_5y`, `5y`, `5_10y`, `10y`, `10_20y`, `20y`, `20_30y`, `30y`, `50y` | required |
| `metric` | `notional` \| `dv01` | `notional` |
| `range` | `1M` \| `3M` \| `6M` \| `1Y` | `3M` |
| `recentLimit` | 1..200 | 50 |

### Response

```ts
type VolumeGridCellResponse = {
  fwd: string
  tenor: string
  metric: 'notional' | 'dv01'
  range: '1M' | '3M' | '6M' | '1Y'
  timeseries: Array<{
    day: string
    notional: number
    dv01: number
    tradeCount: number
    idbCount: number
    custyCount: number
  }>
  recentTrades: Array<{
    package_id: string
    execution_start: string
    tape_label: string | null
    package_type: string | null
    weighted_fixed_rate: number | null
    total_risk: number | null
    total_notional: number | null
    venue: string | null
    is_block_any: boolean | null
  }>
}
```

### SQL strategy

Two queries, one round trip via `Promise.all`:

1. Daily aggregate from `legs_v2` filtered on `contributes_to_flow=TRUE`
   + bucket predicates from `volumeGridBuckets.ts` + range start.
2. Recent packages: select from `arbs_usd_swap_tape_packages_v2`,
   restricted to package IDs whose `legs_json` contains at least one
   leg matching the bucket. Order `execution_start DESC`, limit
   `recentLimit`.

### Bucket helper

Both routes import from
`lib/usd-swaps-tape-v2/volumeGridBuckets.ts`:

- `FORWARD_BUCKETS: ReadonlyArray<{ id: string; lo: number | null; hi: number | null; label: string }>`
- `TENOR_BUCKETS: ReadonlyArray<...>`
- `buildBucketSqlCases(legAlias)` returns `{ fwdCase: string; tenorCase: string }`
- `buildBucketPredicate(legAlias, fwdId, tenorId)` returns
  `{ sql: string; params: number[] }`. Predicate uses positional params
  rather than inlining numerics so the route's parameter list stays
  consistent and parameter binding is uniform.

This keeps boundary definitions in one place; `__tests__` for the
helper confirm round-trip invariants and pin boundaries (e.g. an
input of `tenor_years = 5.5` lands in `5_10y`, not `5y`).

### Caching

Same LRU/ETag pattern. Key includes
`(fwd, tenor, metric, range, recentLimit)`.

## Frontend §1 — `<VolumeGridCard>`

Collapsible card mounted at the top of `usd-swaps-tape-shell`,
above the table.

### Layout

Header strip (always visible) + grid body (when expanded). Header
shows: `▼ Volume Grid`, metric toggle (Notional / DV01), period
selector (Today / 1h / 24h / 1w), `as-of HH:MM ET` badge, manual
refresh button.

Grid body: 5 forward-bucket rows + 1 Total row, 11 tenor-bucket
columns + 1 Total column, plus a left header column for the row
labels. Total cells render with thicker border and slate-300 text;
their colour ramp is the same as data cells.

### Cell content

Each cell is a `<button>`:

- Top line: current value, formatted compact (`$1.2B`, `$45M`, `$48k`).
- Bottom line: `Pn` percentile in mono-9.5 px slate-400.
- Background: percentile-driven via `colorRamp.ts`.
- Foreground: light text (`text-slate-100`) when percentile ≥ ~70 (hot cell), slate-300 otherwise.
- Hover tooltip: full bucket label + current + trade count + `vs P25/P50/P75/min/max (n=…)` + period.
- `aria-label`: human-readable summary (e.g. "5y outright spot — 1.2B notional, 88th percentile vs last 90 trading days").
- `tradeCount === 0` and/or `percentile === null` → `disabled`, `aria-disabled="true"`, `cursor-not-allowed`, dash glyph.

### Header controls (state + persistence)

- `:collapsed` — boolean, localStorage `usd-tape-v2:volume-grid:collapsed`.
- `:metric` — `notional` \| `dv01`, localStorage `usd-tape-v2:volume-grid:metric`.
- `:period` — `today` \| `1h` \| `24h` \| `1w`, localStorage `usd-tape-v2:volume-grid:period`.
- Modal `:cell-range` — `1M` \| `3M` \| `6M` \| `1Y`, localStorage `usd-tape-v2:volume-grid:cell-range`.

Reads run synchronously on first render, gated on
`typeof window !== 'undefined'`. Writes happen in a layout effect on
state change.

### Loading and error states

- First load: skeleton grid (slate cells with `animate-pulse`).
- Re-fetch: top-edge indigo pulse line, grid stays visible.
- Error: rose banner inside card body with the error message and a `retry` button. Cached grid stays visible if available.

### Visual integration

- Card chrome: `bg-slate-900/40 ring-1 ring-slate-800` + `border-b border-slate-800`.
- Mono 11 px cell content; 9.5 px uppercase tracking-wider headers.
- Card height: ~36 px collapsed, ~280 px expanded.

## Frontend §2 — `<VolumeGridCellModal>`

PrimeReact `Dialog` (matches `FlowHistoryGrid`).
Width 80vw, height 75vh, max width 1200 px, `modal` prop true.

### Header

Title: `<fwd label> × <tenor label> — Volume detail` (uses humanise
map). Right side: range selector (1M / 3M / 6M / 1Y) — persisted.
Metric stays pinned to whatever was active on the grid.

### Body — two stacked sections

1. **Volume timeseries chart** (~50% of modal height)
   - Recharts `ComposedChart`. Bars: daily metric stacked by IDB / CUSTY.
   - Reference line at lookback baseline median.
   - Today's bar styled with indigo glow.
   - Trade count overlay: thin line on a secondary y-axis.
   - Tooltip on hover: date, metric, trade count, IDB/CUSTY split.
   - Empty state: "No trades in this bucket over the selected range".

2. **Recent trades table** (~50% of modal height, scrollable)
   - Plain `<table>` (50 rows is too few for `DataTable`).
   - Columns: Time, Type, Tenor, Rate, Risk, Notional, Venue, Block?.
   - Row hover: indigo tint.
   - Row click → close modal → write `package_id` to URL via
     `useColumnFilters` (reuse the `onBinBrush` pattern from
     `AnalyticsPanel.tsx`). Tape narrows to that package.
     v1 caveat: if the package isn't in the loaded set, the URL
     filter fires a fresh fetch via `useTradeTapeData`'s effect on
     `params.columnFilters` — already wired, so no extra plumbing.

### Loading / error / close

- Loading: spinner overlay + skeleton on both sections.
- Error: rose banner above sections, retry button re-fires SWR.
- Esc closes (PrimeReact handles). Existing dock Esc-handler in
  `AnalyticsPanel.tsx` already checks for an open dialog and bails,
  so the dock won't co-close.
- `onHide` clears `selectedCell` so the modal unmounts.

## Frontend §3 — Heatmap colour ramp

`colorRamp.ts` exports `colorForPercentile(p: number | null)` returning
an `hsl()` string interpolated linearly between anchor stops:

| Percentile | Anchor (Tailwind reference) | Notes |
|---|---|---|
| `null` (no history) | `slate-900/30` | n/a cell |
| 0–30 | slate-900 → slate-800 | quieter than typical |
| 30–60 | slate-700 → slate-600 | normal |
| 60–85 | indigo-600 → indigo-500 | active |
| 85–95 | fuchsia-500 → fuchsia-400 | very active |
| 95–100 | rose-500 → rose-400 | violently active |

Foreground text picker: light text when target hue saturation × value
exceeds threshold (in practice, percentile ≥ 70 → `text-slate-100`,
else `text-slate-300`).

`tradeCount === 0` → dashed glyph, `bg-slate-900/30`, no click.

## Wiring into `UsdSwapsTradeTape`

`UsdSwapsTradeTape.tsx` mounts `<VolumeGridCard>` at the top of the
shell, passing a single `onSelectPackage` callback that writes the
package_id to the URL filter. The card owns its own SWR, modal, and
state — orchestrator stays thin.

The existing `--usd-swaps-tape-scale` zoom rule wraps the shell, so
the card scales with the rest of the dashboard and responds to the
1024 px breakpoint.

## State management & polling

- Card SWR: `refreshInterval = collapsed ? 0 : 30_000`.
- Modal SWR: `refreshInterval = 30_000` while open, 0 otherwise.
- SWR dedupes concurrent fetches. Server LRU+ETag keep cost down.
- Manual refresh button: `mutate()` on the SWR key.

## Edge cases

- Empty DB or new bucket with no history: percentile = null, n = 0,
  cell renders as n/a (slate-900/30). Modal still openable; surfaces
  empty timeseries + empty recent-trades.
- Single-day history (n = 1): percentile is 0 or 100. Tooltip shows
  `n = 1` so the trader knows the rank is brittle.
- Outlier prior window (e.g. one trillion-dollar trade): rank-based
  percentile is robust by construction. `pmax` is shown in the tooltip.
- DST / market holiday in lookback: SQL just gets fewer baseline
  windows; `n` reflects actual sample size.
- NULL `forward_start_years` falls into `spot`. NULL `tenor_years`
  is excluded from the grid (no column to put it in).

## Testing

### Unit

- `lib/usd-swaps-tape-v2/volumeGridBuckets.ts`:
  - Boundary values: `forward_start_years = 0.083` → `spot`;
    `tenor_years = 1.5` → `2y` (not `1y`); `tenor_years = 31` → `50y`;
    `tenor_years = 5.5` → `5_10y`.
  - NULL handling: NULL forward → `spot`; NULL tenor → excluded.
  - `buildBucketPredicate` round-trip: applying the predicate to a
    fixture row that should match returns the row; non-matching does
    not.

- `colorRamp.ts`:
  - `colorForPercentile(0)`, `(50)`, `(85)`, `(100)` produce expected
    hex stops.
  - `colorForPercentile(null)` → slate fallback.
  - Foreground picker returns light text for P85+.

- `useVolumeGrid` / `useVolumeGridCell`:
  - Build correct SWR keys.
  - `refreshInterval` 0 when collapsed, 30000 when expanded.
  - Resolve with mocked SWR.

- `VolumeGrid` (pure render):
  - Renders 5×11 cells + total row + total col.
  - Cell with `percentile = 95` carries the rose-class background.
  - Cell with `tradeCount = 0` is `disabled` + `aria-disabled="true"`.
  - `aria-label` formatted correctly.
  - Tooltip shows p25/p50/p75/min/max + n + period.

- `VolumeGridCellModal`:
  - Mounts when `selectedCell` non-null, unmounts on close.
  - Empty timeseries → empty state copy.
  - Recent trades row click → `onSelectPackage` invoked with right id.

### API route tests (Jest)

`volume-grid/route.test.ts`:

- 200 with mock DB returns matrix shape, all 55 cells present (some
  with `n=0`).
- A row with `contributes_to_flow=FALSE` in-bucket is excluded.
- 304 with matching `If-None-Match`.
- LRU hit on identical query (no second DB call).
- 400 on invalid `metric` / `period` / `lookbackDays`.
- Edge: empty DB → all cells `current=0, n=0, percentile=null`.
- Edge: single historical day → `n=1`, percentile = 0 or 100, no NaN.

`volume-grid/cell/route.test.ts`:

- 200 returns timeseries + recentTrades shape.
- Range filter applied (1M = 30 days back).
- `recentLimit` enforced.
- Empty bucket → both arrays empty, 200.
- 400 on missing/invalid `fwd` or `tenor`.

### Integration (RTL)

`UsdSwapsTradeTape.volumeGrid.test.tsx`:

- Mounts full tape with mocked SWR for both volume-grid endpoints.
- Card renders collapsed by default (no localStorage).
- Toggle expand → grid renders → all 55 cells present.
- Toggle metric → SWR re-keys → new data renders.
- Click cell → modal mounts → timeseries chart + recent-trades table render.
- Click recent-trade row → modal closes, URL has `columnFilters` with `package_id`, tape re-fetches with the filter.
- localStorage round-trip across remount.

### E2E (interactive — Chrome MCP)

Driven from the agent loop using the `mcp__Claude_in_Chrome__*` tools
(`tabs_create_mcp`, `navigate`, `find`, `read_page`, `computer`,
`javascript_tool`, `read_network_requests`, `read_console_messages`).
The `dashboard` dev server is started locally (`npm run dev`,
defaults to `http://localhost:3000`); the Chrome extension is
already paired with the agent. There is no codified Puppeteer suite
for this feature — the scripted checklist below is executed
interactively at the end of implementation, with each scenario's
result captured as text in the implementation log.

Scripted checklist:

1. **Happy path.** `navigate` to `/usd-swaps-v2`. `find` "Volume
   Grid" header. Click the expand chevron via `computer.left_click`.
   `read_page` (filter=interactive) on the grid; identify a cell with
   `aria-label` containing a percentile ≥ 50. `hover` it; assert
   tooltip text via `read_page`. Click cell. Wait for modal title +
   timeseries chart + recent-trades table via `find`. Click first
   recent-trade row. Confirm modal closes; check URL via
   `javascript_tool` (`location.href`); confirm `columnFilters`
   payload contains the clicked `package_id`; confirm the tape now
   shows only that package.
2. **Heatmap colour sanity.** Use `javascript_tool` to read
   `getComputedStyle(cell).backgroundColor` on the highest-percentile
   cell and a low-percentile cell; assert distinct RGB ranges (not
   both within the slate band). Use `read_page` to confirm a
   `tradeCount === 0` cell carries `aria-disabled="true"`.
3. **Period switch.** Confirm default period is `today` via
   `read_page`. Click the `1w` segment. Use `read_network_requests`
   filtered by `/volume-grid` to confirm a fresh `period=1w` GET
   fired. Confirm the `as-of` badge updated.
4. **Collapse persistence.** Expand, `navigate` to the same URL
   (forces reload), confirm still expanded via `read_page`. Collapse,
   reload, confirm still collapsed. While collapsed wait 35 s and
   read `/volume-grid` requests via `read_network_requests`; assert
   no new ones during the collapsed window.
5. **Modal range switch.** Open modal, click `1Y` range, confirm
   `/cell?range=1Y` GET via `read_network_requests`.
6. **Error path.** Inject a fault by setting a query param the route
   rejects (e.g. `?volumeGridForceError=1` if a debug hook is added,
   or by stopping the route's downstream DB connection in dev). Read
   the rose banner via `read_page`; click retry; confirm a fresh GET.
7. **Live polling.** Expand grid; capture timestamp; wait 35 s;
   read `/volume-grid` request log via `read_network_requests`;
   assert a second request fired in the window. Collapse, wait 35 s,
   confirm no further requests.
8. **Empty bucket.** Click an `aria-disabled="true"` cell via
   `computer.left_click`; confirm no modal opens (`find` modal title
   returns no match).
9. **Modal stacking.** Trigger the analytics dock by selecting a
   tape row, then open the volume-grid modal. Use `javascript_tool`
   to read `getComputedStyle(.p-dialog).zIndex` and the dock's
   z-index; assert the dialog is on top. Press Esc; confirm the
   modal closes (via `find`) and the dock remains visible.

For each scenario, capture: scenario name, pass/fail, observed
state (key DOM snippet or computed value), and any console errors
via `read_console_messages`.

### Storybook

Out of scope for v1. Story file can be added later for visual review
+ goldens.

## Risks and mitigations

- **Percentile math wrong for rolling windows.** Mitigated by:
  (a) deriving the SQL window bounds in a single helper that is
  unit-tested with synthetic timestamp fixtures, and (b) the API
  test suite asserts percentile = 50 for a fixture where current
  equals the historical median.
- **Bucket boundary drift between matrix route and cell route.**
  Mitigated by the `volumeGridBuckets.ts` helper being the only
  source of CASE expressions and predicates; both routes import.
- **Server cost from 30 s polling for many traders.** Mitigated by:
  (a) server LRU 60 s TTL with ETag → most polls return 304, (b)
  collapsed card pauses polling, (c) the SQL is bounded to the
  legs_v2 partition by `contributes_to_flow=TRUE` plus the indexed
  `original_execution_timestamp` column.
- **Today's percentile is misleading pre-market.** Mitigated by
  the `as-of HH:MM ET` badge and a tooltip note. Considered, then
  rejected: switching today's baseline to "same time-of-day on
  prior days" would be more comparable but doubles SQL complexity;
  trader feedback can pull that into v2 if needed.
- **Click-through on a package below the lazy-load watermark.**
  v1 falls back to URL filter, which triggers a fresh fetch via
  `useTradeTapeData`'s `params.columnFilters` effect. Trader sees
  the package within ~1 s.

## Implementation phasing

The implementation plan (separate doc, written next via the
`writing-plans` skill) will phase the work as:

1. `volumeGridBuckets.ts` helper + tests (no UI, no route).
2. `volume-grid` route + tests (server only, can curl + verify shape).
3. `colorRamp.ts` + buckets.ts client constants + tests (no fetch).
4. `useVolumeGrid` hook + tests.
5. `VolumeGrid` (pure) + `VolumeGridCard` + tests; mount in tape.
6. `volume-grid/cell` route + tests.
7. `useVolumeGridCell` hook + `VolumeGridCellModal` + tests; wire to card.
8. RTL integration test.
9. Interactive Chrome-MCP E2E walkthrough (scripted checklist
   above). Each scenario's outcome logged.
10. Manual QA pass + perf sanity check (network + timing) using
    `read_network_requests` and the browser perf panel.

Each phase ends with a green `npm test` + lint + types before the next
starts.

## Open questions

None blocking. The only deferred question is whether to add a
"baseline = same time-of-day on prior days" option for `today`
percentile fairness. Park for v2.
