// API endpoint for updating a specific manual link

import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const TABLE_NAME = 'arbs_swaption_manual_links_v1'

/**
 * PATCH /api/manual-links/[link_id]
 * Body: {
 *   comment?: string,
 *   tags?: string[]
 * }
 */
export async function PATCH(
  request: Request,
  { params }: { params: { link_id: string } }
) {
  try {
    const linkId = params.link_id
    const body = await request.json()
    const { comment, tags } = body

    // Build dynamic update query
    const updates: string[] = []
    const values: unknown[] = []

    if (comment !== undefined) {
      values.push(comment)
      updates.push(`user_comment = $${values.length}`)
    }

    if (tags !== undefined) {
      values.push(JSON.stringify(tags))
      updates.push(`tags = $${values.length}`)
    }

    if (updates.length === 0) {
      return NextResponse.json(
        { error: 'No fields to update' },
        { status: 400 }
      )
    }

    // Always update timestamp
    updates.push('updated_at = NOW()')

    // Add link_id as final parameter
    values.push(linkId)
    const linkIdParam = values.length

    const result = await query(
      `UPDATE ${TABLE_NAME}
       SET ${updates.join(', ')}
       WHERE link_id = $${linkIdParam}
       RETURNING
         link_id,
         linked_trade_ids,
         created_by,
         created_at,
         updated_at,
         user_comment,
         tags,
         is_active`,
      values
    )

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: 'Link not found' },
        { status: 404 }
      )
    }

    return NextResponse.json({
      link: result.rows[0],
      message: 'Link updated successfully'
    })
  } catch (error: any) {
    console.error('manual-links PATCH error:', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update manual link' },
      { status: 500 }
    )
  }
}
