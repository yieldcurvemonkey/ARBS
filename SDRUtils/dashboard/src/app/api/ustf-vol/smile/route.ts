import { NextResponse } from 'next/server'

import { fetchSmile } from '@/lib/ustf-vol/data'
import type { AssetType, SmileXAxis } from '@/features/ustf-vol/types'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)

    const assetType = (searchParams.get('asset_type') ?? 'ustf') as AssetType
    const product = searchParams.get('product') ?? undefined
    const expiry = searchParams.get('expiry') ?? '1M'
    const tail = searchParams.get('tail') ?? undefined
    const datesParam = searchParams.get('dates') ?? ''
    const xAxis = (searchParams.get('x_axis') ?? 'strike_offset_bps') as SmileXAxis
    const numPoints = Number(searchParams.get('num_points') ?? '21') || 21

    const dates = datesParam
      .split(',')
      .map((d) => d.trim())
      .filter(Boolean)

    if (dates.length === 0) {
      return NextResponse.json({ error: 'dates parameter is required' }, { status: 400 })
    }

    if (assetType === 'ustf' && !product) {
      return NextResponse.json({ error: 'product is required for ustf' }, { status: 400 })
    }
    if (assetType === 'swaption' && !tail) {
      return NextResponse.json({ error: 'tail is required for swaption' }, { status: 400 })
    }

    const data = await fetchSmile({
      assetType,
      product,
      expiry,
      tail,
      dates,
      xAxis,
      numPoints,
    })

    return NextResponse.json(data)
  } catch (error: any) {
    console.error('ustf-vol/smile error:', error)
    return NextResponse.json({ error: error?.message ?? 'Internal error' }, { status: 500 })
  }
}
