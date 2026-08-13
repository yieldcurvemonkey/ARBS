// ABOUTME: Every tenor bucket, z-scored. The one cross-bucket-safe view.
//
// z = (r_b*L - r_b*mu) / (r_b*sigma) = (L - mu) / sigma, so a constant
// retention factor cancels EXACTLY. That is the whole reason this endpoint may
// return all ten buckets at once while /direction/bucket may not.
//
// It returns no level column, and assertNoLevelKeys re-checks the payload
// before it goes out rather than trusting the SELECT list.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import {
  assertNoLevelKeys,
  BadRequest,
  BUCKET_SPACE,
  parseCommon,
  standardisedSql,
  TENOR_BUCKETS,
} from '../route.logic'

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    const { venueClass, series, from, to, lastSessions } = parseCommon(sp)
    const res = await analyticsQuery(standardisedSql(), [
      BUCKET_SPACE, venueClass, series, from, to, lastSessions,
    ])
    const rows = res.rows as Record<string, unknown>[]
    assertNoLevelKeys(rows)
    // Whether the window BOUND the result, so a consumer can never mistake a
    // truncated history for a short one. Exact rather than inferred from the
    // row count: sessions, which is what lastSessions counts.
    const nSessions = new Set(rows.map((r) => String(r.visibility_date))).size
    return NextResponse.json(
      {
        buckets: TENOR_BUCKETS, venueClass, series, from, to,
        lastSessions, sessions: nSessions, truncated: nSessions >= lastSessions,
        rows,
      },
      { headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' } },
    )
  } catch (error: unknown) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 })
    }
    const message = error instanceof Error ? error.message : 'failed'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
