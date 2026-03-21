// ABOUTME: API route for timeseries explorer — queries Supabase computed timeseries tables.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const view = searchParams.get('view') || 'overview'
  const symbol = searchParams.get('symbol') || null
  const limit = Math.min(Number(searchParams.get('limit') || 500), 2000)

  try {
    if (view === 'overview') {
      const res = await query(`
        WITH rows_agg AS (
          SELECT
            symbol,
            COUNT(*) AS row_count,
            COUNT(DISTINCT trading_date) AS date_count,
            MIN(trading_date) AS date_min,
            MAX(trading_date) AS date_max,
            MAX(updated_at) AS last_updated,
            array_agg(DISTINCT column_name ORDER BY column_name) AS column_names
          FROM arbs_computed_timeseries_rows_v1
          GROUP BY symbol
        ),
        blocks_agg AS (
          SELECT
            symbol,
            COUNT(*) AS block_count,
            SUM(row_count) AS block_total_rows,
            MIN(trading_date) AS block_date_min,
            MAX(trading_date) AS block_date_max,
            MAX(created_at) AS block_last_created
          FROM arbs_computed_timeseries_blocks_v1
          GROUP BY symbol
        ),
        all_symbols AS (
          SELECT symbol FROM rows_agg
          UNION
          SELECT symbol FROM blocks_agg
        )
        SELECT
          a.symbol,
          COALESCE(r.row_count, 0)::int AS row_count,
          COALESCE(r.date_count, 0)::int AS date_count,
          COALESCE(r.date_min, b.block_date_min)::text AS date_min,
          COALESCE(r.date_max, b.block_date_max)::text AS date_max,
          COALESCE(r.last_updated, b.block_last_created)::text AS last_updated,
          COALESCE(r.column_names, '{}') AS column_names,
          COALESCE(b.block_count, 0)::int AS block_count,
          COALESCE(b.block_total_rows, 0)::int AS block_total_rows
        FROM all_symbols a
        LEFT JOIN rows_agg r USING (symbol)
        LEFT JOIN blocks_agg b USING (symbol)
        ORDER BY a.symbol
      `)
      return NextResponse.json({ view: 'overview', rows: res.rows })
    }

    if (view === 'rows') {
      const conditions: string[] = []
      const params: any[] = []
      if (symbol) {
        params.push(symbol)
        conditions.push(`symbol = $${params.length}`)
      }
      const whereClause = conditions.length ? 'WHERE ' + conditions.join(' AND ') : ''
      const res = await query(`
        SELECT
          symbol,
          trading_date::text AS trading_date,
          column_name,
          value,
          updated_at::text AS updated_at
        FROM arbs_computed_timeseries_rows_v1
        ${whereClause}
        ORDER BY trading_date DESC
        LIMIT $${params.length + 1}
      `, [...params, limit])
      return NextResponse.json({ view: 'rows', rows: res.rows })
    }

    if (view === 'blocks') {
      const conditions: string[] = []
      const params: any[] = []
      if (symbol) {
        params.push(symbol)
        conditions.push(`symbol = $${params.length}`)
      }
      const whereClause = conditions.length ? 'WHERE ' + conditions.join(' AND ') : ''
      const res = await query(`
        SELECT
          symbol,
          trading_date::text AS trading_date,
          row_count,
          data_format,
          sha256,
          created_at::text AS created_at
        FROM arbs_computed_timeseries_blocks_v1
        ${whereClause}
        ORDER BY trading_date DESC, symbol
        LIMIT $${params.length + 1}
      `, [...params, limit])
      return NextResponse.json({ view: 'blocks', rows: res.rows })
    }

    return NextResponse.json({ error: `Unknown view: ${view}` }, { status: 400 })
  } catch (error: any) {
    console.error('timeseries-explorer GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to query timeseries data' },
      { status: 500 }
    )
  }
}
