# SDRUtils Area Guide

Scope: enrichment pipeline for DTCC-backed SDR analytics against CFTC
Part 43/45 v3.1 Tech Spec.

## Column vocabulary

After the 2026-04-24 remediation (design:
[`docs/plans/2026-04-24-sdr-compliance-remediation-design.md`](../docs/plans/2026-04-24-sdr-compliance-remediation-design.md)),
the enrichment pipeline materializes three families of signals that
every downstream aggregator must read from — never reconstruct by
re-parsing raw SDR fields.

### Economic-vs-Admin matrix (`ec_*` / `economic_*`)

Produced by [`SDRUtils/core/economic_classification.py`](core/economic_classification.py).
One `classify_event` call per row; every aggregator reads the booleans.

- `economic_class` — coarse enum: `ECONOMIC_FLOW`, `ECONOMIC_UNWIND`,
  `ECONOMIC_AMENDMENT`, `RESTATEMENT`, `ADMINISTRATIVE`, `VALUATION`,
  `ERROR`, `ERROR_RECOVERY`, `UNKNOWN`.
- `contributes_to_flow`, `_volume`, `_pnl`, `_pnl_as_delta` — gates.
- `on_p43` — Part 43 public-tape visibility per Appendix F.
- `economic_class_reason` — text citation.

**Rule**: a new aggregator MUST filter on `contributes_to_flow` (or
the appropriate gate); do NOT filter on raw `event_action` /
`event_type` / `lifecycle_type`.

### Lifecycle (`lc_*`)

Produced by [`SDRUtils/core/lifecycle_v2.py`](core/lifecycle_v2.py).

- `lc_n_events_economic` — economic-chain count (VALU/MARU excluded).
- `lc_n_valuation_events` — valuation chain count.
- `lc_was_amended` — MODI with Amendment=True.
- `lc_was_null_filled` — MODI with Amendment=False (post-price backfill).
- `lc_was_scheduled_amortization` — MODI that advances notional
  schedule; neither amendment nor null-fill.
- `lc_has_economics_change` — any ECONOMICS_FIELDS delta.
- `state_machine_violation` + `violation_reason` — transitions that
  break Figure 1/2 (e.g. `MODI_ON_ERRORED_WITHOUT_REVI`). Permissive
  per design D4: we log, never silently coerce.

### Phase 5 structural

- `schedule_truncated` / `schedule_row_count` / `schedule_notional_series`
  — §43.4(d) first-10-row truncation signals.
- `missing_required_fields` — [#115] Collateralisation category ->
  Appendix E validator output.
- `cap_band_violation` — §43.4(f) IRS cap schedule check.
- `rc_timeline_json` — per-UTI reporting-counterparty history.
- `other_payment_ufro` / `_uwin` / `_pexh` — [#57]-[#62] decomposition.
- `frequency_anomaly` — N4 SOFR-OIS reset mismatch.
- `d2_missing` — CORR/EROR/TERM/REVI/MODI(Amend=True) without [#2]
  Original Dissemination Identifier.

### Timestamps

Three CFTC Part 43/45 timestamps are first-class + persisted per row
(2026-07-17 exec-vs-event integration; design in
[`docs/superpowers/specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md`](../docs/superpowers/specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md)).

- `execution_timestamp` (#96) — economic trade time; immutable per UTI.
- `event_timestamp` (#30) — reported-event time; invariant `>= execution`.
  Read at classify time (swaps: real Execution Timestamp; swaptions/capfloors
  de-conflated — fall back to Event when Execution is missing, flagged).
- `original_execution_timestamp` — the chain's first-NEWT execution
  (within-chain lineage via `lc_original_execution_timestamp`), else the row's
  own execution. `original_execution_source` ∈ `newt|lineage|fallback`.
- `report_lag_seconds` = event − execution (≥0) — the "execution vs event"
  delta. `alpha_lag_seconds` = execution − original (≥0).
- `clearing_accepted_timestamp` — NULL except on β/γ NEWT-CLRG rows.
- Package rollups: `event_start`/`event_end`, `max/median_report_lag_seconds`,
  `late_report` (a leg lag over `config.LATE_REPORT_THRESHOLD_SECONDS`).
- **Rule**: FOMC proximity, novation-pair matching, and intraday curve
  snapshots bucket on `original_execution_timestamp` (execution fallback).
  `event_timestamp` + the deltas are transparency columns — NEVER bucket
  economic volume/DV01 on event time by default.
- **Cache**: changing this timestamp family's output bumps BOTH
  `TRADE_TAPE_CACHE_VERSION` and `DETECTION_CACHE_VERSION`. `event_timestamp`
  is NOT backfillable from the tape — historical coverage needs re-ingest
  (runbook: `docs/superpowers/plans/2026-07-17-sdr-timestamp-backfill-runbook.md`).

## Database cutover (Phase 4)

- Write target: `arbs_usd_swap_tape_{packages,legs,display}_v2`.
- `_v1` tables/view are frozen (writes revoked) as the rollback target.
- Dashboard reads via `TAPE_DISPLAY_VIEW` constant in
  [`route.logic.ts`](dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts).
  Rollback: flip constant to `_v1`, redeploy. No rebuild needed.
- `_v1` drop is gated on Phase 6 sign-off criteria (§6.3 of the
  implementation plan).

## Cache

[`SDRUtils/analytics/trade_tape.py`](analytics/trade_tape.py) owns a
pickle cache at `notebooks/sdr/_cache/trade_tape/`. Any change that
shifts enrichment output MUST bump `TRADE_TAPE_CACHE_VERSION`; the
cache key also fingerprints action/event/amendment so synthetic test
fixtures don't collide on hashes.

## Monitoring

[`_tape_monitoring_v2.py`](_swappulse_scripts/_tape_monitoring_v2.py)
creates `arbs_usd_swap_tape_quality_daily_v2` — daily time series of
state_machine_violation, cap_band_violation, frequency_anomaly,
missing_required_fields rate, d2_missing, and matrix class
distribution. Grafana dashboards alert on drift.

## What NOT to do

- Don't filter aggregators on raw `action_type` / `event_type` — use
  `economic_class` + `contributes_to_*`.
- Don't treat VALU/MARU as lifecycle events — use
  `lc_n_events_economic`.
- Don't parse notation-less numeric fields (price/spread) — pass them
  through `parse_notation_scalar` first.
- Don't re-enable strike-based option classification without pairing
  with `parse_notation_scalar` per [#64] Strike price notation.
- Don't drop `_v1` tables without the Phase 6 sign-off checklist
  complete.
- Don't parse raw SDR numerics (`Package transaction price`, `Other
  payment amount`, …) with bare `pd.to_numeric` — they arrive as strings
  with thousands separators and `;` multi-values. Use `numeric_like`
  ([`SDRUtils/packages/ptp_grouper.py`](packages/ptp_grouper.py)) or
  `_coerce_numeric_like`.
- Don't call `df.get(col)` and treat the result as a Series — pandas
  returns `None` for missing columns. Always pass a Series default:
  `df.get(col, pd.Series(index=df.index, dtype=...))`.
- Don't change detector *output* (columns or values) without bumping the
  detection cache version (see `DETECTION_CACHE_VERSION` in
  [`SDRUtils/products/usd/usd_swaps.py`](products/usd/usd_swaps.py)) AND
  `TRADE_TAPE_CACHE_VERSION`.
