// SWR-internals smoke test for useRarityData. Focuses on the URL
// builder + cache-key alignment; full hook integration is covered by
// the higher-level TradeRarityTab tests + dev-server E2E walkthrough.
import { describe, expect, it } from '@jest/globals'
import { buildRarityUrl } from '../useRarityData'
import { rarityKey } from '@/lib/usd-swaps-tape-v2/analyticsCacheKeys'
import type { FocusedTrade } from '../../components/AnalyticsPanel/analytics-types'

const baseFocused: FocusedTrade = {
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
  side: 'PAY',
  platform: 'CUSTY',
  venue: 'TRADITION',
  execution_start: '2026-04-01T00:00:00Z',
  execution_session: null,
  lifecycle_type: null,
  is_block: false,
}

describe('useRarityData URL + cache-key shape', () => {
  it('buildRarityUrl includes all focused-row metrics', () => {
    const url = buildRarityUrl(baseFocused, {
      lookback: 90,
      primaryTol: 2,
      sizeTol: 0.25,
      binMetric: 'fixed_rate',
    })
    expect(url).toContain('value=USD%2FSOFR-OIS%2FCOMPOUND%2F10Y%2FPAR-FIXED')
    expect(url).toContain('focusedRate=387.5')
    expect(url).toContain('focusedDv01=100000')
    expect(url).toContain('focusedNotional=50000000')
    expect(url).toContain('lookback=90')
    expect(url).toContain('binMetric=fixed_rate')
  })

  it('buildRarityUrl drops zero focusedDv01 / focusedNotional', () => {
    const url = buildRarityUrl(
      {
        ...baseFocused,
        dv01_usd_per_bp: 0,
        notional_usd: 0,
      },
      { lookback: 90, primaryTol: 2, sizeTol: 0.25, binMetric: 'fixed_rate' },
    )
    expect(url).not.toContain('focusedDv01')
    expect(url).not.toContain('focusedNotional')
  })

  it('rarityKey changes when bucket changes', () => {
    const a = rarityKey({
      bucket: `tape_label:A`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90 },
    })
    const b = rarityKey({
      bucket: `tape_label:B`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90 },
    })
    expect(a).not.toEqual(b)
  })

  it('rarityKey is stable under repeated identical input', () => {
    const a = rarityKey({
      bucket: `tape_label:X`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90, binMetric: 'dv01' },
    })
    const b = rarityKey({
      bucket: `tape_label:X`,
      groupBy: 'tape_label',
      groupValueOverride: null,
      options: { lookback: 90, binMetric: 'dv01' },
    })
    expect(a).toEqual(b)
  })
})
