import { describe, expect, it } from '@jest/globals'
import type { QuadrantDayAggregate, QuadrantDailyStats, VolGridQuadrant } from '../quadrantHistory.types'
import {
  aggregateToMonthly,
  aggregateToWeekly,
  classifyDayRegime,
  computeDirectionStreak,
  computePremiumShares,
  computeQuadrantDivergence,
  computeRollingAverage,
} from '../quadrantHistory.utils'

const makeStats = (
  net: number,
  overrides: Partial<QuadrantDailyStats> = {},
): QuadrantDailyStats => ({
  tradeCount: overrides.tradeCount ?? 1,
  grossNotional: overrides.grossNotional ?? Math.max(Math.abs(net), 1),
  netNotional: net,
  netDirection: overrides.netDirection ?? (net > 0 ? 'payer' : net < 0 ? 'receiver' : 'balanced'),
  netGrossRatio: overrides.netGrossRatio ?? 1,
  totalPremium: overrides.totalPremium ?? 0,
  custyTradeCount: overrides.custyTradeCount ?? 0,
  idbTradeCount: overrides.idbTradeCount ?? 0,
  custyGross: overrides.custyGross ?? 0,
  idbGross: overrides.idbGross ?? 0,
  custyPremium: overrides.custyPremium ?? 0,
  idbPremium: overrides.idbPremium ?? 0,
})

const makeDay = (date: string, nets: Record<VolGridQuadrant, number>): QuadrantDayAggregate => {
  const quadrants = {
    ULC: makeStats(nets.ULC),
    URC: makeStats(nets.URC),
    LLC: makeStats(nets.LLC),
    LRC: makeStats(nets.LRC),
  }
  return {
    date,
    quadrants,
    boundary: makeStats(0, { tradeCount: 0, grossNotional: 0, netGrossRatio: 0 }),
    unclassified: makeStats(0, { tradeCount: 0, grossNotional: 0, netGrossRatio: 0 }),
    gridTotal: makeStats(
      nets.ULC + nets.URC + nets.LLC + nets.LRC,
      { grossNotional: Object.values(nets).reduce((sum, value) => sum + Math.abs(value), 0) },
    ),
  }
}

describe('quadrantHistory.utils', () => {
  it('computeDirectionStreak handles consecutive receiver days', () => {
    const days = [
      makeDay('2026-02-05', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-04', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-03', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-02', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-01', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
    ]
    const streak = computeDirectionStreak(days, 'URC')
    expect(streak.direction).toBe('receiver')
    expect(streak.consecutiveDays).toBe(5)
  })

  it('computeDirectionStreak breaks on opposite direction', () => {
    const days = [
      makeDay('2026-02-05', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-04', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
      makeDay('2026-02-03', { ULC: -1, URC: 2, LLC: 1, LRC: 1 }),
      makeDay('2026-02-02', { ULC: -1, URC: -1, LLC: 1, LRC: 1 }),
    ]
    const streak = computeDirectionStreak(days, 'URC')
    expect(streak.direction).toBe('receiver')
    expect(streak.consecutiveDays).toBe(2)
  })

  it('computeDirectionStreak handles single day', () => {
    const days = [makeDay('2026-02-05', { ULC: 1, URC: 1, LLC: 1, LRC: 1 })]
    const streak = computeDirectionStreak(days, 'ULC')
    expect(streak.direction).toBe('payer')
    expect(streak.consecutiveDays).toBe(1)
  })

  it('computeDirectionStreak handles balanced breaks', () => {
    const day1 = makeDay('2026-02-05', { ULC: -1, URC: -1, LLC: 1, LRC: 1 })
    day1.quadrants.URC.netDirection = 'receiver'
    const day2 = makeDay('2026-02-04', { ULC: 0, URC: 0, LLC: 0, LRC: 0 })
    day2.quadrants.URC.netDirection = 'balanced'
    const day3 = makeDay('2026-02-03', { ULC: -1, URC: -1, LLC: 1, LRC: 1 })

    const streak = computeDirectionStreak([day1, day2, day3], 'URC')
    expect(streak.direction).toBe('receiver')
    expect(streak.consecutiveDays).toBe(1)
  })

  it('computeDirectionStreak handles empty input', () => {
    const streak = computeDirectionStreak([], 'ULC')
    expect(streak.direction).toBe('balanced')
    expect(streak.consecutiveDays).toBe(0)
  })

  it('classifyDayRegime detects broad receiver and payer', () => {
    const receiverDay = makeDay('2026-02-05', { ULC: -100, URC: -200, LLC: -50, LRC: -80 })
    const payerDay = makeDay('2026-02-06', { ULC: 100, URC: 200, LLC: 50, LRC: 80 })
    expect(classifyDayRegime(receiverDay)).toBe('broad_receiver')
    expect(classifyDayRegime(payerDay)).toBe('broad_payer')
  })

  it('classifyDayRegime detects steepener and flattener', () => {
    const steepener = makeDay('2026-02-05', { ULC: -50, URC: -300, LLC: 20, LRC: 250 })
    const flattener = makeDay('2026-02-05', { ULC: 50, URC: 200, LLC: -30, LRC: -180 })
    expect(classifyDayRegime(steepener)).toBe('steepener')
    expect(classifyDayRegime(flattener)).toBe('flattener')
  })

  it('computeRollingAverage computes rolling values', () => {
    const days = ['2026-02-01', '2026-02-02', '2026-02-03', '2026-02-04', '2026-02-05'].map(
      (date, index) => makeDay(date, { ULC: (index + 1) * 10, URC: 0, LLC: 0, LRC: 0 }),
    )
    const result = computeRollingAverage(days, 'ULC', 'netNotional', 3)
    expect(result.map((entry) => entry.value)).toEqual([null, null, 20, 30, 40])
  })

  it('computeRollingAverage handles window larger than data', () => {
    const days = ['2026-02-01', '2026-02-02', '2026-02-03'].map((date) =>
      makeDay(date, { ULC: 10, URC: 0, LLC: 0, LRC: 0 }),
    )
    const result = computeRollingAverage(days, 'ULC', 'netNotional', 5)
    expect(result.map((entry) => entry.value)).toEqual([null, null, null])
  })

  it('computeRollingAverage handles single value', () => {
    const days = [makeDay('2026-02-01', { ULC: 100, URC: 0, LLC: 0, LRC: 0 })]
    const result = computeRollingAverage(days, 'ULC', 'netNotional', 1)
    expect(result.map((entry) => entry.value)).toEqual([100])
  })

  it('computeRollingAverage handles empty', () => {
    expect(computeRollingAverage([], 'ULC', 'netNotional', 5)).toEqual([])
  })

  it('computeQuadrantDivergence computes differences', () => {
    const day = makeDay('2026-02-05', { ULC: 0, URC: -200, LLC: 0, LRC: 100 })
    const result = computeQuadrantDivergence([day], 'URC', 'LRC', 'netNotional')
    expect(result[0].divergence).toBe(-300)
  })

  it('computeQuadrantDivergence handles empty', () => {
    expect(computeQuadrantDivergence([], 'URC', 'LRC', 'netNotional')).toEqual([])
  })

  it('computePremiumShares handles equal, dominant, and zero totals', () => {
    const equal = makeDay('2026-02-01', { ULC: 0, URC: 0, LLC: 0, LRC: 0 })
    equal.quadrants.ULC.totalPremium = 100
    equal.quadrants.URC.totalPremium = 100
    equal.quadrants.LLC.totalPremium = 100
    equal.quadrants.LRC.totalPremium = 100

    const dominant = makeDay('2026-02-02', { ULC: 0, URC: 0, LLC: 0, LRC: 0 })
    dominant.quadrants.ULC.totalPremium = 0
    dominant.quadrants.URC.totalPremium = 400
    dominant.quadrants.LLC.totalPremium = 0
    dominant.quadrants.LRC.totalPremium = 0

    const zero = makeDay('2026-02-03', { ULC: 0, URC: 0, LLC: 0, LRC: 0 })
    zero.quadrants.ULC.totalPremium = 0
    zero.quadrants.URC.totalPremium = 0
    zero.quadrants.LLC.totalPremium = 0
    zero.quadrants.LRC.totalPremium = 0

    const shares = computePremiumShares([equal, dominant, zero])
    expect(shares[0]).toEqual({ date: '2026-02-01', ULC: 25, URC: 25, LLC: 25, LRC: 25 })
    expect(shares[1]).toEqual({ date: '2026-02-02', ULC: 0, URC: 100, LLC: 0, LRC: 0 })
    expect(shares[2]).toEqual({ date: '2026-02-03', ULC: 0, URC: 0, LLC: 0, LRC: 0 })
  })

  it('aggregateToWeekly groups days into weeks', () => {
    const days = [] as QuadrantDayAggregate[]
    for (let i = 1; i <= 10; i += 1) {
      const day = `2026-01-${String(i).padStart(2, '0')}`
      days.push(makeDay(day, { ULC: i, URC: 0, LLC: 0, LRC: 0 }))
    }
    const weekly = aggregateToWeekly(days)
    expect(weekly.length).toBe(2)
    const totalNet = weekly.reduce((sum, week) => sum + week.quadrants.ULC.netNotional, 0)
    expect(totalNet).toBe(days.reduce((sum, day) => sum + day.quadrants.ULC.netNotional, 0))
  })

  it('aggregateToMonthly groups days into months', () => {
    const jan = makeDay('2026-01-15', { ULC: 10, URC: 0, LLC: 0, LRC: 0 })
    const feb = makeDay('2026-02-15', { ULC: 20, URC: 0, LLC: 0, LRC: 0 })
    const monthly = aggregateToMonthly([jan, feb])
    expect(monthly.length).toBe(2)
  })
})
