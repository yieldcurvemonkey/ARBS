import { query } from '@/lib/db'
import type { TapeRow } from '@/features/swaptions-tape/types'

const SWAPTION_DISPLAY_VIEW_V1 = 'arbs_swaption_display_items_v1'
const SWAPTION_DISPLAY_VIEW_V2 = 'arbs_swaption_display_items_v2'
const CAPFLOOR_DISPLAY_VIEW_V1 = 'arbs_capfloor_display_items_v1'
const SWAPTION_LEGS_TABLE = 'arbs_swaption_legs_v1'
const CAPFLOOR_LEGS_TABLE = 'arbs_capfloor_legs_v1'

export const DISPLAY_PACKAGE_TYPE_SQL = `CASE
  WHEN UPPER(REPLACE(COALESCE(d.package_type, ''), '-', '_')) = 'OUTRIGHT'
   AND UPPER(COALESCE(plat.product_type, '')) IN ('CAP', 'FLOOR')
  THEN UPPER(plat.product_type)
  ELSE COALESCE(d.package_type, '')
END`

type DisplayView = {
  sourceSql: string
  platformLateralSql: string
  columns: string
}

const COLUMNS = [
  'd.package_id',
  'd.package_type',
  `${DISPLAY_PACKAGE_TYPE_SQL} AS reported_package_type`,
  'd.package_source',
  'd.manual_link_id',
  'd.manual_package_id',
  'd.user_comment',
  'd.link_reason',
  'd.tags',
  'd.link_created_by',
  'd.link_created_at',
  'd.link_metrics',
  'd.as_of_date',
  'd.execution_start',
  'd.execution_end',
  'd.expiration_date',
  'd.underlying_expiration_date',
  'd.tenor_label',
  'd.forward_label',
  'd.legs_count',
  'd.total_notional',
  'd.total_premium',
  'd.package_indicator',
  'd.package_transaction_price',
  'd.package_confidence',
  'd.package_reason',
  'd.vega_curve_id',
  'd.vega_curve_type',
  'd.package_metrics',
  'd.legs_json',
  'd.economic_notional',
  'plat.platform_identifier',
  'plat.event_action'
].join(', ')

let cachedView: DisplayView | null = null
let cachedAt = 0
const CACHE_TTL_MS = 60_000

async function relationExists(name: string) {
  try {
    const result = await query<{ rel: string | null }>(
      'SELECT to_regclass($1) AS rel',
      [name]
    )
    return Boolean(result.rows[0]?.rel)
  } catch (error) {
    console.warn('swaptions-tape relation check failed', error)
    return false
  }
}

function buildSwaptionSourceSql(viewName: string, hasManualFields: boolean) {
  if (hasManualFields) {
    return `
      SELECT
        d.package_id,
        d.package_type,
        d.package_source,
        d.link_id AS manual_link_id,
        d.manual_package_id,
        d.user_comment,
        d.link_reason,
        d.tags,
        d.link_created_by,
        d.link_created_at,
        d.link_metrics,
        d.as_of_date,
        d.execution_start,
        d.execution_end,
        d.expiration_date,
        d.underlying_expiration_date,
        d.tenor_label,
        d.forward_label,
        d.legs_count,
        d.total_notional,
        d.total_premium,
        d.package_indicator,
        d.package_transaction_price,
        d.package_confidence,
        d.package_reason,
        d.vega_curve_id,
        d.vega_curve_type,
        d.package_metrics,
        d.legs_json,
        d.economic_notional
      FROM ${viewName} d
    `
  }

  return `
    SELECT
      d.package_id,
      d.package_type,
      NULL::text AS package_source,
      NULL::uuid AS manual_link_id,
      NULL::text AS manual_package_id,
      NULL::text AS user_comment,
      NULL::text AS link_reason,
      NULL::text[] AS tags,
      NULL::text AS link_created_by,
      NULL::timestamptz AS link_created_at,
      NULL::jsonb AS link_metrics,
      d.as_of_date,
      d.execution_start,
      d.execution_end,
      d.expiration_date,
      d.underlying_expiration_date,
      d.tenor_label,
      d.forward_label,
      d.legs_count,
      d.total_notional,
      d.total_premium,
      d.package_indicator,
      d.package_transaction_price,
      d.package_confidence,
      d.package_reason,
      d.vega_curve_id,
      d.vega_curve_type,
      d.package_metrics,
      d.legs_json,
      d.economic_notional
    FROM ${viewName} d
  `
}

function buildCapFloorSourceSql() {
  return `
    SELECT
      d.package_id,
      d.package_type,
      NULL::text AS package_source,
      NULL::uuid AS manual_link_id,
      NULL::text AS manual_package_id,
      NULL::text AS user_comment,
      NULL::text AS link_reason,
      NULL::text[] AS tags,
      NULL::text AS link_created_by,
      NULL::timestamptz AS link_created_at,
      NULL::jsonb AS link_metrics,
      d.as_of_date,
      d.execution_start,
      d.execution_end,
      d.expiration_date,
      d.underlying_expiration_date,
      d.tenor_label,
      d.forward_label,
      d.legs_count,
      d.total_notional,
      d.total_premium,
      d.package_indicator,
      d.package_transaction_price,
      d.package_confidence,
      d.package_reason,
      d.vega_curve_id,
      d.vega_curve_type,
      d.package_metrics,
      d.legs_json,
      d.economic_notional
    FROM ${CAPFLOOR_DISPLAY_VIEW_V1} d
  `
}

function buildPlatformLateralSql(legTableNames: string[]) {
  if (!legTableNames.length) {
    return `
      SELECT
        mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier,
        mode() WITHIN GROUP (ORDER BY l.event_action) AS event_action,
        mode() WITHIN GROUP (ORDER BY l.product_type) AS product_type,
        mode() WITHIN GROUP (ORDER BY l.trade_label) AS trade_label
      FROM (
        SELECT
          NULL::text AS platform_identifier,
          NULL::text AS event_action,
          NULL::text AS product_type,
          NULL::text AS trade_label
        LIMIT 0
      ) l
    `
  }

  const legSources = legTableNames.map(
    (tableName) => `
      SELECT
        l.platform_identifier,
        l.event_action,
        l.product_type,
        l.trade_label
      FROM ${tableName} l
      WHERE l.package_id = d.package_id
    `
  )

  return `
    SELECT
      mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier,
      mode() WITHIN GROUP (ORDER BY l.event_action) AS event_action,
      mode() WITHIN GROUP (ORDER BY l.product_type) AS product_type,
      mode() WITHIN GROUP (ORDER BY l.trade_label) AS trade_label
    FROM (
      ${legSources.join('\nUNION ALL\n')}
    ) l
  `
}

export async function resolveDisplayView(): Promise<DisplayView> {
  const now = Date.now()
  if (cachedView && now - cachedAt < CACHE_TTL_MS) {
    return cachedView
  }

  const [
    hasSwaptionV2,
    hasSwaptionV1,
    hasCapFloorView,
    hasSwaptionLegs,
    hasCapFloorLegs
  ] = await Promise.all([
    relationExists(SWAPTION_DISPLAY_VIEW_V2),
    relationExists(SWAPTION_DISPLAY_VIEW_V1),
    relationExists(CAPFLOOR_DISPLAY_VIEW_V1),
    relationExists(SWAPTION_LEGS_TABLE),
    relationExists(CAPFLOOR_LEGS_TABLE)
  ])

  const sourceQueries: string[] = []
  if (hasSwaptionV2) {
    sourceQueries.push(buildSwaptionSourceSql(SWAPTION_DISPLAY_VIEW_V2, true))
  } else if (hasSwaptionV1) {
    sourceQueries.push(buildSwaptionSourceSql(SWAPTION_DISPLAY_VIEW_V1, false))
  }
  if (hasCapFloorView) {
    sourceQueries.push(buildCapFloorSourceSql())
  }

  if (!sourceQueries.length) {
    throw new Error('No swaption/capfloor display views are available')
  }

  const legTableNames = [
    ...(hasSwaptionLegs ? [SWAPTION_LEGS_TABLE] : []),
    ...(hasCapFloorLegs ? [CAPFLOOR_LEGS_TABLE] : [])
  ]

  cachedView = {
    sourceSql: `(${sourceQueries.join('\nUNION ALL\n')})`,
    platformLateralSql: buildPlatformLateralSql(legTableNames),
    columns: COLUMNS
  }
  cachedAt = now
  return cachedView
}

export type { TapeRow }
