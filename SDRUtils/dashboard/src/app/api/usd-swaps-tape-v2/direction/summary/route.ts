// ABOUTME: Headline numbers for the panel header — window, coverage, vintage.
// Cheap, and it is what tells the reader up front that the ladder is built on
// a fraction of the tape rather than on all of it.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import { BadRequest, parseCommon, summarySql } from '../route.logic'

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    const { venueClass, series } = parseCommon(sp)
    const res = await analyticsQuery(summarySql(), [venueClass, series])
    return NextResponse.json(
      { venueClass, series, summary: res.rows[0] ?? null },
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
