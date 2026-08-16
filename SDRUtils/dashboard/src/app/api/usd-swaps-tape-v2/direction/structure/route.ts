// ABOUTME: One CURVE or FLY structure, one day: every print of it, the dealer's
// side, and a continuous mid built from the same legs of the 1-minute grid.
// See ../structure.logic.ts for the measured arithmetic and the three reasons
// this is not a filter change on the outright endpoint.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import { BadRequest } from '../route.logic'
import {
  buildStructureDisclosures,
  gridTenorsFor,
  latestStructureDateSql,
  parseStructureParams,
  structureCountsSql,
  structureLabel,
  structureMidSql,
  structurePrintsSql,
  type StructureCounts,
  type StructureMidPoint,
  type StructureResponse,
  type StructureRow,
} from '../structure.logic'

const MID_PAD_MINUTES = 15

type CountsRow = {
  on_market: number
  off_market: number
  forward_start: number
  other_rule: number
  all_of_this_structure: number
}

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    // Parse FIRST: a refusal must cost a round trip to nothing.
    const parsed = parseStructureParams(sp)

    let date = parsed.date
    if (date == null) {
      const latest = await analyticsQuery(latestStructureDateSql(), [])
      date = (latest.rows[0]?.as_of_date as string | null) ?? null
      if (date == null) throw new Error('no dealer-direction rows are published yet')
    }
    const p = { ...parsed, date }

    const q = structurePrintsSql(p)
    const c = structureCountsSql(p)
    const [res, cnt] = await Promise.all([
      analyticsQuery(q.text, q.values),
      analyticsQuery(c.text, c.values),
    ])

    const rows = (res.rows as StructureRow[]).map((r) => ({
      ...r,
      // pg hands NUMERIC back as a string; the chart does arithmetic on these.
      traded_bp: Number(r.traded_bp),
      mid_bp: Number(r.mid_bp),
      deviation_bps: Number(r.deviation_bps),
    }))

    const cr = (cnt.rows[0] ?? {}) as Partial<CountsRow>
    const n = (v: unknown): number => (v == null ? 0 : Number(v))
    const counts: StructureCounts = {
      drawn: rows.length,
      onMarket: n(cr.on_market),
      offMarket: n(cr.off_market),
      forwardStart: n(cr.forward_start),
      otherRule: n(cr.other_rule),
      allOfThisStructure: n(cr.all_of_this_structure),
    }

    // --- the continuous mid over the window the prints actually span --------
    //
    // A SECOND ROUND TRIP, deliberately: the window comes from the rows that
    // are drawn, so it cannot disagree with them, and the alternative is
    // restating this endpoint's driving predicate in a second place where it
    // would drift.
    // THE GRID IS SPOT-ONLY. Measured: 0 of 4,529 forward-start legs match it
    // (max residual 35.6 bp). Drawing a spot par spread under forward-starting
    // marks puts them tens of bp off a line that is not their instrument, so
    // the line is WITHHELD rather than drawn wrong. Each print keeps its own
    // exact mid, which is the forward structure mid the classifier used.
    const forwardDrawn = rows.filter((r) => Number(r.fwd_max_years ?? 0) > 0.02).length

    let mid: StructureMidPoint[] = []
    let curveName: string | null = null
    if (rows.length > 0 && forwardDrawn === 0) {
      let lo = Number.POSITIVE_INFINITY
      let hi = Number.NEGATIVE_INFINITY
      for (const r of rows) {
        const t = new Date(r.execution_timestamp).getTime()
        if (!Number.isFinite(t)) continue
        if (t < lo) lo = t
        if (t > hi) hi = t
      }
      if (Number.isFinite(lo) && Number.isFinite(hi)) {
        const pad = MID_PAD_MINUTES * 60_000
        // The tenor tuple as the GRID spells it — the fuzzy marker is stripped
        // for the lookup only; identity keeps it.
        const gridTenors = gridTenorsFor(rows[0]!.tenor_tuple ?? p.tenors)
        const g = structureMidSql(
          p.kind, p.rateIndex, gridTenors,
          new Date(lo - pad).toISOString(), new Date(hi + pad).toISOString(),
        )
        const gr = await analyticsQuery(g.text, g.values)
        const raw = gr.rows as { ts: string | Date; mid_bp: number | string; curve_name: string | null }[]
        mid = raw.map((x) => ({
          ts: x.ts instanceof Date ? x.ts.toISOString() : String(x.ts),
          mid_bp: Number(x.mid_bp),
        }))
        const names = [...new Set(raw.map((x) => x.curve_name).filter((s): s is string => !!s))]
        curveName = names.length ? names.sort().join(' · ') : null
      }
    }

    const body: StructureResponse = {
      date,
      kind: p.kind,
      tenors: p.tenors,
      label: structureLabel(p.kind, p.tenors),
      rateIndex: p.rateIndex,
      venueClass: p.venueClass,
      clock: 'execution',
      levelUnit: 'bp',
      rows,
      mid,
      counts,
      disclosures: [],
      curve_name: curveName ?? rows[0]?.curve_name ?? null,
    }
    body.disclosures = buildStructureDisclosures({
      kind: p.kind,
      tenors: p.tenors,
      rateIndex: p.rateIndex,
      counts,
      midPoints: mid.length,
      curveName: body.curve_name,
      ruleStrict: p.ruleStrict,
      includeOffMarket: p.includeOffMarket,
      forwardDrawn,
    })

    return NextResponse.json(body, {
      headers: { 'Cache-Control': 'private, max-age=120, stale-while-revalidate=300' },
    })
  } catch (error: unknown) {
    if (error instanceof BadRequest) {
      return NextResponse.json({ error: error.message }, { status: 400 })
    }
    // Never a silently empty chart: "nothing traded" and "the query blew up"
    // look identical on an empty scatter and only one is about the market.
    const message = error instanceof Error ? error.message : 'failed'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
