# USD Swaps Package Confidence — Design

Date: 2026-05-03
Scope: dashboard frontend, USD swaps tape v2 feature.

## Problem

Traders cannot tell at a glance whether a row labelled `FLY` (or
`CURVE`, `SPREADOVER`, etc.) is genuinely the structure the broker
reported, or a false positive from the SDR `package_indicator`. The
existing `Pkg` and `Pkg Ind` columns surface the raw labels but never
cross-check them against the leg-level math. For a fly we expect:

1. `package_indicator == true`
2. Belly DV01 ≈ -2× wing DV01 (risk-neutral spread)
3. `(2·rate_belly − rate_wing1 − rate_wing2) · 100 bp ≈ PTS` reported

When all three line up, confidence is high. When the SDR-reported
type contradicts the math, the trader needs to see that immediately.

## Solution shape

A pure-function confidence scorer (`computePackageConfidence(row)`)
keyed off `package_type`. Each type has a list of binary signals; the
result is `{ score: N, total: T, signals: Signal[] }` rendered as
`N/T ✓` with a colour band.

- Frontend-only — no backend changes, no ingest cycle.
- Equal-weight signals (1 vote each); tooltip shows which fired.
- Tolerances exposed via `PACKAGE_CONFIDENCE_TOLERANCES` constant for
  desk-tweakable thresholds without code edits.

## Signal definitions

| Pkg type | Signals |
|---|---|
| OUTRIGHT | (1) `package_indicator !== true` (2) `n_package_legs == 1` |
| CURVE (2 legs) | (1) `package_indicator == true` (2) DV01-neutral: `\|risk1+risk2\| / max(\|r1\|,\|r2\|) < 10%` (3) PTS match: `(rate_back − rate_front) · 100 ≈ PTS ± 0.5 bp` (4) Tenor monotonic ascending (5) `n_legs == 2` |
| FLY (3 legs) | (1) `package_indicator == true` (2) Belly = -2×wings: `\|risk_b + risk_w1 + risk_w2\| / max < 10%` (3) PTS match: `(2·rate_b − rate_w1 − rate_w2) · 100 ≈ PTS ± 0.5 bp` (4) Tenor monotonic (5) `n_legs == 3` |
| SPREADOVER | (1) `package_indicator == true` (2) PTS exists & non-zero (3) `has_spread == true` |
| MATCHED_MATURITY | (1) `package_indicator == true` (2) Same maturity all legs (3) Distinct `rate_index_clean` per leg |
| SPREADOVER_CURVE / _FLY | base CURVE/FLY signals + per-leg PTP/PTS exists |
| MATCHED_MATURITY_CURVE / _FLY | base CURVE/FLY signals + per-leg same-maturity check |
| MAC / IMM / FOMC | OUTRIGHT signal set (these are maturity conventions, not structures) |

## Tolerances

```ts
export const PACKAGE_CONFIDENCE_TOLERANCES = {
  ptsMatchBp: 0.5,        // ± bp window for derived spread vs reported PTS
  riskBalanceRel: 0.10,   // 10% relative tolerance for risk-balance checks
}
```

Lives in `features/usd-swaps-tape-v2/constants.ts`. Real-world tape
data has integer-rounded PTS reports and broker-rounded leg DV01s, so
strict tolerances reject legitimate packages.

## Architecture

```
features/usd-swaps-tape-v2/
  utils/
    packageConfidence.ts        # NEW — pure scorer
    __tests__/
      packageConfidence.test.ts # NEW — unit tests, no React
  components/
    TradeTapeTable/
      columns.tsx               # MOD — Pkg cell adds compact N/T chip
      LegsSubTable.tsx          # MOD — confidence panel above legs table
  constants.ts                  # MOD — tolerances + tone map
```

`computePackageConfidence` is pure: takes a `UsdSwapTapeRow`, returns
the result object. No React imports, trivially unit-testable.

## Rendering

### Compact chip (Pkg column)

Existing `Pkg` cell renders the type badge; suffix it with a small
chip showing `N/T ✓`:

- `N == T` → emerald tone (high confidence)
- `N >= T-1` → amber tone (one signal off)
- otherwise → rose tone (low confidence)
- OUTRIGHT with only structural signals → muted slate (informational)

Tooltip on hover lists each signal: `✓ Package indicator: true`,
`✗ Risk balance: belly -1.4×wings (tol 10%)`, etc.

### Confidence strip (LegsSubTable)

New strip above the existing legs table inside the row expansion.
Header line shows `Confidence  N/T ✓` with the same tone band as the
chip; body lists each signal with its computed numeric values:

```
Confidence  4/5 ✓
✓ Package indicator: true
✓ Risk balance: belly -2.0×wings (Δ 3.2%, tol 10%)
✓ PTS match: 2·3.85 − 3.50 − 4.00 = 0.20% = 20 bp (reported 20, Δ 0.0)
✓ Tenor monotonic: 5Y < 10Y < 30Y
✗ Leg count: expected 3, got 4
```

The numeric breakdowns are the point — trader can verify the math
with their own eyes.

## Testing

### Unit (utils/__tests__/packageConfidence.test.ts)

- FLY 5/10/30 with belly risk -2× and derived spread == reported PTS → 5/5.
- FLY with belly risk off by 25% → risk-balance fail, 4/5.
- FLY with PTS Δ=0.8 bp → PTS-match fail at default tolerance, pass at loose.
- CURVE 5s10s 3.50/4.00, PTS=50 → 5/5.
- OUTRIGHT, `package_indicator=null` → 2/2.
- SPREADOVER without PTS → partial fail.
- SPREADOVER_FLY → CURVE/FLY signals + spread-over signal.
- 2-leg row stamped FLY (n_legs mismatch) → leg-count fail.

### Component

- `LegsSubTable.test`: confidence strip renders with synthetic FLY data;
  signal detail strings match.
- `columns.test`: Pkg chip shows `4/5` token with correct tone class.

### Dev-server smoke test

- Start dev server (`SDRUtils/dashboard`).
- Open the USD swaps tape, scroll the live data.
- Spot-check across visible rows:
  - Known FLY row → ≥ 4/5 with PTS match in green.
  - Known CURVE row → ≥ 4/5.
  - OUTRIGHT row → 2/2.
  - Click expand, verify the breakdown numbers match the leg fixed
    rates and risk values in the legs table.
- Capture browser console — no warnings/errors from the confidence
  module.

## Out of scope

- Backend persistence of confidence score (frontend-derived; revisit
  if alerting needs server-side scoring).
- Confidence-based column filtering/sorting (can layer in via
  `useColumnFilters` later if requested).
- Confidence column in CSV exports.

## Rollback

Revert the three modified files + delete the new util. No DB / API
changes to roll back.
