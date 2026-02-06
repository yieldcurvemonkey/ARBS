// ABOUTME: Historical quadrant aggregates for Vol Grid Flow history mode.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

type QuadrantHistoryRow = {
  trade_date: string | Date
  quadrant: string
  trade_count: number
  gross_notional: number
  net_notional: number
  total_premium: number
  custy_trade_count: number
  idb_trade_count: number
  custy_gross: number
  idb_gross: number
  custy_premium: number
  idb_premium: number
}

const COMICALLY_LARGE_CUSTY_NOTIONAL = 100_000_000_000_000

function parseNumber(value: string | null): number | null {
  if (!value) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function toDateKey(value: string | Date): string {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10)
  }
  if (typeof value === 'string') {
    const match = value.match(/^(\d{4}-\d{2}-\d{2})/)
    if (match) return match[1]
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString().slice(0, 10)
    }
  }
  return String(value)
}

function createEmptyStats() {
  return {
    tradeCount: 0,
    grossNotional: 0,
    netNotional: 0,
    netDirection: 'balanced' as const,
    netGrossRatio: 0,
    totalPremium: 0,
    custyTradeCount: 0,
    idbTradeCount: 0,
    custyGross: 0,
    idbGross: 0,
    custyPremium: 0,
    idbPremium: 0,
  }
}

function normalizeStats(stats: ReturnType<typeof createEmptyStats>) {
  const gross = stats.grossNotional
  const net = stats.netNotional
  stats.netGrossRatio = gross > 0 ? Math.abs(net) / gross : 0
  if (gross === 0) {
    stats.netDirection = 'balanced'
  } else if (stats.netGrossRatio < 0.1) {
    stats.netDirection = 'balanced'
  } else {
    stats.netDirection = net >= 0 ? 'payer' : 'receiver'
  }
  return stats
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const start = searchParams.get('start')
  const end = searchParams.get('end')
  const expiryBoundary = parseNumber(searchParams.get('expiry_boundary'))
  const tenorBoundary = parseNumber(searchParams.get('tenor_boundary'))
  const tolerance = parseNumber(searchParams.get('tolerance'))
  const platform = (searchParams.get('platform') || 'combined').toLowerCase()
  const excludeLargeCustyNotional =
    searchParams.get('excludeLargeCustyNotional') === 'true'

  if (!start || !end) {
    return NextResponse.json({ error: 'start and end parameters are required' }, { status: 400 })
  }
  if (expiryBoundary === null || tenorBoundary === null || tolerance === null) {
    return NextResponse.json(
      { error: 'expiry_boundary, tenor_boundary, and tolerance are required' },
      { status: 400 },
    )
  }
  if (!['combined', 'idb', 'custy'].includes(platform)) {
    return NextResponse.json(
      { error: "platform must be 'combined', 'idb', or 'custy'" },
      { status: 400 },
    )
  }

  try {
    const params: Array<string | number> = [start, end, expiryBoundary, tenorBoundary, tolerance]
    let largeCustyParamIndex: number | null = null
    if (excludeLargeCustyNotional) {
      params.push(COMICALLY_LARGE_CUSTY_NOTIONAL)
      largeCustyParamIndex = params.length
    }

    const whereClauses: string[] = []
    if (platform !== 'combined') {
      whereClauses.push(`platform_type = '${platform}'`)
    }
    if (excludeLargeCustyNotional && largeCustyParamIndex) {
      whereClauses.push(
        `NOT (platform_type = 'custy' AND abs(total_notional) >= $${largeCustyParamIndex})`,
      )
    }
    const whereClause = whereClauses.length ? `WHERE ${whereClauses.join(' AND ')}` : ''

    const sql = `
      WITH leg_info AS (
        SELECT
          l.package_id,
          bool_or(upper(coalesce(l.product_type, '')) LIKE '%PAYER%' OR upper(coalesce(l.trade_label, '')) LIKE '%PAYER%') AS has_payer,
          bool_or(upper(coalesce(l.product_type, '')) LIKE '%RECEIVER%' OR upper(coalesce(l.trade_label, '')) LIKE '%RECEIVER%') AS has_receiver,
          mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier,
          SUM(CASE WHEN l.premium IS NOT NULL THEN l.premium ELSE 0 END) AS leg_premium_sum,
          SUM(CASE WHEN l.premium IS NOT NULL THEN l.premium * 0.5 ELSE 0 END) AS leg_straddle_premium_sum,
          COUNT(*) FILTER (WHERE l.premium IS NOT NULL) AS leg_premium_count
        FROM arbs_swaption_legs_v1 l
        GROUP BY l.package_id
      ),
      base AS (
        SELECT
          p.execution_start::date AS trade_date,
          COALESCE(p.total_notional, 0) AS total_notional,
          p.forward_start_years AS forward_years,
          p.tenor_years AS tenor_years,
          upper(replace(coalesce(p.package_type, ''), '-', '_')) AS package_type,
          CASE
            WHEN upper(replace(coalesce(p.package_type, ''), '-', '_')) = 'STRADDLE'
              AND COALESCE(li.leg_premium_count, 0) > 0
              THEN COALESCE(li.leg_straddle_premium_sum, 0)
            WHEN COALESCE(li.leg_premium_count, 0) > 0
              THEN COALESCE(li.leg_premium_sum, 0)
            ELSE COALESCE(p.total_premium, 0)
          END AS total_premium,
          li.platform_identifier AS platform_identifier,
          li.has_payer AS has_payer,
          li.has_receiver AS has_receiver
        FROM arbs_swaption_packages_v1 p
        LEFT JOIN leg_info li ON li.package_id = p.package_id
        WHERE p.execution_start >= $1
          AND p.execution_start < $2::date + interval '1 day'
      ),
      classified AS (
        SELECT
          trade_date,
          total_notional,
          total_premium,
          CASE
            WHEN forward_years IS NULL OR tenor_years IS NULL THEN 'UNCLASSIFIED'
            WHEN abs(forward_years - $3) <= $5 OR abs(tenor_years - $4) <= $5 THEN 'BOUNDARY'
            WHEN forward_years < $3 AND tenor_years < $4 THEN 'ULC'
            WHEN forward_years < $3 AND tenor_years >= $4 THEN 'URC'
            WHEN forward_years >= $3 AND tenor_years < $4 THEN 'LLC'
            ELSE 'LRC'
          END AS quadrant,
          CASE
            WHEN has_payer AND has_receiver THEN 'MIXED'
            WHEN has_payer THEN 'PAYER'
            WHEN has_receiver THEN 'RECEIVER'
            WHEN package_type LIKE '%PAYER%' AND package_type NOT LIKE '%RECEIVER%' THEN 'PAYER'
            WHEN package_type LIKE '%RECEIVER%' AND package_type NOT LIKE '%PAYER%' THEN 'RECEIVER'
            WHEN package_type IN ('STRADDLE', 'RISK_REVERSAL', 'CUSTY_RR_STRANGLE') THEN 'MIXED'
            WHEN package_type LIKE 'VERTICAL_SPREAD%' THEN 'MIXED'
            ELSE 'UNKNOWN'
          END AS direction,
          CASE
            WHEN platform_identifier IS NULL THEN 'custy'
            WHEN EXISTS (
              SELECT 1
              FROM regexp_split_to_table(upper(platform_identifier), '[\\s,;/]+') AS token
              WHERE token IN ('BGCD', 'ISWV', 'TPSE')
            ) THEN 'idb'
            ELSE 'custy'
          END AS platform_type
        FROM base
      )
      SELECT
        trade_date,
        quadrant,
        COUNT(*) AS trade_count,
        SUM(abs(total_notional)) AS gross_notional,
        SUM(
          CASE
            WHEN direction = 'PAYER' THEN total_notional
            WHEN direction = 'RECEIVER' THEN -total_notional
            ELSE 0
          END
        ) AS net_notional,
        SUM(total_premium) AS total_premium,
        COUNT(*) FILTER (WHERE platform_type = 'custy') AS custy_trade_count,
        COUNT(*) FILTER (WHERE platform_type = 'idb') AS idb_trade_count,
        SUM(abs(total_notional)) FILTER (WHERE platform_type = 'custy') AS custy_gross,
        SUM(abs(total_notional)) FILTER (WHERE platform_type = 'idb') AS idb_gross,
        SUM(total_premium) FILTER (WHERE platform_type = 'custy') AS custy_premium,
        SUM(total_premium) FILTER (WHERE platform_type = 'idb') AS idb_premium
      FROM classified
      ${whereClause}
      GROUP BY trade_date, quadrant
      ORDER BY trade_date ASC, quadrant ASC
    `

    const result = await query<QuadrantHistoryRow>(sql, params)

    const dayMap = new Map<string, any>()
    const ensureDay = (dateValue: string | Date) => {
      const date = toDateKey(dateValue)
      if (dayMap.has(date)) return dayMap.get(date)
      const day = {
        date,
        quadrants: {
          ULC: createEmptyStats(),
          URC: createEmptyStats(),
          LLC: createEmptyStats(),
          LRC: createEmptyStats(),
        },
        boundary: createEmptyStats(),
        unclassified: createEmptyStats(),
        gridTotal: createEmptyStats(),
      }
      dayMap.set(date, day)
      return day
    }

    result.rows.forEach((row) => {
      const day = ensureDay(row.trade_date)
      const stats = {
        tradeCount: Number(row.trade_count) || 0,
        grossNotional: Number(row.gross_notional) || 0,
        netNotional: Number(row.net_notional) || 0,
        netDirection: 'balanced' as const,
        netGrossRatio: 0,
        totalPremium: Number(row.total_premium) || 0,
        custyTradeCount: Number(row.custy_trade_count) || 0,
        idbTradeCount: Number(row.idb_trade_count) || 0,
        custyGross: Number(row.custy_gross) || 0,
        idbGross: Number(row.idb_gross) || 0,
        custyPremium: Number(row.custy_premium) || 0,
        idbPremium: Number(row.idb_premium) || 0,
      }
      normalizeStats(stats)

      switch (row.quadrant) {
        case 'ULC':
        case 'URC':
        case 'LLC':
        case 'LRC':
          day.quadrants[row.quadrant] = stats
          break
        case 'BOUNDARY':
          day.boundary = stats
          break
        default:
          day.unclassified = stats
      }
    })

    const days = Array.from(dayMap.values()).sort((a, b) =>
      String(a.date).localeCompare(String(b.date)),
    )

    days.forEach((day) => {
      const total = createEmptyStats()
      Object.values(day.quadrants).forEach((stats: any) => {
        total.tradeCount += stats.tradeCount
        total.grossNotional += stats.grossNotional
        total.netNotional += stats.netNotional
        total.totalPremium += stats.totalPremium
        total.custyTradeCount += stats.custyTradeCount
        total.idbTradeCount += stats.idbTradeCount
        total.custyGross += stats.custyGross
        total.idbGross += stats.idbGross
        total.custyPremium += stats.custyPremium
        total.idbPremium += stats.idbPremium
      })
      day.gridTotal = normalizeStats(total)
    })

    return NextResponse.json({
      days,
      meta: {
        start,
        end,
        tradingDaysCount: days.length,
        expiryBoundary,
        tenorBoundary,
        tolerance,
        platform,
      },
    })
  } catch (error: any) {
    console.error('swaptions-tape/quadrant-history GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch quadrant history' },
      { status: 500 },
    )
  }
}
