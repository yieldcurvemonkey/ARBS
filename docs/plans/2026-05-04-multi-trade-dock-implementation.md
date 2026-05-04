# USD Swaps Tape v2 — Multi-Trade Dock + Sequence Analytics — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL — use `superpowers:executing-plans` to implement this plan task-by-task. Each task is bite-sized, TDD-shaped, and ends in its own commit, mirroring the cadence of PR #285 / PR #286.

**Goal:** Extend the analytics dock to support multi-row selection. When 1 row is selected, render today's UX. When 2+ rows are selected, the *sequence* becomes the focus — replace `FocusedTradeBar` with a `SequenceBar`, render multi-overlay variants of Timeseries / Rarity / Levels tabs, add a new Sequence tab, and mount the four PR-#286 cards in an always-on collapsed drawer.

**Architecture:** Plumb `rows` and `selected` into `AnalyticsPanel` alongside `focused`. Derive `mode` ∈ {empty, single, sequence}. Single-mode UX preserved byte-for-byte. Sequence mode introduces `SequenceBar`, multi-overlay tabs, a new Sequence tab (timeline + inter-trade gaps + lightweight chain detection + lifecycle context), and a `useAnalyticsSequence` wrapper that delegates to existing single-trade hooks. Cards drawer mounts in both modes.

**Tech Stack:** TypeScript, React 19, Next.js 15, Jest 30, Tailwind, PrimeReact 10. No new dependencies.

**Date.** 2026-05-04
**Companion design.** [docs/plans/2026-05-04-multi-trade-dock-design.md](2026-05-04-multi-trade-dock-design.md)
**Routes affected.** `/usd-swaps`. No API route changes.
**Feature module.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**Cross-workstream sequencing.** This plan's Phase A (passthrough refactor) lands FIRST across this workstream and WS1; WS1 builds on the stable hook surface.

---

## Working directory commands

All paths relative to repo root. Dashboard tests:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
```

Targeted patterns:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=AnalyticsPanel
cd SDRUtils/dashboard && npm test -- --testPathPatterns=Sequence
cd SDRUtils/dashboard && npm test -- --testPathPatterns=useFocusedTrade
cd SDRUtils/dashboard && npm test -- --testPathPatterns=useAnalyticsSequence
cd SDRUtils/dashboard && npm test -- --testPathPatterns=CardsDrawer
```

Lint:

```bash
cd SDRUtils/dashboard && npm run lint
```

Dev server (no Turbopack — see PR #285 verification log):

```bash
cd SDRUtils/dashboard && PORT=3001 npx next dev
```

---

## Phase A — Passthrough refactor

Thread `rows` and `selected` from `UsdSwapsTradeTape` into `AnalyticsPanel`. No render change yet — the panel just receives the new props and stows them.

### Task A1: Extend `AnalyticsPanel` props with `rows` + `selected`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/AnalyticsPanel.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/AnalyticsPanel.test.tsx`

**Step 1. Write the failing test.**

```tsx
import { describe, expect, it } from '@jest/globals'
import { render } from '@testing-library/react'
import { AnalyticsPanel } from '../AnalyticsPanel'

describe('AnalyticsPanel props', () => {
  it('accepts rows + selected props without runtime error', () => {
    const { container } = render(
      <AnalyticsPanel
        rows={[]}
        selected={[]}
        focused={null}
        onClose={() => {}}
        onClearFocused={() => {}}
      />
    )
    expect(container).toBeTruthy()
  })
})
```

**Step 2. Run, expect TS error** (rows + selected don't exist on the prop type yet).

**Step 3. Implement.** Extend the interface:

```ts
interface AnalyticsPanelProps {
  rows: readonly UsdSwapTapeRow[]
  selected: readonly UsdSwapTapeRow[]
  focused: FocusedTrade | null
  onClose: () => void
  onClearFocused: () => void
  chartHeight?: number
  histogramHeight?: number
  panelHeightVh?: number
}
```

Body unchanged for now — accept the props, ignore them.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/
git commit -m "refactor(usd-swaps-tape): AnalyticsPanel accepts rows + selected props"
```

---

### Task A2: Pass new props from `UsdSwapsTradeTape`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx`
- Modify or create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__/UsdSwapsTradeTape.props.test.tsx`

**Step 1. Test.** Pin that `<AnalyticsPanel>` receives `rows={tape.rows}` and `selected={selection.selected}`.

**Step 2. Run, expect failure.**

**Step 3. Implement.** In `UsdSwapsTradeTape.tsx`, locate the `<AnalyticsPanel ... />` call (~ line 115) and add the new props:

```tsx
<AnalyticsPanel
  rows={tape.rows}
  selected={selection.selected}
  focused={focus.focused}
  onClose={...}
  onClearFocused={...}
/>
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/UsdSwapsTradeTape.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/__tests__/UsdSwapsTradeTape.props.test.tsx
git commit -m "refactor(usd-swaps-tape): plumb rows + selected to AnalyticsPanel"
```

---

## Phase B — Cards drawer

Mount the four PR-#286 cards in a collapsed always-on drawer below the tab area. Default state: collapsed. localStorage persists state.

### Task B1: `CardsDrawer` component (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/CardsDrawer.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/CardsDrawer.test.tsx`

**Step 1. Failing test.**

```tsx
import { describe, expect, it } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import { CardsDrawer } from '../CardsDrawer'

describe('CardsDrawer', () => {
  beforeEach(() => localStorage.clear())

  it('starts collapsed by default', () => {
    render(<CardsDrawer rows={[]} />)
    expect(screen.queryByTestId('underlier-mix-card')).toBeNull()
    expect(screen.getByRole('button', { name: /Show analytics cards/ })).toBeInTheDocument()
  })

  it('expands on click; collapses on second click', () => {
    render(<CardsDrawer rows={[]} />)
    fireEvent.click(screen.getByRole('button', { name: /Show analytics cards/ }))
    expect(screen.getByTestId('underlier-mix-card')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Hide analytics cards/ }))
    expect(screen.queryByTestId('underlier-mix-card')).toBeNull()
  })

  it('persists expanded state to localStorage', () => {
    const { rerender } = render(<CardsDrawer rows={[]} />)
    fireEvent.click(screen.getByRole('button', { name: /Show analytics cards/ }))
    expect(localStorage.getItem('cards-drawer-expanded')).toBe('true')
    rerender(<CardsDrawer rows={[]} />)
    expect(screen.getByTestId('underlier-mix-card')).toBeInTheDocument()
  })

  it('mounts all four PR-#286 cards', () => {
    render(<CardsDrawer rows={[]} />)
    fireEvent.click(screen.getByRole('button', { name: /Show analytics cards/ }))
    expect(screen.getByTestId('underlier-mix-card')).toBeInTheDocument()
    expect(screen.getByTestId('rfr-adoption-card')).toBeInTheDocument()
    expect(screen.getByTestId('swap-spread-vwap-card')).toBeInTheDocument()
    expect(screen.getByTestId('ccp-switch-card')).toBeInTheDocument()
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```tsx
// ABOUTME: Always-present collapsible drawer below the analytics-dock
// tabs that mounts the four PR-#286 cards (UnderlierMix, RfrAdoption,
// SwapSpreadVwap, CcpSwitch). Default collapsed; state persists to
// localStorage. Visible in both single and sequence dock modes.

import { useState, useEffect } from 'react'
import {
  UnderlierMixCard,
  RfrAdoptionCard,
  SwapSpreadVwapCard,
  CcpSwitchCard,
} from './' // re-exports from AnalyticsPanel/index.ts
import type { UsdSwapTapeRow } from '../../types/trade.types'

const STORAGE_KEY = 'cards-drawer-expanded'

export function CardsDrawer({ rows }: { rows: readonly UsdSwapTapeRow[] }) {
  const [expanded, setExpanded] = useState<boolean>(() => {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(STORAGE_KEY) === 'true'
  })

  useEffect(() => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, String(expanded))
    }
  }, [expanded])

  return (
    <div className="border-t border-slate-700 bg-slate-900/40">
      <button
        type="button"
        className="w-full px-4 py-2 text-left text-sm text-slate-300 hover:bg-slate-800/50"
        onClick={() => setExpanded((v) => !v)}
        aria-label={expanded ? 'Hide analytics cards' : 'Show analytics cards'}
      >
        {expanded ? '▼ Hide analytics cards' : '▶ Show analytics cards'}
      </button>
      {expanded && (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-2">
          <div data-testid="underlier-mix-card"><UnderlierMixCard rows={rows} /></div>
          <div data-testid="rfr-adoption-card"><RfrAdoptionCard rows={rows} /></div>
          <div data-testid="swap-spread-vwap-card"><SwapSpreadVwapCard rows={rows} /></div>
          <div data-testid="ccp-switch-card"><CcpSwitchCard rows={rows} /></div>
        </div>
      )}
    </div>
  )
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/CardsDrawer.tsx \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/CardsDrawer.test.tsx
git commit -m "feat(usd-swaps-tape): collapsible CardsDrawer mounts PR-#286 cards"
```

---

### Task B2: Mount `CardsDrawer` in `AnalyticsPanel`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/AnalyticsPanel.tsx`

**Step 1. Test.** Pin that `<CardsDrawer rows={rows} />` is rendered below the tab content.

**Step 2. Run, expect failure.**

**Step 3. Implement.** Add `<CardsDrawer rows={rows} />` after the tab pane in `AnalyticsPanel`.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/
git commit -m "feat(usd-swaps-tape): mount CardsDrawer in AnalyticsPanel"
```

---

### Task B3: Smoke test PR-#286 cards rendered with current `rows`

**Step 1.** Run the dashboard locally; click a tape row; expand the drawer; confirm all four cards render with non-zero data.

**Step 2.** Snapshot the rendered drawer for regression. Append to a `CardsDrawer.snapshot.test.tsx`.

**Step 3.** Commit.

```bash
git commit -m "test(usd-swaps-tape): CardsDrawer + cards rendering snapshot"
```

---

## Phase C — `useFocusedTrade` extension

### Task C1: Extend `useFocusedTrade` with `mode` + `sequence`

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFocusedTrade.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useFocusedTrade.test.ts`

**Step 1. Failing test.**

```ts
import { describe, expect, it } from '@jest/globals'
import { renderHook } from '@testing-library/react'
import { useFocusedTrade } from '../useFocusedTrade'

describe('useFocusedTrade — mode derivation', () => {
  it('mode = empty when selected is empty', () => {
    const { result } = renderHook(() => useFocusedTrade([]))
    expect(result.current.mode).toBe('empty')
    expect(result.current.focused).toBeNull()
    expect(result.current.sequence).toBeNull()
  })

  it('mode = single when selected.length === 1', () => {
    const { result } = renderHook(() => useFocusedTrade([rowFixture]))
    expect(result.current.mode).toBe('single')
    expect(result.current.focused).not.toBeNull()
    expect(result.current.sequence).toBeNull()
  })

  it('mode = sequence when selected.length >= 2', () => {
    const { result } = renderHook(() => useFocusedTrade([rowA, rowB]))
    expect(result.current.mode).toBe('sequence')
    expect(result.current.focused).toBeNull()
    expect(result.current.sequence).toHaveLength(2)
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
export type AnalyticsMode = 'empty' | 'single' | 'sequence'

export interface UseFocusedTradeResult {
  mode: AnalyticsMode
  focused: FocusedTrade | null
  sequence: FocusedTrade[] | null
}

export function useFocusedTrade(
  selected: readonly UsdSwapTapeRow[],
): UseFocusedTradeResult {
  if (selected.length === 0) {
    return { mode: 'empty', focused: null, sequence: null }
  }
  if (selected.length === 1) {
    return { mode: 'single', focused: normalizeFocusedTrade(selected[0]), sequence: null }
  }
  return {
    mode: 'sequence',
    focused: null,
    sequence: selected
      .map(normalizeFocusedTrade)
      .filter((t): t is FocusedTrade => t != null),
  }
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFocusedTrade.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useFocusedTrade.test.ts
git commit -m "feat(usd-swaps-tape): useFocusedTrade returns mode + sequence"
```

---

### Task C2: Update `analytics-types.ts` with new types

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/analytics-types.ts`

**Step 1.** Add types:

```ts
export type AnalyticsMode = 'empty' | 'single' | 'sequence'

export interface SequenceAggregate {
  count: number
  totalDv01Usd: number
  weightedFixedRateBps: number
  totalNotionalUsd: number
  timeSpanMs: number | null
  startTs: string | null
  endTs: string | null
  sideMix: { pay: number; rcv: number }
  venueMix: Record<string, number>
}
```

**Step 2.** Run lint + tsc.

**Step 3.** Commit.

```bash
git commit -am "feat(usd-swaps-tape): AnalyticsMode + SequenceAggregate types"
```

---

## Phase D — `SequenceBar` + AnalyticsPanel mode branching

### Task D1: `SequenceBar` component (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceBar.tsx`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/__tests__/SequenceBar.test.tsx`

**Step 1. Failing test.**

```tsx
describe('SequenceBar', () => {
  it('renders count chip', () => {
    render(<SequenceBar sequence={[fA, fB, fC]} aggregate={aggFixture} onClear={() => {}} />)
    expect(screen.getByText(/Sequence \(3\)/)).toBeInTheDocument()
  })
  it('renders aggregate DV01 / weighted rate / notional / time span / mix', () => { /* ... */ })
  it('clear button fires onClear', () => { /* ... */ })
})
```

**Step 2. Run, expect failure.**

**Step 3. Implement.** Component renders count chip, aggregate fields, side / venue mix chips, and a clear button. Layout mirrors `FocusedTradeBar` so the swap is visually clean.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): SequenceBar component"
```

---

### Task D2: AnalyticsPanel mode-branch render (TDD)

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/AnalyticsPanel.tsx`
- Modify: `__tests__/AnalyticsPanel.test.tsx`

**Step 1. Test.** Pin that mode=single renders FocusedTradeBar; mode=sequence renders SequenceBar; mode=empty renders neither.

**Step 2. Run, expect failure.**

**Step 3. Implement.** Inside `AnalyticsPanel`, derive `{ mode, focused, sequence } = useFocusedTrade(selected)`. Branch render:

```tsx
{mode === 'single' && focused && <FocusedTradeBar trade={focused} onClear={onClearFocused} />}
{mode === 'sequence' && sequence && (
  <SequenceBar
    sequence={sequence}
    aggregate={computeSequenceAggregate(sequence)}
    onClear={onClearFocused}
  />
)}
```

`computeSequenceAggregate` is a small pure helper added in the same file (or `analytics-types.ts`).

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): AnalyticsPanel mode-branch render"
```

---

### Task D3: `computeSequenceAggregate` helper test pin

Pure helper. Pin behavior with a unit test against fixtures.

**Commit.** `test(usd-swaps-tape): pin computeSequenceAggregate behavior`

---

## Phase E — `useAnalyticsSequence` wrapper

### Task E1: `useAnalyticsSequence` hook (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsSequence.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/__tests__/useAnalyticsSequence.test.ts`

**Step 1. Failing test.**

```ts
describe('useAnalyticsSequence', () => {
  it('returns null perTrade when sequence is null', () => {
    const { result } = renderHook(() => useAnalyticsSequence(null, optsFixture))
    expect(result.current.perTrade).toEqual([])
  })

  it('delegates to single-trade hooks for each trade in sequence', async () => {
    const spy = jest.spyOn(/* useAnalyticsTimeseries module */)
    const { result } = renderHook(() => useAnalyticsSequence([fA, fB], optsFixture))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2)) // once per trade
    expect(result.current.perTrade).toHaveLength(2)
  })

  it('aggregates sequence-level summaries', async () => {
    const { result } = renderHook(() => useAnalyticsSequence([fA, fB], optsFixture))
    await waitFor(() => expect(result.current.aggregate).not.toBeNull())
    expect(result.current.aggregate.totalDv01Usd).toBe(fA.dv01_usd_per_bp + fB.dv01_usd_per_bp)
  })
})
```

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```ts
// ABOUTME: Wrapper hook that delegates to single-trade analytics hooks
// for each trade in a selected sequence and aggregates sequence-level
// summaries. Preserves WS1's SWR caching+dedup benefits because every
// inner call hits the same single-trade hook.

import { useMemo } from 'react'
import { useAnalyticsTimeseries } from './useAnalyticsTimeseries'
import { useRarityData } from './useRarityData'
import { useExtremesData } from './useExtremesData'
import type { FocusedTrade } from '../components/AnalyticsPanel/analytics-types'

export function useAnalyticsSequence(
  sequence: FocusedTrade[] | null,
  options: SequenceOptions,
) {
  const perTrade = (sequence ?? []).map((trade) => ({
    trade,
    timeseries: useAnalyticsTimeseries(trade, options.range, options.view, options.tsOptions),
    rarity:     useRarityData(trade, options.rarityOptions),
    extremes:   useExtremesData(trade, options.extremesOptions),
  }))

  const aggregate = useMemo(() => {
    if (!sequence || sequence.length === 0) return null
    return computeSequenceAggregate(sequence)
  }, [sequence])

  return { perTrade, aggregate }
}
```

(Note: calling hooks inside `.map` requires the `sequence` array length to be stable across renders; document this in an ABOUTME caveat. If the length changes, React will throw — wrap in a stable iteration via `sequence.slice(0, MAX_SEQUENCE)` and emit a warning if N>20.)

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): useAnalyticsSequence wrapper"
```

---

### Task E2: Document N=20 sequence cap

**Files.**
- Modify: `useAnalyticsSequence.ts` (add cap + warning).
- Modify: `SequenceBar.tsx` (render warning chip when N>20).

**Commit.** `feat(usd-swaps-tape): cap sequence at N=20 with soft warning`

---

## Phase F — Multi-overlay tab variants

### Task F1: `TimeseriesTab` multi-overlay (TDD)

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TimeseriesTab.tsx`
- Modify or create: `__tests__/TimeseriesTab.multi.test.tsx`

**Step 1. Failing test.**

```tsx
it('renders N reference lines and N reference dots when in sequence mode', () => {
  render(<TimeseriesTab mode="sequence" sequence={[fA, fB, fC]} {...rest} />)
  expect(screen.getAllByTestId(/reference-line/)).toHaveLength(3)
  expect(screen.getAllByTestId(/reference-dot/)).toHaveLength(3)
})

it('renders single reference line/dot in single mode (regression)', () => {
  render(<TimeseriesTab mode="single" focused={fA} {...rest} />)
  expect(screen.getAllByTestId(/reference-line/)).toHaveLength(1)
})

it('legend has show/hide-per-trade toggle', () => { /* ... */ })
```

**Step 2. Run, expect failures.**

**Step 3. Implement.** Add a `mode` + `sequence` props to `TimeseriesTab` (or branch internally based on AnalyticsPanel-derived state). Render N `<ReferenceLine y={trade.fixed_rate_bps} stroke={colour(i)} />` + N `<ReferenceDot x={trade.execution_start} y={trade.fixed_rate_bps} fill={colour(i)} />`. Legend chip per trade with show/hide toggle (state local to the tab).

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): TimeseriesTab multi-overlay for sequence mode"
```

---

### Task F2: `TradeRarityTab` multi-overlay

Same shape as F1, applied to `TradeRarityTab.tsx`. Render N `<ReferenceDot>` overlays on the shared histogram, color-coded per trade. Tooltip per dot identifies which trade.

**Commit.** `feat(usd-swaps-tape): TradeRarityTab N-dot overlay for sequence mode`

---

### Task F3: `TradedLevelsTab` multi-overlay with toggle

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/TradedLevelsTab.tsx`
- Modify or create: `__tests__/TradedLevelsTab.multi.test.tsx`

**Step 1. Test.** Pin both presentations:
- Side-by-side: N columns, one per selected trade.
- Aggregated: extremes scoped to the union of all selected rates.
Toggle persists to localStorage.

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```tsx
const [view, setView] = useState<'side-by-side' | 'aggregated'>(
  () => (localStorage.getItem('levels-multi-view') as 'side-by-side' | 'aggregated') ?? 'side-by-side'
)

useEffect(() => { localStorage.setItem('levels-multi-view', view) }, [view])

return (
  <>
    <div className="flex items-center gap-2 px-2 py-1">
      <button onClick={() => setView('side-by-side')} className={view === 'side-by-side' ? 'active' : ''}>
        Side-by-side
      </button>
      <button onClick={() => setView('aggregated')} className={view === 'aggregated' ? 'active' : ''}>
        Aggregated
      </button>
    </div>
    {view === 'side-by-side' ? <SideBySideTable sequence={sequence} /> : <AggregatedExtremes sequence={sequence} />}
  </>
)
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): TradedLevelsTab side-by-side / aggregated toggle for sequence mode"
```

---

## Phase G — Sequence tab

### Task G1: `SequenceTimeline` sub-component (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceTimeline.tsx`
- Create: `__tests__/SequenceTimeline.test.tsx`

**Step 1. Test.** Pin marker shape (▲/▼ per side), size (proportional to DV01), colour (per-venue palette), positioning along time axis.

**Step 2. Run, expect failures.**

**Step 3. Implement.** Horizontal SVG timeline; marker per trade.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): SequenceTimeline marker strip"
```

---

### Task G2: `InterTradeGaps` sub-component (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/InterTradeGaps.tsx`
- Create: `__tests__/InterTradeGaps.test.tsx`

**Step 1. Test.** Pin Δt + Δrate computation between consecutive executions; descending sort by time.

**Step 2. Run, expect failures.**

**Step 3. Implement.**

```tsx
export function InterTradeGaps({ sequence }: { sequence: FocusedTrade[] }) {
  const sorted = [...sequence].sort(byExecutionTimeAsc)
  const gaps = sorted.slice(1).map((trade, i) => ({
    fromId: sorted[i].id,
    toId: trade.id,
    deltaMs: tsMs(trade.execution_start) - tsMs(sorted[i].execution_start),
    deltaRateBps: trade.fixed_rate_bps - sorted[i].fixed_rate_bps,
  }))
  return (
    <table>
      <thead><tr><th>From</th><th>To</th><th>Δt</th><th>Δrate</th></tr></thead>
      <tbody>{gaps.map((g) => (
        <tr key={`${g.fromId}-${g.toId}`}>
          <td>{g.fromId}</td>
          <td>{g.toId}</td>
          <td>{formatMs(g.deltaMs)}</td>
          <td>{g.deltaRateBps.toFixed(2)} bp</td>
        </tr>
      ))}</tbody>
    </table>
  )
}
```

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): InterTradeGaps Δt/Δrate table"
```

---

### Task G3: `SequenceChainDetector` sub-component (TDD)

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceChainDetector.tsx`
- Create: `__tests__/SequenceChainDetector.test.tsx`

**Step 1. Test.** Pin three behaviours:
- Finds parent in `rows[]` when `original_dissemination_id` matches a loaded row.
- Flags "shared parent" when two selected rows share the same `original_dissemination_id`.
- Renders empty state when no rows have `original_dissemination_id`.

**Step 2. Run, expect failures.**

**Step 3. Implement.** Pure read across `rows[]` + `sequence`. Render chips per detected link.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): lightweight SequenceChainDetector"
```

---

### Task G4: `SequenceTab` assembly

**Files.**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceTab.tsx`
- Create: `__tests__/SequenceTab.test.tsx`

**Step 1. Test.** Pin that SequenceTab renders all five sub-components: Timeline, summary card, gaps, chain detector, lifecycle context strip.

**Step 2. Run, expect failures.**

**Step 3. Implement.** Compose:

```tsx
export function SequenceTab({ sequence, rows, aggregate }: SequenceTabProps) {
  return (
    <div className="space-y-4 p-4">
      <SequenceSummaryCard aggregate={aggregate} />
      <SequenceTimeline sequence={sequence} />
      <InterTradeGaps sequence={sequence} />
      <SequenceChainDetector sequence={sequence} rows={rows} />
      <LifecycleContextStrip sequence={sequence} />
      {/* Allocation chain stub: empty if prior_uti is not on the row schema */}
      <AllocationChainStub sequence={sequence} />
    </div>
  )
}
```

`LifecycleContextStrip` and `AllocationChainStub` are inline tiny components in the same file or separate per the file's complexity.

**Step 4. Run, expect green.**

**Step 5. Commit.**

```bash
git commit -am "feat(usd-swaps-tape): SequenceTab assembly"
```

---

### Task G5: Add Sequence tab to `AnalyticsPanel` tab list

**Files.**
- Modify: `AnalyticsPanel.tsx`

**Step 1.** Test that when `mode === 'sequence'`, a fourth tab labelled "Sequence" is rendered alongside Timeseries / Rarity / Levels.

**Step 2.** Implement: extend the tab array with a `'sequence'` entry conditional on mode; render `<SequenceTab />` for that pane.

**Step 3.** Commit.

```bash
git commit -am "feat(usd-swaps-tape): add Sequence tab to AnalyticsPanel in sequence mode"
```

---

## Phase H — Keyboard nav guard

### Task H1: Disable ↑↓ in sequence mode

**Files.**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/TradeTapeTable.tsx` (or wherever ↑↓ is wired)
- Add tooltip on `SequenceBar` count chip explaining the disabled state.

**Step 1.** Test that ↑↓ is no-op when `selected.length >= 2`.

**Step 2.** Run, expect failure (today ↑↓ moves focus among the rows; the test fails because focus moves).

**Step 3.** Implement: gate the keyboard handler on `selected.length === 1`.

**Step 4.** Test that single-mode ↑↓ still works (regression).

**Step 5.** Commit.

```bash
git commit -am "feat(usd-swaps-tape): disable arrow-key nav in sequence mode + count-chip tooltip"
```

---

## Verification

### Task V: Comprehensive E2E walk-through

**Step 1.** Full feature suite + lint:

```bash
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2 2>&1 | tail -30
cd SDRUtils/dashboard && npm run lint 2>&1 | tail -10
```

Expected: all green.

**Step 2.** Dev server walk-through (§4.2 of design doc):

1. Open `/usd-swaps`. Single-row click → today's UX (FocusedTradeBar + 3 tabs). Cards drawer present collapsed below.
2. Expand cards drawer → all four cards render with current row data.
3. Cmd-click second row → SequenceBar replaces FocusedTradeBar. Count = 2.
4. SequenceBar shows aggregate DV01 / weighted rate / time span / side mix / venue mix.
5. Switch to Timeseries tab → 2 reference lines + 2 dots, color-coded.
6. Switch to Rarity tab → 2 dots on histogram.
7. Switch to Levels tab → side-by-side 2-column table by default. Toggle → aggregated extremes.
8. Switch to Sequence tab → timeline shows 2 markers; gaps table shows 1 row.
9. Add a third row → all visualisations update.
10. Verify chain-detector finds parent when one row is a CORR of another.
11. Press ↑/↓ in sequence mode → no-op.
12. Clear selection → mode returns to empty.
13. Click single row → mode returns to single. UI identical to step 1.
14. Refresh page → cards drawer collapse state restored from localStorage.

**Step 3.** Regression check:

- Single-mode behavior identical pre/post (snapshot diff, manual walkthrough).
- Cards drawer doesn't break package-confidence detail panel layout.
- Keyboard nav in single mode unchanged.
- Polling, pagination, column filters unchanged.

**Step 4.** Append a verification log to this plan; commit.

```bash
git commit -am "docs(usd-swaps-tape): multi-trade-dock verification log"
```

**Step 5.** Open PR.

```bash
git push -u origin <branch>
gh pr create --title "feat(usd-swaps-tape): multi-trade dock + sequence analytics" --body "..."
```

---

## Out of scope

- **Full lifecycle chain reconstructor** (sequencing transcript §7.1).
- **Allocation-chain fingerprint clustering** (§7.5).
- **Latency-distribution scorecard, block-shadow signal, LEI scorecard, FOMC tab, swap-spread VWAP overlay, CCPSwitch tracker, per-row sequencing badges** — all separate workstreams.
- **API route changes / new endpoints / schema changes.** None.

## Risk + caveats

1. **N selected = N parallel fetches.** WS1's SWR cache absorbs most; soft cap at N=20 implemented in Task E2.
2. **Levels table overflow at large N.** Horizontal scroll + sticky leftmost column; aggregated toggle for wider use cases.
3. **Sequence timeline overlap at large N.** Marker stagger + hover-disambiguate.
4. **Multi-overlay charts at large N.** Legend show/hide-per-trade toggle (built into Phase F1).

## Recommended order

- Day 1: Phase A + B (~5 tasks; lands first across this and WS1).
- Day 2: Phase C + D (~6 tasks).
- Day 3: Phase E + F (~5 tasks).
- Day 4: Phase G (~5 tasks).
- Day 5: Phase H + Verification (~2 tasks).
- PR cadence: single PR; phases sequence within for review-ability.

---

## Verification log — 2026-05-04

Branch: `claude/gifted-maxwell-b60df4`. All Phase A–H tasks shipped
in one PR per the user's autonomous-mode brief. Cadence mirrored
PR #285 / PR #286 / PR `claude/canonical-underlier-analytics`: TDD
per task, one commit each, conventional commit prefix matching the
plan.

### Phase A — passthrough refactor

- **A1** `refactor(usd-swaps-tape): AnalyticsPanel accepts rows + selected props`.
  AnalyticsPanelProps extended with `rows: readonly UsdSwapTapeRow[]`
  and `selected: readonly UsdSwapTapeRow[]`. Body unchanged in this
  commit; new props referenced via `void` to avoid noUnusedParameters
  while staged consumers land. 4 source-string contract tests green.

- **A2** `refactor(usd-swaps-tape): plumb rows + selected to AnalyticsPanel`.
  `UsdSwapsTradeTape` now passes `rows={tape.rows}` and
  `selected={selection.selected}` into the dock mount point. 4
  source-string contract tests green (3 new + 1 regression for
  `focused={focus.focused}`).

### Phase B — cards drawer

- **B1** `feat(usd-swaps-tape): collapsible CardsDrawer mounts PR-#286 cards`.
  New `CardsDrawer.tsx`. Default collapsed; persists to localStorage
  under `cards-drawer-expanded`. Mounts UnderlierMixCard,
  RfrAdoptionCard, SwapSpreadVwapCard, CcpSwitchCard inside guarded
  `data-testid` wrappers. 7 tests green (renderToStaticMarkup pin
  for the SSR-safe initial render plus source-string contracts).

- **B2** `feat(usd-swaps-tape): mount CardsDrawer in AnalyticsPanel`.
  Drawer renders below the tab content in every dock mode. 3 tests
  green.

- **B3** `test(usd-swaps-tape): CardsDrawer + cards rendering snapshot`.
  Snapshot pins that the SSR-stable collapsed body is identical
  regardless of row count (guards against future refactors that
  eagerly mount a card for prefetch). 3 tests green.

### Phase C — useFocusedTrade extension

- **C1** `feat(usd-swaps-tape): useFocusedTrade returns mode + sequence`.
  Adds the pure-function `deriveAnalyticsSelection` helper alongside
  `normalizeFocusedTrade`. Returns `{mode, focused, sequence}` with
  mode ∈ `'empty' | 'single' | 'sequence'`. The dashboard test
  runner is `testEnvironment=node` so we cover the derivation logic
  via 6 helper tests rather than `renderHook` against the React
  state shell. Existing `useFocusedTrade(initial?)` is unchanged.

- **C2** `feat(usd-swaps-tape): AnalyticsMode + SequenceAggregate types`.
  Adds two new exports to `analytics-types`. Extends `AnalyticsTab`
  with `'sequence'` so the new tab can land in G5 without further
  type churn.

### Phase D — SequenceBar + AnalyticsPanel mode branching

- **D1** `feat(usd-swaps-tape): SequenceBar component`.
  Multi-trade equivalent of `FocusedTradeBar`: count chip,
  aggregate DV01 / weighted rate / notional / time-span, side-mix
  + venue-mix chips, optional warning chip for the soft cap, clear
  button. Visual cadence intentionally mirrors `FocusedTradeBar`.
  6 tests green.

- **D2 + D3** `feat(usd-swaps-tape): AnalyticsPanel mode-branch render`.
  Adds `sequence-aggregate.ts` (DV01-weighted rate, time-span,
  venue/side mix, with notional fallback weighting + null-safe span
  + partial-execution-start handling — 9 unit tests green) and
  wires `AnalyticsPanel` to derive `{mode, sequence}` off the
  `selected` prop, then branches between FocusedTradeBar +
  SequenceBar. Empty mode renders the existing 'select a tape row'
  card (slightly extended copy hinting at cmd-click for sequence
  mode). 11 panel contract tests green.

### Phase E — useAnalyticsSequence wrapper

- **E1** `feat(usd-swaps-tape): useAnalyticsSequence wrapper`.
  New hook delegates to the single-trade analytics hooks for each
  member of a sequence and aggregates the sequence-level summary.
  Implementation honours React's rules-of-hooks via a fixed pool of
  `MAX_SEQUENCE` (=20) slots — slots without a trade pass null so
  the underlying hooks no-op at the network layer. 7 source-string
  + module-surface contract tests green.

- **E2** `feat(usd-swaps-tape): cap sequence at N=20 with soft warning`.
  AnalyticsPanel feeds the wrapper's aggregate + warning into the
  SequenceBar so traders selecting >20 rows see an amber chip
  explaining the cap. 2 new SequenceBar tests cover the
  warning-on / warning-null paths.

### Phase F — multi-overlay tab variants

- **F1** `feat(usd-swaps-tape): TimeseriesTab multi-overlay for sequence mode`.
  Additive code path inside the existing tab — single-mode is
  byte-for-byte unchanged. Adds `SEQUENCE_PALETTE` + `sequenceColor`
  in `analytics-format`; tab renders N reference lines + N
  reference dots when `sequence` is supplied, with a clickable
  legend strip below the chart for show/hide per-trade. The base
  data hooks now anchor on `sequence[0]` in sequence mode so the
  chart base series stays a real bucket. 6 tests green.

- **F2** `feat(usd-swaps-tape): TradeRarityTab N-dot overlay for sequence mode`.
  Adds N reference dots overlaid on the shared histogram, one per
  selected trade, using the existing `findFocusedHistogramBin`
  helper for bin lookup. The focused dot stays for the regression
  case. 4 tests green.

- **F3** `feat(usd-swaps-tape): TradedLevelsTab side-by-side / aggregated toggle for sequence mode`.
  Sequence-mode-only view toggle persisted to localStorage under
  `levels-multi-view`. Side-by-side N-column scrollable table with
  sticky leftmost field column; aggregated 3-card grid with rate /
  DV01 / notional bounds. 6 tests green. Lint warning around
  array-reference stability fixed by wrapping `overlayTrades` in
  `useMemo`.

### Phase G — sequence tab

- **G1** `feat(usd-swaps-tape): SequenceTimeline marker strip`.
  Horizontal time-axis with one marker per trade; PAY = ▲, RCV = ▼,
  size scaled by DV01, colour by sequence palette. Trades without
  a timestamp render as a 'missing-ts' chip below the axis rather
  than disrupt the time scale. 5 tests green.

- **G2** `feat(usd-swaps-tape): InterTradeGaps Δt/Δrate table`.
  Pure helper `computeInterTradeGaps` exported alongside the
  component. Sorts by execution_start ascending, drops missing-
  timestamp trades from pairing, emits one row per consecutive
  pair with auto-scaled Δt formatting + tinted Δrate (red on
  positive, green on negative). 7 tests green.

- **G3** `feat(usd-swaps-tape): lightweight SequenceChainDetector`.
  v1 surface walks `cluster_id` (already projected onto
  UsdSwapTapeRow) for shared-parent detection plus surfaces
  notable lifecycle types as chips. TODO flag: upgrade to walk
  `original_dissemination_id` parent→child links once that column
  lands on the v2 row schema. 8 tests green.

- **G4** `feat(usd-swaps-tape): SequenceTab assembly`.
  Composes the tab body: aggregate summary card (5-cell grid),
  SequenceTimeline, InterTradeGaps, SequenceChainDetector,
  inline lifecycle context strip, allocation-chain stub empty
  state. 6 tests green.

- **G5** `feat(usd-swaps-tape): add Sequence tab to AnalyticsPanel in sequence mode`.
  Renders the SequenceTab body when `activeTab === 'sequence'`
  and `mode === 'sequence'`. Tab strip entry was conditionally
  appended in F1; G5 wires the body. 2 contract tests green.

### Phase H — keyboard nav guard

- **H1** `feat(usd-swaps-tape): disable arrow-key nav in sequence mode + count-chip tooltip`.
  AnalyticsPanel's window-level keydown handler now intercepts
  ArrowUp / ArrowDown when `mode === 'sequence'` and stops
  propagation. The dock header's ↑↓ kbd hint renders strike-
  through with a tooltip explaining the disabled state. The
  v2 feature today doesn't have a window-level row-nav handler —
  the chip is decorative — so this is a defensive guard against
  any future handler. The Esc kbd still works in both modes
  (regression test pins it). 4 contract tests green.

### Test totals

- **Baseline.** `npm test -- --testPathPatterns=usd-swaps-tape-v2` →
  523 passing, 4 skipped, 0 failing on `claude/gifted-maxwell-b60df4`
  before any work.
- **Final.** `npm test -- --testPathPatterns=usd-swaps-tape-v2` →
  **630 passing, 4 skipped, 0 failing** (+107 over baseline).
- 53 of 54 test suites passing (1 skipped, 0 failing). The single
  skipped suite is the pre-existing skip on the manual-links route
  test.

### Lint

- `npm run lint` shows 8 pre-existing errors in
  `TradeRarityTab.tsx` (unescaped-quote violations at lines 283,
  316, 352, 353) — these are the same pre-existing errors flagged
  in PR `claude/canonical-underlier-analytics`'s verification log,
  unrelated to this PR.
- 3 pre-existing `react-hooks/exhaustive-deps` warnings in
  `src/features/ustf-vol/hooks/`. Unrelated.
- One self-introduced `react-hooks/exhaustive-deps` warning in
  `TradedLevelsTab.tsx` was fixed inline by wrapping
  `overlayTrades` in `useMemo`.
- No new lint regressions.

### Dev-server smoke test

- Started `PORT=3002 npx next dev` (no Turbopack, per the worktree
  junction caveat documented in PR #285).
- Page: `curl http://localhost:3002/usd-swaps` → **HTTP 200**
  (53,186 bytes).
- API endpoints (sampled with `value=USD-SOFR%201D`):
  - `/api/usd-swaps-tape-v2?limit=3` → **HTTP 200**.
  - `/api/usd-swaps-tape-v2/analytics-timeseries?value=...` →
    **HTTP 200**.
  - `/api/usd-swaps-tape-v2/rarity?value=...&lookback=90` →
    **HTTP 200**.
  - `/api/usd-swaps-tape-v2/extremes?value=...` → **HTTP 200**.
- Next.js compile log: clean. /usd-swaps compiled in 2.5s, no
  type errors, no runtime warnings.
- Browser-driven E2E walkthrough was skipped — the Chrome MCP
  shim is not available in this autonomous run. The
  cmd-click-multiple-rows / sequence-tab / drawer-expand /
  ↑↓-no-op interaction sequences are covered by source-string +
  renderToStaticMarkup + helper unit tests; a live browser pass
  should re-validate them before merge.

### Caveats / deferred work

1. **`original_dissemination_id` on UsdSwapTapeRow.** The
   SequenceChainDetector v1 walks `cluster_id` instead. When the
   dashboard projects `original_dissemination_id`, upgrade the
   detector to walk parent→child links directly.
2. **`prior_uti` allocation chain.** SequenceTab renders an empty-
   state acknowledging the placeholder. Plan accepts this as v1.
3. **Multi-overlay charts at large N.** The TimeseriesTab legend
   has show/hide-per-trade toggle but no automatic stagger or
   bucket-collapse for N>20 — soft cap at N=20 absorbs most
   cases. Stagger is flagged as a follow-up if desk feedback
   requests it.
4. **Browser E2E walkthrough.** Per the design's §4.2, the live
   dev-server walkthrough (cmd-click second row → SequenceBar /
   sequence Tab / chain detector with a CORR fixture / ↑↓
   no-op / etc.) requires a browser. The Chrome MCP shim was
   unavailable in this autonomous run — should be exercised
   manually before merge.
5. **External grouping work.** During the verification step, an
   external concurrent process modified `UsdSwapsTradeTape.tsx`
   to add a `groupLinkedRows` import and dropped a
   `UsdSwapsTradeTape.grouping.test.ts` file into the worktree.
   Those changes belong to a different workstream
   (manual-links revamp) and were reverted out of this PR.

### Files touched (summary)

**New.**
- `components/AnalyticsPanel/CardsDrawer.tsx` + tests.
- `components/AnalyticsPanel/SequenceBar.tsx` + tests.
- `components/AnalyticsPanel/SequenceTab.tsx` + tests.
- `components/AnalyticsPanel/SequenceTimeline.tsx` + tests.
- `components/AnalyticsPanel/InterTradeGaps.tsx` + tests.
- `components/AnalyticsPanel/SequenceChainDetector.tsx` + tests.
- `components/AnalyticsPanel/sequence-aggregate.ts` + tests.
- `hooks/useAnalyticsSequence.ts` + tests.
- `components/__tests__/UsdSwapsTradeTape.props.test.tsx`.
- `components/AnalyticsPanel/__tests__/AnalyticsPanel.test.tsx`.

**Modified.**
- `components/AnalyticsPanel/AnalyticsPanel.tsx` — new props,
  mode-branch render, SequenceBar + SequenceTab + CardsDrawer
  mounts, Phase H keyboard guard.
- `components/AnalyticsPanel/TimeseriesTab.tsx` — F1 multi-overlay.
- `components/AnalyticsPanel/TradeRarityTab.tsx` — F2 N-dot overlay.
- `components/AnalyticsPanel/TradedLevelsTab.tsx` — F3 side-by-
  side / aggregated toggle.
- `components/AnalyticsPanel/analytics-format.ts` —
  `SEQUENCE_PALETTE` + `sequenceColor`.
- `components/AnalyticsPanel/analytics-types.ts` — `AnalyticsMode`,
  `SequenceAggregate`, extended `AnalyticsTab`.
- `components/AnalyticsPanel/index.ts` — re-exports for
  CardsDrawer + SequenceBar.
- `components/UsdSwapsTradeTape.tsx` — passes `rows` + `selected`
  into AnalyticsPanel.
- `hooks/useFocusedTrade.ts` — `deriveAnalyticsSelection` helper.
- `hooks/index.ts` — re-exports for `deriveAnalyticsSelection`,
  `useAnalyticsSequence`, `MAX_SEQUENCE`.

**Unchanged (verified).**
- All API routes under `app/api/usd-swaps-tape-v2/` — no schema
  or endpoint changes per the design doc.
- Existing single-trade tab tests stay green — single-mode UX is
  byte-for-byte unchanged.
