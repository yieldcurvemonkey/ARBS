# Package Confidence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Render a per-row package-detection confidence score (`X/N ✓`) in the USD swaps tape v2, both as a chip in the `Pkg` column and as a breakdown strip in the row-expansion `LegsSubTable`.

**Architecture:** Pure-function scorer (`utils/packageConfidence.ts`) computes a list of binary signals per `package_type` (OUTRIGHT, CURVE, FLY, SPREADOVER, MATCHED_MATURITY, composite variants, MAC/IMM/FOMC). Tolerances live in `constants.ts`. Two consumers: `columns.tsx` adds an inline chip; `LegsSubTable.tsx` renders a per-signal breakdown above the legs grid.

**Tech Stack:** TypeScript, React 19, Jest 30 (`@jest/globals`), Tailwind, PrimeReact 10. No new dependencies.

**Reference design:** [docs/plans/2026-05-03-package-confidence-design.md](2026-05-03-package-confidence-design.md)

---

## Working directory

All paths are relative to the worktree root (`C:\Users\chris\clee\ARBS\.claude\worktrees\magical-taussig-b4dad0`). Dashboard tests run from `SDRUtils/dashboard/`.

Run tests via:
```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
```

Run dev server via:
```
cd SDRUtils/dashboard && npm run dev
```

---

## Task 1: Add tolerances + tone map + Signal types to constants

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts` (append after `FLAG_CHIP_TONES`)

**Step 1: Append the tolerances + chip tones**

Add to the end of the existing constants file:

```ts
// ---------------------------------------------------------------
// Package-detection confidence (see docs/plans/2026-05-03-package-confidence-design.md).
// computePackageConfidence() in ../utils/packageConfidence.ts reads these.
// Exposed as constants so the desk can tune without code rewrites.
// ---------------------------------------------------------------
export const PACKAGE_CONFIDENCE_TOLERANCES = {
  /** ± bp window for derived-spread vs reported PTS match. */
  ptsMatchBp: 0.5,
  /** Relative tolerance for risk-balance checks (10% = 0.10). */
  riskBalanceRel: 0.10,
}

export const PACKAGE_CONFIDENCE_TONES = {
  /** All signals passed. */
  high: 'bg-emerald-900/40 text-emerald-200 ring-1 ring-emerald-400/40',
  /** One signal failed. */
  medium: 'bg-amber-900/40 text-amber-200 ring-1 ring-amber-400/40',
  /** Multiple signals failed. */
  low: 'bg-rose-900/40 text-rose-200 ring-1 ring-rose-400/40',
  /** OUTRIGHT structural-only check — informational, not a quality grade. */
  info: 'bg-slate-800/60 text-slate-300 ring-1 ring-slate-600/40',
} as const
```

**Step 2: Commit**

```
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/constants.ts
git commit -m "feat(usd-swaps-tape): add package confidence tolerances + tones"
```

---

## Task 2: Create the packageConfidence module skeleton

**Files:**
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`
- Create: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`

**Step 1: Write the failing test for the function signature + OUTRIGHT default**

Create the test file:

```ts
import { describe, expect, it } from '@jest/globals'
import type { UsdSwapTapeRow } from '../../types'
import { computePackageConfidence } from '../packageConfidence'

const baseRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
  ({
    package_id: 'P1',
    package_type: 'OUTRIGHT',
    package_indicator: null,
    n_package_legs: 1,
    legs_count: 1,
    legs_json: [],
    package_metrics: {},
    ...overrides,
  }) as UsdSwapTapeRow

describe('computePackageConfidence — OUTRIGHT', () => {
  it('returns 2/2 for a vanilla outright with no package indicator', () => {
    const result = computePackageConfidence(baseRow())
    expect(result.score).toBe(2)
    expect(result.total).toBe(2)
    expect(result.tone).toBe('info')
    expect(result.signals.map((s) => s.name)).toEqual([
      'package_indicator_off',
      'leg_count',
    ])
    expect(result.signals.every((s) => s.passed)).toBe(true)
  })
})
```

**Step 2: Run the test to verify it fails**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

Expected: FAIL — module does not exist.

**Step 3: Write minimal implementation**

Create `packageConfidence.ts`:

```ts
// ABOUTME: Pure-function scorer that grades package-detection confidence
// for USD swap tape rows by cross-checking package_indicator, leg-level
// risk balance, and the derived spread vs the reported PTS.
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'
import { PACKAGE_CONFIDENCE_TOLERANCES } from '../constants'

export type ConfidenceTone = 'high' | 'medium' | 'low' | 'info'

export type ConfidenceSignal = {
  /** Stable identifier — used by tests + analytics. */
  name: string
  /** Short label for tooltip / breakdown row. */
  label: string
  /** Pass/fail. */
  passed: boolean
  /** Free-text detail with computed numbers (e.g. "Δ 3.2% (tol 10%)"). */
  detail: string
}

export type PackageConfidence = {
  score: number
  total: number
  tone: ConfidenceTone
  signals: ConfidenceSignal[]
  /** Normalized package_type used for scoring (uppercased, NaN -> OUTRIGHT). */
  resolvedType: string
}

function normalizeType(value: unknown): string {
  const s = String(value ?? '').trim().toUpperCase()
  if (!s || s === 'NAN' || s === 'NONE') return 'OUTRIGHT'
  return s
}

function isPackageIndicatorTrue(value: unknown): boolean {
  if (value === true) return true
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase()
    return ['true', 't', '1', 'yes', 'y'].includes(v)
  }
  return false
}

function legCount(row: UsdSwapTapeRow): number {
  if (typeof row.n_package_legs === 'number') return row.n_package_legs
  return Array.isArray(row.legs_json) ? row.legs_json.length : 0
}

function pickTone(score: number, total: number, isInfo: boolean): ConfidenceTone {
  if (isInfo) return 'info'
  if (score === total) return 'high'
  if (score >= total - 1) return 'medium'
  return 'low'
}

function outrightSignals(row: UsdSwapTapeRow): ConfidenceSignal[] {
  const indicatorOn = isPackageIndicatorTrue(row.package_indicator)
  const legs = legCount(row)
  return [
    {
      name: 'package_indicator_off',
      label: 'Package indicator',
      passed: !indicatorOn,
      detail: indicatorOn
        ? 'reported as packaged but classified outright'
        : 'not flagged as a package',
    },
    {
      name: 'leg_count',
      label: 'Leg count',
      passed: legs === 1,
      detail: `expected 1, got ${legs}`,
    },
  ]
}

export function computePackageConfidence(row: UsdSwapTapeRow): PackageConfidence {
  const resolvedType = normalizeType(row.package_type)
  const signals: ConfidenceSignal[] = outrightSignals(row)
  const score = signals.filter((s) => s.passed).length
  const total = signals.length
  const tone = pickTone(score, total, /*isInfo=*/ true)
  return { score, total, tone, signals, resolvedType }
}
```

**Step 4: Run the test to verify it passes**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

Expected: PASS — 1 test, 0 failures.

**Step 5: Commit**

```
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts \
        SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts
git commit -m "feat(usd-swaps-tape): scaffold package confidence module + OUTRIGHT signals"
```

---

## Task 3: CURVE signals (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Write the failing tests**

Append to the test file:

```ts
const curveLeg = (overrides: Partial<UsdSwapTapeLeg>): UsdSwapTapeLeg =>
  ({
    trade_id: 'T',
    tenor_years: 5,
    risk: 0,
    fixed_rate: 0,
    notional: 100_000_000,
    ...overrides,
  }) as UsdSwapTapeLeg

describe('computePackageConfidence — CURVE', () => {
  const curveRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 50,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5s10s with PTS=50', () => {
    const result = computePackageConfidence(curveRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('fails risk balance when belly-leg DV01 imbalanced > 10%', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived spread is more than 0.5 bp off', () => {
    const result = computePackageConfidence(
      curveRow({
        package_transaction_spread: 50,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          // 4.01 - 3.5 = 0.51% = 51 bp — 1 bp off reported 50.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.01 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when 3 legs are stamped CURVE', () => {
    const result = computePackageConfidence(
      curveRow({
        n_package_legs: 3,
        legs_json: [
          curveLeg({ tenor_years: 2, risk: -2_500, fixed_rate: 3.0 }),
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })

  it('fails tenor monotonicity when legs are not ascending', () => {
    const result = computePackageConfidence(
      curveRow({
        legs_json: [
          curveLeg({ tenor_years: 10, risk: -5_000, fixed_rate: 4.0 }),
          curveLeg({ tenor_years: 5, risk: 5_000, fixed_rate: 3.5 }),
        ],
      }),
    )
    // helpers re-sort tenor-asc before checking, so this checks the underlying
    // monotonic helper — the legs as ordered in legs_json are NOT ascending.
    expect(
      result.signals.find((s) => s.name === 'tenor_monotonic')?.passed,
    ).toBe(false)
  })
})
```

**Step 2: Run tests to verify they fail**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

Expected: 5 new failures (CURVE branch returns OUTRIGHT signals).

**Step 3: Implement CURVE branch**

Inside `packageConfidence.ts`, before the export of `computePackageConfidence`, add helpers and a CURVE signal builder:

```ts
function sortLegsTenorAsc(legs: UsdSwapTapeLeg[]): UsdSwapTapeLeg[] {
  return [...legs].sort((a, b) => {
    const at = typeof a?.tenor_years === 'number' ? a.tenor_years : Number.POSITIVE_INFINITY
    const bt = typeof b?.tenor_years === 'number' ? b.tenor_years : Number.POSITIVE_INFINITY
    return at - bt
  })
}

function isAscendingByTenor(legs: UsdSwapTapeLeg[]): boolean {
  for (let i = 1; i < legs.length; i++) {
    const prev = legs[i - 1]?.tenor_years ?? Number.POSITIVE_INFINITY
    const curr = legs[i]?.tenor_years ?? Number.POSITIVE_INFINITY
    if (prev > curr) return false
  }
  return true
}

function legNumberOr(leg: UsdSwapTapeLeg, key: keyof UsdSwapTapeLeg): number | null {
  const v = leg[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** Pass when |sum(risks)| / max(|risks|) <= riskBalanceRel. */
function riskBalanceSignal(
  legs: UsdSwapTapeLeg[],
  weights: number[],
  label: string,
): ConfidenceSignal {
  const tol = PACKAGE_CONFIDENCE_TOLERANCES.riskBalanceRel
  const risks = legs.map((l) => legNumberOr(l, 'risk'))
  if (risks.some((r) => r === null)) {
    return {
      name: 'risk_balance',
      label,
      passed: false,
      detail: 'leg risk missing',
    }
  }
  const weighted = risks.map((r, i) => (r as number) * weights[i])
  const sum = weighted.reduce((a, b) => a + b, 0)
  const denom = Math.max(...weighted.map((v) => Math.abs(v)), 1e-9)
  const rel = Math.abs(sum) / denom
  return {
    name: 'risk_balance',
    label,
    passed: rel <= tol,
    detail: `Δ ${(rel * 100).toFixed(1)}% (tol ${(tol * 100).toFixed(0)}%)`,
  }
}

/** Pass when derived spread (in bp) is within ptsMatchBp of reported PTS. */
function ptsMatchSignal(
  derivedBp: number | null,
  reportedPts: number | null | undefined,
): ConfidenceSignal {
  const tol = PACKAGE_CONFIDENCE_TOLERANCES.ptsMatchBp
  if (derivedBp === null || reportedPts == null) {
    return {
      name: 'pts_match',
      label: 'PTS match',
      passed: false,
      detail:
        derivedBp === null ? 'leg fixed_rate missing' : 'PTS not reported',
    }
  }
  const reported = Number(reportedPts)
  const delta = Math.abs(derivedBp - reported)
  return {
    name: 'pts_match',
    label: 'PTS match',
    passed: delta <= tol,
    detail: `derived ${derivedBp.toFixed(2)}bp vs reported ${reported}bp (Δ ${delta.toFixed(2)}, tol ±${tol})`,
  }
}

function curveSignals(row: UsdSwapTapeRow): ConfidenceSignal[] {
  const legsRaw = (row.legs_json ?? []) as UsdSwapTapeLeg[]
  const legs = sortLegsTenorAsc(legsRaw)
  const indicatorOn = isPackageIndicatorTrue(row.package_indicator)
  const n = legCount(row)
  const front = legs[0]
  const back = legs[1]
  const r1 = front ? legNumberOr(front, 'fixed_rate') : null
  const r2 = back ? legNumberOr(back, 'fixed_rate') : null
  const derivedBp = r1 !== null && r2 !== null ? (r2 - r1) * 100 : null

  return [
    {
      name: 'package_indicator_on',
      label: 'Package indicator',
      passed: indicatorOn,
      detail: indicatorOn ? 'true' : 'broker did not flag as a package',
    },
    riskBalanceSignal(legs.slice(0, 2), [1, 1], 'Risk balance (DV01-neutral)'),
    ptsMatchSignal(derivedBp, row.package_transaction_spread),
    {
      name: 'tenor_monotonic',
      label: 'Tenor monotonic',
      passed: isAscendingByTenor(legsRaw),
      detail: legsRaw
        .map((l) => (typeof l.tenor_years === 'number' ? `${l.tenor_years}Y` : '?'))
        .join(' → '),
    },
    {
      name: 'leg_count',
      label: 'Leg count',
      passed: n === 2,
      detail: `expected 2, got ${n}`,
    },
  ]
}
```

Then dispatch on type in `computePackageConfidence`:

```ts
export function computePackageConfidence(row: UsdSwapTapeRow): PackageConfidence {
  const resolvedType = normalizeType(row.package_type)
  let signals: ConfidenceSignal[]
  let isInfo = false
  switch (resolvedType) {
    case 'CURVE':
      signals = curveSignals(row)
      break
    case 'OUTRIGHT':
    default:
      signals = outrightSignals(row)
      isInfo = true
      break
  }
  const score = signals.filter((s) => s.passed).length
  const total = signals.length
  const tone = pickTone(score, total, isInfo)
  return { score, total, tone, signals, resolvedType }
}
```

**Step 4: Run tests to verify they pass**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

Expected: PASS — 6 tests total.

**Step 5: Commit**

```
git add SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/
git commit -m "feat(usd-swaps-tape): CURVE confidence signals with risk-balance + PTS-match"
```

---

## Task 4: FLY signals (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Write the failing tests**

Append:

```ts
describe('computePackageConfidence — FLY', () => {
  const flyRow = (overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow =>
    baseRow({
      package_type: 'FLY',
      package_indicator: true,
      n_package_legs: 3,
      // 2*3.85 - 3.50 - 4.00 = 0.20% = 20 bp.
      package_transaction_spread: 20,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
      ],
      ...overrides,
    })

  it('returns 5/5 for a textbook 5/10/30 fly', () => {
    const result = computePackageConfidence(flyRow())
    expect(result.score).toBe(5)
    expect(result.total).toBe(5)
    expect(result.tone).toBe('high')
  })

  it('fails belly = -2*wings when belly DV01 is off by 25%', () => {
    const result = computePackageConfidence(
      flyRow({
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // belly under-weighted: should be 5000, given 3750
          curveLeg({ tenor_years: 10, risk: 3_750, fixed_rate: 3.85 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.score).toBe(4)
    expect(
      result.signals.find((s) => s.name === 'risk_balance')?.passed,
    ).toBe(false)
  })

  it('fails PTS match when derived bfly is 0.8 bp off reported PTS', () => {
    const result = computePackageConfidence(
      flyRow({
        package_transaction_spread: 20,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
          // 2*3.854 - 3.5 - 4.0 = 0.208% = 20.8 bp; off by 0.8 bp.
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.854 }),
          curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
  })

  it('fails leg count when only 2 legs are stamped FLY', () => {
    const result = computePackageConfidence(
      flyRow({
        n_package_legs: 2,
        legs_json: [
          curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
          curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'leg_count')?.passed).toBe(false)
  })
})
```

**Step 2: Run tests to verify they fail**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

Expected: 4 new failures.

**Step 3: Implement FLY branch**

Add `flySignals` helper, then route to it from the dispatch switch:

```ts
function flySignals(row: UsdSwapTapeRow): ConfidenceSignal[] {
  const legsRaw = (row.legs_json ?? []) as UsdSwapTapeLeg[]
  const legs = sortLegsTenorAsc(legsRaw)
  const indicatorOn = isPackageIndicatorTrue(row.package_indicator)
  const n = legCount(row)
  const front = legs[0]
  const belly = legs[1]
  const back = legs[2]
  const rF = front ? legNumberOr(front, 'fixed_rate') : null
  const rB = belly ? legNumberOr(belly, 'fixed_rate') : null
  const rK = back ? legNumberOr(back, 'fixed_rate') : null
  const derivedBp =
    rF !== null && rB !== null && rK !== null ? (2 * rB - rF - rK) * 100 : null

  // Risk balance for fly: belly + wing1 + wing2 ≈ 0.
  // Use weights [1, 1, 1] applied to [front, belly, back] risk values directly.
  return [
    {
      name: 'package_indicator_on',
      label: 'Package indicator',
      passed: indicatorOn,
      detail: indicatorOn ? 'true' : 'broker did not flag as a package',
    },
    riskBalanceSignal(legs.slice(0, 3), [1, 1, 1], 'Risk balance (belly = -2×wings)'),
    ptsMatchSignal(derivedBp, row.package_transaction_spread),
    {
      name: 'tenor_monotonic',
      label: 'Tenor monotonic',
      passed: isAscendingByTenor(legsRaw),
      detail: legsRaw
        .map((l) => (typeof l.tenor_years === 'number' ? `${l.tenor_years}Y` : '?'))
        .join(' → '),
    },
    {
      name: 'leg_count',
      label: 'Leg count',
      passed: n === 3,
      detail: `expected 3, got ${n}`,
    },
  ]
}
```

Add `case 'FLY': signals = flySignals(row); break;` to the switch in `computePackageConfidence`.

**Step 4: Run tests**

Expected: PASS — 10 tests total.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): FLY confidence signals (belly = -2×wings)"
```

---

## Task 5: SPREADOVER + MATCHED_MATURITY signals (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Failing tests**

```ts
describe('computePackageConfidence — SPREADOVER', () => {
  it('returns 3/3 when indicator on, has_spread true, PTS non-zero', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: 12,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails PTS-non-zero signal when PTS is missing', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER',
        package_indicator: true,
        has_spread: true,
        package_transaction_spread: null,
        n_package_legs: 1,
        legs_json: [curveLeg({ tenor_years: 5 })],
      }),
    )
    expect(result.signals.find((s) => s.name === 'pts_present')?.passed).toBe(false)
  })
})

describe('computePackageConfidence — MATCHED_MATURITY', () => {
  it('returns 3/3 when legs share maturity and rate indices differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.score).toBe(3)
    expect(result.total).toBe(3)
  })

  it('fails same-maturity when leg maturities differ', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY',
        package_indicator: true,
        n_package_legs: 2,
        legs_json: [
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2036-05-01',
            rate_index_clean: 'USD-SOFR',
          }),
          curveLeg({
            tenor_years: 10,
            swap_maturity_date: '2037-05-01',
            rate_index_clean: 'USD-LIBOR',
          }),
        ],
      }),
    )
    expect(result.signals.find((s) => s.name === 'same_maturity')?.passed).toBe(false)
  })
})
```

**Step 2: Verify they fail**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=packageConfidence
```

**Step 3: Implement**

Add helpers and dispatch:

```ts
function spreadOverSignals(row: UsdSwapTapeRow): ConfidenceSignal[] {
  const indicatorOn = isPackageIndicatorTrue(row.package_indicator)
  const pts = row.package_transaction_spread
  const ptsNumeric = typeof pts === 'number' ? pts : Number(pts)
  const hasPtsNumber = pts != null && Number.isFinite(ptsNumeric) && ptsNumeric !== 0
  return [
    {
      name: 'package_indicator_on',
      label: 'Package indicator',
      passed: indicatorOn,
      detail: indicatorOn ? 'true' : 'broker did not flag as a package',
    },
    {
      name: 'has_spread',
      label: 'Has spread',
      passed: row.has_spread === true,
      detail: row.has_spread === true ? 'has_spread true' : 'has_spread not set',
    },
    {
      name: 'pts_present',
      label: 'PTS reported',
      passed: hasPtsNumber,
      detail: hasPtsNumber ? `PTS = ${ptsNumeric}` : 'PTS missing or zero',
    },
  ]
}

function matchedMaturitySignals(row: UsdSwapTapeRow): ConfidenceSignal[] {
  const indicatorOn = isPackageIndicatorTrue(row.package_indicator)
  const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]
  const maturities = legs
    .map((l) => l.swap_maturity_date ?? l.expiration_date)
    .filter(Boolean) as string[]
  const sameMaturity = maturities.length >= 2 &&
    maturities.every((m) => m === maturities[0])
  const indices = new Set(
    legs
      .map((l) => l.rate_index_clean)
      .filter(Boolean) as string[],
  )
  const indicesDistinct = legs.length >= 2 && indices.size >= 2
  return [
    {
      name: 'package_indicator_on',
      label: 'Package indicator',
      passed: indicatorOn,
      detail: indicatorOn ? 'true' : 'broker did not flag as a package',
    },
    {
      name: 'same_maturity',
      label: 'Same maturity all legs',
      passed: sameMaturity,
      detail: sameMaturity
        ? `all legs mature ${maturities[0]}`
        : `mismatched maturities: ${maturities.join(', ') || '—'}`,
    },
    {
      name: 'distinct_indices',
      label: 'Distinct rate indices (basis)',
      passed: indicesDistinct,
      detail: indicesDistinct
        ? `indices: ${[...indices].join(', ')}`
        : `only one rate index: ${[...indices].join(', ') || '—'}`,
    },
  ]
}
```

Extend the switch:

```ts
case 'SPREADOVER': signals = spreadOverSignals(row); break;
case 'MATCHED_MATURITY': signals = matchedMaturitySignals(row); break;
```

**Step 4: Verify tests pass**

Expected: 14 tests total, all passing.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): SPREADOVER + MATCHED_MATURITY confidence signals"
```

---

## Task 6: Composite types (SPREADOVER_CURVE / _FLY, MATCHED_MATURITY_CURVE / _FLY) (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Failing tests**

```ts
describe('computePackageConfidence — composite types', () => {
  it('SPREADOVER_FLY uses FLY signals + per-leg PTP/PTS presence', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'SPREADOVER_FLY',
        package_indicator: true,
        n_package_legs: 3,
        package_transaction_spread: 20,
        legs_json: [
          {
            ...curveLeg({ tenor_years: 5, risk: -2_500, fixed_rate: 3.5 }),
            package_transaction_spread: 12,
          } as any,
          {
            ...curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 3.85 }),
            package_transaction_spread: 14,
          } as any,
          {
            ...curveLeg({ tenor_years: 30, risk: -2_500, fixed_rate: 4.0 }),
            package_transaction_spread: 16,
          } as any,
        ],
      }),
    )
    expect(result.total).toBe(6)
    expect(result.score).toBe(6)
    expect(result.signals.find((s) => s.name === 'per_leg_pts_present')?.passed).toBe(true)
  })

  it('MATCHED_MATURITY_CURVE uses CURVE signals + same-maturity-per-leg', () => {
    const result = computePackageConfidence(
      baseRow({
        package_type: 'MATCHED_MATURITY_CURVE',
        package_indicator: true,
        n_package_legs: 2,
        package_transaction_spread: 50,
        legs_json: [
          {
            ...curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
            swap_maturity_date: '2031-05-01',
          } as any,
          {
            ...curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.0 }),
            swap_maturity_date: '2036-05-01',
          } as any,
        ],
      }),
    )
    // Base CURVE has 5 signals; composite adds 1 (per-leg matched-maturity check
    // — passes here because each leg's maturity matches its own tenor).
    expect(result.total).toBe(6)
  })
})
```

**Step 2: Verify failures**

**Step 3: Implement**

Add a dispatcher that wraps the base-type signals + appends a composite signal:

```ts
function perLegPtsSignal(legs: UsdSwapTapeLeg[]): ConfidenceSignal {
  const present = legs.every((l) => {
    const v = (l as any).package_transaction_spread
    return v != null && Number.isFinite(Number(v))
  })
  return {
    name: 'per_leg_pts_present',
    label: 'Per-leg PTS',
    passed: present && legs.length > 0,
    detail: present
      ? legs
          .map((l) => `${l.tenor_years ?? '?'}Y=${(l as any).package_transaction_spread}`)
          .join(', ')
      : 'one or more legs missing per-leg PTS',
  }
}

function perLegMatchedMaturitySignal(legs: UsdSwapTapeLeg[]): ConfidenceSignal {
  // Each leg should have its own maturity (no specific equality required —
  // signal flags missing maturities, which would invalidate the matched-
  // maturity overlay).
  const allHaveMaturity = legs.every((l) =>
    Boolean(l.swap_maturity_date ?? l.expiration_date),
  )
  return {
    name: 'per_leg_matched_maturity',
    label: 'Per-leg maturity',
    passed: allHaveMaturity && legs.length > 0,
    detail: allHaveMaturity
      ? legs.map((l) => l.swap_maturity_date ?? l.expiration_date ?? '—').join(', ')
      : 'one or more legs missing maturity date',
  }
}
```

Update dispatch switch — match composite suffixes after the base cases:

```ts
case 'SPREADOVER_CURVE':
  signals = [...curveSignals(row), perLegPtsSignal((row.legs_json ?? []) as UsdSwapTapeLeg[])]
  break
case 'SPREADOVER_FLY':
  signals = [...flySignals(row), perLegPtsSignal((row.legs_json ?? []) as UsdSwapTapeLeg[])]
  break
case 'MATCHED_MATURITY_CURVE':
  signals = [
    ...curveSignals(row),
    perLegMatchedMaturitySignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
  ]
  break
case 'MATCHED_MATURITY_FLY':
  signals = [
    ...flySignals(row),
    perLegMatchedMaturitySignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
  ]
  break
```

**Step 4: Verify pass**

Expected: 16 tests total.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): composite SPREADOVER_*/MATCHED_MATURITY_* signals"
```

---

## Task 7: MAC / IMM / FOMC fallback to OUTRIGHT signal set (TDD)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Failing test**

```ts
describe('computePackageConfidence — maturity-convention types', () => {
  it.each(['MAC', 'IMM', 'FOMC'])(
    'treats %s as OUTRIGHT (informational, 2/2)',
    (kind) => {
      const result = computePackageConfidence(
        baseRow({
          package_type: kind as any,
          package_indicator: false,
          n_package_legs: 1,
          legs_json: [curveLeg({ tenor_years: 5 })],
        }),
      )
      expect(result.tone).toBe('info')
      expect(result.score).toBe(2)
      expect(result.total).toBe(2)
    },
  )
})
```

**Step 2: Verify failure**

The default branch already routes to OUTRIGHT, but the dispatch needs an explicit case so the *resolvedType* still records the original kind (useful for tooltip).

**Step 3: Implement**

Update the switch:

```ts
case 'MAC':
case 'IMM':
case 'FOMC':
case 'OUTRIGHT':
default:
  signals = outrightSignals(row)
  isInfo = true
  break
```

**Step 4: Verify pass**

Expected: 19 tests total.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): MAC/IMM/FOMC fallback to outright confidence"
```

---

## Task 8: Configurable tolerance override (TDD)

Allow the public function to accept a tolerance override so the desk (or tests) can tune without mutating the constants module.

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/__tests__/packageConfidence.test.ts`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/utils/packageConfidence.ts`

**Step 1: Failing test**

```ts
describe('computePackageConfidence — tolerance override', () => {
  it('passes a 0.8 bp PTS miss when ptsMatchBp tolerance is loosened to 1', () => {
    const row = baseRow({
      package_type: 'CURVE',
      package_indicator: true,
      n_package_legs: 2,
      package_transaction_spread: 50,
      legs_json: [
        curveLeg({ tenor_years: 5, risk: -5_000, fixed_rate: 3.5 }),
        curveLeg({ tenor_years: 10, risk: 5_000, fixed_rate: 4.008 }),
      ],
    })
    const tight = computePackageConfidence(row)
    expect(tight.signals.find((s) => s.name === 'pts_match')?.passed).toBe(false)
    const loose = computePackageConfidence(row, { ptsMatchBp: 1.0 })
    expect(loose.signals.find((s) => s.name === 'pts_match')?.passed).toBe(true)
  })
})
```

**Step 2: Verify failure**

**Step 3: Implement**

Refactor `computePackageConfidence` to accept an optional `tolerances` parameter. Thread it through `riskBalanceSignal` / `ptsMatchSignal` (replace the direct `PACKAGE_CONFIDENCE_TOLERANCES` reads with a parameter). Update the public signature to:

```ts
type Tolerances = typeof PACKAGE_CONFIDENCE_TOLERANCES

export function computePackageConfidence(
  row: UsdSwapTapeRow,
  toleranceOverrides?: Partial<Tolerances>,
): PackageConfidence {
  const tol = { ...PACKAGE_CONFIDENCE_TOLERANCES, ...(toleranceOverrides ?? {}) }
  // ... pass `tol` into curveSignals/flySignals/etc.
}
```

Adjust each builder to receive `tol` rather than reading the module constant directly.

**Step 4: Verify pass**

Expected: 20 tests total.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): tolerance override on computePackageConfidence"
```

---

## Task 9: Render compact chip in Pkg column (component test + edit)

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/columns.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/columns.test.ts`

**Step 1: Failing test**

Append to `columns.test.ts`:

```ts
import { computePackageConfidence } from '../../../utils/packageConfidence'

describe('Pkg column confidence chip integration', () => {
  it('imports computePackageConfidence inside columns.tsx', () => {
    expect(columnsSource).toContain('computePackageConfidence')
  })

  it('chip is conditionally rendered with X/N pattern', () => {
    expect(columnsSource).toMatch(/score.*\/.*total/)
  })

  it('FLY row scoring → high tone class is applied', () => {
    const result = computePackageConfidence({
      package_type: 'FLY',
      package_indicator: true,
      n_package_legs: 3,
      package_transaction_spread: 20,
      legs_json: [
        { tenor_years: 5, risk: -2_500, fixed_rate: 3.5 } as any,
        { tenor_years: 10, risk: 5_000, fixed_rate: 3.85 } as any,
        { tenor_years: 30, risk: -2_500, fixed_rate: 4.0 } as any,
      ],
    } as any)
    expect(result.tone).toBe('high')
  })
})
```

**Step 2: Verify failure**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=columns
```

Expected: failures for `computePackageConfidence` import + score pattern.

**Step 3: Edit columns.tsx**

In `columns.tsx`:

1. Add imports near the top:

```ts
import { computePackageConfidence } from '../../utils/packageConfidence'
import { PACKAGE_CONFIDENCE_TONES } from '../../constants'
```

2. Replace the existing `pkg` Column body with one that renders the chip alongside the type badge:

```tsx
<Column
  key="pkg"
  field="package_type"
  filterField="package_type"
  filter
  {...compactFilterMenuProps}
  header={renderHeader(
    'Pkg',
    summaryFor('package_type', config.activeFilters),
  )}
  body={(row: UsdSwapTapeRow) => {
    const conf = computePackageConfidence(row)
    const toneClass = PACKAGE_CONFIDENCE_TONES[conf.tone]
    const tooltip = conf.signals
      .map((s) => `${s.passed ? '✓' : '✗'} ${s.label}: ${s.detail}`)
      .join('\n')
    return (
      <div className="flex items-center gap-1">
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${packageTypeBadgeClassName(row.package_type)}`}
        >
          {packageTypeDisplayLabel(row.package_type)}
        </span>
        <span
          className={`inline-flex items-center rounded px-1 py-0.5 font-mono text-[10px] ${toneClass}`}
          data-testid={`pkg-confidence-${row.package_id}`}
          title={tooltip}
        >
          {conf.score}/{conf.total}
        </span>
      </div>
    )
  }}
  style={{ width: 132 }}
/>,
```

Bump width from 92 → 132 to fit the chip.

**Step 4: Verify pass**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=columns
```

Expected: PASS.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): render confidence chip in Pkg column"
```

---

## Task 10: Render confidence panel in LegsSubTable

**Files:**
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/LegsSubTable.tsx`
- Modify: `SDRUtils/dashboard/src/features/usd-swaps-tape-v2/components/TradeTapeTable/__tests__/LegsSubTable.test.ts`

**Step 1: Failing test**

Append to `LegsSubTable.test.ts` (read the existing file first to keep import patterns consistent):

```ts
describe('LegsSubTable confidence strip', () => {
  it('renders confidence strip with N/T header and per-signal rows for FLY', () => {
    const html = renderToStaticMarkup(
      LegsSubTable({
        row: {
          package_id: 'P-FLY',
          package_type: 'FLY',
          package_indicator: true,
          n_package_legs: 3,
          package_transaction_spread: 20,
          legs_json: [
            { tenor_years: 5, risk: -2_500, fixed_rate: 3.5, trade_id: 'L1' },
            { tenor_years: 10, risk: 5_000, fixed_rate: 3.85, trade_id: 'L2' },
            { tenor_years: 30, risk: -2_500, fixed_rate: 4.0, trade_id: 'L3' },
          ],
        } as any,
      }),
    )
    expect(html).toContain('data-testid="confidence-strip-P-FLY"')
    expect(html).toContain('5/5')
    expect(html).toContain('PTS match')
    expect(html).toContain('Risk balance')
  })
})
```

(`renderToStaticMarkup` must be imported — match the existing import style in the same test file.)

**Step 2: Verify failure**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=LegsSubTable.test
```

**Step 3: Edit LegsSubTable.tsx**

Add imports:

```ts
import { computePackageConfidence } from '../../utils/packageConfidence'
import { PACKAGE_CONFIDENCE_TONES } from '../../constants'
```

Inside the component, before the existing `return (`, compute:

```ts
const confidence = computePackageConfidence(row)
const confidenceTone = PACKAGE_CONFIDENCE_TONES[confidence.tone]
```

Insert the strip JSX just inside the outer wrapper, above the existing PTP block:

```tsx
<div
  className="mb-2 rounded-lg border border-slate-800/80 bg-slate-900/60 px-3 py-2"
  data-testid={`confidence-strip-${row.package_id}`}
>
  <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-400">
    <span>Confidence</span>
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] ${confidenceTone}`}
    >
      {confidence.score}/{confidence.total}
    </span>
    <span className="font-mono text-[10px] text-slate-500">
      ({confidence.resolvedType})
    </span>
  </div>
  <ul className="mt-1 space-y-0.5">
    {confidence.signals.map((s) => (
      <li
        key={s.name}
        className="flex items-baseline gap-2 font-mono text-[11px] leading-tight"
      >
        <span
          className={s.passed ? 'text-emerald-300' : 'text-rose-300'}
          aria-label={s.passed ? 'pass' : 'fail'}
        >
          {s.passed ? '✓' : '✗'}
        </span>
        <span className="text-slate-200">{s.label}:</span>
        <span className="text-slate-400">{s.detail}</span>
      </li>
    ))}
  </ul>
</div>
```

**Step 4: Verify pass**

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=LegsSubTable
```

Expected: PASS.

**Step 5: Commit**

```
git commit -am "feat(usd-swaps-tape): confidence breakdown strip in LegsSubTable"
```

---

## Task 11: Run the full feature test suite

```
cd SDRUtils/dashboard && npm test -- --testPathPatterns=usd-swaps-tape-v2
```

Expected: all tests pass, no skipped suites. Also run lint:

```
cd SDRUtils/dashboard && npm run lint
```

Expected: no new errors. If lint introduces fixes, commit:

```
git commit -am "chore(usd-swaps-tape): lint fixes for confidence module"
```

---

## Task 12: Dev-server smoke test

Per @superpowers:verification-before-completion — verify the live UI before claiming the work is done.

**Step 1: Start dev server**

```
cd SDRUtils/dashboard && npm run dev
```

Wait for `ready`/`compiled` log line. The default URL is `http://localhost:3000` (next.js default).

**Step 2: Open the USD swaps tape route**

Path is the page that mounts `UsdSwapsTradeTape`. Confirm by grepping the app router for `UsdSwapsTradeTape` import; navigate to the corresponding route in the browser.

**Step 3: Spot-check rows**

For at least:

- One row stamped `FLY` (Pkg = "Fly"): chip should read 4/5 or 5/5 in green/amber. Expand → confirm strip shows `2·rB − rF − rK` near reported PTS.
- One row stamped `CURVE`: chip should read 4/5 or 5/5. Expand → strip's PTS-match line shows `(rB − rF) · 100 ≈ PTS`.
- One row stamped `OUTRIGHT`: chip reads 2/2 in muted slate (info tone).
- One row with `package_indicator` true but `package_type` OUTRIGHT (if any): chip should fail the indicator-off check.

For each, hover the chip — the tooltip should list the signals with their detail strings.

**Step 4: Capture browser console**

Open devtools → Console. Confirm no errors / warnings logged from `packageConfidence` or the modified components.

**Step 5: Stop the dev server (Ctrl+C)**

**Step 6: Document results**

Append a brief "verification log" to the design doc (`docs/plans/2026-05-03-package-confidence-design.md`) — bullet what was verified and any caveats. Commit:

```
git commit -am "docs(usd-swaps-tape): package confidence dev-server verification log"
```

---

## Task 13: PR-ready summary

If the user asks for a PR, produce one with:

- Title: `feat(usd-swaps-tape): per-package confidence scoring`
- Summary bullets:
  - New pure-fn scorer (`utils/packageConfidence.ts`) with type-specific signals.
  - Compact `X/N ✓` chip in `Pkg` column + breakdown strip in row expansion.
  - Tunable tolerances via `PACKAGE_CONFIDENCE_TOLERANCES`.
- Test plan checklist:
  - [ ] `npm test -- --testPathPatterns=usd-swaps-tape-v2` passes.
  - [ ] Dev-server smoke test confirmed FLY/CURVE/OUTRIGHT confidence values.
  - [ ] Tooltip on chip lists signal labels + computed numbers.
