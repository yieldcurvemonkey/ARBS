// ABOUTME: Pure client-side aggregation for the MMS (matched-maturity
// swap / UST asset-swap) Analytics tab (design-doc §3, 2026-07-09-mms-
// extension-design.md). Mirrors underlierMix.ts / swapSpreadVwap.ts —
// no new API endpoint, aggregates over the rows already loaded into
// the tape.

import type { UsdSwapTapeRow } from '../types'

export type MmsSummary = {
  mmsCount: number
  totalCount: number
  mmsDv01: number
  totalDv01: number
  dv01Share: number
  mmsNotional: number
  totalNotional: number
  notionalShare: number
}

export type MmsDailyBucket = {
  date: string
  mmsCount: number
  totalCount: number
  mmsDv01: number
  totalDv01: number
  share: number
}

export type MmsMaturitySlice = {
  mmyy: string
  count: number
  dv01: number
  notional: number
}

export type MmsCusipEntry = {
  cusip: string
  mmyy: string
  count: number
  dv01: number
  notional: number
}

export function isMmsRow(row: UsdSwapTapeRow): boolean {
  if (row.is_matched_maturity_all === true) return true
  const pt = String(row.package_type ?? '').toUpperCase()
  return pt.startsWith('MATCHED_MATURITY')
}

function absNum(v: unknown): number {
  return Math.abs(Number(v ?? 0)) || 0
}

export function computeMmsSummary(
  rows: readonly UsdSwapTapeRow[],
): MmsSummary {
  let mmsCount = 0, totalCount = rows.length
  let mmsDv01 = 0, totalDv01 = 0
  let mmsNotional = 0, totalNotional = 0
  for (const row of rows) {
    const dv01 = absNum(row.total_risk)
    const notional = absNum(row.total_notional)
    totalDv01 += dv01
    totalNotional += notional
    if (isMmsRow(row)) {
      mmsCount++
      mmsDv01 += dv01
      mmsNotional += notional
    }
  }
  return {
    mmsCount,
    totalCount,
    mmsDv01,
    totalDv01,
    dv01Share: totalDv01 > 0 ? mmsDv01 / totalDv01 : 0,
    mmsNotional,
    totalNotional,
    notionalShare: totalNotional > 0 ? mmsNotional / totalNotional : 0,
  }
}

function dayBucket(ts: string | null | undefined): string {
  if (!ts) return 'UNKNOWN'
  return ts.slice(0, 10)
}

export function computeMmsDailyVolume(
  rows: readonly UsdSwapTapeRow[],
): MmsDailyBucket[] {
  const buckets = new Map<string, { mmsCount: number; totalCount: number; mmsDv01: number; totalDv01: number }>()
  for (const row of rows) {
    const date = dayBucket(row.execution_start)
    const b = buckets.get(date) ?? { mmsCount: 0, totalCount: 0, mmsDv01: 0, totalDv01: 0 }
    const dv01 = absNum(row.total_risk)
    b.totalCount++
    b.totalDv01 += dv01
    if (isMmsRow(row)) {
      b.mmsCount++
      b.mmsDv01 += dv01
    }
    buckets.set(date, b)
  }
  return Array.from(buckets.entries())
    .map(([date, b]) => ({
      date,
      ...b,
      share: b.totalCount > 0 ? b.mmsCount / b.totalCount : 0,
    }))
    .sort((a, b) => a.date.localeCompare(b.date))
}

const MMYY_RE = /\b(\d{4})(?=\/|\s|$)/g

function extractMmyys(label: string | null | undefined): string[] {
  if (!label) return []
  const matches: string[] = []
  let m: RegExpExecArray | null
  MMYY_RE.lastIndex = 0
  while ((m = MMYY_RE.exec(label)) !== null) {
    matches.push(m[1])
  }
  return matches
}

export function computeMmsMaturityDistribution(
  rows: readonly UsdSwapTapeRow[],
): MmsMaturitySlice[] {
  const buckets = new Map<string, { count: number; dv01: number; notional: number }>()
  for (const row of rows) {
    if (!isMmsRow(row)) continue
    const mmyys = extractMmyys(row.tape_label_ust_alias)
    const dv01 = absNum(row.total_risk)
    const notional = absNum(row.total_notional)
    for (const mmyy of mmyys) {
      const b = buckets.get(mmyy) ?? { count: 0, dv01: 0, notional: 0 }
      b.count++
      b.dv01 += dv01
      b.notional += notional
      buckets.set(mmyy, b)
    }
  }
  return Array.from(buckets.entries())
    .map(([mmyy, b]) => ({ mmyy, ...b }))
    .sort((a, b) => b.count - a.count)
}

export function computeMmsTopCusips(
  rows: readonly UsdSwapTapeRow[],
): MmsCusipEntry[] {
  const buckets = new Map<string, { mmyy: string; count: number; dv01: number; notional: number }>()
  for (const row of rows) {
    if (!isMmsRow(row)) continue
    const legs = row.legs_json ?? []
    for (const leg of legs) {
      if (!leg.matched_ust_maturity || !leg.ust_cusip) continue
      const cusip = String(leg.ust_cusip)
      const b = buckets.get(cusip) ?? {
        mmyy: String(leg.tape_label_ust_alias ?? ''),
        count: 0,
        dv01: 0,
        notional: 0,
      }
      b.count++
      // Leg-level risk/notional aren't always populated on older rows;
      // fall back to an even split of the package total across legs.
      b.dv01 += absNum(leg.risk ?? (row.total_risk ? Number(row.total_risk) / Math.max(legs.length, 1) : 0))
      b.notional += absNum(leg.notional ?? (row.total_notional ? Number(row.total_notional) / Math.max(legs.length, 1) : 0))
      buckets.set(cusip, b)
    }
  }
  return Array.from(buckets.entries())
    .map(([cusip, b]) => ({ cusip, ...b }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 10)
}
