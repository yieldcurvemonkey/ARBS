# USD Swaps Tape v2 — Trader Feedback Round 1

**Date:** 2026-04-16
**Target:** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**Trigger:** trader feedback on `UsdSwapsTradeTape.tsx`

## Feedback (verbatim)

1. Other payment amount, package transaction amount in expanded subtable.
2. Column filters not matching the one in swaption trade tape.
3. Rework the filters.
4. Better color coding.
5. Better package detection logic. **(On hold — out of scope this round.)**

## Summary

Four changes land this round:

| # | Change |
|---|--------|
| 1 | Surface per-leg `other_payment_amount` (OPA) and package-level `package_transaction_price` (PTP). New column `Other Lvl Reported` right of `Reported Lvl`. Expanded subtable gains a PTP header strip + per-leg OPA column. |
| 2 + 3 | Remove every hardcoded filter (FilterChips, fuzzy-search bar, AND/OR toggle, header flag chips, server-side filter params, methodology + flow-history header buttons). Replace with PrimeReact per-column filters on every column, adapted from `SwaptionTradeTape.tsx.bak` (custom fuzzy + timestamp filter elements). URL-sync preserved via an extended `useColumnFilters`. |
| 4 | Row background tinted by `package_structure` (Bloomberg muted palette). UNWIND red overrides any structure tint. Action lifecycle pill gets saturated per-action color. |

---

## 1. Data plumbing — OPA + PTP

### Raw fields (CFTC frame)

- `Other payment amount` (string/numeric, per-leg)
- `Other payment currency` (string)
- `Package transaction price` (string/numeric, package-level)
- `Package transaction price currency` (string)

### Python / DB layer

- **Ingest** (`SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`):
  - Parse `Other payment amount` → numeric on leg frame.
  - Parse `Package transaction price` → numeric, consolidated per `package_id` (`_consistent_str` / first-non-null pattern).
  - Carry through corresponding currency fields.
- **Schema** (`SDRUtils/_swappulse_scripts/_tape_schema.py`):
  - `arbs_usd_swap_tape_legs_v1` — add `other_payment_amount NUMERIC, other_payment_currency TEXT`.
  - `arbs_usd_swap_tape_packages_v1` — add `package_transaction_price NUMERIC, package_transaction_price_currency TEXT`.
  - Migration strategy: additive `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` (idempotent; zero-downtime).
- **Display view** `arbs_usd_swap_tape_display_v1`: rebuild to project new fields and include OPA/OPA-ccy in leg JSON passthrough.

### TypeScript layer

- `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts`:
  - `COLUMNS` adds `d.package_transaction_price`, `d.package_transaction_price_currency`.
  - (leg OPA flows via existing `d.legs_json` passthrough.)
- `SDRUtils/dashboard/src/features/sofr-swaps-tape/types/trade.types.ts` (shared parent):
  - `SofrSwapTapeLeg` gains `other_payment_amount?: number | null; other_payment_currency?: string | null`.
  - `SofrSwapTapeRow` gains `package_transaction_price?: number | null; package_transaction_price_currency?: string | null`.
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/trade.types.ts` inherits via extension.

### UI

- **New column `other_lvl_reported`** (position: right of `Reported Lvl`, width ~110px, mono `text-[11px]`):
  - Line 1: `OPA: <v1>, <v2>, …` — comma-joined non-null leg OPAs, signed, compact (`formatNotional(v, { compact: true, signed: true })`-style). `—` if all null.
  - Line 2: `PTP: <v>` — package value, signed, compact. `—` if null.
  - Currency suffix appended only when mixed with non-USD.
- **`LegsSubTable.tsx` changes:**
  - Header strip above `<table>` (inside the existing `div` panel):
    `Package Transaction Price: <formatted> <ccy>`.
    Hidden entirely when PTP is null.
  - New leg column `OPA` between `Rate` and `Flags`: right-aligned mono, compact signed.

### Tests

- `ingest_usdswaps_tape` unit test: synthetic raw frame → rows with OPA/PTP written correctly; nulls preserved.
- `columns.test.ts`: `other_lvl_reported` body renders stacked OPA/PTP, handles nulls, formats mixed currency.
- `LegsSubTable.test.ts`: PTP strip shows when present, hides on null; OPA column renders + formats.

---

## 2. Filter refactor (feedback #2 + #3)

### Delete

- `components/TradeTapeFilters/TradeTapeFilters.tsx` (global fuzzy search + AND/OR toggle + Reset).
- `components/TradeTapeFilters/FilterChips.tsx` (Venue/CCP/Index/Session chips).
- `components/TradeTapeHeader/FlagChips.tsx` usage in header (lifecycle flag chips).
- Header buttons for methodology + flow history.
- `hooks/useFlagFilters.ts` (entire file — no longer referenced).
- Server filter params in `hooks/useTradeTapeData.ts`: drop `flagFilters` query arg; fetch no longer filtered server-side.
- `utils/fuzzy.ts` once unreferenced (confirmed by grep before removal).

### Port + adapt from `SwaptionTradeTape.tsx.bak`

Target location: `components/TradeTapeTable/`.

- `filter-utils.ts`: `buildColumnFilterPayload`, `matchFilterMeta`, `matchFilterValue`, `hasActiveConstraints`, `getFilterDisplayLabel`, `isEmptyFilterValue`, `parseFilterNumber`, `DEFAULT_TEXT_MATCH_MODE`, `DEFAULT_NUMERIC_MATCH_MODE`.
- `TimestampColumnFilter.tsx`: from/to time-of-day filter element, bound to the `execution_start` column (mirrors bak behavior).
- `ActionColumnFilter.tsx`: multiselect of lifecycle enum values; replaces the removed header flag chips.
- Extend `hooks/useColumnFilters.ts` to URL-sync the full PrimeReact `DataTableFilterMeta` (constraint arrays + per-column AND/OR operator), plus sort state (`sortField`, `sortOrder`). Existing URL-serialization pattern stays; payload shape mirrors bak.

### Column wiring (`components/TradeTapeTable/columns.tsx`)

Every `<Column>` gains `filter` + `filterMatchMode` + `filterElement` props.

| Column | Match modes | Filter element |
|--------|-------------|----------------|
| `execution_start` | range | `<TimestampColumnFilter/>` |
| `action_label` | IN | `<ActionColumnFilter/>` |
| `platform_identifier` | CONTAINS / EQUALS | default text |
| `tape_label` | CONTAINS (fuzzy) | default text + custom match fn |
| `total_risk` / `total_notional` | numeric suite | default numeric |
| `weighted_fixed_rate` | numeric suite | default numeric |
| `other_lvl_reported` | CONTAINS | default text (matches OPA/PTP stringified) |

`DataTable` props: `filters`, `onFilter`, `filterDisplay="menu"`, `showFilterMenu`, `showAddButton`, `showFilterOperator`, `sortField`, `sortOrder`, `onSort`.

Global filtering is client-only on the materialized row set from `useTradeTapeData`.

### Orchestrator (`UsdSwapsTradeTape.tsx`)

- Remove: `flagFilters` hook, `FilterChips`, `fields` memo, `tapeQueryParams` with filter state.
- `useTradeTapeData({})` — empty params; fetch respects only pagination + as-of anchoring.
- `TradeTapeHeader` props shrink to `{ asOfDate, liveStatus, rows, onRefresh, onApplyClean, onResetClean, cleanTape }` — no filters.

### Tests

- `filter-utils.test.ts`: match mode matrix + constraint payload round-trips.
- `useColumnFilters.test.ts`: URL sync of full `DataTableFilterMeta` + sort, resets cleanly.
- `TimestampColumnFilter.test.ts`: from/to selection mutates filter state correctly.
- `TradeTapeTable.test.ts` (integration, light): fuzzy search on `tape_label`, numeric filter on DV01, timestamp filter on `execution_start`.

---

## 3. Color coding (feedback #4)

### Row background — structure-based, Bloomberg muted

Applied in `rowClassName` (`TradeTapeTable/columns.helpers.ts`):

| `package_structure` | Class |
|---------------------|-------|
| `OUTRIGHT` | `bg-slate-800/30` |
| `CURVE` | `bg-blue-900/30` |
| `FLY` | `bg-yellow-900/25` |
| `STRADDLE` | `bg-teal-900/30` |
| `STRANGLE` | `bg-fuchsia-900/25` |
| unknown / null | no class |

**Override:** when row is UNWIND (`row.is_unwind || lifecycle_type === 'UNWIND'` on any leg → existing `is_unwind_any` already computed), `rowClassName` returns `bg-red-900/30` **instead of** the structure class.

### Action pill — saturated per lifecycle

Replace `LIFECYCLE_TONES` in `constants.ts` with the following set (1px ring for definition):

| Lifecycle | Class string |
|-----------|--------------|
| `NEW_RISK` | `bg-emerald-500/30 text-emerald-100 ring-1 ring-emerald-400/40` |
| `UNWIND` | `bg-red-500/30 text-red-100 ring-1 ring-red-400/40` |
| `COMPRESSION` | `bg-sky-500/30 text-sky-100 ring-1 ring-sky-400/40` |
| `TERMINATION` | `bg-zinc-500/30 text-zinc-100 ring-1 ring-zinc-400/40` |
| `NOVATION` | `bg-violet-500/30 text-violet-100 ring-1 ring-violet-400/40` |
| `RESET_OPT` | `bg-amber-500/30 text-amber-100 ring-1 ring-amber-400/40` |
| `CORRECTION` | `bg-orange-500/30 text-orange-100 ring-1 ring-orange-400/40` |
| `CLEARING_TERM` | `bg-teal-500/30 text-teal-100 ring-1 ring-teal-400/40` |
| `EXERCISE_BORN` | `bg-pink-500/30 text-pink-100 ring-1 ring-pink-400/40` |
| `OTHER` | `bg-slate-500/30 text-slate-100 ring-1 ring-slate-400/40` |

### Tests

- `RowBadges.test.ts` updated for new pill class strings.
- New `columns.helpers.test.ts` (or extend existing): `rowClassName` returns correct tint per structure, UNWIND override wins.

---

## 4. Non-goals

- Feedback #5 (better package detection) — out of scope this round.
- Re-writing `SwaptionTradeTape.tsx.bak` or `.tsx` itself.
- Any change to `sofr-swaps-tape` feature beyond the shared type additions.
- Backfilling OPA/PTP for historical ingested days before the ingest upgrade (caller can re-run ingest for specific dates if needed).

## 5. Rollout

1. Schema migration (additive `ADD COLUMN IF NOT EXISTS`) — safe to deploy ahead of code.
2. Ingest update — back-populates new columns on next ingest pass.
3. Display view rebuild — idempotent `CREATE OR REPLACE VIEW`.
4. Frontend changes — shipped together as one feature branch.

No feature flag required; schema additions are additive, frontend consumes new fields with null-safe formatters.

---

**Status:** implemented on 68c6295 (2026-04-16). Feedback items 1–4 landed; #5 (package detection) remains on hold.
