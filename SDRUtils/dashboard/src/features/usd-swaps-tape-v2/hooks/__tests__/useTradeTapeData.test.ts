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
    const q = buildQuery({ limit: 50 })
    expect(q.get('limit')).toBe('50')
  })

  it('does NOT emit any filter query params — filtering is client-only post feedback round 1', () => {
    const q = buildQuery({} as any)
    expect(q.has('filter')).toBe(false)
    expect(q.has('columnFilters')).toBe(false)
    expect(q.has('lifecycle')).toBe(false)
    expect(q.has('tradeTypes')).toBe(false)
    expect(q.has('venues')).toBe(false)
    expect(q.has('clean')).toBe(false)
  })

  it('attaches cursor / since when provided', () => {
    const q1 = buildQuery({}, { cursor: '2026-04-14T00:00:00Z' })
    expect(q1.get('cursor')).toBe('2026-04-14T00:00:00Z')
    const q2 = buildQuery({}, { since: '2026-04-14T20:00:00Z' })
    expect(q2.get('since')).toBe('2026-04-14T20:00:00Z')
  })
})
