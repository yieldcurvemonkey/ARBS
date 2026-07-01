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
  // If the raw string can't be parsed as a date, return null instead of
  // echoing the bad value back as `nextCursor`. Echoing would break the
  // next pagination request with a Postgres cast error and silently
  // halt the trader's lazy-scroll.
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
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
    // pg returns NUMERIC as strings; the PTP/OPA columns are consumed as
    // numbers (client-side sort on dealer_spread_bps sorts lexicographically
    // otherwise). Coerce here so the runtime matches UsdSwapTapeRow.
    for (const r of rows as Array<Record<string, unknown>>) {
      for (const k of [
        'ptp_group_size',
        'opa_signed_net',
        'opa_ptp_residual',
        'dealer_spread_est',
        'dealer_spread_bps',
      ]) {
        if (r[k] != null) {
          const n = Number(r[k])
          r[k] = Number.isFinite(n) ? n : null
        }
      }
    }
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
    // Pagination cache: tape data is append-mostly + polled every 30s
    // by the client. A 15s shared cache lets multiple browser tabs (and
    // an upstream CDN if one ever sits in front) reuse the same page
    // payload while still surfacing fresh prints within the polling
    // cadence. Skip the cache header when the response varies per
    // trader: cursor pages, incremental polls, and column-filtered
    // requests all skip the cache so the unfiltered initial fetch is
    // the only path that benefits from the shared cache. (The cursor
    // tail and incremental polls always hit the DB; column filters are
    // usually trader-specific and short-lived, and would otherwise
    // multiply CDN cache entries without meaningful reuse.)
    const headers: Record<string, string> = {}
    const hasColumnFilters =
      parsed.value.columnFilters &&
      Object.keys(parsed.value.columnFilters).length > 0
    const skipCache =
      !!parsed.value.cursor || !!parsed.value.since || !!hasColumnFilters
    if (!skipCache) {
      headers['Cache-Control'] = 'public, s-maxage=5, stale-while-revalidate=10'
    }
    return NextResponse.json(
      { rows, nextCursor, hasMore, latestExecutionStart },
      { headers },
    )
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message ?? 'failed to load tape' },
      { status: 500 },
    )
  }
}
