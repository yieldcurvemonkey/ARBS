// SWR-internals smoke test for useExtremesData.
import { describe, expect, it } from '@jest/globals'
import { buildExtremesUrl } from '../useExtremesData'
import { extremesKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
import type { FocusedTrade } from '../../components/AnalyticsPanel/analytics-types'

const focused: FocusedTrade = {
  id: 'pkg-1',
  tape_label: 'USD/SOFR-OIS/COMPOUND/10Y/PAR-FIXED',
  package_structure: 'PAR-FIXED',
  package_tenors: '10Y',
  trade_type: 'PAR-FIXED',
  tenor_years: 10,
  fixed_rate_bps: 387.5,
  weighted_fixed_rate: null,
  dv01_usd_per_bp: 100_000,
  notional_usd: 50_000_000,
  pts: null,
  side: 'PAY',
  platform: 'CUSTY',
  venue: 'TRADITION',
  execution_start: '2026-04-01T00:00:00Z',
  execution_session: null,
  lifecycle_type: null,
  is_block: false,
}

describe('useExtremesData URL + cache-key shape', () => {
  it('buildExtremesUrl includes focused metrics and tolerances', () => {
    const url = buildExtremesUrl(focused, { primaryTol: 2, sizeTol: 0.25 })
    expect(url).toContain('value=USD%2FSOFR-OIS%2FCOMPOUND%2F10Y%2FPAR-FIXED')
    expect(url).toContain('focusedRate=387.5')
    expect(url).toContain('focusedNotional=50000000')
    expect(url).toContain('primaryTol=2')
  })

  it('buildExtremesUrl drops zero focusedNotional', () => {
    const url = buildExtremesUrl(
      { ...focused, notional_usd: 0 },
      { primaryTol: 2, sizeTol: 0.25 },
    )
    expect(url).not.toContain('focusedNotional')
  })

  it('extremesKey is stable under repeated identical input', () => {
    const a = extremesKey({
      bucket: 'tape_label:X',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { primaryTol: 2, sizeTol: 0.25 },
    })
    const b = extremesKey({
      bucket: 'tape_label:X',
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { primaryTol: 2, sizeTol: 0.25 },
    })
    expect(a).toEqual(b)
  })
})
