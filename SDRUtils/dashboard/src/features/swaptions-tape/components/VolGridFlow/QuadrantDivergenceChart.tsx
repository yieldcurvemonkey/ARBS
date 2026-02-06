import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { QuadrantDayAggregate } from './quadrantHistory.types'
import { computeQuadrantDivergence } from './quadrantHistory.utils'

export type QuadrantDivergenceFormatters = {
  formatSignedNotional: (value: number | null | undefined) => string
  formatRate: (value: number | null | undefined, decimals?: number) => string
}

type QuadrantDivergenceChartProps = {
  days: QuadrantDayAggregate[]
  formatters: QuadrantDivergenceFormatters
  highlightDate?: string | null
  formatDateLabel: (value: string) => string
}

export function QuadrantDivergenceChart({
  days,
  formatters,
  highlightDate,
  formatDateLabel,
}: QuadrantDivergenceChartProps) {
  if (!days.length) return null

  const data = computeQuadrantDivergence(days, 'URC', 'LRC', 'netNotional')

  return (
    <div className="mt-3 rounded border border-slate-800 bg-slate-950/60 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wide text-slate-400">
        URC - LRC divergence
      </div>
      <div className="h-32">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid stroke="#1f2937" vertical={false} strokeWidth={0.5} />
            <XAxis
              dataKey="date"
              tick={{ fill: '#94a3b8', fontSize: 9, fontFamily: 'ui-monospace' }}
              tickFormatter={formatDateLabel}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 9, fontFamily: 'ui-monospace' }}
              tickFormatter={(value: number) => formatters.formatSignedNotional(value)}
            />
            <Tooltip
              formatter={(value: number) => formatters.formatSignedNotional(value)}
              labelFormatter={formatDateLabel}
              contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #1f2937' }}
            />
            {highlightDate && (
              <ReferenceLine x={highlightDate} stroke="#64748b" strokeDasharray="4 4" />
            )}
            <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
            <Line
              type="monotone"
              dataKey="divergence"
              stroke="#fbbf24"
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
