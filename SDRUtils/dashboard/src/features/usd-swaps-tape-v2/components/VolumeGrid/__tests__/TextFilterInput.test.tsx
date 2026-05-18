// ABOUTME: Source-string contract tests for TextFilterInput.
// The dashboard test runner is testEnvironment: node (no jsdom), so
// DOM-rendering tests are not available. These assertions verify the
// component's structural contracts: debounce wiring, clear button
// conditionality, aria-label, and placeholder text.
import { describe, expect, it } from '@jest/globals'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const src = readFileSync(
  resolve(
    process.cwd(),
    'src/features/usd-swaps-tape-v2/components/VolumeGrid/TextFilterInput.tsx',
  ),
  'utf8',
)

describe('TextFilterInput — props interface', () => {
  it('exports TextFilterInputProps with value, onChange, and debounceMs', () => {
    expect(src).toMatch(/export interface TextFilterInputProps/)
    expect(src).toMatch(/value:\s*string/)
    expect(src).toMatch(/onChange:\s*\(value:\s*string\)\s*=>\s*void/)
    expect(src).toMatch(/debounceMs\?:\s*number/)
  })

  it('defaults debounceMs to 300', () => {
    expect(src).toMatch(/debounceMs\s*=\s*300/)
  })
})

describe('TextFilterInput — debounce wiring', () => {
  it('uses setTimeout with debounceMs for onChange', () => {
    expect(src).toMatch(/setTimeout\(\(\)\s*=>\s*onChange\(next\),\s*debounceMs\)/)
  })

  it('clears pending timer before scheduling a new one', () => {
    expect(src).toMatch(/if\s*\(timerRef\.current\)\s*clearTimeout\(timerRef\.current\)/)
  })

  it('cleans up timer on unmount', () => {
    expect(src).toMatch(/useEffect\(\(\)\s*=>\s*\(\)\s*=>\s*\{/)
  })
})

describe('TextFilterInput — clear button', () => {
  it('renders clear button conditionally on value prop', () => {
    expect(src).toMatch(/\{value\s*&&\s*\(/)
  })

  it('uses aria-label="Clear filter" on the clear button', () => {
    expect(src).toMatch(/aria-label="Clear filter"/)
  })

  it('calls onChange with empty string on clear', () => {
    expect(src).toMatch(/onChange\(''\)/)
  })
})

describe('TextFilterInput — input element', () => {
  it('renders a text input with placeholder "filter trades..."', () => {
    expect(src).toMatch(/placeholder="filter trades\.\.\."/)
  })

  it('binds value to local state', () => {
    expect(src).toMatch(/value=\{local\}/)
  })

  it('uses handleChange for onChange', () => {
    expect(src).toMatch(/onChange=\{handleChange\}/)
  })
})

describe('TextFilterInput — local state sync', () => {
  it('syncs local state when value prop changes via useEffect', () => {
    expect(src).toMatch(/useEffect\(\(\)\s*=>\s*\{\s*setLocal\(value\)\s*\},\s*\[value\]\)/)
  })
})
