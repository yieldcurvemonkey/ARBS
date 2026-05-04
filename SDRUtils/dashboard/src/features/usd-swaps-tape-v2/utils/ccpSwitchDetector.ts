// ABOUTME: CCP-switch (LCH↔CME basis) detector — design-doc §5.10 +
// §4.9. Clarus tracks "CCPSwitch" as a distinct package type because
// the trade is economically a CCP-switch, not a directional view.
// Without an explicit `package_type=CCP_SWITCH` field on the SDR feed,
// we detect at row-level: two opposite-sign legs, same currency, same
// tenor, one cleared at LCH and one at CME. Surfaces directional flow
// (LCH→CME vs CME→LCH) so analysts see the basis pressure.

import type { UsdSwapTapeRow, UsdSwapTapeLeg } from '../types'

const SUPPORTED_CCP_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ['LCH', 'CME'],
] as const

function ccpOf(leg: UsdSwapTapeLeg | undefined | null): string | null {
  if (!leg) return null
  const v = String(leg.ccp ?? '').trim().toUpperCase()
  return v.length > 0 ? v : null
}

function tenorOf(leg: UsdSwapTapeLeg | undefined | null): number | null {
  if (!leg) return null
  const v = (leg as { tenor_years?: number | null }).tenor_years
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

function riskOf(leg: UsdSwapTapeLeg | undefined | null): number | null {
  if (!leg) return null
  const v = leg.risk
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

export type CcpSwitchVerdict = {
  isCcpSwitch: boolean
  fromCcp: string | null
  toCcp: string | null
  /** |risk| of the larger leg, in $ per bp. */
  switchDv01: number
  tenorYears: number | null
}

export function detectCcpSwitch(row: UsdSwapTapeRow): CcpSwitchVerdict {
  const legs = row.legs_json ?? []
  // Need exactly two legs to identify a switch unambiguously. CURVEs and
  // FLYs are non-switches by Clarus convention.
  if (legs.length !== 2) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  const [a, b] = legs
  const ccpA = ccpOf(a)
  const ccpB = ccpOf(b)
  if (!ccpA || !ccpB || ccpA === ccpB) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  const supported = SUPPORTED_CCP_PAIRS.some(
    ([x, y]) => (ccpA === x && ccpB === y) || (ccpA === y && ccpB === x),
  )
  if (!supported) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  const tenorA = tenorOf(a)
  const tenorB = tenorOf(b)
  if (tenorA == null || tenorB == null || Math.abs(tenorA - tenorB) > 0.01) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  const riskA = riskOf(a)
  const riskB = riskOf(b)
  if (riskA == null || riskB == null) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  if (Math.sign(riskA) === Math.sign(riskB) || riskA === 0 || riskB === 0) {
    return { isCcpSwitch: false, fromCcp: null, toCcp: null, switchDv01: 0, tenorYears: null }
  }
  // A CCP switch unwinds an existing position at one CCP and opens an
  // equal-and-opposite position at the other. The unwind leg shows up
  // as positive risk (closing a pay-fixed position = receiving fixed),
  // so the CCP with positive risk is the FROM (the CCP being left)
  // and the CCP with negative risk is the TO (where the new position
  // is being opened). Flip if field experience proves the convention
  // is inverted.
  const fromCcp = riskA > 0 ? ccpA : ccpB
  const toCcp = riskA > 0 ? ccpB : ccpA
  return {
    isCcpSwitch: true,
    fromCcp,
    toCcp,
    switchDv01: Math.max(Math.abs(riskA), Math.abs(riskB)),
    tenorYears: tenorA,
  }
}

export type CcpSwitchDailyAggregate = {
  day: string
  switchCount: number
  /** Σ|risk| of the larger leg per switch, $ per bp. */
  dv01: number
  /** Σ|risk| where flow is LCH → CME. */
  lchToCmeDv01: number
  /** Σ|risk| where flow is CME → LCH. */
  cmeToLchDv01: number
  /** Map<tenorString, dv01>. Tenor is rounded to whole years. */
  byTenor: Record<string, number>
}

function dayBucket(timestamp: string | null | undefined): string | null {
  if (!timestamp) return null
  const ms = Date.parse(timestamp)
  if (!Number.isFinite(ms)) return null
  return new Date(ms).toISOString().slice(0, 10)
}

export function summarizeCcpSwitchActivity(
  rows: readonly UsdSwapTapeRow[],
): CcpSwitchDailyAggregate[] {
  const map = new Map<string, CcpSwitchDailyAggregate>()
  for (const row of rows) {
    const verdict = detectCcpSwitch(row)
    if (!verdict.isCcpSwitch) continue
    const day = dayBucket(row.execution_start)
    if (!day) continue
    const cur =
      map.get(day) ?? {
        day,
        switchCount: 0,
        dv01: 0,
        lchToCmeDv01: 0,
        cmeToLchDv01: 0,
        byTenor: {},
      }
    cur.switchCount += 1
    cur.dv01 += verdict.switchDv01
    if (verdict.fromCcp === 'LCH' && verdict.toCcp === 'CME') {
      cur.lchToCmeDv01 += verdict.switchDv01
    } else if (verdict.fromCcp === 'CME' && verdict.toCcp === 'LCH') {
      cur.cmeToLchDv01 += verdict.switchDv01
    }
    if (verdict.tenorYears != null) {
      const key = String(Math.round(verdict.tenorYears))
      cur.byTenor[key] = (cur.byTenor[key] ?? 0) + verdict.switchDv01
    }
    map.set(day, cur)
  }
  const out = Array.from(map.values())
  out.sort((a, b) => a.day.localeCompare(b.day))
  return out
}
