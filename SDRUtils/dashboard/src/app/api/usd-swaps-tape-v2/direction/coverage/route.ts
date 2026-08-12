// ABOUTME: Which DV01 reached the ladder and which did not, by reason.
//
// Only ~58% of the tape's DV01 is oriented. The dominant exclusion is
// UNORIENTABLE_PKG at ~40% of DV01, and 64.2% of PKG-4+ DV01 is genuinely
// unidentifiable — several mutually inconsistent sign vectors reconcile the
// leg fees to the package price inside the same tolerance, so any answer would
// be a solver tie-break rather than economics. That is structural, not a
// backlog item, and this endpoint is what makes it visible.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import {
  BadRequest,
  coverageSql,
  parseCommon,
  TENOR_BUCKETS,
  type TenorBucket,
} from '../route.logic'

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    const { venueClass, series, from, to } = parseCommon(sp)
    const rawBucket = sp.get('bucket')
    if (rawBucket && !TENOR_BUCKETS.includes(rawBucket as TenorBucket)) {
      throw new BadRequest(`bucket must be one of ${TENOR_BUCKETS.join(', ')}`)
    }
    // byBucket is safe here in a way a level would not be: this endpoint
    // serves the SHARE excluded, which is precisely the quantity that differs
    // across buckets and that the reader has to see differing.
    const byBucket = sp.get('byBucket') === 'true'
    const res = await analyticsQuery(coverageSql(byBucket), [
      venueClass, series, from, to, rawBucket,
    ])
    return NextResponse.json(
      { venueClass, series, from, to, bucket: rawBucket, byBucket, rows: res.rows },
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
