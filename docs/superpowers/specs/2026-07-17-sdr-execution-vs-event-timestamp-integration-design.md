# SDR Execution-vs-Event Timestamp Integration — Design

**Date**: 2026-07-17
**Owner**: @yieldcurvemonkey
**Status**: Draft for review
**Companion**: `2026-07-17-sdr-execution-vs-event-timestamp-integration-implementation.md` (to be written by the writing-plans step)
**Related**: [2026-04-24-sdr-compliance-remediation-design.md](../../plans/2026-04-24-sdr-compliance-remediation-design.md) — §2.1 "Event-vs-Execution timestamp conflation" finding; this spec finishes what that pass deferred.

---

## 1. Summary

The DTCC-backed SDR feed reports two distinct, mandatory timestamps on every swap record — **Execution timestamp** (CFTC Part 45 field #96) and **Event timestamp** (field #30) — and their difference is a first-class, regulator-defined quantity (`event − execution ≥ 0`, a hard TR-enforced invariant). ARBS reads both raw columns at the feed edge but **keeps only one, and even that one means different things per product**:

- **USD swaps**: keep Execution, **drop Event** at the `usd_swaps.py` day-frame merge whitelist. The event timestamp never reaches the tape and is unrecoverable without re-ingest.
- **Swaptions / capfloors**: read Event and **store it into `execution_timestamp`** — a silent cross-product conflation. The same internal column carries execution for swaps but event for swaptions; the true execution time is discarded.
- **Everywhere**: no per-row execution-vs-event delta is computed or persisted; the frontend shows a single "Time" column.
- **`original_execution_timestamp`** (the documented "event-study anchor") is a byte-for-byte **copy** of `execution_timestamp` — the "Phase-4 alpha-join" that would give it real meaning for cleared/novated rows was never implemented. Analytics that CLAUDE.md mandates bucket on this anchor silently bucket on raw execution time; this is correct today only because the two columns are identical.

This design makes **all three timestamps first-class and transparent across the full stack** — ingest → parse → model → lifecycle → enrichment → schema → API → frontend → monitoring — with two precomputed, spec-anchored deltas, and finishes the deferred alpha-join on a best-effort, measured basis.

Approach (decided): **contract-first, bottom-up, phased**, with a single destructive full-history re-ingest as the final gated phase. Scope (decided): **all three tape families** (usd-swaps-tape-v2, swaptions, legacy SOFR), full parity. Alpha-join (decided): **best-effort lineage resolution + a reconciliation report** quantifying β/γ coverage before analytics trust it.

## 2. Background

### 2.1 The three timestamps (from the Tech Spec)

Extracted from CFTC Part 43/45 Technical Specification v3.1/3.2 (worked examples Tables 8–19; field table entries #30, #96, #D3):

| Field | Spec name / # | Definition (paraphrased from spec) | Behaviour |
|---|---|---|---|
| Execution | Execution timestamp / **#96** ("Transaction related") | Date+time the trade was **originally executed**, minting the UTI. *"Remains unchanged throughout the life of the UTI."* For clearing swaps = when the DCO accepts the original swap (fn. 72). | Immutable per UTI; **reused verbatim** on every same-UTI continuation report (MODI/CORR/EROR/REVI/TERM/VALU/PTNG). A **new UTI** (NEWT-CLRG, NEWT-COMP, NEWT-NOVA, NEWT-ALOC, NEWT-EXER) mints a **new** execution timestamp. |
| Event | Event timestamp / **#30** ("Events") | Date+time of **occurrence of the reported event** as determined by the reporting counterparty. | **Hard validation rule: `Event ≥ Execution`.** For NEWT-TRAD, `Event == Execution`. For lifecycle events (amendment/termination/correction/clearing/compression/exercise), it is the event's own — often much later — time. |
| Dissemination | Dissemination timestamp / **#D3** | When the SDR publicly disseminated the report (§43.2). | SDR-generated, a few seconds–minutes after Event. **Not present per-row in the ARBS trade feed** (see §2.3); the closest available report-time proxy is #30. |

Also relevant but out of primary scope: **Reporting timestamp #97** (`≥ Execution`, submission latency) and **Valuation timestamp #113** (VALU/MARU daily marks). Neither is in the current ARBS feed.

**The difference `event − execution ≥ 0` is the lifecycle/reporting lag.** `~0` ⇒ a genuinely fresh execution (NEWT). `>0` (minutes → years) ⇒ maintenance/churn on an old position: a 2018 trade's 2026 amendment carries a 2026 event timestamp against a 2018 execution. Two structural subtleties the design must respect:

1. **New-UTI events mint a fresh execution timestamp** (NEWT-CLRG clearing swaps, NEWT-COMP compression output, NEWT-NOVA/ALOC legs) set to the event instant, so *their own* delta collapses to 0 even though they are **not new economic risk** — they replace terminated originals. Lineage (Original Dissemination Identifier / Prior UTI) + the Cleared flag must net these out.
2. **SDR-transfer NEWT-PTNG** is the one NEWT that keeps the **same** execution timestamp.

### 2.2 What is neglected today (by severity)

Concrete, file-anchored:

- **[CRITICAL] Event timestamp dropped for USD swaps.** `classify_swap_trade` reads only `Execution Timestamp` ([`usd_swaps.py:76,150-153`](../../../SDRUtils/products/usd/usd_swaps.py)); the day-frame merge whitelist (~`usd_swaps.py:1934-1962`) keeps `Event type` but **not** `Event timestamp`. This is the drop point — the raw event time dies here and cannot be reconstructed from the tape.
- **[HIGH] Cross-product conflation.** `usd_swaptions.py:309,354,430,439` and `usd_capfloors.py:201,261,309` read `Event timestamp` and store it **as** `execution_timestamp`, bucketing days on it. The true `Execution Timestamp` is discarded for these products; the internal column name is semantically overloaded.
- **[HIGH] No model slot.** `TradeClassification` has a single `execution_timestamp` field ([`classification.py:57-86`](../../../SDRUtils/core/classification.py)); `config.SDRColumnConfig` has no `raw_event_timestamp`. Storing both is impossible without a model + config change.
- **[HIGH] `original_execution_timestamp` is a placeholder copy.** `trade_tape._enrich_exec_timestamps:765` sets it `= execution_timestamp`; the alpha-join is deferred to an unimplemented "Phase 4" ([`trade_tape.py:748-780`](../../../SDRUtils/analytics/trade_tape.py)). `lifecycle_v2.build_summary` computes the correct within-chain anchor but `flatten_lifecycle_summary:205-277` **drops it** (only `lc_correction_lag_seconds` survives).
- **[HIGH-LATENT] Analytics bucket on the wrong anchor.** `_enrich_context` (FOMC/session), `_enrich_rv` (clustering), `_match_novation_pairs`, and `fomc/intraday/filters/seasonality/liquidity/volume` bucket on `execution_timestamp`, though [`SDRUtils/CLAUDE.md`](../../../SDRUtils/CLAUDE.md) mandates `original_execution_timestamp`. Harmless only because the two are identical today. Also a step-order bug: `_match_novation_pairs` (compute step 7) runs *before* `_enrich_exec_timestamps` (step 9) populates the anchor.
- **[HIGH] Nothing persisted.** No `event_timestamp`, no delta column on `legs_v2`/`packages_v2` or v1 ([`_tape_schema_v2.py`](../../../SDRUtils/_swappulse_scripts/_tape_schema_v2.py)); the only duration materialized is `(execution_end − execution_start)` stuffed into `package_metrics` JSONB. No index for a future event/lag column.
- **[MEDIUM-HIGH] Inconsistent API anchors.** Six aggregation routes bucket on `COALESCE(original_execution*, execution*)` (volume-grid, analytics-timeseries, rarity, timeseries, flow-history, unrecognised-underliers); four use raw `execution_timestamp` (intraday-vwap, block-heatmap, flow-momentum, clusters). `clusters` still reads the **frozen `legs_v1`**. `unrecognised-underliers` aliases the coalesced value **as** `execution_timestamp`. No route lets the caller pick an anchor; no server-side delta exists.
- **[MEDIUM] No frontend event field, delta formatter, or delta filter.** Types carry `original_execution_start`/`clearing_accepted_start` (both anchors already cross the wire) but no event field and no delta; one "Time" column renders `execution_start` (NYC). The leg sub-table's "Exec Ts" renders **UTC** (`LegsSubTable.tsx:32-41`) — inconsistent with the NYC main tape. The only delta logic is the boolean CLR badge (`RowBadges.helpers.ts:178-207`, ≥60s exec-vs-clearing gap). The swaptions leg type has a **dormant unused `event_timestamp` field** (`swaptions-tape/types/trade.types.ts:21`).
- **[MEDIUM] No latency monitoring.** `_tape_monitoring_v2` tracks only classification-flag rates — no median/p95 report-lag panel, no late-report/late-amendment alert.

### 2.3 Two grounding facts that shape the design

1. **The trade feed carries only two per-row timestamps.** `builder.py` parses exactly `Event timestamp` and `Execution Timestamp` from the DTCC trade rows (`builder.py:418-419,485-486`). `dissemDTM` (#D3) exists only in the intraday **slice-index JSON** and is used transiently to select files (`builder.py:598-604`) — it is never carried into trade rows. **Therefore `event_timestamp` (#30) is the report-time proxy; there is no separate dissemination column to recover.**
2. **Lineage machinery for the alpha-join already exists.** `graph_resolver.build_synthetic_uti_mapping` clusters related reports into a "Synthetic UTI" via connected components over **`Original Dissemination Identifier`**, anchoring each component on its earliest NEWT (`graph_resolver.py:74-150`). `LifecycleEvent` already carries `original_dissemination_id` (`lifecycle_v2.py:22`). **But** the α↔β link for cleared swaps depends on whether the public tape actually disseminates that lineage (Prior UTI is frequently masked). Hence the alpha-join must be **best-effort and measured** (§6).

### 2.4 Why transparency matters (analytics that are wrong/fragile today)

- **Flow booked to the wrong day.** Aggregating notional/DV01 by event time would book an old trade's amendment as fresh risk. Even filtered to `Action=NEWT`, cleared/compression/novation output legs are not new risk and double-count unless netted by lineage.
- **Swaptions/capfloors timeline is on report time.** Their FOMC, intraday vol-grid, and event-study bucketing currently key on Event-stored-as-execution — off by the dissemination lag (15 min–24 business hours for post-priced/block trades per audit B3), scattering one trade across later dates.
- **`original_execution` signal is zero.** Schema indexes, dashboard sort/pagination, `backfill_stir_direction.snap_timestamp`, and the analytics-route COALESCE anchors all lean on a byte-copy. When the alpha-join lands, results and sort order change silently unless we plan the cutover.
- **No fresh-vs-late separation.** `lc_correction_lag_seconds` is a whole-chain aggregate (0 for single-event NEWT) — it cannot flag a single fresh trade reported late, the exact block/post-priced case that matters.

## 3. Goals / Non-goals

### Goals

1. **Both regulatory timestamps are first-class and persisted** on every tape row, per product, with correct semantics (no drop, no conflation).
2. **Two precomputed, indexable deltas**: `report_lag_seconds = event − execution` (the "execution vs event" quantity) and `alpha_lag_seconds = execution − original_execution` (clearing/novation lag).
3. **A real, best-effort `original_execution_timestamp`** via existing lineage machinery, with an `original_execution_source` provenance flag and a reconciliation report of β/γ coverage.
4. **Analytics honor the documented anchor**: FOMC/novation/intraday/session/clustering bucket on `original_execution_timestamp` (fallback execution), via a single parameterized `ts_col`, with the step-order bug fixed.
5. **Frontend transparency**: a second timestamp column + a formatted delta chip (`+3d 04:12` / `live`), delta filter/sort, timezone unified to NYC, on all three tape UIs (with mobile parity).
6. **Consistent API anchors**: one `anchor` param across aggregation routes; `clusters` migrated off frozen `legs_v1`; cursor/poll markers stay coherent with `ORDER BY`.
7. **Latency monitoring**: median/p95 `report_lag_seconds`, late-report rate, late-arriving-amendment count in the daily quality series with alerts.
8. **Full historical coverage** via one guarded destructive re-ingest, with cache-version discipline.

### Non-goals

- **EMIR ingestion.** No EMIR feed is wired today; the pipeline is CFTC/DTCC Part 43/45. We add a forward-compat **regime/granularity guard** (§12) and document the EMIR "Event date is date-only" divergence, but do not build EMIR ingest.
- **Dissemination timestamp #D3 per-row.** Not in the trade feed (§2.3). Out of scope beyond documenting its absence.
- **Reporting #97 / Valuation #113 timestamps.** Not in the feed; not added.
- **Non-IR asset classes.** IR only.
- **Reworking the Economic-vs-Admin matrix or lifecycle state machine** beyond surfacing timestamps they already compute.

## 4. The timestamp contract (canonical data model)

One contract, identical names Python ↔ DB ↔ TypeScript. Per **leg** (packages roll up to `_start`/`_end` + `max_*`):

| Column | Type (DB) | Source | Semantics |
|---|---|---|---|
| `execution_timestamp` | `TIMESTAMPTZ NOT NULL` | raw `Execution Timestamp` (#96) | economic trade time, immutable per UTI |
| `event_timestamp` | `TIMESTAMPTZ` (nullable) | raw `Event timestamp` (#30) | reported-event time; `≥ execution` |
| `original_execution_timestamp` | `TIMESTAMPTZ` (nullable) | lineage-resolved (§6) | alpha's original strike; `≤ execution` |
| `report_lag_seconds` | `NUMERIC` | `event − execution` | ≥ 0; **the "execution vs event" delta** (primary UI) |
| `alpha_lag_seconds` | `NUMERIC` | `execution − original_execution` | ≥ 0; clearing/novation lag; 0/NULL when α==self |
| `original_execution_source` | `TEXT` | `'newt' \| 'lineage' \| 'fallback'` | provenance of the alpha-join |
| `event_timestamp_granularity` | `TEXT` | `'second' \| 'day'` | forward-compat; `'second'` for CFTC, `'day'` for EMIR (§12) |

Package rollups: `event_start`/`event_end` = min/max member `event_timestamp`; `max_report_lag_seconds`, `median_report_lag_seconds`; `original_execution_start` becomes **real** (min member `original_execution_timestamp`); `late_report` boolean = `max_report_lag_seconds > THRESHOLD`.

**Delta representation decisions**: store the delta as `NUMERIC` **seconds** (average/percentile-friendly for Grafana; indexable) *and* keep the raw timestamps (never store only the delta). Never bucket economic volume/DV01 on event time by default. `NULL` deltas render as `unknown`, never `0`.

**Invariant assertions (fail-loud at ingest)**: `event_timestamp >= execution_timestamp` (allow small negative tolerance for clock skew, else clamp+flag); `original_execution_timestamp <= execution_timestamp`. Violations increment a monitored counter (mirrors the `_assert_risk_populated` pattern that guards the null-risk-curve hazard).

## 5. Design by layer (build order)

### 5.1 Pipeline foundation (Phase 1)
- `config.py`: add `raw_event_timestamp = "Event timestamp"`; internal `event_timestamp`, `report_lag_seconds`, `original_execution_source` names to `SDRColumnConfig` (alongside `raw_execution_timestamp:207`, `execution_timestamp:179`).
- `core/classification.py`: add `event_timestamp: Optional[datetime]` (and `report_lag_seconds`, `original_execution_source`) to `TradeClassification:57-86`, inherited by `SwapTradeClassification`/`SwaptionTradeClassification`. **Foundational — nothing downstream can carry a second timestamp without this.**
- `usd_swaps.py`: in `classify_swap_trade` also read `row.get("Event timestamp") → event_timestamp`; **add `"Event timestamp"` to the day-frame merge whitelist (~1934-1959)** so it survives the snake_case at 1962. Closes the drop point. Keep day-bucketing on Execution (the correct event-study anchor per the existing 1674-1676 comment).
- `usd_swaptions.py` / `usd_capfloors.py`: **split the conflation** — read `Execution Timestamp → execution_timestamp` **and** `Event timestamp → event_timestamp` separately (currently Event is stored as execution). Gated on a data-reliability check: confirm DTCC `Execution Timestamp` is reliably populated for these products before switching the day-bucket source (§14, D1). Where Execution is missing, fall back to Event with a flag rather than silently.

### 5.2 Enrichment + alpha-join (Phase 2) — see §6
- `lifecycle.py`: remove/flag the silent `exec_ts := event_ts` fallback (`462-463`); optionally surface per-row `event_timestamp`.
- `lifecycle_v2.py`: in `flatten_lifecycle_summary` **emit** `summary.original_execution_timestamp` as `lc_original_execution_timestamp` (+ `lc_latest_update_timestamp`). Keep `lc_correction_lag_seconds` but add a per-row report lag.
- `trade_tape._enrich_exec_timestamps`: carry `event_timestamp` through; compute `report_lag_seconds`; set `original_execution_timestamp` from the lineage resolver (fallback `execution_timestamp`, source-flagged); compute `alpha_lag_seconds`. **Move timestamp-prep before** `_enrich_event_type`/`_enrich_context`/`_enrich_rv` and fix `_match_novation_pairs` step order + anchor.

### 5.3 Analytics anchor realignment (Phase 3) — see §7

### 5.4 Schema + migration (Phase 4) — see §8

### 5.5 API anchor unification (Phase 5) — see §9

### 5.6 Frontend (Phase 6) — see §10

### 5.7 Monitoring (Phase 7) — see §11

### 5.8 Backfill (Phase 8) — see §13

## 6. Alpha-join (best-effort + reconciliation)

**Goal**: give `original_execution_timestamp` a real value = the alpha's original execution for β/γ NEWT-CLRG and NEWT-NOVA rows; leave it `= execution_timestamp` (flagged `fallback`) where public lineage is absent.

**Mechanism** (reuse existing machinery, no new graph code):
1. Within a synthetic-UTI component (`graph_resolver` connected components over `Original Dissemination Identifier`), the component's anchor NEWT `execution_timestamp` is the original execution. Rows in the same component inherit it → `source='lineage'`.
2. A plain NEWT with no prior linkage anchors itself → `source='newt'`.
3. Unlinked β/γ rows (clearing/novation output whose alpha is not disseminated / is masked) → `original_execution_timestamp = execution_timestamp`, `source='fallback'`, `alpha_lag_seconds = 0`.
4. The ±300s `_match_novation_pairs` matcher (`trade_tape.py:225-258`) remains the fallback linker for the novation case; it must run **after** the anchor is populated and bucket on `original_execution_timestamp`.

**Reconciliation report** (the decided deliverable): a data-quality artifact (notebook + a row in the daily quality series) quantifying, per day and per action-type, how many β/γ rows resolved via `lineage` vs `fallback`, and the distribution of `alpha_lag_seconds` for the linked set. Analytics must not trust `alpha_lag` (or an `original_execution`-based bucket) for a day until coverage clears a documented threshold; below it, analytics fall back to `execution_timestamp` for that day. This makes the partial coverage **measurable and safe** rather than silently wrong.

## 7. Analytics anchor realignment

Parameterize a single `ts_col` (default `original_execution_timestamp`, fallback `execution_timestamp`) threaded through:
- `trade_tape._enrich_context` (`add_event_classifications` date_col, `classify_meeting_proximity` input, `execution_session` derivation), `_enrich_rv` (`trade_clustering` ts_col), `_match_novation_pairs` (proximity leg + step order).
- `fomc.classify_meeting_proximity`/`FOMCAnalyzer`, `intraday.*` (cumulative DV01/clustering/timing), `filters.add_execution_date` (source-column aware), `seasonality.add_event_classifications`, `liquidity`, `volume`.
- **Keep `rc_timeline` on `event_timestamp`** — RC changes are a reporting-time concept and are correct as-is.

Guardrail: because the anchor becomes real (diverges from execution for cleared/novated rows), this phase changes bucket membership and sort order for those rows. It ships **after** §6's reconciliation shows acceptable coverage, and behind the cache-version bumps of §14.

## 8. Schema & migration

Additive, idempotent, re-runnable via `ensure_schema()` on the **live** v2 tables (matching the existing `ADD COLUMN IF NOT EXISTS` pattern at `_tape_schema_v2.py:271-393`):
- `legs_v2`: `+ event_timestamp TIMESTAMPTZ`, `+ report_lag_seconds NUMERIC`, `+ alpha_lag_seconds NUMERIC`, `+ original_execution_source TEXT`, `+ event_timestamp_granularity TEXT`.
- `packages_v2`: `+ event_start/event_end TIMESTAMPTZ`, `+ max_report_lag_seconds/median_report_lag_seconds NUMERIC`, `+ late_report BOOLEAN`.
- Indexes: `CREATE INDEX IF NOT EXISTS ... legs_v2(event_timestamp)`; `legs_v2(report_lag_seconds)` for outlier queries; `packages_v2(as_of_date, event_start DESC NULLS LAST)` for potential event-ordered paging. Build `CONCURRENTLY` where possible; **no `NOT NULL` default** on the ~1.3M-row tables (avoids a long lock/rewrite).
- `display_v2` view: add the new **package** columns to the SELECT (`_tape_schema_v2.py:472-595`); legs auto-carry via `to_jsonb(l)`.
- `ingest_usdswaps_tape.py`: extend `LEG_COLUMNS`/`PACKAGE_COLUMNS`, `_LEG_TS_COLS` coercion (`_to_db_value:1002-1008`), `build_package_rows` rollups (`1336-1392`), and `_LATEST_MIGRATION_COLS`.
- Swaptions/SOFR parity: `ingest_usdswaptions.py` + swaptions schema, and legacy `ingest_usdswaps.py` + `_tape_schema.py` — add the same event/delta columns end-to-end (these tables have **no** event/original columns today).

## 9. API anchor unification

- **Expose**: the main row wire already carries both anchors; project `event_start`, the deltas, and `original_execution_source` (extend `lib/usd-swaps-tape-v2.ts resolveDisplayView`; no exclusion change needed).
- **Parameterize**: add `anchor ∈ {execution, event, original, coalesced}` to `packageAnalyticsCtes` (`analytics.ts:260`) so `analytics-timeseries` + `rarity` expose either series + delta; update the fast-path inline copies that bypass the helper (`analytics-timeseries route.ts:201,206,461`; `rarity route.ts:125,150`).
- **Align the split**: bring `intraday-vwap`, `block-heatmap`, `flow-momentum` onto the same anchor param (currently raw execution) so a same-instrument VWAP/volume/heatmap agree across panels.
- **Fix `clusters`**: migrate `clusters/route.logic.ts` off frozen `legs_v1` → `legs_v2`, then honor the anchor.
- **Rename** the misleading `unrecognised-underliers` alias (coalesced value currently named `execution_timestamp` → `anchor_ts`).
- **Ordering default stays `execution_start`** for the main tape; if ordering becomes anchor-selectable, derive `nextCursor`/`latestExecutionStart` from the **same** chosen anchor (else cursor pagination + the 30s incremental poll skip/duplicate rows). This is the single most cursor-fragile change.

## 10. Frontend

- **Types** (`usd-swaps-tape-v2/types/trade.types.ts`, base `sofr-swaps-tape/types`, `swaptions-tape/types`): add `event_timestamp`/`report_lag_seconds`/`original_execution_source` to leg and `event_start`/`max_report_lag_seconds`/`late_report` to row. Wire up the **dormant** swaptions `event_timestamp` field.
- **Formatter** (`utils/format.ts`): `formatTimestampDelta(execIso, eventIso): string` → `+3d 04:12` / `live` (event null / not-yet-disseminated) / signed forms, reusing `NYC_TIMEZONE` + the CLR-badge ms pattern. A `formatEventTimestamp` wrapper over `formatExecutionWindow`.
- **Table** (`columns.tsx`): insert a second timestamp column after "Time" (label "Event"/"Dissem") with an inline delta chip; sortable + `TIME_FILTER_MATCH_MODE_OPTIONS`; optional dedicated "Lag" column. `LegsSubTable.tsx`: add per-leg event ts + delta and **reconcile the local UTC `formatTime` to NYC**. `MobileTradeCards.tsx`: delta chip parity.
- **Filter** (`filter-utils.ts`): add the event field to `TIMESTAMP_FILTER_FIELDS`; add a numeric-candidate path for delta filter/sort (delta is computed, not a stored ISO field). Optionally repurpose the orphan `TimestampColumnFilter` as a delta-range element (switch its matcher UTC→NYC).
- **Verify in Chrome MCP locally before commit/deploy** (per repo memory `feedback_chrome_mcp_before_push`).

## 11. Monitoring

Extend `_tape_monitoring_v2` → `arbs_usd_swap_tape_quality_daily_v2`: daily median/p95 `report_lag_seconds`, `% rows lag > threshold` (late-report rate), late-arriving-amendment count (`lc_correction_crossed_day`), and the §6 alpha-join coverage ratio. Grafana alerts on lag drift and coverage regressions. Ships **in the same change** as the columns, not after (else a feed-timing regression the new column would reveal stays invisible).

## 12. Cross-regime (EMIR) forward-compat

EMIR "Event date" (2.153) is **date-only**; CFTC Event timestamp (#30) is a full datetime. Storing a date-only value in a `TIMESTAMPTZ` and diffing against second-precision execution fabricates a spurious intraday delta. Guard: the `event_timestamp_granularity` column (`'second'` for CFTC, `'day'` for EMIR); any delta consumer interprets EMIR-sourced rows at **day** granularity. We set it `'second'` for the current CFTC feed and document the rule; no EMIR ingest is built.

## 13. Backfill (destructive full re-ingest)

`event_timestamp` is **not reconstructable** from the tape — full coverage requires re-running `run_usdswaps_pipeline` against raw SDR per prior day, which **deletes+rewrites the remote Supabase prod tape** the dashboard reads (repo memory `project_usdswaps_tape_backfill`). Plan:
1. Land all forward-path changes (Phases 1–7) so new ingests already carry the columns.
2. Bump **both** `TRADE_TAPE_CACHE_VERSION` (`trade_tape.py`) and `DETECTION_CACHE_VERSION` (`usd_swaps.py`) — without both, stale cached day-frames lack the new columns and re-ingest silently writes NULLs (repo memory `project_tape_null_risk_curve_hazard`).
3. Run the full-history re-ingest **off-hours**, chunked by day, **guarded by `_assert_risk_populated`** (a transient ERIS curve failure must not publish all-NULL risk as "success" — the 07/06 incident), plus the new timestamp-invariant assertions (§4).
4. Emit the §6 reconciliation report over the re-ingested history; only then flip analytics to the `original_execution` anchor (§7) for days that clear the coverage threshold.

## 14. Cross-cutting decisions & resolutions

- **D1 — swaptions/capfloors source switch.** *Is Event-as-execution deliberate (because DTCC Execution is unreliable for these) or an oversight?* → Verify field availability on real swaptions/capfloors data **before** switching the day-bucket source; if Execution is sparse, keep Event as the day-bucket but still store true Execution separately and flag. Coordinate with any concurrent MMS/regrouping sessions touching these detectors (repo memory `project_mms_package_detection`).
- **D2 — one contract, three tapes.** Same column names across usd-swaps-tape-v2, swaptions, SOFR to prevent the exact per-product drift we are fixing.
- **D3 — anchor default.** Ordering/pagination stays `execution_start`; economic bucketing stays execution (→ real `original_execution` once coverage clears). Event time is a **transparency column + delta**, never the default volume bucket.
- **D4 — deltas stored, not on-read.** Precompute at enrichment; store `NUMERIC` seconds + raw timestamps.
- **D5 — fail-loud invariants** (§4) over silent coercion, consistent with the lifecycle validator's D4 philosophy.

## 15. Testing strategy

- **Unit**: config/model carry both timestamps; each classifier maps the right raw column (regression tests pinning the swaps drop-point fix and the swaptions/capfloors de-conflation); `report_lag = event − execution ≥ 0`; alpha-join source flags on synthetic NEWT/CLRG/NOVA chains; invariant assertions raise on violation.
- **Property**: `event ≥ execution` and `original_execution ≤ execution` across generated lifecycle chains.
- **Schema/ingest**: `ensure_schema()` idempotent (re-run no-op); new columns populate; NULL handling for legacy rows.
- **API**: each aggregation route returns coherent series under each `anchor`; cursor/poll invariants hold when ordering anchor changes; `clusters` reads `legs_v2`.
- **Frontend**: `formatTimestampDelta` cases (`+3d 04:12`/`live`/`unknown`); delta filter/sort; NYC consistency; Chrome-MCP visual check.
- **Fast gate** (per repo `CLAUDE.md`): `conda run -n stir python -m pytest tests -m "not slow and not network and not db"` after each phase; full suite before the backfill.

## 16. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Destructive backfill rewrites prod tape | Off-hours, chunked, `_assert_risk_populated` + invariant guards; forward path lands first |
| Cache-version miss → silent NULLs | Bump **both** cache versions; §15 test asserts new columns non-NULL post-reingest |
| `original_execution` divergence breaks cursor/sort | Keep `execution_start` ordering default; derive cursor from the same anchor; ship analytics anchor flip only after coverage clears |
| Alpha-join partial coverage trusted blindly | Reconciliation report + per-day coverage gate (§6) |
| Swaptions/capfloors source switch breaks vol-grid bucketing | D1 data-availability check first; coordinate with MMS/regrouping sessions |
| Long lock on 1.3M-row ALTER | `ADD COLUMN IF NOT EXISTS` nullable, no default; `CREATE INDEX CONCURRENTLY` |
| EMIR date-only delta spurious | `event_timestamp_granularity` guard (§12) |
| Monitoring gap during rollout | Lag panel ships with the columns, not after |

## 17. Phased build sequence (→ companion implementation plan)

1. **Foundation** — config + model + classifier fixes (swaps drop-point, swaptions/capfloors de-conflation). Cache-version bump groundwork.
2. **Enrichment + alpha-join** — surface `lc_original_execution_timestamp`; lineage resolver + source flag; compute both deltas; fix step order.
3. **Analytics anchor** — parameterize `ts_col`; realign FOMC/novation/intraday/session/clustering; keep rc_timeline on event.
4. **Schema + ingest** — idempotent migrations + indexes; all three tape families; display view.
5. **API** — anchor param; align the route split; migrate `clusters`; cursor coherence; rename misleading alias.
6. **Frontend** — types, `formatTimestampDelta`, second column + delta chip, leg/mobile parity, filters, NYC unification; Chrome-MCP verify.
7. **Monitoring** — lag panel + alerts + alpha-join coverage.
8. **Backfill** — guarded destructive full-history re-ingest; reconciliation report; flip analytics anchor per coverage gate; update `SDRUtils/CLAUDE.md` Timestamps section.

## 18. Open questions (to resolve during planning)

- Exact `report_lag` late-report threshold and the alpha-join coverage gate percentage (need a first pass over real lag/coverage distributions).
- Whether swaptions/capfloors DTCC `Execution Timestamp` is reliably populated (D1) — determines source-switch vs dual-store.
- Whether the main tape should ever offer event-anchored ordering, or keep event strictly as a transparency column (D3 leans keep-as-column).
- SOFR/legacy tape: confirm the legacy `arbs_usd_swap` tables are still consumed enough to justify full parity now vs a thin forward-only column add.
