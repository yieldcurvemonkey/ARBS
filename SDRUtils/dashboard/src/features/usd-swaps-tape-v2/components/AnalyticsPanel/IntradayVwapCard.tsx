'use client'
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'

type Bucket = {
  bucket: string
  vwap: number
  rate_std: number
  trade_count: number
  bucket_dv01: number
  running_vwap: number
  running_std: number
}

type Print = { ts: string; fixed_rate: number; abs_risk: number }

const TENORS = ['2Y', '5Y', '10Y', '30Y']

export function IntradayVwapCard(): JSX.Element {
  const [buckets, setBuckets] = useState<Bucket[]>([])
  const [prints, setPrints] = useState<Print[]>([])
  const [loading, setLoading] = useState(true)
  const [tenor, setTenor] = useState('10Y')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/usd-swaps-tape-v2/intraday-vwap?tenor=${tenor}`)
      if (!res.ok) return
      const json = await res.json()
      setBuckets(json.buckets ?? [])
      setPrints(json.prints ?? [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [tenor])

  useEffect(() => { fetchData() }, [fetchData])

  const chartData = useMemo(() => {
    return buckets.map(b => {
      const t = new Date(b.bucket).toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York',
      })
      return {
        time: t,
        vwap: b.running_vwap ? b.running_vwap * 10000 : null,
        upper1: b.running_vwap && b.running_std ? (b.running_vwap + b.running_std) * 10000 : null,
        lower1: b.running_vwap && b.running_std ? (b.running_vwap - b.running_std) * 10000 : null,
        upper2: b.running_vwap && b.running_std ? (b.running_vwap + 2 * b.running_std) * 10000 : null,
        lower2: b.running_vwap && b.running_std ? (b.running_vwap - 2 * b.running_std) * 10000 : null,
      }
    })
  }, [buckets])

  const outliers = useMemo(() => {
    if (buckets.length === 0) return 0
    const last = buckets[buckets.length - 1]
    if (!last.running_vwap || !last.running_std) return 0
    const threshold = 2 * last.running_std
    return prints.filter(p => Math.abs(p.fixed_rate - last.running_vwap) > threshold).length
  }, [prints, buckets])

  return (
    <div className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">Intraday VWAP</span>
        {outliers > 0 && (
          <span className="rounded bg-rose-500/20 px-1.5 py-0.5 text-[9.5px] text-rose-200 ring-1 ring-rose-500/30">
            {outliers} outlier{outliers > 1 ? 's' : ''} &gt;2σ
          </span>
        )}
      </div>
      <div className="flex gap-1">
        {TENORS.map(t => (
          <button
            key={t}
            type="button"
            onClick={() => setTenor(t)}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              tenor === t
                ? 'border-sky-400 bg-sky-500/20 text-sky-200'
                : 'border-slate-700 text-slate-400 hover:border-slate-500'
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {!loading && chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={160}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} />
            <XAxis dataKey="time" tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }} />
            <YAxis
              domain={['auto', 'auto']}
              tick={{ fill: ANALYTICS_COLORS.slate400, fontSize: 9 }}
              tickFormatter={v => (v != null && Number.isFinite(v)) ? v.toFixed(1) : '—'}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 10, fontFamily: 'monospace' }}
              formatter={(v: number) => (v != null && Number.isFinite(v)) ? v.toFixed(2) + ' bps' : '—'}
            />
            <Line type="monotone" dataKey="vwap" stroke="#38bdf8" strokeWidth={2} dot={false} name="VWAP" />
            <Line type="monotone" dataKey="upper1" stroke="rgba(34, 211, 238, 0.4)" strokeWidth={1} dot={false} strokeDasharray="4 2" name="+1σ" />
            <Line type="monotone" dataKey="lower1" stroke="rgba(34, 211, 238, 0.4)" strokeWidth={1} dot={false} strokeDasharray="4 2" name="-1σ" />
            <Line type="monotone" dataKey="upper2" stroke="rgba(248, 113, 113, 0.4)" strokeWidth={1} dot={false} strokeDasharray="2 2" name="+2σ" />
            <Line type="monotone" dataKey="lower2" stroke="rgba(248, 113, 113, 0.4)" strokeWidth={1} dot={false} strokeDasharray="2 2" name="-2σ" />
          </ComposedChart>
        </ResponsiveContainer>
      ) : loading ? (
        <div className="py-4 text-center text-[10px] text-slate-500">Loading…</div>
      ) : (
        <div className="py-4 text-center text-[10px] text-slate-500">No VWAP data for {tenor} today.</div>
      )}
    </div>
  )
}
