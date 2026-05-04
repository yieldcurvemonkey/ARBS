# USD Swaps Tape v2 — Manual Linking Revamp + Shared Extraction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL — use `superpowers:executing-plans` to implement this plan task-by-task. Each task is bite-sized, TDD-shaped, and ends in its own commit, mirroring the cadence of PR #285 / PR #286.

**Goal:** Extract swaptions-tape's manual-link UI primitives into a new shared module `lib/manual-links-ui/`, refactor swaptions to import from it (zero behaviour change), then adopt the shared module into v2 to bring v2 to swaptions-grade parity (row badges, detail modal, edit / deactivate, validation state machine, history). Verify v2 tape API hydrates manual link metadata onto every row.

**Architecture:** New shared module under `SDRUtils/dashboard/src/lib/manual-links-ui/` with pure functions (`manualLinkColor`, `isManualPackage`, `groupLinkedRows`), components (`ManualLinkBadge`, `ManualLinkDetailModal`, sub-components), hooks (`useManualLinkDetails`, `useManualLinkForm`), API wrappers, and types. Swaptions refactored to import; v2 adopts. v2 tape API LEFT JOINs `arbs_usd_swap_manual_links_v2` so badges render. Admin password gates PATCH/DELETE; POST stays open. Forced-straddle code stays in swaptions (out of scope).

**Tech Stack:** TypeScript, React 19, Next.js 15, Jest 30, Tailwind, PrimeReact 10. No new runtime dependencies.

**Date.** 2026-05-04
**Companion design.** [docs/plans/2026-05-04-manual-links-revamp-design.md](2026-05-04-manual-links-revamp-design.md)
**Routes affected.** `/usd-swaps`, `/swaptions`. API route audit on `/api/usd-swaps-tape-v2/links/*`.
**Feature modules.** `usd-swaps-tape-v2`, `swaptions-tape`. New shared module: `lib/manual-links-ui/`.
**Cross-workstream sequencing.** Independent of WS1 / WS2.

---

## Working directory commands

All paths relative to repo root. Tests:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
cd SDRUtils/dashboard && npm test -- --testPathPatterns=swaptions-tape
cd SDRUtils/dashboard && npm test -- --testPathPatterns=manual-links-ui
```

Targeted patterns:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=ManualLinkBadge
cd SDRUtils/dashboard && npm test -- --testPathPatterns=ManualLinkDetailModal
cd SDRUtils/dashboard && npm test -- --testPathPatterns=useManualLinkForm
cd SDRUtils/dashboard && npm test -- --testPathPatterns=useManualLinkDetails
```

Lint:

```bash
cd SDRUtils/dashboard && npm run lint
```

Dev server:

```bash
cd SDRUtils/dashboard && PORT=3001 npx next dev
```

---

## Phase A — Pure-function extraction (zero behaviour change in swaptions)

### Task A1: Extract `manualLinkColor` (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/color.ts`
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/__tests__/color.test.ts`
- Modify: `SDRUtils/dashboard/src/features/swaptions-tape/components/SwaptionTradeTape.tsx` (delete inline `manualLinkColor`; import from shared)

**Step 1. Failing test.**

```ts
import { describe, expect, it } from '@jest/globals'
import { manualLinkColor } from '../color'

describe('manualLinkColor', () => {
  it('returns same colour for same input across runs', () => {
    expect(manualLinkColor('link-abc')).toBe(manualLinkColor('link-abc'))
  })

  it('returns different colours for different inputs', () => {
    expect(manualLinkColor('a')).not.toBe(manualLinkColor('b'))
  })

  it('returns valid HSL', () => {
    expect(manualLinkColor('x')).toMatch(/^hsl\(\d+, \d+%, \d+%\)$/)
  })

  it('handles empty / null inputs gracefully', () => {
    expect(manualLinkColor('')).toMatch(/^hsl\(/)
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Locate the existing `manualLinkColor` at `SwaptionTradeTape.tsx:2206-2213`; copy verbatim into `color.ts`:

```ts
// ABOUTME: Deterministic linkId → HSL colour. Used by row chips so a
// linked group of trades shares a stable colour across renders. Hash
// is intentionally simple — collisions at ~1-in-256 are visually
// acceptable.

export function manualLinkColor(linkId: string): string {
  let hash = 0
  for (let i = 0; i < linkId.length; i++) {
    hash = (hash << 5) - hash + linkId.charCodeAt(i)
    hash |= 0
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 65%, 55%)`
}
```

**Step 4. Update swaptions to import.** In `SwaptionTradeTape.tsx`, replace the inline `manualLinkColor` definition with `import { manualLinkColor } from '@/lib/manual-links-ui/color'`. Delete the original definition.

**Step 5. Run all tests.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=swaptions-tape 2>&1 | tail -20
cd SDRUtils/dashboard && npm test -- --testPathPatterns=color 2>&1 | tail -10
```

Expected: swaptions suite byte-for-byte green; new color test green.

**Step 6. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/manual-links-ui/color.ts \
        SDRUtils/dashboard/src/lib/manual-links-ui/__tests__/color.test.ts \
        SDRUtils/dashboard/src/features/swaptions-tape/components/SwaptionTradeTape.tsx
git commit -m "refactor(manual-links): extract manualLinkColor to shared module"
```

---

### Task A2: Extract `isManualPackage` + `groupLinkedRows` (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/predicates.ts`
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/grouping.ts`
- Create: `__tests__/predicates.test.ts` and `__tests__/grouping.test.ts`
- Modify: `SwaptionTradeTape.tsx` (delete inline; import from shared)

**Step 1. Failing tests.**

```ts
// predicates.test.ts
import { isManualPackage } from '../predicates'
describe('isManualPackage', () => {
  it.each([
    [{ manual_link_id: 'x' }, true],
    [{ manual_package_id: 'p' }, true],
    [{ package_source: 'MANUAL' }, true],
    [{ package_source: 'HYBRID' }, true],
    [{ package_source: 'INFERRED' }, false],
    [{}, false],
  ])('returns %p for %p', (row, expected) => {
    expect(isManualPackage(row as any)).toBe(expected)
  })
})

// grouping.test.ts
import { groupLinkedRows } from '../grouping'
describe('groupLinkedRows', () => {
  it('clusters rows by manual_package_id then manual_link_id', () => { /* ... */ })
  it('preserves source order within a group', () => { /* ... */ })
  it('passes ungrouped rows through in original order', () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Copy from swaptions (`SwaptionTradeTape.tsx:2199-2204` and `:2215-2246`).

```ts
// predicates.ts
import type { TapeRowLike } from './types'

export function isManualPackage(row: TapeRowLike): boolean {
  if (row.manual_link_id) return true
  if (row.manual_package_id) return true
  if (row.package_source === 'MANUAL' || row.package_source === 'HYBRID') return true
  return false
}
```

```ts
// grouping.ts
import type { TapeRowLike } from './types'

export function groupLinkedRows<R extends TapeRowLike>(rows: readonly R[]): R[] {
  const seen = new Set<string>()
  const out: R[] = []
  for (const row of rows) {
    const key = row.manual_package_id ?? row.manual_link_id ?? null
    if (key && !seen.has(key)) {
      seen.add(key)
      // emit all rows sharing this key, in source order
      for (const r of rows) {
        if ((r.manual_package_id ?? r.manual_link_id ?? null) === key) out.push(r)
      }
    } else if (!key) {
      out.push(row)
    }
  }
  return out
}
```

**Step 4. Update swaptions imports; delete inline definitions.**

**Step 5. Run all tests.**

**Step 6. Commit.**

```bash
git add SDRUtils/dashboard/src/lib/manual-links-ui/ \
        SDRUtils/dashboard/src/features/swaptions-tape/components/SwaptionTradeTape.tsx
git commit -m "refactor(manual-links): extract isManualPackage + groupLinkedRows to shared module"
```

---

### Task A3: Consolidate types into `lib/manual-links-ui/types.ts`

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/types.ts`
- Modify: `SDRUtils/dashboard/src/features/swaptions-tape/types/...` (re-export from shared)
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/types/link.types.ts` (re-export from shared)

**Step 1. Test.** Pin that all consumers' previous imports still resolve.

**Step 2. Run, expect green.**

**Step 3. Implement.** Consolidate the manual-link record types:

```ts
// types.ts
export interface TapeRowLike {
  manual_link_id?: string | null
  manual_package_id?: string | null
  package_source?: 'INFERRED' | 'MANUAL' | 'HYBRID' | string
}

export interface ManualLink {
  link_id: string
  manual_package_id: string
  package_type: string
  linked_trade_ids: string[]
  created_by: string
  created_at: string
  user_comment?: string | null
  link_reason?: string | null
  tags?: string[]
  link_metrics?: Record<string, unknown>
  is_active: boolean
}

export interface ManualLinkTrade {
  trade_id: string
  package_id: string
  trade_label: string
  notional: number
  execution_timestamp: string
  // ... extend per existing swaptions shape
}

export interface ManualLinkHistoryItem {
  history_id: string
  action: 'CREATE' | 'UPDATE' | 'DEACTIVATE'
  changed_by: string
  changed_at: string
  change_details: Record<string, unknown>
  previous_state: Record<string, unknown> | null
}

export interface ManualLinkValidationItem {
  severity: 'info' | 'warning' | 'error'
  code: string
  message: string
}

export interface ManualLinkDetail {
  link: ManualLink
  trades: ManualLinkTrade[]
  history: ManualLinkHistoryItem[]
}
```

**Step 4. Run all tests + lint.**

**Step 5. Commit.**

```bash
git commit -am "refactor(manual-links): consolidate ManualLink types into shared module"
```

**Gate.** Full swaptions test suite green.

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=swaptions-tape 2>&1 | tail -30
```

---

## Phase B — Component extraction

### Task B1: Extract `<ManualLinkBadge>`

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/components/ManualLinkBadge.tsx`
- Create: `__tests__/ManualLinkBadge.test.tsx`
- Modify: `SwaptionTradeTape.tsx` (replace inline badge JSX with `<ManualLinkBadge>`)

**Step 1. Failing tests.**

```tsx
describe('ManualLinkBadge', () => {
  it('renders dot + label + linkId', () => {
    render(<ManualLinkBadge linkId="abc" packageId="pkg-1" label="Manual" />)
    expect(screen.getByTestId('manual-link-dot')).toHaveStyle({ background: manualLinkColor('abc') })
    expect(screen.getByText('Manual')).toBeInTheDocument()
    expect(screen.getByText(/pkg-1/)).toBeInTheDocument()
  })

  it('fires onClick with linkId when clicked', () => { /* ... */ })

  it('renders connector lines when prop set', () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Copy badge JSX from `SwaptionTradeTape.tsx:13401-13442`. Adapt:

```tsx
// ABOUTME: Row-level chip for manually-linked tape rows. Colour is
// derived deterministically from linkId so all rows in one link group
// share a colour. Click opens the detail modal via onClick.

import { manualLinkColor } from '../color'
import type { ReactNode } from 'react'

export interface ManualLinkBadgeProps {
  linkId: string
  packageId?: string | null
  label: 'Manual' | 'Hybrid' | string
  onClick?: (linkId: string) => void
  showConnector?: boolean
}

export function ManualLinkBadge({
  linkId, packageId, label, onClick, showConnector,
}: ManualLinkBadgeProps): ReactNode {
  const colour = manualLinkColor(linkId)
  return (
    <button
      type="button"
      onClick={() => onClick?.(linkId)}
      className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-1.5 py-0.5 text-xs hover:bg-slate-700"
      data-testid="manual-link-badge"
    >
      <span data-testid="manual-link-dot" className="h-2 w-2 rounded-full" style={{ background: colour }} />
      <span>{label}</span>
      {packageId && <span className="font-mono text-[10px] text-slate-400">{packageId}</span>}
      {showConnector && <span aria-hidden className="text-slate-500">│</span>}
    </button>
  )
}
```

**Step 4. Wire into swaptions:** replace the inline JSX in `SwaptionTradeTape.tsx` with `<ManualLinkBadge linkId={...} packageId={...} label={...} onClick={openManualLinkDetails} />`.

**Step 5. Run swaptions test suite — must be green byte-for-byte.**

**Step 6. Commit.**

```bash
git commit -am "refactor(manual-links): extract ManualLinkBadge to shared module"
```

---

### Task B2: Extract `<ManualLinkValidationList>`, `<ManualLinkMetricsTable>`, `<ManualLinkHistoryTable>`

Three small sub-components. One commit each.

For each:

1. Test file with rendering + key-cell-content assertions.
2. Implement copy of swaptions JSX into `lib/manual-links-ui/components/`.
3. Update swaptions imports.
4. Run swaptions suite green.
5. Commit.

**Commits.**
- `refactor(manual-links): extract ManualLinkValidationList`
- `refactor(manual-links): extract ManualLinkMetricsTable`
- `refactor(manual-links): extract ManualLinkHistoryTable`

---

### Task B3: Extract `<ManualLinkDetailModal>` shell

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/components/ManualLinkDetailModal.tsx`
- Create: `__tests__/ManualLinkDetailModal.test.tsx`
- Modify: `SwaptionTradeTape.tsx` (replace inline detail modal with `<ManualLinkDetailModal>`)

**Step 1. Failing tests.**

```tsx
describe('ManualLinkDetailModal', () => {
  it('renders read mode: shows link record + trades + history', () => { /* ... */ })
  it('switch to edit mode prompts admin password', () => { /* ... */ })
  it('edit submit fires PATCH', () => { /* ... */ })
  it('deactivate fires DELETE', () => { /* ... */ })
  it('auto-validates on open', () => { /* ... */ })
  it('renders ManualLinkValidationList + MetricsTable + HistoryTable', () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Copy modal JSX from swaptions (~ lines 11058-11800). Single read+edit component (per user direction): a state field `mode: 'read' | 'edit'` toggles input enablement. Edit mode requires admin password before submit. Deactivate is a separate button with admin password prompt.

The modal accepts:

```ts
interface ManualLinkDetailModalProps {
  visible: boolean
  linkId: string | null
  onClose: () => void
  onCreated?: (link: ManualLink) => void   // for create flow if used as creation surface
  onDeactivated?: (linkId: string) => void
}
```

Internally uses `useManualLinkDetails(linkId)` and `useManualLinkForm(...)` for state.

**Step 4. Wire into swaptions:** replace the inline modal with `<ManualLinkDetailModal>`.

**Step 5. Swaptions test suite must be green.**

**Step 6. Commit.**

```bash
git commit -am "refactor(manual-links): extract ManualLinkDetailModal to shared module"
```

**Gate.** Full swaptions test suite + manual smoke test of the swaptions detail modal flow.

---

## Phase C — Hook extraction

### Task C1: `manualLinkApi` typed wrapper

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/api/manualLinkApi.ts`
- Create: `__tests__/manualLinkApi.test.ts`

**Step 1. Failing tests.**

```ts
describe('manualLinkApi', () => {
  it('createLink POSTs JSON to base path', async () => { /* mock fetch */ })
  it('validateLink POSTs with validate_only=true', async () => { /* ... */ })
  it('updateLink PATCHes with admin password header', async () => { /* ... */ })
  it('deactivateLink DELETEs with admin password header', async () => { /* ... */ })
  it('getLinkDetail GETs /links/:id', async () => { /* ... */ })
  it('throws on non-2xx', async () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: Typed fetch wrapper for the manual-links REST surface. The
// `basePath` parameter lets the same client serve swaptions
// (/api/swaption/links) and v2 (/api/usd-swaps-tape-v2/links) — the
// route handlers for both are re-exports of the sofr handler so the
// wire format is identical.

import type {
  ManualLink, ManualLinkDetail, ManualLinkValidationItem,
} from '../types'

export interface ManualLinkApiClient {
  createLink(body: CreateLinkBody): Promise<{ link_id: string; manual_package_id: string }>
  validateLink(body: CreateLinkBody): Promise<{ validation: ManualLinkValidationItem[]; metrics: Record<string, unknown> }>
  getLinkDetail(linkId: string): Promise<ManualLinkDetail>
  updateLink(linkId: string, body: UpdateLinkBody, adminPassword: string): Promise<{ link_id: string }>
  deactivateLink(linkId: string, adminPassword: string): Promise<void>
}

export function createManualLinkApi(basePath: string): ManualLinkApiClient {
  // ... fetch implementations
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(manual-links): typed manualLinkApi wrapper"
```

---

### Task C2: `useManualLinkDetails` extraction

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/hooks/useManualLinkDetails.ts`
- Create: `__tests__/useManualLinkDetails.test.ts`
- Modify: swaptions consumer to import from shared

**Step 1. Failing tests.**

```ts
it('fetches link detail on linkId change', () => {/* ... */ })
it('exposes loading + error states', () => { /* ... */ })
it('reuses pending request for same linkId', () => { /* ... */ })
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** SWR-or-bespoke hook over `manualLinkApi.getLinkDetail`. Use the existing swaptions implementation as starting point.

**Step 4. Update swaptions imports.**

**Step 5. Swaptions suite green.**

**Step 6. Commit.**

```bash
git commit -am "refactor(manual-links): extract useManualLinkDetails to shared module"
```

---

### Task C3: `useManualLinkForm` extraction

**Files.**
- Create: `SDRUtils/dashboard/src/lib/manual-links-ui/hooks/useManualLinkForm.ts`
- Create: `__tests__/useManualLinkForm.test.ts`
- Modify: swaptions consumer

**Step 1. Failing tests.**

```ts
describe('useManualLinkForm', () => {
  it('auto-validates on dialog open', async () => { /* ... */ })
  it('exposes validation items + metrics', async () => { /* ... */ })
  it('handleCreate fires create POST', async () => { /* ... */ })
  it('handleUpdate fires PATCH with admin password', async () => { /* ... */ })
  it('handleDeactivate fires DELETE with admin password', async () => { /* ... */ })
  it('addTag / removeTag updates tag list', () => { /* ... */ })
  it('reset clears state on close', () => { /* ... */ })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Port the existing swaptions `useManualLinks` (the rich version at `swaptions-tape/hooks/useManualLinks.ts:1-180`) verbatim into the shared module. Rename to `useManualLinkForm` to disambiguate from the v2 minimal hook still in tree.

**Step 4. Update swaptions imports.**

**Step 5. Swaptions suite green; smoke-test the swaptions modal flow manually.**

**Step 6. Commit.**

```bash
git commit -am "refactor(manual-links): extract useManualLinkForm to shared module"
```

**Gate.** Full swaptions suite green; manual smoke of the full swaptions create / edit / deactivate / inspect cycle.

---

## Phase D — v2 adoption (UI primitives)

### Task D1: v2 columns wire `<ManualLinkBadge>`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- Modify or create: `__tests__/columns.test.ts` (extend existing if present)

**Step 1. Failing test.**

```tsx
it('renders ManualLinkBadge in Pkg column when isManualPackage(row)', () => {
  const row = { ...baseRow, manual_link_id: 'L1', manual_package_id: 'P1' }
  render(<PkgCell row={row} />)
  expect(screen.getByTestId('manual-link-badge')).toBeInTheDocument()
})

it('does not render badge when row is inferred', () => {
  render(<PkgCell row={baseRow} />)
  expect(screen.queryByTestId('manual-link-badge')).toBeNull()
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** In the Pkg column body in `columns.tsx`, conditionally render `<ManualLinkBadge>` when `isManualPackage(row)` is true. Click handler invokes a panel-level open-modal callback.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): row badges via shared ManualLinkBadge"
```

---

### Task D2: v2 row grouping via `groupLinkedRows`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx`

**Step 1. Test.** Pin that linked rows render contiguously after grouping.

**Step 2. Run, expect failure.**

**Step 3. Implement.** In the row pipeline (after the existing `displayRows` memo), apply `groupLinkedRows`:

```ts
const groupedRows = useMemo(() => groupLinkedRows(displayRows), [displayRows])
```

Pass `groupedRows` to the table. (Confirm interaction with the existing `dedupeDuplicatePackages` + scroll-anchor pipeline; preserve order semantics.)

**Step 4. Run, expect green; regression check pagination + filters + scroll-anchor.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): row clustering via groupLinkedRows"
```

---

## Phase E — v2 adoption (modal + state machine)

### Task E1: Replace v2 `useManualLinks` with shared `useManualLinkForm`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useManualLinks.ts`

**Step 1. Test.** Pin that v2 dialog mount auto-validates on open and surfaces validation items + metrics.

**Step 2. Run, expect failure.**

**Step 3. Implement.** Replace v2's minimal `useManualLinks` with a re-export or a thin wrapper that calls the shared hook with v2's `basePath`:

```ts
import { useManualLinkForm } from '@/lib/manual-links-ui/hooks/useManualLinkForm'

export function useManualLinks() {
  return useManualLinkForm({ basePath: '/api/usd-swaps-tape-v2/links' })
}
```

**Step 4. Run all tests; v2 suite extended for new behaviour.**

**Step 5. Commit.**

```bash
git commit -am "refactor(usd-swaps-tape): v2 useManualLinks → shared useManualLinkForm"
```

---

### Task E2: Replace v2 `ManualLinksDialog` with `<ManualLinkDetailModal>`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/ManualLinksDialog.tsx`
- Modify: consumers of `<ManualLinksDialog>` (likely `UsdSwapsTradeTape.tsx`)

**Step 1. Test.** Pin that the dialog now uses the shared modal's create flow + read mode + edit + deactivate.

**Step 2. Run, expect failure.**

**Step 3. Implement.** v2's existing `ManualLinksDialog` becomes a thin wrapper around `<ManualLinkDetailModal>`. The "create" path is a special case where `linkId={null}` and the modal opens in edit-mode-with-no-existing-link.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "refactor(usd-swaps-tape): v2 ManualLinksDialog → shared ManualLinkDetailModal"
```

---

### Task E3: Edit + deactivate flows wired in v2

**Files.**
- Modify: `UsdSwapsTradeTape.tsx` (open-modal callback wiring)
- Modify: `<ManualLinkDetailModal>` consumers in v2

**Step 1. Test the full lifecycle.**

```tsx
it('badge click opens detail modal in read mode', () => { /* ... */ })
it('switching to edit mode prompts admin password', () => { /* ... */ })
it('PATCH success closes modal and updates tape row', () => { /* ... */ })
it('DELETE success closes modal and removes badges from grouped rows', () => { /* ... */ })
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Tie row badge `onClick(linkId)` to opening the modal with that `linkId`. Plumb modal callbacks to refresh the tape row data on success.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): v2 edit + deactivate flows wired"
```

---

## Phase F — API + tape JOIN audit

### Task F1: Verify all six endpoints reachable from v2 paths

**Files.**
- Audit: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/links/route.ts`
- Audit: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/links/[linkId]/route.ts`

**Step 1.** Read both route files. Confirm each re-exports the corresponding sofr handler. Required:

- `POST /links` (with `validate_only` query support)
- `GET /links` (list)
- `GET /links/[linkId]` (detail with link + trades + history)
- `PATCH /links/[linkId]` (edit, admin-password gated)
- `DELETE /links/[linkId]` (deactivate, admin-password gated)

**Step 2. Test pin.** Add an integration test that hits each endpoint via `fetch` and confirms the response shape.

**Step 3.** If any endpoint is missing or shaped differently, add the re-export.

**Step 4.** Commit.

```bash
git commit -am "test(usd-swaps-tape): pin manual-links route audit"
```

---

### Task F2: Tape JOIN audit + extend if missing

**Files.**
- Audit: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts`
- Modify if needed: same file
- Extend: `route.logic.test.ts`

**Step 1.** Read `buildTapeQuery`. Confirm it LEFT JOINs `arbs_usd_swap_manual_links_v2` and projects `manual_link_id`, `manual_package_id`, `link_created_by`, `link_created_at`, `user_comment`, `link_reason`, `tags`.

**Step 2. Test pin.**

```ts
it('LEFT JOINs arbs_usd_swap_manual_links_v2 and projects manual link fields', () => {
  const { sql } = buildTapeQuery({ ...baseParams })
  expect(sql).toMatch(/LEFT JOIN\s+arbs_usd_swap_manual_links_v2/i)
  expect(sql).toMatch(/manual_link_id/)
  expect(sql).toMatch(/manual_package_id/)
})
```

**Step 3. Run.** If the JOIN is missing, the test fails. Implement the JOIN with the proper key (likely `linked_trade_ids @> ARRAY[d.package_id]` or via a per-row exists-clause; check existing swaptions JOIN for canonical pattern).

**Step 4. Run, expect green.**

**Step 5.** Manual smoke test on dev server: confirm v2 rows now hydrate with manual link metadata.

**Step 6. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): v2 tape JOIN hydrates manual link metadata on every row"
```

---

## Verification

### Task V: Comprehensive E2E walk-through

**Step 1. Full feature suite + lint.**

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns="usd-swaps-tape-v2|swaptions-tape|manual-links-ui" 2>&1 | tail -40
cd SDRUtils/dashboard && npm run lint 2>&1 | tail -10
```

Expected: all green.

**Step 2. Dev server walk-through (§4.2 of design doc):**

1. Navigate `/usd-swaps`. No row badges yet (no manual links in test data).
2. Open ManualLinksDialog (toolbar button); select 2 rows. Auto-validate fires on open. Validation items + metrics render.
3. Submit create → success. Both rows now show `<ManualLinkBadge>` with the same colour. Linked rows cluster visually via `groupLinkedRows`.
4. Click badge → detail modal opens (read mode). Shows link record, linked trades, empty history.
5. Switch to edit mode → admin password prompt → enter → form editable.
6. Edit comment → submit PATCH → modal updates → history table now has 1 entry.
7. Add a third trade via edit → PATCH → modal updates → history 2 entries.
8. Remove that third trade via edit → PATCH → modal updates → history 3 entries.
9. Click deactivate → admin password → DELETE fires → modal closes → row badges disappear.
10. Refresh → confirm DB state via re-open: link is `is_active=FALSE`.
11. Refresh page → previously-created link no longer renders badges (deactivated).

**Step 3. Swaptions regression walkthrough.** Click through swaptions tape: row badges, group clustering, detail modal, edit, deactivate, validation, force-straddle (out of scope but must still work). Snapshot diff vs pre-change.

**Step 4. v2 regression.** Walk every existing v2 feature: package-confidence detail panel, analytics dock, four PR-#286 cards (post-WS2 if mounted), pagination + filters, polling.

**Step 5.** Append a verification log to this plan; commit.

```bash
git commit -am "docs(usd-swaps-tape): manual-links-revamp verification log"
```

**Step 6. Open PR.**

```bash
git push -u origin <branch>
gh pr create --title "feat(usd-swaps-tape): manual-linking revamp + shared extraction" --body "..."
```

PR body summarises:
- Phase A: pure-function extraction + types consolidation.
- Phase B: component extraction (badge, validation, metrics, history, detail modal).
- Phase C: hooks extraction (useManualLinkDetails, useManualLinkForm) + manualLinkApi.
- Phase D: v2 row badges + grouping.
- Phase E: v2 modal + state-machine adoption + edit/deactivate flows.
- Phase F: API audit + tape JOIN audit.
- E2E verification evidence (badges before/after, modal lifecycle, swaptions regression).

---

## Out of scope

- Real-time WebSocket updates.
- Forced-straddle / `assumed_incomplete_straddle` (stays in swaptions).
- Schema changes.
- Sofr-tape adoption.
- Admin-password UX upgrade (session caching, OAuth).

## Risk + caveats

1. **Swaptions extraction regression.** Phase A → C is the riskiest. Phase gates after A3, B3, C3 require the swaptions test suite to be green byte-for-byte before continuing.
2. **Detail modal divergence over time.** Document the prop contract in the modal's ABOUTME.
3. **Tape JOIN performance.** Index on `arbs_usd_swap_manual_links_v2.linked_trade_ids` likely already exists; benchmark.
4. **Admin-password gate UX.** Matches existing swaptions; future workstream may session-cache.
5. **Colour collision at ~1-in-256.** Acceptable; matches swaptions.
6. **Type unification across consumers.** `types.ts` built up from intersection; consumer-specific extensions remain in consumer modules.

## Recommended order

- Day 1: Phase A (3 tasks, ~half day; gate at A3).
- Day 2: Phase B (5 tasks, ~1 day; gate at B3).
- Day 3: Phase C (3 tasks, ~1 day; gate at C3 with full swaptions smoke).
- Day 4: Phase D + E (5 tasks).
- Day 5: Phase F + Verification (3 tasks).
- PR cadence: single PR; phases sequence within for review-ability.
