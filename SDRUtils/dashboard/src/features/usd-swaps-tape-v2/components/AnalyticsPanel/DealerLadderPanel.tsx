'use client'
// ABOUTME: The signed risk-bucket ladder — within-bucket levels over time, and
// cross-bucket z. Reads arbs_dd_ladder_v1 through /api/usd-swaps-tape-v2/direction/*.
//
// WHAT THIS PANEL DELIBERATELY CANNOT DRAW
// ========================================
//
// A bar chart of signed DV01 across tenor buckets. It is the first chart
// anyone would draw and it is wrong: DV01 retention runs 0.761 at 0-1Y down to
// 0.495 at 15-20Y — a 1.54x cross-bucket scaling distortion — because the
// packages the classifier cannot orient are not a random sample of the tape.
//
//     "the 5y bucket against its own history"   supportable
//     "dealers are longer 5y than 10y"          NOT AVAILABLE
//
// Three things stop it, none of them a comment:
//   1. the level endpoint takes exactly ONE bucket and 400s on a list;
//   2. levels arrive bucket-suffixed (delta_dv01__5_7Y), so two responses do
//      not align into a comparison;
//   3. assertNotCrossBucketLevel throws on any multi-bucket frame carrying a
//      level key, and it is called on every frame that reaches a chart.
//
// The cross-sectional view is z, which is EXACTLY invariant to a constant
// retention factor: z = (r*L - r*mu)/(r*sigma) = (L - mu)/sigma.
//
// FLOW, NOT INVENTORY. Compression and allocation are never publicly reported,
// so a running sum accumulates an unbounded, monotone error with no offsetting
// print. There is no cumulative chart here, and the level is drawn as daily
// BARS rather than a line so it does not read as a stock.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'
import {
  DIRECTION_AMBER,
  DIRECTION_SKY,
  EXCLUSION_PHRASE,
} from '../../utils/dealerDirection'
import {
  assertNotCrossBucketLevel,
  type BucketRow,
  type CoverageRow,
  fmtPct,
  fmtSignedDv01,
  fmtZ,
  indexByBucketDate,
  type LadderSummary,
  latestDate,
  levelKey,
  num,
  recentDates,
  SERIES_OPTIONS,
  type SeriesName,
  type StandardisedRow,
  TENOR_BUCKETS,
  type TenorBucket,
  VENUE_CLASSES,
  VENUE_LABEL,
  type VenueClass,
  zColor,
  zInk,
  Z_CLAMP,
} from './DealerLadderPanel.helpers'

const API = '/api/usd-swaps-tape-v2/direction'
const HEATMAP_DAYS = 60

const CARD =
  'flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300'
const TITLE = 'text-[10px] uppercase tracking-wider text-slate-500'

function Chip({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  title?: string
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
        active
          ? 'bg-slate-700 text-slate-100 ring-1 ring-slate-500'
          : 'bg-slate-900 text-slate-500 hover:text-slate-300'
      }`}
    >
      {children}
    </button>
  )
}

export function DealerLadderPanel(): JSX.Element {
  const [venueClass, setVenueClass] = useState<VenueClass>('D2C')
  const [series, setSeries] = useState<SeriesName>('FLOW')
  const [bucket, setBucket] = useState<TenorBucket>('5-7Y')
  // RAW is primary and the basis travels with the number. Coverage-adjusting
  // by default would silently apply the same directional-mix assumption the
  // cross-section refusal makes loud; doing one quietly while refusing the
  // other loudly is incoherent.
  const [basis, setBasis] = useState<'raw' | 'cov_adj'>('raw')
  const [showExclusions, setShowExclusions] = useState(false)

  const [summary, setSummary] = useState<LadderSummary | null>(null)
  const [std, setStd] = useState<StandardisedRow[]>([])
  const [bucketRows, setBucketRows] = useState<BucketRow[]>([])
  const [coverage, setCoverage] = useState<CoverageRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const qs = useMemo(
    () => `venueClass=${venueClass}&series=${series}`,
    [venueClass, series],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, z] = await Promise.all([
        fetch(`${API}/summary?${qs}`).then((r) => r.json()),
        fetch(`${API}/standardised?${qs}`).then((r) => r.json()),
      ])
      if (s?.error) throw new Error(s.error)
      if (z?.error) throw new Error(z.error)
      setSummary(s.summary ?? null)
      const rows = (z.rows ?? []) as StandardisedRow[]
      // The control, not a comment: if a level key ever appears in the
      // all-bucket payload this throws rather than rendering.
      assertNotCrossBucketLevel(rows as unknown as Record<string, unknown>[])
      setStd(rows)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'failed')
    } finally {
      setLoading(false)
    }
  }, [qs])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await fetch(
          `${API}/bucket?${qs}&bucket=${encodeURIComponent(bucket)}`,
        ).then((x) => x.json())
        if (!cancelled && !r?.error) setBucketRows((r.rows ?? []) as BucketRow[])
      } catch {
        /* the panel keeps its previous bucket rather than blanking */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [qs, bucket])

  useEffect(() => {
    if (!showExclusions) return
    let cancelled = false
    void (async () => {
      try {
        const r = await fetch(`${API}/coverage?${qs}`).then((x) => x.json())
        if (!cancelled && !r?.error) setCoverage((r.rows ?? []) as CoverageRow[])
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [qs, showExclusions])

  const dates = useMemo(() => recentDates(std, HEATMAP_DAYS), [std])
  const byCell = useMemo(() => indexByBucketDate(std), [std])
  const today = useMemo(() => latestDate(std), [std])

  const zField = basis === 'raw' ? 'z_raw' : 'z_cov_adj'

  const levelField = levelKey(bucket, basis)
  const grossField = levelKey(bucket, 'gross')
  const chartData = useMemo(
    () =>
      bucketRows.map((r) => ({
        day: String(r.visibility_date).slice(0, 10),
        level: num(r[levelField]),
        // The pond the net was formed from. A net of zero over $40mm of gross
        // is a different day from a net of zero over nothing, and only the
        // gross tells them apart — so it is on the tooltip beside the net.
        gross: num(r[grossField]),
        coverage: num(r.coverage_frac),
        n_units: num(r.n_units),
        z: num(r[basis === 'raw' ? 'z_raw' : 'z_cov_adj']),
        weight: num(r.mean_abs_signed_weight),
      })),
    [bucketRows, levelField, grossField, basis],
  )

  const covFrac = num(summary?.coverage_frac)
  const totalDv01Excluded = useMemo(() => {
    const total = coverage.reduce((s, r) => s + (num(r.dv01) ?? 0), 0)
    const kept = coverage
      .filter((r) => r.in_ladder)
      .reduce((s, r) => s + (num(r.dv01) ?? 0), 0)
    return { total, kept, excluded: total - kept }
  }, [coverage])

  return (
    <div className={CARD}>
      {/* ---------------------------------------------------------------- */}
      {/* header: which series, and how much of the tape is behind it       */}
      {/* ---------------------------------------------------------------- */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className={TITLE}>
          dealer risk-bucket ladder — signed DV01, on the availability clock
        </span>
        <div className="flex items-center gap-2">
          {/* Three series, never merged. D2D is the street recycling risk
              among itself; folding it into D2C would manufacture customer
              flow that is not there. */}
          <div className="flex gap-1">
            {VENUE_CLASSES.map((v) => (
              <Chip
                key={v}
                active={v === venueClass}
                onClick={() => setVenueClass(v)}
                title={VENUE_LABEL[v]}
              >
                {v}
              </Chip>
            ))}
          </div>
          <div className="flex gap-1">
            {SERIES_OPTIONS.map((s) => (
              <Chip key={s} active={s === series} onClick={() => setSeries(s)}>
                {s}
              </Chip>
            ))}
          </div>
        </div>
      </div>

      {/* Coverage is not a footnote. It sits next to every aggregate, and it
          is the click target for the breakdown. */}
      <div className="flex flex-wrap items-center gap-3 border-y border-slate-800/80 py-1">
        <button
          type="button"
          onClick={() => setShowExclusions((x) => !x)}
          data-testid="dd-coverage-toggle"
          className="flex items-baseline gap-1.5 rounded px-1 py-0.5 hover:bg-slate-900"
          title="Only part of the tape's DV01 can be oriented. Click for the breakdown by reason."
        >
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            DV01 oriented
          </span>
          <span
            className={`tabular-nums text-[13px] font-bold ${
              covFrac != null && covFrac < 0.65 ? 'text-amber-300' : 'text-slate-100'
            }`}
          >
            {fmtPct(covFrac, 1)}
          </span>
          <span className="text-[9.5px] text-sky-300/70">
            {showExclusions ? 'hide breakdown ▾' : 'why? ▸'}
          </span>
        </button>
        <span className="text-[10px] text-slate-500">
          {summary?.first_day ? String(summary.first_day).slice(0, 10) : '—'} …{' '}
          {summary?.last_day ? String(summary.last_day).slice(0, 10) : '—'}
        </span>
        <span className="text-[10px] text-slate-500">
          {num(summary?.n_called)?.toLocaleString() ?? '—'} of{' '}
          {num(summary?.n_units)?.toLocaleString() ?? '—'} units called
        </span>
        <span className="ml-auto text-[9.5px] text-slate-600" title="the git revision that produced these rows, and the tape generation it read">
          {summary?.code_vintage ?? '—'} · tape {summary?.tape_generation ?? '—'}
        </span>
      </div>

      {showExclusions ? (
        <ExclusionBreakdown rows={coverage} totals={totalDv01Excluded} />
      ) : null}

      {error ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/30 p-2 text-[10.5px] text-amber-200">
          {error}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {/* -------------------------------------------------------------- */}
        {/* LEFT: cross-bucket z. The one cross-sectional view that holds.  */}
        {/* -------------------------------------------------------------- */}
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between">
            <span className={TITLE}>
              z, each bucket against its own history — {HEATMAP_DAYS} sessions
            </span>
            <div className="flex items-center gap-1">
              <Chip active={basis === 'raw'} onClick={() => setBasis('raw')} title="the raw level's own z">
                raw
              </Chip>
              <Chip
                active={basis === 'cov_adj'}
                onClick={() => setBasis('cov_adj')}
                title="z of the coverage-adjusted level; read this one for 1-2Y, whose coverage drifts +5.07pp/yr"
              >
                cov-adj
              </Chip>
            </div>
          </div>
          <p className="text-[9.5px] leading-tight text-slate-500">
            z is exactly invariant to a constant retention factor, so it may be
            read across buckets. The <span className="text-slate-300">level</span> may
            not — retention runs 0.761 at 0-1Y against 0.495 at 15-20Y.
          </p>

          <ZHeatmap
            dates={dates}
            byCell={byCell}
            zField={zField}
            selected={bucket}
            onSelect={setBucket}
            today={today}
          />
          <ZLegend />
        </div>

        {/* -------------------------------------------------------------- */}
        {/* RIGHT: one bucket, its own history. Levels live here only.      */}
        {/* -------------------------------------------------------------- */}
        <div className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between">
            <span className={TITLE}>
              {bucket} — {basis === 'raw' ? 'delta_dv01' : 'delta_dv01_cov_adj'}__
              {bucket.replace(/-/g, '_').replace(/\+/g, 'plus')}
            </span>
            <span className="text-[9.5px] text-slate-600">USD per bp, daily flow</span>
          </div>
          <p className="text-[9.5px] leading-tight text-slate-500">
            Bars, not a line, and no cumulative view: compression and allocation
            are never publicly reported, so a running sum carries an unbounded,
            monotone error.
          </p>

          <ResponsiveContainer width="100%" height={168}>
            <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -6 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={ANALYTICS_COLORS.slate800} vertical={false} />
              <XAxis
                dataKey="day"
                tick={{ fill: ANALYTICS_COLORS.slate500, fontSize: 9 }}
                tickFormatter={(v: string) => v.slice(5)}
                minTickGap={28}
              />
              <YAxis
                tick={{ fill: ANALYTICS_COLORS.slate500, fontSize: 9 }}
                tickFormatter={(v: number) => fmtSignedDv01(v)}
                width={52}
              />
              <ReferenceLine y={0} stroke={ANALYTICS_COLORS.slate700} />
              <Tooltip
                cursor={{ fill: 'rgba(148,163,184,0.08)' }}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  fontSize: 10,
                  fontFamily: 'monospace',
                }}
                formatter={(v: number, name: string) =>
                  name === 'level' ? [fmtSignedDv01(v), 'signed DV01'] : [v, name]
                }
                labelFormatter={(l: string) => {
                  const row = chartData.find((d) => d.day === l)
                  return (
                    `${l}   z ${fmtZ(row?.z ?? null)}\n` +
                    `gross pond ${fmtSignedDv01(row?.gross ?? null).replace('+', '')}` +
                    `   n=${row?.n_units ?? '—'}` +
                    `   mean |2p-1| ${(row?.weight ?? 0).toFixed(2)}\n` +
                    `coverage ${fmtPct(row?.coverage ?? null, 0)}`
                  )
                }}
              />
              <Bar dataKey="level" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                {chartData.map((d, i) => (
                  <Cell
                    key={i}
                    fill={(d.level ?? 0) >= 0 ? DIRECTION_SKY : DIRECTION_AMBER}
                    fillOpacity={0.85}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          {/* Coverage on its OWN axis, in its own chart. Never a second
              y-scale on the level chart: two measures of different scale on
              one plot is the single most misread chart there is. */}
          <div className="mt-1">
            <span className="text-[9.5px] uppercase tracking-wider text-slate-600">
              coverage behind that level
            </span>
            <ResponsiveContainer width="100%" height={52}>
              <LineChart data={chartData} margin={{ top: 2, right: 4, bottom: 0, left: -6 }}>
                <XAxis dataKey="day" hide />
                <YAxis
                  domain={[0, 1]}
                  ticks={[0, 0.5, 1]}
                  tick={{ fill: ANALYTICS_COLORS.slate500, fontSize: 8 }}
                  tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                  width={52}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#0f172a',
                    border: '1px solid #334155',
                    fontSize: 10,
                    fontFamily: 'monospace',
                  }}
                  formatter={(v: number) => [fmtPct(v, 1), 'coverage']}
                />
                <Line
                  type="monotone"
                  dataKey="coverage"
                  stroke={ANALYTICS_COLORS.slate400}
                  strokeWidth={2}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <BucketCaveats bucket={bucket} rows={bucketRows} />
        </div>
      </div>

      {loading ? <span className="text-[10px] text-slate-600">loading…</span> : null}
    </div>
  )
}

// ---------------------------------------------------------------------------

function ZHeatmap({
  dates,
  byCell,
  zField,
  selected,
  onSelect,
  today,
}: {
  dates: string[]
  byCell: Map<string, StandardisedRow>
  zField: 'z_raw' | 'z_cov_adj'
  selected: TenorBucket
  onSelect: (b: TenorBucket) => void
  today: string | null
}): JSX.Element {
  return (
    <div className="flex flex-col gap-[2px]" data-testid="dd-z-heatmap">
      {TENOR_BUCKETS.map((b) => {
        const latest = today ? byCell.get(`${b}|${today}`) : undefined
        const latestZ = num(latest?.[zField])
        const covRaw = num(latest?.coverage_frac)
        // The SMOOTHED coverage, not the day's own. Which packages happened
        // to print moves a bucket's coverage by more than 25% relative on
        // between a quarter and two-thirds of days depending on the bucket,
        // so a chip showing one day's fraction is mostly composition noise
        // being read as information. Falls back to the raw fraction while
        // the 63-observation smoother is still filling.
        const covSmooth = num(latest?.coverage_smooth)
        const cov = covSmooth ?? covRaw
        const drift = latest?.coverage_drift_flag === true
        return (
          <button
            key={b}
            type="button"
            onClick={() => onSelect(b)}
            data-testid={`dd-z-row-${b}`}
            className={`flex items-center gap-1.5 rounded px-1 py-[1px] text-left transition-colors ${
              b === selected ? 'bg-slate-800/70 ring-1 ring-slate-600' : 'hover:bg-slate-900'
            }`}
          >
            <span
              className={`w-[46px] shrink-0 text-[10px] tabular-nums ${
                b === selected ? 'text-slate-100' : 'text-slate-400'
              }`}
            >
              {b}
            </span>
            {/* 2px surface gaps between cells: adjacent fills need a gap or
                they read as one continuous block. */}
            <span className="flex min-w-0 flex-1 gap-[1px]">
              {dates.map((d) => {
                const r = byCell.get(`${b}|${d}`)
                const z = num(r?.[zField])
                return (
                  <span
                    key={d}
                    className="h-[13px] min-w-0 flex-1 rounded-[1px]"
                    style={{ backgroundColor: z == null ? '#0b1220' : zColor(z) }}
                    title={
                      `${b}  ${d}\n` +
                      `z ${fmtZ(z)}   percentile ${fmtPct(num(r?.pct_raw), 0)}\n` +
                      `coverage ${fmtPct(num(r?.coverage_frac), 0)}   ` +
                      `n=${r?.n_units ?? '—'}   obs behind z ${r?.z_n_obs ?? '—'}` +
                      (r?.observed === false ? '\nno prints that session' : '')
                    }
                  />
                )
              })}
            </span>
            <span
              className="w-[34px] shrink-0 rounded px-1 text-right text-[10px] tabular-nums"
              style={{ backgroundColor: zColor(latestZ), color: zInk(latestZ) }}
              title="latest z"
            >
              {fmtZ(latestZ)}
            </span>
            <span
              className={`w-[30px] shrink-0 text-right text-[9px] tabular-nums ${
                drift ? 'text-amber-300' : 'text-slate-600'
              }`}
              title={
                (covSmooth != null
                  ? `coverage, trailing 63-session mean: ${fmtPct(covSmooth, 1)}\n`
                    + `latest session alone: ${fmtPct(covRaw, 1)}`
                  : `coverage, latest session: ${fmtPct(covRaw, 1)} `
                    + '(the 63-session smoother has not filled yet)') +
                (drift
                  ? '\n\nTHIS BUCKET\'S COVERAGE DRIFTS. Its level moves for '
                    + 'measurement reasons that look exactly like information. '
                    + 'Read the cov-adj basis, or read z.'
                  : '')
              }
            >
              {fmtPct(cov, 0)}
              {drift ? '!' : ''}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function ZLegend(): JSX.Element {
  const stops = [-Z_CLAMP, -2, -1, 0, 1, 2, Z_CLAMP]
  return (
    <div className="flex items-center gap-2 text-[9px] text-slate-500">
      <span className="text-amber-300">dealer paid / short</span>
      <span className="flex gap-[1px]">
        {stops.map((z) => (
          <span
            key={z}
            className="h-[9px] w-4 rounded-[1px]"
            style={{ backgroundColor: zColor(z) }}
            title={`z ${fmtZ(z)}`}
          />
        ))}
      </span>
      <span className="text-sky-300">dealer received / long</span>
      <span className="ml-auto">z clamped at ±{Z_CLAMP}</span>
    </div>
  )
}

function BucketCaveats({
  bucket,
  rows,
}: {
  bucket: TenorBucket
  rows: BucketRow[]
}): JSX.Element | null {
  const last = rows.length ? rows[rows.length - 1] : null
  const notes: string[] = []
  if (bucket === '1-2Y') {
    notes.push(
      'This bucket\'s exclusion rate drifts at +5.07 pp/yr (t = +3.21), so its ' +
        'level moves for measurement reasons that look exactly like information. ' +
        'Read the cov-adj basis, or read the raw level and subtract a trend you ' +
        'know is there.',
    )
  }
  if (last) {
    const block = num(last.frac_dv01_block as number | null)
    const capped = num(last.frac_dv01_capped as number | null)
    const dead = num(last.frac_dv01_dead_zone as number | null)
    if (capped != null && capped > 0.05) {
      notes.push(
        `${fmtPct(capped, 0)} of the latest cell's DV01 sits on capped notional — ` +
          'the size was not read, so the magnitude is a LOW reading.',
      )
    }
    if (block != null && block > 0.15) {
      notes.push(
        `${fmtPct(block, 0)} is block prints, which arrive delayed; the availability ` +
          'clock already accounts for that but the intraday shape does not.',
      )
    }
    if (dead != null && dead > 0.2) {
      notes.push(
        `${fmtPct(dead, 0)} sat inside the mid's own measurement error, where 2p-1 ` +
          'sends the contribution towards zero automatically.',
      )
    }
  }
  if (!notes.length) return null
  return (
    <ul className="mt-0.5 flex flex-col gap-0.5 text-[9.5px] leading-tight text-amber-200/70">
      {notes.map((n) => (
        <li key={n}>— {n}</li>
      ))}
    </ul>
  )
}

function ExclusionBreakdown({
  rows,
  totals,
}: {
  rows: CoverageRow[]
  totals: { total: number; kept: number; excluded: number }
}): JSX.Element {
  const sorted = [...rows].sort((a, b) => (num(b.dv01) ?? 0) - (num(a.dv01) ?? 0))
  return (
    <div
      className="flex flex-col gap-1 rounded border border-slate-800 bg-slate-900/40 p-2"
      data-testid="dd-exclusion-breakdown"
    >
      <div className="flex items-baseline justify-between">
        <span className={TITLE}>where the DV01 went, by reason</span>
        <span className="text-[10px] text-slate-500">
          {fmtSignedDv01(totals.excluded).replace('−', '')} of{' '}
          {fmtSignedDv01(totals.total).replace('−', '')} excluded
        </span>
      </div>
      {sorted.length === 0 ? (
        <span className="text-[10px] text-slate-600">no coverage rows</span>
      ) : null}
      {sorted.map((r) => {
        const share = num(r.dv01_share) ?? 0
        return (
          <div key={r.reason} className="flex items-center gap-2">
            <span
              className={`w-[164px] shrink-0 truncate text-[10px] ${
                r.in_ladder ? 'text-sky-300' : 'text-slate-400'
              }`}
              title={r.in_ladder ? 'reached the ladder' : (EXCLUSION_PHRASE[r.reason] ?? r.reason)}
            >
              {r.reason}
            </span>
            <span className="h-[8px] min-w-0 flex-1 rounded-full bg-slate-950">
              <span
                className="block h-[8px] rounded-full"
                style={{
                  width: `${Math.max(0, Math.min(1, share)) * 100}%`,
                  backgroundColor: r.in_ladder ? DIRECTION_SKY : '#475569',
                }}
              />
            </span>
            <span className="w-[46px] shrink-0 text-right text-[10px] tabular-nums text-slate-300">
              {fmtPct(share, 1)}
            </span>
            <span className="w-[58px] shrink-0 text-right text-[9.5px] tabular-nums text-slate-500">
              {(num(r.n_units) ?? 0).toLocaleString()}
            </span>
          </div>
        )
      })}
      <p className="mt-0.5 text-[9.5px] leading-tight text-slate-500">
        UNORIENTABLE_PKG is structural, not a backlog item: for 64.2% of PKG-4+
        DV01 several mutually inconsistent sign vectors reconcile the leg fees to
        the package price inside the same tolerance, so any orientation returned
        would be a solver tie-break rather than economics. Ambiguity rises from
        61.45% at four legs to 97.25% at eight or more. And the excluded packages
        are the <em className="not-italic text-slate-300">most</em> customer-facing
        prints on the tape — PKG-4+ is 97.9% D2C against 82.1% for what is
        retained — so whatever this ladder says about the size of customer risk
        transfer is a low reading.
      </p>
    </div>
  )
}
