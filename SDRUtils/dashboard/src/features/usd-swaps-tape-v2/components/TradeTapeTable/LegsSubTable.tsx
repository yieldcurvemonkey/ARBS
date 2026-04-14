'use client'
// ABOUTME: Per-leg expansion table rendered below an expanded package row.
import type { JSX } from 'react'
import { DataTable } from 'primereact/datatable'
import { Column } from 'primereact/column'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { formatDv01, formatNotional, formatRate, formatTime } from '../../utils/format'
import { LIFECYCLE_LABELS, LIFECYCLE_TONES } from '../../constants'

function lifecycleBody(leg: UsdSwapTapeLeg) {
  const type = leg.lifecycle_type
  if (!type) return '—'
  return (
    <span
      className={`px-1 py-0.5 rounded text-[10px] font-semibold ${LIFECYCLE_TONES[type] ?? ''}`}
    >
      {LIFECYCLE_LABELS[type] ?? type}
    </span>
  )
}

function tradeIdBody(leg: UsdSwapTapeLeg) {
  const tid = leg.trade_id ?? '—'
  return (
    <button
      type="button"
      className="font-mono text-[11px] text-slate-300 hover:text-slate-100"
      onClick={() => {
        try {
          navigator.clipboard?.writeText(String(tid))
        } catch {
          /* ignore */
        }
      }}
      aria-label={`copy trade id ${tid}`}
    >
      {tid}
    </button>
  )
}

function crossDayProgress(leg: UsdSwapTapeLeg) {
  const pct = leg.xd_notional_pct_remaining
  if (pct === null || pct === undefined || pct >= 0.999) return null
  const width = `${Math.max(0, Math.min(1, Number(pct))) * 100}%`
  return (
    <div className="w-16 h-1 bg-slate-800 rounded overflow-hidden" aria-label="cross-day notional remaining">
      <div className="h-full bg-emerald-500" style={{ width }} />
    </div>
  )
}

function qualityFlagsBody(leg: UsdSwapTapeLeg) {
  const flags = leg.quality_flags ?? []
  if (flags.length === 0) return '—'
  return (
    <div className="flex gap-1 flex-wrap">
      {flags.map((f) => (
        <span
          key={f}
          className="px-1 py-0.5 rounded bg-zinc-800/60 text-zinc-300 text-[10px]"
        >
          {f}
        </span>
      ))}
    </div>
  )
}

export function LegsSubTable({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const legs = row.legs_json ?? []
  return (
    <div
      className="bg-slate-950/70 px-4 py-2 rounded-md"
      data-testid={`legs-subtable-${row.package_id}`}
    >
      <DataTable
        value={legs as any[]}
        dataKey="trade_id"
        size="small"
        className="text-xs"
        rowClassName={() => 'hover:bg-slate-900/60'}
      >
        <Column header="#" body={(l: UsdSwapTapeLeg) => l.leg_order ?? '—'} style={{ width: 40 }} />
        <Column header="Lifecycle" body={lifecycleBody} style={{ width: 90 }} />
        <Column
          header="Time"
          body={(l: UsdSwapTapeLeg) => formatTime(l.execution_timestamp)}
          style={{ width: 92 }}
        />
        <Column header="Trade ID" body={tradeIdBody} style={{ width: 160 }} />
        <Column
          header="Tape Label"
          body={(l: UsdSwapTapeLeg) => l.tape_label ?? '—'}
          style={{ width: 320 }}
        />
        <Column
          header="Tenor"
          body={(l: UsdSwapTapeLeg) => l.tenor_display ?? l.tenor_label ?? '—'}
          style={{ width: 72 }}
        />
        <Column
          header="Notional"
          body={(l: UsdSwapTapeLeg) => formatNotional(l.notional ?? null, { compact: true })}
          style={{ width: 110 }}
        />
        <Column
          header="DV01"
          body={(l: UsdSwapTapeLeg) => formatDv01(l.risk ?? null, { signed: true })}
          style={{ width: 96 }}
        />
        <Column
          header="Rate"
          body={(l: UsdSwapTapeLeg) => formatRate(l.fixed_rate ?? null)}
          style={{ width: 84 }}
        />
        <Column header="Flags" body={qualityFlagsBody} style={{ width: 140 }} />
        <Column header="X-Day" body={crossDayProgress} style={{ width: 80 }} />
      </DataTable>
    </div>
  )
}
