// ABOUTME: Shared SQL fragments, percentile math, and response-shaping
// utilities used by both /volume-grid and /volume-grid/structure. Split
// from route.logic.ts so the structure endpoint can reuse the same CTE
// patterns without duplicating statistical logic.

import type {
  VolumeGridCell,
  VolumeGridResponse,
} from '@/features/usd-swaps-tape-v2/types/volume-grid.types'

export { buildPkgFamilySql } from '@/lib/usd-swaps-tape-v2/volumeGridBuckets'

export const PLATFORM_CASE_SQL = `
  CASE
    WHEN UPPER(COALESCE(l.venue, '')) = 'D2D' THEN 'IDB'
    WHEN UPPER(COALESCE(l.platform_identifier, '')) IN
      ('BGCD', 'DWSF', 'IGDL', 'ISWV', 'TPSE', 'TSEF') THEN 'IDB'
    ELSE 'CUSTY'
  END
`

export interface RawVolumeGridRow {
  fwd: string
  tenor: string
  current_value: number | string
  idb_current: number | string
  custy_current: number | string
  outright_current: number | string
  curve_current: number | string
  fly_current: number | string
  invoice_current: number | string
  other_current: number | string
  trade_count: number | string
  prior_array: Array<number | string>
  p25: number | string
  p50: number | string
  p75: number | string
  pmin: number | string
  pmax: number | string
  n: number | string
  as_of_ts: string | Date | null
}

export const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

export function computePercentile(current: number, prior: ReadonlyArray<number>): number | null {
  if (prior.length === 0) return null
  let lessOrEqual = 0
  for (const v of prior) if (v <= current) lessOrEqual += 1
  return (lessOrEqual / prior.length) * 100
}

export function summariseCells(
  cells: ReadonlyArray<VolumeGridCell>,
): VolumeGridResponse['totals'] {
  const rowTotals: Record<string, { current: number }> = {}
  const colTotals: Record<string, { current: number }> = {}
  let grandCurrent = 0
  for (const c of cells) {
    if (!rowTotals[c.fwd]) rowTotals[c.fwd] = { current: 0 }
    if (!colTotals[c.tenor]) colTotals[c.tenor] = { current: 0 }
    rowTotals[c.fwd].current += c.current
    colTotals[c.tenor].current += c.current
    grandCurrent += c.current
  }
  const wrap = (entry: { current: number }) => ({
    current: entry.current,
    percentile: null as number | null,
  })
  return {
    rowTotals: Object.fromEntries(
      Object.entries(rowTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    colTotals: Object.fromEntries(
      Object.entries(colTotals).map(([k, v]) => [k, wrap(v)]),
    ),
    grand: { current: grandCurrent, percentile: null },
  }
}

/**
 * Convert a single raw SQL row into a typed VolumeGridCell.
 * Extracted from the inline `.map()` in shapeVolumeGridResponse
 * so the structure endpoint can reuse the same conversion logic.
 */
export function rowToCell(r: RawVolumeGridRow): VolumeGridCell {
  const prior = r.prior_array.map(num)
  const current = num(r.current_value)
  return {
    fwd: r.fwd,
    tenor: r.tenor,
    current,
    idbCurrent: num(r.idb_current),
    custyCurrent: num(r.custy_current),
    outrightCurrent: num(r.outright_current),
    curveCurrent: num(r.curve_current),
    flyCurrent: num(r.fly_current),
    invoiceCurrent: num(r.invoice_current),
    otherCurrent: num(r.other_current),
    tradeCount: num(r.trade_count),
    baseline: {
      p25: num(r.p25),
      p50: num(r.p50),
      p75: num(r.p75),
      min: num(r.pmin),
      max: num(r.pmax),
      n: num(r.n),
    },
    percentile: computePercentile(current, prior),
  }
}
