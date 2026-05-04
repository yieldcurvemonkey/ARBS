// ABOUTME: Per-row package-adjusted DV01 (Clarus's preferred volume
// metric — see design-doc §3.1 / §5.1). Raw |risk| triple-counts a
// 5/10/30 fly because each leg shows up as a separate row in the SDR
// feed; analytics that bucket by package_id need to divide by the leg
// count so the broker fee proxy isn't inflated. Composite types
// (SPREADOVER_*, MATCHED_MATURITY_*) include the UST hedge in the
// denominator because the broker collects fee on the bundle, not the
// swap legs alone.

import type { UsdSwapTapeRow } from '../types'

const SWAP_LEG_COUNT_BY_BASE: Record<string, number> = {
  OUTRIGHT: 1,
  CURVE: 2,
  FLY: 3,
}

function baseTypeOf(packageType: string | null | undefined): string {
  const upper = String(packageType ?? '').toUpperCase()
  if (upper.endsWith('_FLY')) return 'FLY'
  if (upper.endsWith('_CURVE')) return 'CURVE'
  if (upper === 'SPREADOVER' || upper === 'MATCHED_MATURITY') return 'OUTRIGHT'
  return upper || 'OUTRIGHT'
}

function isCompositeWithHedge(packageType: string | null | undefined): boolean {
  const upper = String(packageType ?? '').toUpperCase()
  return (
    upper === 'SPREADOVER' ||
    upper === 'MATCHED_MATURITY' ||
    upper.startsWith('SPREADOVER_') ||
    upper.startsWith('MATCHED_MATURITY_')
  )
}

/**
 * Returns the leg-count denominator the package-adjusted DV01 divides
 * by. Uses package_type alone so the result is stable when legs_json
 * is partially populated (e.g. a UST leg ingest race).
 */
export function packageAdjustedDv01Denominator(
  packageType: string | null | undefined,
  legsCount: number,
): number {
  const upper = String(packageType ?? '').toUpperCase()
  if (upper in SWAP_LEG_COUNT_BY_BASE) {
    return SWAP_LEG_COUNT_BY_BASE[upper]
  }
  if (isCompositeWithHedge(upper)) {
    const swapLegs = SWAP_LEG_COUNT_BY_BASE[baseTypeOf(upper)] ?? 1
    // +1 for the UST hedge leg. Trust the SDR row's reported leg
    // count when it is larger (e.g. multi-tenor invoice trades that
    // still get tagged SPREADOVER_CURVE).
    const denom = swapLegs + 1
    return Math.max(denom, legsCount)
  }
  return Math.max(1, legsCount)
}

function absOrNull(n: unknown): number | null {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null
  return Math.abs(n)
}

/**
 * Sum of |risk| across legs / denom, where denom mirrors the broker-fee
 * convention (one fee per package, not per leg). Returns null when no
 * leg has a numeric risk and the row's package-level total_risk is
 * also missing.
 */
export function computePackageAdjustedDv01(row: UsdSwapTapeRow): number | null {
  const legs = row.legs_json ?? []
  const legRisks = legs
    .map((l) => absOrNull((l as { risk?: number | null }).risk))
    .filter((v): v is number => typeof v === 'number')

  if (legRisks.length === 0) {
    const total = absOrNull(row.total_risk ?? row.gross_risk ?? null)
    if (total == null) return null
    const denom = packageAdjustedDv01Denominator(
      row.package_type ?? null,
      Math.max(1, row.legs_count ?? 1),
    )
    return total / denom
  }

  const denom = packageAdjustedDv01Denominator(
    row.package_type ?? null,
    legRisks.length,
  )
  const sum = legRisks.reduce((a, b) => a + b, 0)
  return sum / denom
}
