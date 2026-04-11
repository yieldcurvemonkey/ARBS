import { randomUUID } from 'crypto'
import { query } from '@/lib/db'

export const MANUAL_LINKS_TABLE = 'arbs_usd_swap_manual_links_v2'
export const MANUAL_LINK_HISTORY_TABLE = 'arbs_usd_swap_link_history_v2'
export const LEGS_TABLE = 'arbs_usd_swap_legs_v2'
export const PACKAGES_TABLE = 'arbs_usd_swap_packages_v2'

type ManualLinkLeg = {
  trade_id: string
  package_id: string
  trade_label?: string | null
  product_type?: string | null
  notional?: number | string | null
  risk?: number | string | null
  fixed_rate?: number | string | null
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

function meanNumbers(values: Array<number | null>) {
  const valid = values.filter((value): value is number => value !== null)
  if (!valid.length) return null
  return valid.reduce((acc, value) => acc + value, 0) / valid.length
}

function minNumbers(values: Array<number | null>) {
  const valid = values.filter((value): value is number => value !== null)
  if (!valid.length) return null
  return Math.min(...valid)
}

function maxNumbers(values: Array<number | null>) {
  const valid = values.filter((value): value is number => value !== null)
  if (!valid.length) return null
  return Math.max(...valid)
}

function buildDateToken(date: Date) {
  const yyyy = String(date.getUTCFullYear())
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(date.getUTCDate()).padStart(2, '0')
  return `${yyyy}${mm}${dd}`
}

export async function checkManualLinkTables() {
  const result = await query<{
    links: string | null
    history: string | null
    legs: string | null
    packages: string | null
  }>(
    'SELECT to_regclass($1) AS links, to_regclass($2) AS history, to_regclass($3) AS legs, to_regclass($4) AS packages',
    [MANUAL_LINKS_TABLE, MANUAL_LINK_HISTORY_TABLE, LEGS_TABLE, PACKAGES_TABLE]
  )
  const row = result.rows[0]
  const linksTable = Boolean(row?.links)
  const historyTable = Boolean(row?.history)
  const legsTable = Boolean(row?.legs)
  const packagesTable = Boolean(row?.packages)
  const missingTables: string[] = []
  if (!linksTable) missingTables.push(MANUAL_LINKS_TABLE)
  if (!historyTable) missingTables.push(MANUAL_LINK_HISTORY_TABLE)
  if (!legsTable) missingTables.push(LEGS_TABLE)
  if (!packagesTable) missingTables.push(PACKAGES_TABLE)
  return { linksTable, historyTable, legsTable, packagesTable, missingTables }
}

export function normalizeIdList(input: unknown) {
  if (!input) return []
  const rawValues = Array.isArray(input) ? input : String(input).split(/[\s,]+/)
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
            risk,
            fixed_rate,
            execution_timestamp,
            platform_identifier,
            leg_metrics,
            package_type,
            manual_link_id,
            is_manually_linked
     FROM ${LEGS_TABLE}
     WHERE trade_id = ANY($1)`,
    [tradeIds]
  )
  return result.rows
}

export function computeLinkMetrics(legs: ManualLinkLeg[]) {
  const notionalValues = legs.map((leg) => toNumber(leg.notional))
  const riskValues = legs.map((leg) => toNumber(leg.risk))
  const fixedRateValues = legs.map((leg) => toNumber(leg.fixed_rate))

  const timestamps = legs
    .map((leg) =>
      leg.execution_timestamp ? Date.parse(leg.execution_timestamp) : NaN
    )
    .filter((value) => Number.isFinite(value))

  const minTs = timestamps.length ? Math.min(...timestamps) : null
  const maxTs = timestamps.length ? Math.max(...timestamps) : null
  const timeSpreadSeconds =
    minTs !== null && maxTs !== null ? (maxTs - minTs) / 1000 : null

  return {
    trade_count: legs.length,
    total_notional: sumNumbers(notionalValues),
    gross_notional: sumNumbers(notionalValues.map((value) => (value === null ? null : Math.abs(value)))),
    total_risk: sumNumbers(riskValues),
    gross_risk: sumNumbers(riskValues.map((value) => (value === null ? null : Math.abs(value)))),
    avg_fixed_rate: meanNumbers(fixedRateValues),
    min_fixed_rate: minNumbers(fixedRateValues),
    max_fixed_rate: maxNumbers(fixedRateValues),
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
      message: `Execution timestamps span ${Math.round(spread)}s.`
    })
  } else {
    items.push({
      key: 'time_spread',
      label: 'Execution window',
      status: 'warn',
      message: 'Execution timestamps unavailable.'
    })
  }

  const riskValue = metrics.gross_risk
  if (riskValue === null || riskValue === 0) {
    items.push({
      key: 'risk',
      label: 'Risk coverage',
      status: 'warn',
      message: 'Gross risk is zero or unavailable.'
    })
  } else {
    items.push({
      key: 'risk',
      label: 'Risk coverage',
      status: 'ok',
      message: `Gross risk ${riskValue.toFixed(0)}.`
    })
  }

  const hasErrors = items.some((item) => item.status === 'error')
  return { items, hasErrors }
}

export async function generateManualPackageId() {
  const token = randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()
  const dateToken = buildDateToken(new Date())
  return `SML-${dateToken}-${token}`
}

export async function applyManualLinkToTrades(linkId: string, tradeIds: string[]) {
  if (!tradeIds.length) return
  await query(
    `UPDATE ${LEGS_TABLE}
     SET manual_link_id = NULL,
         is_manually_linked = FALSE,
         updated_at = NOW()
     WHERE manual_link_id = $1
       AND NOT (trade_id = ANY($2))`,
    [linkId, tradeIds]
  )

  await query(
    `UPDATE ${LEGS_TABLE}
     SET manual_link_id = $1,
         is_manually_linked = TRUE,
         updated_at = NOW()
     WHERE trade_id = ANY($2)`,
    [linkId, tradeIds]
  )

  await query(
    `UPDATE ${PACKAGES_TABLE}
     SET manual_link_id = $1,
         package_source = 'MANUAL',
         updated_at = NOW()
     WHERE package_id IN (
       SELECT DISTINCT package_id
       FROM ${LEGS_TABLE}
       WHERE trade_id = ANY($2)
     )`,
    [linkId, tradeIds]
  )

  await query(
    `UPDATE ${PACKAGES_TABLE} p
     SET manual_link_id = NULL,
         package_source = CASE
           WHEN p.package_source = 'MANUAL' THEN 'AUTO'
           ELSE p.package_source
         END,
         updated_at = NOW()
     WHERE p.manual_link_id = $1
       AND NOT EXISTS (
         SELECT 1
         FROM ${LEGS_TABLE} l
         WHERE l.package_id = p.package_id
           AND l.manual_link_id = $1
       )`,
    [linkId]
  )
}

export async function clearManualLinkFromTrades(linkId: string) {
  await query(
    `UPDATE ${LEGS_TABLE}
     SET manual_link_id = NULL,
         is_manually_linked = FALSE,
         updated_at = NOW()
     WHERE manual_link_id = $1`,
    [linkId]
  )
  await query(
    `UPDATE ${PACKAGES_TABLE}
     SET manual_link_id = NULL,
         package_source = CASE
           WHEN package_source = 'MANUAL' THEN 'AUTO'
           ELSE package_source
         END,
         updated_at = NOW()
     WHERE manual_link_id = $1`,
    [linkId]
  )
}

