import { NextResponse } from 'next/server'
import { ALL_LISTED_VOL_PRODUCTS, LISTED_VOL_RANGE_OPTIONS, ROLLING_EXPIRIES } from '@/features/listed-vol/constants'
import type { ListedVolExpiry, ListedVolProduct, ListedVolRange } from '@/features/listed-vol/types'
import { fetchListedVolTimeseriesData } from '@/lib/listed-vol/data'

export const runtime = 'nodejs'

function parseBoolean(value: string | null, fallback = false) {
  if (value === null) return fallback
  return value === 'true' || value === '1'
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ product: string; expiry: string }> }
) {
  const resolvedParams = await params
  const product = resolvedParams.product.toUpperCase() as ListedVolProduct
  const expiry = resolvedParams.expiry.toUpperCase() as ListedVolExpiry
  if (!ALL_LISTED_VOL_PRODUCTS.includes(product)) {
    return NextResponse.json({ error: 'Invalid product' }, { status: 400 })
  }
  if (!ROLLING_EXPIRIES.includes(expiry)) {
    return NextResponse.json({ error: 'Invalid expiry' }, { status: 400 })
  }

  const { searchParams } = new URL(request.url)
  const rangeParam = (searchParams.get('range')?.toUpperCase() ?? '3M') as ListedVolRange
  const range = LISTED_VOL_RANGE_OPTIONS.includes(rangeParam) ? rangeParam : '3M'

  try {
    const payload = await fetchListedVolTimeseriesData({
      requestedDate: searchParams.get('date'),
      product,
      expiryLabel: expiry,
      range,
      includeSwaption: parseBoolean(searchParams.get('include_swaption')),
      includeRealized: parseBoolean(searchParams.get('include_realized'))
    })
    return NextResponse.json(payload)
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message || 'Failed to load listed vol timeseries' },
      { status: 500 }
    )
  }
}
