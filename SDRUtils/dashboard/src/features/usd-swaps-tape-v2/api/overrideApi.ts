// ABOUTME: Tape-local REST client for structural override CRUD. Mirrors
// the manualLinkApi factory's error-parsing / query-building idioms but
// exports flat named functions bound to the tape overrides base path.
// Do NOT reuse the shared manual-links client — its base path/semantics
// differ (legacy tables vs. read-time tape override resolution).
import { TAPE_V2_API_BASE } from '../constants'
import type { OverrideType, TapeOverride, OverrideValidationItem } from '../types/override.types'

const OVERRIDES_BASE = `${TAPE_V2_API_BASE}/overrides`

export interface CreateOverrideBody {
  override_type: OverrideType
  trade_ids: string[]
  manual_package_id?: string
  reason?: string
  tags?: string[] | string
  user: string
  admin_password: string
  validate_only?: boolean
}

export interface UpdateOverrideBody {
  reason?: string
  tags?: string[] | string
  add_trades?: string[]
  remove_trades?: string[]
  user: string
  admin_password: string
}

export interface DeactivateOverrideBody {
  reason?: string
  user: string
  admin_password: string
}

export interface ListOverridesQuery {
  is_active?: boolean
  created_by?: string
  limit?: number
}

export interface CreateOverrideResult {
  success: true
  override_id: string
  manual_package_id: string | null
  validation: OverrideValidationItem[]
  metrics: Record<string, unknown>
}

export interface ValidateOverrideResult {
  validation: OverrideValidationItem[]
  metrics: Record<string, unknown> | null
  linked_trade_ids: string[]
}

export interface OverrideMemberRow {
  trade_id: string
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
  is_active: boolean
}

export interface OverrideHistoryRow {
  history_id: number
  override_id: string
  action: string
  changed_by: string
  changed_at: string
  change_details: Record<string, unknown> | null
  previous_state: Record<string, unknown> | null
}

export interface OverrideDetailBundle {
  override: TapeOverride
  members: OverrideMemberRow[]
  history: OverrideHistoryRow[]
}

async function parseError(res: Response): Promise<Error> {
  try {
    const payload = await res.json()
    if (payload && typeof payload === 'object' && 'error' in payload && payload.error) {
      return new Error(String((payload as { error: unknown }).error))
    }
  } catch {
    // ignore
  }
  return new Error(`Request failed with status ${res.status}`)
}

function buildQueryString(query: Record<string, unknown>): string {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null) return
    params.set(key, String(value))
  })
  const s = params.toString()
  return s ? `?${s}` : ''
}

export async function createOverride(body: CreateOverrideBody): Promise<CreateOverrideResult> {
  const res = await fetch(OVERRIDES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as CreateOverrideResult
}

export async function validateOverride(body: CreateOverrideBody): Promise<ValidateOverrideResult> {
  const res = await fetch(OVERRIDES_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, validate_only: true }),
  })
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return {
    validation: (payload?.validation as OverrideValidationItem[]) ?? [],
    metrics: (payload?.metrics as Record<string, unknown>) ?? null,
    linked_trade_ids: (payload?.linked_trade_ids as string[]) ?? [],
  }
}

export async function fetchOverrides(query?: ListOverridesQuery): Promise<{ rows: TapeOverride[] }> {
  const url = `${OVERRIDES_BASE}${query ? buildQueryString(query as Record<string, unknown>) : ''}`
  const res = await fetch(url)
  if (!res.ok) throw await parseError(res)
  const payload = await res.json()
  return { rows: (payload?.rows as TapeOverride[]) ?? [] }
}

export async function fetchOverrideDetail(overrideId: string): Promise<OverrideDetailBundle> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`)
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as OverrideDetailBundle
}

export async function updateOverride(
  overrideId: string,
  body: UpdateOverrideBody,
): Promise<{ success: true; override_id: string }> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true; override_id: string }
}

export async function deactivateOverride(
  overrideId: string,
  body: DeactivateOverrideBody,
): Promise<{ success: true }> {
  const res = await fetch(`${OVERRIDES_BASE}/${encodeURIComponent(overrideId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await parseError(res)
  return (await res.json()) as { success: true }
}
