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

**Time-bounded SQL when column filters are active.** A new pure helper `parseDatePattern` accepts the trader's `execution_start` filter input and returns a calendar date or null. `buildColumnFilterClause` consumes the parsed date (or falls back to "today") to emit a single equality on `as_of_date`, which is index-backed via the existing `idx_tape_v2_packages_date (as_of_date, execution_start DESC)`.

### `parseDatePattern(raw: string): { yyyymmdd: string } | null`

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
     c. Skip emitting any direct execution_start clause (the date bound covers it).
3. After walking all fields:
     - Did at least one allowlisted clause get emitted?
       - YES + bound parsed: emit `WHERE as_of_date = $bound`.
       - YES + bound NOT parsed: emit `WHERE as_of_date = (now() AT TIME ZONE 'America/New_York')::date`.
       - NO clauses at all: emit nothing (live tape).
```

Multiple execution_start constraints are tolerated — the first parseable one wins, others are dropped. (Documented; v1 doesn't need full multi-constraint date logic.)

### SQL output examples

**Trader URL (`execution_start contains "04/21"`):**

```sql
WHERE d.as_of_date = $1   -- $1 = '2026-04-21'
ORDER BY d.execution_start DESC
LIMIT 201
```

**Trader filters `tape_label contains "10Y"` only:**

```sql
WHERE (d.tape_label ILIKE $1)             -- $1 = '%10Y%'
  AND d.as_of_date = (now() AT TIME ZONE 'America/New_York')::date
ORDER BY d.execution_start DESC
LIMIT 201
```

**Trader filters `tape_label contains "10Y"` AND `execution_start contains "04/21"`:**

```sql
WHERE (d.tape_label ILIKE $1)             -- $1 = '%10Y%'
  AND d.as_of_date = $2                   -- $2 = '2026-04-21'
ORDER BY d.execution_start DESC
LIMIT 201
```

**Trader has no column filters (live tape):**

```sql
ORDER BY d.execution_start DESC
LIMIT 201
```

(Unchanged.)

### Polling under a date bound

`?since=` requests inherit the same `as_of_date` clause via the same `buildColumnFilterClause` invocation. If the trader has scoped to a past day, `?since=...` with a timestamp at end-of-that-day will return zero new rows (correct — no new prints land on closed days). If the trader has scoped to today, polling continues normally.

### Cursor pagination under a date bound

The existing `WHERE d.execution_start < $cursor` clause composes with the new `WHERE d.as_of_date = $bound` cleanly. The cursor scan walks back through that day's prints only. When `hasMore=false`, the chain stops without dragging further back. This is the desired behaviour.

### Defensive client-side filter

`displayRows` still applies `matchFilterMetaWithRow` for every active constraint, including `execution_start`'s display-string match. Cheap operation on the small server-bounded result; means a malformed pushdown (or a bug in `parseDatePattern`) falls through to client behaviour rather than silently showing wrong data.

## Constraints satisfied

| Constraint | How |
|---|---|
| Analytics dock unchanged | This is a route + pure-helper change. `tape_label` (the dock's bucket key) and `package_id` are untouched. |
| Polling cadence | 30s polling unchanged. `?since=` inherits the date bound naturally. |
| Manual link / dedupe | `dedupeDuplicatePackages` is downstream of the rows array. Unaffected. |
| Cache header | `Cache-Control` skipped when `columnFilters` is non-empty (already done in PR #282). |
| Existing tests stay green | Live tape (no filter) emits no `as_of_date` clause — every existing `buildTapeQuery` test that constructs filterless params still produces a WHERE-free query. |

## Out of scope (deferred follow-ups)

- **Multi-day range patterns** in `execution_start` filter (`04/15 - 04/22`, `>=2026-04-15`).
- **"Show all history" toggle** to disable the implicit "today" bound.
- **Date-range picker** as a first-class toolbar control.
- **Filter chip surfacing** the active time bound ("Filtered: April 21").
- **Original-execution-time bound** for FOMC-dated swaps where the trader is searching by the alpha-leg execution date rather than the dissemination time.

## Risks

- **Year defaulting can surprise.** If today is 2027-01-05 and trader types `12/30`, do they mean 2026 (recent past) or 2027 (future)? The "step back a year if future" rule covers most cases. Documented in the helper.
- **`as_of_date` vs `execution_start` NYC-day equivalence**. The schema sets `as_of_date` at ingest time and the indexes are keyed on it. If there's any drift between `as_of_date` and the NYC-localized date of `execution_start`, the bound could miss prints. Mitigation: client-side `displayRows` filter still runs as a safety net.
- **Trader expects all-history match for tape_label-only filter.** If they were relying on the chain-drag-back behaviour to find historical matches (e.g., "all 10Y prints last week") they'll see only today's. Documented as a known shift; "Show all history" follow-up addresses it.

## Test plan

**Unit (`route.logic.test.ts`):**
- `parseDatePattern` matrix: every accepted format returns expected date; every garbage input returns null.
- `buildColumnFilterClause` emits `as_of_date = today` when `tape_label` set and no execution_start filter.
- `buildColumnFilterClause` emits `as_of_date = $parsed` when execution_start has a date pattern.
- `buildColumnFilterClause` does NOT emit `as_of_date` when columnFilters is empty.
- `buildColumnFilterClause` skips the direct execution_start substring clause when the bound is captured (no double-clause).
- `buildColumnFilterClause` falls through to today bound when execution_start filter is unparseable (e.g., `"NEWFLOW"`).

**Integration (`route.cache-headers.test.ts` family):**
- Same cache-skip behaviour as today (no behaviour change there).

**Browser:**
- Trader URL `?columnFilters={execution_start contains "04/21"}` → single SQL request, single fast response, "matching" count == "loaded" count, no chain-load.
- Trader URL `?columnFilters={tape_label contains "10Y"}` → today's matches only; cursor pages within today only; smaller universe.
- Live tape (no filter) — unchanged.

## Build sequence

1. Pure `parseDatePattern` helper + unit tests. Commit.
2. Modify `buildColumnFilterClause` to consume the parsed date + emit `as_of_date` bound (today or parsed). Commit.
3. Browser verify against the trader's URL. Commit any test polish.
4. Push + extend PR #282 description (or open follow-up PR — decide based on diff size).

## Rollback

Revert the commits on the feature branch. The pure helper is dead code if the wiring commit is reverted; the `as_of_date` clause is conditional on `columnFilters`, so no-filter requests are byte-identical to today.
