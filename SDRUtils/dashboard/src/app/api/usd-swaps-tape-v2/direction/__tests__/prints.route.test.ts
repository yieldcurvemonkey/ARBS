// ABOUTME: The prints route handler, with @/lib/db mocked.
//
// prints.logic.test.ts pins the predicates. This pins the WIRING: that an
// off-market row cannot reach the default response, that a package leg cannot
// carry a mid however the query is edited, that a refusal costs no query, and
// that a DB failure is a 500 rather than an empty chart.
import { beforeEach, describe, expect, it, jest } from '@jest/globals'

const analyticsQueryMock = jest.fn<any>()

jest.unstable_mockModule('@/lib/db', () => ({
  query: jest.fn(async () => ({ rows: [] })),
  analyticsQuery: analyticsQueryMock,
  withClient: jest.fn(),
}))

const { GET } = await import('../prints/route')

const req = (q: string) => new Request(`http://x/api/usd-swaps-tape-v2/direction/prints?${q}`)

const COUNTS = {
  on_market: 119,
  off_market: 10,
  forward_start: 57,
  special_tenor_type: 0,
  unknown_special_tenor_type: 0,
  package_legs: 120,
  strict_subset: 119,
}

/** A minimal but complete print row, in the shape the SQL returns. */
function row(over: Record<string, unknown> = {}) {
  return {
    package_id: 'pkg-1',
    trade_id: 'tr-1',
    execution_timestamp: '2026-06-18T14:03:00.000Z',
    visibility_timestamp: '2026-06-18T14:04:00.000Z',
    visibility_lag_seconds: 60,
    dealer_direction: 'RECEIVED',
    dealer_sign: 1,
    p: 0.62,
    signed_weight: 0.24,
    deviation_bps: -1.04,
    tau_bps: 0.35,
    mid_bias_bps: 0.004,
    in_dead_zone: true,
    kind: 'OUTRIGHT',
    n_legs: 1,
    rule: 'RATE_VS_MID',
    special_tenor_type: 'STANDARD',
    rate_index: 'SOFR',
    venue_class: 'D2C',
    is_block: false,
    is_capped: false,
    notional_imputed: false,
    structure_dv01: 42_000,
    notional: 50_000_000,
    is_notional_capped: false,
    effective_date: '2026-06-22',
    expiration_date: '2036-06-22',
    tenor_years: 10.0027,
    tenor_display: '10Y',
    forward_start_years: 0,
    forward_label: null,
    is_off_market: false,
    traded_pct: 4.03536,
    mid_pct: 4.04576,
    curve_name: 'USD-SOFR-1D',
    curve_timestamp: '2026-06-18T14:03:00.000Z',
    snapshot_lag_seconds: 0,
    snapshot_policy: 'STRICT_1MIN_IN_SESSION',
    tape_generation: 'v3',
    code_vintage: 'abc123',
    ...over,
  }
}

/** The route fires the rows query and the counts query together. */
function serve(rows: unknown[], counts: Record<string, unknown> = COUNTS) {
  analyticsQueryMock.mockImplementation(async (sql: string) =>
    /AS strict_subset/.test(sql) ? { rows: [counts] } : { rows },
  )
}

beforeEach(() => {
  analyticsQueryMock.mockReset()
  serve([])
})

describe('the default response', () => {
  it('carries the rows, the measured counts and the provenance', async () => {
    serve([row(), row({ package_id: 'pkg-2', mid_pct: 4.03022, traded_pct: 4.0288 })])
    const res = await GET(req('date=2026-06-18&tenor=10Y'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.rows).toHaveLength(2)
    expect(body.counts.drawn).toBe(2)
    expect(body.counts.withMid).toBe(2)
    expect(body.counts.onMarket).toBe(119)
    expect(body.counts.dropped.offMarket).toBe(10)
    expect(body.counts.dropped.forwardStart).toBe(57)
    expect(body.counts.dropped.packageLegs).toBe(120)
    expect(body.clock).toBe('execution')
    expect(body.series).toBe('FLOW')
    expect(body.venueClass).toBe('D2C')
    expect(body.provenance.curve_name).toBe('USD-SOFR-1D')
    expect(body.provenance.dd_generation).toBe('v1')
    expect(body.provenance.tape_generation).toBe('v3')
    expect(body.provenance.median_visibility_lag_seconds).toBe(60)
    expect(body.observedTenorYears).toEqual([10.0027, 10.0027])
    // strict mode: the question does not arise
    expect(body.looseTenor).toBe(false)
    expect(body.admittedByLoosening).toBeNull()
  })

  it('an off-market fixture row never reaches it', async () => {
    // THE LEAK TEST. The predicate lives in the SQL builder, so this fails the
    // moment the route stops using it or the builder drops it — the mock
    // returns a mixed set and the default request must return only the
    // on-market rows, with the hidden ones REPORTED rather than vanished.
    analyticsQueryMock.mockImplementation(async (sql: string, params: unknown[]) => {
      if (/AS strict_subset/.test(sql)) return { rows: [COUNTS] }
      const all = [row(), row({ package_id: 'pkg-off', is_off_market: true, mid_pct: null })]
      // Stand in for Postgres: apply the builder's own off-market predicate.
      const filtered = /COALESCE\(l\.is_off_market, false\)\s+= false/.test(sql)
        ? all.filter((r) => r.is_off_market !== true)
        : all
      expect(params).toContain('10Y')
      return { rows: filtered }
    })
    const body = await (await GET(req('date=2026-06-18&tenor=10Y'))).json()
    expect(body.rows).toHaveLength(1)
    expect(body.rows.every((r: { is_off_market: boolean }) => r.is_off_market === false)).toBe(true)
    expect(body.counts.dropped.offMarket).toBe(10)
  })

  it('a CURVE leg row carries mid_pct: null and is not counted as a mid', async () => {
    // THE PER-LEG-MID GUARD. deviation_bps for a CURVE is a structure spread
    // under weights (-1, 1); inverting it per leg is the inversion you cannot
    // recover from once a reader has seen it drawn.
    serve([row(), row({ package_id: 'pkg-curve', kind: 'CURVE', n_legs: 2, mid_pct: null })])
    const body = await (await GET(req('date=2026-06-18&tenor=10Y&kinds=OUTRIGHT,CURVE'))).json()
    const curve = body.rows.find((r: { kind: string }) => r.kind === 'CURVE')
    expect(curve.mid_pct).toBeNull()
    expect(body.counts.drawn).toBe(2)
    expect(body.counts.withMid).toBe(1)
  })

  it('500s rather than serving a per-leg mid if one ever appears', async () => {
    serve([row({ kind: 'FLY', n_legs: 3, mid_pct: 4.01 })])
    const res = await GET(req('date=2026-06-18&tenor=10Y&kinds=OUTRIGHT,FLY'))
    expect(res.status).toBe(500)
    expect((await res.json()).error).toMatch(/cannot be inverted into per-leg mids/)
  })

  it('reports EVERY snapshot policy the day used, not the first row\'s', async () => {
    // The rows arrive ORDER BY execution_timestamp and the first print lands
    // ~20:0x ET the PREVIOUS evening — out of session. Reading provenance off
    // rows[0] would label a whole day of STRICT_1MIN_IN_SESSION prints with the
    // out-of-session policy that priced the earliest one, in the header line
    // that tells the reader what the mid is.
    serve([
      row({ snapshot_policy: 'ASOF_2H_OUT_OF_SESSION' }),
      row({ package_id: 'pkg-2' }),
      row({ package_id: 'pkg-3' }),
    ])
    const body = await (await GET(req('date=2026-06-18&tenor=10Y'))).json()
    expect(body.provenance.snapshot_policy).toBe(
      'ASOF_2H_OUT_OF_SESSION · STRICT_1MIN_IN_SESSION',
    )
    // a single-valued day still collapses to the one string
    expect(body.provenance.curve_name).toBe('USD-SOFR-1D')
  })

  it('reports admittedByLoosening exactly in band mode', async () => {
    serve([row()], { ...COUNTS, on_market: 120, strict_subset: 119 })
    const body = await (await GET(req('date=2026-06-18&tenor=10Y&tenorMatch=band'))).json()
    expect(body.looseTenor).toBe(true)
    expect(body.admittedByLoosening).toBe(1)
  })
})

describe('the refusals reach the client, and cost no query', () => {
  it.each([
    ['tenor=13Y', /must be one of/],
    ['tenor=10Y&rateIndex=ALL', /SOFR-FF basis/],
    ['tenor=10Y&series=LIFECYCLE', /SEASONED/],
    ['tenor=10Y&fwdMaxYears=0.5', /66bp/],
    ['tenor=10Y&date=2024-01-01', /2024-07-01/],
    ['tenor=10Y&kinds=SPREADOVER', /kinds must be/],
    ['tenor=10Y&specialTenorTypes=NEW_THING', /allow-list/],
    ['tenor=10Y&venueClass=ALL', /never summed/],
    ['', /tenor is required/],
  ])('%s -> 400', async (q, pattern) => {
    const res = await GET(req(q))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toMatch(pattern as RegExp)
    expect(analyticsQueryMock).not.toHaveBeenCalled()
  })
})

describe('failures are loud', () => {
  it('a DB failure is a 500 carrying the message, not an empty chart', async () => {
    analyticsQueryMock.mockRejectedValue(new Error('relation does not exist'))
    const res = await GET(req('date=2026-06-18&tenor=10Y'))
    expect(res.status).toBe(500)
    expect((await res.json()).error).toMatch(/relation does not exist/)
  })
})

describe('the disclosures travel with the payload', () => {
  it('carries provenance and the FOMC multiples when FOMC is included', async () => {
    serve([row({ special_tenor_type: 'FOMC' })])
    const body = await (
      await GET(req('date=2026-06-18&tenor=10Y&specialTenorTypes=STANDARD,FOMC'))
    ).json()
    const text = body.disclosures.join('\n')
    expect(text).toContain('6.8')
    expect(text).toContain('4.0')
    expect(text).toMatch(/discrete meeting steps/)
    expect(text).toMatch(/tape v3/)
  })

  it('resolves the latest published day when no date is given', async () => {
    analyticsQueryMock.mockImplementation(async (sql: string) => {
      if (/max\(as_of_date\)/.test(sql)) return { rows: [{ as_of_date: '2026-08-07' }] }
      if (/AS strict_subset/.test(sql)) return { rows: [COUNTS] }
      return { rows: [row()] }
    })
    const body = await (await GET(req('tenor=10Y'))).json()
    expect(body.date).toBe('2026-08-07')
  })
})
