// ABOUTME: Fetches all trades matching a specific swaption tenor for timeseries charting.
// This endpoint bypasses pagination and returns all matching trades directly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView, TapeRow } from '@/lib/swaptions-tape'

const MAX_TIMESERIES_ROWS = 50000
const IDB_MIC_CODES = ['BGCD', 'ISWV', 'TPSE']

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
    const { view, columns } = await resolveDisplayView()
    const conditions: string[] = []
    const params: unknown[] = []

    // Filter by package type
    if (packageTypeParam) {
      const normalized = packageTypeParam.toUpperCase().replace(/-/g, '_')
      params.push(normalized)
      if (normalized === 'OUTRIGHT') {
        conditions.push(
          `(d.package_type IS NULL OR UPPER(REPLACE(d.package_type, '-', '_')) = $${params.length})`
        )
      } else {
        conditions.push(
          `UPPER(REPLACE(d.package_type, '-', '_')) = $${params.length}`
        )
      }
    } else {
      conditions.push("d.package_type ILIKE 'STRADDLE'")
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
