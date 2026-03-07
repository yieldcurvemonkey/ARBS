'use client'

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts'
import type {
  CellDetailResponse,
  VolGridCell,
  VolGridSessionMeta
} from '../types'

type CellDetailPanelProps = {
  cell: VolGridCell | null
  detail: CellDetailResponse | null
  loading: boolean
  error: string | null
  session: VolGridSessionMeta | null
  onClose: () => void
}

function formatNumber(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

function formatChange(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(1)}`
}

function formatNotional(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${(value / 1_000_000).toFixed(0)}mm`
}

function formatTimestamp(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

export function CellDetailPanel({
  cell,
  detail,
  loading,
  error,
  session,
  onClose
}: CellDetailPanelProps) {
  if (!cell) return null
  const isClosingView = session?.isClosingView ?? false

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/50 backdrop-blur-sm">
      <button
        aria-label="Close cell detail"
        className="flex-1"
        onClick={onClose}
      />
      <div className="relative h-full w-full max-w-xl overflow-y-auto border-l border-slate-800 bg-slate-950 shadow-2xl">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-slate-800 bg-slate-950/95 px-6 py-5 backdrop-blur">
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-slate-500">
              Node Detail
            </div>
            <h2 className="mt-1 text-2xl font-semibold text-white">
              {cell.expiry} x {cell.tenor}
            </h2>
            <div className="mt-1 text-sm text-slate-400">
              {isClosingView ? 'Close' : 'Live'} {formatNumber(cell.atmfVol)} bpvol, confidence{' '}
              {(cell.atmfVolConfidence * 100).toFixed(0)}%
            </div>
            {cell.comparisonVol !== null && (
              <div className="mt-1 text-xs text-slate-400">
                MDP close {formatNumber(cell.comparisonVol)} bpvol, basis{' '}
                {formatChange(cell.comparisonDiff)}
              </div>
            )}
            {session?.label && (
              <div className="mt-1 text-xs text-slate-500">{session.label}</div>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-slate-500"
          >
            Close
          </button>
        </div>

        <div className="space-y-6 px-6 py-6">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Volume
              </div>
              <div className="mt-2 text-2xl font-semibold text-white">
                {detail?.volumeStats.tradeCount1w ?? 0}
              </div>
              <div className="text-xs text-slate-400">1-week mapped prints</div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Regime
              </div>
              <div className="mt-2 text-2xl font-semibold text-white">
                {detail?.technicalSignals.regimeLabel ?? '--'}
              </div>
              <div className="text-xs text-slate-400">
                MA {detail?.technicalSignals.maShortVsLong ?? '--'}, autocorr{' '}
                {formatNumber(detail?.technicalSignals.autocorrelation1d ?? null, 2)}
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-100">
                Historical NVOL
              </h3>
              <div className="text-xs text-slate-500">
                {detail?.timeseries.length ?? 0} sessions
              </div>
            </div>
            {loading && <div className="text-sm text-slate-400">Loading...</div>}
            {error && <div className="text-sm text-rose-400">{error}</div>}
            {!loading && !error && (detail?.timeseries.length ?? 0) > 0 && (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={detail?.timeseries}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="date" stroke="#64748b" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#64748b" tick={{ fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#020617',
                        borderColor: '#334155',
                        color: '#e2e8f0'
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="nvol"
                      stroke="#f59e0b"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {!loading && !error && (detail?.timeseries.length ?? 0) === 0 && (
              <div className="text-sm text-slate-500">No EOD history available.</div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Avg Notional 1W
              </div>
              <div className="mt-2 text-xl font-semibold text-white">
                {formatNotional(detail?.volumeStats.avgNotional1w ?? null)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Total Notional 1W
              </div>
              <div className="mt-2 text-xl font-semibold text-white">
                {formatNotional(detail?.volumeStats.totalNotional1w ?? null)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Last Trade
              </div>
              <div className="mt-2 text-xl font-semibold text-white">
                {detail?.volumeStats.lastTradeDate ?? '--'}
              </div>
              <div className="text-xs text-slate-400">
                {detail?.volumeStats.daysSinceLastTrade ?? '--'} days ago
              </div>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Rarity
              </div>
              <div className="mt-2 text-xl font-semibold text-white">
                {formatNumber(detail?.volumeStats.rarityPercentile ?? null, 0)}%
              </div>
              <div className="text-xs text-slate-400">
                Higher means this node is quieter than peers.
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Recent SDR Trades</h3>
            <div className="mt-3 space-y-2">
              {(detail?.recentTrades ?? []).length === 0 && (
                <div className="text-sm text-slate-500">No recent mapped trades.</div>
              )}
              {(detail?.recentTrades ?? []).slice(0, 10).map((trade) => (
                <div
                  key={`${trade.packageId}-${trade.executionTimestamp}`}
                  className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2"
                >
                  <div>
                    <div className="text-sm font-medium text-slate-100">
                      {trade.tradeLabel}
                    </div>
                    <div className="text-xs text-slate-400">
                      {formatTimestamp(trade.executionTimestamp)} ET, {trade.platform ?? '--'}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold text-white">
                      {formatNumber(trade.bpvolYr)}
                    </div>
                    <div className="text-xs text-slate-400">
                      {formatNotional(trade.notional)}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
