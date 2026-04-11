import { query } from '@/lib/db'
import type {
  ListedOptionContractReferenceMode,
  ListedOptionMetricField,
  ListedOptionRowAxis,
  ListedOptionSeriesConfig,
  ListedOptionSnapshotCell,
  ListedOptionSnapshotContractGroup,
  ListedOptionSnapshotFilterOption,
  ListedOptionSnapshotResponse,
  ListedOptionSnapshotRow,
  ListedOptionTimeseriesMultiResponse,
  ListedOptionTimeseriesSeries,
} from '@/features/listed-option-oi-volume/types'
import {
  computeSeriesStats,
  formatNumber,
  formatSeriesConfigLabel,
  getSeriesConfigKey,
  rangeToInterval,
} from '@/features/listed-option-oi-volume/utils'

const TABLE_NAME = 'arbs_listed_option_oi_volume_v1'
const DELTA_BUCKET_SIZE = 5

type SnapshotParams = {
  requestedDate?: string
  field: ListedOptionMetricField
  periodBusinessDays: number
  labelNamespace: 'BBG' | 'Globex' | 'Barchart'
  contractView: ListedOptionContractReferenceMode
  rowAxis: ListedOptionRowAxis
  productFamily?: 'UST' | 'STIR'
  productRoots?: string[]
}

type TimeseriesCollectionParams = {
  series: ListedOptionSeriesConfig[]
  range?: '1M' | '3M' | '6M' | '1Y' | 'ALL'
  startDate?: string
  endDate?: string
  periodBusinessDays?: number
}

type CandidateRow = {
  asOfDate: string
  productFamily: 'UST' | 'STIR'
  productRoot: string
  optionContract: string
  optionContractBarchart: string | null
  underlyingContract: string | null
  underlyingBarchart: string | null
  explicitOptionSymbol: string
  right: 'C' | 'P'
  strike: number | null
  deltaAbs: number | null
  atmOffsetBps: number | null
  openInterest: number | null
  volume: number | null
  forwardPrice: number | null
  expiryDate: string | null
  dteDays: number | null
  cmRank: number | null
}

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatDbDate(value: unknown): string | null {
  if (!value) return null
  const token = String(value).trim()
  if (!token) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(token)) return token
  const parsed = new Date(token)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
}

function metricColumn(field: ListedOptionMetricField) {
  return field === 'volume' || field === 'volume_change' ? 'volume' : 'open_interest'
}

function isChangeField(field: ListedOptionMetricField) {
  return field === 'open_interest_change' || field === 'volume_change'
}

function buildWhereClause(params: {
  productFamily?: 'UST' | 'STIR'
  productRoots?: string[]
  startDate?: string
  endDate?: string
  interval?: string
  alias?: string
}) {
  const values: unknown[] = []
  const filters: string[] = []

  const bind = (value: unknown) => {
    values.push(value)
    return `$${values.length}`
  }

  const tableAlias = params.alias ?? 't'

  if (params.productFamily) {
    filters.push(`${tableAlias}.product_family = ${bind(params.productFamily)}`)
  }

  if (params.productRoots?.length) {
    filters.push(`${tableAlias}.product_root = ANY(${bind(params.productRoots)}::text[])`)
  }

  if (params.startDate) {
    filters.push(`${tableAlias}.as_of_date >= ${bind(params.startDate)}::date`)
  } else if (params.interval) {
    filters.push(`${tableAlias}.as_of_date >= CURRENT_DATE - ${bind(params.interval)}::interval`)
  }

  if (params.endDate) {
    filters.push(`${tableAlias}.as_of_date <= ${bind(params.endDate)}::date`)
  }

  return {
    whereSql: filters.length ? `WHERE ${filters.join(' AND ')}` : '',
    values,
  }
}

function buildDateUniverseLagMap(dates: string[], periodBusinessDays: number) {
  const lagMap = new Map<string, string | null>()

  for (let index = 0; index < dates.length; index += 1) {
    lagMap.set(dates[index]!, index >= periodBusinessDays ? dates[index - periodBusinessDays]! : null)
  }

  return lagMap
}

async function fetchAvailableDates(endDate?: string) {
  const params: unknown[] = []
  const filters: string[] = []

  if (endDate) {
    params.push(endDate)
    filters.push(`as_of_date <= $${params.length}::date`)
  }

  const result = await query<{ as_of_date: string }>(
    `SELECT DISTINCT as_of_date::text AS as_of_date
     FROM ${TABLE_NAME}
     ${filters.length ? `WHERE ${filters.join(' AND ')}` : ''}
     ORDER BY as_of_date`,
    params
  )

  return result.rows
    .map((row) => formatDbDate(row.as_of_date))
    .filter((value): value is string => Boolean(value))
}

async function resolveEffectiveDate(requestedDate?: string) {
  if (requestedDate) {
    const result = await query<{ as_of_date: string }>(
      `SELECT MAX(as_of_date)::text AS as_of_date
       FROM ${TABLE_NAME}
       WHERE as_of_date <= $1::date`,
      [requestedDate]
    )
    return formatDbDate(result.rows[0]?.as_of_date)
  }

  const result = await query<{ as_of_date: string }>(
    `SELECT MAX(as_of_date)::text AS as_of_date FROM ${TABLE_NAME}`
  )
  return formatDbDate(result.rows[0]?.as_of_date)
}

async function fetchAvailableRoots(): Promise<ListedOptionSnapshotFilterOption[]> {
  const result = await query<{ product_family: 'UST' | 'STIR'; product_root: string }>(
    `SELECT DISTINCT product_family, product_root
     FROM ${TABLE_NAME}
     ORDER BY product_family, product_root`
  )

  return result.rows.map((row) => ({
    productFamily: row.product_family,
    productRoot: String(row.product_root ?? ''),
  }))
}

function normalizeCandidateRows(rows: Array<Record<string, unknown>>): CandidateRow[] {
  return rows
    .map((row) => ({
      asOfDate: formatDbDate(row.as_of_date) ?? '',
      productFamily: String(row.product_family ?? 'UST') as CandidateRow['productFamily'],
      productRoot: String(row.product_root ?? ''),
      optionContract: String(row.option_contract ?? ''),
      optionContractBarchart: row.option_contract_barchart
        ? String(row.option_contract_barchart)
        : null,
      underlyingContract: row.underlying_contract ? String(row.underlying_contract) : null,
      underlyingBarchart: row.underlying_barchart ? String(row.underlying_barchart) : null,
      explicitOptionSymbol: String(row.explicit_option_symbol ?? ''),
      right: String(row.right ?? 'C') as CandidateRow['right'],
      strike: parseNumber(row.strike),
      deltaAbs: parseNumber(row.delta_abs),
      atmOffsetBps: parseNumber(row.atm_offset_bps),
      openInterest: parseNumber(row.open_interest),
      volume: parseNumber(row.volume),
      forwardPrice: parseNumber(row.forward_price),
      expiryDate: formatDbDate(row.expiry_date),
      dteDays: parseNumber(row.dte_days),
      cmRank: parseNumber(row.cm_rank),
    }))
    .filter((row) => Boolean(row.asOfDate && row.productRoot && row.explicitOptionSymbol))
}

async function fetchSnapshotRows(params: {
  asOfDate: string
  productFamily?: 'UST' | 'STIR'
  productRoots?: string[]
}) {
  const filters = buildWhereClause({
    productFamily: params.productFamily,
    productRoots: params.productRoots,
    startDate: params.asOfDate,
    endDate: params.asOfDate,
  })

  const result = await query(
    `WITH ranked_contracts AS (
       SELECT
         ranked.as_of_date,
         ranked.product_root,
         ranked.option_contract,
         DENSE_RANK() OVER (
           PARTITION BY ranked.as_of_date, ranked.product_root
           ORDER BY ranked.expiry_date, ranked.option_contract
         ) AS cm_rank
       FROM (
         SELECT DISTINCT
           t.as_of_date,
           t.product_root,
           t.option_contract,
           t.expiry_date
         FROM ${TABLE_NAME} t
         ${filters.whereSql}
       ) ranked
     )
     SELECT
       t.as_of_date::text AS as_of_date,
       t.product_family,
       t.product_root,
       t.option_contract,
       t.option_contract_barchart,
       t.underlying_contract,
       t.underlying_barchart,
       t.explicit_option_symbol,
       t.option_right AS right,
       t.strike,
       t.delta_abs,
       t.atm_offset_bps,
       t.open_interest,
       t.volume,
       t.forward_price,
       t.expiry_date::text AS expiry_date,
       t.dte_days,
       ranked_contracts.cm_rank
     FROM ${TABLE_NAME} t
     LEFT JOIN ranked_contracts
       ON ranked_contracts.as_of_date = t.as_of_date
      AND ranked_contracts.product_root = t.product_root
      AND ranked_contracts.option_contract = t.option_contract
     ${filters.whereSql}
     ORDER BY t.product_family, t.product_root, t.expiry_date, t.option_contract, t.strike DESC, t.option_right`,
    filters.values
  )

  return normalizeCandidateRows(result.rows as Array<Record<string, unknown>>)
}

function buildTupleInClause(items: Array<{ symbol: string; asOfDate: string }>) {
  const params: unknown[] = []
  const tuples = items.map((item) => {
    params.push(item.symbol, item.asOfDate)
    return `($${params.length - 1}, $${params.length}::date)`
  })

  return {
    sql: tuples.join(', '),
    params,
  }
}

async function fetchMetricLookup(items: Array<{ symbol: string; asOfDate: string }>) {
  if (!items.length) {
    return new Map<string, { openInterest: number | null; volume: number | null }>()
  }

  const tupleClause = buildTupleInClause(items)
  const result = await query<{
    explicit_option_symbol: string
    as_of_date: string
    open_interest: string | number | null
    volume: string | number | null
  }>(
    `SELECT explicit_option_symbol, as_of_date::text AS as_of_date, open_interest, volume
     FROM ${TABLE_NAME}
     WHERE (explicit_option_symbol, as_of_date) IN (${tupleClause.sql})`,
    tupleClause.params
  )

  const lookup = new Map<string, { openInterest: number | null; volume: number | null }>()
  for (const row of result.rows) {
    const asOfDate = formatDbDate(row.as_of_date)
    if (!asOfDate) continue
    lookup.set(`${row.explicit_option_symbol}|${asOfDate}`, {
      openInterest: parseNumber(row.open_interest),
      volume: parseNumber(row.volume),
    })
  }
  return lookup
}

function contractGroupKey(
  row: CandidateRow,
  contractView: ListedOptionContractReferenceMode
) {
  return contractView === 'constant_maturity'
    ? `cm:${row.productRoot}:${row.cmRank ?? ''}`
    : `contract:${row.productRoot}:${row.optionContract}`
}

function displayContractLabel(
  row: CandidateRow,
  contractView: ListedOptionContractReferenceMode,
  labelNamespace: 'BBG' | 'Globex' | 'Barchart'
) {
  if (contractView === 'constant_maturity') {
    return `${row.productRoot} CM${row.cmRank ?? '?'}`
  }

  if (labelNamespace === 'Barchart') {
    return row.optionContractBarchart ?? row.optionContract
  }

  return row.optionContract
}

function rowAxisDescriptor(rowAxis: ListedOptionRowAxis, row: CandidateRow) {
  if (rowAxis === 'strike') {
    const axisValue = row.strike
    return {
      key: axisValue === null ? 'strike:null' : `strike:${axisValue.toFixed(6)}`,
      label: axisValue === null ? '--' : formatNumber(axisValue, axisValue % 1 === 0 ? 0 : 3),
      axisValue,
      strike: axisValue,
      deltaAbs: row.deltaAbs,
      bpsOffset: row.atmOffsetBps === null ? null : Math.abs(row.atmOffsetBps),
    }
  }

  if (rowAxis === 'delta') {
    const rawDelta = row.deltaAbs
    const bucket =
      rawDelta === null
        ? null
        : Math.max(0, Math.min(50, Math.round(rawDelta / DELTA_BUCKET_SIZE) * DELTA_BUCKET_SIZE))
    return {
      key: bucket === null ? 'delta:null' : `delta:${bucket.toFixed(2)}`,
      label: bucket === null ? '--' : `${formatNumber(bucket, 0)}D`,
      axisValue: bucket,
      strike: row.strike,
      deltaAbs: bucket,
      bpsOffset: row.atmOffsetBps === null ? null : Math.abs(row.atmOffsetBps),
    }
  }

  const absOffset = row.atmOffsetBps === null ? null : Math.abs(row.atmOffsetBps)
  return {
    key: absOffset === null ? 'bps:null' : `bps:${absOffset.toFixed(6)}`,
    label: absOffset === null ? '--' : `${formatNumber(absOffset, absOffset % 1 === 0 ? 0 : 2)}bp`,
    axisValue: absOffset,
    strike: row.strike,
    deltaAbs: row.deltaAbs,
    bpsOffset: absOffset,
  }
}

function valueFromRow(
  row: CandidateRow,
  field: ListedOptionMetricField,
  previousLookup: Map<string, { openInterest: number | null; volume: number | null }>,
  lagDateByCurrentDate: Map<string, string | null>
) {
  const baseMetric = metricColumn(field) === 'volume' ? row.volume : row.openInterest
  if (!isChangeField(field)) {
    return baseMetric
  }

  const previousDate = lagDateByCurrentDate.get(row.asOfDate) ?? null
  if (!previousDate) {
    return null
  }

  const previousMetric = previousLookup.get(`${row.explicitOptionSymbol}|${previousDate}`)
  const previousValue =
    metricColumn(field) === 'volume' ? previousMetric?.volume ?? null : previousMetric?.openInterest ?? null

  return baseMetric !== null && previousValue !== null ? baseMetric - previousValue : null
}

function buildChartSeries(
  row: CandidateRow,
  params: {
    field: ListedOptionMetricField
    contractView: ListedOptionContractReferenceMode
    rowAxis: ListedOptionRowAxis
    labelNamespace: 'BBG' | 'Globex' | 'Barchart'
  }
): ListedOptionSeriesConfig {
  if (params.contractView === 'explicit' && params.rowAxis === 'strike') {
    return {
      metricField: params.field,
      productFamily: row.productFamily,
      productRoot: row.productRoot,
      labelNamespace: params.labelNamespace,
      contractReferenceMode: 'explicit',
      explicitContract: row.optionContract,
      selectorType: 'explicit_symbol',
      side: row.right,
      selectorValue: row.strike,
      rawSymbolFallback: row.explicitOptionSymbol,
    }
  }

  const selectorType =
    params.rowAxis === 'strike'
      ? 'strike'
      : params.rowAxis === 'delta'
        ? 'delta'
        : 'bps_offset'

  return {
    metricField: params.field,
    productFamily: row.productFamily,
    productRoot: row.productRoot,
    labelNamespace: params.labelNamespace,
    contractReferenceMode: params.contractView,
    explicitContract: params.contractView === 'explicit' ? row.optionContract : undefined,
    constantMaturityRank: params.contractView === 'constant_maturity' ? row.cmRank ?? undefined : undefined,
    selectorType,
    side: row.right,
    selectorValue:
      params.rowAxis === 'strike'
        ? row.strike
        : params.rowAxis === 'delta'
          ? rowAxisDescriptor('delta', row).axisValue
          : row.atmOffsetBps === null
            ? null
            : Math.abs(row.atmOffsetBps),
    rawSymbolFallback: row.explicitOptionSymbol,
  }
}

function sortSnapshotRows(rowAxis: ListedOptionRowAxis, rows: ListedOptionSnapshotRow[]) {
  return [...rows].sort((left, right) => {
    const leftValue = left.axisValue ?? Number.NEGATIVE_INFINITY
    const rightValue = right.axisValue ?? Number.NEGATIVE_INFINITY

    if (rowAxis === 'bps_offset') {
      return leftValue - rightValue
    }

    return rightValue - leftValue
  })
}

function buildContractGroups(
  rows: CandidateRow[],
  contractView: ListedOptionContractReferenceMode,
  labelNamespace: 'BBG' | 'Globex' | 'Barchart'
) {
  const groups = new Map<string, ListedOptionSnapshotContractGroup>()

  for (const row of rows) {
    const id = contractGroupKey(row, contractView)
    if (groups.has(id)) continue

    groups.set(id, {
      id,
      productFamily: row.productFamily,
      productRoot: row.productRoot,
      contractReferenceMode: contractView,
      explicitContract: contractView === 'explicit' ? row.optionContract : null,
      constantMaturityRank: contractView === 'constant_maturity' ? row.cmRank ?? null : null,
      displayLabel: displayContractLabel(row, contractView, labelNamespace),
      underlyingLabel:
        labelNamespace === 'Barchart'
          ? row.underlyingBarchart ?? row.underlyingContract
          : row.underlyingContract,
      forwardPrice: row.forwardPrice,
      expiryDate: row.expiryDate,
      dteDays: row.dteDays,
    })
  }

  return Array.from(groups.values()).sort((left, right) => {
    if (left.productFamily !== right.productFamily) {
      return left.productFamily.localeCompare(right.productFamily)
    }
    if (left.productRoot !== right.productRoot) {
      return left.productRoot.localeCompare(right.productRoot)
    }
    if ((left.constantMaturityRank ?? 0) !== (right.constantMaturityRank ?? 0)) {
      return (left.constantMaturityRank ?? 0) - (right.constantMaturityRank ?? 0)
    }
    return (left.expiryDate ?? '').localeCompare(right.expiryDate ?? '') ||
      (left.explicitContract ?? '').localeCompare(right.explicitContract ?? '')
  })
}

function chooseBestRowForAxis(
  rows: CandidateRow[],
  rowAxis: ListedOptionRowAxis,
  targetAxisValue: number | null
) {
  if (!rows.length) return null
  if (rowAxis === 'strike') {
    return rows.find((row) => row.strike === targetAxisValue) ?? null
  }
  if (rowAxis === 'delta') {
    return rows
      .filter((row) => row.deltaAbs !== null)
      .sort((left, right) => {
        const leftDistance = Math.abs((left.deltaAbs ?? 0) - (targetAxisValue ?? 0))
        const rightDistance = Math.abs((right.deltaAbs ?? 0) - (targetAxisValue ?? 0))
        return leftDistance - rightDistance ||
          Math.abs((right.openInterest ?? 0) + (right.volume ?? 0)) -
            Math.abs((left.openInterest ?? 0) + (left.volume ?? 0))
      })[0] ?? null
  }

  return rows
    .filter((row) => row.atmOffsetBps !== null)
    .sort((left, right) => {
      const leftDistance = Math.abs(Math.abs(left.atmOffsetBps ?? 0) - (targetAxisValue ?? 0))
      const rightDistance = Math.abs(Math.abs(right.atmOffsetBps ?? 0) - (targetAxisValue ?? 0))
      return leftDistance - rightDistance ||
        Math.abs((right.openInterest ?? 0) + (right.volume ?? 0)) -
          Math.abs((left.openInterest ?? 0) + (left.volume ?? 0))
    })[0] ?? null
}

function groupRowsByContractAndAxis(
  rows: CandidateRow[],
  params: {
    field: ListedOptionMetricField
    contractView: ListedOptionContractReferenceMode
    rowAxis: ListedOptionRowAxis
    labelNamespace: 'BBG' | 'Globex' | 'Barchart'
    previousLookup: Map<string, { openInterest: number | null; volume: number | null }>
    lagDateByCurrentDate: Map<string, string | null>
  }
) {
  const contractGroups = buildContractGroups(rows, params.contractView, params.labelNamespace)
  const byContract = new Map<string, CandidateRow[]>()
  const rowDescriptors = new Map<string, ListedOptionSnapshotRow>()

  for (const row of rows) {
    const contractId = contractGroupKey(row, params.contractView)
    const current = byContract.get(contractId) ?? []
    current.push(row)
    byContract.set(contractId, current)

    const axis = rowAxisDescriptor(params.rowAxis, row)
    if (!rowDescriptors.has(axis.key)) {
      rowDescriptors.set(axis.key, {
        rowKey: axis.key,
        rowLabel: axis.label,
        axisValue: axis.axisValue,
        strike: axis.strike,
        deltaAbs: axis.deltaAbs,
        bpsOffset: axis.bpsOffset,
        cells: {},
      })
    }
  }

  for (const snapshotRow of rowDescriptors.values()) {
    for (const contractGroup of contractGroups) {
      const contractRows = (byContract.get(contractGroup.id) ?? []).filter(
        (row) =>
          params.contractView === 'constant_maturity'
            ? row.cmRank === contractGroup.constantMaturityRank
            : row.optionContract === contractGroup.explicitContract
      )

      const callRow = chooseBestRowForAxis(
        contractRows.filter((row) => row.right === 'C'),
        params.rowAxis,
        snapshotRow.axisValue
      )
      const putRow = chooseBestRowForAxis(
        contractRows.filter((row) => row.right === 'P'),
        params.rowAxis,
        snapshotRow.axisValue
      )

      const buildCell = (row: CandidateRow | null): ListedOptionSnapshotCell | null => {
        if (!row) return null
        return {
          contractGroupId: contractGroup.id,
          side: row.right,
          value: valueFromRow(row, params.field, params.previousLookup, params.lagDateByCurrentDate),
          strike: row.strike,
          deltaAbs: row.deltaAbs,
          atmOffsetBps: row.atmOffsetBps,
          explicitOptionSymbol: row.explicitOptionSymbol,
          chartSeries: buildChartSeries(row, params),
        }
      }

      snapshotRow.cells[contractGroup.id] = {
        call: buildCell(callRow),
        put: buildCell(putRow),
      }
    }
  }

  return {
    contractGroups,
    rows: sortSnapshotRows(params.rowAxis, Array.from(rowDescriptors.values())),
  }
}

async function fetchSeriesCandidates(
  config: ListedOptionSeriesConfig,
  window: { startDate?: string; endDate?: string; interval?: string }
) {
  const filters = buildWhereClause({
    productFamily: config.productFamily,
    productRoots: [config.productRoot],
    startDate: window.startDate,
    endDate: window.endDate,
    interval: window.interval,
  })
  const values = [...filters.values]
  const bind = (value: unknown) => {
    values.push(value)
    return `$${values.length}`
  }

  const selectorFilters: string[] = []
  if (config.contractReferenceMode === 'explicit' && config.explicitContract) {
    selectorFilters.push(`t.option_contract = ${bind(config.explicitContract)}`)
  }
  if (config.selectorType === 'explicit_symbol' && config.rawSymbolFallback) {
    selectorFilters.push(`t.explicit_option_symbol = ${bind(config.rawSymbolFallback)}`)
  }
  if (config.side !== 'S') {
    selectorFilters.push(`t.option_right = ${bind(config.side)}`)
  }

  const whereSql = [filters.whereSql.replace(/^WHERE\s+/i, ''), ...selectorFilters]
    .filter(Boolean)
    .join(' AND ')

  const result = await query(
    `WITH ranked_contracts AS (
       SELECT
         ranked.as_of_date,
         ranked.product_root,
         ranked.option_contract,
         DENSE_RANK() OVER (
           PARTITION BY ranked.as_of_date, ranked.product_root
           ORDER BY ranked.expiry_date, ranked.option_contract
         ) AS cm_rank
       FROM (
         SELECT DISTINCT
           t.as_of_date,
           t.product_root,
           t.option_contract,
           t.expiry_date
         FROM ${TABLE_NAME} t
         ${filters.whereSql}
       ) ranked
     )
     SELECT
       t.as_of_date::text AS as_of_date,
       t.product_family,
       t.product_root,
       t.option_contract,
       t.option_contract_barchart,
       t.underlying_contract,
       t.underlying_barchart,
       t.explicit_option_symbol,
       t.option_right AS right,
       t.strike,
       t.delta_abs,
       t.atm_offset_bps,
       t.open_interest,
       t.volume,
       t.forward_price,
       t.expiry_date::text AS expiry_date,
       t.dte_days,
       ranked_contracts.cm_rank
     FROM ${TABLE_NAME} t
     LEFT JOIN ranked_contracts
       ON ranked_contracts.as_of_date = t.as_of_date
      AND ranked_contracts.product_root = t.product_root
      AND ranked_contracts.option_contract = t.option_contract
     ${whereSql ? `WHERE ${whereSql}` : ''}
     ORDER BY t.as_of_date, t.expiry_date, t.option_contract, t.strike DESC, t.option_right`,
    values
  )

  return normalizeCandidateRows(result.rows as Array<Record<string, unknown>>)
}

function selectSeriesRow(
  config: ListedOptionSeriesConfig,
  rows: CandidateRow[]
) {
  if (!rows.length) return null

  if (config.contractReferenceMode === 'constant_maturity') {
    rows = rows.filter((row) => row.cmRank === config.constantMaturityRank)
  }

  if (config.selectorType === 'explicit_symbol') {
    const symbol = String(config.rawSymbolFallback ?? '').toUpperCase()
    return rows.find((row) => row.explicitOptionSymbol.toUpperCase() === symbol) ?? null
  }

  if (config.selectorType === 'strike') {
    const strike = parseNumber(config.selectorValue)
    if (strike === null) return null
    const matching = rows.filter((row) => row.strike !== null && Math.abs(row.strike - strike) < 1e-8)
    if (config.side === 'S') {
      return matching[0] ?? null
    }
    return matching.find((row) => row.right === config.side) ?? null
  }

  if (config.selectorType === 'delta') {
    const delta = parseNumber(config.selectorValue)
    if (delta === null) return null
    const eligible = config.side === 'S' ? rows : rows.filter((row) => row.right === config.side)
    return eligible
      .filter((row) => row.deltaAbs !== null)
      .sort((left, right) => Math.abs((left.deltaAbs ?? 0) - delta) - Math.abs((right.deltaAbs ?? 0) - delta))[0] ?? null
  }

  const offset = parseNumber(config.selectorValue)
  if (offset === null) return null
  const targetOffset =
    config.side === 'P' ? -Math.abs(offset) : config.side === 'C' ? Math.abs(offset) : offset
  const eligible = config.side === 'S' ? rows : rows.filter((row) => row.right === config.side)

  return eligible
    .filter((row) => row.atmOffsetBps !== null)
    .sort(
      (left, right) =>
        Math.abs((left.atmOffsetBps ?? 0) - targetOffset) -
        Math.abs((right.atmOffsetBps ?? 0) - targetOffset)
    )[0] ?? null
}

function metricValueFromLookup(
  field: ListedOptionMetricField,
  row: CandidateRow | null,
  lagMap: Map<string, string | null>,
  previousLookup: Map<string, { openInterest: number | null; volume: number | null }>
) {
  if (!row) return null

  const currentValue = metricColumn(field) === 'volume' ? row.volume : row.openInterest
  if (!isChangeField(field)) return currentValue

  const previousDate = lagMap.get(row.asOfDate) ?? null
  if (!previousDate) return null

  const previousValues = previousLookup.get(`${row.explicitOptionSymbol}|${previousDate}`)
  const previousValue =
    metricColumn(field) === 'volume' ? previousValues?.volume ?? null : previousValues?.openInterest ?? null

  return currentValue !== null && previousValue !== null ? currentValue - previousValue : null
}

export async function fetchListedOptionSnapshot(
  params: SnapshotParams
): Promise<ListedOptionSnapshotResponse> {
  const latestAvailableDate = await resolveEffectiveDate()
  const asOfDate = await resolveEffectiveDate(params.requestedDate)
  const availableRoots = await fetchAvailableRoots()

  if (!asOfDate) {
    return {
      requestedDate: params.requestedDate ?? null,
      asOfDate: null,
      latestAvailableDate,
      periodBusinessDays: params.periodBusinessDays,
      field: params.field,
      labelNamespace: params.labelNamespace,
      contractView: params.contractView,
      rowAxis: params.rowAxis,
      availableRoots,
      contractGroups: [],
      rows: [],
      warnings: ['No listed option open-interest / volume history is stored yet.'],
    }
  }

  const rows = await fetchSnapshotRows({
    asOfDate,
    productFamily: params.productFamily,
    productRoots: params.productRoots,
  })
  const lagDates = buildDateUniverseLagMap(await fetchAvailableDates(asOfDate), params.periodBusinessDays)

  const previousDate = lagDates.get(asOfDate) ?? null
  const previousLookup = await fetchMetricLookup(
    previousDate
      ? rows.map((row) => ({
          symbol: row.explicitOptionSymbol,
          asOfDate: previousDate,
        }))
      : []
  )

  const transformed = groupRowsByContractAndAxis(rows, {
    field: params.field,
    contractView: params.contractView,
    rowAxis: params.rowAxis,
    labelNamespace: params.labelNamespace,
    previousLookup,
    lagDateByCurrentDate: lagDates,
  })

  const warnings: string[] = []
  if (params.requestedDate && params.requestedDate !== asOfDate) {
    warnings.push(`Requested ${params.requestedDate}, showing latest stored snapshot on or before ${asOfDate}.`)
  }
  if (!transformed.rows.length) {
    warnings.push('No rows matched the selected product filters.')
  }

  return {
    requestedDate: params.requestedDate ?? null,
    asOfDate,
    latestAvailableDate,
    periodBusinessDays: params.periodBusinessDays,
    field: params.field,
    labelNamespace: params.labelNamespace,
    contractView: params.contractView,
    rowAxis: params.rowAxis,
    availableRoots,
    contractGroups: transformed.contractGroups,
    rows: transformed.rows,
    warnings,
  }
}

export async function fetchListedOptionTimeseriesCollection(
  params: TimeseriesCollectionParams
): Promise<ListedOptionTimeseriesMultiResponse> {
  const uniqueSeries = Array.from(
    new Map(params.series.map((config) => [getSeriesConfigKey(config), config])).values()
  )

  if (!uniqueSeries.length) {
    return {
      startDate: null,
      endDate: null,
      asOfDate: null,
      series: [],
      warnings: [],
    }
  }

  const window =
    params.startDate || params.endDate
      ? {
          startDate: params.startDate,
          endDate: params.endDate,
        }
      : {
          interval: rangeToInterval(params.range ?? '6M'),
          endDate: params.endDate,
        }

  const periodBusinessDays = Math.max(1, params.periodBusinessDays ?? 1)
  const lagMap = buildDateUniverseLagMap(await fetchAvailableDates(params.endDate), periodBusinessDays)
  const series = await Promise.all(
    uniqueSeries.map(async (config): Promise<ListedOptionTimeseriesSeries> => {
      const candidates = await fetchSeriesCandidates(config, window)
      const groupedByDate = new Map<string, CandidateRow[]>()

      for (const row of candidates) {
        const current = groupedByDate.get(row.asOfDate) ?? []
        current.push(row)
        groupedByDate.set(row.asOfDate, current)
      }

      const selectedRows = Array.from(groupedByDate.entries())
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([asOfDate, rowsForDate]) => ({
          asOf: asOfDate,
          row: selectSeriesRow(config, rowsForDate),
        }))

      const previousLookup = await fetchMetricLookup(
        selectedRows
          .map((entry) => {
            const previousDate = lagMap.get(entry.asOf) ?? null
            if (!entry.row || !previousDate) return null
            return {
              symbol: entry.row.explicitOptionSymbol,
              asOfDate: previousDate,
            }
          })
          .filter((value): value is { symbol: string; asOfDate: string } => Boolean(value))
      )

      const points = selectedRows.map((entry) => ({
        asOf: entry.asOf,
        value: metricValueFromLookup(config.metricField, entry.row, lagMap, previousLookup),
      }))

      return {
        id: getSeriesConfigKey(config),
        label: formatSeriesConfigLabel(config),
        config,
        points,
        stats: computeSeriesStats(points.map((point) => point.value)),
      }
    })
  )

  const warnings = series
    .filter((entry) => entry.points.every((point) => point.value === null))
    .map((entry) => `No data returned for ${entry.label}.`)

  const allDates = series.flatMap((entry) => entry.points.map((point) => point.asOf)).sort()

  return {
    startDate: allDates[0] ?? null,
    endDate: allDates.at(-1) ?? null,
    asOfDate: allDates.at(-1) ?? null,
    series,
    warnings,
  }
}
