# USD Swaps Tape v2 — Trader Feedback Round 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Land trader feedback items 1–4 on `UsdSwapsTradeTape.tsx`: expose OPA/PTP, rip out hardcoded filters in favor of per-column filters ported from `SwaptionTradeTape.tsx.bak`, refresh the color palette.

**Architecture:** Schema-additive backend change flows OPA (per-leg) + PTP (per-package) into the v2 display view; frontend surfaces them via a new stacked `Other Lvl Reported` column and an expanded subtable header strip + OPA leg column. The filter bar, filter chips, and lifecycle flag chips are deleted; replaced by PrimeReact per-column filters wired through a ported `filter-utils.ts` + custom `TimestampColumnFilter` / `ActionColumnFilter`, URL-synced via an extended `useColumnFilters`. Row color already keys off `package_structure` with UNWIND override — we refresh the `LIFECYCLE_TONES` pill palette for saturation.

**Tech Stack:** Next.js (App Router) + React + TypeScript + PrimeReact DataTable for the dashboard; Python + pandas + Postgres for ingest/schema.

**Design doc:** `docs/plans/2026-04-16-usd-swaps-tape-v2-trader-feedback-design.md`

---

## Phase A — Backend schema + ingest

### Task 1: Additive schema migration for OPA + PTP

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/_tape_schema.py` (LEGS_TABLE + PACKAGES_TABLE DDL blocks)

**Step 1: Add OPA columns to legs table DDL**

In the `CREATE TABLE IF NOT EXISTS {LEGS_TABLE}` block, add just before the flag columns:

```python
    other_payment_amount NUMERIC,
    other_payment_currency TEXT,
```

**Step 2: Add PTP columns to packages table DDL**

In the `CREATE TABLE IF NOT EXISTS {PACKAGES_TABLE}` block, add near `package_transaction_spread NUMERIC,`:

```python
    package_transaction_price NUMERIC,
    package_transaction_price_currency TEXT,
```

**Step 3: Add idempotent ALTERs for live tables**

At the bottom of the migration block (or wherever post-CREATE ALTERs live), append:

```python
    ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS other_payment_amount NUMERIC;
    ALTER TABLE {LEGS_TABLE} ADD COLUMN IF NOT EXISTS other_payment_currency TEXT;
    ALTER TABLE {PACKAGES_TABLE} ADD COLUMN IF NOT EXISTS package_transaction_price NUMERIC;
    ALTER TABLE {PACKAGES_TABLE} ADD COLUMN IF NOT EXISTS package_transaction_price_currency TEXT;
```

**Step 4: Rebuild display view**

Locate the `CREATE OR REPLACE VIEW {DISPLAY_VIEW}` SQL. Add to the SELECT projection:
- From packages: `p.package_transaction_price, p.package_transaction_price_currency`
- From legs (into legs_json agg): `l.other_payment_amount, l.other_payment_currency`

**Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/_tape_schema.py
git commit -m "feat(usd-swaps-tape-v2): schema for OPA + PTP fields

Adds other_payment_amount/currency to legs table and
package_transaction_price/currency to packages table. Idempotent
ADD COLUMN IF NOT EXISTS migrations + display view projection."
```

---

### Task 2: Ingest OPA from raw frame

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`

**Step 1: Locate the raw-column → leg-column mapping**

Find the section that normalizes leg-level fields from the raw CFTC frame (search for `Floating rate day count convention` or similar column references).

**Step 2: Add OPA extraction**

Next to existing per-leg field extractions, add:

```python
df["other_payment_amount"] = pd.to_numeric(
    df.get("Other payment amount", pd.Series(dtype="object")).astype(str).str.replace(",", ""),
    errors="coerce",
)
df["other_payment_currency"] = df.get("Other payment currency", pd.Series(dtype="object")).astype("string").where(df.get("Other payment currency").notna(), None)
```

Mirror the coerce-and-null pattern used by other numeric leg fields in the same file.

**Step 3: Add OPA to legs INSERT column list**

Find `_LEG_NUM_COLS` (or equivalent list controlling what gets written to `arbs_usd_swap_tape_legs_v1`) and add `"other_payment_amount"`. Add `"other_payment_currency"` to the corresponding string-column tuple.

**Step 4: Run ingest unit tests**

Run: `pytest SDRUtils/_swappulse_scripts/tests/test_ingest_usdswaps_tape.py -v` (path may differ — search for the test module under `SDRUtils/` if so).
Expected: PASS (no new test yet, existing ones should still pass).

**Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py
git commit -m "feat(usd-swaps-tape-v2): ingest other_payment_amount per leg"
```

---

### Task 3: Aggregate + ingest PTP at package level

**Files:**
- Modify: `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`

**Step 1: Add package-level PTP extraction**

In the per-group aggregation block (look for where `package_structure`, `package_type` are built — around the `_package_structure_label` usage near line 619), add:

```python
            "package_transaction_price": _consistent_num(g, "Package transaction price"),
            "package_transaction_price_currency": _consistent_str(g, "Package transaction price currency"),
```

**Step 2: Add `_consistent_num` helper if missing**

Search for `_consistent_num` — if absent, add next to `_consistent_str`:

```python
def _consistent_num(group: pd.DataFrame, col: str) -> float | None:
    if col not in group.columns:
        return None
    vals = pd.to_numeric(
        group[col].astype(str).str.replace(",", ""),
        errors="coerce",
    ).dropna().unique().tolist()
    if len(vals) == 1:
        return float(vals[0])
    if len(vals) > 1:
        return float(vals[0])  # fall back to first value on disagreement
    return None
```

**Step 3: Add PTP to packages INSERT column list**

Ensure `"package_transaction_price"` and `"package_transaction_price_currency"` appear in the packages-table column list used by the INSERT / upsert.

**Step 4: Run ingest tests**

Run: `pytest SDRUtils/_swappulse_scripts/ -v -k usdswaps_tape`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py
git commit -m "feat(usd-swaps-tape-v2): ingest package_transaction_price"
```

---

## Phase B — TypeScript types + DB layer

### Task 4: Extend shared SOFR tape types

**Files:**
- Modify: `SDRUtils/dashboard/src/features/sofr-swaps-tape/types/trade.types.ts`

**Step 1: Extend `SofrSwapTapeLeg`**

Add to the type definition:

```typescript
  other_payment_amount?: number | null
  other_payment_currency?: string | null
```

**Step 2: Extend `SofrSwapTapeRow`**

Add to the row type:

```typescript
  package_transaction_price?: number | null
  package_transaction_price_currency?: string | null
```

**Step 3: Run type check**

Run: `cd SDRUtils/dashboard && npx tsc --noEmit`
Expected: PASS (new optional fields don't break existing callers).

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/sofr-swaps-tape/types/trade.types.ts
git commit -m "feat(sofr-swaps-tape): OPA/PTP type fields"
```

---

### Task 5: Add PTP columns to v2 DB SELECT

**Files:**
- Modify: `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts`

**Step 1: Add new columns to COLUMNS list**

In the `COLUMNS` array, after `'d.package_transaction_spread',`, add:

```typescript
  'd.package_transaction_price',
  'd.package_transaction_price_currency',
```

Leg OPA flows via existing `d.legs_json` passthrough — no separate column needed if the display view aggregates legs.

**Step 2: Run existing resolver test**

Run: `cd SDRUtils/dashboard && npx vitest run src/lib/usd-swaps-tape-v2`
Expected: PASS.

**Step 3: Commit**

```bash
git add SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts
git commit -m "feat(usd-swaps-tape-v2): select PTP from display view"
```

---

## Phase C — OPA/PTP UI

### Task 6: Formatter for stacked OPA cell

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/format.ts`
- Test: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/format.test.ts`

**Step 1: Write failing tests for `formatOtherLvl`**

Append to `format.test.ts`:

```typescript
import { formatOtherLvl } from '../format'

describe('formatOtherLvl', () => {
  it('returns em-dashes when OPA + PTP both null', () => {
    const result = formatOtherLvl({ legOpa: [null, null], ptp: null })
    expect(result.opaLine).toBe('OPA: —')
    expect(result.ptpLine).toBe('PTP: —')
  })
  it('stacks non-null leg OPAs comma-separated', () => {
    const result = formatOtherLvl({ legOpa: [15627.6, null, -2100], ptp: -671880 })
    expect(result.opaLine).toBe('OPA: 15.6k, -2.1k')
    expect(result.ptpLine).toBe('PTP: -671.9k')
  })
  it('appends currency suffix only on non-USD values', () => {
    const result = formatOtherLvl({
      legOpa: [15627.6],
      ptp: -671880,
      opaCurrency: ['EUR'],
      ptpCurrency: 'USD',
    })
    expect(result.opaLine).toBe('OPA: 15.6k EUR')
    expect(result.ptpLine).toBe('PTP: -671.9k')
  })
})
```

**Step 2: Run test to verify it fails**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/utils/__tests__/format.test.ts -t formatOtherLvl`
Expected: FAIL (function not defined).

**Step 3: Implement `formatOtherLvl`**

In `utils/format.ts`:

```typescript
export function formatOtherLvl(input: {
  legOpa: Array<number | null | undefined>
  ptp: number | null | undefined
  opaCurrency?: Array<string | null | undefined>
  ptpCurrency?: string | null | undefined
}): { opaLine: string; ptpLine: string } {
  const opaParts: string[] = []
  input.legOpa.forEach((v, i) => {
    if (v === null || v === undefined) return
    const ccy = input.opaCurrency?.[i]
    const formatted = formatNotional(v, { compact: true, signed: true })
    opaParts.push(ccy && ccy !== 'USD' ? `${formatted} ${ccy}` : formatted)
  })
  const opaLine = opaParts.length ? `OPA: ${opaParts.join(', ')}` : 'OPA: —'

  let ptpLine: string
  if (input.ptp === null || input.ptp === undefined) {
    ptpLine = 'PTP: —'
  } else {
    const formatted = formatNotional(input.ptp, { compact: true, signed: true })
    ptpLine =
      input.ptpCurrency && input.ptpCurrency !== 'USD'
        ? `PTP: ${formatted} ${input.ptpCurrency}`
        : `PTP: ${formatted}`
  }

  return { opaLine, ptpLine }
}
```

If `formatNotional` doesn't accept `signed: true`, extend it in the same commit (narrow, obvious change) or compose with a sign prefix manually.

**Step 4: Run test to verify it passes**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/utils/__tests__/format.test.ts -t formatOtherLvl`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/format.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/format.test.ts
git commit -m "feat(usd-swaps-tape-v2): formatOtherLvl helper"
```

---

### Task 7: `Other Lvl Reported` column

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts` (COLUMN_DEFS)

**Step 1: Write failing render test**

Add to `columns.test.ts`:

```typescript
it('renders stacked OPA/PTP cell for the other_lvl column', () => {
  const { container } = render(...) // render table with fixture row that has legs with OPA and a PTP
  const cell = container.querySelector('[data-testid="other-lvl-cell"]')
  expect(cell?.textContent).toContain('OPA: 15.6k')
  expect(cell?.textContent).toContain('PTP: -671.9k')
})
```

Use existing fixture conventions in the test file; mirror the `renders reported lvl` test structure.

**Step 2: Run test to verify it fails**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts -t "other_lvl"`
Expected: FAIL.

**Step 3: Add column to `getColumns`**

In `columns.tsx`, after the `rate` column push:

```typescript
<Column
  key="other_lvl"
  field="other_lvl_reported"
  filterField="other_lvl_reported"
  filter
  header={renderHeader('Other Lvl')}
  body={(row: UsdSwapTapeRow) => {
    const legs = row.legs_json ?? []
    const lines = formatOtherLvl({
      legOpa: legs.map((l) => l.other_payment_amount ?? null),
      opaCurrency: legs.map((l) => l.other_payment_currency ?? null),
      ptp: row.package_transaction_price ?? null,
      ptpCurrency: row.package_transaction_price_currency ?? null,
    })
    return (
      <div data-testid="other-lvl-cell" className="flex flex-col font-mono text-[11px] text-gray-200">
        <span>{lines.opaLine}</span>
        <span>{lines.ptpLine}</span>
      </div>
    )
  }}
  style={{ width: 110 }}
/>,
```

Add `import { formatOtherLvl } from '../../utils/format'` at top.

**Step 4: Add COLUMN_DEF entry**

In `constants.ts` `COLUMN_DEFS`, append:

```typescript
  { key: 'other_lvl', header: 'Other Lvl', width: 110 },
```

**Step 5: Run test to verify it passes**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts`
Expected: PASS.

**Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts
git commit -m "feat(usd-swaps-tape-v2): add Other Lvl column with OPA/PTP stack"
```

---

### Task 8: PTP header strip + OPA leg column in LegsSubTable

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/LegsSubTable.test.ts`

**Step 1: Write failing tests**

Add:

```typescript
it('renders package transaction price header strip when present', () => {
  const row = { ...baseRow, package_transaction_price: -671880, package_transaction_price_currency: 'USD' }
  const { getByText } = render(<LegsSubTable row={row} />)
  expect(getByText(/Package Transaction Price/i)).toBeTruthy()
  expect(getByText(/-671.9k/)).toBeTruthy()
})
it('omits the PTP strip when null', () => {
  const row = { ...baseRow, package_transaction_price: null }
  const { queryByText } = render(<LegsSubTable row={row} />)
  expect(queryByText(/Package Transaction Price/i)).toBeNull()
})
it('renders per-leg OPA column', () => {
  const row = { ...baseRow, legs_json: [{ ...baseLeg, other_payment_amount: 15627.6 }] }
  const { container } = render(<LegsSubTable row={row} />)
  expect(container.textContent).toContain('15.6k')
})
```

**Step 2: Run test to verify it fails**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/LegsSubTable.test.ts`
Expected: 3 FAIL.

**Step 3: Implement PTP strip**

At the top of the returned JSX, just inside the outer `<div>`, before the `Leg Details` label:

```tsx
{row.package_transaction_price != null ? (
  <div className="mb-2 flex items-baseline gap-2 text-[10px] uppercase tracking-wide text-slate-400">
    <span>Package Transaction Price</span>
    <span className="font-mono text-[12px] text-slate-100">
      {formatNotional(row.package_transaction_price, { compact: true, signed: true })}
      {row.package_transaction_price_currency && row.package_transaction_price_currency !== 'USD'
        ? ` ${row.package_transaction_price_currency}`
        : ''}
    </span>
  </div>
) : null}
```

**Step 4: Add OPA column to leg table**

In `<thead>`, between `<th>Rate</th>` and `<th>Flags</th>`:

```tsx
<th className="px-2 py-1 text-right">OPA</th>
```

In `<tbody>` row, corresponding position:

```tsx
<td className="whitespace-nowrap px-2 py-1 text-right font-mono">
  {formatNotional(leg.other_payment_amount ?? null, { compact: true, signed: true })}
</td>
```

Update the empty-state `colSpan={13}` to `colSpan={14}`.

**Step 5: Run tests to verify pass**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/LegsSubTable.test.ts`
Expected: PASS.

**Step 6: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/LegsSubTable.test.ts
git commit -m "feat(usd-swaps-tape-v2): subtable surfaces PTP + per-leg OPA"
```

---

## Phase D — Filter refactor: teardown

### Task 9: Remove server-side filter params from data hook

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeTapeData.test.ts`

**Step 1: Strip `flagFilters` param from `useTradeTapeData`**

- Remove `flagFilters` from the hook's param type and from the query-string builder.
- Query string now depends only on pagination + date anchor.

**Step 2: Update existing test**

Remove any test assertions that pass `flagFilters` in query params; they should no longer appear in the outbound URL.

**Step 3: Run tests**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeTapeData.test.ts`
Expected: PASS.

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useTradeTapeData.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useTradeTapeData.test.ts
git commit -m "refactor(usd-swaps-tape-v2): drop server-side flag filter params"
```

---

### Task 10: Delete FilterChips, TradeTapeFilters, useFlagFilters

**Files:**
- Delete: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeFilters/FilterChips.tsx`
- Delete: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeFilters/TradeTapeFilters.tsx`
- Delete: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFlagFilters.ts`
- Delete: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useFlagFilters.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/index.ts` (drop re-export)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx` (drop imports + usage)

**Step 1: Delete files**

```bash
git rm \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeFilters/FilterChips.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeFilters/TradeTapeFilters.tsx \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFlagFilters.ts \
  SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useFlagFilters.test.ts
```

**Step 2: Drop `useFlagFilters` from hooks index**

In `hooks/index.ts`, remove the `useFlagFilters` re-export.

**Step 3: Strip usage from `UsdSwapsTradeTape.tsx`**

- Remove `useFlagFilters` import + call.
- Remove `FilterChips` import + render.
- Remove `fields` memo + `handleFilterByLifecycle`.
- Simplify `tapeQueryParams` to `{}` or drop entirely.
- Pass through only non-filter props to `TradeTapeHeader` (refresh, live status, clean-tape toggle). See Task 11 for header props.

**Step 4: Run typecheck + tests**

Run: `cd SDRUtils/dashboard && npx tsc --noEmit && npx vitest run src/features/usd-swaps-tape-v2`
Expected: PASS.

**Step 5: Commit**

```bash
git add -A SDRUtils/dashboard/src/features/usd-swaps-tape-v2
git commit -m "refactor(usd-swaps-tape-v2): delete hardcoded filter chips + search bar"
```

---

### Task 11: Slim down TradeTapeHeader

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeHeader/TradeTapeHeader.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeHeader/__tests__/TradeTapeHeader.test.ts`

**Step 1: Update header props + render**

- Drop `onOpenFlowHistory`, `onOpenMethodology`, `onToggleLifecycle`, `onFilterByLifecycle`, `flagFilters` from props.
- Remove `FlagChips` render + import.
- Keep: `asOfDate`, `liveStatus`, `rows`, `onRefresh`, `onApplyClean`, `onResetClean`.

**Step 2: Update test fixtures**

Strip removed props from test harness; add assertion that FlagChips no longer renders, and methodology/flow-history buttons are absent.

**Step 3: Remove callers in orchestrator**

In `UsdSwapsTradeTape.tsx`, remove the deleted props when rendering `<TradeTapeHeader>`. Delete `activeModal` support for `'methodology'` and `'flow-history'` (still keep `'timeseries'` and `'links'` — those are triggered elsewhere).

Re-check: `TimeseriesChart` + `FlowHistoryGrid` + `UsdSwapsMethodologyModal` JSX at bottom of component. If no caller opens them anymore, drop the JSX + imports.

**Step 4: Run tests**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeHeader`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2
git commit -m "refactor(usd-swaps-tape-v2): slim TradeTapeHeader to refresh + clean-tape only"
```

---

## Phase E — Filter refactor: port from bak

### Task 12: Port filter-utils.ts

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/filter-utils.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/filter-utils.test.ts`

**Step 1: Copy functions from bak**

Source: `SDRUtils/dashboard/src/components/SwaptionTradeTape.tsx.bak` lines ~460–960.

Port verbatim into `filter-utils.ts` (named exports, no default export):

- `DEFAULT_TEXT_MATCH_MODE`
- `DEFAULT_NUMERIC_MATCH_MODE`
- `isEmptyFilterValue`
- `parseFilterNumber`
- `matchFilterValue`
- `matchFilterMeta`
- `hasActiveConstraints`
- `buildColumnFilterPayload`
- `getFilterDisplayLabel`

Drop any imports the bak file uses for React components — this file is pure logic.

**Step 2: Write tests (adapted from swaption patterns)**

Cover the essentials:

```typescript
describe('matchFilterValue', () => {
  it('returns true for empty filter value', () => { ... })
  it('CONTAINS matches substring case-insensitive', () => { ... })
  it('GREATER_THAN_OR_EQUAL_TO works on numbers', () => { ... })
})

describe('matchFilterMeta', () => {
  it('AND operator requires all constraints to pass', () => { ... })
  it('OR operator requires any constraint to pass', () => { ... })
})

describe('buildColumnFilterPayload', () => {
  it('returns empty object when no active constraints', () => { ... })
  it('serializes constraint arrays', () => { ... })
})
```

**Step 3: Run tests to verify pass**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/filter-utils.test.ts`
Expected: PASS.

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/filter-utils.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/filter-utils.test.ts
git commit -m "feat(usd-swaps-tape-v2): port filter-utils from SwaptionTradeTape"
```

---

### Task 13: Port TimestampColumnFilter

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TimestampColumnFilter.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/TimestampColumnFilter.test.tsx`

**Step 1: Locate bak component**

Source: grep `SDRUtils/dashboard/src/components/SwaptionTradeTape.tsx.bak` for `TimestampColumnFilter` (or equivalent — look for the time-of-day from/to filter used on `execution_timestamp`).

**Step 2: Port component**

Copy the component into the new file. Remove any swaption-specific imports; bring along the minimal PrimeReact dependencies it needs (`Calendar`, `InputText`, etc.). Preserve the `filterCallback` contract.

**Step 3: Write smoke test**

```typescript
it('calls filterCallback on from/to change', () => {
  const cb = vi.fn()
  render(<TimestampColumnFilter value={null} filterCallback={cb} />)
  fireEvent.change(screen.getByLabelText(/from/i), { target: { value: '09:30' } })
  expect(cb).toHaveBeenCalled()
})
```

**Step 4: Run test**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/TimestampColumnFilter.test.tsx`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TimestampColumnFilter.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/TimestampColumnFilter.test.tsx
git commit -m "feat(usd-swaps-tape-v2): TimestampColumnFilter"
```

---

### Task 14: ActionColumnFilter

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/ActionColumnFilter.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/ActionColumnFilter.test.tsx`

**Step 1: Write failing test**

```typescript
it('renders lifecycle checkboxes + calls filterCallback with selection', () => {
  const cb = vi.fn()
  render(<ActionColumnFilter value={null} filterCallback={cb} />)
  fireEvent.click(screen.getByLabelText(/UNWIND/i))
  expect(cb).toHaveBeenCalledWith(['UNWIND'])
})
```

**Step 2: Implement component**

Simple `MultiSelect` over `LIFECYCLE_ORDER` with `LIFECYCLE_LABELS` display. Emits an array of selected lifecycle types; downstream filter uses `FilterMatchMode.IN`.

```typescript
import { MultiSelect } from 'primereact/multiselect'
import { LIFECYCLE_ORDER, LIFECYCLE_LABELS } from '../../constants'

export function ActionColumnFilter({ value, filterCallback }: { value: string[] | null; filterCallback: (v: string[]) => void }) {
  return (
    <MultiSelect
      value={value ?? []}
      options={LIFECYCLE_ORDER.map((k) => ({ value: k, label: LIFECYCLE_LABELS[k] }))}
      optionLabel="label"
      optionValue="value"
      onChange={(e) => filterCallback(e.value)}
      placeholder="Lifecycle"
      className="text-[11px]"
    />
  )
}
```

**Step 3: Run test**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/ActionColumnFilter.test.tsx`
Expected: PASS.

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/ActionColumnFilter.tsx SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/ActionColumnFilter.test.tsx
git commit -m "feat(usd-swaps-tape-v2): ActionColumnFilter for lifecycle multi-select"
```

---

### Task 15: Extend useColumnFilters for full FilterMeta + sort

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.ts`
- Modify: existing tests under `hooks/__tests__/useColumnFilters.test.ts` (create if missing)

**Step 1: Write failing test**

```typescript
it('round-trips DataTableFilterMeta through URL', () => {
  const { result } = renderHook(() => useColumnFilters())
  act(() => result.current.setFilters({
    tape_label: { value: '5Y', matchMode: FilterMatchMode.CONTAINS },
    total_risk: {
      operator: FilterOperator.AND,
      constraints: [{ value: 1000, matchMode: FilterMatchMode.GREATER_THAN }],
    },
  }))
  expect(window.location.search).toContain('tape_label')
  expect(window.location.search).toContain('total_risk')
  const { result: next } = renderHook(() => useColumnFilters())
  expect(next.current.filters.tape_label.value).toBe('5Y')
})

it('round-trips sort field + order', () => { ... })
```

**Step 2: Run test to verify fail**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/hooks/__tests__/useColumnFilters.test.ts`
Expected: FAIL.

**Step 3: Implement URL-sync**

Extend the hook to:
- Accept `filters: DataTableFilterMeta`, `sortField: string | null`, `sortOrder: 1 | -1 | null`.
- Serialize to URL using `buildColumnFilterPayload` (ported in Task 12) for filter payload and discrete `sort_field` / `sort_order` params.
- On mount, hydrate from URL (use existing `useSearchParams`).
- Returns `{ filters, setFilters, sortField, sortOrder, setSort, reset }`.

Drop the global fuzzy + operator state from this hook — those belonged to the removed filter bar.

**Step 4: Run tests**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/hooks/__tests__/useColumnFilters.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useColumnFilters.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useColumnFilters.test.ts
git commit -m "feat(usd-swaps-tape-v2): URL-sync full DataTableFilterMeta + sort"
```

---

### Task 16: Wire filters into columns + DataTable

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx`
- Modify: column tests

**Step 1: Update `getColumns` signature**

Accept `filters: DataTableFilterMeta`; each `<Column>` gets the right `filterMatchMode`, `showFilterMenu`, `showFilterOperator`, and `filterElement` per the design-doc table.

Concrete mapping:
- `execution_start` → `filterElement={<TimestampColumnFilter …/>}`, `dataType="date"`, `filterMatchMode={FilterMatchMode.BETWEEN}`.
- `action_label` → `filterElement={<ActionColumnFilter …/>}`, `filterMatchMode={FilterMatchMode.IN}`.
- `platform_identifier`, `tape_label` → default text, `filterMatchMode={FilterMatchMode.CONTAINS}`, `showFilterMenu`, `showAddButton`.
- Numeric columns (`total_risk`, `total_notional`, `weighted_fixed_rate`) → `dataType="numeric"`, default numeric, `showFilterOperator`.
- `other_lvl_reported` → `dataType="text"`, `filterMatchMode={FilterMatchMode.CONTAINS}`.

**Step 2: Wire DataTable in `TradeTapeTable.tsx`**

- Read filter/sort from `useColumnFilters`.
- `<DataTable>` props:
  - `filters={filters}` `onFilter={(e) => setFilters(e.filters)}`
  - `filterDisplay="menu"` (or `"row"` if bak used that — match bak)
  - `sortField={sortField}` `sortOrder={sortOrder}` `onSort={(e) => setSort(e.sortField, e.sortOrder)}`
- Add a `globalFilterMatchMode` fallback that runs `matchFilterMeta` on every column's `filterField` (for columns with custom match functions).

**Step 3: Run tests**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable`
Expected: PASS.

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable
git commit -m "feat(usd-swaps-tape-v2): per-column filters on every column"
```

---

### Task 17: Remove dangling refs

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/fuzzy.ts` (delete if unreferenced)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/fuzzy.test.ts` (delete with it)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx` (final cleanup)

**Step 1: Grep for fuzzy + flag references**

Run: `grep -rn "useFlagFilters\|FilterChips\|TradeTapeFilters\|fuzzyScore" SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
Expected: either no matches, or only the files to delete.

**Step 2: Delete unused**

```bash
git rm SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/fuzzy.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/fuzzy.test.ts
```

(If fuzzy is still referenced by the new custom `tape_label` match fn, keep it — but then ensure its test file still passes.)

**Step 3: Final orchestrator cleanup**

Make sure `UsdSwapsTradeTape.tsx` is tight: only renders `TradeTapeHeader` + `TradeTapeTable` + any preserved modals.

**Step 4: Run full feature test suite**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2`
Expected: PASS.

**Step 5: Commit**

```bash
git add -A
git commit -m "chore(usd-swaps-tape-v2): prune unused fuzzy utility"
```

---

## Phase F — Color coding

### Task 18: Saturated lifecycle pill palette

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.test.ts`

**Step 1: Write failing test**

In `RowBadges.test.ts`, assert new class strings:

```typescript
it('UNWIND pill uses red-500 saturated palette', () => {
  const { container } = render(<LifecyclePills row={{ ...baseRow, is_unwind: true }} />)
  const pill = container.querySelector('[aria-label*="UNWIND"]') ?? container.firstChild
  expect((pill as HTMLElement).className).toMatch(/bg-red-500\/30/)
})
```

**Step 2: Run test to verify fail**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.test.ts`
Expected: FAIL.

**Step 3: Update `LIFECYCLE_TONES`**

In `constants.ts`, replace the object with:

```typescript
export const LIFECYCLE_TONES: Record<LifecycleType, string> = {
  NEW_RISK: 'bg-emerald-500/30 text-emerald-100 ring-1 ring-emerald-400/40',
  UNWIND: 'bg-red-500/30 text-red-100 ring-1 ring-red-400/40',
  COMPRESSION: 'bg-sky-500/30 text-sky-100 ring-1 ring-sky-400/40',
  TERMINATION: 'bg-zinc-500/30 text-zinc-100 ring-1 ring-zinc-400/40',
  NOVATION: 'bg-violet-500/30 text-violet-100 ring-1 ring-violet-400/40',
  RESET_OPT: 'bg-amber-500/30 text-amber-100 ring-1 ring-amber-400/40',
  CORRECTION: 'bg-orange-500/30 text-orange-100 ring-1 ring-orange-400/40',
  CLEARING_TERM: 'bg-teal-500/30 text-teal-100 ring-1 ring-teal-400/40',
  EXERCISE_BORN: 'bg-pink-500/30 text-pink-100 ring-1 ring-pink-400/40',
  OTHER: 'bg-slate-500/30 text-slate-100 ring-1 ring-slate-400/40',
}
```

**Step 4: Run test to verify pass**

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.test.ts`
Expected: PASS.

**Step 5: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/RowBadges.test.ts
git commit -m "feat(usd-swaps-tape-v2): saturated lifecycle pill palette"
```

---

### Task 19: Confirm row-background palette + UNWIND override

**Files:**
- Review: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.helpers.ts` (existing `rowClassName`)
- Modify if needed: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts` `TRADE_TYPE_ROW_TONES`

**Step 1: Visual diff vs design**

Existing `TRADE_TYPE_ROW_TONES`:

| Key | Current | Design spec |
|-----|---------|-------------|
| OUTRIGHT | `!bg-gray-800/50` | `!bg-slate-800/30` |
| CURVE | `!bg-sky-900/30` | `!bg-blue-900/30` |
| FLY | `!bg-indigo-900/30` | `!bg-yellow-900/25` |
| STRADDLE | (missing) | `!bg-teal-900/30` |
| STRANGLE | (missing) | `!bg-fuchsia-900/25` |

Update to match design. Keep other trade-type keys (SPREADOVER etc.) as-is; those are existing USD conventions not in feedback scope.

**Step 2: Write test for STRADDLE / STRANGLE**

Extend `columns.helpers.test.ts` (create if missing):

```typescript
it('STRADDLE rows get teal-900 tint', () => {
  const row = { ...baseRow, package_type: 'STRADDLE' } as UsdSwapTapeRow
  expect(rowClassName(row)).toContain('!bg-teal-900/30')
})
it('UNWIND overrides structure tint with red', () => {
  const row = { ...baseRow, package_type: 'STRADDLE', is_unwind: true } as UsdSwapTapeRow
  expect(rowClassName(row)).toContain('!bg-red-900/40')
})
```

**Step 3: Run test + update constants**

Update constants per the diff above.

Run: `cd SDRUtils/dashboard && npx vitest run src/features/usd-swaps-tape-v2/components/TradeTapeTable`
Expected: PASS.

**Step 4: Commit**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.helpers.test.ts
git commit -m "feat(usd-swaps-tape-v2): STRADDLE/STRANGLE row tints, align Bloomberg muted palette"
```

---

## Phase G — Integration smoke

### Task 20: Full test suite + manual smoke

**Step 1: Run full test suites**

```bash
cd SDRUtils/dashboard && npx tsc --noEmit && npx vitest run
cd SDRUtils && pytest _swappulse_scripts -v -k usdswaps_tape
```

Expected: all PASS.

**Step 2: Manual smoke via preview**

- Start dashboard dev server.
- Load USD swap tape page.
- Verify: row tints per structure, UNWIND rows red, lifecycle pills vibrant, new "Other Lvl" column, expanded subtable shows PTP + OPA, per-column filter menus work, filter chips gone, fuzzy search bar gone.

**Step 3: Update design doc status**

Append a "Status: implemented on <commit-sha>" footer to `docs/plans/2026-04-16-usd-swaps-tape-v2-trader-feedback-design.md`.

**Step 4: Commit**

```bash
git add docs/plans/2026-04-16-usd-swaps-tape-v2-trader-feedback-design.md
git commit -m "docs(usd-swaps-tape-v2): mark feedback round 1 implemented"
```

---

## Dependencies

- Phase A → Phase B → Phase C (OPA/PTP flows top-down: schema → types → UI).
- Phase D → Phase E (delete before you replace).
- Phase F is independent — can run in parallel with D/E.
- Phase G gate: all prior phases green.

## Commit cadence

~20 commits total across 20 tasks. One commit per task. No batching.
