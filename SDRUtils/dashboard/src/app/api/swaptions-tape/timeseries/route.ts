// ABOUTME: Fetches all trades matching a specific swaption tenor for timeseries charting.
// This endpoint bypasses pagination and returns all matching trades directly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView, TapeRow } from '@/lib/swaptions-tape'

const MAX_TIMESERIES_ROWS = 50000

function parseSeriesKey(seriesKey: string): {
  tenorLabel: string | null
  forwardLabel: string | null
  isFullMatch: boolean
} {
  // Try to parse tenor key format: "1Yx10Y"
  const tenorMatch = seriesKey.match(/^(\d+[DWMY])[xX](\d+[DWMY])$/)
  if (tenorMatch) {
    return {
      forwardLabel: tenorMatch[1],
      tenorLabel: tenorMatch[2],
      isFullMatch: false
    }
  }

  // Otherwise, it's a full match string like "10Y ATM STRADDLE"
  return {
    tenorLabel: null,
    forwardLabel: null,
    isFullMatch: true
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const seriesKey = searchParams.get('seriesKey')
  const excludeCusty = searchParams.get('excludeCusty') === 'true'

  if (!seriesKey) {
    return NextResponse.json(
      { error: 'seriesKey parameter is required' },
      { status: 400 }
    )
  }

  const { tenorLabel, forwardLabel, isFullMatch } = parseSeriesKey(seriesKey)

  try {
    const { view, columns } = await resolveDisplayView()
    const conditions: string[] = []
    const params: unknown[] = []

    // Filter by package type
    conditions.push("d.package_type ILIKE 'STRADDLE'")

    // Filter by action (NEWT-TRAD only)
    conditions.push("plat.event_action = 'NEWT-TRAD'")

    if (!isFullMatch && tenorLabel && forwardLabel) {
      // Match by tenor_label and forward_label
      params.push(tenorLabel)
      conditions.push(`d.tenor_label ILIKE $${params.length}`)
      params.push(forwardLabel)
      conditions.push(`d.forward_label ILIKE $${params.length}`)
    } else {
      // Full match - need to match the entire series key pattern
      // This requires checking trade_label, tenor_label, and forward_label combinations
      params.push(`%${seriesKey}%`)
      const idx = params.length
      conditions.push(`(
        d.tenor_label ILIKE $${idx} OR
        d.forward_label ILIKE $${idx} OR
        d.legs_json::text ILIKE $${idx}
      )`)
    }

    // Exclude custy platforms if requested
    if (excludeCusty) {
      conditions.push(`(
        plat.platform_identifier NOT ILIKE '%BGC%' AND
        plat.platform_identifier NOT ILIKE '%TFS%' AND
        plat.platform_identifier NOT ILIKE '%GFI%' AND
        plat.platform_identifier NOT ILIKE '%ICAP%' AND
        plat.platform_identifier NOT ILIKE '%TRADITION%' AND
        plat.platform_identifier NOT ILIKE '%TP%'
      )`)
    }

    const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

    const result = await query(
      `SELECT ${columns}
       FROM ${view} d
       LEFT JOIN LATERAL (
         SELECT mode() WITHIN GROUP (ORDER BY platform_identifier) AS platform_identifier
               , mode() WITHIN GROUP (ORDER BY event_action) AS event_action
         FROM arbs_swaption_legs_v1 l
         WHERE l.package_id = d.package_id
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
