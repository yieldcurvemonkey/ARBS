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

// `UsdSwapTapeLeg` and `PACKAGE_CONFIDENCE_TOLERANCES` are imported for
// the scorer expansions in Task 3+ (CURVE/FLY/etc.). The references below
// keep the imports active so lint does not strip them between tasks.
export type { UsdSwapTapeLeg }

void PACKAGE_CONFIDENCE_TOLERANCES

export function computePackageConfidence(row: UsdSwapTapeRow): PackageConfidence {
  const resolvedType = normalizeType(row.package_type)
  const signals: ConfidenceSignal[] = outrightSignals(row)
  const score = signals.filter((s) => s.passed).length
  const total = signals.length
  const tone = pickTone(score, total, /*isInfo=*/ true)
  return { score, total, tone, signals, resolvedType }
}
