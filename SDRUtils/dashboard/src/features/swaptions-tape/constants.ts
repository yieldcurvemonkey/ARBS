// Constants for swaptions tape
import type { TimeseriesMetricDefinition, TimeseriesMetricKey, TimeseriesRangeKey, TimeseriesViewKey } from './types/chart.types';

// Action sets
export const SAFE_ACTIONS = new Set(["NEWT", "TRAD", "MODI"]);
export const ACTIVE_ACTIONS = new Set(["NEWT-TRAD", "MODI-TRAD", "CORR-TRAD"]);

// Polling and UI constants
export const POLL_INTERVAL_MS = 5000;
export const ROW_ESTIMATE_PX = 44;
export const EMPTY_VALUE = "\u2014";

// Package background colors
export const PACKAGE_TONES: Record<string, string> = {
  STRADDLE: "!bg-purple-900/30",
  RISK_REVERSAL: "!bg-amber-900/30",
  VERTICAL_SPREAD_1X1: "!bg-blue-900/30",
  VERTICAL_SPREAD_1X2: "!bg-cyan-900/30",
  RECEIVER_LADDER: "!bg-emerald-900/30",
  CUSTY_RR_STRANGLE: "!bg-lime-900/30",
  CAP: "!bg-teal-900/30",
  FLOOR: "!bg-indigo-900/30",
  OUTRIGHT: "!bg-gray-800/50",
};

export const NESTED_TABLE_BG = "bg-slate-900/50";

// Action colors (empty for now, extensible)
export const ACTION_TONES: Record<string, string> = {
  NEWT: "",
  TRAD: "",
  MODI: "",
};

// Column definitions for the table
export const COLUMN_DEFS = [
  { key: "event_action", label: "Action", width: 110 },
  { key: "package_type", label: "Package Type", width: 150 },
  { key: "time", label: "Time", width: 180 },
  { key: "platform", label: "Platform", width: 120 },
  { key: "notional", label: "Notional", width: 130 },
  { key: "label", label: "Trade Label", width: 700 },
];

// Metric schema for different package types
export const METRIC_SCHEMA = {
  STRADDLE: {
    bpvol: "straddle_bpvol_yr",
    theta01: "straddle_theta1d",
    greeks: {
      dv01: "straddle_dv01",
      vega01: "straddle_vega01",
      gamma01: "straddle_gamma01",
    },
  },
  RISK_REVERSAL: {
    bpvol: "rr_atm_bpvol",
    skew: {
      payer: "rr_payer_skew",
      receiver: "rr_receiver_skew",
    },
    greeks: {
      dv01: "rr_wing_dv01",
      vega01: "rr_vega01",
    },
  },
  VERTICAL_SPREAD_1X1: {
    bpvol: ["vs_atm_bpvol_yr", "vs_otm_bpvol_yr"],
    greeks: {
      dv01: ["vs_atm_dv01", "vs_otm_dv01"],
      vega01: ["vs_atm_vega01", "vs_otm_vega01"],
    },
  },
  VERTICAL_SPREAD_1X2: {
    bpvol: ["vs_atm_bpvol_yr", "vs_otm_bpvol_yr"],
    greeks: {
      dv01: ["vs_atm_dv01", "vs_otm_dv01"],
      vega01: ["vs_atm_vega01", "vs_otm_vega01"],
    },
  },
  RECEIVER_LADDER: {
    cols: ["ladder_strikes", "ladder_notionals"],
  },
  PAYER_LADDER: {
    cols: ["ladder_strikes", "ladder_notionals"],
  },
} as const;

// Straddle constants
export const STRADDLE_STYLE = "EURO VANILLA PHYS";
export const STRADDLE_SPLIT_FACTOR = 0.5;
export const BPVOL_DAY_DIVISOR = 15.87;

// Platform constants
export const CUSTY_PLATFORMS = new Set(["BILT", "XXXX"]);

// Straddle greek field mappings
export const STRADDLE_GREEK_FIELDS = {
  dv01: "straddle_dv01",
  vega01: "straddle_vega01",
  gamma01: "straddle_gamma01",
  theta01: "straddle_theta1d",
} as const;

// Timeseries metric definitions
export const TIMESERIES_METRICS: TimeseriesMetricDefinition[] = [
  {
    key: "bpvolYr",
    label: "BPVol/Yr",
    unit: "bpvol/yr",
    color: "#38bdf8",
    decimals: 3,
    chartType: "line",
  },
  {
    key: "bpvolDay",
    label: "BPVol/day",
    unit: "bpvol/day",
    color: "#f59e0b",
    decimals: 3,
    chartType: "line",
  },
  {
    key: "premiumBps",
    label: "Premium (bps)",
    unit: "bps",
    color: "#f97316",
    decimals: 2,
    chartType: "line",
  },
  {
    key: "notional",
    label: "Notional",
    unit: "USD",
    color: "#22c55e",
    decimals: 1,
    chartType: "bar",
  },
  {
    key: "premium",
    label: "Premium",
    unit: "USD",
    color: "#0ea5e9",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "dv01",
    label: "DV01",
    unit: "USD/bp",
    color: "#a855f7",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "vega01",
    label: "Vega01",
    unit: "USD/bp",
    color: "#f472b6",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "gamma01",
    label: "Gamma01",
    unit: "USD/bp^2",
    color: "#eab308",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "theta01",
    label: "Theta1D",
    unit: "USD/day",
    color: "#fb7185",
    decimals: 2,
    chartType: "bar",
  },
];

// Cumulative metrics for daily close view
export const DAILY_CLOSE_CUMULATIVE_METRICS = new Set<TimeseriesMetricKey>([
  "notional",
  "dv01",
  "vega01",
  "gamma01",
  "theta01",
]);

// Timeseries range options
export const TIMESERIES_RANGE_OPTIONS: Array<{
  key: TimeseriesRangeKey;
  label: string;
  days: number | null;
}> = [
  { key: "1D", label: "1D", days: 1 },
  { key: "1W", label: "1W", days: 7 },
  { key: "1M", label: "1M", days: 30 },
  { key: "3M", label: "3M", days: 90 },
  { key: "6M", label: "6M", days: 180 },
  { key: "1Y", label: "1Y", days: 365 },
  { key: "CUSTOM", label: "Custom", days: null },
  { key: "ALL", label: "All", days: null },
];

// Timeseries view options
export const TIMESERIES_VIEW_OPTIONS: Array<{
  key: TimeseriesViewKey;
  label: string;
}> = [
  { key: "INTRADAY", label: "Intraday" },
  { key: "DAILY_CLOSE", label: "Daily Close" },
  { key: "DAILY_OHLC", label: "Daily OHLC" },
];

// Timeseries fetch limit
export const TIMESERIES_FETCH_LIMIT = 500;
