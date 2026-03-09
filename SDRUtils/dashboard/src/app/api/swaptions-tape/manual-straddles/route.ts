// ABOUTME: Persist and fetch manual "Make Straddle" package overrides for swaptions tape.
// ABOUTME: Stores package-level override IDs so inferred straddle tagging survives reloads.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  isValidSimpleAdminPassword,
  SIMPLE_ADMIN_AUTH_ERROR
} from '@/lib/utils'

const MANUAL_STRADDLES_TABLE = 'arbs_swaption_manual_straddles_v1'
const DEFAULT_LIST_LIMIT = 1000
const MAX_LIST_LIMIT = 5000

type ManualStraddlePayload = {
  package_ids?: unknown
  user?: unknown
  admin_password?: unknown
}

function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

function normalizeIdList(input: unknown) {
  if (!input) return [] as string[]
  const rawValues = Array.isArray(input)
    ? input
    : String(input).split(/[\s,]+/)
  const seen = new Set<string>()
  const result: string[] = []
  rawValues.forEach((value) => {
    const normalized = String(value || '').trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    result.push(normalized)
  })
  return result
}

function parseLimit(raw: string | null): number {
  if (!raw) return DEFAULT_LIST_LIMIT
  const parsed = Number(raw)
  if (!Number.isFinite(parsed) || parsed < 1) return DEFAULT_LIST_LIMIT
  return Math.min(parsed, MAX_LIST_LIMIT)
}

async function ensureManualStraddlesTable() {
  try {
    const exists = await query<{ rel: string | null }>(
      'SELECT to_regclass($1) AS rel',
      [MANUAL_STRADDLES_TABLE]
    )
    if (exists.rows[0]?.rel) {
      return null
    }

    await query(
      `CREATE TABLE IF NOT EXISTS ${MANUAL_STRADDLES_TABLE} (
        package_id TEXT PRIMARY KEY,
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_by TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )`
    )
    await query(
      `CREATE INDEX IF NOT EXISTS idx_swaption_manual_straddles_updated
       ON ${MANUAL_STRADDLES_TABLE}(updated_at DESC)`
    )
    return null
  } catch (error: any) {
    console.error('manual straddles table ensure error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to prepare manual straddle storage' },
      { status: 500 }
    )
  }
}

export async function GET(request: Request) {
  const tableError = await ensureManualStraddlesTable()
  if (tableError) return tableError

  const { searchParams } = new URL(request.url)
  const startDate = searchParams.get('start_date')
  const endDate = searchParams.get('end_date')
  const limit = parseLimit(searchParams.get('limit'))

  const params: unknown[] = []
  const conditions: string[] = []

  if (startDate) {
    params.push(startDate)
    conditions.push(`updated_at >= $${params.length}`)
  }
  if (endDate) {
    params.push(endDate)
    conditions.push(`updated_at <= $${params.length}`)
  }

  params.push(limit)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  try {
    const result = await query<{
      package_id: string
      created_by: string | null
      created_at: string
      updated_by: string | null
      updated_at: string
    }>(
      `SELECT package_id,
              created_by,
              created_at,
              updated_by,
              updated_at
       FROM ${MANUAL_STRADDLES_TABLE}
       ${whereClause}
       ORDER BY updated_at DESC
       LIMIT $${params.length}`,
      params
    )
    return NextResponse.json({ rows: result.rows })
  } catch (error: any) {
    console.error('manual straddles GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch manual straddles' },
      { status: 500 }
    )
  }
}

export async function POST(request: Request) {
  let payload: ManualStraddlePayload
  try {
    payload = (await request.json()) as ManualStraddlePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  const packageIds = normalizeIdList(payload.package_ids)
  if (!packageIds.length) {
    return NextResponse.json(
      { error: 'package_ids must include at least one package id.' },
      { status: 400 }
    )
  }
  if (!isValidSimpleAdminPassword(payload.admin_password)) {
    return NextResponse.json(
      { error: SIMPLE_ADMIN_AUTH_ERROR },
      { status: 401 }
    )
  }
  const user = normalizeText(payload.user)

  const tableError = await ensureManualStraddlesTable()
  if (tableError) return tableError

  try {
    const result = await query<{ package_id: string }>(
      `INSERT INTO ${MANUAL_STRADDLES_TABLE} (
         package_id,
         created_by,
         updated_by
       )
       SELECT DISTINCT package_id, $2, $2
       FROM unnest($1::text[]) AS package_id
       ON CONFLICT (package_id) DO UPDATE
       SET updated_at = NOW(),
           updated_by = COALESCE(EXCLUDED.updated_by, ${MANUAL_STRADDLES_TABLE}.updated_by)
       RETURNING package_id`,
      [packageIds, user]
    )

    return NextResponse.json({
      success: true,
      package_ids: result.rows.map((row) => row.package_id)
    })
  } catch (error: any) {
    console.error('manual straddles POST error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to persist manual straddles' },
      { status: 500 }
    )
  }
}

export async function DELETE(request: Request) {
  let payload: ManualStraddlePayload
  try {
    payload = (await request.json()) as ManualStraddlePayload
  } catch {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  const packageIds = normalizeIdList(payload.package_ids)
  if (!packageIds.length) {
    return NextResponse.json(
      { error: 'package_ids must include at least one package id.' },
      { status: 400 }
    )
  }
  if (!isValidSimpleAdminPassword(payload.admin_password)) {
    return NextResponse.json(
      { error: SIMPLE_ADMIN_AUTH_ERROR },
      { status: 401 }
    )
  }

  const tableError = await ensureManualStraddlesTable()
  if (tableError) return tableError

  try {
    const result = await query<{ package_id: string }>(
      `DELETE FROM ${MANUAL_STRADDLES_TABLE}
       WHERE package_id = ANY($1::text[])
       RETURNING package_id`,
      [packageIds]
    )

    return NextResponse.json({
      success: true,
      package_ids: result.rows.map((row) => row.package_id)
    })
  } catch (error: any) {
    console.error('manual straddles DELETE error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to remove manual straddles' },
      { status: 500 }
    )
  }
}
