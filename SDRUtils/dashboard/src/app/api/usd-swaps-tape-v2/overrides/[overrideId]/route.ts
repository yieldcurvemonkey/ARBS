// ABOUTME: Detail / update / deactivate a single manual tape override.
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query, withClient } from '@/lib/db'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '@/lib/utils'
import {
  OVERRIDES_TABLE,
  OVERRIDE_MEMBERS_TABLE,
  OVERRIDE_HISTORY_TABLE,
  computeOverrideMetrics,
  insertMemberRows,
  normalizeIdList,
  normalizeTags,
  normalizeText,
  resolveOverrideLegs,
  supersedeOverlappingOverrides,
  validateOverride,
  type OverrideType,
} from '@/lib/tape-overrides'

type PatchPayload = {
  reason?: unknown
  tags?: unknown
  add_trades?: unknown
  remove_trades?: unknown
  user?: unknown
  admin_password?: unknown
}
type DeletePayload = { reason?: unknown; user?: unknown; admin_password?: unknown }

export async function GET(
  _request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  try {
    const parent = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!parent.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const members = await query(
      `SELECT trade_id, override_id, override_type, manual_package_id, is_active
       FROM ${OVERRIDE_MEMBERS_TABLE}
       WHERE override_id = $1
       ORDER BY trade_id`,
      [overrideId],
    )
    const history = await query(
      `SELECT history_id, action, changed_by, changed_at, change_details, previous_state
       FROM ${OVERRIDE_HISTORY_TABLE}
       WHERE override_id = $1
       ORDER BY changed_at DESC`,
      [overrideId],
    )
    return NextResponse.json({
      override: parent.rows[0],
      members: members.rows,
      history: history.rows,
    })
  } catch (error: any) {
    console.error('tape override GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch override' },
      { status: 500 },
    )
  }
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  let payload: PatchPayload
  try {
    payload = (await request.json()) as PatchPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidTapeWritePassword(payload.admin_password)) {
    return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
  }
  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to update an override.' },
      { status: 400 },
    )
  }

  try {
    const existingResult = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!existingResult.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const existing = existingResult.rows[0]
    const overrideType = existing.override_type as OverrideType
    const manualPackageId: string | null = existing.manual_package_id ?? null

    const existingTradeIds: string[] = Array.isArray(existing.trade_ids) ? existing.trade_ids : []
    const addIds = normalizeIdList(payload.add_trades)
    const removeIds = new Set(normalizeIdList(payload.remove_trades))
    const nextSet = new Set(existingTradeIds)
    addIds.forEach((id) => nextSet.add(id))
    removeIds.forEach((id) => nextSet.delete(id))
    const nextTradeIds = normalizeIdList(Array.from(nextSet))

    const { validation, hasErrors } = validateOverride(overrideType, nextTradeIds)
    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation },
        { status: 409 },
      )
    }

    const legs = await resolveOverrideLegs(nextTradeIds)
    const metrics = computeOverrideMetrics(overrideType, nextTradeIds, legs)

    const nextReason = payload.reason === undefined ? existing.reason : normalizeText(payload.reason)
    const nextTags = payload.tags === undefined ? existing.tags : normalizeTags(payload.tags)
    const changeDetails: Record<string, unknown> = {}
    if (payload.reason !== undefined) changeDetails.reason = nextReason
    if (payload.tags !== undefined) changeDetails.tags = nextTags
    if (addIds.length) changeDetails.add_trades = addIds
    if (removeIds.size) changeDetails.remove_trades = Array.from(removeIds)
    changeDetails.trade_ids = nextTradeIds

    await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        // Drop this override's current member rows so the partial-unique
        // (trade_id) WHERE is_active index does not collide on re-insert.
        await client.query(
          `UPDATE ${OVERRIDE_MEMBERS_TABLE} SET is_active = FALSE WHERE override_id = $1`,
          [overrideId],
        )
        // Any other active override now overlapping the new set is superseded.
        await supersedeOverlappingOverrides(client, nextTradeIds, overrideId, user)
        await client.query(
          `UPDATE ${OVERRIDES_TABLE}
           SET trade_ids = $1, reason = $2, tags = $3, metrics = $4,
               is_active = TRUE, updated_by = $5, updated_at = NOW()
           WHERE override_id = $6`,
          [nextTradeIds, nextReason, nextTags, metrics, user, overrideId],
        )
        await insertMemberRows(client, overrideId, overrideType, manualPackageId, nextTradeIds)
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details, previous_state)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)`,
          [overrideId, 'UPDATED', user, changeDetails, existing],
        )
        await client.query('COMMIT')
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({
      success: true,
      override_id: overrideId,
      manual_package_id: manualPackageId,
      validation,
      metrics,
    })
  } catch (error: any) {
    console.error('tape override PATCH error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update override' },
      { status: 500 },
    )
  }
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ overrideId: string }> },
) {
  const { overrideId } = await context.params
  let payload: DeletePayload
  try {
    payload = (await request.json()) as DeletePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }
  if (!isValidTapeWritePassword(payload.admin_password)) {
    return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
  }
  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to deactivate an override.' },
      { status: 400 },
    )
  }

  try {
    const existingResult = await query(
      `SELECT * FROM ${OVERRIDES_TABLE} WHERE override_id = $1`,
      [overrideId],
    )
    if (!existingResult.rows.length) {
      return NextResponse.json({ error: 'Override not found.' }, { status: 404 })
    }
    const existing = existingResult.rows[0]
    const reason = normalizeText(payload.reason)

    await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        await client.query(
          `UPDATE ${OVERRIDES_TABLE}
           SET is_active = FALSE, updated_by = $1, updated_at = NOW()
           WHERE override_id = $2`,
          [user, overrideId],
        )
        await client.query(
          `UPDATE ${OVERRIDE_MEMBERS_TABLE} SET is_active = FALSE WHERE override_id = $1`,
          [overrideId],
        )
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details, previous_state)
           VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)`,
          [overrideId, 'DEACTIVATED', user, { reason }, existing],
        )
        await client.query('COMMIT')
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('tape override DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to deactivate override' },
      { status: 500 },
    )
  }
}
