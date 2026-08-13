// ABOUTME: One meeting-dated STIR instrument, one day, one rate index, with the
// dealer's side on every print. The web port of
// notebooks/exploratory/dealer_flow_chart.ipynb. See ../stir-flow.logic.ts for
// the three measured facts that decide how it may be drawn.
import { NextResponse } from 'next/server'
import { analyticsQuery } from '@/lib/db'
import { BadRequest } from '../route.logic'
import {
  buildPrintTimeMid,
  buildStirDisclosures,
  latestStirDateSql,
  parseStirFlowParams,
  type StirFlowCounts,
  type StirFlowResponse,
  type StirFlowRow,
  stirFlowCountsSql,
  stirFlowSql,
} from '../stir-flow.logic'

type CountsRow = {
  on_market_mid: number
  tick_rule: number
  off_market: number
  off_index: number
  no_mid: number
  curve_suspect: number
}

export async function GET(req: Request) {
  const sp = new URL(req.url).searchParams
  try {
    // Parse FIRST: a refusal must cost a round trip to nothing.
    const parsed = parseStirFlowParams(sp)

    let date = parsed.date
    if (date == null) {
      const latest = await analyticsQuery(latestStirDateSql(), [])
      date = (latest.rows[0]?.as_of_date as string | null) ?? null
      if (date == null) throw new Error('no classified STIR flow is published yet')
    }
    const p = { ...parsed, date }

    const q = stirFlowSql(p)
    const c = stirFlowCountsSql(p)
    const [res, cnt] = await Promise.all([
      analyticsQuery(q.text, q.values),
      analyticsQuery(c.text, c.values),
    ])

    // DISTINCT ON forces ORDER BY unit_key first, so the wire order is by unit,
    // not by time. The chart is about time.
    const rows = (res.rows as StirFlowRow[])
      .slice()
      .sort(
        (a, b) =>
          new Date(a.execution_timestamp).getTime() -
          new Date(b.execution_timestamp).getTime(),
      )

    const cr = (cnt.rows[0] ?? {}) as Partial<CountsRow>
    const n = (v: unknown): number => (v == null ? 0 : Number(v))
    const counts: StirFlowCounts = {
      drawn: rows.length,
      onMarketMid: n(cr.on_market_mid),
      tickRule: n(cr.tick_rule),
      offMarket: n(cr.off_market),
      offIndex: n(cr.off_index),
      noMid: n(cr.no_mid),
      curveSuspect: n(cr.curve_suspect),
    }

    const mid = buildPrintTimeMid(rows)

    // EVERY distinct value, not rows[0]'s — a day priced against two curve
    // builds should say so rather than silently reporting the first.
    const distinct = (xs: (string | null)[]): string | null => {
      const v = [...new Set(xs.filter((x): x is string => !!x))].sort()
      return v.length ? v.join(' · ') : null
    }

    const body: StirFlowResponse = {
      date,
      tenorQuery: p.tenorQuery,
      rateIndex: p.rateIndex,
      clock: 'execution',
      filters: {
        includeOffMarket: p.includeOffMarket,
        includeTickRule: p.includeTickRule,
      },
      rows,
      mid,
      counts,
      disclosures: [],
      curve_name: distinct(rows.map((r) => r.curve_name)),
      code_vintage: distinct(rows.map((r) => r.code_vintage)),
    }
    body.disclosures = buildStirDisclosures({
      counts,
      filters: body.filters,
      rateIndex: p.rateIndex,
      tenorQuery: p.tenorQuery,
      curveName: body.curve_name,
      midPoints: mid.length,
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
