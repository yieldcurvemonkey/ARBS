# USD Swaps Tape v2 — QA + Analytics Hardening Report

**Date:** 2026-04-25
**Branch:** `dashboard/qa-and-analytics-revamp`
**Page:** `http://localhost:3717/usd-swaps-v2`

## Summary

Multi-phase hardening pass on the USD swap tape v2 dashboard, the
analytics dock, and the supporting Postgres / Python ingest pipeline.

| Phase | Outcome |
|-------|---------|
| 1     | Top P0/P1 defects fixed — focused row tint restored, rarity tab survives sparse buckets, lifecycle pills cover OTHER, pagination cursor robust to bad timestamps, polling sort deterministic. |
| 2     | Analytics-dock routes cut over from `arbs_usd_swap_tape_legs_v1` → `_v2` with original-execution-timestamp ordering. Composite indexes added on (filter, ts) for rate_index_clean / tape_label / trade_type / tenor / canonical_underlier_key. AbortController + 60s result cache wired on all three analytics hooks. |
| 3     | Rarity tab: skeleton loading, localStorage prefs, empty-state copy, dark-theme contrast pass. |
| 4     | New `canonical_underlier_key` column persisted on the v2 leg table, pure-Python resolver in `SDRUtils/core/underlier_canonical.py`, materialized by `analytics.trade_tape.compute()`. Dashboard routes accept `groupBy=canonical`. Cache version bumped to `v6-canonical`. |

Test suites green:
- `pytest tests/test_underlier_canonical.py tests/test_sdr_primitives.py tests/test_sdr_lifecycle_state_machine.py tests/test_sdr_economic_classification.py tests/test_sdr_phase5_structural.py` → 147 passed
- `npm test -- --testPathPatterns=usd-swaps-tape-v2` → 265 passed, 4 skipped

## Phase 1 — Dashboard QA

### Severity legend

| Sev | Meaning |
|-----|---------|
| P0  | Blocker — page unusable / data wrong |
| P1  | Major — workflow blocked or visibly broken |
| P2  | Minor — cosmetic or edge case |
| P3  | Nice-to-have |

### Defects fixed (in-flight)

| ID | Severity | Area | Description | Fix |
|----|----------|------|-------------|-----|
| P2-04 | P0 | UsdSwapsTradeTape.tsx | `focus.focused?.package_id` always `undefined` (FocusedTrade has `id`, not `package_id`) → indigo focused-row tint never activated | Read `focus.focused?.id` |
| P0-01 | P0 | AnalyticsPanel + TradeRarityTab | Rarity tab silently hidden when `recency` was non-null but inner fields nullish | Drop the `&& rarity.recency` guard, render histogram + percentile rows unconditionally; per-card empty states for null recency sub-records |
| P0-04 | P0 | api/usd-swaps-tape-v2/route.ts | `toIsoString` echoed unparseable strings as `nextCursor`, breaking pagination | Return null instead |
| P0-03 | P0 | useTradeTapeData.ts | `localeCompare` on JS Date objects produced non-deterministic poll merge order | Coerce to ISO string before compare |
| P1-01 | P1 | constants.ts | `LIFECYCLE_ORDER` missing `OTHER` → rows whose lifecycle_mix only contains OTHER rendered no pill and were unfilterable | Add `OTHER` to the order |
| P1-09 | P1 | TradedLevelsTab.tsx | Hardcoded "47 in last 90d" sentinel | Removed |
| UX-01 | P2 | AnalyticsPanel | Trade Rarity tab badge showed "P50" before any fetch settled | Show `…` until `stats.count > 0` |
| UX-03 | P2 | TradedLevelsTab | No empty state when `extremes` returned 0 rows | Added empty-state copy |

### Defects deferred (follow-up issues)

| ID | Severity | Area | Description |
|----|----------|------|-------------|
| P0-05/06 | P0 | analytics hooks | No AbortController on `useAnalyticsTimeseries` / `useRarityData` / `useExtremesData` — race condition when trader rapidly clicks rows |  **Fixed in Phase 2 commit** (AbortController + 60s result cache) |
| P0-02 | P0 | rarity/route.ts | `bucketRank: null` when notional missing — surfaced as P0 in audit, partially mitigated by Phase 1 null-tolerant render in TradeRarityTab | Open follow-up: skip the `bucketRank` query when focusedNotional missing rather than building it then nulling |
| P1-02 | P1 | columns.tsx | `dataType="numeric"` filter on `weighted_fixed_rate` doesn't match CURVE/FLY rows where the rendered cell is a `"x% / y%"` string | Open follow-up: add a per-leg numeric range filter mode |
| P1-03 | P1 | TradeTapeTable.tsx | `selectedIds = new Set(...)` rebuilt on every render | Open follow-up: memoize |
| P1-05 | P1 | hooks | `SORT_FIELD_QUERY_KEY` collision between useColumnFilters + useTableControls | useTableControls is dead code — open follow-up to delete |
| P1-06 | P1 | useTradeTapeData | `fetchInFlight.current = true` can stick on a hung fetch | Open follow-up: AbortSignal.timeout(15_000) |
| P1-07 | P1 | ManualLinksDialog | `tradeIds.length < 2` guard counts legs not packages | Open follow-up |
| P1-08 | P1 | LegsSubTable | Audit reported summary row column misalignment — re-verified, the row has 16 cells matching 16 headers, audit was incorrect. No fix needed. |
| P2-07 | P2 | TimeseriesTab | CUSTOM range pill hard-codes a date string | Open follow-up: wire a date-picker |
| UX-02 | P2 | TradeRarityTab | Histogram metric toggle changes the label only | Open follow-up: re-bin by selected metric server-side |
| Misc | P3 | FocusedTradeBar | "Pin" button has no onClick | Open follow-up |

## Phase 2 — Timeseries Perf

### Targets

- INTRADAY 1D: ≤ 250 ms p50 cold
- DAILY_OHLC 1Y: ≤ 600 ms p50
- VOLUME 6M: ≤ 500 ms p50

### Indexes added (additive, idempotent)

```sql
-- _tape_schema_v2.py — applied on next ensure_schema() call
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_rate_idx_orig
  ON arbs_usd_swap_tape_legs_v2(rate_index_clean, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_tape_label_orig
  ON arbs_usd_swap_tape_legs_v2(tape_label, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_trade_type_orig
  ON arbs_usd_swap_tape_legs_v2(trade_type, original_execution_timestamp DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_tenor_orig
  ON arbs_usd_swap_tape_legs_v2(tenor_label, original_execution_timestamp DESC NULLS LAST);
ALTER TABLE arbs_usd_swap_tape_legs_v2
  ADD COLUMN IF NOT EXISTS canonical_underlier_key TEXT;
CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_canonical_orig
  ON arbs_usd_swap_tape_legs_v2(canonical_underlier_key, original_execution_timestamp DESC NULLS LAST);
```

### Other backend changes

- All analytics routes ordered/filtered on
  `COALESCE(original_execution_timestamp, execution_timestamp)` so β/γ
  NEWT-CLRG legs anchor on the alpha's original execution time per
  SDRUtils/CLAUDE.md "Timestamps" rule.
- Response caps tightened: daily 2000 rows, intraday 5000 ticks,
  rarity 50k samples.
- Cutover to `arbs_usd_swap_tape_legs_v2` (was `_v1`) — v1 is the
  rollback target; flip `LEGS_TABLE` in each route to revert.

### Frontend changes

- `useAnalyticsTimeseries`, `useRarityData`, `useExtremesData` each
  carry an AbortController per fetch. Stale fetches from a prior
  focused trade are cancelled before they overwrite state for the new
  one.
- `useAnalyticsTimeseries` caches results per `(bucket, view, range)`
  for 60s in module-level memory. Tab focus changes that flip
  view-only no longer re-issue identical SQL.

EXPLAIN ANALYZE benchmarks against a real Postgres instance are not
in this report — the worktree doesn't have credentialed DB access.
Run before/after with the new indexes against a clone of prod to
confirm the targets above.

## Phase 3 — Rarity UX

### Changes shipped

- localStorage persistence under
  `usd-swaps-tape-v2/rarity-prefs/v1` for basis / histogramMetric /
  primaryTol / sizeTol. Survives page refresh and bucket changes.
- Skeleton percentile rows render while the initial /rarity fetch is
  in flight (`bins.length === 0 && loading`). Replaces the previous
  layout-collapsing spinner.
- Empty-state copy when the focused bucket has zero samples in the
  90-day lookback. Explains the why (tenor too rare, doesn't print to
  the public tape, last print older than lookback) and tells the
  trader what to do (widen tolerance, pin, recheck after ingest).
- Per-recency-card empty states (Last similar, Frequency, Bucket
  rank, All-time records) so a sparse bucket no longer crashes the
  tab on null sub-records.
- Dark-theme contrast pass: ZONE_BG / ZONE_TEXT / ZONE_BORDER bumped
  saturation + lightness so the percentile bars and zone borders read
  distinctly at 11px on slate-950.

Histogram brushing is deferred to a follow-up — it requires
cross-component coordination (Rarity tab → URL columnFilters → tape
DataTable filter state) that is outside the scope of this branch.

## Phase 4 — Canonical underlier key

### Schema

- New column `canonical_underlier_key TEXT` on
  `arbs_usd_swap_tape_legs_v2` (additive ALTER, idempotent).
- Composite index
  `(canonical_underlier_key, original_execution_timestamp DESC NULLS LAST)`.

### Resolver

`SDRUtils/core/underlier_canonical.py` — `canonical_underlier_key(upi_underlier_name)`.

| Input variations | Canonical |
|------------------|-----------|
| USD-SOFR, USD-SOFR-COMPOUND, USD-SOFR-OIS, USD-SOFR-OIS Compound | `USD/SOFR-OIS/COMPOUND` |
| USD-SOFR CME Term | `USD/SOFR-TERM` |
| USD-Federal Funds (any of -H.15 / -OIS / -COMPOUND) | `USD/FED-FUNDS-OIS/COMPOUND` |
| USD-OBFR / USD-Overnight Bank Funding | `USD/OBFR-OIS/COMPOUND` |
| USD-BSBY (any tenor) | `USD/BSBY/IBOR` |
| USD-LIBOR (BBA / ICE / any tenor) | `USD/LIBOR/IBOR` |
| USD-ISDA-Swap Rate / USD-CMS | `USD/ISDA-CMS` |
| USD-SIFMA / USD-BMA | `USD/SIFMA-MUNI` |
| `<X> vs <Y>` basis | `USD/BASIS/<sortedX>+<sortedY>` |
| null / "" / nan | `UNKNOWN` |

### Ingest plumbing

- `LEG_COLUMNS` + `_LEG_TEXT_COLS` in
  `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` extended.
- `analytics.trade_tape._enrich_classification` materializes
  `canonical_underlier_key` alongside `rate_index_clean`.
- `TRADE_TAPE_CACHE_VERSION` bumped `v5-p5` → `v6-canonical` to
  invalidate cached pickles.

### Dashboard

- `analytics-timeseries`, `rarity`, `extremes`, `timeseries` routes
  accept `groupBy=canonical` with `value=USD/SOFR-OIS/COMPOUND`.
- Contract Jest test pinned in
  `dashboard/src/app/api/usd-swaps-tape-v2/__tests__/canonical-underlier-key.test.ts`.

### Backfill (operator action — not run on this branch)

```bash
conda run --no-capture-output -n stir python \
    SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py \
    --start-date 2026-04-01 --end-date 2026-04-23
```

After re-ingest, verify the SOFR-COMPOUND ↔ SOFR-OIS collapse:

```sql
SELECT canonical_underlier_key, COUNT(DISTINCT tape_label)
FROM arbs_usd_swap_tape_legs_v2
WHERE canonical_underlier_key = 'USD/SOFR-OIS/COMPOUND'
GROUP BY 1;
```

A single row with `COUNT > 1` confirms the collapse landed in prod.

### Tests added

- `tests/test_underlier_canonical.py` — 19 cases across SOFR-OIS,
  SOFR-Term, Fed Funds, OBFR, BSBY, LIBOR, ISDA-Swap Rate, SIFMA,
  basis pairs, idempotence, and null handling.
- Frontend Jest contract in
  `dashboard/src/app/api/usd-swaps-tape-v2/__tests__/canonical-underlier-key.test.ts`.

## Defect summary

See "Defects fixed (in-flight)" + "Defects deferred (follow-up issues)"
tables above. The deferred items are tagged with severity + a one-line
description and can be filed as separate tickets / PRs.
