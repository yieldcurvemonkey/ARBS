'use client'
// ABOUTME: The STIR dealer-flow chart — one meeting-dated structure, one day,
// one rate index, with the dealer's side on every print. The web port of
// notebooks/exploratory/dealer_flow_chart.ipynb.
//
// WHAT IS DIFFERENT FROM THE NOTEBOOK, AND WHY
// ============================================
//
//  * MARKS SIT AT THEIR TRADED RATE, which is the notebook default, and the
//    gap to the mid line IS the dealer spread: RECEIVED above, PAID below.
//    That only reads correctly once a unit trap in the source table is
//    reconciled -- fixed_rate is a FRACTION (99.95% of rows) and curve_mid is
//    already PERCENT (99.88%). Subtracting them raw puts EVERY trade 3.66
//    below its mid and looks like a mass inversion; converted, the identity is
//    exact: spread_to_mid_bps == (fixed_rate*100 - curve_mid)*100, median
//    |error| 0.0 over 49,653 of 49,653 rows.
//  * NO CUSTOMER TOGGLE. The notebook has customer=True, which flips every
//    label. Two independent sign inversions were caught during this work, both
//    rendering plausibly. Fixed to the DEALER perspective and every label says
//    "dealer".
//  * rateIndex IS REQUIRED. The notebook infers it from the curve and lets it
//    be None. This chart has already been wrong once by overlaying SOFR on a
//    Fed-Funds line, so there is no path here that leaves it unset.
//  * NO auto_backfill. Rendering a chart must never write to prod.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'
import { DIRECTION_AMBER, DIRECTION_SKY } from '../../utils/dealerDirection'
import {
  buildStirMidSeries,
  instrumentLabel,
  markRadius,
  midPct,
  rateDomain,
  type MidPoint,
  num,
  parseTenorQuery,
  spreadDomain,
  type StirFlowResponse,
  type StirFlowRow,
  type StirInstrument,
  stirMarkStyle,
  STIR_RATE_INDEXES,
  tDomain,
  tradedPct,
  tsMillis,
} from './StirFlowPanel.helpers'

const API = '/api/usd-swaps-tape-v2/direction/stir-flow'
const CARD =
  'flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300'
const TITLE = 'text-[10px] uppercase tracking-wider text-slate-500'
const CHART_H = 280
const DEV_H = 74

function Chip({
  active, onClick, children, title,
}: { active: boolean; onClick: () => void; children: React.ReactNode; title?: string }): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
        active ? 'bg-slate-700 text-slate-100 ring-1 ring-slate-500'
               : 'bg-slate-900 text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  )
}

type MarkDatum = { t: number; y: number; row: StirFlowRow }

function upPath(cx: number, cy: number, r: number): string {
  return `M ${cx} ${cy - r} L ${cx + r} ${cy + r * 0.8} L ${cx - r} ${cy + r * 0.8} Z`
}
function downPath(cx: number, cy: number, r: number): string {
  return `M ${cx} ${cy + r} L ${cx + r} ${cy - r * 0.8} L ${cx - r} ${cy - r * 0.8} Z`
}
function diamondPath(cx: number, cy: number, r: number): string {
  return `M ${cx} ${cy - r} L ${cx + r} ${cy} L ${cx} ${cy + r} L ${cx - r} ${cy} Z`
}

function Mark(props: { cx?: number; cy?: number; payload?: MarkDatum }): JSX.Element | null {
  const { cx, cy, payload } = props
  if (cx == null || cy == null || payload == null) return null
  const s = stirMarkStyle(payload.row)
  const r = markRadius(payload.row.structure_dv01)
  const d = s.shape === 'up' ? upPath(cx, cy, r) : s.shape === 'down' ? downPath(cx, cy, r) : diamondPath(cx, cy, r)
  return (
    <path
      d={d}
      fill={s.filled ? s.color : 'none'}
      fillOpacity={s.filled ? 0.85 : 0}
      stroke={s.color}
      strokeWidth={s.filled ? 0 : 1.4}
      strokeOpacity={0.95}
    />
  )
}

const fmtRate = (x: number | null, d = 4) => (x == null ? '—' : x.toFixed(d))
const fmtBps = (x: number | null, d = 2) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(d)}`)
const fmtNotional = (x: number | null) =>
  x == null ? '—' : Math.abs(x) >= 1e9 ? `${(x / 1e9).toFixed(2)}B` : Math.abs(x) >= 1e6 ? `${(x / 1e6).toFixed(1)}M` : `${(x / 1e3).toFixed(0)}K`

const ET = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
})
const fmtEt = (t: number) => ET.format(new Date(t))

function FlowTooltip({ active, payload }: {
  active?: boolean
  payload?: { payload?: MarkDatum | MidPoint }[]
}): JSX.Element | null {
  if (!active || !payload?.length) return null
  const p = payload[0]?.payload
  if (!p || !('row' in p)) return null
  const r = p.row
  const s = stirMarkStyle(r)
  return (
    <div className="rounded border border-slate-700 bg-slate-950 p-2 font-mono text-[10px] leading-relaxed text-slate-200">
      <div className="font-semibold" style={{ color: s.color }}>
        dealer {s.label}
        {r.classification_method === 'TICK_RULE' ? ' · tick rule' : ''}
        {r.is_off_market ? ' · off-market' : ''}
      </div>
      <div className="text-slate-400">{fmtEt(p.t)} ET</div>
      {/* fixed_rate is a FRACTION, curve_mid is already PERCENT. */}
      <div>traded {fmtRate(tradedPct(r), 4)}%</div>
      <div>mid used {fmtRate(midPct(r), 4)}%</div>
      <div>
        spread to mid <span className="font-semibold">{fmtBps(num(r.spread_to_mid_bps))} bp</span>
      </div>
      <div>DV01 {fmtNotional(num(r.structure_dv01))} · notional {fmtNotional(num(r.notional))}</div>
      <div className="text-slate-400">
        {r.classification_method ?? '—'} · confidence {r.direction_confidence ?? '—'}
        {r.curve_suspect_trade ? ' · CURVE SUSPECT' : ''}
      </div>
      <div className="max-w-[280px] whitespace-pre-wrap text-slate-500">{s.title}</div>
    </div>
  )
}

export function StirFlowPanel(): JSX.Element {
  const [date, setDate] = useState<string | null>(null)
  const [instruments, setInstruments] = useState<StirInstrument[]>([])
  const [instLoading, setInstLoading] = useState(true)
  const [picked, setPicked] = useState<StirInstrument | null>(null)
  const [includeOffMarket, setIncludeOffMarket] = useState(false)
  const [includeTickRule, setIncludeTickRule] = useState(true)

  const [data, setData] = useState<StirFlowResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // --- instruments for the day ---------------------------------------------
  useEffect(() => {
    let cancelled = false
    setInstLoading(true)
    void (async () => {
      try {
        const qs = date ? `?date=${date}` : ''
        const b = await fetch(`${API}/instruments${qs}`).then((r) => r.json())
        if (cancelled) return
        if (b?.error) { setError(b.error); return }
        const rows = (b.rows ?? []) as StirInstrument[]
        setInstruments(rows)
        setDate((d) => d ?? (b.date as string))
        // Keep the pick if it still exists on the new day; otherwise take the
        // busiest. Silently keeping a stale instrument would draw an empty
        // chart and look like "nothing traded".
        setPicked((cur) => {
          if (cur) {
            const same = rows.find(
              (r) => r.tenor_query === cur.tenor_query && r.rate_index_clean === cur.rate_index_clean)
            if (same) return same
          }
          return rows[0] ?? null
        })
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'failed')
      } finally {
        if (!cancelled) setInstLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [date])

  // --- the flow for the picked instrument ----------------------------------
  const qs = useMemo(() => {
    if (!picked || !date) return null
    const p = new URLSearchParams({
      date,
      tenorQuery: picked.tenor_query,
      rateIndex: picked.rate_index_clean,
    })
    if (includeOffMarket) p.set('includeOffMarket', 'true')
    if (!includeTickRule) p.set('includeTickRule', 'false')
    return p.toString()
  }, [picked, date, includeOffMarket, includeTickRule])

  const load = useCallback(async (isCancelled: () => boolean) => {
    if (!qs) return
    setLoading(true)
    try {
      const b = (await fetch(`${API}?${qs}`).then((r) => r.json())) as StirFlowResponse
      if (isCancelled()) return
      if (b?.error) setError(b.error)
      else { setError(null); setData(b) }
    } catch (e: unknown) {
      if (!isCancelled()) setError(e instanceof Error ? e.message : 'failed')
    } finally {
      if (!isCancelled()) setLoading(false)
    }
  }, [qs])

  useEffect(() => {
    let cancelled = false
    void load(() => cancelled)
    return () => { cancelled = true }
  }, [load])

  const rows = useMemo(() => data?.rows ?? [], [data])
  const mid = useMemo(() => buildStirMidSeries(data?.mid ?? []), [data])
  const midCount = useMemo(() => mid.filter((m) => m.mid != null).length, [mid])
  const yDom = useMemo(() => rateDomain(rows, mid), [rows, mid])
  const tDom = useMemo(() => tDomain(rows, mid), [rows, mid])
  const devDom = useMemo(() => spreadDomain(rows), [rows])

  // Marks sit at their OWN TRADED RATE, in percent, so the gap to the mid line
  // is the dealer spread -- RECEIVED above, PAID below. That only works because
  // the units are reconciled: fixed_rate is a fraction and curve_mid is already
  // percent (see tradedPct / midPct).
  const marks: MarkDatum[] = useMemo(() => {
    const out: MarkDatum[] = []
    for (const r of rows) {
      const t = tsMillis(r.execution_timestamp)
      const y = tradedPct(r)
      if (t == null || y == null || !Number.isFinite(y)) continue
      out.push({ t, y, row: r })
    }
    return out
  }, [rows])

  const received = useMemo(() => marks.filter((m) => m.row.dealer_direction === 'RECEIVED'), [marks])
  const paid = useMemo(() => marks.filter((m) => m.row.dealer_direction === 'PAID'), [marks])

  const netDv01 = useMemo(() => {
    let net = 0
    for (const r of rows) {
      const d = num(r.structure_dv01) ?? 0
      net += r.dealer_direction === 'RECEIVED' ? d : -d
    }
    return net
  }, [rows])

  const counts = data?.counts
  const pair = picked ? parseTenorQuery(picked.tenor_query) : null

  return (
    <div className={CARD} data-testid="stir-flow-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className={TITLE}>
          STIR dealer flow{pair ? ` — ${pair.eff} → ${pair.mat}` : ''}
          {picked ? ` · ${picked.rate_index_clean}` : ''}
        </span>
        <input
          type="date"
          value={date ?? ''}
          onChange={(e) => { setDate(e.target.value || null); setData(null) }}
          className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[10px] text-slate-200"
          data-testid="stir-flow-date"
        />
      </div>

      <p className="text-[9.5px] leading-tight text-slate-500">
        One meeting-dated structure, on the execution clock. The dealer&apos;s side of every
        print, from the STIR classifier — a price-implied inference, not a counterparty record.
      </p>

      {/* the instrument picker */}
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="min-w-[340px] max-w-full rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[10px] text-slate-200"
          value={picked ? `${picked.tenor_query}|${picked.rate_index_clean}` : ''}
          onChange={(e) => {
            const [tq, ix] = e.target.value.split('|')
            const found = instruments.find(
              (i) => i.tenor_query === tq && i.rate_index_clean === ix)
            if (found) setPicked(found)
          }}
          data-testid="stir-flow-instrument"
        >
          {instruments.length === 0 ? (
            <option value="">{instLoading ? 'loading instruments…' : 'no instruments on this day'}</option>
          ) : null}
          {instruments.map((i) => (
            <option key={`${i.tenor_query}|${i.rate_index_clean}`} value={`${i.tenor_query}|${i.rate_index_clean}`}>
              {instrumentLabel(i)}
            </option>
          ))}
        </select>

        {/* The index is part of the instrument identity, shown rather than
            chosen: picking it separately is how SOFR ended up on an FF line. */}
        <span className="flex gap-1">
          {STIR_RATE_INDEXES.map((ix) => (
            <Chip
              key={ix}
              active={picked?.rate_index_clean === ix}
              onClick={() => {
                const alt = instruments.find(
                  (i) => i.tenor_query === picked?.tenor_query && i.rate_index_clean === ix)
                if (alt) setPicked(alt)
              }}
              title={
                'The rate index is part of the instrument, not an overlay. SOFR OIS sits '
                + '~1.5–2.5bp off the Fed Funds curve, so putting both on one line draws that '
                + 'basis as if it were a dealer spread — the bug this chart has already had.'
              }
            >
              {ix}
            </Chip>
          ))}
        </span>

        <Chip active={includeOffMarket} onClick={() => setIncludeOffMarket((x) => !x)}
              title="An upfront makes the fixed rate arbitrary: off mid by construction. Drawn as diamonds.">
          off-market
        </Chip>
        <Chip active={includeTickRule} onClick={() => setIncludeTickRule((x) => !x)}
              title="TICK_RULE trades are classified from trade sequence, not from the mid. Drawn hollow.">
          tick-rule
        </Chip>
      </div>

      {/* the counts strip — every filter reports what it removed */}
      {counts ? (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-y border-slate-800/80 py-1 text-[10px] text-slate-400">
          <span><span className="font-bold text-slate-100">{counts.drawn}</span> drawn</span>
          <span className="text-slate-500">mid-based {counts.onMarketMid}</span>
          <span className="text-slate-500">tick-rule {counts.tickRule}</span>
          <span className="text-slate-500">off-market {counts.offMarket}</span>
          <span className={counts.offIndex > 0 ? 'text-amber-300' : 'text-slate-500'}
                title="Trades on the OTHER rate index, removed. Leaving these on the chart is the bug it has already had once.">
            other index removed {counts.offIndex}
          </span>
          {counts.noMid > 0 ? <span className="text-slate-500">no mid {counts.noMid}</span> : null}
          {counts.curveSuspect > 0 ? (
            <span className="text-amber-300" title="The classifier itself doubts the snapshot these were priced against.">
              curve-suspect {counts.curveSuspect}
            </span>
          ) : null}
          <span className="ml-auto" title="Signed DV01 across the drawn trades: received minus paid.">
            net <span className={netDv01 >= 0 ? 'text-sky-300' : 'text-amber-300'}>
              {netDv01 >= 0 ? '+' : '−'}{fmtNotional(Math.abs(netDv01))}
            </span> /bp
          </span>
        </div>
      ) : null}

      {error ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/30 p-2 text-[10.5px] text-amber-200">
          {error}
        </div>
      ) : null}

      <div className="min-h-[22px]">
        {loading ? (
          <div className="rounded border border-slate-800 bg-slate-900/30 px-2 py-1 text-[10px] text-slate-600">
            loading flow…
          </div>
        ) : midCount > 0 ? (
          <div className="rounded border border-slate-700 bg-slate-900/50 px-2 py-1 text-[10px] text-slate-300">
            <span className="text-slate-500">line:</span> the mid the classifier USED, at{' '}
            {midCount} print-time snapshot(s) · {data?.curve_name ?? '—'}
            <span className="ml-2 text-slate-500">
              not a continuous curve — segments between snapshots are drawn, not measured
            </span>
          </div>
        ) : rows.length > 0 ? (
          <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200">
            no stored mid for any of these trades — marks cannot be placed on a level, so only
            the signed distance below is drawn
          </div>
        ) : null}
      </div>

      {rows.length === 0 && !loading ? (
        <div className="rounded border border-slate-700 bg-slate-900/50 px-2 py-3 text-center text-[10px] text-slate-400"
             data-testid="stir-flow-empty">
          {picked
            ? `no ${picked.rate_index_clean} trades on ${picked.tenor_query} for ${date ?? 'this day'} after the filters above`
            : 'pick an instrument'}
        </div>
      ) : null}

      {/* --------------------------- the rate chart --------------------------- */}
      <ResponsiveContainer width="100%" height={CHART_H}>
        <ComposedChart data={mid} margin={{ top: 6, right: 8, bottom: 2, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} vertical={false} />
          <XAxis
            dataKey="t" type="number" scale="time"
            domain={tDom ?? ['dataMin', 'dataMax']}
            tick={{ fill: ANALYTICS_COLORS.slate500, fontSize: 9 }}
            tickFormatter={(v: number) => fmtEt(v)}
            minTickGap={28}
          />
          <YAxis
            type="number" domain={yDom ?? ['auto', 'auto']}
            tick={{ fill: ANALYTICS_COLORS.slate500, fontSize: 9 }}
            tickFormatter={(v: number) => v.toFixed(3)}
            width={54}
          />
          <Tooltip content={<FlowTooltip />} cursor={{ stroke: '#334155', strokeDasharray: '3 3' }} />
          {/* DASHED, always. This line is snapshots at print times; a solid
              stroke is the visual grammar of a continuously observed level and
              this is not one. */}
          {midCount > 1 ? (
            <Line
              type="linear" dataKey="mid"
              stroke={ANALYTICS_COLORS.slate400} strokeWidth={1.25} strokeDasharray="4 3"
              connectNulls={false}
              dot={{ r: 1.6, fill: ANALYTICS_COLORS.slate400, stroke: 'none' }}
              activeDot={false} isAnimationActive={false} name="mid"
            />
          ) : null}
          {/* Never render a Scatter with no data: recharts falls back to the
              CHART's data prop and emits one empty <g> per mid point. */}
          {received.length > 0 ? (
            <Scatter data={received} dataKey="y" shape={<Mark />} isAnimationActive={false} name="received" />
          ) : null}
          {paid.length > 0 ? (
            <Scatter data={paid} dataKey="y" shape={<Mark />} isAnimationActive={false} name="paid" />
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[9.5px] text-slate-500">
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden><path d={upPath(7, 7, 5)} fill={DIRECTION_SKY} fillOpacity={0.85} /></svg>
          dealer RECEIVED fixed (long duration)
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden><path d={downPath(7, 7, 5)} fill={DIRECTION_AMBER} fillOpacity={0.85} /></svg>
          dealer PAID fixed (short duration)
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden><path d={upPath(7, 7, 5)} fill="none" stroke={DIRECTION_SKY} strokeWidth={1.4} /></svg>
          hollow = tick-rule (not mid-based)
        </span>
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden><path d={diamondPath(7, 7, 5)} fill={DIRECTION_SKY} fillOpacity={0.85} /></svg>
          diamond = off-market
        </span>
        <span>size = structure DV01/bp</span>
        <span className="ml-auto">gap to the line = the dealer&apos;s spread</span>
      </div>

      {/* ----------------------- the signed distance -------------------------- */}
      <div className={TITLE}>spread to mid, bp — the dealer&apos;s side, signed</div>
      <ResponsiveContainer width="100%" height={DEV_H}>
        <ComposedChart data={[]} margin={{ top: 4, right: 8, bottom: 2, left: 54 }}>
          <XAxis dataKey="t" type="number" scale="time" domain={tDom ?? ['dataMin', 'dataMax']} hide />
          <YAxis type="number" domain={devDom} hide />
          <Tooltip content={<FlowTooltip />} cursor={false} />
          {rows.length > 0 ? (
            <Scatter
              data={rows
                .map((r) => ({ t: tsMillis(r.execution_timestamp), s: num(r.spread_to_mid_bps), row: r }))
                .filter((x): x is { t: number; s: number; row: StirFlowRow } => x.t != null && x.s != null)
                .map((x) => ({ t: x.t, y: x.s, row: x.row }))}
              dataKey="y"
              shape={<Mark />}
              isAnimationActive={false}
              name="spread"
            />
          ) : null}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex justify-between text-[9px] text-slate-600">
        <span>±{Math.abs(devDom[1]).toFixed(2)} bp</span>
        <span>
          positive = dealer received above mid · negative = dealer paid below mid
        </span>
      </div>

      {data?.disclosures?.length ? (
        <div className="flex flex-col gap-0.5 border-t border-slate-800 pt-1 text-[9px] leading-snug text-slate-500">
          {data.disclosures.map((d) => (
            <span key={d.slice(0, 48)}>— {d}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
