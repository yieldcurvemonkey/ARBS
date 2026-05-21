# Volume Grid Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add custom schema builder, Curve Strip, and Fly Curve prebuilt views to the USD Swaps Tape V2 volume grid.

**Architecture:** Extract shared SQL/percentile utilities from the existing volume-grid route into `volumeGridSqlLib.ts`. Extend the existing `/volume-grid` endpoint with `custom` schema support. Add a new `/volume-grid/structure` endpoint for structure-based analytics (curve/fly). Three new view tabs share the existing VolumeGrid render component.

**Tech Stack:** Next.js API routes, PostgreSQL CTEs, React + Tailwind UI, SWR/polling hooks, localStorage persistence.

**Spec:** `docs/superpowers/specs/2026-05-21-volume-grid-customization-design.md`

---

## Task 1: Types & Constants Foundation

Define all new types, structure definitions, and extend existing type unions before any implementation code depends on them.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/structure-grid.types.ts`
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/structureDefs.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts:19-22`
- Modify: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts:24,26`
- Test: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/structureDefs.test.ts`

- [ ] **Step 1: Create structure-grid.types.ts**

```ts
// ABOUTME: Types for the /volume-grid/structure endpoint and the
// StructureGridView shared component. Curves and flies use the same
// response shape as the standard volume grid but with a "structure"
// axis replacing "tenor".

import type { VolumeGridCell, VolumeGridTotalEntry, VolumeGridSchemaAxis } from './volume-grid.types'

export type StructureType = 'curve' | 'fly'

export interface StructureDef {
  readonly id: string
  readonly label: string
  readonly tenors: readonly number[]
  readonly tolerance: number
}

export interface StructureGridResponse {
  asOf: string
  metric: 'notional' | 'dv01'
  period: string
  lookbackDays: number
  structureType: StructureType
  forwardSchema: string
  axes: {
    forward: VolumeGridSchemaAxis
    structure: VolumeGridSchemaAxis
  }
  cells: VolumeGridCell[]
  totals: {
    rowTotals: Record<string, VolumeGridTotalEntry>
    colTotals: Record<string, VolumeGridTotalEntry>
    grand: VolumeGridTotalEntry
  }
}
```

- [ ] **Step 2: Extend CellId union in volume-grid-views.types.ts**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts`, replace lines 19-22:

```ts
export type CellId =
  | { kind: 'matrix'; fwd: string; tenor: string }
  | { kind: 'collapsed_tenor'; fwd: string }
  | { kind: 'structure'; fwd: string; structure: string; structureType: 'curve' | 'fly' }
```

- [ ] **Step 3: Add `custom` to schema ID types in volumeGridBuckets.ts**

In `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts`, update line 24:

```ts
export type ForwardSchemaId = 'default' | 'legacy' | 'imm16' | 'fomc' | 'custom'
```

Update line 26:

```ts
export type TenorSchemaId = 'default' | 'legacy' | 'venue' | 'custom'
```

Add to `FORWARD_SCHEMA_LABELS` (after line 115):
```ts
const FORWARD_SCHEMA_LABELS: Record<ForwardSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  imm16: 'IMM (16q)',
  fomc: 'FOMC',
  custom: 'Custom',
}
```

Add to `TENOR_SCHEMA_LABELS` (after line 121):
```ts
const TENOR_SCHEMA_LABELS: Record<TenorSchemaId, string> = {
  default: 'Default',
  legacy: 'Legacy',
  venue: 'Venue (MIC)',
  custom: 'Custom',
}
```

Update `FORWARD_SCHEMA_IDS` (line 236):
```ts
export const FORWARD_SCHEMA_IDS: ReadonlyArray<ForwardSchemaId> = ['default', 'legacy', 'imm16', 'fomc', 'custom']
```

Update `TENOR_SCHEMA_IDS` (line 237):
```ts
export const TENOR_SCHEMA_IDS: ReadonlyArray<TenorSchemaId> = ['default', 'legacy', 'venue', 'custom']
```

Add a `structure_default` forward schema and `resolveForwardSchema` custom case. After line 218 (end of `resolveForwardSchema` switch):

```ts
export function resolveForwardSchema(
  id: ForwardSchemaId,
  now: Date = new Date(),
): ResolvedSchema {
  const label = FORWARD_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: FORWARD_DEFAULT, kind: 'years' }
    case 'legacy':  return { id, label, buckets: FORWARD_LEGACY, kind: 'years' }
    case 'imm16':   return { id, label, buckets: computeImm16ForwardBuckets(now), kind: 'years' }
    case 'fomc':
      return {
        id, label,
        buckets: [],
        kind: 'fomc_label',
        extraFilterSql: 'l.fomc_meeting_label IS NOT NULL',
      }
    case 'custom':
      return { id, label, buckets: [], kind: 'years' }
  }
}
```

Add `resolveTenorSchema` custom case. After line 233:

```ts
export function resolveTenorSchema(id: TenorSchemaId): ResolvedSchema {
  const label = TENOR_SCHEMA_LABELS[id]
  switch (id) {
    case 'default': return { id, label, buckets: TENOR_DEFAULT, kind: 'tenor_years' }
    case 'legacy':  return { id, label, buckets: TENOR_LEGACY, kind: 'tenor_years' }
    case 'venue':
      return {
        id, label,
        buckets: [],
        kind: 'venue',
        extraFilterSql: 'l.platform_identifier IS NOT NULL',
      }
    case 'custom':
      return { id, label, buckets: [], kind: 'tenor_years' }
  }
}
```

Add the `structure_default` forward schema and its computation function. Before `FORWARD_SCHEMA_LABELS`:

```ts
export function computeStructureDefaultForwardBuckets(now: Date = new Date()): ReadonlyArray<BucketDef> {
  const imms = computeImmDates(now, 4)
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'short',
    year: '2-digit',
  })
  const immBuckets: BucketDef[] = imms.map((imm, i) => {
    const yearsFromNow = (imm.getTime() - now.getTime()) / (365.25 * ONE_DAY_MS)
    return {
      id: `imm_${i + 1}`,
      label: `IMM${i + 1} (${fmt.format(imm).replace(' ', '')})`,
      lo: Math.max(0, yearsFromNow - 0.125),
      hi: yearsFromNow + 0.125,
    }
  })
  return [
    { id: 'spot', label: 'Spot', lo: null, hi: 0.125 },
    ...immBuckets,
    { id: '1y', label: '1Y', lo: 0.875, hi: 1.125 },
    { id: '2y', label: '2Y', lo: 1.875, hi: 2.125 },
    { id: '5y', label: '5Y', lo: 4.875, hi: 5.125 },
  ]
}
```

- [ ] **Step 4: Create structureDefs.ts**

```ts
// ABOUTME: Curve and fly structure definitions used by CurveStripView
// and FlyCurveView. Each StructureDef identifies a specific multi-leg
// package structure (e.g. "2s10s") by its constituent tenor years.

import type { StructureDef } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'

const T = 0.125  // ±45 day tolerance

export const BENCHMARK_CURVES: readonly StructureDef[] = [
  { id: '2s5s',   label: '2s5s',   tenors: [2, 5],   tolerance: T },
  { id: '2s10s',  label: '2s10s',  tenors: [2, 10],  tolerance: T },
  { id: '2s30s',  label: '2s30s',  tenors: [2, 30],  tolerance: T },
  { id: '5s10s',  label: '5s10s',  tenors: [5, 10],  tolerance: T },
  { id: '5s30s',  label: '5s30s',  tenors: [5, 30],  tolerance: T },
  { id: '10s30s', label: '10s30s', tenors: [10, 30], tolerance: T },
]

export const TIGHT_CURVES: readonly StructureDef[] = [
  { id: '3s5s',   label: '3s5s',   tenors: [3, 5],   tolerance: T },
  { id: '5s7s',   label: '5s7s',   tenors: [5, 7],   tolerance: T },
  { id: '7s10s',  label: '7s10s',  tenors: [7, 10],  tolerance: T },
  { id: '10s20s', label: '10s20s', tenors: [10, 20], tolerance: T },
  { id: '20s30s', label: '20s30s', tenors: [20, 30], tolerance: T },
]

export const ALL_CURVES: readonly StructureDef[] = [...BENCHMARK_CURVES, ...TIGHT_CURVES]

export const STANDARD_FLIES: readonly StructureDef[] = [
  { id: '2s5s10s',  label: '2s5s10s',  tenors: [2, 5, 10],  tolerance: T },
  { id: '2s5s30s',  label: '2s5s30s',  tenors: [2, 5, 30],  tolerance: T },
  { id: '2s10s30s', label: '2s10s30s', tenors: [2, 10, 30], tolerance: T },
  { id: '5s10s30s', label: '5s10s30s', tenors: [5, 10, 30], tolerance: T },
]

export const TIGHT_FLIES: readonly StructureDef[] = [
  { id: '3s5s7s',    label: '3s5s7s',    tenors: [3, 5, 7],    tolerance: T },
  { id: '5s7s10s',   label: '5s7s10s',   tenors: [5, 7, 10],   tolerance: T },
  { id: '7s10s20s',  label: '7s10s20s',  tenors: [7, 10, 20],  tolerance: T },
  { id: '10s20s30s', label: '10s20s30s', tenors: [10, 20, 30], tolerance: T },
]

export const ALL_FLIES: readonly StructureDef[] = [...STANDARD_FLIES, ...TIGHT_FLIES]
```

- [ ] **Step 5: Write structureDefs test**

```ts
import { describe, expect, it } from '@jest/globals'
import {
  ALL_CURVES, ALL_FLIES, BENCHMARK_CURVES, STANDARD_FLIES,
  TIGHT_CURVES, TIGHT_FLIES,
} from '../structureDefs'

describe('structureDefs', () => {
  it('benchmark curves are 2-leg structures', () => {
    for (const s of BENCHMARK_CURVES) {
      expect(s.tenors).toHaveLength(2)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
    }
  })
  it('standard flies are 3-leg structures', () => {
    for (const s of STANDARD_FLIES) {
      expect(s.tenors).toHaveLength(3)
      expect(s.tenors[0]).toBeLessThan(s.tenors[1])
      expect(s.tenors[1]).toBeLessThan(s.tenors[2])
    }
  })
  it('ALL_CURVES = benchmark + tight', () => {
    expect(ALL_CURVES.length).toBe(BENCHMARK_CURVES.length + TIGHT_CURVES.length)
  })
  it('ALL_FLIES = standard + tight', () => {
    expect(ALL_FLIES.length).toBe(STANDARD_FLIES.length + TIGHT_FLIES.length)
  })
  it('all structure ids are unique', () => {
    const allIds = [...ALL_CURVES, ...ALL_FLIES].map((s) => s.id)
    expect(new Set(allIds).size).toBe(allIds.length)
  })
})
```

- [ ] **Step 6: Run tests**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="structureDefs|volumeGridBuckets" --no-coverage`

Expected: All pass. The `volumeGridBuckets` tests verify the existing schemas still work after adding `custom`.

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/structure-grid.types.ts \
  SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/structureDefs.ts \
  SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/structureDefs.test.ts \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid-views.types.ts \
  SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts
git commit -m "feat(volume-grid): add types, structure defs, and custom schema ID support"
```

---

## Task 2: Shared SQL Library Extraction

Extract reusable SQL building blocks from `route.logic.ts` into `volumeGridSqlLib.ts`. The existing endpoint then imports from the library — behavior-preserving refactor.

**Files:**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridSqlLib.ts`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts`
- Test: existing `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts` (must still pass)

- [ ] **Step 1: Create volumeGridSqlLib.ts**

Extract these from `route.logic.ts`:
- `PLATFORM_CASE_SQL` constant (lines 311-318)
- `computePercentile` function (lines 621-626)
- `summariseCells` function (lines 628-654)
- `RawVolumeGridRow` interface (lines 656-675)
- `num` helper (lines 677-680)
- Re-export `buildPkgFamilySql` from volumeGridBuckets

```ts
// ABOUTME: Shared SQL fragments, percentile math, and response-shaping
// utilities used by both /volume-grid and /volume-grid/structure. Split
// from route.logic.ts so the structure endpoint can reuse the same CTE
// patterns without duplicating statistical logic.

import {
  buildPkgFamilySql as _buildPkgFamilySql,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeGridCell,
  VolumeGridResponse,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export const PLATFORM_CASE_SQL = `
  CASE
    WHEN UPPER(COALESCE(l.venue, '')) = 'D2D' THEN 'IDB'
    WHEN UPPER(COALESCE(l.platform_identifier, '')) IN
      ('BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF') THEN 'IDB'
    ELSE 'CUSTY'
  END
`

export const buildPkgFamilySql = _buildPkgFamilySql

export const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export function computePercentile(current: number, prior: ReadonlyArray<number>): number | null {
  if (prior.length === 0) return null
  let lessOrEqual = 0
  for (const v of prior) if (v <= current) lessOrEqual += 1
  return (lessOrEqual / prior.length) * 100
}

export interface RawVolumeGridRow {
  fwd: string
  tenor: string
  current_value: number | string
  idb_current: number | string
  custy_current: number | string
  outright_current: number | string
  curve_current: number | string
  fly_current: number | string
  other_current: number | string
  trade_count: number | string
  prior_array: Array<number | string>
  p25: number | string
  p50: number | string
  p75: number | string
  pmin: number | string
  pmax: number | string
  n: number | string
  as_of_ts: string | Date | null
}

export function rowToCell(r: RawVolumeGridRow): VolumeGridCell {
  const prior = r.prior_array.map(num)
  const current = num(r.current_value)
  return {
    fwd: r.fwd,
    tenor: r.tenor,
    current,
    idbCurrent: num(r.idb_current),
    custyCurrent: num(r.custy_current),
    outrightCurrent: num(r.outright_current),
    curveCurrent: num(r.curve_current),
    flyCurrent: num(r.fly_current),
    otherCurrent: num(r.other_current),
    tradeCount: num(r.trade_count),
    baseline: {
      p25: num(r.p25),
      p50: num(r.p50),
      p75: num(r.p75),
      min: num(r.pmin),
      max: num(r.pmax),
      n: num(r.n),
    },
    percentile: computePercentile(current, prior),
  }
}

export function summariseCells(
  cells: ReadonlyArray<VolumeGridCell>,
): VolumeGridResponse['totals'] {
  const rowTotals: Record<string, { current: number }> = {}
  const colTotals: Record<string, { current: number }> = {}
  let grandCurrent = 0
  for (const c of cells) {
    if (!rowTotals[c.fwd]) rowTotals[c.fwd] = { current: 0 }
    if (!colTotals[c.tenor]) colTotals[c.tenor] = { current: 0 }
    rowTotals[c.fwd].current += c.current
    colTotals[c.tenor].current += c.current
    grandCurrent += c.current
  }
  const wrap = (entry: { current: number }) => ({
    current: entry.current,
    percentile: null as number | null,
  })
  return {
    rowTotals: Object.fromEntries(
      Object.entries(rowTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    colTotals: Object.fromEntries(
      Object.entries(colTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    grand: { current: grandCurrent, percentile: null },
  }
}

export function buildPriorSummaryCte(
  sourceCte: string,
  metricCol: string,
  groupByCols: string[],
): string {
  const groupBy = groupByCols.join(', ')
  return `
    SELECT ${groupBy},
      array_agg(window_value ORDER BY window_value) AS prior_array,
      percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
      percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
      MIN(window_value) AS pmin,
      MAX(window_value) AS pmax,
      COUNT(*)::int AS n
    FROM ${sourceCte}
    GROUP BY ${groupBy}
  `
}

export function buildCurrentAggSelectCols(metricCol: string): string {
  return `
    SUM(${metricCol}) AS current_value,
    SUM(${metricCol}) FILTER (WHERE platform = 'IDB')   AS idb_current,
    SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY') AS custy_current,
    SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
    SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
    SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
    SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
    COUNT(*)::int AS trade_count,
    MAX(ts) AS last_ts
  `
}

export function buildFinalSelectSql(groupByA: string, groupByB: string): string {
  return `
    SELECT
      COALESCE(c.${groupByA}, p.${groupByA})     AS fwd,
      COALESCE(c.${groupByB}, p.${groupByB}) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
      COALESCE(c.idb_current, 0)               AS idb_current,
      COALESCE(c.custy_current, 0)             AS custy_current,
      COALESCE(c.outright_current, 0)          AS outright_current,
      COALESCE(c.curve_current, 0)             AS curve_current,
      COALESCE(c.fly_current, 0)               AS fly_current,
      COALESCE(c.other_current, 0)             AS other_current,
      COALESCE(c.trade_count, 0)               AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0)  AS p25,
      COALESCE(p.p50, 0)  AS p50,
      COALESCE(p.p75, 0)  AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0)    AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (${groupByA}, ${groupByB})
  `
}
```

- [ ] **Step 2: Refactor route.logic.ts to import from shared lib**

In `route.logic.ts`, replace the local definitions with imports:

```ts
import {
  PLATFORM_CASE_SQL,
  buildPkgFamilySql,
  computePercentile,
  summariseCells,
  num,
  rowToCell,
  type RawVolumeGridRow,
} from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
```

Remove from `route.logic.ts`:
- `PLATFORM_CASE_SQL` constant (lines 311-318)
- `computePercentile` function (lines 621-626)
- `summariseCells` function (lines 628-654)
- `RawVolumeGridRow` interface (lines 656-675)
- `num` helper (lines 677-680)

In `shapeVolumeGridResponse` (line 724), replace the inline `map` body with `rowToCell(r)`:

```ts
  const cells: VolumeGridCell[] = rows
    .filter((r) => validFwd.has(r.fwd) && validTenor.has(r.tenor))
    .map((r) => rowToCell(r))
```

Keep re-exporting `computePercentile`, `summariseCells`, and `RawVolumeGridRow` from `route.logic.ts` so existing test imports still work:

```ts
export { computePercentile, summariseCells, type RawVolumeGridRow } from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
```

- [ ] **Step 3: Run existing tests**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid" --no-coverage`

Expected: All existing tests pass unchanged — this is a pure extract refactor.

- [ ] **Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridSqlLib.ts \
  SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts
git commit -m "refactor(volume-grid): extract shared SQL/percentile utils to volumeGridSqlLib"
```

---

## Task 3: Custom Schema API Extension

Extend the existing `/volume-grid` and `/volume-grid/cell` endpoints to accept `custom` schemas with inline bucket definitions via JSON query params.

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts:66-67,72-125`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.ts:38-39`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts:41-42,47-118`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts:50-51`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write the failing test for custom schema parsing**

Add to the bottom of `route.logic.test.ts`:

```ts
describe('parseVolumeGridParams — custom schemas', () => {
  it('accepts forwardSchema=custom with forwardBuckets JSON', () => {
    const buckets = JSON.stringify([
      { id: 'spot', label: 'Spot', lo: null, hi: 0.5 },
      { id: '6m_plus', label: '6M+', lo: 0.5, hi: null },
    ])
    const out = parseVolumeGridParams(
      new URLSearchParams(`forwardSchema=custom&forwardBuckets=${encodeURIComponent(buckets)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.forwardSchema).toBe('custom')
      expect(out.value.customForwardBuckets).toHaveLength(2)
      expect(out.value.customForwardBuckets![0].id).toBe('spot')
    }
  })

  it('rejects forwardSchema=custom without forwardBuckets', () => {
    const out = parseVolumeGridParams(
      new URLSearchParams('forwardSchema=custom'),
    )
    expect(out.ok).toBe(false)
  })

  it('rejects forwardBuckets with invalid JSON', () => {
    const out = parseVolumeGridParams(
      new URLSearchParams('forwardSchema=custom&forwardBuckets=not-json'),
    )
    expect(out.ok).toBe(false)
  })
})
```

- [ ] **Step 2: Run the test to see it fail**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage`

Expected: FAIL — `customForwardBuckets` doesn't exist on the return type yet.

- [ ] **Step 3: Extend VolumeGridParams and parseVolumeGridParams**

In `route.logic.ts`, extend the `VolumeGridParams` interface:

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
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
}
```

Add import for `BucketDef`:

```ts
import {
  ...,
  type BucketDef,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
```

In `parseVolumeGridParams`, after the existing schema validation (around line 90), add custom bucket parsing:

```ts
  let customForwardBuckets: BucketDef[] | undefined
  if (forwardSchemaRaw === 'custom') {
    const raw = search.get('forwardBuckets')
    if (!raw) return { ok: false, error: 'forwardBuckets JSON is required when forwardSchema=custom' }
    try {
      customForwardBuckets = JSON.parse(raw)
      if (!Array.isArray(customForwardBuckets) || customForwardBuckets.length === 0) {
        return { ok: false, error: 'forwardBuckets must be a non-empty array' }
      }
    } catch {
      return { ok: false, error: 'forwardBuckets must be valid JSON' }
    }
  }
  let customTenorBuckets: BucketDef[] | undefined
  if (tenorSchemaRaw === 'custom') {
    const raw = search.get('tenorBuckets')
    if (!raw) return { ok: false, error: 'tenorBuckets JSON is required when tenorSchema=custom' }
    try {
      customTenorBuckets = JSON.parse(raw)
      if (!Array.isArray(customTenorBuckets) || customTenorBuckets.length === 0) {
        return { ok: false, error: 'tenorBuckets must be a non-empty array' }
      }
    } catch {
      return { ok: false, error: 'tenorBuckets must be valid JSON' }
    }
  }
```

Add `customForwardBuckets` and `customTenorBuckets` to the return value.

- [ ] **Step 4: Wire custom buckets through in route.ts**

In `route.ts`, after resolving schemas (lines 38-39), override buckets when custom:

```ts
  const forwardSchema = resolveForwardSchema(parsed.value.forwardSchema, now)
  if (parsed.value.customForwardBuckets) {
    forwardSchema.buckets = parsed.value.customForwardBuckets
  }
  const tenorSchema = resolveTenorSchema(parsed.value.tenorSchema)
  if (parsed.value.customTenorBuckets) {
    tenorSchema.buckets = parsed.value.customTenorBuckets
  }
```

Note: `ResolvedSchema.buckets` is typed as `ReadonlyArray<BucketDef>` — the resolved object from the function is not frozen, so assignment works. But for safety, cast the assignment if TypeScript complains:

```ts
  if (parsed.value.customForwardBuckets) {
    (forwardSchema as { buckets: ReadonlyArray<BucketDef> }).buckets = parsed.value.customForwardBuckets
  }
```

- [ ] **Step 5: Apply the same custom bucket parsing to the cell endpoint**

In `cell/route.logic.ts`, extend `VolumeGridCellParams` with optional `customForwardBuckets` and `customTenorBuckets`. In `parseVolumeGridCellParams`, add the same JSON parsing logic after schema validation.

In `cell/route.ts`, override resolved schema buckets the same way before building predicates.

- [ ] **Step 6: Run tests**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid" --no-coverage`

Expected: All pass including the new custom schema tests.

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts \
  SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.ts \
  SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts \
  SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts \
  SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts
git commit -m "feat(volume-grid): accept custom bucket definitions via JSON query params"
```

---

## Task 4: Structure Endpoint API

New `/volume-grid/structure` route that matches packages to curve/fly structure definitions and computes leg-specific risk metrics.

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/route.logic.ts`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write the failing test for structure param parsing**

Create `structure/__tests__/route.logic.test.ts`:

```ts
import { describe, expect, it } from '@jest/globals'
import { parseStructureGridParams } from '../route.logic'

describe('parseStructureGridParams', () => {
  const validStructures = JSON.stringify([
    { id: '2s10s', label: '2s10s', tenors: [2, 10], tolerance: 0.125 },
  ])

  it('applies defaults with required params', () => {
    const out = parseStructureGridParams(
      new URLSearchParams(`structureType=curve&structures=${encodeURIComponent(validStructures)}`),
    )
    expect(out.ok).toBe(true)
    if (out.ok) {
      expect(out.value.structureType).toBe('curve')
      expect(out.value.metric).toBe('dv01')
      expect(out.value.period).toBe('today')
    }
  })

  it('rejects missing structureType', () => {
    expect(parseStructureGridParams(
      new URLSearchParams(`structures=${encodeURIComponent(validStructures)}`),
    ).ok).toBe(false)
  })

  it('rejects missing structures', () => {
    expect(parseStructureGridParams(
      new URLSearchParams('structureType=curve'),
    ).ok).toBe(false)
  })

  it('rejects invalid structureType', () => {
    expect(parseStructureGridParams(
      new URLSearchParams(`structureType=spread&structures=${encodeURIComponent(validStructures)}`),
    ).ok).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="structure/__tests__/route.logic" --no-coverage`

Expected: FAIL — module not found.

- [ ] **Step 3: Create route.logic.ts for the structure endpoint**

```ts
// ABOUTME: Pure helpers for /api/usd-swaps-tape-v2/volume-grid/structure.
// Matches packages to specific curve/fly structure definitions by leg
// tenors, extracts the risk of a specific leg (long for curves, belly
// for flies), then computes the same percentile/baseline analytics as
// the standard volume grid.

import {
  buildBucketCaseSql,
  buildPackageTypeFilter,
  computeStructureDefaultForwardBuckets,
  resolveForwardSchema,
  PACKAGE_TYPE_GROUPS,
  type BucketDef,
  type ForwardSchemaId,
  type ResolvedSchema,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import {
  PLATFORM_CASE_SQL,
  buildPkgFamilySql,
  computePercentile,
  summariseCells,
  num,
  type RawVolumeGridRow,
} from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
import {
  computeWindowBounds,
  timeOfDayInEt,
  type WindowBounds,
} from '../route.logic'
import type { StructureDef, StructureType, StructureGridResponse } from '@/features/usd-swaps-tape-v2/types/structure-grid.types'
import type { VolumeGridCell, VolumeMetric, VolumePeriod } from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface StructureGridParams {
  structureType: StructureType
  structures: StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  forwardSchema: ForwardSchemaId
  textFilter?: string
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_STRUCTURE_TYPES: ReadonlySet<StructureType> = new Set(['curve', 'fly'])
const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set([
  'today', '1h', '24h', '1w', '2w', '3w', '1m', '3m',
])

export function parseStructureGridParams(search: URLSearchParams): ParseResult<StructureGridParams> {
  const structureTypeRaw = search.get('structureType')
  if (!structureTypeRaw || !VALID_STRUCTURE_TYPES.has(structureTypeRaw as StructureType)) {
    return { ok: false, error: `structureType must be one of ${[...VALID_STRUCTURE_TYPES].join(', ')}` }
  }
  const structuresRaw = search.get('structures')
  if (!structuresRaw) {
    return { ok: false, error: 'structures JSON is required' }
  }
  let structures: StructureDef[]
  try {
    structures = JSON.parse(structuresRaw)
    if (!Array.isArray(structures) || structures.length === 0) {
      return { ok: false, error: 'structures must be a non-empty array' }
    }
  } catch {
    return { ok: false, error: 'structures must be valid JSON' }
  }
  const metricRaw = (search.get('metric') ?? 'dv01').toLowerCase()
  if (!VALID_METRICS.has(metricRaw as VolumeMetric)) {
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  }
  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod)) {
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  }
  let lookbackDays = 90
  const lookbackRaw = search.get('lookbackDays')
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 730) {
      return { ok: false, error: 'lookbackDays must be 1..730' }
    }
    lookbackDays = Math.floor(n)
  }
  const forwardSchemaRaw = (search.get('forwardSchema') ?? 'structure_default').toLowerCase()
  const textFilter = search.get('textFilter') ?? undefined
  return {
    ok: true,
    value: {
      structureType: structureTypeRaw as StructureType,
      structures,
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
      forwardSchema: forwardSchemaRaw as ForwardSchemaId,
      textFilter,
    },
  }
}

function structurePackageTypes(structureType: StructureType): string[] {
  if (structureType === 'curve') {
    return [
      ...PACKAGE_TYPE_GROUPS.curve,
      ...PACKAGE_TYPE_GROUPS.spreadover_curve,
    ]
  }
  return [
    ...PACKAGE_TYPE_GROUPS.fly,
    ...PACKAGE_TYPE_GROUPS.spreadover_fly,
  ]
}

function buildStructureMatchValues(structures: StructureDef[]): string {
  return structures.map((s) => {
    const tenorsArr = `ARRAY[${s.tenors.map((t) => `${t}::numeric`).join(',')}]`
    return `('${s.id}', ${s.tenors.length}, ${tenorsArr}, ${s.tolerance})`
  }).join(',\n    ')
}

export interface BuiltSql {
  sql: string
  params: Array<string | number>
}

export function buildStructureGridSqlTimeOfDay(
  params: StructureGridParams,
  bounds: Extract<WindowBounds, { kind: 'time_of_day' }>,
  forwardSchema: ResolvedSchema,
): BuiltSql {
  const metricCol = params.metric === 'notional' ? 'notional_leg_value' : 'risk_leg_value'
  const fwdBucketExpr = buildBucketCaseSql('rl', 'forward_start_years', forwardSchema.buckets)
  const pkgTypes = structurePackageTypes(params.structureType)
  const pkgTypePlaceholders = pkgTypes.map((_, i) => `$${6 + i}`).join(', ')
  const riskLegRank = params.structureType === 'curve' ? 'sm.leg_count' : '2'

  const sqlParams: Array<string | number> = [
    bounds.lookbackStart.toISOString(),
    bounds.lookbackEnd.toISOString(),
    bounds.todayDateEt,
    bounds.todSecondsLo,
    bounds.todSecondsHi,
    ...pkgTypes,
  ]

  let textFilterClause = ''
  if (params.textFilter != null) {
    const textParamIdx = sqlParams.length + 1
    sqlParams.push(params.textFilter)
    textFilterClause = `AND p.tape_label ILIKE '%' || $${textParamIdx}::text || '%'`
  }

  const sql = `
    WITH structure_defs(structure_id, expected_legs, tenor_array, tolerance) AS (
      VALUES ${buildStructureMatchValues(params.structures)}
    ),
    packages AS (
      SELECT p.package_id, p.execution_start, p.tape_label, p.venue,
             p.platform_identifier, p.is_block_any, p.package_type
      FROM arbs_usd_swap_tape_packages_v2 p
      WHERE p.package_type IN (${pkgTypePlaceholders})
        AND p.execution_start >= $1::timestamptz
        AND p.execution_start <  $2::timestamptz
        ${textFilterClause}
    ),
    structure_match AS (
      SELECT
        p.package_id,
        p.execution_start,
        p.venue,
        p.platform_identifier,
        p.package_type,
        s.structure_id,
        s.expected_legs,
        l.tenor_years,
        ABS(COALESCE(l.risk, 0))     AS risk_val,
        ABS(COALESCE(l.notional, 0)) AS notional_val,
        l.forward_start_years,
        ROW_NUMBER() OVER (
          PARTITION BY p.package_id, s.structure_id
          ORDER BY l.tenor_years ASC
        ) AS leg_rank,
        COUNT(*) OVER (
          PARTITION BY p.package_id, s.structure_id
        ) AS leg_count
      FROM packages p
      JOIN arbs_usd_swap_tape_legs_v2 l ON l.package_id = p.package_id
        AND COALESCE(l.contributes_to_flow, FALSE) = TRUE
      CROSS JOIN structure_defs s
      WHERE EXISTS (
        SELECT 1 FROM unnest(s.tenor_array) AS t(v)
        WHERE l.tenor_years BETWEEN t.v - s.tolerance AND t.v + s.tolerance
      )
    ),
    risk_leg AS (
      SELECT
        sm.package_id,
        sm.structure_id,
        sm.risk_val AS risk_leg_value,
        sm.notional_val AS notional_leg_value,
        sm.forward_start_years,
        sm.execution_start AS ts,
        sm.venue,
        sm.platform_identifier,
        sm.package_type,
        (date_trunc('day', sm.execution_start AT TIME ZONE 'America/New_York'))::date AS day_et,
        EXTRACT(EPOCH FROM (
          (sm.execution_start AT TIME ZONE 'America/New_York')
          - date_trunc('day', sm.execution_start AT TIME ZONE 'America/New_York')
        )) AS tod_seconds_et
      FROM structure_match sm
      WHERE sm.leg_count = sm.expected_legs
        AND sm.leg_rank = ${riskLegRank}
    ),
    bucketed AS (
      SELECT
        structure_id,
        ${fwdBucketExpr} AS fwd_bucket,
        risk_leg_value,
        notional_leg_value,
        ts,
        day_et,
        tod_seconds_et,
        ${PLATFORM_CASE_SQL.replace(/l\./g, 'risk_leg.')} AS platform,
        ${buildPkgFamilySql('risk_leg').replace(/risk_leg\./g, '')} AS pkg_family
      FROM risk_leg
      WHERE tod_seconds_et >= $4::numeric
        AND tod_seconds_et <= $5::numeric
    ),
    prior_per_day AS (
      SELECT fwd_bucket, structure_id, day_et,
        SUM(${metricCol}) AS window_value
      FROM bucketed
      WHERE fwd_bucket <> 'other' AND day_et < $3::date
      GROUP BY fwd_bucket, structure_id, day_et
    ),
    prior_summary AS (
      SELECT fwd_bucket, structure_id,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin,
        MAX(window_value) AS pmax,
        COUNT(*)::int AS n
      FROM prior_per_day
      GROUP BY fwd_bucket, structure_id
    ),
    current_agg AS (
      SELECT fwd_bucket, structure_id,
        SUM(${metricCol}) AS current_value,
        SUM(${metricCol}) FILTER (WHERE platform = 'IDB')   AS idb_current,
        SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY') AS custy_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM bucketed
      WHERE fwd_bucket <> 'other' AND day_et = $3::date
      GROUP BY fwd_bucket, structure_id
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket) AS fwd,
      COALESCE(c.structure_id, p.structure_id) AS tenor,
      COALESCE(c.current_value, 0) AS current_value,
      COALESCE(c.idb_current, 0) AS idb_current,
      COALESCE(c.custy_current, 0) AS custy_current,
      COALESCE(c.outright_current, 0) AS outright_current,
      COALESCE(c.curve_current, 0) AS curve_current,
      COALESCE(c.fly_current, 0) AS fly_current,
      COALESCE(c.other_current, 0) AS other_current,
      COALESCE(c.trade_count, 0) AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0) AS p25,
      COALESCE(p.p50, 0) AS p50,
      COALESCE(p.p75, 0) AS p75,
      COALESCE(p.pmin, 0) AS pmin,
      COALESCE(p.pmax, 0) AS pmax,
      COALESCE(p.n, 0) AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, structure_id)
  `

  return { sql, params: sqlParams }
}

export function buildStructureGridSqlRolling(
  params: StructureGridParams,
  bounds: Extract<WindowBounds, { kind: 'rolling' }>,
  forwardSchema: ResolvedSchema,
): BuiltSql {
  const metricCol = params.metric === 'notional' ? 'notional_leg_value' : 'risk_leg_value'
  const fwdBucketExpr = buildBucketCaseSql('rl', 'forward_start_years', forwardSchema.buckets)
  const pkgTypes = structurePackageTypes(params.structureType)
  const pkgTypePlaceholders = pkgTypes.map((_, i) => `$${4 + i}`).join(', ')
  const riskLegRank = params.structureType === 'curve' ? 'sm.leg_count' : '2'

  const sqlParams: Array<string | number> = [
    bounds.lookbackStart.toISOString(),
    bounds.lookbackEnd.toISOString(),
    bounds.currentStart.toISOString(),
    ...pkgTypes,
  ]

  let textFilterClause = ''
  if (params.textFilter != null) {
    const textParamIdx = sqlParams.length + 1
    sqlParams.push(params.textFilter)
    textFilterClause = `AND p.tape_label ILIKE '%' || $${textParamIdx}::text || '%'`
  }

  // Same CTE chain as time-of-day but with rolling window logic
  // (identical to the standard volume grid's rolling mode)
  const sql = `
    WITH structure_defs(structure_id, expected_legs, tenor_array, tolerance) AS (
      VALUES ${buildStructureMatchValues(params.structures)}
    ),
    packages AS (
      SELECT p.package_id, p.execution_start, p.tape_label, p.venue,
             p.platform_identifier, p.is_block_any, p.package_type
      FROM arbs_usd_swap_tape_packages_v2 p
      WHERE p.package_type IN (${pkgTypePlaceholders})
        AND p.execution_start >= $1::timestamptz
        AND p.execution_start <  $2::timestamptz
        ${textFilterClause}
    ),
    structure_match AS (
      SELECT
        p.package_id, p.execution_start, p.venue, p.platform_identifier, p.package_type,
        s.structure_id, s.expected_legs,
        l.tenor_years,
        ABS(COALESCE(l.risk, 0)) AS risk_val,
        ABS(COALESCE(l.notional, 0)) AS notional_val,
        l.forward_start_years,
        ROW_NUMBER() OVER (PARTITION BY p.package_id, s.structure_id ORDER BY l.tenor_years ASC) AS leg_rank,
        COUNT(*) OVER (PARTITION BY p.package_id, s.structure_id) AS leg_count
      FROM packages p
      JOIN arbs_usd_swap_tape_legs_v2 l ON l.package_id = p.package_id
        AND COALESCE(l.contributes_to_flow, FALSE) = TRUE
      CROSS JOIN structure_defs s
      WHERE EXISTS (
        SELECT 1 FROM unnest(s.tenor_array) AS t(v)
        WHERE l.tenor_years BETWEEN t.v - s.tolerance AND t.v + s.tolerance
      )
    ),
    risk_leg AS (
      SELECT sm.package_id, sm.structure_id,
        sm.risk_val AS risk_leg_value, sm.notional_val AS notional_leg_value,
        sm.forward_start_years, sm.execution_start AS ts,
        sm.venue, sm.platform_identifier, sm.package_type
      FROM structure_match sm
      WHERE sm.leg_count = sm.expected_legs AND sm.leg_rank = ${riskLegRank}
    ),
    bucketed AS (
      SELECT
        structure_id,
        ${fwdBucketExpr} AS fwd_bucket,
        risk_leg_value, notional_leg_value, ts,
        ${PLATFORM_CASE_SQL.replace(/l\./g, 'risk_leg.')} AS platform,
        ${buildPkgFamilySql('risk_leg').replace(/risk_leg\./g, '')} AS pkg_family,
        CASE WHEN ts >= $3::timestamptz THEN 'current' ELSE 'baseline' END AS window_kind,
        ${bounds.windowIdSql} AS baseline_window_id
      FROM risk_leg
    ),
    prior_per_window AS (
      SELECT fwd_bucket, structure_id, baseline_window_id,
        SUM(${metricCol}) AS window_value
      FROM bucketed
      WHERE window_kind = 'baseline' AND fwd_bucket <> 'other'
      GROUP BY fwd_bucket, structure_id, baseline_window_id
    ),
    prior_summary AS (
      SELECT fwd_bucket, structure_id,
        array_agg(window_value ORDER BY window_value) AS prior_array,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY window_value) AS p25,
        percentile_cont(0.50) WITHIN GROUP (ORDER BY window_value) AS p50,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY window_value) AS p75,
        MIN(window_value) AS pmin, MAX(window_value) AS pmax, COUNT(*)::int AS n
      FROM prior_per_window
      GROUP BY fwd_bucket, structure_id
    ),
    current_agg AS (
      SELECT fwd_bucket, structure_id,
        SUM(${metricCol}) AS current_value,
        SUM(${metricCol}) FILTER (WHERE platform = 'IDB') AS idb_current,
        SUM(${metricCol}) FILTER (WHERE platform = 'CUSTY') AS custy_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve') AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly') AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other') AS other_current,
        COUNT(*)::int AS trade_count, MAX(ts) AS last_ts
      FROM bucketed
      WHERE window_kind = 'current' AND fwd_bucket <> 'other'
      GROUP BY fwd_bucket, structure_id
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket) AS fwd,
      COALESCE(c.structure_id, p.structure_id) AS tenor,
      COALESCE(c.current_value, 0) AS current_value,
      COALESCE(c.idb_current, 0) AS idb_current,
      COALESCE(c.custy_current, 0) AS custy_current,
      COALESCE(c.outright_current, 0) AS outright_current,
      COALESCE(c.curve_current, 0) AS curve_current,
      COALESCE(c.fly_current, 0) AS fly_current,
      COALESCE(c.other_current, 0) AS other_current,
      COALESCE(c.trade_count, 0) AS trade_count,
      COALESCE(p.prior_array, ARRAY[]::numeric[]) AS prior_array,
      COALESCE(p.p25, 0) AS p25, COALESCE(p.p50, 0) AS p50, COALESCE(p.p75, 0) AS p75,
      COALESCE(p.pmin, 0) AS pmin, COALESCE(p.pmax, 0) AS pmax, COALESCE(p.n, 0) AS n,
      MAX(c.last_ts) OVER () AS as_of_ts
    FROM current_agg c
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, structure_id)
  `

  return { sql, params: sqlParams }
}

export function buildStructureGridSql(
  params: StructureGridParams,
  bounds: WindowBounds,
  forwardSchema: ResolvedSchema,
): BuiltSql {
  return bounds.kind === 'time_of_day'
    ? buildStructureGridSqlTimeOfDay(params, bounds, forwardSchema)
    : buildStructureGridSqlRolling(params, bounds as Extract<WindowBounds, { kind: 'rolling' }>, forwardSchema)
}

export function resolveStructureForwardSchema(
  id: string,
  now: Date,
): ResolvedSchema {
  if (id === 'structure_default') {
    return {
      id: 'structure_default',
      label: 'Structure Default',
      buckets: computeStructureDefaultForwardBuckets(now),
      kind: 'years',
    }
  }
  return resolveForwardSchema(id as ForwardSchemaId, now)
}

export function shapeStructureGridResponse(
  rows: ReadonlyArray<RawVolumeGridRow>,
  params: StructureGridParams,
  forwardSchema: ResolvedSchema,
): StructureGridResponse {
  const validFwd = new Set(forwardSchema.buckets.map((b) => b.id))
  const validStructure = new Set(params.structures.map((s) => s.id))
  const cells: VolumeGridCell[] = rows
    .filter((r) => validFwd.has(r.fwd) && validStructure.has(r.tenor))
    .map((r) => {
      const prior = r.prior_array.map(num)
      const current = num(r.current_value)
      return {
        fwd: r.fwd,
        tenor: r.tenor,
        current,
        idbCurrent: num(r.idb_current),
        custyCurrent: num(r.custy_current),
        outrightCurrent: num(r.outright_current),
        curveCurrent: num(r.curve_current),
        flyCurrent: num(r.fly_current),
        otherCurrent: num(r.other_current),
        tradeCount: num(r.trade_count),
        baseline: {
          p25: num(r.p25), p50: num(r.p50), p75: num(r.p75),
          min: num(r.pmin), max: num(r.pmax), n: num(r.n),
        },
        percentile: computePercentile(current, prior),
      }
    })
  const totals = summariseCells(cells)
  const asOf = (() => {
    const raw = rows[0]?.as_of_ts
    if (!raw) return new Date().toISOString()
    if (raw instanceof Date) return raw.toISOString()
    return new Date(String(raw)).toISOString()
  })()
  return {
    asOf,
    metric: params.metric,
    period: params.period,
    lookbackDays: params.lookbackDays,
    structureType: params.structureType,
    forwardSchema: params.forwardSchema,
    axes: {
      forward: {
        id: forwardSchema.id,
        label: forwardSchema.label,
        buckets: forwardSchema.buckets.map((b) => ({ id: b.id, label: b.label })),
      },
      structure: {
        id: 'structures',
        label: 'Structures',
        buckets: params.structures.map((s) => ({ id: s.id, label: s.label })),
      },
    },
    cells,
    totals,
  }
}
```

- [ ] **Step 4: Create route.ts for the structure endpoint**

```ts
// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/structure
// Returns structure × forward matrix of {current, baseline, percentile}
// for curve/fly package structures with leg-specific risk extraction.

import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import { computeWindowBounds } from '../route.logic'
import type { RawVolumeGridRow } from '@/lib/usd-swaps-tape-v2/volumeGridSqlLib'
import {
  buildStructureGridSql,
  parseStructureGridParams,
  resolveStructureForwardSchema,
  shapeStructureGridResponse,
} from './route.logic'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 2048)
const LRU_TTL = Number(process.env.ANALYTICS_LRU_TTL ?? 300_000)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: LRU_TTL,
})
const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=300, stale-while-revalidate=600',
} as const

async function produceStructureGrid(request: Request): Promise<{ status: number; payload: unknown }> {
  const { searchParams } = new URL(request.url)
  const parsed = parseStructureGridParams(searchParams)
  if (!parsed.ok) return { status: 400, payload: { error: parsed.error } }

  const now = new Date()
  const bounds = computeWindowBounds(parsed.value.period, parsed.value.lookbackDays, now)
  const forwardSchema = resolveStructureForwardSchema(parsed.value.forwardSchema, now)
  const built = buildStructureGridSql(parsed.value, bounds, forwardSchema)

  try {
    const { rows } = await query<RawVolumeGridRow>(built.sql, built.params)
    const payload = shapeStructureGridResponse(rows, parsed.value, forwardSchema)
    return { status: 200, payload }
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/structure error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch structure grid'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceStructureGrid,
)
```

- [ ] **Step 5: Run tests**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="structure/__tests__/route.logic" --no-coverage`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/structure/
git commit -m "feat(volume-grid): add /volume-grid/structure endpoint for curve/fly analytics"
```

---

## Task 5: Structure Cell Endpoint Extension

Extend the existing `/volume-grid/cell` endpoint to handle `kind: 'structure'` cell drill-downs.

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts:23-118`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts:43-202`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`

- [ ] **Step 1: Extend cell param parsing for structure mode**

In `cell/route.logic.ts`, extend `VolumeGridCellParams`:

```ts
export interface VolumeGridCellParams {
  fwd: string
  tenor?: string
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit: number
  forwardSchema: ForwardSchemaId
  tenorSchema: TenorSchemaId
  packageType: PackageTypeGroupId
  textFilter?: string
  structureType?: 'curve' | 'fly'
  structureTenors?: number[]
  structureTolerance?: number
}
```

In `parseVolumeGridCellParams`, add structure param parsing after the existing validation:

```ts
  const structureType = search.get('structureType') as 'curve' | 'fly' | null ?? undefined
  let structureTenors: number[] | undefined
  let structureTolerance: number | undefined
  if (structureType) {
    if (structureType !== 'curve' && structureType !== 'fly') {
      return { ok: false, error: `structureType must be curve or fly` }
    }
    const tenorsRaw = search.get('structureTenors')
    if (!tenorsRaw) return { ok: false, error: 'structureTenors is required when structureType is set' }
    try {
      structureTenors = JSON.parse(tenorsRaw)
      if (!Array.isArray(structureTenors)) return { ok: false, error: 'structureTenors must be an array' }
    } catch {
      return { ok: false, error: 'structureTenors must be valid JSON' }
    }
    structureTolerance = Number(search.get('structureTolerance') ?? 0.125)
  }
```

When `structureType` is set, make `tenor` optional (the structure itself defines the tenor constraint).

- [ ] **Step 2: Build structure-aware bucket predicates in cell/route.ts**

In `cell/route.ts`, add a new branch for structure mode. When `p.structureType` is present:

```ts
  if (p.structureType && p.structureTenors) {
    // Structure mode: match packages by multi-leg tenor pattern
    const pkgTypes = p.structureType === 'curve'
      ? ['CURVE', 'SPREADOVER_CURVE', 'MATCHED_MATURITY_CURVE']
      : ['FLY', 'SPREADOVER_FLY', 'MATCHED_MATURITY_FLY']

    // Build a structure-aware predicate for the cell's trades
    // This filters to packages whose legs match the structure tenors
    // AND fall in the forward bucket
    // (Implementation: build SQL predicate that matches packages via
    // leg tenors within tolerance, same CROSS JOIN pattern as the
    // structure endpoint but scoped to a single structure)
  }
```

The three parallel queries (timeseries, intraday, recent trades) use the structure-aware predicate instead of the standard bucket predicate.

For recent trades, add an `is_risk_leg` flag to the legs subquery: the leg whose `leg_rank` matches the risk leg (max tenor for curve, rank 2 for fly).

- [ ] **Step 3: Run tests**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/cell" --no-coverage`

Expected: All existing tests pass, new structure tests pass.

- [ ] **Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/
git commit -m "feat(volume-grid): extend cell endpoint with structure-matching predicate"
```

---

## Task 6: useStructureGrid Hook

Data-fetching hook for the structure endpoint, mirroring `useVolumeGrid`.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useStructureGrid.ts`

- [ ] **Step 1: Create useStructureGrid.ts**

```ts
// ABOUTME: Hook for /api/usd-swaps-tape-v2/volume-grid/structure. Same
// polling pattern as useVolumeGrid — plain useState/setInterval, pauses
// when collapsed or tab hidden.
'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TAPE_V2_API_BASE } from '../constants'
import type { VolumeMetric, VolumePeriod } from '../types/volume-grid.types'
import type { StructureDef, StructureGridResponse, StructureType } from '../types/structure-grid.types'

export interface UseStructureGridArgs {
  structureType: StructureType
  structures: readonly StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
  forwardSchema?: string
  collapsed: boolean
  textFilter?: string
}

export interface UseStructureGridReturn {
  data: StructureGridResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<StructureGridResponse | undefined>
}

const REFRESH_MS = 30_000

export function buildStructureGridUrl(
  args: Pick<UseStructureGridArgs,
    'structureType' | 'structures' | 'metric' | 'period' | 'lookbackDays' | 'forwardSchema' | 'textFilter'
  >,
): string {
  const q = new URLSearchParams({
    structureType: args.structureType,
    structures: JSON.stringify(args.structures),
    metric: args.metric,
    period: args.period,
    forwardSchema: args.forwardSchema ?? 'structure_default',
  })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  if (args.textFilter) q.set('textFilter', args.textFilter)
  return `${TAPE_V2_API_BASE}/volume-grid/structure?${q}`
}

export function useStructureGrid(args: UseStructureGridArgs): UseStructureGridReturn {
  const url = args.collapsed ? null : buildStructureGridUrl(args)
  const [data, setData] = useState<StructureGridResponse | undefined>(undefined)
  const [error, setError] = useState<Error | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const urlRef = useRef(url)
  urlRef.current = url
  const generationRef = useRef(0)

  const runFetch = useCallback(async (): Promise<StructureGridResponse | undefined> => {
    const target = urlRef.current
    if (!target) return undefined
    const gen = ++generationRef.current
    setIsLoading(true)
    try {
      const res = await fetch(target)
      if (!res.ok) throw new Error(`structure-grid fetch failed: ${res.status}`)
      const payload = (await res.json()) as StructureGridResponse
      if (generationRef.current !== gen) return undefined
      setData(payload)
      setError(null)
      return payload
    } catch (e) {
      if (generationRef.current !== gen) return undefined
      setError(e instanceof Error ? e : new Error(String(e)))
      return undefined
    } finally {
      if (generationRef.current === gen) setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!url) return
    void runFetch()
    let id: number | null = window.setInterval(() => void runFetch(), REFRESH_MS)
    const onVis = () => {
      if (document.hidden) { if (id != null) { window.clearInterval(id); id = null } }
      else { void runFetch(); if (id == null) id = window.setInterval(() => void runFetch(), REFRESH_MS) }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => { if (id != null) window.clearInterval(id); document.removeEventListener('visibilitychange', onVis) }
  }, [url, runFetch])

  return useMemo(() => ({ data, error, isLoading, refresh: runFetch }), [data, error, isLoading, runFetch])
}
```

- [ ] **Step 2: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useStructureGrid.ts
git commit -m "feat(volume-grid): add useStructureGrid hook for structure endpoint"
```

---

## Task 7: StructureGridView Shared Component + Curve Strip + Fly Curve Views

Create the shared `StructureGridView` component and the two thin wrapper views.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/StructureGridView.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CurveStripView.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FlyCurveView.tsx`

- [ ] **Step 1: Create StructureGridView.tsx**

```tsx
'use client'
// ABOUTME: Shared component for Curve Strip and Fly Curve views. Fetches
// from /volume-grid/structure and renders the existing VolumeGrid with
// forward-start rows × structure columns.

import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useStructureGrid } from '../../../hooks/useStructureGrid'
import type {
  VolumeGridColorMode,
  VolumeGridViewMode,
  VolumeMetric,
  VolumePeriod,
  VolumeGridResponse,
} from '../../../types/volume-grid.types'
import type { StructureDef, StructureType } from '../../../types/structure-grid.types'
import type { CellId } from '../../../types/volume-grid-views.types'

export interface StructureGridViewProps {
  structureType: StructureType
  structures: readonly StructureDef[]
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  textFilter: string
  onCellClick: (cell: CellId) => void
}

export function StructureGridView({
  structureType,
  structures,
  metric,
  period,
  lookbackDays,
  textFilter,
  onCellClick,
}: StructureGridViewProps): JSX.Element {
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')

  const grid = useStructureGrid({
    structureType,
    structures,
    metric,
    period,
    lookbackDays,
    textFilter,
    collapsed: false,
  })

  const gridData: VolumeGridResponse | undefined = useMemo(() => {
    if (!grid.data) return undefined
    return {
      asOf: grid.data.asOf,
      metric: grid.data.metric as VolumeMetric,
      period: grid.data.period as VolumePeriod,
      lookbackDays: grid.data.lookbackDays,
      forwardSchema: 'default' as const,
      tenorSchema: 'default' as const,
      packageType: 'all' as const,
      viewMode: 'volume' as const,
      axes: {
        forward: grid.data.axes.forward,
        tenor: grid.data.axes.structure,
      },
      cells: grid.data.cells,
      totals: grid.data.totals,
    }
  }, [grid.data])

  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      onCellClick({
        kind: 'structure',
        fwd: id.fwd,
        structure: id.tenor,
        structureType,
      })
    },
    [onCellClick, structureType],
  )

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <Toggle
          options={[
            { id: 'activity' as const, label: 'Activity' },
            { id: 'grid' as const, label: 'Grid' },
          ]}
          value={colorMode}
          onChange={setColorMode}
        />
        <Toggle
          options={[
            { id: 'volume' as const, label: 'Volume' },
            { id: 'idb_custy' as const, label: 'IDB / CUSTY' },
          ]}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      {gridData ? (
        <VolumeGrid
          data={gridData}
          metric={metric}
          period={period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType="all"
          onCellClick={handleCellClick}
        />
      ) : (
        <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
          {Array.from({ length: 96 }).map((_, i) => (
            <div key={i} className="rounded-sm bg-slate-800/40" />
          ))}
        </div>
      )}
    </div>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Create CurveStripView.tsx**

```tsx
'use client'
import type { JSX } from 'react'
import { useState } from 'react'
import { StructureGridView } from './StructureGridView'
import { BENCHMARK_CURVES, ALL_CURVES } from '@/lib/usd-swaps-tape-v2/structureDefs'
import type { ViewProps } from '../../../types/volume-grid-views.types'

export function CurveStripView(props: ViewProps): JSX.Element {
  const [showAll, setShowAll] = useState(false)
  return (
    <>
      <div className="flex items-center gap-2 px-3 pb-1">
        <Toggle
          options={[
            { id: 'benchmark', label: 'Benchmark' },
            { id: 'all', label: 'All' },
          ]}
          value={showAll ? 'all' : 'benchmark'}
          onChange={(v) => setShowAll(v === 'all')}
        />
      </div>
      <StructureGridView
        structureType="curve"
        structures={showAll ? ALL_CURVES : BENCHMARK_CURVES}
        metric={props.metric}
        period={props.period}
        lookbackDays={props.lookbackDays}
        textFilter={props.textFilter}
        onCellClick={props.onCellClick}
      />
    </>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Create FlyCurveView.tsx**

```tsx
'use client'
import type { JSX } from 'react'
import { useState } from 'react'
import { StructureGridView } from './StructureGridView'
import { STANDARD_FLIES, ALL_FLIES } from '@/lib/usd-swaps-tape-v2/structureDefs'
import type { ViewProps } from '../../../types/volume-grid-views.types'

export function FlyCurveView(props: ViewProps): JSX.Element {
  const [showAll, setShowAll] = useState(false)
  return (
    <>
      <div className="flex items-center gap-2 px-3 pb-1">
        <Toggle
          options={[
            { id: 'standard', label: 'Standard' },
            { id: 'all', label: 'All' },
          ]}
          value={showAll ? 'all' : 'standard'}
          onChange={(v) => setShowAll(v === 'all')}
        />
      </div>
      <StructureGridView
        structureType="fly"
        structures={showAll ? ALL_FLIES : STANDARD_FLIES}
        metric={props.metric}
        period={props.period}
        lookbackDays={props.lookbackDays}
        textFilter={props.textFilter}
        onCellClick={props.onCellClick}
      />
    </>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/StructureGridView.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CurveStripView.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/FlyCurveView.tsx
git commit -m "feat(volume-grid): add StructureGridView, CurveStripView, FlyCurveView"
```

---

## Task 8: Custom Schema Builder UI

Create the Custom view tab with schema builder modal and localStorage persistence.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/CustomSchemaBuilderModal.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CustomGridView.tsx`

- [ ] **Step 1: Create CustomSchemaBuilderModal.tsx**

A modal dialog with:
- Name input
- Tenor axis bucket editor (list of {label, lo, hi} rows with add/remove)
- Forward axis bucket editor (same)
- Package type dropdown
- Preset loader (Default, Legacy schemas as starting points)
- Save/Load/Delete/Apply buttons
- localStorage persistence at `usd-tape-v2:volume-grid:custom-schemas`

The modal takes `{ open, onClose, onApply, initialSchema? }` props. `onApply` receives a `CustomSchema` object. See spec Section 2 for the full interface.

This is a form-heavy component (~200 lines) following the existing Tailwind patterns. The bucket editor renders each bucket as a row of inputs:
```
[Label input] [Lo number] [Hi number] [× button]
[+ Add Bucket]
```

- [ ] **Step 2: Create CustomGridView.tsx**

```tsx
'use client'
import type { JSX } from 'react'
import { useCallback, useMemo, useState } from 'react'
import { VolumeGrid } from '../VolumeGrid'
import { useVolumeGrid } from '../../../hooks/useVolumeGrid'
import { CustomSchemaBuilderModal } from '../CustomSchemaBuilderModal'
import type { CellId, BucketOverrides } from '../../../types/volume-grid-views.types'
import type { ViewProps } from '../../../types/volume-grid-views.types'
import type { VolumeGridColorMode, VolumeGridViewMode } from '../../../types/volume-grid.types'
import type { BucketDef, PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

interface CustomSchema {
  name: string
  tenorBuckets: BucketDef[]
  forwardBuckets: BucketDef[]
  packageType: PackageTypeGroupId
}

const LS_SCHEMAS = 'usd-tape-v2:volume-grid:custom-schemas'
const LS_ACTIVE = 'usd-tape-v2:volume-grid:custom-active'

function loadSchemas(): CustomSchema[] {
  try {
    const raw = window.localStorage.getItem(LS_SCHEMAS)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function loadActiveIndex(): number | null {
  const raw = window.localStorage.getItem(LS_ACTIVE)
  if (raw == null) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

export function CustomGridView(props: ViewProps): JSX.Element {
  const [schemas, setSchemas] = useState<CustomSchema[]>(() =>
    typeof window === 'undefined' ? [] : loadSchemas(),
  )
  const [activeIdx, setActiveIdx] = useState<number | null>(() =>
    typeof window === 'undefined' ? null : loadActiveIndex(),
  )
  const [modalOpen, setModalOpen] = useState(false)
  const [viewMode, setViewMode] = useState<VolumeGridViewMode>('volume')
  const [colorMode, setColorMode] = useState<VolumeGridColorMode>('activity')

  const active = activeIdx != null ? schemas[activeIdx] : undefined

  const grid = useVolumeGrid({
    metric: props.metric,
    period: props.period,
    lookbackDays: props.lookbackDays,
    forwardSchema: active ? 'custom' : 'default',
    tenorSchema: active ? 'custom' : 'default',
    packageType: active?.packageType ?? 'all',
    viewMode,
    textFilter: props.textFilter,
    collapsed: !active,
    // Custom bucket JSON params are added to the URL by the hook
    // via the forwardBuckets/tenorBuckets query params
  })

  // Override the URL builder to include custom buckets
  // (This requires extending useVolumeGrid or building the URL manually)

  const handleCellClick = useCallback(
    (id: { fwd: string; tenor: string }) => {
      props.onCellClick({ kind: 'matrix', fwd: id.fwd, tenor: id.tenor })
    },
    [props.onCellClick],
  )

  const handleApply = useCallback((schema: CustomSchema) => {
    const newSchemas = [...schemas]
    const existingIdx = newSchemas.findIndex((s) => s.name === schema.name)
    if (existingIdx >= 0) {
      newSchemas[existingIdx] = schema
      setActiveIdx(existingIdx)
    } else {
      newSchemas.push(schema)
      setActiveIdx(newSchemas.length - 1)
    }
    setSchemas(newSchemas)
    window.localStorage.setItem(LS_SCHEMAS, JSON.stringify(newSchemas))
    window.localStorage.setItem(LS_ACTIVE, String(existingIdx >= 0 ? existingIdx : newSchemas.length - 1))
    setModalOpen(false)
  }, [schemas])

  if (!active) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-12 text-slate-400">
        <p className="font-mono text-sm">No custom schema configured</p>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="rounded border border-indigo-500/40 bg-indigo-500/15 px-4 py-1.5 font-mono text-[11px] text-indigo-200 hover:bg-indigo-500/25"
        >
          Configure Custom Schema
        </button>
        <CustomSchemaBuilderModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onApply={handleApply}
        />
      </div>
    )
  }

  return (
    <div className="px-3 pb-3">
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] text-slate-300 hover:bg-slate-800"
        >
          ⚙ {active.name}
        </button>
        <Toggle
          options={[
            { id: 'activity' as const, label: 'Activity' },
            { id: 'grid' as const, label: 'Grid' },
          ]}
          value={colorMode}
          onChange={setColorMode}
        />
        <Toggle
          options={[
            { id: 'volume' as const, label: 'Volume' },
            { id: 'idb_custy' as const, label: 'IDB / CUSTY' },
          ]}
          value={viewMode}
          onChange={setViewMode}
        />
      </div>
      {grid.data ? (
        <VolumeGrid
          data={grid.data}
          metric={props.metric}
          period={props.period}
          viewMode={viewMode}
          colorMode={colorMode}
          packageType={active.packageType}
          onCellClick={handleCellClick}
        />
      ) : (
        <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
          {Array.from({ length: 96 }).map((_, i) => (
            <div key={i} className="rounded-sm bg-slate-800/40" />
          ))}
        </div>
      )}
      <CustomSchemaBuilderModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onApply={handleApply}
        initialSchema={active}
      />
    </div>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >{o.label}</button>
      ))}
    </div>
  )
}
```

Note: the `useVolumeGrid` hook's `buildVolumeGridUrl` needs to be extended to include `forwardBuckets` and `tenorBuckets` JSON params when `forwardSchema='custom'` or `tenorSchema='custom'`. Add optional `customForwardBuckets` and `customTenorBuckets` to `UseVolumeGridArgs` and update `buildVolumeGridUrl` to serialize them.

- [ ] **Step 3: Extend useVolumeGrid to support custom bucket params**

In `useVolumeGrid.ts`, add to `UseVolumeGridArgs`:
```ts
  customForwardBuckets?: BucketDef[]
  customTenorBuckets?: BucketDef[]
```

In `buildVolumeGridUrl`, add:
```ts
  if (args.customForwardBuckets) q.set('forwardBuckets', JSON.stringify(args.customForwardBuckets))
  if (args.customTenorBuckets) q.set('tenorBuckets', JSON.stringify(args.customTenorBuckets))
```

- [ ] **Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/CustomSchemaBuilderModal.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/CustomGridView.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts
git commit -m "feat(volume-grid): add CustomGridView with schema builder modal"
```

---

## Task 9: Cell Modal Integration

Wire the new `CellId` kinds through the modal system — structure cells route to the structure-aware cell endpoint, risk legs get visual highlighting.

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx:82-93`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts:14-52`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx:281-298`

- [ ] **Step 1: Update VolumeGridCard modalCell derivation**

In `VolumeGridCard.tsx`, replace lines 87-93:

```ts
  const modalCell = selectedCell
    ? selectedCell.kind === 'matrix'
      ? { fwd: selectedCell.fwd, tenor: selectedCell.tenor }
      : selectedCell.kind === 'collapsed_tenor'
        ? { fwd: selectedCell.fwd }
        : { fwd: selectedCell.fwd, tenor: selectedCell.structure }
    : null

  const modalForwardSchema = selectedCell?.kind === 'collapsed_tenor' ? 'fomc' as const : 'default' as const

  const modalStructureType = selectedCell?.kind === 'structure' ? selectedCell.structureType : undefined
  const modalStructure = selectedCell?.kind === 'structure' ? selectedCell.structure : undefined
```

Pass `structureType` and `structure` to `VolumeGridCellModal`.

- [ ] **Step 2: Extend useVolumeGridCell for structure mode**

In `useVolumeGridCell.ts`, add to `UseVolumeGridCellArgs`:

```ts
  structureType?: 'curve' | 'fly'
  structureTenors?: number[]
  structureTolerance?: number
```

In `buildVolumeGridCellUrl`, when `args.structureType` is set, add the structure params:

```ts
  if (args.structureType) {
    q.set('structureType', args.structureType)
    if (args.structureTenors) q.set('structureTenors', JSON.stringify(args.structureTenors))
    if (args.structureTolerance != null) q.set('structureTolerance', String(args.structureTolerance))
  }
```

- [ ] **Step 3: Add risk leg highlighting in VolumeGridCellModal**

In `VolumeGridCellModal.tsx`, in the leg rows section (around line 282), add a visual highlight when the leg is the risk leg. The `RecentTradeLeg` type gets an optional `isRiskLeg` field from the API response.

In the leg row `<tr>`, add conditional styling:

```tsx
<tr key={`leg-${i}`} data-testid="leg-row"
  className={`border-t border-slate-800/30 bg-slate-900/40 text-[10px] ${
    leg.isRiskLeg ? 'text-amber-300 font-medium' : 'text-slate-400'
  }`}>
```

Add `isRiskLeg` to `RecentTradeLeg` in `volume-grid.types.ts`:

```ts
export interface RecentTradeLeg {
  tenorYears: number
  forwardStartYears: number
  notional: number
  risk: number
  inCell: boolean
  isRiskLeg?: boolean
}
```

- [ ] **Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts
git commit -m "feat(volume-grid): wire structure CellId through modal + risk leg highlight"
```

---

## Task 10: View Registration & Final Wiring

Register all new views, make activeView validation dynamic, and bump the localStorage defaults version.

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx:21,64`

- [ ] **Step 1: Register new views in volumeGridViews.ts**

Replace the entire file:

```ts
import type { VolumeGridViewDef } from '../../../types/volume-grid-views.types'
import { DefaultGridView } from './DefaultGridView'
import { FomcStripView } from './FomcStripView'
import { CurveStripView } from './CurveStripView'
import { FlyCurveView } from './FlyCurveView'
import { CustomGridView } from './CustomGridView'

export const VOLUME_GRID_VIEWS: ReadonlyArray<VolumeGridViewDef> = [
  {
    id: 'default',
    label: 'Grid',
    component: DefaultGridView,
    controls: () => null,
  },
  {
    id: 'fomc_strip',
    label: 'FOMC Strip',
    component: FomcStripView,
    controls: () => null,
  },
  {
    id: 'curve_strip',
    label: 'Curve Strip',
    component: CurveStripView,
    controls: () => null,
  },
  {
    id: 'fly_curve',
    label: 'Fly Curve',
    component: FlyCurveView,
    controls: () => null,
  },
  {
    id: 'custom',
    label: 'Custom',
    component: CustomGridView,
    controls: () => null,
  },
]
```

- [ ] **Step 2: Update VolumeGridCard view validation**

In `VolumeGridCard.tsx`, update the defaults version (line 21):

```ts
const DEFAULTS_VERSION = 'all-today-1m-v4'
```

Replace the hardcoded view validation (line 64):

```ts
      const storedView = window.localStorage.getItem(KEY_VIEW)
      const validViewIds = new Set(VOLUME_GRID_VIEWS.map((v) => v.id))
      if (storedView && validViewIds.has(storedView)) setActiveView(storedView)
```

Add import at the top:

```ts
import { VOLUME_GRID_VIEWS } from './views/volumeGridViews'
```

- [ ] **Step 3: Run full test suite**

Run: `cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid|volumeGridBuckets|structureDefs" --no-coverage`

Expected: All tests pass.

- [ ] **Step 4: Type check**

Run: `cd SDRUtils/dashboard && npx tsc --noEmit`

Expected: No type errors.

- [ ] **Step 5: Start dev server and verify in browser**

Run: `cd SDRUtils/dashboard && npm run dev`

Verify:
1. Default Grid view still works as before
2. FOMC Strip still works
3. Curve Strip tab appears — shows structure × forward grid (may show empty cells if no curve trades match)
4. Fly Curve tab appears — same
5. Custom tab shows "Configure" empty state, modal opens
6. Clicking a structure cell opens the modal with timeseries/trades

- [ ] **Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/views/volumeGridViews.ts \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx
git commit -m "feat(volume-grid): register Curve Strip, Fly Curve, Custom views + bump defaults"
```

---

## Summary

| Task | Description | New Files | Modified Files |
|------|-------------|-----------|----------------|
| 1 | Types & constants | 2 | 2 |
| 2 | Shared SQL library | 1 | 1 |
| 3 | Custom schema API | 0 | 4 |
| 4 | Structure endpoint | 2 | 0 |
| 5 | Structure cell endpoint | 0 | 2 |
| 6 | useStructureGrid hook | 1 | 0 |
| 7 | StructureGridView + views | 3 | 0 |
| 8 | Custom Schema Builder UI | 2 | 1 |
| 9 | Cell modal integration | 0 | 4 |
| 10 | View registration & wiring | 0 | 2 |
| **Total** | | **11 new** | **16 modified** |
