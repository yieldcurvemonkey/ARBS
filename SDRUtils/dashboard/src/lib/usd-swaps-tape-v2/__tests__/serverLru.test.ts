import { describe, expect, it, beforeEach, afterEach, jest } from '@jest/globals'
import { ServerLru } from '../serverLru'

describe('ServerLru', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })
  afterEach(() => {
    jest.useRealTimers()
  })

  it('hits within TTL', () => {
    const lru = new ServerLru<string>({ max: 4, ttlMs: 60_000 })
    lru.set('k', 'v')
    expect(lru.get('k')).toBe('v')
  })

  it('expires after TTL', () => {
    const lru = new ServerLru<string>({ max: 4, ttlMs: 60_000 })
    lru.set('k', 'v')
    jest.advanceTimersByTime(61_000)
    expect(lru.get('k')).toBeUndefined()
  })

  it('evicts oldest when over max', () => {
    const lru = new ServerLru<string>({ max: 2, ttlMs: 60_000 })
    lru.set('a', 'va')
    lru.set('b', 'vb')
    lru.set('c', 'vc')
    expect(lru.get('a')).toBeUndefined()
    expect(lru.get('b')).toBe('vb')
    expect(lru.get('c')).toBe('vc')
  })

  it('promotes on get (LRU semantics)', () => {
    const lru = new ServerLru<string>({ max: 2, ttlMs: 60_000 })
    lru.set('a', 'va')
    lru.set('b', 'vb')
    lru.get('a')
    lru.set('c', 'vc')
    expect(lru.get('a')).toBe('va')
    expect(lru.get('b')).toBeUndefined()
  })

  it('reports size and supports clear', () => {
    const lru = new ServerLru<string>({ max: 4, ttlMs: 60_000 })
    expect(lru.size()).toBe(0)
    lru.set('a', 'va')
    lru.set('b', 'vb')
    expect(lru.size()).toBe(2)
    lru.clear()
    expect(lru.size()).toBe(0)
    expect(lru.get('a')).toBeUndefined()
  })
})
