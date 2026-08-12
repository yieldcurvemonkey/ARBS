// ABOUTME: One tenor bucket's signed-DV01 series, against its own history.
// Serves levels, and therefore serves exactly one bucket — see route.logic.ts
// for why asking it for several is refused rather than answered.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import {
  BadRequest,
  BUCKET_SPACE,
  bucketSql,
  parseBucket,
  parseCommon,
  suffixLevels,
} from '../route.logic'

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    const bucket = parseBucket(sp)
    const { venueClass, series, from, to } = parseCommon(sp)
    const res = await analyticsQuery(bucketSql(), [
      BUCKET_SPACE, bucket, venueClass, series, from, to,
    ])
    return NextResponse.json(
      {
        bucket,
        venueClass,
        series,
        from,
        to,
        // The level keys go out bucket-suffixed, exactly as the Python module
        // names them, so two of these responses cannot be concatenated into a
        // cross-bucket level comparison.
        rows: suffixLevels(res.rows as Record<string, unknown>[], bucket),
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
