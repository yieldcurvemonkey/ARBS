// ABOUTME: Client component for the curve explorer — fetches and displays curve inventory from Supabase with granular drill-down.
'use client'

import { useCallback, useEffect, useState } from 'react'

type View = 'overview' | 'snapshots' | 'intraday' | 'analytics' | 'snapshot-detail'

interface OverviewRow {
  curve_name: string
  snapshot_days: number
  total_snapshots: number
  intraday_days: number
  analytics_days: number
  date_min: string | null
  date_max: string | null
}

interface SnapshotRow {
  curve_name: string
  trading_date: string
  snapshot_count: number
  earliest_utc: string
  latest_utc: string
  tags: string[]
}

interface BlockRow {
  curve_name: string
  trading_date: string
  row_count: number
  data_format: string
  sha256: string
  created_at: string
}

interface SnapshotDetailRow {
  curve_name: string
  timestamp_utc: string
  trading_date: string
  session_minute: number
  tags: string[]
  cfg_hash: string
  reference_key: string
  interpolation: string
  source_variant: string
  node_count: number
  node_date_min: string | null
  node_date_max: string | null
  node_dates: string[]
  discount_factors: number[]
  created_at: string
}

const VIEW_LABELS: Record<View, string> = {
  overview: 'Overview',
  snapshots: 'Tagged Snapshots',
  intraday: 'Intraday Blocks',
  analytics: 'Analytics Blocks',
  'snapshot-detail': 'Snapshot Detail',
}

export default function CurveExplorer() {
  const [view, setView] = useState<View>('overview')
  const [curveFilter, setCurveFilter] = useState('')
  const [dateFilter, setDateFilter] = useState('')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ view })
      if (curveFilter) params.set('curve_name', curveFilter)
      if (dateFilter && view === 'snapshot-detail') params.set('trading_date', dateFilter)
      const res = await fetch(`/api/curve-explorer?${params}`)
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.error || `HTTP ${res.status}`)
      }
      const json = await res.json()
      setData(json.rows || [])
    } catch (err: any) {
      setError(err.message)
      setData([])
    } finally {
      setLoading(false)
    }
  }, [view, curveFilter, dateFilter])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const drillInto = (curveName: string, targetView: View, tradingDate?: string) => {
    setCurveFilter(curveName)
    setDateFilter(tradingDate || '')
    setView(targetView)
  }

  // Breadcrumb navigation
  const goBack = () => {
    if (view === 'snapshot-detail') {
      setDateFilter('')
      setView('snapshots')
    } else if (view !== 'overview') {
      setCurveFilter('')
      setDateFilter('')
      setView('overview')
    }
  }

  // Which tabs to show in the nav (hide snapshot-detail from top tabs)
  const navViews: View[] = ['overview', 'snapshots', 'intraday', 'analytics']

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Curve Store Explorer</h1>
        <button
          onClick={fetchData}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Breadcrumb */}
      {(curveFilter || dateFilter) && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <button onClick={() => { setCurveFilter(''); setDateFilter(''); setView('overview') }} className="text-blue-400 hover:text-blue-300">
            All Curves
          </button>
          {curveFilter && (
            <>
              <span className="text-slate-600">/</span>
              <button
                onClick={() => { setDateFilter(''); setView('snapshots') }}
                className={dateFilter ? 'text-blue-400 hover:text-blue-300' : 'text-slate-200 font-semibold'}
              >
                <span className="font-mono">{curveFilter}</span>
              </button>
            </>
          )}
          {dateFilter && (
            <>
              <span className="text-slate-600">/</span>
              <span className="font-mono font-semibold text-slate-200">{dateFilter}</span>
            </>
          )}
        </div>
      )}

      {/* View tabs */}
      <div className="flex items-center gap-2">
        {navViews.map((v) => (
          <button
            key={v}
            onClick={() => { setView(v); setDateFilter(''); if (v === 'overview') setCurveFilter('') }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              (view === v || (view === 'snapshot-detail' && v === 'snapshots'))
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            {VIEW_LABELS[v]}
          </button>
        ))}

        {curveFilter && (
          <div className="ml-4 flex items-center gap-2 rounded-lg bg-blue-950/50 px-3 py-1.5 text-xs text-blue-300">
            <span>Filtered: <span className="font-mono font-semibold">{curveFilter}</span></span>
            {dateFilter && <span className="text-blue-400">/ {dateFilter}</span>}
            <button
              onClick={() => { setCurveFilter(''); setDateFilter('') }}
              className="ml-1 text-blue-400 hover:text-white"
            >
              &times;
            </button>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 p-4 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/50">
        {view === 'overview' && <OverviewTable rows={data as OverviewRow[]} onDrill={drillInto} />}
        {view === 'snapshots' && <SnapshotsTable rows={data as SnapshotRow[]} onDrillDetail={drillInto} />}
        {view === 'intraday' && <BlocksTable rows={data as BlockRow[]} kind="intraday" />}
        {view === 'analytics' && <BlocksTable rows={data as BlockRow[]} kind="analytics" />}
        {view === 'snapshot-detail' && <SnapshotDetailTable rows={data as SnapshotDetailRow[]} onBack={goBack} />}
      </div>

      {!loading && data.length === 0 && !error && (
        <p className="text-center text-sm text-slate-500">No data found.</p>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */

function OverviewTable({ rows, onDrill }: { rows: OverviewRow[]; onDrill: (name: string, view: View) => void }) {
  if (!rows.length) return null
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Curve</th>
          <th className="px-4 py-3 text-right">Snapshot Days</th>
          <th className="px-4 py-3 text-right">Total Snapshots</th>
          <th className="px-4 py-3 text-right">Intraday Days</th>
          <th className="px-4 py-3 text-right">Analytics Days</th>
          <th className="px-4 py-3">Date Range</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.curve_name} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
            <td className="px-4 py-2.5 font-mono font-semibold text-emerald-400">{r.curve_name}</td>
            <td className="px-4 py-2.5 text-right">
              <DrillButton value={r.snapshot_days} onClick={() => onDrill(r.curve_name, 'snapshots')} />
            </td>
            <td className="px-4 py-2.5 text-right text-slate-300">{r.total_snapshots.toLocaleString()}</td>
            <td className="px-4 py-2.5 text-right">
              <DrillButton value={r.intraday_days} onClick={() => onDrill(r.curve_name, 'intraday')} />
            </td>
            <td className="px-4 py-2.5 text-right">
              <DrillButton value={r.analytics_days} onClick={() => onDrill(r.curve_name, 'analytics')} />
            </td>
            <td className="px-4 py-2.5 text-slate-400">
              {r.date_min && r.date_max ? `${r.date_min} → ${r.date_max}` : '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DrillButton({ value, onClick }: { value: number; onClick: () => void }) {
  if (value === 0) return <span className="text-slate-600">0</span>
  return (
    <button
      onClick={onClick}
      className="text-blue-400 underline decoration-blue-400/30 underline-offset-2 transition hover:text-blue-300 hover:decoration-blue-300"
    >
      {value.toLocaleString()}
    </button>
  )
}

function SnapshotsTable({ rows, onDrillDetail }: { rows: SnapshotRow[]; onDrillDetail: (name: string, view: View, date?: string) => void }) {
  if (!rows.length) return null
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Curve</th>
          <th className="px-4 py-3">Trading Date</th>
          <th className="px-4 py-3 text-right">Snapshots</th>
          <th className="px-4 py-3">Earliest (UTC)</th>
          <th className="px-4 py-3">Latest (UTC)</th>
          <th className="px-4 py-3">Tags</th>
          <th className="px-4 py-3"></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.curve_name}-${r.trading_date}-${i}`} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
            <td className="px-4 py-2.5 font-mono text-emerald-400">{r.curve_name}</td>
            <td className="px-4 py-2.5 font-mono text-slate-300">{r.trading_date}</td>
            <td className="px-4 py-2.5 text-right">
              <button
                onClick={() => onDrillDetail(r.curve_name, 'snapshot-detail', r.trading_date)}
                className="text-blue-400 underline decoration-blue-400/30 underline-offset-2 transition hover:text-blue-300"
              >
                {r.snapshot_count}
              </button>
            </td>
            <td className="px-4 py-2.5 text-xs text-slate-400">{formatTs(r.earliest_utc)}</td>
            <td className="px-4 py-2.5 text-xs text-slate-400">{formatTs(r.latest_utc)}</td>
            <td className="px-4 py-2.5">
              <div className="flex flex-wrap gap-1">
                {(r.tags || []).map((t) => (
                  <span key={t} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tagColor(t)}`}>
                    {t}
                  </span>
                ))}
              </div>
            </td>
            <td className="px-4 py-2.5">
              <button
                onClick={() => onDrillDetail(r.curve_name, 'snapshot-detail', r.trading_date)}
                className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400 transition hover:border-slate-500 hover:text-white"
              >
                Details &rarr;
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function BlocksTable({ rows, kind }: { rows: BlockRow[]; kind: 'intraday' | 'analytics' }) {
  if (!rows.length) return null
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Curve</th>
          <th className="px-4 py-3">Trading Date</th>
          <th className="px-4 py-3 text-right">Rows</th>
          <th className="px-4 py-3">Format</th>
          <th className="px-4 py-3">SHA256</th>
          <th className="px-4 py-3">Created</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.curve_name}-${r.trading_date}-${i}`} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
            <td className="px-4 py-2.5 font-mono text-emerald-400">{r.curve_name}</td>
            <td className="px-4 py-2.5 font-mono text-slate-300">{r.trading_date}</td>
            <td className="px-4 py-2.5 text-right text-slate-300">{r.row_count.toLocaleString()}</td>
            <td className="px-4 py-2.5 text-xs text-slate-400">{r.data_format}</td>
            <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{r.sha256?.slice(0, 12)}...</td>
            <td className="px-4 py-2.5 text-xs text-slate-400">{formatTs(r.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/* -------------------------------------------------------------------------- */
/* Snapshot Detail — individual timestamps with expandable node data          */
/* -------------------------------------------------------------------------- */

function SnapshotDetailTable({ rows, onBack }: { rows: SnapshotDetailRow[]; onBack: () => void }) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (!rows.length) return null

  return (
    <div>
      {/* Summary bar */}
      <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/80 px-4 py-3">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="text-xs text-blue-400 hover:text-blue-300"
          >
            &larr; Back to snapshots
          </button>
          <span className="text-xs text-slate-500">
            {rows.length} snapshot{rows.length !== 1 ? 's' : ''} found
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          {rows.length > 0 && (
            <>
              <span>Curve: <span className="font-mono text-emerald-400">{rows[0].curve_name}</span></span>
              <span>Date: <span className="font-mono text-slate-300">{rows[0].trading_date}</span></span>
            </>
          )}
        </div>
      </div>

      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
            <th className="w-8 px-2 py-3"></th>
            <th className="px-4 py-3">Timestamp (UTC)</th>
            <th className="px-4 py-3 text-right">Session Min</th>
            <th className="px-4 py-3">Tags</th>
            <th className="px-4 py-3 text-right">Nodes</th>
            <th className="px-4 py-3">Node Span</th>
            <th className="px-4 py-3">Interpolation</th>
            <th className="px-4 py-3">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const isExpanded = expandedIdx === i
            return (
              <SnapshotDetailRowComponent
                key={`${r.timestamp_utc}-${i}`}
                row={r}
                isExpanded={isExpanded}
                onToggle={() => setExpandedIdx(isExpanded ? null : i)}
              />
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SnapshotDetailRowComponent({
  row,
  isExpanded,
  onToggle,
}: {
  row: SnapshotDetailRow
  isExpanded: boolean
  onToggle: () => void
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b transition ${
          isExpanded
            ? 'border-blue-800/50 bg-blue-950/30'
            : 'border-slate-800/50 hover:bg-slate-800/40'
        }`}
      >
        <td className="px-2 py-2.5 text-center text-slate-500">
          <span className={`inline-block transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
            &#9654;
          </span>
        </td>
        <td className="px-4 py-2.5 font-mono text-sm text-slate-200">
          {formatTs(row.timestamp_utc)}
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-slate-400">
          {row.session_minute}
          <span className="ml-1 text-[10px] text-slate-600">
            ({formatSessionTime(row.session_minute)})
          </span>
        </td>
        <td className="px-4 py-2.5">
          <div className="flex flex-wrap gap-1">
            {(row.tags || []).map((t) => (
              <span key={t} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tagColor(t)}`}>
                {t}
              </span>
            ))}
          </div>
        </td>
        <td className="px-4 py-2.5 text-right font-mono text-slate-300">
          {row.node_count}
        </td>
        <td className="px-4 py-2.5 text-xs text-slate-400">
          {row.node_date_min && row.node_date_max
            ? `${row.node_date_min} → ${row.node_date_max}`
            : '—'}
        </td>
        <td className="px-4 py-2.5 text-xs text-slate-400">{row.interpolation}</td>
        <td className="px-4 py-2.5 text-xs text-slate-500">{row.source_variant || '—'}</td>
      </tr>

      {/* Expanded: node_dates + discount_factors */}
      {isExpanded && (
        <tr className="border-b border-blue-800/30 bg-blue-950/20">
          <td colSpan={8} className="px-4 py-4">
            <NodeDataPanel row={row} />
          </td>
        </tr>
      )}
    </>
  )
}

function NodeDataPanel({ row }: { row: SnapshotDetailRow }) {
  const nodes = row.node_dates || []
  const dfs = row.discount_factors || []
  const pairs = nodes.map((d, i) => ({ date: d, df: dfs[i] }))

  return (
    <div className="space-y-3">
      {/* Metadata row */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
        <span className="text-slate-500">cfg_hash: <span className="font-mono text-slate-400">{row.cfg_hash || '—'}</span></span>
        <span className="text-slate-500">reference_key: <span className="font-mono text-slate-400">{row.reference_key || '—'}</span></span>
        <span className="text-slate-500">created: <span className="text-slate-400">{formatTs(row.created_at)}</span></span>
      </div>

      {/* Node table */}
      <div className="max-h-80 overflow-auto rounded-lg border border-slate-800 bg-slate-900/80">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-slate-900">
            <tr className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-600">
              <th className="px-3 py-2 text-right">#</th>
              <th className="px-3 py-2">Node Date</th>
              <th className="px-3 py-2 text-right">Discount Factor</th>
              <th className="px-3 py-2 text-right">Tenor (approx)</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((p, i) => {
              const tenorYears = approximateTenor(row.node_date_min, p.date)
              return (
                <tr key={i} className="border-b border-slate-800/30 hover:bg-slate-800/30">
                  <td className="px-3 py-1.5 text-right text-slate-600">{i + 1}</td>
                  <td className="px-3 py-1.5 font-mono text-slate-300">{p.date}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-slate-200">{p.df?.toFixed(10)}</td>
                  <td className="px-3 py-1.5 text-right text-slate-500">{tenorYears}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="text-[10px] text-slate-600">
        {pairs.length} nodes &middot; Click row to collapse
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

function formatTs(ts: string | null): string {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z'
  } catch {
    return ts
  }
}

function tagColor(tag: string): string {
  if (tag === 'EOD') return 'bg-amber-900/60 text-amber-300'
  if (tag === 'OPEN') return 'bg-green-900/60 text-green-300'
  if (tag === 'SETTLE') return 'bg-purple-900/60 text-purple-300'
  if (tag === 'FIX') return 'bg-cyan-900/60 text-cyan-300'
  return 'bg-slate-800 text-slate-300'
}

function formatSessionTime(sessionMinute: number): string {
  // session_minute = minutes since 06:00 CT
  const totalMinutes = 6 * 60 + sessionMinute
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  const h12 = h > 12 ? h - 12 : h === 0 ? 12 : h
  const ampm = h >= 12 ? 'PM' : 'AM'
  return `${h12}:${m.toString().padStart(2, '0')} ${ampm} CT`
}

function approximateTenor(baseDate: string | null, nodeDate: string): string {
  if (!baseDate) return '—'
  try {
    const base = new Date(baseDate)
    const node = new Date(nodeDate)
    const diffDays = (node.getTime() - base.getTime()) / (1000 * 60 * 60 * 24)
    if (diffDays <= 0) return '0D'
    if (diffDays < 30) return `${Math.round(diffDays)}D`
    if (diffDays < 365) return `${Math.round(diffDays / 30.44)}M`
    const years = diffDays / 365.25
    return years >= 10 ? `${Math.round(years)}Y` : `${years.toFixed(1)}Y`
  } catch {
    return '—'
  }
}
