# Volume Grid 'All' Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and enhance the volume grid's 'All' package type option to correctly include curve/fly legs with per-cell composition breakdown and leg-annotated drill-down analytics.

**Architecture:** The SQL builders gain 4 FILTER columns for package-family decomposition (outright/curve/fly/other). The cell modal's recent trades query adds a correlated JSON subquery returning per-leg detail with `inCell` flags. The VolumeGridCell component adds a thin stacked bar showing composition, and the modal table gains expandable leg rows.

**Tech Stack:** TypeScript, Next.js API routes, PostgreSQL (via `@/lib/db`), React (PrimeReact Dialog, Recharts), Jest + React Testing Library.

**Spec:** [`docs/superpowers/specs/2026-05-14-volume-grid-all-enhancement-design.md`](../specs/2026-05-14-volume-grid-all-enhancement-design.md)

---

## File Map

### Modified files

| File | Responsibility |
|------|---------------|
| `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts` | New `buildPkgFamilySql()` helper |
| `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts` | Extend `VolumeGridCell`, `VolumeGridCellRecentTrade` |
| `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts` | `pkg_family` CASE + 4 FILTER columns in both SQL builders, extend `RawVolumeGridRow` + `shapeVolumeGridResponse` |
| `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts` | Enhance `buildRecentTradesSql` with legs JSON subquery |
| `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts` | Thread `inCellPredicate`, map legs in response |
| `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx` | Thread `packageType` prop to cells |
| `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx` | Pass `packageType` to `VolumeGrid` |
| `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx` | Mini stacked bar for package composition |
| `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx` | Expandable leg rows, cell contribution column, package badge |

### Test files (extend existing)

| File | Covers |
|------|--------|
| `volume-grid/__tests__/route.logic.test.ts` | SQL builder pkg_family columns, response shaping |
| `volume-grid/cell/__tests__/route.logic.test.ts` | Leg-annotated recent trades SQL |
| `__tests__/volumeGridBuckets.test.ts` | `buildPkgFamilySql` + regression guard |
| `VolumeGrid/__tests__/VolumeGridCell.test.tsx` | Stacked bar rendering |
| `VolumeGrid/__tests__/VolumeGridCellModal.test.tsx` | Expandable leg rows |

---

## Task 1: Data Layer Verification

**Files:** None (manual DB queries)

This task verifies that curve/fly legs are correctly stored in the database before writing any code. Run these queries against the production database.

- [ ] **Step 1: Find a real FLY package**

```sql
SELECT package_id, tape_label, package_type, total_risk, total_notional,
       n_package_legs, execution_start
FROM arbs_usd_swap_tape_packages_v2
WHERE package_type = 'FLY'
ORDER BY execution_start DESC
LIMIT 5;
```

Record a `package_id` from the results for the next step.

- [ ] **Step 2: Trace legs for the FLY package**

```sql
SELECT leg_id, package_id, tenor_years, forward_start_years,
       notional, risk, contributes_to_flow, venue, platform_identifier
FROM arbs_usd_swap_tape_legs_v2
WHERE package_id = '<package_id_from_step_1>'
ORDER BY tenor_years;
```

**Expected:** 3 rows with:
- Distinct `tenor_years` (e.g., 5, 10, 30)
- Same `forward_start_years` across all legs
- Body leg (middle tenor) has ~2x the risk of each wing
- All 3 have `contributes_to_flow = TRUE`

If any of these fail, document the gap and stop — pipeline fix needed first.

- [ ] **Step 3: Find a real CURVE package and verify**

```sql
SELECT p.package_id, p.tape_label, p.package_type,
       l.tenor_years, l.forward_start_years, l.risk, l.notional, l.contributes_to_flow
FROM arbs_usd_swap_tape_packages_v2 p
JOIN arbs_usd_swap_tape_legs_v2 l ON l.package_id = p.package_id
WHERE p.package_type = 'CURVE'
ORDER BY p.execution_start DESC, l.tenor_years
LIMIT 10;
```

**Expected:** 2 legs per package, different tenors, same forward, opposite-sign risk, `contributes_to_flow = TRUE`.

- [ ] **Step 4: Verify 'All' API returns curve/fly contributions**

```bash
curl -s "http://localhost:3000/api/usd-swaps-tape-v2/volume-grid?packageType=all&period=1w&metric=dv01" | jq '.cells | map(select(.current > 0)) | length'
```

Compare count against same query with `packageType=outright`. The 'all' count should be >= the outright count.

- [ ] **Step 5: Commit verification notes**

```bash
git add -A && git commit -m "chore: verify data layer for volume grid 'All' enhancement"
```

---

## Task 2: Type & Constant Foundation

**Files:**
- Modify: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts:359-413`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts:25-34,89-112`
- Test: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts`

- [ ] **Step 1: Write test for `buildPkgFamilySql`**

Add to `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts`:

```typescript
import { buildPackageTypeFilter, buildPkgFamilySql } from '../volumeGridBuckets'

describe('buildPackageTypeFilter regression', () => {
  it('returns TRUE with no params for the all group', () => {
    const result = buildPackageTypeFilter('all', 'p', 1)
    expect(result.sql).toBe('TRUE')
    expect(result.params).toEqual([])
  })
})

describe('buildPkgFamilySql', () => {
  it('returns a CASE expression using the given alias', () => {
    const sql = buildPkgFamilySql('p')
    expect(sql).toContain("p.package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY')")
    expect(sql).toContain("THEN 'outright'")
    expect(sql).toContain("THEN 'curve'")
    expect(sql).toContain("THEN 'fly'")
    expect(sql).toContain("ELSE 'other'")
  })

  it('uses the provided alias for column references', () => {
    const sql = buildPkgFamilySql('pkg')
    expect(sql).toContain('pkg.package_type')
    expect(sql).not.toContain('p.package_type')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volumeGridBuckets" --no-coverage
```

Expected: FAIL — `buildPkgFamilySql` is not exported.

- [ ] **Step 3: Add `buildPkgFamilySql` to volumeGridBuckets.ts**

Add after the `buildPackageTypeFilter` function (after line 413) in `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts`:

```typescript
export function buildPkgFamilySql(alias: string): string {
  return `CASE
    WHEN ${alias}.package_type IN ('OUTRIGHT','SPREADOVER','MATCHED_MATURITY') THEN 'outright'
    WHEN ${alias}.package_type IN ('CURVE','SPREADOVER_CURVE','MATCHED_MATURITY_CURVE') THEN 'curve'
    WHEN ${alias}.package_type IN ('FLY','SPREADOVER_FLY','MATCHED_MATURITY_FLY') THEN 'fly'
    ELSE 'other'
  END`
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volumeGridBuckets" --no-coverage
```

Expected: PASS

- [ ] **Step 5: Extend `VolumeGridCell` type**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts`, add 4 fields to the `VolumeGridCell` interface after line 33 (`percentile: number | null`):

```typescript
export interface VolumeGridCell {
  fwd: string
  tenor: string
  current: number
  idbCurrent: number
  custyCurrent: number
  tradeCount: number
  baseline: VolumeGridBaseline
  percentile: number | null
  outrightCurrent: number
  curveCurrent: number
  flyCurrent: number
  otherCurrent: number
}
```

- [ ] **Step 6: Add `RecentTradeLeg` type and extend `VolumeGridCellRecentTrade`**

In the same file, add a new interface before `VolumeGridCellRecentTrade` (before line 89) and extend the existing type:

```typescript
export interface RecentTradeLeg {
  tenorYears: number
  forwardStartYears: number
  notional: number
  risk: number
  inCell: boolean
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
  legs: RecentTradeLeg[] | null
}
```

- [ ] **Step 7: Commit**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/volumeGridBuckets.ts \
        SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/__tests__/volumeGridBuckets.test.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/volume-grid.types.ts
git commit -m "feat(volume-grid): add buildPkgFamilySql helper and extend types for 'All' enhancement"
```

---

## Task 3: Main Grid SQL — pkg_family Composition (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts:339-530,573-683`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write failing tests for pkg_family columns in SQL**

Add to `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts`, inside the existing `describe('buildVolumeGridSqlTimeOfDay')` block (after line 205):

```typescript
  it('emits pkg_family CASE and per-family FILTER columns in current_agg', () => {
    const built = buildVolumeGridSqlTimeOfDay({
      metric: 'dv01', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'all', bounds,
    })
    expect(built.sql).toContain("THEN 'outright'")
    expect(built.sql).toContain("THEN 'curve'")
    expect(built.sql).toContain("THEN 'fly'")
    expect(built.sql).toContain("ELSE 'other'")
    expect(built.sql).toContain("FILTER (WHERE pkg_family = 'outright')")
    expect(built.sql).toContain('outright_current')
    expect(built.sql).toContain('curve_current')
    expect(built.sql).toContain('fly_current')
    expect(built.sql).toContain('other_current')
  })
```

Add inside `describe('buildVolumeGridSqlRolling')` (after line 222):

```typescript
  it('emits pkg_family FILTER columns in rolling SQL', () => {
    const built = buildVolumeGridSqlRolling({
      metric: 'dv01', forwardSchema: fwd, tenorSchema: tenor,
      packageType: 'all', bounds,
    })
    expect(built.sql).toContain("FILTER (WHERE pkg_family = 'outright')")
    expect(built.sql).toContain('outright_current')
    expect(built.sql).toContain('curve_current')
    expect(built.sql).toContain('fly_current')
    expect(built.sql).toContain('other_current')
  })
```

- [ ] **Step 2: Write failing test for shapeVolumeGridResponse with family columns**

Add inside `describe('shapeVolumeGridResponse')` (after line 341):

```typescript
  it('maps pkg_family composition columns to cell fields', () => {
    const fwd = resolveForwardSchema('default')
    const tenor = resolveTenorSchema('default')
    const out = shapeVolumeGridResponse(
      [
        {
          fwd: 'spot', tenor: '5y',
          current_value: 175, idb_current: 100, custy_current: 75,
          outright_current: 100, curve_current: 50, fly_current: 25, other_current: 0,
          trade_count: 10, prior_array: [], p25: 0, p50: 0, p75: 0, pmin: 0, pmax: 0, n: 0,
          as_of_ts: null,
        },
      ],
      {
        metric: 'dv01', period: '1w', lookbackDays: 90,
        forwardSchema: 'default', tenorSchema: 'default', packageType: 'all',
        viewMode: 'volume',
      },
      fwd,
      tenor,
    )
    expect(out.cells.length).toBe(1)
    expect(out.cells[0].outrightCurrent).toBe(100)
    expect(out.cells[0].curveCurrent).toBe(50)
    expect(out.cells[0].flyCurrent).toBe(25)
    expect(out.cells[0].otherCurrent).toBe(0)
  })
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage
```

Expected: FAIL — SQL does not contain pkg_family, and `RawVolumeGridRow` lacks the new fields.

- [ ] **Step 4: Add pkg_family to `buildVolumeGridSqlTimeOfDay`**

In `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts`:

Add import at line 16 (extend existing import from volumeGridBuckets):

```typescript
import {
  buildBucketCaseSql,
  buildFomcBucketsFromLabels,
  buildPackageTypeFilter,
  buildPkgFamilySql,           // <-- ADD
  buildVenueBucketsFromIdentifiers,
  // ... rest unchanged
} from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
```

In `buildVolumeGridSqlTimeOfDay` (line 339), modify the `legs` CTE SELECT. After the `${PLATFORM_CASE_SQL} AS platform,` line (line 363), add:

```typescript
        ${buildPkgFamilySql('p')} AS pkg_family,
```

In the `current_agg` CTE (line 402), after the `custy_current` FILTER line (line 406), add 4 new lines:

```typescript
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
```

In the final SELECT (after line 419, after `custy_current`), add:

```typescript
      COALESCE(c.outright_current, 0)          AS outright_current,
      COALESCE(c.curve_current, 0)             AS curve_current,
      COALESCE(c.fly_current, 0)               AS fly_current,
      COALESCE(c.other_current, 0)             AS other_current,
```

- [ ] **Step 5: Add pkg_family to `buildVolumeGridSqlRolling`**

Same pattern in `buildVolumeGridSqlRolling` (line 437):

In the `legs` CTE, after `${PLATFORM_CASE_SQL} AS platform` (line 459), add:

```typescript
        ${buildPkgFamilySql('p')} AS pkg_family
```

In `current_agg`, after custy_current FILTER (line 506), add the same 4 lines:

```typescript
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'outright') AS outright_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'curve')    AS curve_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'fly')      AS fly_current,
        SUM(${metricCol}) FILTER (WHERE pkg_family = 'other')    AS other_current,
```

In the final SELECT, after custy_current (line 519), add:

```typescript
      COALESCE(c.outright_current, 0)          AS outright_current,
      COALESCE(c.curve_current, 0)             AS curve_current,
      COALESCE(c.fly_current, 0)               AS fly_current,
      COALESCE(c.other_current, 0)             AS other_current,
```

- [ ] **Step 6: Extend `RawVolumeGridRow` and `shapeVolumeGridResponse`**

In `RawVolumeGridRow` (line 573), add after `custy_current` (line 578):

```typescript
  outright_current: number | string
  curve_current: number | string
  fly_current: number | string
  other_current: number | string
```

In `shapeVolumeGridResponse` (line 627), in the cell mapping `.map((r) => {`, after line 638 (`custyCurrent: num(r.custy_current),`), add:

```typescript
        outrightCurrent: num(r.outright_current),
        curveCurrent: num(r.curve_current),
        flyCurrent: num(r.fly_current),
        otherCurrent: num(r.other_current),
```

- [ ] **Step 7: Fix the empty-cell fallback in VolumeGrid.tsx**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx`, line 134-141, the fallback cell literal needs the new fields. After `custyCurrent: 0,` (line 137), add:

```typescript
            outrightCurrent: 0, curveCurrent: 0, flyCurrent: 0, otherCurrent: 0,
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage
```

Expected: All tests PASS (both new and existing).

- [ ] **Step 9: Verify existing shapeVolumeGridResponse tests still pass**

The existing test at line 266 passes raw rows without the new fields. Since `num(undefined)` returns 0 via the `Number(undefined) → NaN → !isFinite → 0` path, existing tests should pass. Verify:

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/__tests__/route.logic" --no-coverage -t "shapeVolumeGridResponse"
```

Expected: PASS — all existing tests green.

- [ ] **Step 10: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/__tests__/route.logic.test.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx
git commit -m "feat(volume-grid): add pkg_family composition columns to main grid SQL and response"
```

---

## Task 4: Cell Drill-Down — Leg-Annotated Recent Trades (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts:322-355`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts:43-157`
- Test: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`

- [ ] **Step 1: Write failing test for `buildRecentTradesSql` with legs subquery**

Add to `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts`:

```typescript
describe('buildRecentTradesSql with legs', () => {
  it('includes a json_agg legs subquery when inCellPredicateSql is provided', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'l.tenor_years >= $2 AND l.tenor_years < $3',
      packageFilterSql: 'TRUE',
      limitParam: '$4',
      inCellPredicateSql: 'l2.tenor_years >= $2 AND l2.tenor_years < $3',
    })
    expect(sql).toContain('json_agg')
    expect(sql).toContain('json_build_object')
    expect(sql).toContain('l2.tenor_years')
    expect(sql).toContain('l2.forward_start_years')
    expect(sql).toContain('in_cell')
    expect(sql).toContain('l2.package_id = p.package_id')
  })

  it('omits legs subquery when inCellPredicateSql is not provided', () => {
    const sql = buildRecentTradesSql({
      bucketPredicateSql: 'l.tenor_years >= $2',
      packageFilterSql: 'TRUE',
      limitParam: '$3',
    })
    expect(sql).not.toContain('json_agg')
    expect(sql).not.toContain('l2.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/cell/__tests__/route.logic" --no-coverage
```

Expected: FAIL — `inCellPredicateSql` is not a recognized option.

- [ ] **Step 3: Enhance `buildRecentTradesSql`**

In `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts`, replace the `buildRecentTradesSql` function (lines 322-355) with:

```typescript
export function buildRecentTradesSql(opts: {
  bucketPredicateSql: string
  packageFilterSql: string
  schemaExtraFilterSql?: string
  limitParam: string
  inCellPredicateSql?: string
}): string {
  const extraFilter = opts.schemaExtraFilterSql ? `AND ${opts.schemaExtraFilterSql}` : ''
  const legsSubquery = opts.inCellPredicateSql
    ? `,
      (
        SELECT json_agg(json_build_object(
          'tenor_years', l2.tenor_years,
          'forward_start_years', l2.forward_start_years,
          'notional', ABS(COALESCE(l2.notional, 0)),
          'risk', ABS(COALESCE(l2.risk, 0)),
          'in_cell', CASE WHEN (${opts.inCellPredicateSql}) THEN true ELSE false END
        ) ORDER BY l2.tenor_years)
        FROM arbs_usd_swap_tape_legs_v2 l2
        WHERE l2.package_id = p.package_id
          AND COALESCE(l2.contributes_to_flow, FALSE) = TRUE
      ) AS legs`
    : ''
  return `
    WITH eligible_packages AS (
      SELECT DISTINCT l.package_id
      FROM arbs_usd_swap_tape_legs_v2 l
      JOIN arbs_usd_swap_tape_packages_v2 p ON p.package_id = l.package_id
      WHERE COALESCE(l.contributes_to_flow, FALSE) = TRUE
        AND COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
        AND ${opts.bucketPredicateSql}
        AND ${opts.packageFilterSql}
        ${extraFilter}
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
      p.is_block_any${legsSubquery}
    FROM arbs_usd_swap_tape_packages_v2 p
    JOIN eligible_packages e ON e.package_id = p.package_id
    ORDER BY p.execution_start DESC
    LIMIT ${opts.limitParam}
  `
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/cell/__tests__/route.logic" --no-coverage
```

Expected: All PASS (new and existing).

- [ ] **Step 5: Thread `inCellPredicateSql` in the route handler**

In `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts`, modify the `buildRecentTradesSql` call (lines 67-72).

First, build a second bucket predicate with alias `l2` but the same parameter indices. Add after line 56 (`)`):

```typescript
  const inCellPredicate = buildBucketPredicate('l2', forwardSchema, tenorSchema, p.fwd, p.tenor, 2)
```

Then update the `buildRecentTradesSql` call to include `inCellPredicateSql`:

```typescript
  const tradesSql = buildRecentTradesSql({
    bucketPredicateSql: predicate.sql,
    packageFilterSql: pkgFilter.sql,
    schemaExtraFilterSql: combinedExtra || undefined,
    limitParam: `$${limitParamIndex}`,
    inCellPredicateSql: inCellPredicate.sql,
  })
```

- [ ] **Step 6: Map legs in the response**

In the same file, modify the `recentTrades` mapping (lines 123-135). Replace with:

```typescript
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
      legs: Array.isArray(r.legs)
        ? (r.legs as Array<Record<string, unknown>>).map((leg) => ({
            tenorYears: num(leg.tenor_years),
            forwardStartYears: num(leg.forward_start_years),
            notional: num(leg.notional),
            risk: num(leg.risk),
            inCell: leg.in_cell === true,
          }))
        : null,
    }))
```

- [ ] **Step 7: Run all cell route tests**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="volume-grid/cell" --no-coverage
```

Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/route.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/volume-grid/cell/__tests__/route.logic.test.ts
git commit -m "feat(volume-grid): add leg-annotated recent trades to cell drill-down"
```

---

## Task 5: VolumeGridCell — Mini Stacked Bar (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx:26-136`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx:13-22,66-84,107-122`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx:310-319`
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCell.test.tsx`

- [ ] **Step 1: Write failing tests for stacked bar**

Add to `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCell.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { VolumeGridCell } from '../VolumeGridCell'
import type { VolumeGridCell as Cell } from '../../../types/volume-grid.types'

const makeCell = (overrides: Partial<Cell> = {}): Cell => ({
  fwd: 'spot', tenor: '5y', current: 100, idbCurrent: 60, custyCurrent: 40,
  tradeCount: 5,
  baseline: { p25: 50, p50: 75, p75: 90, min: 10, max: 120, n: 20 },
  percentile: 60,
  outrightCurrent: 60, curveCurrent: 30, flyCurrent: 10, otherCurrent: 0,
  ...overrides,
})

describe('VolumeGridCell — pkg family stacked bar', () => {
  it('renders stacked bar when packageType=all and tradeCount > 0', () => {
    const { container } = render(
      <VolumeGridCell
        cell={makeCell()}
        metric="dv01" period="1w" viewMode="volume" packageType="all"
        onClick={() => {}}
      />,
    )
    const bar = container.querySelector('[data-testid="pkg-family-bar"]')
    expect(bar).not.toBeNull()
  })

  it('does not render stacked bar when packageType is not all', () => {
    const { container } = render(
      <VolumeGridCell
        cell={makeCell()}
        metric="dv01" period="1w" viewMode="volume" packageType="outright"
        onClick={() => {}}
      />,
    )
    const bar = container.querySelector('[data-testid="pkg-family-bar"]')
    expect(bar).toBeNull()
  })

  it('does not render stacked bar when tradeCount is 0', () => {
    const { container } = render(
      <VolumeGridCell
        cell={makeCell({ tradeCount: 0 })}
        metric="dv01" period="1w" viewMode="volume" packageType="all"
        onClick={() => {}}
      />,
    )
    const bar = container.querySelector('[data-testid="pkg-family-bar"]')
    expect(bar).toBeNull()
  })

  it('renders correct segment widths based on family proportions', () => {
    const { container } = render(
      <VolumeGridCell
        cell={makeCell({ current: 100, outrightCurrent: 50, curveCurrent: 30, flyCurrent: 20, otherCurrent: 0 })}
        metric="dv01" period="1w" viewMode="volume" packageType="all"
        onClick={() => {}}
      />,
    )
    const bar = container.querySelector('[data-testid="pkg-family-bar"]')
    const segments = bar?.children
    expect(segments?.length).toBeGreaterThanOrEqual(3)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGridCell.test" --no-coverage
```

Expected: FAIL — `packageType` is not a valid prop.

- [ ] **Step 3: Add `packageType` prop to VolumeGridCellProps**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx`, add to the imports (line 12):

```typescript
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
```

Add to `VolumeGridCellProps` (after line 35, before `onClick`):

```typescript
  packageType?: PackageTypeGroupId
```

Update the destructuring at line 59:

```typescript
export const VolumeGridCell = memo(function VolumeGridCell({
  cell, metric, period, viewMode, colorMode = 'activity', colorPercentile, forwardAxis, tenorAxis, packageType, onClick,
}: VolumeGridCellProps): JSX.Element {
```

- [ ] **Step 4: Add the stacked bar rendering**

In the same file, add these computed values after `const custyPct` (line 72):

```typescript
  const showPkgBar = packageType === 'all' && !isEmpty
  const outrightShare = safeShare(cell.outrightCurrent, cell.current)
  const curveShare = safeShare(cell.curveCurrent, cell.current)
  const flyShare = safeShare(cell.flyCurrent, cell.current)
  const otherShare = safeShare(cell.otherCurrent, cell.current)
```

Add the bar JSX inside the `<button>`, right after the IDB/CUSTY split bar div (after line 110, before the `{isEmpty ? (` check):

```tsx
      {showPkgBar && (
        <div
          data-testid="pkg-family-bar"
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 flex h-1"
          title={`Outright: ${fmtCompact(cell.outrightCurrent, metric)} | Curve: ${fmtCompact(cell.curveCurrent, metric)} | Fly: ${fmtCompact(cell.flyCurrent, metric)}${cell.otherCurrent > 0 ? ` | Other: ${fmtCompact(cell.otherCurrent, metric)}` : ''}`}
        >
          {outrightShare > 0 && <div className="bg-slate-400/80" style={{ width: `${outrightShare * 100}%` }} />}
          {curveShare > 0 && <div className="bg-amber-400/80" style={{ width: `${curveShare * 100}%` }} />}
          {flyShare > 0 && <div className="bg-emerald-400/80" style={{ width: `${flyShare * 100}%` }} />}
          {otherShare > 0 && <div className="bg-purple-400/80" style={{ width: `${otherShare * 100}%` }} />}
        </div>
      )}
```

- [ ] **Step 5: Thread `packageType` through VolumeGrid and VolumeGridCard**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx`:

Add import:
```typescript
import type { PackageTypeGroupId } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'
```

Add to `VolumeGridProps` (line 13, after `colorMode`):
```typescript
  packageType?: PackageTypeGroupId
```

Update the destructuring at line 24:
```typescript
export function VolumeGrid({ data, metric, period, viewMode, colorMode, packageType, onCellClick, onCellHover, onCellLeave }: VolumeGridProps): JSX.Element {
```

Add `packageType` to `RowFragment` props pass-through (inside the `forwardAxis.buckets.map`, after line 78):
```typescript
            packageType={packageType}
```

Add `packageType` to `RowFragment` prop type (line 107, after `colorMode`):
```typescript
  packageType?: PackageTypeGroupId
```

Pass it to `VolumeGridCell` (line 149, after `tenorAxis`):
```typescript
              packageType={props.packageType}
```

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx`, add `packageType` to the `VolumeGrid` call (line 310, after `colorMode={colorMode}`):
```typescript
              packageType={packageType}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGridCell.test" --no-coverage
```

Expected: All PASS.

- [ ] **Step 7: Run all VolumeGrid tests to check for regressions**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGrid" --no-coverage
```

Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCell.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGrid.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCard.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCell.test.tsx
git commit -m "feat(volume-grid): add pkg-family stacked bar to VolumeGridCell for 'All' view"
```

---

## Task 6: VolumeGridCellModal — Enhanced Recent Trades (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx:152-185`
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx`

- [ ] **Step 1: Write failing tests for enhanced recent trades table**

Add to `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx`:

```typescript
describe('VolumeGridCellModal — leg-annotated recent trades (source contract)', () => {
  const src = readFileSync(
    resolve(__dirname, '../VolumeGridCellModal.tsx'),
    'utf-8',
  )

  it('renders expand chevron for multi-leg trades', () => {
    expect(src).toContain('data-testid="leg-expand"')
  })

  it('renders leg sub-rows with inCell badge', () => {
    expect(src).toContain('data-testid="leg-row"')
    expect(src).toContain('inCell')
  })

  it('renders cell contribution column', () => {
    expect(src).toContain('data-testid="cell-contribution"')
  })

  it('renders package type badge', () => {
    expect(src).toContain('data-testid="pkg-type-badge"')
  })

  it('shows "all package types" subtitle when packageType is all', () => {
    expect(src).toContain('Includes all package types')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGridCellModal.test" --no-coverage
```

Expected: FAIL — source does not contain the new test-ids.

- [ ] **Step 3: Add package type badge colors**

In `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx`, add after the `fmtTime` helper (after line 43):

```typescript
const PKG_BADGE_COLORS: Record<string, string> = {
  OUTRIGHT: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  SPREADOVER: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  MATCHED_MATURITY: 'bg-slate-500/20 text-slate-300 ring-slate-500/30',
  CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  SPREADOVER_CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  MATCHED_MATURITY_CURVE: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  SPREADOVER_FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  MATCHED_MATURITY_FLY: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
}
const pkgBadgeClass = (pt: string | null): string =>
  PKG_BADGE_COLORS[pt ?? ''] ?? 'bg-purple-500/20 text-purple-300 ring-purple-500/30'
```

- [ ] **Step 4: Add chart subtitle for 'All'**

In the component body, add a subtitle below the timeseries chart header. Before the `<div className="grid min-h-[230px]` line (line 112), add:

```tsx
        {props.packageType === 'all' && (
          <div className="font-mono text-[9.5px] text-slate-500">
            Includes all package types (outright, curve, fly, etc.)
          </div>
        )}
```

- [ ] **Step 5: Add expandable leg rows state**

Inside the `VolumeGridCellModal` function, after the `range` state (line 75), add:

```typescript
  const [expandedPkgs, setExpandedPkgs] = useState<Set<string>>(new Set())
  const toggleExpand = (pkgId: string) => {
    setExpandedPkgs((prev) => {
      const next = new Set(prev)
      if (next.has(pkgId)) next.delete(pkgId)
      else next.add(pkgId)
      return next
    })
  }
```

- [ ] **Step 6: Replace the recent trades table body**

Replace the table header and body (lines 154-184) with the enhanced version:

```tsx
          <table className="w-full text-left font-mono text-[11px]">
            <thead className="sticky top-0 bg-slate-900/80 text-[9.5px] uppercase tracking-wider text-slate-500">
              <tr>
                <Th> </Th><Th>Time</Th><Th>Type</Th><Th>Tape</Th><Th>Rate</Th>
                <Th>Risk</Th><Th>Notional</Th><Th data-testid="cell-contribution">Cell</Th><Th>Venue</Th><Th>Block?</Th>
              </tr>
            </thead>
            <tbody>
              {data?.recentTrades.length ? data.recentTrades.map((t) => {
                const legs = t.legs ?? []
                const isMultiLeg = legs.length > 1
                const isExpanded = expandedPkgs.has(t.package_id)
                const inCellRisk = legs.filter((l) => l.inCell).reduce((s, l) => s + l.risk, 0)
                const inCellNotional = legs.filter((l) => l.inCell).reduce((s, l) => s + l.notional, 0)
                return (
                  <>
                    <tr
                      key={t.package_id}
                      className="cursor-pointer border-t border-slate-800/60 hover:bg-indigo-500/10"
                      onClick={() => {
                        props.onSelectPackage(t.package_id)
                        props.onClose()
                      }}
                    >
                      <Td>
                        {isMultiLeg && (
                          <button
                            type="button"
                            data-testid="leg-expand"
                            className="text-slate-500 hover:text-slate-300"
                            onClick={(e) => { e.stopPropagation(); toggleExpand(t.package_id) }}
                          >
                            {isExpanded ? '▾' : '▸'}
                          </button>
                        )}
                      </Td>
                      <Td>{fmtTime(t.execution_start)}</Td>
                      <Td>
                        <span data-testid="pkg-type-badge" className={`rounded px-1 py-0.5 text-[9.5px] ring-1 ${pkgBadgeClass(t.package_type)}`}>
                          {t.package_type ?? '-'}
                        </span>
                      </Td>
                      <Td>{t.tape_label ?? '-'}</Td>
                      <Td>{fmtRate(t.weighted_fixed_rate)}</Td>
                      <Td>{t.total_risk == null ? '-' : fmtCompact(t.total_risk, 'dv01')}</Td>
                      <Td>{t.total_notional == null ? '-' : fmtCompact(t.total_notional, 'notional')}</Td>
                      <Td>
                        {legs.length > 0
                          ? `${fmtCompact(props.metric === 'dv01' ? inCellRisk : inCellNotional, props.metric)} / ${fmtCompact(props.metric === 'dv01' ? (t.total_risk ?? 0) : (t.total_notional ?? 0), props.metric)}`
                          : '-'}
                      </Td>
                      <Td>{t.venue ?? '-'}</Td>
                      <Td>{t.is_block_any ? 'BLOCK' : ''}</Td>
                    </tr>
                    {isMultiLeg && isExpanded && legs.map((leg, i) => (
                      <tr key={`${t.package_id}-leg-${i}`} data-testid="leg-row" className="border-t border-slate-800/30 bg-slate-900/40 text-[10px] text-slate-400">
                        <Td> </Td>
                        <Td> </Td>
                        <Td> </Td>
                        <Td>{`${leg.tenorYears}Y fwd ${leg.forwardStartYears.toFixed(2)}y`}</Td>
                        <Td> </Td>
                        <Td>{fmtCompact(leg.risk, 'dv01')}</Td>
                        <Td>{fmtCompact(leg.notional, 'notional')}</Td>
                        <Td>
                          <span className={leg.inCell ? 'text-emerald-400' : 'text-slate-600'}>
                            {leg.inCell ? '●' : '○'}
                          </span>
                        </Td>
                        <Td> </Td>
                        <Td> </Td>
                      </tr>
                    ))}
                  </>
                )
              }) : (
                <tr><td className="p-2 text-slate-500" colSpan={10}>No recent trades for this bucket.</td></tr>
              )}
            </tbody>
          </table>
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGridCellModal.test" --no-coverage
```

Expected: All PASS.

- [ ] **Step 8: Run the full VolumeGrid test suite for regressions**

```bash
cd SDRUtils/dashboard && npx jest --testPathPattern="VolumeGrid" --no-coverage
```

Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/VolumeGridCellModal.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/VolumeGrid/__tests__/VolumeGridCellModal.test.tsx
git commit -m "feat(volume-grid): add expandable leg rows and pkg badges to cell modal"
```

---

## Task 7: Chrome MCP E2E Verification (Merge Gate)

**Files:** None (manual browser verification)

This is the final verification step. **Do not merge without completing this.**

- [ ] **Step 1: Start the dev server**

```bash
cd SDRUtils/dashboard && npm run dev
```

- [ ] **Step 2: Open the USD swaps tape v2 page in Chrome MCP**

Navigate to `http://localhost:3000/usd-swaps-tape-v2` (or the appropriate route).

- [ ] **Step 3: Select packageType = 'All' in the volume grid dropdown**

Change the package type dropdown from "Outright" to "All". Verify the grid renders with non-zero cell values.

- [ ] **Step 4: Verify stacked bars appear**

Inspect cells visually. Cells with mixed package type contributions should show a thin colored bar at the top edge. Hover over a bar to verify the tooltip shows "Outright: Xk | Curve: Yk | Fly: Zk" breakdown.

- [ ] **Step 5: Click a cell to open the modal**

Click a cell that should contain curve/fly contributions. Verify:
- Volume detail timeseries chart loads
- Intraday seasonality chart loads
- "Includes all package types" subtitle appears below chart titles
- Recent trades table renders

- [ ] **Step 6: Verify enhanced recent trades table**

In the modal's recent trades table:
- FLY/CURVE packages should show expand chevrons (▸)
- Package type badges should be color-coded (amber for CURVE, green for FLY)
- "Cell" column should show cell contribution vs total (e.g., "25k / 50k")
- Click the expand chevron to reveal leg sub-rows
- Leg sub-rows should show tenor, forward, risk, notional
- `inCell` badge: green dot (●) for legs in this cell, hollow (○) for legs outside

- [ ] **Step 7: Cross-check with outright-only view**

Switch back to `packageType='Outright'`. Verify:
- Stacked bars disappear
- Cell values decrease (curve/fly legs removed)
- Modal no longer shows "Includes all package types" subtitle

- [ ] **Step 8: Verify the specific FLY test case**

Find a 5Y/10Y/30Y FLY trade in the grid:
- Select `forwardSchema=imm16` to see IMM forward buckets
- The FLY's 3 legs should appear in 3 different tenor columns within the same forward row
- Body (10Y) cell should show ~2x the wing (5Y, 30Y) contribution
- Click each cell and verify the FLY package appears in recent trades with correct leg annotations

- [ ] **Step 9: Screenshot key states for PR evidence**

Capture screenshots of:
1. Grid with 'All' selected showing stacked bars
2. Cell modal with expanded FLY trade showing leg sub-rows
3. Grid with 'Outright' selected (comparison)

- [ ] **Step 10: Final commit and PR**

```bash
git push -u origin claude/admiring-lederberg-a58869
```

Create PR referencing the spec and screenshots.
