import { NextResponse } from 'next/server'

import { fetchTimeseriesCollection } from '@/lib/ustf-vol/data'
import type { SeriesConfig, TimeRange } from '@/features/ustf-vol/types'

export const dynamic = 'force-dynamic'

export async function POST(request: Request) {
  try {
    const body = await request.json()
    const series = (Array.isArray(body?.series) ? body.series : []) as SeriesConfig[]
    const range = (body?.range ?? '6M') as TimeRange
    const startDate =
      typeof body?.startDate === 'string' && body.startDate.trim() ? body.startDate.trim() : undefined
    const endDate =
      typeof body?.endDate === 'string' && body.endDate.trim() ? body.endDate.trim() : undefined

    const data = await fetchTimeseriesCollection({
      series,
      range,
      startDate,
      endDate,
    })

    return NextResponse.json(data)
  } catch (error: any) {
    console.error('ustf-vol/timeseries-multi error:', error)
    return NextResponse.json(
      { error: error?.message ?? 'Internal error' },
      { status: 500 }
    )
  }
}
