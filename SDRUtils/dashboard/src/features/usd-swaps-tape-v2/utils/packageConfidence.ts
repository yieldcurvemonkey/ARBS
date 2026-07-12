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
   * Deprecated: previously held a heuristic override of resolvedType
   * (SPREADOVER_FLY → FLY, SPREADOVER_CURVE → CURVE) when the per-leg
   * PTS profile looked identical to the package PTS. The override has
   * been removed — the Python detector now authoritatively tags genuine
   * spreadover-curves, so the badge should always trust the stored
   * package_type. Always null; kept on the type so downstream call
   * sites' `inferredType ?? package_type` fallbacks keep working
   * without a signature change.
   */
  inferredType: string | null
  /** Always null now that the inferredType override has been removed. */
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

/** Pass when all legs have similar absolute DV01 (risk) values. */
function riskBalanceSignal(
  legs: UsdSwapTapeLeg[],
  _weights: number[],
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
  const absRisks = risks.map((r) => Math.abs(r as number))
  const avg = absRisks.reduce((a, b) => a + b, 0) / absRisks.length
  if (avg <= 0) {
    return {
      name: 'risk_balance',
      label,
      passed: false,
      detail: 'zero risk',
    }
  }
  const maxDelta = Math.max(...absRisks.map((r) => Math.abs(r - avg)))
  const rel = maxDelta / avg
  return {
    name: 'risk_balance',
    label,
    passed: rel <= rel_tol,
    detail: `Δ ${(rel * 100).toFixed(1)}% (tol ${(rel_tol * 100).toFixed(0)}%)`,
  }
}

function flyRiskBalanceSignal(
  legs: UsdSwapTapeLeg[],
  tol: Tolerances,
): ConfidenceSignal {
  const rel_tol = tol.riskBalanceRel
  const risks = legs.slice(0, 3).map((l) => legNumberOr(l, 'risk'))
  if (risks.length < 3 || risks.some((r) => r === null)) {
    return {
      name: 'risk_balance',
      label: 'Risk balance (belly = 2x wing)',
      passed: false,
      detail: 'leg risk missing',
    }
  }

  const [frontAbs, bellyAbs, backAbs] = risks.map((r) => Math.abs(r as number))
  const wingDenom = Math.max(frontAbs, backAbs, 1e-9)
  const wingRel = Math.abs(frontAbs - backAbs) / wingDenom
  const wingAvg = (frontAbs + backAbs) / 2
  const expectedBelly = 2 * wingAvg
  const bellyDenom = Math.max(bellyAbs, expectedBelly, 1e-9)
  const bellyRel = Math.abs(bellyAbs - expectedBelly) / bellyDenom

  return {
    name: 'risk_balance',
    label: 'Risk balance (belly = 2x wing)',
    passed: wingRel <= rel_tol && bellyRel <= rel_tol,
    detail: `wings delta ${(wingRel * 100).toFixed(1)}%, belly delta ${(bellyRel * 100).toFixed(1)}% (tol ${(rel_tol * 100).toFixed(0)}%)`,
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

/**
 * Scale factors we accept when deciding whether two values "match up
 * to a clean order of magnitude". Order matters — 1 is checked first
 * so an exact match wins over a 100× match when both pass.
 *
 * The cases we're trying to absorb:
 *   100 / 0.01      decimal ↔ percent  (1 decimal = 100%, 1% = 0.01)
 *   10000 / 0.0001  decimal ↔ bps      (1 decimal = 10000bp, 1bp = 0.0001)
 *   100 / 0.01      percent ↔ bps      (1% = 100bp)
 *   1000 / 0.001    catch-all for misencoded prints we've seen in the
 *                   wild (e.g. accidental ÷1000 from a units widget)
 */
const PTS_SCALE_FACTORS: readonly number[] = [
  1, 10, 0.1, 100, 0.01, 1000, 0.001, 10_000, 0.0001,
] as const

type ScaleMatch = {
  factor: number
  /** |a - b * factor|, so the residual after applying the scale. */
  residual: number
}

/**
 * Relative tolerance applied when checking factor ≠ 1 matches. Held
 * tight (5%) so a unit-mismatch (which would produce residual = 0)
 * passes cleanly while random noise across orders of magnitude
 * doesn't sneak through.
 */
const SCALE_REL_TOL = 0.05

/**
 * Try to express `a` as `b * factor` for any factor in `scales`.
 * Returns the best (smallest-residual) match or null.
 *
 * Tolerance is split: the factor=1 case uses the absolute `tol`
 * (preserves existing PTS-match semantics — sub-bp slack on
 * sub-bp values). All non-1 factors use a relative tolerance
 * (|a - b·f| / max(|a|, |b·f|) ≤ SCALE_REL_TOL) because absolute
 * slack at one scale is enormous slack at another and would
 * false-positive on random noise.
 *
 * `b === 0` short-circuits to a direct |a| ≤ tol check at factor 1
 * so we don't divide-by-zero our way into a misleading match.
 */
function findScaleMatch(
  a: number,
  b: number,
  tol: number,
  scales: readonly number[] = PTS_SCALE_FACTORS,
): ScaleMatch | null {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  if (b === 0) {
    return Math.abs(a) <= tol ? { factor: 1, residual: Math.abs(a) } : null
  }
  let best: ScaleMatch | null = null
  for (const f of scales) {
    const scaled = b * f
    const residual = Math.abs(a - scaled)
    let fits = false
    if (f === 1) {
      fits = residual <= tol
    } else {
      const denom = Math.max(Math.abs(a), Math.abs(scaled))
      // Guard the division: if both sides round to ~0, fall back to
      // absolute-tolerance even for non-1 factors.
      fits = denom < 1e-12 ? residual <= tol : residual / denom <= SCALE_REL_TOL
    }
    if (fits) {
      if (best === null || residual < best.residual) {
        best = { factor: f, residual }
      }
    }
  }
  return best
}

/**
 * Pass when derived spread (in bp) is within ptsMatchBp of reported
 * PTS — directly OR up to a clean order-of-magnitude scale factor.
 *
 * Rationale: PTS in the SDR feed is recorded in inconsistent units
 * (sometimes decimal, sometimes percent, sometimes bps). The legs'
 * `fixed_rate` units we derive from also drift between decimal and
 * percent forms. When derived and reported differ only by a clean
 * factor of 100 / 10000 / etc., it's a unit-encoding mismatch and the
 * underlying spread actually agrees — the override should still fire
 * but the detail string surfaces the implied scale so an analyst can
 * audit the call.
 */
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
  const directDelta = Math.abs(derivedBp - reported)
  const scale = findScaleMatch(derivedBp, reported, bp_tol)
  if (scale && scale.factor !== 1 && scale.residual < directDelta) {
    return {
      name: 'pts_match',
      label: 'PTS match',
      passed: true,
      detail: `derived ${formatBp(derivedBp)}bp vs reported ${formatBp(reported)}bp matches at ${scale.factor}× scale (Δ ${formatBp(scale.residual)}, tol ±${bp_tol}); likely unit mismatch (decimal/percent/bps)`,
    }
  }
  if (directDelta <= bp_tol) {
    return {
      name: 'pts_match',
      label: 'PTS match',
      passed: true,
      detail: `derived ${formatBp(derivedBp)}bp vs reported ${formatBp(reported)}bp (Δ ${formatBp(directDelta)}, tol ±${bp_tol})`,
    }
  }
  if (scale && scale.factor !== 1) {
    return {
      name: 'pts_match',
      label: 'PTS match',
      passed: true,
      detail: `derived ${formatBp(derivedBp)}bp vs reported ${formatBp(reported)}bp matches at ${scale.factor}× scale (Δ ${formatBp(scale.residual)}, tol ±${bp_tol}); likely unit mismatch (decimal/percent/bps)`,
    }
  }
  return {
    name: 'pts_match',
    label: 'PTS match',
    passed: false,
    detail: `derived ${formatBp(derivedBp)}bp vs reported ${formatBp(reported)}bp (Δ ${formatBp(directDelta)}, tol ±${bp_tol})`,
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

function fixedRateSpreadToBp(
  spread: number,
  rates: Array<number | null>,
): number {
  const finiteRates = rates.filter(
    (r): r is number => r !== null && Number.isFinite(r),
  )
  if (!finiteRates.length) return spread * 100
  const maxAbsRate = Math.max(...finiteRates.map((r) => Math.abs(r)))
  // fixed_rate arrives as either decimal rates (0.0384) or percent points
  // (3.84). Convert the derived spread into bp using the observed leg unit.
  return spread * (maxAbsRate < 1 ? 10_000 : 100)
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
    rF !== null && rB !== null && rK !== null
      ? fixedRateSpreadToBp(2 * rB - rF - rK, [rF, rB, rK])
      : null

  // Risk balance for fly: belly risk should be about 2x a single wing,
  // with front/back wings similar. Use magnitudes because some SDR rows
  // report every leg risk with the same sign.
  return [
    {
      name: 'package_indicator_on',
      label: 'Package indicator',
      passed: indicatorOn,
      detail: indicatorOn ? 'true' : 'broker did not flag as a package',
    },
    flyRiskBalanceSignal(legs, tol),
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
  const derivedBp =
    r1 !== null && r2 !== null
      ? fixedRateSpreadToBp(r2 - r1, [r1, r2])
      : null

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
  return {
    score,
    total,
    tone,
    signals,
    resolvedType,
    inferredType: null,
    inferredTypeReason: null,
  }
}
