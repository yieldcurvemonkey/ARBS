# SDR Execution-vs-Event Timestamp Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, this session) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CFTC Part 43/45 Execution (#96) and Event (#30) timestamps first-class and transparent across the full SDR stack — store both + two deltas, finish the `original_execution` alpha-join best-effort, realign analytics to the documented anchor, surface a second timestamp column + delta chip in the tape UIs, add latency monitoring, and stage a guarded full-history re-ingest.

**Architecture:** Contract-first, bottom-up. One canonical timestamp contract (identical column names Python↔DB↔TS) is defined once, then each layer is built and independently verified. Deltas are precomputed at enrichment and stored as `NUMERIC` seconds. The alpha-join reuses existing `graph_resolver` lineage and degrades gracefully with a source flag + reconciliation report.

**Tech Stack:** Python 3 (pandas, `conda run -n stir`), Postgres/Supabase (idempotent DDL), Next.js/TypeScript (jest ESM via `npm test`), React tape UIs.

**Design source:** [2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md](../specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md)

## Global Constraints

- **Test gate (per repo CLAUDE.md):** `conda run -n stir python -m pytest tests -m "not slow and not network and not db"` after each Python phase. Full suite needs network + DATABASE_URL (~1.5h) — run before backfill only.
- **Dashboard tests:** `npm test` only (jest ESM); plain `npx jest` bypasses ESM mocks → false Supabase failures (repo memory `project_dashboard_jest_esm`).
- **Cache versions:** any change to enrichment output (columns/values) MUST bump `TRADE_TAPE_CACHE_VERSION` (`SDRUtils/analytics/trade_tape.py`); any detector-output change MUST bump `DETECTION_CACHE_VERSION` (`SDRUtils/products/usd/usd_swaps.py`). Bump BOTH before re-ingest.
- **Canonical column names** (identical everywhere): `execution_timestamp`, `event_timestamp`, `original_execution_timestamp`, `report_lag_seconds`, `alpha_lag_seconds`, `original_execution_source` (`'newt'|'lineage'|'fallback'`), `event_timestamp_granularity` (`'second'|'day'`). Package rollups: `event_start`, `event_end`, `max_report_lag_seconds`, `median_report_lag_seconds`, `late_report`.
- **Tuning constants (decided):** `LATE_REPORT_THRESHOLD_SECONDS = 900`; `ALPHA_JOIN_COVERAGE_GATE = 0.95`. Both live in `SDRUtils/config.py`.
- **Invariants (fail-loud at ingest):** `event_timestamp >= execution_timestamp` (small negative tolerance for clock skew → clamp + flag); `original_execution_timestamp <= execution_timestamp`.
- **Non-negotiable safety:** the destructive full-history re-ingest (Phase 8) is STAGED with a runbook, NOT executed autonomously (it deletes+rewrites the remote prod Supabase tape). Guard with `_assert_risk_populated`.
- **Frontend:** verify tape UI changes in Chrome MCP locally before commit (repo memory `feedback_chrome_mcp_before_push`).

---

## Phase 1 — Pipeline foundation (config + model + classifier fixes)

Closes the CRITICAL swaps drop-point and the HIGH swaptions/capfloors conflation; adds the model/config slots everything else needs.

### Task 1.1: config slots + tuning constants

**Files:** Modify `SDRUtils/config.py`; Test `tests/sdr/test_config_timestamps.py`.
**Produces:** `SDRColumnConfig.raw_event_timestamp = "Event timestamp"`; internal names `event_timestamp`, `report_lag_seconds`, `alpha_lag_seconds`, `original_execution_source`, `event_timestamp_granularity`; module consts `LATE_REPORT_THRESHOLD_SECONDS = 900`, `ALPHA_JOIN_COVERAGE_GATE = 0.95`.

- [ ] Write failing test asserting `SDRColumns.raw_event_timestamp == "Event timestamp"` and the internal-name attributes + consts exist.
- [ ] Run → fail. Add the fields/consts. Run → pass. Commit.

### Task 1.2: `TradeClassification.event_timestamp`

**Files:** Modify `SDRUtils/core/classification.py` (`TradeClassification:57-86`, inherited by `SwapTradeClassification`, `SwaptionTradeClassification`); Test `tests/sdr/test_classification_model.py`.
**Produces:** `event_timestamp: Optional[datetime] = None`, `report_lag_seconds: Optional[float] = None`, `original_execution_source: Optional[str] = None` on the dataclass.

- [ ] Test: construct a `SwapTradeClassification` with `event_timestamp` set; assert round-trips through the frame-builder (`to_dict`/asdict) as a column.
- [ ] Run → fail. Add fields. Run → pass. Commit.

### Task 1.3: USD swaps — read Event timestamp + fix the drop point

**Files:** Modify `SDRUtils/products/usd/usd_swaps.py` (`classify_swap_trade:76,150-153`; day-frame merge whitelist `~1934-1962`); Test `tests/sdr/test_usd_swaps_event_ts.py`.
**Interfaces:** consumes 1.2's `event_timestamp` field.

- [ ] Test: a synthetic day-frame with distinct `Execution Timestamp` and `Event timestamp` → after `build_classification_dataframe`, the output frame has both `execution_timestamp` and `event_timestamp` columns with the correct values (regression pin on the drop point).
- [ ] Run → fail (event_timestamp missing). Add `event_timestamp` read in `classify_swap_trade`; add `"Event timestamp"` to the merge whitelist so it survives snake_case. Run → pass. Verify day-bucketing still uses Execution (unchanged). Commit.

### Task 1.4: Swaptions/capfloors — de-conflate (store both, graceful fallback)

**Files:** Modify `SDRUtils/products/usd/usd_swaptions.py` (`classify_trade:309,354,430,439`), `SDRUtils/products/usd/usd_capfloors.py` (`classify_trade:201,261,309`); Test `tests/sdr/test_swaption_capfloor_deconflation.py`.
**Decision (D1):** `execution_timestamp` ← `Execution Timestamp`; where missing/NaT, fall back to `Event timestamp` and set `original_execution_source='fallback'`. `event_timestamp` ← `Event timestamp`. **Day-partition bucketing source left unchanged** (still `Event timestamp`) to avoid an unverifiable partition/behavior change; documented inline.

- [ ] Test A: row with both present → `execution_timestamp == Execution`, `event_timestamp == Event`, not equal (de-conflated).
- [ ] Test B: row with `Execution Timestamp` NaT → `execution_timestamp == Event`, source flag `'fallback'`.
- [ ] Run → fail. Implement dual read + fallback in both classifiers. Run → pass. Commit.

### Task 1.5: Phase 1 gate

- [ ] `conda run -n stir python -m pytest tests -m "not slow and not network and not db"` → green (or pre-existing failures triaged & documented). Commit any fixups.

---

## Phase 2 — Enrichment + alpha-join

### Task 2.1: Surface the within-chain original execution from lifecycle_v2

**Files:** Modify `SDRUtils/core/lifecycle_v2.py` (`flatten_lifecycle_summary:205-277` — emit `lc_original_execution_timestamp`, `lc_latest_update_timestamp`); Modify `SDRUtils/core/lifecycle.py` (flag/remove the silent `exec_ts:=event_ts` fallback at `462-463`, replace with explicit source flag); Test `tests/sdr/test_lifecycle_original_exec.py`.
**Produces:** `lc_original_execution_timestamp` column on the lifecycle-flattened frame.

- [ ] Test: a NEWT+MODI chain → `lc_original_execution_timestamp == NEWT.execution_timestamp`; `lc_latest_update_timestamp == last event_timestamp`.
- [ ] Run → fail. Emit the columns. Run → pass. Commit.

### Task 2.2: Lineage-based alpha-join resolver

**Files:** Create `SDRUtils/analytics/alpha_join.py` (thin wrapper over `graph_resolver.build_synthetic_uti_mapping`); Test `tests/sdr/test_alpha_join.py`.
**Produces:** `resolve_original_execution(df) -> df` adding `original_execution_timestamp`, `original_execution_source`, `alpha_lag_seconds`. Component anchor NEWT execution → `'lineage'`; self-NEWT → `'newt'`; unlinked → `= execution_timestamp`, `'fallback'`, `alpha_lag=0`.

- [ ] Test: two-report component (NEWT + linked CLRG via `Original Dissemination Identifier`) → CLRG row inherits NEWT execution as `original_execution_timestamp`, source `'lineage'`, `alpha_lag = execution - original > 0`.
- [ ] Test: orphan CLRG (no linkage) → `source='fallback'`, `original == execution`, `alpha_lag == 0`.
- [ ] Run → fail. Implement. Run → pass. Commit.

### Task 2.3: trade_tape enrichment — event passthrough, deltas, real anchor, step-order fix

**Files:** Modify `SDRUtils/analytics/trade_tape.py` (`_enrich_exec_timestamps:748-780`; `_match_novation_pairs:225-258`; compute-step ordering; `TRADE_TAPE_CACHE_VERSION` bump; cache key `325-327` fingerprint new cols); Test `tests/sdr/test_trade_tape_timestamps.py`.
**Interfaces:** consumes 2.1 `lc_original_execution_timestamp`, 2.2 `resolve_original_execution`.
**Behavior:** `event_timestamp` carried through; `report_lag_seconds = (event - execution).total_seconds()` (clamped ≥0 with tolerance, flag violations); `original_execution_timestamp` from `lc_original_execution_timestamp` else the alpha-join resolver else `execution` (source-flagged); `alpha_lag_seconds`. Move timestamp-prep before `_enrich_event_type`/`_enrich_context`/`_enrich_rv`; `_match_novation_pairs` reads `original_execution_timestamp`, runs after it exists.

- [ ] Test: enriched frame has `event_timestamp`, `report_lag_seconds` (≥0, correct), `original_execution_timestamp` (real, not a blind copy), `alpha_lag_seconds`, `original_execution_source`.
- [ ] Test: invariant violation (event < execution beyond tolerance) → clamped + flagged, monitored counter incremented.
- [ ] Run → fail. Implement + bump cache version. Run → pass. Commit.

### Task 2.4: Phase 2 gate → fast gate green. Commit.

---

## Phase 3 — Analytics anchor realignment

Repoint economic bucketing to `COALESCE(original_execution_timestamp, execution_timestamp)` (safe at any coverage — fallback rows have `original == execution`). Keep `rc_timeline` on `event_timestamp`.

### Task 3.1: Parameterize `ts_col` across analytics modules

**Files:** Modify `SDRUtils/analytics/{fomc.py,intraday.py,filters.py,seasonality.py,liquidity.py,volume.py}` and `SDRUtils/analytics/trade_tape.py` (`_enrich_context`, `_enrich_rv`); Test `tests/sdr/test_analytics_anchor.py`.
**Interface:** add `ts_col: str = "original_execution_timestamp"` (with per-row fallback to `execution_timestamp`) to `classify_meeting_proximity`, `trade_clustering`, `add_event_classifications`, `add_execution_date`, `daily_vwap`, liquidity/volume date derivations.

- [ ] Test: with a frame where `original_execution` differs from `execution` on cleared rows, FOMC-proximity/clustering/daily buckets key off `original_execution`; with identical values, output unchanged from today (back-compat regression).
- [ ] Run → fail. Parameterize (default anchor, execution fallback). Run → pass. Commit.

### Task 3.2: Phase 3 gate → fast gate green. Commit.

---

## Phase 4 — Schema + ingest (all three tape families)

### Task 4.1: v2 tape DDL (idempotent) + indexes + display view

**Files:** Modify `SDRUtils/_swappulse_scripts/_tape_schema_v2.py` (legs_v2 + packages_v2 `ADD COLUMN IF NOT EXISTS` block at `271-393` pattern; indexes; `display_v2` SELECT `472-595`); Test `tests/sdr/test_tape_schema_v2_migration.py` (DDL-string assertions; idempotency of `ensure_schema` SQL — no DB needed for string-level checks).
**Adds (§8 of design):** legs `event_timestamp`, `report_lag_seconds`, `alpha_lag_seconds`, `original_execution_source`, `event_timestamp_granularity`; packages `event_start/end`, `max_report_lag_seconds`, `median_report_lag_seconds`, `late_report`; indexes `legs_v2(event_timestamp)`, `legs_v2(report_lag_seconds)`, `packages_v2(as_of_date, event_start DESC NULLS LAST)`; new package cols in `display_v2`.

- [ ] Test: generated DDL contains each `ADD COLUMN IF NOT EXISTS <col>`; display-view SELECT includes the new package cols; no `NOT NULL` default on the new leg cols.
- [ ] Run → fail. Add DDL/indexes/view. Run → pass. Commit.

### Task 4.2: v2 ingest plumbing

**Files:** Modify `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` (`LEG_COLUMNS`, `PACKAGE_COLUMNS`, `_LEG_TS_COLS`/`_to_db_value:1002-1008`, `build_package_rows:1336-1392` rollups incl. `median`, `late_report` from `LATE_REPORT_THRESHOLD_SECONDS`, `_LATEST_MIGRATION_COLS`); Test `tests/sdr/test_ingest_tape_rollups.py`.

- [ ] Test: `build_package_rows` on legs with known `event_timestamp`/`report_lag_seconds` → `event_start/end`, `max/median_report_lag_seconds`, `late_report` correct; `original_execution_start` = min real anchor.
- [ ] Run → fail. Implement. Run → pass. Commit.

### Task 4.3: swaptions + SOFR/legacy schema+ingest parity (additive)

**Files:** Modify `SDRUtils/_swappulse_scripts/ingest_usdswaptions.py` (+swaptions schema), `SDRUtils/_swappulse_scripts/ingest_usdcapfloors.py`, `SDRUtils/_swappulse_scripts/ingest_usdswaps.py` (+`_tape_schema.py` legacy) — add `event_timestamp` (+ deltas where the tape has the anchor) additively. Test `tests/sdr/test_other_tapes_schema.py`.

- [ ] Test: each ingest's column list + schema DDL includes `event_timestamp`.
- [ ] Run → fail. Add columns. Run → pass. Commit.

### Task 4.4: Phase 4 gate → fast gate green. Commit.

---

## Phase 5 — API anchor unification (TypeScript)

### Task 5.1: Expose event + deltas on the main row wire

**Files:** Modify `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts` (`resolveDisplayView:50-75`; project `event_start`, deltas, `original_execution_source`); Test `.../__tests__/`.

- [ ] Test (jest): projected columns include the new fields. Run `npm test`. Commit.

### Task 5.2: `anchor` param + align the route split + fix `clusters` + rename alias

**Files:** Modify `SDRUtils/dashboard/src/lib/usd-swaps-tape-v2/analytics.ts` (`packageAnalyticsCtes` `tsAnchor: 'execution'|'event'|'original'|'coalesced'`); the aggregation routes `volume-grid/analytics-timeseries/rarity/timeseries/flow-history/intraday-vwap/block-heatmap/flow-momentum/clusters/data-quality`; migrate `clusters/route.logic.ts` off `legs_v1`→`legs_v2`; rename `unrecognised-underliers` alias `execution_timestamp`→`anchor_ts`; keep `route.logic.ts` ORDER BY `execution_start` default with cursor/`latestExecutionStart` derived from the same anchor. Tests in each route's `__tests__`.

- [ ] Test each route's logic under the anchor param; cursor coherence test. Run `npm test`. Commit per route-group.

### Task 5.3: Phase 5 gate → `npm test` green. Commit.

---

## Phase 6 — Frontend (types, formatter, columns, filters, NYC unification)

### Task 6.1: Types + delta formatter

**Files:** Modify `.../usd-swaps-tape-v2/types/trade.types.ts`, base `sofr-swaps-tape/types/trade.types.ts`, `swaptions-tape/types/trade.types.ts` (wire the dormant `event_timestamp`); Add `formatTimestampDelta(execIso, eventIso): string` to `.../usd-swaps-tape-v2/utils/format.ts` (`+3d 04:12` / `live` / `unknown`, NYC). Test `.../__tests__/format.test.ts`.

- [ ] Test: `formatTimestampDelta` cases (positive, null→`live`, missing→`unknown`). Run `npm test`. Commit.

### Task 6.2: Second column + delta chip + leg/mobile parity + NYC fix + delta filter

**Files:** Modify `.../TradeTapeTable/columns.tsx` (second timestamp column + delta chip), `LegsSubTable.tsx` (per-leg event + delta; UTC→NYC), `MobileTradeCards.tsx`, `filter-utils.ts` (`TIMESTAMP_FILTER_FIELDS` + numeric delta candidate path), `RowBadges.helpers.ts` (optional lag badge). Tests in `__tests__`.

- [ ] Tests for column render + filter. Run `npm test`. **Chrome MCP visual verify** on the local dashboard. Commit.

### Task 6.3: Phase 6 gate → `npm test` green + Chrome MCP screenshot. Commit.

---

## Phase 7 — Monitoring

### Task 7.1: Lag + coverage panel

**Files:** Modify `SDRUtils/_swappulse_scripts/_tape_monitoring_v2.py` (add daily median/p95 `report_lag_seconds`, late-report rate, late-amendment count, alpha-join coverage ratio to `arbs_usd_swap_tape_quality_daily_v2`); Test `tests/sdr/test_tape_monitoring_lag.py`.

- [ ] Test: monitoring frame includes the new metrics computed from synthetic rows. Run fast gate. Commit.

---

## Phase 8 — Backfill (STAGED, not executed) + docs

### Task 8.1: Backfill runbook + guard wiring

**Files:** Create `docs/superpowers/plans/2026-07-17-sdr-timestamp-backfill-runbook.md`; ensure the re-ingest path calls `_assert_risk_populated` + the new timestamp-invariant assertions; the reconciliation report generator.
**Do NOT execute** the destructive prod re-ingest. Document: bump both cache versions → off-hours chunked re-ingest → reconciliation report → flip analytics anchor per coverage gate.

- [ ] Write runbook. Commit.

### Task 8.2: Update SDRUtils/CLAUDE.md Timestamps section

**Files:** Modify `SDRUtils/CLAUDE.md` (document `event_timestamp` + deltas as first-class persisted columns; the anchor rule; cache-version rule reminder).

- [ ] Update + commit.

---

## Self-review (spec coverage)

- Spec §5.1 → Phase 1; §6 alpha-join + reconciliation → Tasks 2.2, 7.1, 8.1; §7 anchor → Phase 3; §8 schema → Phase 4; §9 API → Phase 5; §10 frontend → Phase 6; §11 monitoring → Phase 7; §12 EMIR guard → `event_timestamp_granularity` col (Tasks 1.1/4.1); §13 backfill → Phase 8 (staged). All spec sections mapped.
- Delta/format decisions, cache bumps, invariants → Global Constraints + Tasks 2.3/4.1/4.2.
