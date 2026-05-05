# USD Swaps Tape v2 — Volume Grid Heatmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a collapsible top-of-page volume heatmap to the USD swaps tape v2, with each forward × tenor cell coloured by percentile-vs-lookback and clickable into a modal showing the bucket's daily volume timeseries + recent trades.

**Architecture:** New backend routes `/volume-grid` (matrix) and `/volume-grid/cell` (drill-down) read from `arbs_usd_swap_tape_legs_v2` filtered on `contributes_to_flow=TRUE`. Bucket boundaries live in a shared `lib/usd-swaps-tape-v2/volumeGridBuckets.ts` helper. Front-end is a self-contained `<VolumeGridCard>` mounted in `UsdSwapsTradeTape.tsx` that owns its own SWR (with collapse-aware polling) and a PrimeReact `Dialog` modal. Click-through routes a `package_id` URL filter via the existing `useColumnFilters` plumbing.

**Tech Stack:** Next.js 15 App Router, TypeScript, Postgres via `@/lib/db`, SWR, Recharts, PrimeReact `Dialog`, Tailwind, Jest + `@testing-library/react`. E2E validation runs interactively via the Chrome MCP extension (no codified Puppeteer suite).

**Reference design:** [`docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-design.md`](./2026-05-05-usd-swaps-tape-v2-volume-grid-design.md). Read it before starting Task 1.

---

## Conventions

- All work happens in the existing worktree at `.claude/worktrees/vigilant-cohen-0e2e8c` on branch `claude/vigilant-cohen-0e2e8c`.
- All `npm` commands run from `SDRUtils/dashboard/`. Use `cd SDRUtils/dashboard && npm test ...` style or `npm --prefix SDRUtils/dashboard test ...`.
- Tests are Jest. Run a single suite via `npm test -- --testPathPatterns=<pattern>`.
- Lint with `npm run lint`. Type-check via `npx tsc --noEmit`.
- Commit between tasks using Conventional Commits (`feat:`, `test:`, `refactor:`).
- New files start with an `// ABOUTME:` line where reasonable (matches existing pattern in `FlowHistoryGrid.tsx`).
- After each task: run the test for that file, then `npm run lint` for the touched paths, then commit.

---

## Task 1: Bucket helper module + boundary tests

**Goal:** Single source of truth for forward + tenor bucket boundaries, SQL CASE expressions, and predicate builders.

**Files:**
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts`
- Create: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts`

**Step 1: Write the failing test for forward bucket classification.**

Create `volumeGridBuckets.test.ts`:

```ts
import { describe, expect, it } from '@jest/globals'
import {
  classifyForwardBucket,
  classifyTenorBucket,
  FORWARD_BUCKETS,
  TENOR_BUCKETS,
  buildBucketSqlCases,
  buildBucketPredicate,
} from '../volumeGridBuckets'

describe('classifyForwardBucket', () => {
  it.each([
    [null, 'spot'],
    [0, 'spot'],
    [0.05, 'spot'],
    [0.083, '6m_1y'],
    [0.5, '6m_1y'],
    [0.999, '6m_1y'],
    [1.0, '1y_2y'],
    [1.5, '1y_2y'],
    [1.999, '1y_2y'],
    [2.0, '2y_5y'],
    [4.999, '2y_5y'],
    [5.0, '5y_10y'],
    [9.999, '5y_10y'],
    [10.0, 'fwd_other'],
    [50, 'fwd_other'],
  ])('forward_start_years=%s -> %s', (years, bucket) => {
    expect(classifyForwardBucket(years)).toBe(bucket)
  })
})

describe('classifyTenorBucket', () => {
  it.each([
    [null, null],
    [0.5, '1y'],
    [1.0, '1y'],
    [1.4999, '1y'],
    [1.5, '2y'],
    [2.4999, '2y'],
    [2.5, '2_5y'],
    [4.4999, '2_5y'],
    [4.5, '5y'],
    [5.4999, '5y'],
    [5.5, '5_10y'],
    [9.4999, '5_10y'],
    [9.5, '10y'],
    [10.9999, '10y'],
    [11.0, '10_20y'],
    [19.4999, '10_20y'],
    [19.5, '20y'],
    [20.9999, '20y'],
    [21.0, '20_30y'],
    [29.4999, '20_30y'],
    [29.5, '30y'],
    [30.9999, '30y'],
    [31.0, '50y'],
    [60, '50y'],
  ])('tenor_years=%s -> %s', (years, bucket) => {
    expect(classifyTenorBucket(years)).toBe(bucket)
  })
})

describe('FORWARD_BUCKETS / TENOR_BUCKETS', () => {
  it('forward buckets are exactly the five rendered rows', () => {
    expect(FORWARD_BUCKETS.map((b) => b.id)).toEqual([
      'spot', '6m_1y', '1y_2y', '2y_5y', '5y_10y',
    ])
  })
  it('tenor buckets are exactly the eleven rendered cols', () => {
    expect(TENOR_BUCKETS.map((b) => b.id)).toEqual([
      '1y', '2y', '2_5y', '5y', '5_10y', '10y',
      '10_20y', '20y', '20_30y', '30y', '50y',
    ])
  })
})

describe('buildBucketSqlCases', () => {
  it('emits forward + tenor CASE expressions referencing the leg alias', () => {
    const { fwdCase, tenorCase } = buildBucketSqlCases('l')
    expect(fwdCase).toContain('l.forward_start_years')
    expect(fwdCase).toContain("'spot'")
    expect(fwdCase).toContain("'5y_10y'")
    expect(fwdCase).toContain("'fwd_other'")
    expect(tenorCase).toContain('l.tenor_years')
    expect(tenorCase).toContain("'1y'")
    expect(tenorCase).toContain("'50y'")
  })
})

describe('buildBucketPredicate', () => {
  it('returns a parameterised WHERE clause with bind values', () => {
    const out = buildBucketPredicate('l', 'spot', '5y', 1)
    expect(out.sql).toMatch(/l\.forward_start_years/)
    expect(out.sql).toMatch(/l\.tenor_years/)
    expect(out.params.length).toBeGreaterThan(0)
    // Params should be the numeric boundaries used in the WHERE.
    expect(out.params).toEqual(expect.arrayContaining([Number]))
  })
  it('rejects unknown bucket ids', () => {
    expect(() => buildBucketPredicate('l', 'bogus', '5y', 1)).toThrow(/forward/)
    expect(() => buildBucketPredicate('l', 'spot', 'bogus', 1)).toThrow(/tenor/)
  })
})
```

**Step 2: Run the test to verify it fails.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volumeGridBuckets
```

Expected: ALL tests fail with "Cannot find module" error.

**Step 3: Implement the module.**

Create `volumeGridBuckets.ts`:

```ts
// ABOUTME: Single source of truth for the volume-grid forward x tenor
// bucket boundaries, SQL CASE expressions, and parameterised WHERE-clause
// builders. Both /api/usd-swaps-tape-v2/volume-grid and
// /api/usd-swaps-tape-v2/volume-grid/cell import from here so boundaries
// can never drift between the matrix view and its drill-down.

export type ForwardBucketId =
  | 'spot' | '6m_1y' | '1y_2y' | '2y_5y' | '5y_10y' | 'fwd_other'

export type TenorBucketId =
  | '1y' | '2y' | '2_5y' | '5y' | '5_10y' | '10y'
  | '10_20y' | '20y' | '20_30y' | '30y' | '50y'

interface Bucket<Id extends string> {
  readonly id: Id
  /** Inclusive lower bound in years. `null` means -infinity. */
  readonly lo: number | null
  /** Exclusive upper bound in years. `null` means +infinity. */
  readonly hi: number | null
  /** Display label used in tooltips and modal titles. */
  readonly label: string
}

export const FORWARD_BUCKETS: ReadonlyArray<Bucket<Exclude<ForwardBucketId, 'fwd_other'>>> = [
  { id: 'spot',   lo: null,  hi: 0.083, label: 'spot' },
  { id: '6m_1y',  lo: 0.083, hi: 1.0,   label: '6m-1Y' },
  { id: '1y_2y',  lo: 1.0,   hi: 2.0,   label: '1Y-2Y' },
  { id: '2y_5y',  lo: 2.0,   hi: 5.0,   label: '2Y-5Y' },
  { id: '5y_10y', lo: 5.0,   hi: 10.0,  label: '5-10Y' },
] as const

export const TENOR_BUCKETS: ReadonlyArray<Bucket<TenorBucketId>> = [
  { id: '1y',     lo: null, hi: 1.5,  label: '1y' },
  { id: '2y',     lo: 1.5,  hi: 2.5,  label: '2y' },
  { id: '2_5y',   lo: 2.5,  hi: 4.5,  label: '2-5y' },
  { id: '5y',     lo: 4.5,  hi: 5.5,  label: '5y' },
  { id: '5_10y',  lo: 5.5,  hi: 9.5,  label: '5-10y' },
  { id: '10y',    lo: 9.5,  hi: 11.0, label: '10y' },
  { id: '10_20y', lo: 11.0, hi: 19.5, label: '10-20y' },
  { id: '20y',    lo: 19.5, hi: 21.0, label: '20y' },
  { id: '20_30y', lo: 21.0, hi: 29.5, label: '20-30y' },
  { id: '30y',    lo: 29.5, hi: 31.0, label: '30y' },
  { id: '50y',    lo: 31.0, hi: null, label: '50y' },
] as const

export function classifyForwardBucket(years: number | null | undefined): ForwardBucketId {
  if (years == null || years < 0.083) return 'spot'
  if (years < 1.0)  return '6m_1y'
  if (years < 2.0)  return '1y_2y'
  if (years < 5.0)  return '2y_5y'
  if (years < 10.0) return '5y_10y'
  return 'fwd_other'
}

export function classifyTenorBucket(
  years: number | null | undefined,
): TenorBucketId | null {
  if (years == null) return null
  if (years < 1.5)  return '1y'
  if (years < 2.5)  return '2y'
  if (years < 4.5)  return '2_5y'
  if (years < 5.5)  return '5y'
  if (years < 9.5)  return '5_10y'
  if (years < 11.0) return '10y'
  if (years < 19.5) return '10_20y'
  if (years < 21.0) return '20y'
  if (years < 29.5) return '20_30y'
  if (years < 31.0) return '30y'
  return '50y'
}

export function buildBucketSqlCases(legAlias: string): {
  fwdCase: string
  tenorCase: string
} {
  const a = legAlias
  const fwdCase = `
    CASE
      WHEN ${a}.forward_start_years IS NULL OR ${a}.forward_start_years < 0.083 THEN 'spot'
      WHEN ${a}.forward_start_years <  1.0  THEN '6m_1y'
      WHEN ${a}.forward_start_years <  2.0  THEN '1y_2y'
      WHEN ${a}.forward_start_years <  5.0  THEN '2y_5y'
      WHEN ${a}.forward_start_years < 10.0  THEN '5y_10y'
      ELSE 'fwd_other'
    END`
  const tenorCase = `
    CASE
      WHEN ${a}.tenor_years IS NULL THEN NULL
      WHEN ${a}.tenor_years <  1.5  THEN '1y'
      WHEN ${a}.tenor_years <  2.5  THEN '2y'
      WHEN ${a}.tenor_years <  4.5  THEN '2_5y'
      WHEN ${a}.tenor_years <  5.5  THEN '5y'
      WHEN ${a}.tenor_years <  9.5  THEN '5_10y'
      WHEN ${a}.tenor_years < 11.0  THEN '10y'
      WHEN ${a}.tenor_years < 19.5  THEN '10_20y'
      WHEN ${a}.tenor_years < 21.0  THEN '20y'
      WHEN ${a}.tenor_years < 29.5  THEN '20_30y'
      WHEN ${a}.tenor_years < 31.0  THEN '30y'
      ELSE '50y'
    END`
  return { fwdCase, tenorCase }
}

export function buildBucketPredicate(
  legAlias: string,
  fwdId: string,
  tenorId: string,
  startParamIndex: number,
): { sql: string; params: number[] } {
  const fwd = FORWARD_BUCKETS.find((b) => b.id === fwdId)
  if (!fwd) throw new Error(`unknown forward bucket id: ${fwdId}`)
  const tenor = TENOR_BUCKETS.find((b) => b.id === tenorId)
  if (!tenor) throw new Error(`unknown tenor bucket id: ${tenorId}`)
  const params: number[] = []
  const a = legAlias
  const parts: string[] = []
  let pi = startParamIndex
  // Forward: NULL or below 0.083 means 'spot'. Other forward buckets have
  // explicit lo/hi.
  if (fwd.id === 'spot') {
    parts.push(`(${a}.forward_start_years IS NULL OR ${a}.forward_start_years < $${pi})`)
    params.push(fwd.hi as number)
    pi += 1
  } else {
    parts.push(`${a}.forward_start_years >= $${pi}`)
    params.push(fwd.lo as number)
    pi += 1
    if (fwd.hi != null) {
      parts.push(`${a}.forward_start_years < $${pi}`)
      params.push(fwd.hi)
      pi += 1
    }
  }
  // Tenor: '1y' uses NULL-safe lower side; '50y' has no upper.
  if (tenor.lo != null) {
    parts.push(`${a}.tenor_years >= $${pi}`)
    params.push(tenor.lo)
    pi += 1
  } else {
    parts.push(`${a}.tenor_years IS NOT NULL`)
  }
  if (tenor.hi != null) {
    parts.push(`${a}.tenor_years < $${pi}`)
    params.push(tenor.hi)
    pi += 1
  }
  return { sql: parts.join(' AND '), params }
}
```

The `expect.arrayContaining([Number])` in the predicate test was a placeholder — fix the test to assert on a real shape:

```ts
// In the test file, replace the placeholder block:
it('returns a parameterised WHERE clause with bind values', () => {
  const out = buildBucketPredicate('l', 'spot', '5y', 1)
  expect(out.sql).toMatch(/l\.forward_start_years IS NULL OR l\.forward_start_years < \$1/)
  expect(out.sql).toMatch(/l\.tenor_years >= \$2/)
  expect(out.sql).toMatch(/l\.tenor_years < \$3/)
  expect(out.params).toEqual([0.083, 4.5, 5.5])
})
it('handles 50y (no upper bound)', () => {
  const out = buildBucketPredicate('l', '5y_10y', '50y', 1)
  expect(out.sql).not.toMatch(/tenor_years <\s+\$/)
  expect(out.params).toEqual([5.0, 10.0, 31.0])
})
```

**Step 4: Run the test to verify it passes.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volumeGridBuckets
```

Expected: all tests PASS.

**Step 5: Lint + commit.**

```bash
cd SDRUtils/dashboard && npm run lint -- src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts
git commit -m "feat(usd-swaps-tape-v2): volumeGridBuckets helper for forward x tenor SQL

Single source of truth for matrix + drill-down bucket boundaries."
```

---

## Task 2: Volume-grid response types

**Goal:** Shared TS types for the matrix and cell endpoints, used by both routes and front-end hooks.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/index.ts`

**Step 1: Write the type module.**

```ts
// ABOUTME: Response shapes for /volume-grid and /volume-grid/cell.
// Imported by the route handlers and the SWR hooks.

import type { ForwardBucketId, TenorBucketId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export type VolumeMetric = 'notional' | 'dv01'
export type VolumePeriod = 'today' | '1h' | '24h' | '1w'
export type VolumeCellRange = '1M' | '3M' | '6M' | '1Y'

export interface VolumeGridBaseline {
  p25: number
  p50: number
  p75: number
  min: number
  max: number
  n: number
}

export interface VolumeGridCell {
  fwd: Exclude<ForwardBucketId, 'fwd_other'>
  tenor: TenorBucketId
  current: number
  tradeCount: number
  baseline: VolumeGridBaseline
  /** 0..100 rank of `current` within the prior-window distribution; null when `n=0`. */
  percentile: number | null
}

export interface VolumeGridTotalEntry {
  current: number
  percentile: number | null
}

export interface VolumeGridResponse {
  asOf: string
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
  cells: VolumeGridCell[]
  totals: {
    rowTotals: Record<string, VolumeGridTotalEntry>
    colTotals: Record<string, VolumeGridTotalEntry>
    grand: VolumeGridTotalEntry
  }
}

export interface VolumeGridCellTimeseriesPoint {
  day: string
  notional: number
  dv01: number
  tradeCount: number
  idbCount: number
  custyCount: number
}

export interface VolumeGridCellRecentTrade {
  package_id: string
  execution_start: string
  tape_label: string | null
  package_type: string | null
  weighted_fixed_rate: number | null
  total_risk: number | null
  total_notional: number | null
  venue: string | null
  is_block_any: boolean | null
}

export interface VolumeGridCellResponse {
  fwd: Exclude<ForwardBucketId, 'fwd_other'>
  tenor: TenorBucketId
  metric: VolumeMetric
  range: VolumeCellRange
  timeseries: VolumeGridCellTimeseriesPoint[]
  recentTrades: VolumeGridCellRecentTrade[]
}
```

**Step 2: Re-export from `types/index.ts`.**

Open `types/index.ts` and append:

```ts
export type {
  VolumeMetric,
  VolumePeriod,
  VolumeCellRange,
  VolumeGridBaseline,
  VolumeGridCell,
  VolumeGridTotalEntry,
  VolumeGridResponse,
  VolumeGridCellTimeseriesPoint,
  VolumeGridCellRecentTrade,
  VolumeGridCellResponse,
} from './volume-grid.types'
```

**Step 3: Type-check.**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit
```

Expected: no new errors.

**Step 4: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/index.ts
git commit -m "feat(usd-swaps-tape-v2): volume-grid response types"
```

---

## Task 3: Volume-grid route — pure SQL builder + percentile helper

**Goal:** Extract the SQL construction and post-processing into pure functions that can be unit-tested without a DB.

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts`

**Step 1: Write the failing tests.**

```ts
import { describe, expect, it } from '@jest/globals'
import {
  buildVolumeGridSql,
  computeWindowBounds,
  computePercentile,
  summariseCells,
  parseVolumeGridParams,
} from '../route.logic'

describe('parseVolumeGridParams', () => {
  it('applies defaults for missing params', () => {
    const out = parseVolumeGridParams(new URLSearchParams())
    expect(out).toEqual({
      ok: true,
      value: { metric: 'notional', period: 'today', lookbackDays: 90 },
    })
  })
  it('rejects invalid metric', () => {
    const out = parseVolumeGridParams(new URLSearchParams('metric=foo'))
    expect(out.ok).toBe(false)
  })
  it('rejects invalid period', () => {
    const out = parseVolumeGridParams(new URLSearchParams('period=foo'))
    expect(out.ok).toBe(false)
  })
  it('rejects out-of-range lookbackDays', () => {
    expect(parseVolumeGridParams(new URLSearchParams('lookbackDays=0')).ok).toBe(false)
    expect(parseVolumeGridParams(new URLSearchParams('lookbackDays=999')).ok).toBe(false)
  })
})

describe('computeWindowBounds', () => {
  const now = new Date('2026-05-05T14:32:00Z')
  it('today: current=since 00:00 ET, baseline=last 90 trading days', () => {
    const out = computeWindowBounds('today', 90, now)
    expect(out.currentStart.getTime()).toBeLessThan(now.getTime())
    expect(out.baselineStart.getTime()).toBeLessThan(out.currentStart.getTime())
    expect(out.windowIdSql).toContain('date_trunc')
  })
  it('1h: current is now-1h..now', () => {
    const out = computeWindowBounds('1h', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(60 * 60 * 1000)
  })
  it('24h: current is now-24h..now', () => {
    const out = computeWindowBounds('24h', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(24 * 60 * 60 * 1000)
  })
  it('1w: current is now-7d..now, baseline is 52 weeks', () => {
    const out = computeWindowBounds('1w', 90, now)
    expect(now.getTime() - out.currentStart.getTime()).toBe(7 * 24 * 60 * 60 * 1000)
    // 52 weeks regardless of lookbackDays input.
    expect(now.getTime() - out.baselineStart.getTime()).toBeGreaterThanOrEqual(
      52 * 7 * 24 * 60 * 60 * 1000,
    )
  })
})

describe('buildVolumeGridSql', () => {
  it('uses gross_notional for metric=notional', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain('gross_notional')
    expect(sql).not.toContain('SUM(gross_dv01)')
  })
  it('uses gross_dv01 for metric=dv01', () => {
    const sql = buildVolumeGridSql('dv01', 'today')
    expect(sql).toContain('gross_dv01')
  })
  it('filters on contributes_to_flow=TRUE', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain('contributes_to_flow')
    expect(sql).toContain('TRUE')
  })
  it('excludes fwd_other rows', () => {
    const sql = buildVolumeGridSql('notional', 'today')
    expect(sql).toContain("<> 'fwd_other'")
  })
})

describe('computePercentile', () => {
  it('returns 0 when current is below all prior values', () => {
    expect(computePercentile(0, [10, 20, 30])).toBe(0)
  })
  it('returns 100 when current exceeds all prior values', () => {
    expect(computePercentile(100, [10, 20, 30])).toBe(100)
  })
  it('returns ~50 when current is at the median', () => {
    expect(computePercentile(20, [10, 20, 30])).toBeCloseTo(66.67, 1)
  })
  it('returns null when prior is empty', () => {
    expect(computePercentile(5, [])).toBeNull()
  })
})

describe('summariseCells', () => {
  it('aggregates row + col + grand totals', () => {
    const cells = [
      { fwd: 'spot', tenor: '5y', current: 10, tradeCount: 3, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
      { fwd: 'spot', tenor: '10y', current: 20, tradeCount: 5, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
      { fwd: '6m_1y', tenor: '5y', current: 5, tradeCount: 1, baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 }, percentile: null },
    ] as never
    const totals = summariseCells(cells)
    expect(totals.rowTotals.spot.current).toBe(30)
    expect(totals.rowTotals['6m_1y'].current).toBe(5)
    expect(totals.colTotals['5y'].current).toBe(15)
    expect(totals.colTotals['10y'].current).toBe(20)
    expect(totals.grand.current).toBe(35)
  })
})
```

**Step 2: Run test, verify failure.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volume-grid/__tests__/route.logic
```

Expected: every test fails with "Cannot find module".

**Step 3: Implement `route.logic.ts`.**

```ts
// ABOUTME: Pure helpers for /api/usd-swaps-tape-v2/volume-grid. Split out
// from route.ts so SQL construction, parameter parsing, percentile math,
// and totals aggregation can be unit-tested without spinning up a DB.

import { buildBucketSqlCases } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeGridCell,
  VolumeMetric,
  VolumePeriod,
  VolumeGridResponse,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface VolumeGridParams {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays: number
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_PERIODS: ReadonlySet<VolumePeriod> = new Set(['today', '1h', '24h', '1w'])

export function parseVolumeGridParams(search: URLSearchParams): ParseResult<VolumeGridParams> {
  const metricRaw = (search.get('metric') ?? 'notional').toLowerCase()
  const periodRaw = (search.get('period') ?? 'today').toLowerCase()
  const lookbackRaw = search.get('lookbackDays')
  if (!VALID_METRICS.has(metricRaw as VolumeMetric)) {
    return { ok: false, error: `metric must be one of ${[...VALID_METRICS].join(', ')}` }
  }
  if (!VALID_PERIODS.has(periodRaw as VolumePeriod)) {
    return { ok: false, error: `period must be one of ${[...VALID_PERIODS].join(', ')}` }
  }
  let lookbackDays = 90
  if (lookbackRaw != null) {
    const n = Number(lookbackRaw)
    if (!Number.isFinite(n) || n < 1 || n > 365) {
      return { ok: false, error: 'lookbackDays must be 1..365' }
    }
    lookbackDays = Math.floor(n)
  }
  return {
    ok: true,
    value: {
      metric: metricRaw as VolumeMetric,
      period: periodRaw as VolumePeriod,
      lookbackDays,
    },
  }
}

export interface WindowBounds {
  currentStart: Date
  currentEnd: Date
  baselineStart: Date
  /**
   * SQL fragment that maps a leg's `ts` to a baseline window id (one
   * row in `prior` per (bucket, window_id)). E.g. for `today` the
   * window id is the date in ET; for `1h` the (date, hour); for `1w`
   * the ISO week.
   */
  windowIdSql: string
}

const ONE_HOUR_MS = 60 * 60 * 1000
const ONE_DAY_MS = 24 * ONE_HOUR_MS

export function computeWindowBounds(
  period: VolumePeriod,
  lookbackDays: number,
  now: Date = new Date(),
): WindowBounds {
  const currentEnd = now
  switch (period) {
    case 'today': {
      const startOfDay = new Date(now)
      startOfDay.setUTCHours(4, 0, 0, 0) // 00:00 ET ~= 04:00 UTC (DST-naive)
      if (startOfDay.getTime() > now.getTime()) {
        startOfDay.setUTCDate(startOfDay.getUTCDate() - 1)
      }
      const baselineStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        currentStart: startOfDay,
        currentEnd,
        baselineStart,
        windowIdSql: `date_trunc('day', ts AT TIME ZONE 'America/New_York')`,
      }
    }
    case '1h': {
      const baselineStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        currentStart: new Date(now.getTime() - ONE_HOUR_MS),
        currentEnd,
        baselineStart,
        windowIdSql: `date_trunc('hour', ts AT TIME ZONE 'America/New_York')`,
      }
    }
    case '24h': {
      const baselineStart = new Date(now.getTime() - lookbackDays * ONE_DAY_MS)
      return {
        currentStart: new Date(now.getTime() - 24 * ONE_HOUR_MS),
        currentEnd,
        baselineStart,
        windowIdSql: `date_trunc('day', ts AT TIME ZONE 'America/New_York')`,
      }
    }
    case '1w': {
      // 1w fixes baseline to 52 weeks regardless of lookbackDays input;
      // 90 days produces too few weekly samples for percentile stability.
      const baselineStart = new Date(now.getTime() - 52 * 7 * ONE_DAY_MS)
      return {
        currentStart: new Date(now.getTime() - 7 * ONE_DAY_MS),
        currentEnd,
        baselineStart,
        windowIdSql: `date_trunc('week', ts AT TIME ZONE 'America/New_York')`,
      }
    }
  }
}

export function buildVolumeGridSql(metric: VolumeMetric, _period: VolumePeriod): string {
  const { fwdCase, tenorCase } = buildBucketSqlCases('l')
  const metricCol = metric === 'notional' ? 'gross_notional' : 'gross_dv01'
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS gross_notional,
        ABS(COALESCE(l.risk, 0))     AS gross_dv01,
        ${fwdCase} AS fwd_bucket,
        ${tenorCase} AS tenor_bucket
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) <  $2::timestamptz
    ),
    bucketed AS (
      SELECT * FROM legs
      WHERE fwd_bucket <> 'fwd_other'
        AND tenor_bucket IS NOT NULL
    ),
    windowed AS (
      SELECT *,
        CASE
          WHEN ts >= $3::timestamptz THEN 'current'
          ELSE 'baseline'
        END AS window_kind,
        $WINDOW_ID_SQL AS baseline_window_id
      FROM bucketed
    ),
    prior_per_window AS (
      SELECT fwd_bucket, tenor_bucket, baseline_window_id,
        SUM(${metricCol}) AS window_value
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
        COUNT(*)::int AS n
      FROM prior_per_window
      GROUP BY fwd_bucket, tenor_bucket
    ),
    current_agg AS (
      SELECT fwd_bucket, tenor_bucket,
        SUM(${metricCol}) AS current_value,
        COUNT(*)::int AS trade_count,
        MAX(ts) AS last_ts
      FROM windowed
      WHERE window_kind = 'current'
      GROUP BY fwd_bucket, tenor_bucket
    )
    SELECT
      COALESCE(c.fwd_bucket, p.fwd_bucket)     AS fwd,
      COALESCE(c.tenor_bucket, p.tenor_bucket) AS tenor,
      COALESCE(c.current_value, 0)             AS current_value,
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
    FULL OUTER JOIN prior_summary p USING (fwd_bucket, tenor_bucket)
  `
}

export function computePercentile(current: number, prior: ReadonlyArray<number>): number | null {
  if (prior.length === 0) return null
  let lessOrEqual = 0
  for (const v of prior) if (v <= current) lessOrEqual += 1
  return (lessOrEqual / prior.length) * 100
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
  // Percentiles for totals are not computed in this helper — the route
  // computes them from the SQL prior_array union per axis.
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
```

**Step 4: Run tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volume-grid/__tests__/route.logic
```

Expected: PASS for all helpers.

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts
git commit -m "feat(usd-swaps-tape-v2): pure SQL/percentile helpers for volume-grid"
```

---

## Task 4: Volume-grid route handler

**Goal:** Wire the handler that calls the helpers, runs the SQL, and emits the LRU/ETag response.

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.ts`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts` (add the row→cell shaping helper if not yet present)

**Step 1: Write a route smoke test that fakes `query`.**

Create `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.test.ts`:

```ts
import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

beforeEach(() => {
  queryMock.mockReset()
})

describe('GET /api/usd-swaps-tape-v2/volume-grid', () => {
  it('400 on invalid metric', async () => {
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api?metric=foo'))
    expect(res.status).toBe(400)
  })
  it('200 with matrix shape on happy path', async () => {
    queryMock.mockResolvedValueOnce({
      rows: [
        {
          fwd: 'spot', tenor: '5y',
          current_value: 100, trade_count: 5,
          prior_array: [10, 20, 30],
          p25: 15, p50: 20, p75: 25, pmin: 10, pmax: 30, n: 3,
          as_of_ts: '2026-05-05T14:32:00Z',
        },
      ],
    })
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.metric).toBe('notional')
    expect(body.period).toBe('today')
    expect(body.cells.length).toBe(1)
    expect(body.cells[0]).toMatchObject({
      fwd: 'spot', tenor: '5y',
      current: 100, tradeCount: 5,
      baseline: { p25: 15, p50: 20, p75: 25, min: 10, max: 30, n: 3 },
      percentile: 100,
    })
    expect(body.totals.grand.current).toBe(100)
  })
})
```

**Step 2: Run test, expect failures (route does not exist).**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volume-grid/__tests__/route.test
```

Expected: failures.

**Step 3: Add the row→cell shaping helper to `route.logic.ts`.**

Append to `route.logic.ts`:

```ts
import type { VolumeGridResponse } from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface RawVolumeGridRow {
  fwd: string
  tenor: string
  current_value: number | string
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

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export function shapeVolumeGridResponse(
  rows: ReadonlyArray<RawVolumeGridRow>,
  params: VolumeGridParams,
): VolumeGridResponse {
  const cells = rows
    // Drop rows that fell outside the rendered axes (defensive).
    .filter((r) => r.fwd !== 'fwd_other' && r.tenor !== null && r.tenor !== '')
    .map((r) => {
      const prior = r.prior_array.map(num)
      const current = num(r.current_value)
      const cell = {
        fwd: r.fwd as VolumeGridCell['fwd'],
        tenor: r.tenor as VolumeGridCell['tenor'],
        current,
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
      return cell
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
    cells,
    totals,
  }
}
```

Add a unit test for this shaping helper to `route.logic.test.ts`:

```ts
import { shapeVolumeGridResponse } from '../route.logic'

describe('shapeVolumeGridResponse', () => {
  it('drops fwd_other and null tenor cells', () => {
    const out = shapeVolumeGridResponse(
      [
        { fwd: 'fwd_other', tenor: '5y', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: '', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
        { fwd: 'spot', tenor: '5y', current_value: 1, trade_count: 1, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0, as_of_ts: null },
      ],
      { metric: 'notional', period: 'today', lookbackDays: 90 },
    )
    expect(out.cells.length).toBe(1)
    expect(out.cells[0].fwd).toBe('spot')
  })
})
```

**Step 4: Implement `route.ts`.**

```ts
// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid
// Returns the forward x tenor matrix of {current, baseline, percentile}
// per (metric, period). Server LRU + ETag matches analytics-timeseries
// caching so SWR hits stay cheap.

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'
import {
  buildVolumeGridSql,
  computeWindowBounds,
  parseVolumeGridParams,
  shapeVolumeGridResponse,
  type RawVolumeGridRow,
} from './route.logic'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 512)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: 60_000,
})

const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=60, must-revalidate',
} as const

function cacheKey(url: URL): string {
  const params = new URLSearchParams(url.search)
  const sorted = [...params.entries()].sort()
  return JSON.stringify(sorted)
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const ifNoneMatch = request.headers.get('If-None-Match')
  const key = cacheKey(url)
  const hit = lru.get(key)
  if (hit) {
    if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: hit.etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(hit.payload, { headers: { ETag: hit.etag, ...CACHE_HEADERS } })
  }

  const parsed = parseVolumeGridParams(url.searchParams)
  if (!parsed.ok) return NextResponse.json({ error: parsed.error }, { status: 400 })

  const bounds = computeWindowBounds(parsed.value.period, parsed.value.lookbackDays)
  const sqlTemplate = buildVolumeGridSql(parsed.value.metric, parsed.value.period)
  const sql = sqlTemplate.replace('$WINDOW_ID_SQL', bounds.windowIdSql)

  try {
    const { rows } = await query<RawVolumeGridRow>(sql, [
      bounds.baselineStart.toISOString(),
      bounds.currentEnd.toISOString(),
      bounds.currentStart.toISOString(),
    ])
    const payload = shapeVolumeGridResponse(rows, parsed.value)
    const etag = computeEtag(payload)
    lru.set(key, { payload, etag })
    if (matchesIfNoneMatch(etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(payload, { headers: { ETag: etag, ...CACHE_HEADERS } })
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch volume grid'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
```

**Step 5: Re-run all volume-grid tests.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=volume-grid
```

Expected: all PASS.

**Step 6: Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.test.ts
git commit -m "feat(usd-swaps-tape-v2): /volume-grid route + LRU/ETag caching"
```

---

## Task 5: Color ramp + client buckets module

**Goal:** Pure UI helpers for colour mapping and human-readable bucket labels.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/colorRamp.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/buckets.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/colorRamp.test.ts`

**Step 1: Write tests for `colorRamp.ts`.**

```ts
import { describe, expect, it } from '@jest/globals'
import { colorForPercentile, foregroundForPercentile } from '../colorRamp'

describe('colorForPercentile', () => {
  it('returns the slate fallback for null', () => {
    const out = colorForPercentile(null)
    expect(out).toMatch(/slate|hsl/)
  })
  it('returns a slate hue at low percentiles', () => {
    expect(colorForPercentile(10)).toMatch(/^hsl\(210/)
  })
  it('returns an indigo hue at percentile 70', () => {
    expect(colorForPercentile(70)).toMatch(/^hsl\(2[0-9]{2}/)
  })
  it('returns a fuchsia hue at percentile 90', () => {
    expect(colorForPercentile(90)).toMatch(/^hsl\(31/)
  })
  it('returns a rose hue at percentile 99', () => {
    expect(colorForPercentile(99)).toMatch(/^hsl\(34[0-9]/)
  })
})

describe('foregroundForPercentile', () => {
  it('uses slate-300 at low percentile', () => {
    expect(foregroundForPercentile(10)).toMatch(/slate-300/)
  })
  it('uses slate-100 at high percentile', () => {
    expect(foregroundForPercentile(95)).toMatch(/slate-100/)
  })
  it('uses slate-500 when null', () => {
    expect(foregroundForPercentile(null)).toMatch(/slate-500/)
  })
})
```

**Step 2: Run, expect failure.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid/__tests__/colorRamp
```

**Step 3: Implement `colorRamp.ts`.**

```ts
// ABOUTME: Maps a 0..100 percentile to an hsl() background colour and a
// foreground tailwind class. Single hue ramp from slate -> indigo ->
// fuchsia -> rose so high-percentile cells visually dominate.

const STOPS: Array<{ at: number; hue: number; sat: number; light: number }> = [
  { at: 0,   hue: 210, sat: 25, light: 14 }, // slate-900
  { at: 30,  hue: 210, sat: 18, light: 22 },
  { at: 60,  hue: 222, sat: 30, light: 32 }, // slate-700-ish
  { at: 70,  hue: 240, sat: 65, light: 50 }, // indigo-500
  { at: 85,  hue: 290, sat: 75, light: 52 }, // ~fuchsia
  { at: 95,  hue: 320, sat: 80, light: 58 },
  { at: 100, hue: 350, sat: 82, light: 60 }, // rose-500
]

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function colorForPercentile(p: number | null): string {
  if (p == null) return 'hsl(220, 14%, 18%)' // slate-900/30 fallback
  const clamped = Math.max(0, Math.min(100, p))
  for (let i = 1; i < STOPS.length; i += 1) {
    const lo = STOPS[i - 1]
    const hi = STOPS[i]
    if (clamped <= hi.at) {
      const t = (clamped - lo.at) / (hi.at - lo.at)
      return `hsl(${lerp(lo.hue, hi.hue, t).toFixed(0)}, ${lerp(lo.sat, hi.sat, t).toFixed(0)}%, ${lerp(lo.light, hi.light, t).toFixed(0)}%)`
    }
  }
  return `hsl(${STOPS[STOPS.length - 1].hue}, ${STOPS[STOPS.length - 1].sat}%, ${STOPS[STOPS.length - 1].light}%)`
}

export function foregroundForPercentile(p: number | null): string {
  if (p == null) return 'text-slate-500'
  return p >= 70 ? 'text-slate-100' : 'text-slate-300'
}
```

**Step 4: Implement `buckets.ts` (client labels).**

```ts
// ABOUTME: Human-readable labels and ordering for the volume-grid axes.
// Server-side authority is volumeGridBuckets.ts in src/lib; this module
// is the UI copy of the labels + bucket id ordering.

import { FORWARD_BUCKETS, TENOR_BUCKETS } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export const FORWARD_AXIS = FORWARD_BUCKETS
export const TENOR_AXIS = TENOR_BUCKETS

export function fwdLabel(id: string): string {
  return FORWARD_BUCKETS.find((b) => b.id === id)?.label ?? id
}
export function tenorLabel(id: string): string {
  return TENOR_BUCKETS.find((b) => b.id === id)?.label ?? id
}
```

**Step 5: Run colorRamp tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid/__tests__/colorRamp
```

**Step 6: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/colorRamp.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/buckets.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/colorRamp.test.ts
git commit -m "feat(usd-swaps-tape-v2): VolumeGrid colorRamp + buckets UI helpers"
```

---

## Task 6: `useVolumeGrid` hook

**Goal:** SWR fetch hook for the matrix endpoint, with collapse-aware polling.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useVolumeGrid.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/index.ts`

**Step 1: Write the failing hook test.**

```ts
import { describe, expect, it, jest } from '@jest/globals'
import { renderHook, waitFor } from '@testing-library/react'
import { useVolumeGrid } from '../useVolumeGrid'

const fetchMock = jest.fn()
beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch
})
beforeEach(() => fetchMock.mockReset())

describe('useVolumeGrid', () => {
  it('returns data after fetch', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        asOf: '2026-05-05T14:32:00Z', metric: 'notional', period: 'today',
        lookbackDays: 90, cells: [], totals: { rowTotals: {}, colTotals: {}, grand: { current: 0, percentile: null } },
      }),
    })
    const { result } = renderHook(() =>
      useVolumeGrid({ metric: 'notional', period: 'today', collapsed: false }),
    )
    await waitFor(() => {
      expect(result.current.data).toBeDefined()
    })
    expect(result.current.data?.cells).toEqual([])
  })
  it('skips fetch when collapsed', () => {
    renderHook(() =>
      useVolumeGrid({ metric: 'notional', period: 'today', collapsed: true }),
    )
    expect(fetchMock).not.toHaveBeenCalled()
  })
  it('builds the URL with correct params', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({}) })
    renderHook(() =>
      useVolumeGrid({ metric: 'dv01', period: '1w', collapsed: false }),
    )
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('metric=dv01')
    expect(url).toContain('period=1w')
  })
})
```

**Step 2: Run, expect failures.**

**Step 3: Implement `useVolumeGrid.ts`.**

```ts
// ABOUTME: SWR hook for /api/usd-swaps-tape-v2/volume-grid. Polls every
// 30s when expanded; pauses when collapsed.
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  VolumeGridResponse, VolumeMetric, VolumePeriod,
} from '../types/volume-grid.types'

export interface UseVolumeGridArgs {
  metric: VolumeMetric
  period: VolumePeriod
  lookbackDays?: number
  collapsed: boolean
  /** Test seam — defaults to the package-wide `fetch`. */
  fetcher?: typeof fetch
}

export interface UseVolumeGridReturn {
  data: VolumeGridResponse | undefined
  error: Error | null
  isLoading: boolean
  refresh: () => Promise<VolumeGridResponse | undefined>
}

const DEFAULT_REFRESH_INTERVAL_MS = 30_000

function buildUrl(args: UseVolumeGridArgs): string {
  const q = new URLSearchParams({ metric: args.metric, period: args.period })
  if (args.lookbackDays != null) q.set('lookbackDays', String(args.lookbackDays))
  return `${TAPE_V2_API_BASE}/volume-grid?${q}`
}

export function useVolumeGrid(args: UseVolumeGridArgs): UseVolumeGridReturn {
  const fetcher = args.fetcher ?? fetch
  const url = args.collapsed ? null : buildUrl(args)
  const swr = useSWR<VolumeGridResponse, Error>(
    url,
    async (u: string) => {
      const res = await fetcher(u)
      if (!res.ok) throw new Error(`volume-grid fetch failed: ${res.status} ${res.statusText}`)
      return res.json() as Promise<VolumeGridResponse>
    },
    {
      refreshInterval: args.collapsed ? 0 : DEFAULT_REFRESH_INTERVAL_MS,
      revalidateOnFocus: true,
      dedupingInterval: 5_000,
    },
  )
  return {
    data: swr.data,
    error: swr.error ?? null,
    isLoading: swr.isLoading,
    refresh: () => swr.mutate(),
  }
}
```

**Step 4: Re-export from `hooks/index.ts`.**

Append `export { useVolumeGrid } from './useVolumeGrid'`.

**Step 5: Run hook tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=hooks/__tests__/useVolumeGrid
```

**Step 6: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGrid.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useVolumeGrid.test.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/index.ts
git commit -m "feat(usd-swaps-tape-v2): useVolumeGrid SWR hook with collapse-aware polling"
```

---

## Task 7: `<VolumeGridCell>` pure component + tests

**Goal:** Single cell with colour, value, percentile badge, tooltip, click handler. Pure render — no fetch.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCell.test.tsx`

**Step 1: Write the failing test.**

```tsx
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import { VolumeGridCell } from '../VolumeGridCell'

const baseCell = {
  fwd: 'spot' as const,
  tenor: '5y' as const,
  current: 1_200_000_000,
  tradeCount: 12,
  baseline: { p25: 0, p50: 5e8, p75: 1e9, min: 0, max: 2e9, n: 90 },
  percentile: 88,
}

describe('<VolumeGridCell>', () => {
  it('renders the formatted current value and percentile badge', () => {
    render(
      <VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={() => {}} />,
    )
    expect(screen.getByText(/1\.2B/)).toBeTruthy()
    expect(screen.getByText(/P88/)).toBeTruthy()
  })
  it('disables itself when tradeCount is zero', () => {
    render(
      <VolumeGridCell
        cell={{ ...baseCell, tradeCount: 0, percentile: null, current: 0 }}
        metric="notional" period="today" onClick={() => {}}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn).toHaveProperty('disabled', true)
  })
  it('calls onClick when clicked', () => {
    const onClick = jest.fn()
    render(<VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={onClick} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledWith({ fwd: 'spot', tenor: '5y' })
  })
  it('exposes a descriptive aria-label', () => {
    render(
      <VolumeGridCell cell={baseCell} metric="notional" period="today" onClick={() => {}} />,
    )
    expect(screen.getByRole('button').getAttribute('aria-label')).toMatch(
      /spot.*5y.*88th percentile/i,
    )
  })
})
```

**Step 2: Run, expect failure.**

**Step 3: Implement `VolumeGridCell.tsx`.**

```tsx
'use client'
// ABOUTME: One cell of the volume-grid heatmap. Pure render.

import type { JSX } from 'react'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import { fwdLabel, tenorLabel } from './buckets'
import type {
  VolumeGridCell as Cell, VolumeMetric, VolumePeriod,
} from '../../types/volume-grid.types'

const fmtCompact = (n: number, metric: VolumeMetric): string => {
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}k`
  return `${sign}${abs.toFixed(metric === 'dv01' ? 0 : 0)}`
}

export interface VolumeGridCellProps {
  cell: Cell
  metric: VolumeMetric
  period: VolumePeriod
  onClick: (id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => void
}

export function VolumeGridCell({ cell, metric, period, onClick }: VolumeGridCellProps): JSX.Element {
  const isEmpty = cell.tradeCount === 0 || cell.percentile == null
  const bg = isEmpty ? 'transparent' : colorForPercentile(cell.percentile)
  const fg = foregroundForPercentile(cell.percentile)
  const label = `${fwdLabel(cell.fwd)} x ${tenorLabel(cell.tenor)} — ${fmtCompact(cell.current, metric)} ${metric}, ${cell.percentile == null ? 'no history' : `${Math.round(cell.percentile)}th percentile vs lookback`}`
  const tooltip = isEmpty
    ? 'No trades in this bucket for the current window'
    : `${fmtCompact(cell.current, metric)} ${metric} (${cell.tradeCount} trades, ${period}) | vs P25=${fmtCompact(cell.baseline.p25, metric)} P50=${fmtCompact(cell.baseline.p50, metric)} P75=${fmtCompact(cell.baseline.p75, metric)} min=${fmtCompact(cell.baseline.min, metric)} max=${fmtCompact(cell.baseline.max, metric)} (n=${cell.baseline.n})`
  return (
    <button
      type="button"
      disabled={isEmpty}
      aria-disabled={isEmpty}
      aria-label={label}
      title={tooltip}
      onClick={() => onClick({ fwd: cell.fwd, tenor: cell.tenor })}
      style={{ backgroundColor: bg }}
      className={`flex h-12 w-full flex-col items-center justify-center rounded-sm border border-slate-800/40 px-1 text-center font-mono text-[11px] leading-tight transition-colors ${fg} ${isEmpty ? 'cursor-not-allowed opacity-50' : 'hover:ring-1 hover:ring-indigo-300/60'}`}
    >
      {isEmpty ? <span className="text-slate-600">—</span> : (
        <>
          <span className="tabular-nums">{fmtCompact(cell.current, metric)}</span>
          <span className="text-[9.5px] text-slate-400">P{Math.round(cell.percentile ?? 0)}</span>
        </>
      )}
    </button>
  )
}
```

**Step 4: Run cell tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid/__tests__/VolumeGridCell
```

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCell.test.tsx
git commit -m "feat(usd-swaps-tape-v2): VolumeGridCell pure component"
```

---

## Task 8: `<VolumeGrid>` pure render + tests

**Goal:** 5×11 grid of cells + Total row + Total column. Pure — no fetch.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGrid.test.tsx`

**Step 1: Write the failing test.**

```tsx
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen } from '@testing-library/react'
import { VolumeGrid } from '../VolumeGrid'
import type { VolumeGridResponse } from '../../../types/volume-grid.types'

const fixture: VolumeGridResponse = {
  asOf: '2026-05-05T14:32:00Z',
  metric: 'notional',
  period: 'today',
  lookbackDays: 90,
  cells: [
    { fwd: 'spot', tenor: '5y', current: 1e9, tradeCount: 5, baseline: { p25: 1e8, p50: 5e8, p75: 9e8, min: 0, max: 1.2e9, n: 90 }, percentile: 88 },
  ],
  totals: {
    rowTotals: { spot: { current: 1e9, percentile: 88 } },
    colTotals: { '5y': { current: 1e9, percentile: 88 } },
    grand: { current: 1e9, percentile: 88 },
  },
}

describe('<VolumeGrid>', () => {
  it('renders a 5x11 grid plus total row and total column', () => {
    render(
      <VolumeGrid data={fixture} metric="notional" period="today" onCellClick={() => {}} />,
    )
    // 5 forward rows + 1 Total row = 6 row labels.
    expect(screen.getAllByTestId('volume-grid-row-label').length).toBe(6)
    // 11 tenor cols + 1 Total col = 12 col labels.
    expect(screen.getAllByTestId('volume-grid-col-label').length).toBe(12)
    // 5 * 11 = 55 inner cells.
    expect(screen.getAllByTestId('volume-grid-cell').length).toBe(55)
  })
  it('routes cell clicks to onCellClick', () => {
    const onCellClick = jest.fn()
    render(
      <VolumeGrid data={fixture} metric="notional" period="today" onCellClick={onCellClick} />,
    )
    const cells = screen.getAllByTestId('volume-grid-cell')
    const populated = cells.find((el) => el.getAttribute('aria-disabled') !== 'true')!
    populated.click()
    expect(onCellClick).toHaveBeenCalled()
  })
})
```

**Step 2: Run, expect failure.**

**Step 3: Implement `VolumeGrid.tsx`.**

```tsx
'use client'
// ABOUTME: Pure render of the forward x tenor matrix + totals. No fetch.

import type { JSX } from 'react'
import { useMemo } from 'react'
import { FORWARD_AXIS, TENOR_AXIS, fwdLabel, tenorLabel } from './buckets'
import { VolumeGridCell } from './VolumeGridCell'
import { colorForPercentile, foregroundForPercentile } from './colorRamp'
import type {
  VolumeGridCell as Cell, VolumeGridResponse, VolumeMetric, VolumePeriod,
} from '../../types/volume-grid.types'

export interface VolumeGridProps {
  data: VolumeGridResponse
  metric: VolumeMetric
  period: VolumePeriod
  onCellClick: (id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => void
}

export function VolumeGrid({ data, metric, period, onCellClick }: VolumeGridProps): JSX.Element {
  // Index cells by (fwd,tenor) for O(1) lookup.
  const cellMap = useMemo(() => {
    const m = new Map<string, Cell>()
    for (const c of data.cells) m.set(`${c.fwd}|${c.tenor}`, c)
    return m
  }, [data.cells])
  return (
    <div
      className="grid gap-px font-mono text-[10.5px] text-slate-300"
      style={{
        gridTemplateColumns: `minmax(54px,auto) repeat(${TENOR_AXIS.length},minmax(58px,1fr)) minmax(64px,auto)`,
      }}
    >
      <div /> {/* corner */}
      {TENOR_AXIS.map((t) => (
        <div
          key={t.id}
          data-testid="volume-grid-col-label"
          className="px-1 pb-1 text-center text-[9.5px] uppercase tracking-wider text-slate-500"
        >
          {t.label}
        </div>
      ))}
      <div
        data-testid="volume-grid-col-label"
        className="px-1 pb-1 text-center text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        Total
      </div>
      {FORWARD_AXIS.map((f) => (
        <RowFragment
          key={f.id}
          fwd={f.id}
          fwdLabelText={fwdLabel(f.id)}
          cellMap={cellMap}
          metric={metric}
          period={period}
          rowTotal={data.totals.rowTotals[f.id]}
          onCellClick={onCellClick}
        />
      ))}
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        Total
      </div>
      {TENOR_AXIS.map((t) => (
        <TotalCell
          key={t.id}
          value={data.totals.colTotals[t.id]?.current ?? 0}
          percentile={data.totals.colTotals[t.id]?.percentile ?? null}
          metric={metric}
        />
      ))}
      <TotalCell
        value={data.totals.grand.current}
        percentile={data.totals.grand.percentile}
        metric={metric}
        emphasized
      />
    </div>
  )
}

function RowFragment(props: {
  fwd: Cell['fwd']
  fwdLabelText: string
  cellMap: Map<string, Cell>
  metric: VolumeMetric
  period: VolumePeriod
  rowTotal: { current: number; percentile: number | null } | undefined
  onCellClick: VolumeGridProps['onCellClick']
}): JSX.Element {
  return (
    <>
      <div
        data-testid="volume-grid-row-label"
        className="flex items-center px-1 text-[9.5px] uppercase tracking-wider text-slate-400"
      >
        {props.fwdLabelText}
      </div>
      {TENOR_AXIS.map((t) => {
        const cell =
          props.cellMap.get(`${props.fwd}|${t.id}`) ??
          ({
            fwd: props.fwd,
            tenor: t.id,
            current: 0, tradeCount: 0,
            baseline: { p25: 0, p50: 0, p75: 0, min: 0, max: 0, n: 0 },
            percentile: null,
          } as Cell)
        return (
          <div key={t.id} data-testid="volume-grid-cell">
            <VolumeGridCell
              cell={cell}
              metric={props.metric}
              period={props.period}
              onClick={props.onCellClick}
            />
          </div>
        )
      })}
      <TotalCell
        value={props.rowTotal?.current ?? 0}
        percentile={props.rowTotal?.percentile ?? null}
        metric={props.metric}
      />
    </>
  )
}

function TotalCell(props: {
  value: number
  percentile: number | null
  metric: VolumeMetric
  emphasized?: boolean
}): JSX.Element {
  const fmt = (() => {
    const abs = Math.abs(props.value)
    if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
    if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
    if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
    return abs.toFixed(0)
  })()
  return (
    <div
      style={{ backgroundColor: colorForPercentile(props.percentile) }}
      className={`flex h-12 flex-col items-center justify-center rounded-sm border border-slate-700/60 text-center text-[11px] tabular-nums ${foregroundForPercentile(props.percentile)} ${props.emphasized ? 'font-semibold ring-1 ring-indigo-400/40' : ''}`}
    >
      <span>{fmt}</span>
      {props.percentile != null && <span className="text-[9.5px] text-slate-400">P{Math.round(props.percentile)}</span>}
    </div>
  )
}
```

**Step 4: Run grid tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid/__tests__/VolumeGrid.test
```

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGrid.test.tsx
git commit -m "feat(usd-swaps-tape-v2): VolumeGrid pure render with totals"
```

---

## Task 9: `<VolumeGridCard>` — fetch wrapper, header, persistence (pre-modal)

**Goal:** Collapsible card with metric + period toggles, persistence, refresh button. Modal hookup deferred to a later task.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCard.test.tsx`

**Step 1: Write the failing test.**

```tsx
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { VolumeGridCard } from '../VolumeGridCard'

const fixture = {
  asOf: '2026-05-05T14:32:00Z', metric: 'notional', period: 'today', lookbackDays: 90,
  cells: [], totals: { rowTotals: {}, colTotals: {}, grand: { current: 0, percentile: null } },
}

const fetchMock = jest.fn()
beforeAll(() => { global.fetch = fetchMock as unknown as typeof fetch })
beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true, json: async () => fixture })
  window.localStorage.clear()
})

describe('<VolumeGridCard>', () => {
  it('starts collapsed by default and does not fetch', async () => {
    render(<VolumeGridCard onSelectPackage={() => {}} />)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByTestId('volume-grid')).toBeNull()
  })
  it('fetches when expanded', async () => {
    render(<VolumeGridCard onSelectPackage={() => {}} />)
    fireEvent.click(screen.getByLabelText(/expand|toggle volume grid/i))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.getByTestId('volume-grid')).toBeTruthy()
  })
  it('persists collapse state to localStorage', () => {
    render(<VolumeGridCard onSelectPackage={() => {}} />)
    fireEvent.click(screen.getByLabelText(/expand|toggle volume grid/i))
    expect(window.localStorage.getItem('usd-tape-v2:volume-grid:collapsed')).toBe('false')
  })
  it('re-fetches on metric change', async () => {
    render(<VolumeGridCard onSelectPackage={() => {}} />)
    fireEvent.click(screen.getByLabelText(/expand|toggle volume grid/i))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    fetchMock.mockClear()
    fireEvent.click(screen.getByText(/dv01/i))
    await waitFor(() => {
      const url = fetchMock.mock.calls[0]?.[0] as string
      expect(url).toContain('metric=dv01')
    })
  })
})
```

**Step 2: Run, expect failures.**

**Step 3: Implement `VolumeGridCard.tsx`.**

```tsx
'use client'
// ABOUTME: Collapsible top-of-page card hosting the volume-grid heatmap.
// Owns metric/period state with localStorage persistence; opens the cell
// drill-down modal on click (modal wired in a later task).

import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { VolumeGrid } from './VolumeGrid'
import { useVolumeGrid } from '../../hooks/useVolumeGrid'
import type {
  VolumeMetric, VolumePeriod,
  VolumeGridCell as Cell,
} from '../../types/volume-grid.types'

const KEY_COLLAPSED = 'usd-tape-v2:volume-grid:collapsed'
const KEY_METRIC    = 'usd-tape-v2:volume-grid:metric'
const KEY_PERIOD    = 'usd-tape-v2:volume-grid:period'

function readBool(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  const v = window.localStorage.getItem(key)
  return v == null ? fallback : v === 'true'
}
function readEnum<T extends string>(key: string, allowed: ReadonlyArray<T>, fallback: T): T {
  if (typeof window === 'undefined') return fallback
  const v = window.localStorage.getItem(key)
  return (allowed as ReadonlyArray<string>).includes(v ?? '') ? (v as T) : fallback
}

export interface VolumeGridCardProps {
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCard({ onSelectPackage }: VolumeGridCardProps): JSX.Element {
  const [collapsed, setCollapsed] = useState<boolean>(() => readBool(KEY_COLLAPSED, true))
  const [metric, setMetric] = useState<VolumeMetric>(() =>
    readEnum<VolumeMetric>(KEY_METRIC, ['notional', 'dv01'], 'notional'),
  )
  const [period, setPeriod] = useState<VolumePeriod>(() =>
    readEnum<VolumePeriod>(KEY_PERIOD, ['today', '1h', '24h', '1w'], 'today'),
  )
  const [selectedCell, setSelectedCell] = useState<{ fwd: Cell['fwd']; tenor: Cell['tenor'] } | null>(null)

  useEffect(() => { window.localStorage.setItem(KEY_COLLAPSED, String(collapsed)) }, [collapsed])
  useEffect(() => { window.localStorage.setItem(KEY_METRIC, metric) }, [metric])
  useEffect(() => { window.localStorage.setItem(KEY_PERIOD, period) }, [period])

  const grid = useVolumeGrid({ metric, period, collapsed })

  const onCellClick = useCallback((id: { fwd: Cell['fwd']; tenor: Cell['tenor'] }) => {
    setSelectedCell(id)
  }, [])

  const asOf = grid.data?.asOf
    ? new Date(grid.data.asOf).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'America/New_York' })
    : null

  void onSelectPackage // wired up in the modal task
  void selectedCell

  return (
    <section
      data-testid="volume-grid-card"
      className="border-b border-slate-800 bg-slate-900/40 ring-1 ring-slate-800"
    >
      <header className="flex items-center gap-2 px-3 py-1.5 text-slate-300">
        <button
          type="button"
          aria-label="Toggle volume grid"
          onClick={() => setCollapsed((v) => !v)}
          className="rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800"
        >
          {collapsed ? '▲ Volume Grid' : '▼ Volume Grid'}
        </button>
        <Toggle
          options={[{ id: 'notional', label: 'Notional' }, { id: 'dv01', label: 'DV01' }]}
          value={metric}
          onChange={setMetric}
        />
        <Toggle
          options={[
            { id: 'today', label: 'Today' },
            { id: '1h', label: '1h' },
            { id: '24h', label: '24h' },
            { id: '1w', label: '1w' },
          ]}
          value={period}
          onChange={setPeriod}
        />
        {asOf && (
          <span className="ml-1 rounded bg-slate-800/60 px-1.5 py-[1px] font-mono text-[9.5px] text-slate-400">
            as-of {asOf} ET
          </span>
        )}
        <button
          type="button"
          onClick={() => grid.refresh()}
          aria-label="Refresh"
          className="ml-auto rounded border border-slate-700 px-2 py-[2px] font-mono text-[10.5px] hover:bg-slate-800"
          disabled={grid.isLoading}
        >
          ⟳
        </button>
        {grid.error && (
          <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[9.5px] text-rose-200 ring-1 ring-rose-500/30">
            {grid.error.message}
          </span>
        )}
      </header>
      {!collapsed && (
        <div className="px-3 pb-3" data-testid="volume-grid">
          {grid.data ? (
            <VolumeGrid
              data={grid.data}
              metric={metric}
              period={period}
              onCellClick={onCellClick}
            />
          ) : (
            <SkeletonGrid />
          )}
        </div>
      )}
    </section>
  )
}

function Toggle<T extends string>({
  options, value, onChange,
}: { options: ReadonlyArray<{ id: T; label: string }>; value: T; onChange: (v: T) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === o.id ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function SkeletonGrid(): JSX.Element {
  return (
    <div className="grid h-32 animate-pulse grid-cols-12 gap-px">
      {Array.from({ length: 12 * 6 }).map((_, i) => (
        <div key={i} className="rounded-sm bg-slate-800/40" />
      ))}
    </div>
  )
}
```

**Step 4: Run card tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid/__tests__/VolumeGridCard
```

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCard.test.tsx
git commit -m "feat(usd-swaps-tape-v2): VolumeGridCard collapsible shell + persistence"
```

---

## Task 10: Mount `<VolumeGridCard>` in `UsdSwapsTradeTape`

**Goal:** Render the card at the top of the tape shell with a stub `onSelectPackage` (real wiring in Task 14).

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx`

**Step 1: Add the import + mount the card above the table.**

In `UsdSwapsTradeTape.tsx`:

1. Add to the imports near the top:

   ```tsx
   import { VolumeGridCard } from './VolumeGrid/VolumeGridCard'
   ```

2. Inside the shell `<div className="usd-swaps-tape-shell ...">`, before `<div className="flex flex-1 min-h-0 overflow-hidden">`, insert:

   ```tsx
   <VolumeGridCard
     onSelectPackage={(packageId) => {
       // Stub — real URL-filter wiring lands in the modal-integration task.
       console.debug('[volume-grid] onSelectPackage', packageId)
     }}
   />
   ```

**Step 2: Run the existing tape integration tests to confirm nothing broke.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=UsdSwapsTradeTape
```

Expected: existing tests still PASS.

**Step 3: Boot the dev server and visual-check.**

```bash
cd SDRUtils/dashboard && npm run dev
```

Open `http://localhost:3000/usd-swaps-v2`. Confirm:
- Card chrome renders at top (collapsed by default).
- Click "Volume Grid" → grid expands, fetches `/api/usd-swaps-tape-v2/volume-grid` (DevTools → Network).
- Tape table still works under the card.

Stop the dev server (Ctrl-C) before committing.

**Step 4: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx
git commit -m "feat(usd-swaps-tape-v2): mount VolumeGridCard in tape shell"
```

---

## Task 11: `/volume-grid/cell` route — pure logic + tests

**Goal:** Build the SQL + parse params for the drill-down route as pure helpers, then wire the handler.

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`

**Step 1: Write the failing tests.**

```ts
import { describe, expect, it } from '@jest/globals'
import {
  parseVolumeGridCellParams,
  buildTimeseriesSql,
  buildRecentTradesSql,
  rangeToStartDate,
} from '../route.logic'

describe('parseVolumeGridCellParams', () => {
  it('rejects missing fwd', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('tenor=5y'))
    expect(out.ok).toBe(false)
  })
  it('rejects missing tenor', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot'))
    expect(out.ok).toBe(false)
  })
  it('applies defaults', () => {
    const out = parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y'))
    expect(out.ok).toBe(true)
    expect(out.value).toMatchObject({ metric: 'notional', range: '3M', recentLimit: 50 })
  })
  it('rejects bogus bucket ids', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=foo&tenor=5y')).ok).toBe(false)
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=foo')).ok).toBe(false)
  })
  it('clamps recentLimit', () => {
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&recentLimit=0')).ok).toBe(false)
    expect(parseVolumeGridCellParams(new URLSearchParams('fwd=spot&tenor=5y&recentLimit=999')).ok).toBe(false)
  })
})

describe('rangeToStartDate', () => {
  it('subtracts approximately the right interval', () => {
    const now = new Date('2026-05-05T00:00:00Z')
    const out = rangeToStartDate('1M', now)
    const days = (now.getTime() - out.getTime()) / 86_400_000
    expect(days).toBeGreaterThanOrEqual(28)
    expect(days).toBeLessThanOrEqual(32)
  })
})

describe('buildTimeseriesSql / buildRecentTradesSql', () => {
  it('timeseries SQL filters on contributes_to_flow and groups by day', () => {
    const sql = buildTimeseriesSql()
    expect(sql).toContain('contributes_to_flow')
    expect(sql).toContain('GROUP BY day')
  })
  it('recentTrades SQL orders by execution_start DESC and limits', () => {
    const sql = buildRecentTradesSql()
    expect(sql).toContain('ORDER BY')
    expect(sql).toContain('execution_start DESC')
    expect(sql).toContain('LIMIT')
  })
})
```

**Step 2: Run, expect failure.**

**Step 3: Implement `route.logic.ts`.**

```ts
// ABOUTME: Pure helpers for /volume-grid/cell. SQL templates take the
// parameter-binding indices as a starting offset so callers thread their
// own bind list cleanly.

import {
  buildBucketPredicate,
  FORWARD_BUCKETS,
  TENOR_BUCKETS,
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
import type {
  VolumeCellRange,
  VolumeMetric,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export interface VolumeGridCellParams {
  fwd: string
  tenor: string
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit: number
}

export type ParseResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: string }

const VALID_METRICS: ReadonlySet<VolumeMetric> = new Set(['notional', 'dv01'])
const VALID_RANGES: ReadonlySet<VolumeCellRange> = new Set(['1M', '3M', '6M', '1Y'])

export function parseVolumeGridCellParams(
  search: URLSearchParams,
): ParseResult<VolumeGridCellParams> {
  const fwd = search.get('fwd')
  const tenor = search.get('tenor')
  if (!fwd) return { ok: false, error: 'fwd is required' }
  if (!tenor) return { ok: false, error: 'tenor is required' }
  if (!FORWARD_BUCKETS.some((b) => b.id === fwd)) return { ok: false, error: `unknown fwd: ${fwd}` }
  if (!TENOR_BUCKETS.some((b) => b.id === tenor)) return { ok: false, error: `unknown tenor: ${tenor}` }
  const metric = (search.get('metric') ?? 'notional').toLowerCase() as VolumeMetric
  if (!VALID_METRICS.has(metric)) return { ok: false, error: `unknown metric: ${metric}` }
  const range = (search.get('range') ?? '3M').toUpperCase() as VolumeCellRange
  if (!VALID_RANGES.has(range)) return { ok: false, error: `unknown range: ${range}` }
  const recentRaw = search.get('recentLimit')
  let recentLimit = 50
  if (recentRaw != null) {
    const n = Number(recentRaw)
    if (!Number.isFinite(n) || n < 1 || n > 200) {
      return { ok: false, error: 'recentLimit must be 1..200' }
    }
    recentLimit = Math.floor(n)
  }
  return { ok: true, value: { fwd, tenor, metric, range, recentLimit } }
}

export function rangeToStartDate(range: VolumeCellRange, now: Date = new Date()): Date {
  const out = new Date(now)
  switch (range) {
    case '1M': out.setUTCMonth(out.getUTCMonth() - 1); return out
    case '3M': out.setUTCMonth(out.getUTCMonth() - 3); return out
    case '6M': out.setUTCMonth(out.getUTCMonth() - 6); return out
    case '1Y': out.setUTCFullYear(out.getUTCFullYear() - 1); return out
  }
}

export function buildTimeseriesSql(): string {
  // Bind order: $1=range_start, $2..N=bucket predicate params.
  return `
    WITH legs AS (
      SELECT
        COALESCE(l.original_execution_timestamp, l.execution_timestamp) AS ts,
        ABS(COALESCE(l.notional, 0)) AS notional,
        ABS(COALESCE(l.risk, 0))     AS dv01,
        l.venue
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND %BUCKET_PREDICATE%
    )
    SELECT
      date_trunc('day', ts AT TIME ZONE 'America/New_York')::date AS day,
      SUM(notional) AS notional,
      SUM(dv01)     AS dv01,
      COUNT(*)::int AS trade_count,
      COUNT(*) FILTER (WHERE venue = 'D2D')::int AS idb_count,
      COUNT(*) FILTER (WHERE venue <> 'D2D' OR venue IS NULL)::int AS custy_count
    FROM legs
    GROUP BY day
    ORDER BY day ASC
  `
}

export function buildRecentTradesSql(): string {
  // Bind order: $1=range_start, $2..N=bucket predicate params, $LAST=limit.
  return `
    WITH eligible_packages AS (
      SELECT DISTINCT l.package_id
      FROM arbs_usd_swap_tape_legs_v2 l
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND %BUCKET_PREDICATE%
    )
    SELECT
      p.package_id,
      p.execution_start,
      p.tape_label,
      p.package_type,
      p.weighted_fixed_rate,
      p.total_risk,
      p.total_notional,
      p.venue,
      p.is_block_any
    FROM arbs_usd_swap_tape_packages_v2 p
    JOIN eligible_packages e ON e.package_id = p.package_id
    ORDER BY p.execution_start DESC
    LIMIT %LIMIT_PLACEHOLDER%
  `
}

export { buildBucketPredicate }
```

**Step 4: Run logic tests, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=cell/__tests__/route.logic
```

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts
git commit -m "feat(usd-swaps-tape-v2): pure helpers for /volume-grid/cell"
```

---

## Task 12: `/volume-grid/cell` route handler + smoke test

**Goal:** Wire the handler with LRU/ETag, mocking out the DB in a smoke test.

**Files:**
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.test.ts`

**Step 1: Write a smoke test.**

```ts
import { describe, expect, it, jest, beforeEach } from '@jest/globals'

const queryMock = jest.fn()
jest.unstable_mockModule('@/lib/db', () => ({ query: queryMock }))

beforeEach(() => queryMock.mockReset())

describe('GET /api/usd-swaps-tape-v2/volume-grid/cell', () => {
  it('400 when fwd missing', async () => {
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api?tenor=5y'))
    expect(res.status).toBe(400)
  })
  it('200 returns timeseries + recentTrades', async () => {
    queryMock
      .mockResolvedValueOnce({
        rows: [
          { day: '2026-05-04', notional: 1e9, dv01: 50000, trade_count: 5, idb_count: 3, custy_count: 2 },
        ],
      })
      .mockResolvedValueOnce({
        rows: [
          {
            package_id: 'pkg-1', execution_start: '2026-05-05T13:00:00Z',
            tape_label: '5Y Outright', package_type: 'OUTRIGHT',
            weighted_fixed_rate: 0.0384, total_risk: 50000, total_notional: 1e9,
            venue: 'D2D', is_block_any: false,
          },
        ],
      })
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api?fwd=spot&tenor=5y'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.timeseries.length).toBe(1)
    expect(body.recentTrades.length).toBe(1)
    expect(body.recentTrades[0].package_id).toBe('pkg-1')
  })
})
```

**Step 2: Run, expect failure.**

**Step 3: Implement `route.ts`.**

```ts
// ABOUTME: GET /api/usd-swaps-tape-v2/volume-grid/cell.
// Returns daily volume timeseries + most-recent N packages for the bucket.

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import { computeEtag, matchesIfNoneMatch } from '@/lib/usd-swaps-tape-v2/etag'
import {
  buildBucketPredicate,
  buildRecentTradesSql,
  buildTimeseriesSql,
  parseVolumeGridCellParams,
  rangeToStartDate,
} from './route.logic'
import type {
  VolumeGridCellResponse,
  VolumeGridCellRecentTrade,
  VolumeGridCellTimeseriesPoint,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 512)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: 60_000,
})
const CACHE_HEADERS = { 'Cache-Control': 'private, max-age=60, must-revalidate' } as const

const cacheKey = (url: URL): string => {
  const sorted = [...new URLSearchParams(url.search).entries()].sort()
  return JSON.stringify(sorted)
}

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export async function GET(request: Request) {
  const url = new URL(request.url)
  const ifNoneMatch = request.headers.get('If-None-Match')
  const key = cacheKey(url)
  const hit = lru.get(key)
  if (hit) {
    if (matchesIfNoneMatch(hit.etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: hit.etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(hit.payload, { headers: { ETag: hit.etag, ...CACHE_HEADERS } })
  }

  const parsed = parseVolumeGridCellParams(url.searchParams)
  if (!parsed.ok) return NextResponse.json({ error: parsed.error }, { status: 400 })
  const p = parsed.value

  const rangeStart = rangeToStartDate(p.range)
  const predicate = buildBucketPredicate('l', p.fwd, p.tenor, 2)

  const tsSql = buildTimeseriesSql().replace('%BUCKET_PREDICATE%', predicate.sql)
  const tradesSql = buildRecentTradesSql()
    .replace('%BUCKET_PREDICATE%', predicate.sql)
    .replace('%LIMIT_PLACEHOLDER%', `$${2 + predicate.params.length}`)

  try {
    const tsParams = [rangeStart.toISOString(), ...predicate.params]
    const tradesParams = [rangeStart.toISOString(), ...predicate.params, p.recentLimit]

    const [tsResult, tradesResult] = await Promise.all([
      query<Record<string, unknown>>(tsSql, tsParams),
      query<Record<string, unknown>>(tradesSql, tradesParams),
    ])

    const timeseries: VolumeGridCellTimeseriesPoint[] = tsResult.rows.map((r) => ({
      day: typeof r.day === 'string' ? r.day : new Date(r.day as string).toISOString().slice(0, 10),
      notional: num(r.notional),
      dv01: num(r.dv01),
      tradeCount: num(r.trade_count),
      idbCount: num(r.idb_count),
      custyCount: num(r.custy_count),
    }))
    const recentTrades: VolumeGridCellRecentTrade[] = tradesResult.rows.map((r) => ({
      package_id: String(r.package_id),
      execution_start: typeof r.execution_start === 'string'
        ? r.execution_start
        : new Date(r.execution_start as string).toISOString(),
      tape_label: (r.tape_label as string | null) ?? null,
      package_type: (r.package_type as string | null) ?? null,
      weighted_fixed_rate: r.weighted_fixed_rate == null ? null : num(r.weighted_fixed_rate),
      total_risk: r.total_risk == null ? null : num(r.total_risk),
      total_notional: r.total_notional == null ? null : num(r.total_notional),
      venue: (r.venue as string | null) ?? null,
      is_block_any: (r.is_block_any as boolean | null) ?? null,
    }))
    const payload: VolumeGridCellResponse = {
      fwd: p.fwd as VolumeGridCellResponse['fwd'],
      tenor: p.tenor as VolumeGridCellResponse['tenor'],
      metric: p.metric, range: p.range,
      timeseries, recentTrades,
    }
    const etag = computeEtag(payload)
    lru.set(key, { payload, etag })
    if (matchesIfNoneMatch(etag, ifNoneMatch)) {
      return new Response(null, { status: 304, headers: { ETag: etag, ...CACHE_HEADERS } })
    }
    return NextResponse.json(payload, { headers: { ETag: etag, ...CACHE_HEADERS } })
  } catch (error) {
    console.error('usd-swaps-tape-v2/volume-grid/cell error', error)
    const message = error instanceof Error ? error.message : 'failed to fetch cell drill-down'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
```

**Step 4: Run, verify pass.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=cell/__tests__/route
```

**Step 5: Commit.**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.test.ts
git commit -m "feat(usd-swaps-tape-v2): /volume-grid/cell route handler"
```

---

## Task 13: `useVolumeGridCell` hook + tests

**Goal:** SWR hook for the drill-down endpoint, only fetches when modal is open.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useVolumeGridCell.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useVolumeGridCell.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/index.ts`

**Step 1: Write tests** (mirror `useVolumeGrid` test structure — verify URL contains `fwd`, `tenor`, `range`; skips fetch when `cell == null`).

**Step 2: Implement.**

```ts
// ABOUTME: SWR hook for /api/usd-swaps-tape-v2/volume-grid/cell.
import useSWR from 'swr'
import { TAPE_V2_API_BASE } from '../constants'
import type {
  VolumeCellRange, VolumeMetric,
  VolumeGridCellResponse,
} from '../types/volume-grid.types'

export interface UseVolumeGridCellArgs {
  cell: { fwd: string; tenor: string } | null
  metric: VolumeMetric
  range: VolumeCellRange
  recentLimit?: number
  fetcher?: typeof fetch
}

export function useVolumeGridCell(args: UseVolumeGridCellArgs) {
  const fetcher = args.fetcher ?? fetch
  const url = (() => {
    if (!args.cell) return null
    const q = new URLSearchParams({
      fwd: args.cell.fwd, tenor: args.cell.tenor,
      metric: args.metric, range: args.range,
    })
    if (args.recentLimit != null) q.set('recentLimit', String(args.recentLimit))
    return `${TAPE_V2_API_BASE}/volume-grid/cell?${q}`
  })()
  const swr = useSWR<VolumeGridCellResponse, Error>(
    url,
    async (u: string) => {
      const res = await fetcher(u)
      if (!res.ok) throw new Error(`cell fetch failed: ${res.status} ${res.statusText}`)
      return res.json() as Promise<VolumeGridCellResponse>
    },
    { refreshInterval: 30_000, revalidateOnFocus: true, dedupingInterval: 5_000 },
  )
  return { data: swr.data, error: swr.error ?? null, isLoading: swr.isLoading, refresh: () => swr.mutate() }
}
```

Re-export from `hooks/index.ts`.

**Step 3: Run hook tests, verify pass; commit.**

```bash
git add ...
git commit -m "feat(usd-swaps-tape-v2): useVolumeGridCell SWR hook"
```

---

## Task 14: `<VolumeGridCellModal>` — chart + recent-trades + click-through wiring

**Goal:** PrimeReact `Dialog` rendering the timeseries chart and recent-trades table; row click closes modal and writes the package_id to the URL filter.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx` (mount the modal)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx` (replace stub `onSelectPackage`)

**Step 1: Write the modal test (uses mocked SWR; renders with `selectedCell` non-null, asserts chart container + table rows present, row click invokes prop).**

```tsx
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import { VolumeGridCellModal } from '../VolumeGridCellModal'

const fixture = {
  fwd: 'spot', tenor: '5y', metric: 'notional', range: '3M',
  timeseries: [
    { day: '2026-05-04', notional: 1e9, dv01: 50000, tradeCount: 5, idbCount: 3, custyCount: 2 },
  ],
  recentTrades: [
    {
      package_id: 'pkg-1', execution_start: '2026-05-05T13:00:00Z',
      tape_label: '5Y Outright', package_type: 'OUTRIGHT',
      weighted_fixed_rate: 0.0384, total_risk: 50000, total_notional: 1e9,
      venue: 'D2D', is_block_any: false,
    },
  ],
}
const fetchMock = jest.fn()
beforeAll(() => { global.fetch = fetchMock as unknown as typeof fetch })
beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockResolvedValue({ ok: true, json: async () => fixture })
})

describe('<VolumeGridCellModal>', () => {
  it('renders the timeseries chart container and trades table', async () => {
    render(
      <VolumeGridCellModal
        cell={{ fwd: 'spot', tenor: '5y' }}
        metric="notional"
        onClose={() => {}}
        onSelectPackage={() => {}}
      />,
    )
    await screen.findByText(/5y/i)
    expect(screen.getByTestId('volume-grid-cell-chart')).toBeTruthy()
    expect(await screen.findByText(/pkg-1/i)).toBeTruthy()
  })
  it('row click invokes onSelectPackage and onClose', async () => {
    const onSelect = jest.fn()
    const onClose = jest.fn()
    render(
      <VolumeGridCellModal
        cell={{ fwd: 'spot', tenor: '5y' }}
        metric="notional"
        onClose={onClose}
        onSelectPackage={onSelect}
      />,
    )
    const row = await screen.findByText(/pkg-1/i)
    fireEvent.click(row.closest('tr')!)
    expect(onSelect).toHaveBeenCalledWith('pkg-1')
    expect(onClose).toHaveBeenCalled()
  })
})
```

**Step 2: Run, expect failure.**

**Step 3: Implement `VolumeGridCellModal.tsx`.**

```tsx
'use client'
// ABOUTME: PrimeReact Dialog with daily volume timeseries + recent trades
// for the clicked grid cell. Row click closes modal and routes the
// package_id to onSelectPackage (which writes a URL filter).

import type { JSX } from 'react'
import { useState } from 'react'
import { Dialog } from 'primereact/dialog'
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { useVolumeGridCell } from '../../hooks/useVolumeGridCell'
import { fwdLabel, tenorLabel } from './buckets'
import type {
  VolumeCellRange, VolumeMetric,
} from '../../types/volume-grid.types'

const KEY_RANGE = 'usd-tape-v2:volume-grid:cell-range'

const fmtCompact = (n: number, metric: VolumeMetric): string => {
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${(abs / 1e3).toFixed(0)}k`
  return abs.toFixed(metric === 'dv01' ? 0 : 0)
}

const fmtRate = (r: number | null): string => (r == null ? '-' : `${(r * 100).toFixed(3)}%`)
const fmtTime = (ts: string): string =>
  new Date(ts).toLocaleString('en-US', {
    timeZone: 'America/New_York', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })

export interface VolumeGridCellModalProps {
  cell: { fwd: string; tenor: string } | null
  metric: VolumeMetric
  onClose: () => void
  onSelectPackage: (packageId: string) => void
}

export function VolumeGridCellModal(props: VolumeGridCellModalProps): JSX.Element {
  const [range, setRange] = useState<VolumeCellRange>(() => {
    if (typeof window === 'undefined') return '3M'
    const v = window.localStorage.getItem(KEY_RANGE)
    return ['1M', '3M', '6M', '1Y'].includes(v ?? '') ? (v as VolumeCellRange) : '3M'
  })
  const onRangeChange = (r: VolumeCellRange) => {
    setRange(r)
    if (typeof window !== 'undefined') window.localStorage.setItem(KEY_RANGE, r)
  }

  const { data, error, isLoading } = useVolumeGridCell({
    cell: props.cell, metric: props.metric, range,
  })

  const headerLabel = props.cell
    ? `${fwdLabel(props.cell.fwd)} × ${tenorLabel(props.cell.tenor)} — Volume detail`
    : 'Volume detail'

  return (
    <Dialog
      header={headerLabel}
      visible={props.cell != null}
      onHide={props.onClose}
      style={{ width: '80vw', maxWidth: 1200, height: '75vh' }}
      modal
    >
      <div className="flex h-full flex-col gap-3">
        <div className="flex items-center gap-2 text-slate-300">
          <RangeToggle value={range} onChange={onRangeChange} />
          {isLoading && (
            <span className="rounded bg-sky-500/15 px-1.5 py-[1px] font-mono text-[10px] text-sky-200 ring-1 ring-sky-500/30">
              loading…
            </span>
          )}
          {error && (
            <span className="rounded bg-rose-500/15 px-1.5 py-[1px] font-mono text-[10px] text-rose-200 ring-1 ring-rose-500/30">
              {error.message}
            </span>
          )}
        </div>
        <div data-testid="volume-grid-cell-chart" className="h-[40%] min-h-[200px]">
          {data?.timeseries.length ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.timeseries}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.2)" />
                <XAxis dataKey="day" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }}
                       tickFormatter={(v) => fmtCompact(Number(v), props.metric)} />
                <Tooltip
                  contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
                  formatter={(value: number, name: string) => {
                    if (name === 'tradeCount') return [String(value), 'trades']
                    return [fmtCompact(value, props.metric), props.metric]
                  }}
                />
                <Bar
                  dataKey={props.metric === 'notional' ? 'notional' : 'dv01'}
                  fill="#6366f1"
                />
                {data.timeseries.length > 1 && (
                  <ReferenceLine
                    y={median(data.timeseries.map((p) => p[props.metric === 'notional' ? 'notional' : 'dv01']))}
                    stroke="#94a3b8"
                    strokeDasharray="4 2"
                  />
                )}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">
              No trades in this bucket over the selected range.
            </div>
          )}
        </div>
        <div className="flex-1 overflow-auto rounded border border-slate-800">
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="sticky top-0 bg-slate-900/80 text-[9.5px] uppercase tracking-wider text-slate-500">
              <tr>
                <Th>Time</Th><Th>Type</Th><Th>Tape</Th><Th>Rate</Th>
                <Th>Risk</Th><Th>Notional</Th><Th>Venue</Th><Th>Block?</Th>
              </tr>
            </thead>
            <tbody>
              {data?.recentTrades.length ? data.recentTrades.map((t) => (
                <tr
                  key={t.package_id}
                  className="cursor-pointer border-t border-slate-800/60 hover:bg-indigo-500/10"
                  onClick={() => {
                    props.onSelectPackage(t.package_id)
                    props.onClose()
                  }}
                >
                  <Td>{fmtTime(t.execution_start)}</Td>
                  <Td>{t.package_type ?? '-'}</Td>
                  <Td>{t.tape_label ?? '-'}</Td>
                  <Td>{fmtRate(t.weighted_fixed_rate)}</Td>
                  <Td>{t.total_risk == null ? '-' : fmtCompact(t.total_risk, 'dv01')}</Td>
                  <Td>{t.total_notional == null ? '-' : fmtCompact(t.total_notional, 'notional')}</Td>
                  <Td>{t.venue ?? '-'}</Td>
                  <Td>{t.is_block_any ? 'BLOCK' : ''}</Td>
                  <Td className="hidden">{t.package_id}</Td>
                </tr>
              )) : (
                <tr><td className="p-2 text-slate-500" colSpan={8}>No recent trades for this bucket.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Dialog>
  )
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const s = [...values].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

function Th({ children }: { children: React.ReactNode }): JSX.Element {
  return <th className="px-2 py-1.5">{children}</th>
}
function Td({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
  return <td className={`px-2 py-1.5 ${className ?? ''}`}>{children}</td>
}

function RangeToggle({ value, onChange }: { value: VolumeCellRange; onChange: (v: VolumeCellRange) => void }): JSX.Element {
  return (
    <div className="flex items-center rounded border border-slate-700 p-[1px]">
      {(['1M', '3M', '6M', '1Y'] as const).map((r) => (
        <button
          key={r} type="button" onClick={() => onChange(r)}
          className={`px-2 py-[1px] font-mono text-[10.5px] ${value === r ? 'bg-indigo-500/25 text-indigo-100' : 'text-slate-300 hover:bg-slate-800'}`}
        >
          {r}
        </button>
      ))}
    </div>
  )
}
```

**Step 4: Mount the modal inside `VolumeGridCard.tsx`.**

In the card body, after the grid render, add:

```tsx
<VolumeGridCellModal
  cell={selectedCell}
  metric={metric}
  onClose={() => setSelectedCell(null)}
  onSelectPackage={onSelectPackage}
/>
```

And import it:

```tsx
import { VolumeGridCellModal } from './VolumeGridCellModal'
```

Remove the `void selectedCell` and `void onSelectPackage` placeholders.

**Step 5: Replace the stub `onSelectPackage` in `UsdSwapsTradeTape.tsx`.**

Use the same `useColumnFilters` URL pattern as `AnalyticsPanel.onBinBrush`:

```tsx
import { useRouter, usePathname, useSearchParams } from 'next/navigation'
import { FilterMatchMode } from 'primereact/api'
import { COLUMN_FILTER_QUERY_KEY } from '../hooks/useColumnFilters'

// inside component:
const router = useRouter()
const pathname = usePathname()
const searchParams = useSearchParams()

const onSelectPackageFromGrid = useCallback((packageId: string) => {
  const next = new URLSearchParams(searchParams?.toString() ?? '')
  next.set(
    COLUMN_FILTER_QUERY_KEY,
    JSON.stringify({
      package_id: { value: packageId, matchMode: FilterMatchMode.EQUALS },
    }),
  )
  router.replace(`${pathname}?${next.toString()}`, { scroll: false })
}, [pathname, router, searchParams])

// then pass to the card:
<VolumeGridCard onSelectPackage={onSelectPackageFromGrid} />
```

**Step 6: Run all VolumeGrid tests + tape integration tests.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=VolumeGrid
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=UsdSwapsTradeTape
```

Expected: PASS.

**Step 7: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx
git commit -m "feat(usd-swaps-tape-v2): VolumeGridCellModal + URL-filter click-through"
```

---

## Task 15: RTL integration test for the full feature

**Goal:** End-to-end component test of card → cell click → modal → row click → URL filter.

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__/UsdSwapsTradeTape.volumeGrid.test.tsx`

**Step 1: Author the integration test.** Mock both fetch endpoints (`/volume-grid` and `/cell`) plus the existing tape endpoints; assert: card renders → expand → grid shows → click cell → modal opens → click trade → modal closes + URL has `columnFilters` payload with `package_id`.

```tsx
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import UsdSwapsTradeTape from '../UsdSwapsTradeTape'

const gridFixture = {
  asOf: '2026-05-05T14:32:00Z', metric: 'notional', period: 'today', lookbackDays: 90,
  cells: [
    { fwd: 'spot', tenor: '5y', current: 1e9, tradeCount: 5,
      baseline: { p25: 1e8, p50: 5e8, p75: 9e8, min: 0, max: 1.2e9, n: 90 },
      percentile: 88 },
  ],
  totals: {
    rowTotals: { spot: { current: 1e9, percentile: 88 } },
    colTotals: { '5y': { current: 1e9, percentile: 88 } },
    grand: { current: 1e9, percentile: 88 },
  },
}
const cellFixture = {
  fwd: 'spot', tenor: '5y', metric: 'notional', range: '3M',
  timeseries: [{ day: '2026-05-04', notional: 1e9, dv01: 50000, tradeCount: 5, idbCount: 3, custyCount: 2 }],
  recentTrades: [{
    package_id: 'pkg-1', execution_start: '2026-05-05T13:00:00Z',
    tape_label: '5Y Outright', package_type: 'OUTRIGHT',
    weighted_fixed_rate: 0.0384, total_risk: 50000, total_notional: 1e9,
    venue: 'D2D', is_block_any: false,
  }],
}

const fetchMock = jest.fn()
beforeAll(() => { global.fetch = fetchMock as unknown as typeof fetch })
beforeEach(() => {
  window.localStorage.clear()
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (input: string | URL | Request) => {
    const url = String(input)
    if (url.includes('/volume-grid/cell')) return new Response(JSON.stringify(cellFixture), { status: 200 })
    if (url.includes('/volume-grid')) return new Response(JSON.stringify(gridFixture), { status: 200 })
    // Fallback for the tape endpoint and friends; return empty payloads so
    // the table renders but stays empty.
    return new Response(JSON.stringify({ rows: [], hasMore: false, nextCursor: null, latestExecutionStart: null }), { status: 200 })
  })
})

describe('UsdSwapsTradeTape — volume grid integration', () => {
  it('expand → click cell → click trade → URL filter applied', async () => {
    render(<UsdSwapsTradeTape />)
    fireEvent.click(screen.getByLabelText(/toggle volume grid/i))
    await waitFor(() => expect(screen.getByTestId('volume-grid')).toBeTruthy())
    const cells = screen.getAllByTestId('volume-grid-cell')
    const populated = cells.find((el) => el.querySelector('button[aria-disabled="false"]'))
    expect(populated).toBeTruthy()
    fireEvent.click(populated!.querySelector('button')!)
    await screen.findByText(/pkg-1/i)
    fireEvent.click(screen.getByText(/pkg-1/i).closest('tr')!)
    await waitFor(() => {
      expect(window.location.search).toContain('package_id')
    })
  })
})
```

**Step 2: Run, ensure pass; iterate if mock shape mismatches.**

```bash
npm --prefix SDRUtils/dashboard test -- --testPathPatterns=UsdSwapsTradeTape.volumeGrid
```

**Step 3: Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__/UsdSwapsTradeTape.volumeGrid.test.tsx
git commit -m "test(usd-swaps-tape-v2): RTL integration for volume grid"
```

---

## Task 16: Type-check + full unit suite

**Goal:** Catch any TS or test regressions across the whole touched surface before E2E.

**Step 1: Run full type-check.**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit
```

Expected: zero errors. Fix any until clean.

**Step 2: Run lint on touched paths.**

```bash
cd SDRUtils/dashboard && npm run lint -- src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts src/app/api/usd-swaps-tape-v2/volume-grid src/features/usd-swaps-tape-v2/components/VolumeGrid src/features/usd-swaps-tape-v2/hooks
```

Expected: zero errors / warnings. Fix any.

**Step 3: Run all dashboard tests.**

```bash
npm --prefix SDRUtils/dashboard test
```

Expected: all PASS.

**Step 4: If anything was fixed, commit.**

```bash
git commit -am "chore(usd-swaps-tape-v2): clean lint/types after volume-grid"
```

---

## Task 17: Chrome-MCP E2E walkthrough

**Goal:** Execute the scripted checklist from the design doc using the Chrome MCP tools (`mcp__Claude_in_Chrome__*`). Each scenario logs pass/fail.

**Pre-requisites:** dev server running locally (`cd SDRUtils/dashboard && npm run dev`). The DB connection must point at a non-empty warehouse (use the same connection as the rest of dev).

**Step 1: Boot the dev server in the background.**

```bash
cd SDRUtils/dashboard && npm run dev
```

Wait until logs say `ready - started server on http://localhost:3000`.

**Step 2: Confirm Chrome extension is paired.**

Use `mcp__Claude_in_Chrome__list_connected_browsers`. If absent, tell the user to open the Chrome extension.

**Step 3: Run scenario 1 — happy path.**

Use `mcp__Claude_in_Chrome__tabs_create_mcp` → `navigate` to `http://localhost:3000/usd-swaps-v2` → `find` "Volume Grid" → `computer.left_click` the toggle button → `read_page` to find a populated cell → `computer.left_click` the cell → wait for the modal title via `find` → click the first trade row via `computer.left_click` on the row text → use `javascript_tool` to read `location.search` and assert `columnFilters` payload contains `package_id`. Capture pass/fail in the log.

**Step 4: Run scenarios 2–9 from the design doc** — colour-sanity, period switch, collapse persistence, modal range switch, error path, live polling, empty bucket, modal stacking. For each: short pass/fail line + key DOM/network observation.

**Step 5: Stop the dev server.**

`Ctrl-C` in the terminal where it's running.

**Step 6: Append a brief E2E log to a new file.**

Create `docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-e2e-log.md` with one line per scenario (pass/fail + observation).

**Step 7: Commit the log.**

```bash
git add docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-e2e-log.md
git commit -m "test(usd-swaps-tape-v2): Chrome MCP E2E walkthrough log"
```

---

## Task 18: Performance + final sweep

**Goal:** Sanity-check that polling doesn't hammer the warehouse and the page still feels fast.

**Step 1: Network audit during 60s poll cycle.**

With dev server running and the card expanded:

- Use `mcp__Claude_in_Chrome__read_network_requests` filtered by `/volume-grid`.
- Wait 65 s.
- Read again. Assert: at most 3 `/volume-grid` GETs in the window (≤30s polling + initial). Assert: at least one returned 304 (LRU/ETag working). Document.

**Step 2: Confirm collapsed state pauses polling.**

- Collapse the card.
- Wait 35 s.
- `read_network_requests` filtered by `/volume-grid`. Assert: zero new GETs.

**Step 3: SQL plan sanity (optional, only if reviewer asks).**

Run `EXPLAIN ANALYZE` against the warehouse on the matrix SQL with realistic params; assert the index on `(contributes_to_flow, original_execution_timestamp)` is used. Skip if unavailable.

**Step 4: Final commit if anything was tweaked.**

```bash
git status
# If any changes, stage and commit a "perf:" or "chore:" commit.
```

---

## Task 19: PR

**Goal:** Push branch and open PR.

**Step 1: Push the branch.**

```bash
git push -u origin claude/vigilant-cohen-0e2e8c
```

**Step 2: Open the PR.**

```bash
gh pr create --title "feat(usd-swaps-tape-v2): volume grid heatmap + cell drill-down" --body "$(cat <<'EOF'
## Summary

- New top-of-page collapsible volume heatmap on the USD swap tape v2: forward × tenor matrix with percentile-vs-lookback colour ramp.
- New `/api/usd-swaps-tape-v2/volume-grid` (matrix) and `/volume-grid/cell` (drill-down) routes; both honour the `contributes_to_flow=TRUE` mandate.
- Cell click opens a PrimeReact `Dialog` with daily volume timeseries + recent-trades table; row click writes a `package_id` URL filter via the existing `useColumnFilters` plumbing.
- Bucket boundaries live in a single `lib/usd-swaps-tape-v2/volumeGridBuckets.ts` helper imported by both routes.

Design doc: [`docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-design.md`](docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-design.md)

## Test plan

- [x] Unit: `volumeGridBuckets`, `colorRamp`, `route.logic` for both endpoints
- [x] Hook: `useVolumeGrid`, `useVolumeGridCell`
- [x] Component: `VolumeGridCell`, `VolumeGrid`, `VolumeGridCard`, `VolumeGridCellModal`
- [x] Integration: `UsdSwapsTradeTape.volumeGrid.test.tsx`
- [x] Chrome MCP E2E walkthrough — log committed at `docs/plans/2026-05-05-usd-swaps-tape-v2-volume-grid-e2e-log.md`
- [x] Polling/collapse perf sanity — verified ≥1 ETag-304 hit and zero requests while collapsed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.

---

## Reference: existing patterns to mirror

| Concern | Reference |
|---|---|
| Server LRU + ETag | `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/analytics-timeseries/route.ts` |
| `packageAnalyticsCtes` helper | `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/analytics.ts` |
| PrimeReact `Dialog` + Recharts | `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx` |
| URL-filter click-through | `AnalyticsPanel.tsx` `onBinBrush` |
| localStorage prefs (synchronous read on first render) | `AnalyticsPanel.tsx` rarity prefs block |
| Per-route smoke test with mocked `query` | `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/risk-concentration/__tests__/route.logic.test.ts` |
| Existing E2E pattern (Puppeteer) | `SDRUtils/dashboard/__tests__/e2e/usd-swaps-v2.test.ts` (kept for context; this feature uses Chrome MCP instead) |

## Coding standards

- Filter aggregators on `contributes_to_flow=TRUE` (per `SDRUtils/CLAUDE.md`). Never branch on raw `event_action` / `event_type`.
- Use `original_execution_timestamp` (fall back to `execution_timestamp`) as the time anchor.
- Prefer existing helpers (`@/lib/db`, `ServerLru`, `computeEtag`) over rolling new ones.
- New files start with `// ABOUTME:` summary line.
- Conventional Commits.
