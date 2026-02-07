// ABOUTME: Manual link utilities for swaption package linking operations.
import { query } from './db'
import { randomUUID } from 'crypto'

export const MANUAL_LINKS_TABLE = 'arbs_swaption_manual_links_v1'
export const MANUAL_LINK_HISTORY_TABLE = 'arbs_swaption_link_history_v1'

export function normalizeIdList(raw: unknown): string[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean)
  if (typeof raw === 'string') return raw.split(',').map(s => s.trim()).filter(Boolean)
  return []
}

export function generateManualPackageId(): string {
  return `MANUAL-${randomUUID().slice(0, 8).toUpperCase()}`
}

export async function checkManualLinkTables(): Promise<boolean> {
  try {
    await query(`SELECT 1 FROM ${MANUAL_LINKS_TABLE} LIMIT 0`)
    return true
  } catch {
    return false
  }
}

export async function findManualLinkConflicts(tradeIds: string[]): Promise<any[]> {
  if (!tradeIds.length) return []
  const result = await query(
    `SELECT link_id, manual_package_id, linked_trade_ids
     FROM ${MANUAL_LINKS_TABLE}
     WHERE is_active = true
       AND linked_trade_ids && $1`,
    [tradeIds],
  )
  return result.rows
}

export async function resolveLinkLegs(tradeIds: string[]): Promise<any[]> {
  if (!tradeIds.length) return []
  const result = await query(
    `SELECT l.*, p.package_type, p.tenor_label, p.forward_label, p.execution_start
     FROM arbs_swaption_legs_v1 l
     JOIN arbs_swaption_packages_v1 p ON p.package_id = l.package_id
     WHERE l.trade_id = ANY($1)`,
    [tradeIds],
  )
  return result.rows
}

export function buildValidationItems(legs: any[]): any[] {
  return legs.map(l => ({
    tradeId: l.trade_id,
    packageId: l.package_id,
    packageType: l.package_type,
    tenorLabel: l.tenor_label,
    forwardLabel: l.forward_label,
  }))
}

export function computeLinkMetrics(legs: any[]): Record<string, any> {
  const totalNotional = legs.reduce((sum: number, l: any) => sum + (Number(l.notional) || 0), 0)
  const totalPremium = legs.reduce((sum: number, l: any) => sum + (Number(l.premium) || 0), 0)
  return { totalNotional, totalPremium, legCount: legs.length }
}
