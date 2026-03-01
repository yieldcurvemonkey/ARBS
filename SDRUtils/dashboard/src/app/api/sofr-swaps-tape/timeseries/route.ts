// ABOUTME: Fetches all SOFR swaps for a strict forward x tenor series key.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView, SofrSwapTapeRow } from '@/lib/sofr-swaps-tape'
import { parseSeriesKey } from '@/lib/sofr-swaps-api-utils'

const MAX_TIMESERIES_ROWS = 50_000
const LEGS_TABLE = 'arbs_usd_swap_legs_v2'
const IDB_MIC_CODES = ['BGCD', 'ISWV', 'TPSE']
const FORWARD_YEARS_TOLERANCE = 0.06
const TENOR_YEARS_TOLERANCE = 0.1
const SPOT_FORWARD_MAX_YEARS = 0.08

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const seriesKey = searchParams.get('seriesKey')
  const packageTypeParam = searchParams.get('packageType')
  const platformParam = (searchParams.get('platform') || 'combined').trim()

  if (!seriesKey) {
    return NextResponse.json(
      { error: 'seriesKey parameter is required' },
      { status: 400 }
    )
  }

  const { tenorLabel, forwardLabel, tenorYears, forwardYears, isValid } =
    parseSeriesKey(seriesKey)
  if (
    !isValid ||
    !tenorLabel ||
    !forwardLabel ||
    tenorYears === null ||
    forwardYears === null
  ) {
    return NextResponse.json(
      {
        error: 'seriesKey must be a strict forward x tenor key (e.g. 3Mx10Y).'
      },
      { status: 400 }
    )
  }

  try {
    const { view, columns } = await resolveDisplayView()
    const conditions: string[] = []
    const params: unknown[] = []

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
    }

    params.push(tenorLabel)
    const tenorLabelParam = params.length
    params.push(tenorYears)
    const tenorYearsParam = params.length
    conditions.push(
      `(d.tenor_label ILIKE $${tenorLabelParam} OR (d.tenor_years IS NOT NULL AND ABS(d.tenor_years - $${tenorYearsParam}) <= ${TENOR_YEARS_TOLERANCE}))`
    )

    params.push(forwardLabel)
    const forwardLabelParam = params.length
    params.push(forwardYears)
    const forwardYearsParam = params.length
    const forwardClauses = [
      `d.forward_label ILIKE $${forwardLabelParam}`,
      `(d.forward_start_years IS NOT NULL AND ABS(d.forward_start_years - $${forwardYearsParam}) <= ${FORWARD_YEARS_TOLERANCE})`
    ]
    if (forwardYears <= SPOT_FORWARD_MAX_YEARS) {
      forwardClauses.push(
        `coalesce(lower(trim(d.forward_label)), '') IN ('spot', '0d', '0w', '0m', '0y')`
      )
    }
    conditions.push(`(${forwardClauses.join(' OR ')})`)

    const normalizedPlatform = platformParam.toLowerCase()
    if (normalizedPlatform && normalizedPlatform !== 'combined') {
      if (normalizedPlatform === 'idb') {
        conditions.push(
          `EXISTS (
            SELECT 1
            FROM regexp_split_to_table(upper(coalesce(plat.platform_identifier, '')), '[\\s,;/]+') AS token
            WHERE token IN ('BGCD', 'ISWV', 'TPSE')
          )`
        )
      } else if (normalizedPlatform === 'custy') {
        conditions.push(
          `NOT EXISTS (
            SELECT 1
            FROM regexp_split_to_table(upper(coalesce(plat.platform_identifier, '')), '[\\s,;/]+') AS token
            WHERE token IN ('BGCD', 'ISWV', 'TPSE')
          )`
        )
      } else {
        params.push(`%${platformParam}%`)
        conditions.push(`coalesce(plat.platform_identifier, '') ILIKE $${params.length}`)
      }
    }

    if (IDB_MIC_CODES.length === 0) {
      return NextResponse.json({ rows: [], count: 0, truncated: false })
    }

    const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

    const result = await query(
      `SELECT ${columns}
       FROM ${view} d
       LEFT JOIN LATERAL (
         SELECT mode() WITHIN GROUP (ORDER BY platform_identifier) AS platform_identifier
               , mode() WITHIN GROUP (ORDER BY event_action) AS event_action
         FROM ${LEGS_TABLE} l
         WHERE l.package_id = d.package_id
       ) plat ON TRUE
       ${whereClause}
       ORDER BY d.execution_start ASC
       LIMIT ${MAX_TIMESERIES_ROWS}`,
      params
    )

    const rows = result.rows as SofrSwapTapeRow[]
    return NextResponse.json({
      rows,
      count: rows.length,
      truncated: rows.length >= MAX_TIMESERIES_ROWS
    })
  } catch (error: any) {
    console.error('sofr-swaps-tape/timeseries GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch SOFR swaps timeseries data' },
      { status: 500 }
    )
  }
}
