import type { QuadrantDayAggregate } from './quadrantHistory.types'
import { classifyDayRegime } from './quadrantHistory.utils'

const REGIME_COLORS: Record<string, string> = {
  broad_receiver: 'bg-cyan-400',
  broad_payer: 'bg-emerald-400',
  steepener: 'bg-amber-400',
  flattener: 'bg-rose-400',
  gamma_receiver: 'bg-slate-400',
  vega_supply: 'bg-sky-400',
  mixed: 'bg-slate-600',
  quiet: 'bg-slate-800',
}

const REGIME_LABELS: Record<string, string> = {
  broad_receiver: 'Broad receiver',
  broad_payer: 'Broad payer',
  steepener: 'Steepener',
  flattener: 'Flattener',
  gamma_receiver: 'Gamma receiver',
  vega_supply: 'Vega supply',
  mixed: 'Mixed',
  quiet: 'Quiet',
}

type QuadrantRegimeStripProps = {
  days: QuadrantDayAggregate[]
  formatDateLabel: (date: string) => string
}

export function QuadrantRegimeStrip({ days, formatDateLabel }: QuadrantRegimeStripProps) {
  if (!days.length) return null

  const avgGross =
    days.reduce((sum, day) => sum + day.gridTotal.grossNotional, 0) / days.length

  return (
    <div className="mt-3 rounded border border-slate-800 bg-slate-950/50 px-3 py-2">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-400">
        Regime strip
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {days.map((day) => {
          const quietThreshold = avgGross * 0.5
          const isQuiet =
            avgGross > 0 && day.gridTotal.grossNotional < quietThreshold
          const regime = isQuiet ? 'quiet' : classifyDayRegime(day)
          const color = REGIME_COLORS[regime] ?? 'bg-slate-600'
          return (
            <span
              key={day.date}
              title={`${formatDateLabel(day.date)} - ${REGIME_LABELS[regime] ?? regime}`}
              className={`h-2.5 w-2.5 rounded-full ${color}`}
            />
          )
        })}
      </div>
      <div className="mt-2 text-[10px] text-slate-500">
        Legend: receiver, payer, steepener, flattener, quiet, mixed
      </div>
    </div>
  )
}
