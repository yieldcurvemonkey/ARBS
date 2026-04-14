// ABOUTME: GET /api/usd-swaps-tape-v2 — lifecycle-complete cursor-paginated tape.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { resolveDisplayView } from '@/lib/usd-swaps-tape-v2'
import type { UsdSwapTapeRow } from '@/features/usd-swaps-tape-v2/types'
import { buildTapeQuery, parseParams } from './route.logic'

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
    const nextCursor = hasMore ? String(rows[rows.length - 1]?.execution_start ?? '') : null
    const latestExecutionStart = rows.length
      ? String(rows[0]?.execution_start ?? '')
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
