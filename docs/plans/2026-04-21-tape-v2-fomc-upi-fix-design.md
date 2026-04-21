# USD Swap Tape v2 — FOMC/IMM Labeling + Package UPI Gate

**Date:** 2026-04-21
**Scope:** `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` and its upstream dependencies (`core/tenors.py`, `analytics/trade_tape.py`, `packages/{curve,fly,basis,mms}.py`).

## Problem

Trade labeling and package detection for `usd-swap-tape-v2` are flakey:

1. **FOMC/IMM label misclassification.** IMM dates (3rd Wednesday of Mar/Jun/Sep/Dec) and FOMC meeting dates frequently coincide. The current `detect_special_tenor` (`core/tenors.py:377`) gives FOMC priority whenever *either* date touches a FOMC calendar entry, and `_assign_meeting` in `trade_tape.py:704` applies an FOMC meeting label if *either* `effective_date` OR `expiration_date` matches. Result: IMM-dated constant-maturity trades get tagged FOMC.
2. **Package false positives.** Existing detectors (`curve`, `fly`, `basis`, `mms`) group candidate trades by time window, PV01 tolerance, tenor, and optionally `UPI Underlier Name`. They do not require an identical `Unique Product Identifier` (the 12-char DSB code). SDR-native packages share exactly the same UPI across legs, so any heterogeneous-UPI grouping is a false positive.

## Fix

### 1. FOMC/IMM labeling — tier priority

Rewrite `detect_special_tenor` (`SDRUtils/core/tenors.py`) and the label emitter in `_enrich_context` (`SDRUtils/analytics/trade_tape.py`) to follow this strict priority:

| Tier | Condition | Label shape | Example |
|------|-----------|-------------|---------|
| 1 | `eff` and `mat` are **consecutive FOMC meeting dates** | `FOMC MMMYY` (short-hand, eff side) | `FOMC APR26` for eff=4/28/2026, mat=6/16/2026 |
| 2 | `eff` is quarterly IMM (month codes H/M/U/Z) AND `mat` is constant-maturity tenor | `IMM_<code><yyyy> <tenor>` | `IMM_Z2026 10Y` |
| 3 | `eff` is FOMC-meeting-dated AND (`mat` is non-consecutive FOMC OR constant-tenor) | `FOMC MMMYY <mat>` | `FOMC APR26 10Y`, `FOMC APR26 DEC26` |
| else | — | fall through to existing STANDARD path | |

"Consecutive" = adjacent rows in `load_fomc_schedule()` output (already sorted by `effective_date`).

When eff is both a FOMC meeting and an IMM quarterly date (dates coincide) with a constant-tenor mat: tier 1 fails (mat isn't FOMC), tier 2 fires → `IMM` wins. This is the core bugfix.

### 2. Package detection — UPI hard gate

- **Detector level (`packages/curve.py`, `fly.py`, `basis.py`, `mms.py`).** Add `require_same_upi: bool = True` + `upi_col: str = "Unique Product Identifier"` parameters. Include `upi_col` in the candidate group-key list. Legs with differing UPI fall into separate candidate groups and never get bundled.
- **Safety net in `TradeTape._enrich_packages` (`analytics/trade_tape.py:580`).** After leg resolution via `package_legs`, validate each multi-leg group: if legs have >1 distinct UPI, reset `package_type=OUTRIGHT`, clear `package_id` and `package_legs`, set `is_package=False`. Catches SDR-native packages (`Package indicator` column) that bypass our detectors.

## Architecture

```
Raw SDR CSV
  └─► ingest_usdswaps (classifier)
        └─ detect_curve_trades_df / detect_fly_trades_df / basis / mms
             └─ NEW: require_same_upi gate in candidate group-key
  └─► per-trade rows with special_tenor_type (NEW tier logic) + package_type/_legs
        │
        ▼
TradeTape.compute()
  ├─ _enrich_context → fomc_meeting_label (NEW tier-aware formatter)
  └─ _enrich_packages → un-package heterogeneous-UPI groups (NEW safety net)
        │
        ▼
ingest_usdswaps_tape → leg rows + package rows → DB
```

## Files touched

- `SDRUtils/core/tenors.py` — `detect_special_tenor` decision order + helper for consecutive-FOMC check.
- `SDRUtils/analytics/trade_tape.py` — `_enrich_context` label formatter; `_enrich_packages` UPI validator.
- `SDRUtils/analytics/fomc.py` — re-export `load_fomc_schedule` already suffices; add a tiny `consecutive_meeting_pair(eff, mat, schedule) -> bool` helper.
- `SDRUtils/packages/curve.py`, `fly.py`, `basis.py`, `mms.py` — `require_same_upi` parameter.
- `SDRUtils/_swappulse_scripts/ingest_usdswaps_tape.py` — no logic change; inherits corrected `fomc_meeting_label` + `package_type` from TradeTape.

## Tests

Run under `conda run -n stir pytest`.

- `tests/test_tenors_special_type.py` (new) — parametrize eff/mat pairs against FOMC + IMM calendars covering all 3 tiers and ambiguous cases (FOMC-on-IMM).
- `tests/test_trade_tape_fomc_label.py` (new) — feed fixture rows through `_enrich_context` and assert exact label strings: `FOMC APR26`, `IMM_Z2026 10Y`, `FOMC APR26 10Y`, `FOMC APR26 DEC26`.
- `tests/test_package_upi_gate.py` (new) — feed detectors two otherwise-identical trades with distinct UPIs; assert no package formed.
- `tests/test_trade_tape_on_fixture.py` (extend) — synthetic curve with mismatched UPI across legs must un-package.
- Regression against `notebooks/sdr/sdr_example.csv` — diff label counts and package counts before/after.

## Non-goals

- No schema / DB column changes.
- No dashboard / frontend work.
- `_CENTRAL_BANK_DATES` registry keys stay as `FOMC_APR2026`; short-hand `FOMC APR26` is produced at the tape-label layer only.
