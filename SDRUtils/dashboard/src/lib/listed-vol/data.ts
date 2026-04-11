import {
  ALL_LISTED_VOL_PRODUCTS,
  LISTED_VOL_LOOKBACK_SESSIONS,
  ROLLING_EXPIRIES,
  STIR_PRODUCTS,
  UST_PRODUCTS
} from '@/features/listed-vol/constants'
import { computeCellHistoryStats, computeStats, filterByRange } from '@/features/listed-vol/analytics'
import type {
  ListedVolComparisonResponse,
  ListedVolComparisonRow,
  ListedVolExpiry,
  ListedVolGridCell,
  ListedVolGridResponse,
  ListedVolHistoryGridResponse,
  ListedVolProduct,
  ListedVolProductClass,
  ListedVolRange,
  ListedVolRealizedRow,
  ListedVolSeriesPoint,
  ListedVolSeriesStats,
  ListedVolTimeseriesResponse
} from '@/features/listed-vol/types'
import { query } from '@/lib/db'

const LISTED_SNAPSHOTS_TABLE = 'arbs_listed_option_vol_snapshots_v1'
const LISTED_COMPARISON_TABLE = 'arbs_listed_vs_swaption_vol_v1'
const REALIZED_SNAPSHOTS_TABLE = 'arbs_realized_vol_snapshots_v1'

type SnapshotRow = {
  as_of_date: string
  product: ListedVolProduct
  product_class: Exclude<ListedVolProductClass, 'ALL'>
  expiry_label: ListedVolExpiry
  atm_nvol_price: number | string | null
  atm_nvol_bps: number | string | null
  forward_price: number | string | null
  forward_yield: number | string | null
  fv01: number | string | null
  underlying_contract: string | null
  source: string | null
}

type HistoryRow = {
  as_of_date: string
  product: ListedVolProduct
  expiry_label: ListedVolExpiry
  atm_nvol_bps: number | string | null
}

type ComparisonRow = {
  as_of_date: string
  product: ListedVolProduct
  expiry_label: ListedVolExpiry
  listed_atm_nvol_bps: number | string | null
  swaption_atmf_nvol_bps: number | string | null
  vol_ratio: number | string | null
  vol_diff_bps: number | string | null
  swaption_expiry_label: string | null
  swaption_tenor_label: string | null
}

type RealizedRow = {
  as_of_date: string
  product: ListedVolProduct
  window_label: ListedVolExpiry
  realized_nvol_bps: number | string | null
  implied_realized_ratio: number | string | null
}

type DateRow = {
  as_of_date: string | null
}

function parseNumber(value: unknown) {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function dateToTimestamp(date: string) {
  return new Date(`${date}T00:00:00Z`).getTime()
}

function productsForClass(productClass: ListedVolProductClass) {
  if (productClass === 'UST') return UST_PRODUCTS
  if (productClass === 'STIR') return STIR_PRODUCTS
  return ALL_LISTED_VOL_PRODUCTS
}

function sortByProductExpiry<T extends { product: ListedVolProduct; expiryLabel: ListedVolExpiry }>(rows: T[]) {
  const productOrder = new Map(ALL_LISTED_VOL_PRODUCTS.map((product, index) => [product, index]))
  const expiryOrder = new Map(ROLLING_EXPIRIES.map((expiry, index) => [expiry, index]))
  return rows.slice().sort((left, right) => {
    const productDiff = (productOrder.get(left.product) ?? 999) - (productOrder.get(right.product) ?? 999)
    if (productDiff !== 0) return productDiff
    return (expiryOrder.get(left.expiryLabel) ?? 999) - (expiryOrder.get(right.expiryLabel) ?? 999)
  })
}

async function resolveAvailableDate(params: {
  requestedDate?: string | null
  products: ListedVolProduct[]
  tableName?: string
}): Promise<string | null> {
  const tableName = params.tableName ?? LISTED_SNAPSHOTS_TABLE
  if (params.requestedDate) {
    const result = await query<DateRow>(
      `
        SELECT MAX(as_of_date)::text AS as_of_date
        FROM ${tableName}
        WHERE product = ANY($1)
          AND as_of_date <= $2
      `,
      [params.products, params.requestedDate]
    )
    return result.rows[0]?.as_of_date ?? null
  }

  const result = await query<DateRow>(
    `
      SELECT MAX(as_of_date)::text AS as_of_date
      FROM ${tableName}
      WHERE product = ANY($1)
    `,
    [params.products]
  )
  return result.rows[0]?.as_of_date ?? null
}

function buildSeriesStats(values: Array<number | null>): ListedVolSeriesStats {
  return computeStats(values)
}

function buildGridCell(
  row: SnapshotRow,
  historyMap: Map<string, Array<{ date: string; value: number | null }>>,
  includeHistory: boolean,
  lookback: number
): ListedVolGridCell {
  const key = `${row.product}_${row.expiry_label}`
  const history = historyMap.get(key) ?? []
  const stats = computeCellHistoryStats(history.map((point) => point.value))
  return {
    asOfDate: row.as_of_date,
    product: row.product,
    productClass: row.product_class,
    expiryLabel: row.expiry_label,
    atmNvolBps: parseNumber(row.atm_nvol_bps),
    atmNvolPrice: parseNumber(row.atm_nvol_price),
    dailyChange: stats.dailyChange,
    zScore: stats.zScore,
    percentile: stats.percentile,
    historyMean: stats.mean,
    historyStd: stats.std,
    forwardPrice: parseNumber(row.forward_price),
    forwardYield: parseNumber(row.forward_yield),
    fv01: parseNumber(row.fv01),
    underlyingContract: row.underlying_contract,
    source: row.source,
    history: includeHistory ? history.slice(-lookback) : undefined
  }
}

export async function fetchListedVolGridData(params: {
  requestedDate?: string | null
  productClass: ListedVolProductClass
  includeHistory?: boolean
  lookback?: number
}): Promise<ListedVolGridResponse> {
  const products = productsForClass(params.productClass)
  const asOfDate = await resolveAvailableDate({
    requestedDate: params.requestedDate,
    products
  })
  if (!asOfDate) {
    throw new Error('No listed vol data available')
  }

  const historyStartDate = new Date(`${asOfDate}T00:00:00Z`)
  historyStartDate.setUTCDate(historyStartDate.getUTCDate() - 130)

  const [currentResult, historyResult, realizedResult] = await Promise.all([
    query<SnapshotRow>(
      `
        SELECT
          as_of_date::text AS as_of_date,
          product,
          product_class,
          expiry_label,
          atm_nvol_price,
          atm_nvol_bps,
          forward_price,
          forward_yield,
          fv01,
          underlying_contract,
          source
        FROM ${LISTED_SNAPSHOTS_TABLE}
        WHERE as_of_date = $1
          AND product = ANY($2)
      `,
      [asOfDate, products]
    ),
    query<HistoryRow>(
      `
        SELECT
          as_of_date::text AS as_of_date,
          product,
          expiry_label,
          atm_nvol_bps
        FROM ${LISTED_SNAPSHOTS_TABLE}
        WHERE as_of_date >= $1
          AND as_of_date <= $2
          AND product = ANY($3)
        ORDER BY as_of_date ASC
      `,
      [historyStartDate.toISOString().slice(0, 10), asOfDate, products]
    ),
    query<RealizedRow>(
      `
        SELECT
          as_of_date::text AS as_of_date,
          product,
          window_label,
          realized_nvol_bps,
          implied_realized_ratio
        FROM ${REALIZED_SNAPSHOTS_TABLE}
        WHERE as_of_date = $1
          AND product = ANY($2)
      `,
      [asOfDate, products]
    )
  ])

  const historyMap = new Map<string, Array<{ date: string; value: number | null }>>()
  for (const row of historyResult.rows) {
    const key = `${row.product}_${row.expiry_label}`
    const bucket = historyMap.get(key) ?? []
    bucket.push({
      date: row.as_of_date,
      value: parseNumber(row.atm_nvol_bps)
    })
    historyMap.set(key, bucket)
  }

  const cells = sortByProductExpiry(
    currentResult.rows.map((row) =>
      buildGridCell(
        row,
        historyMap,
        params.includeHistory ?? false,
        params.lookback ?? LISTED_VOL_LOOKBACK_SESSIONS
      )
    )
  )

  const realizedRows: ListedVolRealizedRow[] = realizedResult.rows
    .map((row) => ({
      asOfDate: row.as_of_date,
      product: row.product,
      windowLabel: row.window_label,
      realizedNvolBps: parseNumber(row.realized_nvol_bps),
      impliedRealizedRatio: parseNumber(row.implied_realized_ratio)
    }))
    .sort((left, right) => {
      const productDiff = ALL_LISTED_VOL_PRODUCTS.indexOf(left.product) - ALL_LISTED_VOL_PRODUCTS.indexOf(right.product)
      if (productDiff !== 0) return productDiff
      return ROLLING_EXPIRIES.indexOf(left.windowLabel) - ROLLING_EXPIRIES.indexOf(right.windowLabel)
    })

  return {
    requestedDate: params.requestedDate ?? null,
    asOfDate,
    productClass: params.productClass,
    products,
    expiries: ROLLING_EXPIRIES,
    cells,
    realizedRows
  }
}

export async function fetchListedVolHistoryGridData(params: {
  requestedDate?: string | null
  productClass: ListedVolProductClass
  lookback?: number
}): Promise<ListedVolHistoryGridResponse> {
  const lookback = Math.max(1, params.lookback ?? 20)
  const base = await fetchListedVolGridData({
    requestedDate: params.requestedDate,
    productClass: params.productClass,
    includeHistory: true,
    lookback
  })
  return {
    ...base,
    lookback
  }
}

export async function fetchListedVolComparisonData(params: {
  requestedDate?: string | null
  product: ListedVolProduct
}): Promise<ListedVolComparisonResponse> {
  const asOfDate = await resolveAvailableDate({
    requestedDate: params.requestedDate,
    products: [params.product],
    tableName: LISTED_COMPARISON_TABLE
  })
  if (!asOfDate) {
    throw new Error('No listed vs swaption comparison data available')
  }

  const result = await query<ComparisonRow>(
    `
      SELECT
        as_of_date::text AS as_of_date,
        product,
        expiry_label,
        listed_atm_nvol_bps,
        swaption_atmf_nvol_bps,
        vol_ratio,
        vol_diff_bps,
        swaption_expiry_label,
        swaption_tenor_label
      FROM ${LISTED_COMPARISON_TABLE}
      WHERE as_of_date = $1
        AND product = $2
    `,
    [asOfDate, params.product]
  )

  const rows: ListedVolComparisonRow[] = sortByProductExpiry(
    result.rows.map((row) => ({
      asOfDate: row.as_of_date,
      product: row.product,
      expiryLabel: row.expiry_label,
      listedAtmNvolBps: parseNumber(row.listed_atm_nvol_bps),
      swaptionAtmfNvolBps: parseNumber(row.swaption_atmf_nvol_bps),
      volRatio: parseNumber(row.vol_ratio),
      volDiffBps: parseNumber(row.vol_diff_bps),
      swaptionExpiryLabel: row.swaption_expiry_label,
      swaptionTenorLabel: row.swaption_tenor_label
    }))
  )

  return {
    requestedDate: params.requestedDate ?? null,
    asOfDate,
    product: params.product,
    rows
  }
}

export async function fetchListedVolTimeseriesData(params: {
  requestedDate?: string | null
  product: ListedVolProduct
  expiryLabel: ListedVolExpiry
  range: ListedVolRange
  includeSwaption: boolean
  includeRealized: boolean
}): Promise<ListedVolTimeseriesResponse> {
  const asOfDate = await resolveAvailableDate({
    requestedDate: params.requestedDate,
    products: [params.product]
  })
  if (!asOfDate) {
    throw new Error('No listed vol timeseries data available')
  }

  const result = await query<SnapshotRow & ComparisonRow & RealizedRow>(
    `
      SELECT
        s.as_of_date::text AS as_of_date,
        s.product,
        s.expiry_label,
        s.atm_nvol_bps,
        c.swaption_atmf_nvol_bps,
        c.vol_ratio,
        c.vol_diff_bps,
        r.realized_nvol_bps,
        r.implied_realized_ratio
      FROM ${LISTED_SNAPSHOTS_TABLE} s
      LEFT JOIN ${LISTED_COMPARISON_TABLE} c
        ON s.as_of_date = c.as_of_date
       AND s.product = c.product
       AND s.expiry_label = c.expiry_label
      LEFT JOIN ${REALIZED_SNAPSHOTS_TABLE} r
        ON s.as_of_date = r.as_of_date
       AND s.product = r.product
       AND s.expiry_label = r.window_label
      WHERE s.product = $1
        AND s.expiry_label = $2
        AND s.as_of_date <= $3
      ORDER BY s.as_of_date ASC
    `,
    [params.product, params.expiryLabel, asOfDate]
  )

  const points = filterByRange(
    result.rows.map<ListedVolSeriesPoint>((row) => ({
      date: row.as_of_date,
      timestamp: dateToTimestamp(row.as_of_date),
      listedNvolBps: parseNumber(row.atm_nvol_bps),
      swaptionNvolBps: params.includeSwaption ? parseNumber(row.swaption_atmf_nvol_bps) : null,
      volRatio: params.includeSwaption ? parseNumber(row.vol_ratio) : null,
      volDiffBps: params.includeSwaption ? parseNumber(row.vol_diff_bps) : null,
      realizedNvolBps: params.includeRealized ? parseNumber(row.realized_nvol_bps) : null,
      impliedRealizedRatio: params.includeRealized ? parseNumber(row.implied_realized_ratio) : null
    })),
    params.range
  )

  const listedStats = buildSeriesStats(points.map((point) => point.listedNvolBps))
  const swaptionStats = params.includeSwaption
    ? buildSeriesStats(points.map((point) => point.swaptionNvolBps))
    : null
  const ratioStats = params.includeSwaption
    ? buildSeriesStats(points.map((point) => point.volRatio))
    : null
  const realizedStats = params.includeRealized
    ? buildSeriesStats(points.map((point) => point.realizedNvolBps))
    : null

  return {
    requestedDate: params.requestedDate ?? null,
    asOfDate,
    product: params.product,
    expiryLabel: params.expiryLabel,
    range: params.range,
    points,
    stats: {
      listed: listedStats,
      swaption: swaptionStats,
      ratio: ratioStats,
      realized: realizedStats
    }
  }
}
