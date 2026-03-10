import { NextResponse } from 'next/server'
import { fetchListedVolGridData } from '@/lib/listed-vol/data'
import type { ListedVolProductClass } from '@/features/listed-vol/types'

export const runtime = 'nodejs'

function normalizeProductClass(value: string | null): ListedVolProductClass {
  if (value === 'UST' || value === 'STIR' || value === 'ALL') return value
  return 'ALL'
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  try {
    const payload = await fetchListedVolGridData({
      requestedDate: searchParams.get('date'),
      productClass: normalizeProductClass(searchParams.get('product_class'))
    })
    return NextResponse.json(payload)
  } catch (error: any) {
    return NextResponse.json(
      { error: error?.message || 'Failed to load listed vol grid' },
      { status: 500 }
    )
  }
}
