// ABOUTME: Client component for the curve explorer — fetches and displays curve inventory from Supabase.
'use client'

import { useCallback, useEffect, useState } from 'react'

type View = 'overview' | 'snapshots' | 'intraday' | 'analytics'

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

const VIEW_LABELS: Record<View, string> = {
  overview: 'Overview',
  snapshots: 'Tagged Snapshots',
  intraday: 'Intraday Blocks',
  analytics: 'Analytics Blocks',
}

export default function CurveExplorer() {
  const [view, setView] = useState<View>('overview')
  const [curveFilter, setCurveFilter] = useState('')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ view })
      if (curveFilter) params.set('curve_name', curveFilter)
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
  }, [view, curveFilter])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const drillInto = (curveName: string, targetView: View) => {
    setCurveFilter(curveName)
    setView(targetView)
  }

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

      {/* View tabs */}
      <div className="flex items-center gap-2">
        {(Object.keys(VIEW_LABELS) as View[]).map((v) => (
          <button
            key={v}
            onClick={() => { setView(v); if (v === 'overview') setCurveFilter('') }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              view === v
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
            <button
              onClick={() => setCurveFilter('')}
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
        {view === 'snapshots' && <SnapshotsTable rows={data as SnapshotRow[]} />}
        {view === 'intraday' && <BlocksTable rows={data as BlockRow[]} kind="intraday" />}
        {view === 'analytics' && <BlocksTable rows={data as BlockRow[]} kind="analytics" />}
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

function SnapshotsTable({ rows }: { rows: SnapshotRow[] }) {
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
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.curve_name}-${r.trading_date}-${i}`} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
            <td className="px-4 py-2.5 font-mono text-emerald-400">{r.curve_name}</td>
            <td className="px-4 py-2.5 font-mono text-slate-300">{r.trading_date}</td>
            <td className="px-4 py-2.5 text-right text-slate-300">{r.snapshot_count}</td>
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
  return 'bg-slate-800 text-slate-300'
}
