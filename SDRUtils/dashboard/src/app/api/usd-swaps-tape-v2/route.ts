// ABOUTME: GET /api/usd-swaps-tape-v2 — lifecycle-complete cursor-paginated tape.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView } from '@/lib/usd-swaps-tape-v2'
import type { UsdSwapTapeRow } from '@/features/usd-swaps-tape-v2/types'
import { buildTapeQuery, parseParams } from './route.logic'

function toIsoString(value: unknown): string | null {
  if (!value) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString()
  }
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toISOString()
}

export async function GET(req: Request) {
  const url = new URL(req.url)
  const parsed = parseParams(url.searchParams)
  if (!parsed.ok) {
    return NextResponse.json({ error: parsed.error }, { status: parsed.status ?? 400 })
  }

  try {
    const { view, columns } = await resolveDisplayView()
    const { sql, params } = buildTapeQuery(parsed.value, view, columns)
    const result = await query<UsdSwapTapeRow>(sql, params)
    const rows = result.rows.slice(0, parsed.value.limit)
    const hasMore = result.rows.length > parsed.value.limit
    // The pg driver hands back `timestamp with time zone` as a JS Date, so
    // naive `String(date)` yields the JS toString form
    // (e.g. "Thu Apr 09 2026 16:08:23 GMT-0400 (Eastern Daylight Time)"),
    // which Postgres then refuses to cast back to timestamptz when the
    // client echoes it as the `cursor` / `since` param. Normalise to ISO so
    // the round-trip works for both lazy-scroll pagination and polling.
    const nextCursor = hasMore ? toIsoString(rows[rows.length - 1]?.execution_start) : null
    const latestExecutionStart = rows.length
      ? toIsoString(rows[0]?.execution_start)
      : null
    return NextResponse.json({
      rows,
      nextCursor,
      hasMore,
      latestExecutionStart,
    })
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message ?? 'failed to load tape' },
      { status: 500 },
    )
  }
}
