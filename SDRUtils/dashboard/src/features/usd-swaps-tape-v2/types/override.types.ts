export type OverrideType = 'GROUP' | 'SPLIT' | 'DETACH'

export interface TapeOverride {
  override_id: string
  override_type: OverrideType
  manual_package_id: string | null
  trade_ids: string[]
  created_by: string
  created_at: string
  updated_at: string | null
  is_active: boolean
  reason: string | null
  tags: string[] | null
  metrics: Record<string, unknown>
}

export interface OverrideValidationItem {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
}
