// ABOUTME: The direction route handlers, with @/lib/db mocked.
//
// route.logic.test.ts pins the pure functions. This pins the wiring: that the
// refusals actually reach the client as 400s, that the level keys leave
// bucket-suffixed, and that the all-bucket endpoint refuses to emit a level
// even if the SELECT list were edited to include one.
import { beforeEach, describe, expect, it, jest } from '@jest/globals'

const analyticsQueryMock = jest.fn<any>()

jest.unstable_mockModule('@/lib/db', () => ({
  query: jest.fn(async () => ({ rows: [] })),
  analyticsQuery: analyticsQueryMock,
  withClient: jest.fn(),
}))

const { GET: bucketGET } = await import('../bucket/route')
const { GET: stdGET } = await import('../standardised/route')
const { GET: covGET } = await import('../coverage/route')
const { GET: sumGET } = await import('../summary/route')

const req = (path: string) => new Request(`http://x/api${path}`)

beforeEach(() => {
  analyticsQueryMock.mockReset()
  analyticsQueryMock.mockResolvedValue({ rows: [] })
})

describe('GET /direction/bucket', () => {
  it('400s on a bucket list, with the measurement in the message', async () => {
    const res = await bucketGET(req('/direction/bucket?bucket=5-7Y&bucket=7-10Y'))
    expect(res.status).toBe(400)
    const body = await res.json()
    expect(body.error).toMatch(/0\.761/)
    expect(body.error).toMatch(/0\.495/)
    expect(analyticsQueryMock).not.toHaveBeenCalled()
  })

  it('400s with no bucket at all', async () => {
    const res = await bucketGET(req('/direction/bucket'))
    expect(res.status).toBe(400)
    expect(analyticsQueryMock).not.toHaveBeenCalled()
  })

  it('serves one bucket, with the level bucket-suffixed', async () => {
    analyticsQueryMock.mockResolvedValue({
      rows: [{
        visibility_date: '2026-04-01', observed: true,
        delta_dv01: 1_000_000, delta_dv01_cov_adj: 990_000,
        abs_dv01: 4_000_000, z_raw: 1.5, coverage_frac: 0.58,
      }],
    })
    const res = await bucketGET(
      req('/direction/bucket?bucket=5-7Y&venueClass=D2C&series=FLOW'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.bucket).toBe('5-7Y')
    const row = body.rows[0]
    expect(row).toHaveProperty('delta_dv01__5_7Y', 1_000_000)
    expect(row).toHaveProperty('delta_dv01_cov_adj__5_7Y', 990_000)
    expect(row).toHaveProperty('abs_dv01__5_7Y', 4_000_000)
    // The bare names must NOT survive: they are what would let two responses
    // be concatenated into a cross-bucket comparison.
    expect(row).not.toHaveProperty('delta_dv01')
    expect(row).not.toHaveProperty('abs_dv01')
    // z is not renamed, because z is the thing that IS comparable.
    expect(row).toHaveProperty('z_raw', 1.5)
    expect(row).toHaveProperty('coverage_frac', 0.58)
  })

  it('binds the bucket rather than interpolating it', async () => {
    await bucketGET(req('/direction/bucket?bucket=5-7Y'))
    const [sql, params] = analyticsQueryMock.mock.calls[0] as [string, unknown[]]
    expect(sql).not.toContain('5-7Y')
    expect(params).toContain('5-7Y')
  })
})

describe('GET /direction/standardised', () => {
  it('serves every bucket', async () => {
    analyticsQueryMock.mockResolvedValue({
      rows: [
        { bucket_key: '5-7Y', visibility_date: '2026-04-01', z_raw: 1.5 },
        { bucket_key: '7-10Y', visibility_date: '2026-04-01', z_raw: -0.4 },
      ],
    })
    const res = await stdGET(req('/direction/standardised'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.rows).toHaveLength(2)
    expect(body.buckets).toHaveLength(10)
  })

  it('REFUSES to emit a level even when the query returns one', async () => {
    // The SELECT list is a list and lists get edited. This is the check that
    // survives that edit: a level in the all-bucket payload is a 500, not a
    // chart.
    analyticsQueryMock.mockResolvedValue({
      rows: [
        { bucket_key: '5-7Y', visibility_date: '2026-04-01', delta_dv01: 1 },
        { bucket_key: '7-10Y', visibility_date: '2026-04-01', delta_dv01: 2 },
      ],
    })
    const res = await stdGET(req('/direction/standardised'))
    expect(res.status).toBe(500)
    expect((await res.json()).error).toMatch(/not comparable across buckets/)
  })

  it('400s on a venue class that is not one of the three', async () => {
    const res = await stdGET(req('/direction/standardised?venueClass=ALL'))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toMatch(/never summed/)
  })

  it('400s below the sample floor', async () => {
    const res = await stdGET(req('/direction/standardised?from=2024-01-01'))
    expect(res.status).toBe(400)
    expect((await res.json()).error).toMatch(/2024-07-01/)
  })
})

describe('GET /direction/coverage', () => {
  it('serves the breakdown by reason', async () => {
    analyticsQueryMock.mockResolvedValue({
      rows: [
        { reason: 'IN_LADDER', n_units: 10, dv01: 58, dv01_share: 0.58, in_ladder: true },
        { reason: 'UNORIENTABLE_PKG', n_units: 4, dv01: 40, dv01_share: 0.40, in_ladder: false },
      ],
    })
    const res = await covGET(req('/direction/coverage'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.rows[0].reason).toBe('IN_LADDER')
    expect(body.rows[1].in_ladder).toBe(false)
  })

  it('may go by bucket — a SHARE is the thing that differs across buckets', async () => {
    await covGET(req('/direction/coverage?byBucket=true'))
    const [sql] = analyticsQueryMock.mock.calls[0] as [string]
    expect(sql).toContain('PARTITION BY bucket_key')
  })

  it('400s on an unknown bucket', async () => {
    const res = await covGET(req('/direction/coverage?bucket=6Y'))
    expect(res.status).toBe(400)
  })
})

describe('GET /direction/summary', () => {
  it('returns null rather than inventing a row when nothing is published', async () => {
    analyticsQueryMock.mockResolvedValue({ rows: [] })
    const res = await sumGET(req('/direction/summary'))
    expect(res.status).toBe(200)
    expect((await res.json()).summary).toBeNull()
  })

  it('carries the vintage and the tape generation', async () => {
    analyticsQueryMock.mockResolvedValue({
      rows: [{ code_vintage: 'abc123', tape_generation: 'v3', coverage_frac: 0.58 }],
    })
    const body = await (await sumGET(req('/direction/summary'))).json()
    expect(body.summary.code_vintage).toBe('abc123')
    expect(body.summary.tape_generation).toBe('v3')
  })
})

describe('a DB failure is a 500, not a silent empty chart', () => {
  it('surfaces the message', async () => {
    analyticsQueryMock.mockRejectedValue(new Error('relation does not exist'))
    const res = await stdGET(req('/direction/standardised'))
    expect(res.status).toBe(500)
    expect((await res.json()).error).toMatch(/relation does not exist/)
  })
})
