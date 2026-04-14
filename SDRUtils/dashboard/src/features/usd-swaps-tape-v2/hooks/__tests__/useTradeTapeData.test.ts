import { describe, expect, it } from '@jest/globals'
import { __internal } from '../useTradeTapeData'

const buildQuery = __internal.buildQuery

describe('useTradeTapeData buildQuery', () => {
  it('emits an empty query when no params are set', () => {
    const q = buildQuery({})
    expect(q.toString()).toBe('')
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
