// ABOUTME: Create + list manual tape overrides (GROUP/SPLIT/DETACH).
export const dynamic = 'force-dynamic'
import { NextResponse } from 'next/server'
import { query, withClient } from '@/lib/db'
import { isValidTapeWritePassword, TAPE_WRITE_AUTH_ERROR } from '@/lib/utils'
import {
  OVERRIDES_TABLE,
  OVERRIDE_HISTORY_TABLE,
  GENERATE_PACKAGE_ID,
  allocateManualPackageId,
  computeOverrideMetrics,
  insertMemberRows,
  isOverrideType,
  normalizeIdList,
  normalizeTags,
  normalizeText,
  resolveManualPackageId,
  resolveOverrideLegs,
  supersedeOverlappingOverrides,
  validateOverride,
} from '@/lib/tape-overrides'

const DEFAULT_LIST_LIMIT = 200
const MAX_LIST_LIMIT = 1000

type OverridePostPayload = {
  override_type?: unknown
  trade_ids?: unknown
  manual_package_id?: unknown
  reason?: unknown
  tags?: unknown
  user?: unknown
  admin_password?: unknown
  validate_only?: unknown
}

function parseBoolean(value: string | null): boolean | null {
  if (!value) return null
  const v = value.trim().toLowerCase()
  if (['true', '1', 'yes', 'y'].includes(v)) return true
  if (['false', '0', 'no', 'n'].includes(v)) return false
  return null
}

function parseLimit(value: string | null): number {
  if (!value) return DEFAULT_LIST_LIMIT
  const parsed = Number(value)
  if (Number.isNaN(parsed) || parsed < 1) return DEFAULT_LIST_LIMIT
  return Math.min(parsed, MAX_LIST_LIMIT)
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const createdBy = searchParams.get('created_by')
  const isActive = parseBoolean(searchParams.get('is_active'))
  const limit = parseLimit(searchParams.get('limit'))

  const params: unknown[] = []
  const conditions: string[] = []
  if (createdBy) {
    params.push(`%${createdBy}%`)
    conditions.push(`created_by ILIKE $${params.length}`)
  }
  if (isActive !== null) {
    params.push(isActive)
    conditions.push(`is_active = $${params.length}`)
  }
  params.push(limit)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query(
      `SELECT * FROM ${OVERRIDES_TABLE}
       ${whereClause}
       ORDER BY created_at DESC
       LIMIT $${params.length}`,
      params,
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('tape overrides GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch overrides' },
      { status: 500 },
    )
  }
}

export async function POST(request: Request) {
  let payload: OverridePostPayload
  try {
    payload = (await request.json()) as OverridePostPayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  if (!isOverrideType(payload.override_type)) {
    return NextResponse.json(
      { error: "override_type must be one of 'GROUP', 'SPLIT', 'DETACH'." },
      { status: 400 },
    )
  }
  const overrideType = payload.override_type
  const tradeIds = normalizeIdList(payload.trade_ids)
  if (!tradeIds.length) {
    return NextResponse.json(
      { error: 'trade_ids must include at least one trade.' },
      { status: 400 },
    )
  }

  const validateOnly =
    payload.validate_only === true ||
    String(payload.validate_only).toLowerCase() === 'true'

  try {
    const legs = await resolveOverrideLegs(tradeIds)
    const metrics = computeOverrideMetrics(overrideType, tradeIds, legs)
    const { validation, hasErrors } = validateOverride(overrideType, tradeIds)

    if (validateOnly) {
      return NextResponse.json({ validation, metrics, linked_trade_ids: tradeIds })
    }
    if (hasErrors) {
      return NextResponse.json(
        { error: 'Validation failed', validation, metrics },
        { status: 409 },
      )
    }
    if (!isValidTapeWritePassword(payload.admin_password)) {
      return NextResponse.json({ error: TAPE_WRITE_AUTH_ERROR }, { status: 403 })
    }
    const user = normalizeText(payload.user)
    if (!user) {
      return NextResponse.json(
        { error: 'user is required to create an override.' },
        { status: 400 },
      )
    }

    const reason = normalizeText(payload.reason)
    const tags = normalizeTags(payload.tags)
    const requestedPkgId = resolveManualPackageId(
      overrideType,
      normalizeText(payload.manual_package_id),
    )

    const created = await withClient(async (client) => {
      await client.query('BEGIN')
      try {
        const manualPackageId =
          requestedPkgId === GENERATE_PACKAGE_ID
            ? await allocateManualPackageId(client)
            : requestedPkgId

        const insertParent = await client.query(
          `INSERT INTO ${OVERRIDES_TABLE}
             (override_type, manual_package_id, trade_ids, created_by, reason, tags, metrics)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           RETURNING override_id, manual_package_id`,
          [overrideType, manualPackageId, tradeIds, user, reason, tags, metrics],
        )
        const overrideId: string = insertParent.rows[0].override_id
        const finalPackageId: string | null = insertParent.rows[0].manual_package_id

        await supersedeOverlappingOverrides(client, tradeIds, overrideId, user)
        await insertMemberRows(client, overrideId, overrideType, finalPackageId, tradeIds)
        await client.query(
          `INSERT INTO ${OVERRIDE_HISTORY_TABLE}
             (override_id, action, changed_by, change_details)
           VALUES ($1, $2, $3, $4::jsonb)`,
          [overrideId, 'CREATED', user, { override_type: overrideType, trade_ids: tradeIds, manual_package_id: finalPackageId, reason, tags }],
        )
        await client.query('COMMIT')
        return { override_id: overrideId, manual_package_id: finalPackageId }
      } catch (txErr) {
        await client.query('ROLLBACK')
        throw txErr
      }
    })

    return NextResponse.json({
      success: true,
      override_id: created.override_id,
      manual_package_id: created.manual_package_id,
      validation,
      metrics,
    })
  } catch (error: any) {
    console.error('tape overrides POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to create override' },
      { status: 500 },
    )
  }
}
