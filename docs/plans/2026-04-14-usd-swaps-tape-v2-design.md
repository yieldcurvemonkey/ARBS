# USD Swap Tape v2 — Dashboard Replacement Design

**Status:** Approved for implementation planning.
**Scope:** Replace the existing USD swap SDR trade tape page with a production-grade, lifecycle-complete tape powered by `SDRUtils.analytics.trade_tape.TradeTape`. Mirror the UX style of the existing swaption trade tape at `/usd-rates-vol-analytics/vol-tape`, but surface the richer swap enrichment and full trade lifecycle.

## 1. Goals

- Every trade in the CFTC SDR USD-swap stream is visible — NEWT, UNWIND, COMPRESSION, TERMINATION, NOVATION, RESET_OPTIMIZATION, CORRECTION, CLEARING_TERMINATION, EXERCISE_BORN.
- Lifecycle, quality, package structure, classification, FOMC context, and temporal clustering surface as first-class UI affordances, not buried in JSON.
- `tape_label` (professional ANNA DSB-derived label, e.g. `USD-SOFR-COMPOUND 1D Constant Spot 10Y Outright PHYS`) is the hero identifier — table column, group-by key, chart title, filter value.
- `risk` (correct DV01 from TradeTape) replaces the legacy `dv01` column everywhere.
- Package trades read as one economic unit; a 2Y/5Y curve is one row with two-leg expansion.
- Feel matches a Bloomberg trade blotter: dark, monospace numbers, dense but scannable, color-coded lifecycle.
- Manual linking / merge / comments / tags continue to work; no user state loss at cutover.

## 2. Non-Goals

- No refactor of the swaption tape monolith.
- No real-time (sub-poll-cycle) latency. Polling at 30s matches existing UX.
- No investment advice, no derived prescriptive alerts.
- No new authentication or sharing model beyond what the dashboard already provides.

## 3. Architecture Overview

Data flow:

```
CFTC SDR raw files
       ↓
Classification pipeline (existing)  ←  load_usd_swaps()
       ↓
ingest_usdswaps.py (existing)       →  arbs_usd_swap_packages_v2
                                       arbs_usd_swap_legs_v2
       ↓
ingest_usdswaps_tape.py (NEW)       →  arbs_usd_swap_tape_packages_v1
  wraps TradeTape.compute()            arbs_usd_swap_tape_legs_v1
                                       arbs_usd_swap_tape_display_v1 (view)
       ↓
/api/usd-swaps-tape-v2/* (NEW)       →  cursor-paginated JSON with legs_json
       ↓
features/usd-swaps-tape-v2/ (NEW)    →  React UI at /usd-swaps
```

Key decisions:

- **Separate ingest + new tape tables** (not extending existing ingest columns). Keeps TradeTape enrichment versioning independent; legacy pipeline untouched.
- **Package-first rows with leg expansion** — matches current swap-tape and swaption-tape UX; legs carry per-trade enrichment in `legs_json`.
- **Full lifecycle displayed by default.** Clean-tape filtering is opt-in; the default view shows every trade type the SDR reports.
- **URL is source of truth for filter/flag/sidecar state.** Bookmarkable, shareable views. No client-side state store.
- **Manual-link infrastructure preserved.** The existing `arbs_usd_swap_manual_links_v2` + history tables are LEFT JOINed by the new ingest and the new API. Merge / unmerge / comment / tag endpoints under `/api/usd-swaps-tape-v2/*` re-export the existing handlers.

Frontend approach: fresh feature directory `features/usd-swaps-tape-v2/`, swaption-style layout, copy-and-adapt sub-components. Swaption monolith untouched. Shared-abstraction refactor deferred.

## 4. Backend Pipeline & Schema

### 4.1 Ingest script — `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py`

- Runs after `ingest_usdswaps.py` (chained in the deploy trigger; invocation detail decided at implementation).
- Reads the same-day classified DataFrame via `load_usd_swaps()` plus the optional raw cross-day frame.
- Constructs `TradeTape(df, raw_df=raw_df).compute(use_cache=True)` to get the ~60-column enriched frame.
- Computes `package_summary()` for per-package aggregates; joins into the packages table.
- Upserts rows into the two new tables; materializes the display view.
- No filtering at ingest time — **every classified trade is persisted**, including terminations, unwinds, compressions, novations, resets, clearing terminations, corrections, exercises.
- `TradeTape.compute(use_cache=True)` reuses the pickle cache for idempotent same-day re-ingests.
- Observability via `arbs_usd_swap_tape_ingestion_runs_v1` (fields: `run_id`, `started_at`, `ended_at`, `rows_in`, `rows_out`, `failed_rows` JSONB, `status`, `error_text`, `cache_hit`).

### 4.2 Table — `arbs_usd_swap_tape_legs_v1`

Per-trade (leg-level), primary key `trade_id`, FK `package_id` → `arbs_usd_swap_tape_packages_v1`. Columns grouped:

- **Identifiers:** `trade_id`, `package_id`, `as_of_date`.
- **Timing:** `execution_timestamp`, `execution_session`, `execution_hour_et`, `effective_date`, `expiration_date`.
- **Duration:** `tenor_years`, `tenor_label`, `tenor_display` (`~7Y` for off-date), `forward_start_years`, `forward_label`, `forward_bucket`.
- **Economics:** `notional`, `notional_currency`, `risk` (correct DV01), `fixed_rate`.
- **Classification:** `trade_type` (OUTRIGHT/CURVE/FLY/SPREADOVER/MATCHED_MATURITY/MAC/IMM/FOMC), `rate_index_clean` (SOFR/FED_FUNDS/OTHER), `venue` (D2D/D2C), `ccp` (LCH/CME), `platform_identifier`.
- **Tape label:** `tape_label`, `upi_reset_freq`, `upi_notional_schedule`, `upi_delivery_type`.
- **Lifecycle flags:** `is_new_risk`, `is_unwind`, `is_compression`, `is_compression_spec`, `is_reset_optimization`, `is_novation`, `is_novation_born`, `is_novation_terminated`, `is_exercise_born`, `is_clearing_termination`, `lifecycle_type`, `lc_n_events`, `lc_status`.
- **Quality flags:** `is_ufro`, `is_off_market`, `is_capped`, `is_block`, `is_off_date`, `is_mac`, `is_spreadover`, `is_asset_swap`, `is_non_standard_term`, `quality_flags TEXT[]`.
- **FOMC / calendar:** `is_fomc_dated`, `fomc_meeting_label`, `fomc_proximity`, `is_month_end`, `is_quarter_end`.
- **Clustering:** `cluster_id`, `cluster_size`, `is_multi_meeting_cluster`.
- **Cross-day lifecycle (nullable):** `xd_status`, `xd_n_events`, `xd_notional_pct_remaining`, `xd_is_terminated`, `xd_has_partial_unwind`.
- **Manual link:** `manual_link_id UUID REFERENCES arbs_usd_swap_manual_links_v2(link_id)`.
- **Spill:** `enrichment_metrics JSONB` for any column not hoisted above; future-proofs without schema migrations.

Indexes: `(package_id)`, `(execution_timestamp)`, `(lifecycle_type)`, `(cluster_id)`, GIN on `enrichment_metrics`, GIN on `quality_flags`.

### 4.3 Table — `arbs_usd_swap_tape_packages_v1`

Per-package aggregate, primary key `package_id`. Columns:

- **Identifiers:** `package_id`, `manual_link_id`, `as_of_date`.
- **Timing:** `execution_start`, `execution_end`.
- **Structure:** `package_structure` (`2Y/5Y/10Y Curve`), `package_type`, `package_tenors`, `n_package_legs`, `legs_count`.
- **Aggregates:** `total_notional`, `gross_notional`, `total_risk`, `gross_risk`, `weighted_fixed_rate`, `min_fixed_rate`, `max_fixed_rate`, `has_spread`, `package_transaction_spread`.
- **Rolled-up classification:** `rate_index_clean`, `venue`, `ccp`, `execution_session`.
- **Rolled-up lifecycle flags (any-leg OR):** `is_new_risk`, `is_unwind`, `is_compression_any`, `is_ufro_any`, `is_block_any`, `is_capped_any`, `is_off_date_any`, `is_termination_any`, `is_novation_any`, `is_reset_optimization_any`, `is_clearing_termination_any`, `is_correction_any`.
- **Lifecycle mix:** `lifecycle_mix JSONB` — `{ new_risk, unwind, compression, termination, novation, reset_opt, correction, clearing_term, exercise_born }` leg counts for quick rendering.
- **FOMC / cluster:** `is_fomc_dated`, `fomc_meeting_label`, `cluster_id`, `cluster_size`.
- **Representative tape label:** `tape_label` — most-descriptive leg label or package-level composite.
- **Spill:** `package_metrics JSONB`.

Indexes: `(as_of_date, execution_start DESC)`, `(package_type, as_of_date)`, `(cluster_id)`, `(fomc_meeting_label)`, GIN on `package_metrics`.

### 4.4 Display view — `arbs_usd_swap_tape_display_v1`

Mirrors `arbs_usd_swap_display_items_v4` pattern:

```sql
CREATE OR REPLACE VIEW arbs_usd_swap_tape_display_v1 AS
SELECT
  p.*,
  l.legs_json,
  ml.manual_package_id,
  ml.user_comment,
  ml.link_reason,
  ml.tags,
  ml.link_metrics,
  ml.created_by AS link_created_by,
  ml.created_at AS link_created_at
FROM arbs_usd_swap_tape_packages_v1 p
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(/* every column on tape_legs */)
        ORDER BY leg_order
    ) AS legs_json
    FROM arbs_usd_swap_tape_legs_v1 l
    WHERE l.package_id = p.package_id
) l ON TRUE
LEFT JOIN arbs_usd_swap_manual_links_v2 ml ON ml.link_id = p.manual_link_id;
```

Cursor paginatable on `p.execution_start DESC`.

## 5. API Layer

New API tree: `SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/`.

### 5.1 `GET /api/usd-swaps-tape-v2` — main tape endpoint

Query params (contract-compatible with the existing `sofr-swaps-tape` route, extended):

| Param | Type | Default | Purpose |
|---|---|---|---|
| `cursor` | ISO ts | — | Paginate older. Mutually exclusive with `since`. |
| `since` | ISO ts | — | Poll for newer. |
| `limit` | int | 200 | Max 500. |
| `filter` | string | — | Global ILIKE across `tape_label`, `package_structure`, `package_tenors`, `trade_id`. |
| `columnFilters` | JSON | `{}` | PrimeReact `DataTableFilterMeta`. |
| `columnFilterOp` | `and`/`or` | `and` | Combining operator. |
| `clean` | bool | **`false`** | When `true`, excludes UNWIND / COMPRESSION / UFRO / RESET_OPTIMIZATION / NOVATION_TERMINATED / CLEARING_TERMINATION rows. |
| `lifecycle` | CSV | all | Explicit lifecycle whitelist; every value checked by default. |
| `tradeTypes` | CSV | all | `OUTRIGHT,CURVE,FLY,SPREADOVER,MATCHED_MATURITY,MAC,IMM,FOMC`. |
| `venues` | CSV | all | `D2D,D2C`. |
| `ccps` | CSV | all | `LCH,CME`. |
| `sessions` | CSV | all | `Asia,London,NY_AM,NY_PM,Late`. |
| `rateIndex` | CSV | all | `SOFR,FED_FUNDS,OTHER`. |
| `tenors` | CSV | all | `2Y,5Y,10Y,...`. |
| `fomcMeeting` | string | — | e.g. `APR26`. |

Column-filter fields extend the existing set with: `trade_type`, `venue`, `ccp`, `session`, `rate_index`, `tape_label`, `fomc_meeting`, `lifecycle`.

Response (extends `SofrSwapTapeRow`):

```ts
type UsdSwapTapeRow = SofrSwapTapeRow & {
  package_structure, trade_type, venue, ccp, rate_index_clean,
  execution_session, tape_label, fomc_meeting_label: string | null;
  is_fomc_dated, is_unwind, is_block_any, is_capped_any,
  is_off_date_any, is_compression_any, is_ufro_any,
  is_termination_any, is_novation_any, is_reset_optimization_any,
  is_clearing_termination_any, is_correction_any: boolean | null;
  cluster_id: string | null;
  cluster_size: number | null;
  lifecycle_mix: Record<string, number> | null;
  legs_json: UsdSwapTapeLeg[];
};

type UsdSwapTapeLeg = SofrSwapTapeLeg & {
  tape_label, trade_type, tenor_display, venue, ccp, rate_index_clean,
  execution_session, lifecycle_type, fomc_meeting_label,
  fomc_proximity, cluster_id: string | null;
  is_new_risk, is_unwind, is_compression, is_reset_optimization,
  is_ufro, is_off_market, is_capped, is_block, is_off_date,
  is_novation_born, is_novation_terminated, is_exercise_born,
  is_clearing_termination, is_non_standard_term: boolean | null;
  xd_is_terminated, xd_has_partial_unwind: boolean | null;
  xd_notional_pct_remaining: number | null;
  quality_flags: string[] | null;
};
```

### 5.2 Sidecar endpoints

| Route | Purpose | Key query params | Response |
|---|---|---|---|
| `GET /risk-concentration` | Grouped DV01 aggregation | `groupBy`, `clean`, `lifecycle`, other filters | `{ groups: [{ value, trade_count, total_dv01, total_notional }] }` |
| `GET /packages` | Package-summary list | `date`, `limit`, `sortBy`, filters | `{ packages: [{ package_id, package_structure, trade_type, n_legs, total_risk, total_notional, rate_index, tape_label, execution_start }] }` |
| `GET /fomc-clusters` | FOMC meeting roll-ups | `date` | `{ meetings: [{ fomc_meeting_label, meeting_date, trade_count, net_risk, gross_notional, has_multi_meeting_flow }] }` |
| `GET /clusters` | Temporal cluster timeline | `date` | `{ clusters: [{ cluster_id, start_ts, end_ts, trade_count, total_risk, tape_labels[] }] }` |
| `GET /flow-history` | Port of existing quadrant grid | same as current | same as current |
| `GET /timeseries` | Port + `groupBy=tape_label` extension | `groupBy`, `value`, `metric`, `view`, `range` | same shape as current |

### 5.3 Manual-link endpoints

`POST /merge`, `POST /unmerge`, `POST /comment`, `POST /tags` re-export existing `sofr-swaps-tape` handlers. Operate on shared `arbs_usd_swap_manual_links_v2` table — existing links and history remain intact.

### 5.4 Supporting lib

`src/lib/usd-swaps-tape-v2.ts` — mirrors `usd-swaps-tape.ts`, exports `resolveDisplayView()` returning the `arbs_usd_swap_tape_display_v1` view + column list (and a graceful fallback in case the view doesn't exist yet during rollout).

## 6. Frontend Feature Directory

```
features/usd-swaps-tape-v2/
  index.ts
  constants.ts
  types/
    index.ts
    trade.types.ts          # UsdSwapTapeRow, UsdSwapTapeLeg
    filter.types.ts         # ColumnFilterMeta, FlagChip, TradeTypeFilter, LifecycleChip
    chart.types.ts          # TimeseriesPoint, TimeseriesMetricKey, OHLC
    link.types.ts           # ManualLink (shared with existing)
    sidecar.types.ts        # RiskConcentrationGroup, PackageSummary, FomcMeeting, Cluster
  hooks/
    index.ts
    useTradeTapeData.ts     # cursor + polling + upsert
    useColumnFilters.ts     # URL-synced PrimeReact filter state
    useRowExpansion.ts      # expandedRows keyed by package_id
    useRowSelection.ts
    useSavedUser.ts
    useManualLinks.ts
    useTimeseriesData.ts
    useRiskConcentration.ts
    usePackageBrowser.ts
    useFomcClusters.ts
    useTemporalClusters.ts
    useFlagFilters.ts       # lifecycle + flag chip state synced to URL
  components/
    UsdSwapsTradeTape.tsx                      # main orchestrator, ≤900 lines target
    TradeTapeHeader/
      TradeTapeHeader.tsx
      FlagChips.tsx
      CleanTapeToggle.tsx
    TradeTapeFilters/
      TradeTapeFilters.tsx
      FilterChips.tsx
    TradeTapeTable/
      TradeTapeTable.tsx                       # PrimeReact DataTable
      columns.tsx                              # body templates
      LegsSubTable.tsx                         # per-leg expansion
      RowBadges.tsx                            # flag + FOMC + off-date badges
      TapeLabelCell.tsx                        # hero cell
    TradeTapeCharts/
      TimeseriesChart.tsx
      FlowHistoryGrid.tsx
    Sidecars/
      RiskConcentration/RiskConcentrationPanel.tsx
      PackageBrowser/PackageBrowserPanel.tsx
      FomcClusters/FomcClustersPanel.tsx
      TemporalClusterTimeline/ClusterTimelineStrip.tsx
    ManualLinksDialog/ManualLinksDialog.tsx
    UsdSwapsMethodologyModal.tsx
```

Page cutover: `src/app/usd-swaps/page.tsx` eventually imports from `features/usd-swaps-tape-v2` in place of the current re-export chain.

Main container target size ≤900 lines; swaption tape's 14k-line monolith is the anti-pattern.

URL state is the only source of truth for filter / flag / sidecar selection. No Redux / Zustand. Hooks read from and write to `searchParams`.

## 7. Main Table & Lifecycle UX

### 7.1 Columns (package row)

| # | Column | Source | Width |
|---|---|---|---:|
| 1 | Select | — | 40 |
| 2 | Expand | — | 36 |
| 3 | Time | `execution_start` | 92 |
| 4 | **Lifecycle** | roll-up + `lifecycle_mix` | 90 |
| 5 | **Tape Label** | `tape_label` | 420 |
| 6 | Type | `trade_type` | 110 |
| 7 | Structure | `package_structure` | 150 |
| 8 | Tenor | `tenor_display` | 72 |
| 9 | DV01 | `total_risk` | 96 |
| 10 | Notional | `total_notional` | 110 |
| 11 | Rate | `weighted_fixed_rate` | 84 |
| 12 | Venue | `venue` | 72 |
| 13 | CCP | `ccp` | 64 |
| 14 | Session | `execution_session` | 76 |
| 15 | Flags | quality flags | 140 |
| 16 | Actions | — | 56 |

Resizable / reorderable / show-hide via PrimeReact column chooser; state persists to `localStorage` per user.

### 7.2 Row treatment by lifecycle

| Lifecycle | Row class | Notes |
|---|---|---|
| NEW_RISK (NEWT) | default + `hover:bg-slate-800/40` | baseline |
| UNWIND | `bg-red-950/25 text-red-100`; explicit `−` sign on DV01 | |
| COMPRESSION | `bg-zinc-900/40 text-zinc-400 italic` | |
| TERMINATION (non-compression) | `bg-rose-950/30 text-rose-100` | |
| NOVATION_BORN | `bg-purple-950/25 text-purple-100` + `⇢` prefix | |
| NOVATION_TERMINATED | `bg-purple-950/25` + `⇠` prefix + line-through on tape_label | Hover highlights partner via `novation_match_id` |
| RESET_OPTIMIZATION | `bg-neutral-900/40 text-neutral-500 text-xs` | |
| CLEARING_TERMINATION | `bg-red-950/40 border-l-2 border-red-500` | |
| CORRECTION | default; `CORR` pill replaces `NEW` pill | |
| EXERCISE_BORN | `bg-amber-950/25 text-amber-100` + `⚡` prefix | |

Row height stays at `ROW_ESTIMATE_PX = 44`. Treatment is cosmetic only — virtual scroll math unchanged.

### 7.3 Tape Label hero cell (`TapeLabelCell.tsx`)

```
[index chip] [reset chip] [fwd/tenor] [structure] [meeting chip]? [block?] [off-date?] [unwind?]
 SOFR         1D           Spot 5Y     Outright    APR26           BLK       ~          UNW
```

Colors follow `rate_index_clean`. Off-date `~` glyph uses `text-yellow-300`. FOMC chip uses amber. Unwind and block are inline flag glyphs, always accompanied by text.

### 7.4 Package expansion — `LegsSubTable.tsx`

Nested PrimeReact DataTable with per-leg columns: `leg_order`, `lifecycle`, `execution_timestamp`, `trade_id`, `tape_label`, `tenor_display`, `notional`, `risk`, `fixed_rate`, `quality_flags`, `xd_status` + `xd_notional_pct_remaining` progress bar. Background `bg-slate-950/70` to differentiate from parent rows.

### 7.5 Filters

Three layers:

1. **Filter chip bar** (sticky): multi-select dropdowns for `Lifecycle`, `Trade Type`, `Venue`, `CCP`, `Session`, `Rate Index`. All values selected by default. Users uncheck to hide. Includes a single-button **Clean Tape** preset that unchecks UNWIND / COMPRESSION / UFRO / RESET_OPT / NOVATION_TERM / CLEARING_TERM from Lifecycle; second press restores.
2. **Column filters**: PrimeReact per-column filters on Tape Label, Time, Notional, DV01, Tenor, Rate. Serialized to URL `?columnFilters=...`.
3. **Global search**: ILIKE across tape_label / package_structure / tenors / trade_id.

All three serialize to URL via `useColumnFilters` / `useFlagFilters`. Bookmark-friendly.

### 7.6 Sort / selection / infinite scroll

Default sort: `execution_start DESC`. Header click toggles single-column sort; URL-serialized.
Multi-select via checkboxes. Selected-state toolbar reveals Merge / Comment / Tag / Export.
Virtual scroll + cursor pagination. Poll every `30s` via `since=latestExecutionStart`.

## 8. Header & Visual Language

### 8.1 Three-strip header

- **Strip 1**: title · as-of · live-dot · Refresh · Columns · Methodology.
- **Strip 2**: six clickable summary stats (Trades, New Risk, Gross DV01, Gross Notional, Packages, Clusters), each with a micro-caption. Clicking a stat filters the tape. Monospace, tabular-nums.
- **Strip 3**: lifecycle mix bar — pill row per lifecycle (`[NEW 812] [UNW 186] …`) above a stacked horizontal bar. Clicking pills toggles lifecycle chip state (shared with filter bar). Right-edge `Clean Tape` toggle.

### 8.2 Design tokens

Dark theme: `bg-slate-950` (page), `bg-slate-900` (cards), `bg-slate-950/70` (nested tables), `hover:bg-slate-800/40` (rows). Text primary `text-slate-100`, secondary `text-slate-400`. Monospace `ui-monospace, JetBrains Mono, Menlo, ...` for every number.

### 8.3 Unified lifecycle palette

Single token dictionary used across table row treatment, lifecycle pills, stacked bar, sidecar charts, and summary. Red = unwind, green = new risk, zinc = compression, purple = novation, amber = FOMC / exercise, rose = termination, neutral = reset-opt, sky = correction, dark-red = clearing-term.

### 8.4 Chip tiers

1. **Hard pills** — filled bg, uppercase (lifecycle, trade_type, flags).
2. **Soft chips** — muted bg, ring (venue, ccp, session).
3. **Inline indicators** — text-only glyphs inside Tape Label cell.

### 8.5 Iconography, responsive, a11y

Lucide-react only. Responsive column collapse below 1024px. Keyboard shortcuts `/` (global search), `c` (Clean Tape), `Esc`. Color-encoded state always paired with text. `aria-label` on glyphs.

## 9. Sidecars

Four new + two ported. Collapsible right-side drawer (320–420px) at ≥1280px; modal below. Active sidecar in URL `?sidecar=<name>`. One at a time. Default on load: Risk Concentration.

Cross-panel interaction contract: every sidecar can write filter state. Clicking a sidecar element updates the URL, which triggers the main table re-query.

### 9.1 Risk Concentration (`RiskConcentrationPanel.tsx`)

GroupBy selector row (tape_label / trade_type / venue / ccp / session / tenor / rate_index / fomc_meeting). Sorted horizontal bar list, divergent (positive green, negative red), max 30 rows. Click → filter.

### 9.2 Package Browser (`PackageBrowserPanel.tsx`)

Virtualized card list, sorted by `|total_risk|`. Top filter chips (Curves / Flies / Spreadovers / MAC / IMM / FOMC). Click card → filter main table by `package_id`, auto-expand, scroll into view. Manual packages get `🔗` prefix and purple tint.

### 9.3 FOMC Meeting Clusters (`FomcClustersPanel.tsx`)

Horizontal strip of meeting cards, ordered by meeting_date. Each card shows days-to-meeting, trade count, net risk, direction, `has_multi_meeting_flow` badge. Click → filter by `fomcMeeting`. Empty state when no FOMC trades today.

### 9.4 Temporal Cluster Timeline (`ClusterTimelineStrip.tsx`)

Full-width strip between header and table (not in drawer). Height ~48px. Toggleable via header button; preference in localStorage. Horizontal time axis with vertical bars per cluster — width = duration, height ∝ `log(trade_count)`, color = dominant lifecycle. Hover tooltip, click to filter by `cluster_id`, brushed range selector for time-window filter.

### 9.5 Timeseries Modal (port)

Port of `features/swaptions-tape/components/TradeTapeCharts/TimeseriesChart.tsx`. Metrics: Notional, DV01 (signed), Trade Count, Weighted Fixed Rate. Adds `Group By` (package / tape_label / trade_type / tenor). INTRADAY / DAILY_CLOSE / DAILY_OHLC tabs preserved.

### 9.6 Flow-History Quadrant Grid (port)

Port of existing `sofr-swaps-tape` flow-history + `flowHistory.utils.ts`. Opened via header button. Respects active lifecycle chip filters.

## 10. Cutover & Migration

1. **Schema + ingest** — land tables, view, ingest script. Dual-run with existing ingest; reconcile counts.
2. **API routes** — additive `/api/usd-swaps-tape-v2/*`. Curl + Jest validation.
3. **Frontend behind a new route** — publish at `/usd-swaps-v2` alongside `/usd-swaps`. Banner on old page: "Try the new tape →".
4. **Soak & trader UAT** (~1 week). See §12.
5. **Cutover** — flip `/usd-swaps/page.tsx` import to v2; redirect `/sofr-swaps` and `/usd-swaps-v2` to `/usd-swaps`.
6. **Cleanup (separate PR)** — delete `features/sofr-swaps-tape/` + `features/usd-swaps-tape/`; delete `/api/sofr-swaps-tape/` + `/api/usd-swaps-tape/`; keep underlying legacy tables (read by `load_usd_swaps()` and manual-link history).

Rollback: step 5 is a one-line import change. No destructive DB operations.

## 11. Error Handling

### 11.1 Python ingest

- `TradeTape.compute()` failure → log, write `status='error'` in runs table, exit non-zero.
- Per-row transform failure → skip row, append to `failed_rows` JSONB, proceed.
- DB unreachable → retry 3× with backoff (30s / 90s / 180s), fail loud.
- Cache corruption → already self-heals inside `TradeTape`.

### 11.2 Next.js API

- All SQL wrapped in try/catch → `NextResponse.json({ error }, { status: 500 })`.
- Invalid query-param values → `400` with explicit acceptable-value list.
- Cursor + since → `400`.
- Empty result → `200` with empty array.
- Missing display view → `500` with hint to run the new ingest.

### 11.3 Frontend

- `useTradeTapeData` surfaces three error states: `initialError` (full-panel card + Retry), `pollError` (amber live-dot, tooltip shows retry ETA), `paginationError` (bottom toast + Retry).
- Per-sidecar error boundaries — one crash doesn't poison the page.
- URL-referenced stale IDs (cluster/package/meeting) silently drop with a small toast.
- Manual-link write failures → error toast preserving selection state.
- Top-level React error boundary preserves URL on reset.

## 12. Testing & Trader UAT

### 12.1 Python (pytest)

- `test_ingest_usdswaps_tape.py` — fixture DataFrame covering every lifecycle; assert all rows written, flags correct, `is_unwind` fires on `forward_start_years < -0.02`, cross-day columns populate with `raw_df`, `manual_link_id` joins when linked.
- Golden-file test — `TradeTape.compute()` schema stability; reuse `tests/fixtures/build_tape_golden.py` if present.
- Idempotency — repeat ingest produces identical row content.

### 12.2 Jest

- `/api/usd-swaps-tape-v2/*` route tests: default `clean=false` returns all rows, `lifecycle` CSV maps to SQL, `columnFilters` → ILIKE, cursor + since → 400.
- Aggregate routes (`risk-concentration`, `packages`, `fomc-clusters`, `clusters`) — response shape + aggregation correctness.
- `useTradeTapeData.test.ts` — copy-adapt from swaption; extend for new URL params.
- `useFlagFilters.test.ts` — chip toggle → URL round-trip; Clean Tape preset flips the right set.
- `TradeTapeTable/columns.test.tsx` — snapshot per lifecycle row treatment; TapeLabelCell combinations.

### 12.3 Puppeteer E2E

- Load `/usd-swaps-v2`; wait for data; assert at least one row per lifecycle type exists.
- Toggle Clean Tape → counts drop; Lifecycle pills dim.
- Click FOMC meeting card → table filters.
- Row expansion shows legs; copy-trade-id works.
- Timeseries modal opens + metric toggle.

### 12.4 Trader UAT checklist

- [ ] All lifecycle types (NEWT / UNW / CMP / NOVA / RST / TERM / CORR / CLR / XERC) visible with correct pill + row treatment.
- [ ] `tape_label` matches trader's mental model for 5+ random trades.
- [ ] Off-date trades show `~` prefix.
- [ ] FOMC-dated trades carry meeting chip; FOMC sidecar groups them.
- [ ] Package expansion shows each leg's tape_label.
- [ ] Manual merge / unmerge / comment / tag flows still work.
- [ ] Clean Tape toggle hides exactly UNW / CMP / RST / NOVA_TERM / CLR.
- [ ] Every sidecar filter writes back to main table.
- [ ] URL restores full view on reload.
- [ ] Live-dot amber within one poll cycle of simulated outage.

## 13. Performance

- Indexes as per §4.2 / §4.3.
- Package-level pagination (200 rows default) keeps payloads 300–500 KB even with `legs_json`.
- Sidecar aggregate endpoints operate on single-day scans of `tape_packages` (low row count, <100 ms expected).
- Client: `useMemo` for timeseries data, debounced 250 ms column-filter fires, 150 ms sidecar refetch on chip change, per-hook `AbortController`.
- Ingest cold ~5 min, warm <60 s via `TradeTape` pickle cache.

## 14. Observability

- `arbs_usd_swap_tape_ingestion_runs_v1` — one row per run; dashboard Methodology modal shows last-run freshness + cache-hit.
- Structured logs on every API route (`method`, `params_digest`, `duration_ms`, `row_count`) → existing Vercel logging.
- Client `console.error` stub ready for future Sentry integration; no new dependency in v1.

## 15. Open Questions for Implementation

- Ingest chaining mechanism: `--run-tape` flag on `ingest_usdswaps.py` vs a thin orchestration wrapper. Decide during implementation; both are low-risk.
- Exact SQL for `lifecycle_mix` aggregation — can live in the ingest or in the display view. Ingest is simpler; view is always fresh.
- Cluster timeline toggle default (on / off) — leaning on, because it's glanceable and cheap; finalize after trader feedback.
- Whether to expose per-leg timeseries chart (not just per-package) — stretch goal, leave as a flag on the Timeseries modal's Group By selector.

## 16. References

- Backend enrichment: `SDRUtils/analytics/trade_tape.py`
- Existing classified input: `notebooks/sdr/_usd_swaps_common.py::load_usd_swaps`
- Existing ingest: `SDRUtils/_swappulse_scripts/ingest_usdswaps.py`
- Style reference: `SDRUtils/dashboard/src/features/swaptions-tape/` + `app/usd-rates-vol-analytics/vol-tape/page.tsx`
- Page being replaced: `SDRUtils/dashboard/src/features/sofr-swaps-tape/` + `app/usd-swaps/page.tsx`
- Prior design docs: `docs/plans/2026-04-13-trade-tape-design.md`, `docs/plans/2026-04-13-trade-tape.md`
