// ABOUTME: Manage a single manual SOFR swap link (detail, update, deactivate).
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  applyManualLinkToTrades,
  buildValidationItems,
  checkManualLinkTables,
  clearManualLinkFromTrades,
  computeLinkMetrics,
  findManualLinkConflicts,
  LEGS_TABLE,
  MANUAL_LINK_HISTORY_TABLE,
  MANUAL_LINKS_TABLE,
  normalizeIdList,
  resolveLinkLegs
} from '@/lib/manual-sofr-swap-links'

type ManualLinkPatchPayload = {
  comment?: unknown
  link_reason?: unknown
  package_type?: unknown
  tags?: unknown
  add_trades?: unknown
  remove_trades?: unknown
  user?: unknown
}

type ManualLinkDeletePayload = {
  reason?: unknown
  user?: unknown
}

async function ensureManualLinkTables() {
  try {
    const availability = await checkManualLinkTables()
    if (
      !availability.linksTable ||
      !availability.historyTable ||
      !availability.legsTable ||
      !availability.packagesTable
    ) {
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
    console.error('sofr-swap manual links availability error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to verify manual link tables' },
      { status: 500 }
    )
  }
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function normalizeTags(value: unknown): string[] | null {
  if (value === undefined) return null
  if (Array.isArray(value)) {
    const tags = value
      .map((entry) => String(entry).trim())
      .filter(Boolean)
    return tags.length ? tags : []
  }
  if (typeof value === 'string') {
    const tags = value
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
    return tags.length ? tags : []
  }
  return []
}

export async function GET(
  request: Request,
  context: { params: Promise<{ linkId: string }> }
) {
  const { linkId } = await context.params
  const availability = await ensureManualLinkTables()
  if (availability) return availability
  try {
    const linkResult = await query(
      `SELECT *
       FROM ${MANUAL_LINKS_TABLE}
       WHERE link_id = $1`,
      [linkId]
    )
    if (!linkResult.rows.length) {
      return NextResponse.json({ error: 'Manual link not found.' }, { status: 404 })
    }

    const link = linkResult.rows[0]
    const tradeIds: string[] = Array.isArray(link.linked_trade_ids)
      ? link.linked_trade_ids
      : []

    const tradesResult = tradeIds.length
      ? await query(
          `SELECT trade_id,
                  package_id,
                  trade_label,
                  product_type,
                  notional,
                  risk,
                  fixed_rate,
                  execution_timestamp,
                  platform_identifier
           FROM ${LEGS_TABLE}
           WHERE trade_id = ANY($1)
           ORDER BY execution_timestamp DESC`,
          [tradeIds]
        )
      : { rows: [] }

    const historyResult = await query(
      `SELECT history_id,
              action,
              changed_by,
              changed_at,
              change_details,
              previous_state
       FROM ${MANUAL_LINK_HISTORY_TABLE}
       WHERE link_id = $1
       ORDER BY changed_at DESC`,
      [linkId]
    )

    return NextResponse.json({
      link,
      trades: tradesResult.rows,
      history: historyResult.rows
    })
  } catch (error: any) {
    console.error('sofr-swap manual link GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch manual link' },
      { status: 500 }
    )
  }
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ linkId: string }> }
) {
  const { linkId } = await context.params
  const availability = await ensureManualLinkTables()
  if (availability) return availability

  let payload: ManualLinkPatchPayload
  try {
    payload = (await request.json()) as ManualLinkPatchPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to update manual links.' },
      { status: 400 }
    )
  }

  try {
    const linkResult = await query(
      `SELECT *
       FROM ${MANUAL_LINKS_TABLE}
       WHERE link_id = $1`,
      [linkId]
    )
    if (!linkResult.rows.length) {
      return NextResponse.json({ error: 'Manual link not found.' }, { status: 404 })
    }

    const existing = linkResult.rows[0]
    const existingTradeIds: string[] = Array.isArray(existing.linked_trade_ids)
      ? existing.linked_trade_ids
      : []

    const addIdsRaw = normalizeIdList(payload.add_trades)
    const removeIdsRaw = normalizeIdList(payload.remove_trades)
    const addLegs = addIdsRaw.length ? await resolveLinkLegs(addIdsRaw) : []
    const removeLegs = removeIdsRaw.length ? await resolveLinkLegs(removeIdsRaw) : []

    const addTradeIds = new Set<string>([
      ...addIdsRaw,
      ...addLegs.map((leg) => leg.trade_id)
    ])
    const removeTradeIds = new Set<string>([
      ...removeIdsRaw,
      ...removeLegs.map((leg) => leg.trade_id)
    ])

    const nextTradeIdSet = new Set(existingTradeIds)
    addTradeIds.forEach((id) => nextTradeIdSet.add(id))
    removeTradeIds.forEach((id) => nextTradeIdSet.delete(id))
    const nextTradeIdsCandidate = Array.from(nextTradeIdSet)
    const nextLegs = await resolveLinkLegs(nextTradeIdsCandidate)
    const nextTradeIds = Array.from(new Set(nextLegs.map((leg) => leg.trade_id)))
    if (nextTradeIds.length < 2) {
      return NextResponse.json(
        { error: 'Manual links require at least two trades.' },
        { status: 400 }
      )
    }

    const metrics = computeLinkMetrics(nextLegs)
    const conflicts = await findManualLinkConflicts(nextTradeIds, linkId)
    const { items, hasErrors } = buildValidationItems(nextLegs, metrics, conflicts)

    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation: items, metrics },
        { status: 409 }
      )
    }

    const nextPackageType =
      payload.package_type === undefined
        ? existing.package_type
        : normalizeText(payload.package_type)
    const nextComment =
      payload.comment === undefined
        ? existing.user_comment
        : normalizeText(payload.comment)
    const nextReason =
      payload.link_reason === undefined
        ? existing.link_reason
        : normalizeText(payload.link_reason)
    const nextTags =
      payload.tags === undefined ? existing.tags : normalizeTags(payload.tags)

    const changeDetails: Record<string, unknown> = {}
    if (payload.package_type !== undefined) changeDetails.package_type = nextPackageType
    if (payload.comment !== undefined) changeDetails.user_comment = nextComment
    if (payload.link_reason !== undefined) changeDetails.link_reason = nextReason
    if (payload.tags !== undefined) changeDetails.tags = nextTags
    if (addTradeIds.size) changeDetails.add_trades = Array.from(addTradeIds)
    if (removeTradeIds.size) changeDetails.remove_trades = Array.from(removeTradeIds)

    const updateResult = await query(
      `UPDATE ${MANUAL_LINKS_TABLE}
       SET package_type = $1,
           user_comment = $2,
           link_reason = $3,
           tags = $4,
           linked_trade_ids = $5,
           link_metrics = $6,
           updated_by = $7,
           updated_at = NOW()
       WHERE link_id = $8
       RETURNING link_id, manual_package_id`,
      [
        nextPackageType,
        nextComment,
        nextReason,
        nextTags,
        nextTradeIds,
        metrics,
        user,
        linkId
      ]
    )

    await applyManualLinkToTrades(linkId, nextTradeIds)

    await query(
      `INSERT INTO ${MANUAL_LINK_HISTORY_TABLE} (
        link_id,
        action,
        changed_by,
        change_details,
        previous_state
      ) VALUES ($1, $2, $3, $4, $5)`,
      [linkId, 'UPDATED', user, changeDetails, existing]
    )

    return NextResponse.json({
      success: true,
      link_id: updateResult.rows[0]?.link_id,
      manual_package_id: updateResult.rows[0]?.manual_package_id,
      validation: items,
      metrics
    })
  } catch (error: any) {
    console.error('sofr-swap manual link PATCH error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update manual link' },
      { status: 500 }
    )
  }
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ linkId: string }> }
) {
  const { linkId } = await context.params
  const availability = await ensureManualLinkTables()
  if (availability) return availability

  let payload: ManualLinkDeletePayload
  try {
    payload = (await request.json()) as ManualLinkDeletePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  const user = normalizeText(payload.user)
  if (!user) {
    return NextResponse.json(
      { error: 'user is required to deactivate manual links.' },
      { status: 400 }
    )
  }

  try {
    const linkResult = await query(
      `SELECT *
       FROM ${MANUAL_LINKS_TABLE}
       WHERE link_id = $1`,
      [linkId]
    )
    if (!linkResult.rows.length) {
      return NextResponse.json({ error: 'Manual link not found.' }, { status: 404 })
    }

    const reason = normalizeText(payload.reason)
    await query(
      `UPDATE ${MANUAL_LINKS_TABLE}
       SET is_active = FALSE,
           updated_by = $1,
           updated_at = NOW()
       WHERE link_id = $2`,
      [user, linkId]
    )

    await clearManualLinkFromTrades(linkId)

    await query(
      `INSERT INTO ${MANUAL_LINK_HISTORY_TABLE} (
        link_id,
        action,
        changed_by,
        change_details,
        previous_state
      ) VALUES ($1, $2, $3, $4, $5)`,
      [linkId, 'DEACTIVATED', user, { reason }, linkResult.rows[0]]
    )

    return NextResponse.json({ success: true })
  } catch (error: any) {
    console.error('sofr-swap manual link DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to deactivate manual link' },
      { status: 500 }
    )
  }
}
