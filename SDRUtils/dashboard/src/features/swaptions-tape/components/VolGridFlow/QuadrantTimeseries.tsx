import { useMemo } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  HistoryMetricKey,
  QuadrantDayAggregate,
  VolGridQuadrant,
} from './quadrantHistory.types'
import { computeRollingAverage } from './quadrantHistory.utils'

export type QuadrantTimeseriesDatum = {
  date: string
  ULC: number | null
  URC: number | null
  LLC: number | null
  LRC: number | null
  raw: QuadrantDayAggregate
  isToday?: boolean
}

export type QuadrantTimeseriesFormatters = {
  formatNotional: (value: number | null | undefined) => string
  formatSignedNotional: (value: number | null | undefined) => string
  formatRate: (value: number | null | undefined, decimals?: number) => string
  formatCount: (value: number | null | undefined) => string
  formatDateLabel: (value: string) => string
}

export type QuadrantTimeseriesMetric = {
  key: HistoryMetricKey
  label: string
  yAxisLabel: string
  chartType: 'area' | 'bar' | 'line' | 'stackedArea'
}

type QuadrantTimeseriesProps = {
  data: QuadrantTimeseriesDatum[]
  days: QuadrantDayAggregate[]
  metric: QuadrantTimeseriesMetric
  formatters: QuadrantTimeseriesFormatters
  highlightDate?: string | null
  showLegend?: boolean
  showRollingAverage?: boolean
  singleQuadrant?: VolGridQuadrant
  compact?: boolean
  onDateSelect?: (date: string) => void
}

const QUADRANTS: VolGridQuadrant[] = ['ULC', 'URC', 'LLC', 'LRC']

const QUADRANT_COLORS: Record<VolGridQuadrant, { stroke: string; fill: string }> = {
  ULC: { stroke: '#94a3b8', fill: '#94a3b8' },
  URC: { stroke: '#fbbf24', fill: '#fbbf24' },
  LLC: { stroke: '#34d399', fill: '#34d399' },
  LRC: { stroke: '#38bdf8', fill: '#38bdf8' },
}

function renderTodayDot(props: any) {
  const { cx, cy, payload, dataKey, index } = props
  if (!payload?.isToday) return null
  const key = `today-dot-${payload?.date ?? 'na'}-${dataKey ?? 'series'}-${index ?? 0}`
  return (
    <circle
      key={key}
      cx={cx}
      cy={cy}
      r={3.5}
      fill="#e2e8f0"
      stroke="#0f172a"
      strokeWidth={1}
    />
  )
}

function renderTodayBar(props: any) {
  const { x, y, width, height, fill, payload } = props
  if (!width || !height) return null
  const adjustedHeight = Math.abs(height)
  const adjustedY = height < 0 ? y + height : y
  const stroke = payload?.isToday ? '#e2e8f0' : 'none'
  const strokeWidth = payload?.isToday ? 1 : 0
  return (
    <rect
      x={x}
      y={adjustedY}
      width={width}
      height={adjustedHeight}
      fill={fill}
      stroke={stroke}
      strokeWidth={strokeWidth}
      rx={2}
      ry={2}
    />
  )
}

function formatMetricTick(
  metric: QuadrantTimeseriesMetric,
  formatters: QuadrantTimeseriesFormatters,
) {
  const { formatNotional, formatRate, formatCount, formatSignedNotional } = formatters
  return (value: number) => {
    if (!Number.isFinite(value)) return '--'
    switch (metric.key) {
      case 'netNotional':
        return formatSignedNotional(value)
      case 'grossNotional':
      case 'totalPremium':
        return formatNotional(value)
      case 'tradeCount':
        return formatCount(value)
      case 'netGrossRatio':
        return formatRate(value, 2)
      case 'premiumShare':
      case 'custyShare':
        return `${formatRate(value, 1)}%`
      case 'pace':
        return `${formatRate(value, 2)}x`
      default:
        return formatRate(value, 2)
    }
  }
}

function QuadrantHistoryTooltip({
  active,
  payload,
  label,
  formatters,
}: {
  active?: boolean
  payload?: any[]
  label?: string
  formatters: QuadrantTimeseriesFormatters
}) {
  if (!active || !payload?.length) return null
  const day = payload[0]?.payload?.raw as QuadrantDayAggregate | undefined
  if (!day) return null

  const { formatNotional, formatSignedNotional } = formatters
  const header = label
    ? new Date(`${label}T00:00:00Z`).toLocaleDateString('en-US', {
        month: 'short',
        day: '2-digit',
        year: 'numeric',
        weekday: 'short',
      })
    : day.date
  const directionColor = (direction: string) => {
    if (direction === 'receiver') return 'text-cyan-300'
    if (direction === 'payer') return 'text-emerald-300'
    return 'text-slate-200'
  }

  return (
    <div className="rounded border border-slate-800 bg-slate-950/90 p-2 text-[11px] text-slate-200 shadow-lg">
      <div className="mb-2 text-xs font-semibold text-slate-100">{header}</div>
      <div className="space-y-1">
        {QUADRANTS.map((quadrant) => {
          const stats = day.quadrants[quadrant]
          return (
            <div key={quadrant} className="flex items-center justify-between gap-3">
              <span className="w-8 text-[10px] font-semibold text-slate-300">
                {quadrant}
              </span>
              <span className={`font-mono ${directionColor(stats.netDirection)}`}>
                {formatSignedNotional(stats.netNotional)} net
              </span>
              <span className="font-mono text-slate-400">
                {formatNotional(stats.grossNotional)} gross
              </span>
              <span className="font-mono text-slate-500">{stats.tradeCount} tr</span>
            </div>
          )
        })}
        <div className="mt-2 border-t border-slate-800 pt-1">
          <div className="flex items-center justify-between gap-3 text-[10px] text-slate-400">
            <span>Grid</span>
            <span className="font-mono text-slate-200">
              {formatSignedNotional(day.gridTotal.netNotional)} net
            </span>
            <span className="font-mono text-slate-500">
              {formatNotional(day.gridTotal.grossNotional)} gross
            </span>
            <span className="font-mono text-slate-500">
              {day.gridTotal.tradeCount} tr
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function buildRollingAverageSeries(
  days: QuadrantDayAggregate[],
  data: QuadrantTimeseriesDatum[],
  windowSize: number,
  suffix: string,
) {
  const series = QUADRANTS.reduce((acc, quadrant) => {
    const values = computeRollingAverage(days, quadrant, 'netNotional', windowSize)
    acc[quadrant] = values.map((entry) => entry.value)
    return acc
  }, {} as Record<VolGridQuadrant, Array<number | null>>)

  return data.map((datum, index) => ({
    ...datum,
    [`ULC_${suffix}`]: series.ULC[index] ?? null,
    [`URC_${suffix}`]: series.URC[index] ?? null,
    [`LLC_${suffix}`]: series.LLC[index] ?? null,
    [`LRC_${suffix}`]: series.LRC[index] ?? null,
  }))
}

export function QuadrantTimeseries({
  data,
  days,
  metric,
  formatters,
  highlightDate,
  showLegend = true,
  showRollingAverage = false,
  singleQuadrant,
  compact = false,
  onDateSelect,
}: QuadrantTimeseriesProps) {
  const quadrants = singleQuadrant ? [singleQuadrant] : QUADRANTS
  const dataWithRolling = useMemo(() => {
    if (!showRollingAverage || metric.key !== 'netNotional') return data
    const withFive = buildRollingAverageSeries(days, data, 5, 'ma5')
    return buildRollingAverageSeries(days, withFive, 20, 'ma20')
  }, [data, days, metric.key, showRollingAverage])

  const chartData = dataWithRolling

  const yAxisFormatter = formatMetricTick(metric, formatters)
  const yDomain =
    metric.key === 'netGrossRatio'
      ? [0, 1]
      : metric.key === 'premiumShare' || metric.key === 'custyShare'
        ? [0, 100]
        : ['auto', 'auto']

  const axisTick = {
    fill: '#94a3b8',
    fontSize: compact ? 9 : 10,
    fontFamily: 'ui-monospace',
  }
  const gridStroke = '#1f2937'

  const handleClick = (event: any) => {
    const label = event?.activeLabel
    if (label && onDateSelect) onDateSelect(label)
  }

  const renderSeries = () => {
    if (metric.chartType === 'bar') {
      return (
        <BarChart data={chartData} onClick={handleClick}>
          <CartesianGrid stroke={gridStroke} vertical={false} strokeWidth={0.5} />
          <XAxis dataKey="date" tick={axisTick} tickFormatter={formatters.formatDateLabel} />
          <YAxis
            tick={axisTick}
            tickFormatter={yAxisFormatter}
            domain={yDomain as any}
            label={
              compact
                ? undefined
                : {
                    value: metric.yAxisLabel,
                    angle: -90,
                    position: 'insideLeft',
                    fill: '#94a3b8',
                    fontSize: 10,
                  }
            }
          />
          <Tooltip
            content={<QuadrantHistoryTooltip formatters={formatters} />}
            cursor={{ stroke: '#475569', strokeDasharray: '3 3' }}
          />
          {highlightDate && (
            <ReferenceLine x={highlightDate} stroke="#64748b" strokeDasharray="4 4" />
          )}
          {quadrants.map((quadrant) => (
            <Bar
              key={quadrant}
              dataKey={quadrant}
              fill={QUADRANT_COLORS[quadrant].fill}
              radius={compact ? 0 : [2, 2, 0, 0]}
              shape={renderTodayBar}
            />
          ))}
          {showLegend && !compact && (
            <Legend
              verticalAlign="top"
              align="right"
              iconType="square"
              wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
            />
          )}
        </BarChart>
      )
    }

    if (metric.chartType === 'line') {
      return (
        <LineChart data={chartData} onClick={handleClick}>
          <CartesianGrid stroke={gridStroke} vertical={false} strokeWidth={0.5} />
          <XAxis dataKey="date" tick={axisTick} tickFormatter={formatters.formatDateLabel} />
          <YAxis
            tick={axisTick}
            tickFormatter={yAxisFormatter}
            domain={yDomain as any}
            label={
              compact
                ? undefined
                : {
                    value: metric.yAxisLabel,
                    angle: -90,
                    position: 'insideLeft',
                    fill: '#94a3b8',
                    fontSize: 10,
                  }
            }
          />
          <Tooltip
            content={<QuadrantHistoryTooltip formatters={formatters} />}
            cursor={{ stroke: '#475569', strokeDasharray: '3 3' }}
          />
          {highlightDate && (
            <ReferenceLine x={highlightDate} stroke="#64748b" strokeDasharray="4 4" />
          )}
          {quadrants.map((quadrant) => (
            <Line
              key={quadrant}
              type="monotone"
              dataKey={quadrant}
              stroke={QUADRANT_COLORS[quadrant].stroke}
              strokeWidth={compact ? 1 : 1.5}
              dot={renderTodayDot}
              connectNulls
            />
          ))}
          {showLegend && !compact && (
            <Legend
              verticalAlign="top"
              align="right"
              iconType="line"
              wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
            />
          )}
        </LineChart>
      )
    }

    if (metric.chartType === 'stackedArea') {
      return (
        <AreaChart data={chartData} onClick={handleClick}>
          <CartesianGrid stroke={gridStroke} vertical={false} strokeWidth={0.5} />
          <XAxis dataKey="date" tick={axisTick} tickFormatter={formatters.formatDateLabel} />
          <YAxis
            tick={axisTick}
            tickFormatter={yAxisFormatter}
            domain={yDomain as any}
            label={
              compact
                ? undefined
                : {
                    value: metric.yAxisLabel,
                    angle: -90,
                    position: 'insideLeft',
                    fill: '#94a3b8',
                    fontSize: 10,
                  }
            }
          />
          <Tooltip
            content={<QuadrantHistoryTooltip formatters={formatters} />}
            cursor={{ stroke: '#475569', strokeDasharray: '3 3' }}
          />
          {highlightDate && (
            <ReferenceLine x={highlightDate} stroke="#64748b" strokeDasharray="4 4" />
          )}
          {quadrants.map((quadrant) => (
            <Area
              key={quadrant}
              type="monotone"
              dataKey={quadrant}
              stackId="share"
              stroke={QUADRANT_COLORS[quadrant].stroke}
              strokeWidth={1.5}
              fill={QUADRANT_COLORS[quadrant].fill}
              fillOpacity={0.2}
              dot={renderTodayDot}
              connectNulls
            />
          ))}
          {showLegend && !compact && (
            <Legend
              verticalAlign="top"
              align="right"
              iconType="square"
              wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
            />
          )}
        </AreaChart>
      )
    }

    return (
      <AreaChart data={chartData} onClick={handleClick}>
        <CartesianGrid stroke={gridStroke} vertical={false} strokeWidth={0.5} />
        <XAxis dataKey="date" tick={axisTick} tickFormatter={formatters.formatDateLabel} />
        <YAxis
          tick={axisTick}
          tickFormatter={yAxisFormatter}
          domain={yDomain as any}
          label={
            compact
              ? undefined
              : {
                  value: metric.yAxisLabel,
                  angle: -90,
                  position: 'insideLeft',
                  fill: '#94a3b8',
                  fontSize: 10,
                }
          }
        />
        <Tooltip
          content={<QuadrantHistoryTooltip formatters={formatters} />}
          cursor={{ stroke: '#475569', strokeDasharray: '3 3' }}
        />
        {highlightDate && (
          <ReferenceLine x={highlightDate} stroke="#64748b" strokeDasharray="4 4" />
        )}
        <ReferenceLine y={0} stroke="#475569" strokeDasharray="4 4" />
        {quadrants.map((quadrant) => (
          <Area
            key={quadrant}
            type="monotone"
            dataKey={quadrant}
            stroke={QUADRANT_COLORS[quadrant].stroke}
            strokeWidth={1.5}
            fill={QUADRANT_COLORS[quadrant].fill}
            fillOpacity={0.15}
            dot={renderTodayDot}
            connectNulls
          />
        ))}
        {showRollingAverage && metric.key === 'netNotional' && !compact && (
          <>
            {quadrants.map((quadrant) => (
              <Line
                key={`${quadrant}-ma5`}
                type="monotone"
                dataKey={`${quadrant}_ma5`}
                stroke={QUADRANT_COLORS[quadrant].stroke}
                strokeWidth={1}
                strokeOpacity={0.6}
                dot={false}
                connectNulls
              />
            ))}
            {quadrants.map((quadrant) => (
              <Line
                key={`${quadrant}-ma20`}
                type="monotone"
                dataKey={`${quadrant}_ma20`}
                stroke={QUADRANT_COLORS[quadrant].stroke}
                strokeWidth={1}
                strokeOpacity={0.35}
                dot={false}
                connectNulls
              />
            ))}
          </>
        )}
        {showLegend && !compact && (
          <Legend
            verticalAlign="top"
            align="right"
            iconType="line"
            wrapperStyle={{ fontSize: '10px', color: '#94a3b8' }}
          />
        )}
      </AreaChart>
    )
  }

  return (
    <div className={compact ? 'h-40' : 'h-[220px] 2xl:h-[280px]'}>
      <ResponsiveContainer width="100%" height="100%">
        {renderSeries()}
      </ResponsiveContainer>
    </div>
  )
}
