import { QuadrantTimeseries, QuadrantTimeseriesDatum, QuadrantTimeseriesFormatters, QuadrantTimeseriesMetric } from './QuadrantTimeseries'
import type { QuadrantDayAggregate, VolGridQuadrant } from './quadrantHistory.types'

const QUADRANT_LAYOUT: Array<{ key: VolGridQuadrant; label: string }> = [
  { key: 'ULC', label: 'ULC' },
  { key: 'URC', label: 'URC' },
  { key: 'LLC', label: 'LLC' },
  { key: 'LRC', label: 'LRC' },
]

type QuadrantTimeseriesGridProps = {
  data: QuadrantTimeseriesDatum[]
  days: QuadrantDayAggregate[]
  metric: QuadrantTimeseriesMetric
  formatters: QuadrantTimeseriesFormatters
  highlightDate?: string | null
  showRollingAverage?: boolean
  onDateSelect?: (date: string) => void
}

export function QuadrantTimeseriesGrid({
  data,
  days,
  metric,
  formatters,
  highlightDate,
  showRollingAverage,
  onDateSelect,
}: QuadrantTimeseriesGridProps) {
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {QUADRANT_LAYOUT.map((quadrant) => (
        <div key={quadrant.key} className="rounded border border-slate-800 bg-slate-950/40 p-2">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300">
            {quadrant.label}
          </div>
          <QuadrantTimeseries
            data={data}
            days={days}
            metric={metric}
            formatters={formatters}
            highlightDate={highlightDate}
            showLegend={false}
            showRollingAverage={showRollingAverage}
            singleQuadrant={quadrant.key}
            compact
            onDateSelect={onDateSelect}
          />
        </div>
      ))}
    </div>
  )
}
