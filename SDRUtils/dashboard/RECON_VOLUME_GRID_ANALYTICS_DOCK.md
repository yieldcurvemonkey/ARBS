# USD Swaps Tape v2: Volume Grid + Analytics Dock — Recon Report & Implementation Plan

**Date:** 2026-05-06
**Scope:** Volume Grid heatmap, Analytics Dock (Timeseries / Rarity / Traded Levels / Sequence), bucket-equivalence correctness, regression sweep, new analytics opportunities.
**Chrome MCP status:** **UNAVAILABLE** this session. All findings below are code-inferred from static reading + subagent exploration. No live-validated latency measurements, network captures, or screenshots were produced. Every claim that would normally cite a chrome MCP artifact is marked `[CODE-INFERRED]` instead.

---

## 1. Executive Summary

1. **Missing composite index.** Volume grid WHERE clause filters `(contributes_to_flow = TRUE, original_execution_timestamp >= $1)` but the legs table only has single-column indexes on each. A composite index would eliminate the sequential scan on the hot path. `[CODE-INFERRED: _tape_schema_v2.py:idx_tape_v2_legs_flow is single-column]`

2. **Cell modal has no hover-prefetch.** Unlike the analytics dock (which prefetches on 150ms debounce), clicking a volume grid cell cold-fires 3 SQL queries. Adding debounced prefetch on cell hover would make the modal feel instant. `[CODE-INFERRED: useVolumeGridCell.ts uses SWR but no prefetch hook wires to cell hover]`

3. **SWR bypass in useVolumeGrid is a real bug, not a workaround.** The IndexedDB cache provider stores entries keyed by their serialized form. SWR serializes array keys via `unstable_serialize` (producing a stable hash string), but URL-string keys serialize to the URL itself. The provider's `get`/`set` work identically for both — the actual bug was likely a race between the async IndexedDB hydration and the first fetch. The SwrProvider renders children before IndexedDB hydrates, so the first fetch writes to the transient empty-Map fallback, which is discarded when the real provider mounts. `[CODE-INFERRED: SwrProvider.tsx:28-48, IndexedDBCacheProvider.ts]`

4. **Orthogonal-payload split already landed.** `useGrossDv01` and `excludeLargeCusty` toggles don't bust the SWR cache key — the server returns all 4 variants in one payload. This is a significant recent win. `[CODE-INFERRED: analyticsCacheKeys.ts:29-32, analytics-timeseries/route.ts]`

5. **LOCF interpolation is client-side and O(minutes) per render.** `interpolateIntradayMinutely` iterates ~4320 minute-slots (72h) per intraday view switch. For fixed_rate this is cheap, but the sort + Map construction runs on every rawTicks change. Could move server-side with `generate_series`. `[CODE-INFERRED: TimeseriesTab.helpers.ts:150-204]`

6. **Prefix normalization covers SOFR-OIS/SOFR-COMPOUND correctly.** Tests confirm both `USD-SOFR-COMPOUND 1D ...` and `USD-SOFR-OIS Compound 1D ...` normalize to `USD-SOFR-OIS COMPOUND 1D ...`. The route.logic.ts `buildOutrightTapeLabelCandidates` generates both variants for SQL matching. `[CODE-INFERRED: analytics.test.ts, route.logic.ts:38-57]`

7. **UFRO tokens are intentionally preserved in tape_label normalization.** The `ANALYTICS_LIFECYCLE_FLAG_TOKENS` list explicitly excludes UFRO/BLOCK — they describe trade economics, not lifecycle. This means UFRO trades mix into bucket aggregations. Operator decision needed. `[CODE-INFERRED: analytics.ts:72-83]`

8. **Volume grid cells are not memoized.** `VolumeGridCell` is a plain function component with no `React.memo`. On any toggle change (metric, period, color mode, view mode), all 128+ cells re-render even if their data hasn't changed. `[CODE-INFERRED: VolumeGridCell.tsx:58]`

9. **Cell modal runs 3 parallel queries — good.** `Promise.all([tsResult, tradesResult, intradayResult])` in the cell route handler parallelizes the SQL. The dominant cost is SQL execution, not serialization. `[CODE-INFERRED: volume-grid/cell/route.ts:124]`

10. **30s polling is hardcoded with no backoff.** `DEFAULT_REFRESH_INTERVAL_MS = 30_000` in useVolumeGrid.ts. No visibility API integration — polls even when the tab is backgrounded. `[CODE-INFERRED: useVolumeGrid.ts:46]`

11. **Sequence mode allocates 20 fixed hook slots unconditionally.** Every render invokes 60 hooks (20 slots × 3 hooks each). Null-trade slots no-op at the network layer but still run the full useSWR/useMemo chain. `[CODE-INFERRED: useAnalyticsSequence.ts:74-97]`

12. **Color ramp contrast may fail WCAG AA at mid-percentiles.** The foreground switches from dark to light at p15 and p90. The p50 stop is `rgb(221,221,221)` with `text-slate-950` foreground — this should pass, but p25-p49 range (blue-to-gray gradient) against dark text needs empirical validation. `[CODE-INFERRED: colorRamp.ts:6-11, 32-35]`

---

## 2. Recon — Volume Grid

### 2.1 SQL & Route Layer

**Observation:** Two SQL families (`time_of_day` and `rolling`) share an identical CTE structure (`legs → bucketed → prior_summary → current_agg`) but are built by separate functions. The `legs` CTE always computes `COALESCE(l.original_execution_timestamp, l.execution_timestamp)` twice (once for `ts`, once for `day_et` / filtering). `[route.logic.ts:354-430, 451-529]`

**Possible directions:**
- (a) Extract common CTE builder to deduplicate
- (b) Compute `ts` once in the CTE and reference it downstream
- (c) Leave as-is — the SQL planner likely CSE-eliminates it

**Observation:** `rollingBounds` enforces a `4× floor` on lookbackDays (`Math.max(lookbackDays, windowDays * 4)`) so percentile has ≥4 prior windows. When Window=`1w` × Baseline=`1w`, this silently inflates lookback to 28 days. The user sees "Baseline: 1w" but the query reaches back 28 days. `[route.logic.ts:143]`

**Possible directions:**
- (a) Surface the effective lookback in the response payload
- (b) Disable Baseline options that would be silently overridden
- (c) Accept the behavior as intentional floor and document in tagline

### 2.2 Modal Endpoint (`/volume-grid/cell`)

**Observation:** The cell endpoint runs 3 SQL queries in parallel via `Promise.all`. Each query independently joins `legs_v2` to `packages_v2` and filters on `contributes_to_flow`. No shared CTE across the three queries. `[cell/route.ts:124]`

**Observation:** The intraday seasonality query uses `generate_series` server-side for the minute grid — good pattern that the analytics dock intraday LOCF does NOT use. `[cell/route.logic.ts:198-319]`

**Observation:** No hover-prefetch wiring exists for cell hover. The modal only fetches on click via `useVolumeGridCell` (SWR-backed). `[useVolumeGridCell.ts:52-71]`

**Possible directions:**
- (a) Add debounced prefetch on cell hover (reuse the `useAnalyticsPrefetch` pattern)
- (b) Share a base CTE across the 3 cell queries using `WITH` + `CROSS JOIN LATERAL`
- (c) Pre-warm the modal's SWR cache from the grid response payload (grid already has per-cell data)

### 2.3 SWR Provider Divergence

**Observation:** `useVolumeGrid.ts` is the only dock hook bypassing SWR. The comment (lines 6-13) attributes this to "URL-string key path producing no cache entries" in the IndexedDB provider. `[useVolumeGrid.ts:6-13]`

**Analysis:** The IndexedDB cache provider (`IndexedDBCacheProvider.ts`) uses a `Map<string, unknown>` shadow keyed by whatever string SWR passes to `get`/`set`. SWR serializes keys via `unstable_serialize`: array keys become a stable JSON-like hash, URL strings stay as-is. Both should work — the `Map` doesn't discriminate. The likely root cause is the **hydration race**: `SwrProvider.tsx` renders children with an empty-Map fallback until the async `createIndexedDBCacheProvider` resolves. Any SWR fetch that completes during this window writes to the transient fallback map, which is discarded when the real provider mounts. Array-keyed hooks happen to fire after hydration completes (they depend on `focused` being set, which requires a user click); the volume grid fires immediately on mount. `[SwrProvider.tsx:28-48, IndexedDBCacheProvider.ts:92-196]`

**Possible directions:**
- (a) Fix: gate volume grid's first fetch until the SWR provider hydrates (flag in context)
- (b) Fix: in SwrProvider, copy transient-map entries into the real provider on mount
- (c) Accept: the useState/setInterval approach works and has no observable bug

### 2.4 Render & Component Memoization

**Observation:** `VolumeGridCell` is not wrapped in `React.memo`. The parent `VolumeGrid` creates a `cellMap` via `useMemo` (good) and a `gridMaxCurrent` via `useMemo` (good), but iterates `forwardAxis.buckets × tenorAxis.buckets` creating JSX elements every render. Each cell receives an inline-computed `colorPercentile` prop that changes reference on every render. `[VolumeGrid.tsx:22-101, VolumeGridCell.tsx:58]`

**Observation:** `colorForPercentile` is pure and cheap (linear interpolation over 5 stops), but called per-cell per-render. No caching needed — the cost is in React reconciliation, not computation. `[colorRamp.ts:17-30]`

**Possible directions:**
- (a) Wrap `VolumeGridCell` in `React.memo` with a custom comparator
- (b) Extract `colorPercentile` into the `cellMap` so it's computed once
- (c) Profile first (React DevTools Profiler) — if renders are <16ms, skip

### 2.5 Payload Size

**Observation:** The grid response contains `cells[]` (one per populated bucket) + `totals` + `axes`. Default schema: 8 forward × 16 tenor = 128 cells max. Each cell: 11 numeric fields + 2 strings. Estimated payload: ~8-12 KB JSON. Compact and appropriate. `[route.logic.ts:595-683]`

**Possible directions:** No optimization needed. Payload is already lean.

### 2.6 Polling Cadence

**Observation:** `DEFAULT_REFRESH_INTERVAL_MS = 30_000`. No `document.visibilitychange` listener — polls when tab is backgrounded. No exponential backoff on error. `[useVolumeGrid.ts:46, 109-118]`

**Possible directions:**
- (a) Pause polling when `document.hidden === true` (Page Visibility API)
- (b) Reduce to 15s for `today`/`1h` periods (time-of-day sensitive), 60s for weekly+
- (c) Add exponential backoff on consecutive errors

### 2.7 Color/Accessibility

**Observation:** Color ramp stops: blue(0) → lightblue(25) → gray(50) → salmon(75) → red(100). The p50 neutral is `rgb(221,221,221)` — distinguishable from both ends but may be hard to differentiate from p40/p60 for color-vision-deficient users. No deuteranopia-safe fallback. `[colorRamp.ts:6-11]`

**Possible directions:**
- (a) Add a `highContrast` toggle using a blue-to-orange ramp (safer for CVD)
- (b) Add cell border thickness or pattern as a redundant channel
- (c) Run WebAIM contrast check on each stop against `text-slate-950` and `text-slate-100`

### 2.8 Toggle-Bar Density

**Observation:** The header bar contains: collapse button, Notional/DV01 toggle, "WINDOW" label, 8 window buttons, "BASELINE" label, 8 baseline buttons, Activity/Grid toggle, Package select, View select, Forward schema select, Tenor schema select, as-of badge, refresh button. That's 25+ interactive elements in a single `flex-wrap` row. `[VolumeGridCard.tsx:213-314]`

**Possible directions:**
- (a) Move schema selects (Forward, Tenor) into a "Settings" popover
- (b) Move Window + Baseline into a combined "Comparison" popover
- (c) Group Notional/DV01 + View + Color into a "Display" popover
- (d) Leave as-is — traders may prefer one-click access over popover nesting

### 2.9 Modal Information Architecture

**Observation:** The cell modal renders: daily volume bar chart + intraday seasonality line chart (side by side), then a recent trades table below. Clicking a trade row routes its `package_id` to the tape filter and closes the modal. `[VolumeGridCellModal.tsx:66-189]`

**Possible directions:**
- (a) Add a timeseries view (rate chart) to the modal — currently volume-only
- (b) Add IDB/CUSTY split bars to the daily chart
- (c) Show percentile context inline: "this cell is P87 — 3rd busiest 5Y × Spot cell in the last 3M"

---

## 3. Recon — Analytics Dock

### 3.1 EOD Fetching

**Observation:** `useAnalyticsTimeseries` fires two independent SWR hooks: `dailySwr` (always when `bucket != null && !needsIntraday`) and `intradaySwr` (lazy, only when `view === 'INTRADAY'`). The daily path runs `buildOutrightTapeLabelCandidates` first for a fast-path query against the packages table directly (skipping the full `packageAnalyticsCtes` join) when the label is an outright. Falls back to the generic path if the fast path returns 0 rows. `[analytics-timeseries/route.ts:176-392, 426-440]`

**Observation:** The daily SQL uses `(array_agg(fixed_rate ORDER BY ts DESC) FILTER (WHERE fixed_rate IS NOT NULL))[1]` for close rate. This materializes the full array then takes element [1]. `DISTINCT ON (day, platform) ... ORDER BY day, platform, ts DESC` would be an alternative that avoids the array allocation, but would require restructuring the GROUP BY. `[analytics-timeseries/route.ts:338-339]`

**Possible directions:**
- (a) Replace `array_agg(...)[1]` with a `LATERAL` subquery or `DISTINCT ON` for close rate
- (b) Profile the SQL EXPLAIN to see if the array_agg is actually the bottleneck vs the JOIN
- (c) Leave as-is — Postgres optimizes `array_agg` for small groups efficiently

### 3.2 Intraday Fetching

**Observation:** Intraday SQL anchors on `MAX(execution_timestamp) - 72h` for the bucket. The LOCF interpolation is then done client-side in `interpolateIntradayMinutely`. `[analytics-timeseries/route.ts:199, TimeseriesTab.helpers.ts:150-204]`

**Observation:** LOCF complexity: sorts points O(n log n), then iterates O(minutes) where minutes ≈ 4320 (72h × 60). For each minute, looks up a Map entry. Total: O(n log n + 4320). For typical n < 2000 ticks, this is sub-millisecond. `[TimeseriesTab.helpers.ts:154-203]`

**Possible directions:**
- (a) Move LOCF server-side: `generate_series(first_ts, last_ts, '1 minute') LEFT JOIN ... LAST_VALUE(...) OVER (ORDER BY ts ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)`
- (b) Keep client-side but memoize more aggressively (currently via `useMemo` on `[isIntraday, effectiveMetric, rawTicks]` — adequate)
- (c) Reduce to 24h window for LOCF and show 72h only for raw ticks

### 3.3 Hover-Prefetch Correctness

**Observation:** `useAnalyticsPrefetch` builds cache keys using `timeseriesKey`, `rarityKey`, `extremesKey` from `analyticsCacheKeys.ts`. The prefetch passes `removeZeroRates: true` to match the dock-hook default. It reads localStorage for rarity prefs (binMetric, primaryTol, sizeTol) so the prefetch cache key aligns with the dock's key. `[useAnalyticsPrefetch.ts:98-229]`

**Observation:** The `fireIfMissing` function serializes the key via `unstable_serialize` before checking the cache — this matches SWR's internal serialization so the cache check actually works. `[useAnalyticsPrefetch.ts:203-224]`

**Possible direction:** This looks correct by code inspection. Needs live validation (chrome MCP) to confirm the prefetch actually fires on hover and the dock click produces no second network request.

### 3.4 Sequence-Mode Fan-Out

**Observation:** `useAnalyticsSequence` allocates `MAX_SEQUENCE = 20` slots. Each slot runs `useAnalyticsTimeseries` + `useRarityData` + `useExtremesData` unconditionally (60 hook invocations per render). Null-trade slots pass `null` to each hook, which returns early without fetching. `[useAnalyticsSequence.ts:60-114]`

**Observation:** When two trades share the same tape_label, their `timeseriesKey` values are identical. SWR deduplicates these at the cache level — only one fetch fires. However, the 20 `useSWR` calls still run their key-computation and cache-lookup logic. `[analyticsCacheKeys.ts:59-70]`

**Possible directions:**
- (a) Accept the 60-hook overhead — it's React reconciliation cost, not network
- (b) Build a custom `useSWRMulti`-like hook that deduplicates at the key level before invoking SWR
- (c) Reduce MAX_SEQUENCE to 10 if traders rarely select >10 rows

### 3.5 Density/UX

**Observation:** The TimseriesTab control rail has 3 rows: (1) Series pills, Metric seg, View seg, Range seg, Bucket select, Overlays toggles; (2) DV01 Net/Gross toggle, Exclude outliers toggle, Remove 0s toggle, Y min/max inputs; (3) Assumptions strip. That's ~15 interactive controls visible simultaneously. `[TimeseriesTab.tsx:317-530]`

**Possible directions:**
- (a) Collapse row 2 into a "Display settings" popover
- (b) Move Y min/max into the chart area as draggable handles
- (c) Leave as-is — traders using this surface are power users who want immediate access

### 3.6 Plotly vs Recharts Split

**Observation:** `fixed_rate` and `spread_to_mid` render via `DockTimeseriesChart` (Plotly). `dv01`, `notional`, and `VOLUME` views render via Recharts `ComposedChart`. The Plotly chart uses `plotly.js-dist-min` via dynamic import. Recharts and Plotly have different hover, zoom, and axis styling. `[TimeseriesTab.tsx:569-629, 631-885, DockTimeseriesChart.tsx]`

**Observation:** The Plotly chart uses `hovermode: 'x unified'` and custom `hoverlabel` styling. The Recharts chart uses a custom `TsTooltip` component with fixed `position={{ x: 72, y: 8 }}`. Hover behavior will feel different between the two. `[DockTimeseriesChart.tsx:276, TimeseriesTab.tsx:690-696]`

**Possible directions:**
- (a) Migrate all views to Plotly for consistency (Plotly's bar chart is adequate)
- (b) Style the Recharts tooltip to visually match Plotly's `hoverlabel`
- (c) Accept the split — it's a known trade-off for stacked-bar rendering quality

---

## 4. Bucket Equivalence — Empirical Results

### 4.1 Prefix Divergence Catalog

| SDR Variant | Normalized Form | Coverage |
|---|---|---|
| `USD-SOFR-COMPOUND 1D ...` | `USD-SOFR-OIS COMPOUND 1D ...` | Covered `[analytics.ts:109]` |
| `USD-SOFR-OIS Compound 1D ...` | `USD-SOFR-OIS COMPOUND 1D ...` | Covered `[analytics.ts:109]` |
| `USD-SOFR-OIS COMPOUND 1D ...` | `USD-SOFR-OIS COMPOUND 1D ...` | Identity, covered |
| `USD-SOFR-CME-TERM 3M ...` | `USD-SOFR-TERM 3M ...` | Covered `[analytics.ts:107]` |
| `USD-SOFR TERM 3M ...` | `USD-SOFR-TERM 3M ...` | Covered (regex allows whitespace) |
| `USD SOFR OIS Compound 1D ...` | `USD-SOFR-OIS COMPOUND 1D ...` | Covered (regex `[-\s]+`) |
| `PHY` / `PHYSICAL` | `PHYS` | Covered `[analytics.ts:104-105]` |

**Observation:** The `route.logic.ts` `buildOutrightTapeLabelCandidates` function generates BOTH prefix variants for SQL matching via `addSofrOisCompoundVariants`. This means the fast-path outright query correctly finds rows regardless of which prefix the SDR feed used. `[route.logic.ts:38-57]`

**Observation:** The `normalizeAnalyticsTapeLabelSql` function (SQL-side parity) uses POSIX regex in PostgreSQL. It's applied in `packageAnalyticsFilterPredicate` via an OR: `p.tape_label = $1 OR normalized(p.tape_label) = normalized($1)`. This double-match ensures the normalizer doesn't need to be exhaustive — raw matches still work. `[analytics.ts:164-176]`

**Gap identified:** The volume grid does NOT use `normalizeAnalyticsTapeLabel` at all. It groups by `forward_start_years` and `tenor_years` columns, not by tape_label. Prefix divergence is a non-issue for the volume grid — it only matters for the analytics dock timeseries/rarity/extremes which bucket by tape_label. `[route.logic.ts:284-301]`

### 4.2 UFRO Contamination

**Observation:** `ANALYTICS_LIFECYCLE_FLAG_TOKENS` explicitly excludes `UFRO` and `BLOCK`. The comment states: "UFRO (off-market upfront marker) and BLOCK (size flag) stay in — they describe the trade economics, not its lifecycle." `[analytics.ts:72-83]`

**Impact:** A tape_label like `USD-SOFR-OIS COMPOUND 1D Constant Spot 30Y Outright UFRO PHYS` will normalize to `USD-SOFR-OIS COMPOUND 1D CONSTANT SPOT 30Y OUTRIGHT UFRO PHYS` — **different bucket** from `USD-SOFR-OIS COMPOUND 1D CONSTANT SPOT 30Y OUTRIGHT PHYS`. UFRO trades form their own bucket and don't contaminate the non-UFRO bucket.

**However:** The `removeZeroRates` filter (default ON) already drops most off-market trades since UFRO prints often have `fixed_rate = 0`. The contamination risk is limited to UFRO trades with non-zero rates.

**Quantification:** Cannot be done without live data access (chrome MCP or direct SQL). Need to query: `SELECT COUNT(*) FROM arbs_usd_swap_tape_packages_v2 WHERE tape_label ILIKE '%UFRO%' AND weighted_fixed_rate <> 0` to understand the actual population.

### 4.3 Options Matrix

| Option | Description | Pros | Cons |
|---|---|---|---|
| **(a) Collapse-and-filter at SQL** | Strip UFRO from tape_label normalization; add `WHERE NOT is_ufro` to analytics queries | Clean baseline, simple | Loses all UFRO visibility; may hide legitimate off-market flow the trader wants to see |
| **(b) Split into toggle-able series** | Keep UFRO in a separate bucket; add "Include off-market" toggle to dock controls | Trader controls visibility; no data loss | Adds UI complexity; another toggle in an already dense control rail |
| **(c) Badge on focused-trade marker** | Leave data as-is; add a "UFRO" badge on the reference line when the focused trade is off-market | Zero-risk; informational | Doesn't address the percentile contamination question |
| **(d) Hybrid** | Collapse UFRO prefix in normalizer (merge into same bucket); add `is_ufro` flag to the timeseries point payload; let client filter/highlight | Best of both; no bucket fragmentation | Most implementation work; server payload grows |

**Operator decision required** — see Section 8.

---

## 5. New Analytics Opportunities

### 5.1 Volume Grid Enhancements

| Feature | Why traders care | Data available | Data needed | Rough complexity | Reference |
|---|---|---|---|---|---|
| **Time-of-day curve overlay per cell** | See if 10Y Spot is quiet at open but hot after 10am | Intraday seasonality already computed for cell modal | None — `buildIntradaySeasonalitySql` exists | S | `cell/route.logic.ts:198` |
| **Day-of-week seasonality** | Monday vs Friday volume patterns differ (end-of-week hedging) | `day_et` in legs CTE | Add `EXTRACT(DOW FROM ...)` to GROUP BY | S | `route.logic.ts:362` |
| **FOMC/NFP/auction proximity flags** | Volume spikes around macro events; trader wants to discount those | `fomc_meeting_label` on legs, auction schedule external | Auction calendar ingestion | M | `volumeGridBuckets.ts:209` |
| **Lifecycle composition (NEW vs UNWIND)** | Distinguish genuine new flow from churn/unwind activity | `economic_class` on legs | Add `COUNT(*) FILTER (WHERE economic_class = 'ECONOMIC_UNWIND')` | S | `CLAUDE.md:19-22` |
| **IDB vs CUSTY directional skew** | Which side is more active — dealer flow or client demand? | Already split in `idb_current` / `custy_current` | Percentage delta visualization | S | `route.logic.ts:403-405` |
| **Volume-of-volume** | Volatility of the volume series — is today's volume unusual for this time of week? | Prior window arrays in `prior_array` | Client-side stddev of prior_array | S | `route.logic.ts:420` |
| **Cross-cell co-movement** | When 2Y Spot is hot, is 5Y also hot? Correlation structure | Full grid time series | Historical grid snapshots (new table) | L | N/A |

### 5.2 Analytics Dock Enhancements

| Feature | Why traders care | Data available | Data needed | Rough complexity | Reference |
|---|---|---|---|---|---|
| **Tenor-curve overlay** | When looking at 10Y, see 5Y/30Y context lines simultaneously | Analytics timeseries by tape_label | Multi-bucket fetch in single view | M | `useAnalyticsTimeseries.ts` |
| **Spread-to-fly / spread-to-curve overlays** | Package-level relative value context | Package types in `package_type` column | Aggregation across matching package pairs | M | `analytics.ts:194-218` |
| **Volatility cone** | Is the bucket close rate's realized vol high or low vs history? | Daily close series | Client-side rolling stddev at 1W/1M/3M/1Y horizons | M | N/A |
| **Block / non-block volume split** | Block trades represent institutional positioning | `is_block_any` on packages table | `FILTER (WHERE is_block_any)` in daily agg | S | `cell/route.logic.ts:349` |
| **Intraday auction-window flagging** | NY 8:30, 10:00, 14:00 data releases drive volume spikes | Timestamps already ET-converted | Visual reference lines on intraday chart | S | `TimeseriesTab.tsx:656` |
| **Same-trade re-rate detection** | MODI events that change the fixed_rate on a UTI | `lc_was_amended`, `lc_has_economics_change` | New query against lifecycle columns | M | `CLAUDE.md:37-38` |

---

## 6. Regression Matrix

**Status: NOT TESTED.** Chrome MCP was unavailable this session. The matrix below represents the **test plan** a build session should execute before landing any changes. Each cell would be populated with `OK | DEGRADED | BROKEN` after live validation.

| Route | Surface | Status | Note |
|---|---|---|---|
| `/usd-swaps` | Volume Grid — expand/collapse | NOT TESTED | |
| `/usd-swaps` | Volume Grid — every Window button (8) | NOT TESTED | |
| `/usd-swaps` | Volume Grid — every Baseline button (8) | NOT TESTED | |
| `/usd-swaps` | Volume Grid — Activity/Grid color mode | NOT TESTED | |
| `/usd-swaps` | Volume Grid — Volume/IDB-CUSTY view | NOT TESTED | |
| `/usd-swaps` | Volume Grid — every Package type (9) | NOT TESTED | |
| `/usd-swaps` | Volume Grid — Forward: Default/Legacy/IMM16/FOMC | NOT TESTED | |
| `/usd-swaps` | Volume Grid — Tenor: Default/Legacy/Venue | NOT TESTED | |
| `/usd-swaps` | Volume Grid — Refresh button | NOT TESTED | |
| `/usd-swaps` | Volume Grid — cell click → modal → data + charts | NOT TESTED | |
| `/usd-swaps` | Volume Grid — modal close → tape filter applied | NOT TESTED | |
| `/usd-swaps` | Tape table — column filters, sort, checkbox, expansion | NOT TESTED | |
| `/usd-swaps` | Tape table — Show/Hide Analytics | NOT TESTED | |
| `/usd-swaps` | Analytics Dock — Timeseries (all Series/Metric/View/Range combos) | NOT TESTED | |
| `/usd-swaps` | Analytics Dock — Trade Rarity | NOT TESTED | |
| `/usd-swaps` | Analytics Dock — Traded Levels | NOT TESTED | |
| `/usd-swaps` | Analytics Dock — Sequence (2+ rows) | NOT TESTED | |
| `/usd-swaps` | Analytics Dock — hover prefetch | NOT TESTED | |
| `/usd-swaps` | Keyboard: ↑↓ row nav, Esc close | NOT TESTED | |
| `/usd-rates-vol-analytics/*` | Plotly modules load, no console errors | NOT TESTED | |
| `/usts-rv` | UST RV loads, Plotly renders | NOT TESTED | |
| `/curve-explorer` | Route loads or 404 | NOT TESTED | |
| `/timeseries-explorer` | Route loads or 404 | NOT TESTED | |
| `/` | Home nav clean | NOT TESTED | |

---

## 7. Implementation Plan

### Phase 0 — Verifications (no code changes)

**Step 0.1: Confirm SWR hydration race hypothesis**
- **Goal:** Validate whether the volume grid SWR bypass is caused by the async IndexedDB hydration race or a genuine URL-key incompatibility.
- **Files affected:** None (read-only investigation)
- **Test surface:** Chrome DevTools: (1) add `console.log` in IndexedDBCacheProvider `set()` with key type, (2) load `/usd-swaps`, (3) observe whether URL-string keys appear in the IDB store after hydration completes.
- **Risks:** None
- **Rollback:** N/A
- **Dependency:** None
- **Estimated effort:** S — one dev session with chrome DevTools
- **Addresses:** Finding 3 from Section 2.3

**Step 0.2: Quantify UFRO population**
- **Goal:** Count UFRO trades with non-zero rates to size the bucket contamination risk.
- **Files affected:** None (SQL query only)
- **Test surface:** `SELECT tape_label, COUNT(*), AVG(weighted_fixed_rate) FROM arbs_usd_swap_tape_packages_v2 WHERE tape_label ILIKE '%UFRO%' AND weighted_fixed_rate <> 0 GROUP BY tape_label ORDER BY COUNT(*) DESC LIMIT 50`
- **Risks:** None
- **Rollback:** N/A
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Finding 7 from Section 4.2

**Step 0.3: Profile volume grid SQL with EXPLAIN ANALYZE**
- **Goal:** Confirm whether the missing composite index is the dominant cost factor.
- **Files affected:** None
- **Test surface:** Run `EXPLAIN (ANALYZE, BUFFERS) <volume-grid SQL>` with representative params.
- **Risks:** None
- **Rollback:** N/A
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Finding 1 from Section 2.1

**Step 0.4: Run full chrome MCP regression sweep**
- **Goal:** Populate the regression matrix in Section 6 with actual OK/DEGRADED/BROKEN status.
- **Files affected:** None
- **Test surface:** Every cell in the Section 6 table.
- **Risks:** None
- **Rollback:** N/A
- **Dependency:** Chrome MCP availability
- **Estimated effort:** M — 1-2 hours of systematic clicking + network capture

### Phase 1 — Quick Wins

**Step 1.1: Add composite index on legs table**
- **Goal:** Speed up volume grid + analytics queries that filter on `contributes_to_flow = TRUE` with a timestamp range.
- **Files affected:** `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` (add index definition)
- **Change shape:** Add `CREATE INDEX IF NOT EXISTS idx_tape_v2_legs_flow_ts ON arbs_usd_swap_tape_legs_v2(contributes_to_flow, original_execution_timestamp DESC NULLS LAST) WHERE contributes_to_flow = TRUE`
- **Test surface:** `EXPLAIN ANALYZE` before/after; volume-grid API timing comparison
- **Risks:** Index creation on large table takes time; use `CONCURRENTLY`
- **Rollback:** `DROP INDEX idx_tape_v2_legs_flow_ts`
- **Dependency:** Step 0.3 confirms index is needed
- **Estimated effort:** S
- **Addresses:** Finding 1

**Step 1.2: Add `React.memo` to VolumeGridCell**
- **Goal:** Prevent 128+ cell re-renders on toggle changes that don't affect individual cell data.
- **Files affected:** `VolumeGridCell.tsx`
- **Change shape:** Wrap export in `React.memo` with shallow-compare of `cell`, `metric`, `period`, `viewMode`, `colorMode`, `colorPercentile`
- **Test surface:** Existing `VolumeGridCell.test.tsx`, `VolumeGrid.test.tsx`; React DevTools Profiler before/after
- **Risks:** Stale renders if comparator misses a prop. Low risk — props are primitive or stable objects.
- **Rollback:** Remove `React.memo` wrapper
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Finding 8

**Step 1.3: Pause volume grid polling when tab is backgrounded**
- **Goal:** Stop 30s interval fires when the trader has tabbed away.
- **Files affected:** `useVolumeGrid.ts`
- **Change shape:** Add `document.addEventListener('visibilitychange', ...)` that clears/restarts the interval based on `document.hidden`.
- **Test surface:** Existing `useVolumeGrid.test.ts`; add test for visibility state transitions
- **Risks:** None — resume-on-focus fires an immediate fetch to catch up
- **Rollback:** Remove visibility listener
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Finding 10

**Step 1.4: Add hover-prefetch for volume grid cell modal**
- **Goal:** Pre-warm the cell modal's SWR cache on cell hover so click renders instantly.
- **Files affected:** `VolumeGridCell.tsx` (add onMouseEnter/onMouseLeave), new hook `useVolumeGridCellPrefetch.ts`
- **Change shape:** Debounced (200ms) prefetch fires `mutate(cellKey, fetchFn, { revalidate: false })` on cell hover. Pattern mirrors `useAnalyticsPrefetch.ts`.
- **Test surface:** New unit test for the prefetch hook; chrome MCP verification
- **Risks:** Overfetch if trader sweeps mouse across many cells. Mitigated by debounce + `fireIfMissing` check.
- **Rollback:** Remove `onMouseEnter`/`onMouseLeave` from cell
- **Dependency:** None
- **Estimated effort:** M
- **Addresses:** Finding 2

### Phase 2 — Structural

**Step 2.1: Unify volume grid onto SWR (fix hydration race)** *(blocked on Step 0.1)*
- **Goal:** Remove the SWR bypass in `useVolumeGrid.ts` and use the standard SWR hook path.
- **Files affected:** `useVolumeGrid.ts`, `SwrProvider.tsx`
- **Change shape:**
  - In `SwrProvider.tsx`: before rendering children with the real provider, copy any entries from the transient fallback map into the new provider.
  - In `useVolumeGrid.ts`: replace `useState`/`setInterval` with `useSWR` using an array key (`['volume-grid', metric, period, ...]`) + `refreshInterval: 30_000`.
- **Test surface:** `useVolumeGrid.test.ts` (update from manual-fetch to SWR mock); chrome MCP cold/warm cache comparison
- **Risks:** If the root cause is different from the hydration race (Step 0.1), this fix doesn't help. Step 0.1 must confirm first.
- **Rollback:** Revert to the current useState/setInterval implementation
- **Dependency:** Step 0.1
- **Estimated effort:** M
- **Addresses:** Finding 3

**Step 2.2: Move intraday LOCF server-side** *(optional, operator decision)*
- **Goal:** Eliminate client-side minute-grid interpolation by returning pre-interpolated points from the server.
- **Files affected:** `analytics-timeseries/route.ts` (intraday SQL), `TimeseriesTab.helpers.ts` (remove `interpolateIntradayMinutely`), `TimeseriesTab.tsx` (remove conditional LOCF call)
- **Change shape:** Server SQL: `generate_series(first_ts, last_ts, '1 minute') AS minutes LEFT JOIN LATERAL (SELECT fixed_rate FROM ticks WHERE ts <= minutes.t ORDER BY ts DESC LIMIT 1)`. Return pre-filled minute grid.
- **Test surface:** `route.logic.test.ts`, `TimeseriesTab.helpers.test.ts`; compare visual output before/after
- **Risks:** Increases server response payload (~4320 points instead of ~500 raw ticks). May slow the SQL query. Profile first.
- **Rollback:** Re-enable client-side LOCF
- **Dependency:** None
- **Estimated effort:** M
- **Addresses:** Finding 5

### Phase 3 — New Analytics

**Step 3.1: Day-of-week seasonality in volume grid**
- **Goal:** Add DOW context to the cell tooltip or as an optional grid overlay.
- **Files affected:** `route.logic.ts` (add DOW to CTE), `VolumeGridCell.tsx` (tooltip), types
- **Change shape:** Add `EXTRACT(DOW FROM day_et)` to the prior_per_day CTE; aggregate per-DOW averages; return in cell payload.
- **Test surface:** `route.logic.test.ts`; snapshot test for tooltip text
- **Risks:** Payload grows by ~7 numbers per cell. Minimal.
- **Rollback:** Remove DOW fields from response
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Section 5.1

**Step 3.2: Lifecycle composition (NEW vs UNWIND) in volume grid**
- **Goal:** Show what fraction of the cell's volume is genuine new flow vs unwind churn.
- **Files affected:** `route.logic.ts` (add `economic_class` FILTER to current_agg), types, `VolumeGridCell.tsx` (tooltip or sub-bar)
- **Change shape:** Add `SUM(...) FILTER (WHERE economic_class = 'ECONOMIC_UNWIND')` alongside the existing `SUM(...)`.
- **Test surface:** `route.logic.test.ts`
- **Risks:** Requires JOIN to legs table to access `economic_class` — already in the CTE. Low risk.
- **Rollback:** Remove FILTER column
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Section 5.1

**Step 3.3: Block / non-block volume split in analytics dock**
- **Goal:** Let the trader see how much of the bucket's daily volume came from block trades.
- **Files affected:** `analytics-timeseries/route.ts` (add `is_block_any` FILTER), types, `TimeseriesTab.tsx` (optional series toggle)
- **Change shape:** Add `COUNT(*) FILTER (WHERE is_block_any)` and corresponding DV01/notional FILTERs to the daily aggregate.
- **Test surface:** `route.logic.test.ts`, `route.orthogonal.test.ts`
- **Risks:** Another field in the orthogonal-payload split. Keep it additive.
- **Rollback:** Remove FILTER columns
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Section 5.2

**Step 3.4: Intraday reference lines for macro windows**
- **Goal:** Draw vertical reference lines at 8:30, 10:00, 14:00 ET on the intraday chart.
- **Files affected:** `DockTimeseriesChart.tsx` (Plotly shapes), `TimeseriesTab.tsx` (Recharts ReferenceLines)
- **Change shape:** Add 3 fixed-time vertical shapes/lines. Gate behind a toggle or show always.
- **Test surface:** Visual inspection; snapshot test
- **Risks:** None — purely additive visual
- **Rollback:** Remove shapes/lines
- **Dependency:** None
- **Estimated effort:** S
- **Addresses:** Section 5.2

### Phase 4 — Cleanup

**Step 4.1: Deduplicate daily SQL `mapDailyRowsToPoints`**
- **Goal:** The `produceOutrightPackageTimeseries` and `produceAnalyticsTimeseries` functions both contain identical `mapDailyRowsToPoints` logic. Extract to shared helper.
- **Files affected:** `analytics-timeseries/route.ts`
- **Change shape:** The function `mapDailyRowsToPoints` already exists at line 118 but the fallback path at line 629 has an inline copy. Route both paths through the shared function.
- **Test surface:** Existing `route.logic.test.ts`, `route.orthogonal.test.ts`
- **Risks:** Low — pure refactor
- **Rollback:** Revert inline
- **Dependency:** None
- **Estimated effort:** S

**Step 4.2: Consolidate localStorage persistence in VolumeGridCard**
- **Goal:** The card has 10 separate `useEffect` hooks for persisting each state field to localStorage. Consolidate into one `useEffect` with a serialized state object.
- **Files affected:** `VolumeGridCard.tsx`
- **Change shape:** Replace 10 `useEffect`s with one that serializes `{ collapsed, metric, period, lookback, ... }` to a single localStorage key.
- **Test surface:** `VolumeGridCard.test.tsx`
- **Risks:** Migration: old per-key entries would be orphaned. Add a one-time migration read.
- **Rollback:** Revert to per-key effects
- **Dependency:** None
- **Estimated effort:** S

---

## 8. Open Questions for the Operator

1. **UFRO filtering strategy.** Should UFRO trades be (a) excluded from the bucket baseline, (b) split into a separate toggle-able series, (c) preserved as-is with a badge, or (d) hybrid: collapse prefix + conditional filter? See Section 4.3 for trade-offs.

2. **SWR unification priority.** The SWR bypass in `useVolumeGrid.ts` works. Is unifying it onto SWR worth the risk (Step 2.1), or should we accept the current implementation?

3. **Server-side LOCF.** Moving intraday LOCF to the server (Step 2.2) increases response payload but removes client computation. The current client cost is sub-millisecond. Is this worth doing?

4. **Toggle-bar density.** Should we move some volume grid controls into popovers (Step Phase 4), or do traders prefer the current one-click-access layout?

5. **Baseline floor transparency.** When Baseline=`1w` is selected but the effective lookback is 28 days (4× floor), should the UI surface this? Options: (a) show effective lookback in tagline, (b) disable Baseline options shorter than Window×4, (c) leave as-is.

6. **MAX_SEQUENCE cap.** The current cap is 20. Have traders ever hit it? Should it be reduced to 10 (halving the hook overhead) or is 20 the right ceiling?

7. **Color ramp accessibility.** Should we add a CVD-safe (colorblind) mode toggle, or is the current blue-gray-red ramp sufficient for the user base?

8. **Plotly vs Recharts consolidation.** Is the visual inconsistency between the two charting libraries (hover behavior, axis styling) worth the effort to unify? Or is the current split acceptable?

---

## 9. Out-of-Scope Notes

1. **Database credentials in source.** `SDRUtils/dashboard/src/lib/db.ts:15-17` contains a hardcoded Supabase pooler password as a fallback default. This should be removed or rotated — it's a secret committed to source.

2. **`DAILY_ROW_CAP = 2000` / `INTRADAY_TICK_CAP = 5000`.** These caps are reasonable but not surfaced to the client. If a bucket has >2000 trading days of history, the oldest days are silently dropped. Consider returning a `truncated: true` flag.

3. **Test coverage gaps.** The volume grid route handler tests (`route.test.ts`, `route.logic.test.ts`) exist but no integration test runs against a real database. The analytics-timeseries has an `integration.test.ts` but it's unclear if CI runs it.

4. **`CardsDrawer` (PR #286).** The always-on cards drawer renders below the dock in both single and sequence modes. No investigation was done on its content or performance since it was out of scope for this recon.

5. **`VolumeGridCard` defaults version.** `DEFAULTS_VERSION = 'open-dv01-1w-v1'` — there's a one-time default migration that sets metric=DV01 and period=1w on first visit after the version bump. If another default change is needed, bump this constant.

6. **`produceOutrightPackageTimeseries` fast path.** This optimization queries the packages table directly (skipping the full legs JOIN) when the tape_label matches an outright pattern. Falls back to the generic path if 0 rows. This is a significant perf optimization but adds code duplication — the full daily SQL in the generic path does the same aggregation with additional CTEs.
