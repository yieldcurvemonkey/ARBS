// ABOUTME: Rich tooltip shown on hover over a vol grid cell.
// Displays vol, change, premium, source, last print details, and propagation info.
'use client'

import { VolGridCell } from '../types'

type Props = {
  cell: VolGridCell
  position: { x: number; y: number }
}

function formatTimestamp(epoch: number | null): string {
  if (!epoch) return '—'
  const d = new Date(epoch)
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'America/New_York',
  }) + ' ET'
}

function formatStaleness(minutes: number): string {
  if (minutes < 0) return 'no data'
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${Math.round(minutes)} min ago`
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)} hours ago`
  return `${(minutes / 1440).toFixed(1)} days ago`
}

function formatNotional(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}bn`
  if (n >= 1e6) return `${(n / 1e6).toFixed(0)}mm`
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`
  return String(n)
}

function formatPremium(premium: number | null): string {
  if (premium === null) return '—'
  if (Math.abs(premium) >= 1e6) return `$${(premium / 1e6).toFixed(2)}mm`
  if (Math.abs(premium) >= 1e3) return `$${(premium / 1e3).toFixed(0)}k`
  return `$${premium.toFixed(0)}`
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'direct_observation': return 'Direct observation'
    case 'interpolated': return 'Interpolated'
    case 'propagated': return 'Propagated from neighbor'
    case 'prior': return 'Prior (historical median)'
    case 'no_data': return 'No data'
    default: return source
  }
}

export function VolGridTooltip({ cell, position }: Props) {
  // Clamp position to avoid going off screen
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.min(position.x, window.innerWidth - 320),
    top: Math.max(8, Math.min(position.y, window.innerHeight - 350)),
    zIndex: 100,
  }

  return (
    <div style={style} className="w-[300px] bg-slate-900 border border-slate-700 rounded-lg shadow-xl p-3 text-xs font-mono pointer-events-none">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-slate-700">
        <span className="text-sm font-semibold text-white">
          {cell.expiry}x{cell.tenor}
        </span>
        <span className="text-[10px] text-slate-400 uppercase">{cell.quadrant}</span>
      </div>

      {/* Vol info */}
      <div className="space-y-1.5">
        <Row label="ATMF Vol" value={cell.atmfVol !== null ? `${cell.atmfVol.toFixed(1)} bpvol/yr` : '—'} />
        <Row
          label="Change"
          value={cell.atmfVolChange !== null
            ? `${cell.atmfVolChange >= 0 ? '+' : ''}${cell.atmfVolChange.toFixed(1)} from prior`
            : '—'}
          valueClass={cell.atmfVolChange !== null
            ? (cell.atmfVolChange > 0 ? 'text-red-400' : cell.atmfVolChange < 0 ? 'text-green-400' : 'text-slate-300')
            : 'text-slate-500'}
        />
        <Row
          label="Premium"
          value={cell.atmfPremium !== null
            ? `${formatPremium(cell.atmfPremium)} / 100mm (${cell.atmfPremiumBps?.toFixed(1) ?? '—'} bps)`
            : '—'}
        />
        <Row label="Source" value={sourceLabel(cell.atmfVolSource)} />
        <Row label="Confidence" value={cell.atmfVolConfidence.toFixed(2)} />

        <div className="border-t border-slate-700/50 my-1.5" />

        <Row label="Last print" value={formatTimestamp(cell.atmfVolChangeTime)} />
        <Row label="Staleness" value={cell.staleness >= 0 ? formatStaleness(cell.staleness) : 'no data'} />
        <Row label="Obs today" value={String(cell.observationCount)} />

        {/* Last observation details */}
        {cell.lastObservation && (
          <>
            <div className="border-t border-slate-700/50 my-1.5" />
            <Row
              label="Trade"
              value={`${cell.lastObservation.platform} ${formatNotional(cell.lastObservation.notional)} ${cell.lastObservation.packageType.toLowerCase()} at ${cell.lastObservation.bpvolYr.toFixed(1)}bp`}
            />
          </>
        )}

        {/* Propagation info */}
        {cell.lastPropagatedFrom && cell.atmfVolSource === 'propagated' && (
          <>
            <div className="border-t border-slate-700/50 my-1.5" />
            <Row label="Propagated from" value={cell.lastPropagatedFrom} />
          </>
        )}
      </div>
    </div>
  )
}

function Row({ label, value, valueClass = 'text-slate-200' }: {
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500">{label}:</span>
      <span className={valueClass}>{value}</span>
    </div>
  )
}
