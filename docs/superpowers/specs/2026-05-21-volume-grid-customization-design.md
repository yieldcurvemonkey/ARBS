# Volume Grid Customization: Custom Buckets, Curve Strip & Fly Curve

**Date:** 2026-05-21
**Status:** Approved design

---

## Overview

Three enhancements to the USD Swaps Tape V2 volume grid:

1. **Custom Schema Builder** — a new view tab where users define arbitrary tenor and forward-start buckets, with full analytics support
2. **Curve Strip** — a prebuilt view showing volume/percentile analytics for common spot-starting and forward-starting curve structures (risk = long leg DV01)
3. **Fly Curve** — a prebuilt view showing volume/percentile analytics for common fly structures (risk = belly leg DV01)

All three integrate into the existing `VolumeGridCard` view-tab system alongside the existing Default and FOMC Strip views.

---

## Architecture Approach

**Approach A with shared CTE library:**

- Extract common SQL building blocks (time windows, percentile statistics, caching, platform/family splits) from the existing `route.logic.ts` into a reusable `volumeGridSqlLib.ts`
- Extend the existing `/volume-grid` endpoint to accept custom bucket definitions for the Custom view
- New `/volume-grid/structure` endpoint purpose-built for Curve Strip and Fly Curve — structure-based analytics require fundamentally different SQL (multi-leg package matching, specific-leg risk extraction)
- Both endpoints import from the shared library

**Rationale:** Structure-based analytics are a different query shape than single-leg bucketing. A dedicated endpoint keeps both codepaths clean. The shared CTE library eliminates duplication.

---

## 1. Shared CTE Library

**New file:** `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridSqlLib.ts`

### Extracted utilities

| Function | Description |
|---|---|
| `buildTimeWindowParams` | Generates time-of-day vs. rolling window SQL fragments and bind params. Weekend auto-detection (Sat/Sun → Friday full-day). |
| `buildPriorSummaryCte` | `percentile_cont(0.25/0.50/0.75)`, `MIN`, `MAX`, `COUNT`, `array_agg(window_value ORDER BY window_value)` grouped by bucket keys. Parameterized by group-by column names. |
| `buildCurrentAggCte` | Current-window sum split by platform (IDB/CUSTY) and pkg_family (outright/curve/fly/other), plus `trade_count`. Parameterized by metric column and group-by columns. |
| `buildFinalJoinSql` | `FULL OUTER JOIN` current + prior, `COALESCE` to 0 for all numeric columns. |
| `PLATFORM_CASE_SQL` | Re-exported constant for IDB/CUSTY classification. |
| `buildPkgFamilySql` | Re-exported function for outright/curve/fly/other classification. |
| `shapePercentile` | Client-side: computes percentile from `prior_array` — `lessOrEqual / prior.length * 100`. |
| `shapeTotals` | Client-side: sums cells into row/column/grand totals. |
| `buildLruCache` | LRU cache factory (configurable size and TTL). |
| `buildEtagHeaders` | ETag generation + `Cache-Control: private, max-age=300, stale-while-revalidate=600` headers. |

### Refactoring scope

The existing `route.logic.ts` refactors to import these utilities. The SQL string construction in `buildVolumeGridSqlTimeOfDay` and `buildVolumeGridSqlRolling` calls the shared CTE builders instead of inlining the patterns. Behavior is identical post-refactor — verified by existing usage before adding new features.

---

## 2. Custom Schema Builder

### Concept

A new view tab ("Custom") in the `VOLUME_GRID_VIEWS` array. Users build arbitrary tenor and forward-start bucket schemas via a modal, persist them to localStorage, and render the grid with full analytics (percentiles, IDB/CUSTY split, drill-down).

### UI

**View tab behavior:**
- Selecting "Custom" tab shows either: (a) the grid if a schema is active, or (b) an empty state with a "Configure" button
- A gear icon in the view controls opens the schema builder modal at any time

**Schema builder modal:**
- **Name** — text input for the schema label
- **Tenor Axis** — ordered list of bucket rows, each with:
  - `Label` (text, e.g. "Front End")
  - `Lo` (number input, years — nullable for "from the start")
  - `Hi` (number input, years — nullable for "to the end")
  - `[×]` remove button
  - `[+ Add Bucket]` appends a new row
- **Forward Axis** — same structure as tenor axis
- **Package Type** — dropdown with existing `PackageTypeGroupId` options
- **Presets** — "Load Preset" dropdown with built-in schemas (Default, Legacy, IMM16) as starting points
- **Actions** — `[Save]` persists to localStorage, `[Load]` dropdown shows saved schemas, `[Delete]` removes saved schema, `[Apply]` closes modal and renders

**Validation:**
- At least one bucket required on each axis
- `Lo < Hi` for each bucket (or one nullable for open-ended)
- Overlapping ranges are allowed (user's choice)
- Name must be non-empty for saving

### localStorage schema

```ts
interface CustomSchema {
  name: string
  tenorBuckets: BucketDef[]
  forwardBuckets: BucketDef[]
  packageType: PackageTypeGroupId
}
```

Key: `usd-tape-v2:volume-grid:custom-schemas` — stores `CustomSchema[]`.
Key: `usd-tape-v2:volume-grid:custom-active` — stores the index of the active schema (or null).

### API integration

**Existing `/volume-grid` endpoint extension:**

New accepted values:
- `forwardSchema='custom'` + `forwardBuckets=<JSON>` query param
- `tenorSchema='custom'` + `tenorBuckets=<JSON>` query param

When schema is `custom`:
- `resolveForwardSchema` / `resolveTenorSchema` parse the JSON param into `BucketDef[]`
- `buildBucketCaseSql(alias, column, buckets)` already works with arbitrary `BucketDef[]` — no SQL changes needed
- All downstream logic (bucketed CTE, prior summary, current agg) works unchanged

**Cell endpoint extension:**
- Same params: `forwardSchema='custom'` + `forwardBuckets=<JSON>`, `tenorSchema='custom'` + `tenorBuckets=<JSON>`
- `buildBucketPredicate` resolves the specific bucket's `lo`/`hi` from the custom definitions

### Component

**File:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CustomGridView.tsx`

- Manages own state: active custom schema, modal open/closed
- Calls `useVolumeGrid` with `forwardSchema='custom'`, `tenorSchema='custom'`, and the bucket JSON params
- Renders `VolumeGrid` (same grid component as DefaultGridView)
- Modal component: `CustomSchemaBuilderModal.tsx`

---

## 3. Structure Endpoint API

### Route

`GET /api/usd-swaps-tape-v2/volume-grid/structure`

**Files:**
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/route.ts`
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/route.logic.ts`

### Parameters

| Param | Type | Default | Description |
|---|---|---|---|
| `structureType` | `'curve' \| 'fly'` | required | Package family. Determines risk leg selection. |
| `structures` | JSON | required | Array of `StructureDef` objects defining which structures to match. |
| `metric` | `'notional' \| 'dv01'` | `'dv01'` | Aggregation metric (default dv01 since these are risk-weighted views). |
| `period` | string | `'today'` | Same time windows as existing endpoint. |
| `lookbackDays` | number | `90` | Same. |
| `forwardSchema` | string | `'default'` | Forward-start axis bucketing. Reuses existing forward schemas. Also accepts `'structure_default'` for the curated Spot/IMM1-4/1Y/2Y/5Y set. |
| `textFilter` | string | — | Same ILIKE filter. |

### StructureDef

```ts
interface StructureDef {
  id: string        // unique key, e.g. "2s10s"
  label: string     // display label, e.g. "2s10s"
  tenors: number[]  // leg tenors in years, e.g. [2, 10] for curve, [2, 5, 10] for fly
  tolerance: number // matching window ± around each tenor, e.g. 0.125 (45 days)
}
```

### Risk leg selection

Determined by `structureType`, not per-structure:
- **`curve`** — long leg: the leg with `MAX(tenor_years)` within the matched package
- **`fly`** — belly leg: the leg with the median `tenor_years` (second of three sorted legs)

### SQL CTE chain

```sql
-- 1. packages: filter by package type, time window, contributes_to_flow, textFilter
WITH packages AS (
  SELECT p.package_id, p.execution_start, p.tape_label, p.venue,
         p.platform_identifier, p.is_block_any
  FROM arbs_usd_swap_tape_packages_v2 p
  WHERE p.package_type IN ($curve_or_fly_types)
    AND p.execution_timestamp BETWEEN $lookback_start AND $lookback_end
    AND ($textFilter IS NULL OR p.tape_label ILIKE $textFilter)
),

-- 2. structure_match: join legs, match packages to structure definitions
-- For each package, check if its sorted leg tenors match a StructureDef
-- within tolerance. Assign structure_id to matched packages.
structure_match AS (
  SELECT
    p.package_id,
    p.execution_start,
    s.structure_id,
    l.tenor_years,
    l.risk,
    l.notional,
    l.forward_start_years,
    l.contributes_to_flow,
    -- rank legs within package by tenor
    ROW_NUMBER() OVER (
      PARTITION BY p.package_id, s.structure_id
      ORDER BY l.tenor_years ASC
    ) AS leg_rank,
    COUNT(*) OVER (
      PARTITION BY p.package_id, s.structure_id
    ) AS leg_count
  FROM packages p
  JOIN arbs_usd_swap_tape_legs_v2 l ON l.package_id = p.package_id
    AND l.contributes_to_flow = TRUE
  CROSS JOIN (VALUES
    -- dynamically generated from structures param:
    ('2s10s', 2, ARRAY[2.0, 10.0], 0.125),
    ('5s30s', 2, ARRAY[5.0, 30.0], 0.125),
    ...
  ) AS s(structure_id, expected_legs, tenor_array, tolerance)
  WHERE l.tenor_years BETWEEN ANY(s.tenor_array) - s.tolerance
                          AND ANY(s.tenor_array) + s.tolerance
),

-- 3. risk_leg: extract the specific leg's risk
-- For curves: leg_rank = leg_count (max tenor = long leg)
-- For flies: leg_rank = 2 (middle of 3 sorted = belly)
risk_leg AS (
  SELECT
    package_id,
    structure_id,
    risk AS risk_leg_value,
    notional AS notional_leg_value,
    forward_start_years
  FROM structure_match
  WHERE leg_count = expected_legs  -- only fully matched packages
    AND leg_rank = $risk_leg_rank  -- curve: leg_count, fly: 2
),

-- 4. bucketed: apply forward schema to risk leg's forward_start_years
bucketed AS (
  SELECT
    structure_id,
    CASE ... END AS fwd_bucket,  -- from buildBucketCaseSql
    risk_leg_value,
    notional_leg_value,
    ...time columns from shared lib...
  FROM risk_leg
  WHERE fwd_bucket != 'other'
),

-- 5-7: prior_summary, current_agg, final — from shared CTE library
-- grouped by (structure_id, fwd_bucket) instead of (tenor_bucket, fwd_bucket)
```

**Note on structure matching:** The CROSS JOIN + tolerance matching approach is robust for standard tenors. The `leg_count = expected_legs` filter ensures only packages with exactly the right number of matching legs are included (prevents a 2s5s10s fly from matching a 2s10s curve definition).

### Response shape

Same as existing volume grid, with axis names adjusted:

```ts
interface StructureGridResponse {
  axes: {
    forward: BucketDef[]     // forward-start axis
    structure: BucketDef[]   // structure axis (from structures param)
  }
  cells: Record<string, VolumeGridCell>  // keyed by "fwd|structure"
  totals: { rows: Record<string, number>, cols: Record<string, number>, grand: number }
  asOf: string
}
```

`VolumeGridCell` shape is unchanged — `current`, `idbCurrent`, `custyCurrent`, `outrightCurrent`, `curveCurrent`, `flyCurrent`, `tradeCount`, `baseline`, `percentile`.

### Caching

Same strategy as existing endpoint: server-side LRU (2048 entries, 5min TTL) + ETag + Cache-Control. Cache key includes `structureType` + `structures` hash + all other params.

---

## 4. Curve Strip View

### View registration

New entry in `VOLUME_GRID_VIEWS`:
```ts
{ id: 'curve_strip', label: 'Curve Strip', component: CurveStripView, controls: CurveStripControls }
```

### Structure definitions

**Benchmark curves (6):**

| ID | Label | Tenors |
|---|---|---|
| `2s5s` | 2s5s | [2, 5] |
| `2s10s` | 2s10s | [2, 10] |
| `2s30s` | 2s30s | [2, 30] |
| `5s10s` | 5s10s | [5, 10] |
| `5s30s` | 5s30s | [5, 30] |
| `10s30s` | 10s30s | [10, 30] |

**Tight curves (5):**

| ID | Label | Tenors |
|---|---|---|
| `3s5s` | 3s5s | [3, 5] |
| `5s7s` | 5s7s | [5, 7] |
| `7s10s` | 7s10s | [7, 10] |
| `10s20s` | 10s20s | [10, 20] |
| `20s30s` | 20s30s | [20, 30] |

All with `tolerance: 0.125` (±45 days).

### Forward axis

New forward schema `structure_default` — curated for structure views:

| ID | Label | Lo | Hi | Notes |
|---|---|---|---|---|
| `spot` | Spot | null | 0.125 | Spot-starting |
| `imm1` | IMM1 | dynamic | dynamic | ±0.125y around next IMM date |
| `imm2` | IMM2 | dynamic | dynamic | ±0.125y around 2nd IMM date |
| `imm3` | IMM3 | dynamic | dynamic | ±0.125y around 3rd IMM date |
| `imm4` | IMM4 | dynamic | dynamic | ±0.125y around 4th IMM date |
| `1y` | 1Y | 0.875 | 1.125 | ±0.125y around 1.0 |
| `2y` | 2Y | 1.875 | 2.125 | ±0.125y around 2.0 |
| `5y` | 5Y | 4.875 | 5.125 | ±0.125y around 5.0 |

IMM dates computed at request time reusing `computeImm16ForwardBuckets` logic (first 4 dates only).

### Layout

2D grid rendered by the existing `VolumeGrid` component:
- **Rows:** forward-start buckets (Spot, IMM1–4, 1Y, 2Y, 5Y)
- **Columns:** curve structures (2s5s through 10s30s, optionally tight curves)

### View-specific control

Toggle: **"Benchmark"** (6 liquid curves) / **"All"** (11 including tight curves). Rendered in the `controls` slot.

### Risk metric

Long leg DV01. For a 2s10s, this is the 10Y leg's DV01. Determined by `structureType: 'curve'` at the API level.

### Component

**File:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CurveStripView.tsx`

Thin wrapper around `StructureGridView` (shared component):
```ts
<StructureGridView
  structureType="curve"
  structures={showAll ? ALL_CURVES : BENCHMARK_CURVES}
  forwardBuckets={structureForwardBuckets}
  {...viewProps}
/>
```

---

## 5. Fly Curve View

### View registration

```ts
{ id: 'fly_curve', label: 'Fly Curve', component: FlyCurveView, controls: FlyCurveControls }
```

### Structure definitions

**Standard flies (4):**

| ID | Label | Tenors |
|---|---|---|
| `2s5s10s` | 2s5s10s | [2, 5, 10] |
| `2s5s30s` | 2s5s30s | [2, 5, 30] |
| `2s10s30s` | 2s10s30s | [2, 10, 30] |
| `5s10s30s` | 5s10s30s | [5, 10, 30] |

**Tight flies (4):**

| ID | Label | Tenors |
|---|---|---|
| `3s5s7s` | 3s5s7s | [3, 5, 7] |
| `5s7s10s` | 5s7s10s | [5, 7, 10] |
| `7s10s20s` | 7s10s20s | [7, 10, 20] |
| `10s20s30s` | 10s20s30s | [10, 20, 30] |

All with `tolerance: 0.125`.

### Layout

Same 2D grid as Curve Strip:
- **Rows:** forward-start buckets (same `structure_default` schema)
- **Columns:** fly structures

### View-specific control

Toggle: **"Standard"** (4 liquid flies) / **"All"** (8 including tight flies).

### Risk metric

Belly leg DV01. For a 2s5s10s, this is the 5Y leg's DV01. Determined by `structureType: 'fly'` at the API level.

### Component

**File:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FlyCurveView.tsx`

Thin wrapper around `StructureGridView`:
```ts
<StructureGridView
  structureType="fly"
  structures={showAll ? ALL_FLIES : STANDARD_FLIES}
  forwardBuckets={structureForwardBuckets}
  {...viewProps}
/>
```

---

## 6. Cell Modal Integration

### Extended CellId

```ts
type CellId =
  | { kind: 'matrix'; fwd: string; tenor: string }
  | { kind: 'collapsed_tenor'; fwd: string }
  | { kind: 'structure'; fwd: string; structure: string; structureType: 'curve' | 'fly' }
```

### Cell endpoint extension

**Existing route:** `GET /api/usd-swaps-tape-v2/volume-grid/cell`

**New params** (used when `structureType` is present):

| Param | Description |
|---|---|
| `structureType` | `'curve'` or `'fly'` |
| `structure` | Structure ID (e.g. `'2s10s'`) |
| `structureTenors` | JSON array of tenor values (e.g. `[2, 10]`) |
| `structureTolerance` | Tolerance value (e.g. `0.125`) |

When these params are present, the cell endpoint uses a structure-matching predicate instead of the single-leg tenor bucket predicate:
- Matches packages whose sorted leg tenors fall within tolerance of the `structureTenors`
- Extracts the risk leg (long for curve, belly for fly) for the timeseries and intraday charts
- Recent trades query: returns full package with all legs, risk leg highlighted with a `is_risk_leg: true` flag

### Three parallel queries (same structure as existing cell endpoint)

1. **Timeseries** — daily `SUM(risk_leg_value)` or `SUM(notional_leg_value)` for the structure + forward bucket over the selected range
2. **Intraday seasonality** — cumulative risk-leg metric by minute-of-day, current vs. average
3. **Recent trades** — most recent N packages matching the structure, with all legs shown and risk leg highlighted

### useVolumeGridCell extension

When `cellId.kind === 'structure'`:
- Constructs URL with `structureType`, `structure`, `structureTenors`, `structureTolerance` params
- Response shape is identical to existing cell response — no chart component changes needed

### Modal rendering

No changes to `VolumeGridCellModal`, `BarChart`, or `IntradaySeasonalityChart`. The only change is in `useVolumeGridCell` URL construction and the cell endpoint's SQL.

The recent trades table gains one visual enhancement: when `structureType` is present, the risk leg row in the expanded legs view gets a subtle accent highlight (e.g., bold text or left border color).

---

## 7. View Registration & State

### Updated VOLUME_GRID_VIEWS

```ts
export const VOLUME_GRID_VIEWS: ReadonlyArray<VolumeGridViewDef> = [
  { id: 'default',      label: 'Default',      component: DefaultGridView,  controls: DefaultGridControls },
  { id: 'fomc_strip',   label: 'FOMC Strip',   component: FomcStripView,    controls: null },
  { id: 'curve_strip',  label: 'Curve Strip',   component: CurveStripView,   controls: CurveStripControls },
  { id: 'fly_curve',    label: 'Fly Curve',     component: FlyCurveView,     controls: FlyCurveControls },
  { id: 'custom',       label: 'Custom',        component: CustomGridView,   controls: CustomGridControls },
]
```

### VolumeGridCard activeView validation

Line 64 of `VolumeGridCard.tsx` validates `activeView` against a hardcoded set. Update to:
```ts
const VALID_VIEWS = new Set(VOLUME_GRID_VIEWS.map(v => v.id))
```

### localStorage version bump

Bump `defaults-version` to `'all-today-1m-v4'` to reset users to default view on deploy (prevents stale view IDs from crashing).

---

## 8. Shared StructureGridView Component

**File:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/StructureGridView.tsx`

Shared between CurveStripView and FlyCurveView.

### Props

```ts
interface StructureGridViewProps extends ViewProps {
  structureType: 'curve' | 'fly'
  structures: StructureDef[]
  forwardBuckets: BucketDef[]
}
```

### Behavior

- Calls `useStructureGrid` hook (new) which fetches from `/volume-grid/structure`
- Renders the existing `VolumeGrid` component with axes mapped: `forward → rows`, `structure → columns`
- Cell click produces `CellId = { kind: 'structure', fwd, structure, structureType }`
- Supports the same `colorMode` (activity / grid) and `viewMode` (volume / idb_custy) toggles as DefaultGridView

### useStructureGrid hook

**File:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useStructureGrid.ts`

Same pattern as `useVolumeGrid` — `useState/useEffect` + `setInterval(30s)`, pauses when collapsed or tab hidden.

---

## 9. New Files Summary

| File | Purpose |
|---|---|
| `src/lib/usd-swaps-tape-v2/volumeGridSqlLib.ts` | Shared SQL CTE builders, cache, headers |
| `src/lib/usd-swaps-tape-v2/structureDefs.ts` | Curve and fly structure constants (StructureDef arrays) |
| `src/app/api/.../volume-grid/structure/route.ts` | Structure endpoint — param validation, cache |
| `src/app/api/.../volume-grid/structure/route.logic.ts` | Structure endpoint — SQL, response shaping |
| `src/features/.../VolumeGrid/views/StructureGridView.tsx` | Shared structure grid component |
| `src/features/.../VolumeGrid/views/CurveStripView.tsx` | Curve Strip view (thin wrapper) |
| `src/features/.../VolumeGrid/views/FlyCurveView.tsx` | Fly Curve view (thin wrapper) |
| `src/features/.../VolumeGrid/views/CustomGridView.tsx` | Custom schema view |
| `src/features/.../VolumeGrid/CustomSchemaBuilderModal.tsx` | Schema builder modal UI |
| `src/features/.../hooks/useStructureGrid.ts` | Data fetching hook for structure endpoint |
| `src/features/.../types/structure-grid.types.ts` | StructureDef, StructureGridResponse types |

## 10. Modified Files Summary

| File | Change |
|---|---|
| `src/app/api/.../volume-grid/route.logic.ts` | Refactor to import from shared lib; add `custom` schema handling |
| `src/app/api/.../volume-grid/cell/route.logic.ts` | Add structure-matching predicate path; add `custom` schema handling |
| `src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts` | Add `'custom'` to schema ID types; add `'structure_default'` forward schema; export `StructureDef` type |
| `src/features/.../VolumeGrid/views/volumeGridViews.ts` | Register 3 new views |
| `src/features/.../types/volume-grid-views.types.ts` | Extend `CellId` union with `'structure'` kind |
| `src/features/.../VolumeGrid/VolumeGridCard.tsx` | Dynamic view ID validation; bump defaults-version |
| `src/features/.../hooks/useVolumeGridCell.ts` | Route to structure cell params when `kind === 'structure'` |
| `src/features/.../VolumeGrid/VolumeGridCellModal.tsx` | Risk leg highlight in trades table |

---

## 11. Build Sequence

1. **Shared CTE library** — extract from existing endpoint, verify no regression
2. **Custom schema API** — extend endpoint with `custom` schema support
3. **Custom Schema Builder UI** — modal + view component + localStorage
4. **Structure endpoint API** — new route with structure-matching SQL
5. **Structure cell endpoint** — extend cell route with structure predicate
6. **StructureGridView + hook** — shared component and data fetching
7. **Curve Strip view** — structure defs + thin wrapper + controls
8. **Fly Curve view** — structure defs + thin wrapper + controls
9. **Cell modal integration** — CellId extension, risk leg highlight
10. **View registration** — wire everything into VOLUME_GRID_VIEWS + VolumeGridCard
