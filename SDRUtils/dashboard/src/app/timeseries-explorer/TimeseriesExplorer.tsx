// ABOUTME: Client component for timeseries explorer — fetches and displays computed timeseries inventory from Supabase.
'use client'

import { useCallback, useEffect, useState } from 'react'

type View = 'overview' | 'rows' | 'blocks'

interface OverviewRow {
  symbol: string
  row_count: number
  date_count: number
  date_min: string | null
  date_max: string | null
  last_updated: string | null
  column_names: string[]
  block_count: number
  block_total_rows: number
}

interface TsRow {
  symbol: string
  trading_date: string
  column_name: string
  value: number
  updated_at: string
}

interface BlockRow {
  symbol: string
  trading_date: string
  row_count: number
  data_format: string
  sha256: string
  created_at: string
}

const VIEW_LABELS: Record<View, string> = {
  overview: 'Overview',
  rows: 'Timeseries Rows',
  blocks: 'Day Blocks',
}

export default function TimeseriesExplorer() {
  const [view, setView] = useState<View>('overview')
  const [symbolFilter, setSymbolFilter] = useState('')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({ view })
      if (symbolFilter) params.set('symbol', symbolFilter)
      const res = await fetch(`/api/timeseries-explorer?${params}`)
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
  }, [view, symbolFilter])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const drillInto = (symbol: string, targetView: View) => {
    setSymbolFilter(symbol)
    setView(targetView)
  }

  const navViews: View[] = ['overview', 'rows', 'blocks']

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Timeseries Explorer</h1>
        <button
          onClick={fetchData}
          disabled={loading}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Breadcrumb */}
      {symbolFilter && (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <button onClick={() => { setSymbolFilter(''); setView('overview') }} className="text-blue-400 hover:text-blue-300">
            All Symbols
          </button>
          <span className="text-slate-600">/</span>
          <span className="font-mono font-semibold text-slate-200">{symbolFilter}</span>
        </div>
      )}

      {/* View tabs */}
      <div className="flex items-center gap-2">
        {navViews.map((v) => (
          <button
            key={v}
            onClick={() => { setView(v); if (v === 'overview') setSymbolFilter('') }}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              view === v
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
          >
            {VIEW_LABELS[v]}
          </button>
        ))}

        {symbolFilter && (
          <div className="ml-4 flex items-center gap-2 rounded-lg bg-blue-950/50 px-3 py-1.5 text-xs text-blue-300">
            <span>Filtered: <span className="font-mono font-semibold">{symbolFilter}</span></span>
            <button
              onClick={() => setSymbolFilter('')}
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
        {view === 'rows' && <RowsTable rows={data as TsRow[]} />}
        {view === 'blocks' && <BlocksTable rows={data as BlockRow[]} />}
      </div>

      {!loading && data.length === 0 && !error && (
        <p className="text-center text-sm text-slate-500">No data found.</p>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Overview                                                                    */
/* -------------------------------------------------------------------------- */

function OverviewTable({ rows, onDrill }: { rows: OverviewRow[]; onDrill: (symbol: string, view: View) => void }) {
  if (!rows.length) return null
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Symbol</th>
          <th className="px-4 py-3">Product</th>
          <th className="px-4 py-3 text-right">Rows</th>
          <th className="px-4 py-3 text-right">Dates</th>
          <th className="px-4 py-3 text-right">Blocks</th>
          <th className="px-4 py-3">Date Range</th>
          <th className="px-4 py-3">Columns</th>
          <th className="px-4 py-3">Last Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const parsed = parseSymbol(r.symbol)
          return (
            <tr key={r.symbol} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
              <td className="max-w-[20rem] px-4 py-2.5">
                <span className="font-mono text-sm text-emerald-400 break-all">{r.symbol}</span>
              </td>
              <td className="px-4 py-2.5">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${productColor(parsed.product)}`}>
                  {parsed.product}
                </span>
              </td>
              <td className="px-4 py-2.5 text-right">
                <DrillButton value={r.row_count ?? 0} onClick={() => onDrill(r.symbol, 'rows')} />
              </td>
              <td className="px-4 py-2.5 text-right text-slate-300">{(r.date_count ?? 0).toLocaleString()}</td>
              <td className="px-4 py-2.5 text-right">
                <DrillButton value={r.block_count ?? 0} onClick={() => onDrill(r.symbol, 'blocks')} />
              </td>
              <td className="px-4 py-2.5 text-slate-400 text-xs">
                {r.date_min && r.date_max ? `${r.date_min} → ${r.date_max}` : '—'}
              </td>
              <td className="px-4 py-2.5">
                <div className="flex flex-wrap gap-1 max-w-[16rem]">
                  {(r.column_names || []).slice(0, 3).map((c) => (
                    <span key={c} className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300 truncate max-w-[10rem]">
                      {c}
                    </span>
                  ))}
                  {(r.column_names || []).length > 3 && (
                    <span className="text-[10px] text-slate-500">+{r.column_names.length - 3}</span>
                  )}
                </div>
              </td>
              <td className="px-4 py-2.5 text-xs text-slate-400">{formatTs(r.last_updated)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/* -------------------------------------------------------------------------- */
/* Timeseries Rows                                                             */
/* -------------------------------------------------------------------------- */

function RowsTable({ rows }: { rows: TsRow[] }) {
  if (!rows.length) return null

  // Group by trading_date for a nicer layout
  const byDate = new Map<string, TsRow[]>()
  for (const r of rows) {
    const existing = byDate.get(r.trading_date)
    if (existing) existing.push(r)
    else byDate.set(r.trading_date, [r])
  }

  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Symbol</th>
          <th className="px-4 py-3">Trading Date</th>
          <th className="px-4 py-3">Column</th>
          <th className="px-4 py-3 text-right">Value</th>
          <th className="px-4 py-3">Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const isFirstOfDate = i === 0 || rows[i - 1].trading_date !== r.trading_date
          return (
            <tr
              key={`${r.symbol}-${r.trading_date}-${i}`}
              className={`border-b transition hover:bg-slate-800/40 ${
                isFirstOfDate ? 'border-slate-700' : 'border-slate-800/30'
              }`}
            >
              <td className="px-4 py-2 font-mono text-xs text-emerald-400 max-w-[16rem] truncate">{r.symbol}</td>
              <td className={`px-4 py-2 font-mono text-slate-300 ${isFirstOfDate ? 'font-semibold' : 'text-slate-500'}`}>
                {isFirstOfDate ? r.trading_date : ''}
              </td>
              <td className="px-4 py-2 text-xs text-slate-300">{r.column_name}</td>
              <td className="px-4 py-2 text-right font-mono text-slate-200">{formatValue(r.value)}</td>
              <td className="px-4 py-2 text-xs text-slate-500">{formatTs(r.updated_at)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/* -------------------------------------------------------------------------- */
/* Day Blocks                                                                  */
/* -------------------------------------------------------------------------- */

function BlocksTable({ rows }: { rows: BlockRow[] }) {
  if (!rows.length) return null
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
          <th className="px-4 py-3">Symbol</th>
          <th className="px-4 py-3">Trading Date</th>
          <th className="px-4 py-3 text-right">Rows</th>
          <th className="px-4 py-3">Format</th>
          <th className="px-4 py-3">SHA256</th>
          <th className="px-4 py-3">Created</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.symbol}-${r.trading_date}-${i}`} className="border-b border-slate-800/50 transition hover:bg-slate-800/40">
            <td className="px-4 py-2.5 font-mono text-xs text-emerald-400 max-w-[16rem] truncate">{r.symbol}</td>
            <td className="px-4 py-2.5 font-mono text-slate-300">{r.trading_date}</td>
            <td className="px-4 py-2.5 text-right text-slate-300">{(r.row_count ?? 0).toLocaleString()}</td>
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
/* Shared                                                                      */
/* -------------------------------------------------------------------------- */

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

function formatTs(ts: string | null): string {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z'
  } catch {
    return ts
  }
}

function formatValue(v: number | null): string {
  if (v == null) return '—'
  // Show basis points for small numbers that look like rates, else normal precision
  const abs = Math.abs(v)
  if (abs < 0.5 && abs > 0) return `${(v * 100).toFixed(4)}%`
  if (abs < 100) return v.toFixed(6)
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 })
}

interface ParsedSymbol {
  product: string
  source: string
  detail: string
}

function parseSymbol(sym: string): ParsedSymbol {
  const parts = sym.split('::')
  return {
    product: parts[0] || 'UNKNOWN',
    source: parts[1] || '',
    detail: parts.slice(2).join('::') || '',
  }
}

function productColor(product: string): string {
  switch (product) {
    case 'IRS': return 'bg-blue-900/60 text-blue-300'
    case 'FRB': return 'bg-purple-900/60 text-purple-300'
    case 'STIRFUTURE': return 'bg-amber-900/60 text-amber-300'
    case 'USTFUTURE': return 'bg-green-900/60 text-green-300'
    case 'IRSWAPTION': return 'bg-cyan-900/60 text-cyan-300'
    case 'FXFORWARD': return 'bg-rose-900/60 text-rose-300'
    case 'STIRCAPFLOOR': return 'bg-orange-900/60 text-orange-300'
    case 'STIRFUTUREOPTION': return 'bg-yellow-900/60 text-yellow-300'
    case 'USTFUTUREOPTION': return 'bg-teal-900/60 text-teal-300'
    default: return 'bg-slate-800 text-slate-300'
  }
}
