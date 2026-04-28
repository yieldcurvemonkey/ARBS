# USD Swaps Tape v2 — Pagination + Polling Optimisation — Design

**Date:** 2026-04-28
**Branch:** `dashboard/tape-pagination-rework`
**Page:** `http://localhost:3717/usd-swaps-v2` (now redirects to `/usd-swaps`)

## Problem statement

Trader-reported defects on the live tape:

1. **Screen "shakes" on poll** — every 30s tape poll shifts the visible rows so the row the trader was looking at jumps out from under their cursor.
2. **Filtered fetches feel laggy** — applying a per-column filter (e.g. `tape_label contains 10Y`) makes the dashboard slow / janky for several seconds.
3. **Filter sometimes loads incompletely** — after applying a filter the trader sometimes has to refresh the page to get all matching trades.
4. **"Too many trades at once"** — when a filter is active the tape appears to drag down every remaining cursor page from the server.

## Diagnosis (browser-validated)

### Bug 1 — poll shake

`useTradeTapeData.upsertRows` re-sorts the merged array `execution_start DESC` after every `?since=` poll ([useTradeTapeData.ts:187-189](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts)). New prints land at index 0+, pushing existing rows down. PrimeReact's `VirtualScroller` anchors viewport by pixel `scrollTop` (`itemSize: ROW_ESTIMATE_PX = 40`), not by row identity. All rows shift down `N × 40px` while `scrollTop` stays constant — a different row appears under the cursor.

Live repro: scrollTop = 2000 stayed constant; the row at that pixel went from `4/23/2026 16:46:42` → `4/23/2026 16:42:37` (older) after a single poll added 17 rows above.

### Bugs 2/3/4 — filter drag-down

`parseParams` parses `columnFilters` ([route.logic.ts:130](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts)) but `buildTapeQuery` does not consume it — every column filter is applied client-side in the `displayRows` memo ([TradeTapeTable.tsx:155-201](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx)). The chain-load `useEffect` ([TradeTapeTable.tsx:210-239](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx)) drags every 200-row cursor page until either `hasMore = false` or the 20k cap. Each page carries multi-leg `legs_json` (KB+ per package via the `to_jsonb(l)` LATERAL aggregation in the display view) and triggers a re-evaluation of the O(N) `displayRows` filter+sort memo. The 15s `AbortController.timeout` at `useTradeTapeData.ts:213` aborts slow pages, throws, halts the chain mid-way without flipping `hasMore` — hence "page refresh fixes it".

Live repro: filter `tape_label contains 10Y` fired ~74 cursor pages, returned 14,701 rows from the server in <30s, only 4,323 of which matched the filter; chain still climbing toward 20k.

## Approach (chosen)

**A — server-side filter pushdown + scroll-anchor poll-merge.**

Two independent fixes addressing the two root causes. Either can ship without the other; both will ship on the same branch.

### A1. Server-side filter pushdown

Translate the `columnFilters` payload that the client already sends into parameterised SQL `WHERE` fragments inside `buildTapeQuery`. The cursor scan returns only matching rows, so the chain-load loop no longer drags down unfiltered pages.

#### Allowlist

Two field families:

| Family | Fields | SQL strategy |
|---|---|---|
| **Package columns** (live on the row directly) | `tape_label`, `total_risk`, `total_notional`, `weighted_fixed_rate`, `package_type`, `package_indicator`, `execution_start`, `other_lvl_reported` | direct `WHERE d.<col> <op> $n` |
| **Leg columns** (null at package level, walked via `legs_json`) | `platform_identifier`, `lifecycle_type` | `EXISTS (SELECT 1 FROM jsonb_array_elements(d.legs_json) l WHERE l->>'<col>' <op> $n)` |

`execution_start` is a special case — the filter compares against the NYC-localised display string (`M/D/YYYY HH:MM:SS`), not the raw ISO timestamp ([filter-utils.ts:11-20](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/filter-utils.ts)). Pushdown for timestamp fields is **NOT** included in the allowlist for v1 — it would require formatting in SQL and getting timezone semantics right under load. Timestamp filters fall through to the existing client-side path. Documented in the test pinning the allowlist.

#### Match modes

| Match mode | Text columns | Numeric columns |
|---|---|---|
| `CONTAINS` | `<col> ILIKE '%' \|\| $n \|\| '%'` (with `% _ \` escaping) | n/a (falls to client) |
| `NOT_CONTAINS` | `<col> NOT ILIKE '%' \|\| $n \|\| '%'` | n/a |
| `STARTS_WITH` | `<col> ILIKE $n \|\| '%'` | n/a |
| `ENDS_WITH` | `<col> ILIKE '%' \|\| $n` | n/a |
| `EQUALS` | `LOWER(<col>) = LOWER($n)` | `<col> = $n::numeric` |
| `NOT_EQUALS` | `LOWER(<col>) <> LOWER($n)` | `<col> <> $n::numeric` |
| `LESS_THAN` / `LESS_THAN_OR_EQUAL_TO` / `GREATER_THAN` / `GREATER_THAN_OR_EQUAL_TO` | n/a | `<col> < $n::numeric` etc. |
| `IN` | each value: `LOWER(<col>) = LOWER($n)` joined by `OR` | each value: `<col> = $n::numeric` joined by `OR` |

Mirrors `matchFilterValue` in `filter-utils.ts` so the SQL pushdown produces the same result set as the existing client-side path.

#### AND / OR within a field

Per-field operator (`AND` / `OR`) is consumed: each field's constraints are joined by its own operator and wrapped in parentheses; fields are joined by AND.

#### Cross-field operator

`columnFilterOp` is parsed but not used in v1 — every cross-field combination is AND, matching the current client-side behaviour. Open follow-up if traders ask for OR.

#### Defensive client-side filter retained

`displayRows` continues to apply the same filters client-side. Cheap when the rows array is already filter-tight, and means a malformed pushdown clause never silently shows wrong data — the server returns at most the matches; the client filters again to the same set.

#### Cache header

Today: cached on initial fetch only (no `cursor`/`since`). The `Cache-Control: s-maxage=15, stale-while-revalidate=60` header is keyed on the full URL including `columnFilters`, so column filters naturally produce separate cache entries. Since column filters are usually trader-specific and short-lived, **skip the cache header when columnFilters is non-empty** — same logic as cursor/since today. Documented in the route handler.

### A2. Scroll-anchor poll-merge

Add a scroll anchor in `TradeTapeTable` that fires before/after the rows array changes via polling:

1. Before each render where `displayRows` may change, capture the package_id of the row at the user's current top-visible position (`scrollTop / ROW_ESTIMATE_PX`).
2. After the new `displayRows` lands, find the same package_id, compute its new offset.
3. If the user is not already at the very top (`scrollTop > 0`), set `scrollTop` to `newOffset + (oldScrollTop - oldAnchorOffset)`.

In effect: rows shifting down because of poll-inserted rows above gets compensated by an equal scroll bump, so the anchor row stays under the cursor. Implementation lives entirely inside `TradeTapeTable`; the hook is unchanged.

If the user IS at top (`scrollTop === 0`), do not anchor — they want to see new prints arrive.

Edge cases:
- Anchor row was filtered out / removed: skip the bump (let the natural scroll position stand).
- First render after navigation: no anchor captured yet, skip.
- VirtualScroller may race with our `useLayoutEffect` setting scrollTop. Mitigation: use `scrollTo({ top, behavior: 'instant' })` and gate on `displayRows` reference change, not on every render.

## Constraints satisfied

| Constraint | How |
|---|---|
| Analytics dock keeps working | `package_id` stays the dataKey, `tape_label` stays the analytics bucket, `legs_json` complete, `selection.selected` reconciles by `package_id`, `focusedPackageId` flow unchanged. Server returns the same row shape — only rows get filtered, none get rewritten. |
| Polling can't stop | Polling cadence (30s) and the `?since=` request shape unchanged. |
| Manual link / orphan dedupe (`dedupeDuplicatePackages`) | Untouched. The merge order in `upsertRows` is unchanged. The dedupe runs over whatever rows the merge produces. |
| Cache header | Cursor/since path remains uncached. New rule: also skip the cache header when `columnFilters` is non-empty. Documented in the route. |
| Existing tests stay green | The `useTradeTapeData` build-query test pins "no filter params emitted by the hook" — that stays true; the hook still emits no filter params. The pushdown is consumed via the URL `columnFilters` param that the page (Next.js) attaches to the route, not via the hook. (See "wiring" note below.) |
| 20k autoload cap | Kept as defensive backstop for any non-allowlisted filter that falls through to client-side filtering. |

### Wiring note

`useTradeTapeData` does NOT need to know about column filters. The route's `columnFilters` param can be wired in two ways:

1. **Pass `columnFilters` queryString through to the hook** — the hook attaches it to every fetch URL (initial, cursor, since).
2. **Scope the route to honour the URL's `columnFilters` only on initial fetch from the page**.

We pick (1). The hook accepts a new optional `columnFilters` parameter (string — pre-serialised JSON). When present, every `fetchTape` call appends `&columnFilters=...`. When the param value changes, the hook resets and fetches fresh. The `useTradeTapeData buildQuery` test gets a new case for the new param.

## Test plan

**Server (route.logic.test.ts)** — extend with:
- New section `buildTapeQuery columnFilters pushdown` with cases per allowlisted column × match mode covering `tape_label CONTAINS / EQUALS / IN`, `total_risk LESS_THAN / GREATER_THAN_OR_EQUAL_TO`, `weighted_fixed_rate EQUALS`, `platform_identifier CONTAINS` (leg via EXISTS), `lifecycle_type EQUALS` (leg via EXISTS).
- Pin: `execution_start` filter is **not** pushed (timestamp display-string formatting deferred).
- Pin: SQL injection — special chars in the filter value are parametrised, not interpolated (verify by reading the params array, not the SQL string).
- Pin: cross-field AND (multiple fields all push their own clauses).
- Pin: per-field OR works (multiple constraints in one field with `OR` operator).
- Pin: empty / null filter values produce no clause and no params.

**Hook (useTradeTapeData.test.ts)** — extend with:
- `buildQuery` emits `columnFilters` query param when the hook is configured with it.
- A change in the `columnFilters` param resets `rows` and fires a fresh `replace=true` fetch (same shape as `params.limit` change).
- Polling (`?since=`) and cursor (`?cursor=...`) requests carry the same `columnFilters` param when set.

**Table (TradeTapeTable scroll anchor)** — new file `TradeTapeTable.scroll-anchor.test.tsx`:
- Pin: when `displayRows` extends with N new rows above the current anchor row and `scrollTop > 0`, scrollTop bumps by approximately `N × ROW_ESTIMATE_PX` so the anchor row stays under the cursor.
- Pin: when `scrollTop === 0`, no scroll bump.
- Pin: when the anchor row is no longer in `displayRows` (filtered out), no scroll bump.

**Browser verification (Phase 4)**:
- Repro Bug 1: scrollTop=2000 → poll fires → confirm visible row text under that pixel is unchanged.
- Repro Bug 2/4: apply filter `tape_label contains 10Y` → confirm network tab shows ONE filtered request, not 74 cursor pages.
- Repro Bug 3: apply filter, observe no premature stall — `hasMore=false` reached without page refresh.
- Smoke: row click → analytics dock opens → 3 tabs render → multi-row select → ManualLinksDialog opens with correct trade IDs.

## Build sequence

1. Server-side filter pushdown — `buildTapeQuery` extension, allowlist + match-mode tables, parametrised SQL. Tests against `route.logic`. Commit.
2. Cache-Control rule update — skip the cache header when `columnFilters` is non-empty. Tests in `route.ts` integration suite. Commit.
3. Hook wiring — `useTradeTapeData` accepts `columnFilters` as an optional param. Reset-on-change effect. Tests. Commit.
4. Page wiring — pass `useColumnFilters().queryString` slice for `columnFilters` into `useTradeTapeData`. Smoke tests. Commit.
5. Scroll-anchor poll-merge — `useScrollAnchor` hook in `TradeTapeTable`. Test against jsdom-mocked scroller. Commit.
6. Browser verification + before/after evidence captured. Open PR.

## Out of scope (deferred follow-ups)

- **Cursor tiebreaker** `(execution_start, package_id) DESC` — duplicate-timestamp page boundaries are rare at ms precision; defer.
- **Variable row height** — expanded `LegsSubTable` rows are taller than 40px. PrimeReact `VirtualScroller` doesn't natively support variable heights. The shake fix (scroll-anchor) compensates regardless of row height because it anchors by package_id, not by pixel offset.
- **Cross-field OR** in column filters — `columnFilterOp` parsed but not consumed.
- **Server-side timestamp-display-string filter** — would require Postgres `to_char(... AT TIME ZONE 'America/New_York', 'FMMM/FMDD/YYYY HH24:MI:SS')` matching with leading-zero stripping; defer until traders ask.

## Rollback

Server filter pushdown is gated by the request URL — if `columnFilters` is not present, the SQL produced by `buildTapeQuery` is byte-for-byte identical to today. To roll back the entire feature:

1. Revert the commits on this branch.

To roll back partial — drop server pushdown only:

1. Revert commits 1–4. The scroll-anchor commit (5) is independent and stays.

## Risks

- **Pushdown semantics drift from client semantics** — the SQL match must produce the same set as `matchFilterValue` for every (column, matchMode) pair. Mitigated by the defensive client-side filter still running on top, plus tests that match SQL output to a small known dataset client-side. If they ever diverge the client filter is the safety net.
- **EXISTS subquery cost** — leg-only fields use a per-row `jsonb_array_elements` expansion. This already exists in the `tenors` filter path today, so the cost profile is known. If load tests show pain, add a generated column on `packages_v2` that pre-aggregates leg attributes, or add a GIN index on `legs_json`.
- **Scroll-anchor jitter** — if the captured anchor row moves OUT of `displayRows` between poll and re-render (e.g. filtered out), there is a one-frame visual jump. Acceptable; documented in the test.
