// Hook for managing timeseries chart data
// TODO: Extract full implementation from SwaptionTradeTape.tsx (lines 1728-1995)

import { useEffect, useRef, useState } from 'react';
import type { TapeRow, StraddleTimeseriesPoint, DailyTimeseriesPoint, TimeseriesViewKey, TimeseriesMetricKey, TimeseriesRangeKey } from '../types';

export interface UseTimeseriesDataParams {
  seriesKey: string | null;
  isStraddle: boolean;
  excludeCusty: boolean;
}

export interface UseTimeseriesDataReturn {
  showTimeseries: boolean;
  setShowTimeseries: (show: boolean) => void;
  timeseriesView: TimeseriesViewKey;
  setTimeseriesView: (view: TimeseriesViewKey) => void;
  timeseriesMetric: TimeseriesMetricKey;
  setTimeseriesMetric: (metric: TimeseriesMetricKey) => void;
  timeseriesRange: TimeseriesRangeKey;
  setTimeseriesRange: (range: TimeseriesRangeKey) => void;
  customRangeStart: string;
  setCustomRangeStart: (date: string) => void;
  customRangeEnd: string;
  setCustomRangeEnd: (date: string) => void;
  showLineDots: boolean;
  setShowLineDots: (show: boolean) => void;
  excludeCusty: boolean;
  setExcludeCusty: (exclude: boolean) => void;
  timeseriesLoading: boolean;
  timeseriesError: string | null;
  timeseriesNotice: string | null;
  extraTimeseriesRows: TapeRow[];
  timeseriesData: StraddleTimeseriesPoint[];
  rangedTimeseriesData: StraddleTimeseriesPoint[];
  intradayChartData: StraddleTimeseriesPoint[];
  dailySeries: DailyTimeseriesPoint[];
  fetchTimeseriesRows: () => Promise<void>;
}

/**
 * Manages timeseries chart data fetching and state
 * Handles different view modes (intraday, daily close, OHLC)
 * Supports range selection and custom date ranges
 *
 * @param params - Series key and configuration
 * @returns Timeseries data and control functions
 */
export function useTimeseriesData(params: UseTimeseriesDataParams): UseTimeseriesDataReturn {
  const { seriesKey, isStraddle, excludeCusty: excludeCustyParam } = params;

  const [showTimeseries, setShowTimeseries] = useState(false);
  const [timeseriesView, setTimeseriesView] = useState<TimeseriesViewKey>('INTRADAY');
  const [timeseriesMetric, setTimeseriesMetric] = useState<TimeseriesMetricKey>('bpvolYr');
  const [timeseriesRange, setTimeseriesRange] = useState<TimeseriesRangeKey>('1Y');
  const [customRangeStart, setCustomRangeStart] = useState('');
  const [customRangeEnd, setCustomRangeEnd] = useState('');
  const [showLineDots, setShowLineDots] = useState(false);
  const [excludeCusty, setExcludeCusty] = useState(false);
  const [extraTimeseriesRows, setExtraTimeseriesRows] = useState<TapeRow[]>([]);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);
  const [timeseriesError, setTimeseriesError] = useState<string | null>(null);
  const [timeseriesNotice, setTimeseriesNotice] = useState<string | null>(null);

  const timeseriesFetchKeyRef = useRef<string | null>(null);
  const timeseriesFetchInFlight = useRef(false);

  // TODO: Extract computed values from lines 1759-1830
  const timeseriesData: StraddleTimeseriesPoint[] = [];
  const rangedTimeseriesData: StraddleTimeseriesPoint[] = [];
  const intradayChartData: StraddleTimeseriesPoint[] = [];
  const dailySeries: DailyTimeseriesPoint[] = [];

  // TODO: Extract fetchTimeseriesRows from lines 1927-1981
  const fetchTimeseriesRows = async () => {
    if (!seriesKey || !showTimeseries || timeseriesFetchInFlight.current) return;

    timeseriesFetchInFlight.current = true;
    setTimeseriesLoading(true);
    setTimeseriesError(null);
    setTimeseriesNotice(null);

    try {
      const params = new URLSearchParams({ seriesKey });
      if (excludeCusty) params.set('excludeCusty', 'true');

      const res = await fetch(`/api/swaptions-tape/timeseries?${params}`);
      if (!res.ok) throw new Error(`Fetch failed: ${res.statusText}`);

      const data = await res.json();
      setExtraTimeseriesRows(data.rows || []);

      if (data.truncated) {
        setTimeseriesNotice(`Data truncated to ${data.rows?.length || 0} rows`);
      }
    } catch (err) {
      setTimeseriesError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setTimeseriesLoading(false);
      timeseriesFetchInFlight.current = false;
    }
  };

  // Auto-fetch when seriesKey or dependencies change
  useEffect(() => {
    if (showTimeseries && seriesKey) {
      fetchTimeseriesRows();
    }
  }, [seriesKey, excludeCusty, showTimeseries]);

  return {
    showTimeseries,
    setShowTimeseries,
    timeseriesView,
    setTimeseriesView,
    timeseriesMetric,
    setTimeseriesMetric,
    timeseriesRange,
    setTimeseriesRange,
    customRangeStart,
    setCustomRangeStart,
    customRangeEnd,
    setCustomRangeEnd,
    showLineDots,
    setShowLineDots,
    excludeCusty,
    setExcludeCusty,
    timeseriesLoading,
    timeseriesError,
    timeseriesNotice,
    extraTimeseriesRows,
    timeseriesData,
    rangedTimeseriesData,
    intradayChartData,
    dailySeries,
    fetchTimeseriesRows,
  };
}
