import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useTradeTapeData'

const buildQuery = __internal.buildQuery

describe('useTradeTapeData buildQuery', () => {
  it('always emits a page size so the server caps each fetch predictably', () => {
    const q = buildQuery({})
    // Default page size is intentionally larger than the swaption tape so
    // traders see a deep tape on first paint; VirtualScroller still chains
    // additional pages at the same size as the server scrolls further back.
    expect(q.get('limit')).toBe('200')
  })

  it('honours a caller-supplied limit override', () => {
    const q = buildQuery({ limit: 200 })
    expect(q.get('limit')).toBe('200')
  })

  it('serializes global filter + column filters + operator', () => {
    const q = buildQuery({
      filter: 'SOFR',
      columnFilterPayloadKey: '{"a":1}',
      columnFilterOperator: 'or',
    })
    expect(q.get('filter')).toBe('SOFR')
    expect(q.get('columnFilters')).toBe('{"a":1}')
    expect(q.get('columnFilterOp')).toBe('or')
  })

  it('serializes flag filter sets as CSV in sorted order', () => {
    const q = buildQuery({
      flagFilters: {
        lifecycle: new Set(['UNWIND', 'NEW_RISK'] as any),
        tradeTypes: new Set(['OUTRIGHT', 'CURVE']),
        venues: new Set(['D2D']),
        ccps: new Set(),
        sessions: new Set(),
        rateIndex: new Set(['SOFR']),
        tenors: new Set(['5Y', '10Y']),
        fomcMeeting: 'APR26',
        clean: true,
      },
    })
    expect(q.get('clean')).toBe('true')
    expect(q.get('lifecycle')).toBe('new_risk,unwind')
    expect(q.get('tradeTypes')).toBe('CURVE,OUTRIGHT')
    expect(q.get('venues')).toBe('D2D')
    expect(q.get('rateIndex')).toBe('SOFR')
    expect(q.get('tenors')).toBe('10Y,5Y')
    expect(q.get('fomcMeeting')).toBe('APR26')
    expect(q.has('ccps')).toBe(false)
  })

  it('attaches cursor / since when provided', () => {
    const q1 = buildQuery({}, { cursor: '2026-04-14T00:00:00Z' })
    expect(q1.get('cursor')).toBe('2026-04-14T00:00:00Z')
    const q2 = buildQuery({}, { since: '2026-04-14T20:00:00Z' })
    expect(q2.get('since')).toBe('2026-04-14T20:00:00Z')
  })
})
