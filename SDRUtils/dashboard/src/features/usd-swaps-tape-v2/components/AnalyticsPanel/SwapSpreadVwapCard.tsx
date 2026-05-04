'use client'
// ABOUTME: Per-Bloomberg-ticker daily VWAP card for USD swap spreads
// (USSFCT2/5/10/30) and outright SOFR OIS (USSO5/10/30) — design-doc
// §5.6 + §5.15 + Clarus's "Swapalypse Now" pattern. Renders headline
// VWAP + 30-day mini-sparkline per ticker; click-through to drill into
// the underlying tape rows is wired via onTickerClick.
import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import type { UsdSwapTapeRow } from '../../types'
import {
  ALL_TICKERS,
  SWAP_SPREAD_TICKERS,
  USD_OIS_TICKERS,
  computeDailyVwap,
  type DailyVwapPoint,
} from '../../utils/swapSpreadVwap'

type TickerGroup = 'spreads' | 'ois'

function formatBps(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return `${value.toFixed(1)} bps`
}

function MiniSparkline({
  points,
  width = 120,
  height = 24,
}: {
  points: DailyVwapPoint[]
  width?: number
  height?: number
}): JSX.Element {
  if (points.length === 0) {
    return (
      <div
        className="text-[10px] text-slate-500"
        style={{ width, height, lineHeight: `${height}px` }}
      >
        no prints
      </div>
    )
  }
  const ys = points.map((p) => p.vwapBps)
  const min = Math.min(...ys)
  const max = Math.max(...ys)
  const range = max - min === 0 ? 1 : max - min
  const padX = 2
  const padY = 2
  const innerW = width - padX * 2
  const innerH = height - padY * 2
  const x = (i: number): number =>
    points.length <= 1 ? padX + innerW / 2 : padX + (i / (points.length - 1)) * innerW
  const y = (v: number): number => padY + innerH - ((v - min) / range) * innerH
  const path = ys
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(2)} ${y(v).toFixed(2)}`)
    .join(' ')
  return (
    <svg
      role="img"
      aria-label={`VWAP sparkline (${points.length} days)`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="rounded bg-slate-900"
    >
      <path d={path} fill="none" stroke="#a78bfa" strokeWidth={1.4} />
    </svg>
  )
}

export interface SwapSpreadVwapCardProps {
  rows: readonly UsdSwapTapeRow[]
  /** Trailing days of history to render in each sparkline. */
  windowDays?: number
  onTickerClick?: (ticker: string) => void
}

export function SwapSpreadVwapCard(props: SwapSpreadVwapCardProps): JSX.Element {
  const windowDays = props.windowDays ?? 30
  const [group, setGroup] = useState<TickerGroup>('spreads')
  const tickers = group === 'spreads' ? SWAP_SPREAD_TICKERS : USD_OIS_TICKERS

  const seriesByTicker = useMemo(() => {
    const out = new Map<string, DailyVwapPoint[]>()
    for (const t of ALL_TICKERS) {
      const all = computeDailyVwap(props.rows, t.ticker)
      out.set(t.ticker, all.slice(-windowDays))
    }
    return out
  }, [props.rows, windowDays])

  return (
    <div
      data-testid="swap-spread-vwap-card"
      className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300"
    >
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          {group === 'spreads' ? 'USD swap spreads (VWAP)' : 'USD SOFR OIS outright (VWAP)'}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setGroup('spreads')}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              group === 'spreads'
                ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                : 'border-slate-700 text-slate-400 hover:border-slate-500'
            }`}
          >
            Spreads
          </button>
          <button
            type="button"
            onClick={() => setGroup('ois')}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              group === 'ois'
                ? 'border-indigo-400 bg-indigo-500/20 text-indigo-200'
                : 'border-slate-700 text-slate-400 hover:border-slate-500'
            }`}
          >
            OIS
          </button>
        </div>
      </div>
      <table className="w-full table-auto border-separate border-spacing-y-1">
        <thead>
          <tr className="text-[9.5px] uppercase tracking-wider text-slate-500">
            <th className="text-left">Ticker</th>
            <th className="text-right">Latest VWAP</th>
            <th className="text-left">{windowDays}d trail</th>
            <th className="text-right">Days</th>
          </tr>
        </thead>
        <tbody>
          {tickers.map((spec) => {
            const series = seriesByTicker.get(spec.ticker) ?? []
            const latest = series.length > 0 ? series[series.length - 1] : null
            const onClick = props.onTickerClick
              ? () => props.onTickerClick?.(spec.ticker)
              : undefined
            return (
              <tr
                key={spec.ticker}
                title={spec.label}
                className={onClick ? 'cursor-pointer hover:bg-slate-900/40' : ''}
                onClick={onClick}
              >
                <td className="text-left text-slate-200">{spec.ticker}</td>
                <td className="text-right tabular-nums text-slate-100">
                  {latest ? formatBps(latest.vwapBps) : '—'}
                </td>
                <td className="text-left">
                  <MiniSparkline points={series} />
                </td>
                <td className="text-right tabular-nums text-slate-500">{series.length}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
