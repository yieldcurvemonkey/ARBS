// ABOUTME: Live calibration feed panel showing qualifying trades that feed the vol surface.
'use client'

import { CalibrationObservation } from '../types'

type Props = {
  trades: CalibrationObservation[]
  filteredOutCount: number
}

function formatTime(epoch: number): string {
  return new Date(epoch).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'America/New_York',
  })
}

function formatNotional(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}bn`
  if (n >= 1e6) return `${(n / 1e6).toFixed(0)}mm`
  return `${(n / 1e3).toFixed(0)}k`
}

export function CalibrationFeed({ trades, filteredOutCount }: Props) {
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg overflow-hidden">
      <div className="px-3 py-2 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
          Calibration Feed
        </h3>
        <span className="text-[10px] text-slate-500">
          {trades.length} qualifying &middot; {filteredOutCount} filtered out
        </span>
      </div>
      <div className="max-h-[240px] overflow-y-auto">
        {trades.length === 0 ? (
          <div className="px-3 py-4 text-xs text-slate-600 text-center">
            No qualifying calibration trades
          </div>
        ) : (
          <table className="w-full text-[11px] font-mono">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800/50">
                <th className="px-2 py-1 text-left font-normal">Time</th>
                <th className="px-2 py-1 text-left font-normal">Bucket</th>
                <th className="px-2 py-1 text-left font-normal">Type</th>
                <th className="px-2 py-1 text-right font-normal">Notional</th>
                <th className="px-2 py-1 text-left font-normal">Platform</th>
                <th className="px-2 py-1 text-right font-normal">Vol (bp)</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade, idx) => (
                <tr
                  key={trade.packageId}
                  className={`border-b border-slate-800/30 hover:bg-slate-800/40 ${idx === 0 ? 'bg-blue-900/10' : ''}`}
                >
                  <td className="px-2 py-1 text-slate-400">{formatTime(trade.executionTimestamp)}</td>
                  <td className="px-2 py-1 text-slate-200">{trade.tradeLabel}</td>
                  <td className="px-2 py-1 text-slate-400">{trade.packageType}</td>
                  <td className="px-2 py-1 text-right text-slate-300">{formatNotional(trade.notional)}</td>
                  <td className="px-2 py-1 text-slate-400">{trade.platform}</td>
                  <td className="px-2 py-1 text-right text-slate-200 font-medium">{trade.bpvolYr.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
