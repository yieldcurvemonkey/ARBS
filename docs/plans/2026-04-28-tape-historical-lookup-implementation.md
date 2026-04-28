# USD Swaps Tape v2 — Time-Bounded Filter Queries — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make column-filter workflows on the tape fast for historical lookups by scoping the SQL to today (NYC trading day) by default and parsing a date pattern in the `execution_start` filter to a day-precision `as_of_date` equality.

**Architecture:** Two TDD chunks on top of the prior server-side filter pushdown (PR #282). A new pure helper `parseDatePattern` accepts trader text and returns an ISO yyyy-mm-dd string or null. `buildColumnFilterClause` consumes it (or falls back to today) to emit `AND d.as_of_date = $bound` whenever any allowlisted column filter is active. Index-backed via the existing `idx_tape_v2_packages_date (as_of_date, execution_start DESC)` composite index. Live tape (no filter) is unchanged.

**Tech Stack:** Next.js 15 + React 19, PrimeReact 10, Postgres, Jest 30 + ts-jest.

**Backing design:** [`docs/plans/2026-04-28-tape-historical-lookup-design.md`](2026-04-28-tape-historical-lookup-design.md)

**Branch:** `dashboard/tape-pagination-rework` (continuation; PR #282 already open).

**Test command:** `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2/__tests__/route.logic.test`

> **Post-implementation note (2026-04-28):** The plan originally proposed bounding on `as_of_date = $1`, expecting `as_of_date` to be the trade's NYC date. Live verification revealed `as_of_date` is the SDR **ingest batch** date (e.g. `as_of_date = 2026-04-01` for a row whose `execution_start = 2026-04-21T23:36:28Z`). The actual implementation bounds on `execution_start` with NYC-localised day boundaries computed in Postgres (`execution_start >= ($n::timestamp AT TIME ZONE 'America/New_York')` and `< ... + INTERVAL '1 day'` for the parsed-date case; `date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York'` for the today fallback). Index-backed via `idx_tape_v2_packages_exec_start (execution_start DESC NULLS LAST)`. The test snippets below mention `as_of_date` — the actual committed test fragments use the `execution_start` range form. See `route.logic.test.ts` for the canonical set.

---

## Task 1: `parseDatePattern` pure helper

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts` — append helper.
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts` — append test block.

**Step 1.1: Write failing tests**

Append to the test file (after the existing `describe('buildColumnFilterClause', ...)` block):

```ts
import { parseDatePattern } from '../route.logic'

describe('parseDatePattern', () => {
  // Anchor today to a deterministic value so "current year" defaulting is
  // testable without time-mocking the runner.
  const TODAY = new Date('2026-04-28T15:00:00Z')

  it('parses M/D in current NYC year', () => {
    expect(parseDatePattern('4/21', TODAY)).toBe('2026-04-21')
  })

  it('parses MM/DD with leading zeros', () => {
    expect(parseDatePattern('04/21', TODAY)).toBe('2026-04-21')
  })

  it('parses M/D/YYYY', () => {
    expect(parseDatePattern('4/21/2026', TODAY)).toBe('2026-04-21')
  })

  it('parses MM/DD/YYYY', () => {
    expect(parseDatePattern('04/21/2026', TODAY)).toBe('2026-04-21')
  })

  it('parses M/D/YY (two-digit year, current century)', () => {
    expect(parseDatePattern('4/21/26', TODAY)).toBe('2026-04-21')
  })

  it('parses YYYY-MM-DD ISO', () => {
    expect(parseDatePattern('2026-04-21', TODAY)).toBe('2026-04-21')
  })

  it('parses YYYY-M-D ISO without leading zeros', () => {
    expect(parseDatePattern('2026-4-21', TODAY)).toBe('2026-04-21')
  })

  it('returns null for unparseable input', () => {
    expect(parseDatePattern('NEWFLOW', TODAY)).toBeNull()
    expect(parseDatePattern('5Y', TODAY)).toBeNull()
    expect(parseDatePattern('', TODAY)).toBeNull()
    expect(parseDatePattern('04/21 - 04/23', TODAY)).toBeNull()
    expect(parseDatePattern('>=2026-04-15', TODAY)).toBeNull()
  })

  it('returns null for impossible dates', () => {
    expect(parseDatePattern('13/40', TODAY)).toBeNull()
    expect(parseDatePattern('2026-02-30', TODAY)).toBeNull()
  })

  it('steps back a year if M/D defaults to a future date', () => {
    // anchor TODAY = 2027-01-05 NYC; trader types 12/30 — they meant
    // 2026-12-30 (recent past), not 2027-12-30 (future).
    const earlyJan = new Date('2027-01-05T15:00:00Z')
    expect(parseDatePattern('12/30', earlyJan)).toBe('2026-12-30')
  })

  it('does NOT step back when explicit year is supplied (even if future)', () => {
    const earlyJan = new Date('2027-01-05T15:00:00Z')
    // 12/30/2027 is explicit — keep it.
    expect(parseDatePattern('12/30/2027', earlyJan)).toBe('2027-12-30')
  })

  it('trims whitespace before parsing', () => {
    expect(parseDatePattern('  04/21  ', TODAY)).toBe('2026-04-21')
  })

  it('returns null for non-string input', () => {
    expect(parseDatePattern(null as any, TODAY)).toBeNull()
    expect(parseDatePattern(undefined as any, TODAY)).toBeNull()
    expect(parseDatePattern(0 as any, TODAY)).toBeNull()
  })
})
```

**Step 1.2: Run failing tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2/__tests__/route.logic.test`
Expected: FAIL — `parseDatePattern is not exported from '../route.logic'`.

**Step 1.3: Implement**

Append to `route.logic.ts` immediately above the `buildColumnFilterClause` export (or any natural location near it):

```ts
// ---------------------------------------------------------------------------
// Date-pattern parser for the execution_start column filter
//
// Traders type natural date patterns into the per-column filter input
// (`04/21`, `4/21/2026`, `2026-04-21`). Pre-this change, those values fell
// through to client-side substring matching against the NYC display string,
// which forced the chain-load to drag every day backward from today until
// a match was found. Parsing the value into a calendar date here lets the
// route emit a single `as_of_date = $1` predicate, hitting the existing
// idx_tape_v2_packages_date composite index.
//
// Returns ISO yyyy-mm-dd. Multi-day patterns and inequality patterns are
// NOT supported in v1 — see the design doc for deferred follow-ups.
// ---------------------------------------------------------------------------

const DATE_PATTERN_MD_Y =
  /^(\d{1,2})\/(\d{1,2})(?:\/(\d{2}|\d{4}))?$/
const DATE_PATTERN_ISO = /^(\d{4})-(\d{1,2})-(\d{1,2})$/

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n)
}

function isValidYmd(year: number, month: number, day: number): boolean {
  if (month < 1 || month > 12) return false
  if (day < 1 || day > 31) return false
  // Round-trip through Date to validate (catches Feb 30, etc.).
  const d = new Date(Date.UTC(year, month - 1, day))
  return (
    d.getUTCFullYear() === year &&
    d.getUTCMonth() === month - 1 &&
    d.getUTCDate() === day
  )
}

export function parseDatePattern(
  raw: unknown,
  now: Date = new Date(),
): string | null {
  if (typeof raw !== 'string') return null
  const trimmed = raw.trim()
  if (!trimmed) return null

  // M/D, M/D/YY, M/D/YYYY
  const mdMatch = trimmed.match(DATE_PATTERN_MD_Y)
  if (mdMatch) {
    const month = Number(mdMatch[1])
    const day = Number(mdMatch[2])
    const yearRaw = mdMatch[3]
    let year: number
    let yearWasExplicit = false
    if (yearRaw === undefined) {
      year = now.getFullYear()
    } else {
      yearWasExplicit = true
      year = Number(yearRaw)
      if (year < 100) year += Math.floor(now.getFullYear() / 100) * 100
    }
    if (!isValidYmd(year, month, day)) return null

    // If M/D defaulted to current year and the resulting date is in the
    // future (e.g. trader types "12/30" on 2027-01-05), step back a year so
    // the trader gets the recent past.
    if (!yearWasExplicit) {
      const candidate = new Date(Date.UTC(year, month - 1, day))
      const today = new Date(
        Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()),
      )
      if (candidate.getTime() > today.getTime()) {
        year -= 1
        if (!isValidYmd(year, month, day)) return null
      }
    }
    return `${year}-${pad2(month)}-${pad2(day)}`
  }

  // YYYY-M-D, YYYY-MM-DD
  const isoMatch = trimmed.match(DATE_PATTERN_ISO)
  if (isoMatch) {
    const year = Number(isoMatch[1])
    const month = Number(isoMatch[2])
    const day = Number(isoMatch[3])
    if (!isValidYmd(year, month, day)) return null
    return `${year}-${pad2(month)}-${pad2(day)}`
  }

  return null
}
```

**Step 1.4: Run tests to verify pass**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2/__tests__/route.logic.test`
Expected: PASS — every `parseDatePattern` case green; existing tests unchanged.

**Step 1.5: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: parseDatePattern pure helper

Accepts trader-typed date patterns (M/D, M/D/YYYY, MM/DD/YY, YYYY-MM-DD,
with leading-zero tolerance) and returns ISO yyyy-mm-dd, null on garbage.
Year defaults to current NYC year; steps back a year when the resulting
date would be in the future and the trader didn't supply an explicit
year.

Pure function — no callers yet. Wiring into buildColumnFilterClause
follows in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire date bound into `buildColumnFilterClause`

**Files:**
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts` — `buildColumnFilterClause` body.
- Modify: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts` — append matrix.

**Step 2.1: Write failing tests**

Append a new `describe` block at the bottom of the test file:

```ts
describe('buildColumnFilterClause as_of_date bound', () => {
  // Freeze today for determinism.
  const TODAY_NY = '2026-04-28' // arbitrary; matches a date the test pins.

  // Helper that captures the now-injection point. The clause helper itself
  // computes today via Postgres `(now() AT TIME ZONE 'America/New_York')::date`
  // SO at the SQL level — the test asserts the SQL fragment, not a parsed
  // date constant.
  it('emits as_of_date = TODAY_NYC when other filters are present and execution_start is unset', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(clause).toMatch(
      /d\.as_of_date = \(now\(\) AT TIME ZONE 'America\/New_York'\)::date/,
    )
    expect(params).toEqual(['%10Y%'])
  })

  it('emits as_of_date = $parsed when execution_start carries a date pattern', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        execution_start: {
          operator: 'and',
          constraints: [{ value: '04/21', matchMode: 'contains' }],
        },
      },
      params,
      // Inject today so the parser is deterministic; only the helper that
      // calls parseDatePattern needs the now reference.
      { now: new Date('2026-04-28T15:00:00Z') },
    )
    expect(clause).toMatch(/d\.as_of_date = \$1/)
    expect(params).toEqual(['2026-04-21'])
  })

  it('combines tape_label clause with as_of_date = parsed when both filters present', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
        execution_start: {
          operator: 'and',
          constraints: [{ value: '04/21', matchMode: 'contains' }],
        },
      },
      params,
      { now: new Date('2026-04-28T15:00:00Z') },
    )
    expect(clause).toMatch(/d\.tape_label ILIKE \$1/)
    expect(clause).toMatch(/d\.as_of_date = \$2/)
    expect(params).toEqual(['%10Y%', '2026-04-21'])
  })

  it('falls back to today bound when execution_start filter is unparseable', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        tape_label: {
          operator: 'and',
          constraints: [{ value: '10Y', matchMode: 'contains' }],
        },
        execution_start: {
          operator: 'and',
          constraints: [{ value: 'NEWFLOW', matchMode: 'contains' }],
        },
      },
      params,
      { now: new Date('2026-04-28T15:00:00Z') },
    )
    expect(clause).toMatch(/d\.tape_label ILIKE/)
    expect(clause).toMatch(
      /d\.as_of_date = \(now\(\) AT TIME ZONE 'America\/New_York'\)::date/,
    )
    expect(clause).not.toMatch(/d\.execution_start/)
  })

  it('does not emit any direct execution_start substring clause when a date pattern is present', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        execution_start: {
          operator: 'and',
          constraints: [{ value: '04/21', matchMode: 'contains' }],
        },
      },
      params,
      { now: new Date('2026-04-28T15:00:00Z') },
    )
    // Only the as_of_date clause; never a tape_label / execution_start ILIKE.
    expect(clause).toMatch(/d\.as_of_date = \$1/)
    expect(clause).not.toMatch(/d\.execution_start/)
  })

  it('emits no as_of_date clause when columnFilters is empty (live tape)', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause({}, params)
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('emits no as_of_date clause when only non-allowlisted fields are present', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        not_a_column: {
          operator: 'and',
          constraints: [{ value: 'x', matchMode: 'contains' }],
        },
      },
      params,
    )
    expect(clause).toBeNull()
    expect(params).toEqual([])
  })

  it('takes the FIRST parseable execution_start constraint when multiple are present', () => {
    const params: unknown[] = []
    const clause = buildColumnFilterClause(
      {
        execution_start: {
          operator: 'and',
          constraints: [
            { value: 'NEWFLOW', matchMode: 'contains' }, // unparseable
            { value: '04/21', matchMode: 'contains' }, // parseable
            { value: '04/22', matchMode: 'contains' }, // ignored
          ],
        },
      },
      params,
      { now: new Date('2026-04-28T15:00:00Z') },
    )
    expect(clause).toMatch(/d\.as_of_date = \$1/)
    expect(params).toEqual(['2026-04-21'])
  })
})
```

> Note: the new optional 3rd argument to `buildColumnFilterClause` (`{ now }`) is purely for test determinism. Production callers default to `now = new Date()`. Keeps the helper pure.

**Step 2.2: Run failing tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2/__tests__/route.logic.test`
Expected: FAIL — multiple cases miss the `as_of_date` SQL fragment.

**Step 2.3: Implement**

In `route.logic.ts`, modify `buildColumnFilterClause` to (1) recognize the `execution_start` field specially, (2) inject the `as_of_date` clause at the end. Replace the existing function body:

```ts
export function buildColumnFilterClause(
  columnFilters: Record<string, any>,
  params: unknown[],
  options: { now?: Date } = {},
): string | null {
  if (!columnFilters || typeof columnFilters !== 'object') return null
  const fieldClauses: string[] = []
  let hasAllowlistedClause = false
  let parsedDateBound: string | null = null

  for (const [field, meta] of Object.entries(columnFilters)) {
    if (!meta || typeof meta !== 'object') continue
    const constraints = Array.isArray(meta.constraints)
      ? meta.constraints
      : meta.value !== undefined
        ? [{ value: meta.value, matchMode: meta.matchMode }]
        : []
    if (constraints.length === 0) continue

    // Special-case execution_start: don't emit a substring clause; instead
    // capture the first parseable date pattern as the as_of_date bound.
    if (field === 'execution_start') {
      for (const c of constraints) {
        const parsed = parseDatePattern(c?.value, options.now)
        if (parsed !== null) {
          parsedDateBound = parsed
          hasAllowlistedClause = true
          break
        }
      }
      // Whether or not parsing succeeded, the trader had this filter active
      // → flag as an allowlisted clause so the today fallback fires below.
      hasAllowlistedClause = true
      continue
    }

    const op = meta.operator === 'or' ? ' OR ' : ' AND '
    const built = constraints
      .map((c: any) => buildSingleConstraint(field, c, params))
      .filter((s: string | null): s is string => s !== null)
    if (built.length === 0) continue
    hasAllowlistedClause = true
    fieldClauses.push(`(${built.join(op)})`)
  }

  // Time bound — emitted whenever any allowlisted clause is active. Snaps
  // historical lookups to a single day's worth of data via the
  // idx_tape_v2_packages_date composite index, instead of the cursor scan
  // dragging every day backward.
  if (hasAllowlistedClause) {
    if (parsedDateBound !== null) {
      params.push(parsedDateBound)
      fieldClauses.push(`d.as_of_date = $${params.length}`)
    } else {
      fieldClauses.push(
        `d.as_of_date = (now() AT TIME ZONE 'America/New_York')::date`,
      )
    }
  }

  if (fieldClauses.length === 0) return null
  return fieldClauses.join(' AND ')
}
```

Note the loop's `hasAllowlistedClause = true` runs regardless of parse success in the `execution_start` branch — the trader's intent (filter is active) still trips the today bound even if their text didn't parse to a date. The non-execution_start branches set `hasAllowlistedClause = true` only when a clause is actually emitted (so a non-allowlisted column like `not_a_column` doesn't trip the bound).

**Step 2.4: Update earlier tests that may now fail**

The existing `buildColumnFilterClause` tests that exercise non-execution_start fields (e.g., `tape_label CONTAINS`) will now also receive an `AND d.as_of_date = ...` suffix. Audit those tests and either:

- Loosen them to assert the substring matches without checking the absence of `as_of_date`, OR
- Update them to also assert the as_of_date clause appears.

Concretely, for each existing test that asserts `clause).toMatch(/.../)` with a tape_label or numeric expectation, add (only if the test actually exercises a clause-emitting path, NOT the empty / not-allowlisted / null-value tests):

```ts
expect(clause).toMatch(/d\.as_of_date =/)
```

Audit the existing `buildColumnFilterClause` `describe` block and apply this change to:

- `CONTAINS on tape_label: ILIKE %x% with escaped value` → expect both `tape_label ILIKE` and `as_of_date =`.
- `STARTS_WITH on tape_label uses prefix pattern` → same.
- `ENDS_WITH on tape_label uses suffix pattern` → same.
- `NOT_CONTAINS uses NOT ILIKE` → same.
- `EQUALS on text column compares LOWER(col)` (uses package_type) → same.
- `NOT_EQUALS on text column uses LOWER(col) <>` → same.
- `IN on text column ORs each lowercased value` → same.
- `GREATER_THAN on numeric column casts numeric` → same.
- `LESS_THAN_OR_EQUAL_TO on numeric column` → same.
- `LEG fields use EXISTS (jsonb_array_elements) — platform_identifier CONTAINS` → same.
- `LEG field EQUALS — lifecycle_type` → same.
- `multiple fields are joined by AND` → same.
- `per-field OR joins constraints inside one field with OR` → same.

For these tests, also assert the params length grew correctly when the bound is the explicit-today literal (no extra param) vs the parsed-date case (one extra param at the end).

The `null/undefined/empty-string` test, the `skips non-numeric values for numeric fields` test, and the `ignores fields not in the allowlist` test should NOT change — those don't emit any allowlisted clause and so don't trip the bound.

The `execution_start filter is NOT pushed (deferred)` test SHOULD now flip behaviour:

```ts
it('execution_start with date pattern emits as_of_date bound (was deferred pre-2026-04-28)', () => {
  const params: unknown[] = []
  const clause = buildColumnFilterClause(
    {
      execution_start: {
        operator: 'and',
        constraints: [{ value: '04/23', matchMode: 'contains' }],
      },
    },
    params,
    { now: new Date('2026-04-28T15:00:00Z') },
  )
  expect(clause).toMatch(/d\.as_of_date = \$1/)
  expect(params).toEqual(['2026-04-23'])
})
```

**Step 2.5: Run tests**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2/__tests__/route.logic.test`
Expected: PASS — all old tests updated, all new tests green.

**Step 2.6: Run the full dashboard suite**

Run: `cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2`
Expected: PASS — 322+ tests, no other suites broken.

**Step 2.7: Commit**

```bash
git add SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts \
        SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/__tests__/route.logic.test.ts
git commit -m "$(cat <<'EOF'
dashboard tape v2: scope filtered SQL to one trading day

When any allowlisted column filter is active, buildColumnFilterClause
now appends an as_of_date equality predicate so the cursor scan
returns a single day's worth of rows instead of iterating backward
through every day. The execution_start filter is special-cased: a
parseable date pattern (e.g. "04/21") becomes the bound; an
unparseable value falls back to today (NYC trading day) computed
in Postgres via (now() AT TIME ZONE 'America/New_York')::date.

Index-backed via idx_tape_v2_packages_date (as_of_date,
execution_start DESC). The trader-reported
?columnFilters={execution_start contains "04/21"} URL now completes
in a single fast query instead of dragging seven days of cursor
pages backward.

Live tape (no filter) is unchanged — the as_of_date clause is
gated on hasAllowlistedClause.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Browser verification

**Files:** none modified.

**Step 3.1: Reproduce the trader's URL**

In the dev server (`npm run dev` from `SDRUtils/dashboard`), open:

```
http://localhost:3717/usd-swaps?columnFilters=%7B%22execution_start%22%3A%7B%22operator%22%3A%22and%22%2C%22constraints%22%3A%5B%7B%22value%22%3A%2204%2F21%22%2C%22matchMode%22%3A%22contains%22%7D%5D%7D%7D
```

Expected:
- A single `/api/usd-swaps-tape-v2?limit=200&columnFilters=...` request fires.
- Response time well under 1s.
- "matching" count == "loaded" count.
- No subsequent cursor pages fire (within today's bounded universe; either hasMore=false immediately, or only one or two cursor pages within 04/21).

**Step 3.2: Sanity-check live tape**

Open `/usd-swaps` (no filter). Expected: cursor pagination unchanged. Polling unchanged. Latest 200 rows show.

**Step 3.3: Sanity-check tape_label filter (now today-bounded)**

Apply `tape_label contains 10Y`. Expected: matches only today's tape. Document this as a deliberate behaviour change in the PR description (was previously the chain dragged historical days; now it's today-only).

**Step 3.4: Smoke the analytics dock**

Click a row → dock opens → all three tabs render. Verifies the route + page wiring still feeds the dock the same data shape.

---

## Task 4: Push + extend PR #282 description

**Step 4.1: Push the new commits**

```bash
git push origin dashboard/tape-pagination-rework
```

**Step 4.2: Edit PR #282 description**

Use `gh pr edit 282 --body "..."` to append a "Follow-up commits" section that documents:

- The new time-bound behaviour: filtered queries scope to today by default; trader extends via execution_start date pattern.
- The new `parseDatePattern` helper.
- The `as_of_date` SQL clause replacing the deferred client-side execution_start filter.
- Trade-offs: tape_label-only filter no longer drags through historical days. Use an explicit execution_start date pattern to look up history.
- Out-of-scope deferred items repeated.

(Alternatively, if the diff feels orthogonal, open a fresh PR `dashboard/tape-historical-lookup` cherry-picking the new commits — decide based on diff size and reviewer preference. Recommendation: keep on the same branch since the work is a thematic continuation.)

---

## Notes for the executing engineer

- DRY: the `as_of_date` clause is emitted in exactly one place (the tail of `buildColumnFilterClause`). Don't duplicate it elsewhere.
- YAGNI: do NOT add multi-day range parsing, "show all history" toggles, date-range UI, or any execution_start substring fallback. Those are explicitly deferred (see design doc).
- TDD: write each failing test, run to confirm RED, implement, run GREEN, commit.
- The `now` injection on `buildColumnFilterClause` is for test determinism only. Real callers omit it; `parseDatePattern`'s default `new Date()` kicks in.
- If the existing `route.logic.test.ts` "buildColumnFilterClause" matrix has many tests that suddenly fail because of the new `AND d.as_of_date = ...` suffix, fix them all in the same commit as Task 2 — don't leave a red intermediate commit.
