# Volume Grid Enhancement: View Registry + FOMC Strip + Customization

**Date**: 2026-05-16
**Status**: Approved
**Scope**: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/`

## Overview

Enhance the USD Swaps volume grid with:
1. A **view registry** pattern supporting prebuilt views with bespoke components
2. An **FOMC Strip** view — a compact horizontal strip showing volume per FOMC meeting
3. A **text filter** (fuzzy contains search) at both grid and cell-modal levels
4. **Bucket overrides** (hide/merge) for the default grid view

The current grid becomes the "Default Grid" view. New views render as entirely separate components with their own controls, sharing only the cell modal for analytics drill-down.

## Architecture

### View Switcher

```
VolumeGridCard (thin shell)
  ├── <header>
  │     ├── Collapse toggle
  │     ├── ViewSwitcher tabs: ["Grid", "FOMC Strip"]
  │     ├── TextFilterInput (shared, all views)
  │     └── View-specific controls (rendered by active view)
  ├── ActiveView
  │     ├── DefaultGridView → existing VolumeGrid + dropdowns
  │     └── FomcStripView → horizontal strip, ~6 cells
  └── VolumeGridCellModal (shared, accepts CellId union)
```

### View Registry

```ts
interface VolumeGridViewDef {
  id: string                                    // 'default' | 'fomc_strip'
  label: string                                 // 'Grid' | 'FOMC Strip'
  component: React.ComponentType<ViewProps>
  controls: React.ComponentType<ControlsProps>
  defaultParams: Partial<VolumeGridParams>
}
```

Each view owns its rendering and controls. The card shell manages:
- View selection (localStorage-persisted)
- Collapse state
- Text filter state (shared across views)
- Cell modal open/close

## FOMC Strip View

### Layout

A single horizontal row of ~6-8 cells, one per active FOMC meeting. Cells are wider (~120px) to show more information density:

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    JUN26         │  │    SEP26         │  │    NOV26         │
│   12.4M DV01    │  │   8.2M DV01     │  │   3.1M DV01     │
│   P72            │  │   P45            │  │   P28            │
│   ██░░ 68/32    │  │   ██░░ 55/45    │  │   █░░░ 82/18    │
│   14 trades     │  │   9 trades      │  │   4 trades      │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Controls

- **Metric**: Notional / DV01
- **Window**: Today / 1h / 24h / 1w (same periods)
- **Baseline**: 1w / 1m / 3m / 6m (lookback for percentile)
- **Label mode toggle**: Absolute (JUN26) / FOMC# (FOMC1, FOMC2...)

No Forward/Tenor schema dropdowns — the view fully defines its data shape.

### Constant-Maturity Alias Mapping

Computed client-side from current date:
```
FOMC1 = next upcoming meeting
FOMC2 = meeting after FOMC1
FOMC3 = ...
```

Utility: `buildFomcConstantMaturityMap(now: Date): Map<string, string>`

As of 2026-05-16: FOMC1 = JUN26, FOMC2 = SEP26, etc.

### API Usage

Calls `/volume-grid` with:
- `forwardSchema=fomc`
- `collapseAxis=tenor` (new param — server skips tenor bucketing)

Returns one cell per FOMC meeting label, tenor dimension collapsed.

## Text Filter (Fuzzy Search)

### Grid-Level Filter

- Compact text input in the controls bar (right side, before refresh button)
- Debounced 300ms
- Passed to API as `?textFilter=<value>`
- Backend applies: `AND (l.tape_label ILIKE '%' || $N::text || '%' OR p.tape_label ILIKE '%' || $N::text || '%')`
- Narrows the population *before* bucketing — cell values reflect only matching trades
- When active: "filtered" badge shown near as-of timestamp
- Clear button (x) resets

### Cell-Modal Filter

- Second text input inside VolumeGridCellModal, above recent trades table
- Client-side only — filters the fetched `recentTrades` array
- Does NOT affect timeseries/seasonality charts
- Instant (no debounce)

### Safety

- Value always passed as parameterized bind (`$N`), never interpolated
- `ILIKE` pattern: `'%' || $N || '%'` — user input is data, not SQL
- When `textFilter` is omitted, the clause is not emitted (zero cost)

## Bucket Overrides (Hide / Merge)

Applies to **Default Grid view only** (FOMC strip has fixed ~6 buckets).

### Operations

1. **Hide**: Uncheck a bucket in the customize popover. Applied client-side by filtering `axes.forward.buckets` / `axes.tenor.buckets` + corresponding cells before render.
2. **Merge**: Select 2+ adjacent buckets → merge into one. Client-side: sum `current` values, recalculate percentile from combined `prior_array`. Custom label (auto-generated or user-editable).

### UI

Gear icon next to Forward/Tenor schema dropdowns → popover with checkbox grid + merge controls.

### Storage

```ts
interface BucketOverrides {
  hidden: string[]
  merged: Array<{ ids: string[]; label: string }>
}
```

localStorage key: `usd-tape-v2:volume-grid:overrides:{forwardSchema}:{tenorSchema}`

### Cell Modal Integration

- Merged bucket click → modal receives all constituent bucket IDs
- Queries cell endpoint with combined lo/hi bounds (existing `buildBucketPredicate` supports ranges)

## Cell Modal Changes

### CellId Union Type

```ts
type CellId =
  | { kind: 'matrix'; fwd: string; tenor: string }
  | { kind: 'collapsed_tenor'; fwd: string }
```

- `matrix` → existing behavior
- `collapsed_tenor` → queries cell endpoint with fwd only, omits tenor predicate

### Adaptations

- Header label: `"JUN26 (FOMC1) — Volume detail"` for strip vs `"3M-6M x 5Y-7Y — Volume detail"` for grid
- Receives active `textFilter` from parent — passes to cell API for consistent timeseries
- `tenor` becomes optional in `parseVolumeGridCellParams` when `forwardSchema=fomc`

### Unchanged

- Daily volume bar chart
- Intraday seasonality cumulative line chart
- Recent trades table with package expansion
- Range toggle (1M / 3M / 6M / 1Y)
- Click-through to tape filter

## API Changes

### `/api/usd-swaps-tape-v2/volume-grid` (GET)

New optional query params:

| Param | Type | Default | Purpose |
|-------|------|---------|---------|
| `textFilter` | string | omitted | Contains-filter on `tape_label` |
| `collapseAxis` | `'tenor'` \| `'forward'` | omitted | Collapse one axis into a single aggregate |

**`collapseAxis=tenor`**: Tenor bucket expression becomes constant `'_all_'`. Response axes.tenor = single bucket `{ id: '_all_', label: 'All' }`. Avoids computing 16 unused tenor columns for strip views. Validation: `parseVolumeGridParams` accepts `collapseAxis` in `{'tenor', 'forward'}` or omitted; rejects other values with 400.

### `/api/usd-swaps-tape-v2/volume-grid/cell` (GET)

- `tenor` becomes optional (required unless `forwardSchema=fomc`)
- New optional `textFilter` param (same ILIKE semantics)

### No New Routes

Both views use existing endpoints with different param combinations.

### No Python Pipeline Changes

`fomc_meeting_label` already populated. Constant-maturity alias is a client-side display concern.

## File Changes

### New Files

| Path | Purpose |
|------|---------|
| `components/VolumeGrid/VolumeGridViewSwitcher.tsx` | Tab bar + active view renderer |
| `components/VolumeGrid/views/DefaultGridView.tsx` | Extracted current grid + controls |
| `components/VolumeGrid/views/FomcStripView.tsx` | Horizontal strip + FOMC controls |
| `components/VolumeGrid/views/FomcStripCell.tsx` | Single FOMC strip cell |
| `components/VolumeGrid/views/volumeGridViews.ts` | View registry array |
| `components/VolumeGrid/TextFilterInput.tsx` | Shared debounced filter |
| `components/VolumeGrid/BucketOverridesPopover.tsx` | Customize panel |
| `lib/usd-swaps-tape-v2/fomcConstantMaturity.ts` | FOMC# mapping utility |
| `types/volume-grid-views.types.ts` | ViewDef, CellId, BucketOverrides types |

### Modified Files

| Path | Change |
|------|--------|
| `VolumeGridCard.tsx` | Slim to shell: collapse + ViewSwitcher + CellModal |
| `VolumeGridCellModal.tsx` | Accept CellId union, optional textFilter |
| `useVolumeGrid.ts` | Accept textFilter, collapseAxis params |
| `useVolumeGridCell.ts` | Make tenor optional, accept textFilter |
| `route.logic.ts` (API) | textFilter SQL, collapseAxis logic |
| `cell/route.logic.ts` (API) | Optional tenor, textFilter |
| `volumeGridBuckets.ts` | Export `buildFomcConstantMaturityMap()` |
| `volume-grid.types.ts` | CellId type, collapseAxis in response |

### Unchanged

- `VolumeGrid.tsx` (pure matrix renderer)
- `VolumeGridCell.tsx` (individual cell)
- `colorRamp.ts`
- Python pipeline
- Database schema

## Build Order

1. Types + utilities (fomcConstantMaturity, volume-grid-views.types)
2. API changes (route.logic.ts — textFilter + collapseAxis)
3. Hooks (useVolumeGrid, useVolumeGridCell — new params)
4. Shared components (TextFilterInput, BucketOverridesPopover)
5. Views (DefaultGridView extract, FomcStripView)
6. Orchestration (VolumeGridViewSwitcher, refactored VolumeGridCard)
7. Modal (VolumeGridCellModal CellId union support)
8. Unit + component tests
9. E2E via Chrome MCP

## Testing Strategy

### Unit Tests (TypeScript)

- `route.logic.ts`: textFilter SQL generation, collapseAxis constant-bucket logic
- `cell/route.logic.ts`: optional tenor handling, textFilter
- `fomcConstantMaturity.ts`: alias mapping correctness across date boundaries
- `BucketOverrides`: hide/merge logic produces correct filtered/summed cells

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid"`

### Component Tests (vitest + testing-library)

- `VolumeGridViewSwitcher.test.tsx`: tab switching renders correct view
- `FomcStripView.test.tsx`: renders ~6 cells, label toggle
- `TextFilter.test.tsx`: debounce, clear, badge
- `BucketOverridesPopover.test.tsx`: hide/merge interactions

### End-to-End (Chrome MCP — Critical Path)

Start dev server (`cd SDRUtils/dashboard && npm run dev`), verify in browser:

1. **Default Grid**: no regressions — grid renders, cells click, modal works, all dropdowns functional
2. **View Switcher**: tabs appear, switching works, state persists
3. **FOMC Strip**: ~6 horizontal cells, correct labels, abs/FOMC# toggle, cell click opens modal with FOMC data, timeseries + seasonality render
4. **Text Filter**: typing narrows grid values, clear restores, filter active badge shows, cell modal reflects filter
5. **Bucket Overrides**: gear icon → popover, hide removes row/col, merge sums correctly, merged cell click opens modal with combined data
6. **Performance**: filtered grid <2s, FOMC strip with collapseAxis loads faster than full grid

### Python (conda env stir)

No new Python tests required for this feature. Existing `fomc_meeting_label` enrichment tested by pipeline suite.
