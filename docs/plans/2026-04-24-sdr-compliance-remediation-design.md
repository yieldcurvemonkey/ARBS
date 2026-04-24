# SDR Pipeline Compliance Remediation — Design

**Date**: 2026-04-24
**Owner**: @yieldcurvemonkey
**Status**: Draft for review
**Companion**: [2026-04-24-sdr-compliance-remediation-implementation.md](./2026-04-24-sdr-compliance-remediation-implementation.md)

---

## 1. Summary

A compliance audit of the DTCC-backed SDR analytics pipeline against CFTC Part 43/45 v3.1 Tech Spec surfaced 10 BLOCKERs, 13 HIGHs, and a long tail of MEDIUM/NIT findings. The central failure mode: the pipeline does not systematically distinguish **economic** events (that change market risk between counterparties) from **administrative** events (clearing novation, SDR transfer, post-price backfill, compression, allocation, mirror swaps, inter-affiliate). Every high-impact flow/PnL/volume signal consumed by usd-swaps-tape-v2 is affected.

This doc defines:
- a three-layer refactor (primitives → lifecycle → classification) plus a consumer cutover,
- a canonical **Economic-vs-Admin matrix** as the single source of truth for every aggregator,
- schema and data-model changes required to surface that classification to the dashboard and analytics layers,
- cross-cutting design decisions and their resolutions.

Implementation is sequenced in six phases over the companion implementation doc.

## 2. Background

### 2.1 What's broken

Concrete examples the audit captured:

- **Clearing triple-count** ([#100], [Example 6], §45.8(i)) — one cleared swap becomes three SDR rows (α TERM-CLRG + β NEWT-CLRG + γ NEWT-CLRG). No dedup. Volume inflates 3× on cleared flow. [SDRUtils/analytics/trade_tape.py:516-559](../../SDRUtils/analytics/trade_tape.py)
- **Compression TERMs as unwinds** (§43.2, [Example 7]) — LCH/CME nightly compression cycles emit large TERM bursts with `Event type=COMP`. Flow aggregators filter on `event_type=='TERM'` without excluding compression. Every cycle reads as large dealer unwind. [SDRUtils/analytics/flow.py:30-125](../../SDRUtils/analytics/flow.py)
- **Event-vs-Execution timestamp conflation** (§43.3(a)(4), §43.5) — ingest is wired to `Event timestamp` as the bucketing key ([SDRUtils/data/builder.py:383,446,1002,1152](../../SDRUtils/data/builder.py)). For post-priced and block trades, P43 arrival lags execution by 15min–24 business hours. Every intraday curve snapshot, FOMC-window filter, and auction-timing analytic is misaligned.
- **Package-spread notation ignored** ([#52]: 1=monetary/3=decimal/4=bps) — pipeline reads the spread value without the notation. A 257 bps package spread is compared to a 0.01 decimal gate and rejected; a 0.0257 decimal spread is accepted as reasonable. [SDRUtils/products/usd/usd_swaps.py:498-500](../../SDRUtils/products/usd/usd_swaps.py)
- **All-9s sentinels flow through as real numbers** — `9.9999999999` at notation=3 is the canonical "decimal unknown" sentinel; pipeline treats it as a real price. Matched-maturity package aggregates read ~1e10. [SDRUtils/core/parsing.py:34-57](../../SDRUtils/core/parsing.py)
- **VALU/MARU counted as lifecycle events** — `lc_n_events = len(chain)` includes daily valuation rows, inflating event counts by 250+/year per open trade. Any `is_new_risk` or staleness heuristic using `lc_n_events ≤ 1` fails after day 1. [SDRUtils/core/lifecycle_v2.py:118](../../SDRUtils/core/lifecycle_v2.py), [SDRUtils/core/lifecycle.py:351-352](../../SDRUtils/core/lifecycle.py)
- **Amendment indicator signal computed but not consumed** — `was_economically_modified` vs `was_null_filled` is set correctly in [SDRUtils/core/lifecycle_v2.py:63-68](../../SDRUtils/core/lifecycle_v2.py) but the resulting `lc_was_amended` / `lc_was_null_filled` columns are not in the tape schema, not in the display view, not read by the dashboard. Post-priced price backfills (Amendment=False, admin-only) count as intraday economic amendments.

### 2.2 Why this is the right framing

The spec separates economic events from plumbing:
- §43.2 explicitly excludes compression, 100%-owned inter-affiliate, DCO default-management, and mirror swaps from "publicly reportable swap transaction".
- §45.1 defines "open swap" by terminal-state machine, not by row count.
- §45.4(b)/(c), §45.8(g)/(i), §45.10(d) describe a lifecycle where administrative events preserve UTI and net-zero market risk.

The pipeline currently treats every row as independently significant. The refactor re-centers everything on a classification that every aggregator reads from a single source.

## 3. Goals / Non-goals

### Goals

1. **Correctness**: every aggregator (flow, volume, PnL, new-risk, FOMC bucketing) respects the Economic-vs-Admin matrix.
2. **Single source of truth**: one function, `classify_event(...)`, produces columns consumed by every aggregator. No per-aggregator special cases.
3. **Dashboard parity then replacement**: usd-swaps-tape-v2 visibly switches to corrected aggregates with a clean cutover (no parallel-run window per product direction).
4. **Defensive data layer**: sentinels masked, notations inspected, timestamps tz-aware, schedules parsed as arrays.
5. **State machine legal per Figure 1/2**: EROR→REVI→MODI enforced; illegal transitions logged, never silently coerced.

### Non-goals

- Non-IR asset classes (CR/EQ/FX/CO).
- Second SDR source (ICE, UTI-SDR, etc.). DTCC only, per product.
- Notebook migrations in [notebooks/sdr/](../../notebooks/sdr/) (per product).
- An uncapped P45 integration — remains a separate workstream.
- A parallel-run `_v1`/`_v2` display view. Full cutover per product direction.
- Portfolio-reconciliation / EOD-collateral dashboards (addressed at schema level in Phase 5 but consumer work is out of scope).

## 4. Design principles

**P1. Classify once, read everywhere.** The matrix is computed at enrichment time, materialized as columns, and read by every downstream aggregator. Duplicated logic per-consumer is how the current bugs accumulated.

**P2. Never silently coerce malformed data.** Illegal state transitions, missing required fields, and sentinel values all produce quality flags. Downstream decides whether to drop or include; the producer does not decide for them.

**P3. Separate valuation from lifecycle.** VALU/MARU do not belong in the same event chain as NEWT/MODI/TERM. They are EOD updates, counted separately.

**P4. Spec data element (#) is the schema of record.** Our internal column names map to spec fields. New columns derived from classification carry `ec_*` prefix; lifecycle columns keep `lc_*`; cross-day keep `xd_*`.

**P5. Bump, don't parallel-run.** Cache versions (`TRADE_TAPE_CACHE_VERSION`) and Postgres table suffixes (`_v2`) are incremented on each phase that changes schema. No code-level A/B fallbacks.

## 5. Architecture

### 5.1 Three-layer model

```
┌─────────────────────────────────────────────────────────┐
│  L0  Primitives:  parse_sdr_timestamp, parse_notation,  │
│                   parse_notional, parse_schedule,       │
│                   DAY_COUNT_TABLE, SENTINEL_MASKS       │
└────────────────────────────▲────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────┐
│  L1  Lifecycle:   replay_lifecycle_full,                │
│                   resolve_lifecycle_for_day,            │
│                   resolve_lifecycle_cross_day,          │
│                   LifecycleEvent, LifecycleSummary      │
│                   (adds valuation_chain, split from     │
│                    economic chain)                      │
└────────────────────────────▲────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────┐
│  L2  Classification:   classify_event(row) → ec_* cols  │
│                        Economic-vs-Admin matrix table   │
└────────────────────────────▲────────────────────────────┘
                             │
┌────────────────────────────┴────────────────────────────┐
│  Consumers:  trade_tape.compute, flow.py,               │
│              SDRDataBuilder curves,                     │
│              FlowHistoryGrid, TradeTapeTable            │
└─────────────────────────────────────────────────────────┘
```

Each layer depends only on the one below. No consumer reads raw SDR fields; they read `ec_*` / `lc_*` / `xd_*` columns or well-typed primitives.

### 5.2 Economic-vs-Admin matrix (canonical)

This table is the source of truth. It lives in `SDRUtils/core/economic_classification.py` and is the only place classification logic exists.

| Action×Event | kind | on_p43 | flow | volume | pnl | citation |
|---|---|---|---|---|---|---|
| NEWT-TRAD | ECONOMIC_FLOW | ✓ | ✓ | ✓ | ✓ | §43.2; [Ex 1] |
| NEWT-NOVA | ADMINISTRATIVE (CP rotation) | ✓ | ✗ | ✗ | ✗ | [Ex 4]; §45.8(g) |
| NEWT-CLRG (β, γ) | ADMINISTRATIVE | ✗ | ✗ | ✗ | ✗ | [Ex 6]; §45.8(i) |
| NEWT-ALOC | ADMINISTRATIVE | ✗ | ✗ | ✗ | ✗ | [Ex 11] |
| NEWT-EXER | ECONOMIC_FLOW | ✓ | ✓ | ✓ | ✓ | [App F] |
| NEWT-PTNG | ADMINISTRATIVE (SDR transfer) | ✗ | ✗ | ✗ | ✗ | §45.10(d); [Ex 13] |
| TERM-TRAD | ECONOMIC_UNWIND | ✓ | ✓ (−) | ✗ | ✓ | [Ex 3] |
| TERM-ETRM | ECONOMIC_UNWIND (full) | ✓ | ✓ (−1×) | ✗ | ✓ | [Ex 3]; [#31 fn] |
| TERM-NOVA | ADMINISTRATIVE (CP rotation) | ✓ | ✗ | ✗ | ✗ | [Ex 4] |
| TERM-CLRG (α) | ADMINISTRATIVE | ✓ | ✗ | ✗ | ✗ | [Ex 6]; §43.3(a)(5) |
| TERM-CLAL | ADMINISTRATIVE | ✗ | ✗ | ✗ | ✗ | [App F] |
| TERM-ALOC | ADMINISTRATIVE | ✗ | ✗ | ✗ | ✗ | [Ex 11] |
| TERM-COMP | ADMINISTRATIVE (compression, §43.2 exclusion) | ✗ | ✗ | ✗ | ✗ | §43.2; [Ex 7] |
| PRTO-PTNG | ADMINISTRATIVE (SDR transfer) | ✗ | ✗ | ✗ | ✗ | §45.10(d) |
| MODI-TRAD (Amend=True) | ECONOMIC_AMENDMENT | ✓ | ✓ (delta) | ✗ | ✓ (delta) | [#28] |
| MODI-TRAD (Amend=False) | ADMINISTRATIVE (null-fill / post-price backfill) | ✓ | ✗ | ✗ | ✗ | §43.3(a)(4) |
| MODI-NOVA (partial) | ADMINISTRATIVE | ✓ | ✗ | ✗ | ✗ | [Ex 5] |
| CORR | RESTATEMENT | ✓ | replace | ✗ | replace | [App F] |
| EROR | ERROR | ✓ | ✗ | ✗ | ✗ | §45.14 |
| REVI | ERROR_RECOVERY | ✓ | ✗ | ✗ | ✗ | §45.14; [Ex 2] |
| VALU | VALUATION | ✗ | ✗ | ✗ | ✗ | §45.4(c) |
| MARU | VALUATION | ✗ | ✗ | ✗ | ✗ | §45.4(c) |

The `kind` column drives a 6-valued enum. `flow`/`volume`/`pnl`/`on_p43` are derived booleans. Aggregators read the booleans, never the kind directly.

### 5.3 Data model changes

#### New columns at trade-tape layer (per leg and per package)

| Column | Type | Source | Purpose |
|---|---|---|---|
| `economic_class` | enum str | Matrix kind | Human-readable classification |
| `contributes_to_flow` | bool | Matrix | Flow aggregator gate |
| `contributes_to_volume` | bool | Matrix | Volume aggregator gate |
| `contributes_to_pnl` | bool | Matrix | PnL aggregator gate |
| `contributes_to_pnl_as_delta` | bool | Matrix | Distinguishes delta-PnL (amendments) from full-PnL (terminations) |
| `on_p43` | bool | Matrix | Documents P43 visibility; used by P43-reconciliation checks |
| `lc_was_amended` | bool | lifecycle_v2.was_economically_modified | Already produced; now projected |
| `lc_was_null_filled` | bool | lifecycle_v2.was_null_filled | Already produced; now projected |
| `lc_has_economics_change` | bool | lifecycle_v2.economics_changed | Already produced; now projected |
| `lc_n_events_economic` | int | Replaces `lc_n_events` semantic | Excludes VALU/MARU |
| `lc_n_valuation_events` | int | New | Count of VALU+MARU rows |
| `original_execution_timestamp` | ts (UTC) | Per NEWT event, excluding β/γ clearing acceptance | Event-study timing anchor |
| `clearing_accepted_timestamp` | ts (UTC) | Beta/gamma NEWT-CLRG raw execution_timestamp | Preserves clearing acceptance for audit |
| `schedule_truncated` | bool | Compared schedule-array length to 10 | Part 43 first-10-rows truncation signal |
| `schedule_row_count` | int | Length after `;`-split | Schedule visibility |
| `notional_source` | enum str | `{'p43_capped','p43_uncapped','p45'}` | Documents which feed the notional came from |
| `cap_band_violation` | bool | Cap vs original tenor mismatch per §43.4(f) | Compliance-audit signal |
| `state_machine_violation` | bool | Illegal transition per Figure 1/2 | Data-quality signal |
| `violation_reason` | str | Text reason | Diagnosis aid |

#### Primitives layer additions

- `SDRUtils/core/parsing.py`: `parse_sdr_timestamp(value) -> datetime` (UTC), `mask_sentinels(series, field_type)`, `parse_notation_scalar(value, notation)`, `parse_schedule(cell)` returning `list[...]`.
- `SDRUtils/core/conventions.py` (new): `DAY_COUNT_TABLE: dict[str, ql.DayCounter]` covering A001–A020 + NARR per [Appendix C].

#### Lifecycle layer changes

- `LifecycleSummary` gets `valuation_chain: list[LifecycleEvent]` and `economic_chain: list[LifecycleEvent]`. `chain` stays as the union for backwards-comp until Phase 6 removal.
- `flatten_lifecycle_summary` adds `lc_n_events_economic` and `lc_n_valuation_events`.
- `replay_lifecycle_full` validates transitions; emits `quality_flag` on EROR→MODI without REVI.
- `_enrich_event_type` gated on action prefix ∈ {NEWT, TERM, MODI} before setting `is_novation` / `is_compression` / `is_exercise_born` / `is_clearing_termination`.

#### Postgres / display-view changes

- New tables created alongside v1: `arbs_usd_swap_tape_packages_v2`, `arbs_usd_swap_tape_legs_v2`. The `_v1` tables are **not dropped**; they are frozen (writes revoked, reads preserved) and held as a rollback target per D7.
- Display view `arbs_usd_swap_tape_display_v2` created with the expanded projection. `arbs_usd_swap_tape_display_v1` remains in place, frozen.
- Dashboard API points at `_v2` unconditionally via a config constant `TAPE_DISPLAY_VIEW` (new) defaulted to `arbs_usd_swap_tape_display_v2`. Rollback path: flip the constant to `..._v1` and redeploy — single-line change. No in-code fallback branching.

## 6. Cross-cutting decisions (resolved)

| # | Decision | Resolution |
|---|---|---|
| D1 | Single `classify_event()` vs per-aggregator logic | **Single function**, columns materialized at enrichment time. Rationale: matrix correctness is testable as a table; duplicated logic per-consumer is exactly how the current bugs accrued. |
| D2 | Matrix location | **Python module** (`SDRUtils/core/economic_classification.py`) with typed dict. Not YAML — cells depend on other fields (Amendment indicator, post_priced, is_compression) that YAML can't express compactly. |
| D3 | Legacy cache handling | **Bump `TRADE_TAPE_CACHE_VERSION`** + rename Postgres tables to `_v2`. Existing mechanism at [SDRUtils/analytics/trade_tape.py:65](../../SDRUtils/analytics/trade_tape.py) is sufficient. Daily parquet cache at [SDRUtils/data/builder.py:615-650](../../SDRUtils/data/builder.py) is untouched — those are raw SDR, not enrichment. |
| D4 | Strict vs permissive state machine | **Permissive with quality flags**. §45.14 and the ISDA no-action letter both acknowledge out-of-order messages. Rejecting causes gaps; silently coercing causes invisible corruption. Middle path: accept, flag, let consumers decide. |
| D5 | Capped-notional representation | **Keep capped value + `notional_source` column**. Aggregators explicitly handle `'p43_capped'` — document as lower-bound in dashboard tooltips. Uncapped P45 integration deferred. |
| D6 | Schedule modeling | **Implement `;`-split parser for up to 10 rows as part of Phase 1** (M12). Distributional question (trades with >10 steps) becomes a Phase 5 investigation; answerable off existing DTCC data. |
| D7 | Dashboard cutover strategy | **Full rework; preserve v1 as rollback path.** No parallel-run — API points at `_v2` unconditionally after cutover. `_v1` tables and display view remain **frozen** (read privileges only, writes revoked, no ongoing ingest into them) for a defined retention window so we can revert by flipping the API back. `_v1` is only dropped after explicit sign-off once `_v2` is stable in production (see Phase 6 decommission criteria). |
| D8 | Non-dashboard consumers | **In scope**: [SDRUtils/analytics/flow.py](../../SDRUtils/analytics/flow.py) and [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py) migrate in Phase 4 (per product). [notebooks/sdr/](../../notebooks/sdr/) out of scope. |

## 7. Key risks

| Risk | Mitigation |
|---|---|
| Dashboard users see unexpected number changes on cutover day | Pre-ship an explainer doc describing expected movements on compression and clearing-heavy days; include "toggle to include administrative events" control in FlowHistoryGrid defaulted off. |
| Permissive state machine masks real data errors | `state_machine_violation` columns surface to a Phase 6 monitoring panel; alert on rate > baseline. |
| Matrix rows miss an Action×Event combo in real data | Phase 3 unit tests enumerate every combo observed in a 1-week DTCC slice; integration test fails if a row has `economic_class == None`. |
| Day-count mapping wrong for an A00x we haven't seen in USD | Phase 1 tests round-trip every A00x against QuantLib's canonical yearFraction for a known payload; deviation from known reference values blocks merge. |
| Full-rework cutover breaks a downstream consumer we didn't map | Phase 4 preparatory step: grep repo for `lifecycle_type`, `is_new_risk`, `is_unwind`, `is_compression_any` — every call-site must be on the cutover list. |

## 8. Open questions (remaining)

All initial open questions are resolved per product direction. One new question surfaced during design:

- **Q1**: Cutover ownership — who signs off on the day the `_v2` view replaces `_v1`? Product or engineering lead? Needed before Phase 4 ship.

## 9. Success criteria (summary)

- Every finding in the audit (B1–B10, H1–H13, M1–M12, N1–N7) is either (a) landed in a phase or (b) explicitly closed as not-applicable with justification.
- The 50-UTI reconstruction test (defined in the implementation doc) passes end-to-end: ingest → enrichment → tape → dashboard API.
- Compression cycles produce 0 flow; clearing novation contributes 1× (not 3×); post-priced MODI backfills contribute 0 flow delta; VALU spam does not inflate `lc_n_events_economic`.
- `FlowHistoryGrid` on a non-compression, non-clearing day is visually identical pre/post migration (proof of no over-correction).
- No aggregator in the repo reads raw `action_type`/`event_type` fields to make flow/volume/PnL decisions. All decisions route through `economic_class` + the `contributes_to_*` columns.
