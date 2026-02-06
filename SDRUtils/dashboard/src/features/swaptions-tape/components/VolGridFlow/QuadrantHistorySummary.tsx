import type { QuadrantDayAggregate, VolGridQuadrant } from './quadrantHistory.types'
import { computeQuadrantPeriodStats } from './quadrantHistory.utils'

export type QuadrantHistorySummaryFormatters = {
  formatNotional: (value: number | null | undefined) => string
  formatSignedNotional: (value: number | null | undefined) => string
  formatRate: (value: number | null | undefined, decimals?: number) => string
  formatDateLabel: (value: string) => string
}

type QuadrantHistorySummaryProps = {
  days: QuadrantDayAggregate[]
  formatters: QuadrantHistorySummaryFormatters
  lookbackLabel: string
}

const QUADRANTS: VolGridQuadrant[] = ['ULC', 'URC', 'LLC', 'LRC']

const directionLabel = (direction: string) => {
  if (direction === 'receiver') return 'rcvr'
  if (direction === 'payer') return 'pyr'
  return 'mixed'
}

export function QuadrantHistorySummary({
  days,
  formatters,
  lookbackLabel,
}: QuadrantHistorySummaryProps) {
  const { formatNotional, formatRate, formatDateLabel } = formatters
  const stats = QUADRANTS.map((quadrant) =>
    computeQuadrantPeriodStats(days, quadrant),
  )

  return (
    <div className="mt-3 rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        Period Summary ({lookbackLabel})
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        {stats.map((entry) => {
          const consistency = entry.netDirectionConsistency * 100
          const streak = entry.currentStreak
          const streakLabel =
            streak.consecutiveDays > 0
              ? `${directionLabel(streak.direction)} ${streak.consecutiveDays}d since ${
                  streak.startDate ? formatDateLabel(streak.startDate) : '--'
                }`
              : 'no streak'
          return (
            <div key={entry.quadrant} className="space-y-1">
              <div className="text-[11px] font-semibold text-slate-100">
                {entry.quadrant}
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Days</span>
                <span className="font-mono text-slate-200">
                  {entry.activeDays}/{entry.totalDays}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Avg net</span>
                <span className="font-mono text-slate-200">
                  {formatters.formatSignedNotional(entry.avgDailyNet)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Direction</span>
                <span className="font-mono text-slate-200">
                  {directionLabel(entry.majorityDirection)} {formatRate(consistency, 0)}%
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Avg gross</span>
                <span className="font-mono text-slate-200">
                  {formatNotional(entry.avgDailyGross)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Total prem</span>
                <span className="font-mono text-slate-200">
                  {formatNotional(entry.totalPremium)}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">Prem share</span>
                <span className="font-mono text-slate-200">
                  {formatRate(entry.premiumShare * 100, 1)}%
                </span>
              </div>
              <div className="text-[10px] text-slate-400">Streak: {streakLabel}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
