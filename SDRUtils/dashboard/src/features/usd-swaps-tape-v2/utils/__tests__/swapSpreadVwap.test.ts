import { describe, expect, it } from '@jest/globals'
import {
  computeDailyVwap,
  resolveSwapSpreadTicker,
  SWAP_SPREAD_TICKERS,
  USD_OIS_TICKERS,
} from '../swapSpreadVwap'
import type { UsdSwapTapeRow } from '../../types'

const row = (
  partial: {
    fixed_rate?: number | null
    notional?: number | null
    risk?: number | null
    package_type?: string | null
    tenor_years?: number | null
    canonical_underlier_key?: string | null
    ts?: string
  } = {},
): UsdSwapTapeRow =>
  ({
    package_id: `P-${Math.random()}`,
    package_type: partial.package_type ?? 'OUTRIGHT',
    legs_count: 1,
    weighted_fixed_rate: partial.fixed_rate ?? null,
    total_notional: partial.notional ?? null,
    total_risk: partial.risk ?? null,
    canonical_underlier_key:
      partial.canonical_underlier_key ?? 'USD/SOFR-OIS/COMPOUND',
    legs_json: [
      {
        risk: partial.risk ?? null,
        notional: partial.notional ?? null,
        fixed_rate: partial.fixed_rate ?? null,
        tenor_years: partial.tenor_years ?? null,
        canonical_underlier_key:
          partial.canonical_underlier_key ?? 'USD/SOFR-OIS/COMPOUND',
      },
    ] as any,
    execution_start: partial.ts ?? '2026-05-04T15:00:00Z',
  } as any)

describe('SWAP_SPREAD_TICKERS + USD_OIS_TICKERS', () => {
  it('contains the canonical USD swap-spread tenors', () => {
    expect(SWAP_SPREAD_TICKERS.map((t) => t.ticker)).toEqual([
      'USSFCT2',
      'USSFCT5',
      'USSFCT10',
      'USSFCT30',
    ])
  })

  it('contains the canonical USD OIS tenors', () => {
    expect(USD_OIS_TICKERS.map((t) => t.ticker)).toEqual([
      'USSO5',
      'USSO10',
      'USSO30',
    ])
  })
})

describe('resolveSwapSpreadTicker', () => {
  it('matches a SPREADOVER package by tenor', () => {
    const spread5y = row({
      package_type: 'SPREADOVER',
      tenor_years: 5,
    })
    expect(resolveSwapSpreadTicker(spread5y)).toBe('USSFCT5')
  })

  it('matches USSFCT10 for a SPREADOVER 10Y', () => {
    expect(
      resolveSwapSpreadTicker(row({ package_type: 'SPREADOVER', tenor_years: 10 })),
    ).toBe('USSFCT10')
  })

  it('matches USSO5 for outright SOFR-OIS at 5Y', () => {
    expect(
      resolveSwapSpreadTicker(
        row({ package_type: 'OUTRIGHT', tenor_years: 5 }),
      ),
    ).toBe('USSO5')
  })

  it('returns null for a non-canonical underlier (e.g. LIBOR)', () => {
    expect(
      resolveSwapSpreadTicker(
        row({
          package_type: 'OUTRIGHT',
          tenor_years: 5,
          canonical_underlier_key: 'USD/LIBOR/IBOR',
        }),
      ),
    ).toBeNull()
  })

  it('returns null for an unmappable tenor (e.g. 7Y)', () => {
    expect(
      resolveSwapSpreadTicker(row({ package_type: 'OUTRIGHT', tenor_years: 7 })),
    ).toBeNull()
  })

  it('returns null when tenor is missing', () => {
    expect(
      resolveSwapSpreadTicker(row({ package_type: 'SPREADOVER' })),
    ).toBeNull()
  })
})

describe('computeDailyVwap', () => {
  it('weights fixed_rate by |risk| within a single day', () => {
    // Two SPREADOVER 5Y prints, one large + one small
    // Expected VWAP = (3.50 * 100 + 4.00 * 25) / 125 = 3.60
    const rows: UsdSwapTapeRow[] = [
      row({
        package_type: 'SPREADOVER',
        tenor_years: 5,
        fixed_rate: 0.035,
        risk: 100_000,
        notional: 500_000_000,
        ts: '2026-05-01T10:00:00Z',
      }),
      row({
        package_type: 'SPREADOVER',
        tenor_years: 5,
        fixed_rate: 0.04,
        risk: 25_000,
        notional: 100_000_000,
        ts: '2026-05-01T15:00:00Z',
      }),
    ]
    const points = computeDailyVwap(rows, 'USSFCT5')
    expect(points).toHaveLength(1)
    expect(points[0].day).toBe('2026-05-01')
    // 3.5*100 + 4.0*25 = 350 + 100 = 450; 450/125 = 3.6 (in pct);
    // converted to bps = 360
    expect(points[0].vwapBps).toBeCloseTo(360, 5)
    expect(points[0].tradeCount).toBe(2)
    expect(points[0].totalNotional).toBe(600_000_000)
  })

  it('ignores rows that do not match the ticker', () => {
    const rows: UsdSwapTapeRow[] = [
      row({
        package_type: 'SPREADOVER',
        tenor_years: 10,
        fixed_rate: 0.035,
        risk: 100_000,
        notional: 500_000_000,
      }),
      row({
        package_type: 'SPREADOVER',
        tenor_years: 5,
        fixed_rate: 0.04,
        risk: 25_000,
        notional: 100_000_000,
      }),
    ]
    const points = computeDailyVwap(rows, 'USSFCT5')
    expect(points).toHaveLength(1)
    expect(points[0].tradeCount).toBe(1)
  })

  it('returns empty array when no rows match', () => {
    expect(computeDailyVwap([], 'USSFCT5')).toEqual([])
  })

  it('falls back to even weights when |risk| is missing', () => {
    const rows: UsdSwapTapeRow[] = [
      row({
        package_type: 'SPREADOVER',
        tenor_years: 5,
        fixed_rate: 0.030,
        risk: null,
        notional: 100_000_000,
      }),
      row({
        package_type: 'SPREADOVER',
        tenor_years: 5,
        fixed_rate: 0.040,
        risk: null,
        notional: 100_000_000,
      }),
    ]
    const points = computeDailyVwap(rows, 'USSFCT5')
    // Even weighting → VWAP = 3.5%, in bps = 350
    expect(points[0].vwapBps).toBeCloseTo(350, 5)
  })
})
