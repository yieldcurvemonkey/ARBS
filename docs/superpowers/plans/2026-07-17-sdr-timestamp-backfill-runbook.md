# SDR Execution-vs-Event Timestamp — Backfill & Cutover Runbook

**Date**: 2026-07-17
**Owner**: @yieldcurvemonkey
**Status**: STAGED — do NOT run steps 3+ unattended
**Design**: [../specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md](../specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md)
**Plan**: [2026-07-17-sdr-execution-vs-event-timestamp-integration.md](./2026-07-17-sdr-execution-vs-event-timestamp-integration.md)

---

## Why this is a runbook, not a script

Populating `event_timestamp` and the report/alpha-lag columns for historical
rows requires re-running `run_usdswaps_pipeline` against raw SDR per prior day.
That **deletes + rewrites the remote Supabase prod tape** the dashboard reads
(memory: `project_usdswaps_tape_backfill`). It is destructive and outward-facing,
so it must be run **attended, off-hours, chunked, and guarded**. The forward
path (all code) is already merged on `feat/sdr-exec-vs-event-timestamp`; this
runbook covers only the data cutover.

## Pre-flight (already done in code — verify before running)

- [x] Cache versions bumped: `TRADE_TAPE_CACHE_VERSION = v22-exec-vs-event-timestamps`
      (`SDRUtils/analytics/trade_tape.py`) **and**
      `DETECTION_CACHE_VERSION = ptp16-exec-vs-event-timestamps`
      (`SDRUtils/products/usd/usd_swaps.py`). Without BOTH, stale cached
      day-frames lack `event_timestamp` and re-ingest silently writes NULLs.
- [x] Schema migration is additive/idempotent (`ADD COLUMN IF NOT EXISTS`),
      nullable, no default → a fast metadata-only ALTER on the ~1.3M-row table.
- [x] Migration markers added to `_LATEST_MIGRATION_COLS`
      (`ingest_usdswaps_tape.py`) so `ensure_schema()`'s short-circuit does not
      skip the new columns.
- [ ] Fast gate green on the branch:
      `conda run -n stir python -m pytest tests -m "not slow and not network and not db"`
      (2 pre-existing `test_stir_future_mdp_fixings.py` failures are unrelated).

## Step 1 — Apply the schema migration (SAFE, additive)

Runs the idempotent DDL (`TAPE_SCHEMA_SQL_V2`) via the ingest's
`ensure_schema()` against the live v2 DB. `ADD COLUMN IF NOT EXISTS` +
`CREATE OR REPLACE VIEW` are non-destructive (no data rewrite). New columns are
NULL until Step 3. Confirm `arbs_usd_swap_tape_display_v2` now exposes
`event_start`, `event_end`, `max_report_lag_seconds`, `median_report_lag_seconds`,
`late_report`, and that `information_schema.columns` shows the six new leg
columns. Build the new indexes `CONCURRENTLY` if the ALTER path does not.

Also apply the monitoring view: run `MONITORING_SQL_V2`
(`SDRUtils/_swappulse_scripts/_tape_monitoring_v2.py`) so
`arbs_usd_swap_tape_quality_daily_v2` gains the report-lag + alpha-coverage
columns.

## Step 2 — Smoke test on ONE day (bounded blast radius)

Re-ingest a single recent low-traffic day and inspect before committing to full
history:
- `event_timestamp` populated on essentially every leg (CFTC feed always
  carries #30); `event_timestamp_granularity = 'second'`.
- `report_lag_seconds >= 0`; `report_lag_invariant_violations` ~ 0 (a nonzero
  count means feed clock-skew beyond the 5s tolerance — investigate before
  proceeding).
- Package `late_report` set where `max_report_lag_seconds > 900`.
- `original_execution_source` distribution sane (mostly `newt`; some `lineage`
  on amendment chains; `fallback` only where lineage/execution missing).
- Dashboard `/usd-swaps-tape-v2` shows the new **Event** column with real
  values + report-lag chips → **this is the required Chrome MCP visual check**
  (memory: `feedback_chrome_mcp_before_push`). Verify light + dark, desktop +
  mobile card, and the expanded leg sub-table's per-leg event line.

## Step 3 — Full-history re-ingest (DESTRUCTIVE — attended only)

Run `run_usdswaps_pipeline` day-by-day over the target history window
(confirm the window — full v2 history, or a bounded recent span). For each day:
- Guard with `_assert_risk_populated` so a transient ERIS curve failure cannot
  publish all-NULL risk as "success" (the 07/06 incident; memory:
  `project_tape_null_risk_curve_hazard`).
- Run in an off-hours window; the dashboard reads prod live during the rewrite.
- Chunk + checkpoint so a mid-run failure is resumable without redoing the
  whole span.

## Step 4 — Reconciliation report (alpha-join coverage)

After re-ingest, read `arbs_usd_swap_tape_quality_daily_v2`:
`n_alpha_lineage / (n_alpha_lineage + n_alpha_fallback + n_alpha_newt)` per day.
Only trust `alpha_lag_seconds`-based signals for days whose lineage coverage
clears `config.ALPHA_JOIN_COVERAGE_GATE` (0.95). Below the gate, treat
`alpha_lag` as unreliable for that day. Note: the tape's bucketing anchor is
`COALESCE(original_execution, execution)`, which is safe at ANY coverage — this
gate governs only the alpha-lag *signal*, not the anchor.

## Step 5 — Monitoring & alerts

Point Grafana at the new `arbs_usd_swap_tape_quality_daily_v2` columns; alert on
rising `median_report_lag_seconds` / `p95_report_lag_seconds`, a spike in
`late_report_rows`, any `report_lag_invariant_violations`, and a drop in
alpha-join coverage.

## Rollback

The new columns are additive and nullable; to roll back the feature, revert the
display view's package-column SELECT and the frontend column (or simply ignore
the columns — they degrade to 'live'/'unknown' in the UI). No data rewrite is
needed to roll back; a `DROP COLUMN` is available but unnecessary.

## Deferred follow-ups (documented, not in this cutover)

- **API aggregation-anchor unification**: the aggregation routes still split
  between `COALESCE(original_execution*, execution*)` and raw `execution*`
  bucketing; `clusters` still reads frozen `legs_v1`; `unrecognised-underliers`
  aliases the coalesced value as `execution_timestamp`. Harmless today (original
  == execution for ~all rows) but should be unified + `clusters` migrated to
  `legs_v2` before the alpha-join makes the anchors diverge. Separate workstream.
- **Secondary-tape UI**: swaptions / capfloors / legacy SOFR now persist
  `event_timestamp` (leg grain) but have no delta rollups, API projection, or UI
  column yet — a follow-up mirroring the usd-swaps-tape-v2 UI.
- **Cross-UTI alpha-join depth**: the hot-path anchor uses the within-chain
  lifecycle original execution; deeper cross-UTI clearing/novation resolution
  (`SDRUtils/analytics/alpha_join.py`) is available as a reconciliation tool and
  can be promoted into ingest once its production coverage is measured.
