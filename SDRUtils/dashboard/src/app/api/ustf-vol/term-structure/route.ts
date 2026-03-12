import { NextResponse } from 'next/server'

import { fetchTermStructure } from '@/lib/ustf-vol/data'
import type { AssetType } from '@/features/ustf-vol/types'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)

    const assetType = (searchParams.get('asset_type') ?? 'swaption') as AssetType
    const expiry = searchParams.get('expiry') ?? '1M'
    const datesParam = searchParams.get('dates') ?? ''
    const strikeOffsetBps = Number(searchParams.get('strike_offset_bps') ?? '0') || 0

    const dates = datesParam
      .split(',')
      .map((d) => d.trim())
      .filter(Boolean)

    if (dates.length === 0) {
      return NextResponse.json({ error: 'dates parameter is required' }, { status: 400 })
    }

    const data = await fetchTermStructure({
      assetType,
      expiry,
      dates,
      strikeOffsetBps,
    })

    return NextResponse.json(data)
  } catch (error: any) {
    console.error('ustf-vol/term-structure error:', error)
    return NextResponse.json({ error: error?.message ?? 'Internal error' }, { status: 500 })
  }
}
