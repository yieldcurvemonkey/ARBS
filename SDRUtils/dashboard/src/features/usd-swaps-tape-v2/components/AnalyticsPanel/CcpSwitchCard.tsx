'use client'
// ABOUTME: CCP basis (LCH↔CME) trades widget — design-doc §5.10 + §4.9.
// Aggregates the loaded tape rows into per-day switch counts + DV01,
// directional flow (LCH→CME vs CME→LCH), and tenor breakdown so
// analysts can see the basis pressure at a glance.
import type { JSX } from 'react'
import { useMemo } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import { summarizeCcpSwitchActivity } from '../../utils/ccpSwitchDetector'

export interface CcpSwitchCardProps {
  rows: readonly UsdSwapTapeRow[]
}

function formatDv01(v: number): string {
  if (!Number.isFinite(v)) return '—'
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`
  return v.toFixed(0)
}

export function CcpSwitchCard(props: CcpSwitchCardProps): JSX.Element {
  const aggregates = useMemo(
    () => summarizeCcpSwitchActivity(props.rows),
    [props.rows],
  )
  const totals = useMemo(() => {
    let switchCount = 0
    let dv01 = 0
    let lchToCme = 0
    let cmeToLch = 0
    const byTenor: Record<string, number> = {}
    for (const a of aggregates) {
      switchCount += a.switchCount
      dv01 += a.dv01
      lchToCme += a.lchToCmeDv01
      cmeToLch += a.cmeToLchDv01
      for (const [k, v] of Object.entries(a.byTenor)) {
        byTenor[k] = (byTenor[k] ?? 0) + v
      }
    }
    return { switchCount, dv01, lchToCme, cmeToLch, byTenor }
  }, [aggregates])

  const tenorRows = Object.entries(totals.byTenor).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  )
  const netFlow = totals.lchToCme - totals.cmeToLch

  return (
    <div
      data-testid="ccp-switch-card"
      className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          CCP basis trades
        </span>
        <span className="text-[10px] text-slate-500">
          {totals.switchCount} switches · {aggregates.length} days
        </span>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="text-[20px] font-semibold tracking-tight text-purple-200">
          {formatDv01(totals.dv01)}
        </span>
        <span className="pb-0.5 text-[10px] text-slate-500">total switch DV01</span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 text-[10px]">
        <span>
          LCH → CME{' '}
          <span className="text-purple-200">{formatDv01(totals.lchToCme)}</span>
        </span>
        <span>
          CME → LCH{' '}
          <span className="text-purple-200">{formatDv01(totals.cmeToLch)}</span>
        </span>
        <span className="col-span-2">
          Net flow{' '}
          <span
            className={
              netFlow > 0 ? 'text-emerald-300' : netFlow < 0 ? 'text-rose-300' : ''
            }
          >
            {netFlow >= 0 ? '+' : ''}
            {formatDv01(Math.abs(netFlow))} {netFlow >= 0 ? 'LCH→CME' : 'CME→LCH'}
          </span>
        </span>
      </div>
      {tenorRows.length > 0 ? (
        <div>
          <div className="text-[9.5px] uppercase tracking-wider text-slate-500">
            By tenor
          </div>
          <div className="flex flex-col gap-0.5">
            {tenorRows.map(([tenor, dv01]) => (
              <div key={tenor} className="flex items-center justify-between">
                <span className="text-slate-400">{tenor}Y</span>
                <span className="tabular-nums text-slate-200">{formatDv01(dv01)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-[10px] text-slate-500">No CCP-switch packages detected.</div>
      )}
    </div>
  )
}
