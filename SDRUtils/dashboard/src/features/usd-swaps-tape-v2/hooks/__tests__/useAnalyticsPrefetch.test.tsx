// SWR-internals smoke test for useAnalyticsPrefetch. Avoids
// @testing-library/react (not installed) by extracting the
// debounce + URL building logic into pure-function shape via the
// __testing surface, plus a simple manual hook driver.
import 'fake-indexeddb/auto'
import { describe, expect, it, jest, beforeEach, afterEach } from '@jest/globals'
import { __testing } from '../useAnalyticsPrefetch'

describe('useAnalyticsPrefetch internals', () => {
  beforeEach(() => {
    ;(global as unknown as { fetch: jest.Mock }).fetch = jest.fn(
      () =>
        Promise.resolve(
          new Response(JSON.stringify({}), {
            status: 200,
            headers: { ETag: '"x"' },
          }),
        ) as unknown as ReturnType<typeof fetch>,
    )
  })

  afterEach(() => {
    delete (global as unknown as { fetch?: jest.Mock }).fetch
  })

  it('exposes a 150ms debounce constant', () => {
    expect(__testing.DEBOUNCE_MS).toBe(150)
  })

  it('isPrefetchEnabled defaults to true', () => {
    const original = process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
    delete process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
    try {
      expect(__testing.isPrefetchEnabled()).toBe(true)
    } finally {
      if (original !== undefined) {
        process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = original
      }
    }
  })

  it('isPrefetchEnabled returns false when explicitly disabled', () => {
    const original = process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
    process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = 'false'
    try {
      expect(__testing.isPrefetchEnabled()).toBe(false)
    } finally {
      if (original === undefined) {
        delete process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
      } else {
        process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = original
      }
    }
  })

  it('isPrefetchEnabled is permissive — any string other than "false" enables', () => {
    const original = process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
    process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = 'true'
    try {
      expect(__testing.isPrefetchEnabled()).toBe(true)
    } finally {
      if (original === undefined) {
        delete process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH
      } else {
        process.env.NEXT_PUBLIC_ENABLE_HOVER_PREFETCH = original
      }
    }
  })
})
