// ABOUTME: One day of USD-swap prints for one tenor, on the EXECUTION clock,
// against the continuous 1-minute par grid, with each mark's own mid still
// reconstructed from its deviation. See ../prints.logic.ts for the measured
// agreement between the two, and for why a package leg can never carry a mid.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import { DD_GENERATION } from '@/lib/dealer-direction-tables'
import { BadRequest } from '../route.logic'
import {
  assertNoPackageMid,
  buildDisclosures,
  latestDateSql,
  median,
  midGridAvailabilitySql,
  midGridSql,
  midWindow,
  parsePrintsParams,
  type MidGrid,
  type MidGridPoint,
  type PrintRow,
  type PrintsCounts,
  type PrintsProvenance,
  type PrintsResponse,
  printsCountsSql,
  printsSql,
} from '../prints.logic'

type CountsRow = {
  on_market: number
  off_market: number
  forward_start: number
  special_tenor_type: number
  unknown_special_tenor_type: number
  package_legs: number
  strict_subset: number
}

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    // Parse FIRST, and only then touch the database: a refusal must cost a
    // round trip to nothing.
    const parsed = parsePrintsParams(sp)

    let date = parsed.date
    if (date == null) {
      const latest = await analyticsQuery(latestDateSql(), [])
      date = (latest.rows[0]?.as_of_date as string | null) ?? null
      if (date == null) {
        throw new Error('no dealer-direction rows are published yet')
      }
    }
    const p = { ...parsed, date }

    const q = printsSql(p)
    const c = printsCountsSql(p)
    // Availability does NOT depend on the rows, so it rides along in phase 1.
    // It answers a question the grid query cannot: an empty result means "this
    // tenor has no grid at all" (Fed Funds 7Y/20Y/30Y) or "the grid exists but
    // this window is a hole", and those are different sentences on screen.
    const [res, cnt, avail] = await Promise.all([
      analyticsQuery(q.text, q.values),
      analyticsQuery(c.text, c.values),
      analyticsQuery(midGridAvailabilitySql(), [p.rateIndex, p.tenor]),
    ])

    const rows = res.rows as PrintRow[]
    // The control, not a comment. Throws rather than rendering a fiction.
    assertNoPackageMid(rows)

    // --- phase 2: the continuous mid over the window the marks actually span --
    //
    // A SECOND ROUND TRIP, DELIBERATELY. The window could be computed inside
    // the grid statement as a CTE, which would save ~20ms — at the cost of
    // restating printsSql's twelve-clause driving predicate in a second place,
    // where it would drift out of step the first time a filter is added and
    // silently draw the line over the wrong span. The window is taken from the
    // rows that are actually drawn, so it cannot disagree with them.
    const gridAvailable = avail.rows[0]?.ok === true
    const window = midWindow(rows)
    let points: MidGridPoint[] = []
    let gridCurve: string | null = null
    let gridPolicy: string | null = null
    if (gridAvailable && window != null) {
      const g = midGridSql(p.rateIndex, p.tenor, window[0], window[1])
      const gr = await analyticsQuery(g.text, g.values)
      const raw = gr.rows as {
        ts: string | Date
        mid_pct: number | string
        curve_name: string | null
        snapshot_policy: string | null
      }[]
      points = raw.map((r) => ({
        ts: r.ts instanceof Date ? r.ts.toISOString() : String(r.ts),
        mid_pct: Number(r.mid_pct),
      }))
      const names = [...new Set(raw.map((r) => r.curve_name).filter((x): x is string => !!x))]
      const pols = [...new Set(raw.map((r) => r.snapshot_policy).filter((x): x is string => !!x))]
      gridCurve = names.length ? names.sort().join(' · ') : null
      gridPolicy = pols.length ? pols.sort().join(' · ') : null
    }
    const mid: MidGrid = {
      available: gridAvailable,
      points,
      curve_name: gridCurve,
      snapshot_policy: gridPolicy,
      window,
    }

    const cr = (cnt.rows[0] ?? {}) as Partial<CountsRow>
    const n = (v: unknown): number => (v == null ? 0 : Number(v))

    const counts: PrintsCounts = {
      drawn: rows.length,
      onMarket: n(cr.on_market),
      withMid: rows.filter((r) => r.mid_pct != null).length,
      dropped: {
        offMarket: n(cr.off_market),
        forwardStart: n(cr.forward_start),
        specialTenorType: n(cr.special_tenor_type),
        unknownSpecialTenorType: n(cr.unknown_special_tenor_type),
        packageLegs: n(cr.package_legs),
      },
    }

    // Exact, not estimated: the strict subset is a FILTER inside the same scan
    // that produced the band total. Null in strict mode, where the question
    // does not arise.
    const admittedByLoosening =
      p.tenorMatch === 'band' ? n(cr.on_market) - n(cr.strict_subset) : null

    const years = rows
      .map((r) => (r.tenor_years == null ? null : Number(r.tenor_years)))
      .filter((x): x is number => x != null && Number.isFinite(x))
    const observedTenorYears: [number, number] | null = years.length
      ? [Math.min(...years), Math.max(...years)]
      : null

    const deadZone = rows.filter((r) => r.in_dead_zone === true).length
    const sizeNotRead = rows.filter(
      (r) => r.is_capped === true || r.is_notional_capped === true || r.notional_imputed === true,
    ).length
    const visLags = rows.map((r) => (r.visibility_lag_seconds == null ? null : Number(r.visibility_lag_seconds)))

    // EVERY distinct value, not rows[0]'s. The day is ORDER BY
    // execution_timestamp and the first print lands ~20:0x ET the previous
    // evening — out of session — so rows[0].snapshot_policy would describe a
    // whole day of STRICT_1MIN_IN_SESSION prints by the out-of-session policy
    // that priced the earliest one. A single-valued day still collapses to the
    // one string.
    const distinct = (xs: (string | null)[]): string | null => {
      const v = [...new Set(xs.filter((x): x is string => x != null && x !== ''))].sort()
      return v.length === 0 ? null : v.join(' · ')
    }

    const provenance: PrintsProvenance = {
      curve_name: distinct(rows.map((r) => r.curve_name)),
      snapshot_policy: distinct(rows.map((r) => r.snapshot_policy)),
      median_snapshot_lag_seconds: median(
        rows.map((r) => (r.snapshot_lag_seconds == null ? null : Number(r.snapshot_lag_seconds))),
      ),
      median_visibility_lag_seconds: median(visLags),
      max_visibility_lag_seconds: visLags.reduce<number | null>(
        (m, x) => (x == null ? m : m == null || x > m ? x : m),
        null,
      ),
      dead_zone_share: rows.length ? deadZone / rows.length : 0,
      size_not_read: sizeNotRead,
      tape_generation: rows[0]?.tape_generation ?? '—',
      code_vintage: rows[0]?.code_vintage ?? '—',
      dd_generation: DD_GENERATION,
    }

    const body: PrintsResponse = {
      date,
      tenor: p.tenor,
      rateIndex: p.rateIndex,
      venueClass: p.venueClass,
      series: 'FLOW',
      clock: 'execution',
      filters: {
        kinds: p.kinds,
        specialTenorTypes: p.specialTenorTypes,
        fwdMaxYears: p.fwdMaxYears,
        tenorMatch: p.tenorMatch,
        includeOffMarket: p.includeOffMarket,
      },
      looseTenor: p.tenorMatch === 'band',
      admittedByLoosening,
      observedTenorYears,
      rows,
      mid,
      counts,
      disclosures: [],
      provenance,
    }
    body.disclosures = buildDisclosures({
      filters: body.filters,
      counts,
      provenance,
      looseTenor: body.looseTenor,
      admittedByLoosening,
      observedTenorYears,
      tenor: p.tenor,
      mid,
      rateIndex: p.rateIndex,
    })

    return NextResponse.json(body, {
      headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' },
    })
  } catch (error: unknown) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 })
    }
    // A DB failure is a 500 carrying the message, never a silently empty chart:
    // "no prints today" and "the query blew up" look identical on an empty
    // scatter and only one of them is about the market.
    const message = error instanceof Error ? error.message : 'failed'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
