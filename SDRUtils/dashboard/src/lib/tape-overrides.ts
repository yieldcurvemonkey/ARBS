// ABOUTME: Tape-local helpers for manual package overrides (GROUP/SPLIT/DETACH):
// validation, metrics, supersession, membership rows, manual_package_id gen.
import { randomUUID } from 'crypto'
import type { PoolClient } from 'pg'
import { query } from '@/lib/db'
import {
  TAPE_LEGS,
  TAPE_OVERRIDE_HISTORY,
  TAPE_OVERRIDE_MEMBERS,
  TAPE_OVERRIDES,
} from '@/lib/tape-tables'

export const OVERRIDES_TABLE = TAPE_OVERRIDES
export const OVERRIDE_MEMBERS_TABLE = TAPE_OVERRIDE_MEMBERS
export const OVERRIDE_HISTORY_TABLE = TAPE_OVERRIDE_HISTORY
export const TAPE_LEGS_TABLE = TAPE_LEGS

export type OverrideType = 'GROUP' | 'SPLIT' | 'DETACH'
export const OVERRIDE_TYPES: OverrideType[] = ['GROUP', 'SPLIT', 'DETACH']

export interface OverrideValidationItem {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
}

export interface OverrideMetrics {
  trade_count: number
  override_type: OverrideType
  distinct_package_ids: number
  source_package_ids: string[]
}

export interface OverrideLeg {
  trade_id: string
  package_id: string | null
}

export interface OverrideMemberRow {
  trade_id: string
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
}

// Sentinel: resolveManualPackageId returns this when the caller must
// allocate a fresh id inside the transaction (GROUP with none supplied).
export const GENERATE_PACKAGE_ID = '__GENERATE__'

export function isOverrideType(value: unknown): value is OverrideType {
  return typeof value === 'string' && (OVERRIDE_TYPES as string[]).includes(value)
}

export function normalizeText(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function normalizeTags(value: unknown): string[] | null {
  if (value === undefined || value === null) return null
  if (Array.isArray(value)) {
    const tags = value.map((entry) => String(entry).trim()).filter(Boolean)
    return tags.length ? tags : null
  }
  if (typeof value === 'string') {
    const tags = value.split(',').map((entry) => entry.trim()).filter(Boolean)
    return tags.length ? tags : null
  }
  return null
}

export function normalizeIdList(input: unknown): string[] {
  if (!input) return []
  const rawValues = Array.isArray(input) ? input : String(input).split(/[\s,]+/)
  const seen = new Set<string>()
  const result: string[] = []
  rawValues.forEach((value) => {
    const normalized = String(value).trim()
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    result.push(normalized)
  })
  return result
}

function buildDateToken(date: Date): string {
  const yyyy = String(date.getUTCFullYear())
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(date.getUTCDate()).padStart(2, '0')
  return `${yyyy}${mm}${dd}`
}

export function generateManualPackageId(): string {
  const token = randomUUID().replace(/-/g, '').slice(0, 8).toUpperCase()
  return `SMO-${buildDateToken(new Date())}-${token}`
}

// GROUP clusters need a manual_package_id; SPLIT/DETACH do not (the view keys
// synthetic rows off package_id + trade_id). A caller-supplied id always wins.
export function resolveManualPackageId(
  overrideType: OverrideType,
  provided: string | null,
): string | null {
  if (provided) return provided
  return overrideType === 'GROUP' ? GENERATE_PACKAGE_ID : null
}

export function validateOverride(
  overrideType: OverrideType,
  tradeIds: string[],
): { validation: OverrideValidationItem[]; hasErrors: boolean } {
  const validation: OverrideValidationItem[] = []
  const count = tradeIds.length
  if (overrideType === 'GROUP' && count < 2) {
    validation.push({
      level: 'error',
      code: 'GROUP_MIN_TRADES',
      message: 'GROUP overrides require at least two trades.',
    })
  } else if (count < 1) {
    validation.push({
      level: 'error',
      code: 'MIN_TRADES',
      message: 'Select at least one trade.',
    })
  } else {
    validation.push({
      level: 'info',
      code: 'TRADE_COUNT',
      message: `${count} trade${count === 1 ? '' : 's'} selected.`,
    })
  }
  const hasErrors = validation.some((item) => item.level === 'error')
  return { validation, hasErrors }
}

export function computeOverrideMetrics(
  overrideType: OverrideType,
  tradeIds: string[],
  legs: OverrideLeg[],
): OverrideMetrics {
  const packageIds = Array.from(
    new Set(
      legs
        .map((leg) => (leg.package_id == null ? '' : String(leg.package_id).trim()))
        .filter(Boolean),
    ),
  )
  return {
    trade_count: tradeIds.length,
    override_type: overrideType,
    distinct_package_ids: packageIds.length,
    source_package_ids: packageIds,
  }
}

export function buildMemberRows(
  overrideId: string,
  overrideType: OverrideType,
  manualPackageId: string | null,
  tradeIds: string[],
): OverrideMemberRow[] {
  return tradeIds.map((tradeId) => ({
    trade_id: tradeId,
    override_id: overrideId,
    override_type: overrideType,
    manual_package_id: manualPackageId,
  }))
}

// --- DB helpers (read-only reads via `query`; transactional writes take a client) ---

export async function resolveOverrideLegs(tradeIds: string[]): Promise<OverrideLeg[]> {
  if (!tradeIds.length) return []
  const result = await query<OverrideLeg>(
    `SELECT trade_id, package_id
     FROM ${TAPE_LEGS_TABLE}
     WHERE trade_id = ANY($1)`,
    [tradeIds],
  )
  return result.rows
}

export async function findOverlappingActiveOverrideIds(
  tradeIds: string[],
  excludeOverrideId?: string,
): Promise<string[]> {
  if (!tradeIds.length) return []
  const params: unknown[] = [tradeIds]
  let sql = `SELECT override_id FROM ${OVERRIDES_TABLE}
             WHERE is_active = TRUE AND trade_ids && $1`
  if (excludeOverrideId) {
    params.push(excludeOverrideId)
    sql += ` AND override_id <> $${params.length}`
  }
  const result = await query<{ override_id: string }>(sql, params)
  return result.rows.map((row) => row.override_id)
}

// Allocate a manual_package_id not already present. The (manual_package_id)
// index is non-unique, so this is a best-effort pre-check inside the txn.
export async function allocateManualPackageId(client: PoolClient): Promise<string> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const candidate = generateManualPackageId()
    const existing = await client.query(
      `SELECT 1 FROM ${OVERRIDES_TABLE} WHERE manual_package_id = $1 LIMIT 1`,
      [candidate],
    )
    if (!existing.rows.length) return candidate
  }
  throw new Error('Failed to allocate manual_package_id after 5 attempts')
}

// Deactivate every active override overlapping `tradeIds` (excluding
// `newOverrideId`), point them at the new parent, deactivate their member
// rows, and log SUPERSEDED history. Must run before inserting the new members
// so the partial-unique (trade_id) WHERE is_active index is not violated.
export async function supersedeOverlappingOverrides(
  client: PoolClient,
  tradeIds: string[],
  newOverrideId: string,
  changedBy: string,
): Promise<string[]> {
  const overlapping = await client.query<{ override_id: string }>(
    `SELECT override_id FROM ${OVERRIDES_TABLE}
     WHERE is_active = TRUE AND trade_ids && $1 AND override_id <> $2`,
    [tradeIds, newOverrideId],
  )
  const ids = overlapping.rows.map((row) => row.override_id)
  if (!ids.length) return []

  await client.query(
    `UPDATE ${OVERRIDES_TABLE}
     SET is_active = FALSE, superseded_by = $1, updated_by = $2, updated_at = NOW()
     WHERE override_id = ANY($3)`,
    [newOverrideId, changedBy, ids],
  )
  await client.query(
    `UPDATE ${OVERRIDE_MEMBERS_TABLE}
     SET is_active = FALSE
     WHERE override_id = ANY($1)`,
    [ids],
  )
  await client.query(
    `INSERT INTO ${OVERRIDE_HISTORY_TABLE} (override_id, action, changed_by, change_details)
     SELECT oid, 'SUPERSEDED', $2, $3::jsonb
     FROM unnest($1::uuid[]) AS oid`,
    [ids, changedBy, { superseded_by: newOverrideId }],
  )
  return ids
}

// Insert member rows for an override in a single statement.
export async function insertMemberRows(
  client: PoolClient,
  overrideId: string,
  overrideType: OverrideType,
  manualPackageId: string | null,
  tradeIds: string[],
): Promise<void> {
  if (!tradeIds.length) return
  await client.query(
    `INSERT INTO ${OVERRIDE_MEMBERS_TABLE}
       (trade_id, override_id, override_type, manual_package_id, is_active)
     SELECT t, $2, $3, $4, TRUE FROM unnest($1::text[]) AS t`,
    [tradeIds, overrideId, overrideType, manualPackageId],
  )
}
