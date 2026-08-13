// ABOUTME: What meeting-dated STIR instruments traded on a day, busiest first.
// Feeds the picker on the STIR flow panel — you cannot ask for a chart of one
// instrument until you know which ones exist.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import { BadRequest } from '../../route.logic'
import {
  latestStirDateSql,
  MAX_INSTRUMENTS,
  MIN_INSTRUMENT_TRADES,
  type StirInstrument,
  stirInstrumentsSql,
} from '../../stir-flow.logic'

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    const rawDate = sp.get('date')
    if (rawDate && !/^\d{4}-\d{2}-\d{2}$/.test(rawDate)) {
      throw new BadRequest('date must be YYYY-MM-DD')
    }

    let date = rawDate
    if (!date) {
      const latest = await analyticsQuery(latestStirDateSql(), [])
      date = (latest.rows[0]?.as_of_date as string | null) ?? null
      if (date == null) throw new Error('no classified STIR flow is published yet')
    }

    const q = stirInstrumentsSql()
    const res = await analyticsQuery(q.text, [date, MIN_INSTRUMENT_TRADES, MAX_INSTRUMENTS])
    const rows = res.rows as StirInstrument[]

    return NextResponse.json(
      {
        date,
        minTrades: MIN_INSTRUMENT_TRADES,
        limit: MAX_INSTRUMENTS,
        // Whether the list was cut. 14,367 instruments exist across the table
        // and the long tail is one-print date pairs, so "these are the busiest
        // 60" and "these are all of them" are different facts.
        truncated: rows.length >= MAX_INSTRUMENTS,
        rows,
      },
      { headers: { 'Cache-Control': 'private, max-age=300, stale-while-revalidate=600' } },
    )
  } catch (error: unknown) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 })
    }
    const message = error instanceof Error ? error.message : 'failed'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
