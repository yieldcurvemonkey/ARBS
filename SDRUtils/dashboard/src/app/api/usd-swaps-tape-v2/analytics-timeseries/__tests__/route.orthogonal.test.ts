// Phase 5 — orthogonal-payload split. Pin the new payload contract:
// the timeseries route returns gross/net + raw/filtered DV01 in a
// single response so the client can toggle useGrossDv01 /
// excludeLargeCusty locally without re-fetching.
import { describe, expect, it, jest } from '@jest/globals'

// Synthetic SQL row covering the new aggregate columns.
const queryMock = jest.fn(async () => ({
  rows: [
    {
      day: '2026-04-01',
      idb_close: 0.0387,
      custy_close: 0.0386,
      idb_open: 0.038,
      custy_open: 0.0381,
      idb_high: 0.0395,
      idb_low: 0.0379,
      custy_high: 0.039,
      custy_low: 0.038,
      idb_dv01_gross: 110_000,
      custy_dv01_gross: 50_000,
      idb_dv01_net: -10_000,
      custy_dv01_net: 5_000,
      custy_dv01_gross_excl_large: 30_000,
      custy_dv01_net_excl_large: 4_000,
      idb_notional: 1_000_000_000,
      custy_notional: 500_000_000,
      custy_notional_excl_large: 300_000_000,
      idb_prints: 12,
      custy_prints: 8,
      custy_prints_excl_large: 5,
    },
  ],
}))

jest.unstable_mockModule('@/lib/db', () => ({
  query: queryMock,
}))

function req(qs: string): Request {
  return new Request(`http://t/api/usd-swaps-tape-v2/analytics-timeseries?${qs}`, {
    method: 'GET',
  })
}

describe('analytics-timeseries — orthogonal-payload split', () => {
  it('returns full grid of (gross|net) × (raw|excl-large) variants', async () => {
    const { GET } = await import('../route')
    const r = await GET(
      req(
        'value=A/A&groupBy=canonical&range=1M&view=DAILY_CLOSE&useGrossDv01=true&excludeLargeCusty=true',
      ),
    )
    const json = await r.json()
    expect(Array.isArray(json.points)).toBe(true)
    const p = json.points[0]
    // Full variant grid:
    expect(p.idbDv01_gross).toBe(110_000)
    expect(p.idbDv01_net).toBe(-10_000)
    expect(p.custyDv01_gross).toBe(50_000)
    expect(p.custyDv01_net).toBe(5_000)
    expect(p.custyDv01_gross_excl_large).toBe(30_000)
    expect(p.custyDv01_net_excl_large).toBe(4_000)
    expect(p.custyNotional_raw).toBe(500_000_000)
    expect(p.custyNotional_excl_large).toBe(300_000_000)
    expect(p.custyPrints_raw).toBe(8)
    expect(p.custyPrints_excl_large).toBe(5)
  })

  it('legacy idbDv01/custyDv01 fields pick the requested variant', async () => {
    const { GET } = await import('../route')

    // gross + excludeLargeCusty=true → custyDv01 = custyDv01_gross_excl_large.
    const grossExcl = await (
      await GET(
        req(
          'value=B/B&groupBy=canonical&range=1M&view=DAILY_CLOSE&useGrossDv01=true&excludeLargeCusty=true',
        ),
      )
    ).json()
    expect(grossExcl.points[0].idbDv01).toBe(110_000)
    expect(grossExcl.points[0].custyDv01).toBe(30_000) // gross + filtered

    // net + excludeLargeCusty=false → custyDv01 = custyDv01_net.
    const netRaw = await (
      await GET(
        req(
          'value=C/C&groupBy=canonical&range=1M&view=DAILY_CLOSE&useGrossDv01=false&excludeLargeCusty=false',
        ),
      )
    ).json()
    expect(netRaw.points[0].idbDv01).toBe(-10_000)
    expect(netRaw.points[0].custyDv01).toBe(5_000) // net + raw
  })
})
