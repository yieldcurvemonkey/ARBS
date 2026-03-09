// ABOUTME: Fetches all trades matching a specific swaption tenor for timeseries charting.
// This endpoint bypasses pagination and returns all matching trades directly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  DISPLAY_PACKAGE_TYPE_SQL,
  resolveDisplayView,
  TapeRow
} from '@/lib/swaptions-tape'

const MAX_TIMESERIES_ROWS = 50000
const IDB_MIC_CODES = ['BGCD', 'ISWV', 'TPSE']
const COMICALLY_LARGE_CUSTY_NOTIONAL = 100_000_000_000_000

function parseSeriesKey(seriesKey: string): {
  tenorLabel: string | null
  forwardLabel: string | null
  isValid: boolean
} {
  // Parse strict tenor key format: "1Yx10Y"
  const tenorMatch = seriesKey.match(
    /^(\d+(?:\.\d+)?[DWMY])[xX](\d+(?:\.\d+)?[DWMY])$/i
  )
  if (tenorMatch) {
    return {
      forwardLabel: tenorMatch[1],
      tenorLabel: tenorMatch[2],
      isValid: true
    }
  }

  return {
    tenorLabel: null,
    forwardLabel: null,
    isValid: false
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const seriesKey = searchParams.get('seriesKey')
  const excludeCusty = searchParams.get('excludeCusty') === 'true'
  const excludeLargeCustyNotional =
    searchParams.get('excludeLargeCustyNotional') === 'true'
  const packageTypeParam = searchParams.get('packageType')

  if (!seriesKey) {
    return NextResponse.json(
      { error: 'seriesKey parameter is required' },
      { status: 400 }
    )
  }

  const { tenorLabel, forwardLabel, isValid } = parseSeriesKey(seriesKey)

  try {
    if (!isValid || !tenorLabel || !forwardLabel) {
      return NextResponse.json(
        {
          error:
            'seriesKey must be a strict forward x tenor key (e.g. 3Mx10Y).'
        },
        { status: 400 }
      )
    }
    const { sourceSql, platformLateralSql, columns } = await resolveDisplayView()
    const conditions: string[] = []
    const params: unknown[] = []

    // Filter by package type
    if (packageTypeParam) {
      const normalized = packageTypeParam.toUpperCase().replace(/-/g, '_')
      params.push(normalized)
      conditions.push(
        `UPPER(REPLACE(COALESCE(${DISPLAY_PACKAGE_TYPE_SQL}, ''), '-', '_')) = $${params.length}`
      )
    } else {
      conditions.push(
        `UPPER(REPLACE(COALESCE(${DISPLAY_PACKAGE_TYPE_SQL}, ''), '-', '_')) = 'STRADDLE'`
      )
    }

    // Filter by action (NEWT-TRAD only)
    conditions.push("plat.event_action = 'NEWT-TRAD'")

    // Match by tenor_label and forward_label
    params.push(tenorLabel)
    conditions.push(`d.tenor_label ILIKE $${params.length}`)
    params.push(forwardLabel)
    conditions.push(`d.forward_label ILIKE $${params.length}`)

    // Exclude custy platforms if requested (keep IDB MICs only)
    if (excludeCusty) {
      const idbPlaceholders = IDB_MIC_CODES.map(
        (_, idx) => `$${params.length + idx + 1}`
      ).join(', ')
      params.push(...IDB_MIC_CODES)
      conditions.push(
        `UPPER(plat.platform_identifier) IN (${idbPlaceholders})`
      )
    }

    if (excludeLargeCustyNotional) {
      params.push(COMICALLY_LARGE_CUSTY_NOTIONAL)
      const thresholdParam = `$${params.length}`
      conditions.push(
        `NOT (
          abs(coalesce(d.total_notional, 0)) >= ${thresholdParam}
          AND NOT EXISTS (
            SELECT 1
            FROM regexp_split_to_table(upper(coalesce(plat.platform_identifier, '')), '[\\s,;/]+') AS token
            WHERE token IN ('BGCD', 'ISWV', 'TPSE')
          )
        )`
      )
    }

    const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

    const result = await query(
      `SELECT ${columns}
       FROM ${sourceSql} d
       LEFT JOIN LATERAL (
         ${platformLateralSql}
       ) plat ON TRUE
       ${whereClause}
       ORDER BY d.execution_start ASC
       LIMIT ${MAX_TIMESERIES_ROWS}`,
      params
    )

    const rows = result.rows as TapeRow[]

    return NextResponse.json({
      rows,
      count: rows.length,
      truncated: rows.length >= MAX_TIMESERIES_ROWS
    })
  } catch (error: any) {
    console.error('swaptions-tape/timeseries GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch timeseries data' },
      { status: 500 }
    )
  }
}
