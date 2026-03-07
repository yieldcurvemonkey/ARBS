'use client'

import { Dialog } from '@/components/ui/Dialog/Dialog'
import type {
  CalibrationObservation,
  CellDetailResponse,
  VolGridCell,
  VolGridSessionMeta
} from '../types'
import {
  formatChange,
  formatConfidence,
  formatNotional,
  formatNumber,
  formatTime,
  formatTimestamp
} from '../utils'
import { PlotlyNvolChart } from './PlotlyNvolChart'

type CellAnalyticsModalProps = {
  cell: VolGridCell | null
  detail: CellDetailResponse | null
  loading: boolean
  error: string | null
  session: VolGridSessionMeta | null
  onClose: () => void
}

function StatCard({
  label,
  value,
  unit,
  subtitle,
  colored
}: {
  label: string
  value: string
  unit?: string
  subtitle?: string
  colored?: boolean
}) {
  const colorClass = colored
    ? value.startsWith('+')
      ? 'text-red-400'
      : value.startsWith('-')
        ? 'text-emerald-400'
        : 'text-white'
    : 'text-white'

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-3">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${colorClass}`}>
        {value}
        {unit && <span className="ml-1 text-xs text-slate-400">{unit}</span>}
      </div>
      {subtitle && <div className="mt-0.5 text-[10px] text-slate-400">{subtitle}</div>}
    </div>
  )
}

function TradeRow({ trade }: { trade: CalibrationObservation }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <div>
        <div className="text-sm font-medium text-slate-100">{trade.tradeLabel}</div>
        <div className="text-xs text-slate-400">
          {formatTimestamp(trade.executionTimestamp)} ET, {trade.platform ?? '--'}
        </div>
      </div>
      <div className="text-right">
        <div className="text-sm font-semibold text-white">
          {formatNumber(trade.bpvolYr)}
        </div>
        <div className="text-xs text-slate-400">{formatNotional(trade.notional)}</div>
      </div>
    </div>
  )
}

export function CellAnalyticsModal({
  cell,
  detail,
  loading,
  error,
  session,
  onClose
}: CellAnalyticsModalProps) {
  if (!cell) return null
  const isClosingView = session?.isClosingView ?? false

  return (
    <Dialog
      isOpen={!!cell}
      onClose={onClose}
      size="5xl"
      title={`${cell.expiry} x ${cell.tenor} — Node Analytics`}
    >
      <div className="space-y-6">
        {/* Header Stats */}
        <div className="grid gap-3 sm:grid-cols-4">
          <StatCard
            label="ATMF Vol"
            value={formatNumber(cell.atmfVol)}
            unit="bpvol"
            subtitle={isClosingView ? 'Close' : 'Live'}
          />
          <StatCard
            label="Confidence"
            value={formatConfidence(cell.atmfVolConfidence)}
            subtitle={`Source: ${cell.atmfVolSource}`}
          />
          <StatCard
            label="1d Change"
            value={formatChange(cell.atmfVolChange)}
            colored
          />
          <StatCard
            label="Regime"
            value={cell.regimeLabel ?? '--'}
          />
        </div>

        {cell.comparisonVol !== null && (
          <div className="text-xs text-slate-400">
            MDP close {formatNumber(cell.comparisonVol)} bpvol, basis{' '}
            {formatChange(cell.comparisonDiff)}
          </div>
        )}

        {/* Plotly NVOL Timeseries Chart */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-100">Historical NVOL</h3>
            <div className="text-xs text-slate-500">
              {detail?.timeseries.length ?? 0} sessions
            </div>
          </div>
          {loading && <div className="text-sm text-slate-400">Loading timeseries...</div>}
          {error && <div className="text-sm text-rose-400">{error}</div>}
          {!loading && !error && detail && detail.timeseries.length > 0 && (
            <PlotlyNvolChart
              timeseries={detail.timeseries}
              title={`${cell.expiry}x${cell.tenor} Historical NVOL`}
              height={380}
            />
          )}
          {!loading && !error && (detail?.timeseries.length ?? 0) === 0 && (
            <div className="text-sm text-slate-500">No EOD history available.</div>
          )}
        </div>

        {/* Volume Stats */}
        <div className="grid gap-3 sm:grid-cols-4">
          <StatCard
            label="1W Trade Count"
            value={String(detail?.volumeStats.tradeCount1w ?? 0)}
          />
          <StatCard
            label="Avg Notional 1W"
            value={formatNotional(detail?.volumeStats.avgNotional1w ?? null)}
          />
          <StatCard
            label="Total Notional 1W"
            value={formatNotional(detail?.volumeStats.totalNotional1w ?? null)}
          />
          <StatCard
            label="Rarity"
            value={`${formatNumber(detail?.volumeStats.rarityPercentile ?? null, 0)}%`}
            subtitle="Higher = quieter than peers"
          />
        </div>

        {/* Technical Signals */}
        <div className="grid gap-3 sm:grid-cols-2">
          <StatCard
            label="Technical Regime"
            value={detail?.technicalSignals.regimeLabel ?? '--'}
            subtitle={`MA ${detail?.technicalSignals.maShortVsLong ?? '--'}, autocorr ${formatNumber(detail?.technicalSignals.autocorrelation1d ?? null, 2)}`}
          />
          <StatCard
            label="Last Trade"
            value={detail?.volumeStats.lastTradeDate ?? '--'}
            subtitle={`${detail?.volumeStats.daysSinceLastTrade ?? '--'} days ago`}
          />
        </div>

        {/* Recent SDR Trades */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
          <h3 className="text-sm font-semibold text-slate-100">Recent SDR Trades</h3>
          <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
            {(detail?.recentTrades ?? []).length === 0 && (
              <div className="text-sm text-slate-500">No recent mapped trades.</div>
            )}
            {(detail?.recentTrades ?? []).slice(0, 15).map((trade) => (
              <TradeRow
                key={`${trade.packageId}-${trade.executionTimestamp}`}
                trade={trade}
              />
            ))}
          </div>
        </div>

        {/* Trade Rarity — future integration placeholder */}
        <div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/30 p-4 text-xs text-slate-500">
          Trade rarity analytics (percentile badges, distribution histograms, recency scorecard)
          will be integrated after API enhancements to provide TapeRow-compatible data for
          individual grid nodes.
        </div>
      </div>
    </Dialog>
  )
}
