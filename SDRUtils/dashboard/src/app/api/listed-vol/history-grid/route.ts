import { NextResponse } from 'next/server'
import { fetchListedVolHistoryGridData } from '@/lib/listed-vol/data'
import type { ListedVolProductClass } from '@/features/listed-vol/types'

export const runtime = 'nodejs'

function normalizeProductClass(value: string | null): ListedVolProductClass {
  if (value === 'UST' || value === 'STIR' || value === 'ALL') return value
  return 'ALL'
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const lookbackRaw = Number(searchParams.get('lookback') ?? 20)
  const lookback = Number.isFinite(lookbackRaw) && lookbackRaw > 0 ? Math.round(lookbackRaw) : 20
  try {
    const payload = await fetchListedVolHistoryGridData({
      requestedDate: searchParams.get('date'),
      productClass: normalizeProductClass(searchParams.get('product_class')),
      lookback
    })
    return NextResponse.json(payload)
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message || 'Failed to load listed vol history grid' },
      { status: 500 }
    )
  }
}
