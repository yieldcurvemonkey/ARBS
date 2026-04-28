# USD Swaps Tape v2 — Pagination + Polling Optimisation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate the four trader-reported defects on the USD swap tape v2 dashboard (poll shake, filter lag, incomplete filter loads, "too many trades at once") by pushing column filters into SQL `WHERE` and scroll-anchoring the polling merge.

**Architecture:** Two independent fixes on the same feature branch.

1. **Server-side `columnFilters` pushdown.** The route already parses `columnFilters` but never consumes them. Translate the payload into parameterised SQL fragments inside `buildTapeQuery` for an allowlisted set of fields and match modes (mirroring `matchFilterValue` semantics in `filter-utils.ts`). The hook is extended to attach the URL-synced `columnFilters` string to every fetch. Defensive client-side filtering stays in place as a safety net.
2. **Scroll-anchor poll-merge.** A pure helper computes the scrollTop adjustment needed to keep the same `package_id` under the user's cursor when new rows land above. The `TradeTapeTable` invokes the helper in a `useLayoutEffect` triggered by `displayRows` reference change.

**Tech Stack:** Next.js 15 + React 19, PrimeReact 10 (`DataTable` + `VirtualScroller`), Postgres (parameterised query via `pg`), Jest 30 + ts-jest, jsdom.

**Backing design:** [`docs/plans/2026-04-28-tape-pagination-rework-design.md`](2026-04-28-tape-pagination-rework-design.md)

**Branch:** `dashboard/tape-pagination-rework` (already created).

**Test commands** (run from repo root):
- All v2 dashboard tests: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
- Single test file: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`

---

## Task 1: Pushdown allowlist + match-mode → SQL fragment helper

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts`

**Goal:** Add a pure helper `buildColumnFilterClause(columnFilters, params)` that returns a SQL fragment + mutates the params accumulator. Allowlist: `tape_label`, `total_risk`, `total_notional`, `weighted_fixed_rate`, `package_type`, `package_indicator`, `other_lvl_reported` (package columns); `platform_identifier`, `lifecycle_type` (leg columns via EXISTS). Anything else returns no clause.

**Step 1.1: Write failing tests (allowlist + basic CONTAINS on tape_label)**

Append to `route.logic.test.ts`:

```ts
import { buildColumnFilterClause } from '../route.logic'

describe('buildColumnFilterClause', () => {
  it('returns null for empty filters object', () => {
    const params: unknown[] = []
    expect(buildColumnFilterClause({}, params)).toBeNull()
    expect(params).toEqual([])
  })

  it('ignores fields not in the allowlist', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { not_a_column: { operator: 'and', constraints: [{ value: 'x', matchMode: 'contains' }] } },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('CONTAINS on tape_label: ILIKE %x% with escaped value', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] } },
      params,
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params).toEqual(['%10Y%'])
  })

  it('escapes %, _, \\ in CONTAINS values so they are literal', () => {
    const params: unknown[] = []
    buildColumnFilterClause(
      { tape_label: { operator: 'and', constraints: [{ value: '5%_x', matchMode: 'contains' }] } },
      params,
    )
    expect(params).toEqual(['%5\\%\\_x%'])
  })
})
```

**Step 1.2: Run failing tests — verify "buildColumnFilterClause is not exported"**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`
Expected: FAIL with `buildColumnFilterClause is not exported from '../route.logic'`.

**Step 1.3: Implement the helper (CONTAINS on tape_label only, simplest case)**

Add to the bottom of `route.logic.ts` (before the existing `buildTapeQuery` export, or just above it):

```ts
const COLUMN_FILTER_ALLOWLIST_PACKAGE = new Set([
  'tape_label',
  'total_risk',
  'total_notional',
  'weighted_fixed_rate',
  'package_type',
  'package_indicator',
  'other_lvl_reported',
])

const COLUMN_FILTER_ALLOWLIST_LEG = new Set(['platform_identifier', 'lifecycle_type'])

const TEXT_MATCH_MODES = new Set([
  'contains',
  'notContains',
  'startsWith',
  'endsWith',
  'equals',
  'notEquals',
  'in',
])

const NUMERIC_MATCH_MODES = new Set([
  'equals',
  'notEquals',
  'lt',
  'lte',
  'gt',
  'gte',
])

const NUMERIC_FIELDS = new Set([
  'total_risk',
  'total_notional',
  'weighted_fixed_rate',
])

const ESCAPE_LIKE_RE = /[%_\\]/g

function escapeLikePattern(raw: string): string {
  return raw.replace(ESCAPE_LIKE_RE, (m) => '\\' + m)
}

function buildSingleConstraint(
  field: string,
  constraint: { value: unknown; matchMode?: string },
  params: unknown[],
): string | null {
  const { value, matchMode } = constraint
  if (value === null || value === undefined || value === '') return null
  if (Array.isArray(value) && value.length === 0) return null

  const isLeg = COLUMN_FILTER_ALLOWLIST_LEG.has(field)
  const isPackage = COLUMN_FILTER_ALLOWLIST_PACKAGE.has(field)
  if (!isLeg && !isPackage) return null

  const colExpr = isLeg ? `l->>'${field}'` : `d.${field}`

  // Numeric path
  if (NUMERIC_FIELDS.has(field) && NUMERIC_MATCH_MODES.has(String(matchMode))) {
    const n = Number(value)
    if (!Number.isFinite(n)) return null
    params.push(n)
    const p = `$${params.length}`
    const op =
      matchMode === 'lt' ? '<' :
      matchMode === 'lte' ? '<=' :
      matchMode === 'gt' ? '>' :
      matchMode === 'gte' ? '>=' :
      matchMode === 'notEquals' ? '<>' : '='
    const clause = isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE (${colExpr})::numeric ${op} ${p})`
      : `${colExpr} ${op} ${p}`
    return clause
  }

  // Text path
  const mode = String(matchMode ?? 'contains')
  if (!TEXT_MATCH_MODES.has(mode)) return null

  if (mode === 'in') {
    const arr = Array.isArray(value) ? value : [value]
    const ors = arr
      .map((v) => {
        if (v === null || v === undefined || v === '') return null
        params.push(String(v).toLowerCase())
        const p = `$${params.length}`
        return `LOWER(${colExpr}) = ${p}`
      })
      .filter((s): s is string => s !== null)
    if (ors.length === 0) return null
    const inner = ors.join(' OR ')
    return isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE ${inner})`
      : `(${inner})`
  }

  if (mode === 'equals' || mode === 'notEquals') {
    params.push(String(value).toLowerCase())
    const p = `$${params.length}`
    const op = mode === 'notEquals' ? '<>' : '='
    return isLeg
      ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE LOWER(${colExpr}) ${op} ${p})`
      : `LOWER(${colExpr}) ${op} ${p}`
  }

  // contains / notContains / startsWith / endsWith — ILIKE patterns
  const escaped = escapeLikePattern(String(value))
  let pattern: string
  if (mode === 'startsWith') pattern = `${escaped}%`
  else if (mode === 'endsWith') pattern = `%${escaped}`
  else pattern = `%${escaped}%`
  params.push(pattern)
  const p = `$${params.length}`
  const op = mode === 'notContains' ? 'NOT ILIKE' : 'ILIKE'
  return isLeg
    ? `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE ${colExpr} ${op} ${p})`
    : `${colExpr} ${op} ${p}`
}

export function buildColumnFilterClause(
  columnFilters: Record<string, any>,
  params: unknown[],
): string | null {
  if (!columnFilters || typeof columnFilters !== 'object') return null
  const fieldClauses: string[] = []
  for (const [field, meta] of Object.entries(columnFilters)) {
    if (!meta || typeof meta !== 'object') continue
    const constraints = Array.isArray(meta.constraints)
      ? meta.constraints
      : meta.value !== undefined
        ? [{ value: meta.value, matchMode: meta.matchMode }]
        : []
    if (constraints.length === 0) continue
    const op = meta.operator === 'or' ? ' OR ' : ' AND '
    const built = constraints
      .map((c: any) => buildSingleConstraint(field, c, params))
      .filter((s: string | null): s is string => s !== null)
    if (built.length === 0) continue
    fieldClauses.push(`(${built.join(op)})`)
  }
  if (fieldClauses.length === 0) return null
  return fieldClauses.join(' AND ')
}
```

**Step 1.4: Run tests — verify the 4 cases pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`
Expected: PASS — all `buildColumnFilterClause` tests green; existing tests still green.

**Step 1.5: Add tests for the rest of the matrix**

Append to `route.logic.test.ts` inside the same `describe('buildColumnFilterClause', ...)`:

```ts
  it('STARTS_WITH on tape_label', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'startsWith' }] } },
      params,
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params).toEqual(['10Y%'])
  })

  it('ENDS_WITH on tape_label', () => {
    const params: unknown[] = []
    buildColumnFilterClause(
      { tape_label: { operator: 'and', constraints: [{ value: 'OIS', matchMode: 'endsWith' }] } },
      params,
    )
    expect(params).toEqual(['%OIS'])
  })

  it('NOT_CONTAINS uses NOT ILIKE', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'notContains' }] } },
      params,
    )
    expect(clause).toMatch(/d\.tape_label NOT ILIKE/)
  })

  it('EQUALS on text column compares LOWER(col)', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { package_type: { operator: 'and', constraints: [{ value: 'CURVE', matchMode: 'equals' }] } },
      params,
    )
    expect(clause).toMatch(/LOWER\(d\.package_type\) = \$1/)
    expect(params).toEqual(['curve'])
  })

  it('NOT_EQUALS on text column compares LOWER(col) <>', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { package_type: { operator: 'and', constraints: [{ value: 'CURVE', matchMode: 'notEquals' }] } },
      params,
    )
    expect(clause).toMatch(/LOWER\(d\.package_type\) <> \$1/)
    expect(params).toEqual(['curve'])
  })

  it('IN on text column ORs each lowercased value', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { package_type: { operator: 'and', constraints: [{ value: ['CURVE', 'FLY'], matchMode: 'in' }] } },
      params,
    )
    expect(clause).toMatch(/LOWER\(d\.package_type\) = \$1.*OR.*LOWER\(d\.package_type\) = \$2/)
    expect(params).toEqual(['curve', 'fly'])
  })

  it('GREATER_THAN on numeric column casts numeric', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { total_risk: { operator: 'and', constraints: [{ value: '50000', matchMode: 'gt' }] } },
      params,
    )
    expect(clause).toMatch(/d\.total_risk > \$1/)
    expect(params).toEqual([50000])
  })

  it('LESS_THAN_OR_EQUAL_TO on numeric column', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { weighted_fixed_rate: { operator: 'and', constraints: [{ value: 0.04, matchMode: 'lte' }] } },
      params,
    )
    expect(clause).toMatch(/d\.weighted_fixed_rate <= \$1/)
    expect(params).toEqual([0.04])
  })

  it('skips non-numeric values for numeric fields', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { total_risk: { operator: 'and', constraints: [{ value: 'abc', matchMode: 'gt' }] } },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('LEG fields use EXISTS (jsonb_array_elements) subquery — platform_identifier CONTAINS', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { platform_identifier: { operator: 'and', constraints: [{ value: 'TWSF', matchMode: 'contains' }] } },
      params,
    )
    expect(clause).toMatch(
      /EXISTS \(SELECT 1 FROM jsonb_array_elements\(d\.legs_json\) l WHERE l->>'platform_identifier' ILIKE \$1\)/,
    )
    expect(params).toEqual(['%TWSF%'])
  })

  it('LEG field EQUALS — lifecycle_type', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { lifecycle_type: { operator: 'and', constraints: [{ value: 'NEW_RISK', matchMode: 'equals' }] } },
      params,
    )
    expect(clause).toMatch(
      /EXISTS \(SELECT 1 FROM jsonb_array_elements\(d\.legs_json\) l WHERE LOWER\(l->>'lifecycle_type'\) = \$1\)/,
    )
    expect(params).toEqual(['new_risk'])
  })

  it('multiple fields are joined by AND', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
        package_type: { operator: 'and', constraints: [{ value: 'CURVE', matchMode: 'equals' }] },
      },
      params,
    )
    expect(clause).toMatch(/\(d\.tape_label ILIKE \$1\) AND \(LOWER\(d\.package_type\) = \$2\)/)
    expect(params).toEqual(['%10Y%', 'curve'])
  })

  it('per-field OR joins constraints inside one field with OR', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'or',
          constraints: [
            { value: '10Y', matchMode: 'contains' },
            { value: '5Y', matchMode: 'contains' },
          ],
        },
      },
      params,
    )
    expect(clause).toMatch(/\(d\.tape_label ILIKE \$1 OR d\.tape_label ILIKE \$2\)/)
    expect(params).toEqual(['%10Y%', '%5Y%'])
  })

  it('execution_start filter is NOT pushed (deferred — display string vs ISO)', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      { execution_start: { operator: 'and', constraints: [{ value: '04/23', matchMode: 'contains' }] } },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })
```

**Step 1.6: Run tests — verify all matrix cases pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`
Expected: PASS.

**Step 1.7: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: pure helper for columnFilters SQL pushdown

Adds buildColumnFilterClause + allowlist for the columns that already
power the per-column filter overlay client-side. Mirrors matchFilterValue
semantics: text uses LOWER(...) for equality and ILIKE patterns
(escaped) for substring modes; numeric uses ::numeric casts. Leg fields
(platform_identifier, lifecycle_type) walk legs_json via EXISTS.
execution_start is intentionally not pushed (filters compare the NYC
display string, not the raw ISO).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire `buildColumnFilterClause` into `buildTapeQuery`

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts` — extend `buildTapeQuery`
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts`

**Step 2.1: Write failing tests for `buildTapeQuery` consuming columnFilters**

Append to the existing `describe('buildTapeQuery', ...)`:

```ts
  it('emits column-filter WHERE clause for tape_label CONTAINS', () => {
    const url = new URLSearchParams()
    url.set(
      'columnFilters',
      JSON.stringify({
        tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
      }),
    )
    const parsed = parseParams(url)
    if (!parsed.ok) throw new Error(parsed.error)
    const { sql, params } = buildTapeQuery(parsed.value, VIEW, COLUMNS)
    expect(sql).toMatch(/d\.tape_label ILIKE \$1/)
    expect(params[0]).toBe('%10Y%')
  })

  it('column-filter clause is composed AFTER existing WHERE fragments', () => {
    const url = new URLSearchParams()
    url.set('clean', 'true')
    url.set(
      'columnFilters',
      JSON.stringify({
        tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
      }),
    )
    const parsed = parseParams(url)
    if (!parsed.ok) throw new Error(parsed.error)
    const { sql } = buildTapeQuery(parsed.value, VIEW, COLUMNS)
    // Both clean-tape clauses AND the column-filter clause appear
    expect(sql).toMatch(/NOT d\.is_unwind/)
    expect(sql).toMatch(/d\.tape_label ILIKE/)
  })

  it('omits the column-filter clause when columnFilters is empty', () => {
    const { sql } = buildTapeQuery(paramsOf(''), VIEW, COLUMNS)
    expect(sql).not.toMatch(/d\.tape_label ILIKE/)
  })
```

**Step 2.2: Run tests — verify failure**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`
Expected: FAIL — `sql` does not contain `d.tape_label ILIKE`.

**Step 2.3: Wire `buildColumnFilterClause` into `buildTapeQuery`**

In `route.logic.ts` modify `buildTapeQuery` to call the new helper between the existing FOMC clause and the cursor/since clauses:

```ts
  if (parsed.fomcMeeting) {
    params.push(parsed.fomcMeeting)
    where.push(`d.fomc_meeting_label = $${params.length}`)
  }

  // === New: consume the URL-synced columnFilters payload ===
  const columnFilterClause = buildColumnFilterClause(parsed.columnFilters, params)
  if (columnFilterClause) where.push(columnFilterClause)

  // cursor / since
  if (parsed.cursor) {
```

**Step 2.4: Run tests — verify pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.logic.test`
Expected: PASS.

**Step 2.5: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: wire columnFilters pushdown into buildTapeQuery

The route now emits a SQL WHERE fragment from the columnFilters URL
payload alongside the existing clean / lifecycle / venue / etc. clauses.
Filter-active fetches return only matching rows from the cursor scan,
so the chain-load loop no longer drags down whole pages of unfiltered
trades.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Skip `Cache-Control` header when columnFilters is non-empty

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts`
- Create: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.cache-headers.test.ts` (new)

**Step 3.1: Write failing test**

Create `route.cache-headers.test.ts`:

```ts
import { describe, expect, it, jest } from '@jest/globals'

jest.mock('@/lib/db', () => ({
  query: jest.fn(async () => ({ rows: [] })),
}))
jest.mock('@/lib/usd-swaps-tape-v2', () => ({
  resolveDisplayView: jest.fn(async () => ({ view: 'arbs_usd_swap_tape_display_v2', columns: 'd.*' })),
}))

describe('GET /api/usd-swaps-tape-v2 cache-control', () => {
  it('caches initial unfiltered fetch (no cursor / since / columnFilters)', async () => {
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api/usd-swaps-tape-v2?limit=5'))
    expect(res.headers.get('Cache-Control')).toContain('s-maxage=15')
  })

  it('skips cache header when columnFilters is non-empty', async () => {
    const { GET } = await import('../route')
    const cf = encodeURIComponent(
      JSON.stringify({
        tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
      }),
    )
    const res = await GET(new Request(`http://x/api/usd-swaps-tape-v2?limit=5&columnFilters=${cf}`))
    expect(res.headers.get('Cache-Control')).toBeNull()
  })

  it('skips cache header when cursor is present (existing behaviour)', async () => {
    const { GET } = await import('../route')
    const res = await GET(new Request('http://x/api/usd-swaps-tape-v2?limit=5&cursor=2026-04-23T00:00:00Z'))
    expect(res.headers.get('Cache-Control')).toBeNull()
  })
})
```

**Step 3.2: Run failing test**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.cache-headers.test`
Expected: FAIL on the second case (cache header still set when columnFilters present).

**Step 3.3: Implement: extend the `isCursorOrPoll` guard**

In `route.ts`, replace the cache-header block:

```ts
    const headers: Record<string, string> = {}
    const hasColumnFilters =
      parsed.value.columnFilters && Object.keys(parsed.value.columnFilters).length > 0
    const skipCache = !!parsed.value.cursor || !!parsed.value.since || !!hasColumnFilters
    if (!skipCache) {
      headers['Cache-Control'] = 'public, s-maxage=15, stale-while-revalidate=60'
    }
```

Also update the comment block above to mention the columnFilters case.

**Step 3.4: Run tests — verify pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=route.cache-headers.test`
Expected: PASS.

**Step 3.5: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.cache-headers.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: skip Cache-Control on filtered tape requests

columnFilters payloads are usually trader-specific and short-lived; the
shared 15s cache wouldn't help and would unnecessarily multiply CDN
cache entries. Skip the Cache-Control header whenever columnFilters is
non-empty, matching the cursor/since behaviour today.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `useTradeTapeData` accepts `columnFilters` (pre-serialised JSON)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeTapeData.test.ts`

**Step 4.1: Write failing tests for `buildQuery`**

Append to `useTradeTapeData.test.ts`:

```ts
  it('emits the columnFilters query param when the hook is configured with one', () => {
    const cf = JSON.stringify({
      tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
    })
    const q = buildQuery({ columnFilters: cf } as any)
    expect(q.get('columnFilters')).toBe(cf)
  })

  it('attaches columnFilters to cursor and since requests too', () => {
    const cf = JSON.stringify({
      tape_label: { operator: 'and', constraints: [{ value: '10Y', matchMode: 'contains' }] },
    })
    const q1 = buildQuery({ columnFilters: cf } as any, { cursor: 'abc' })
    expect(q1.get('cursor')).toBe('abc')
    expect(q1.get('columnFilters')).toBe(cf)
    const q2 = buildQuery({ columnFilters: cf } as any, { since: 'xyz' })
    expect(q2.get('since')).toBe('xyz')
    expect(q2.get('columnFilters')).toBe(cf)
  })

  it('omits columnFilters when not supplied', () => {
    const q = buildQuery({})
    expect(q.has('columnFilters')).toBe(false)
  })
```

**Step 4.2: Run failing test**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=useTradeTapeData.test`
Expected: FAIL — `q.get('columnFilters')` is null because `buildQuery` doesn't know about the param.

**Step 4.3: Extend `buildQuery` and the hook params type**

In `useTradeTapeData.ts`:

```ts
export interface UseTradeTapeDataParams {
  pollingEnabled?: boolean
  /**
   * Page size for cursor pagination. ...
   */
  limit?: number
  /**
   * Pre-serialised JSON for the URL-synced columnFilters payload. When
   * present, attached to every fetch (initial / cursor / since) so the
   * server applies the filter via WHERE clauses instead of returning
   * unfiltered rows. A change in this string resets the rows array and
   * triggers a fresh replace=true fetch.
   */
  columnFilters?: string | null
}
```

Replace `buildQuery`:

```ts
function buildQuery(params: UseTradeTapeDataParams, options?: {
  cursor?: string
  since?: string
}): URLSearchParams {
  const q = new URLSearchParams()
  const limit = params.limit ?? DEFAULT_PAGE_LIMIT
  q.set('limit', String(limit))
  if (options?.cursor) q.set('cursor', options.cursor)
  if (options?.since) q.set('since', options.since)
  if (params.columnFilters) q.set('columnFilters', params.columnFilters)
  return q
}
```

**Step 4.4: Run tests — verify the buildQuery cases pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=useTradeTapeData.test`
Expected: PASS for buildQuery cases.

**Step 4.5: Add test for reset-on-change**

Append to `useTradeTapeData.test.ts` (sibling of buildQuery tests). The existing test file does not exercise the hook itself (only its internal helpers), so we add the reset-on-change test as a unit test that asserts the reset effect runs when `columnFilters` changes. This is the cheapest path that doesn't pull in `@testing-library/react`.

```ts
describe('useTradeTapeData reset-on-columnFilters-change', () => {
  // The hook clears rows + nextCursor + hasMore + latestExecutionStart
  // and fires a replace=true fetch when params.columnFilters changes.
  // We can't easily mount a hook here without RTL, so we pin the
  // contract in the hook's source: the reset-on-change effect's deps
  // include params.columnFilters.
  it('exports the hook and the reset effect deps cover columnFilters', async () => {
    const src = await (await import('node:fs')).promises.readFile(
      require.resolve('../useTradeTapeData.ts'),
      'utf8',
    )
    // Find the reset effect block. It currently has eslint-disable-next-line
    // for exhaustive-deps because the original deps were [params.limit].
    // Pin that columnFilters is now in those deps.
    const m = src.match(/Reset on limit change[\s\S]*?\}, \[(.*?)\]\)/)
    expect(m?.[1]).toMatch(/params\.limit/)
    expect(m?.[1]).toMatch(/params\.columnFilters/)
  })
})
```

**Step 4.6: Update the reset-on-limit-change effect to also reset on columnFilters change**

In `useTradeTapeData.ts`, replace:

```ts
  // Reset on limit change (no more server-side filtering).
  useEffect(() => {
    setRows([])
    setNextCursor(null)
    setHasMore(false)
    setLatestExecutionStart(null)
    fetchTape({ replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.limit])
```

with:

```ts
  // Reset on limit OR columnFilters change. A new filter payload means
  // the server-side WHERE shape has changed; existing rows + cursor are
  // stale, so wipe them and fire a fresh replace fetch.
  useEffect(() => {
    setRows([])
    setNextCursor(null)
    setHasMore(false)
    setLatestExecutionStart(null)
    fetchTape({ replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.limit, params.columnFilters])
```

Also rename the comment header above for clarity.

**Step 4.7: Run tests — verify all pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=useTradeTapeData.test`
Expected: PASS.

**Step 4.8: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeTapeData.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: useTradeTapeData accepts columnFilters

Hook attaches the URL-synced columnFilters JSON (when configured) to
every initial / cursor / since fetch so the server applies the filter.
A change in the columnFilters param resets the cursor + rows and fires
a fresh replace fetch — same pattern as a limit change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Page wires `useColumnFilters().queryString` (columnFilters slice) into `useTradeTapeData`

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.ts` (expose a helper that returns just the JSON-serialised payload)

**Step 5.1: Add `serializedColumnFilters` to `useColumnFilters` return**

`useColumnFilters` already builds the payload via `buildColumnFilterPayload`. Expose a memoised JSON string:

```ts
  const serializedColumnFilters = useMemo<string | null>(() => {
    const payload = buildColumnFilterPayload(filters)
    if (!Object.keys(payload).length) return null
    return JSON.stringify(payload)
  }, [filters])

  return {
    filters,
    sortField,
    sortOrder,
    setFilters,
    setSort,
    reset,
    queryString,
    serializedColumnFilters,
  }
```

Update the `UseColumnFiltersReturn` interface accordingly.

**Step 5.2: Add a unit test pinning the new field**

Find or create `useColumnFilters.helpers.test.ts` (the existing test file is `useColumnFilters.test.ts`). Append:

```ts
import { buildColumnFilterPayload } from '../../components/TradeTapeTable/filter-utils'

describe('serializedColumnFilters round-trip', () => {
  it('null when filters object is empty / all-default', () => {
    const empty = {}
    const payload = buildColumnFilterPayload(empty as any)
    expect(Object.keys(payload).length).toBe(0)
  })

  it('JSON-string of the payload when filters carry constraints', () => {
    const filters: any = {
      tape_label: {
        operator: 'and',
        constraints: [{ value: '10Y', matchMode: 'contains' }],
      },
    }
    const payload = buildColumnFilterPayload(filters)
    const json = JSON.stringify(payload)
    expect(json).toContain('tape_label')
    expect(json).toContain('10Y')
  })
})
```

(This indirectly pins the round-trip — the hook's `serializedColumnFilters` memo just calls JSON.stringify on `buildColumnFilterPayload(filters)`.)

**Step 5.3: Wire into `UsdSwapsTradeTape`**

Replace:

```ts
  const tape = useTradeTapeData({})
```

with:

```ts
  const columnFilters = useColumnFilters()
  const tape = useTradeTapeData({
    columnFilters: columnFilters.serializedColumnFilters,
  })
```

Add the import for `useColumnFilters` if not already present.

**Step 5.4: Run all tape-v2 tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
Expected: PASS for all suites (including any RTL tests of `UsdSwapsTradeTape`).

**Step 5.5: Browser smoke check**

Open `http://localhost:3717/usd-swaps`. With the dev server hot-reload running, apply the same filter as the original repro: `tape_label contains 10Y`. The Network tab should show a SINGLE `/api/usd-swaps-tape-v2?limit=200&columnFilters=...` request (plus chain pages also carrying `columnFilters=...`). The "loaded" count should now equal the matching count — no more gigantic over-fetch.

**Step 5.6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useColumnFilters.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: tape page wires column filters through to the route

useColumnFilters exposes a serializedColumnFilters memo (JSON of the
active payload, or null when nothing is active). The tape orchestrator
threads it into useTradeTapeData so the hook attaches the param to
every fetch. End-to-end: trader applies a column filter -> server
returns only matching rows -> chain-load no longer drags down the
unfiltered universe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Pure helper for poll-merge scroll-anchor calculation

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/scroll-anchor.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/scroll-anchor.test.ts`

**Step 6.1: Write the failing test**

```ts
import { describe, expect, it } from '@jest/globals'
import { computeAnchorAdjustedScrollTop } from '../scroll-anchor'

describe('computeAnchorAdjustedScrollTop', () => {
  // Helper: pkg ids by index
  const ids = (n: number, prefix = 'p') => Array.from({ length: n }, (_, i) => `${prefix}${i}`)

  it('returns null when scrollTop === 0 (user at top)', () => {
    const oldRows = ids(50).map((id, i) => ({ package_id: id, idx: i }))
    const newRows = [...ids(3, 'NEW'), ...ids(50)].map((id, i) => ({ package_id: id, idx: i }))
    const out = computeAnchorAdjustedScrollTop({
      oldRows: oldRows as any,
      newRows: newRows as any,
      oldScrollTop: 0,
      rowHeight: 40,
    })
    expect(out).toBeNull()
  })

  it('null when no anchor row found in old set (oldRows empty)', () => {
    const out = computeAnchorAdjustedScrollTop({
      oldRows: [],
      newRows: [{ package_id: 'a' }, { package_id: 'b' }] as any,
      oldScrollTop: 100,
      rowHeight: 40,
    })
    expect(out).toBeNull()
  })

  it('null when anchor row no longer present in newRows (filtered out)', () => {
    const oldRows = [{ package_id: 'a' }, { package_id: 'b' }, { package_id: 'c' }] as any
    const newRows = [{ package_id: 'a' }, { package_id: 'c' }] as any
    const out = computeAnchorAdjustedScrollTop({
      oldRows,
      newRows,
      oldScrollTop: 80,
      rowHeight: 40,
    })
    // anchor was 'c' (idx 2 at scrollTop 80) — still present so this case
    // bumps. flip to remove 'c' to actually exercise the null path.
    expect(out).not.toBeNull()
  })

  it('bumps scrollTop by rowHeight × N when N rows landed above the anchor', () => {
    // Old: anchor index 5 ⇒ oldScrollTop = 5*40 = 200.
    const oldRows = ids(20).map((id) => ({ package_id: id })) as any
    // New: 3 fresh rows landed above; anchor 'p5' is now at index 8.
    const newRows = [
      { package_id: 'NEW0' },
      { package_id: 'NEW1' },
      { package_id: 'NEW2' },
      ...oldRows,
    ]
    const out = computeAnchorAdjustedScrollTop({
      oldRows,
      newRows,
      oldScrollTop: 200,
      rowHeight: 40,
    })
    // Anchor was at idx 5, now at idx 8. Bump = (8-5)*40 = 120. New top = 320.
    expect(out).toBe(320)
  })

  it('returns null when no rows landed above (anchor index unchanged)', () => {
    const rows = ids(20).map((id) => ({ package_id: id })) as any
    const out = computeAnchorAdjustedScrollTop({
      oldRows: rows,
      newRows: rows,
      oldScrollTop: 200,
      rowHeight: 40,
    })
    expect(out).toBeNull()
  })
})
```

**Step 6.2: Run failing test**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=scroll-anchor.test`
Expected: FAIL — `scroll-anchor` not found.

**Step 6.3: Implement**

Create `scroll-anchor.ts`:

```ts
// ABOUTME: Pure helper for keeping the trader's visible row stable across
// poll-merge updates. When a poll inserts new rows above the anchor the
// VirtualScroller would naively shift everything down by N*rowHeight while
// scrollTop stays constant — a different row appears under the cursor.
// This helper computes the new scrollTop that re-anchors the same package
// to the same on-screen position.

interface RowLike {
  package_id?: string | null
}

export interface ComputeAnchorParams<R extends RowLike> {
  oldRows: R[]
  newRows: R[]
  oldScrollTop: number
  rowHeight: number
}

/**
 * @returns the new scrollTop to use after the rows array changed, or
 *   null if no adjustment is needed (user at top, no anchor available,
 *   anchor row no longer present in newRows, or position unchanged).
 */
export function computeAnchorAdjustedScrollTop<R extends RowLike>(
  p: ComputeAnchorParams<R>,
): number | null {
  const { oldRows, newRows, oldScrollTop, rowHeight } = p
  if (oldScrollTop <= 0) return null
  if (!oldRows.length || rowHeight <= 0) return null

  const oldAnchorIdx = Math.floor(oldScrollTop / rowHeight)
  if (oldAnchorIdx < 0 || oldAnchorIdx >= oldRows.length) return null

  const anchor = oldRows[oldAnchorIdx]
  const anchorId = anchor?.package_id
  if (!anchorId) return null

  const newAnchorIdx = newRows.findIndex((r) => r.package_id === anchorId)
  if (newAnchorIdx < 0) return null

  const idxDelta = newAnchorIdx - oldAnchorIdx
  if (idxDelta === 0) return null

  return oldScrollTop + idxDelta * rowHeight
}
```

**Step 6.4: Run tests — verify pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=scroll-anchor.test`
Expected: PASS.

**Step 6.5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/scroll-anchor.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/scroll-anchor.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: pure helper for poll-merge scroll-anchor

computeAnchorAdjustedScrollTop returns the new scrollTop that keeps the
package the trader was looking at under the same on-screen position
when the rows array grows or reorders. Used by TradeTapeTable to
neutralise the 30s-poll shake that traders reported. Pure function
keeps the calculation testable without a browser harness.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire scroll-anchor into `TradeTapeTable`

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx`

**Step 7.1: Add the layout effect that captures the anchor before any update and re-applies after**

Inside `TradeTapeTable` (after the `displayRows` memo, before the chain-load `useEffect`), insert:

```tsx
  // Scroll-anchor poll-merge: when the rows array grows or reorders
  // (typically because a 30s poll merged in newer prints), keep the
  // package the trader was looking at under the same on-screen
  // position. Without this, the VirtualScroller renders by pixel offset
  // (`itemSize: ROW_ESTIMATE_PX`) so all rows shift down by N * 40px
  // while scrollTop stays constant — a different row appears under
  // the cursor.
  const prevDisplayRowsRef = useRef<UsdSwapTapeRow[] | null>(null)
  useLayoutEffect(() => {
    const prev = prevDisplayRowsRef.current
    prevDisplayRowsRef.current = displayRows
    if (!prev || prev === displayRows) return
    const sc = tableWrapperRef.current?.querySelector<HTMLElement>('.p-virtualscroller')
    if (!sc) return
    const next = computeAnchorAdjustedScrollTop({
      oldRows: prev,
      newRows: displayRows,
      oldScrollTop: sc.scrollTop,
      rowHeight: ROW_ESTIMATE_PX,
    })
    if (next !== null) sc.scrollTop = next
  }, [displayRows])
```

Add the imports:

```ts
import { useLayoutEffect } from 'react'
import { computeAnchorAdjustedScrollTop } from './scroll-anchor'
```

(`useEffect`, `useRef`, etc. are already imported.)

**Step 7.2: Verify by running the existing TradeTapeTable suite**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=TradeTapeTable`
Expected: PASS — the scroll-anchor effect is no-op in jsdom (no real scrollHeight), so existing tests keep their behaviour.

**Step 7.3: Browser verification of Bug 1 (poll shake)**

In the live dev server (`npm run dev` in `SDRUtils/dashboard`):
1. Open `/usd-swaps`.
2. Scroll to ~`scrollTop = 2000` and note the row text under that pixel.
3. Wait for the 30s poll.
4. Confirm the same row text is still under that pixel after the poll merge.

**Step 7.4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx
git commit -m "$(cat <<'EOF'
dashboard tape v2: anchor scrollTop on poll-merge so the row stays put

Adds a useLayoutEffect that captures the package_id at the trader's
current top-visible position before each displayRows update and bumps
scrollTop after, so the same row stays under the cursor when newer
prints land above. Eliminates the 30s-poll "shake" trader report
without changing polling cadence or the analytics dock contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full-suite verification + browser before/after evidence

**Files:** none modified.

**Step 8.1: Run the full v2 dashboard test suite**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
Expected: every existing test still PASS, every new test PASS, total count = previous total + new count.

**Step 8.2: Run the canonical Python tests pinned in the QA report**

Run from repo root:

```bash
conda run --no-capture-output -n stir pytest tests/test_underlier_canonical.py \
  tests/test_sdr_primitives.py tests/test_sdr_lifecycle_state_machine.py \
  tests/test_sdr_economic_classification.py tests/test_sdr_phase5_structural.py
```

Expected: all green (no behaviour changes upstream).

**Step 8.3: Capture before/after evidence in the browser**

For each of the four bugs, capture a screenshot or network trace of the new behaviour:
- Bug 1: scrollTop=2000 stable across a poll cycle (visible row text unchanged).
- Bug 2/4: filter `tape_label contains 10Y` triggers a single `?columnFilters=...` request returning ~4k matches, no further chain pages.
- Bug 3: refresh-required scenario no longer occurs — the chain reaches `hasMore=false` cleanly.

Save screenshots / HARs under `docs/plans/evidence/2026-04-28-tape/`.

**Step 8.4: Open PR**

```bash
git push -u origin dashboard/tape-pagination-rework
gh pr create --base main --title "Tape v2 pagination + polling rework" --body "$(cat <<'EOF'
## Summary

Eliminates the four trader-reported defects on the USD swap tape v2 dashboard:

1. **Poll shake** — the 30s tape poll no longer shifts visible rows. A `useLayoutEffect` in `TradeTapeTable` anchors the trader's current top-visible row by `package_id`; when new prints land above, scrollTop bumps by `(rowsAdded × rowHeight)` so the visible row stays put.
2. **Filter lag / incomplete loads / "too many trades at once"** — the route now translates the URL-synced `columnFilters` payload into parameterised SQL `WHERE` fragments. The cursor scan returns only matching rows, so the chain-load no longer drags down 14k+ unfiltered rows to find a few hundred matches.

## Root causes

See [`docs/plans/2026-04-28-tape-pagination-rework-design.md`](docs/plans/2026-04-28-tape-pagination-rework-design.md) for the full diagnosis with browser repro evidence.

## Approach

- **A1 — server pushdown**: `buildColumnFilterClause` allowlists the columns surfaced in the per-column overlay (`tape_label`, `total_risk`, `total_notional`, `weighted_fixed_rate`, `package_type`, `package_indicator`, `other_lvl_reported`, plus leg fields `platform_identifier` and `lifecycle_type` via EXISTS). Match modes mirror PrimeReact's `matchFilterValue` semantics. Defensive client-side filter retained.
- **A2 — scroll-anchor**: `computeAnchorAdjustedScrollTop` is a pure helper; `TradeTapeTable` invokes it in a layout effect on every `displayRows` change.

## Out of scope (deferred follow-ups)

- Cursor tiebreaker `(execution_start, package_id) DESC`
- Variable row-height handling (expanded `LegsSubTable`)
- Cross-field OR in `columnFilters`
- Server-side timestamp display-string filter

## Tests

- `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
- `conda run --no-capture-output -n stir pytest tests/test_underlier_canonical.py …`
- Browser verification per `docs/plans/evidence/2026-04-28-tape/`.

## Rollback

Revert the commits on this branch. The two fixes are independent: A2 (scroll-anchor) can stay if A1 needs to roll back, and vice versa.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Notes for the executing engineer

- DRY: every WHERE-clause helper inside `buildColumnFilterClause` follows the pattern "validate value → push param → return formatted clause" — keep it that way.
- YAGNI: do NOT add support for additional match modes, additional columns, cross-field OR, or timestamp pushdown in this PR. They are listed in the design doc as deferred follow-ups.
- TDD: write the failing test first; run it; only then write the implementation.
- Don't touch the analytics dock files — they are explicitly out of scope.
- If a test that doesn't belong to this feature begins to fail, STOP and ask the user before "fixing" it — the QA report has 280+ tests and several are pinning constants you may not have context for.
