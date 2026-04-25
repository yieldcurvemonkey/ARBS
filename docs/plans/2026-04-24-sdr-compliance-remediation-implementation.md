# SDR Pipeline Compliance Remediation — Implementation Plan

**Date**: 2026-04-24
**Owner**: @yieldcurvemonkey
**Status**: Draft for review
**Companion**: [2026-04-24-sdr-compliance-remediation-design.md](./2026-04-24-sdr-compliance-remediation-design.md)

---

## 0. Overview

Six phases. Each phase is independently shippable, testable, and leaves the pipeline in a consistent state. Phase 1–3 are invisible to users; Phase 4 is the visible cutover; Phase 5–6 clean up the long tail.

| Phase | Theme | Findings addressed | User-visible? |
|---|---|---|---|
| 1 | Data-layer primitives | B3, B4, B5, H3, H6, H8 (narrowed), M12 | No |
| 2 | Lifecycle state machine | B7, B8, H4, H5, H13, M9, M11 | No (schema adds only) |
| 3 | Classification layer (new) | N/A — foundation for Phase 4 | No |
| 4 | Aggregator cutover (full v1 → v2) | B1, B2, B6, B9, H1, H2, H9, H10, H11, H12 | **Yes** |
| 5 | Cross-cutting structural | B10, H7, M1, M2, M3, M4, N4 | Minor |
| 6 | Hygiene, NITs, monitoring | M5 (close), M7, M8, N1–N7 | No |

---

## Phase 1 — Data-layer primitives

### 1.1 Findings

- **B3** Execution vs Event timestamp conflation — [SDRUtils/products/usd/usd_swaps.py:847-849](../../SDRUtils/products/usd/usd_swaps.py), [SDRUtils/data/builder.py:383,446,1002,1152](../../SDRUtils/data/builder.py), [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py:377,1008](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py)
- **B4** Package-transaction spread notation not inspected — [SDRUtils/products/usd/usd_swaps.py:498-500](../../SDRUtils/products/usd/usd_swaps.py)
- **B5** All-9s sentinels flow through — [SDRUtils/core/parsing.py:34-57](../../SDRUtils/core/parsing.py)
- **H3** Day count [#53] / Appendix C mapping absent — [SDRUtils/config.py:88,106](../../SDRUtils/config.py), [SDRUtils/core/dates.py:202](../../SDRUtils/core/dates.py)
- **H6** Curve builder `ts_col` defaults to Event — [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py:377,1008](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py)
- **H8** (narrowed) Naive datetime in downstream — [SDRUtils/core/lifecycle.py:450-455](../../SDRUtils/core/lifecycle.py)
- **M12** Semicolon-delimited schedule fields — new finding from raw-data pass

### 1.2 Deliverables

**New module**: `SDRUtils/core/primitives/` (or single file if layout prefers) exporting:

```python
# Sentinel constants and masking
PRICE_SENTINEL = 99999.9999999999999
SPREAD_DECIMAL_SENTINEL = 9.9999999999
SPREAD_BPS_SENTINEL = 99999
PACKAGE_PRICE_SENTINEL = 99999.9999999999999

def mask_sentinels(series: pd.Series, field_type: Literal['price','spread_decimal','spread_bps','package_price']) -> pd.Series:
    """Return series with sentinel values replaced by NaN."""

# Notation-aware parsing (covers [#49], [#52], [#75], [#77])
def parse_notation_scalar(value: float, notation: int | float) -> float:
    """
    notation == 1 → monetary; return as-is (caller must pair with currency).
    notation == 3 → decimal; return as-is.
    notation == 4 → bps; return / 10000.
    """

# Day count (Appendix C)
DAY_COUNT_TABLE: dict[str, ql.DayCounter] = {
    "A001": ql.Thirty360(ql.Thirty360.BondBasis),
    "A004": ql.Actual360(),
    "A005": ql.Actual365Fixed(),
    "A006": ql.ActualActual(ql.ActualActual.ICMA),
    "A007": ql.Thirty360(ql.Thirty360.EurobondBasis),
    "A008": ql.ActualActual(ql.ActualActual.ISDA),
    # ... full A001-A020
    "NARR": None,  # narrative, requires manual mapping
}

def resolve_day_counter(code: str | None, fallback: ql.DayCounter) -> ql.DayCounter:
    """Resolve Appendix C code; fallback on NARR or missing."""

# Timestamp (tz-aware)
def parse_sdr_timestamp(value: Any) -> pd.Timestamp:
    """Coerce to UTC; raise on non-UTC naive; coerce Z-suffix correctly."""

# Schedule (semicolon-delimited multi-value)
def parse_schedule(cell: Any) -> list[float] | list[str]:
    """Split `;` into array. Empty cell → []. Single value → [v]."""

# Notional with capped flag (already exists at parsing.py:16-31, keep)
def parse_notional(cell: Any) -> tuple[float, bool]:
    """Return (value, is_capped). Strips '+' suffix."""
```

**Primary changes** to existing code:
- `SDRUtils/core/parsing.py`: `to_float` wraps `mask_sentinels` calls for price/spread/package fields.
- `SDRUtils/products/usd/usd_swaps.py:498-500`: read notation columns and route through `parse_notation_scalar`.
- `SDRUtils/products/usd/usd_swaps.py:847-849`: **uncomment** the Execution Timestamp line; delete the Event timestamp derivation.
- `SDRUtils/data/builder.py:383,446,1002,1152`: default `ts_col` to `"Execution Timestamp"`.
- `MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py:377,1008`: same default change.
- `SDRUtils/core/lifecycle.py:450-455`: replace naked `.to_pydatetime()` with `parse_sdr_timestamp`.
- `SDRUtils/core/dates.py:202`: accept day-count code from row; use `resolve_day_counter`.

### 1.3 Schema additions (Phase 1)

- `notional_source` (enum) — `{'p43_capped','p43_uncapped','p45'}`. Populated by `parse_notional` + ingest-layer tagging.
- `is_notional_capped` (bool) — already exists at [SDRUtils/core/classification.py:76](../../SDRUtils/core/classification.py). Keep.

### 1.4 Tests

- `tests/core/test_primitives.py` — property tests over sentinels, notations, timestamps, schedules.
- `tests/core/test_day_count.py` — round-trip yearFraction for A001, A004, A005, A006, A007, A008 against known reference values.
- `tests/data/test_builder_tscol.py` — assert default `ts_col == "Execution Timestamp"` in both `fetch_historical_reports` and `fetch_intraday_reports`.
- `tests/products/usd/test_package_spread_notation.py` — 257 at notation=4 → 0.0257; 0.0257 at notation=3 → 0.0257; 9.9999999999 at notation=3 → NaN.
- `tests/core/test_schedule_parse.py` — 10-element schedule from `sdr_example.csv` row 1 parses to `list[float]` length 10.

### 1.5 Migration

- Primitives themselves: additive, no migration.
- **Timestamp flip** (B3/H6): existing enrichment caches and Postgres tables have `execution_start` derived from Event timestamp. Must invalidate. Bump `TRADE_TAPE_CACHE_VERSION` from `"v1"` to `"v2-p1"`. Rebuild Postgres tables from scratch.
- Note: daily raw-SDR parquet files under `notebooks/sdr/_cache/` do not need rebuilding — they are untouched pre-enrichment data.

### 1.6 Rollout / rollback

- Feature-flag not required (Phase 1 is internal). Ship in one release.
- Rollback: revert the commits. Bump `TRADE_TAPE_CACHE_VERSION` back to `"v1"`; rebuild tables.

### 1.7 Gate

All Phase 1 tests pass + one week of DTCC data reprocesses end-to-end without exceptions + spot-check: sample trade from `sdr_example.csv` row 3 (`2293643764000000101`) produces identical enrichment pre/post for non-capped, non-post-priced cases.

---

## Phase 2 — Lifecycle state machine

### 2.1 Findings

- **B7** VALU/MARU counted as lifecycle events — [SDRUtils/core/lifecycle.py:351-352](../../SDRUtils/core/lifecycle.py), [SDRUtils/core/lifecycle_v2.py:118](../../SDRUtils/core/lifecycle_v2.py)
- **B8** Fallback `lifecycle_map` missing REVI/EROR/VALU/MARU/ALOC/NOVA/COMP/PTNG — [SDRUtils/analytics/trade_tape.py:447-457](../../SDRUtils/analytics/trade_tape.py)
- **H4** Event-type flags applied to non-lifecycle actions — [SDRUtils/analytics/trade_tape.py:516-559](../../SDRUtils/analytics/trade_tape.py)
- **H5** MODI-post-EROR without REVI — [SDRUtils/core/lifecycle.py:329-336](../../SDRUtils/core/lifecycle.py)
- **H13** Schedule step → phantom amendment — [SDRUtils/core/lifecycle_v2.py:63-67,161-181](../../SDRUtils/core/lifecycle_v2.py)
- **M9** MODI Amendment=None warning — [SDRUtils/core/lifecycle.py:205-215](../../SDRUtils/core/lifecycle.py)
- **M11** Intraday dedup key inconsistent — [SDRUtils/data/builder.py:1071](../../SDRUtils/data/builder.py)

### 2.2 Deliverables

**Dual-chain lifecycle**: `LifecycleSummary` gets `economic_chain` and `valuation_chain`. `chain` remains for backward compat during Phase 2; removed in Phase 6.

```python
@dataclass
class LifecycleSummary:
    economic_chain: list[LifecycleEvent] = field(default_factory=list)
    valuation_chain: list[LifecycleEvent] = field(default_factory=list)
    chain: list[LifecycleEvent] = field(default_factory=list)  # DEPRECATED; union; removed Phase 6
    # ...
```

`build_summary` routes events: `{VALU, MARU}` → `valuation_chain`; everything else → `economic_chain`.

`flatten_lifecycle_summary` emits:
```python
{
    "lc_n_events_economic": len(summary.economic_chain),
    "lc_n_valuation_events": len(summary.valuation_chain),
    "lc_n_events": len(summary.economic_chain),  # back-compat alias; removed Phase 6
    "lc_status": ...,
    "lc_was_amended": summary.was_economically_modified,
    "lc_was_null_filled": summary.was_null_filled,
    "lc_has_economics_change": summary.economics_changed,
    # ... existing fields
}
```

**Complete `lifecycle_map`** in [trade_tape.py:447-457](../../SDRUtils/analytics/trade_tape.py):

```python
lifecycle_map = {
    "NEWT": "NEW_TRADE",
    "TERM": "TERMINATION",
    "CORR": "CORRECTION",
    "MODI": "MODIFICATION",
    "REVI": "REVIVE",
    "EROR": "ERROR",
    "VALU": "VALUATION",
    "MARU": "MARGIN_UPDATE",
    # ALOC/NOVA/COMP/CLRG/PTNG handled via event_type axis — keep lifecycle_type for
    # action axis only
}
```

**Event-type flag gate** in `_enrich_event_type` (H4): wrap flag assignments in `action_prefix.isin({"NEWT", "TERM", "MODI"})` mask. VALU/MARU/CORR/EROR/REVI rows get `is_novation = False` unconditionally.

**State machine validator** (H5, M9):

```python
def validate_transition(prev_state: ResolvedState, action: str, event: Optional[str], amendment: Optional[bool]) -> QualityFlag | None:
    """Returns a QualityFlag if the transition violates Figure 1/2, else None."""
    if prev_state == "ERRORED" and action == "MODI":
        return QualityFlag("MODI_ON_ERRORED_WITHOUT_REVI")
    if prev_state == "TERMINATED" and action == "MODI":
        return QualityFlag("MODI_ON_TERMINATED")
    if action == "MODI" and amendment is None:
        return QualityFlag("MODI_AMENDMENT_NONE")  # warning, not error
    return None
```

`replay_lifecycle_full` calls `validate_transition` on every dispatch; accumulates flags on the `ResolvedTrade`; emits `state_machine_violation: bool` and `violation_reason: str` into flat columns.

**Intraday dedup alignment** (M11): change [builder.py:1071](../../SDRUtils/data/builder.py) from `drop_duplicates(subset=["report_slice", ts_col])` to `drop_duplicates(subset=["Dissemination Identifier"], keep="last")`. "Last" preserves the most recent slice's view of a disseminated message.

**Schedule step recognition** (H13): `build_summary` treats MODI with `amendment_indicator is False` AND matching `[#34 Effective date of the notional amount-Leg 1]` in the scheduled sequence as a schedule-step, NOT a null-fill. Introduce `is_schedule_step: bool` flag on `LifecycleEvent`; sets `was_null_filled = False` and `was_scheduled_amortization = True`.

### 2.3 Schema additions

- `lc_n_events_economic` (int)
- `lc_n_valuation_events` (int)
- `lc_was_amended` (bool)
- `lc_was_null_filled` (bool)
- `lc_has_economics_change` (bool)
- `lc_was_scheduled_amortization` (bool)
- `state_machine_violation` (bool)
- `violation_reason` (str)

### 2.4 Tests

Table-driven from [Appendix F]. One test per Action×Event combo:

```
test_NEWT_TRAD → lc_status=ACTIVE, is_new_risk=True
test_MODI_TRAD_Amend_True → was_economically_modified=True, was_null_filled=False
test_MODI_TRAD_Amend_False → was_null_filled=True, was_economically_modified=False
test_MODI_TRAD_Amend_None → violation_reason includes MODI_AMENDMENT_NONE
test_EROR_then_MODI → state_machine_violation=True
test_EROR_then_REVI_then_MODI → state_machine_violation=False
test_VALU_spam → lc_n_events_economic=1, lc_n_valuation_events=N
test_VALU_with_bogus_event_type_NOVA → is_novation=False
test_scheduled_amortization_MODI → was_null_filled=False, was_scheduled_amortization=True
```

Plus an integration test: process 1-week DTCC IR slice end-to-end; assert no row has `economic_class == None`; `lc_n_events_economic` distribution is sane (median 1).

### 2.5 Migration

Bump `TRADE_TAPE_CACHE_VERSION` to `"v2-p2"`. Rebuild Postgres tables (still `_v1` — no consumer cutover yet). Raw parquet cache untouched.

### 2.6 Gate

- All Appendix F unit tests pass.
- 1-week DTCC reprocess: 0 exceptions; rate of `state_machine_violation=True` below baseline TBD but < 0.1% of rows (sanity).
- `FlowHistoryGrid` and `TradeTapeTable` still function on the unchanged `_v1` tables — Phase 2 is schema-additive only.

---

## Phase 3 — Classification layer

### 3.1 Findings

None directly. Ships the foundation for Phase 4.

### 3.2 Deliverables

**New module**: `SDRUtils/core/economic_classification.py`

```python
from enum import Enum
from dataclasses import dataclass
from typing import Mapping

class EconomicKind(str, Enum):
    ECONOMIC_FLOW = "ECONOMIC_FLOW"
    ECONOMIC_UNWIND = "ECONOMIC_UNWIND"
    ECONOMIC_AMENDMENT = "ECONOMIC_AMENDMENT"
    RESTATEMENT = "RESTATEMENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    VALUATION = "VALUATION"
    ERROR = "ERROR"
    ERROR_RECOVERY = "ERROR_RECOVERY"

@dataclass(frozen=True)
class EconomicClassification:
    kind: EconomicKind
    contributes_to_flow: bool
    contributes_to_volume: bool
    contributes_to_pnl: bool
    contributes_to_pnl_as_delta: bool
    on_p43: bool
    reason: str  # e.g. "§43.2 compression exclusion"

# The canonical matrix. Keys are (action, event, amendment_bucket) where
# amendment_bucket is True/False/None — None means the cell is amendment-insensitive.
MATRIX: Mapping[tuple[str, str | None, bool | None], EconomicClassification] = {
    ("NEWT", "TRAD", None): EconomicClassification(
        kind=EconomicKind.ECONOMIC_FLOW,
        contributes_to_flow=True, contributes_to_volume=True,
        contributes_to_pnl=True, contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason="§43.2; [Example 1]"
    ),
    ("NEWT", "NOVA", None): EconomicClassification(
        kind=EconomicKind.ADMINISTRATIVE,
        contributes_to_flow=False, contributes_to_volume=False,
        contributes_to_pnl=False, contributes_to_pnl_as_delta=False,
        on_p43=True,
        reason="[Example 4]; §45.8(g) — CP rotation, no net risk change"
    ),
    # ... every matrix row from design §5.2
}

def classify_event(
    action: str,
    event: str | None,
    amendment_indicator: bool | None,
    *,
    post_priced: bool = False,
    is_compression: bool = False,
    prime_brokerage: bool = False,
    clearing_exception: str | None = None,  # AFFL, INTR, etc.
    is_clearing_alpha: bool = False,        # True for TERM-CLRG alpha; β/γ use NEWT-CLRG
) -> EconomicClassification:
    """
    Lookup matrix with overrides for:
    - prime_brokerage=True → ADMINISTRATIVE regardless (§43.3(a)(6))
    - clearing_exception=='AFFL' → ADMINISTRATIVE (§43.2 inter-affiliate)
    - MODI-TRAD Amendment=False → ADMINISTRATIVE (null-fill / post-price backfill)
    """
```

**Enrichment step** in [trade_tape.py](../../SDRUtils/analytics/trade_tape.py) adds a new `_enrich_economic_class` method, invoked after `_enrich_lifecycle`/`_enrich_event_type` but before aggregator-facing computations. Materializes columns:

- `economic_class` (str)
- `contributes_to_flow` (bool)
- `contributes_to_volume` (bool)
- `contributes_to_pnl` (bool)
- `contributes_to_pnl_as_delta` (bool)
- `on_p43` (bool)
- `economic_class_reason` (str)

**Helper** for aggregators:

```python
def filter_economic(df: pd.DataFrame, kind: Literal["flow","volume","pnl"]) -> pd.DataFrame:
    col = {"flow": "contributes_to_flow", "volume": "contributes_to_volume", "pnl": "contributes_to_pnl"}[kind]
    return df[df[col]]
```

### 3.3 Tests

- `tests/core/test_economic_classification.py`: one test per matrix row.
- Property test: `ADMINISTRATIVE` rows always have all four `contributes_*` booleans False.
- Integration test: 1-week DTCC slice, no row has `economic_class == None`.
- Golden file: reference enrichment of `sdr_example.csv` row-by-row classifications.

### 3.4 Migration

Bump `TRADE_TAPE_CACHE_VERSION` to `"v3-p3"`. Phase 3 adds columns; aggregators do not yet read them.

### 3.5 Gate

- All 21+ matrix rows covered.
- 1-week DTCC slice: no null `economic_class`; distribution sane (most rows `ECONOMIC_FLOW`, small % `ADMINISTRATIVE` and `VALUATION`).
- `TradeTape.compute` runtime regression < 10% (classification is O(n) pandas).

---

## Phase 4 — Aggregator cutover (full v1 → v2)

### 4.1 Findings

- **B1** Clearing triple-count
- **B2** Compression TERMs as unwinds
- **B6** Amendment-False MODI in flow (consumer-side wiring)
- **B9** `portfolio_code='TRANSACTIONLEVEL'` sentinel not handled
- **H1** Beta/gamma execution timestamp
- **H2** Partial novation residual double-count
- **H9** `is_new_risk` hard-coded on NEWT prefix
- **H10** RC-flip aggregation
- **H11** Prime-brokerage mirror filter
- **H12** AFFL inter-affiliate filter

### 4.2 Scope (per product D7/D8)

**Full rework, no parallel-run. `_v1` preserved as rollback path** (frozen, not dropped). In-scope consumers:

1. [SDRUtils/analytics/trade_tape.py](../../SDRUtils/analytics/trade_tape.py)
2. [SDRUtils/analytics/_tape_schema.py](../../SDRUtils/analytics/_tape_schema.py)
3. [SDRUtils/analytics/flow.py](../../SDRUtils/analytics/flow.py) (per D8)
4. [SDRUtils/analytics/compression.py](../../SDRUtils/analytics/compression.py)
5. [SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py](../../SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py)
6. [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py) (per D8)
7. Postgres: create `arbs_usd_swap_tape_{packages,legs,display}_v2` from expanded projection **alongside** existing `_v1`. Freeze `_v1` (see §4.11). Do not drop.
8. [SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts](../../SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts) — view resolution, column list.
9. [SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts) + `route.logic.ts` — point at `_v2`.
10. [SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx) — aggregation logic.
11. [SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/) — surface new optional columns (Amendment, Economic class).

**Out of scope** (per D8): [notebooks/sdr/](../../notebooks/sdr/) — unchanged.

### 4.3 Step-by-step cutover order

Schema-first to avoid broken intermediate states.

1. **Producer columns land** in `_tape_schema.py` + `trade_tape.py` (Phase 3 output consumed here for the first time).
2. **Ingest projection expanded** in `ingest_usdswaps_tape.py` LEG_COLUMNS + package columns.
3. **Postgres `_v2` tables created** from expanded projection, **alongside** existing `_v1` (no rename, no drop). Backfill from a 2-week window. Verify row counts match `_v1` (schema-additive means no row loss).
4. **Postgres `_v2` display view created** mirroring `_v1` but with new columns. `_v1` view remains.
5. **Python aggregators cut over** in one commit: `flow.py`, `trade_tape.py` internal helpers, `SDRDataBuilder.py` curve ingest. Each replaces hand-rolled filters with `filter_economic(df, ...)`. `is_new_risk` rewritten to consume `economic_class`. Novation-pair matcher (trade_tape.py:144-221) drops notional-equality gate in favor of Prior UTI.
6. **Ingest pipeline writes to `_v2` only.** Stop writes to `_v1`. `_v1` is now frozen at the pre-cutover state.
7. **Dashboard API points at `_v2`** via a new config constant `TAPE_DISPLAY_VIEW` in `route.logic.ts` (default `"arbs_usd_swap_tape_display_v2"`). No flag branching in the query code — the constant is the only lever.
8. **Dashboard column list updated** in `usd-swaps-tape-v2.ts` `COLUMNS` + `resolveDisplayView`. New fields exposed: `economic_class`, `lc_was_amended`, `lc_was_null_filled`, `original_execution_timestamp`, `clearing_accepted_timestamp`.
9. **FlowHistoryGrid aggregation rewritten**: filter on `contributes_to_flow`/`contributes_to_volume` before quadrant bucketing. Add "include administrative events" toggle defaulted off.
10. **TradeTapeTable columns extended**: add `economic_class` column (filterable), `lc_was_amended` indicator.
11. **Freeze `_v1` in Postgres** (revoke writes, keep reads). See §4.11 for the exact DDL. Do NOT drop.

### 4.4 Specific rewrites

**H1 — split execution timestamp**:
- Add producer columns: `original_execution_timestamp` (ts UTC), `clearing_accepted_timestamp` (ts UTC or NULL).
- For `NEWT-CLRG` rows with `lc_status == "ACTIVE"` AND `package_indicator == True` AND Prior UTI links to an alpha: `original_execution_timestamp = alpha.execution_timestamp`, `clearing_accepted_timestamp = this_row.execution_timestamp`.
- For all other rows: `original_execution_timestamp = execution_timestamp`, `clearing_accepted_timestamp = NULL`.
- Dashboard displays `original_execution_timestamp` in the "Exec" column. Tooltip shows `clearing_accepted_timestamp` when non-NULL.
- FOMC proximity and novation-pair matching consume `original_execution_timestamp`.

**H2 — novation-pair matcher**:
- Drop `if t_notional != n_row.get("notional", -1): continue` at [trade_tape.py:182](../../SDRUtils/analytics/trade_tape.py).
- Match instead on `Prior UTI` ↔ `Dissemination Identifier` linkage plus timestamp window.
- Partial novation: MODI-NOVA residual reduction on UTI A paired with NEWT-NOVA slice on UTI B linked by Prior UTI. Net flow contribution = 0.

**H9 — `is_new_risk` rewrite**:
```python
# Old at trade_tape.py:457
df["is_new_risk"] = action_prefix == "NEWT"

# New
df["is_new_risk"] = (
    df["economic_class"] == "ECONOMIC_FLOW"
) & (df["action_prefix"] == "NEWT")
```

**H10 — RC timeline**:
```python
# New helper in SDRUtils/core/rc_timeline.py
def build_rc_timeline(uti_group: pd.DataFrame) -> list[tuple[pd.Timestamp, str]]:
    """Per-UTI RC history respecting §45.8(g)."""
```
RC-keyed aggregations in `flow.py` consume the timeline, not the current-state RC.

**H11 — PB mirror exclusion**:
`classify_event` already handles this via `prime_brokerage` parameter. Wire [SDRUtils/products/usd/usd_swaps.py:958](../../SDRUtils/products/usd/usd_swaps.py) `Prime brokerage transaction indicator` into the classification call site.

**H12 — AFFL exclusion**:
`classify_event` handles via `clearing_exception` parameter. Ingest layer must populate from `[#11] Clearing exception` + `[#12] Clearing exception party`. If those fields are not yet extracted, add them in [_tape_schema.py](../../SDRUtils/analytics/_tape_schema.py).

### 4.5 Schema additions (Phase 4)

All the Phase 3 matrix-derived columns are now in the display view projection:
- `economic_class`, `contributes_to_flow`, `contributes_to_volume`, `contributes_to_pnl`, `contributes_to_pnl_as_delta`, `on_p43`, `economic_class_reason`
- `original_execution_timestamp`, `clearing_accepted_timestamp`
- `lc_was_amended`, `lc_was_null_filled`, `lc_has_economics_change`
- `lc_n_events_economic`, `lc_n_valuation_events`

### 4.6 Tests

**50-UTI reconstruction test** (see §7 below) runs end-to-end: raw SDR → enrichment → `_v2` tables → dashboard API response. Every test case must pass.

Specific aggregator tests:

- `test_clearing_alpha_beta_gamma_single_volume`: 1 alpha + 2 β/γ → volume = 1× notional, flow = 0.
- `test_compression_cycle_zero_flow`: 10-row LCH COMP cycle → flow = 0, volume = 0.
- `test_post_priced_backfill_zero_flow_delta`: NEWT-TRAD + MODI-TRAD Amend=False → flow delta = 0, `FlowHistoryGrid` shows single trade.
- `test_fomc_window_cleared_swap_original_exec`: cleared swap executed 14:30, accepted 16:45 → bucketed on 14:30.
- `test_partial_novation_net_zero`: MODI-NOVA (−3M) + NEWT-NOVA (3M) linked by Prior UTI → net flow = 0.
- `test_affl_inter_affiliate_excluded`: row with `Clearing exception = AFFL` → `contributes_to_flow = False`.
- `test_prime_brokerage_mirror_excluded`: row with `Prime brokerage indicator = True` → `contributes_to_flow = False`.

Dashboard-level:
- `FlowHistoryGrid` visual-diff test: non-compression, non-clearing day (e.g. a mid-week mid-month day) — output bytes identical pre/post (no over-correction).
- `FlowHistoryGrid` visual-diff test: known-compression day — flow drops by >= 80% after cutover.

### 4.7 Migration

- Bump `TRADE_TAPE_CACHE_VERSION` to `"v4-p4"`.
- Create `arbs_usd_swap_tape_{packages,legs,display}_v2` — do NOT drop or rename `_v1`.
- One-shot backfill from raw SDR parquet into `_v2` tables before the commit that flips the API.
- Freeze `_v1` via write-privilege revoke once `_v2` is verified live (see §4.11 runbook).
- Decommission of `_v1` is deferred to Phase 6 and requires explicit sign-off per the criteria in §6.3.

### 4.8 Rollout

**Single-release cutover** per D7. Sequence in one change window:
1. Deploy producer-side changes; create Postgres `_v2` alongside `_v1` (both live, `_v1` still receiving writes).
2. Backfill `_v2` from raw parquet; verify row counts + spot-check against `_v1` for non-compression non-clearing days.
3. Switch ingest pipeline to write `_v2` only. `_v1` stops receiving new rows.
4. Freeze `_v1` in Postgres (revoke writes). See §4.11.
5. Deploy dashboard pointing at `_v2` via `TAPE_DISPLAY_VIEW` constant.
6. Verify `FlowHistoryGrid` renders; verify `TradeTapeTable` pagination + filter work; smoke-test the API.
7. Monitor for 24h. Do **not** drop `_v1`.

Communications to dashboard users ahead of cutover: document expected deltas on compression days, clearing-heavy days, and post-priced flows. Surface "include administrative events" toggle to allow users to recover the legacy view if needed.

### 4.9 Rollback

Rollback is **one file edit + one redeploy**. See §4.11 for the runbook.

Recovery path if rollback is needed:
1. Edit `TAPE_DISPLAY_VIEW` constant in `route.logic.ts` from `"..._v2"` back to `"..._v1"`.
2. Redeploy dashboard.
3. `_v1` is frozen but readable — serves dashboard immediately, no rebuild required.
4. Investigate the failure, land a fix on a separate branch, re-attempt cutover when ready.

RPO = 0 (no data loss; `_v1` is frozen at last pre-cutover ingest). RTO ≤ one redeploy cycle.

**The pre-cutover snapshot step from earlier drafts is obsolete** — `_v1` itself is the rollback target. Do not drop `_v1` in Phase 4 under any circumstance.

### 4.10 Gate

All 50 reconstruction UTIs pass. Compression-day and clearing-day deltas match expectations (documented threshold). Non-compression day is byte-identical on `FlowHistoryGrid`. No dashboard errors for 24h post-cutover. `_v1` tables exist, are read-accessible, and have writes revoked.

### 4.11 v1 preservation & rollback runbook

**Goal**: keep `_v1` readable and consistent for a retention window so that flipping `TAPE_DISPLAY_VIEW` back to `_v1` restores the previous dashboard behavior without rebuild.

#### Freeze procedure (run once, immediately after §4.8 step 3)

```sql
-- Revoke all write privileges on v1 objects.
-- Keep SELECT for the dashboard role so rollback works instantly.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    arbs_usd_swap_tape_packages_v1,
    arbs_usd_swap_tape_legs_v1
FROM PUBLIC, <ingest_role>, <application_role>;

-- Also revoke on the v1 display view if it's a materialized view.
-- For regular views, no privilege change needed.

-- Document the freeze date (tag comment visible in pg_description).
COMMENT ON TABLE arbs_usd_swap_tape_packages_v1
  IS 'FROZEN 2026-04-24 — v2 cutover. Rollback target until Phase 6 sign-off.';
COMMENT ON TABLE arbs_usd_swap_tape_legs_v1
  IS 'FROZEN 2026-04-24 — v2 cutover. Rollback target until Phase 6 sign-off.';
```

#### Rollback procedure (only if cutover fails)

1. In [SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.logic.ts), change:
   ```typescript
   export const TAPE_DISPLAY_VIEW = "arbs_usd_swap_tape_display_v2";
   ```
   back to:
   ```typescript
   export const TAPE_DISPLAY_VIEW = "arbs_usd_swap_tape_display_v1";
   ```
2. Redeploy the dashboard.
3. Verify `FlowHistoryGrid` and `TradeTapeTable` render.
4. File a defect ticket linking the original cutover PR with the failure mode observed.

#### What the rollback does NOT restore

- Enrichment caches under `notebooks/sdr/_cache/trade_tape/` are keyed by `TRADE_TAPE_CACHE_VERSION`. Rolling the view back does not invalidate those. If you need to rebuild the `_v1` enrichment from scratch, revert `TRADE_TAPE_CACHE_VERSION` to its pre-cutover value or delete the cache directory.
- Python aggregators (`flow.py`, `SDRDataBuilder.py`) will still consume `_v2` semantics internally. Rolling back the view only restores the dashboard surface. For a full Python rollback, revert the Phase 4 producer commit too.
- `_v2` tables remain populated and readable; no cleanup needed on rollback.

#### Retention & decommission criteria (fires in Phase 6)

`_v1` is dropped only when ALL of the following hold:
- `_v2` has been live for at least 30 calendar days without a rollback.
- No alerting incident on `economic_class` distribution or `state_machine_violation` rate in that window.
- Dashboard user sign-off captured in a short memo in `docs/plans/`.
- No open queries or jobs reference `_v1` (verify via `pg_stat_statements` grep over a 7-day window).

The Phase 6 deliverable includes the DDL to drop `_v1` once these criteria are confirmed.

---

## Phase 5 — Cross-cutting structural

### 5.1 Findings

- **B10** Public-tape first-10-schedule-rows truncation — [SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py](../../SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py), [SDRUtils/analytics/trade_tape.py](../../SDRUtils/analytics/trade_tape.py)
- **H7** Collateralisation category required-fields — [#115] Appendix E
- **M1** Cap-band validation by original tenor — §43.4(f)
- **M2** Partial-unwind delta vs prior state — [SDRUtils/core/lifecycle_v2.py:161-181](../../SDRUtils/core/lifecycle_v2.py)
- **M3** UFRO/UWIN/PEXH cash aggregation — [#57-62]
- **M4** D2-chain validation — [Appendix A: D1-D4]
- **N4** Frequency anomaly detection

### 5.2 Deliverables

- `SDRUtils/core/schedule_model.py` — full schedule array consumer with `schedule_truncated`, `schedule_row_count` signals; depends on `parse_schedule` from Phase 1.
- `SDRUtils/core/collateral_required.py` — registry `COLLATERAL_REQUIRED_FIELDS: dict[Category, set[FieldName]]` per Appendix E. Validator walks rows, emits `missing_required_fields` array.
- `SDRUtils/core/cap_bands.py` — `validate_cap_band(notional: float, tenor_years: float, is_capped: bool)` per §43.4(f). Adds `cap_band_violation` column.
- `SDRUtils/core/rc_timeline.py` (started in Phase 4 for H10; completed here) — `build_rc_timeline` for every UTI; exposed as `rc_timeline_json` column.
- `SDRUtils/core/lifecycle_v2.py` — `compute_event_deltas` walks chain pairwise, emits `event_delta_notional` list so M2 (partial unwind delta vs immediate-prior-state, not inception) is correct.
- `SDRUtils/core/other_payments.py` — separate UFRO/UWIN/PEXH aggregation; emits distinct columns per payment type.
- D2-chain validator at [lifecycle.py:497-520](../../SDRUtils/core/lifecycle.py) — warn on CORR/EROR/TERM/REVI/MODI(Amend=True) with null `Original Dissemination Identifier`.
- Frequency anomaly check: SOFR-OIS with YEAR+1 reset → `frequency_anomaly = True`.

### 5.3 Schema additions

- `schedule_truncated`, `schedule_row_count`, `schedule_notional_series` (list[float])
- `missing_required_fields` (list[str])
- `cap_band_violation` (bool)
- `rc_timeline_json` (str)
- `event_delta_notional` (list[float])
- `other_payment_ufro`, `other_payment_uwin`, `other_payment_pexh` (float each)
- `frequency_anomaly` (bool)

### 5.4 Tests

- `test_schedule_parse_truncated`: 25-step schedule input → `schedule_truncated=True`, `schedule_row_count=10`.
- `test_prc1_missing_vm_pre_haircut`: PRC1 row missing [#125], [#127] → `missing_required_fields=["#125","#127"]`.
- `test_cap_band_3y_500m`: 3Y trade reported at $500M capped → `cap_band_violation=True` (§43.4(f) 2–10Y cap is $100M).
- `test_partial_unwind_multi_step`: NEWT 10M + MODI(−3M) + MODI(−2M) → deltas [0, −3M, −2M], not [0, −3M, −5M].
- `test_ufro_uwin_segregation`: row with both UFRO and UWIN payments → surface as separate columns, not summed.
- `test_d2_null_on_corr`: CORR row without Original Dissemination Identifier → `quality_flag="D2_MISSING"`.
- `test_sofr_ois_year1_reset`: YEAR+1 floating reset on SOFR underlier → `frequency_anomaly=True`.

### 5.5 Migration

Bump `TRADE_TAPE_CACHE_VERSION` to `"v5-p5"`. Rebuild Postgres tables `_v2` (additive columns; no rename needed — still in `_v2` family).

### 5.6 Gate

All Phase 5 tests pass. Distribution checks on 1-month slice:
- `cap_band_violation=True` rate ≈ 0 (if >0, that's genuine compliance signal — alert).
- `schedule_truncated=True` rate matches expectation from raw data.
- `frequency_anomaly=True` rate low.

---

## Phase 6 — Hygiene, NITs, monitoring, v1 decommission

### 6.1 Findings

- **M5** SDR-transfer dedup — close as "not applicable, DTCC-only"
- **M7** Jurisdiction [#104] MIXX
- **M8** CNH currency allowlist audit
- **N1** PLI counterparty identifier docstring
- **N2** Day-counter docstring pointing at [#53]
- **N3** Leg2 notional fallback warning
- **N4** Frequency anomaly (landed in Phase 5)
- **N5** Strike-price re-enable decision (deferred; document)
- **N6** Prime-brokerage indicator usage (landed in Phase 4)
- **N7** Package delimiter (document `;` convention)

### 6.2 Deliverables

- Cleanup: remove `chain` (union) field from `LifecycleSummary`; callers use `economic_chain` / `valuation_chain`.
- Remove legacy `lc_n_events` alias from `flatten_lifecycle_summary`.
- Remove fallback `lifecycle_map` path at [trade_tape.py:447-457](../../SDRUtils/analytics/trade_tape.py) — all data now has `lc_status`.
- Add a monitoring panel for quality flags: `state_machine_violation`, `cap_band_violation`, `frequency_anomaly`, `missing_required_fields`. One graph per flag over time. Alert on drift.
- M7 grep: confirm no filter on `Jurisdiction == "CFTC"` that drops MIXX.
- M8 grep: ensure no allowlist contains `"CNH"`.
- N1/N2/N3/N7: docstring additions.

### 6.3 v1 decommission (gated)

This is the only destructive step in the entire plan. It does NOT ship as part of Phase 6 automatically — it requires explicit sign-off against the criteria from §4.11.

**Prerequisite checklist** (every item must be confirmed before running the drop):

- [ ] `_v2` has been live for ≥ 30 calendar days since Phase 4 cutover.
- [ ] Zero rollbacks or cutover-related incidents in that window.
- [ ] `economic_class` distribution and `state_machine_violation` rate within tolerance for the full window.
- [ ] Dashboard user sign-off memo filed in `docs/plans/2026-MM-DD-v1-decommission-signoff.md`.
- [ ] No open queries or jobs reference `_v1` (verified via `pg_stat_statements` and repo grep over the prior 7 days).
- [ ] Point-in-time backup of `_v1` tables taken and archived per retention policy.

**Drop DDL** (run only after checklist):

```sql
DROP VIEW IF EXISTS arbs_usd_swap_tape_display_v1;
DROP TABLE IF EXISTS arbs_usd_swap_tape_legs_v1;
DROP TABLE IF EXISTS arbs_usd_swap_tape_packages_v1;
```

Remove `_v1` fallback references in any code comments that mentioned rollback paths.

### 6.4 Gate

- Legacy code paths removed.
- Monitoring panel live.
- All UNVERIFIED items from audit now VERIFIED.
- CLAUDE.md for SDR pipeline area updated with new column vocabulary.
- `_v1` decommission: either completed (with checklist evidence) or explicitly deferred with a tracked ticket.

---

## 7. Acceptance — the 50-UTI reconstruction test

### 7.1 Selection

50 UTIs drawn from a representative DTCC window (covering a compression day, a clearing-heavy day, a post-priced block day, a novation day, an error-recovery day). Coverage of the following Action×Event classes:

| Class | Min count |
|---|---|
| NEWT-TRAD vanilla | 10 |
| NEWT-TRAD post-priced | 3 |
| NEWT-TRAD block | 3 |
| NEWT-TRAD LN off-facility | 3 |
| NEWT-NOVA (full novation born) | 2 |
| NEWT-CLRG (β/γ) | 3 |
| NEWT-ALOC | 2 |
| NEWT-EXER | 1 |
| NEWT-PTNG | 1 |
| TERM-TRAD | 3 |
| TERM-ETRM | 2 |
| TERM-NOVA | 2 |
| TERM-CLRG (α) | 3 |
| TERM-COMP | 5 |
| PRTO-PTNG | 1 |
| MODI-TRAD Amend=True | 2 |
| MODI-TRAD Amend=False (post-price backfill) | 2 |
| MODI-NOVA (partial novation) | 1 |
| CORR | 1 |
| EROR then REVI | 1 |
| VALU-only day | (as UTI overlay) |

### 7.2 Assertions

For each UTI:

1. **Terminal state**: final `lc_status` matches Figure 1/2 expectation.
2. **Economic contribution**: sum of `contributes_to_flow` rows across the UTI's event chain matches the classification matrix expectation (e.g., full novation → 0; partial unwind → −delta).
3. **Reporting counterparty attribution**: at any novation boundary, `rc_timeline_json` produces the correct hierarchy per §45.8(g).
4. **P43 visibility**: rows with `on_p43 == False` do not appear in a P43-joined view.
5. **UTI continuity**: across PRTO/NEWT-PTNG pairs, UTI preserved; across MODI chains, UTI preserved.

### 7.3 Per-finding proof

| Finding | Test case(s) |
|---|---|
| B1 | NEWT-CLRG chain → volume 1×, flow 0 |
| B2 | TERM-COMP cycle → volume 0, flow 0 |
| B3 | post-priced NEWT + backfill MODI → bucketed on original exec ts |
| B4 | package spread 257 at notation=4 → 0.0257 |
| B5 | package price 9.9999999999 at notation=3 → NaN |
| B6 | MODI Amend=False → flow delta 0 |
| B7 | NEWT + 250× VALU → `lc_n_events_economic` = 1 |
| B8 | REVI in fallback path → `lifecycle_type='REVIVE'` |
| B9 | 3 trades with `portfolio_code='TRANSACTIONLEVEL'` → 3 groups |
| B10 | 25-step schedule → `schedule_truncated=True`, `schedule_row_count=10` |
| H1 | cleared swap exec 14:30 / accept 16:45 → bucketed 14:30 |
| H2 | partial novation 3M of 10M → net flow 0 |
| H3 | trade with A006 → yearFraction differs from A004 |
| H4 | VALU with `event_type='NOVA'` → `is_novation=False` |
| H5 | EROR then MODI → `state_machine_violation=True` |
| H6 | block trade P43 delay 30min → curve uses exec ts |
| H7 | PRC1 missing VM fields → `missing_required_fields=['#125','#127']` |
| H8 | naive ts without Z → quality flag |
| H9 | NEWT-CLRG → `is_new_risk=False` |
| H10 | novation RC flip → groupby(RC) no phantom volume |
| H11 | prime-brokerage mirror → `contributes_to_flow=False` |
| H12 | AFFL clearing exception → `contributes_to_flow=False` |
| H13 | scheduled amortization step → `was_scheduled_amortization=True`, NOT `was_economically_modified` |
| M1 | 3Y swap capped at $500M → `cap_band_violation=True` |
| M2 | NEWT + 3 chained MODIs → delta vs immediate prior, not vs inception |
| M3 | UFRO+UWIN on same row → two distinct columns, not summed |
| M4 | CORR with null D2 → `quality_flag='D2_MISSING'` |
| M9 | MODI Amend=None → `violation_reason` contains `MODI_AMENDMENT_NONE` |
| M11 | same D1 across 2 intraday slices → dedup retains 1 |
| M12 | 10-step `;`-delimited schedule → parses to list length 10 |
| N4 | SOFR-OIS YEAR+1 reset → `frequency_anomaly=True` |

### 7.4 Test harness

`tests/integration/test_reconstruction_50uti.py` reads a pinned fixture file `tests/fixtures/sdr_50uti_reconstruction.parquet` (snapshot of raw SDR for selected UTIs), runs full pipeline, asserts matrix assertions.

Run with `conda run -n stir pytest tests/integration/test_reconstruction_50uti.py` per the repo's Python env convention.

---

## 8. Risks and mitigations (consolidated)

| Risk | Mitigation |
|---|---|
| Full cutover (D7) breaks an unmapped consumer | Two-layer mitigation: (a) Phase 4 step 0 exhaustive grep of `lifecycle_type`, `is_new_risk`, `is_unwind`, `is_compression_any`, `is_termination_any`, `is_novation_any` — every call site on the migration list; (b) `_v1` preserved frozen per §4.11 — rollback is one constant edit + redeploy, no rebuild. |
| Permissive state machine hides real errors | Phase 6 monitoring panel + alerts on violation rate. |
| Matrix incomplete for a seen-in-production combo | Phase 3 integration test fails on any null `economic_class`. |
| Day-count table disagreement with external pricer | Phase 1 yearFraction tests against known reference values. |
| Backfill of `_v2` tables takes too long to ship in one release | Stage backfill asynchronously before cutover; flip API only when `_v2` is caught up. |
| Dashboard users confused by volume drops on clearing days | Pre-cutover explainer doc; "include administrative events" toggle provides escape hatch. |
| Someone re-enables strike parsing (N5) without notation awareness | Phase 6 doc-comment on the commented-out block at [SDRUtils/core/classification.py:163-168](../../SDRUtils/core/classification.py) explicitly requires `parse_notation_scalar` before uncomment. |

---

## 9. Open questions (remaining)

- **Q1** Who signs off on the day `_v1` is dropped? (Product or engineering lead.) Answer needed before Phase 4 ship.

All other questions are resolved per product direction (D7: full rework; D8: flow.py and SDRDataBuilder.py in scope; notebooks out of scope).

---

## Appendix A — Finding index (phase placement)

| ID | Severity | Phase |
|---|---|---|
| B1 Clearing triple-count | BLOCKER | 4 |
| B2 Compression TERMs in flow | BLOCKER | 4 |
| B3 Event vs Execution timestamp | BLOCKER | 1 |
| B4 Package spread notation | BLOCKER | 1 |
| B5 All-9s sentinels | BLOCKER | 1 |
| B6 Amendment indicator not gated | BLOCKER | 4 (wiring) |
| B7 VALU/MARU in lc_n_events | BLOCKER | 2 |
| B8 REVI→OTHER in fallback | BLOCKER | 2 |
| B9 TRANSACTIONLEVEL sentinel | BLOCKER | 4 |
| B10 First-10-schedule-rows truncation | BLOCKER | 5 (+ M12 parser in 1) |
| H1 Beta/gamma exec timestamp | HIGH | 4 |
| H2 Partial novation double-count | HIGH | 4 |
| H3 Day count mapping | HIGH | 1 |
| H4 Event flags on non-lifecycle | HIGH | 2 |
| H5 MODI post-EROR without REVI | HIGH | 2 |
| H6 Curve builder ts_col | HIGH | 1 |
| H7 Collateral required fields | HIGH | 5 |
| H8 Naive datetime (narrowed) | MEDIUM | 1 |
| H9 is_new_risk hard-coded | HIGH | 4 |
| H10 RC-flip aggregation | HIGH | 4/5 |
| H11 Prime brokerage filter | HIGH | 4 |
| H12 AFFL filter | HIGH | 4 |
| H13 Schedule step as amendment | HIGH | 2 |
| M1 Cap-band validation | MEDIUM | 5 |
| M2 Partial-unwind delta | MEDIUM | 5 |
| M3 UFRO/UWIN/PEXH separation | MEDIUM | 5 |
| M4 D2 chain validation | MEDIUM | 5 |
| M5 SDR transfer dedup | MEDIUM | 6 (close as N/A) |
| M7 MIXX jurisdiction | MEDIUM | 6 |
| M8 CNH allowlist | MEDIUM | 6 |
| M9 MODI Amendment=None | MEDIUM | 2 |
| M11 Intraday dedup inconsistent | MEDIUM | 2 |
| M12 Semicolon schedule parser | MEDIUM | 1 |
| N1–N7 | NIT | 6 |

## Appendix B — Files touched by phase

### Phase 1
- [SDRUtils/core/parsing.py](../../SDRUtils/core/parsing.py)
- [SDRUtils/core/dates.py](../../SDRUtils/core/dates.py)
- [SDRUtils/core/conventions.py](../../SDRUtils/core/conventions.py) (new)
- [SDRUtils/config.py](../../SDRUtils/config.py)
- [SDRUtils/products/usd/usd_swaps.py](../../SDRUtils/products/usd/usd_swaps.py)
- [SDRUtils/data/builder.py](../../SDRUtils/data/builder.py)
- [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py)

### Phase 2
- [SDRUtils/core/lifecycle.py](../../SDRUtils/core/lifecycle.py)
- [SDRUtils/core/lifecycle_v2.py](../../SDRUtils/core/lifecycle_v2.py)
- [SDRUtils/analytics/trade_tape.py](../../SDRUtils/analytics/trade_tape.py)
- [SDRUtils/data/builder.py](../../SDRUtils/data/builder.py) (M11 intraday dedup)

### Phase 3
- [SDRUtils/core/economic_classification.py](../../SDRUtils/core/economic_classification.py) (new)
- [SDRUtils/analytics/trade_tape.py](../../SDRUtils/analytics/trade_tape.py) (enrichment call)

### Phase 4
- [SDRUtils/analytics/trade_tape.py](../../SDRUtils/analytics/trade_tape.py)
- [SDRUtils/analytics/_tape_schema.py](../../SDRUtils/analytics/_tape_schema.py)
- [SDRUtils/analytics/flow.py](../../SDRUtils/analytics/flow.py)
- [SDRUtils/analytics/compression.py](../../SDRUtils/analytics/compression.py)
- [SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py](../../SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py)
- [MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py](../../MDP/IRSwaps/SDR_INTRADAY/rl_curve_utils/SDRDataBuilder.py)
- Postgres: `arbs_usd_swap_tape_*_v2` created alongside `_v1`. `_v1` frozen (writes revoked), NOT dropped.
- [SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts](../../SDRUtils/dashboard/src/lib/usd-swaps-tape-v2.ts)
- [SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts](../../SDRUtils/dashboard/src/app/api/usd-swaps-tape-v2/route.ts) + `route.logic.ts`
- [SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeCharts/FlowHistoryGrid.tsx)
- [SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/](../../SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/)

### Phase 5
- [SDRUtils/core/schedule_model.py](../../SDRUtils/core/schedule_model.py) (new)
- [SDRUtils/core/collateral_required.py](../../SDRUtils/core/collateral_required.py) (new)
- [SDRUtils/core/cap_bands.py](../../SDRUtils/core/cap_bands.py) (new)
- [SDRUtils/core/rc_timeline.py](../../SDRUtils/core/rc_timeline.py) (new)
- [SDRUtils/core/other_payments.py](../../SDRUtils/core/other_payments.py) (new)
- [SDRUtils/core/lifecycle_v2.py](../../SDRUtils/core/lifecycle_v2.py) (M2 per-event deltas)
- [SDRUtils/core/lifecycle.py](../../SDRUtils/core/lifecycle.py) (M4 D2 validation)

### Phase 6
- Various — cleanup, docstrings, monitoring panel.
