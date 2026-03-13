import { NextResponse } from 'next/server'

import { parseTimeseriesRouteParams } from '@/app/api/listed-option-oi-volume/route-logic'
import { fetchListedOptionTimeseriesCollection } from '@/lib/listed-option-oi-volume/data'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const parsed = parseTimeseriesRouteParams(body)
    if (!parsed.ok) {
      return NextResponse.json({ error: parsed.error }, { status: 400 })
    }

    const data = await fetchListedOptionTimeseriesCollection(parsed.value)
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('listed-option-oi-volume/timeseries-multi error:', error)
    return NextResponse.json(
      { error: error?.message ?? 'Internal error' },
      { status: 500 }
    )
  }
}
