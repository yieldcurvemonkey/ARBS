// ABOUTME: Pure utilities for quadrant history analytics and aggregation.

import type {
  DirectionStreak,
  FlowRegime,
  HistoryLookback,
  QuadrantDayAggregate,
  QuadrantDailyStats,
  QuadrantPeriodStats,
  VolGridQuadrant,
} from './quadrantHistory.types'

const QUADRANTS: VolGridQuadrant[] = ['ULC', 'URC', 'LLC', 'LRC']

const MS_PER_DAY = 24 * 60 * 60 * 1000

function coerceDateKey(value: string | Date): string {
  if (value instanceof Date) {
    return value.toISOString().slice(0, 10)
  }
  if (typeof value === 'string') {
    const match = value.match(/^(\d{4}-\d{2}-\d{2})/)
    if (match) return match[1]
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString().slice(0, 10)
    }
    return value
  }
  return String(value)
}

function createEmptyStats(): QuadrantDailyStats {
  return {
    tradeCount: 0,
    grossNotional: 0,
    netNotional: 0,
    netDirection: 'balanced',
    netGrossRatio: 0,
    totalPremium: 0,
    custyTradeCount: 0,
    idbTradeCount: 0,
    custyGross: 0,
    idbGross: 0,
    custyPremium: 0,
    idbPremium: 0,
  }
}

function cloneStats(source: QuadrantDailyStats): QuadrantDailyStats {
  return { ...source }
}

function normalizeStats(stats: QuadrantDailyStats): QuadrantDailyStats {
  const gross = stats.grossNotional
  const net = stats.netNotional
  stats.netGrossRatio = gross > 0 ? Math.abs(net) / gross : 0
  if (gross === 0) {
    stats.netDirection = 'balanced'
  } else if (stats.netGrossRatio < 0.1) {
    stats.netDirection = 'balanced'
  } else {
    stats.netDirection = net >= 0 ? 'payer' : 'receiver'
  }
  return stats
}

function addStats(target: QuadrantDailyStats, source: QuadrantDailyStats) {
  target.tradeCount += source.tradeCount
  target.grossNotional += source.grossNotional
  target.netNotional += source.netNotional
  target.totalPremium += source.totalPremium
  target.custyTradeCount += source.custyTradeCount
  target.idbTradeCount += source.idbTradeCount
  target.custyGross += source.custyGross
  target.idbGross += source.idbGross
  target.custyPremium += source.custyPremium
  target.idbPremium += source.idbPremium
}

function createEmptyDayAggregate(date: string): QuadrantDayAggregate {
  const quadrants = QUADRANTS.reduce(
    (acc, quadrant) => {
      acc[quadrant] = createEmptyStats()
      return acc
    },
    {} as Record<VolGridQuadrant, QuadrantDailyStats>,
  )
  return {
    date,
    quadrants,
    boundary: createEmptyStats(),
    unclassified: createEmptyStats(),
    gridTotal: createEmptyStats(),
  }
}

function recomputeGridTotal(day: QuadrantDayAggregate) {
  const total = createEmptyStats()
  QUADRANTS.forEach((quadrant) => addStats(total, day.quadrants[quadrant]))
  day.gridTotal = normalizeStats(total)
}

function toUtcDate(date: string | Date): Date {
  if (date instanceof Date) {
    return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()))
  }
  const match = date.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (match) {
    return new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])))
  }
  const parsed = new Date(date)
  if (Number.isNaN(parsed.getTime())) return parsed
  return new Date(Date.UTC(parsed.getUTCFullYear(), parsed.getUTCMonth(), parsed.getUTCDate()))
}

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10)
}

function getWeekStart(date: Date): string {
  const day = date.getUTCDay()
  const diff = day === 0 ? -6 : 1 - day
  const start = new Date(date)
  start.setUTCDate(start.getUTCDate() + diff)
  return toIsoDate(start)
}

function getMonthStart(date: Date): string {
  return toIsoDate(new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)))
}

function resolveDirection(stats: QuadrantDailyStats): 'payer' | 'receiver' | 'balanced' {
  if (stats.netDirection === 'payer' || stats.netDirection === 'receiver') {
    return stats.netDirection
  }
  const gross = stats.grossNotional
  if (gross === 0) return 'balanced'
  const ratio = gross > 0 ? Math.abs(stats.netNotional) / gross : 0
  if (ratio < 0.1) return 'balanced'
  return stats.netNotional >= 0 ? 'payer' : 'receiver'
}

export function computeRollingAverage(
  days: QuadrantDayAggregate[],
  quadrant: VolGridQuadrant,
  metric: 'netNotional' | 'grossNotional' | 'tradeCount' | 'totalPremium',
  windowSize: number,
): { date: string; value: number | null }[] {
  if (!days.length || windowSize <= 0) return []
  const values = days.map((day) => day.quadrants[quadrant][metric])
  const output: { date: string; value: number | null }[] = []

  for (let index = 0; index < values.length; index += 1) {
    if (index + 1 < windowSize) {
      output.push({ date: coerceDateKey(days[index].date as any), value: null })
      continue
    }
    let sum = 0
    for (let windowIndex = index - windowSize + 1; windowIndex <= index; windowIndex += 1) {
      sum += values[windowIndex] ?? 0
    }
    output.push({ date: coerceDateKey(days[index].date as any), value: sum / windowSize })
  }

  return output
}

export function computeDirectionStreak(
  days: QuadrantDayAggregate[],
  quadrant: VolGridQuadrant,
): DirectionStreak {
  if (!days.length) {
    return {
      quadrant,
      direction: 'balanced',
      consecutiveDays: 0,
      startDate: '',
    }
  }

  const firstDirection = resolveDirection(days[0].quadrants[quadrant])
  if (firstDirection === 'balanced') {
    return {
      quadrant,
      direction: 'balanced',
      consecutiveDays: 0,
      startDate: coerceDateKey(days[0].date as any),
    }
  }

  let count = 0
  let startDate = coerceDateKey(days[0].date as any)
  for (const day of days) {
    const direction = resolveDirection(day.quadrants[quadrant])
    if (direction !== firstDirection) break
    count += 1
    startDate = coerceDateKey(day.date as any)
  }

  return {
    quadrant,
    direction: firstDirection,
    consecutiveDays: count,
    startDate,
  }
}

export function computeQuadrantDivergence(
  days: QuadrantDayAggregate[],
  quadrantA: VolGridQuadrant,
  quadrantB: VolGridQuadrant,
  metric: 'netNotional' | 'grossNotional' | 'totalPremium',
): { date: string; divergence: number }[] {
  return days.map((day) => ({
    date: coerceDateKey(day.date as any),
    divergence: day.quadrants[quadrantA][metric] - day.quadrants[quadrantB][metric],
  }))
}

export function classifyDayRegime(day: QuadrantDayAggregate): FlowRegime {
  const nets = QUADRANTS.map((q) => day.quadrants[q].netNotional)
  const grossTotals = QUADRANTS.map((q) => day.quadrants[q].grossNotional)
  const allZero = grossTotals.every((value) => value === 0)
  if (allZero) return 'quiet'

  const allNegative = nets.every((value) => value < 0)
  if (allNegative) return 'broad_receiver'

  const allPositive = nets.every((value) => value > 0)
  if (allPositive) return 'broad_payer'

  const urc = day.quadrants.URC.netNotional
  const lrc = day.quadrants.LRC.netNotional
  if (urc < 0 && lrc > 0) return 'steepener'
  if (urc > 0 && lrc < 0) return 'flattener'

  const topRow = day.quadrants.ULC.netNotional + day.quadrants.URC.netNotional
  const bottomRow = day.quadrants.LLC.netNotional + day.quadrants.LRC.netNotional
  if (topRow < 0 && bottomRow >= 0) return 'gamma_receiver'
  if (bottomRow > 0 && topRow <= 0) return 'vega_supply'

  return 'mixed'
}

export function computeQuadrantPeriodStats(
  days: QuadrantDayAggregate[],
  quadrant: VolGridQuadrant,
): QuadrantPeriodStats {
  const totalDays = days.length
  const activeDays = days.filter((day) => day.quadrants[quadrant].tradeCount > 0)
  const activeCount = activeDays.length
  const avgDailyNet =
    activeCount > 0
      ? activeDays.reduce((sum, day) => sum + day.quadrants[quadrant].netNotional, 0) /
        activeCount
      : 0
  const avgDailyGross =
    activeCount > 0
      ? activeDays.reduce((sum, day) => sum + day.quadrants[quadrant].grossNotional, 0) /
        activeCount
      : 0
  const totalPremium = days.reduce(
    (sum, day) => sum + day.quadrants[quadrant].totalPremium,
    0,
  )
  const totalGridPremium = days.reduce((sum, day) => sum + day.gridTotal.totalPremium, 0)
  const premiumShare = totalGridPremium > 0 ? totalPremium / totalGridPremium : 0

  let payerDays = 0
  let receiverDays = 0
  activeDays.forEach((day) => {
    const direction = resolveDirection(day.quadrants[quadrant])
    if (direction === 'payer') payerDays += 1
    if (direction === 'receiver') receiverDays += 1
  })

  let majorityDirection: 'payer' | 'receiver' | 'balanced' = 'balanced'
  let majorityCount = 0
  if (payerDays > receiverDays) {
    majorityDirection = 'payer'
    majorityCount = payerDays
  } else if (receiverDays > payerDays) {
    majorityDirection = 'receiver'
    majorityCount = receiverDays
  }

  const netDirectionConsistency =
    activeCount > 0 && majorityCount > 0 ? majorityCount / activeCount : 0

  const sorted = ensureSortedDays(days)
  const daysDesc = [...sorted].reverse()
  const currentStreak = computeDirectionStreak(daysDesc, quadrant)

  let maxStreak: DirectionStreak = {
    quadrant,
    direction: 'balanced',
    consecutiveDays: 0,
    startDate: '',
  }
  let currentDirection: 'payer' | 'receiver' | null = null
  let currentCount = 0
  let currentStart = ''

  daysDesc.forEach((day) => {
    const direction = resolveDirection(day.quadrants[quadrant])
    if (direction !== 'payer' && direction !== 'receiver') {
      currentDirection = null
      currentCount = 0
      currentStart = ''
      return
    }

    if (currentDirection === direction) {
      currentCount += 1
    } else {
      currentDirection = direction
      currentCount = 1
    }
    currentStart = coerceDateKey(day.date as any)

    if (currentCount > maxStreak.consecutiveDays) {
      maxStreak = {
        quadrant,
        direction,
        consecutiveDays: currentCount,
        startDate: currentStart,
      }
    }
  })

  return {
    quadrant,
    activeDays: activeCount,
    totalDays,
    avgDailyNet,
    avgDailyGross,
    totalPremium,
    premiumShare,
    netDirectionConsistency,
    majorityDirection,
    currentStreak,
    maxStreak,
  }
}

export function computePremiumShares(days: QuadrantDayAggregate[]): {
  date: string
  ULC: number
  URC: number
  LLC: number
  LRC: number
}[] {
  return days.map((day) => {
    const dateKey = coerceDateKey(day.date as any)
    const total = QUADRANTS.reduce(
      (sum, quadrant) => sum + day.quadrants[quadrant].totalPremium,
      0,
    )
    if (total === 0) {
      return { date: dateKey, ULC: 0, URC: 0, LLC: 0, LRC: 0 }
    }
    return {
      date: dateKey,
      ULC: (day.quadrants.ULC.totalPremium / total) * 100,
      URC: (day.quadrants.URC.totalPremium / total) * 100,
      LLC: (day.quadrants.LLC.totalPremium / total) * 100,
      LRC: (day.quadrants.LRC.totalPremium / total) * 100,
    }
  })
}

function aggregateDays(
  days: QuadrantDayAggregate[],
  keyFn: (date: string) => string,
): QuadrantDayAggregate[] {
  const map = new Map<string, QuadrantDayAggregate>()

  days.forEach((day) => {
    const key = keyFn(coerceDateKey(day.date as any))
    let bucket = map.get(key)
    if (!bucket) {
      bucket = createEmptyDayAggregate(key)
      map.set(key, bucket)
    }

    QUADRANTS.forEach((quadrant) => {
      addStats(bucket!.quadrants[quadrant], day.quadrants[quadrant])
    })
    addStats(bucket.boundary, day.boundary)
    addStats(bucket.unclassified, day.unclassified)
  })

  const aggregated = Array.from(map.values())
  aggregated.forEach((day) => {
    QUADRANTS.forEach((quadrant) => normalizeStats(day.quadrants[quadrant]))
    normalizeStats(day.boundary)
    normalizeStats(day.unclassified)
    recomputeGridTotal(day)
  })

  return aggregated.sort((a, b) => a.date.localeCompare(b.date))
}

export function aggregateToWeekly(days: QuadrantDayAggregate[]): QuadrantDayAggregate[] {
  return aggregateDays(days, (date) => getWeekStart(toUtcDate(date)))
}

export function aggregateToMonthly(days: QuadrantDayAggregate[]): QuadrantDayAggregate[] {
  return aggregateDays(days, (date) => getMonthStart(toUtcDate(date)))
}

export function lookbackToDateRange(
  lookback: HistoryLookback,
  referenceDate?: string,
): { start: string; end: string } {
  const endDate = referenceDate ? toUtcDate(referenceDate) : new Date()
  const end = toIsoDate(endDate)

  const daysBack = (() => {
    switch (lookback) {
      case '1W':
        return 7
      case '1M':
        return 30
      case '3M':
        return 90
      case '6M':
        return 180
      case '1Y':
        return 365
      case 'ALL':
        return null
      default:
        return 90
    }
  })()

  if (daysBack === null) {
    return { start: '2000-01-01', end }
  }

  const startDate = new Date(endDate.getTime() - daysBack * MS_PER_DAY)
  return { start: toIsoDate(startDate), end }
}

export function mergeDayAggregate(
  base: QuadrantDayAggregate,
  override: QuadrantDayAggregate,
): QuadrantDayAggregate {
  const merged = createEmptyDayAggregate(coerceDateKey(base.date as any))
  QUADRANTS.forEach((quadrant) => {
    merged.quadrants[quadrant] = normalizeStats(cloneStats(base.quadrants[quadrant]))
  })
  merged.boundary = normalizeStats(cloneStats(base.boundary))
  merged.unclassified = normalizeStats(cloneStats(base.unclassified))
  merged.gridTotal = normalizeStats(cloneStats(base.gridTotal))

  QUADRANTS.forEach((quadrant) => {
    merged.quadrants[quadrant] = normalizeStats(cloneStats(override.quadrants[quadrant]))
  })
  merged.boundary = normalizeStats(cloneStats(override.boundary))
  merged.unclassified = normalizeStats(cloneStats(override.unclassified))
  merged.gridTotal = normalizeStats(cloneStats(override.gridTotal))
  merged.date = coerceDateKey(override.date as any)

  return merged
}

export function ensureSortedDays(days: QuadrantDayAggregate[]): QuadrantDayAggregate[] {
  const normalized = days.map((day) => {
    const dateKey = coerceDateKey(day.date as any)
    if (dateKey === day.date) return day
    return { ...day, date: dateKey }
  })
  return normalized.sort((a, b) => a.date.localeCompare(b.date))
}

export function buildGridTotal(day: QuadrantDayAggregate): QuadrantDailyStats {
  const total = createEmptyStats()
  QUADRANTS.forEach((quadrant) => addStats(total, day.quadrants[quadrant]))
  return normalizeStats(total)
}

export function ensureNormalizedDay(day: QuadrantDayAggregate): QuadrantDayAggregate {
  day.date = coerceDateKey(day.date as any)
  QUADRANTS.forEach((quadrant) => normalizeStats(day.quadrants[quadrant]))
  normalizeStats(day.boundary)
  normalizeStats(day.unclassified)
  day.gridTotal = buildGridTotal(day)
  return day
}

export function buildEmptyDayAggregate(date: string): QuadrantDayAggregate {
  return createEmptyDayAggregate(date)
}
