// ABOUTME: USD-only RFR Adoption indicator (design-doc §4.2 + §5.4 +
// Clarus's "Recreating the RFR Adoption Indicator" 2025-04-29). Numerator =
// ΣDV01 across SOFR-OIS / Term-SOFR / Fed-Funds-OIS / OBFR-OIS;
// Denominator = numerator + LIBOR (legacy + synthetic) + BSBY. Returns
// a single point ratio + monthly time-series for sparkline rendering.

import type { UsdSwapTapeRow } from '../types'

export const RFR_NUMERATOR_KEYS: readonly string[] = [
  'USD/SOFR-OIS/COMPOUND',
  'USD/SOFR-TERM',
  'USD/FED-FUNDS-OIS/COMPOUND',
  'USD/OBFR-OIS/COMPOUND',
]

export const RFR_DENOMINATOR_KEYS: readonly string[] = [
  ...RFR_NUMERATOR_KEYS,
  'USD/LIBOR/IBOR',
  'USD/BSBY/IBOR',
]

const NUM_SET = new Set(RFR_NUMERATOR_KEYS)
const DENOM_SET = new Set(RFR_DENOMINATOR_KEYS)

export type RfrAdoptionRatio = {
  ratio: number
  numerator: number
  denominator: number
}

function rowCanonicalKey(row: UsdSwapTapeRow): string | null {
  if (typeof row.canonical_underlier_key === 'string' && row.canonical_underlier_key) {
    return row.canonical_underlier_key
  }
  return row.legs_json?.[0]?.canonical_underlier_key ?? null
}

function rowAbsRisk(row: UsdSwapTapeRow): number {
  const v = Number(row.total_risk ?? 0)
  if (Number.isFinite(v)) return Math.abs(v)
  return 0
}

export function computeRfrAdoptionRatio(
  rows: readonly UsdSwapTapeRow[],
): RfrAdoptionRatio {
  let numerator = 0
  let denominator = 0
  for (const row of rows) {
    const key = rowCanonicalKey(row)
    if (!key || !DENOM_SET.has(key)) continue
    const risk = rowAbsRisk(row)
    denominator += risk
    if (NUM_SET.has(key)) numerator += risk
  }
  const ratio = denominator > 0 ? numerator / denominator : Number.NaN
  return { ratio, numerator, denominator }
}

export type RfrAdoptionMonthlyPoint = {
  /** ISO month "YYYY-MM". */
  month: string
  ratio: number
  numerator: number
  denominator: number
}

function monthBucket(timestamp: string | null | undefined): string | null {
  if (!timestamp) return null
  const ms = Date.parse(timestamp)
  if (!Number.isFinite(ms)) return null
  const d = new Date(ms)
  const yyyy = String(d.getUTCFullYear()).padStart(4, '0')
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  return `${yyyy}-${mm}`
}

export function computeRfrAdoptionMonthly(
  rows: readonly UsdSwapTapeRow[],
): RfrAdoptionMonthlyPoint[] {
  const map = new Map<string, { numerator: number; denominator: number }>()
  for (const row of rows) {
    const key = rowCanonicalKey(row)
    if (!key || !DENOM_SET.has(key)) continue
    const month = monthBucket(row.execution_start)
    if (!month) continue
    const risk = rowAbsRisk(row)
    const cur = map.get(month) ?? { numerator: 0, denominator: 0 }
    cur.denominator += risk
    if (NUM_SET.has(key)) cur.numerator += risk
    map.set(month, cur)
  }
  const out: RfrAdoptionMonthlyPoint[] = []
  for (const [month, agg] of map.entries()) {
    const ratio = agg.denominator > 0 ? agg.numerator / agg.denominator : Number.NaN
    out.push({ month, ratio, numerator: agg.numerator, denominator: agg.denominator })
  }
  out.sort((a, b) => a.month.localeCompare(b.month))
  return out
}
