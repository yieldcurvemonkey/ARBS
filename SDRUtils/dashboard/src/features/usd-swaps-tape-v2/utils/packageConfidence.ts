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

export function computePackageConfidence(row: UsdSwapTapeRow): PackageConfidence {
  const resolvedType = normalizeType(row.package_type)
  let signals: ConfidenceSignal[]
  let isInfo = false
  switch (resolvedType) {
    case 'CURVE':
      signals = curveSignals(row)
      break
    case 'FLY':
      signals = flySignals(row)
      break
    case 'SPREADOVER':
      signals = spreadOverSignals(row)
      break
    case 'MATCHED_MATURITY':
      signals = matchedMaturitySignals(row)
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
