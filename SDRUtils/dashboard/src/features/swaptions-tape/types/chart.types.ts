// Timeseries chart types

export type TimeseriesChartType = "line" | "bar";

export type TimeseriesMetricKey =
  | "bpvolYr"
  | "bpvolDay"
  | "premiumBps"
  | "notional"
  | "premium"
  | "dv01"
  | "vega01"
  | "gamma01"
  | "theta01";

export type TimeseriesMetricDefinition = {
  key: TimeseriesMetricKey;
  label: string;
  color: string;
  decimals: number;
  chartType: TimeseriesChartType;
  unit?: string;
};

export type TimeseriesRangeKey =
  | "1D"
  | "1W"
  | "1M"
  | "3M"
  | "6M"
  | "1Y"
  | "CUSTOM"
  | "ALL";
export type TimeseriesViewKey = "INTRADAY" | "DAILY_CLOSE" | "DAILY_OHLC";

export type StraddleTimeseriesPoint = {
  timestamp: number;
  timeLabel: string;
  bpvolYr: number | null;
  bpvolDay: number | null;
  premiumBps: number | null;
  notional: number | null;
  premium: number | null;
  dv01: number | null;
  vega01: number | null;
  gamma01: number | null;
  theta01: number | null;
};

export type DailyTimeseriesPoint = {
  timestamp: number;
  timeLabel: string;
  open: number;
  high: number;
  low: number;
  close: number;
  daySum: number;
  range: number;
};

export type TimeseriesChartPoint = {
  timestamp: number;
  timeLabel: string;
  custyValue?: number | null;
  idbValue?: number | null;
};

export type TimeseriesExtremePoint = {
  value: number;
  timeLabel: string;
  timestamp: number;
};

export type TimeseriesSummaryStats = {
  tradeCount: number;
  totalNotional: number | null;
  avgNotional: number | null;
  medianNotional: number | null;
  tradesPerDay: number | null;
  avgGapMs: number | null;
  activeDays: number | null;
};

export type SeriesValuePoint = {
  timestamp: number;
  timeLabel: string;
  value: number;
};
