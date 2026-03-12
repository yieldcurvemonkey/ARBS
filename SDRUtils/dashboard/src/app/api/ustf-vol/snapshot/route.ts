import { NextResponse } from 'next/server'

import { fetchComparisonSnapshot } from '@/lib/ustf-vol/data'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const data = await fetchComparisonSnapshot()
    return NextResponse.json(data)
  } catch (error: any) {
    console.error('ustf-vol/snapshot error:', error)
    return NextResponse.json(
      { error: error?.message ?? 'Internal error' },
      { status: 500 }
    )
  }
}
