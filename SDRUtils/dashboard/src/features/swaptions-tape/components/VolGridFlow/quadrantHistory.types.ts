// ABOUTME: Types for Vol Grid Flow quadrant history data and analytics.

export type VolGridQuadrant = 'ULC' | 'URC' | 'LLC' | 'LRC'

export type QuadrantConfig = {
  expiryBoundaryYears: number
  tenorBoundaryYears: number
  boundaryToleranceYears: number
}

export type QuadrantDailyStats = {
  tradeCount: number
  grossNotional: number
  netNotional: number
  netDirection: 'payer' | 'receiver' | 'balanced'
  netGrossRatio: number
  totalPremium: number
  custyTradeCount: number
  idbTradeCount: number
  custyGross: number
  idbGross: number
  custyPremium: number
  idbPremium: number
}

export type QuadrantDayAggregate = {
  date: string
  quadrants: Record<VolGridQuadrant, QuadrantDailyStats>
  boundary: QuadrantDailyStats
  unclassified: QuadrantDailyStats
  gridTotal: QuadrantDailyStats
}

export type QuadrantHistoryResponse = {
  days: QuadrantDayAggregate[]
  meta: {
    start: string
    end: string
    tradingDaysCount: number
    expiryBoundary: number
    tenorBoundary: number
    tolerance: number
    platform: 'combined' | 'idb' | 'custy'
  }
}

export type DirectionStreak = {
  quadrant: VolGridQuadrant
  direction: 'payer' | 'receiver' | 'balanced'
  consecutiveDays: number
  startDate: string
}

export type FlowRegime =
  | 'broad_receiver'
  | 'broad_payer'
  | 'steepener'
  | 'flattener'
  | 'gamma_receiver'
  | 'vega_supply'
  | 'mixed'
  | 'quiet'

export type QuadrantPeriodStats = {
  quadrant: VolGridQuadrant
  activeDays: number
  totalDays: number
  avgDailyNet: number
  avgDailyGross: number
  totalPremium: number
  premiumShare: number
  netDirectionConsistency: number
  majorityDirection: 'payer' | 'receiver' | 'balanced'
  currentStreak: DirectionStreak
  maxStreak: DirectionStreak
}

export type HistoryMetricKey =
  | 'netNotional'
  | 'grossNotional'
  | 'tradeCount'
  | 'totalPremium'
  | 'netGrossRatio'
  | 'premiumShare'
  | 'custyShare'
  | 'pace'

export type HistoryViewMode = 'stacked' | 'grid'
export type HistoryAggregation = 'daily' | 'weekly' | 'monthly'

export type HistoryLookback = '1W' | '1M' | '3M' | '6M' | '1Y' | 'ALL'
