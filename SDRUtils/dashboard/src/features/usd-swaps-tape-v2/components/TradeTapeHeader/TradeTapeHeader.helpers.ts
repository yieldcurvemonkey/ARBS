// Pure helpers for header summary computation.
import type { UsdSwapTapeRow, LifecycleType } from '../../types'

export type TapeSummary = {
  tradeCount: number
  newRisk: number
  grossDv01: number
  grossNotional: number
  packageCount: number
  clusterCount: number
  lifecycleCounts: Partial<Record<LifecycleType, number>>
}

export function summarize(rows: UsdSwapTapeRow[]): TapeSummary {
  const lifecycleCounts: Partial<Record<LifecycleType, number>> = {}
  const clusters = new Set<string>()
  let grossDv01 = 0
  let grossNotional = 0
  let tradeCount = 0
  let newRisk = 0

  for (const row of rows) {
    grossDv01 += Math.abs(Number(row.gross_risk ?? row.total_risk ?? 0))
    grossNotional += Math.abs(Number(row.gross_notional ?? row.total_notional ?? 0))
    const legs = row.legs_count ?? 1
    tradeCount += legs
    if (row.is_new_risk) newRisk += legs
    if (row.cluster_id) clusters.add(row.cluster_id)
    const mix = row.lifecycle_mix ?? {}
    for (const [k, v] of Object.entries(mix)) {
      const key = k as LifecycleType
      lifecycleCounts[key] = (lifecycleCounts[key] ?? 0) + Number(v ?? 0)
    }
  }

  return {
    tradeCount,
    newRisk,
    grossDv01,
    grossNotional,
    packageCount: rows.length,
    clusterCount: clusters.size,
    lifecycleCounts,
  }
}
