'use client'
// ABOUTME: Modal chart showing timeseries for a given (groupBy, value).
import type { JSX } from 'react'
import { useMemo, useState } from 'react'
import { Dialog } from 'primereact/dialog'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { useTimeseriesData } from '../../hooks/useTimeseriesData'
import { TIMESERIES_METRICS, TIMESERIES_VIEWS } from '../../constants'
import type {
  TimeseriesGroupByKey,
  TimeseriesMetricKey,
  TimeseriesViewKey,
} from '../../types'

const GROUP_BY_OPTIONS: Array<{ key: TimeseriesGroupByKey; label: string }> = [
  { key: 'package', label: 'Package' },
  { key: 'tape_label', label: 'Tape label' },
  { key: 'trade_type', label: 'Trade type' },
  { key: 'tenor', label: 'Tenor' },
]

export interface TimeseriesChartProps {
  open: boolean
  onClose: () => void
  initialGroupBy?: TimeseriesGroupByKey
  initialValue?: string
}

export function TimeseriesChart(props: TimeseriesChartProps): JSX.Element {
  const [groupBy, setGroupBy] = useState<TimeseriesGroupByKey>(
    props.initialGroupBy ?? 'package',
  )
  const [value, setValue] = useState<string>(props.initialValue ?? '')
  const [metric, setMetric] = useState<TimeseriesMetricKey>('risk')
  const [view, setView] = useState<TimeseriesViewKey>('INTRADAY')
  const { points, loading, error } = useTimeseriesData({
    groupBy,
    value: value || null,
    metric,
    view,
    range: '1D',
  })

  const data = useMemo(
    () =>
      points.map((p) => ({
        ts: p.ts,
        value: typeof p.value === 'number' ? p.value : 0,
      })),
    [points],
  )

  return (
    <Dialog
      header="Timeseries"
      visible={props.open}
      onHide={props.onClose}
      style={{ width: '80vw', maxWidth: 1200 }}
      modal
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-1">
            <span className="text-slate-400">Group by</span>
            <select
              className="bg-slate-900 text-slate-100 rounded px-1 py-0.5"
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as TimeseriesGroupByKey)}
            >
              {GROUP_BY_OPTIONS.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <input
            type="text"
            placeholder="value"
            className="bg-slate-900 text-slate-100 rounded px-2 py-1 flex-1"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <label className="flex items-center gap-1">
            <span className="text-slate-400">Metric</span>
            <select
              className="bg-slate-900 text-slate-100 rounded px-1 py-0.5"
              value={metric}
              onChange={(e) => setMetric(e.target.value as TimeseriesMetricKey)}
            >
              {TIMESERIES_METRICS.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span className="text-slate-400">View</span>
            <select
              className="bg-slate-900 text-slate-100 rounded px-1 py-0.5"
              value={view}
              onChange={(e) => setView(e.target.value as TimeseriesViewKey)}
            >
              {TIMESERIES_VIEWS.map((v) => (
                <option key={v.key} value={v.key}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error ? <p className="text-red-300 text-sm">{error}</p> : null}
        {loading ? <p className="text-slate-400 text-sm">Loading…</p> : null}
        <div style={{ width: '100%', height: 360 }}>
          <ResponsiveContainer>
            <LineChart data={data}>
              <CartesianGrid stroke="#1e293b" />
              <XAxis dataKey="ts" stroke="#94a3b8" tick={{ fontSize: 10 }} />
              <YAxis stroke="#94a3b8" tick={{ fontSize: 10 }} />
              <Tooltip
                contentStyle={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                }}
              />
              <Line type="monotone" dataKey="value" stroke="#38bdf8" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Dialog>
  )
}
