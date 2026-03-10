import { NextResponse } from 'next/server'
import { fetchListedVolComparisonData } from '@/lib/listed-vol/data'
import type { ListedVolProduct } from '@/features/listed-vol/types'
import { ALL_LISTED_VOL_PRODUCTS } from '@/features/listed-vol/constants'

export const runtime = 'nodejs'

function normalizeProduct(value: string | null): ListedVolProduct | null {
  if (!value) return null
  const token = value.toUpperCase() as ListedVolProduct
  return ALL_LISTED_VOL_PRODUCTS.includes(token) ? token : null
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const product = normalizeProduct(searchParams.get('product'))
  if (!product) {
    return NextResponse.json({ error: 'Invalid product' }, { status: 400 })
  }

  try {
    const payload = await fetchListedVolComparisonData({
      requestedDate: searchParams.get('date'),
      product
    })
    return NextResponse.json(payload)
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message || 'Failed to load listed vs swaption comparison' },
      { status: 500 }
    )
  }
}
