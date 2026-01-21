// ABOUTME: CRUD entry point for manual swaption link records.
// ABOUTME: Supports creation, validation, and search for manual links.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  buildValidationItems,
  checkManualLinkTables,
  computeLinkMetrics,
  findManualLinkConflicts,
  generateManualPackageId,
  MANUAL_LINK_HISTORY_TABLE,
  MANUAL_LINKS_TABLE,
  normalizeIdList,
  resolveLinkLegs
} from '@/lib/manual-links'

type ManualLinkPayload = {
  trade_ids?: unknown
  package_type?: unknown
  comment?: unknown
  link_reason?: unknown
  tags?: unknown
  user?: unknown
  validate_only?: unknown
}

const DEFAULT_LIST_LIMIT = 200
const MAX_LIST_LIMIT = 1000

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

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function normalizeTags(value: unknown): string[] | null {
  if (!value) return null
  if (Array.isArray(value)) {
    const tags = value
      .map((entry) => String(entry).trim())
      .filter(Boolean)
    return tags.length ? tags : null
  }
  if (typeof value === 'string') {
    const tags = value
      .split(',')
      .map((entry) => entry.trim())
      .filter(Boolean)
    return tags.length ? tags : null
  }
  return null
}

function parseBoolean(value: string | null): boolean | null {
  if (!value) return null
  const normalized = value.trim().toLowerCase()
  if (['true', '1', 'yes', 'y'].includes(normalized)) return true
  if (['false', '0', 'no', 'n'].includes(normalized)) return false
  return null
}

function parseLimit(value: string | null): number {
  if (!value) return DEFAULT_LIST_LIMIT
  const parsed = Number(value)
  if (Number.isNaN(parsed) || parsed < 1) return DEFAULT_LIST_LIMIT
  return Math.min(parsed, MAX_LIST_LIMIT)
}

export async function GET(request: Request) {
  const availability = await ensureManualLinkTables()
  if (availability) return availability

  const { searchParams } = new URL(request.url)
  const startDate = searchParams.get('start_date')
  const endDate = searchParams.get('end_date')
  const createdBy = searchParams.get('created_by')
  const tagsParam = searchParams.get('tags')
  const isActiveParam = searchParams.get('is_active')
  const limit = parseLimit(searchParams.get('limit'))

  const params: unknown[] = []
  const conditions: string[] = []

  if (startDate) {
    params.push(startDate)
    conditions.push(`created_at >= $${params.length}`)
  }
  if (endDate) {
    params.push(endDate)
    conditions.push(`created_at <= $${params.length}`)
  }
  if (createdBy) {
    params.push(`%${createdBy}%`)
    conditions.push(`created_by ILIKE $${params.length}`)
  }
  if (tagsParam) {
    const tags = normalizeTags(tagsParam)
    if (tags?.length) {
      params.push(tags)
      conditions.push(`tags && $${params.length}`)
    }
  }
  const isActive = parseBoolean(isActiveParam)
  if (isActive !== null) {
    params.push(isActive)
    conditions.push(`is_active = $${params.length}`)
  }

  params.push(limit)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query(
      `SELECT *
       FROM ${MANUAL_LINKS_TABLE}
       ${whereClause}
       ORDER BY created_at DESC
       LIMIT $${params.length}`,
      params
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('manual links GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch manual links' },
      { status: 500 }
    )
  }
}

export async function POST(request: Request) {
  let payload: ManualLinkPayload
  try {
    payload = (await request.json()) as ManualLinkPayload
  } catch (error: any) {
    return NextResponse.json(
      { error: 'Invalid JSON payload' },
      { status: 400 }
    )
  }

  const inputIds = normalizeIdList(payload.trade_ids)
  if (!inputIds.length) {
    return NextResponse.json(
      { error: 'trade_ids must include at least two items.' },
      { status: 400 }
    )
  }

  const availability = await ensureManualLinkTables()
  if (availability) return availability

  try {
    const legs = await resolveLinkLegs(inputIds)
    const metrics = computeLinkMetrics(legs)
    const linkedTradeIds = Array.from(
      new Set(legs.map((leg) => leg.trade_id))
    )
    const conflicts = await findManualLinkConflicts(linkedTradeIds)
    const { items, hasErrors } = buildValidationItems(
      legs,
      metrics,
      conflicts
    )

    const validateOnly =
      payload.validate_only === true ||
      String(payload.validate_only).toLowerCase() === 'true'

    if (validateOnly) {
      return NextResponse.json({
        validation: items,
        metrics
      })
    }

    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation: items, metrics },
        { status: 409 }
      )
    }

    const user = normalizeText(payload.user)
    if (!user) {
      return NextResponse.json(
        { error: 'user is required to create a manual link.' },
        { status: 400 }
      )
    }

    if (linkedTradeIds.length < 2) {
      return NextResponse.json(
        { error: 'Manual links require at least two trades.' },
        { status: 400 }
      )
    }

    const packageType = normalizeText(payload.package_type)
    const comment = normalizeText(payload.comment)
    const linkReason = normalizeText(payload.link_reason)
    const tags = normalizeTags(payload.tags)

    let linkResult: { link_id: string; manual_package_id: string } | null = null
    let attempts = 0
    while (!linkResult && attempts < 3) {
      attempts += 1
      const manualPackageId = await generateManualPackageId()
      try {
        const insertResult = await query(
          `INSERT INTO ${MANUAL_LINKS_TABLE} (
            manual_package_id,
            package_type,
            linked_trade_ids,
            created_by,
            user_comment,
            link_reason,
            tags,
            link_metrics
          ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
          RETURNING link_id, manual_package_id`,
          [
            manualPackageId,
            packageType,
            linkedTradeIds,
            user,
            comment,
            linkReason,
            tags,
            metrics
          ]
        )
        linkResult = insertResult.rows[0]
      } catch (error: any) {
        if (error?.code === '23505') {
          continue
        }
        throw error
      }
    }

    if (!linkResult) {
      return NextResponse.json(
        { error: 'Failed to allocate manual package id.' },
        { status: 500 }
      )
    }

    await query(
      `INSERT INTO ${MANUAL_LINK_HISTORY_TABLE} (
        link_id,
        action,
        changed_by,
        change_details,
        previous_state
      ) VALUES ($1, $2, $3, $4, $5)`,
      [
        linkResult.link_id,
        'CREATED',
        user,
        {
          linked_trade_ids: linkedTradeIds,
          package_type: packageType,
          link_reason: linkReason,
          tags,
          user_comment: comment
        },
        null
      ]
    )

    return NextResponse.json({
      success: true,
      link_id: linkResult.link_id,
      manual_package_id: linkResult.manual_package_id,
      validation: items,
      metrics
    })
  } catch (error: any) {
    console.error('manual links POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create manual link' },
      { status: 500 }
    )
  }
}
