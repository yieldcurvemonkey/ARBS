// Scale-aware bp rendering for the Package Transaction Spread (PTS) and the
// derived rate spread. SDR PTS values arrive in inconsistent units (decimal
// fraction, percent, or bps), so we anchor the scale to the legs' fixed-rate
// spread: a curve/fly PTS that ties out to the derived spread at a clean scale
// factor is shown in bp at that factor; a single spreadover (no counter-leg)
// falls back to a magnitude band. Mirrors SDRUtils/core/pts_scale.py.
import type { UsdSwapTapeRow } from '../types'
import { EMPTY_VALUE } from '../constants'

const PTS_SCALE_FACTORS = [1, 10, 0.1, 100, 0.01, 1000, 0.001, 10_000, 0.0001]
const SCALE_REL_TOL = 0.05
const DEFAULT_BP_TOL = 0.5

function isFiniteNum(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

export function findScaleMatch(
  a: number,
  b: number,
  tol = DEFAULT_BP_TOL,
): { factor: number; residual: number } | null {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  if (b === 0) return Math.abs(a) <= tol ? { factor: 1, residual: Math.abs(a) } : null
  let best: { factor: number; residual: number } | null = null
  for (const f of PTS_SCALE_FACTORS) {
    const scaled = b * f
    const residual = Math.abs(a - scaled)
    const fits =
      f === 1
        ? residual <= tol
        : (() => {
            const denom = Math.max(Math.abs(a), Math.abs(scaled))
            return denom < 1e-12 ? residual <= tol : residual / denom <= SCALE_REL_TOL
          })()
    if (fits && (best === null || residual < best.residual)) best = { factor: f, residual }
  }
  return best
}

/** Convert a fixed-rate spread to bp, auto-detecting decimal vs percent rates. */
export function fixedRateSpreadToBp(spread: number, rates: Array<number | null | undefined>): number {
  const finite = rates.filter(isFiniteNum) as number[]
  if (finite.length === 0) return spread * 100
  return spread * (Math.max(...finite.map((r) => Math.abs(r))) < 1 ? 10_000 : 100)
}

function structureKind(row: UsdSwapTapeRow): string {
  return String(row.package_type ?? row.trade_type ?? '').toUpperCase()
}

function isSpreadStructure(kind: string): boolean {
  return (
    kind === 'CURVE' ||
    kind === 'FLY' ||
    kind.endsWith('_CURVE') ||
    kind.endsWith('_FLY')
  )
}

/** Derived rate spread in bp for a curve/fly, given the already-computed
 *  summary rate spread (back-front for curves, 2·belly-wings for flies) and the
 *  legs' fixed rates. Null for non-spread structures or missing data. */
export function derivedSpreadBp(
  row: UsdSwapTapeRow,
  summaryRate: number | null,
): number | null {
  if (!isSpreadStructure(structureKind(row)) || !isFiniteNum(summaryRate)) return null
  const rates = (row.legs_json ?? []).map((l) => l?.fixed_rate ?? null)
  return fixedRateSpreadToBp(summaryRate, rates)
}

/** Reported PTS expressed in bp. When a derived spread is available (curve/fly)
 *  the scale is chosen to tie out to it; otherwise a magnitude band is used
 *  (|pts|<=0.01 -> decimal ×10000, 0.10<=|pts|<=1.0 -> percent ×100). */
export function ptsInBp(pts: number | null | undefined, derivedBp: number | null): number | null {
  if (!isFiniteNum(pts)) return null
  if (pts === 0) return 0
  if (derivedBp !== null && Number.isFinite(derivedBp)) {
    const m = findScaleMatch(Math.abs(derivedBp), Math.abs(pts))
    if (m) return pts * m.factor
  }
  const a = Math.abs(pts)
  if (a <= 0.01) return pts * 10_000
  if (a >= 0.1 && a <= 1.0) return pts * 100
  if (a > 1.0 && a <= 100) return pts // already bp-scale
  return null
}

export function formatBp(n: number | null): string {
  if (n === null || !Number.isFinite(n)) return EMPTY_VALUE
  // Show up to 3 decimals (4 for sub-bp values) so precise ties read as
  // "12.755bps", then trim trailing zeros so round values read as "33.3bps".
  const a = Math.abs(n)
  const digits = a !== 0 && a < 1 ? 4 : 3
  let s = n.toFixed(digits)
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '')
  return `${s}bps`
}
