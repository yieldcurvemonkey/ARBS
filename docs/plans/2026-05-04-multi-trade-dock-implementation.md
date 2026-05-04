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
