# USD Swaps Tape v2 — Time-Bounded Filter Queries — Design

**Date:** 2026-04-28
**Branch:** `dashboard/tape-pagination-rework` (continuation of PR #282)
**Triggered by:** trader report — `?columnFilters={execution_start contains "04/21"}` is slow because the chain iterates every day.

## Problem

The prior pagination rework ([2026-04-28-tape-pagination-rework-design.md](2026-04-28-tape-pagination-rework-design.md)) pushed `tape_label`, `package_type`, etc. into SQL but left `execution_start` as a client-only filter (timestamp display strings deferred). Symptoms today:

1. Trader applies `execution_start contains "04/21"` → server returns unfiltered cursor pages → chain-load drags every day backward from today until a match is found. Slow.
2. Trader applies `tape_label contains "10Y"` → server pushes the filter, but the cursor scan still walks every day's worth of matching prints (15 days × ~thousand matches each → still slow). Even a successful pushdown can return a million rows over months.

The underlying issue is that **column-filter workflows don't want unbounded historical pagination** — the trader is doing a lookup against a specific time window, not a deep historical scroll.

## Diagnosis

The cursor model is correct for the live-tape workflow (latest first, scroll back, polling). It is wrong for the column-filter workflow, which is a **bounded historical lookup** — the trader knows roughly when the print they want occurred and uses the column filters to drill into it.

The fix is to scope filter-active queries to a sensible time window:

- When the trader sets a date pattern in `execution_start` → snap the SQL to that day.
- When no date pattern is set but other column filters are → default to today (NYC trading day).
- When no column filter is active → keep the current cursor pagination unchanged.

## Approach

**Time-bounded SQL when column filters are active.** A new pure helper `parseDatePattern` accepts the trader's `execution_start` filter input and returns a calendar date or null. `buildColumnFilterClause` consumes the parsed date (or falls back to "today") to emit a NYC-day range clause on `execution_start`.

The existing `idx_tape_v2_packages_exec_start (execution_start DESC NULLS LAST)` index covers the range scan. (The packages table also has an `as_of_date` column with a composite index, but `as_of_date` represents the SDR ingest **batch date**, not the trade's NYC trading day — confirmed in dev: a row with `execution_start = 2026-04-21T23:36:28Z` carries `as_of_date = 2026-04-01`. Bounding on `as_of_date` would silently miss prints.)

### `parseDatePattern(raw: string, now?: Date): string | null`

Accepts:

| Input | Parsed |
|---|---|
| `04/21` | April 21 of current NYC year |
| `4/21` | same |
| `04/21/2026` | April 21, 2026 |
| `4/21/2026` | same |
| `2026-04-21` | April 21, 2026 |
| `2026-4-21` | same |
| `4/21/26` | April 21, 2026 (two-digit year, current century) |
| anything else (`NEWFLOW`, `5Y`, empty, `04/21 - 04/23`) | `null` |

Returns the parsed date as an ISO `yyyy-mm-dd` string. Multi-day patterns and inequality patterns (`>=...`, range syntax) are **not** supported in v1.

**Year defaulting**: when only month/day given, default to current NYC year. If the resulting date is in the future (rare — would happen at year-end), step back a year.

### `buildColumnFilterClause` — new behaviour

Pseudocode:

```
1. Walk columnFilters payload as today.
2. If `execution_start` field is present:
     a. For each constraint, try parseDatePattern(constraint.value).
     b. If ANY constraint yields a parsed date, capture the FIRST one as `bound`.
     c. Mark hasAllowlistedClause = true even when parsing fails — the trader's
        intent (filter is active) still trips the today fallback.
     d. Skip emitting any direct execution_start substring clause.
3. After walking all fields:
     - hasAllowlistedClause + bound parsed: emit a parameterised range using $bound.
     - hasAllowlistedClause + bound not parsed: emit a today range using NOW() in Postgres.
     - No allowlisted clauses: emit nothing (live tape).
```

Multiple execution_start constraints are tolerated — the first parseable one wins, others are dropped. (Documented; v1 doesn't need full multi-constraint date logic.)

### SQL output examples

**Trader URL (`execution_start contains "04/21"`):**

```sql
WHERE d.execution_start >= ($1::timestamp AT TIME ZONE 'America/New_York')
  AND d.execution_start <  ($1::timestamp AT TIME ZONE 'America/New_York') + INTERVAL '1 day'
ORDER BY d.execution_start DESC
LIMIT 201
-- $1 = '2026-04-21'
```

**Trader filters `tape_label contains "10Y"` only:**

```sql
WHERE (d.tape_label ILIKE $1)
  AND d.execution_start >= date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York'
  AND d.execution_start <  date_trunc('day', now() AT TIME ZONE 'America/New_York') AT TIME ZONE 'America/New_York' + INTERVAL '1 day'
ORDER BY d.execution_start DESC
LIMIT 201
-- $1 = '%10Y%'
```

**Trader filters `tape_label contains "10Y"` AND `execution_start contains "04/21"`:**

```sql
WHERE (d.tape_label ILIKE $1)
  AND d.execution_start >= ($2::timestamp AT TIME ZONE 'America/New_York')
  AND d.execution_start <  ($2::timestamp AT TIME ZONE 'America/New_York') + INTERVAL '1 day'
ORDER BY d.execution_start DESC
LIMIT 201
-- $1 = '%10Y%', $2 = '2026-04-21'
```

**Trader has no column filters (live tape):**

```sql
ORDER BY d.execution_start DESC
LIMIT 201
```

(Unchanged.)

### Polling under a date bound

`?since=` requests inherit the same time-bound clause via the same `buildColumnFilterClause` invocation. If the trader has scoped to a past day, `?since=...` returns zero new rows after end-of-day (correct — no new prints land on closed days). If the trader has scoped to today, polling continues normally.

### Cursor pagination under a date bound

The existing `WHERE d.execution_start < $cursor` clause composes with the time-bound predicates cleanly. The cursor scan walks back through that day's prints only. When `hasMore=false`, the chain stops without dragging further back. This is the desired behaviour.

### Defensive client-side filter

`displayRows` still applies `matchFilterMetaWithRow` for every active constraint, including `execution_start`'s display-string match. Cheap operation on the small server-bounded result; means a malformed pushdown (or a bug in `parseDatePattern`) falls through to client behaviour rather than silently showing wrong data.

## Constraints satisfied

| Constraint | How |
|---|---|
| Analytics dock unchanged | This is a route + pure-helper change. `tape_label` (the dock's bucket key) and `package_id` are untouched. |
| Polling cadence | 30s polling unchanged. `?since=` inherits the date bound naturally. |
| Manual link / dedupe | `dedupeDuplicatePackages` is downstream of the rows array. Unaffected. |
| Cache header | `Cache-Control` skipped when `columnFilters` is non-empty (already done in PR #282). |
| Existing tests stay green | Live tape (no filter) emits no time-bound clause — every existing `buildTapeQuery` test that constructs filterless params still produces a WHERE-free query. |

## Out of scope (deferred follow-ups)

- **Multi-day range patterns** in `execution_start` filter (`04/15 - 04/22`, `>=2026-04-15`).
- **"Show all history" toggle** to disable the implicit "today" bound.
- **Date-range picker** as a first-class toolbar control.
- **Filter chip surfacing** the active time bound ("Filtered: April 21").
- **Original-execution-time bound** for FOMC-dated swaps where the trader is searching by the alpha-leg execution date rather than the dissemination time.

## Risks

- **Year defaulting can surprise.** If today is 2027-01-05 and trader types `12/30`, do they mean 2026 (recent past) or 2027 (future)? The "step back a year if future" rule covers most cases. Documented in the helper.
- **DST boundary at midnight.** A NYC day is 23 or 25 hours twice a year. Letting Postgres compute the boundary via `AT TIME ZONE` handles this correctly per pg semantics.
- **Trader expects all-history match for tape_label-only filter.** If they were relying on the chain-drag-back behaviour to find historical matches (e.g., "all 10Y prints last week") they'll see only today's. Documented as a known shift; "Show all history" follow-up addresses it.
- **`as_of_date` is the SDR ingest batch date, not the trade's NYC date.** Confirmed in dev (an execution_start of 2026-04-21T23:36Z carries as_of_date 2026-04-01). Bounding on as_of_date would silently miss prints. We bound on execution_start with NYC-localised range instead.

## Test plan

**Unit (`route.logic.test.ts`):**
- `parseDatePattern` matrix: every accepted format returns expected date; every garbage input returns null.
- `buildColumnFilterClause` emits today range when `tape_label` set and no execution_start filter.
- `buildColumnFilterClause` emits parsed-date range when execution_start has a date pattern.
- `buildColumnFilterClause` does NOT emit a time-bound clause when columnFilters is empty.
- `buildColumnFilterClause` skips the direct execution_start substring clause when the bound is captured (no double-clause).
- `buildColumnFilterClause` falls through to today range when execution_start filter is unparseable (e.g., `"NEWFLOW"`).

**Integration (`route.cache-headers.test.ts` family):**
- Same cache-skip behaviour as today (no behaviour change there).

**Browser:**
- Trader URL `?columnFilters={execution_start contains "04/21"}` → bounded server query, "matching" count == "loaded" count, chain completes cleanly with `hasMore=false`.
- Trader URL `?columnFilters={tape_label contains "10Y"}` → today's matches only; cursor pages within today only; smaller universe.
- Live tape (no filter) — unchanged.

## Build sequence

1. Pure `parseDatePattern` helper + unit tests. Commit.
2. Modify `buildColumnFilterClause` to consume the parsed date + emit the NYC-day range bound (today or parsed). Commit.
3. Browser verify against the trader's URL. Commit any test polish.
4. Push + extend PR #282 description (or open follow-up PR — decide based on diff size).

## Rollback

Revert the commits on the feature branch. The pure helper is dead code if the wiring commit is reverted; the time-bound clause is conditional on `columnFilters`, so no-filter requests are byte-identical to today.
