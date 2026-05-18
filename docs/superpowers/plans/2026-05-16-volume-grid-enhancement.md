# Volume Grid Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a view registry with FOMC strip preset, text filter (fuzzy search), and bucket overrides to the USD Swaps volume grid.

**Architecture:** View Registry pattern — `VolumeGridCard` becomes a thin shell with a tab switcher that delegates to view-specific components (`DefaultGridView`, `FomcStripView`). Shared `VolumeGridCellModal` accepts a `CellId` union. Backend API gets two new optional params (`textFilter`, `collapseAxis`).

**Tech Stack:** Next.js 14 (App Router), React 18, TypeScript, PrimeReact (Dialog), Recharts, SWR, PostgreSQL (Supabase), vitest + testing-library, Chrome MCP for E2E.

**Design Spec:** `docs/superpowers/specs/2026-05-16-volume-grid-enhancement-design.md`

**Environment:**
- Frontend: `cd SDRUtils/dashboard && npm run dev` (dev server on localhost:3000)
- Tests: `cd SDRUtils/dashboard && npm test -- --testPathPattern="<pattern>"`
- Python (if needed): `conda run -n stir pytest ...`
- E2E: Chrome MCP tools against running dev server

---

## File Map

### New Files

| File | Responsibility |
|------|----------------|
| `src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts` | `CellId`, `BucketOverrides`, `VolumeGridViewDef`, shared view prop interfaces |
| `src/lib/usd-swaps-tape-v2/fomcConstantMaturity.ts` | `buildFomcConstantMaturityMap()` — FOMC# ↔ absolute label mapping |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/TextFilterInput.tsx` | Debounced text input with clear button and "filtered" badge |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/BucketOverridesPopover.tsx` | Gear icon + customize panel (hide/merge buckets) |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridViewSwitcher.tsx` | Tab bar + active view renderer |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts` | View registry definitions array |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/DefaultGridView.tsx` | Extracted current grid rendering + controls |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripView.tsx` | FOMC horizontal strip + controls |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripCell.tsx` | Single wider FOMC cell component |

All paths relative to `SDRUtils/dashboard/`.

### Modified Files

| File | Change |
|------|--------|
| `src/features/usd-swaps-tape-v2/types/volume-grid.types.ts` | Add optional `collapseAxis` + `textFilter` to `VolumeGridResponse` |
| `src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts` | Export new `buildFomcConstantMaturityMap` |
| `src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts` | Parse `textFilter`+`collapseAxis`, inject into SQL |
| `src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts` | Make `tenor` optional, add `textFilter` |
| `src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts` | Accept `textFilter`, `collapseAxis` |
| `src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts` | Make `tenor` optional, add `textFilter` |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx` | Slim to shell |
| `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx` | Accept `CellId`, optional `textFilter` |

---

## Task 1: Types & FOMC Constant-Maturity Utility

**Files:**
- Create: `src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts`
- Create: `src/lib/usd-swaps-tape-v2/fomcConstantMaturity.ts`
- Create: `src/lib/usd-swaps-tape-v2/__tests__/fomcConstantMaturity.test.ts`
- Modify: `src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`

- [ ] **Step 1: Create the view types file**

```ts
// src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts
import type { ComponentType } from 'react'
import type {
  VolumeGridResponse,
  VolumeMetric,
  VolumePeriod,
} from './volume-grid.types'
import type {
  ForwardSchemaId,
  PackageTypeGroupId,
  TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type CollapseAxis = 'tenor' | 'forward'

export type CellId =
  | { kind: 'matrix'; fwd: string; tenor: string }
  | { kind: 'collapsed_tenor'; fwd: string }

export interface BucketOverrides {
  hidden: string[]
  merged: Array<{ ids: string[]; label: string }>
}

export type FomcLabelMode = 'absolute' | 'constant_maturity'

export interface ViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export interface ControlsProps {
  metric: VolumeMetric
  setMetric: (m: VolumeMetric) => void
  period: VolumePeriod
  setPeriod: (p: VolumePeriod) => void
  lookbackDays: number
  setLookbackDays: (d: number) => void
}

export interface VolumeGridViewDef {
  id: string
  label: string
  component: ComponentType<ViewProps>
  controls: ComponentType<ControlsProps>
}
```

- [ ] **Step 2: Add `collapseAxis` and `textFilter` to the response type**

In `src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`, add to `VolumeGridResponse`:

```ts
// After the existing `viewMode: VolumeGridViewMode` field:
  collapseAxis?: 'tenor' | 'forward'
  textFilter?: string
```

- [ ] **Step 3: Write the failing test for `buildFomcConstantMaturityMap`**

```ts
// src/lib/usd-swaps-tape-v2/__tests__/fomcConstantMaturity.test.ts
import { describe, expect, it } from '@jest/globals'
import { buildFomcConstantMaturityMap } from '../fomcConstantMaturity'

describe('buildFomcConstantMaturityMap', () => {
  it('maps FOMC1 to next upcoming meeting', () => {
    // 2026-05-16: next FOMC is JUN 2026 (third Wed = Jun 17)
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(map.get('FOMC1')).toBe('JUN26')
  })

  it('maps FOMC2 to second upcoming meeting', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    // After JUN26, the next scheduled FOMC is SEP26
    expect(map.get('FOMC2')).toBe('SEP26')
  })

  it('returns empty map for far-future date with no meetings', () => {
    const now = new Date('2099-01-01T00:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    expect(map.size).toBe(0)
  })

  it('builds reverse map from absolute to alias', () => {
    const now = new Date('2026-05-16T12:00:00Z')
    const map = buildFomcConstantMaturityMap(now)
    const reverse = new Map([...map.entries()].map(([k, v]) => [v, k]))
    expect(reverse.get('JUN26')).toBe('FOMC1')
  })
})
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="fomcConstantMaturity" --no-coverage`

Expected: FAIL — module not found

- [ ] **Step 5: Implement `buildFomcConstantMaturityMap`**

```ts
// src/lib/usd-swaps-tape-v2/fomcConstantMaturity.ts
import { parseFomcLabel } from './volumeGridBuckets'

// 2024-2027 FOMC meeting months (Fed publishes this schedule)
const FOMC_MONTHS: ReadonlyArray<[number, number]> = [
  // [year, monthIdx0]  — 8 meetings per year
  [2024, 0], [2024, 2], [2024, 4], [2024, 6], [2024, 8], [2024, 10],
  [2025, 0], [2025, 2], [2025, 4], [2025, 6], [2025, 8], [2025, 11],
  [2026, 0], [2026, 2], [2026, 4], [2026, 5], [2026, 8], [2026, 10],
  [2027, 0], [2027, 2], [2027, 4], [2027, 5], [2027, 8], [2027, 10],
]

const MONTH_LABELS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

function fomcLabelFromYearMonth(year: number, monthIdx: number): string {
  const yy = String(year % 100).padStart(2, '0')
  return `${MONTH_LABELS[monthIdx]}${yy}`
}

export function buildFomcConstantMaturityMap(now: Date = new Date()): Map<string, string> {
  const result = new Map<string, string>()
  const upcoming = FOMC_MONTHS
    .map(([y, m]) => ({ label: fomcLabelFromYearMonth(y, m), date: new Date(Date.UTC(y, m, 15)) }))
    .filter((x) => x.date.getTime() > now.getTime())
    .sort((a, b) => a.date.getTime() - b.date.getTime())

  for (let i = 0; i < upcoming.length; i++) {
    result.set(`FOMC${i + 1}`, upcoming[i].label)
  }
  return result
}

export function fomcAliasForLabel(label: string, map: Map<string, string>): string | null {
  for (const [alias, absLabel] of map) {
    if (absLabel === label) return alias
  }
  return null
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="fomcConstantMaturity" --no-coverage`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts \
        src/features/usd-swaps-tape-v2/types/volume-grid.types.ts \
        src/lib/usd-swaps-tape-v2/fomcConstantMaturity.ts \
        src/lib/usd-swaps-tape-v2/__tests__/fomcConstantMaturity.test.ts
git commit -m "feat(volume-grid): add view types and FOMC constant-maturity mapping"
```

---

## Task 2: API — `textFilter` and `collapseAxis` in Volume Grid Endpoint

**Files:**
- Modify: `src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts`
- Modify: `src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write failing tests for `textFilter` and `collapseAxis` parsing**

Add to the existing `route.logic.test.ts`:

```ts
describe('parseVolumeGridParams — textFilter & collapseAxis', () => {
  it('accepts textFilter as passthrough string', () => {
    const out = parseVolumeGridParams(new URLSearchParams('textFilter=Fed'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBe('Fed')
  })

  it('omits textFilter when not provided', () => {
    const out = parseVolumeGridParams(new URLSearchParams())
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBeUndefined()
  })

  it('accepts collapseAxis=tenor', () => {
    const out = parseVolumeGridParams(new URLSearchParams('collapseAxis=tenor'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.collapseAxis).toBe('tenor')
  })

  it('accepts collapseAxis=forward', () => {
    const out = parseVolumeGridParams(new URLSearchParams('collapseAxis=forward'))
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.collapseAxis).toBe('forward')
  })

  it('rejects invalid collapseAxis', () => {
    const out = parseVolumeGridParams(new URLSearchParams('collapseAxis=bad'))
    expect(out.ok).toBe(false)
  })

  it('omits collapseAxis when not provided', () => {
    const out = parseVolumeGridParams(new URLSearchParams())
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.collapseAxis).toBeUndefined()
  })
})

describe('buildVolumeGridSql — textFilter', () => {
  it('includes ILIKE clause when textFilter present', () => {
    const forwardSchema = resolveForwardSchema('default')
    const tenorSchema = resolveTenorSchema('default')
    const bounds = computeWindowBounds('today', 30)
    const { sql, params } = buildVolumeGridSql({
      metric: 'dv01',
      forwardSchema,
      tenorSchema,
      packageType: 'all',
      bounds,
      textFilter: 'Fed',
    })
    expect(sql).toContain('ILIKE')
    expect(params).toContain('Fed')
  })

  it('omits ILIKE clause when textFilter undefined', () => {
    const forwardSchema = resolveForwardSchema('default')
    const tenorSchema = resolveTenorSchema('default')
    const bounds = computeWindowBounds('today', 30)
    const { sql } = buildVolumeGridSql({
      metric: 'dv01',
      forwardSchema,
      tenorSchema,
      packageType: 'all',
      bounds,
    })
    expect(sql).not.toContain('ILIKE')
  })
})

describe('buildVolumeGridSql — collapseAxis', () => {
  it('replaces tenor bucket with constant when collapseAxis=tenor', () => {
    const forwardSchema = resolveForwardSchema('fomc')
    const tenorSchema = resolveTenorSchema('default')
    const bounds = computeWindowBounds('today', 30)
    const { sql } = buildVolumeGridSql({
      metric: 'dv01',
      forwardSchema,
      tenorSchema,
      packageType: 'all',
      bounds,
      collapseAxis: 'tenor',
    })
    expect(sql).toContain("'_all_' AS tenor_bucket")
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage`

Expected: FAIL — `textFilter` property does not exist, `collapseAxis` property does not exist

- [ ] **Step 3: Add `textFilter` and `collapseAxis` to `VolumeGridParams` and parser**

In `route.logic.ts`, update the `VolumeGridParams` interface:

```ts
export interface VolumeGridParams {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  viewMode: VolumeGridViewMode
  textFilter?: string
  collapseAxis?: 'tenor' | 'forward'
}
```

In `parseVolumeGridParams`, before the `return`, add:

```ts
  const textFilter = search.get('textFilter') ?? undefined
  const collapseAxisRaw = search.get('collapseAxis')
  let collapseAxis: 'tenor' | 'forward' | undefined
  if (collapseAxisRaw != null) {
    if (collapseAxisRaw !== 'tenor' && collapseAxisRaw !== 'forward') {
      return { ok: false, error: `collapseAxis must be 'tenor' or 'forward'` }
    }
    collapseAxis = collapseAxisRaw
  }
```

And add both to the returned `value`:

```ts
  return {
    ok: true,
    value: {
      metric: ...,
      // ... existing fields ...
      textFilter,
      collapseAxis,
    },
  }
```

- [ ] **Step 4: Update `SqlBuildContext` and SQL builders to handle new params**

Add to `SqlBuildContext`:

```ts
export interface SqlBuildContext {
  metric: VolumeMetric
  forwardSchema: ResolvedSchema
  tenorSchema: ResolvedSchema
  packageType: PackageTypeGroupId
  bounds: WindowBounds
  textFilter?: string
  collapseAxis?: 'tenor' | 'forward'
}
```

In `buildVolumeGridSqlTimeOfDay` and `buildVolumeGridSqlRolling`, apply two changes:

**A. Text filter** — after the `${pkgFilter.sql}` line in the WHERE clause, conditionally append:

```ts
  const textFilterClause = ctx.textFilter
    ? `AND (l.tape_label ILIKE '%' || $${params.length + 1}::text || '%' OR p.tape_label ILIKE '%' || $${params.length + 1}::text || '%')`
    : ''
  if (ctx.textFilter) params.push(ctx.textFilter)
```

Insert `${textFilterClause}` after `${extraFilter}` in the SQL string.

**B. Collapse axis** — in the `legs` CTE, conditionally override the bucket expression:

```ts
  const tenorBucketExpr = ctx.collapseAxis === 'tenor'
    ? `'_all_'`
    : buildTenorBucketSql(ctx.tenorSchema, 'l')
  const fwdBucketExpr = ctx.collapseAxis === 'forward'
    ? `'_all_'`
    : buildForwardBucketSql(ctx.forwardSchema, 'l')
```

And adjust the validity predicates:

```ts
  const fwdValid = ctx.collapseAxis === 'forward'
    ? 'TRUE'
    : fwdBucketIsValidSqlPredicate(ctx.forwardSchema)
  const tenorValid = ctx.collapseAxis === 'tenor'
    ? 'TRUE'
    : tenorBucketIsValidSqlPredicate(ctx.tenorSchema)
```

- [ ] **Step 5: Update `shapeVolumeGridResponse` to handle collapsed axis**

When `collapseAxis=tenor`, the response's `axes.tenor` should be a single bucket:

```ts
  const resolvedTenor: ResolvedSchema =
    params.collapseAxis === 'tenor'
      ? { id: 'collapsed', label: 'All', buckets: [{ id: '_all_', label: 'All', lo: null, hi: null }], kind: 'tenor_years' }
      : tenorSchema.kind === 'venue'
        ? { ...tenorSchema, buckets: buildVenueBucketsFromIdentifiers(...) }
        : tenorSchema
```

Similarly for `collapseAxis=forward`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage`

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts \
        src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts
git commit -m "feat(volume-grid): add textFilter and collapseAxis to grid API"
```

---

## Task 3: API — Optional `tenor` and `textFilter` in Cell Endpoint

**Files:**
- Modify: `src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts`
- Modify: `src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
describe('parseVolumeGridCellParams — optional tenor', () => {
  it('allows missing tenor when forwardSchema=fomc', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=JUN26&forwardSchema=fomc&metric=dv01'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.tenor).toBeUndefined()
  })

  it('requires tenor when forwardSchema is not fomc', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=spot&forwardSchema=default&metric=dv01'),
    )
    expect(out.ok).toBe(false)
    if (!out.ok) expect(out.error).toContain('tenor is required')
  })

  it('passes textFilter through', () => {
    const out = parseVolumeGridCellParams(
      new URLSearchParams('fwd=JUN26&tenor=2y-3y&forwardSchema=fomc&metric=dv01&textFilter=OIS'),
    )
    expect(out.ok).toBe(true)
    if (out.ok) expect(out.value.textFilter).toBe('OIS')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid/cell/__tests__/route.logic" --no-coverage`

Expected: FAIL

- [ ] **Step 3: Implement**

In `cell/route.logic.ts`, update `VolumeGridCellParams`:

```ts
export interface VolumeGridCellParams {
  fwd: string
  tenor?: string       // optional when forwardSchema=fomc
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  textFilter?: string
}
```

In `parseVolumeGridCellParams`, change the `tenor` validation:

```ts
  const tenor = search.get('tenor') ?? undefined
  if (!tenor && forwardSchemaRaw !== 'fomc') {
    return { ok: false, error: 'tenor is required when forwardSchema is not fomc' }
  }
```

Add textFilter parsing:

```ts
  const textFilter = search.get('textFilter') ?? undefined
```

In `buildTimeseriesSql`, `buildIntradaySeasonalitySql`, and `buildRecentTradesSql`, add an optional `textFilterSql` parameter similar to `schemaExtraFilterSql`:

```ts
  const textFilterClause = opts.textFilterSql ?? ''
```

Append in the WHERE: `${textFilterClause}`

The caller constructs:
```ts
const textFilterSql = params.textFilter
  ? `(l.tape_label ILIKE '%' || $${nextBind}::text || '%' OR p.tape_label ILIKE '%' || $${nextBind}::text || '%')`
  : undefined
```

When `tenor` is undefined, `buildBucketPredicate` should skip the tenor predicate — add a conditional that only emits the forward bucket's SQL range.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid/cell/__tests__/route.logic" --no-coverage`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts \
        src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts
git commit -m "feat(volume-grid/cell): optional tenor for FOMC, add textFilter"
```

---

## Task 4: Hooks — `useVolumeGrid` and `useVolumeGridCell` Updates

**Files:**
- Modify: `src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts`
- Modify: `src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts`

- [ ] **Step 1: Update `useVolumeGrid` to accept new params**

In `useVolumeGrid.ts`, add to `UseVolumeGridArgs`:

```ts
export interface UseVolumeGridArgs {
  // ... existing fields ...
  textFilter?: string
  collapseAxis?: 'tenor' | 'forward'
}
```

In `buildVolumeGridUrl`, add:

```ts
  if (args.textFilter) q.set('textFilter', args.textFilter)
  if (args.collapseAxis) q.set('collapseAxis', args.collapseAxis)
```

- [ ] **Step 2: Update `useVolumeGridCell` to make `tenor` optional and accept `textFilter`**

In `useVolumeGridCell.ts`, update the interface:

```ts
export interface UseVolumeGridCellArgs {
  cell: { fwd: string; tenor?: string } | null   // tenor now optional
  metric: VolumeMetric
  range: VolumeCellRange
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  recentLimit?: number
  textFilter?: string
  fetcher?: typeof fetch
}
```

In `buildVolumeGridCellUrl`:

```ts
  const q = new URLSearchParams({
    fwd: args.cell.fwd,
    metric: args.metric,
    range: args.range,
    forwardSchema: args.forwardSchema,
    tenorSchema: args.tenorSchema,
    packageType: args.packageType,
  })
  if (args.cell.tenor) q.set('tenor', args.cell.tenor)
  if (args.recentLimit != null) q.set('recentLimit', String(args.recentLimit))
  if (args.textFilter) q.set('textFilter', args.textFilter)
```

- [ ] **Step 3: Run existing hook tests to verify no regressions**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="useVolumeGrid" --no-coverage`

Expected: PASS (existing tests should still work since new fields are optional)

- [ ] **Step 4: Commit**

```bash
git add src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts \
        src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts
git commit -m "feat(hooks): add textFilter/collapseAxis to useVolumeGrid, optional tenor to useVolumeGridCell"
```

---

## Task 5: TextFilterInput Component

**Files:**
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/TextFilterInput.tsx`
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/TextFilterInput.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// __tests__/TextFilterInput.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { TextFilterInput } from '../TextFilterInput'

describe('TextFilterInput', () => {
  it('renders input with placeholder', () => {
    render(<TextFilterInput value="" onChange={vi.fn()} />)
    expect(screen.getByPlaceholderText('filter trades...')).toBeInTheDocument()
  })

  it('calls onChange after debounce', async () => {
    vi.useFakeTimers()
    const onChange = vi.fn()
    render(<TextFilterInput value="" onChange={onChange} />)
    const input = screen.getByPlaceholderText('filter trades...')
    fireEvent.change(input, { target: { value: 'Fed' } })
    expect(onChange).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(300) })
    expect(onChange).toHaveBeenCalledWith('Fed')
    vi.useRealTimers()
  })

  it('shows clear button when value is non-empty', () => {
    render(<TextFilterInput value="Fed" onChange={vi.fn()} />)
    expect(screen.getByLabelText('Clear filter')).toBeInTheDocument()
  })

  it('hides clear button when value is empty', () => {
    render(<TextFilterInput value="" onChange={vi.fn()} />)
    expect(screen.queryByLabelText('Clear filter')).not.toBeInTheDocument()
  })

  it('calls onChange with empty string on clear click', () => {
    const onChange = vi.fn()
    render(<TextFilterInput value="Fed" onChange={onChange} />)
    fireEvent.click(screen.getByLabelText('Clear filter'))
    expect(onChange).toHaveBeenCalledWith('')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="TextFilterInput" --no-coverage`

Expected: FAIL — module not found

- [ ] **Step 3: Implement TextFilterInput**

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/TextFilterInput.tsx
'use client'
import { useCallback, useEffect, useRef, useState, type JSX } from 'react'

export interface TextFilterInputProps {
  value: string
  onChange: (value: string) => void
  debounceMs?: number
}

export function TextFilterInput({ value, onChange, debounceMs = 300 }: TextFilterInputProps): JSX.Element {
  const [local, setLocal] = useState(value)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { setLocal(value) }, [value])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = e.target.value
    setLocal(next)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => onChange(next), debounceMs)
  }, [onChange, debounceMs])

  const handleClear = useCallback(() => {
    setLocal('')
    onChange('')
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [onChange])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  return (
    <div className="relative flex items-center">
      <input
        type="text"
        value={local}
        onChange={handleChange}
        placeholder="filter trades..."
        className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-[2px] pr-6 font-mono text-[10.5px] text-slate-200 placeholder:text-slate-600 hover:bg-slate-800 focus:border-indigo-500/50 focus:outline-none"
      />
      {value && (
        <button
          type="button"
          aria-label="Clear filter"
          onClick={handleClear}
          className="absolute right-1 font-mono text-[10px] text-slate-500 hover:text-slate-300"
        >
          ×
        </button>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="TextFilterInput" --no-coverage`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/TextFilterInput.tsx \
        src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/TextFilterInput.test.tsx
git commit -m "feat(volume-grid): add TextFilterInput component with debounce"
```

---

## Task 6: BucketOverridesPopover Component

**Files:**
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/BucketOverridesPopover.tsx`
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/BucketOverridesPopover.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// __tests__/BucketOverridesPopover.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BucketOverridesPopover } from '../BucketOverridesPopover'

const BUCKETS = [
  { id: 'spot', label: 'Spot' },
  { id: '1w-3m', label: '1W-3M' },
  { id: '3m-6m', label: '3M-6M' },
]

describe('BucketOverridesPopover', () => {
  it('renders gear icon button', () => {
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('Customize buckets')).toBeInTheDocument()
  })

  it('toggles popover open on click', () => {
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    expect(screen.getByText('Spot')).toBeInTheDocument()
    expect(screen.getByText('1W-3M')).toBeInTheDocument()
  })

  it('unchecking a bucket adds to hidden', () => {
    const onChange = vi.fn()
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    const checkbox = screen.getByLabelText('Spot')
    fireEvent.click(checkbox)
    expect(onChange).toHaveBeenCalledWith({ hidden: ['spot'], merged: [] })
  })

  it('reset button clears overrides', () => {
    const onChange = vi.fn()
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: ['spot'], merged: [] }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    fireEvent.click(screen.getByText('Reset'))
    expect(onChange).toHaveBeenCalledWith({ hidden: [], merged: [] })
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="BucketOverridesPopover" --no-coverage`

- [ ] **Step 3: Implement BucketOverridesPopover**

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/BucketOverridesPopover.tsx
'use client'
import { useCallback, useRef, useState, type JSX } from 'react'
import type { BucketOverrides } from '../../types/volume-grid-views.types'

export interface BucketOverridesPopoverProps {
  buckets: ReadonlyArray<{ id: string; label: string }>
  overrides: BucketOverrides
  onChange: (overrides: BucketOverrides) => void
}

export function BucketOverridesPopover({ buckets, overrides, onChange }: BucketOverridesPopoverProps): JSX.Element {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const toggleHidden = useCallback((bucketId: string) => {
    const isHidden = overrides.hidden.includes(bucketId)
    const next = isHidden
      ? overrides.hidden.filter((id) => id !== bucketId)
      : [...overrides.hidden, bucketId]
    onChange({ ...overrides, hidden: next })
  }, [overrides, onChange])

  const reset = useCallback(() => {
    onChange({ hidden: [], merged: [] })
  }, [onChange])

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        aria-label="Customize buckets"
        onClick={() => setOpen((v) => !v)}
        className="rounded border border-slate-700 px-1.5 py-[2px] font-mono text-[10.5px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        ⚙
      </button>
      {open && (
        <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded border border-slate-700 bg-slate-900 p-3 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
              Customize buckets
            </span>
            <button
              type="button"
              onClick={reset}
              className="font-mono text-[10px] text-indigo-300 hover:text-indigo-200"
            >
              Reset
            </button>
          </div>
          <div className="grid grid-cols-2 gap-1">
            {buckets.map((b) => (
              <label key={b.id} className="flex items-center gap-1.5 font-mono text-[10px] text-slate-300">
                <input
                  type="checkbox"
                  aria-label={b.label}
                  checked={!overrides.hidden.includes(b.id)}
                  onChange={() => toggleHidden(b.id)}
                  className="h-3 w-3 rounded border-slate-600 bg-slate-800"
                />
                {b.label}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="BucketOverridesPopover" --no-coverage`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/BucketOverridesPopover.tsx \
        src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/BucketOverridesPopover.test.tsx
git commit -m "feat(volume-grid): add BucketOverridesPopover component"
```

---

## Task 7: DefaultGridView — Extract from VolumeGridCard

**Files:**
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/DefaultGridView.tsx`

- [ ] **Step 1: Create the DefaultGridView component**

Extract the grid rendering + controls from `VolumeGridCard.tsx` into its own view component. This component receives the shared state via props and renders:
- Metric, window, baseline, color mode toggles
- Forward/Tenor schema dropdowns
- Package type dropdown
- View mode dropdown
- BucketOverridesPopover (new)
- The `VolumeGrid` matrix component
- As-of timestamp + filtered badge

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/views/DefaultGridView.tsx
'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { BucketOverridesPopover } from '../BucketOverridesPopover'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { useVolumeGridCellPrefetch } from '../../../hooks/useVolumeGridCellPrefetch'
import type { CellId, BucketOverrides } from '../../../types/volume-grid-views.types'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
} from '../../../types/volume-grid.types'
import {
  FORWARD_SCHEMA_IDS,
  PACKAGE_TYPE_GROUP_IDS,
  PACKAGE_TYPE_GROUP_LABELS,
  TENOR_SCHEMA_IDS,
  type ForwardSchemaId,
  type PackageTypeGroupId,
  type TenorSchemaId,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

// Re-use the existing Toggle/Select helpers (move to shared file or inline)
// ... (copy Toggle and Select from VolumeGridCard)

const LOOKBACK_IDS = ['1w', '2w', '3w', '1m', '3m', '6m', '1y', '2y'] as const
type LookbackId = (typeof LOOKBACK_IDS)[number]
const LOOKBACK_DAYS: Record<LookbackId, number> = {
  '1w': 7, '2w': 14, '3w': 21, '1m': 30, '3m': 90, '6m': 180, '1y': 365, '2y': 730,
}

export interface DefaultGridViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export function DefaultGridView({ metric, period, lookbackDays, textFilter, onCellClick }: DefaultGridViewProps): JSX.Element {
  const [forwardSchema, setForwardSchema] = useState<ForwardSchemaId>('default')
  const [tenorSchema, setTenorSchema] = useState<TenorSchemaId>('default')
  const [packageType, setPackageType] = useState<PackageTypeGroupId>('all')
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')
  const [overrides, setOverrides] = useState<BucketOverrides>({ hidden: [], merged: [] })

  const grid = useVolumeGrid({
    metric, period, collapsed: false,
    lookbackDays,
    forwardSchema, tenorSchema, packageType, viewMode,
    textFilter: textFilter || undefined,
  })

  const cellPrefetch = useVolumeGridCellPrefetch({ metric, forwardSchema, tenorSchema, packageType })

  const handleCellClick = useCallback((id: { fwd: string; tenor: string }) => {
    onCellClick({ kind: 'matrix', ...id })
  }, [onCellClick])

  // Apply bucket overrides client-side
  const filteredData = useMemo(() => {
    if (!grid.data || overrides.hidden.length === 0) return grid.data
    return {
      ...grid.data,
      axes: {
        forward: {
          ...grid.data.axes.forward,
          buckets: grid.data.axes.forward.buckets.filter((b) => !overrides.hidden.includes(b.id)),
        },
        tenor: {
          ...grid.data.axes.tenor,
          buckets: grid.data.axes.tenor.buckets.filter((b) => !overrides.hidden.includes(b.id)),
        },
      },
      cells: grid.data.cells.filter(
        (c) => !overrides.hidden.includes(c.fwd) && !overrides.hidden.includes(c.tenor),
      ),
    }
  }, [grid.data, overrides.hidden])

  // ... render controls + VolumeGrid with filteredData
  // (mirror existing VolumeGridCard render logic, using Toggle/Select from shared)
  return (
    <div className="px-3 pb-3">
      {/* Controls row - forward/tenor schema selects, package type, view mode, color mode, overrides gear */}
      {/* ... */}
      {filteredData ? (
        <VolumeGrid
          data={filteredData}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={packageType}
          onCellClick={handleCellClick}
          onCellHover={cellPrefetch.onCellHover}
          onCellLeave={cellPrefetch.onCellLeave}
        />
      ) : (
        <SkeletonGrid />
      )}
    </div>
  )
}

function SkeletonGrid(): JSX.Element {
  return (
    <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
      {Array.from({ length: 12 * 8 }).map((_, i) => (
        <div key={i} className="rounded-sm bg-slate-800/40" />
      ))}
    </div>
  )
}
```

Note: The full implementation will need to replicate the Toggle/Select helpers from VolumeGridCard. Extract them into a shared `VolumeGrid/controls.tsx` file or copy inline. The exact controls UI mirrors the current VolumeGridCard header.

- [ ] **Step 2: Verify compilation**

Run: `cd SDRUtils/dashboard && npx tsc --noEmit --pretty 2>&1 | head -30`

Expected: No errors in new file (existing errors may be present)

- [ ] **Step 3: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/views/DefaultGridView.tsx
git commit -m "feat(volume-grid): extract DefaultGridView from VolumeGridCard"
```

---

## Task 8: FomcStripView + FomcStripCell

**Files:**
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripView.tsx`
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripCell.tsx`
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/__tests__/FomcStripView.test.tsx`

- [ ] **Step 1: Write failing test for FomcStripView**

```tsx
// views/__tests__/FomcStripView.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FomcStripView } from '../FomcStripView'

vi.mock('../../../../hooks/useVolumeGrid', () => ({
  useVolumeGrid: () => ({
    data: {
      asOf: '2026-05-16T16:00:00Z',
      axes: {
        forward: {
          id: 'fomc', label: 'FOMC',
          buckets: [
            { id: 'JUN26', label: 'JUN26' },
            { id: 'SEP26', label: 'SEP26' },
            { id: 'NOV26', label: 'NOV26' },
          ],
        },
        tenor: { id: 'collapsed', label: 'All', buckets: [{ id: '_all_', label: 'All' }] },
      },
      cells: [
        { fwd: 'JUN26', tenor: '_all_', current: 12400000, idbCurrent: 8400000, custyCurrent: 4000000, tradeCount: 14, baseline: { p25: 5e6, p50: 9e6, p75: 14e6, min: 2e6, max: 20e6, n: 22 }, percentile: 72, outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0 },
        { fwd: 'SEP26', tenor: '_all_', current: 8200000, idbCurrent: 4500000, custyCurrent: 3700000, tradeCount: 9, baseline: { p25: 4e6, p50: 7e6, p75: 11e6, min: 1e6, max: 15e6, n: 22 }, percentile: 45, outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0 },
        { fwd: 'NOV26', tenor: '_all_', current: 3100000, idbCurrent: 2500000, custyCurrent: 600000, tradeCount: 4, baseline: { p25: 2e6, p50: 4e6, p75: 6e6, min: 500000, max: 8e6, n: 22 }, percentile: 28, outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0 },
      ],
      totals: { rowTotals: {}, colTotals: {}, grand: { current: 23700000, percentile: null } },
      metric: 'dv01', period: 'today', lookbackDays: 30,
      forwardSchema: 'fomc', tenorSchema: 'default', packageType: 'all', viewMode: 'volume',
    },
    error: null, isLoading: false, refresh: vi.fn(),
  }),
}))

describe('FomcStripView', () => {
  it('renders one cell per FOMC meeting', () => {
    render(
      <FomcStripView
        metric="dv01"
        period="today"
        lookbackDays={30}
        textFilter=""
        onCellClick={vi.fn()}
      />,
    )
    expect(screen.getByText('JUN26')).toBeInTheDocument()
    expect(screen.getByText('SEP26')).toBeInTheDocument()
    expect(screen.getByText('NOV26')).toBeInTheDocument()
  })

  it('renders cells horizontally in a flex row', () => {
    const { container } = render(
      <FomcStripView
        metric="dv01"
        period="today"
        lookbackDays={30}
        textFilter=""
        onCellClick={vi.fn()}
      />,
    )
    const strip = container.querySelector('[data-testid="fomc-strip"]')
    expect(strip).toBeInTheDocument()
    expect(strip?.className).toContain('flex')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="FomcStripView" --no-coverage`

Expected: FAIL

- [ ] **Step 3: Implement FomcStripCell**

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripCell.tsx
'use client'
import { memo, type JSX } from 'react'
import { colorForPercentile, foregroundForPercentile } from '../colorRamp'
import type { VolumeGridCell as Cell, VolumeMetric } from '../../../types/volume-grid.types'

const fmtCompact = (n: number): string => {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
  return abs.toFixed(0)
}

function safeShare(part: number, total: number): number {
  if (!Number.isFinite(total) || total <= 0) return 0
  return Math.max(0, Math.min(1, part / total))
}

export interface FomcStripCellProps {
  cell: Cell
  label: string
  aliasLabel: string | null
  metric: VolumeMetric
  onClick: () => void
}

export const FomcStripCell = memo(function FomcStripCell({
  cell, label, aliasLabel, metric, onClick,
}: FomcStripCellProps): JSX.Element {
  const isEmpty = cell.tradeCount === 0
  const bg = isEmpty ? 'transparent' : colorForPercentile(cell.percentile)
  const fg = foregroundForPercentile(cell.percentile)
  const idbShare = safeShare(cell.idbCurrent, cell.current)
  const custyShare = safeShare(cell.custyCurrent, cell.current)

  return (
    <button
      type="button"
      disabled={isEmpty}
      onClick={onClick}
      style={{ backgroundColor: bg }}
      className={`relative flex h-20 w-[120px] flex-col items-center justify-center rounded border border-slate-800/40 px-2 font-mono transition-colors ${fg} ${isEmpty ? 'cursor-not-allowed opacity-50' : 'hover:ring-1 hover:ring-indigo-300/60'}`}
    >
      <span className="text-[10px] uppercase tracking-wider text-slate-400">
        {label}
        {aliasLabel && <span className="ml-1 text-slate-600">({aliasLabel})</span>}
      </span>
      {isEmpty ? (
        <span className="text-slate-600">—</span>
      ) : (
        <>
          <span className="text-sm tabular-nums">{fmtCompact(cell.current)} {metric}</span>
          <span className="text-[9.5px] text-slate-400">
            P{cell.percentile != null ? Math.round(cell.percentile) : '-'}
          </span>
          <div className="absolute inset-x-0 bottom-0 flex h-1.5">
            <div className="bg-cyan-300/80" style={{ width: `${idbShare * 100}%` }} />
            <div className="bg-indigo-400/80" style={{ width: `${custyShare * 100}%` }} />
          </div>
          <span className="absolute bottom-2 right-1.5 text-[8px] text-slate-500">
            {cell.tradeCount}
          </span>
        </>
      )}
    </button>
  )
})
```

- [ ] **Step 4: Implement FomcStripView**

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripView.tsx
'use client'
import { useCallback, useMemo, useState, type JSX } from 'react'
import { FomcStripCell } from './FomcStripCell'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { buildFomcConstantMaturityMap, fomcAliasForLabel } from '@/lib/usd-swaps-tape-v2/fomcConstantMaturity'
import type { CellId } from '../../../types/volume-grid-views.types'
import type { VolumeGridCell as Cell, VolumeMetric, VolumePeriod } from '../../../types/volume-grid.types'
import type { FomcLabelMode } from '../../../types/volume-grid-views.types'

export interface FomcStripViewProps {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export function FomcStripView({ metric, period, lookbackDays, textFilter, onCellClick }: FomcStripViewProps): JSX.Element {
  const [labelMode, setLabelMode] = useState<FomcLabelMode>('absolute')

  const grid = useVolumeGrid({
    metric, period, collapsed: false,
    lookbackDays,
    forwardSchema: 'fomc',
    tenorSchema: 'default',
    packageType: 'all',
    viewMode: 'volume',
    textFilter: textFilter || undefined,
    collapseAxis: 'tenor',
  })

  const fomcMap = useMemo(() => buildFomcConstantMaturityMap(), [])

  const cellMap = useMemo(() => {
    if (!grid.data) return new Map<string, Cell>()
    const m = new Map<string, Cell>()
    for (const c of grid.data.cells) m.set(c.fwd, c)
    return m
  }, [grid.data])

  const handleCellClick = useCallback((fwd: string) => {
    onCellClick({ kind: 'collapsed_tenor', fwd })
  }, [onCellClick])

  const buckets = grid.data?.axes.forward.buckets ?? []

  return (
    <div className="px-3 pb-3">
      <div className="mb-2 flex items-center gap-2">
        <div className="flex items-center rounded border border-slate-700 p-[1px]">
          <button
            type="button"
            onClick={() => setLabelMode('absolute')}
            className={`px-2 py-[1px] font-mono text-[10.5px] ${labelMode === 'absolute' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            Absolute
          </button>
          <button
            type="button"
            onClick={() => setLabelMode('constant_maturity')}
            className={`px-2 py-[1px] font-mono text-[10.5px] ${labelMode === 'constant_maturity' ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
          >
            FOMC#
          </button>
        </div>
        {grid.isLoading && (
          <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[10px] text-sky-200 ring-1 ring-sky-500/30">
            loading…
          </span>
        )}
      </div>
      <div data-testid="fomc-strip" className="flex gap-2 overflow-x-auto">
        {buckets.map((b) => {
          const cell = cellMap.get(b.id) ?? {
            fwd: b.id, tenor: '_all_', current: 0, idbCurrent: 0, custyCurrent: 0,
            tradeCount: 0, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 },
            percentile: null, outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0,
          }
          const alias = fomcAliasForLabel(b.id, fomcMap)
          const displayLabel = labelMode === 'constant_maturity' && alias ? alias : b.id
          const displayAlias = labelMode === 'constant_maturity' ? b.id : alias
          return (
            <FomcStripCell
              key={b.id}
              cell={cell}
              label={displayLabel}
              aliasLabel={displayAlias}
              metric={metric}
              onClick={() => handleCellClick(b.id)}
            />
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Run tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="FomcStripView" --no-coverage`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripView.tsx \
        src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FomcStripCell.tsx \
        src/features/usd-swaps-tape-v2/components/VolumeGrid/views/__tests__/FomcStripView.test.tsx
git commit -m "feat(volume-grid): add FomcStripView and FomcStripCell"
```

---

## Task 9: View Registry + ViewSwitcher

**Files:**
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts`
- Create: `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridViewSwitcher.tsx`

- [ ] **Step 1: Create view registry**

```ts
// src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts
import type { VolumeGridViewDef } from '../../../types/volume-grid-views.types'
import { DefaultGridView } from './DefaultGridView'
import { FomcStripView } from './FomcStripView'

export const VOLUME_GRID_VIEWS: ReadonlyArray<VolumeGridViewDef> = [
  {
    id: 'default',
    label: 'Grid',
    component: DefaultGridView,
    controls: () => null, // DefaultGridView renders its own controls inline
  },
  {
    id: 'fomc_strip',
    label: 'FOMC Strip',
    component: FomcStripView,
    controls: () => null, // FomcStripView renders its own controls inline
  },
]
```

- [ ] **Step 2: Create VolumeGridViewSwitcher**

```tsx
// src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridViewSwitcher.tsx
'use client'
import type { JSX } from 'react'
import { VOLUME_GRID_VIEWS } from './views/volumeGridViews'
import type { CellId } from '../../types/volume-grid-views.types'
import type { VolumeMetric, VolumePeriod } from '../../types/volume-grid.types'

export interface VolumeGridViewSwitcherProps {
  activeViewId: string
  onViewChange: (id: string) => void
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export function VolumeGridViewSwitcher({
  activeViewId, onViewChange,
  metric, period, lookbackDays, textFilter, onCellClick,
}: VolumeGridViewSwitcherProps): JSX.Element {
  const view = VOLUME_GRID_VIEWS.find((v) => v.id === activeViewId) ?? VOLUME_GRID_VIEWS[0]
  const Component = view.component

  return (
    <>
      <ViewTabs activeId={activeViewId} onChange={onViewChange} />
      <Component
        metric={metric}
        period={period}
        lookbackDays={lookbackDays}
        textFilter={textFilter}
        onCellClick={onCellClick}
      />
    </>
  )
}

function ViewTabs({ activeId, onChange }: { activeId: string; onChange: (id: string) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {VOLUME_GRID_VIEWS.map((v) => (
        <button
          key={v.id}
          type="button"
          onClick={() => onChange(v.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${activeId === v.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {v.label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts \
        src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridViewSwitcher.tsx
git commit -m "feat(volume-grid): add view registry and VolumeGridViewSwitcher"
```

---

## Task 10: Refactor VolumeGridCard to Shell

**Files:**
- Modify: `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx`

- [ ] **Step 1: Refactor VolumeGridCard**

The card becomes a thin shell managing:
- Collapse state
- Active view selection (localStorage-persisted)
- Metric / period / lookback (shared across views)
- Text filter state
- Cell modal open/close

Key changes:
1. Remove all grid-rendering logic (now in `DefaultGridView`)
2. Remove schema/packageType/viewMode/colorMode state (now in `DefaultGridView`)
3. Add view switcher tab
4. Add TextFilterInput
5. Keep VolumeGridCellModal

```tsx
// Simplified VolumeGridCard structure (overwrite existing):
'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { VolumeGridViewSwitcher } from './VolumeGridViewSwitcher'
import { VolumeGridCellModal } from './VolumeGridCellModal'
import { TextFilterInput } from './TextFilterInput'
import { useIsMobile } from '@/lib/hooks/useIsMobile'
import type { CellId } from '../../types/volume-grid-views.types'
import type { VolumeMetric, VolumePeriod } from '../../types/volume-grid.types'

const KEY_COLLAPSED = 'usd-tape-v2:volume-grid:collapsed'
const KEY_METRIC = 'usd-tape-v2:volume-grid:metric'
const KEY_PERIOD = 'usd-tape-v2:volume-grid:period'
const KEY_LOOKBACK = 'usd-tape-v2:volume-grid:lookback'
const KEY_VIEW = 'usd-tape-v2:volume-grid:active-view'
const KEY_TEXT_FILTER = 'usd-tape-v2:volume-grid:text-filter'

type LookbackId = '1w' | '2w' | '3w' | '1m' | '3m' | '6m' | '1y' | '2y'
const LOOKBACK_IDS: ReadonlyArray<LookbackId> = ['1w', '2w', '3w', '1m', '3m', '6m', '1y', '2y']
const LOOKBACK_DAYS: Record<LookbackId, number> = {
  '1w': 7, '2w': 14, '3w': 21, '1m': 30, '3m': 90, '6m': 180, '1y': 365, '2y': 730,
}

export interface VolumeGridCardProps {
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCard({ onSelectPackage }: VolumeGridCardProps): JSX.Element {
  const [collapsed, setCollapsed] = useState(false)
  const [metric, setMetric] = useState<VolumeMetric>('dv01')
  const [period, setPeriod] = useState<VolumePeriod>('today')
  const [lookback, setLookback] = useState<LookbackId>('1m')
  const [activeView, setActiveView] = useState('default')
  const [textFilter, setTextFilter] = useState('')
  const [selectedCell, setSelectedCell] = useState<CellId | null>(null)
  const isMobile = useIsMobile()

  // Hydrate from localStorage (same pattern as before)
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (hydrated) return
    setHydrated(true)
    // ... read from localStorage ...
  }, [hydrated])

  // Persist to localStorage
  useEffect(() => {
    if (!hydrated) return
    localStorage.setItem(KEY_METRIC, metric)
    localStorage.setItem(KEY_PERIOD, period)
    localStorage.setItem(KEY_LOOKBACK, lookback)
    localStorage.setItem(KEY_VIEW, activeView)
    localStorage.setItem(KEY_COLLAPSED, String(collapsed))
  }, [hydrated, metric, period, lookback, activeView, collapsed])

  useEffect(() => {
    if (isMobile) setCollapsed(true)
  }, [isMobile])

  const onCellClick = useCallback((cell: CellId) => {
    setSelectedCell(cell)
  }, [])

  return (
    <section data-testid="volume-grid-card" className="border-b border-slate-800 bg-slate-900/40 ring-1 ring-slate-800">
      <header className={`flex flex-wrap items-center px-3 text-slate-300 ${isMobile ? 'gap-3 py-3' : 'gap-2 py-1.5'}`}>
        <button type="button" onClick={() => setCollapsed((v) => !v)}
          className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800">
          {collapsed ? '▲ Volume Grid' : '▼ Volume Grid'}
        </button>
        {/* Metric toggle */}
        {/* Period toggle */}
        {/* Lookback toggle */}
        {/* View switcher tabs rendered inline via VolumeGridViewSwitcher's ViewTabs */}
        <TextFilterInput value={textFilter} onChange={setTextFilter} />
        {textFilter && (
          <span className="rounded bg-amber-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-amber-200 ring-1 ring-amber-500/30">
            filtered
          </span>
        )}
      </header>
      {!collapsed && (
        <VolumeGridViewSwitcher
          activeViewId={activeView}
          onViewChange={setActiveView}
          metric={metric}
          period={period}
          lookbackDays={LOOKBACK_DAYS[lookback]}
          textFilter={textFilter}
          onCellClick={onCellClick}
        />
      )}
      <VolumeGridCellModal
        cell={selectedCell}
        metric={metric}
        textFilter={textFilter || undefined}
        onClose={() => setSelectedCell(null)}
        onSelectPackage={onSelectPackage}
      />
    </section>
  )
}
```

- [ ] **Step 2: Run existing VolumeGridCard tests to check what breaks**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="VolumeGridCard" --no-coverage`

Fix any broken assertions (the test may need updating since the card structure changed — e.g., it no longer directly renders `VolumeGrid`).

- [ ] **Step 3: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx
git commit -m "refactor(volume-grid): slim VolumeGridCard to shell with view switcher"
```

---

## Task 11: Update VolumeGridCellModal for CellId Union

**Files:**
- Modify: `src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`

- [ ] **Step 1: Update props to accept CellId**

Change `VolumeGridCellModalProps`:

```ts
import type { CellId } from '../../types/volume-grid-views.types'

export interface VolumeGridCellModalProps {
  cell: CellId | null                    // was { fwd: string; tenor: string } | null
  metric: VolumeMetric
  textFilter?: string                    // new
  onClose: () => void
  onSelectPackage: (packageId: string) => void
}
```

Remove `forwardSchema`, `tenorSchema`, `packageType`, `forwardAxis`, `tenorAxis` from props — instead derive them from the cell context (the FOMC strip always uses `forwardSchema=fomc`, the default grid passes its current selections).

Actually, to keep it simpler: keep `forwardSchema`/`tenorSchema`/`packageType` as optional props with defaults, and derive from the `CellId.kind`:

```ts
export interface VolumeGridCellModalProps {
  cell: CellId | null
  metric: VolumeMetric
  forwardSchema?: ForwardSchemaId
  tenorSchema?: TenorSchemaId
  packageType?: PackageTypeGroupId
  forwardAxis?: VolumeGridSchemaAxis
  tenorAxis?: VolumeGridSchemaAxis
  textFilter?: string
  onClose: () => void
  onSelectPackage: (packageId: string) => void
}
```

- [ ] **Step 2: Adapt the useVolumeGridCell call**

```ts
  const cellForHook = props.cell
    ? props.cell.kind === 'matrix'
      ? { fwd: props.cell.fwd, tenor: props.cell.tenor }
      : { fwd: props.cell.fwd }  // collapsed_tenor — no tenor
    : null

  const { data, error, isLoading } = useVolumeGridCell({
    cell: cellForHook,
    metric: props.metric,
    range,
    forwardSchema: props.forwardSchema ?? 'fomc',
    tenorSchema: props.tenorSchema ?? 'default',
    packageType: props.packageType ?? 'all',
    textFilter: props.textFilter,
  })
```

- [ ] **Step 3: Update header label**

```ts
  const headerLabel = props.cell
    ? props.cell.kind === 'collapsed_tenor'
      ? `${props.cell.fwd} — Volume detail`
      : `${lookupLabel(props.forwardAxis, props.cell.fwd)} × ${lookupLabel(props.tenorAxis, props.cell.tenor)} — Volume detail`
    : 'Volume detail'
```

- [ ] **Step 4: Add client-side text filter to recent trades table**

Below the range toggle, add a local filter input:

```tsx
  const [localTradeFilter, setLocalTradeFilter] = useState('')
  const filteredTrades = useMemo(() => {
    if (!localTradeFilter || !data?.recentTrades) return data?.recentTrades ?? []
    const lower = localTradeFilter.toLowerCase()
    return data.recentTrades.filter(
      (t) => t.tape_label?.toLowerCase().includes(lower),
    )
  }, [data?.recentTrades, localTradeFilter])
```

Render a small filter input above the table:

```tsx
  <input
    type="text"
    value={localTradeFilter}
    onChange={(e) => setLocalTradeFilter(e.target.value)}
    placeholder="filter trades..."
    className="w-40 rounded border border-slate-700 bg-slate-900 px-2 py-[1px] font-mono text-[10px] text-slate-200 placeholder:text-slate-600"
  />
```

Use `filteredTrades` instead of `data.recentTrades` in the table render.

- [ ] **Step 5: Run modal tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="VolumeGridCellModal" --no-coverage`

Fix any broken assertions from the prop change.

- [ ] **Step 6: Commit**

```bash
git add src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx
git commit -m "feat(volume-grid): update CellModal for CellId union + textFilter"
```

---

## Task 12: Integration Test — Full Test Suite

**Files:**
- Modify: Various `__tests__/` files

- [ ] **Step 1: Run full volume-grid test suite**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPattern="volume-grid" --no-coverage`

- [ ] **Step 2: Fix any failures**

Common issues:
- `VolumeGridCard.test.tsx` may assert the presence of schema dropdowns that are now inside `DefaultGridView`
- Type mismatches in mock data for `cell` prop (now expects `CellId` instead of `{fwd, tenor}`)
- Missing module paths for newly created files

- [ ] **Step 3: Run TypeScript compilation check**

Run: `cd SDRUtils/dashboard && npx tsc --noEmit 2>&1 | grep -i error | head -20`

Fix any type errors.

- [ ] **Step 4: Commit fixes**

```bash
git add -A
git commit -m "test(volume-grid): fix test suite after view registry refactor"
```

---

## Task 13: E2E Testing via Chrome MCP

**Files:** None (manual testing)

**Prerequisites:** Dev server running at localhost:3000

- [ ] **Step 1: Start dev server**

Run: `cd SDRUtils/dashboard && npm run dev`

- [ ] **Step 2: Navigate to USD Swaps tape page**

Use Chrome MCP to navigate to the USD Swaps tape page (localhost:3000 route for the tape).

- [ ] **Step 3: Verify Default Grid — no regressions**

Check:
- Volume grid card renders with heatmap cells
- All existing dropdowns (metric, window, baseline, forward schema, tenor schema, package type, view mode, color mode) work
- Cell click opens modal with timeseries chart + intraday seasonality + recent trades
- Modal close works, refresh button works

- [ ] **Step 4: Verify View Switcher**

Check:
- "Grid" and "FOMC Strip" tabs visible in header
- Clicking "FOMC Strip" switches to the strip view
- Clicking "Grid" returns to the default view
- View selection persists across page refresh (localStorage)

- [ ] **Step 5: Verify FOMC Strip**

Check:
- Renders ~6 horizontal cells with FOMC meeting labels (JUN26, SEP26, etc.)
- Absolute/FOMC# toggle switches labels correctly
- Cell click opens modal with volume detail for that FOMC meeting
- Modal shows timeseries and recent trades for FOMC-dated trades

- [ ] **Step 6: Verify Text Filter**

Check:
- Text input visible in header
- Typing "Fed" → grid values change (lower, reflecting filtered subset)
- "filtered" badge appears
- Clear (×) restores original values
- Filter works in both Grid and FOMC Strip views
- Cell modal respects active filter (timeseries reflects filtered data)

- [ ] **Step 7: Verify Bucket Overrides (Default Grid)**

Check:
- Gear icon visible next to schema dropdowns
- Clicking opens popover with bucket checkboxes
- Unchecking a bucket hides that row/column from the grid
- Reset button restores all buckets
- Hidden bucket persists across view switches (within session)

- [ ] **Step 8: Performance check**

Verify:
- Default grid loads in <2s
- FOMC strip loads faster than default (fewer cells, collapseAxis)
- Text filter doesn't cause visible lag (debounce working)

---

## Summary

| Task | What it produces | Test command |
|------|-----------------|--------------|
| 1 | Types + FOMC utility | `npm test -- --testPathPattern="fomcConstantMaturity"` |
| 2 | Grid API: textFilter + collapseAxis | `npm test -- --testPathPattern="volume-grid/__tests__/route.logic"` |
| 3 | Cell API: optional tenor + textFilter | `npm test -- --testPathPattern="volume-grid/cell/__tests__/route.logic"` |
| 4 | Hook updates | `npm test -- --testPathPattern="useVolumeGrid"` |
| 5 | TextFilterInput component | `npm test -- --testPathPattern="TextFilterInput"` |
| 6 | BucketOverridesPopover | `npm test -- --testPathPattern="BucketOverridesPopover"` |
| 7 | DefaultGridView extraction | `npx tsc --noEmit` |
| 8 | FomcStripView + FomcStripCell | `npm test -- --testPathPattern="FomcStripView"` |
| 9 | View registry + switcher | `npx tsc --noEmit` |
| 10 | VolumeGridCard shell refactor | `npm test -- --testPathPattern="VolumeGridCard"` |
| 11 | CellModal CellId union | `npm test -- --testPathPattern="VolumeGridCellModal"` |
| 12 | Integration test fixes | `npm test -- --testPathPattern="volume-grid"` |
| 13 | E2E via Chrome MCP | Manual browser verification |

All test commands run from `SDRUtils/dashboard/`.
