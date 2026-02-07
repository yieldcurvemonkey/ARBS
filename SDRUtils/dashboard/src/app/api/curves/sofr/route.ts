// ABOUTME: Exposes SOFR discount curve via IRSwapsMDP for premium grid pricing.
import { NextResponse } from 'next/server'
import { getSofrCurve } from '@/lib/vol-grid/sofrCurve'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const source = searchParams.get('source') || undefined
  const curveName = searchParams.get('curve_name') || undefined
  const timestamp = searchParams.get('timestamp') || undefined

  try {
    const curve = await getSofrCurve({
      source,
      curveName,
      timestamp
    })
    return NextResponse.json(curve)
  } catch (error: any) {
    console.error('sofr curve GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch SOFR curve' },
      { status: 500 }
    )
  }
}
