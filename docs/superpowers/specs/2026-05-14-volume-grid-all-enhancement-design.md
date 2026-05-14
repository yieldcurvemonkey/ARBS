# Volume Grid 'All' Enhancement — Design Spec

**Date**: 2026-05-14
**Scope**: USD Swaps Tape V2 volume grid — rework the 'All' package type
option to correctly include curve/fly/multi-leg trades with per-cell
composition breakdown and enhanced analytics drill-down.

## Background

The volume grid aggregates leg-level flow from `arbs_usd_swap_tape_legs_v2`
into a forward-start x tenor heatmap. Each cell shows current-window volume
vs. historical percentile. The grid supports filtering by package type
(outright, curve, fly, etc.) and an 'All' option that removes the filter.

**Current state**: The SQL plumbing for 'All' exists —
`buildPackageTypeFilter('all')` returns `TRUE` (no filter), and queries
aggregate at the individual leg level. However, this path has **never been
verified end-to-end**: nobody has confirmed that curve/fly legs land in
correct buckets, that the analytics drill-down works for mixed package
types, or that the UI communicates composition clearly.

**Goal**: Verify correctness, add per-cell package-type composition
breakdown (mini stacked bar), and enhance the cell modal's Recent trades
with leg-level annotations.

## 1. Data Layer Verification

Before any code changes, verify the upstream Python pipeline correctly
decomposes multi-leg packages.

### Checks

1. **FLY trade** (e.g., IMM_M2026 5Y/10Y/30Y, 50k risk):
   - 3 rows in `arbs_usd_swap_tape_legs_v2` with correct `package_id`
   - `forward_start_years` ≈ IMM M2026 offset (buckets into `1w_3m`)
   - `tenor_years` = 5, 10, 30 respectively
   - `risk` = 25k (wings), 50k (body)
   - `contributes_to_flow = TRUE` on all 3 legs

2. **CURVE trade**: 2 rows, same forward, different tenors, opposite-sign
   risk, `contributes_to_flow = TRUE`

3. **API cross-check**: Call `/api/usd-swaps-tape-v2/volume-grid?packageType=all`
   and verify cell values include contributions from curve/fly legs.

### If gaps are found

Fixes live in the Python enrichment pipeline (`SDRUtils/packages/fly.py`,
`curve.py`). Document as a blocker; pipeline fixes are prerequisite but
out of scope for this dashboard enhancement.

## 2. SQL Enhancements

### 2a. Package family composition columns (main grid)

Add a `pkg_family` derived column to the `legs` CTE in both
`buildVolumeGridSqlTimeOfDay` and `buildVolumeGridSqlRolling`:

```sql
CASE
  WHEN p.package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY')
    THEN 'outright'
  WHEN p.package_type IN ('CURVE','SPREADOVER_CURVE','MATCHED_MATURITY_CURVE')
    THEN 'curve'
  WHEN p.package_type IN ('FLY','SPREADOVER_FLY','MATCHED_MATURITY_FLY')
    THEN 'fly'
  ELSE 'other'
END AS pkg_family
```

Add 4 FILTER columns to `current_agg`:

```sql
SUM(metric) FILTER (WHERE pkg_family = 'outright') AS outright_current,
SUM(metric) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
SUM(metric) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
SUM(metric) FILTER (WHERE pkg_family = 'other')    AS other_current
```

These columns are **always returned** regardless of `packageType` filter.
When filtering to a specific package type, non-matching family columns
naturally return 0.

### 2b. VolumeGridCell type extension

```typescript
interface VolumeGridCell {
  // existing fields unchanged
  fwd: string
  tenor: string
  current: number
  idbCurrent: number
  custyCurrent: number
  tradeCount: number
  baseline: { p25: number; p50: number; p75: number; min: number; max: number; n: number }
  percentile: number | null

  // NEW: package-type family composition
  outrightCurrent: number
  curveCurrent: number
  flyCurrent: number
  otherCurrent: number
}
```

`shapeVolumeGridResponse` maps the 4 new SQL columns into these fields.
`RawVolumeGridRow` gets matching `outright_current`, `curve_current`,
`fly_current`, `other_current` fields.

### 2c. Cell drill-down — leg-annotated recent trades

Enhance `buildRecentTradesSql` to include a JSON array of legs per
package, with an `inCell` boolean marking contributing legs:

```sql
SELECT
  p.package_id, p.execution_start, p.tape_label, p.package_type,
  p.weighted_fixed_rate, p.total_risk, p.total_notional,
  p.venue, p.is_block_any,
  (
    SELECT json_agg(json_build_object(
      'tenor_years', l2.tenor_years,
      'forward_start_years', l2.forward_start_years,
      'notional', ABS(COALESCE(l2.notional, 0)),
      'risk', ABS(COALESCE(l2.risk, 0)),
      'in_cell', CASE
        WHEN ({fwd_bucket_predicate} AND {tenor_bucket_predicate})
        THEN true ELSE false
      END
    ) ORDER BY l2.tenor_years)
    FROM arbs_usd_swap_tape_legs_v2 l2
    WHERE l2.package_id = p.package_id
      AND COALESCE(l2.contributes_to_flow, FALSE) = TRUE
  ) AS legs
FROM ...
```

The `fwd_bucket_predicate` and `tenor_bucket_predicate` reuse
`buildBucketPredicate` (already exists in `volumeGridBuckets.ts`).

Response type addition:

```typescript
interface RecentTradeWithLegs {
  package_id: string
  execution_start: string
  tape_label: string
  package_type: string
  weighted_fixed_rate: number | null
  total_risk: number | null
  total_notional: number | null
  venue: string | null
  is_block_any: boolean
  legs: Array<{
    tenorYears: number
    forwardStartYears: number
    notional: number
    risk: number
    inCell: boolean
  }>
}
```

### 2d. Timeseries & Intraday Seasonality

No SQL changes needed. These queries already aggregate at leg level
within the bucket predicate. `packageType='all'` passes through
correctly. Verified by tests only.

## 3. UI Changes

### 3a. VolumeGridCell — mini stacked bar

A thin (4px) horizontal stacked bar below the main value number,
showing composition by package family.

**Rendering rules:**
- Only renders when `packageType='all'` AND `tradeCount > 0`
- Segments: outright (slate), curve (amber), fly (emerald), other (purple)
- Only non-zero segments render
- Segment width = `(familyCurrent / current) * 100%`
- Tooltip on hover: "Outright: 120k | Curve: 45k | Fly: 30k"
- Hidden for specific package type filters (bar would be 100% one color)

**Color choices** are intentionally distinct from the percentile heatmap
(reds/blues) to avoid visual confusion.

### 3b. Cell modal — enhanced Recent trades table

Additions to the existing table:

1. **Expandable leg rows**: Trade rows with >1 leg show an expand
   chevron. Sub-rows show per-leg: tenor, forward, notional, risk,
   and an `inCell` badge (green dot if leg falls in this cell, dimmed
   otherwise). Outright rows (single leg) have no chevron.

2. **Cell contribution column**: Shows sum of risk/notional from legs
   in this cell vs. package total. E.g., "25k / 50k" for a fly wing.

3. **Package type badge**: Color-coded chip using the same palette as
   the stacked bar (amber for CURVE, green for FLY, etc.).

### 3c. Chart subtitle for 'All'

When `packageType='all'`, add a subtitle below the Volume detail and
Intraday Seasonality chart titles:
"Includes all package types (outright, curve, fly, etc.)"

## 4. Testing Strategy

### 4a. Unit tests — SQL builder layer

**Extend** `volume-grid/__tests__/route.logic.test.ts`:

- Synthetic FLY: 3 legs, verify SQL includes `pkg_family` CASE and
  4 FILTER columns
- Synthetic CURVE: 2 legs, verify ABS(risk) contribution to cells
- Mixed 'all': outright + curve + fly in same cell, verify
  `current_value` = sum, family columns sum correctly
- Package type passthrough: `packageType='outright'` → curve/fly
  columns are 0

**Extend** `volume-grid/cell/__tests__/route.logic.test.ts`:

- FLY with 3 legs, cell targets 10Y → `inCell=true` only on 10Y leg
- CURVE with 2 legs spanning cells → correct `inCell` assignment
- OUTRIGHT → legs array length 1, `inCell=true`

**Extend** `__tests__/volumeGridBuckets.test.ts`:

- `buildPackageTypeFilter('all')` returns `{ sql: 'TRUE', params: [] }`
  (regression guard)

### 4b. Unit tests — response shaping

- Raw row with 4 family columns → correct `VolumeGridCell` fields
- `summariseCells` totals still correct (existing tests stay green)

### 4c. Component tests

**Extend** `VolumeGrid/__tests__/VolumeGridCell.test.tsx`:

- `packageType='all'` + mixed composition → stacked bar renders
  with correct segment widths
- `packageType='outright'` → no stacked bar
- `tradeCount=0` → no stacked bar
- Tooltip content matches breakdown values

**Extend** `VolumeGrid/__tests__/VolumeGridCellModal.test.tsx`:

- FLY trade expandable, 3 leg sub-rows
- `inCell` badges green/dimmed correctly
- Cell contribution column shows correct ratio
- Outright row not expandable

### 4d. Live data verification

1. Query prod DB for a real FLY package
2. Trace its legs — verify forward/tenor/risk/contributes_to_flow
3. Manually compute expected cell placement
4. Compare against API response with `packageType=all`

### 4e. Chrome MCP E2E verification (merge gate)

1. Start dev server, open USD swaps tape v2 in Chrome
2. Select `packageType='All'`
3. Verify grid renders with non-zero values
4. Inspect cells for mini stacked bars with correct colors
5. Click a cell with fly/curve legs → verify:
   - Volume detail timeseries loads
   - Intraday seasonality loads
   - Recent trades show expandable FLY/CURVE rows
   - `inCell` badges correct
   - Cell contribution column correct
6. Switch to `packageType='Outright'` → stacked bars disappear,
   values decrease
7. Screenshot key states for PR evidence

## 5. Files to Modify

### API / Logic
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts`
  — add `pkg_family` CASE + 4 FILTER columns to both SQL builders,
  extend `RawVolumeGridRow` and `shapeVolumeGridResponse`
- `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts`
  — enhance `buildRecentTradesSql` with legs JSON subquery
- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts`
  — export `PKG_FAMILY_CASE_SQL` constant for reuse

### Types
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`
  — extend `VolumeGridCell`, add `RecentTradeWithLegs`

### UI Components
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx`
  — add mini stacked bar rendering
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`
  — expandable leg rows, cell contribution column, package type badge,
  chart subtitle for 'All'

### Tests
- `volume-grid/__tests__/route.logic.test.ts` — extend
- `volume-grid/cell/__tests__/route.logic.test.ts` — extend
- `__tests__/volumeGridBuckets.test.ts` — extend
- `VolumeGrid/__tests__/VolumeGridCell.test.tsx` — extend
- `VolumeGrid/__tests__/VolumeGridCellModal.test.tsx` — extend
