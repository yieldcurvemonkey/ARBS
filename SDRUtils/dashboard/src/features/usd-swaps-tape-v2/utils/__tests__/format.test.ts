import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../constants'
import {
  formatClusterSuffix,
  formatDate,
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatRate,
  formatRateRange,
  formatTenor,
  formatTime,
} from '../format'

describe('formatNotional', () => {
  it('returns the empty marker for null / undefined / NaN', () => {
    expect(formatNotional(null)).toBe(EMPTY_VALUE)
    expect(formatNotional(undefined)).toBe(EMPTY_VALUE)
    expect(formatNotional(Number.NaN)).toBe(EMPTY_VALUE)
  })

  it('formats with commas by default', () => {
    expect(formatNotional(1_234_567)).toBe('1,234,567')
  })

  it('compacts billions / millions / thousands', () => {
    expect(formatNotional(1_500_000_000, { compact: true })).toBe('1.5B')
    expect(formatNotional(12_500_000, { compact: true })).toBe('12.5M')
    expect(formatNotional(150_000, { compact: true })).toBe('150K')
    expect(formatNotional(250, { compact: true })).toBe('250')
  })
})

describe('formatDv01', () => {
  it('returns compact by default, unsigned', () => {
    expect(formatDv01(1_500_000)).toBe('1.5M')
  })

  it('adds sign prefix when signed=true', () => {
    expect(formatDv01(1_500_000, { signed: true })).toBe('+1.5M')
    expect(formatDv01(-1_500_000, { signed: true })).toBe('\u22121.5M')
    expect(formatDv01(0, { signed: true })).toBe('0')
  })
})

describe('formatRate', () => {
  it('defaults to 3 decimal places of percent', () => {
    expect(formatRate(0.04523)).toBe('4.523%')
  })

  it('accepts precision override', () => {
    expect(formatRate(0.04523, { precision: 1 })).toBe('4.5%')
  })

  it('returns the empty marker on null', () => {
    expect(formatRate(null)).toBe(EMPTY_VALUE)
  })
})

describe('formatRateRange', () => {
  it('returns a single rate when the endpoints match', () => {
    expect(formatRateRange(0.04, 0.04)).toBe('4.000%')
  })

  it('renders both endpoints when the rates differ', () => {
    expect(formatRateRange(0.03, 0.05)).toContain('3.000%')
    expect(formatRateRange(0.03, 0.05)).toContain('5.000%')
  })
})

describe('formatTenor', () => {
  it('reads tenor_display off the first leg', () => {
    const row = {
      legs_json: [{ tenor_display: '~7Y', tenor_label: '7Y' } as any],
    } as any
    expect(formatTenor(row)).toBe('~7Y')
  })

  it('falls back through tenor_label / package_tenors / empty marker', () => {
    expect(
      formatTenor({ legs_json: [], tenor_label: '5Y', package_tenors: null } as any),
    ).toBe('5Y')
    expect(formatTenor({ legs_json: [] } as any)).toBe(EMPTY_VALUE)
  })
})

describe('formatTime', () => {
  it('returns the empty marker on null', () => {
    expect(formatTime(null)).toBe(EMPTY_VALUE)
  })

  it('returns a HH:MM:SS-ish string for valid ISO', () => {
    const formatted = formatTime('2026-04-14T14:30:15Z')
    expect(formatted.length).toBeGreaterThan(0)
    expect(formatted).not.toBe(EMPTY_VALUE)
  })
})

describe('formatDate', () => {
  it('returns the empty marker on null', () => {
    expect(formatDate(null)).toBe(EMPTY_VALUE)
  })

  it('renders an en-US calendar date for valid ISO input', () => {
    const formatted = formatDate('2026-04-14T14:30:15Z')
    expect(formatted.length).toBeGreaterThan(0)
    expect(formatted).toContain('2026')
  })
})

describe('formatExecutionWindow', () => {
  it('returns the empty marker when the start timestamp is missing', () => {
    expect(formatExecutionWindow(null, null)).toBe(EMPTY_VALUE)
  })

  it('renders the full timestamp when start and end match', () => {
    const formatted = formatExecutionWindow(
      '2026-04-14T14:30:15Z',
      '2026-04-14T14:30:15Z',
    )
    expect(formatted).toContain('2026')
    expect(formatted).not.toContain(' / ')
  })

  it('renders a range when execution_start and execution_end differ', () => {
    const formatted = formatExecutionWindow(
      '2026-04-14T14:30:15Z',
      '2026-04-14T14:31:15Z',
    )
    expect(formatted).toContain('2026')
    expect(formatted).toContain(' / ')
  })
})

describe('formatClusterSuffix', () => {
  it('returns empty string for <2', () => {
    expect(formatClusterSuffix(null)).toBe('')
    expect(formatClusterSuffix(1)).toBe('')
  })

  it('formats +N for larger clusters', () => {
    expect(formatClusterSuffix(5)).toBe(' (+4)')
  })
})
