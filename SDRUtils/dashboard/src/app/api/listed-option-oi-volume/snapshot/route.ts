import { NextResponse } from 'next/server'

import { parseSnapshotRouteParams } from '@/app/api/listed-option-oi-volume/route-logic'
import { fetchListedOptionSnapshot } from '@/lib/listed-option-oi-volume/data'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const url = new URL(request.url)
    const parsed = parseSnapshotRouteParams(url.searchParams)
    if (!parsed.ok) {
      return NextResponse.json({ error: parsed.error }, { status: 400 })
    }

    const data = await fetchListedOptionSnapshot(parsed.value)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('listed-option-oi-volume/snapshot error:', error)
    return NextResponse.json(
      { error: error?.message ?? 'Internal error' },
      { status: 500 }
    )
  }
}
