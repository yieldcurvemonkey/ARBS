import { describe, expect, it } from '@jest/globals'
import { EMPTY_VALUE } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'
import {
  formatClusterSuffix,
  formatDate,
  formatDv01,
  formatExecutionWindow,
  formatNotional,
  formatOtherLvl,
  formatRate,
  formatRateRange,
  formatReportedLvl,
  formatTenor,
  formatTime,
  formatTimestampDelta,
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

describe('formatDv01 headline rounding', () => {
  it('rounds the user-reported 49.9K case to 50K', () => {
    expect(formatDv01(49_900)).toBe('50K')
  })

  it('rounds tight-above values to the same headline bucket', () => {
    expect(formatDv01(50_100)).toBe('50K')
  })

  it('snaps to the headline ladder when within ~5% tolerance', () => {
    // 9_800 rounds to "10K" (within 2% of 10).
    expect(formatDv01(9_800)).toBe('10K')
    // 24_100 snaps up to 25 (within 4% of 25 ladder value); raw integer
    // rounding would give "24K".
    expect(formatDv01(24_100)).toBe('25K')
    // 48_500 snaps up to 50 (3% away); raw integer rounding would give "49K".
    expect(formatDv01(48_500)).toBe('50K')
    // 96_000 snaps up to 100K (4% away).
    expect(formatDv01(96_000)).toBe('100K')
  })

  it('snaps to 40 when the value is within 5% of a ladder entry', () => {
    // 41_500 is 3.75% above 40 — snap (ladder has 40).
    expect(formatDv01(41_500)).toBe('40K')
    // 72_000 is 4% below 75 — snap.
    expect(formatDv01(72_000)).toBe('75K')
  })

  it('does NOT snap when no ladder value is close enough; integer rounds', () => {
    // 35_000: 30 is 17% away, 40 is 12.5% away. No snap. Integer round.
    expect(formatDv01(35_000)).toBe('35K')
    // 46_000: 50 is 8% away, 40 is 15% away. No snap. Integer round.
    expect(formatDv01(46_000)).toBe('46K')
  })

  it('uses integer rounding on scaled K values (no 1-decimal noise)', () => {
    expect(formatDv01(6_800)).toBe('7K')
    expect(formatDv01(4_900)).toBe('5K')
  })

  it('rounds negative values the same way, with signed-only negatives', () => {
    expect(formatDv01(-49_900, { signNegativeOnly: true })).toBe('\u221250K')
    expect(formatDv01(+49_900, { signNegativeOnly: true })).toBe('50K')
  })

  it('keeps sub-1K values unscaled and integer', () => {
    expect(formatDv01(700)).toBe('700')
    expect(formatDv01(450)).toBe('450')
  })

  it('snaps millions to headline ladder', () => {
    expect(formatDv01(1_020_000)).toBe('1M')    // within 2% of 1
    expect(formatDv01(2_400_000)).toBe('2.5M')  // within 4% of 2.5 ladder
    expect(formatDv01(5_100_000)).toBe('5M')    // within 2% of 5
    expect(formatDv01(1_020_000_000)).toBe('1B')
  })
})

describe('formatDv01', () => {
  it('returns compact headline-rounded by default, unsigned', () => {
    // 1.5 is a ladder entry → snaps to itself, renders "1.5M" verbatim.
    expect(formatDv01(1_500_000)).toBe('1.5M')
  })

  it('adds sign prefix when signed=true', () => {
    expect(formatDv01(1_500_000, { signed: true })).toBe('+1.5M')
    expect(formatDv01(-1_500_000, { signed: true })).toBe('\u22121.5M')
    expect(formatDv01(0, { signed: true })).toBe('0')
  })

  it('with signNegativeOnly, drops the + for positives but keeps the − for negatives', () => {
    // Matches the trade-tape column feedback: "+" is visual noise but the
    // receive-side (negative) risk must still be obviously signed.
    expect(formatDv01(1_500_000, { signNegativeOnly: true })).toBe('1.5M')
    expect(formatDv01(-1_500_000, { signNegativeOnly: true })).toBe(
      '\u22121.5M',
    )
    expect(formatDv01(0, { signNegativeOnly: true })).toBe('0')
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

  it('renders timestamps in the NYC trading timezone regardless of viewer locale', () => {
    // 2026-04-14T14:30:15Z is 10:30:15 local in New York (EDT, UTC-4).
    const formatted = formatExecutionWindow(
      '2026-04-14T14:30:15Z',
      '2026-04-14T14:31:15Z',
    )
    expect(formatted).toContain('10:30:15')
    expect(formatted).toContain('10:31:15')
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

describe('formatOtherLvl', () => {
  it('returns em-dashes when OPA + PTP + PTS all null', () => {
    const result = formatOtherLvl({ legOpa: [null, null], ptp: null, pts: null })
    expect(result.opaLine).toBe('OPA: \u2014')
    expect(result.ptpLine).toBe('PTP: \u2014')
    expect(result.ptsLine).toBe('PTS: \u2014')
  })
  it('stacks non-null leg OPAs slash-separated', () => {
    const result = formatOtherLvl({ legOpa: [15627.6, null, -2100], ptp: -671880 })
    expect(result.opaLine).toBe('OPA: 15.6k / -2.1k')
    // P2-01: scaled values >= 100 drop to 0 decimals so 6-figure PTPs
    // stay narrow. 15.6 (< 100) keeps the 1-decimal precision.
    expect(result.ptpLine).toBe('PTP: -672k')
  })

  it('renders per-leg PTP values with slash delimiter when legPtp supplied', () => {
    const result = formatOtherLvl({
      legOpa: [null, null],
      legPtp: [100_000, 50_000],
      ptp: 75_000,
      pts: null,
    })
    // P2-01 precision rule: scaled >= 100 → 0 decimals (100k);
    // scaled < 100 → 1 decimal (50.0k).
    expect(result.ptpLine).toBe('PTP: 100k / 50.0k')
  })

  it('renders per-leg PTS values with slash delimiter when legPts supplied', () => {
    const result = formatOtherLvl({
      legOpa: [null, null],
      legPts: [0.0025, -0.0005],
      ptp: null,
      pts: 0.0010,
    })
    expect(result.ptsLine).toBe('PTS: 0.0025 / -0.0005')
  })

  it('collapses identical per-leg PTS values to a single print', () => {
    const result = formatOtherLvl({
      legOpa: [null, null, null],
      legPts: [0.0000125, 0.0000125, 0.0000125],
      ptp: null,
      pts: 0.0000125,
    })
    expect(result.ptsLine).toBe('PTS: 0.000013')
  })

  it('falls back to the scalar pts when legPts is empty or all nullish', () => {
    const result = formatOtherLvl({
      legOpa: [],
      legPts: [null, null],
      pts: -0.004,
      ptp: null,
    })
    expect(result.ptsLine).toBe('PTS: -0.004')
  })
  it('truncates OPA to 3 legs with "..." for larger packages', () => {
    const result = formatOtherLvl({
      legOpa: [13900, 16000, 21400, 8100],
      ptp: 58400,
    })
    expect(result.opaLine).toBe('OPA: 13.9k / 16.0k / 21.4k ...')
  })

  it('shows all 3 OPA values without "..." for exactly 3 legs', () => {
    const result = formatOtherLvl({
      legOpa: [13900, 16000, 21400],
      ptp: 51300,
    })
    expect(result.opaLine).toBe('OPA: 13.9k / 16.0k / 21.4k')
  })

  it('appends currency suffix only on non-USD values', () => {
    const result = formatOtherLvl({
      legOpa: [15627.6],
      ptp: -671880,
      opaCurrency: ['EUR'],
      ptpCurrency: 'USD',
    })
    expect(result.opaLine).toBe('OPA: 15.6k EUR')
    // P2-01: 671.88 ≥ 100 → 0 decimals.
    expect(result.ptpLine).toBe('PTP: -672k')
  })
  it('renders Package Transaction Spread as the raw value, no unit coercion', () => {
    // Scale-aware bp/% conversion was removed because SDR reporters
    // disagree on units — show the raw decimal exactly as received.
    expect(formatOtherLvl({ legOpa: [], ptp: null, pts: 0.0025 }).ptsLine).toBe(
      'PTS: 0.0025',
    )
    expect(formatOtherLvl({ legOpa: [], ptp: null, pts: -0.0005 }).ptsLine).toBe(
      'PTS: -0.0005',
    )
    expect(formatOtherLvl({ legOpa: [], ptp: null, pts: 1.5 }).ptsLine).toBe(
      'PTS: 1.5',
    )
  })
  it('trims trailing zeros on the PTS value', () => {
    expect(formatOtherLvl({ legOpa: [], ptp: null, pts: 0.1 }).ptsLine).toBe(
      'PTS: 0.1',
    )
  })
  it('falls back to the empty marker when PTS is missing', () => {
    expect(formatOtherLvl({ legOpa: [], ptp: null }).ptsLine).toBe('PTS: \u2014')
    expect(formatOtherLvl({ legOpa: [], ptp: null, pts: null }).ptsLine).toBe(
      'PTS: \u2014',
    )
  })
})

describe('formatReportedLvl', () => {
  const baseRow = {
    legs_json: [],
    weighted_fixed_rate: null,
    trade_type: null,
  } as unknown as UsdSwapTapeRow

  it('returns the weighted rate for plain outright trades', () => {
    const row = {
      ...baseRow,
      trade_type: 'OUTRIGHT',
      weighted_fixed_rate: 0.03622,
    } as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622%')
  })

  it('joins per-leg rates with " / " for CURVE trades', () => {
    const row = {
      ...baseRow,
      trade_type: 'CURVE',
      weighted_fixed_rate: 0.036,
      legs_json: [
        { fixed_rate: 0.03622 },
        { fixed_rate: 0.03827 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622% / 3.827%')
  })

  it('joins three rates with " / " for FLY trades', () => {
    const row = {
      ...baseRow,
      trade_type: 'FLY',
      weighted_fixed_rate: 0.038,
      legs_json: [
        { fixed_rate: 0.03622 },
        { fixed_rate: 0.038 },
        { fixed_rate: 0.041 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622% / 3.800% / 4.100%')
  })

  it('is case-insensitive on trade_type', () => {
    const row = {
      ...baseRow,
      trade_type: 'curve',
      legs_json: [
        { fixed_rate: 0.01, tenor_years: 2 },
        { fixed_rate: 0.02, tenor_years: 10 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('1.000% / 2.000%')
  })

  it('orders CURVE legs by tenor: front leg first, back leg last', () => {
    // Legs arrive in reverse order (back leg first in legs_json) — must
    // still render short-tenor-first.
    const row = {
      ...baseRow,
      package_type: 'CURVE',
      legs_json: [
        { fixed_rate: 0.03878, tenor_years: 30 }, // back leg (30Y)
        { fixed_rate: 0.04132, tenor_years: 10 }, // front leg (10Y)
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('4.132% / 3.878%')
  })

  it('orders FLY legs: short wing / belly / long wing', () => {
    // User spec: front wing (short) -> belly (middle) -> back wing (long).
    const row = {
      ...baseRow,
      package_type: 'FLY',
      legs_json: [
        { fixed_rate: 0.04100, tenor_years: 10 }, // long wing
        { fixed_rate: 0.03800, tenor_years: 7 },  // belly
        { fixed_rate: 0.03622, tenor_years: 5 },  // short wing
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622% / 3.800% / 4.100%')
  })

  it('recognises SPREADOVER_CURVE composite types (per-leg rates)', () => {
    const row = {
      ...baseRow,
      package_type: 'SPREADOVER_CURVE',
      legs_json: [
        { fixed_rate: 0.03650, tenor_years: 5 },
        { fixed_rate: 0.03878, tenor_years: 10 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.650% / 3.878%')
  })

  it('recognises MATCHED_MATURITY_FLY composite types (per-leg rates)', () => {
    const row = {
      ...baseRow,
      package_type: 'MATCHED_MATURITY_FLY',
      legs_json: [
        { fixed_rate: 0.035, tenor_years: 5 },
        { fixed_rate: 0.038, tenor_years: 7 },
        { fixed_rate: 0.041, tenor_years: 10 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.500% / 3.800% / 4.100%')
  })

  it('recognises CURVE via package_type when trade_type is absent', () => {
    // The tape display view selects ``package_type`` but NOT ``trade_type``,
    // so main-tape rows arrive with ``trade_type=undefined``. The helper
    // must still render per-leg rates.
    const row = {
      ...baseRow,
      trade_type: undefined,
      package_type: 'CURVE',
      weighted_fixed_rate: 0.037,
      legs_json: [
        { fixed_rate: 0.03622 },
        { fixed_rate: 0.03827 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622% / 3.827%')
  })

  it('recognises FLY via package_type when trade_type is absent', () => {
    const row = {
      ...baseRow,
      trade_type: undefined,
      package_type: 'FLY',
      weighted_fixed_rate: 0.038,
      legs_json: [
        { fixed_rate: 0.03622 },
        { fixed_rate: 0.038 },
        { fixed_rate: 0.041 },
      ],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.622% / 3.800% / 4.100%')
  })

  it('falls back to weighted rate when a CURVE has <2 leg rates', () => {
    const row = {
      ...baseRow,
      trade_type: 'CURVE',
      weighted_fixed_rate: 0.036,
      legs_json: [{ fixed_rate: 0.03622 }],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.600%')
  })

  it('falls back to weighted rate when leg rates are null', () => {
    const row = {
      ...baseRow,
      trade_type: 'CURVE',
      weighted_fixed_rate: 0.036,
      legs_json: [{ fixed_rate: null }, { fixed_rate: null }],
    } as unknown as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe('3.600%')
  })

  it('returns EMPTY_VALUE when there is nothing to show', () => {
    const row = {
      ...baseRow,
      trade_type: 'OUTRIGHT',
      weighted_fixed_rate: null,
    } as UsdSwapTapeRow
    expect(formatReportedLvl(row)).toBe(EMPTY_VALUE)
  })
})

describe('formatTimestampDelta (Execution-vs-Event report lag)', () => {
  const exec = '2026-03-09T14:00:00Z'

  it('returns "unknown" when the execution timestamp is missing', () => {
    expect(formatTimestampDelta(null, exec)).toBe('unknown')
    expect(formatTimestampDelta(undefined, exec)).toBe('unknown')
  })

  it('returns "live" when the event timestamp is missing (not yet disseminated)', () => {
    expect(formatTimestampDelta(exec, null)).toBe('live')
    expect(formatTimestampDelta(exec, undefined)).toBe('live')
  })

  it('returns "unknown" on unparseable input', () => {
    expect(formatTimestampDelta('nope', 'nope')).toBe('unknown')
  })

  it('returns "0s" for a same-second report (fresh NEWT)', () => {
    expect(formatTimestampDelta(exec, exec)).toBe('0s')
  })

  it('formats sub-minute lag', () => {
    expect(formatTimestampDelta(exec, '2026-03-09T14:00:43Z')).toBe('+43s')
  })

  it('formats minute+second lag', () => {
    expect(formatTimestampDelta(exec, '2026-03-09T14:03:20Z')).toBe('+3m 20s')
  })

  it('formats hour lag as HH:MM:SS', () => {
    expect(formatTimestampDelta(exec, '2026-03-09T18:12:30Z')).toBe('+04:12:30')
  })

  it('formats multi-day lag as +Nd HH:MM (late amendment)', () => {
    expect(formatTimestampDelta(exec, '2026-03-12T18:12:00Z')).toBe('+3d 04:12')
  })

  it('shows a negative sign on an invariant breach (event before execution)', () => {
    expect(formatTimestampDelta(exec, '2026-03-09T13:59:01Z')).toBe('-59s')
  })
})
