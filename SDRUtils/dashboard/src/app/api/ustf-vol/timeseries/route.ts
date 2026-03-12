import { NextResponse } from 'next/server'

import { fetchTimeseries } from '@/lib/ustf-vol/data'
import type { AssetType, TimeRange, TimeseriesMode } from '@/features/ustf-vol/types'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)

    const series1Type = (searchParams.get('series1_type') ?? 'ustf') as AssetType
    const series1Product = searchParams.get('series1_product') ?? undefined
    const series1Expiry = searchParams.get('series1_expiry') ?? '1M'
    const series1Tail = searchParams.get('series1_tail') ?? undefined

    const series2Type = searchParams.get('series2_type') as AssetType | undefined
    const series2Product = searchParams.get('series2_product') ?? undefined
    const series2Expiry = searchParams.get('series2_expiry') ?? undefined
    const series2Tail = searchParams.get('series2_tail') ?? undefined

    const mode = (searchParams.get('mode') ?? 'overlay') as TimeseriesMode
    const range = (searchParams.get('range') ?? '6M') as TimeRange

    const data = await fetchTimeseries({
      series1Type,
      series1Product,
      series1Expiry,
      series1Tail,
      series2Type: series2Type || undefined,
      series2Product,
      series2Expiry: series2Expiry || undefined,
      series2Tail,
      mode,
      range,
    })

    return NextResponse.json(data)
  } catch (error: any) {
    console.error('ustf-vol/timeseries error:', error)
    return NextResponse.json({ error: error?.message ?? 'Internal error' }, { status: 500 })
  }
}
