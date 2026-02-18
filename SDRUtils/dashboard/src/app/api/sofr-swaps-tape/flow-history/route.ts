// ABOUTME: Historical forward/tenor flow aggregates for SOFR swaps flow grid mode.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

type FlowHistoryRow = {
  trade_date: string | Date
  bucket: string
  trade_count: number
  gross_notional: number
  gross_risk: number
  avg_fixed_rate: number | null
  idb_trade_count: number
  custy_trade_count: number
}

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
    grossRisk: 0,
    avgFixedRate: null as number | null,
    idbTradeCount: 0,
    custyTradeCount: 0
  }
}

function mergeStatsInto(
  target: ReturnType<typeof createEmptyStats>,
  source: ReturnType<typeof createEmptyStats>
) {
  const totalTrades = target.tradeCount + source.tradeCount
  const weightedAvg =
    source.avgFixedRate === null
      ? target.avgFixedRate
      : target.avgFixedRate === null
        ? source.avgFixedRate
        : ((target.avgFixedRate * target.tradeCount) +
            (source.avgFixedRate * source.tradeCount)) /
          Math.max(1, totalTrades)

  target.tradeCount = totalTrades
  target.grossNotional += source.grossNotional
  target.grossRisk += source.grossRisk
  target.idbTradeCount += source.idbTradeCount
  target.custyTradeCount += source.custyTradeCount
  target.avgFixedRate = weightedAvg
  return target
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const start = searchParams.get('start')
  const end = searchParams.get('end')
  const forwardBoundary = parseNumber(
    searchParams.get('forwardBoundary') ?? searchParams.get('forward_boundary')
  )
  const tenorBoundary = parseNumber(
    searchParams.get('tenorBoundary') ?? searchParams.get('tenor_boundary')
  )
  const tolerance = parseNumber(searchParams.get('tolerance'))
  const platform = (searchParams.get('platform') || 'combined').toLowerCase()

  if (!start || !end) {
    return NextResponse.json(
      { error: 'start and end parameters are required' },
      { status: 400 }
    )
  }
  if (forwardBoundary === null || tenorBoundary === null || tolerance === null) {
    return NextResponse.json(
      {
        error:
          'forwardBoundary, tenorBoundary, and tolerance parameters are required'
      },
      { status: 400 }
    )
  }
  if (!['combined', 'idb', 'custy'].includes(platform)) {
    return NextResponse.json(
      { error: "platform must be 'combined', 'idb', or 'custy'" },
      { status: 400 }
    )
  }

  try {
    const params: Array<string | number> = [
      start,
      end,
      forwardBoundary,
      tenorBoundary,
      tolerance
    ]
    const platformFilter =
      platform === 'combined'
        ? ''
        : platform === 'idb'
          ? "WHERE platform_type = 'idb'"
          : "WHERE platform_type = 'custy'"

    const sql = `
      WITH leg_info AS (
        SELECT
          l.package_id,
          mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier
        FROM arbs_sofr_swap_legs_v1 l
        GROUP BY l.package_id
      ),
      base AS (
        SELECT
          p.execution_start::date AS trade_date,
          p.forward_start_years AS forward_years,
          p.tenor_years AS tenor_years,
          abs(COALESCE(p.total_notional, 0)) AS gross_notional,
          abs(COALESCE(p.total_risk, 0)) AS gross_risk,
          p.weighted_fixed_rate AS fixed_rate,
          CASE
            WHEN li.platform_identifier IS NULL THEN 'custy'
            WHEN EXISTS (
              SELECT 1
              FROM regexp_split_to_table(upper(li.platform_identifier), '[\\s,;/]+') AS token
              WHERE token IN ('BGCD', 'ISWV', 'TPSE')
            ) THEN 'idb'
            ELSE 'custy'
          END AS platform_type
        FROM arbs_sofr_swap_packages_v1 p
        LEFT JOIN leg_info li ON li.package_id = p.package_id
        WHERE p.execution_start >= $1
          AND p.execution_start < $2::date + interval '1 day'
      ),
      classified AS (
        SELECT
          trade_date,
          gross_notional,
          gross_risk,
          fixed_rate,
          platform_type,
          CASE
            WHEN forward_years IS NULL OR tenor_years IS NULL THEN 'UNKNOWN'
            WHEN abs(forward_years - $3) <= $5 OR abs(tenor_years - $4) <= $5 THEN 'BOUNDARY'
            WHEN forward_years < $3 AND tenor_years < $4 THEN 'FRONT_SHORT'
            WHEN forward_years < $3 AND tenor_years >= $4 THEN 'FRONT_LONG'
            WHEN forward_years >= $3 AND tenor_years < $4 THEN 'FORWARD_SHORT'
            ELSE 'FORWARD_LONG'
          END AS bucket
        FROM base
      )
      SELECT
        trade_date,
        bucket,
        COUNT(*) AS trade_count,
        SUM(gross_notional) AS gross_notional,
        SUM(gross_risk) AS gross_risk,
        AVG(fixed_rate) AS avg_fixed_rate,
        COUNT(*) FILTER (WHERE platform_type = 'idb') AS idb_trade_count,
        COUNT(*) FILTER (WHERE platform_type = 'custy') AS custy_trade_count
      FROM classified
      ${platformFilter}
      GROUP BY trade_date, bucket
      ORDER BY trade_date ASC, bucket ASC
    `

    const result = await query<FlowHistoryRow>(sql, params)
    const dayMap = new Map<string, any>()

    const ensureDay = (dateValue: string | Date) => {
      const date = toDateKey(dateValue)
      if (dayMap.has(date)) return dayMap.get(date)
      const day = {
        date,
        quadrants: {
          frontShort: createEmptyStats(),
          frontLong: createEmptyStats(),
          forwardShort: createEmptyStats(),
          forwardLong: createEmptyStats()
        },
        boundary: createEmptyStats(),
        unknown: createEmptyStats(),
        gridTotal: createEmptyStats()
      }
      dayMap.set(date, day)
      return day
    }

    result.rows.forEach((row) => {
      const day = ensureDay(row.trade_date)
      const stats = {
        tradeCount: Number(row.trade_count) || 0,
        grossNotional: Number(row.gross_notional) || 0,
        grossRisk: Number(row.gross_risk) || 0,
        avgFixedRate:
          row.avg_fixed_rate === null || row.avg_fixed_rate === undefined
            ? null
            : Number(row.avg_fixed_rate),
        idbTradeCount: Number(row.idb_trade_count) || 0,
        custyTradeCount: Number(row.custy_trade_count) || 0
      }

      switch (row.bucket) {
        case 'FRONT_SHORT':
          day.quadrants.frontShort = stats
          break
        case 'FRONT_LONG':
          day.quadrants.frontLong = stats
          break
        case 'FORWARD_SHORT':
          day.quadrants.forwardShort = stats
          break
        case 'FORWARD_LONG':
          day.quadrants.forwardLong = stats
          break
        case 'BOUNDARY':
          day.boundary = stats
          break
        default:
          day.unknown = stats
      }
    })

    const days = Array.from(dayMap.values()).sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    )

    days.forEach((day) => {
      const total = createEmptyStats()
      Object.values(day.quadrants).forEach((stats: any) => {
        mergeStatsInto(total, stats)
      })
      day.gridTotal = total
    })

    return NextResponse.json({
      days,
      meta: {
        start,
        end,
        forwardBoundary,
        tenorBoundary,
        tolerance,
        platform,
        tradingDaysCount: days.length
      }
    })
  } catch (error: any) {
    console.error('sofr-swaps-tape/flow-history GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch SOFR swap flow history' },
      { status: 500 }
    )
  }
}
