import { randomUUID } from 'crypto'
import { query } from '@/lib/db'

export const MANUAL_LINKS_TABLE = 'arbs_swaption_manual_links_v1'
export const MANUAL_LINK_HISTORY_TABLE = 'arbs_swaption_link_history_v1'

type ManualLinkLeg = {
  trade_id: string
  package_id: string
  trade_label?: string | null
  product_type?: string | null
  notional?: number | string | null
  premium?: number | string | null
  execution_timestamp?: string | null
  platform_identifier?: string | null
  leg_metrics?: Record<string, unknown> | null
  package_type?: string | null
  manual_link_id?: string | null
  is_manually_linked?: boolean | number | string | null
}

type ManualLinkConflict = {
  link_id: string
  manual_package_id: string
  linked_trade_ids: string[]
  is_active?: boolean | null
}

type ValidationItem = {
  key: string
  label: string
  status: 'ok' | 'warn' | 'error'
  message: string
}

const DV01_KEYS = ['dv01', 'outright_dv01', 'straddle_dv01', 'rr_dv01', 'vs_dv01']
const VEGA01_KEYS = [
  'vega01',
  'outright_vega01',
  'straddle_vega01',
  'rr_vega01',
  'vs_vega01'
]
const GAMMA01_KEYS = [
  'gamma01',
  'outright_gamma01',
  'straddle_gamma01',
  'rr_gamma01',
  'vs_gamma01'
]
const THETA01_KEYS = [
  'theta01',
  'outright_theta1d',
  'straddle_theta1d',
  'rr_theta1d',
  'vs_theta1d'
]

const TIME_SPREAD_WARN_SECONDS = 60 * 60

function toNumber(value: unknown) {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function sumNumbers(values: Array<number | null>) {
  const valid = values.filter((value): value is number => value !== null)
  if (!valid.length) return null
  return valid.reduce((acc, value) => acc + value, 0)
}

function extractMetric(
  metrics: Record<string, unknown> | null | undefined,
  keys: string[]
) {
  if (!metrics) return null
  for (const key of keys) {
    const value = toNumber(metrics[key])
    if (value !== null) return value
  }
  return null
}

function buildDateToken(date: Date) {
  const yyyy = String(date.getUTCFullYear())
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(date.getUTCDate()).padStart(2, '0')
  return `${yyyy}${mm}${dd}`
}

export async function checkManualLinkTables() {
  const result = await query<{ links: string | null; history: string | null }>(
    'SELECT to_regclass($1) AS links, to_regclass($2) AS history',
    [MANUAL_LINKS_TABLE, MANUAL_LINK_HISTORY_TABLE]
  )
  const row = result.rows[0]
  const linksTable = Boolean(row?.links)
  const historyTable = Boolean(row?.history)
  const missingTables: string[] = []
  if (!linksTable) missingTables.push(MANUAL_LINKS_TABLE)
  if (!historyTable) missingTables.push(MANUAL_LINK_HISTORY_TABLE)
  return { linksTable, historyTable, missingTables }
}

export function normalizeIdList(input: unknown) {
  if (!input) return []
  const rawValues = Array.isArray(input)
    ? input
    : String(input).split(/[\s,]+/)
  const seen = new Set<string>()
  const result: string[] = []
  rawValues.forEach((value) => {
    const normalized = String(value).trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    result.push(normalized)
  })
  return result
}

export async function resolveLinkLegs(tradeIds: string[]) {
  if (!tradeIds.length) return [] as ManualLinkLeg[]
  const result = await query<ManualLinkLeg>(
    `SELECT trade_id,
            package_id,
            trade_label,
            product_type,
            notional,
            premium,
            execution_timestamp,
            platform_identifier,
            leg_metrics,
            package_type,
            manual_link_id,
            is_manually_linked
     FROM arbs_swaption_legs_v1
     WHERE trade_id = ANY($1)`,
    [tradeIds]
  )
  return result.rows
}

export function computeLinkMetrics(legs: ManualLinkLeg[]) {
  const notionalValues = legs.map((leg) => toNumber(leg.notional))
  const premiumValues = legs.map((leg) => toNumber(leg.premium))
  const dv01Values = legs.map((leg) =>
    extractMetric(leg.leg_metrics, DV01_KEYS)
  )
  const vega01Values = legs.map((leg) =>
    extractMetric(leg.leg_metrics, VEGA01_KEYS)
  )
  const gamma01Values = legs.map((leg) =>
    extractMetric(leg.leg_metrics, GAMMA01_KEYS)
  )
  const theta01Values = legs.map((leg) =>
    extractMetric(leg.leg_metrics, THETA01_KEYS)
  )

  const timestamps = legs
    .map((leg) => (leg.execution_timestamp ? Date.parse(leg.execution_timestamp) : NaN))
    .filter((value) => Number.isFinite(value))

  const minTs = timestamps.length ? Math.min(...timestamps) : null
  const maxTs = timestamps.length ? Math.max(...timestamps) : null
  const timeSpreadSeconds =
    minTs !== null && maxTs !== null ? (maxTs - minTs) / 1000 : null

  return {
    trade_count: legs.length,
    total_notional: sumNumbers(notionalValues),
    total_premium: sumNumbers(premiumValues),
    total_dv01: sumNumbers(dv01Values),
    total_vega01: sumNumbers(vega01Values),
    total_gamma01: sumNumbers(gamma01Values),
    total_theta01: sumNumbers(theta01Values),
    time_spread_seconds: timeSpreadSeconds
  }
}

export async function findManualLinkConflicts(
  tradeIds: string[],
  excludeLinkId?: string
) {
  if (!tradeIds.length) return [] as ManualLinkConflict[]
  const params: Array<string[] | string> = [tradeIds]
  let whereClause = 'linked_trade_ids && $1'
  if (excludeLinkId) {
    params.push(excludeLinkId)
    whereClause += ` AND link_id <> $${params.length}`
  }
  const result = await query<ManualLinkConflict>(
    `SELECT link_id,
            manual_package_id,
            linked_trade_ids,
            is_active
     FROM ${MANUAL_LINKS_TABLE}
     WHERE is_active = TRUE AND ${whereClause}`,
    params
  )
  return result.rows
}

export function buildValidationItems(
  legs: ManualLinkLeg[],
  metrics: ReturnType<typeof computeLinkMetrics>,
  conflicts: ManualLinkConflict[]
) {
  const items: ValidationItem[] = []
  const tradeCount = metrics.trade_count ?? legs.length

  if (tradeCount < 2) {
    items.push({
      key: 'trade_count',
      label: 'Trade count',
      status: 'error',
      message: 'Select at least two trades to create a manual link.'
    })
  } else {
    items.push({
      key: 'trade_count',
      label: 'Trade count',
      status: 'ok',
      message: `${tradeCount} trade${tradeCount === 1 ? '' : 's'} selected.`
    })
  }

  if (conflicts.length) {
    const conflictLabels = conflicts
      .map((conflict) => conflict.manual_package_id || conflict.link_id)
      .filter(Boolean)
    const message = conflictLabels.length
      ? `Trades already linked to ${conflictLabels.join(', ')}.`
      : 'One or more trades are already manually linked.'
    items.push({
      key: 'conflicts',
      label: 'Existing manual links',
      status: 'error',
      message
    })
  } else {
    items.push({
      key: 'conflicts',
      label: 'Existing manual links',
      status: 'ok',
      message: 'No existing manual links detected.'
    })
  }

  const packageIds = Array.from(
    new Set(legs.map((leg) => String(leg.package_id || '').trim()).filter(Boolean))
  )
  if (packageIds.length > 1) {
    items.push({
      key: 'package_ids',
      label: 'Package spread',
      status: 'warn',
      message: `Trades span ${packageIds.length} packages.`
    })
  } else {
    items.push({
      key: 'package_ids',
      label: 'Package spread',
      status: 'ok',
      message: 'Trades are in a single package.'
    })
  }

  if (metrics.time_spread_seconds !== null) {
    const spread = metrics.time_spread_seconds
    items.push({
      key: 'time_spread',
      label: 'Execution window',
      status: spread > TIME_SPREAD_WARN_SECONDS ? 'warn' : 'ok',
      message:
        spread > TIME_SPREAD_WARN_SECONDS
          ? `Execution timestamps span ${Math.round(spread)}s.`
          : `Execution timestamps span ${Math.round(spread)}s.`
    })
  } else {
    items.push({
      key: 'time_spread',
      label: 'Execution window',
      status: 'warn',
      message: 'Execution timestamps unavailable.'
    })
  }

  const hasErrors = items.some((item) => item.status === 'error')
  return { items, hasErrors }
}

export async function generateManualPackageId() {
  const token = randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()
  const dateToken = buildDateToken(new Date())
  return `ML-${dateToken}-${token}`
}
