// ABOUTME: Source-string contract tests for the
// useAnalyticsSequence wrapper. The dashboard test runner is
// `node` (no jsdom + no @testing-library/react), so we cannot drive
// the React state shell directly; instead we cover the wrapper's
// non-React responsibilities (cap, warning copy, aggregate
// passthrough, MAX_SEQUENCE export) via source-string assertions
// plus pure-function checks against the imported MAX_SEQUENCE
// constant.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { MAX_SEQUENCE } from '../useAnalyticsSequence'

const wrapperSource = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/hooks/useAnalyticsSequence.ts',
  ),
  'utf8',
)

describe('useAnalyticsSequence — module surface', () => {
  it('exports a 20-trade soft cap', () => {
    expect(MAX_SEQUENCE).toBe(20)
  })

  it('imports each single-trade hook so caching+dedup is preserved', () => {
    expect(wrapperSource).toMatch(/import\s*\{[\s\S]*useAnalyticsTimeseries[\s\S]*\}\s*from\s+['"]\.\/useAnalyticsTimeseries['"]/)
    expect(wrapperSource).toMatch(/import\s*\{[\s\S]*useRarityData[\s\S]*\}\s*from\s+['"]\.\/useRarityData['"]/)
    expect(wrapperSource).toMatch(/import\s*\{[\s\S]*useExtremesData[\s\S]*\}\s*from\s+['"]\.\/useExtremesData['"]/)
  })

  it('imports computeSequenceAggregate and emits an `aggregate` field', () => {
    expect(wrapperSource).toContain('computeSequenceAggregate')
    expect(wrapperSource).toMatch(/aggregate\s*:\s*SequenceAggregate\s*\|\s*null/)
  })

  it('uses a fixed-length loop to avoid rules-of-hooks violations', () => {
    // The wrapper must iterate MAX_SEQUENCE slots unconditionally so
    // hook order stays stable across renders. A `.map(...)` over a
    // dynamic-length sequence would break the hook order if the
    // selection grows or shrinks.
    expect(wrapperSource).toMatch(/for\s*\(\s*let\s+i\s*=\s*0[\s\S]*i\s*<\s*MAX_SEQUENCE/)
  })

  it('passes null in unused slots to the inner hooks (no fetches fired)', () => {
    expect(wrapperSource).toMatch(/const\s+trade\s*=\s*capped\[i\]\s*\?\?\s*null/)
  })

  it('surfaces a soft-cap warning when N > MAX_SEQUENCE', () => {
    expect(wrapperSource).toMatch(/truncated/)
    expect(wrapperSource).toMatch(/Selection capped at/)
  })

  it('returns a perTrade entry per active sequence trade (not per slot)', () => {
    // Slots without a trade do NOT push into perTrade — that contract
    // matters because the SequenceTab iterates perTrade for rendering.
    expect(wrapperSource).toMatch(/if\s*\(\s*trade\s*\)\s*\{\s*slots\.push/)
  })
})
