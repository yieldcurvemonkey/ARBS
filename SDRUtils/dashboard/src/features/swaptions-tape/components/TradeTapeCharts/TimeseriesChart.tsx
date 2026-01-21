// Timeseries chart component
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines ~1500-2700)

"use client";

import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import type { TimeseriesMetricKey, TimeseriesViewKey, TimeseriesRangeKey, StraddleTimeseriesPoint } from '../../types';

export interface TimeseriesChartProps {
  visible: boolean;
  seriesKey: string | null;
  data: StraddleTimeseriesPoint[];
  metric: TimeseriesMetricKey;
  view: TimeseriesViewKey;
  range: TimeseriesRangeKey;
  showLineDots: boolean;
  loading: boolean;
  error: string | null;
  notice: string | null;
  onMetricChange: (metric: TimeseriesMetricKey) => void;
  onViewChange: (view: TimeseriesViewKey) => void;
  onRangeChange: (range: TimeseriesRangeKey) => void;
  onToggleLineDots: () => void;
  onClose: () => void;
}

/**
 * Timeseries chart for straddle trades
 * Supports multiple metrics, views, and date ranges
 */
export function TimeseriesChart(props: TimeseriesChartProps) {
  const {
    visible,
    seriesKey,
    data,
    metric,
    view,
    range,
    showLineDots,
    loading,
    error,
    notice,
    onMetricChange,
    onViewChange,
    onRangeChange,
    onToggleLineDots,
    onClose,
  } = props;

  if (!visible || !seriesKey) return null;

  // TODO: Extract chart controls (metric selector, view selector, range selector)
  // TODO: Extract chart rendering logic
  // TODO: Extract custom tooltip
  // TODO: Extract OHLC rendering for DAILY_OHLC view

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
      <div className="bg-gray-900 rounded-lg p-6 w-11/12 max-w-6xl max-h-[90vh] overflow-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-bold">Timeseries: {seriesKey}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            ✕
          </button>
        </div>

        {/* TODO: Add chart controls */}

        {/* Chart */}
        {loading && <div className="text-center py-8">Loading...</div>}
        {error && <div className="text-red-500 text-center py-8">{error}</div>}
        {notice && <div className="text-yellow-500 text-sm mb-2">{notice}</div>}

        {!loading && !error && data.length > 0 && (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="timeLabel" stroke="#9ca3af" />
              <YAxis stroke="#9ca3af" />
              <Tooltip />
              <Line
                type="monotone"
                dataKey={metric}
                stroke="#38bdf8"
                dot={showLineDots}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
