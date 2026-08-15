'use client'
// ABOUTME: Every print of one tenor, on one day, on the EXECUTION clock,
// against the continuous 1-minute par grid. Reads arbs_dd_unit_v1 joined to the
// v3 tape legs, plus arbs_dd_curve_mid_v1, through
// /api/usd-swaps-tape-v2/direction/prints.
//
// ===================================================================
// THE MID IS NOT A QUOTE, AND THE CHART IS BUILT SO IT CANNOT PRETEND TO BE
// ===================================================================
//
// TWO DIFFERENT OBJECTS SHARE THIS AXIS, and they must never render alike:
//
//   THE LINE   arbs_dd_curve_mid_v1 — a MODELLED par rate every minute, built
//              by the same SessionBranchPricer against the same Citi minute
//              curve that repriced every mark. Solid, no dots.
//   EACH MARK  its own mid, reconstructed as `traded - deviation/100`. Exact
//              for that print by construction, and what deviation_bps — hence
//              the direction call — is measured against.
//
// They agree where they are the same instrument: median residual EXACTLY 0.000000
// bp, p95 0.132 bp over 3,206 prints. The tail is the instrument differing (of 9
// prints beyond 0.5bp the median maturity gap to the grid swap is 6 days and none
// is an exact match), so the residual is a CHIP ON SCREEN rather than a hidden
// check. Where there is no grid — Fed Funds 7Y/20Y/30Y, measured: 12 FF tenors
// against SOFR's 21 — the line falls back to a polyline through the prints and
// says so in an amber strip.
//
// Four mechanisms stop either one reading as a continuous quoted market:
//
//   1. dots first, and the dots are the data;
//   2. the line BREAKS rather than bridging — grid segments only across gaps
//      <= 10 min (measured: no intra-day grid gap exceeds 5 min on any sampled
//      day, the overnight hole is ~2h), reconstruction only across <= 20 min
//      (p50 print gap 5.0 min, p90 23.0, max 177.8);
//   3. the RECONSTRUCTION is dashed — a solid line is the visual grammar of a
//      quote, and a join-the-dots has not earned it;
//   4. type="linear", never "monotone" — a spline invents curvature between two
//      model points.
//
// Below 12 mid points neither line is drawn and only dots are.
//
// WHAT IS DELIBERATELY NOT HERE
// -----------------------------
//   * no customer/dealer perspective toggle. Two independent sign inversions
//     were caught during the backend work, both producing completely plausible
//     output. Fixed to the DEALER perspective, and every label says "dealer".
//   * no clock toggle. The reconstructed mid is a function of execution time
//     (snapshot_lag_seconds is 0 for the overwhelming majority), so plotting it
//     against visibility time would shear the mid against its own pricing
//     clock — a half-broken mode. The reporting lag is disclosed instead.
//   * no direction on a package leg. A unit's dealer_direction is a STRUCTURE
//     direction; in a steepener the dealer receives one leg and pays the other,
//     so painting a leg with it is a guaranteed inversion.
//   * no conviction-by-opacity, and no dead-zone filter. in_dead_zone is
//     REPORTING-ONLY and is true for 92.5% of the reference day, so fading by
//     conviction would fade nearly every mark to illegibility while removing no
//     error.
import type { JSX } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ANALYTICS_COLORS } from './analytics-format'
import { IntradayPrintsPlot } from './IntradayPrintsPlot'
import { StructurePrintsPanel } from './StructurePrintsPanel'
import {
  DIRECTION_AMBER,
  DIRECTION_NEUTRAL,
  DIRECTION_SKY,
} from '../../utils/dealerDirection'
import {
  chevronPath,
  chooseMidSeries,
  clampToDomain,
  diamondPath,
  directionOf,
  downTrianglePath,
  etDateOf,
  etMidnightFor,
  fmtEtClock,
  fmtEtStamp,
  fmtLagSeconds,
  fmtNotional,
  fmtNum,
  fmtPctShare,
  fmtRate,
  fmtSignedBps,
  FWD_MAX_DEFAULT,
  FWD_MAX_OPTIONS,
  followFocused,
  type FollowSource,
  structureOf,
  hourlyTicks,
  legendSizeRefs,
  markerOpacity,
  markerRadius,
  type MidPoint,
  normaliseRateIndex,
  tapeDayFor,
  midGridResidual,
  type MidSource,
  MIN_MID_POINTS,
  type Pinned,
  PRINT_TENORS,
  type PrintRow,
  type PrintsResponse,
  RATE_INDEXES,
  sizeNotRead,
  stemColor,
  tDomain,
  tsMillis,
  upTrianglePath,
  VENUE_CLASSES,
  yDomain,
} from './IntradayPrintsPanel.helpers'

const API = '/api/usd-swaps-tape-v2/direction/prints'

const CARD =
  'flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-300'
const TITLE = 'text-[10px] uppercase tracking-wider text-slate-500'
const CHART_H = 300
const DEV_H = 64
// left MUST equal the price chart's plot offset — margin.left (0) plus the
// YAxis `width` (54) — or the two panels shear against each other and a stem
// no longer sits under the mark it belongs to.
const DEV_MARGIN = { top: 6, right: 8, bottom: 2, left: 54 }

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

type MarkDatum = {
  t: number
  y: number
  pinned: Pinned
  trueY: number
  row: PrintRow
}

/**
 * In the analytics dock this panel FOLLOWS the tape's focused trade: the tenor,
 * the rate index, the venue class and the day all come from whatever row is
 * selected. That is the point of it living in the dock rather than in a
 * standalone view.
 *
 * Following is a toggle, not a cage — pinning lets you keep one instrument on
 * screen while clicking around the tape. And nothing is ever guessed: a
 * selection this chart cannot draw (a 4Y, a basis trade, a `~10Y`) leaves the
 * controls where they were and says so, because silently swapping in a
 * different instrument under the reader's own selection is the failure this
 * whole panel is built against.
 */
export function IntradayPrintsPanel({ focused }: { focused?: FollowSource | null } = {}): JSX.Element {
  // A CURVE or FLY selection is a DIFFERENT INSTRUMENT with a different axis —
  // a spread in bp, not a rate in percent — so it gets its own chart rather
  // than being squeezed onto this one. Delegating here keeps the switch at the
  // one place that knows what is selected.
  const structure = structureOf(focused)
  if (structure) {
    return (
      <StructurePrintsPanel
        selection={{
          kind: structure.kind,
          tenors: structure.tenors,
          rateIndex: normaliseRateIndex(focused?.rate_index_clean)
            ?? normaliseRateIndex((focused?.legs_json ?? []).map((l) => l?.rate_index_clean).find((x) => !!x))
            ?? 'SOFR',
          venueClass: focused?.dd_venue_class ?? 'D2C',
          date: tapeDayFor(focused?.execution_start),
        }}
      />
    )
  }
  return <OutrightPrintsPanel focused={focused} />
}

function OutrightPrintsPanel({ focused }: { focused?: FollowSource | null } = {}): JSX.Element {
  const [date, setDate] = useState<string | null>(null)
  const [latestDate, setLatestDate] = useState<string | null>(null)
  const [tenor, setTenor] = useState<string>('10Y')
  const [rateIndex, setRateIndex] = useState<string>('SOFR')
  const [venueClass, setVenueClass] = useState<string>('D2C')
  const [showPackageLegs, setShowPackageLegs] = useState(false)
  const [includeOffMarket, setIncludeOffMarket] = useState(false)
  const [tenorMatch, setTenorMatch] = useState<'strict' | 'band'>('strict')
  const [fwdMaxYears, setFwdMaxYears] = useState<number>(FWD_MAX_DEFAULT)
  const [followSelection, setFollowSelection] = useState(true)
  const [followRefusals, setFollowRefusals] = useState<string[]>([])

  const [data, setData] = useState<PrintsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Take what the selection can give and REPORT what it could not.
  const followKey = focused
    ? `${focused.tenor_display ?? ''}|${focused.rate_index_clean ?? ''}|`
      + `${focused.execution_start ?? ''}|${focused.dd_venue_class ?? ''}`
    : ''
  useEffect(() => {
    if (!followSelection || !focused) return
    const f = followFocused(focused)
    if (f.tenor) setTenor(f.tenor)
    if (f.rateIndex) setRateIndex(f.rateIndex)
    if (f.venueClass) setVenueClass(f.venueClass)
    if (f.date) setDate(f.date)
    setFollowRefusals(f.refusals)
  }, [followSelection, followKey, focused])

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (date) p.set('date', date)
    p.set('tenor', tenor)
    p.set('rateIndex', rateIndex)
    p.set('venueClass', venueClass)
    p.set('kinds', showPackageLegs ? 'OUTRIGHT,CURVE,FLY,PKG' : 'OUTRIGHT')
    p.set('tenorMatch', tenorMatch)
    p.set('fwdMaxYears', String(fwdMaxYears))
    if (includeOffMarket) p.set('includeOffMarket', 'true')
    return p.toString()
  }, [date, tenor, rateIndex, venueClass, showPackageLegs, tenorMatch, fwdMaxYears, includeOffMarket])

  // The cancelled flag lives in the EFFECT, not in the loader: a loader that
  // owns its own flag can never be cancelled by the effect that started it, and
  // a superseded response would land on top of a newer one.
  const load = useCallback(
    async (isCancelled: () => boolean) => {
      setLoading(true)
      try {
        const body = (await fetch(`${API}?${qs}`).then((r) => r.json())) as PrintsResponse
        if (isCancelled()) return
        // A refusal or a DB failure is surfaced, never swallowed into an empty
        // chart: "no prints today" and "the query blew up" look identical on an
        // empty scatter and only one of them is about the market. On a failure
        // the previous day's rows stay on screen rather than blanking.
        if (body?.error) {
          setError(body.error)
        } else {
          setError(null)
          setData(body)
          setLatestDate((d) => d ?? body.date)
        }
      } catch (e: unknown) {
        if (!isCancelled()) setError(e instanceof Error ? e.message : 'failed')
      } finally {
        if (!isCancelled()) setLoading(false)
      }
    },
    [qs],
  )

  useEffect(() => {
    let cancelled = false
    void load(() => cancelled)
    return () => {
      cancelled = true
    }
  }, [load])

  const rows = useMemo(() => data?.rows ?? [], [data])
  const shownDate = date ?? data?.date ?? ''

  // The line comes from the 1-minute par grid where there is one, and from the
  // per-print reconstruction where there is not (Fed Funds 7Y/20Y/30Y). Which
  // one is RENDERED, not inferred: solid for a curve, dashed for a polyline.
  const { source: midSource, points: midSeries } = useMemo(
    () => chooseMidSeries(rows, data?.mid),
    [rows, data?.mid],
  )
  const midCount = useMemo(() => midSeries.filter((m) => m.mid != null).length, [midSeries])
  const midResid = useMemo(
    () => (midSource === 'grid' ? midGridResidual(rows, data?.mid?.points ?? []) : null),
    [midSource, rows, data?.mid],
  )
  const yDom = useMemo(() => yDomain(rows, fwdMaxYears, midSeries), [rows, fwdMaxYears, midSeries])
  const tDom = useMemo(() => tDomain(rows, midSeries), [rows, midSeries])
  const etMidnight = useMemo(() => etMidnightFor(rows), [rows])
  const ticks = useMemo(() => hourlyTicks(tDom), [tDom])

  const marks: MarkDatum[] = useMemo(() => {
    const out: MarkDatum[] = []
    for (const r of rows) {
      const t = tsMillis(r.execution_timestamp)
      if (t == null) continue
      const { value, pinned } = clampToDomain(Number(r.traded_pct), yDom)
      out.push({ t, y: value, pinned, trueY: Number(r.traded_pct), row: r })
    }
    return out
  }, [rows, yDom])

  // Render order is z-order: package rings sit behind everything (level only),
  // then the edge-pinned off-market marks, then the directional marks.
  const packageMarks = useMemo(() => marks.filter((m) => m.row.kind !== 'OUTRIGHT'), [marks])
  const offMarketMarks = useMemo(
    () => marks.filter((m) => m.row.kind === 'OUTRIGHT' && m.row.is_off_market === true),
    [marks],
  )
  const directionalMarks = useMemo(
    () => marks.filter((m) => m.row.kind === 'OUTRIGHT' && m.row.is_off_market !== true),
    [marks],
  )

  const counts = data?.counts
  const prov = data?.provenance
  // Toggle-invariant denominator: the on-market population plus the off-market
  // one. Using rows.length would double-count once off-market marks are shown.
  const total = (counts?.onMarket ?? 0) + (counts?.dropped.offMarket ?? 0)

  return (
    <div className={CARD} data-testid="intraday-prints-panel">
      {/* ------------------------------------------------------------------ */}
      {/* header                                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className={TITLE}>
          intraday traded prints — {tenor} {rateIndex}
          {fwdMaxYears > FWD_MAX_DEFAULT ? ` · forward start ≤ ${fwdMaxYears}y` : ''}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="date"
            value={shownDate}
            max={latestDate ?? undefined}
            min="2024-07-01"
            onChange={(e) => setDate(e.target.value || null)}
            className="rounded bg-slate-900 px-1 py-0.5 text-[10px] text-slate-300 ring-1 ring-slate-700"
            title="as_of_date — the UTC calendar date of EXECUTION, which runs from ~20:0x ET the previous evening"
          />
          <div className="flex gap-1">
            {PRINT_TENORS.map((t) => (
              <Chip key={t} active={t === tenor} onClick={() => setTenor(t)}>
                {t}
              </Chip>
            ))}
          </div>
        </div>
      </div>

      {/* The clock, stated. This chart answers "where did it trade", not "what
          could you have known" — those are different charts and only one of
          them is this one. */}
      <p className="text-[9.5px] leading-tight text-slate-500">
        execution clock (ET) — where it traded, not what you could have known;
        the ladder aggregates on the availability clock. mid ={' '}
        <span className="text-slate-300">traded − deviation</span>, against{' '}
        {prov?.curve_name ?? '—'} under {prov?.snapshot_policy ?? '—'} (median
        snapshot lag {fmtLagSeconds(prov?.median_snapshot_lag_seconds)}).
      </p>

      {/* ------------------------------------------------------------------ */}
      {/* controls                                                            */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-center gap-2 border-y border-slate-800/80 py-1">
        <div className="flex gap-1">
          {RATE_INDEXES.map((r) => (
            <Chip
              key={r}
              active={r === rateIndex}
              onClick={() => setRateIndex(r)}
              title="one index per chart — SOFR OIS sits ~1.5–2.4bp off the Fed Funds curve, and overlaying both draws that basis as if it were bid-offer"
            >
              {r}
            </Chip>
          ))}
        </div>
        <div className="flex gap-1">
          {VENUE_CLASSES.map((v) => (
            <Chip
              key={v}
              active={v === venueClass}
              onClick={() => setVenueClass(v)}
              title="three series, never summed: dealers recycling risk among themselves is not customer flow"
            >
              {v}
            </Chip>
          ))}
        </div>
        <span className="mx-1 h-3 w-px bg-slate-800" />
        <Chip
          active={tenorMatch === 'strict'}
          onClick={() => setTenorMatch('strict')}
          title="tenor_display — an equality test on a pre-computed strict label (9.984–10.027y at 10Y)"
        >
          strict tenor
        </Chip>
        <Chip
          active={tenorMatch === 'band'}
          onClick={() => setTenorMatch('band')}
          title="tenor_label — a ±6-month band (9.50–10.49y at 10Y)"
        >
          band
        </Chip>
        <span className="mx-1 h-3 w-px bg-slate-800" />
        <span className="text-[9.5px] text-slate-600">fwd ≤</span>
        {FWD_MAX_OPTIONS.map((f) => (
          <Chip
            key={f}
            active={f === fwdMaxYears}
            onClick={() => setFwdMaxYears(f)}
            title="a forward start is a different instrument — a 10y10y prints 66bp from spot"
          >
            {f}y
          </Chip>
        ))}
        <span className="mx-1 h-3 w-px bg-slate-800" />
        {focused ? (
          <Chip
            active={followSelection}
            onClick={() => setFollowSelection((x) => !x)}
            title="Follow the trade selected in the tape above — its tenor, rate index, venue and tape day. Unpin to hold one instrument on screen while clicking around the tape."
          >
            follow selection
          </Chip>
        ) : null}
        <Chip
          active={includeOffMarket}
          onClick={() => setIncludeOffMarket((x) => !x)}
          title="show fee-bearing prints as hollow diamonds, pinned to the edge — they never enter the y-domain"
        >
          off-market
        </Chip>
        <Chip
          active={showPackageLegs}
          onClick={() => setShowPackageLegs((x) => !x)}
          title="curve / fly / package legs, level only — a leg of a structure carries no resolvable direction"
        >
          package legs
        </Chip>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* the measured chips — every one of these is a count, not an inference */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-wrap items-center gap-3 text-[10px]">
        <span className="text-slate-200">
          <span className="tabular-nums text-[13px] font-bold">{counts?.drawn ?? 0}</span> prints
          drawn
        </span>
        <span className="text-slate-500" title="mid points behind the dashed line">
          {counts?.withMid ?? 0} with a reconstructed mid
        </span>
        <span
          className={includeOffMarket ? 'text-amber-300' : 'text-slate-500'}
          title="a print with an upfront is off mid by construction; including them in the domain stretches the axis 31×"
        >
          off-market {includeOffMarket ? 'shown' : 'hidden'}: {counts?.dropped.offMarket ?? 0}
          {total > 0 ? ` (${fmtPctShare((counts?.dropped.offMarket ?? 0) / total)})` : ''}
        </span>
        <span className="text-slate-500" title="a 10y10y is not a 10Y — measured 66bp apart">
          forward-starting hidden: {counts?.dropped.forwardStart ?? 0}
        </span>
        {/* dropped.packageLegs counts what the KIND filter removed, so it
            necessarily falls to zero once the legs are shown. The chip counts
            the rows instead in that mode, otherwise it would read "0" with 120
            rings on screen. */}
        <span
          className={showPackageLegs ? 'text-slate-300' : 'text-slate-500'}
          title="curve / fly / package legs at this tenor — level only, no direction"
        >
          package legs {showPackageLegs ? 'shown' : 'hidden'}:{' '}
          {showPackageLegs ? packageMarks.length : (counts?.dropped.packageLegs ?? 0)}
        </span>
        <span className="text-slate-500">
          reporting lag median {fmtLagSeconds(prov?.median_visibility_lag_seconds)} (max{' '}
          {fmtLagSeconds(prov?.max_visibility_lag_seconds)})
        </span>
        <span className="ml-auto text-[9.5px] text-slate-600" title="the tape generation and git revision behind these rows">
          tape {prov?.tape_generation ?? '—'} · dd {prov?.dd_generation ?? '—'} ·{' '}
          {prov?.code_vintage ?? '—'}
        </span>
      </div>

      {/* The dead-zone share, stated plainly and interpreted not at all. Why
          92% of a day sits inside tau is a hypothesis, not a measurement. */}
      <div className="text-[9.5px] text-slate-500">
        {fmtPctShare(prov?.dead_zone_share ?? 0, 0)} of these calls are inside the dead zone
        (reporting-only flag — nothing in the aggregation depends on it, so no mark is faded and
        none are dropped).
      </div>

      {error ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/30 p-2 text-[10.5px] text-amber-200">
          {error}
        </div>
      ) : null}

      {data?.looseTenor ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200">
          loose tenor: tenor_label {tenor} spans a ±6-month band (9.50–10.49y at 10Y) against
          tenor_display&apos;s 9.984–10.027 · +{data.admittedByLoosening ?? 0} prints admitted
          {data.observedTenorYears
            ? ` · returned set runs ${data.observedTenorYears[0].toFixed(4)}–${data.observedTenorYears[1].toFixed(4)}y`
            : ''}
        </div>
      ) : null}

      {fwdMaxYears > FWD_MAX_DEFAULT ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200">
          forward-starting prints admitted up to {fwdMaxYears}y. A 10y10y is not a 10Y — measured
          66bp apart — and the y-domain has recomputed around them. This is a different chart, not
          an overlay.
        </div>
      ) : null}

      {midSource === 'none' && midCount > 0 ? (
        <div className="rounded border border-slate-700 bg-slate-900/50 px-2 py-1 text-[10px] text-slate-300">
          not enough clean prints to draw a mid (n={midCount}, floor={MIN_MID_POINTS}) — the dots
          are still the data
        </div>
      ) : null}

      {/* WHAT THE LINE IS. Two different objects render as one shape unless the
          chart says which; a polyline through eight prints read as a curve is
          exactly the misreading this panel exists to prevent.

          THE ROW IS ALWAYS PRESENT, so the chart below it does not jump when
          the fetch lands. Measured: this strip appearing pushed the content
          under it 54px and was 0.018 of a 0.230 cumulative layout shift —
          small next to the page's own 0.120, but it is the one that moves
          while the reader is already looking at the chart. */}
      {followSelection && followRefusals.length > 0 ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200">
          <span className="font-semibold">the selected trade was only partly followed</span>
          {followRefusals.map((r) => (
            <span key={r.slice(0, 40)} className="block">— {r}</span>
          ))}
        </div>
      ) : null}

      <div className="min-h-[22px]">
      {loading && midSource === 'none' ? (
        <div className="rounded border border-slate-800 bg-slate-900/30 px-2 py-1 text-[10px] text-slate-600">
          measuring the mid…
        </div>
      ) : midSource === 'grid' ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-slate-700 bg-slate-900/50 px-2 py-1 text-[10px] text-slate-300">
          <span>
            <span className="text-slate-500">line:</span> modelled 1-min par grid,{' '}
            {data?.mid.points.length ?? 0} pts · {data?.mid.curve_name ?? '—'}
          </span>
          {midResid != null ? (
            <span title="Each mark's own mid (traded − deviation) against the grid point at the minute of that print's curve snapshot. ~0 for a spot standard swap — literally the same instrument. Grows with the maturity gap for a broken-dated one.">
              <span className="text-slate-500">mark vs line:</span> med{' '}
              {fmtSignedBps(midResid.medianBps, 4)} · p95 {fmtNum(midResid.p95Bps, 3)}bp · max{' '}
              {fmtNum(midResid.maxBps, 3)}bp (n={midResid.n})
            </span>
          ) : null}
          <span className="text-slate-500">breaks at gaps &gt; 10 min</span>
        </div>
      ) : midSource === 'reconstructed' ? (
        <div className="rounded border border-amber-700/50 bg-amber-950/20 px-2 py-1 text-[10px] text-amber-200">
          <span className="font-semibold">no continuous mid for {rateIndex} {tenor}</span> —{' '}
          {data?.mid.available === false
            ? 'the 1-minute par grid does not carry this tenor on this index (Fed Funds is built on 12 tenors and has no 7Y, 20Y or 30Y; SOFR carries all eight). '
            : 'the grid is empty over this window. '}
          The dashed line is a polyline through the prints themselves, not a curve: it exists only
          where somebody traded.
        </div>
      ) : null}
      </div>

      {/* AN EMPTY PLOT IS A CLAIM. Same defect as the blank heatmap and the
          blank exclusion drawer: a frame with nothing in it reads as "nothing
          traded" whether the day is genuinely empty, the filters removed
          everything, or the fetch is still in flight. Those are three
          different sentences. */}
      {rows.length === 0 ? (
        <div
          className="rounded border border-slate-700 bg-slate-900/50 px-2 py-3 text-center text-[10px] text-slate-400"
          data-testid={`prints-empty-${loading ? 'loading' : 'empty'}`}
        >
          {loading
            ? 'loading prints…'
            : `no ${rateIndex} ${tenor} ${venueClass} prints on ${shownDate || 'this day'} ` +
              'after the filters above. The counts strip says how many each filter removed.'}
        </div>
      ) : null}

      {/* ------------------------------------------------------------------ */}
      {/* the chart                                                           */}
      {/* ------------------------------------------------------------------ */}
      {/* ONE PLOTLY FIGURE, TWO PANELS, ONE CROSSHAIR.
          The rate on top and the signed distance from mid below share an x
          axis, so a spike line crosses both: the question a reader has at a
          mark is "how far off mid was that", and the answer is directly under
          it. Dark, pannable, scroll-zoomable. */}
      <IntradayPrintsPlot
        rows={rows}
        mid={midSeries}
        midSource={midSource}
        yDomain={yDom}
        tDomain={tDom}
        height={CHART_H + DEV_H}
        tenor={tenor}
        rateIndex={rateIndex}
      />

      <MarkLegend
        showPackageLegs={showPackageLegs}
        includeOffMarket={includeOffMarket}
        midSource={midSource}
      />


      {data?.disclosures?.length ? (
        <ul className="mt-0.5 flex flex-col gap-0.5 text-[9.5px] leading-tight text-slate-500">
          {data.disclosures.map((d) => (
            <li key={d}>— {d}</li>
          ))}
        </ul>
      ) : null}

      {loading ? <span className="text-[10px] text-slate-600">loading…</span> : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The marks
// ---------------------------------------------------------------------------

/**
 * One custom shape for every mark.
 *
 * recharts' built-in shape="triangle" only points up, so both directional marks
 * come from explicit paths. Direction is encoded TWICE — hue and shape — plus
 * the word in the legend and the word in the tooltip: the house emerald/rose
 * pair scores deuteranopia ΔE 4.6, so colour alone says nothing at all to a
 * red-green viewer on a chart whose entire content is a sign.
 */
function Mark(props: { cx?: number; cy?: number; payload?: MarkDatum }): JSX.Element | null {
  const { cx, cy, payload } = props
  if (cx == null || cy == null || payload == null) return null
  const row = payload.row
  const style = directionOf(row)
  const r = markerRadius(row.structure_dv01)
  const opacity = markerOpacity(row)
  // "the size was not read" is a block cap or an imputed notional: the LEVEL is
  // real, so the mark is drawn — the AREA is a floor, so its outline is dashed.
  const dashed = sizeNotRead(row)
  const stroke = style.color
  const common = {
    stroke,
    strokeWidth: dashed ? 1 : style.filled ? 0 : 1.25,
    strokeDasharray: dashed ? '2 1.5' : undefined,
    fill: style.filled ? style.color : 'none',
    fillOpacity: style.filled ? opacity : 0,
    strokeOpacity: opacity,
  }

  if (payload.pinned != null) {
    // Off-domain: a small hollow chevron at the edge it was pinned to. It is
    // visible, and it owns none of the axis.
    return (
      <path
        d={chevronPath(cx, cy, Math.min(r, 6), payload.pinned)}
        fill="none"
        stroke={stroke}
        strokeWidth={1.25}
        strokeOpacity={opacity}
      />
    )
  }
  if (style.shape === 'up') return <path d={upTrianglePath(cx, cy, r)} {...common} />
  if (style.shape === 'down') return <path d={downTrianglePath(cx, cy, r)} {...common} />
  if (style.shape === 'diamond') return <path d={diamondPath(cx, cy, r)} {...common} />
  if (style.shape === 'ring') {
    return <circle cx={cx} cy={cy} r={r} fill="none" stroke={DIRECTION_NEUTRAL} strokeWidth={1} strokeOpacity={0.6} />
  }
  return <circle cx={cx} cy={cy} r={r} {...common} />
}

function MarkLegend({
  showPackageLegs,
  includeOffMarket,
  midSource,
}: {
  showPackageLegs: boolean
  includeOffMarket: boolean
  midSource: MidSource
}): JSX.Element {
  // The size key calls markerRadius() itself, so it cannot drift from the
  // marks it is a key for.
  const sizes = legendSizeRefs()
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[9.5px] text-slate-500">
      <span className="flex items-center gap-1">
        <svg width="14" height="14" aria-hidden>
          <path d={upTrianglePath(7, 7, 5)} fill={DIRECTION_SKY} fillOpacity={0.9} />
        </svg>
        dealer RECEIVED fixed (long duration)
      </span>
      <span className="flex items-center gap-1">
        <svg width="14" height="14" aria-hidden>
          <path d={downTrianglePath(7, 7, 5)} fill={DIRECTION_AMBER} fillOpacity={0.9} />
        </svg>
        dealer PAID fixed (short duration)
      </span>
      <span className="flex items-center gap-1">
        <svg width="14" height="14" aria-hidden>
          <circle cx="7" cy="7" r="4" fill={DIRECTION_NEUTRAL} />
        </svg>
        no call
      </span>
      {/* THE KEY MUST DESCRIBE THE CHART ON SCREEN. A dashed swatch captioned
          "at print times" beside a solid modelled curve is a legend for a
          different chart, and the reader believes the legend. */}
      {midSource !== 'none' ? (
        <span className="flex items-center gap-1">
          <svg width="24" height="10" aria-hidden>
            <line
              x1="1"
              y1="5"
              x2="23"
              y2="5"
              stroke={ANALYTICS_COLORS.slate400}
              strokeWidth={midSource === 'grid' ? 1.5 : 1.25}
              strokeDasharray={midSource === 'grid' ? undefined : '4 3'}
            />
          </svg>
          {midSource === 'grid'
            ? 'modelled 1-min par mid — the same curve every mark was repriced against, not a quoted mid'
            : 'model mid at print times — reconstructed from deviation, not a quoted mid'}
        </span>
      ) : null}
      <span className="flex items-center gap-1">
        <svg width={sizes.length * 30} height="28" aria-hidden>
          {sizes.map((s, i) => (
            <g key={s.dv01}>
              <circle
                cx={15 + i * 30}
                cy={12}
                r={s.r}
                fill="none"
                stroke={ANALYTICS_COLORS.slate500}
              />
              <text
                x={15 + i * 30}
                y={26}
                textAnchor="middle"
                fill={ANALYTICS_COLORS.slate500}
                fontSize="7.5"
              >
                {s.dv01 / 1000}k
              </text>
            </g>
          ))}
        </svg>
        size = structure DV01/bp
      </span>
      {showPackageLegs ? (
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden>
            <circle cx="7" cy="7" r="4.5" fill="none" stroke={DIRECTION_NEUTRAL} />
          </svg>
          package leg — level only, direction not resolvable per leg
        </span>
      ) : null}
      {includeOffMarket ? (
        <span className="flex items-center gap-1">
          <svg width="14" height="14" aria-hidden>
            <path d={diamondPath(7, 7, 5)} fill="none" stroke={ANALYTICS_COLORS.slate400} />
          </svg>
          off-market (fee-bearing) — edge-pinned, outside the y-domain
        </span>
      ) : null}
      <span className="ml-auto">marker outline dashed = size not read (block cap / imputed)</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// The tooltip
// ---------------------------------------------------------------------------

function Row({ k, v }: { k: string; v: string }): JSX.Element {
  return (
    <div className="flex gap-2">
      <span className="w-[92px] shrink-0 text-slate-500">{k}</span>
      <span className="text-slate-200">{v}</span>
    </div>
  )
}

function PrintTooltip(props: {
  active?: boolean
  payload?: { payload?: MarkDatum | MidPoint }[]
}): JSX.Element | null {
  if (!props.active || !props.payload?.length) return null
  const hit = props.payload.find((p) => p.payload && 'row' in (p.payload as MarkDatum))
  if (!hit) return null
  const d = hit.payload as MarkDatum
  const r = d.row
  const style = directionOf(r)
  const vis = tsMillis(r.visibility_timestamp)
  return (
    <div className="rounded border border-slate-700 bg-slate-900 p-2 font-mono text-[10px] leading-tight">
      <Row k="executed" v={`${fmtEtStamp(d.t)} ET`} />
      <Row
        k="public"
        v={`${fmtEtStamp(vis)} ET  (+${fmtLagSeconds(r.visibility_lag_seconds)})`}
      />
      <div className="my-1 h-px bg-slate-800" />
      <div className="flex gap-2">
        <span className="w-[92px] shrink-0 text-slate-500">direction</span>
        <span style={{ color: style.color }}>{style.label}</span>
      </div>
      <Row
        k="p / 2p−1"
        v={`${fmtNum(r.p, 3)} / ${fmtNum(r.signed_weight, 3)}`}
      />
      <div className="my-1 h-px bg-slate-800" />
      <Row k="traded" v={`${fmtRate(r.traded_pct)} %`} />
      <Row
        k="mid (recon)"
        v={r.mid_pct == null ? '— (not invertible for this row)' : `${fmtRate(r.mid_pct)} %`}
      />
      <Row k="deviation" v={fmtSignedBps(r.deviation_bps)} />
      <Row
        k="tau"
        v={`${fmtNum(r.tau_bps, 3)} bp${r.in_dead_zone ? '  — INSIDE THE DEAD ZONE' : ''}`}
      />
      <div className="my-1 h-px bg-slate-800" />
      <Row
        k="notional"
        v={`${fmtNotional(r.notional)}${sizeNotRead(r) ? '  ≥ (block cap — size not read)' : ''}`}
      />
      <Row k="structure DV01" v={`${fmtNotional(r.structure_dv01)} /bp`} />
      <Row k="kind" v={`${r.kind} · ${r.n_legs} leg${r.n_legs === 1 ? '' : 's'}`} />
      <Row
        k="tenor"
        v={`${r.tenor_display} · ${fmtNum(r.tenor_years, 4)}y · ${r.effective_date} → ${r.expiration_date}`}
      />
      <Row
        k="forward"
        v={`${fmtNum(r.forward_start_years, 4)}y${r.forward_label ? ` (${r.forward_label})` : ''}`}
      />
      <Row k="stt / venue" v={`${r.special_tenor_type} · ${r.venue_class}`} />
      <div className="my-1 h-px bg-slate-800" />
      <Row
        k="curve"
        v={`${r.curve_name ?? '—'} @ ${r.snapshot_policy ?? '—'} (+${fmtLagSeconds(r.snapshot_lag_seconds)})`}
      />
      {d.pinned ? (
        <div className="mt-1 text-amber-300">
          off-domain, pinned to the {d.pinned} edge — true rate {fmtRate(d.trueY)}%
        </div>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The deviation strip
// ---------------------------------------------------------------------------

/**
 * Signed deviation per print, as stems from zero, on its OWN axis and its own
 * chart. Never a second y-scale on the price plot.
 *
 * Hand-drawn SVG rather than recharts, for one measured reason: a recharts
 * custom Scatter shape receives only filtered SVG props plus cx/cy/payload —
 * `filterProps(this.props, false)` strips the axis objects — so a stem has no
 * way to find the pixel of its own zero line, and `<Bar>` has no bandwidth on a
 * numeric time axis. This shares the price chart's exact time domain and left
 * gutter, so the two panels line up column for column.
 */
function DeviationStrip({
  rows,
  tDom,
}: {
  rows: PrintRow[]
  tDom: [number, number] | null
}): JSX.Element | null {
  const pts = useMemo(
    () =>
      rows
        .filter((r) => r.kind === 'OUTRIGHT' && r.is_off_market !== true)
        .map((r) => ({ t: tsMillis(r.execution_timestamp), dev: Number(r.deviation_bps), row: r }))
        .filter((p): p is { t: number; dev: number; row: PrintRow } => p.t != null && Number.isFinite(p.dev)),
    [rows],
  )
  // b0 is taken over the SAME population the stems are drawn from. Over all
  // rows it would mix a CURVE's structure-level bias into the reference line
  // for a set of outright deviations — invisible with the default toggles,
  // because they are then the same set, and wrong the moment package legs are
  // switched on.
  const biases = useMemo(
    () =>
      rows
        .filter((r) => r.kind === 'OUTRIGHT' && r.is_off_market !== true)
        .map((r) => (r.mid_bias_bps == null ? null : Number(r.mid_bias_bps)))
        .filter((x): x is number => x != null && Number.isFinite(x))
        .sort((a, b) => a - b),
    [rows],
  )
  if (tDom == null || pts.length === 0) return null

  const b0 = biases.length ? biases[Math.floor(biases.length / 2)]! : null
  const m = Math.max(0.05, ...pts.map((p) => Math.abs(p.dev)), Math.abs(b0 ?? 0)) * 1.1
  const plotTop = DEV_MARGIN.top
  const plotH = DEV_H - DEV_MARGIN.top - DEV_MARGIN.bottom
  const zeroY = plotTop + plotH / 2
  // Symmetric domain [-m, +m], so zero is the exact vertical middle. The whole
  // reason the domain is symmetric.
  const yOf = (v: number) => zeroY - (v / m) * (plotH / 2)
  const [t0, t1] = tDom
  const span = Math.max(1, t1 - t0)

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[9.5px] uppercase tracking-wider text-slate-600">
        deviation from the reconstructed mid, bp — how far off mid it traded
      </span>
      <div style={{ paddingLeft: DEV_MARGIN.left, paddingRight: DEV_MARGIN.right }}>
        <svg
          width="100%"
          height={DEV_H}
          viewBox={`0 0 1000 ${DEV_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="signed deviation per print"
        >
          <line x1={0} y1={zeroY} x2={1000} y2={zeroY} stroke={ANALYTICS_COLORS.slate700} />
          {b0 != null ? (
            <line
              x1={0}
              y1={yOf(b0)}
              x2={1000}
              y2={yOf(b0)}
              stroke={ANALYTICS_COLORS.slate500}
              strokeDasharray="3 3"
            />
          ) : null}
          {pts.map((p, i) => {
            const x = ((p.t - t0) / span) * 1000
            return (
              <line
                key={`${p.row.package_id}-${i}`}
                x1={x}
                y1={zeroY}
                x2={x}
                y2={yOf(p.dev)}
                // THE SAME CALL THE MARK ABOVE MAKES. Never sign(deviation):
                // the producer sets the side from the BIAS-CORRECTED deviation
                // (backfill_dealer_direction.py:961, `dealer_side(dev - b0)`),
                // so every print between 0 and b0 is called on the opposite
                // side from its raw deviation — and a stem coloured by
                // `dev >= 0` would paint exactly those the opposite colour
                // from their own mark in the chart directly above. The stem's
                // side of zero is the second channel; the b0 line is drawn so
                // the two read together.
                stroke={stemColor(p.row)}
                strokeWidth={1}
                strokeOpacity={0.85}
                vectorEffect="non-scaling-stroke"
              />
            )
          })}
        </svg>
      </div>
      <div className="flex justify-between text-[9px] text-slate-600" style={{ paddingLeft: DEV_MARGIN.left }}>
        <span>±{m.toFixed(2)} bp</span>
        <span>{b0 == null ? '' : `b0 (median mid bias) ${fmtSignedBps(b0)}`}</span>
      </div>
    </div>
  )
}
