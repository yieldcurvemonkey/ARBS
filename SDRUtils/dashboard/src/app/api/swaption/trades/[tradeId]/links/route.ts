// ABOUTME: Fetch manual link history for a specific trade id.
// ABOUTME: Returns all active and inactive manual links containing the trade.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  checkManualLinkTables,
  MANUAL_LINK_HISTORY_TABLE,
  MANUAL_LINKS_TABLE
} from '@/lib/manual-links'

async function ensureManualLinkTables() {
  try {
    const availability = await checkManualLinkTables()
    if (!availability.linksTable || !availability.historyTable) {
      const missing =
        availability.missingTables.length > 0
          ? availability.missingTables.join(', ')
          : `${MANUAL_LINKS_TABLE}, ${MANUAL_LINK_HISTORY_TABLE}`
      return NextResponse.json(
        {
          error: `Manual linking is not enabled. Missing table(s): ${missing}.`
        },
        { status: 503 }
      )
    }
    return null
  } catch (error: any) {
    console.error('manual links availability error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to verify manual link tables' },
      { status: 500 }
    )
  }
}

export async function GET(
  request: Request,
  context: { params: Promise<{ tradeId: string }> }
) {
  const { tradeId } = await context.params
  const availability = await ensureManualLinkTables()
  if (availability) return availability
  try {
    const result = await query(
      `SELECT *
       FROM ${MANUAL_LINKS_TABLE}
       WHERE linked_trade_ids @> ARRAY[$1]::text[]
       ORDER BY created_at DESC`,
      [tradeId]
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('trade links GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch trade link history' },
      { status: 500 }
    )
  }
}
