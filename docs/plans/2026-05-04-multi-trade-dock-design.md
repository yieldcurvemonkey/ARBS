# USD Swaps Tape v2 — Multi-Trade Dock + Sequence Analytics — Design

**Date.** 2026-05-04
**Companion plan.** [docs/plans/2026-05-04-multi-trade-dock-implementation.md](2026-05-04-multi-trade-dock-implementation.md) (forthcoming)
**Routes affected.** `/usd-swaps` (v2 redirect target).
**Feature module.** `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/`
**Stack.** Same as WS1. No new runtime dependencies.

---

## 0. Why this plan

The analytics dock today binds to exactly one focused trade.
`useFocusedTrade` derives `FocusedTrade | null` from `selection.selected[0]` at
[useFocusedTrade.ts:60-113](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useFocusedTrade.ts:60); `AnalyticsPanel` and its three tabs (Timeseries,
Rarity, Levels) all consume `focused: FocusedTrade`. Selecting multiple rows is
supported by the table (PrimeReact checkbox multi-select via
[useRowSelection.ts:11-23](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useRowSelection.ts:11)) but only `selected[0]` is shown in the dock.

Two pressures motivate change:

1. **Sequencing carries information the static print does not.** When two or more
   trades are selected together, their *ordering* in time, venue mix, lifecycle
   chain, and allocation lineage carry positioning signals that no single-trade
   analytic can capture. The dock should let the analyst select N trades and treat
   them as a sequence whose analytics adapt to that focus. (Motivation in detail in
   the SDR sequencing transcript supplied with this workstream; not summarised here.)
2. **Four PR #286 cards are exported but unmounted** — `UnderlierMixCard`,
   `RfrAdoptionCard`, `SwapSpreadVwapCard`, `CcpSwitchCard`. They need the loaded
   `UsdSwapTapeRow[]` collection, not just `focused`, and `AnalyticsPanel` today
   doesn't receive `rows`. The same passthrough refactor that unblocks multi-trade
   mode unblocks these cards. This is documented as a deferred follow-up in the
   verification log of [2026-05-04-canonical-underlier-analytics.md](2026-05-04-canonical-underlier-analytics.md).

When `selected.length === 1` the dock must look identical to today.

---

## 1. Approach

Thread `rows` and `selected` into `AnalyticsPanel` alongside `focused`. Derive a
`mode` from `selected.length`. In `single` mode, render today's UX. In `sequence`
mode (N≥2), replace `FocusedTradeBar` with a `SequenceBar`, render multi-overlay
variants of the three existing tabs, add a new "Sequence" tab, and mount the four
PR #286 cards as a collapsed always-on drawer below the tab area.

The user has chosen the **sequence-as-focus** semantic: when N≥2, the *sequence
itself* is the focus. The analytics adapt to that focus.

### 1.1 Selection / focus / mode

```ts
useFocusedTrade(selected: UsdSwapTapeRow[]) → {
  mode: 'empty' | 'single' | 'sequence'   // = selected.length-derived
  focused: FocusedTrade | null              // present when mode === 'single'
  sequence: FocusedTrade[] | null           // present when mode === 'sequence'
}
```

`useFocusedTrade` extends to return all three; tabs / dock components branch on
`mode`. Existing single-trade code paths read `focused`; new code paths read
`sequence`.

### 1.2 Passthrough refactor (shared with WS1 prerequisite)

`AnalyticsPanel` props extend:

```ts
interface AnalyticsPanelProps {
  rows: readonly UsdSwapTapeRow[]      // NEW — for cards drawer + chain detector
  selected: readonly UsdSwapTapeRow[]  // NEW — for sequence mode
  focused: FocusedTrade | null         // existing — for single mode
  onClose: () => void
  onClearFocused: () => void
  // chart / histogram / panel sizing — existing
}
```

`UsdSwapsTradeTape` plumbs `tape.rows` and `selection.selected` through. This is
**Phase A** of this workstream and lands first; WS1 builds on the stable hook
surface afterwards.

### 1.3 SequenceBar

Replaces `FocusedTradeBar` when `mode === 'sequence'`. Shows:

- Count chip ("Sequence (3)")
- Aggregate DV01, weighted fixed rate, total notional
- Time span (first → last `execution_start`)
- Side mix ("2 PAY / 1 RCV")
- Venue mix ("TWSF: 1, BBSF: 2")
- Clear-selection button

### 1.4 Multi-overlay tab variants

- **Timeseries** — N reference lines + N reference dots, color-coded by index in
  selection. Legend chip per trade with show/hide toggle.
- **Rarity** — same shared histogram, N dots overlaid (one per selected trade).
  Per-dot tooltip identifies which trade. No re-binning.
- **Levels** — toggle (default = side-by-side N-column table; alt = aggregated
  extremes scoped to the union of all selected rates). Toggle persists to
  localStorage. User chose **both via toggle**.

### 1.5 New Sequence tab

Mechanical signals only. Game-theoretic interpretation belongs in
tooltips/help if anywhere — not in the UI.

Content:

- **Timeline strip** — horizontal time axis, one marker per trade, marker shape
  encodes side (▲ PAY / ▼ RCV), marker size encodes DV01, marker colour encodes
  venue. Hover reveals trade detail.
- **Aggregate summary card** — duplicates SequenceBar metrics in a chart-friendly
  full-width layout.
- **Inter-trade gaps** — table of (Δt, Δrate) between consecutive executions,
  ordered by time.
- **Lightweight chain detection** — if any selected row has a non-null
  `original_dissemination_id`, walk the link to the parent in the loaded `rows[]`
  and surface as "this row is a CORR/MODI/TERM of `<parent>`". If two selected
  rows share the same `original_dissemination_id`, flag "shared parent". Walk only
  within `rows[]` — full chain reconstruction across the loaded window is out of
  scope (see §6).
- **Allocation chain stub** — if any row exposes a `prior_uti` field (Phase 2 of
  the v2 schema may already populate this; verify in implementation), surface as
  "linked to `<prior_uti>`". If `prior_uti` is not on the row schema today, the
  stub renders an empty state and the field is added in a separate workstream.
- **Compression / lifecycle context** — render `lifecycle_type` and
  `economic_class` per selected row in a compact strip.

This is a v1 surface. Deeper analytics (allocation-chain fingerprint clustering,
latency-distribution scorecard, block-shadow signal) are flagged as separate
workstreams that can build on this foundation later.

### 1.6 Card mounting (always-on collapsed drawer)

Below the tab content, a collapsible drawer mounts `<UnderlierMixCard rows={rows} />`,
`<RfrAdoptionCard rows={rows} />`, `<SwapSpreadVwapCard rows={rows} />`,
`<CcpSwitchCard rows={rows} />`. Default state: collapsed (per user direction).
The drawer is always present (single mode and sequence mode); user expands when
interested. Collapsed state persists to localStorage.

The cards are pure aggregations over the loaded row set; they don't depend on
`focused` or `selected`. They unblock independent of multi-trade mode.

### 1.7 useAnalyticsSequence wrapper

New hook (the user explicitly chose the wrapper approach over extending hook
signatures):

```ts
function useAnalyticsSequence(
  sequence: FocusedTrade[] | null,
  options: SequenceOptions,
): {
  perTrade: Array<{
    trade: FocusedTrade
    timeseries: ReturnType<typeof useAnalyticsTimeseries>
    rarity:     ReturnType<typeof useRarityData>
    extremes:   ReturnType<typeof useExtremesData>
  }>
  aggregate: SequenceAggregate
}
```

Internally calls the existing single-trade hooks per element of `sequence`,
preserving WS1's caching and dedup benefits. The `aggregate` field computes
sequence-level summaries (aggregate DV01, weighted rate, time span, etc.) for
SequenceBar + summary card consumption.

In single mode, tabs continue to use `useAnalyticsTimeseries(focused)` directly. In
sequence mode, tabs use the wrapper's `perTrade` array.

### 1.8 Keyboard nav in sequence mode

Disabled per user direction — ↑↓ are no-ops when `mode === 'sequence'`. Single
mode preserves current ↑↓ behavior. A subtle tooltip on the SequenceBar count chip
explains the disabled state.

---

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  UsdSwapsTradeTape                                           │
│    rows ─┐                                                    │
│    selection.selected ─┐                                      │
│    focus ───────────┐ │                                       │
│                     ▼ ▼ ▼                                     │
│              ┌─────────────────────┐                         │
│              │   AnalyticsPanel    │                         │
│              │   mode = derived    │                         │
│              └─────────┬───────────┘                         │
│                        │                                      │
│        ┌───────────────┴────────────────┐                    │
│        ▼ single                          ▼ sequence           │
│  ┌──────────────┐                ┌──────────────┐            │
│  │FocusedTrade  │                │SequenceBar   │            │
│  │     Bar      │                └──────────────┘            │
│  └──────────────┘                  + multi-overlay tabs       │
│  + 3 single tabs                   + Sequence tab             │
│                                                                │
│  ┌──────────────────────────────────────────────────────┐    │
│  │   Cards drawer (always present, collapsed default)   │    │
│  │   UnderlierMix · RfrAdoption · SwapSpreadVwap · CCP  │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 New / modified files (preview)

**New.**
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceBar.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceTab.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceTimeline.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/InterTradeGaps.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/SequenceChainDetector.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/AnalyticsPanel/CardsDrawer.tsx`
- `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/hooks/useAnalyticsSequence.ts`

**Modified.**
- `useFocusedTrade.ts` — add `mode` + `sequence` outputs.
- `AnalyticsPanel.tsx` — add `rows` + `selected` props; mode-branch render.
- `TimeseriesTab.tsx` — multi-overlay support.
- `TradeRarityTab.tsx` — N-dot overlay.
- `TradedLevelsTab.tsx` — toggle: side-by-side vs aggregated.
- `analytics-types.ts` — add `Sequence`, `AnalyticsMode`, `SequenceAggregate` types.
- `UsdSwapsTradeTape.tsx` — pass new props.

**Unchanged (verified).**
- `useRowSelection.ts` — already supports multi-select.
- `useTradeTapeData.ts` — no change.
- API routes — no change.

---

## 3. Constraints satisfied

| Constraint | How |
|---|---|
| Single-mode UX preserved | When `selected.length === 1`, AnalyticsPanel renders `FocusedTradeBar` + 3 single-trade tabs identical to today. |
| Tabs not rewritten | Multi-overlay variants are additive code paths inside existing tab files; single-trade rendering is unchanged. |
| Existing tests stay green | Current tab tests assume `focused: FocusedTrade`; the test path renders single mode where behavior is unchanged. |
| Cards land independently | Cards drawer mounts in both single and sequence modes; trader sees the four PR #286 cards regardless. |
| Sequencing transcript framing respected | Sequence tab v1 surfaces mechanical signals only; deeper game-theoretic analytics deferred to separate workstreams. |
| Keyboard nav in sequence mode disabled | Per user direction. Single-mode behavior unchanged. |
| WS1 surface stable | Hook signatures (`useAnalyticsTimeseries`, etc.) are extended via a wrapper hook (`useAnalyticsSequence`) that delegates to them; WS1's swap can land cleanly on top. |

---

## 4. Test plan

User direction: "be very comprehensive in front end testing".

### 4.1 Unit / integration

- `useFocusedTrade.test.ts` — extended for mode derivation across selection sizes (0 / 1 / 2 / N).
- `useAnalyticsSequence.test.ts` — delegation to single-trade hooks; aggregation across N traces; updates when sequence changes.
- `SequenceBar.test.tsx` — renders all aggregate fields; clear button works; correct count.
- `SequenceTab.test.tsx` — timeline renders N markers; gaps table sorted by time; chain detector finds parent in `rows[]` when present, no-ops when absent; allocation stub renders empty state when `prior_uti` not on row.
- `SequenceTimeline.test.tsx` — marker shape/size/colour encodings.
- `InterTradeGaps.test.tsx` — Δt + Δrate computation, descending sort.
- `SequenceChainDetector.test.tsx` — parent lookup; shared-parent flag; no-op when no `original_dissemination_id`.
- `CardsDrawer.test.tsx` — collapsed default; expand / collapse toggle persists to localStorage; mounts all four cards with `rows` prop.
- `AnalyticsPanel.test.tsx` — mode branching: empty / single / sequence rendering; card drawer always present.
- `TimeseriesTab.multi.test.tsx` — N overlay reference lines + dots; legend per trade; show/hide toggle.
- `TradeRarityTab.multi.test.tsx` — N dots on shared histogram; tooltip per dot.
- `TradedLevelsTab.multi.test.tsx` — toggle between side-by-side and aggregated; toggle state persisted.

### 4.2 Comprehensive E2E (dev server)

`PORT=3001 npx next dev`:

1. Open `/usd-swaps`. Single-row click → today's UX (FocusedTradeBar + 3 tabs).
2. Verify cards drawer is present (collapsed) below tabs in single mode.
3. Expand cards drawer → all four cards render with current row data.
4. Cmd-click second row → SequenceBar replaces FocusedTradeBar. Count = 2.
5. SequenceBar shows aggregate DV01, weighted rate, time span, side mix, venue mix.
6. Switch to Timeseries tab → 2 reference lines + 2 dots, colour-coded.
7. Switch to Rarity tab → 2 dots on histogram.
8. Switch to Levels tab → side-by-side 2-column table by default. Toggle → aggregated extremes.
9. Switch to Sequence tab → timeline shows 2 markers; gaps table shows 1 row.
10. Add a third row → all visualisations update.
11. Verify chain-detector finds parent when one row is a CORR of another (use a known fixture).
12. Press ↑/↓ in sequence mode → no-op.
13. Clear selection → mode returns to empty.
14. Click single row → mode returns to single. UI identical to step 1.
15. Refresh page → cards drawer collapse state restored from localStorage.

### 4.3 Regression

- Verify single-mode behavior identical pre/post (snapshot diff, manual walkthrough).
- Verify cards drawer doesn't break package-confidence detail panel layout.
- Verify keyboard nav still works in single mode.
- Verify polling, pagination, column filters unchanged.
- Verify manual-link dialog unchanged (post-WS3 tests cover the v2 revamped flow).

---

## 5. Build sequence

One PR; phases sequence within.

- **Phase A — passthrough refactor.** `rows` + `selected` props on `AnalyticsPanel`, plumbing from `UsdSwapsTradeTape`. No render change yet. Tests pin new props. *(Lands first across this and WS1.)*
- **Phase B — Cards drawer.** Mount four PR-#286 cards in collapsed drawer, both modes. localStorage state. Tests.
- **Phase C — `useFocusedTrade` extension.** Add `mode` + `sequence` outputs. Tests.
- **Phase D — SequenceBar + AnalyticsPanel mode branching.** Render either `FocusedTradeBar` or `SequenceBar`. Tests.
- **Phase E — `useAnalyticsSequence` hook.** Delegating wrapper. Tests.
- **Phase F — Multi-overlay tab variants.** Timeseries (N lines/dots) → Rarity (N dots) → Levels (toggle). One commit per tab.
- **Phase G — Sequence tab.** Timeline + gaps + summary + chain detector + allocation stub + lifecycle context. Tests per sub-component.
- **Phase H — Keyboard-nav guard.** Disable ↑↓ in sequence mode. Tests.
- **Verification — full E2E** walk-through (§4.2) + regression check (§4.3).
- **Open PR.**

---

## 6. Out of scope

- **Full lifecycle chain reconstructor** (transcript §7.1). v1 walks links only within the loaded `rows[]`. A separate workstream would persist a chain table and reach across the loaded window.
- **Allocation-chain fingerprint clustering** (transcript §7.5). v1 surfaces stub hints if `prior_uti` is on the row; clustering ML is a separate workstream.
- **Latency-distribution scorecard** (transcript §7.2), block-shadow signal (§7.4), LEI scorecard (§7.7), FOMC tab (§7.9), swap-spread VWAP overlay with macro annotations (§7.10), CCPSwitch tracker (§7.11), per-row sequencing badges (§7.12) — all flagged as future workstreams motivated by the sequencing transcript.
- **API route changes.** Sequence analytics in v1 are pure aggregations over per-trade single-fetch results.
- **New endpoints.** None.
- **Schema changes.** None expected. If `prior_uti` isn't already projected by the v2 tape route, the allocation stub renders empty state and the field is added in a separate workstream.

---

## 7. Risks

1. **N selected trades = N parallel analytics-fetches.** A trader who selects 10 rows fires 30 backend requests (3 per trade). Mitigation: WS1's SWR + cache + dedup absorbs most; UI cap at N=20 with a soft warning if exceeded.
2. **Levels table overflow at large N.** Side-by-side table with 10+ columns is unreadable. Mitigation: horizontal scroll + sticky leftmost column; aggregated toggle handles wider use cases.
3. **Cards drawer size.** Four cards may not fit at smaller viewport heights. Mitigation: drawer collapsed by default; user expands at will.
4. **Sequence tab timeline at large N.** Beyond ~30 trades, markers overlap. Mitigation: marker stagger + hover-to-disambiguate.
5. **Keyboard nav disabled may surprise traders.** Mitigation: tooltip on the selection count chip explaining the mode.
6. **Multi-overlay charts at large N.** 10 reference lines on Timeseries chart is visual chaos. Mitigation: legend with show/hide-per-trade toggles (built into Phase F).
7. **WS1 dependency.** WS2 lands first; WS1 then swaps hooks under it. If WS2's sequence-mode flow exposes a corner case in the existing hook surface, WS1's swap may need to absorb it. Mitigation: WS2's `useAnalyticsSequence` wrapper provides a clean integration point.

---

## 8. Rollback

Phase commits are individually revertible:

- Drop Sequence tab (Phase G): single-mode unchanged, multi-overlay tabs remain.
- Drop multi-overlay variants (Phase F): single mode + Sequence tab + cards remain.
- Drop SequenceBar/mode branching (Phase D): N≥2 just shows first selected (regress to today).
- Drop cards drawer (Phase B): four cards remain unmounted (regress to pre-change).
- Drop passthrough (Phase A): full revert.

Each phase ships behind no flag — all are additive — but commits are individually
clean.
