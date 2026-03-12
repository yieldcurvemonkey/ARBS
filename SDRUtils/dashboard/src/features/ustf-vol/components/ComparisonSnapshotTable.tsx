'use client'

import { formatSignedNumber, formatSnapshotDate, formatVol } from '../utils'
import { useUstfComparisonSnapshot } from '../hooks/useUstfComparisonSnapshot'

function getSpreadTone(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return 'text-slate-400'
  }

  if (value > 0) {
    return 'text-emerald-300'
  }

  if (value < 0) {
    return 'text-rose-300'
  }

  return 'text-slate-100'
}

function getZScoreTone(value: number | null): string {
  if (value === null || !Number.isFinite(value)) {
    return 'text-slate-400'
  }

  if (Math.abs(value) >= 1.5) {
    return 'text-amber-300'
  }

  return 'text-slate-200'
}

function LoadingRows() {
  return (
    <>
      {Array.from({ length: 6 }).map((_, index) => (
        <tr key={index} className="border-b border-slate-800/80 last:border-b-0">
          <td className="px-3 py-3">
            <div className="h-3 w-28 animate-pulse rounded bg-slate-800" />
            <div className="mt-2 h-2.5 w-40 animate-pulse rounded bg-slate-900" />
          </td>
          {Array.from({ length: 5 }).map((__, cellIndex) => (
            <td key={cellIndex} className="px-3 py-3 text-right">
              <div className="ml-auto h-3 w-14 animate-pulse rounded bg-slate-800" />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

export function ComparisonSnapshotTable() {
  const { data, loading, error } = useUstfComparisonSnapshot()
  const rows = data?.rows ?? []

  return (
    <section className="overflow-hidden rounded-xl border border-slate-700/80 bg-[linear-gradient(180deg,rgba(15,23,42,0.96),rgba(2,6,23,0.98))] shadow-[0_18px_40px_rgba(2,6,23,0.28)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/80 bg-slate-900/95 px-4 py-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.24em] text-slate-500">
            Snapshot
          </div>
          <div className="mt-1 text-sm font-semibold text-slate-100">
            OTC vs listed implied vol sheet
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          <span>Units bpvol</span>
          <span>Spread listed - otc</span>
          <span>Updated {formatSnapshotDate(data?.latestUpdatedAt ?? null)}</span>
        </div>
      </div>

      {error ? (
        <div className="border-t border-rose-900/50 bg-rose-950/40 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left text-xs text-slate-300">
            <thead className="bg-slate-950/80">
              <tr className="border-b border-slate-800/80">
                <th className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Pair
                </th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  As of
                </th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Listed
                </th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  OTC
                </th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Spread
                </th>
                <th className="px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Z
                </th>
              </tr>
            </thead>

            <tbody className="bg-slate-950/30 font-mono tabular-nums">
              {loading ? (
                <LoadingRows />
              ) : (
                rows.map((row) => (
                  <tr
                    key={row.pairLabel}
                    className="border-b border-slate-800/80 transition hover:bg-slate-900/50 last:border-b-0"
                  >
                    <td className="px-3 py-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-100">
                        {row.pairLabel}
                      </div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        {row.listedLabel} vs {row.otcLabel}
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right text-slate-300">
                      {formatSnapshotDate(row.asOfDate)}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-100">
                      {formatVol(row.listedVol)}
                    </td>
                    <td className="px-3 py-3 text-right text-slate-100">
                      {formatVol(row.otcVol)}
                    </td>
                    <td className={`px-3 py-3 text-right ${getSpreadTone(row.spread)}`}>
                      {formatSignedNumber(row.spread)}
                    </td>
                    <td className={`px-3 py-3 text-right ${getZScoreTone(row.spreadZScore)}`}>
                      {formatSignedNumber(row.spreadZScore, 2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
