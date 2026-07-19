import { describe, expect, it } from '@jest/globals'
import {
  aggregateUnrecognisedUnderliers,
  isUnrecognisedCanonicalKey,
  type UnrecognisedRow,
} from '../route.logic'

describe('isUnrecognisedCanonicalKey', () => {
  it.each([
    ['USD/SOFR-OIS/COMPOUND', false],
    ['USD/FED-FUNDS-OIS/COMPOUND', false],
    ['USD/OBFR-OIS/COMPOUND', false],
    ['USD/BSBY/IBOR', false],
    ['USD/LIBOR/IBOR', false],
    ['USD/ISDA-CMS', false],
    ['USD/SIFMA-MUNI', false],
    ['USD/SOFR-TERM', false],
    ['UNKNOWN', true],
    ['', true],
    [null, true],
    ['USD/BASIS/SOFR-OIS+FED-FUNDS-OIS', true], // basis isn't in the
    // canonical bucket whitelist — analysts must opt it in. Treated as
    // "needs review" until we add basis buckets explicitly.
    ['USD/UNRECOGNISED-INDEX', true],
  ])('canonical=%s -> unrecognised=%s', (key, expected) => {
    expect(isUnrecognisedCanonicalKey(key)).toBe(expected)
  })
})

describe('aggregateUnrecognisedUnderliers', () => {
  const rows: UnrecognisedRow[] = [
    {
      floating_rate_index: 'USD-NEW-FANCY-RATE',
      canonical_underlier_key: 'UNKNOWN',
      notional: 100_000_000,
      anchor_ts: '2026-05-04T10:00:00Z',
    },
    {
      floating_rate_index: 'USD-NEW-FANCY-RATE',
      canonical_underlier_key: 'UNKNOWN',
      notional: 50_000_000,
      anchor_ts: '2026-05-04T15:30:00Z',
    },
    {
      // Recognised — should be filtered out
      floating_rate_index: 'USD-SOFR-OIS Compound 1D',
      canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND',
      notional: 200_000_000,
      anchor_ts: '2026-05-04T11:00:00Z',
    },
    {
      floating_rate_index: 'USD-WEIRD-VARIANT',
      canonical_underlier_key: null,
      notional: 25_000_000,
      anchor_ts: '2026-05-03T22:00:00Z',
    },
  ]

  it('groups by raw floating_rate_index and sums notional', () => {
    const out = aggregateUnrecognisedUnderliers(rows)
    expect(out.map((r) => r.floating_rate_index).sort()).toEqual([
      'USD-NEW-FANCY-RATE',
      'USD-WEIRD-VARIANT',
    ])
    const fancy = out.find((r) => r.floating_rate_index === 'USD-NEW-FANCY-RATE')
    expect(fancy?.totalNotional).toBe(150_000_000)
    expect(fancy?.count).toBe(2)
  })

  it('reports first-seen and last-seen timestamps', () => {
    const out = aggregateUnrecognisedUnderliers(rows)
    const fancy = out.find((r) => r.floating_rate_index === 'USD-NEW-FANCY-RATE')
    expect(fancy?.firstSeen).toBe('2026-05-04T10:00:00.000Z')
    expect(fancy?.lastSeen).toBe('2026-05-04T15:30:00.000Z')
  })

  it('sorts by descending notional', () => {
    const out = aggregateUnrecognisedUnderliers(rows)
    expect(out[0].floating_rate_index).toBe('USD-NEW-FANCY-RATE')
    expect(out[1].floating_rate_index).toBe('USD-WEIRD-VARIANT')
  })

  it('returns empty list when every row is recognised', () => {
    const recognised: UnrecognisedRow[] = [
      {
        floating_rate_index: 'USD-SOFR',
        canonical_underlier_key: 'USD/SOFR-OIS/COMPOUND',
        notional: 1_000,
        anchor_ts: '2026-05-04T10:00:00Z',
      },
    ]
    expect(aggregateUnrecognisedUnderliers(recognised)).toEqual([])
  })
})
