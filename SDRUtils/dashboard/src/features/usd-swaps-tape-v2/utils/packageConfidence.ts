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
  /**
   * Heuristic override of the resolvedType when the per-leg PTS profile
   * looks identical to the package PTS — strong evidence the trade is
   * actually the base type rather than the SPREADOVER_* variant the
   * upstream classifier tagged it with. Null when no override fires.
   * Currently fires for SPREADOVER_FLY → FLY and SPREADOVER_CURVE →
   * CURVE.
   */
  inferredType: string | null
  /** Free-text reason the inferredType override fired (or null). */
  inferredTypeReason: string | null
}

type Tolerances = typeof PACKAGE_CONFIDENCE_TOLERANCES

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
  tol: Tolerances,
): ConfidenceSignal {
  const rel_tol = tol.riskBalanceRel
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
    passed: rel <= rel_tol,
    detail: `Δ ${(rel * 100).toFixed(1)}% (tol ${(rel_tol * 100).toFixed(0)}%)`,
  }
}

/**
 * Render a tiny PTS / derived-spread number with enough precision that
 * sub-bp values (e.g. 0.0000125) don't collapse to "0.00bp" in the UI.
 * Falls back to scientific notation for values ≤ 1e-3 so the breakdown
 * is readable on prints where the spread term is essentially zero.
 */
function formatBp(value: number): string {
  if (!Number.isFinite(value)) return String(value)
  const abs = Math.abs(value)
  if (abs === 0) return '0'
  if (abs < 1e-3) return value.toExponential(3)
  if (abs < 1) return value.toFixed(6).replace(/\.?0+$/, '')
  return value.toFixed(3).replace(/\.?0+$/, '')
}

/** Pass when derived spread (in bp) is within ptsMatchBp of reported PTS. */
function ptsMatchSignal(
  derivedBp: number | null,
  reportedPts: number | null | undefined,
  tol: Tolerances,
): ConfidenceSignal {
  const bp_tol = tol.ptsMatchBp
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
    passed: delta <= bp_tol,
    detail: `derived ${formatBp(derivedBp)}bp vs reported ${formatBp(reported)}bp (Δ ${formatBp(delta)}, tol ±${bp_tol})`,
  }
}

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
          .map((l) => `${l.tenor_years ?? '?'}Y=${formatBp(Number((l as any).package_transaction_spread))}`)
          .join(', ')
      : 'one or more legs missing per-leg PTS',
  }
}

function legPts(leg: UsdSwapTapeLeg): number | null {
  const v = (leg as { package_transaction_spread?: unknown }).package_transaction_spread
  if (v == null) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

/**
 * Decide whether a SPREADOVER_FLY / SPREADOVER_CURVE row is mislabeled
 * and should display as the base type. Triggers when:
 *
 *   1. Every leg has a per-leg PTS populated.
 *   2. Every per-leg PTS equals the package PTS within `ptsMatchBp`.
 *
 * Rationale: a real SPREADOVER package has a UST hedge leg whose
 * implied spread is computed off a different leg's PTS, so per-leg
 * PTS values diverge. When all per-leg PTSes collapse to the package
 * PTS, the upstream classifier almost certainly fired the
 * SPREADOVER_* heuristic on noise — it's a base-type FLY / CURVE.
 */
function inferBaseTypeOverride(
  resolvedType: string,
  row: UsdSwapTapeRow,
  tol: Tolerances,
): { type: string; reason: string } | null {
  if (resolvedType !== 'SPREADOVER_FLY' && resolvedType !== 'SPREADOVER_CURVE') {
    return null
  }
  const legs = (row.legs_json ?? []) as UsdSwapTapeLeg[]
  if (legs.length < 2) return null
  const pkgPts = row.package_transaction_spread
  if (pkgPts == null) return null
  const pkgPtsNum = Number(pkgPts)
  if (!Number.isFinite(pkgPtsNum)) return null
  const perLeg: number[] = []
  for (const leg of legs) {
    const v = legPts(leg)
    if (v == null) return null
    perLeg.push(v)
  }
  const allMatchPackage = perLeg.every(
    (v) => Math.abs(v - pkgPtsNum) <= tol.ptsMatchBp,
  )
  if (!allMatchPackage) return null
  const baseType = resolvedType === 'SPREADOVER_FLY' ? 'FLY' : 'CURVE'
  const formatted = formatBp(pkgPtsNum)
  return {
    type: baseType,
    reason: `every per-leg PTS = ${formatted} matches package PTS = ${formatted} (within ±${tol.ptsMatchBp}bp); SPREADOVER_${baseType === 'FLY' ? 'FLY' : 'CURVE'} hedge leg expected to differ`,
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

function flySignals(row: UsdSwapTapeRow, tol: Tolerances): ConfidenceSignal[] {
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
    riskBalanceSignal(legs.slice(0, 3), [1, 1, 1], 'Risk balance (belly = -2×wings)', tol),
    ptsMatchSignal(derivedBp, row.package_transaction_spread, tol),
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

function curveSignals(row: UsdSwapTapeRow, tol: Tolerances): ConfidenceSignal[] {
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
    riskBalanceSignal(legs.slice(0, 2), [1, 1], 'Risk balance (DV01-neutral)', tol),
    ptsMatchSignal(derivedBp, row.package_transaction_spread, tol),
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

export function computePackageConfidence(
  row: UsdSwapTapeRow,
  toleranceOverrides?: Partial<Tolerances>,
): PackageConfidence {
  const tol: Tolerances = { ...PACKAGE_CONFIDENCE_TOLERANCES, ...(toleranceOverrides ?? {}) }
  const resolvedType = normalizeType(row.package_type)
  let signals: ConfidenceSignal[]
  let isInfo = false
  switch (resolvedType) {
    case 'CURVE':
      signals = curveSignals(row, tol)
      break
    case 'FLY':
      signals = flySignals(row, tol)
      break
    case 'SPREADOVER':
      signals = spreadOverSignals(row)
      break
    case 'MATCHED_MATURITY':
      signals = matchedMaturitySignals(row)
      break
    case 'SPREADOVER_CURVE':
      signals = [
        ...curveSignals(row, tol),
        perLegPtsSignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
      ]
      break
    case 'SPREADOVER_FLY':
      signals = [
        ...flySignals(row, tol),
        perLegPtsSignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
      ]
      break
    case 'MATCHED_MATURITY_CURVE':
      signals = [
        ...curveSignals(row, tol),
        perLegMatchedMaturitySignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
      ]
      break
    case 'MATCHED_MATURITY_FLY':
      signals = [
        ...flySignals(row, tol),
        perLegMatchedMaturitySignal((row.legs_json ?? []) as UsdSwapTapeLeg[]),
      ]
      break
    case 'MAC':
    case 'IMM':
    case 'FOMC':
    case 'OUTRIGHT':
    default:
      signals = outrightSignals(row)
      isInfo = true
      break
  }
  const score = signals.filter((s) => s.passed).length
  const total = signals.length
  const tone = pickTone(score, total, isInfo)
  const override = inferBaseTypeOverride(resolvedType, row, tol)
  if (override) {
    signals = [
      ...signals,
      {
        name: 'inferred_base_type',
        label: `Inferred type: ${override.type}`,
        passed: true,
        detail: override.reason,
      },
    ]
  }
  return {
    score,
    total,
    tone,
    signals,
    resolvedType,
    inferredType: override?.type ?? null,
    inferredTypeReason: override?.reason ?? null,
  }
}
