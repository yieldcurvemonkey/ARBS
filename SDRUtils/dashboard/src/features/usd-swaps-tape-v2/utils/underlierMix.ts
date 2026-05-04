// ABOUTME: Aggregates loaded tape rows into per-canonical-bucket
// volume slices. Powers the AnalyticsPanel "Underlier mix" card —
// stacked-bar style breakdown of trade count / Σ|risk| / Σnotional /
// package-adjusted DV01 by canonical underlier (SOFR-OIS, Term-SOFR,
// Fed-Funds-OIS, OBFR-OIS, etc). Pure-frontend so it shows up
// instantly when the user pivots windows; no extra API roundtrip.

import type { UsdSwapTapeRow } from '../types'
import { computePackageAdjustedDv01 } from './packageAdjustedDv01'

export type UnderlierMixMetric = 'count' | 'risk' | 'notional' | 'pa_dv01'

export type UnderlierMixWindow = 'today' | '7d' | '30d' | '90d' | 'YTD'

export type UnderlierMixSlice = {
  /** Canonical bucket key (UNKNOWN if no canonical_underlier_key was set). */
  key: string
  /** Aggregated value in metric units. */
  value: number
  /** Share of total in [0,1]. NaN if total is zero. */
  share: number
  /** Number of underlying rows that fed this bucket (always count). */
  rowCount: number
}

const MS_PER_DAY = 24 * 60 * 60 * 1000

function rowCanonicalKey(row: UsdSwapTapeRow): string {
  if (typeof row.canonical_underlier_key === 'string' && row.canonical_underlier_key) {
    return row.canonical_underlier_key
  }
  const firstLeg = row.legs_json?.[0]
  if (firstLeg?.canonical_underlier_key) {
    return firstLeg.canonical_underlier_key
  }
  return 'UNKNOWN'
}

function rowMetricValue(row: UsdSwapTapeRow, metric: UnderlierMixMetric): number {
  if (metric === 'count') return 1
  if (metric === 'risk') return Math.abs(Number(row.total_risk ?? 0))
  if (metric === 'notional') return Math.abs(Number(row.total_notional ?? 0))
  // pa_dv01 — prefer the materialised column when present, otherwise
  // fall back to the client-side helper so the card works against rows
  // produced before the API materialiser ships.
  return row.package_adjusted_dv01 ?? computePackageAdjustedDv01(row) ?? 0
}

export function computeUnderlierMix(
  rows: readonly UsdSwapTapeRow[],
  metric: UnderlierMixMetric,
): UnderlierMixSlice[] {
  if (rows.length === 0) return []
  const bucketed = new Map<string, { value: number; rowCount: number }>()
  for (const row of rows) {
    const key = rowCanonicalKey(row)
    const value = rowMetricValue(row, metric)
    const existing = bucketed.get(key) ?? { value: 0, rowCount: 0 }
    existing.value += value
    existing.rowCount += 1
    bucketed.set(key, existing)
  }
  const total = Array.from(bucketed.values()).reduce((a, b) => a + b.value, 0)
  const slices: UnderlierMixSlice[] = Array.from(bucketed.entries()).map(
    ([key, agg]) => ({
      key,
      value: agg.value,
      rowCount: agg.rowCount,
      share: total > 0 ? agg.value / total : Number.NaN,
    }),
  )
  slices.sort((a, b) => b.value - a.value)
  return slices
}

export function filterRowsToWindow(
  rows: readonly UsdSwapTapeRow[],
  window: UnderlierMixWindow,
  nowMs: number = Date.now(),
): UsdSwapTapeRow[] {
  if (window === 'YTD') {
    const yearStart = new Date(nowMs)
    yearStart.setUTCMonth(0, 1)
    yearStart.setUTCHours(0, 0, 0, 0)
    const cutoff = yearStart.getTime()
    return rows.filter((r) => {
      const ts = r.execution_start ? Date.parse(r.execution_start) : NaN
      return Number.isFinite(ts) && ts >= cutoff
    })
  }
  let cutoff: number
  if (window === 'today') {
    const todayStart = new Date(nowMs)
    todayStart.setUTCHours(0, 0, 0, 0)
    cutoff = todayStart.getTime()
  } else {
    const days = window === '7d' ? 7 : window === '30d' ? 30 : 90
    cutoff = nowMs - days * MS_PER_DAY
  }
  return rows.filter((r) => {
    const ts = r.execution_start ? Date.parse(r.execution_start) : NaN
    return Number.isFinite(ts) && ts >= cutoff
  })
}
