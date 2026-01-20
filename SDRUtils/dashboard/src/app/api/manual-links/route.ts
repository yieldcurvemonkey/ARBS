// API endpoints for manual trade linking
// Frontend-driven: backend just persists linkages

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const TABLE_NAME = 'arbs_swaption_manual_links_v1'

/**
 * GET /api/manual-links
 * Query params:
 *   - start: ISO timestamp (optional)
 *   - end: ISO timestamp (optional)
 *   - trade_ids: comma-separated trade IDs (optional)
 *   - is_active: true/false (default: true)
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const start = searchParams.get('start')
  const end = searchParams.get('end')
  const tradeIdsParam = searchParams.get('trade_ids')
  const isActive = searchParams.get('is_active') !== 'false' // Default true

  const conditions: string[] = []
  const params: unknown[] = []

  // Filter by active status
  if (isActive) {
    conditions.push('is_active = true')
  }

  // Filter by date range
  if (start) {
    params.push(start)
    conditions.push(`created_at >= $${params.length}`)
  }
  if (end) {
    params.push(end)
    conditions.push(`created_at <= $${params.length}`)
  }

  // Filter by trade IDs (find links containing any of these trades)
  if (tradeIdsParam) {
    const tradeIds = tradeIdsParam.split(',').map((id) => id.trim())
    params.push(tradeIds)
    conditions.push(`linked_trade_ids && $${params.length}::text[]`)
  }

  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query(
      `SELECT
        link_id,
        linked_trade_ids,
        created_by,
        created_at,
        updated_at,
        user_comment,
        tags,
        is_active
       FROM ${TABLE_NAME}
       ${whereClause}
       ORDER BY created_at DESC`,
      params
    )

    return NextResponse.json({
      links: result.rows,
      count: result.rows.length
    })
  } catch (error: any) {
    console.error('manual-links GET error:', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch manual links' },
      { status: 500 }
    )
  }
}

/**
 * POST /api/manual-links
 * Body: {
 *   trade_ids: string[],
 *   comment?: string,
 *   tags?: string[],
 *   user: string
 * }
 */
export async function POST(request: Request) {
  try {
    const body = await request.json()
    const { trade_ids, comment, tags, user } = body

    // Validation
    if (!trade_ids || !Array.isArray(trade_ids) || trade_ids.length < 2) {
      return NextResponse.json(
        { error: 'trade_ids must be an array with at least 2 elements' },
        { status: 400 }
      )
    }

    if (!user || typeof user !== 'string') {
      return NextResponse.json(
        { error: 'user (string) is required' },
        { status: 400 }
      )
    }

    // Check if any trade is already linked
    const checkResult = await query(
      `SELECT link_id, linked_trade_ids, created_by
       FROM ${TABLE_NAME}
       WHERE is_active = true
         AND linked_trade_ids && $1::text[]`,
      [trade_ids]
    )

    if (checkResult.rows.length > 0) {
      return NextResponse.json(
        {
          error: 'One or more trades are already in an active link',
          conflicting_links: checkResult.rows
        },
        { status: 409 }
      )
    }

    // Create link
    const result = await query(
      `INSERT INTO ${TABLE_NAME} (
        linked_trade_ids,
        created_by,
        user_comment,
        tags
      ) VALUES ($1, $2, $3, $4)
      RETURNING
        link_id,
        linked_trade_ids,
        created_by,
        created_at,
        updated_at,
        user_comment,
        tags,
        is_active`,
      [trade_ids, user, comment || null, JSON.stringify(tags || [])]
    )

    return NextResponse.json({
      link: result.rows[0],
      message: 'Link created successfully'
    }, { status: 201 })
  } catch (error: any) {
    console.error('manual-links POST error:', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create manual link' },
      { status: 500 }
    )
  }
}

/**
 * DELETE /api/manual-links?link_id=<uuid>
 * Soft delete (sets is_active = false)
 */
export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url)
  const linkId = searchParams.get('link_id')

  if (!linkId) {
    return NextResponse.json(
      { error: 'link_id query parameter is required' },
      { status: 400 }
    )
  }

  try {
    const result = await query(
      `UPDATE ${TABLE_NAME}
       SET is_active = false,
           updated_at = NOW()
       WHERE link_id = $1
       RETURNING link_id`,
      [linkId]
    )

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: 'Link not found' },
        { status: 404 }
      )
    }

    return NextResponse.json({
      link_id: result.rows[0].link_id,
      message: 'Link deleted successfully'
    })
  } catch (error: any) {
    console.error('manual-links DELETE error:', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to delete manual link' },
      { status: 500 }
    )
  }
}
