import { query } from '@/lib/db'
import type {
  UstsRvSnapshotRequest,
  UstsRvSnapshotResponse,
  UstsRvPoint,
  UstsRvValueColumn,
  UstsRvXColumn
} from '@/features/usts-rv/types'

const POINTS_TABLE = 'arbs_ust_rv_points_v1'

const AVAILABLE_VALUE_COLUMNS: UstsRvValueColumn[] = [
  'mmss',
  'ytm',
  'clean_price',
  'dirty_price',
  'mdur',
  'coupon',
  'carry_bps',
  'roll_bps',
  'carry_and_roll_bps'
]

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

function rowToPoint(row: Record<string, unknown>): UstsRvPoint {
  return {
    cusip: String(row.cusip ?? ''),
    ust_label: toSafeString(row.ust_label),
    oi: toSafeString(row.oi),
    rank: toSafeNumber(row.rank),
    ttm: toSafeNumber(row.ttm),
    mdur: toSafeNumber(row.mdur),
    ytm: toSafeNumber(row.ytm),
    mmss: toSafeNumber(row.mmss),
    clean_price: toSafeNumber(row.clean_price),
    dirty_price: toSafeNumber(row.dirty_price),
    coupon: toSafeNumber(row.coupon),
    carry_bps: toSafeNumber(row.carry_bps),
    roll_bps: toSafeNumber(row.roll_bps),
    carry_and_roll_bps: toSafeNumber(row.carry_and_roll_bps),
    issue_date: toSafeString(row.issue_date),
    maturity_date: toSafeString(row.maturity_date),
    market_timestamp: toSafeString(row.market_timestamp)
  }
}

export async function getUstsRvSnapshot(
  req: UstsRvSnapshotRequest
): Promise<UstsRvSnapshotResponse> {
  const curveName = req.curveName || 'USD-SOFR-1D'
  const minTtm = req.minTtm ?? 1.0
  const xColumn: UstsRvXColumn | string = req.xColumn || 'ttm'
  const includeValues = req.includeValues || ['mmss', 'ytm']

  const targetAsOf = req.asOf || new Date().toISOString().slice(0, 10)

  // Find the best as_of_date
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
  if (asOfStr !== targetAsOf) {
    warnings.push(`Using DB snapshot asOf ${asOfStr} for requested ${targetAsOf}.`)
  }

  const pointsResult = await query(
    `SELECT
       cusip, oi, ust_label, rank, ttm, mdur, ytm, mmss,
       clean_price, dirty_price, coupon,
       carry_bps, roll_bps, carry_and_roll_bps,
       issue_date, maturity_date, market_timestamp, snapshot_ts
     FROM ${POINTS_TABLE}
     WHERE curve_name = $1 AND as_of_date = $2
       AND (ttm IS NULL OR ttm >= $3)
     ORDER BY ttm NULLS LAST, oi NULLS LAST, rank NULLS LAST, cusip`,
    [curveName, selectedAsOf, minTtm]
  )

  const points: UstsRvPoint[] = pointsResult.rows.map(rowToPoint)

  return {
    requestedAsOf: targetAsOf,
    asOf: asOfStr,
    requestedLive: targetAsOf === new Date().toISOString().slice(0, 10),
    curveName,
    xColumn,
    includeValues,
    availableValueColumns: AVAILABLE_VALUE_COLUMNS,
    points,
    splineSeries: [],
    meta: {
      asOf: asOfStr,
      pointCount: points.length,
      curveName,
      warnings
    }
  }
}

function formatDate(val: unknown): string {
  if (val instanceof Date) return val.toISOString().slice(0, 10)
  return String(val).slice(0, 10)
}
