import { query } from '@/lib/db'
import type {
  UstsRvTimeseriesRequest,
  UstsRvTimeseriesResponse,
  UstsRvTimeseriesSeries,
  UstsRvTimeseriesPoint,
  UstsRvValueColumn
} from '@/features/usts-rv/types'

const POINTS_TABLE = 'arbs_ust_rv_points_v1'

const VALUE_SQL_COLUMN: Record<UstsRvValueColumn, string> = {
  mmss: 'mmss',
  ytm: 'ytm',
  clean_price: 'clean_price',
  dirty_price: 'dirty_price',
  mdur: 'mdur',
  coupon: 'coupon',
  carry_bps: 'carry_bps',
  roll_bps: 'roll_bps',
  carry_and_roll_bps: 'carry_and_roll_bps'
}

const CT_RE = /^CT(\d{1,2})$/i

function toSafeNumber(val: unknown): number | null {
  if (val === null || val === undefined) return null
  const n = Number(val)
  return Number.isFinite(n) ? n : null
}

function toSafeString(val: unknown): string | null {
  if (val === null || val === undefined) return null
  if (val instanceof Date) return val.toISOString()
  return String(val)
}

function formatDate(val: unknown): string {
  if (val instanceof Date) return val.toISOString().slice(0, 10)
  return String(val).slice(0, 10)
}

export async function getUstsRvTimeseries(
  req: UstsRvTimeseriesRequest
): Promise<UstsRvTimeseriesResponse> {
  const curveName = req.curveName || 'USD-SOFR-1D'
  const valueColumn = req.valueColumn || 'ytm'
  const sqlCol = VALUE_SQL_COLUMN[valueColumn]
  if (!sqlCol) {
    throw new Error(`Unknown valueColumn: ${valueColumn}`)
  }

  const cusips = req.cusips || []
  if (!cusips.length) {
    return {
      requestedAsOf: req.asOf || new Date().toISOString().slice(0, 10),
      asOf: req.asOf || new Date().toISOString().slice(0, 10),
      requestedLive: false,
      curveName,
      valueColumn,
      startDate: null,
      endDate: null,
      series: [],
      meta: { seriesCount: 0, totalPoints: 0, warnings: [] }
    }
  }

  const targetAsOf = req.asOf || new Date().toISOString().slice(0, 10)
  const lookbackDays = req.lookbackDays ?? 365

  // Resolve latest as_of
  const asOfResult = await query(
    `SELECT MAX(as_of_date) AS as_of_date FROM ${POINTS_TABLE}
     WHERE curve_name = $1 AND as_of_date <= $2::date`,
    [curveName, targetAsOf]
  )
  let selectedAsOf = asOfResult.rows[0]?.as_of_date
  const warnings: string[] = []

  if (!selectedAsOf) {
    const latestResult = await query(
      `SELECT MAX(as_of_date) AS as_of_date FROM ${POINTS_TABLE} WHERE curve_name = $1`,
      [curveName]
    )
    selectedAsOf = latestResult.rows[0]?.as_of_date
    if (selectedAsOf) {
      warnings.push(
        `No DB snapshot found on/before ${targetAsOf}; using latest available ${formatDate(selectedAsOf)}.`
      )
    }
  }

  if (!selectedAsOf) {
    throw new Error(
      `No UST RV snapshots found in table '${POINTS_TABLE}' for curve '${curveName}'.`
    )
  }

  const asOfStr = formatDate(selectedAsOf)

  // Compute date range
  let startDate = req.startDate || null
  let endDate = req.endDate || asOfStr
  if (!startDate) {
    const d = new Date(endDate)
    d.setDate(d.getDate() - lookbackDays)
    startDate = d.toISOString().slice(0, 10)
  }

  // Split cusips into real CUSIPs and CT aliases
  const realCusips: string[] = []
  const ctAliases: Map<string, number> = new Map()
  for (const c of cusips) {
    const ctMatch = c.match(CT_RE)
    if (ctMatch) {
      ctAliases.set(c.toUpperCase(), Number(ctMatch[1]))
    } else {
      realCusips.push(c)
    }
  }

  const series: UstsRvTimeseriesSeries[] = []

  // Fetch real CUSIP timeseries
  if (realCusips.length) {
    const result = await query(
      `SELECT cusip, oi, ust_label, rank, as_of_date, ${sqlCol} AS value, snapshot_ts
       FROM ${POINTS_TABLE}
       WHERE curve_name = $1
         AND cusip = ANY($2)
         AND as_of_date BETWEEN $3::date AND $4::date
       ORDER BY cusip, as_of_date`,
      [curveName, realCusips, startDate, endDate]
    )

    const byCusip = new Map<string, { oi: string | null; ust_label: string | null; rank: number | null; points: UstsRvTimeseriesPoint[] }>()
    for (const row of result.rows) {
      const cusip = String(row.cusip)
      if (!byCusip.has(cusip)) {
        byCusip.set(cusip, {
          oi: toSafeString(row.oi),
          ust_label: toSafeString(row.ust_label),
          rank: toSafeNumber(row.rank),
          points: []
        })
      }
      byCusip.get(cusip)!.points.push({
        asOf: formatDate(row.as_of_date),
        value: toSafeNumber(row.value),
        snapshotTs: toSafeString(row.snapshot_ts)
      })
    }

    for (const cusip of realCusips) {
      const data = byCusip.get(cusip)
      series.push({
        cusip,
        ust_label: data?.ust_label ?? null,
        oi: data?.oi ?? null,
        rank: data?.rank ?? null,
        points: data?.points ?? []
      })
    }
  }

  // Fetch CT alias timeseries (rank=0 OTR for the tenor)
  for (const [alias, tenor] of ctAliases) {
    const result = await query(
      `SELECT cusip, oi, ust_label, rank, as_of_date, ${sqlCol} AS value, snapshot_ts
       FROM ${POINTS_TABLE}
       WHERE curve_name = $1
         AND rank = 0
         AND oi LIKE $2
         AND as_of_date BETWEEN $3::date AND $4::date
       ORDER BY as_of_date`,
      [curveName, `${tenor}-%`, startDate, endDate]
    )

    const points: UstsRvTimeseriesPoint[] = result.rows.map((row: Record<string, unknown>) => ({
      asOf: formatDate(row.as_of_date),
      value: toSafeNumber(row.value),
      snapshotTs: toSafeString(row.snapshot_ts)
    }))

    const firstRow = result.rows[0]
    series.push({
      cusip: alias,
      ust_label: toSafeString(firstRow?.ust_label) || `Constant Maturity ${tenor}Y`,
      oi: toSafeString(firstRow?.oi),
      rank: 0,
      points
    })
  }

  let totalPoints = 0
  for (const s of series) totalPoints += s.points.length

  return {
    requestedAsOf: targetAsOf,
    asOf: asOfStr,
    requestedLive: targetAsOf === new Date().toISOString().slice(0, 10),
    curveName,
    valueColumn,
    startDate,
    endDate,
    series,
    meta: {
      seriesCount: series.length,
      totalPoints,
      warnings
    }
  }
}
