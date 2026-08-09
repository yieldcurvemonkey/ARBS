import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { TAPE_SIGNAL } from '@/lib/tape-tables'

export const dynamic = 'force-dynamic'

export async function GET() {
  try {
    const result = await query<{
      updated_at: string
      packages_written: number
      legs_written: number
    }>(
      `SELECT updated_at, packages_written, legs_written FROM ${TAPE_SIGNAL} WHERE id = 1`,
      [],
    )
    const row = result.rows[0]
    if (!row) {
      return NextResponse.json({ updated_at: null })
    }
    return NextResponse.json(row, {
      headers: { 'Cache-Control': 'no-cache, no-store' },
    })
  } catch {
    return NextResponse.json({ updated_at: null })
  }
}
