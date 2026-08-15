'use client'
// ABOUTME: One CURVE or FLY structure, one session: the minutely spread from the
// 1-minute par grid, with every print of that structure and the dealer's side.
//
// This is what a 10s30s selection on the tape should show. The sibling panel
// draws a RATE for a single tenor; this draws a SPREAD in basis points, and the
// two never share an axis. They share `darkLayout` so the crosshair, the ink and
// the hover behaviour cannot drift apart.
//
// THE LEVEL IS EXACT, NOT RECONSTRUCTED. deviation_bps is already
// structure-grain, so mid = traded - deviation. Verified on 25,692 units over 26
// months (CURVE 17,197/17,197, FLY 8,495/8,495, to better than 3e-12 bp), and
// hand-traced against PTS_4652395859000000101 whose legs 4.2395/4.4550 give
// exactly the 21.55 bp the tape header shows.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ANALYTICS_COLORS } from './analytics-format'
import { darkLayout, iso, purgePlot, renderPlot } from './analytics-plotly'
import { DIRECTION_AMBER, DIRECTION_NEUTRAL, DIRECTION_SKY } from '../../utils/dealerDirection'

const API = '/api/usd-swaps-tape-v2/direction/structure'
const CARD =
  'flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300'
const TITLE = 'text-[10px] uppercase tracking-wider text-slate-500'
const CHART_H = 360

export type StructureSelection = {
  kind: 'CURVE' | 'FLY'
  tenors: string[]
  rateIndex: string
  venueClass: string
  date: string | null
}

type Row = {
  package_id: string
  execution_timestamp: string
  dealer_direction: 'RECEIVED' | 'PAID' | 'ABSTAINED'
  traded_bp: number
  mid_bp: number
  deviation_bps: number
  structure_dv01: number | string | null
  notional_total: number | string | null
  tenor_tuple: string[]
  leg_rates_pct: (number | string)[]
  rule: string
  special_tenor_type: string | null
  is_off_market: boolean
  p: number | string | null
}

type Resp = {
  date: string
  label: string
  kind: string
  tenors: string[]
  rateIndex: string
  venueClass: string
  levelUnit: string
  rows: Row[]
  mid: { ts: string; mid_bp: number }[]
  counts: {
    drawn: number; onMarket: number; offMarket: number
    forwardStart: number; otherRule: number; allOfThisStructure: number
  }
  disclosures: string[]
  curve_name: string | null
  error?: string
}

const num = (v: unknown): number | null => {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
const fmtNot = (x: number | null) =>
  x == null ? '—'
    : Math.abs(x) >= 1e9 ? `${(x / 1e9).toFixed(2)}B`
    : Math.abs(x) >= 1e6 ? `${(x / 1e6).toFixed(1)}M`
    : `${(x / 1e3).toFixed(0)}K`

/** Same size law as the sibling panel, so a mark of a given area means the
 *  same amount of risk on both charts. */
const R_MIN = 3.5
const R_MAX = 14
const DV01_REF = 100_000
function radius(dv01: number | null): number {
  if (dv01 == null || dv01 <= 0) return R_MIN
  return Math.min(R_MAX, R_MIN + (R_MAX - R_MIN) * Math.sqrt(Math.min(Math.abs(dv01) / DV01_REF, 1)))
}

function Chip({ active, onClick, children, title }: {
  active: boolean; onClick: () => void; children: React.ReactNode; title?: string
}): JSX.Element {
  return (
    <button
      type="button" onClick={onClick} title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
        active ? 'bg-slate-700 text-slate-100 ring-1 ring-slate-500'
               : 'bg-slate-900 text-slate-500 hover:text-slate-300'}`}
    >{children}</button>
  )
}

export function StructurePrintsPanel({ selection }: { selection: StructureSelection }): JSX.Element {
  const [date, setDate] = useState<string | null>(selection.date)
  const [includeOffMarket, setIncludeOffMarket] = useState(false)
  const [ruleStrict, setRuleStrict] = useState(true)
  const [fwdMax, setFwdMax] = useState(0.02)
  const [data, setData] = useState<Resp | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const plotRef = useRef<HTMLDivElement>(null)

  // A new selection is a new instrument: drop the old day so the panel does not
  // show yesterday's 5s10s under today's 10s30s title.
  const selKey = `${selection.kind}|${selection.tenors.join(',')}|${selection.rateIndex}|${selection.venueClass}`
  useEffect(() => { setDate(selection.date); setData(null) }, [selKey, selection.date])

  const qs = useMemo(() => {
    const p = new URLSearchParams({
      kind: selection.kind,
      tenors: selection.tenors.join(','),
      rateIndex: selection.rateIndex,
      venueClass: selection.venueClass,
      fwdMaxYears: String(fwdMax),
    })
    if (date) p.set('date', date)
    if (includeOffMarket) p.set('includeOffMarket', 'true')
    if (!ruleStrict) p.set('ruleStrict', 'false')
    return p.toString()
  }, [selKey, selection, date, includeOffMarket, ruleStrict, fwdMax])

  const load = useCallback(async (cancelled: () => boolean) => {
    setLoading(true)
    try {
      const b = (await fetch(`${API}?${qs}`).then((r) => r.json())) as Resp
      if (cancelled()) return
      if (b?.error) setError(b.error)
      else { setError(null); setData(b); setDate((d) => d ?? b.date) }
    } catch (e: unknown) {
      if (!cancelled()) setError(e instanceof Error ? e.message : 'failed')
    } finally { if (!cancelled()) setLoading(false) }
  }, [qs])

  useEffect(() => {
    let c = false
    void load(() => c)
    return () => { c = true }
  }, [load])

  const rows = useMemo(() => data?.rows ?? [], [data])
  const mid = useMemo(() => data?.mid ?? [], [data])

  // ---------------------------------------------------------------- plot ---
  useEffect(() => {
    const el = plotRef.current
    if (!el) return
    let disposed = false
    let lib: unknown = null

    const groups = new Map<string, Row[]>()
    for (const r of rows) {
      const key = `${r.dealer_direction}|${r.is_off_market}`
      const g = groups.get(key) ?? []
      g.push(r)
      groups.set(key, g)
    }

    const traces: unknown[] = []
    if (mid.length > 0) {
      traces.push({
        type: 'scattergl', mode: 'lines', name: 'mid',
        x: mid.map((m) => m.ts), y: mid.map((m) => m.mid_bp),
        connectgaps: false,
        line: { color: ANALYTICS_COLORS.slate400, width: 1.6 },
        hovertemplate: 'mid %{y:.3f} bp<extra></extra>',
        xaxis: 'x', yaxis: 'y',
      })
    }
    for (const [key, g] of groups) {
      const dir = key.split('|')[0]
      const off = key.endsWith('true')
      const color = dir === 'RECEIVED' ? DIRECTION_SKY : dir === 'PAID' ? DIRECTION_AMBER : DIRECTION_NEUTRAL
      traces.push({
        type: 'scattergl', mode: 'markers',
        name: off ? `${dir} (off-mkt)` : dir,
        x: g.map((r) => r.execution_timestamp),
        y: g.map((r) => r.traded_bp),
        customdata: g.map((r) => [
          dir,
          r.traded_bp.toFixed(3),
          r.mid_bp.toFixed(3),
          r.deviation_bps.toFixed(3),
          fmtNot(num(r.structure_dv01)),
          fmtNot(num(r.notional_total)),
          (r.leg_rates_pct ?? []).map((x) => Number(x).toFixed(4)).join(' / '),
          r.rule,
          off ? ' · off-market' : '',
        ]),
        marker: {
          symbol: off ? 'diamond-open' : dir === 'RECEIVED' ? 'triangle-up' : 'triangle-down',
          size: g.map((r) => radius(num(r.structure_dv01)) * 2),
          color: off ? 'rgba(0,0,0,0)' : color,
          opacity: 0.9,
          line: { color, width: off ? 1.4 : 0 },
        },
        hovertemplate:
          '<b>dealer %{customdata[0]}</b>%{customdata[8]}<br>'
          + 'traded %{customdata[1]} bp  ·  mid %{customdata[2]} bp<br>'
          + 'deviation %{customdata[3]} bp<br>'
          + 'DV01 %{customdata[4]} / bp  ·  notional %{customdata[5]}<br>'
          + 'legs %{customdata[6]}%  ·  %{customdata[7]}<extra></extra>',
        xaxis: 'x', yaxis: 'y',
      })
    }
    if (rows.length > 0) {
      traces.push({
        type: 'bar', name: 'deviation',
        x: rows.map((r) => r.execution_timestamp),
        y: rows.map((r) => r.deviation_bps),
        marker: {
          color: rows.map((r) =>
            r.dealer_direction === 'RECEIVED' ? DIRECTION_SKY
              : r.dealer_direction === 'PAID' ? DIRECTION_AMBER : DIRECTION_NEUTRAL),
          line: { width: 0 },
        },
        hovertemplate: '%{y:+.3f} bp off mid<extra></extra>',
        xaxis: 'x', yaxis: 'y2', showlegend: false,
      })
    }

    const ts: number[] = []
    for (const r of rows) ts.push(new Date(r.execution_timestamp).getTime())
    for (const m of mid) ts.push(new Date(m.ts).getTime())
    const layout = darkLayout({
      height: CHART_H,
      yTitle: `${data?.label ?? 'structure'}, bp`,
      yTickFormat: '.2f',
      y2Title: 'off mid, bp',
      xRange: ts.length ? [iso(Math.min(...ts)), iso(Math.max(...ts))] : undefined,
    })

    renderPlot(el, traces, layout, () => disposed)
      .then((l) => { lib = l })
      .catch((err) => console.error('StructurePrintsPanel render error', err))
    return () => { disposed = true; purgePlot(lib, el) }
  }, [rows, mid, data?.label])

  const c = data?.counts
  const net = useMemo(() => {
    let n = 0
    for (const r of rows) {
      const d = num(r.structure_dv01) ?? 0
      n += r.dealer_direction === 'RECEIVED' ? d : -d
    }
    return n
  }, [rows])

  return (
    <div className={CARD} data-testid="structure-prints-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className={TITLE}>
          {data?.label ?? `${selection.kind} ${selection.tenors.join('/')}`} — {selection.rateIndex}
          {' · '}{selection.venueClass}
        </span>
        <input
          type="date" value={date ?? ''}
          onChange={(e) => setDate(e.target.value || null)}
          className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[10px] text-slate-200"
          data-testid="structure-date"
        />
      </div>

      <p className="text-[9.5px] leading-tight text-slate-500">
        The level is the STRUCTURE price in basis points — positive is an upward-sloping
        quote. Each print&apos;s mid is exact (mid = traded − deviation, both structure-grain);
        the line is the same weights applied to the 1-minute par grid.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <Chip active={includeOffMarket} onClick={() => setIncludeOffMarket((x) => !x)}
              title="A structure is off-market if ANY leg carries an upfront — the fee lands on one leg but prices the whole package.">
          off-market
        </Chip>
        <Chip active={!ruleStrict} onClick={() => setRuleStrict((x) => !x)}
              title="Include prints not priced under RATE_VS_MID. Under NPV_VS_UPFRONT the deviation is an edge against a fee — a different quantity on the same axis.">
          all rules
        </Chip>
        {[0.02, 0.25].map((f) => (
          <Chip key={f} active={fwdMax === f} onClick={() => setFwdMax(f)}
                title="A forward-starting curve is not the spot curve.">
            fwd ≤ {f}y
          </Chip>
        ))}
      </div>

      {c ? (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-y border-slate-800/80 py-1 text-[10px] text-slate-400">
          <span><span className="font-bold text-slate-100">{c.drawn}</span> prints drawn</span>
          <span className="text-slate-500">of {c.allOfThisStructure} for this structure</span>
          {c.offMarket > 0 ? <span className="text-slate-500">off-market {c.offMarket}</span> : null}
          {c.forwardStart > 0 ? <span className="text-slate-500">forward-starting {c.forwardStart}</span> : null}
          {c.otherRule > 0 ? <span className="text-amber-300">other rule {c.otherRule}</span> : null}
          <span className="ml-auto" title="Signed structure DV01 across the drawn prints: received minus paid.">
            net <span className={net >= 0 ? 'text-sky-300' : 'text-amber-300'}>
              {net >= 0 ? '+' : '−'}{fmtNot(Math.abs(net))}</span> /bp
          </span>
        </div>
      ) : null}

      {error ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/30 p-2 text-[10.5px] text-amber-200">{error}</div>
      ) : null}

      {loading && rows.length === 0 ? (
        <div className="rounded border border-slate-800 bg-slate-900/30 px-2 py-1 text-[10px] text-slate-600">
          loading {data?.label ?? 'structure'} prints…
        </div>
      ) : !loading && rows.length === 0 ? (
        <div className="rounded border border-slate-700 bg-slate-900/50 px-2 py-3 text-center text-[10px] text-slate-400"
             data-testid="structure-empty">
          no {selection.rateIndex} {data?.label ?? selection.tenors.join('/')} prints on{' '}
          {date ?? 'this day'} at {selection.venueClass} after the filters above
          {c && c.allOfThisStructure > 0
            ? ` — ${c.allOfThisStructure} exist before filtering`
            : ''}
        </div>
      ) : null}

      <div ref={plotRef} className="w-full" style={{ height: `${CHART_H}px` }} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[9.5px] text-slate-500">
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden>
            <path d="M 7 2 L 12 11 L 2 11 Z" fill={DIRECTION_SKY} fillOpacity={0.9} />
          </svg>
          dealer RECEIVED the spread
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden>
            <path d="M 7 12 L 12 3 L 2 3 Z" fill={DIRECTION_AMBER} fillOpacity={0.9} />
          </svg>
          dealer PAID the spread
        </span>
        <span>size = structure DV01/bp</span>
        <span className="ml-auto">gap to the line = the dealer&apos;s spread</span>
      </div>

      {data?.disclosures?.length ? (
        <div className="flex flex-col gap-0.5 border-t border-slate-800 pt-1 text-[9px] leading-snug text-slate-500">
          {data.disclosures.map((d) => <span key={d.slice(0, 44)}>— {d}</span>)}
        </div>
      ) : null}
    </div>
  )
}
