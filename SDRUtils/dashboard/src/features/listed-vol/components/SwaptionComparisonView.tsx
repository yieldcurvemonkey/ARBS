'use client'

import type { ListedVolComparisonRow } from '../types'
import { formatRatio, formatSigned, formatVol } from '../utils'

type SwaptionComparisonViewProps = {
  rows: ListedVolComparisonRow[]
}

export function SwaptionComparisonView({
  rows
}: SwaptionComparisonViewProps) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/70">
      <div className="border-b border-slate-800 px-5 py-4">
        <h3 className="text-base font-semibold text-white">Swaption vs Listed</h3>
        <p className="mt-1 text-sm text-slate-400">
          Matched expiry buckets versus mapped OTC swaption tenor.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/60 text-left text-xs uppercase tracking-[0.16em] text-slate-400">
              <th className="px-4 py-3">Expiry</th>
              <th className="px-4 py-3">Listed</th>
              <th className="px-4 py-3">Swaption</th>
              <th className="px-4 py-3">Ratio</th>
              <th className="px-4 py-3">Diff</th>
              <th className="px-4 py-3">Map</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.expiryLabel} className="border-b border-slate-900/80 text-sm text-slate-200 last:border-b-0">
                <td className="px-4 py-3 font-semibold">{row.expiryLabel}</td>
                <td className="px-4 py-3 tabular-nums">{formatVol(row.listedAtmNvolBps)}</td>
                <td className="px-4 py-3 tabular-nums">{formatVol(row.swaptionAtmfNvolBps)}</td>
                <td className="px-4 py-3 tabular-nums">{formatRatio(row.volRatio)}</td>
                <td className="px-4 py-3 tabular-nums">{formatSigned(row.volDiffBps)}</td>
                <td className="px-4 py-3 text-slate-400">
                  {row.swaptionExpiryLabel ?? '--'} x {row.swaptionTenorLabel ?? '--'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
