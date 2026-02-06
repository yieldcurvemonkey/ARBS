// ABOUTME: USD Swaptions Trade Tape table (event action + package summary) powered by arbs_swaption_display_items_v2
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Link2,
  RefreshCw,
  X,
  XCircle,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Customized,
  Line,
  LineChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TradeRarityPanel } from "./TradeRarityPanel/TradeRarityPanel";
import { TimeseriesAnnotations } from "./TradeRarityPanel/TimeseriesAnnotations";
import {
  DataTable,
  DataTableFilterMeta,
  DataTableSortEvent,
} from "primereact/datatable";
import { Column } from "primereact/column";
import { FilterMatchMode, FilterOperator } from "primereact/api";
import { VirtualScrollerLazyEvent } from "primereact/virtualscroller";
import "primereact/resources/themes/lara-dark-indigo/theme.css";
import "primereact/resources/primereact.min.css";
import "primeicons/primeicons.css";

type TapeLeg = {
  trade_id?: string;
  leg_order?: number;
  product_type?: string | null;
  trade_label?: string | null;
  strike?: number | null;
  notional?: number | null;
  notional_currency?: string | null;
  premium?: number | null;
  is_notional_capped?: boolean | number | string | null;
  is_manually_linked?: boolean | number | string | null;
  manual_link_id?: string | null;
  exercise_style?: string | null;
  package_type?: string | null;
  execution_timestamp?: string | null;
  execution_start?: string | null;
  execution_end?: string | null;
  execution_time?: string | null;
  event_timestamp?: string | null;
  leg_metrics?: Record<string, any>;
  event_action?: string | null;
};

type TapeRow = {
  package_id: string;
  package_type: string | null;
  package_source?: string | null;
  manual_link_id?: string | null;
  manual_package_id?: string | null;
  user_comment?: string | null;
  link_reason?: string | null;
  tags?: string[] | null;
  link_metrics?: Record<string, any> | null;
  link_created_by?: string | null;
  link_created_at?: string | null;
  detection_strat?: string | null;
  as_of_date: string | null;
  execution_start: string;
  execution_end: string;
  expiration_date: string | null;
  underlying_expiration_date: string | null;
  tenor_label: string | null;
  forward_label: string | null;
  legs_count: number;
  total_notional: number | null;
  total_premium: number | null;
  package_indicator: boolean | null;
  package_transaction_price: number | null;
  package_confidence: number | null;
  package_reason: string | null;
  is_notional_capped?: boolean | number | string | null;
  vega_curve_id?: string | null;
  vega_curve_type?: string | null;
  package_metrics: Record<string, any> | null;
  legs_json: TapeLeg[];
  platform_identifier?: string | null;
  event_action?: string | null;
};

type TapeResponse = {
  rows: TapeRow[];
  nextCursor: string | null;
  hasMore: boolean;
  latestExecutionStart: string | null;
};

type ManualLinkValidationStatus = "ok" | "warn" | "error";

type ManualLinkValidationItem = {
  key: string;
  label: string;
  status: ManualLinkValidationStatus;
  message: string;
};

type ManualLinkTrade = {
  trade_id: string;
  package_id: string;
  trade_label?: string | null;
  product_type?: string | null;
  notional?: number | null;
  execution_timestamp?: string | null;
  platform_identifier?: string | null;
};

type ManualLinkHistoryItem = {
  history_id: number;
  action: string;
  changed_by: string;
  changed_at: string;
  change_details?: Record<string, any> | null;
  previous_state?: Record<string, any> | null;
};

type ManualLinkDetail = {
  link_id: string;
  manual_package_id: string;
  package_type: string | null;
  linked_trade_ids: string[];
  created_by: string;
  created_at: string;
  updated_by?: string | null;
  updated_at?: string | null;
  user_comment?: string | null;
  link_reason?: string | null;
  tags?: string[] | null;
  link_metrics?: Record<string, any> | null;
  is_active: boolean;
};

type ManualLinkRow = {
  link_id: string;
  manual_package_id: string;
  linked_trade_ids?: string[] | string | null;
  is_active?: boolean | null;
  created_at?: string | null;
  package_type?: string | null;
};

type LegMetricValues = {
  bpvol: number | null;
  dv01: number | null;
  vega01: number | null;
  gamma01: number | null;
  theta01: number | null;
};

type ColumnFilterConstraint = {
  value: any;
  matchMode?: string;
};

type ColumnFilterPayload = Record<
  string,
  {
    operator?: string;
    constraints: ColumnFilterConstraint[];
  }
>;

type TimeseriesChartType = "line" | "bar";

type TimeseriesMetricKey =
  | "bpvolYr"
  | "bpvolDay"
  | "premiumBps"
  | "notional"
  | "premium"
  | "dv01"
  | "vega01"
  | "gamma01"
  | "theta01";

type TimeseriesMetricDefinition = {
  key: TimeseriesMetricKey;
  label: string;
  color: string;
  decimals: number;
  chartType: TimeseriesChartType;
  unit?: string;
};

type TimeseriesRangeKey =
  | "1D"
  | "1W"
  | "1M"
  | "3M"
  | "6M"
  | "1Y"
  | "CUSTOM"
  | "ALL";
type TimeseriesViewKey = "INTRADAY" | "DAILY_CLOSE" | "DAILY_OHLC";

type StraddleTimeseriesPoint = {
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

type DailyTimeseriesPoint = {
  timestamp: number;
  timeLabel: string;
  open: number;
  high: number;
  low: number;
  close: number;
  daySum: number;
  range: number;
};

type TimeseriesChartPoint = {
  timestamp: number;
  timeLabel: string;
  custyValue?: number | null;
  idbValue?: number | null;
};

type TimeseriesExtremePoint = {
  value: number;
  timeLabel: string;
  timestamp: number;
};

type TimeseriesSummaryStats = {
  tradeCount: number;
  totalNotional: number | null;
  avgNotional: number | null;
  medianNotional: number | null;
  totalPremium: number | null;
  avgPremium: number | null;
  medianPremium: number | null;
  avgVega01: number | null;
  medianVega01: number | null;
  tradesPerDay: number | null;
  avgGapMs: number | null;
  activeDays: number | null;
};

type SequenceDirection = "PAYER" | "RECEIVER" | "MIXED" | "UNKNOWN";

type SequenceRowMeta = {
  row: TapeRow;
  timestamp: number | null;
  direction: SequenceDirection;
  directionSymbol: string;
  notional: number | null;
  signedNotional: number | null;
  platform: string | null;
  isIdb: boolean;
  isCusty: boolean;
  bucketKey: string | null;
};

type SequenceSummary = {
  tradeCount: number;
  bucketKey: string | null;
  bucketBreakdown: Array<{ key: string; count: number }>;
  windowLabel: string;
  durationMs: number | null;
  avgGapMs: number | null;
  minGapMs: number | null;
  maxGapMs: number | null;
  gapTrend: "accelerating" | "decelerating" | "steady" | null;
  tradesPerHour: number | null;
  grossNotional: number | null;
  netNotional: number | null;
  netToGrossPct: number | null;
  netDirection: "PAYER" | "RECEIVER" | "FLAT" | "UNKNOWN";
  directionPattern: string;
  directionCompact: string;
  directionCounts: {
    payer: number;
    receiver: number;
    mixed: number;
    unknown: number;
  };
  clipSizes: number[];
  clipUniformityPct: number | null;
  clipUniformityLabel: string;
  clipMedian: number | null;
  platformBreakdown: Array<{
    platform: string;
    count: number;
    sharePct: number;
  }>;
  idbSharePct: number | null;
  custySharePct: number | null;
  bpvolStart: number | null;
  bpvolEnd: number | null;
  bpvolChange: number | null;
  sequenceRows: Array<{
    id: string;
    timeLabel: string;
    direction: SequenceDirection;
    directionSymbol: string;
    notional: number | null;
    platform: string | null;
    label: string;
  }>;
  runningNetSeries: Array<{
    index: number;
    timestamp: number | null;
    timeLabel: string;
    netValue: number | null;
    directionSymbol: string;
    notional: number | null;
  }>;
  imbalancePeak: number | null;
  imbalancePeakIndex: number | null;
  reversionTrades: number | null;
  reversionMs: number | null;
  firstOpposingGapMs: number | null;
  estimatedParticipants: number | null;
  participantClusters: number[];
  initiatorLabel: string;
  initiatorConfidence: "low" | "medium" | "high";
  hedgedPct: number | null;
  sizeProfile: string;
  narrative: string;
  warnings: string[];
};

type SequenceCluster = {
  id: string;
  bucketKey: string;
  rows: TapeRow[];
  startTimestamp: number;
  endTimestamp: number;
  durationMs: number;
};

const SAFE_ACTIONS = new Set(["NEWT", "TRAD", "MODI"]);
const ACTIVE_ACTIONS = new Set(["NEWT-TRAD", "MODI-TRAD", "CORR-TRAD"]);
const POLL_INTERVAL_MS = 5000;
const ROW_ESTIMATE_PX = 44;
const SEQUENCE_CLUSTER_MAX_GAP_MINUTES = 60;
const SEQUENCE_CLUSTER_MIN_TRADES = 3;
const CLIP_UNIFORMITY_TOLERANCE = 0.1;
const ONE_HOUR_MS = 60 * 60 * 1000;
const ONE_DAY_MS = 24 * ONE_HOUR_MS;
const ONE_YEAR_MS = 365 * ONE_DAY_MS;
const POST_CLUSTER_WINDOW_MS = 2 * ONE_HOUR_MS;
const HEDGE_LATENCY_NOTIONAL = 100_000_000;
const HEDGE_LATENCY_MAX_WINDOW_MS = 6 * ONE_HOUR_MS;
const EMPTY_VALUE = "\u2014";
const PACKAGE_TONES: Record<string, string> = {
  STRADDLE: "!bg-purple-900/30", // Purple (Distinct from others)
  RISK_REVERSAL: "!bg-amber-900/30", // Amber (Orange-yellow, distinct from Red)
  VERTICAL_SPREAD_1X1: "!bg-blue-900/30", // Blue
  VERTICAL_SPREAD_1X2: "!bg-cyan-900/30", // Cyan (High contrast with Blue and Emerald)
  RECEIVER_LADDER: "!bg-emerald-900/30", // Emerald (Distinct Green)
  CUSTY_RR_STRANGLE: "!bg-lime-900/30", // Lime (Bright Yellow-Green, replaces Pink)
  OUTRIGHT: "!bg-gray-800/50", // Gray (Neutral, distinct from saturated colors)
};
const NESTED_TABLE_BG = "bg-slate-900/50";

const ACTION_TONES: Record<string, string> = {
  NEWT: "",
  TRAD: "",
  MODI: "",
};

const COLUMN_DEFS = [
  { key: "event_action", label: "Action", width: 110 },
  { key: "package_type", label: "Package Type", width: 150 },
  { key: "time", label: "Time", width: 180 },
  { key: "platform", label: "Platform", width: 120 },
  { key: "notional", label: "Notional", width: 130 },
  { key: "label", label: "Trade Label", width: 700 },
];

const METRIC_SCHEMA = {
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

const STRADDLE_STYLE = "EURO VANILLA PHYS";
const STRADDLE_SPLIT_FACTOR = 0.5;
const BPVOL_DAY_DIVISOR = 15.87;
const IDB_MIC_CODES = ["BGCD", "ISWV", "TPSE"] as const;
const CUSTY_MIC_CODES = ["BILT", "XXXX", "TWSF", "BBSF", "XOFF"] as const;
const IDB_MIC_SET = new Set<string>(IDB_MIC_CODES);
const CUSTY_MIC_SET = new Set<string>(CUSTY_MIC_CODES);
const STRADDLE_GREEK_FIELDS = {
  dv01: "straddle_dv01",
  vega01: "straddle_vega01",
  gamma01: "straddle_gamma01",
  theta01: "straddle_theta1d",
} as const;
const CUSTY_SERIES_COLOR = "#f59e0b";
const IDB_SERIES_COLOR = "#38bdf8";
const TIMESERIES_METRICS: TimeseriesMetricDefinition[] = [
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
const DAILY_CLOSE_CUMULATIVE_METRICS = new Set<TimeseriesMetricKey>([
  "notional",
  "dv01",
  "vega01",
  "gamma01",
  "theta01",
]);
const TIMESERIES_RANGE_OPTIONS: Array<{
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
const TIMESERIES_VIEW_OPTIONS: Array<{
  key: TimeseriesViewKey;
  label: string;
}> = [
  { key: "INTRADAY", label: "Intraday" },
  { key: "DAILY_CLOSE", label: "Daily Close" },
  { key: "DAILY_OHLC", label: "Daily OHLC" },
];
const TIMESERIES_FETCH_LIMIT = 500;
const TIMESERIES_MAX_ROWS = 50000;
const TIMESERIES_MAX_PAGES = 10000;
const TIMESERIES_MAX_SCAN_MS = 60000 * 2;
const MANUAL_PACKAGE_TYPES = [
  { value: "USER_STRADDLE_PAIR", label: "Straddle Pair" },
  { value: "USER_VERTICAL_SPREAD", label: "Vertical Spread" },
  { value: "USER_TIME_SPREAD", label: "Time Spread" },
  { value: "USER_CUSTOM", label: "Custom" },
];
const MANUAL_LINK_REASONS = [
  { value: "Vega hedge", label: "Vega hedge" },
  { value: "Customer flow", label: "Customer flow" },
  { value: "Time spread", label: "Time spread" },
  { value: "Structure repair", label: "Structure repair" },
  { value: "Other", label: "Other" },
];
const TENOR_REGEX =
  /(\d+(?:\.\d+)?\s*(?:M|MO|MON|MONTH|MONTHS|Y|YR|YEAR|YEARS))\s*x\s*(\d+(?:\.\d+)?\s*(?:M|MO|MON|MONTH|MONTHS|Y|YR|YEAR|YEARS))/i;
const TENOR_TOKEN_REGEX =
  /^(\d+(?:\.\d+)?)(?:\s*)(M|MO|MON|MONTH|MONTHS|Y|YR|YEAR|YEARS)$/i;

/**
 * Smart rounding that handles machine epsilon errors and removes trailing zeros
 * Examples:
 * - 249.999 -> "250"
 * - 1.50000 -> "1.5"
 * - 1.00000 -> "1"
 * - 1.2345 with decimals=2 -> "1.23"
 */
function smartRound(value: number, decimals: number): string {
  // Round to one extra decimal to catch epsilon errors, then round to desired precision
  const epsilon = 1 / Math.pow(10, decimals + 1);
  const rounded = Math.round((value + epsilon) * Math.pow(10, decimals)) / Math.pow(10, decimals);

  // Format with fixed decimals then remove trailing zeros
  return rounded
    .toFixed(decimals)
    .replace(/\.?0+$/, "");
}

function formatTenorNumber(value: number): string {
  if (Number.isInteger(value)) return String(value);
  return value
    .toFixed(6)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}

function normalizeTenorToken(value: string | null | undefined): string | null {
  if (!value) return null;
  const normalized = String(value).trim().toUpperCase();
  if (!normalized) return null;
  const match = normalized.match(TENOR_TOKEN_REGEX);
  if (!match) return null;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount) || amount <= 0) return null;
  const unit = match[2].toUpperCase();
  const formattedAmount = formatTenorNumber(amount);

  if (unit.startsWith("M")) {
    if (Number.isInteger(amount) && amount % 12 === 0) {
      return `${formatTenorNumber(amount / 12)}Y`;
    }
    return `${formattedAmount}M`;
  }

  if (unit.startsWith("Y")) {
    if (Number.isInteger(amount)) return `${formattedAmount}Y`;
    const months = amount * 12;
    if (Number.isInteger(months)) {
      return `${formatTenorNumber(months)}M`;
    }
    return `${formattedAmount}Y`;
  }

  return null;
}

const STRIKE_MATCH_EPS = 1e-4;
const STRIKE_DISPLAY_DECIMALS = 3;
const DEFAULT_TEXT_MATCH_MODE = FilterMatchMode.CONTAINS;
const DEFAULT_NUMERIC_MATCH_MODE = FilterMatchMode.EQUALS;
const TIME_FILTER_MATCH_MODE_OPTIONS = [
  { label: "Contains", value: FilterMatchMode.CONTAINS },
  { label: "Equals", value: FilterMatchMode.EQUALS },
  { label: "Not equals", value: FilterMatchMode.NOT_EQUALS },
  { label: "Greater than", value: FilterMatchMode.GREATER_THAN },
  {
    label: "Greater than or equal",
    value: FilterMatchMode.GREATER_THAN_OR_EQUAL_TO,
  },
  { label: "Less than", value: FilterMatchMode.LESS_THAN },
  {
    label: "Less than or equal",
    value: FilterMatchMode.LESS_THAN_OR_EQUAL_TO,
  },
];
const FILTER_FIELDS = [
  "action",
  "package_type",
  "time",
  "platform",
  "notional",
  "label",
] as const;
const COLUMN_FILTER_QUERY_KEY = "columnFilters";
const COLUMN_FILTER_OPERATOR_QUERY_KEY = "columnFilterOp";
const SELECTED_PACKAGES_QUERY_KEY = "selectedPackages";
const SELECTED_ONLY_QUERY_KEY = "selectedOnly";
const NUMERIC_FILTER_FIELDS = new Set(["notional"]);

const INITIAL_FILTERS: DataTableFilterMeta = {
  action: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  },
  package_type: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  },
  time: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  },
  platform: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  },
  notional: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_NUMERIC_MATCH_MODE }],
  },
  label: {
    operator: FilterOperator.AND,
    constraints: [{ value: null, matchMode: DEFAULT_TEXT_MATCH_MODE }],
  },
};

function normalizePackageType(type: string | null): string {
  if (!type) return "";
  return type.replace(/-/g, "_").toUpperCase();
}

function packageTone(type: string | null): string {
  if (!type) return "!bg-gray-900/30";
  const normalized = normalizePackageType(type);
  return PACKAGE_TONES[normalized] || "!bg-gray-900/30";
}

function legAction(leg: TapeLeg): string | null {
  return (leg.event_action ||
    leg.leg_metrics?.event_action ||
    leg.leg_metrics?.action ||
    null) as string | null;
}

function extractPrimaryAction(row: TapeRow): string | null {
  if (row.event_action) return row.event_action.toUpperCase();
  const legs = row.legs_json || [];
  if (!legs.length) return null;
  const action = legAction(legs[0]);
  return action ? action.toUpperCase() : null;
}

function hasActionWarning(row: TapeRow): boolean {
  return (row.legs_json || []).some((leg) => {
    const action = legAction(leg);
    return action && !SAFE_ACTIONS.has(action.toUpperCase());
  });
}

function resolvePlatformIdentifier(row: TapeRow): string | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLeg = legs[0] as any;
  const metrics = firstLeg?.leg_metrics || {};
  const platform =
    metrics.platform_identifier ||
    metrics.platform ||
    firstLeg?.platform_identifier ||
    row.platform_identifier ||
    row.package_metrics?.platform_identifier;
  return platform ? String(platform) : null;
}

function normalizePlatformTokens(
  platform: string | null | undefined,
): string[] {
  if (!platform) return [];
  return platform
    .trim()
    .toUpperCase()
    .split(/[\s,;/]+/)
    .filter(Boolean);
}

function isIdbPlatform(platform: string | null | undefined): boolean {
  const tokens = normalizePlatformTokens(platform);
  return tokens.some((token) => IDB_MIC_SET.has(token));
}

function isCustyPlatform(platform: string | null | undefined): boolean {
  const tokens = normalizePlatformTokens(platform);
  if (!tokens.length) return true;
  if (tokens.some((token) => CUSTY_MIC_SET.has(token))) return true;
  return !tokens.some((token) => IDB_MIC_SET.has(token));
}

function formatExecutionWindow(start: string, end: string): string {
  if (!start) return "--";
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : startDate;
  const startStr = `${startDate.toLocaleDateString("en-US")} ${startDate.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  const endStr = `${endDate.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  if (startDate.getTime() === endDate.getTime()) return startStr;
  return `${startStr} / ${endStr}`;
}

const MONTH_NAMES_SHORT = [
  "jan",
  "feb",
  "mar",
  "apr",
  "may",
  "jun",
  "jul",
  "aug",
  "sep",
  "oct",
  "nov",
  "dec",
] as const;

const MONTH_NAMES_LONG = [
  "january",
  "february",
  "march",
  "april",
  "may",
  "june",
  "july",
  "august",
  "september",
  "october",
  "november",
  "december",
] as const;

const DAY_NAMES_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

function buildDateSearchTokens(date: Date, useUtc = false): string[] {
  if (Number.isNaN(date.getTime())) return [];
  const year = useUtc ? date.getUTCFullYear() : date.getFullYear();
  const month = (useUtc ? date.getUTCMonth() : date.getMonth()) + 1;
  const day = useUtc ? date.getUTCDate() : date.getDate();
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  const monthShort = MONTH_NAMES_SHORT[month - 1];
  const monthLong = MONTH_NAMES_LONG[month - 1];

  return [
    `${month}/${day}`,
    `${mm}/${dd}`,
    `${month}-${day}`,
    `${mm}-${dd}`,
    `${month}.${day}`,
    `${mm}.${dd}`,
    `${month}/${day}/${year}`,
    `${mm}/${dd}/${year}`,
    `${year}-${mm}-${dd}`,
    `${monthShort} ${day}`,
    `${monthLong} ${day}`,
    `${day} ${monthShort}`,
    `${day} ${monthLong}`,
    `${monthShort} ${day} ${year}`,
    `${monthLong} ${day} ${year}`,
  ];
}

function buildExecutionTimeFilterValue(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const tokenSet = new Set<string>();
  const appendToken = (value: string | null | undefined) => {
    if (!value) return;
    const normalized = value.trim().toLowerCase();
    if (normalized) tokenSet.add(normalized);
  };

  appendToken(formatExecutionWindow(start || "", end || ""));

  [start, end].forEach((rawValue) => {
    if (!rawValue) return;
    appendToken(rawValue);
    const date = new Date(rawValue);
    buildDateSearchTokens(date, false).forEach((token) => appendToken(token));
    buildDateSearchTokens(date, true).forEach((token) => appendToken(token));
  });

  return Array.from(tokenSet).join(" ");
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const dateStr = date.toLocaleDateString("en-US");
  const timeStr = date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${dateStr} ${timeStr}`;
}

function isValid(value: any) {
  if (value === null || value === undefined) return false;
  if (typeof value === "number" && Number.isNaN(value)) return false;
  if (typeof value === "string" && value.trim() === "") return false;
  return true;
}

/**
 * Format large numbers with improved precision (4-5 significant figures)
 * Examples:
 * - 1,012,500 -> "1.0125m"
 * - 1,000,000 -> "1m"
 * - 1,234,567 -> "1.2346m"
 * - 999,500 -> "999.5k"
 * - 1,234,567,890 -> "1.2346b"
 */
function formatLargeNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";

  const absValue = Math.abs(value);
  const sign = value < 0 ? "-" : "";

  // Billion range
  if (absValue >= 1_000_000_000) {
    const billions = absValue / 1_000_000_000;
    if (billions >= 100) return `${sign}${smartRound(billions, 2)}b`;
    if (billions >= 10) return `${sign}${smartRound(billions, 3)}b`;
    return `${sign}${smartRound(billions, 4)}b`;
  }

  // Million range
  if (absValue >= 1_000_000) {
    const millions = absValue / 1_000_000;
    if (millions >= 100) return `${sign}${smartRound(millions, 2)}m`;
    if (millions >= 10) return `${sign}${smartRound(millions, 3)}m`;
    return `${sign}${smartRound(millions, 4)}m`;
  }

  // Thousand range
  if (absValue >= 1_000) {
    const thousands = absValue / 1_000;
    if (thousands >= 100) return `${sign}${smartRound(thousands, 2)}k`;
    if (thousands >= 10) return `${sign}${smartRound(thousands, 3)}k`;
    return `${sign}${smartRound(thousands, 4)}k`;
  }

  // Below 1000, return as-is with appropriate decimal places
  return `${sign}${smartRound(absValue, 2)}`;
}

function formatNotional(notional: number | null | undefined) {
  if (!isValid(notional)) return "--";
  const value = Number(notional);
  const mm = value / 1_000_000;

  // Billion range (1000mm+)
  if (mm >= 1000) {
    const bn = mm / 1000;
    if (bn >= 100) return `${smartRound(bn, 2)}bn`;
    if (bn >= 10) return `${smartRound(bn, 3)}bn`;
    return `${smartRound(bn, 4)}bn`;
  }

  // Million range - use 4-5 significant figures
  if (mm >= 100) return `${smartRound(mm, 2)}mm`;
  if (mm >= 10) return `${smartRound(mm, 3)}mm`;
  if (mm >= 1) return `${smartRound(mm, 4)}mm`;

  // Below 1mm, show in thousands
  const k = value / 1_000;
  if (k >= 100) return `${smartRound(k, 2)}k`;
  if (k >= 10) return `${smartRound(k, 3)}k`;
  if (k >= 1) return `${smartRound(k, 4)}k`;

  // Below 1k, show raw value
  return smartRound(value, 2);
}

function computeDisplayNotional(row: TapeRow): number | null {
  const packageType = normalizePackageType(row.package_type);
  const isStraddle = packageType === "STRADDLE";
  const isRiskReversal = packageType === "RISK_REVERSAL";
  const legs = row.legs_json || [];
  let displayNotional = row.total_notional;
  if (isStraddle) {
    displayNotional = legs[0]?.notional ?? row.total_notional;
  } else if (isRiskReversal && legs.length) {
    const strikeValues = legs
      .map((leg) => (isValid(leg.strike) ? Number(leg.strike) : null))
      .filter((strike): strike is number => strike !== null);
    const maxStrike = strikeValues.length ? Math.max(...strikeValues) : null;
    const minStrike = strikeValues.length ? Math.min(...strikeValues) : null;
    const wingLeg =
      (maxStrike !== null
        ? legs.find((leg) => strikeMatches(leg.strike ?? null, maxStrike))
        : null) ??
      (minStrike !== null
        ? legs.find((leg) => strikeMatches(leg.strike ?? null, minStrike))
        : null);
    displayNotional = wingLeg?.notional ?? row.total_notional;
  }
  return displayNotional ?? null;
}

function formatStrikeAbsolute(strike?: number | null) {
  const strikeValue = parseMetricNumber(strike);
  if (strikeValue === null) return "--";
  const strikePct = strikeValue * 100;
  const factor = 10 ** STRIKE_DISPLAY_DECIMALS;
  const rounded = Math.round((strikePct + Number.EPSILON) * factor) / factor;
  return rounded.toFixed(STRIKE_DISPLAY_DECIMALS);
}

function formatStrikeOffset(offset?: number | null, signAlways = true) {
  if (!isValid(offset)) return "ATMF";
  const rounded = Math.round(Number(offset));
  if (rounded === 0) return "ATMF";
  if (rounded > 0) return signAlways ? `ATMF+${rounded}bp` : `ATMF+${rounded}`;
  return signAlways ? `ATMF${rounded}bp` : `ATMF${rounded}`;
}

function formatMetricValue(value: number | null | undefined, decimals = 3) {
  if (!isValid(value)) return "--";
  const numericValue = Number(value);
  if (Math.abs(numericValue) >= 1000) {
    return formatLargeNumber(numericValue);
  }
  return smartRound(numericValue, decimals);
}

function formatMetricDisplay(value: number | null | undefined, decimals = 3) {
  if (!isValid(value)) return EMPTY_VALUE;
  return formatMetricValue(value, decimals);
}

function formatRate(value: number | null | undefined, decimals = 2) {
  if (!isValid(value)) return "--";
  return smartRound(Number(value), decimals);
}

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "--";
  return Math.round(numeric).toLocaleString("en-US");
}

function parseMetricNumber(value: any): number | null {
  if (!isValid(value)) return null;
  const numericValue = Number(value);
  return Number.isNaN(numericValue) ? null : numericValue;
}

function parseMetricSeries(value: any): number | null {
  if (!isValid(value)) return null;
  if (Array.isArray(value)) {
    const numbers = value
      .map((entry) => parseMetricNumber(entry))
      .filter((entry): entry is number => entry !== null);
    if (!numbers.length) return null;
    return numbers.reduce((sum, entry) => sum + entry, 0);
  }
  if (typeof value === "string") {
    const normalized = value.trim();
    if (!normalized) return null;
    if (/[\\/|,]/.test(normalized)) {
      const parts = normalized
        .split(/[\\/|,]+/)
        .map((entry) => entry.trim())
        .filter(Boolean);
      const numbers = parts
        .map((entry) => parseMetricNumber(entry))
        .filter((entry): entry is number => entry !== null);
      if (numbers.length) {
        return numbers.reduce((sum, entry) => sum + entry, 0);
      }
    }
  }
  return parseMetricNumber(value);
}

function normalizeManualFlag(value: any): boolean {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === "number") return value !== 0;
  const normalized = String(value).trim().toLowerCase();
  return ["true", "1", "yes", "y", "t"].includes(normalized);
}

function normalizeNotionalCapped(value: any): boolean {
  if (!isValid(value)) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const normalized = String(value).trim().toLowerCase();
  if (["true", "1", "yes", "y", "t"].includes(normalized)) return true;
  if (["false", "0", "no", "n", "f"].includes(normalized)) return false;
  return normalized.length > 0;
}

function isRowNotionalCapped(row: TapeRow): boolean {
  const metrics = row.package_metrics || {};
  const rowValue =
    row.is_notional_capped ??
    (metrics as any).is_notional_capped ??
    (metrics as any).straddle_is_notional_capped;
  if (normalizeNotionalCapped(rowValue)) return true;
  const legs = row.legs_json || [];
  return legs.some((leg) =>
    normalizeNotionalCapped(
      leg.leg_metrics?.is_notional_capped ?? leg.is_notional_capped,
    ),
  );
}

function isManualPackage(row: TapeRow): boolean {
  if (row.manual_link_id) return true;
  if (row.manual_package_id) return true;
  const source = row.package_source?.toUpperCase();
  return source === "MANUAL" || source === "HYBRID";
}

function manualLinkColor(linkId?: string | null): string | null {
  if (!linkId) return null;
  let hash = 0;
  for (let i = 0; i < linkId.length; i += 1) {
    hash = (hash * 31 + linkId.charCodeAt(i)) % 360;
  }
  return `hsl(${hash}, 65%, 52%)`;
}

function groupLinkedRows(rows: TapeRow[]): TapeRow[] {
  const groups = new Map<string, TapeRow[]>();
  rows.forEach((row) => {
    const linkId = row.manual_package_id || row.manual_link_id;
    if (!linkId) return;
    if (!groups.has(linkId)) {
      groups.set(linkId, []);
    }
    groups.get(linkId)?.push(row);
  });

  if (!groups.size) return rows;

  const emitted = new Set<string>();
  const result: TapeRow[] = [];

  rows.forEach((row) => {
    const linkId = row.manual_package_id || row.manual_link_id;
    if (!linkId) {
      result.push(row);
      return;
    }
    if (emitted.has(linkId)) return;
    emitted.add(linkId);
    const groupRows = groups.get(linkId);
    if (groupRows) {
      result.push(...groupRows);
    }
  });

  return result;
}

function formatDurationSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "--";
  const absSeconds = Math.abs(numeric);
  if (absSeconds < 60) return `${Math.round(absSeconds)}s`;
  const minutes = Math.round(absSeconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

function formatDurationMs(value: number | null | undefined): string {
  if (!isValid(value)) return "--";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "--";
  const absMs = Math.abs(numeric);
  if (absMs < 1000) return `${Math.round(absMs)}ms`;
  const seconds = absMs / 1000;
  if (seconds < 60) return `${smartRound(seconds, 1)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${smartRound(minutes, 1)}m`;
  const hours = minutes / 60;
  if (hours < 48) return `${smartRound(hours, 1)}h`;
  const days = hours / 24;
  if (days < 365) return `${smartRound(days, 1)}d`;
  const years = days / 365;
  return `${smartRound(years, 1)}y`;
}

function formatDateShort(timestamp: number | null | undefined): string {
  if (!isValid(timestamp)) return "--";
  const date = new Date(Number(timestamp));
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  });
}

function formatDayOfWeek(index: number | null | undefined): string {
  if (index === null || index === undefined) return "--";
  return DAY_NAMES_SHORT[index] ?? "--";
}

function formatSignedNotional(value: number | null | undefined): string {
  if (!isValid(value)) return "--";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "--";
  const sign = numeric < 0 ? "-" : "+";
  return `${sign}${formatNotional(Math.abs(numeric))}`;
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const ts = new Date(value).getTime();
  if (Number.isNaN(ts)) return null;
  return ts;
}

function clusterValuesByTolerance(
  values: number[],
  tolerancePct: number,
): number[][] {
  if (!values.length) return [];
  const sorted = [...values].sort((a, b) => a - b);
  const clusters: number[][] = [];
  sorted.forEach((value) => {
    let placed = false;
    for (const cluster of clusters) {
      const anchor = cluster[0];
      if (anchor === 0) continue;
      if (Math.abs(value - anchor) / anchor <= tolerancePct) {
        cluster.push(value);
        placed = true;
        break;
      }
    }
    if (!placed) {
      clusters.push([value]);
    }
  });
  return clusters;
}

function classifySizeProfile(
  values: number[],
  uniformityPct: number | null,
): string {
  if (!values.length) return "unknown";
  if (uniformityPct !== null && uniformityPct >= 80) return "uniform clips";
  const sorted = [...values].sort((a, b) => a - b);
  const clusters = clusterValuesByTolerance(values, CLIP_UNIFORMITY_TOLERANCE);
  const largestCluster = clusters.reduce(
    (max, cluster) => Math.max(max, cluster.length),
    0,
  );
  if (largestCluster >= values.length - 1) {
    return "one odd lot";
  }
  const isAscending = values.every(
    (value, index) => index === 0 || value >= values[index - 1],
  );
  const isDescending = values.every(
    (value, index) => index === 0 || value <= values[index - 1],
  );
  if (isAscending && values[values.length - 1] >= values[0] * 1.5) {
    return "escalating clips";
  }
  if (isDescending && values[0] >= values[values.length - 1] * 1.5) {
    return "descending clips";
  }
  if (sorted[sorted.length - 1] >= sorted[0] * 3) {
    return "wide dispersion";
  }
  return "varied clips";
}

function percentileRank(value: number, values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  let count = 0;
  for (const entry of sorted) {
    if (entry <= value) count += 1;
  }
  return (count / sorted.length) * 100;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2;
  }
  return sorted[mid];
}

function extractLegDirection(leg: TapeLeg): "PAYER" | "RECEIVER" | null {
  const raw = `${leg.product_type ?? ""} ${leg.trade_label ?? ""}`.toUpperCase();
  if (raw.includes("PAYER")) return "PAYER";
  if (raw.includes("RECEIVER")) return "RECEIVER";
  return null;
}

function resolveRowDirection(row: TapeRow): SequenceDirection {
  const packageType = normalizePackageType(row.package_type);
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const legDirections = legs
    .map((leg) => extractLegDirection(leg))
    .filter((direction): direction is "PAYER" | "RECEIVER" => direction !== null);
  const hasPayer = legDirections.includes("PAYER");
  const hasReceiver = legDirections.includes("RECEIVER");
  if (hasPayer && hasReceiver) return "MIXED";
  if (hasPayer) return "PAYER";
  if (hasReceiver) return "RECEIVER";

  if (packageType.includes("PAYER") && !packageType.includes("RECEIVER")) {
    return "PAYER";
  }
  if (packageType.includes("RECEIVER") && !packageType.includes("PAYER")) {
    return "RECEIVER";
  }
  if (
    packageType === "STRADDLE" ||
    packageType === "RISK_REVERSAL" ||
    packageType === "CUSTY_RR_STRANGLE" ||
    packageType.startsWith("VERTICAL_SPREAD")
  ) {
    return "MIXED";
  }
  return "UNKNOWN";
}

function directionToSymbol(direction: SequenceDirection): string {
  if (direction === "PAYER") return "P";
  if (direction === "RECEIVER") return "R";
  if (direction === "MIXED") return "M";
  return "?";
}

function buildSequenceSummary(rows: TapeRow[]): SequenceSummary {
  const tradeCount = rows.length;
  const rowMeta: SequenceRowMeta[] = rows.map((row) => {
    const timestamp = parseTimestamp(row.execution_start);
    const direction = resolveRowDirection(row);
    const directionSymbol = directionToSymbol(direction);
    const notional = computeDisplayNotional(row);
    const signedNotional =
      notional !== null && direction === "PAYER"
        ? notional
        : notional !== null && direction === "RECEIVER"
          ? -notional
          : null;
    const platform = resolvePlatformIdentifier(row);
    const isIdb = isIdbPlatform(platform);
    const isCusty = isCustyPlatform(platform);
    const bucketKey = resolveTenorKey(row);
    return {
      row,
      timestamp,
      direction,
      directionSymbol,
      notional,
      signedNotional,
      platform,
      isIdb,
      isCusty,
      bucketKey,
    };
  });

  const sortedMeta = [...rowMeta].sort((left, right) => {
    if (left.timestamp === null && right.timestamp === null) return 0;
    if (left.timestamp === null) return 1;
    if (right.timestamp === null) return -1;
    return left.timestamp - right.timestamp;
  });

  const bucketCounts = new Map<string, number>();
  sortedMeta.forEach((meta) => {
    const key = meta.bucketKey || "UNKNOWN";
    bucketCounts.set(key, (bucketCounts.get(key) || 0) + 1);
  });
  const bucketBreakdown = Array.from(bucketCounts.entries())
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => b.count - a.count);
  const bucketKey = bucketBreakdown[0]?.key || null;

  const timestamps = sortedMeta
    .map((meta) => meta.timestamp)
    .filter((value): value is number => value !== null);
  const startTimestamp = timestamps.length ? timestamps[0] : null;
  const endTimestamp = timestamps.length
    ? timestamps[timestamps.length - 1]
    : null;
  const durationMs =
    startTimestamp !== null && endTimestamp !== null
      ? Math.max(0, endTimestamp - startTimestamp)
      : null;
  const windowLabel =
    startTimestamp !== null && endTimestamp !== null
      ? formatExecutionWindow(
          sortedMeta.find((meta) => meta.timestamp !== null)?.row
            .execution_start ?? "",
          sortedMeta
            .slice()
            .reverse()
            .find((meta) => meta.timestamp !== null)?.row.execution_start ?? "",
        )
      : "--";

  const gaps: number[] = [];
  for (let i = 1; i < timestamps.length; i += 1) {
    gaps.push(timestamps[i] - timestamps[i - 1]);
  }
  const avgGapMs =
    gaps.length > 0 ? gaps.reduce((a, b) => a + b, 0) / gaps.length : null;
  const minGapMs = gaps.length ? Math.min(...gaps) : null;
  const maxGapMs = gaps.length ? Math.max(...gaps) : null;
  let gapTrend: "accelerating" | "decelerating" | "steady" | null = null;
  if (gaps.length >= 2) {
    const first = gaps[0];
    const last = gaps[gaps.length - 1];
    if (last < first * 0.7) {
      gapTrend = "accelerating";
    } else if (last > first * 1.3) {
      gapTrend = "decelerating";
    } else {
      gapTrend = "steady";
    }
  }

  const tradesPerHour =
    durationMs !== null && durationMs > 0
      ? (tradeCount / durationMs) * 3_600_000
      : null;

  const clipSizes = sortedMeta
    .map((meta) => meta.notional)
    .filter((value): value is number => isValid(value))
    .map((value) => Math.abs(value));

  const grossNotional =
    clipSizes.length > 0
      ? clipSizes.reduce((sum, value) => sum + value, 0)
      : null;

  let netNotionalSum = 0;
  let signedCount = 0;
  sortedMeta.forEach((meta) => {
    if (meta.signedNotional === null) return;
    netNotionalSum += meta.signedNotional;
    signedCount += 1;
  });
  const netNotional = signedCount > 0 ? netNotionalSum : null;

  const netDirection =
    grossNotional === null || netNotional === null
      ? "UNKNOWN"
      : netNotional > 0
        ? "PAYER"
        : netNotional < 0
          ? "RECEIVER"
          : "FLAT";

  const netToGrossPct =
    grossNotional && grossNotional !== 0 && netNotional !== null
      ? (Math.abs(netNotional) / grossNotional) * 100
      : null;

  const directionCounts = sortedMeta.reduce(
    (counts, meta) => {
      if (meta.direction === "PAYER") counts.payer += 1;
      else if (meta.direction === "RECEIVER") counts.receiver += 1;
      else if (meta.direction === "MIXED") counts.mixed += 1;
      else counts.unknown += 1;
      return counts;
    },
    { payer: 0, receiver: 0, mixed: 0, unknown: 0 },
  );

  const directionSymbols = sortedMeta.map((meta) => meta.directionSymbol);
  const directionPattern = directionSymbols.join(" \u2192 ");
  const directionCompact = directionSymbols
    .map((symbol) => {
      if (symbol === "P") return "+";
      if (symbol === "R") return "-";
      return "?";
    })
    .join("");

  const clipMedian = (() => {
    if (!clipSizes.length) return null;
    const sorted = [...clipSizes].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    if (sorted.length % 2 === 0) {
      return (sorted[mid - 1] + sorted[mid]) / 2;
    }
    return sorted[mid];
  })();
  const clipUniformityPct =
    clipMedian !== null && clipMedian > 0
      ? (clipSizes.filter(
          (value) =>
            Math.abs(value - clipMedian) <= clipMedian * CLIP_UNIFORMITY_TOLERANCE,
        ).length /
          clipSizes.length) *
        100
      : null;
  const clipUniformityLabel =
    clipUniformityPct === null
      ? "N/A"
      : clipUniformityPct >= 80
        ? "Uniform"
        : clipUniformityPct >= 55
          ? "Mostly uniform"
          : "Varied";
  const sizeProfile = classifySizeProfile(clipSizes, clipUniformityPct);

  const participantClusters = clipSizes.length
    ? clusterValuesByTolerance(clipSizes, CLIP_UNIFORMITY_TOLERANCE).map(
        (cluster) =>
          cluster.reduce((sum, value) => sum + value, 0) / cluster.length,
      )
    : [];
  const estimatedParticipants = participantClusters.length || null;

  const platformCounts = new Map<string, number>();
  let idbCount = 0;
  let custyCount = 0;
  sortedMeta.forEach((meta) => {
    const key = meta.platform || "UNKNOWN";
    platformCounts.set(key, (platformCounts.get(key) || 0) + 1);
    if (meta.isIdb) idbCount += 1;
    if (meta.isCusty) custyCount += 1;
  });
  const platformBreakdown = Array.from(platformCounts.entries())
    .map(([platform, count]) => ({
      platform,
      count,
      sharePct: tradeCount ? (count / tradeCount) * 100 : 0,
    }))
    .sort((a, b) => b.count - a.count);
  const idbSharePct = tradeCount ? (idbCount / tradeCount) * 100 : null;
  const custySharePct = tradeCount ? (custyCount / tradeCount) * 100 : null;

  const bpvolValues = sortedMeta
    .map((meta) => {
      const pkgType = normalizePackageType(meta.row.package_type);
      return resolvePackageBpvolYr(meta.row, pkgType);
    })
    .filter((value): value is number => isValid(value));
  const bpvolStart = bpvolValues.length ? bpvolValues[0] : null;
  const bpvolEnd = bpvolValues.length
    ? bpvolValues[bpvolValues.length - 1]
    : null;
  const bpvolChange =
    bpvolStart !== null && bpvolEnd !== null ? bpvolEnd - bpvolStart : null;

  const sequenceRows = sortedMeta.map((meta) => ({
    id: meta.row.package_id,
    timeLabel:
      meta.timestamp !== null
        ? new Date(meta.timestamp).toLocaleTimeString("en-US", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        : "--",
    direction: meta.direction,
    directionSymbol: meta.directionSymbol,
    notional: meta.notional,
    platform: meta.platform,
    label: buildRichLabel(meta.row),
  }));

  let runningNet = 0;
  const runningNetSeries = sortedMeta.map((meta, index) => {
    if (meta.signedNotional !== null) {
      runningNet += meta.signedNotional;
    }
    return {
      index,
      timestamp: meta.timestamp,
      timeLabel:
        meta.timestamp !== null
          ? new Date(meta.timestamp).toLocaleTimeString("en-US", {
              hour12: false,
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })
          : "--",
      netValue: meta.signedNotional !== null ? runningNet : null,
      directionSymbol: meta.directionSymbol,
      notional: meta.notional,
    };
  });
  let imbalancePeak: number | null = null;
  let imbalancePeakIndex: number | null = null;
  runningNetSeries.forEach((point, index) => {
    if (point.netValue === null) return;
    if (imbalancePeak === null || Math.abs(point.netValue) > Math.abs(imbalancePeak)) {
      imbalancePeak = point.netValue;
      imbalancePeakIndex = index;
    }
  });
  let reversionTrades: number | null = null;
  let reversionMs: number | null = null;
  if (imbalancePeakIndex !== null && imbalancePeak !== null) {
    const target = Math.abs(imbalancePeak) * 0.33;
    for (let i = imbalancePeakIndex + 1; i < runningNetSeries.length; i += 1) {
      const point = runningNetSeries[i];
      if (point.netValue === null) continue;
      if (Math.abs(point.netValue) <= target) {
        reversionTrades = i - imbalancePeakIndex;
        const startTs = runningNetSeries[imbalancePeakIndex].timestamp;
        if (startTs !== null && point.timestamp !== null) {
          reversionMs = point.timestamp - startTs;
        }
        break;
      }
    }
  }

  let firstOpposingGapMs: number | null = null;
  const firstDirectional = sortedMeta.find(
    (meta) => meta.direction === "PAYER" || meta.direction === "RECEIVER",
  );
  if (firstDirectional && firstDirectional.timestamp !== null) {
    const targetDirection =
      firstDirectional.direction === "PAYER" ? "RECEIVER" : "PAYER";
    const opposing = sortedMeta.find(
      (meta) =>
        meta.timestamp !== null && meta.direction === targetDirection,
    );
    if (opposing && opposing.timestamp !== null) {
      firstOpposingGapMs = opposing.timestamp - firstDirectional.timestamp;
    }
  }

  const hedgedPct =
    netToGrossPct !== null ? Math.max(0, 100 - netToGrossPct) : null;

  const firstMeta = sortedMeta[0];
  let initiatorLabel = "Initiator unclear";
  let initiatorConfidence: "low" | "medium" | "high" = "low";
  if (firstMeta) {
    const rest = sortedMeta.slice(1);
    const restIdbShare =
      rest.length > 0
        ? rest.filter((meta) => meta.isIdb).length / rest.length
        : 0;
    if (firstMeta.isCusty) {
      initiatorLabel = "Custy initiator";
      initiatorConfidence = restIdbShare >= 0.5 ? "high" : "medium";
    } else if (firstMeta.isIdb) {
      initiatorLabel = "Likely dealer initiator";
      initiatorConfidence = restIdbShare >= 0.7 ? "low" : "medium";
    } else {
      initiatorLabel = "Initiator unclear";
      initiatorConfidence = "low";
    }
  }

  const warnings: string[] = [];
  if (bucketBreakdown.length > 1) {
    warnings.push("Multiple buckets selected; summary aggregates across them.");
  }
  if (directionCounts.unknown + directionCounts.mixed > 0) {
    warnings.push("Some trades have mixed/unknown direction; net may be understated.");
  }

  const narrativeParts: string[] = [];
  const hasBothDirections =
    directionCounts.payer > 0 && directionCounts.receiver > 0;
  if (hasBothDirections) {
    if (netToGrossPct !== null && netToGrossPct <= 20) {
      narrativeParts.push(
        "Mixed direction with low net/gross suggests offsetting hedges or risk recycling.",
      );
    } else if (netDirection === "UNKNOWN") {
      narrativeParts.push(
        "Mixed direction with unclear net due to missing notional data.",
      );
    } else {
      narrativeParts.push(
        `Mixed flow with a net ${netDirection.toLowerCase()} lean.`,
      );
    }
  } else if (directionCounts.payer > 0 || directionCounts.receiver > 0) {
    if (netDirection === "UNKNOWN") {
      narrativeParts.push(
        "One-way flow detected, but net direction is unclear without notionals.",
      );
    } else {
      narrativeParts.push(
        `One-way ${netDirection.toLowerCase()} flow suggests directional accumulation.`,
      );
    }
  } else {
    narrativeParts.push(
      "Directionality is unclear due to multi-leg structures in the selection.",
    );
  }
  if (idbSharePct !== null && idbSharePct >= 80) {
    narrativeParts.push("Activity is concentrated on IDB venues.");
  } else if (custySharePct !== null && custySharePct >= 80) {
    narrativeParts.push("Flow is custy-heavy across venues.");
  } else if (idbSharePct !== null && custySharePct !== null) {
    narrativeParts.push(
      "Mix of custy and IDB prints suggests intermediation in flight.",
    );
  }
  if (gapTrend === "accelerating") {
    narrativeParts.push("Inter-trade gaps are compressing, indicating urgency.");
  } else if (gapTrend === "decelerating") {
    narrativeParts.push("Gaps are widening, suggesting the sequence is fading.");
  }

  return {
    tradeCount,
    bucketKey,
    bucketBreakdown,
    windowLabel,
    durationMs,
    avgGapMs,
    minGapMs,
    maxGapMs,
    gapTrend,
    tradesPerHour,
    grossNotional,
    netNotional,
    netToGrossPct,
    netDirection,
    directionPattern,
    directionCompact,
    directionCounts,
    clipSizes,
    clipUniformityPct,
    clipUniformityLabel,
    clipMedian,
    platformBreakdown,
    idbSharePct,
    custySharePct,
    bpvolStart,
    bpvolEnd,
    bpvolChange,
    sequenceRows,
    runningNetSeries,
    imbalancePeak,
    imbalancePeakIndex,
    reversionTrades,
    reversionMs,
    firstOpposingGapMs,
    estimatedParticipants,
    participantClusters,
    initiatorLabel,
    initiatorConfidence,
    hedgedPct,
    sizeProfile,
    narrative: narrativeParts.join(" "),
    warnings,
  };
}

function detectSequenceClusters(
  rows: TapeRow[],
  maxGapMinutes: number,
  minTrades: number,
): SequenceCluster[] {
  const clusters: SequenceCluster[] = [];
  const grouped = new Map<string, TapeRow[]>();
  rows.forEach((row) => {
    const action = extractPrimaryAction(row);
    if (action && !ACTIVE_ACTIONS.has(action)) return;
    const bucketKey = resolveTenorKey(row);
    if (!bucketKey) return;
    const timestamp = parseTimestamp(row.execution_start);
    if (timestamp === null) return;
    const list = grouped.get(bucketKey);
    if (list) {
      list.push(row);
    } else {
      grouped.set(bucketKey, [row]);
    }
  });

  grouped.forEach((bucketRows, bucketKey) => {
    const sorted = bucketRows
      .map((row) => ({
        row,
        timestamp: parseTimestamp(row.execution_start) || 0,
      }))
      .sort((a, b) => a.timestamp - b.timestamp);
    let current: typeof sorted = [];
    sorted.forEach((entry, index) => {
      if (current.length === 0) {
        current = [entry];
        return;
      }
      const prev = current[current.length - 1];
      const gapMinutes = (entry.timestamp - prev.timestamp) / 60000;
      if (gapMinutes <= maxGapMinutes) {
        current.push(entry);
      } else {
        if (current.length >= minTrades) {
          const startTimestamp = current[0].timestamp;
          const endTimestamp = current[current.length - 1].timestamp;
          clusters.push({
            id: `${bucketKey}-${startTimestamp}`,
            bucketKey,
            rows: current.map((item) => item.row),
            startTimestamp,
            endTimestamp,
            durationMs: Math.max(0, endTimestamp - startTimestamp),
          });
        }
        current = [entry];
      }
      if (index === sorted.length - 1 && current.length >= minTrades) {
        const startTimestamp = current[0].timestamp;
        const endTimestamp = current[current.length - 1].timestamp;
        clusters.push({
          id: `${bucketKey}-${startTimestamp}`,
          bucketKey,
          rows: current.map((item) => item.row),
          startTimestamp,
          endTimestamp,
          durationMs: Math.max(0, endTimestamp - startTimestamp),
        });
      }
    });
  });

  return clusters;
}

function dedupeManualTrades(trades: ManualLinkTrade[]): ManualLinkTrade[] {
  const seen = new Set<string>();
  return trades.filter((trade) => {
    const key = trade?.trade_id ? String(trade.trade_id) : "";
    if (!key) return true;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function parseIdList(value: string): string[] {
  if (!value) return [];
  return value
    .split(/[,\s]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function normalizeSelectedPackageIds(
  ids: Array<string | null | undefined>,
): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  ids.forEach((entry) => {
    const value = typeof entry === "string" ? entry.trim() : "";
    if (!value || seen.has(value)) return;
    seen.add(value);
    normalized.push(value);
  });
  return normalized;
}

function parseSelectedPackageIds(rawValue: string | null): string[] {
  if (!rawValue) return [];
  return normalizeSelectedPackageIds(parseIdList(rawValue));
}

function serializeSelectedPackageIds(
  ids: Array<string | null | undefined>,
): string {
  return normalizeSelectedPackageIds(ids).join(",");
}

function parseBooleanQueryFlag(rawValue: string | null): boolean {
  if (!rawValue) return false;
  const normalized = rawValue.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes";
}

function formatManualMetricValue(value: any): string {
  if (!isValid(value)) return "--";
  if (typeof value === "number") return formatMetricValue(value, 3);
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry)).join(", ");
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function parseAxisInput(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const normalized = trimmed.toLowerCase();
  if (normalized === "auto") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function isEmptyFilterValue(value: any) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string" && value.trim() === "") return true;
  if (Array.isArray(value) && value.length === 0) return true;
  return false;
}

function parseFilterNumber(value: any): number | null {
  if (typeof value === "number" && !Number.isNaN(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const numeric = Number(value);
    return Number.isNaN(numeric) ? null : numeric;
  }
  return null;
}

const ISO_TIMESTAMP_PATTERN =
  /\b\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b/i;
const ISO_LOCAL_TIMESTAMP_PATTERN =
  /\b(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?\b/i;
const US_LOCAL_TIMESTAMP_PATTERN =
  /\b(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?\b/;
const EASTERN_TIME_ZONE = "America/New_York";
const EASTERN_PARTS_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: EASTERN_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

function parseFilterYear(rawYear: string): number {
  const parsed = Number(rawYear);
  if (!Number.isFinite(parsed)) return Number.NaN;
  if (rawYear.length === 2) {
    return parsed >= 70 ? parsed + 1900 : parsed + 2000;
  }
  return parsed;
}

function extractTimeZoneParts(timestampMs: number, timeZone: string) {
  const formatter =
    timeZone === EASTERN_TIME_ZONE
      ? EASTERN_PARTS_FORMATTER
      : new Intl.DateTimeFormat("en-US", {
          timeZone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        });
  const parts = formatter.formatToParts(new Date(timestampMs));
  const values: Record<string, number> = {};
  parts.forEach((part) => {
    if (part.type === "literal") return;
    const numeric = Number(part.value);
    if (Number.isFinite(numeric)) values[part.type] = numeric;
  });
  const year = values.year;
  const month = values.month;
  const day = values.day;
  const hour = values.hour;
  const minute = values.minute;
  const second = values.second;
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    !Number.isInteger(second)
  ) {
    return null;
  }
  return { year, month, day, hour, minute, second };
}

function toEasternEpochMs(
  year: number,
  month: number,
  day: number,
  hour = 0,
  minute = 0,
  second = 0,
): number | null {
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    !Number.isInteger(hour) ||
    !Number.isInteger(minute) ||
    !Number.isInteger(second)
  ) {
    return null;
  }
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  if (hour < 0 || hour > 23) return null;
  if (minute < 0 || minute > 59) return null;
  if (second < 0 || second > 59) return null;

  const desiredAsUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  const probe = new Date(desiredAsUtc);
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() + 1 !== month ||
    probe.getUTCDate() !== day ||
    probe.getUTCHours() !== hour ||
    probe.getUTCMinutes() !== minute ||
    probe.getUTCSeconds() !== second
  ) {
    return null;
  }

  let candidate = desiredAsUtc;
  for (let i = 0; i < 4; i += 1) {
    const zoned = extractTimeZoneParts(candidate, EASTERN_TIME_ZONE);
    if (!zoned) return null;
    const zonedAsUtc = Date.UTC(
      zoned.year,
      zoned.month - 1,
      zoned.day,
      zoned.hour,
      zoned.minute,
      zoned.second,
    );
    const delta = desiredAsUtc - zonedAsUtc;
    if (delta === 0) break;
    candidate += delta;
  }

  const finalized = extractTimeZoneParts(candidate, EASTERN_TIME_ZONE);
  if (!finalized) return null;
  if (
    finalized.year !== year ||
    finalized.month !== month ||
    finalized.day !== day ||
    finalized.hour !== hour ||
    finalized.minute !== minute ||
    finalized.second !== second
  ) {
    return null;
  }
  return candidate;
}

function parseFilterTimestamp(value: any): number | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\+/g, " ").replace(/\s+/g, " ").trim();
  if (!normalized) return null;

  const isoMatch = normalized.match(ISO_TIMESTAMP_PATTERN)?.[0];
  if (isoMatch && /(?:z|[+-]\d{2}:?\d{2})$/i.test(isoMatch)) {
    const parsed = Date.parse(isoMatch);
    if (!Number.isNaN(parsed)) return parsed;
  }

  const usMatch = normalized.match(US_LOCAL_TIMESTAMP_PATTERN);
  if (usMatch) {
    const month = Number(usMatch[1]);
    const day = Number(usMatch[2]);
    const year = parseFilterYear(usMatch[3]);
    const hour = usMatch[4] ? Number(usMatch[4]) : 0;
    const minute = usMatch[5] ? Number(usMatch[5]) : 0;
    const second = usMatch[6] ? Number(usMatch[6]) : 0;
    const parsed = toEasternEpochMs(year, month, day, hour, minute, second);
    if (parsed !== null) return parsed;
  }

  const isoLocalMatch = normalized.match(ISO_LOCAL_TIMESTAMP_PATTERN);
  if (isoLocalMatch) {
    const year = Number(isoLocalMatch[1]);
    const month = Number(isoLocalMatch[2]);
    const day = Number(isoLocalMatch[3]);
    const hour = isoLocalMatch[4] ? Number(isoLocalMatch[4]) : 0;
    const minute = isoLocalMatch[5] ? Number(isoLocalMatch[5]) : 0;
    const second = isoLocalMatch[6] ? Number(isoLocalMatch[6]) : 0;
    const parsed = toEasternEpochMs(year, month, day, hour, minute, second);
    if (parsed !== null) return parsed;
  }

  const direct = Date.parse(normalized);
  if (!Number.isNaN(direct)) return direct;

  return null;
}

function normalizeFilterConstraintValue(field: string, value: any) {
  if (NUMERIC_FILTER_FIELDS.has(field)) {
    if (Array.isArray(value)) {
      return value.map((entry) => {
        const numericValue = parseFilterNumber(entry);
        return numericValue !== null ? numericValue : entry;
      });
    }
    const numericValue = parseFilterNumber(value);
    return numericValue !== null ? numericValue : value;
  }
  return value;
}

function parseColumnFilterOperator(value: string | null) {
  return value === FilterOperator.OR ? FilterOperator.OR : FilterOperator.AND;
}

function buildColumnFilterPayload(filters: DataTableFilterMeta) {
  const payload: ColumnFilterPayload = {};
  FILTER_FIELDS.forEach((field) => {
    const filterMeta = (filters || {})[field];
    if (!filterMeta) return;
    const filterMetaAny = filterMeta as any;
    const constraints = Array.isArray(filterMetaAny.constraints)
      ? filterMetaAny.constraints
      : [
          {
            value: filterMetaAny.value,
            matchMode: filterMetaAny.matchMode,
          },
        ];
    const activeConstraints = constraints
      .map((constraint: any) => ({
        value: constraint?.value,
        matchMode: constraint?.matchMode,
      }))
      .filter((constraint: any) => !isEmptyFilterValue(constraint.value));
    if (!activeConstraints.length) return;
    payload[field] = {
      operator:
        filterMetaAny.operator === FilterOperator.OR
          ? FilterOperator.OR
          : FilterOperator.AND,
      constraints: activeConstraints,
    };
  });
  return payload;
}

function parseColumnFilterPayload(rawValue: string | null): DataTableFilterMeta {
  if (!rawValue) return INITIAL_FILTERS;
  let parsed: ColumnFilterPayload | null = null;
  try {
    parsed = JSON.parse(rawValue) as ColumnFilterPayload;
  } catch {
    return INITIAL_FILTERS;
  }

  if (!parsed || typeof parsed !== "object") return INITIAL_FILTERS;

  const nextFilters: DataTableFilterMeta = { ...INITIAL_FILTERS };
  FILTER_FIELDS.forEach((field) => {
    const rawFilter = parsed?.[field];
    if (!rawFilter) return;
    const constraints = Array.isArray(rawFilter.constraints)
      ? rawFilter.constraints
      : [
          {
            value: (rawFilter as any).value,
            matchMode: (rawFilter as any).matchMode,
          },
        ];
    const normalizedConstraints = constraints
      .map((constraint: any) => ({
        value: normalizeFilterConstraintValue(field, constraint?.value),
        matchMode:
          typeof constraint?.matchMode === "string"
            ? constraint.matchMode
            : (INITIAL_FILTERS as any)[field]?.constraints?.[0]?.matchMode,
      }))
      .filter((constraint: any) => !isEmptyFilterValue(constraint.value));
    if (!normalizedConstraints.length) return;
    nextFilters[field] = {
      operator:
        rawFilter.operator === FilterOperator.OR
          ? FilterOperator.OR
          : FilterOperator.AND,
      constraints: normalizedConstraints,
    };
  });
  return nextFilters;
}

function matchFilterValue(
  rowValue: any,
  filterValue: any,
  matchMode?: string,
): boolean {
  if (isEmptyFilterValue(filterValue)) return true;
  if (!isValid(rowValue)) return false;
  const mode = matchMode || DEFAULT_TEXT_MATCH_MODE;

  if (mode === FilterMatchMode.IN) {
    if (!Array.isArray(filterValue)) return false;
    return filterValue.some((item) =>
      matchFilterValue(rowValue, item, FilterMatchMode.EQUALS),
    );
  }

  const rowNumber = parseFilterNumber(rowValue);
  const filterNumber = parseFilterNumber(filterValue);
  const rowTimestamp = parseFilterTimestamp(rowValue);
  const filterTimestamp = parseFilterTimestamp(filterValue);
  const comparisonModes = new Set<string>([
    FilterMatchMode.EQUALS,
    FilterMatchMode.NOT_EQUALS,
    FilterMatchMode.LESS_THAN,
    FilterMatchMode.LESS_THAN_OR_EQUAL_TO,
    FilterMatchMode.GREATER_THAN,
    FilterMatchMode.GREATER_THAN_OR_EQUAL_TO,
  ]);
  if (
    comparisonModes.has(mode) &&
    rowTimestamp !== null &&
    filterTimestamp !== null
  ) {
    switch (mode) {
      case FilterMatchMode.EQUALS:
        return rowTimestamp === filterTimestamp;
      case FilterMatchMode.NOT_EQUALS:
        return rowTimestamp !== filterTimestamp;
      case FilterMatchMode.LESS_THAN:
        return rowTimestamp < filterTimestamp;
      case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
        return rowTimestamp <= filterTimestamp;
      case FilterMatchMode.GREATER_THAN:
        return rowTimestamp > filterTimestamp;
      case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
        return rowTimestamp >= filterTimestamp;
      default:
        return false;
    }
  }
  const numericModes = new Set<string>([
    FilterMatchMode.EQUALS,
    FilterMatchMode.NOT_EQUALS,
    FilterMatchMode.LESS_THAN,
    FilterMatchMode.LESS_THAN_OR_EQUAL_TO,
    FilterMatchMode.GREATER_THAN,
    FilterMatchMode.GREATER_THAN_OR_EQUAL_TO,
  ]);
  if (numericModes.has(mode) && rowNumber !== null && filterNumber !== null) {
    switch (mode) {
      case FilterMatchMode.EQUALS:
        return rowNumber === filterNumber;
      case FilterMatchMode.NOT_EQUALS:
        return rowNumber !== filterNumber;
      case FilterMatchMode.LESS_THAN:
        return rowNumber < filterNumber;
      case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
        return rowNumber <= filterNumber;
      case FilterMatchMode.GREATER_THAN:
        return rowNumber > filterNumber;
      case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
        return rowNumber >= filterNumber;
      default:
        return false;
    }
  }

  const rowString = String(rowValue).toLowerCase();
  const filterString = String(filterValue).toLowerCase();

  switch (mode) {
    case FilterMatchMode.STARTS_WITH:
      return rowString.startsWith(filterString);
    case FilterMatchMode.CONTAINS:
      return rowString.includes(filterString);
    case FilterMatchMode.NOT_CONTAINS:
      return !rowString.includes(filterString);
    case FilterMatchMode.ENDS_WITH:
      return rowString.endsWith(filterString);
    case FilterMatchMode.EQUALS:
      return rowString === filterString;
    case FilterMatchMode.NOT_EQUALS:
      return rowString !== filterString;
    default:
      return rowString.includes(filterString);
  }
}

function matchFilterMeta(rowValue: any, filterMeta: any): boolean {
  if (!filterMeta) return true;
  const constraints = Array.isArray(filterMeta.constraints)
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode,
        },
      ];
  const activeConstraints = constraints.filter(
    (constraint: any) => !isEmptyFilterValue(constraint?.value),
  );
  if (!activeConstraints.length) return true;
  const operator = filterMeta.operator || FilterOperator.AND;
  const useOr = operator === FilterOperator.OR;
  return useOr
    ? activeConstraints.some((constraint: any) =>
        matchFilterValue(rowValue, constraint.value, constraint.matchMode),
      )
    : activeConstraints.every((constraint: any) =>
        matchFilterValue(rowValue, constraint.value, constraint.matchMode),
      );
}

function hasActiveConstraints(filterMeta: any): boolean {
  if (!filterMeta) return false;
  const constraints = Array.isArray(filterMeta.constraints)
    ? filterMeta.constraints
    : [
        {
          value: filterMeta.value,
          matchMode: filterMeta.matchMode,
        },
      ];
  return constraints.some(
    (constraint: any) => !isEmptyFilterValue(constraint?.value),
  );
}

function formatFilterValue(value: any): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  return String(value);
}

function formatMatchModeLabel(mode?: string): string {
  switch (mode) {
    case FilterMatchMode.STARTS_WITH:
      return "starts with";
    case FilterMatchMode.CONTAINS:
      return "contains";
    case FilterMatchMode.NOT_CONTAINS:
      return "not contains";
    case FilterMatchMode.ENDS_WITH:
      return "ends with";
    case FilterMatchMode.EQUALS:
      return "equals";
    case FilterMatchMode.NOT_EQUALS:
      return "not equals";
    case FilterMatchMode.LESS_THAN:
      return "<";
    case FilterMatchMode.LESS_THAN_OR_EQUAL_TO:
      return "<=";
    case FilterMatchMode.GREATER_THAN:
      return ">";
    case FilterMatchMode.GREATER_THAN_OR_EQUAL_TO:
      return ">=";
    case FilterMatchMode.IN:
      return "in";
    default:
      return "contains";
  }
}

function formatTimeseriesMetric(
  metricKey: TimeseriesMetricKey,
  value: number | null | undefined,
  decimals: number,
): string {
  if (!isValid(value)) return "--";
  if (metricKey === "notional") {
    return formatNotional(Number(value));
  }
  return formatMetricValue(Number(value), decimals);
}

function buildTimeseriesDomain(
  values: number[],
  includeZero: boolean,
): [number, number] | null {
  if (!values.length) return null;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    const padding = min === 0 ? 1 : Math.abs(min) * 0.05;
    min -= padding;
    max += padding;
  } else {
    const padding = (max - min) * 0.1;
    min -= padding;
    max += padding;
  }
  if (includeZero) {
    if (min > 0) min = 0;
    if (max < 0) max = 0;
  }
  return [min, max];
}

function parseDateInput(value: string, isEnd: boolean): number | null {
  if (!value) return null;
  const suffix = isEnd ? "T23:59:59" : "T00:00:00";
  const timestamp = new Date(`${value}${suffix}`).getTime();
  return Number.isNaN(timestamp) ? null : timestamp;
}

function formatDateKey(timestamp: number): string {
  const date = new Date(timestamp);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDateLabel(timestamp: number): string {
  return new Date(timestamp).toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "2-digit",
  });
}

function resolveTimeseriesMetricValue(
  point: StraddleTimeseriesPoint,
  metricKey: TimeseriesMetricKey,
  transform?: (value: number) => number,
): number | null {
  const value = point[metricKey];
  if (!isValid(value)) return null;
  const numericValue = Number(value);
  if (Number.isNaN(numericValue)) return null;
  return transform ? transform(numericValue) : numericValue;
}

function buildDailyTimeseries(
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  transform?: (value: number) => number,
): DailyTimeseriesPoint[] {
  if (!points.length) return [];
  const buckets = new Map<
    string,
    {
      timestamp: number;
      timeLabel: string;
      open: number;
      high: number;
      low: number;
      close: number;
      daySum: number;
      openTimestamp: number;
      closeTimestamp: number;
    }
  >();

  points.forEach((point) => {
    const value = resolveTimeseriesMetricValue(point, metricKey, transform);
    if (value === null) return;
    const dayStart = new Date(
      new Date(point.timestamp).getFullYear(),
      new Date(point.timestamp).getMonth(),
      new Date(point.timestamp).getDate(),
    ).getTime();
    const dateKey = formatDateKey(point.timestamp);
    const existing = buckets.get(dateKey);
    if (!existing) {
      buckets.set(dateKey, {
        timestamp: dayStart,
        timeLabel: formatDateLabel(point.timestamp),
        open: value,
        high: value,
        low: value,
        close: value,
        daySum: value,
        openTimestamp: point.timestamp,
        closeTimestamp: point.timestamp,
      });
      return;
    }
    existing.daySum += value;
    if (value > existing.high) existing.high = value;
    if (value < existing.low) existing.low = value;
    if (point.timestamp < existing.openTimestamp) {
      existing.open = value;
      existing.openTimestamp = point.timestamp;
    }
    if (point.timestamp >= existing.closeTimestamp) {
      existing.close = value;
      existing.closeTimestamp = point.timestamp;
    }
  });

  return Array.from(buckets.values())
    .sort((left, right) => left.timestamp - right.timestamp)
    .map(({ closeTimestamp, openTimestamp, ...rest }) => ({
      ...rest,
      range: rest.high - rest.low,
    }));
}

type SeriesValuePoint = {
  timestamp: number;
  timeLabel: string;
  value: number;
};

function buildIntradaySeries(
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  transform?: (value: number) => number,
): SeriesValuePoint[] {
  return points
    .map((point) => {
      const value = resolveTimeseriesMetricValue(point, metricKey, transform);
      if (value === null) return null;
      return {
        timestamp: point.timestamp,
        timeLabel: point.timeLabel,
        value,
      };
    })
    .filter((point): point is SeriesValuePoint => point !== null)
    .sort((left, right) => left.timestamp - right.timestamp);
}

function mergeIntradaySeries(
  custyPoints: SeriesValuePoint[],
  idbPoints: SeriesValuePoint[],
): TimeseriesChartPoint[] {
  const merged: TimeseriesChartPoint[] = [];
  custyPoints.forEach((point) => {
    merged.push({
      timestamp: point.timestamp,
      timeLabel: point.timeLabel,
      custyValue: point.value,
    });
  });
  idbPoints.forEach((point) => {
    merged.push({
      timestamp: point.timestamp,
      timeLabel: point.timeLabel,
      idbValue: point.value,
    });
  });
  return merged.sort((left, right) => left.timestamp - right.timestamp);
}

function mergeDailySeries(
  custyPoints: DailyTimeseriesPoint[],
  idbPoints: DailyTimeseriesPoint[],
  valueKey: "close" | "daySum",
): TimeseriesChartPoint[] {
  const buckets = new Map<number, TimeseriesChartPoint>();
  const appendPoint = (
    point: DailyTimeseriesPoint,
    key: "custyValue" | "idbValue",
  ) => {
    const existing = buckets.get(point.timestamp) ?? {
      timestamp: point.timestamp,
      timeLabel: point.timeLabel,
    };
    const value = point[valueKey];
    if (isValid(value)) {
      existing[key] = Number(value);
    }
    buckets.set(point.timestamp, existing);
  };
  custyPoints.forEach((point) => appendPoint(point, "custyValue"));
  idbPoints.forEach((point) => appendPoint(point, "idbValue"));
  return Array.from(buckets.values()).sort(
    (left, right) => left.timestamp - right.timestamp,
  );
}

function filterTimeseriesByRange(
  points: StraddleTimeseriesPoint[],
  rangeKey: TimeseriesRangeKey,
  customRangeStart: string,
  customRangeEnd: string,
  latestTimestamp: number | null,
): StraddleTimeseriesPoint[] {
  if (!points.length) return [];
  if (rangeKey === "CUSTOM") {
    const startTimestamp = parseDateInput(customRangeStart, false);
    const endTimestamp = parseDateInput(customRangeEnd, true);
    if (startTimestamp === null && endTimestamp === null) {
      return points;
    }
    return points.filter((point) => {
      if (startTimestamp !== null && point.timestamp < startTimestamp) {
        return false;
      }
      if (endTimestamp !== null && point.timestamp > endTimestamp) {
        return false;
      }
      return true;
    });
  }
  const rangeConfig = TIMESERIES_RANGE_OPTIONS.find(
    (option) => option.key === rangeKey,
  );
  if (!rangeConfig || rangeConfig.days === null || latestTimestamp === null) {
    return points;
  }
  const cutoff = latestTimestamp - rangeConfig.days * 24 * 60 * 60 * 1000;
  return points.filter((point) => point.timestamp >= cutoff);
}

function findTimeseriesExtremes(
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
  transform?: (value: number) => number,
): { min: TimeseriesExtremePoint | null; max: TimeseriesExtremePoint | null } {
  let minPoint: TimeseriesExtremePoint | null = null;
  let maxPoint: TimeseriesExtremePoint | null = null;
  points.forEach((point) => {
    const value = resolveTimeseriesMetricValue(point, metricKey, transform);
    if (value === null) return;
    if (!minPoint || value < minPoint.value) {
      minPoint = {
        value,
        timeLabel: point.timeLabel,
        timestamp: point.timestamp,
      };
    }
    if (!maxPoint || value > maxPoint.value) {
      maxPoint = {
        value,
        timeLabel: point.timeLabel,
        timestamp: point.timestamp,
      };
    }
  });
  return { min: minPoint, max: maxPoint };
}

function buildLocalDateKey(timestamp: number): string | null {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function computeTimeseriesSummary(
  points: StraddleTimeseriesPoint[],
): TimeseriesSummaryStats {
  const tradeCount = points.length;
  const notionals = points
    .map((point) => point.notional)
    .filter(isValid)
    .map((value) => Math.abs(Number(value)))
    .filter((value) => Number.isFinite(value));
  const totalNotional = notionals.length
    ? notionals.reduce((sum, value) => sum + value, 0)
    : null;
  const avgNotional =
    notionals.length && totalNotional !== null
      ? totalNotional / notionals.length
      : null;
  const medianNotional = notionals.length ? median(notionals) : null;

  const premiums = points
    .map((point) => point.premium)
    .filter(isValid)
    .map((value) => Math.abs(Number(value)))
    .filter((value) => Number.isFinite(value));
  const totalPremium = premiums.length
    ? premiums.reduce((sum, value) => sum + value, 0)
    : null;
  const avgPremium =
    premiums.length && totalPremium !== null
      ? totalPremium / premiums.length
      : null;
  const medianPremium = premiums.length ? median(premiums) : null;

  const vegas = points
    .map((point) => point.vega01)
    .filter(isValid)
    .map((value) => Math.abs(Number(value)))
    .filter((value) => Number.isFinite(value));
  const totalVega = vegas.length
    ? vegas.reduce((sum, value) => sum + value, 0)
    : null;
  const avgVega01 =
    vegas.length && totalVega !== null ? totalVega / vegas.length : null;
  const medianVega01 = vegas.length ? median(vegas) : null;

  const timestamps = points
    .map((point) => point.timestamp)
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);
  let avgGapMs: number | null = null;
  if (timestamps.length > 1) {
    let totalGap = 0;
    for (let index = 1; index < timestamps.length; index += 1) {
      totalGap += timestamps[index] - timestamps[index - 1];
    }
    avgGapMs = totalGap / (timestamps.length - 1);
  }
  const activeDaysSet = new Set<string>();
  timestamps.forEach((timestamp) => {
    const key = buildLocalDateKey(timestamp);
    if (key) activeDaysSet.add(key);
  });
  const activeDays = activeDaysSet.size;
  const tradesPerDay =
    activeDays > 0 ? tradeCount / activeDays : null;

  return {
    tradeCount,
    totalNotional,
    avgNotional,
    medianNotional,
    totalPremium,
    avgPremium,
    medianPremium,
    avgVega01,
    medianVega01,
    tradesPerDay,
    avgGapMs,
    activeDays,
  };
}

function OhlcSeries({
  data,
  xAxisMap,
  yAxisMap,
  stroke,
}: {
  data?: DailyTimeseriesPoint[];
  xAxisMap?: Record<string, any>;
  yAxisMap?: Record<string, any>;
  stroke?: string;
}) {
  const series = Array.isArray(data) ? data : [];
  const xAxis = xAxisMap ? Object.values(xAxisMap)[0] : null;
  const yAxis = yAxisMap ? Object.values(yAxisMap)[0] : null;
  const xScale = xAxis?.scale;
  const yScale = yAxis?.scale;
  if (!xScale || !yScale || !series.length) return null;

  const stepSize =
    typeof xScale.step === "function" ? xScale.step() : undefined;
  const bandWidth =
    typeof xScale.bandwidth === "function" ? xScale.bandwidth() : stepSize || 0;
  const tickHalf = bandWidth ? Math.min(6, bandWidth / 2) : 6;
  const color = stroke || "#e2e8f0";

  return (
    <g>
      {series.map((point) => {
        if (
          !isValid(point.open) ||
          !isValid(point.high) ||
          !isValid(point.low) ||
          !isValid(point.close)
        ) {
          return null;
        }
        const xValue = xScale(point.timeLabel);
        if (xValue === undefined || xValue === null) return null;
        const centerX = Number(xValue) + (bandWidth ? bandWidth / 2 : 0);
        const yHigh = yScale(point.high);
        const yLow = yScale(point.low);
        const yOpen = yScale(point.open);
        const yClose = yScale(point.close);
        const coords = [yHigh, yLow, yOpen, yClose];
        if (
          coords.some(
            (value) => typeof value !== "number" || Number.isNaN(value),
          )
        ) {
          return null;
        }
        return (
          <g
            key={`${point.timestamp}-ohlc`}
            stroke={color}
            strokeWidth={1.5}
          >
            <line x1={centerX} x2={centerX} y1={yHigh} y2={yLow} />
            <line
              x1={centerX - tickHalf}
              x2={centerX}
              y1={yOpen}
              y2={yOpen}
            />
            <line
              x1={centerX}
              x2={centerX + tickHalf}
              y1={yClose}
              y2={yClose}
            />
          </g>
        );
      })}
    </g>
  );
}

function resolveTenorKey(row: TapeRow): string | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const tradeLabel = legs[0]?.trade_label ?? "";
  const rawLabel = `${tradeLabel} ${row.forward_label ?? ""} ${row.tenor_label ?? ""}`;
  const forwardLabel = normalizeTenorToken(row.forward_label);
  const tenorLabel = normalizeTenorToken(row.tenor_label);
  if (forwardLabel && tenorLabel) {
    return `${forwardLabel}x${tenorLabel}`;
  }
  const match = rawLabel.match(TENOR_REGEX);
  if (match) {
    const matchForward = normalizeTenorToken(match[1]);
    const matchTenor = normalizeTenorToken(match[2]);
    if (matchForward && matchTenor) {
      return `${matchForward}x${matchTenor}`;
    }
  }
  return null;
}

function buildStraddleSeriesKey(row: TapeRow): string | null {
  const tenorKey = resolveTenorKey(row);
  if (tenorKey) return tenorKey;
  return null;
}

function resolveStraddleNotional(row: TapeRow): number | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLegNotional = legs[0]?.notional;
  if (isValid(firstLegNotional)) return Number(firstLegNotional);
  return parseMetricNumber(row.total_notional);
}

function resolvePackageNotional(row: TapeRow): number | null {
  return computeDisplayNotional(row);
}

function resolveStraddleBpvolYr(row: TapeRow): number | null {
  const metrics = row.package_metrics || {};
  const directValue = parseMetricNumber((metrics as any).straddle_bpvol_yr);
  if (directValue !== null) return directValue;
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  return parseMetricNumber((legs[0] as any)?.leg_metrics?.straddle_bpvol_yr);
}

function computeStraddlePremium(row: TapeRow): number | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  let total: number | null = null;
  legs.forEach((leg) => {
    if (!isValid(leg?.premium)) return;
    const premiumValue = Number(leg.premium) * STRADDLE_SPLIT_FACTOR;
    if (Number.isNaN(premiumValue)) return;
    total = total === null ? premiumValue : total + premiumValue;
  });
  if (total !== null) return total;
  return isValid(row.total_premium) ? Number(row.total_premium) : null;
}

function computePackagePremium(row: TapeRow, packageType: string): number | null {
  if (packageType === "STRADDLE") return computeStraddlePremium(row);
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  let total: number | null = null;
  legs.forEach((leg) => {
    if (!isValid(leg?.premium)) return;
    const premiumValue = Number(leg.premium);
    if (Number.isNaN(premiumValue)) return;
    total = total === null ? premiumValue : total + premiumValue;
  });
  if (total !== null) return total;
  return isValid(row.total_premium) ? Number(row.total_premium) : null;
}

function computeStraddlePremiumBps(row: TapeRow): number | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  let total: number | null = null;
  legs.forEach((leg) => {
    if (!isValid(leg?.premium) || !isValid(leg?.notional)) return;
    const premiumValue = Number(leg.premium) * STRADDLE_SPLIT_FACTOR;
    const notionalValue = Number(leg.notional);
    if (Number.isNaN(premiumValue) || Number.isNaN(notionalValue)) return;
    if (notionalValue === 0) return;
    const premiumBps = (premiumValue / notionalValue) * 10_000;
    total = total === null ? premiumBps : total + premiumBps;
  });
  if (total !== null) return total;
  const premiumValue = computeStraddlePremium(row);
  const notionalValue = resolveStraddleNotional(row);
  if (
    premiumValue !== null &&
    notionalValue !== null &&
    notionalValue !== 0
  ) {
    return (premiumValue / notionalValue) * 10_000;
  }
  return null;
}

function computePackagePremiumBps(
  row: TapeRow,
  packageType: string,
): number | null {
  if (packageType === "STRADDLE") return computeStraddlePremiumBps(row);
  const premiumValue = computePackagePremium(row, packageType);
  const notionalValue = resolvePackageNotional(row);
  if (
    premiumValue !== null &&
    notionalValue !== null &&
    notionalValue !== 0
  ) {
    return (premiumValue / notionalValue) * 10_000;
  }
  return null;
}

function resolveStraddleGreek(
  row: TapeRow,
  key: keyof typeof STRADDLE_GREEK_FIELDS,
): number | null {
  const metrics = row.package_metrics || {};
  const field = STRADDLE_GREEK_FIELDS[key];
  const directValue = parseMetricNumber((metrics as any)[field]);
  if (directValue !== null) return directValue;
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  return parseMetricNumber((legs[0] as any)?.leg_metrics?.[field]);
}

function sumMetricNumbers(...values: any[]): number | null {
  let total: number | null = null;
  values.forEach((value) => {
    const numeric = parseMetricNumber(value);
    if (numeric === null) return;
    total = total === null ? numeric : total + numeric;
  });
  return total;
}

function resolvePackageBpvolYr(
  row: TapeRow,
  packageType: string,
): number | null {
  if (packageType === "STRADDLE") return resolveStraddleBpvolYr(row);
  const metrics = row.package_metrics || {};
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  if (packageType === "RISK_REVERSAL") {
    return (
      parseMetricNumber((metrics as any).rr_skew_bpvol) ??
      parseMetricNumber((metrics as any).rr_atm_bpvol) ??
      parseMetricNumber((legs[0] as any)?.leg_metrics?.rr_atm_bpvol)
    );
  }
  if (
    packageType === "VERTICAL_SPREAD_1X1" ||
    packageType === "VERTICAL_SPREAD_1X2"
  ) {
    return (
      parseMetricNumber((metrics as any).vs_atm_bpvol_yr) ??
      parseMetricNumber((metrics as any).vs_otm_bpvol_yr)
    );
  }
  if (!packageType || packageType === "OUTRIGHT") {
    return parseMetricNumber((legs[0] as any)?.leg_metrics?.outright_bpvol_yr);
  }
  return null;
}

function resolvePackageGreek(
  row: TapeRow,
  packageType: string,
  key: keyof typeof STRADDLE_GREEK_FIELDS,
): number | null {
  if (packageType === "STRADDLE") return resolveStraddleGreek(row, key);
  const metrics = row.package_metrics || {};
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];

  if (packageType === "RISK_REVERSAL") {
    if (key === "dv01") {
      return (
        parseMetricNumber((metrics as any).rr_dv01) ??
        parseMetricNumber((metrics as any).rr_wing_dv01)
      );
    }
    if (key === "vega01") {
      return parseMetricNumber((metrics as any).rr_vega01);
    }
    if (key === "gamma01") {
      return parseMetricNumber((metrics as any).rr_gamma01);
    }
    if (key === "theta01") {
      return parseMetricNumber((metrics as any).rr_theta1d);
    }
  }

  if (
    packageType === "VERTICAL_SPREAD_1X1" ||
    packageType === "VERTICAL_SPREAD_1X2"
  ) {
    if (key === "dv01") {
      return sumMetricNumbers(
        (metrics as any).vs_dv01,
        (metrics as any).vs_atm_dv01,
        (metrics as any).vs_otm_dv01,
      );
    }
    if (key === "vega01") {
      return sumMetricNumbers(
        (metrics as any).vs_vega01,
        (metrics as any).vs_atm_vega01,
        (metrics as any).vs_otm_vega01,
      );
    }
    if (key === "gamma01") {
      return parseMetricNumber((metrics as any).vs_gamma01);
    }
    if (key === "theta01") {
      return parseMetricNumber((metrics as any).vs_theta1d);
    }
  }

  if (!packageType || packageType === "OUTRIGHT") {
    const legMetrics = (legs[0] as any)?.leg_metrics || {};
    if (key === "dv01") return parseMetricNumber(legMetrics.outright_dv01);
    if (key === "vega01") return parseMetricNumber(legMetrics.outright_vega01);
    if (key === "gamma01") return parseMetricNumber(legMetrics.outright_gamma01);
    if (key === "theta01") return parseMetricNumber(legMetrics.outright_theta1d);
  }

  return null;
}

function buildTimeseriesSeriesKey(
  row: TapeRow,
  packageType: string,
): string | null {
  if (packageType === "STRADDLE") return buildStraddleSeriesKey(row);
  const tenorKey = resolveTenorKey(row);
  if (tenorKey) return tenorKey;
  return null;
}

function buildTimeseriesPoint(
  row: TapeRow,
  packageType: string,
): StraddleTimeseriesPoint | null {
  if (packageType === "STRADDLE") {
    return buildStraddleTimeseriesPoint(row);
  }
  if (!row.execution_start) return null;
  const timestamp = new Date(row.execution_start).getTime();
  if (Number.isNaN(timestamp)) return null;
  const timeLabel = new Date(row.execution_start).toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const bpvolYr = resolvePackageBpvolYr(row, packageType);
  const bpvolDay = bpvolYr !== null ? bpvolYr / BPVOL_DAY_DIVISOR : null;
  const notional = resolvePackageNotional(row);
  const premium = computePackagePremium(row, packageType);
  const premiumBps = computePackagePremiumBps(row, packageType);
  const dv01 = resolvePackageGreek(row, packageType, "dv01");
  const vega01 = resolvePackageGreek(row, packageType, "vega01");
  const gamma01 = resolvePackageGreek(row, packageType, "gamma01");
  const theta01 = resolvePackageGreek(row, packageType, "theta01");
  return {
    timestamp,
    timeLabel,
    bpvolYr,
    bpvolDay,
    premiumBps,
    notional,
    premium,
    dv01,
    vega01,
    gamma01,
    theta01,
  };
}

function buildStraddleTimeseriesPoint(
  row: TapeRow,
): StraddleTimeseriesPoint | null {
  if (!row.execution_start) return null;
  const timestamp = new Date(row.execution_start).getTime();
  if (Number.isNaN(timestamp)) return null;
  const timeLabel = new Date(row.execution_start).toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const bpvolYr = resolveStraddleBpvolYr(row);
  const bpvolDay = bpvolYr !== null ? bpvolYr / BPVOL_DAY_DIVISOR : null;
  const notional = resolveStraddleNotional(row);
  const premium = computeStraddlePremium(row);
  const premiumBps = computeStraddlePremiumBps(row);
  const dv01 = resolveStraddleGreek(row, "dv01");
  const vega01 = resolveStraddleGreek(row, "vega01");
  const gamma01 = resolveStraddleGreek(row, "gamma01");
  const theta01 = resolveStraddleGreek(row, "theta01");
  return {
    timestamp,
    timeLabel,
    bpvolYr,
    bpvolDay,
    premiumBps,
    notional,
    premium,
    dv01,
    vega01,
    gamma01,
    theta01,
  };
}

function normalizeStrikeToLegScale(
  metricStrike: number | null,
  legSampleStrike: number | null,
): number | null {
  if (metricStrike === null || legSampleStrike === null) return metricStrike;
  const metricAbs = Math.abs(metricStrike);
  const legAbs = Math.abs(legSampleStrike);
  if (metricAbs > 1 && legAbs > 0 && legAbs <= 1) {
    return metricStrike / 100;
  }
  if (metricAbs <= 1 && legAbs > 1) {
    return metricStrike * 100;
  }
  return metricStrike;
}

function pickMetricKey(
  keyOptions: string | readonly string[],
  useSecondary: boolean,
) {
  if (Array.isArray(keyOptions)) {
    return keyOptions[useSecondary ? 1 : 0];
  }
  return keyOptions;
}

function strikeMatches(
  leftStrike: number | null | undefined,
  rightStrike: number | null | undefined,
) {
  if (!isValid(leftStrike) || !isValid(rightStrike)) return false;
  return Math.abs(Number(leftStrike) - Number(rightStrike)) <= STRIKE_MATCH_EPS;
}

function findStrikeIndex(
  targetStrike: number | null | undefined,
  candidates: any[],
) {
  if (!isValid(targetStrike)) return null;
  const numericStrike = Number(targetStrike);
  for (
    let candidateIndex = 0;
    candidateIndex < candidates.length;
    candidateIndex += 1
  ) {
    const candidateValue = candidates[candidateIndex];
    if (strikeMatches(numericStrike, candidateValue)) {
      return candidateIndex;
    }
  }
  return null;
}

function resolveLadderLegIndex(
  leg: TapeLeg,
  metrics: Record<string, any>,
  legIndex: number,
) {
  const strikes = Array.isArray(metrics.ladder_strikes)
    ? metrics.ladder_strikes
    : [];
  const strikeIndex = strikes.length
    ? findStrikeIndex(leg.strike ?? null, strikes)
    : null;
  if (strikeIndex !== null) return strikeIndex;

  const orderIndex = isValid(leg.leg_order) ? Number(leg.leg_order) - 1 : null;
  if (orderIndex !== null && orderIndex >= 0) return orderIndex;

  return legIndex >= 0 ? legIndex : null;
}

function resolveLadderValue(
  metrics: Record<string, any>,
  key: string,
  legIndex: number | null,
  fallback: number | null | undefined,
) {
  const values = Array.isArray(metrics[key]) ? metrics[key] : [];
  if (
    legIndex !== null &&
    legIndex >= 0 &&
    legIndex < values.length &&
    isValid(values[legIndex])
  ) {
    return Number(values[legIndex]);
  }
  return isValid(fallback) ? Number(fallback) : null;
}

function isRiskReversalWing(
  leg: TapeLeg,
  metrics: Record<string, any>,
  legs: TapeLeg[],
  legIndex: number,
) {
  const sampleLegStrike =
    legs.find((candidate) => isValid(candidate.strike))?.strike ?? null;
  const outStrike = metrics.rr_out_strike;
  const outStrikeValues = Array.isArray(outStrike)
    ? outStrike
    : isValid(outStrike)
      ? [outStrike]
      : [];
  const normalizedOutStrikes = outStrikeValues
    .map((value) => normalizeStrikeToLegScale(Number(value), sampleLegStrike))
    .filter((value): value is number => value !== null);
  const outStrikeIndex = normalizedOutStrikes.length
    ? findStrikeIndex(leg.strike ?? null, normalizedOutStrikes)
    : null;
  if (outStrikeIndex !== null) return true;

  const atmStrikeValue = isValid(metrics.rr_atm_strike)
    ? normalizeStrikeToLegScale(Number(metrics.rr_atm_strike), sampleLegStrike)
    : null;
  if (
    atmStrikeValue !== null &&
    strikeMatches(leg.strike ?? null, atmStrikeValue)
  ) {
    return false;
  }

  if (normalizedOutStrikes.length) {
    return false;
  }

  const forwardStrikeValue =
    atmStrikeValue ??
    (isValid(metrics.rr_atmf)
      ? normalizeStrikeToLegScale(Number(metrics.rr_atmf), sampleLegStrike)
      : null);
  const strikeCandidates = legs
    .map((candidate) =>
      isValid(candidate.strike) ? Number(candidate.strike) : null,
    )
    .filter((strike): strike is number => strike !== null);
  if (
    forwardStrikeValue !== null &&
    strikeCandidates.length &&
    isValid(leg.strike)
  ) {
    const maxDistance = Math.max(
      ...strikeCandidates.map((strike) =>
        Math.abs(strike - forwardStrikeValue),
      ),
    );
    const legDistance = Math.abs(Number(leg.strike) - forwardStrikeValue);
    return Math.abs(legDistance - maxDistance) <= STRIKE_MATCH_EPS;
  }

  return legIndex > 0;
}

function isVerticalSpreadAtm(
  leg: TapeLeg,
  metrics: Record<string, any>,
  legIndex: number,
) {
  if (strikeMatches(leg.strike ?? null, metrics.vs_atm_strike)) return true;
  if (strikeMatches(leg.strike ?? null, metrics.vs_otm_strike)) return false;
  if (isValid(leg.leg_order)) return Number(leg.leg_order) <= 1;
  return legIndex === 0;
}

const EMPTY_LEG_METRICS: LegMetricValues = {
  bpvol: null,
  dv01: null,
  vega01: null,
  gamma01: null,
  theta01: null,
};

function selectLegMetrics({
  leg,
  metrics,
  packageType,
  legs,
  legIndex,
}: {
  leg: TapeLeg;
  metrics: Record<string, any>;
  packageType: string;
  legs: TapeLeg[];
  legIndex: number;
}): LegMetricValues {
  if (!metrics) return EMPTY_LEG_METRICS;
  if (packageType === "STRADDLE") {
    const schema = METRIC_SCHEMA.STRADDLE;
    return {
      bpvol: parseMetricNumber(metrics[schema.bpvol]),
      dv01: parseMetricNumber(metrics[schema.greeks.dv01]),
      vega01: parseMetricNumber(metrics[schema.greeks.vega01]),
      gamma01: parseMetricNumber(metrics[schema.greeks.gamma01]),
      theta01: parseMetricNumber(metrics[schema.theta01]),
    };
  }

  if (packageType === "RISK_REVERSAL") {
    const isWing = isRiskReversalWing(leg, metrics, legs, legIndex);
    const atmBpvol = parseMetricNumber(metrics.rr_atm_bpvol);
    return {
      bpvol: atmBpvol,
      dv01: isWing ? parseMetricNumber(metrics.rr_wing_dv01) : null,
      vega01: null,
      gamma01: null,
      theta01: null,
    };
  }

  if (
    packageType === "VERTICAL_SPREAD_1X1" ||
    packageType === "VERTICAL_SPREAD_1X2"
  ) {
    const schema =
      packageType === "VERTICAL_SPREAD_1X1"
        ? METRIC_SCHEMA.VERTICAL_SPREAD_1X1
        : METRIC_SCHEMA.VERTICAL_SPREAD_1X2;
    const useAtm = isVerticalSpreadAtm(leg, metrics, legIndex);
    const useOtm = !useAtm;
    return {
      bpvol: parseMetricNumber(metrics[pickMetricKey(schema.bpvol, useOtm)]),
      dv01: parseMetricNumber(
        metrics[pickMetricKey(schema.greeks.dv01, useOtm)],
      ),
      vega01: parseMetricNumber(
        metrics[pickMetricKey(schema.greeks.vega01, useOtm)],
      ),
      gamma01: null,
      theta01: null,
    };
  }

  if (!packageType || packageType === "OUTRIGHT") {
    const legMetrics = leg.leg_metrics || {};
    return {
      bpvol: parseMetricNumber(legMetrics.outright_bpvol_yr),
      dv01: parseMetricNumber(legMetrics.outright_dv01),
      vega01: parseMetricNumber(legMetrics.outright_vega01),
      gamma01: parseMetricNumber(legMetrics.outright_gamma01),
      theta01: parseMetricNumber(legMetrics.outright_theta1d),
    };
  }

  return EMPTY_LEG_METRICS;
}

function extractUnderlyingBase(
  tradeLabel?: string | null,
  row?: TapeRow,
): string {
  if (tradeLabel) {
    return tradeLabel
      .replace(/PAYER\s*/i, "")
      .replace(/RECEIVER\s*/i, "")
      .trim();
  }
  const tenor = row?.tenor_label || "";
  const fwd = row?.forward_label || "";
  const base = [fwd, tenor].filter(Boolean).join(" ");
  return base || "USD-SOFR";
}

function removeTrailingStyle(underlying: string, style: string) {
  const regex = new RegExp(`\\s*${style.replace(/\s+/g, "\\s+")}\\s*$`, "i");
  return underlying.replace(regex, "").trim();
}

function resolveRiskReversalWidthBps(
  strikes: number[],
  metrics: Record<string, any>,
): number | null {
  if (!strikes.length) {
    const widthFromMetrics = parseMetricNumber(metrics.rr_out_strike);
    return widthFromMetrics !== null ? Math.round(widthFromMetrics) : null;
  }

  const sortedStrikes = [...strikes].sort((a, b) => a - b);
  const minStrike = sortedStrikes[0];
  const maxStrike = sortedStrikes[sortedStrikes.length - 1];
  const middleIndex = Math.floor(sortedStrikes.length / 2);
  const atmfFromStrikes =
    sortedStrikes.length >= 3
      ? sortedStrikes.length % 2 === 1
        ? sortedStrikes[middleIndex]
        : (sortedStrikes[middleIndex - 1] + sortedStrikes[middleIndex]) / 2
      : null;
  const atmf = atmfFromStrikes ?? parseMetricNumber(metrics.rr_atmf);
  const widthFromStrikes =
    atmf !== null
      ? Math.round(
          Math.max(Math.abs(maxStrike - atmf), Math.abs(atmf - minStrike)) *
            10000,
        )
      : null;
  if (widthFromStrikes !== null) return widthFromStrikes;

  const widthFromMetrics = parseMetricNumber(metrics.rr_out_strike);
  return widthFromMetrics !== null ? Math.round(widthFromMetrics) : null;
}

function buildRichLabel(row: TapeRow): string {
  const legs = row.legs_json || [];
  const pkgType = (row.package_type || "").toUpperCase();
  const metrics = row.package_metrics || {};
  const underlying = extractUnderlyingBase(legs[0]?.trade_label, row);
  const firstLeg = legs[0] || {};
  const legMetrics = firstLeg.leg_metrics || {};
  const style = STRADDLE_STYLE;

  // OUTRIGHT
  if (!pkgType || pkgType === "OUTRIGHT") {
    const direction = firstLeg.product_type
      ?.toString()
      .toUpperCase()
      .includes("PAYER")
      ? "PAYER"
      : "RECEIVER";
    const offsetRaw = legMetrics.outright_strike_offset_rounded_bps;
    if (isValid(offsetRaw)) {
      let offset = Number(offsetRaw);
      const money = legMetrics.outright_moneyness;
      if (money === "OTM_RECEIVER" || money === "ITM_PAYER")
        offset = -Math.abs(offset);
      if (money === "OTM_PAYER" || money === "ITM_RECEIVER")
        offset = Math.abs(offset);
      return `${underlying} ${direction} ${formatStrikeOffset(offset)}`;
    }
    const strikePct = formatStrikeAbsolute(firstLeg.strike);
    return `${underlying} ${direction} @ ${strikePct}`;
  }

  // STRADDLE
  if (pkgType === "STRADDLE") {
    const cleanUnderlying = removeTrailingStyle(underlying, style);
    return `${cleanUnderlying} ${style} STRADDLE`;
  }

  // RISK REVERSAL
  if (pkgType === "RISK_REVERSAL") {
    const strikes = legs
      .map((leg) => parseMetricNumber(leg.strike))
      .filter((strike): strike is number => strike !== null)
      .sort((a, b) => a - b);
    const width = resolveRiskReversalWidthBps(strikes, metrics);
    if (width !== null) {
      return `${underlying} ${width}bp RR`;
    }
    if (strikes.length >= 3) {
      const strikeStr = strikes.map((s) => formatStrikeAbsolute(s)).join("/");
      return `${underlying} ${strikeStr} RR`;
    }
    return `${underlying} RR`;
  }

  // CUSTY STRANGLE / RR STRANGLE
  if (pkgType === "CUSTY_RR_STRANGLE") {
    const width = isValid(metrics.custy_rr_width_bps)
      ? `${Math.round(Number(metrics.custy_rr_width_bps))}bp`
      : null;
    const payerLeg = legs.find((l) =>
      l.product_type?.toString().toUpperCase().includes("PAYER"),
    );
    const recvLeg = legs.find((l) =>
      l.product_type?.toString().toUpperCase().includes("RECEIVER"),
    );
    if (width) {
      return `${underlying} ${width} WIDE`;
    }
    if (payerLeg && recvLeg) {
      const payerK = formatStrikeAbsolute(payerLeg.strike);
      const recvK = formatStrikeAbsolute(recvLeg.strike);
      return `${underlying} ${recvK}/${payerK} WIDE`;
    }
    return `${underlying} WIDE`;
  }

  // VERTICAL SPREADS
  if (pkgType === "VERTICAL_SPREAD_1X1" || pkgType === "VERTICAL_SPREAD_1X2") {
    const spreadType = metrics.vs_spread_type?.toString().includes("RECEIVER")
      ? "RECEIVER"
      : "PAYER";

    if (
      isValid(metrics.vs_atm_strike_offset) &&
      isValid(metrics.vs_otm_strike_offset)
    ) {
      const atm = Number(metrics.vs_atm_strike_offset);
      const otm = Number(metrics.vs_otm_strike_offset);
      const atmStr =
        spreadType === "RECEIVER"
          ? `ATMF-${Math.abs(Math.round(atm))}`
          : `ATMF+${Math.abs(Math.round(atm))}`;
      const otmStr =
        spreadType === "RECEIVER"
          ? `ATMF-${Math.abs(Math.round(otm))}`
          : `ATMF+${Math.abs(Math.round(otm))}`;
      return `${underlying} ${atmStr}/${otmStr} ${spreadType} SPREAD`;
    }

    const strikes = legs
      .map((l) => l.strike)
      .filter((s) => isValid(s))
      .map(Number)
      .sort((a, b) => a - b);
    if (strikes.length >= 2) {
      const strikeStr = strikes.map((s) => formatStrikeAbsolute(s)).join("/");
      return `${underlying} ${strikeStr} ${spreadType} SPREAD`;
    }
    return `${underlying} ${spreadType} SPREAD`;
  }

  // LADDERS
  if (pkgType === "RECEIVER_LADDER" || pkgType === "PAYER_LADDER") {
    const strikes =
      Array.isArray(metrics.ladder_strikes) && metrics.ladder_strikes.length
        ? metrics.ladder_strikes
        : legs
            .map((l) => l.strike)
            .filter((s) => isValid(s))
            .sort((a, b) => Number(a) - Number(b));

    const strikeStr =
      Array.isArray(strikes) && strikes.length
        ? strikes.map((s: any) => formatStrikeAbsolute(Number(s))).join("/")
        : "--";

    const qualifiers: string[] = [];
    if (isValid(metrics.ladder_structure))
      qualifiers.push(String(metrics.ladder_structure));
    if (isValid(metrics.ladder_direction))
      qualifiers.push(String(metrics.ladder_direction));
    qualifiers.push(pkgType.includes("PAYER") ? "PAYER" : "RECEIVER");
    qualifiers.push("LADDER");
    return `${underlying} ${strikeStr} ${qualifiers.join(" ")}`;
  }

  // Fallback
  return `${underlying} ${pkgType || ""}`.trim();
}

function LegsSubtable({
  row,
  seriesRows,
}: {
  row: TapeRow;
  seriesRows: TapeRow[];
}) {
  const searchParams = useSearchParams();
  const metrics = row.package_metrics || {};
  const packageType = normalizePackageType(row.package_type);
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const manualLinkId = row.manual_link_id;
  const manualColor = manualLinkColor(
    row.manual_link_id || row.manual_package_id,
  );
  const rowIsManual = isManualPackage(row);
  const isStraddle = packageType === "STRADDLE";
  const isOutright = !packageType || packageType === "OUTRIGHT";
  const isRiskReversal = packageType === "RISK_REVERSAL";
  const showStraddleSchema = isStraddle || isRiskReversal;
  const showOutrightSchema = isOutright;
  const showNotionalCappedColumn = showStraddleSchema || showOutrightSchema;
  const showPremiumBpsColumn = showStraddleSchema || showOutrightSchema;
  const splitFactor = isStraddle ? STRADDLE_SPLIT_FACTOR : 1;
  const [showTimeseries, setShowTimeseries] = useState(false);
  const [timeseriesView, setTimeseriesView] =
    useState<TimeseriesViewKey>("DAILY_CLOSE");
  const [timeseriesMetric, setTimeseriesMetric] =
    useState<TimeseriesMetricKey>("vega01");
  const [timeseriesRange, setTimeseriesRange] =
    useState<TimeseriesRangeKey>("1Y");
  const [customRangeStart, setCustomRangeStart] = useState("");
  const [customRangeEnd, setCustomRangeEnd] = useState("");
  const [yAxisMinInput, setYAxisMinInput] = useState("");
  const [yAxisMaxInput, setYAxisMaxInput] = useState("");
  const [showLineDots, setShowLineDots] = useState(true);
  const [showSigmaBands, setShowSigmaBands] = useState(false);
  const [timeseriesTab, setTimeseriesTab] = useState<"CHART" | "RARITY">(
    "CHART",
  );
  const [showCustySeries, setShowCustySeries] = useState(true);
  const [showIdbSeries, setShowIdbSeries] = useState(true);
  const [useGrossVega, setUseGrossVega] = useState(true);
  const [extraTimeseriesRows, setExtraTimeseriesRows] = useState<TapeRow[]>([]);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);
  const [timeseriesError, setTimeseriesError] = useState<string | null>(null);
  const [timeseriesNotice, setTimeseriesNotice] = useState<string | null>(null);
  const timeseriesFetchKeyRef = useRef<string | null>(null);
  const timeseriesFetchInFlight = useRef(false);
  const [showRawDataModal, setShowRawDataModal] = useState(false);
  const [modalPosition, setModalPosition] = useState<{ top: number } | null>(null);
  const columnFiltersParam = searchParams.get(COLUMN_FILTER_QUERY_KEY);
  const columnFilterOpParam = searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY);
  const filterParam = searchParams.get("filter");
  const seriesKey =
    packageType && packageType.length > 0
      ? buildTimeseriesSeriesKey(row, packageType)
      : null;
  const canShowTimeseries = !!seriesKey;
  const combinedSeriesRows = useMemo(() => {
    const merged = new Map<string, TapeRow>();
    seriesRows.forEach((candidate) =>
      merged.set(candidate.package_id, candidate),
    );
    extraTimeseriesRows.forEach((candidate) =>
      merged.set(candidate.package_id, candidate),
    );
    return Array.from(merged.values());
  }, [extraTimeseriesRows, seriesRows]);
  const timeseriesRows = useMemo(() => {
    if (!showTimeseries || !seriesKey || !packageType) return [];
    const candidates = Array.isArray(combinedSeriesRows)
      ? combinedSeriesRows
      : [];
    return candidates.filter((candidate) => {
      if (normalizePackageType(candidate.package_type) !== packageType) {
        return false;
      }
      const action = extractPrimaryAction(candidate);
      if (action !== "NEWT-TRAD") return false;
      if (buildTimeseriesSeriesKey(candidate, packageType) !== seriesKey) {
        return false;
      }
      return true;
    });
  }, [combinedSeriesRows, packageType, seriesKey, showTimeseries]);
  const {
    custy: custyTimeseriesData,
    idb: idbTimeseriesData,
    all: allTimeseriesData,
  } = useMemo(() => {
    const custyPoints: StraddleTimeseriesPoint[] = [];
    const idbPoints: StraddleTimeseriesPoint[] = [];
    timeseriesRows.forEach((candidate) => {
      const point = buildTimeseriesPoint(candidate, packageType);
      if (!point) return;
      const platform = resolvePlatformIdentifier(candidate);
      if (isCustyPlatform(platform)) {
        custyPoints.push(point);
      } else {
        idbPoints.push(point);
      }
    });
    custyPoints.sort((left, right) => left.timestamp - right.timestamp);
    idbPoints.sort((left, right) => left.timestamp - right.timestamp);
    const allPoints = [...custyPoints, ...idbPoints].sort(
      (left, right) => left.timestamp - right.timestamp,
    );
    return {
      custy: custyPoints,
      idb: idbPoints,
      all: allPoints,
    };
  }, [packageType, timeseriesRows]);
  const latestTimestamp = useMemo(() => {
    if (!allTimeseriesData.length) return null;
    return allTimeseriesData[allTimeseriesData.length - 1].timestamp;
  }, [allTimeseriesData]);
  const rangedCustyData = useMemo(
    () =>
      filterTimeseriesByRange(
        custyTimeseriesData,
        timeseriesRange,
        customRangeStart,
        customRangeEnd,
        latestTimestamp,
      ),
    [
      custyTimeseriesData,
      timeseriesRange,
      customRangeStart,
      customRangeEnd,
      latestTimestamp,
    ],
  );
  const rangedIdbData = useMemo(
    () =>
      filterTimeseriesByRange(
        idbTimeseriesData,
        timeseriesRange,
        customRangeStart,
        customRangeEnd,
        latestTimestamp,
      ),
    [
      idbTimeseriesData,
      timeseriesRange,
      customRangeStart,
      customRangeEnd,
      latestTimestamp,
    ],
  );
  const rangedAllData = useMemo(
    () =>
      filterTimeseriesByRange(
        allTimeseriesData,
        timeseriesRange,
        customRangeStart,
        customRangeEnd,
        latestTimestamp,
      ),
    [
      allTimeseriesData,
      timeseriesRange,
      customRangeStart,
      customRangeEnd,
      latestTimestamp,
    ],
  );
  const metricTransform = useMemo(() => {
    if (timeseriesMetric === "vega01" && useGrossVega) {
      return (value: number) => Math.abs(value);
    }
    return undefined;
  }, [timeseriesMetric, useGrossVega]);
  const custyIntraday = useMemo(
    () =>
      buildIntradaySeries(rangedCustyData, timeseriesMetric, metricTransform),
    [metricTransform, rangedCustyData, timeseriesMetric],
  );
  const idbIntraday = useMemo(
    () => buildIntradaySeries(rangedIdbData, timeseriesMetric, metricTransform),
    [metricTransform, rangedIdbData, timeseriesMetric],
  );
  const custyDailySeries = useMemo(
    () =>
      buildDailyTimeseries(rangedCustyData, timeseriesMetric, metricTransform),
    [metricTransform, rangedCustyData, timeseriesMetric],
  );
  const idbDailySeries = useMemo(
    () => buildDailyTimeseries(rangedIdbData, timeseriesMetric, metricTransform),
    [metricTransform, rangedIdbData, timeseriesMetric],
  );
  const allDailySeries = useMemo(
    () => buildDailyTimeseries(rangedAllData, timeseriesMetric, metricTransform),
    [metricTransform, rangedAllData, timeseriesMetric],
  );
  const selectedMetric =
    TIMESERIES_METRICS.find((metric) => metric.key === timeseriesMetric) ||
    TIMESERIES_METRICS[0];
  const metricLabelWithUnit =
    selectedMetric.unit &&
    !selectedMetric.label
      .toLowerCase()
      .includes(selectedMetric.unit.toLowerCase())
      ? `${selectedMetric.label} (${selectedMetric.unit})`
      : selectedMetric.label;
  const rangeLabel =
    TIMESERIES_RANGE_OPTIONS.find((option) => option.key === timeseriesRange)
      ?.label ?? timeseriesRange;
  const useDailySum =
    timeseriesView === "DAILY_CLOSE" &&
    DAILY_CLOSE_CUMULATIVE_METRICS.has(timeseriesMetric);
  const dailyValueKey = useDailySum ? "daySum" : "close";
  const showCusty = showCustySeries;
  const showIdb = showIdbSeries;
  const seriesSelectionCount = (showCusty ? 1 : 0) + (showIdb ? 1 : 0);
  const ohlcNote =
    timeseriesView === "DAILY_OHLC" && seriesSelectionCount > 1
      ? "OHLC shows combined Custy + IDB."
      : null;
  const summarySeries = useMemo(() => {
    const entries: Array<{
      key: string;
      label: string;
      tone: string;
      stats: TimeseriesSummaryStats;
    }> = [];
    if (showCusty) {
      entries.push({
        key: "custy",
        label: "Custy",
        tone: "text-amber-300",
        stats: computeTimeseriesSummary(rangedCustyData),
      });
    }
    if (showIdb) {
      entries.push({
        key: "idb",
        label: "IDB",
        tone: "text-sky-300",
        stats: computeTimeseriesSummary(rangedIdbData),
      });
    }
    if (showCusty && showIdb) {
      entries.push({
        key: "combined",
        label: "Combined",
        tone: "text-slate-200",
        stats: computeTimeseriesSummary(rangedAllData),
      });
    }
    return entries;
  }, [rangedAllData, rangedCustyData, rangedIdbData, showCusty, showIdb]);
  const mergedIntradayData = useMemo(
    () =>
      mergeIntradaySeries(
        showCusty ? custyIntraday : [],
        showIdb ? idbIntraday : [],
      ),
    [custyIntraday, idbIntraday, showCusty, showIdb],
  );
  const mergedDailyData = useMemo(
    () =>
      mergeDailySeries(
        showCusty ? custyDailySeries : [],
        showIdb ? idbDailySeries : [],
        dailyValueKey,
      ),
    [custyDailySeries, dailyValueKey, idbDailySeries, showCusty, showIdb],
  );
  const chartData =
    timeseriesView === "INTRADAY" ? mergedIntradayData : mergedDailyData;
  const ohlcSeries = useMemo(() => {
    if (seriesSelectionCount === 1) {
      return showIdb ? idbDailySeries : custyDailySeries;
    }
    return allDailySeries;
  }, [
    allDailySeries,
    custyDailySeries,
    idbDailySeries,
    seriesSelectionCount,
    showIdb,
  ]);
  const chartValues = useMemo(() => {
    if (timeseriesView === "DAILY_OHLC") {
      return ohlcSeries
        .flatMap((point) => [point.open, point.high, point.low, point.close])
        .filter((value) => !Number.isNaN(value));
    }
    return chartData
      .flatMap((point) => [point.custyValue, point.idbValue])
      .filter((value): value is number => isValid(value));
  }, [chartData, ohlcSeries, timeseriesView]);
  const currentTimeseriesPoint = useMemo(
    () => (packageType ? buildTimeseriesPoint(row, packageType) : null),
    [packageType, row],
  );
  const currentMetricValue = useMemo(() => {
    if (!currentTimeseriesPoint) return null;
    return resolveTimeseriesMetricValue(
      currentTimeseriesPoint,
      timeseriesMetric,
      metricTransform,
    );
  }, [currentTimeseriesPoint, metricTransform, timeseriesMetric]);
  const timeseriesDistributionValues = useMemo(
    () =>
      rangedAllData
        .map((point) =>
          resolveTimeseriesMetricValue(point, timeseriesMetric, metricTransform),
        )
        .filter((value): value is number => isValid(value)),
    [metricTransform, rangedAllData, timeseriesMetric],
  );
  const currentTimeLabel = currentTimeseriesPoint?.timeLabel ?? null;
  const currentTimestamp = currentTimeseriesPoint?.timestamp ?? null;
  const rangeMinTimestamp = rangedAllData.length
    ? rangedAllData[0].timestamp
    : null;
  const rangeMaxTimestamp = rangedAllData.length
    ? rangedAllData[rangedAllData.length - 1].timestamp
    : null;
  const showHighlight =
    currentTimestamp !== null &&
    rangeMinTimestamp !== null &&
    rangeMaxTimestamp !== null &&
    currentTimestamp >= rangeMinTimestamp &&
    currentTimestamp <= rangeMaxTimestamp;
  const metricFormatter = useCallback(
    (value: number) =>
      formatTimeseriesMetric(timeseriesMetric, value, selectedMetric.decimals),
    [selectedMetric.decimals, timeseriesMetric],
  );
  const metricFormatterWithUnit = useCallback(
    (value: number) => {
      const formatted = metricFormatter(value);
      if (!selectedMetric.unit || formatted === "--") return formatted;
      return `${formatted} ${selectedMetric.unit}`;
    },
    [metricFormatter, selectedMetric.unit],
  );
  const rarityFormatters = useMemo(
    () => ({
      formatNotional,
      formatMetricValue,
      formatRate,
      formatCount,
      formatDurationMs,
    }),
    [],
  );
  const custyExtremes = useMemo(
    () =>
      findTimeseriesExtremes(
        custyTimeseriesData,
        timeseriesMetric,
        metricTransform,
      ),
    [custyTimeseriesData, metricTransform, timeseriesMetric],
  );
  const idbExtremes = useMemo(
    () =>
      findTimeseriesExtremes(
        idbTimeseriesData,
        timeseriesMetric,
        metricTransform,
      ),
    [idbTimeseriesData, metricTransform, timeseriesMetric],
  );
  const renderOhlcTooltip = useCallback(
    ({ active, payload }: any) => {
      if (!active || !payload || !payload.length) return null;
      const point = payload[0]?.payload as DailyTimeseriesPoint | undefined;
      if (!point) return null;
      return (
        <div className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200">
          <div className="font-semibold text-slate-100">{point.timeLabel}</div>
          <div className="flex items-center justify-between gap-3">
            <span>Open</span>
            <span className="font-mono">
              {metricFormatterWithUnit(point.open)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>High</span>
            <span className="font-mono">
              {metricFormatterWithUnit(point.high)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Low</span>
            <span className="font-mono">
              {metricFormatterWithUnit(point.low)}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Close</span>
            <span className="font-mono">
              {metricFormatterWithUnit(point.close)}
            </span>
          </div>
        </div>
      );
    },
    [metricFormatterWithUnit],
  );
  const includeZeroInDomain =
    (timeseriesView === "INTRADAY" && selectedMetric.chartType === "bar") ||
    (timeseriesView === "DAILY_CLOSE" && useDailySum);
  const yDomain = useMemo(() => {
    const autoDomain = buildTimeseriesDomain(chartValues, includeZeroInDomain);
    const manualMin = parseAxisInput(yAxisMinInput);
    const manualMax = parseAxisInput(yAxisMaxInput);
    if (manualMin === null && manualMax === null) {
      return autoDomain;
    }
    return [
      manualMin ?? autoDomain?.[0] ?? "auto",
      manualMax ?? autoDomain?.[1] ?? "auto",
    ] as [number | string, number | string];
  }, [
    chartValues,
    includeZeroInDomain,
    yAxisMaxInput,
    yAxisMinInput,
  ]);
  const hasSeriesSelection = showCusty || showIdb;
  const hasChartData =
    hasSeriesSelection &&
    (timeseriesView === "DAILY_OHLC"
      ? ohlcSeries.length > 0
      : chartData.length > 0);
  const isLineChartView =
    (timeseriesView === "DAILY_CLOSE" && !useDailySum) ||
    (timeseriesView === "INTRADAY" && selectedMetric.chartType === "line");
  const isOhlcView = timeseriesView === "DAILY_OHLC";
  const timeseriesFetchKey = useMemo(
    () => `${seriesKey ?? ""}|${packageType ?? ""}`,
    [packageType, seriesKey],
  );

  useEffect(() => {
    setExtraTimeseriesRows([]);
    setTimeseriesError(null);
    setTimeseriesNotice(null);
    timeseriesFetchKeyRef.current = null;
  }, [packageType, seriesKey]);

  useEffect(() => {
    if (!showTimeseries) return;
    setTimeseriesTab("CHART");
  }, [packageType, seriesKey, showTimeseries]);

  useEffect(() => {
    if (!showTimeseries || !packageType || !seriesKey) return;
    if (
      timeseriesRange !== "ALL" &&
      timeseriesRange !== "CUSTOM" &&
      timeseriesRange !== "1Y"
    ) {
      return;
    }
    if (timeseriesFetchInFlight.current) return;
    if (timeseriesFetchKeyRef.current === timeseriesFetchKey) return;

    let cancelled = false;
    const fetchTimeseriesRows = async () => {
      timeseriesFetchInFlight.current = true;
      setTimeseriesLoading(true);
      setTimeseriesError(null);
      setTimeseriesNotice(null);

      try {
        const params = new URLSearchParams();
        params.set("seriesKey", seriesKey);
        params.set("packageType", packageType);

        const res = await fetch(
          `/api/swaptions-tape/timeseries?${params.toString()}`,
        );
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || "Failed to load timeseries data");
        }

        const data: { rows: TapeRow[]; count: number; truncated: boolean } = await res.json();

        // Client-side filtering to ensure exact match
        const collected = new Map<string, TapeRow>();
        data.rows.forEach((rowItem) => {
          if (normalizePackageType(rowItem.package_type) !== packageType) {
            return;
          }
          const action = extractPrimaryAction(rowItem);
          if (action !== "NEWT-TRAD") return;
          if (buildTimeseriesSeriesKey(rowItem, packageType) !== seriesKey) {
            return;
          }
          collected.set(rowItem.package_id, rowItem);
        });

        if (cancelled) return;
        setExtraTimeseriesRows(Array.from(collected.values()));
        timeseriesFetchKeyRef.current = timeseriesFetchKey;

        if (data.truncated) {
          setTimeseriesNotice(
            `Timeseries data was truncated at ${TIMESERIES_MAX_ROWS} rows; showing partial history.`
          );
        }
      } catch (error: any) {
        if (!cancelled) {
          setTimeseriesError(
            error?.message || "Failed to load timeseries data",
          );
        }
      } finally {
        timeseriesFetchInFlight.current = false;
        if (!cancelled) {
          setTimeseriesLoading(false);
        }
      }
    };

    fetchTimeseriesRows();

    return () => {
      cancelled = true;
    };
  }, [
    packageType,
    seriesKey,
    showTimeseries,
    timeseriesFetchKey,
    timeseriesRange,
  ]);
  const isLadder =
    packageType === "RECEIVER_LADDER" || packageType === "PAYER_LADDER";
  const orderedLegs = [...legs].sort((leftLeg, rightLeg) => {
    if (isValid(leftLeg.leg_order) && isValid(rightLeg.leg_order)) {
      return Number(leftLeg.leg_order) - Number(rightLeg.leg_order);
    }
    if (isValid(leftLeg.leg_order)) return -1;
    if (isValid(rightLeg.leg_order)) return 1;
    return 0;
  });
  const riskReversalStrikeExtremes = isRiskReversal
    ? orderedLegs
        .map((leg) => (isValid(leg.strike) ? Number(leg.strike) : null))
        .filter((strike): strike is number => strike !== null)
    : [];
  const rrMaxStrike = riskReversalStrikeExtremes.length
    ? Math.max(...riskReversalStrikeExtremes)
    : null;
  const rrMinStrike = riskReversalStrikeExtremes.length
    ? Math.min(...riskReversalStrikeExtremes)
    : null;
  const normalizedLegs = isRiskReversal
    ? orderedLegs.map((leg) => {
        if (
          rrMaxStrike !== null &&
          strikeMatches(leg.strike ?? null, rrMaxStrike)
        ) {
          return { ...leg, product_type: "SWAPTION_PAYER" };
        }
        if (
          rrMinStrike !== null &&
          strikeMatches(leg.strike ?? null, rrMinStrike)
        ) {
          return { ...leg, product_type: "SWAPTION_RECEIVER" };
        }
        return leg;
      })
    : orderedLegs;
  const [ladderStrikeKey, ladderNotionalKey] =
    METRIC_SCHEMA.RECEIVER_LADDER.cols;
  const payerSkewValue = isRiskReversal
    ? parseMetricNumber(metrics.rr_payer_skew)
    : null;
  const receiverSkewValue = isRiskReversal
    ? parseMetricNumber(metrics.rr_receiver_skew)
    : null;

  const resolveNotionalCapped = (leg: TapeLeg) => {
    const cappedValue =
      leg.leg_metrics?.is_notional_capped ??
      leg.is_notional_capped ??
      row.is_notional_capped ??
      metrics.is_notional_capped ??
      metrics.straddle_is_notional_capped;
    if (!isValid(cappedValue)) return "False";
    if (typeof cappedValue === "boolean") return cappedValue ? "True" : "False";
    if (typeof cappedValue === "number") return cappedValue ? "True" : "False";
    const normalized = String(cappedValue).trim().toLowerCase();
    if (["true", "yes", "y", "1", "t"].includes(normalized)) return "True";
    if (["false", "no", "n", "0", "f"].includes(normalized)) return "False";
    return normalized ? "True" : "False";
  };

  const adjustSplitValue = (value: number | null) =>
    value === null ? null : value * splitFactor;

  const resolveStraddleSide = (leg: TapeLeg) => {
    const side = String(leg.product_type ?? "").toUpperCase();
    if (side.includes("RECEIVER")) return "RECEIVER";
    if (side.includes("PAYER")) return "PAYER";
    return null;
  };

  const applyStraddleSign = (value: number | null, sign: 1 | -1) => {
    if (value === null) return null;
    return sign * Math.abs(value);
  };

  const applyStraddleGreeks = (
    leg: TapeLeg,
    values: {
      dv01: number | null;
      vega01: number | null;
      gamma01: number | null;
      theta01: number | null;
    },
  ) => {
    if (!isStraddle) return values;
    const side = resolveStraddleSide(leg);
    if (!side) return values;
    const dv01Sign = side === "PAYER" ? -1 : 1;
    return {
      dv01: applyStraddleSign(values.dv01, dv01Sign),
      vega01: applyStraddleSign(values.vega01, 1),
      gamma01: applyStraddleSign(values.gamma01, 1),
      theta01: applyStraddleSign(values.theta01, -1),
    };
  };

  const accumulateValue = (current: number | null, value: number | null) => {
    if (value === null) return current;
    if (current === null) return value;
    return current + value;
  };

  const computeLegValues = (leg: TapeLeg, legIndex: number) => {
    const legNumber = isValid(leg.leg_order)
      ? Number(leg.leg_order)
      : legIndex + 1;
    const ladderIndex = isLadder
      ? resolveLadderLegIndex(leg, metrics, legIndex)
      : null;
    const strikeValue = isLadder
      ? resolveLadderValue(metrics, ladderStrikeKey, ladderIndex, leg.strike)
      : isValid(leg.strike)
        ? Number(leg.strike)
        : null;
    const notionalValue = isLadder
      ? resolveLadderValue(
          metrics,
          ladderNotionalKey,
          ladderIndex,
          leg.notional,
        )
      : isValid(leg.notional)
        ? Number(leg.notional)
        : null;
    const legMetrics = selectLegMetrics({
      leg,
      metrics,
      packageType,
      legs: normalizedLegs,
      legIndex,
    });
    const premiumValue = adjustSplitValue(
      isValid(leg.premium) ? Number(leg.premium) : null,
    );
    const premiumBpsValue =
      premiumValue !== null &&
      isValid(notionalValue) &&
      Number(notionalValue) !== 0
        ? (premiumValue / Number(notionalValue)) * 10_000
        : null;
    let bpvolValue = isValid(legMetrics.bpvol)
      ? Number(legMetrics.bpvol)
      : null;
    if (
      isRiskReversal &&
      bpvolValue !== null &&
      isValid(strikeValue) &&
      rrMaxStrike !== null &&
      rrMinStrike !== null
    ) {
      if (strikeMatches(strikeValue, rrMaxStrike) && payerSkewValue !== null) {
        bpvolValue += payerSkewValue;
      } else if (
        strikeMatches(strikeValue, rrMinStrike) &&
        receiverSkewValue !== null
      ) {
        bpvolValue += receiverSkewValue;
      }
    }
    const bpvolDayValue =
      bpvolValue !== null ? bpvolValue / BPVOL_DAY_DIVISOR : null;
    const greekValues = applyStraddleGreeks(leg, {
      dv01: adjustSplitValue(legMetrics.dv01),
      vega01: adjustSplitValue(legMetrics.vega01),
      gamma01: adjustSplitValue(legMetrics.gamma01),
      theta01: adjustSplitValue(legMetrics.theta01),
    });

    return {
      legNumber,
      strikeValue,
      notionalValue,
      premiumValue,
      premiumBpsValue,
      bpvolValue,
      bpvolDayValue,
      dv01Value: greekValues.dv01,
      vega01Value: greekValues.vega01,
      gamma01Value: greekValues.gamma01,
      theta01Value: greekValues.theta01,
    };
  };

  const riskReversalTotals = isRiskReversal
    ? (() => {
        const highLegIndex =
          rrMaxStrike !== null
            ? normalizedLegs.findIndex((leg) =>
                strikeMatches(leg.strike ?? null, rrMaxStrike),
              )
            : -1;
        const lowLegIndex =
          rrMinStrike !== null
            ? normalizedLegs.findIndex((leg) =>
                strikeMatches(leg.strike ?? null, rrMinStrike),
              )
            : -1;
        const middleLegs = normalizedLegs
          .map((leg, index) => ({ leg, index }))
          .filter(
            ({ leg }) =>
              !strikeMatches(leg.strike ?? null, rrMaxStrike) &&
              !strikeMatches(leg.strike ?? null, rrMinStrike),
          );
        const middlePayer = middleLegs.find(({ leg }) =>
          String(leg.product_type ?? "").toUpperCase().includes("PAYER"),
        );
        const middleReceiver = middleLegs.find(({ leg }) =>
          String(leg.product_type ?? "").toUpperCase().includes("RECEIVER"),
        );

        const highLeg =
          highLegIndex >= 0 ? normalizedLegs[highLegIndex] : null;
        const lowLeg = lowLegIndex >= 0 ? normalizedLegs[lowLegIndex] : null;
        const highValues =
          highLeg && highLegIndex >= 0
            ? computeLegValues(highLeg, highLegIndex)
            : null;
        const lowValues =
          lowLeg && lowLegIndex >= 0
            ? computeLegValues(lowLeg, lowLegIndex)
            : null;
        const middlePayerValues = middlePayer
          ? computeLegValues(middlePayer.leg, middlePayer.index)
          : null;
        const highPremium = isValid(highLeg?.premium)
          ? Number(highLeg?.premium)
          : null;
        const lowPremium = isValid(lowLeg?.premium)
          ? Number(lowLeg?.premium)
          : null;
        const middlePayerPremium = isValid(middlePayer?.leg.premium)
          ? Number(middlePayer?.leg.premium)
          : null;
        const middleReceiverPremium = isValid(middleReceiver?.leg.premium)
          ? Number(middleReceiver?.leg.premium)
          : null;

        const totalPremium =
          highPremium !== null && lowPremium !== null
            ? highPremium -
              lowPremium +
              (middleReceiverPremium ?? 0) +
              (middlePayerPremium ?? 0)
            : null;

        const totalBpvolYr =
          parseMetricNumber(metrics.rr_skew_bpvol) ??
          ((highValues?.bpvolValue ?? null) !== null &&
          (lowValues?.bpvolValue ?? null) !== null
            ? (highValues?.bpvolValue ?? 0) - (lowValues?.bpvolValue ?? 0)
            : null);
        const totalBpvolDay =
          totalBpvolYr !== null
            ? totalBpvolYr / BPVOL_DAY_DIVISOR
            : (highValues?.bpvolDayValue ?? null) !== null &&
                (lowValues?.bpvolDayValue ?? null) !== null
              ? (highValues?.bpvolDayValue ?? 0) -
                (lowValues?.bpvolDayValue ?? 0)
              : null;

        const totalDv01 = parseMetricNumber(metrics.rr_dv01);
        const totalWingDv01 = parseMetricNumber(metrics.rr_wing_dv01);
        const totalVega01 = parseMetricNumber(metrics.rr_vega01);
        const totalGamma01 = parseMetricNumber(metrics.rr_gamma01);
        const totalTheta01 = parseMetricNumber(metrics.rr_theta1d);

        const wingNotional = highValues?.notionalValue ?? null;
        const middlePayerNotional = middlePayerValues?.notionalValue ?? null;
        const wingToDeltaRatio =
          wingNotional !== null &&
          middlePayerNotional !== null &&
          middlePayerNotional !== 0
            ? wingNotional / middlePayerNotional
            : null;

        return {
          totalPremium,
          totalBpvolYr,
          totalBpvolDay,
          totalDv01,
          totalWingDv01,
          totalVega01,
          totalGamma01,
          totalTheta01,
          wingToDeltaRatio,
        };
      })()
    : null;

  const straddleTotals = isStraddle
    ? orderedLegs.reduce(
        (totals, leg, legIndex) => {
          const values = computeLegValues(leg, legIndex);
          return {
            premium: accumulateValue(totals.premium, values.premiumValue),
            premiumBps: accumulateValue(
              totals.premiumBps,
              values.premiumBpsValue,
            ),
            dv01: accumulateValue(totals.dv01, values.dv01Value),
            vega01: accumulateValue(totals.vega01, values.vega01Value),
            gamma01: accumulateValue(totals.gamma01, values.gamma01Value),
            theta01: accumulateValue(totals.theta01, values.theta01Value),
          };
        },
        {
          premium: null,
          premiumBps: null,
          dv01: null,
          vega01: null,
          gamma01: null,
          theta01: null,
        } as {
          premium: number | null;
          premiumBps: number | null;
          dv01: number | null;
          vega01: number | null;
          gamma01: number | null;
          theta01: number | null;
        },
      )
    : null;

  if (!normalizedLegs.length) {
    return (
      <div className="px-2 py-1 text-xs text-slate-400">
        No legs available.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-2 px-2">
        {canShowTimeseries && (
          <button
            type="button"
            onClick={() => setShowTimeseries((current) => !current)}
            className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-slate-800"
          >
            {showTimeseries ? "Hide Timeseries" : "Show Timeseries"}
          </button>
        )}
        <button
          type="button"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            // Position modal near the top of viewport, aligned with the row
            const topPosition = window.scrollY + Math.max(100, rect.top - 50);
            setModalPosition({
              top: topPosition,
            });
            setShowRawDataModal(true);
          }}
          className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-slate-800"
        >
          Show Raw Data
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
        <thead className="bg-slate-950/40 text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-2 py-1 text-left">Leg</th>
            <th className="px-2 py-1 text-left">Side</th>
            <th className="px-2 py-1 text-right">Strike</th>
            <th className="px-0.5 py-1 text-right">Notional</th>
            {showNotionalCappedColumn && (
              <th className="px-0.5 py-1 text-right">Notional Capped</th>
            )}
            <th className="px-2 py-1 text-right">Premium</th>
            {showPremiumBpsColumn && (
              <th className="px-2 py-1 text-right">Premium (bps)</th>
            )}
            <th className="px-2 py-1 text-right">BPVol/Yr</th>
            <th className="px-2 py-1 text-right">BPVol/day</th>
            <th className="px-2 py-1 text-right">DV01</th>
            <th className="px-2 py-1 text-right">Vega01</th>
            <th className="px-2 py-1 text-right">Gamma01</th>
            {showStraddleSchema && (
              <th className="py-1 pl-2 pr-4 text-right">Theta1D</th>
            )}
          </tr>
        </thead>
        <tbody className="text-slate-100">
          {normalizedLegs.map((leg, legIndex) => {
            const values = computeLegValues(leg, legIndex);
            const legKey =
              leg.trade_id || `${row.package_id}-leg-${legIndex}`;
            const isLegManual =
              rowIsManual ||
              normalizeManualFlag(leg.is_manually_linked) ||
              (!!manualLinkId && leg.manual_link_id === manualLinkId);

            return (
              <tr key={legKey} className="odd:bg-slate-900/40">
                <td className="px-2 py-1 font-mono text-slate-100">
                  <div className="flex items-center gap-1">
                    {isLegManual && (
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: manualColor || "#64748b" }}
                      />
                    )}
                    #{values.legNumber}
                  </div>
                </td>
                <td className="px-2 py-1 text-slate-300">
                  {leg.product_type
                    ? String(leg.product_type).toUpperCase()
                    : "--"}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatStrikeAbsolute(values.strikeValue)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatNotional(values.notionalValue)}
                </td>
                {showNotionalCappedColumn && (
                  <td className="px-1 py-1 text-right font-mono">
                    {resolveNotionalCapped(leg)}
                  </td>
                )}
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.premiumValue, 3)}
                </td>
                {showPremiumBpsColumn && (
                  <td className="px-1 py-1 text-right font-mono">
                    {formatMetricValue(values.premiumBpsValue, 3)}
                  </td>
                )}
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.bpvolValue, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.bpvolDayValue, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.dv01Value, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.vega01Value, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.gamma01Value, 3)}
                </td>
                {showStraddleSchema && (
                  <td className="py-1 pl-1 pr-4 text-right font-mono">
                    {formatMetricValue(values.theta01Value, 3)}
                  </td>
                )}
              </tr>
            );
          })}
          {isRiskReversal && riskReversalTotals && (
            <tr className="bg-slate-950/60 font-semibold">
              <td className="px-2 py-1 font-mono text-slate-200">Total</td>
              <td className="px-2 py-1 text-slate-400">--</td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              {showStraddleSchema && (
                <td className="px-1 py-1 text-right font-mono text-slate-400">
                  --
                </td>
              )}
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalPremium, 3)}
              </td>
              {showStraddleSchema && (
                <td className="px-1 py-1 text-right font-mono text-slate-400">
                  --
                </td>
              )}
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalBpvolYr, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalBpvolDay, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                <div className="flex flex-col items-end leading-tight">
                  <span>
                    {formatMetricValue(riskReversalTotals.totalDv01, 3)}
                  </span>
                  {isValid(riskReversalTotals.totalWingDv01) && (
                    <span className="text-slate-300">
                      Wing{" "}
                      {formatMetricValue(riskReversalTotals.totalWingDv01, 3)}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalVega01, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalGamma01, 3)}
              </td>
              {showStraddleSchema && (
                <td className="py-1 pl-1 pr-4 text-right font-mono">
                  {formatMetricValue(riskReversalTotals.totalTheta01, 3)}
                </td>
              )}
            </tr>
          )}
          {isStraddle && (
            <tr className="bg-slate-950/60 font-semibold">
              <td className="px-2 py-1 font-mono text-slate-200">Total</td>
              <td className="px-2 py-1 text-slate-400">--</td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.premium, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.premiumBps, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.dv01, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.vega01, 3)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.gamma01, 3)}
              </td>
              <td className="py-1 pl-1 pr-4 text-right font-mono">
                {formatMetricValue(straddleTotals?.theta01, 3)}
              </td>
            </tr>
          )}
        </tbody>
        </table>
      </div>
      {isRiskReversal && (
        <div className="flex flex-wrap gap-4 text-[11px] text-slate-300">
          <span className="font-mono">
            Payer Skew: {formatMetricDisplay(payerSkewValue, 3)}
          </span>
          <span className="font-mono">
            Receiver Skew: {formatMetricDisplay(receiverSkewValue, 3)}
          </span>
          <span className="font-mono">
            Wing-to-Delta Notional Ratio:{" "}
            {formatMetricDisplay(riskReversalTotals?.wingToDeltaRatio, 3)}
          </span>
        </div>
      )}
      {canShowTimeseries && showTimeseries && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 text-[11px] uppercase tracking-wide text-slate-400">
              <span className="block truncate">{seriesKey}</span>
              <span className="block truncate text-[10px] text-slate-500 normal-case">
                {timeseriesTab === "CHART"
                  ? `${metricLabelWithUnit} - ${rangeLabel}`
                  : "Trade Rarity"}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex overflow-hidden rounded border border-slate-700">
                <button
                  type="button"
                  onClick={() => setTimeseriesTab("CHART")}
                  className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    timeseriesTab === "CHART"
                      ? "bg-slate-700 text-slate-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  Timeseries
                </button>
                <button
                  type="button"
                  onClick={() => setTimeseriesTab("RARITY")}
                  className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    timeseriesTab === "RARITY"
                      ? "bg-slate-700 text-slate-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  Trade Rarity
                </button>
              </div>
              {timeseriesTab === "CHART" && (
                <>
                  <div className="inline-flex overflow-hidden rounded border border-slate-700">
                <button
                  type="button"
                  onClick={() =>
                    setShowCustySeries((current) => !current)
                  }
                  className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    showCustySeries
                      ? "bg-amber-500/20 text-amber-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  Custy
                </button>
                <button
                  type="button"
                  onClick={() => setShowIdbSeries((current) => !current)}
                  className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    showIdbSeries
                      ? "bg-sky-500/20 text-sky-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  IDB
                </button>
              </div>
              {timeseriesMetric === "vega01" && (
                <button
                  type="button"
                  onClick={() => setUseGrossVega((current) => !current)}
                  className={`rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    useGrossVega
                      ? "bg-emerald-500/20 text-emerald-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  {useGrossVega ? "Gross Vega" : "Net Vega"}
                </button>
              )}
              {isLineChartView && (
                <button
                  type="button"
                  onClick={() => setShowLineDots((current) => !current)}
                  className={`rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                    !showLineDots
                      ? "bg-slate-700 text-slate-100"
                      : "text-slate-300 hover:bg-slate-800"
                  }`}
                >
                  No Dots
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowSigmaBands((current) => !current)}
                className={`rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  showSigmaBands
                    ? "bg-cyan-500/20 text-cyan-100"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                Sigma Bands
              </button>
              <div className="inline-flex overflow-hidden rounded border border-slate-700">
                {TIMESERIES_VIEW_OPTIONS.map((option) => {
                  const isActive = option.key === timeseriesView;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setTimeseriesView(option.key)}
                      className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                        isActive
                          ? "bg-slate-700 text-slate-100"
                          : "text-slate-300 hover:bg-slate-800"
                      }`}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex overflow-hidden rounded border border-slate-700">
                {TIMESERIES_RANGE_OPTIONS.map((option) => {
                  const isActive = option.key === timeseriesRange;
                  return (
                    <button
                      key={option.key}
                      type="button"
                      onClick={() => setTimeseriesRange(option.key)}
                      className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                        isActive
                          ? "bg-slate-700 text-slate-100"
                          : "text-slate-300 hover:bg-slate-800"
                      }`}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex overflow-hidden rounded border border-slate-700">
                {TIMESERIES_METRICS.map((metric) => {
                  const isActive = metric.key === timeseriesMetric;
                  return (
                    <button
                      key={metric.key}
                      type="button"
                      onClick={() => setTimeseriesMetric(metric.key)}
                      className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                        isActive
                          ? "bg-slate-700 text-slate-100"
                          : "text-slate-300 hover:bg-slate-800"
                      }`}
                    >
                      {metric.label}
                    </button>
                  );
                })}
              </div>
                </>
              )}
            </div>
          </div>
          {timeseriesTab === "CHART" && (
            <>
          {timeseriesRange === "CUSTOM" && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
              <label className="flex items-center gap-2">
                <span className="uppercase tracking-wide">From</span>
                <input
                  type="date"
                  value={customRangeStart}
                  onChange={(event) => setCustomRangeStart(event.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                />
              </label>
              <label className="flex items-center gap-2">
                <span className="uppercase tracking-wide">To</span>
                <input
                  type="date"
                  value={customRangeEnd}
                  onChange={(event) => setCustomRangeEnd(event.target.value)}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                />
              </label>
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <label className="flex items-center gap-2">
              <span className="uppercase tracking-wide">Y Min</span>
              <input
                type="number"
                step="any"
                value={yAxisMinInput}
                onChange={(event) => setYAxisMinInput(event.target.value)}
                className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                placeholder="auto"
              />
            </label>
            <label className="flex items-center gap-2">
              <span className="uppercase tracking-wide">Y Max</span>
              <input
                type="number"
                step="any"
                value={yAxisMaxInput}
                onChange={(event) => setYAxisMaxInput(event.target.value)}
                className="w-24 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-200"
                placeholder="auto"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setYAxisMinInput("");
                setYAxisMaxInput("");
              }}
              className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-slate-800"
            >
              Auto
            </button>
          </div>
          {summarySeries.length > 0 && (
            <div className="mt-3 grid gap-2 lg:grid-cols-4">
              {summarySeries.map((entry) => {
                const stats = entry.stats;
                return (
                  <div
                    key={entry.key}
                    className="rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300"
                  >
                    <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-400">
                      <span className={`font-semibold ${entry.tone}`}>
                        {entry.label}
                      </span>
                      <span className="font-mono text-slate-200">
                        {formatCount(stats.tradeCount)} trades
                      </span>
                    </div>
                    <div className="mt-2 grid gap-1.5 text-[11px]">
                      <div className="flex items-center justify-between gap-3 border-b border-slate-800/60 pb-1">
                        <span className="text-slate-400">Trades/active day</span>
                        <span className="font-mono text-slate-100">
                          {formatRate(stats.tradesPerDay, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3 border-b border-slate-800/60 pb-1">
                        <span className="text-slate-400">Avg gap</span>
                        <span className="font-mono text-slate-100">
                          {formatDurationMs(stats.avgGapMs)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Avg notional</span>
                        <span className="font-mono text-slate-100">
                          {formatNotional(stats.avgNotional)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Median notional</span>
                        <span className="font-mono text-slate-100">
                          {formatNotional(stats.medianNotional)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Avg vega</span>
                        <span className="font-mono text-slate-100">
                          {formatMetricValue(stats.avgVega01, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Median vega</span>
                        <span className="font-mono text-slate-100">
                          {formatMetricValue(stats.medianVega01, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3 border-t border-slate-800/60 pt-1">
                        <span className="text-slate-400">Total notional</span>
                        <span className="font-mono text-slate-100">
                          {formatNotional(stats.totalNotional)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Total premium</span>
                        <span className="font-mono text-slate-100">
                          {formatMetricValue(stats.totalPremium, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Avg premium</span>
                        <span className="font-mono text-slate-100">
                          {formatMetricValue(stats.avgPremium, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Median premium</span>
                        <span className="font-mono text-slate-100">
                          {formatMetricValue(stats.medianPremium, 2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-slate-400">Active days</span>
                        <span className="font-mono text-slate-100">
                          {formatCount(stats.activeDays)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
              {summarySeries.length > 1 && (
                <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-[11px] text-slate-300">
                  <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-400">
                    <span className="font-semibold text-slate-200">
                      Premium Split
                    </span>
                    <span className="font-mono text-slate-200">
                      {formatMetricValue(
                        (summarySeries.find((s) => s.key === "combined")?.stats
                          .totalPremium ?? 0) || null,
                        2,
                      )}
                    </span>
                  </div>
                  <div className="mt-2 grid gap-1.5 text-[11px]">
                    {(() => {
                      const custy = summarySeries.find(
                        (s) => s.key === "custy",
                      )?.stats;
                      const idb = summarySeries.find(
                        (s) => s.key === "idb",
                      )?.stats;
                      const custyPremium = custy?.totalPremium ?? null;
                      const idbPremium = idb?.totalPremium ?? null;
                      const combined =
                        (custyPremium ?? 0) + (idbPremium ?? 0);
                      const custyShare =
                        combined > 0 && custyPremium !== null
                          ? (custyPremium / combined) * 100
                          : null;
                      const idbShare =
                        combined > 0 && idbPremium !== null
                          ? (idbPremium / combined) * 100
                          : null;
                      const ratio =
                        custyPremium !== null &&
                        idbPremium !== null &&
                        idbPremium !== 0
                          ? custyPremium / idbPremium
                          : null;
                      return (
                        <>
                          <div className="flex items-center justify-between gap-3 border-b border-slate-800/60 pb-1">
                            <span className="text-amber-300">Custy total</span>
                            <span className="font-mono text-slate-100">
                              {formatMetricValue(custyPremium, 2)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-3 border-b border-slate-800/60 pb-1">
                            <span className="text-sky-300">IDB total</span>
                            <span className="font-mono text-slate-100">
                              {formatMetricValue(idbPremium, 2)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-slate-400">
                              Custy/IDB ratio
                            </span>
                            <span className="font-mono text-slate-100">
                              {formatRate(ratio, 2)}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-slate-400">Custy share</span>
                            <span className="font-mono text-slate-100">
                              {formatRate(custyShare, 1)}%
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-slate-400">IDB share</span>
                            <span className="font-mono text-slate-100">
                              {formatRate(idbShare, 1)}%
                            </span>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </div>
              )}
            </div>
          )}
          {hasChartData ? (
            <div className="mt-3 h-56 md:h-64 lg:h-72">
              <ResponsiveContainer width="100%" height="100%">
                {isOhlcView ? (
                  <ComposedChart data={ohlcSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis
                      dataKey="timeLabel"
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      minTickGap={20}
                    />
                    <YAxis
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      tickFormatter={metricFormatter}
                      domain={yDomain ?? ["auto", "auto"]}
                      allowDataOverflow
                      label={{
                        value: metricLabelWithUnit,
                        angle: -90,
                        position: "insideLeft",
                        fill: "#94a3b8",
                        fontSize: 10,
                      }}
                    />
                    <TimeseriesAnnotations
                      distributionValues={timeseriesDistributionValues}
                      currentValue={currentMetricValue}
                      currentTimeLabel={currentTimeLabel}
                      showSigmaBands={showSigmaBands}
                      formatValue={metricFormatterWithUnit}
                      showHighlight={showHighlight}
                    />
                    <Tooltip
                      content={renderOhlcTooltip}
                      labelStyle={{ color: "#e2e8f0" }}
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        border: "1px solid #1f2937",
                      }}
                    />
                    <Customized
                      component={(props: any) => (
                        <OhlcSeries
                          {...props}
                          stroke={selectedMetric.color}
                        />
                      )}
                    />
                    <Line
                      type="monotone"
                      dataKey="close"
                      stroke="transparent"
                      dot={false}
                      activeDot={{ r: 4, fill: selectedMetric.color }}
                    />
                  </ComposedChart>
                ) : isLineChartView ? (
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis
                      dataKey="timeLabel"
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      minTickGap={20}
                    />
                    <YAxis
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      tickFormatter={metricFormatter}
                      domain={yDomain ?? ["auto", "auto"]}
                      allowDataOverflow
                      label={{
                        value: metricLabelWithUnit,
                        angle: -90,
                        position: "insideLeft",
                        fill: "#94a3b8",
                        fontSize: 10,
                      }}
                    />
                    <TimeseriesAnnotations
                      distributionValues={timeseriesDistributionValues}
                      currentValue={currentMetricValue}
                      currentTimeLabel={currentTimeLabel}
                      showSigmaBands={showSigmaBands}
                      formatValue={metricFormatterWithUnit}
                      showHighlight={showHighlight}
                    />
                    <Tooltip
                      formatter={(value: number) => metricFormatterWithUnit(value)}
                      labelStyle={{ color: "#e2e8f0" }}
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        border: "1px solid #1f2937",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="custyValue"
                      name="Custy"
                      stroke={CUSTY_SERIES_COLOR}
                      strokeWidth={2}
                      dot={
                        showLineDots
                          ? { r: 3, fill: CUSTY_SERIES_COLOR }
                          : false
                      }
                      activeDot={showLineDots ? { r: 4 } : false}
                      connectNulls
                      hide={!showCusty}
                    />
                    <Line
                      type="monotone"
                      dataKey="idbValue"
                      name="IDB"
                      stroke={IDB_SERIES_COLOR}
                      strokeWidth={2}
                      dot={
                        showLineDots
                          ? { r: 3, fill: IDB_SERIES_COLOR }
                          : false
                      }
                      activeDot={showLineDots ? { r: 4 } : false}
                      connectNulls
                      hide={!showIdb}
                    />
                    <Legend
                      verticalAlign="top"
                      align="right"
                      iconType="line"
                      wrapperStyle={{ fontSize: "10px", color: "#94a3b8" }}
                    />
                  </LineChart>
                ) : (
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                    <XAxis
                      dataKey="timeLabel"
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      minTickGap={20}
                    />
                    <YAxis
                      tick={{ fill: "#94a3b8", fontSize: 10 }}
                      tickFormatter={metricFormatter}
                      domain={yDomain ?? ["auto", "auto"]}
                      allowDataOverflow
                      label={{
                        value: metricLabelWithUnit,
                        angle: -90,
                        position: "insideLeft",
                        fill: "#94a3b8",
                        fontSize: 10,
                      }}
                    />
                    <TimeseriesAnnotations
                      distributionValues={timeseriesDistributionValues}
                      currentValue={currentMetricValue}
                      currentTimeLabel={currentTimeLabel}
                      showSigmaBands={showSigmaBands}
                      formatValue={metricFormatterWithUnit}
                      showHighlight={showHighlight}
                    />
                    <Tooltip
                      formatter={(value: number) => metricFormatterWithUnit(value)}
                      labelStyle={{ color: "#e2e8f0" }}
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        border: "1px solid #1f2937",
                      }}
                    />
                    <Bar
                      dataKey="custyValue"
                      name="Custy"
                      fill={CUSTY_SERIES_COLOR}
                      radius={[3, 3, 0, 0]}
                      hide={!showCusty}
                    />
                    <Bar
                      dataKey="idbValue"
                      name="IDB"
                      fill={IDB_SERIES_COLOR}
                      radius={[3, 3, 0, 0]}
                      hide={!showIdb}
                    />
                    <Legend
                      verticalAlign="top"
                      align="right"
                      iconType="square"
                      wrapperStyle={{ fontSize: "10px", color: "#94a3b8" }}
                    />
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="mt-3 text-xs text-slate-400">
              {!hasSeriesSelection
                ? "Select Custy and/or IDB to display a series."
                : timeseriesLoading
                  ? "Loading more history..."
                  : timeseriesError || "No timeseries data available."}
            </div>
          )}
          {(showCusty || showIdb) && (
            <div className="mt-2 flex flex-wrap items-center gap-4 text-[11px] text-slate-400">
              {showCusty && (custyExtremes.min || custyExtremes.max) && (
                <span className="flex flex-wrap items-center gap-2">
                  <span className="uppercase tracking-wide text-amber-300">
                    Custy
                  </span>
                  {custyExtremes.min && (
                    <span>
                      Low:{" "}
                      <span className="font-mono text-slate-200">
                        {metricFormatterWithUnit(custyExtremes.min.value)}
                      </span>{" "}
                      @ {custyExtremes.min.timeLabel}
                    </span>
                  )}
                  {custyExtremes.max && (
                    <span>
                      High:{" "}
                      <span className="font-mono text-slate-200">
                        {metricFormatterWithUnit(custyExtremes.max.value)}
                      </span>{" "}
                      @ {custyExtremes.max.timeLabel}
                    </span>
                  )}
                </span>
              )}
              {showIdb && (idbExtremes.min || idbExtremes.max) && (
                <span className="flex flex-wrap items-center gap-2">
                  <span className="uppercase tracking-wide text-sky-300">
                    IDB
                  </span>
                  {idbExtremes.min && (
                    <span>
                      Low:{" "}
                      <span className="font-mono text-slate-200">
                        {metricFormatterWithUnit(idbExtremes.min.value)}
                      </span>{" "}
                      @ {idbExtremes.min.timeLabel}
                    </span>
                  )}
                  {idbExtremes.max && (
                    <span>
                      High:{" "}
                      <span className="font-mono text-slate-200">
                        {metricFormatterWithUnit(idbExtremes.max.value)}
                      </span>{" "}
                      @ {idbExtremes.max.timeLabel}
                    </span>
                  )}
                </span>
              )}
            </div>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span>Units: {metricLabelWithUnit}</span>
            <span className="text-slate-600">•</span>
            <span>IDB MICs: {IDB_MIC_CODES.join(", ")}</span>
            <span className="text-slate-600">•</span>
            <span>Custy MICs: {CUSTY_MIC_CODES.join(", ")}</span>
            <span className="text-slate-600">•</span>
            <span>Unknown/blank MICs treated as Custy</span>
            <span className="text-slate-600">•</span>
            <span>
              {timeseriesMetric === "vega01" && useGrossVega
                ? "Gross Vega = sum of abs(Vega01)"
                : "Daily Close sums cumulative metrics (notional/greeks)"}
            </span>
            <span className="text-slate-600">•</span>
            <span>High/Low based on loaded history</span>
            <span className="text-slate-600">|</span>
            <span>
              Summary stats use selected range + loaded history (size uses abs
              notional)
            </span>
            {ohlcNote && (
              <>
                <span className="text-slate-600">•</span>
                <span>{ohlcNote}</span>
              </>
            )}
          </div>
          {timeseriesNotice && !timeseriesLoading && !timeseriesError && (
            <div className="mt-2 text-[11px] text-amber-300">
              {timeseriesNotice}
            </div>
          )}
            </>
          )}
          {timeseriesTab === "RARITY" && (
            <div className="mt-3">
              <TradeRarityPanel
                selectedRow={row}
                timeseriesRows={timeseriesRows}
                formatters={rarityFormatters}
              />
            </div>
          )}
        </div>
      )}
      <RawDataModal
        isOpen={showRawDataModal}
        data={row}
        position={modalPosition}
        onClose={() => setShowRawDataModal(false)}
      />
    </div>
  );
}

function RawDataModal({
  isOpen,
  data,
  position,
  onClose,
}: {
  isOpen: boolean;
  data: TapeRow;
  position: { top: number } | null;
  onClose: () => void;
}) {
  if (!isOpen) return null;

  // Position modal horizontally centered, vertically at the row position
  const modalStyle: React.CSSProperties = position
    ? {
        position: 'absolute' as const,
        top: `${position.top}px`,
        left: '50%',
        transform: 'translateX(-50%)',
        maxWidth: '800px',
        width: 'calc(100vw - 32px)',
      }
    : {};

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 p-4" onClick={onClose}>
      <div
        className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-xl"
        style={modalStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            Raw Data
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
            aria-label="Close raw data modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-4">
          <pre className="text-xs text-slate-200 bg-slate-950 rounded-lg p-4 overflow-x-auto">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

function NetFlowSparkline({
  series,
  peakIndex,
}: {
  series: SequenceSummary["runningNetSeries"];
  peakIndex: number | null;
}) {
  const values = series
    .map((point) =>
      typeof point.netValue === "number" && Number.isFinite(point.netValue)
        ? point.netValue
        : null,
    )
    .filter((value): value is number => value !== null);
  if (values.length < 2) {
    return (
      <div className="text-[10px] text-slate-500">
        Net flow unavailable for this selection.
      </div>
    );
  }
  const width = 240;
  const height = 56;
  const padding = 6;
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, 0);
  const range = maxValue - minValue || 1;
  const stepCount = Math.max(series.length - 1, 1);
  const scaleX = (index: number) =>
    padding + (index / stepCount) * (width - padding * 2);
  const scaleY = (value: number) =>
    height - padding - ((value - minValue) / range) * (height - padding * 2);

  let path = "";
  let prevX: number | null = null;
  let prevY: number | null = null;
  series.forEach((point, index) => {
    if (typeof point.netValue !== "number" || !Number.isFinite(point.netValue)) {
      return;
    }
    const x = scaleX(index);
    const y = scaleY(point.netValue);
    if (prevX === null || prevY === null) {
      path = `M ${x} ${y}`;
    } else {
      path += ` L ${x} ${prevY} L ${x} ${y}`;
    }
    prevX = x;
    prevY = y;
  });

  const baselineY = scaleY(0);
  const peakPoint =
    peakIndex !== null &&
    typeof series[peakIndex]?.netValue === "number" &&
    Number.isFinite(series[peakIndex]?.netValue)
      ? {
          x: scaleX(peakIndex),
          y: scaleY(series[peakIndex].netValue as number),
        }
      : null;

  return (
    <svg width={width} height={height} className="overflow-visible">
      <line
        x1={padding}
        x2={width - padding}
        y1={baselineY}
        y2={baselineY}
        stroke="rgba(148,163,184,0.4)"
        strokeDasharray="3 3"
      />
      <path
        d={path}
        fill="none"
        stroke="#38bdf8"
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {peakPoint && (
        <circle
          cx={peakPoint.x}
          cy={peakPoint.y}
          r={3}
          fill="#f97316"
          stroke="rgba(15,23,42,0.8)"
          strokeWidth={1}
        />
      )}
    </svg>
  );
}

function SequenceAnalysisPanel({
  rows,
  cluster,
}: {
  rows: TapeRow[];
  cluster: SequenceCluster | null;
}) {
  const summary = useMemo(() => buildSequenceSummary(rows), [rows]);

  const [historyRows, setHistoryRows] = useState<TapeRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyTruncated, setHistoryTruncated] = useState(false);
  const historyFetchKeyRef = useRef<string | null>(null);

  const bucketKey = useMemo(() => {
    if (summary.bucketBreakdown.length !== 1) return null;
    if (!summary.bucketKey || summary.bucketKey === "UNKNOWN") return null;
    return summary.bucketKey;
  }, [summary.bucketBreakdown.length, summary.bucketKey]);

  const packageTypeKey = useMemo(() => {
    const types = new Set<string>();
    rows.forEach((row) => {
      const normalized = normalizePackageType(row.package_type);
      types.add(normalized || "OUTRIGHT");
    });
    return types.size === 1 ? Array.from(types)[0] : null;
  }, [rows]);

  const anchorTimestamp = useMemo(() => {
    const timestamps = rows
      .map((row) => parseTimestamp(row.execution_start))
      .filter((value): value is number => value !== null);
    return timestamps.length ? Math.max(...timestamps) : null;
  }, [rows]);

  useEffect(() => {
    if (!bucketKey || !packageTypeKey) {
      setHistoryRows([]);
      setHistoryError(null);
      setHistoryTruncated(false);
      historyFetchKeyRef.current = null;
      return;
    }
    const fetchKey = `${bucketKey}|${packageTypeKey}`;
    if (historyFetchKeyRef.current === fetchKey) return;

    let cancelled = false;
    const controller = new AbortController();

    const fetchHistory = async () => {
      setHistoryLoading(true);
      setHistoryError(null);
      setHistoryRows([]);
      setHistoryTruncated(false);
      try {
        const params = new URLSearchParams();
        params.set("seriesKey", bucketKey);
        params.set("packageType", packageTypeKey);
        const res = await fetch(
          `/api/swaptions-tape/timeseries?${params.toString()}`,
          { signal: controller.signal },
        );
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || "Failed to load sequence history.");
        }
        const payload = await res.json();
        if (cancelled) return;
        const rows = Array.isArray(payload?.rows) ? payload.rows : [];
        setHistoryRows(rows as TapeRow[]);
        setHistoryTruncated(!!payload?.truncated);
        historyFetchKeyRef.current = fetchKey;
      } catch (error: any) {
        if (cancelled) return;
        setHistoryError(
          error?.message || "Failed to load sequence history.",
        );
      } finally {
        if (!cancelled) {
          setHistoryLoading(false);
        }
      }
    };

    fetchHistory();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [bucketKey, packageTypeKey]);

  const historyWindowRows = useMemo(() => {
    if (!anchorTimestamp) return [];
    const windowStart = anchorTimestamp - ONE_YEAR_MS;
    return historyRows.filter((row): row is TapeRow => {
      if (!row) return false;
      const ts = parseTimestamp(row.execution_start);
      if (ts === null) return false;
      return ts >= windowStart && ts <= anchorTimestamp;
    });
  }, [anchorTimestamp, historyRows]);

  const currentStartTs = useMemo(() => {
    const timestamps = rows
      .map((row) => parseTimestamp(row.execution_start))
      .filter((value): value is number => value !== null);
    return timestamps.length ? Math.min(...timestamps) : null;
  }, [rows]);

  const currentEndTs = useMemo(() => {
    const timestamps = rows
      .map((row) => parseTimestamp(row.execution_start))
      .filter((value): value is number => value !== null);
    return timestamps.length ? Math.max(...timestamps) : null;
  }, [rows]);

  const historicalClusters = useMemo(
    () =>
      historyWindowRows.length
        ? detectSequenceClusters(
            historyWindowRows,
            SEQUENCE_CLUSTER_MAX_GAP_MINUTES,
            SEQUENCE_CLUSTER_MIN_TRADES,
          )
        : [],
    [historyWindowRows],
  );

  const minTradesForStats = Math.max(
    SEQUENCE_CLUSTER_MIN_TRADES,
    summary.tradeCount,
  );

  const similarClusters = useMemo(() => {
    const maxWindowMs = SEQUENCE_CLUSTER_MAX_GAP_MINUTES * 60 * 1000;
    return historicalClusters.filter(
      (cluster) =>
        cluster.rows.length >= minTradesForStats &&
        cluster.durationMs <= maxWindowMs,
    );
  }, [historicalClusters, minTradesForStats]);

  const clusterStats = useMemo(() => {
    return similarClusters.map((cluster) => {
      const summary = buildSequenceSummary(cluster.rows);
      const startDate = new Date(cluster.startTimestamp);
      return {
        cluster,
        summary,
        tradeCount: cluster.rows.length,
        grossNotional: summary.grossNotional,
        pace: summary.tradesPerHour,
        netDirection: summary.netDirection,
        netToGrossPct: summary.netToGrossPct,
        directionKey: summary.directionCompact,
        sizeProfile: summary.sizeProfile,
        startTimestamp: cluster.startTimestamp,
        endTimestamp: cluster.endTimestamp,
        durationMs: cluster.durationMs,
        startHour: startDate.getHours(),
        dayOfWeek: startDate.getDay(),
        dayOfMonth: startDate.getDate(),
      };
    });
  }, [similarClusters]);

  const clusterStatsPrior = useMemo(() => {
    if (currentStartTs === null) return clusterStats;
    return clusterStats.filter((stat) => stat.endTimestamp < currentStartTs);
  }, [clusterStats, currentStartTs]);

  const historyRowPoints = useMemo(() => {
    const points = historyWindowRows
      .map((row) => {
        if (!row) return null;
        const timestamp = parseTimestamp(row.execution_start);
        if (timestamp === null || !Number.isFinite(timestamp)) return null;
        const notional = computeDisplayNotional(row);
        const direction = resolveRowDirection(row);
        const packageType = normalizePackageType(row.package_type) || "OUTRIGHT";
        const bpvol = resolvePackageBpvolYr(row, packageType);
        return {
          timestamp,
          notional,
          direction,
          bpvol,
        };
      })
      .filter(
        (point): point is {
          timestamp: number;
          notional: number | null;
          direction: SequenceDirection;
          bpvol: number | null;
        } =>
          !!point &&
          typeof point.timestamp === "number" &&
          Number.isFinite(point.timestamp),
      )
      .sort((a, b) => a.timestamp - b.timestamp);
    return points;
  }, [historyWindowRows]);

  const clusterRarity = useMemo(() => {
    if (!clusterStats.length || currentStartTs === null) return null;
    const startTimes = clusterStats
      .map((stat) => stat.startTimestamp)
      .sort((a, b) => a - b);
    const intervals: number[] = [];
    for (let i = 1; i < startTimes.length; i += 1) {
      intervals.push(startTimes[i] - startTimes[i - 1]);
    }
    const avgIntervalDays =
      intervals.length > 0
        ? intervals.reduce((sum, value) => sum + value, 0) /
          intervals.length /
          ONE_DAY_MS
        : null;

    const lastCluster = clusterStatsPrior.reduce(
      (latest, stat) =>
        !latest || stat.startTimestamp > latest.startTimestamp ? stat : latest,
      null as (typeof clusterStatsPrior)[number] | null,
    );
    const lastClusterDaysAgo =
      lastCluster && currentStartTs !== null
        ? (currentStartTs - lastCluster.startTimestamp) / ONE_DAY_MS
        : null;

    const grossValues = clusterStats
      .map((stat) => stat.grossNotional)
      .filter((value): value is number => value !== null);
    const paceValues = clusterStats
      .map((stat) => stat.pace)
      .filter((value): value is number => value !== null);

    const grossPercentile =
      summary.grossNotional !== null
        ? percentileRank(summary.grossNotional, grossValues)
        : null;
    const pacePercentile =
      summary.tradesPerHour !== null
        ? percentileRank(summary.tradesPerHour, paceValues)
        : null;

    const hourBuckets = new Map<number, number>();
    clusterStats.forEach((stat) => {
      const bucket = Math.floor(stat.startHour / 4);
      hourBuckets.set(bucket, (hourBuckets.get(bucket) || 0) + 1);
    });
    const [modeBucket] =
      Array.from(hourBuckets.entries()).sort((a, b) => b[1] - a[1])[0] || [];
    const bucketStartHour =
      modeBucket !== undefined ? modeBucket * 4 : null;
    const typicalTimeLabel =
      bucketStartHour !== null
        ? `${String(bucketStartHour).padStart(2, "0")}:00-${String(
            bucketStartHour + 4,
          ).padStart(2, "0")}:00 ET`
        : null;

    const currentHour =
      currentStartTs !== null ? new Date(currentStartTs).getHours() : null;
    const currentBucket =
      currentHour !== null ? Math.floor(currentHour / 4) : null;
    let timeOfDayNote: string | null = null;
    if (
      currentBucket !== null &&
      modeBucket !== undefined &&
      currentBucket !== modeBucket
    ) {
      timeOfDayNote =
        currentBucket < (modeBucket as number)
          ? "unusually early"
          : "unusually late";
    }

    const dayOfWeekCounts = new Map<number, number>();
    clusterStats.forEach((stat) => {
      dayOfWeekCounts.set(
        stat.dayOfWeek,
        (dayOfWeekCounts.get(stat.dayOfWeek) || 0) + 1,
      );
    });
    const topDay = Array.from(dayOfWeekCounts.entries()).sort(
      (a, b) => b[1] - a[1],
    )[0];
    const typicalDayLabel = topDay
      ? `${formatDayOfWeek(topDay[0])} (${formatRate(
          (topDay[1] / clusterStats.length) * 100,
          0,
        )}%)`
      : null;

    const domCounts = new Map<number, number>();
    clusterStats.forEach((stat) => {
      const bin = Math.min(Math.floor((stat.dayOfMonth - 1) / 5), 5);
      domCounts.set(bin, (domCounts.get(bin) || 0) + 1);
    });
    const topDom = Array.from(domCounts.entries()).sort(
      (a, b) => b[1] - a[1],
    )[0];
    const domLabel = topDom
      ? topDom[0] === 5
        ? "26-31"
        : `${topDom[0] * 5 + 1}-${topDom[0] * 5 + 5}`
      : null;

    return {
      clusterCount: clusterStats.length,
      avgIntervalDays,
      lastClusterDaysAgo,
      lastClusterDate: lastCluster ? formatDateShort(lastCluster.startTimestamp) : null,
      grossPercentile,
      pacePercentile,
      typicalTimeLabel,
      timeOfDayNote,
      typicalDayLabel,
      domLabel,
    };
  }, [clusterStats, clusterStatsPrior, currentStartTs, summary.grossNotional, summary.tradesPerHour]);

  const postClusterHistory = useMemo(() => {
    if (!clusterStatsPrior.length || !historyRowPoints.length) return null;
    const windows = [30, 60, 120].map((m) => m * 60 * 1000);
    let follow30 = 0;
    let follow60 = 0;
    let follow120 = 0;
    let additionalGrossSum = 0;
    let additionalGrossCount = 0;
    const payerVolDrifts: number[] = [];
    const receiverVolDrifts: number[] = [];

    const timestamps = historyRowPoints.map((point) => point.timestamp);

    const findFirstIndexAfter = (ts: number) => {
      let lo = 0;
      let hi = timestamps.length;
      while (lo < hi) {
        const mid = Math.floor((lo + hi) / 2);
        if (timestamps[mid] <= ts) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    };

    clusterStatsPrior.forEach((stat) => {
      const startIndex = findFirstIndexAfter(stat.endTimestamp);
      const endWindow = stat.endTimestamp + windows[2];
      let has30 = false;
      let has60 = false;
      let has120 = false;
      let gross = 0;
      for (let i = startIndex; i < historyRowPoints.length; i += 1) {
        const point = historyRowPoints[i];
        if (!point) continue;
        if (point.timestamp > endWindow) break;
        const delta = point.timestamp - stat.endTimestamp;
        if (delta <= windows[0]) has30 = true;
        if (delta <= windows[1]) has60 = true;
        if (delta <= windows[2]) has120 = true;
        if (point.notional !== null) gross += Math.abs(point.notional);
      }
      if (has30) follow30 += 1;
      if (has60) follow60 += 1;
      if (has120) follow120 += 1;
      if (gross > 0) {
        additionalGrossSum += gross;
        additionalGrossCount += 1;
      }

      let nextVolTrade: typeof historyRowPoints[number] | null = null;
      for (let i = startIndex; i < historyRowPoints.length; i += 1) {
        const point = historyRowPoints[i];
        if (!point) continue;
        const delta = point.timestamp - stat.endTimestamp;
        if (delta > ONE_DAY_MS) break;
        if (point.bpvol !== null) {
          nextVolTrade = point;
          break;
        }
      }

      if (
        stat.summary.bpvolEnd !== null &&
        nextVolTrade &&
        nextVolTrade.bpvol !== null
      ) {
        const drift = nextVolTrade.bpvol - stat.summary.bpvolEnd;
        if (stat.netDirection === "PAYER") payerVolDrifts.push(drift);
        if (stat.netDirection === "RECEIVER") receiverVolDrifts.push(drift);
      }
    });

    const sampleSize = clusterStatsPrior.length;
    return {
      sampleSize,
      follow30Pct: sampleSize ? (follow30 / sampleSize) * 100 : null,
      follow60Pct: sampleSize ? (follow60 / sampleSize) * 100 : null,
      follow120Pct: sampleSize ? (follow120 / sampleSize) * 100 : null,
      avgAdditionalGross2h:
        additionalGrossCount > 0
          ? additionalGrossSum / additionalGrossCount
          : null,
      payerVolDriftAvg: payerVolDrifts.length
        ? payerVolDrifts.reduce((a, b) => a + b, 0) / payerVolDrifts.length
        : null,
      receiverVolDriftAvg: receiverVolDrifts.length
        ? receiverVolDrifts.reduce((a, b) => a + b, 0) /
          receiverVolDrifts.length
        : null,
    };
  }, [clusterStatsPrior, historyRowPoints]);

  const patternMatch = useMemo(() => {
    if (!clusterStats.length) return null;
    const sameSize = clusterStats.filter(
      (stat) => stat.tradeCount === summary.tradeCount,
    );
    const patternCount = sameSize.filter(
      (stat) => stat.directionKey === summary.directionCompact,
    ).length;
    const sizeProfileCount = sameSize.filter(
      (stat) => stat.sizeProfile === summary.sizeProfile,
    ).length;

    const grossValues = clusterStats
      .map((stat) => stat.grossNotional)
      .filter((value): value is number => value !== null);
    const paceValues = clusterStats
      .map((stat) => stat.pace)
      .filter((value): value is number => value !== null);

    const grossPct =
      summary.grossNotional !== null
        ? percentileRank(summary.grossNotional, grossValues)
        : null;
    const pacePct =
      summary.tradesPerHour !== null
        ? percentileRank(summary.tradesPerHour, paceValues)
        : null;
    const anomalyScore =
      grossPct !== null && pacePct !== null
        ? (grossPct + pacePct) / 2
        : null;
    const anomalyLabel =
      anomalyScore === null
        ? "unknown"
        : anomalyScore >= 90
          ? "rare"
          : anomalyScore >= 70
            ? "notable"
            : "routine";

    let bestMatch: typeof clusterStats[number] | null = null;
    let bestScore = Number.POSITIVE_INFINITY;
    clusterStats.forEach((stat) => {
      if (currentStartTs !== null && stat.startTimestamp === currentStartTs) {
        return;
      }
      let score = 0;
      score += stat.directionKey === summary.directionCompact ? 0 : 1;
      score += stat.sizeProfile === summary.sizeProfile ? 0 : 0.5;
      if (summary.netToGrossPct !== null && stat.netToGrossPct !== null) {
        score +=
          Math.abs(summary.netToGrossPct - stat.netToGrossPct) / 50;
      } else {
        score += 0.5;
      }
      if (summary.durationMs !== null) {
        score +=
          Math.abs(summary.durationMs - stat.durationMs) /
          (SEQUENCE_CLUSTER_MAX_GAP_MINUTES * 60 * 1000);
      }
      if (summary.grossNotional !== null && stat.grossNotional !== null) {
        score +=
          Math.abs(summary.grossNotional - stat.grossNotional) /
          summary.grossNotional;
      }
      if (score < bestScore) {
        bestScore = score;
        bestMatch = stat;
      }
    });

    return {
      patternFreqPct: sameSize.length
        ? (patternCount / sameSize.length) * 100
        : null,
      sizeProfileFreqPct: sameSize.length
        ? (sizeProfileCount / sameSize.length) * 100
        : null,
      anomalyScore,
      anomalyLabel,
      bestMatch,
    };
  }, [
    clusterStats,
    currentStartTs,
    summary.directionCompact,
    summary.durationMs,
    summary.grossNotional,
    summary.netToGrossPct,
    summary.sizeProfile,
    summary.tradeCount,
    summary.tradesPerHour,
  ]);

  const hedgeLatencyStats = useMemo(() => {
    if (!historyRowPoints.length) return null;
    const latencies: number[] = [];
    for (let i = 0; i < historyRowPoints.length; i += 1) {
      const point = historyRowPoints[i];
      if (
        point.notional === null ||
        point.notional < HEDGE_LATENCY_NOTIONAL
      ) {
        continue;
      }
      if (point.direction !== "PAYER" && point.direction !== "RECEIVER") {
        continue;
      }
      const target =
        point.direction === "PAYER" ? "RECEIVER" : "PAYER";
      for (let j = i + 1; j < historyRowPoints.length; j += 1) {
        const next = historyRowPoints[j];
        const delta = next.timestamp - point.timestamp;
        if (delta > HEDGE_LATENCY_MAX_WINDOW_MS) break;
        if (next.direction === target) {
          latencies.push(delta);
          break;
        }
      }
    }
    return {
      medianMs: median(latencies),
      currentMs: summary.firstOpposingGapMs,
    };
  }, [historyRowPoints, summary.firstOpposingGapMs]);

  const intradayInventory = useMemo(() => {
    if (currentStartTs === null || !historyRowPoints.length) return null;
    const day = new Date(currentStartTs);
    const dayStart = new Date(
      day.getFullYear(),
      day.getMonth(),
      day.getDate(),
    ).getTime();
    const dayEnd = dayStart + ONE_DAY_MS;
    let net = 0;
    let gross = 0;
    let peak = 0;
    historyRowPoints.forEach((point) => {
      if (point.timestamp < dayStart || point.timestamp > dayEnd) return;
      if (point.notional !== null) {
        gross += Math.abs(point.notional);
      }
      if (point.direction === "PAYER" && point.notional !== null) {
        net += point.notional;
      }
      if (point.direction === "RECEIVER" && point.notional !== null) {
        net -= point.notional;
      }
      peak = Math.max(peak, Math.abs(net));
    });
    return {
      gross: gross || null,
      net: gross ? net : null,
      peak: gross ? peak : null,
    };
  }, [currentStartTs, historyRowPoints]);

  const bucketLabel =
    summary.bucketBreakdown.length > 1
      ? "Mixed buckets"
      : summary.bucketKey && summary.bucketKey !== "UNKNOWN"
        ? summary.bucketKey
        : "Unlabeled bucket";
  const bucketDetail = summary.bucketBreakdown
    .map((entry) => `${entry.key} (${entry.count})`)
    .join(" \u00b7 ");
  const clipLabel = summary.clipSizes.length
    ? summary.clipSizes.map((value) => formatNotional(value)).join(" / ")
    : "--";
  const platformLabel = summary.platformBreakdown.length
    ? summary.platformBreakdown
        .slice(0, 3)
        .map(
          (entry) =>
            `${entry.platform} ${formatRate(entry.sharePct, 0)}%`,
        )
        .join(" \u00b7 ")
    : "--";

  const directionTone = (direction: SequenceDirection) => {
    if (direction === "PAYER") return "text-rose-300";
    if (direction === "RECEIVER") return "text-emerald-300";
    if (direction === "MIXED") return "text-amber-300";
    return "text-slate-400";
  };

  const netFlowSteps = useMemo(() => {
    const values = summary.runningNetSeries
      .map((point) => point.netValue)
      .filter((value): value is number => value !== null)
      .map((value) => formatSignedNotional(value));
    if (!values.length) return "--";
    return ["0", ...values].join(" \u2192 ");
  }, [summary.runningNetSeries]);

  const imbalancePoint =
    summary.imbalancePeakIndex !== null
      ? summary.runningNetSeries[summary.imbalancePeakIndex]
      : null;

  const participantLabel = summary.participantClusters.length
    ? summary.participantClusters.map((value) => formatNotional(value)).join(" / ")
    : "--";

  const historyStatusNote = !bucketKey
    ? "History unavailable for mixed bucket selections."
    : !packageTypeKey
      ? "History unavailable for mixed package types."
      : null;

  if (rows.length < 2) return null;

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-4 text-xs text-slate-200">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-slate-400">
            Sequence Analysis
          </div>
          <div className="text-sm font-semibold text-slate-100">
            {bucketLabel}
          </div>
          <div className="text-[11px] text-slate-400">
            {summary.windowLabel}
            {summary.durationMs !== null && (
              <>
                {" "}
                {"\u00b7"} {formatDurationMs(summary.durationMs)}
              </>
            )}
          </div>
          {bucketDetail && (
            <div className="text-[10px] text-slate-500 truncate">
              {bucketDetail}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="rounded border border-slate-700 bg-slate-900/60 px-2 py-1 font-mono text-slate-200">
            {summary.tradeCount} trades
          </span>
          {cluster && (
            <span className="rounded border border-sky-500/50 bg-sky-500/10 px-2 py-1 font-mono text-sky-200">
              Cluster {cluster.rows.length} {"\u00b7"}{" "}
              {formatDurationMs(cluster.durationMs)}
            </span>
          )}
          <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 font-mono text-emerald-200">
            Net {summary.netDirection.toLowerCase()}
          </span>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-4">
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Flow
          </div>
          <div className="mt-2 space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Gross</span>
              <span className="font-mono text-slate-100">
                {formatNotional(summary.grossNotional)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Net</span>
              <span className="font-mono text-slate-100">
                {formatSignedNotional(
                  summary.grossNotional === null ? null : summary.netNotional,
                )}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Net/Gross</span>
              <span className="font-mono text-slate-100">
                {summary.netToGrossPct !== null
                  ? `${formatRate(summary.netToGrossPct, 1)}%`
                  : "--"}
              </span>
            </div>
            {summary.bpvolStart !== null && summary.bpvolEnd !== null && (
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Vol drift</span>
                <span className="font-mono text-slate-100">
                  {formatMetricValue(summary.bpvolStart, 2)} {"\u2192"}{" "}
                  {formatMetricValue(summary.bpvolEnd, 2)} (
                  {formatMetricValue(summary.bpvolChange, 2)})
                </span>
              </div>
            )}
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Timing
          </div>
          <div className="mt-2 space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Avg gap</span>
              <span className="font-mono text-slate-100">
                {formatDurationMs(summary.avgGapMs)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Min gap</span>
              <span className="font-mono text-slate-100">
                {formatDurationMs(summary.minGapMs)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Max gap</span>
              <span className="font-mono text-slate-100">
                {formatDurationMs(summary.maxGapMs)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Trades/hr</span>
              <span className="font-mono text-slate-100">
                {summary.tradesPerHour !== null
                  ? formatRate(summary.tradesPerHour, 2)
                  : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Gap trend</span>
              <span className="font-mono text-slate-100">
                {summary.gapTrend ?? "--"}
              </span>
            </div>
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Clips
          </div>
          <div className="mt-2 space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Sequence</span>
              <span className="font-mono text-slate-100">{clipLabel}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Uniformity</span>
              <span className="font-mono text-slate-100">
                {summary.clipUniformityLabel}
                {summary.clipUniformityPct !== null
                  ? ` (${formatRate(summary.clipUniformityPct, 0)}%)`
                  : ""}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Median</span>
              <span className="font-mono text-slate-100">
                {formatNotional(summary.clipMedian)}
              </span>
            </div>
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Venue
          </div>
          <div className="mt-2 space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Platforms</span>
              <span className="font-mono text-slate-100">{platformLabel}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">IDB share</span>
              <span className="font-mono text-slate-100">
                {summary.idbSharePct !== null
                  ? `${formatRate(summary.idbSharePct, 0)}%`
                  : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Custy share</span>
              <span className="font-mono text-slate-100">
                {summary.custySharePct !== null
                  ? `${formatRate(summary.custySharePct, 0)}%`
                  : "--"}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Flow Momentum
          </div>
          <div className="mt-2">
            <NetFlowSparkline
              series={summary.runningNetSeries}
              peakIndex={summary.imbalancePeakIndex}
            />
            <div className="mt-2 text-[10px] text-slate-400">
              Net flow:{" "}
              <span className="font-mono text-slate-200">{netFlowSteps}</span>
            </div>
          </div>
          <div className="mt-3 grid gap-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Imbalance peak</span>
              <span className="font-mono text-slate-100">
                {summary.imbalancePeak !== null
                  ? `${formatSignedNotional(summary.imbalancePeak)}${
                      imbalancePoint?.timeLabel
                        ? ` @ ${imbalancePoint.timeLabel}`
                        : ""
                    }`
                  : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Reversion speed</span>
              <span className="font-mono text-slate-100">
                {summary.reversionTrades !== null
                  ? `${summary.reversionTrades} trades / ${formatDurationMs(
                      summary.reversionMs,
                    )}`
                  : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Hedged in-cluster</span>
              <span className="font-mono text-slate-100">
                {summary.hedgedPct !== null
                  ? `${formatRate(summary.hedgedPct, 0)}%`
                  : "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Participants</span>
              <span className="font-mono text-slate-100">
                {summary.estimatedParticipants ?? "--"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Clip clusters</span>
              <span className="font-mono text-slate-100">
                {participantLabel}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Initiator</span>
              <span className="font-mono text-slate-100">
                {summary.initiatorLabel} ({summary.initiatorConfidence})
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Opposing print</span>
              <span className="font-mono text-slate-100">
                {summary.firstOpposingGapMs !== null
                  ? formatDurationMs(summary.firstOpposingGapMs)
                  : "--"}
                {hedgeLatencyStats?.medianMs
                  ? ` (median ${formatDurationMs(
                      hedgeLatencyStats.medianMs,
                    )})`
                  : ""}
              </span>
            </div>
            {intradayInventory && (
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Day net / gross</span>
                <span className="font-mono text-slate-100">
                  {formatSignedNotional(intradayInventory.net)} /{" "}
                  {formatNotional(intradayInventory.gross)}
                </span>
              </div>
            )}
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Cluster Rarity
          </div>
          {historyLoading && (
            <div className="mt-2 text-[11px] text-slate-400">
              Loading cluster history...
            </div>
          )}
          {historyError && (
            <div className="mt-2 text-[11px] text-rose-300">
              {historyError}
            </div>
          )}
          {!historyLoading && !historyError && clusterRarity && (
            <div className="mt-2 space-y-1 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">
                  Clusters &gt;={minTradesForStats} trades ({'<='}{SEQUENCE_CLUSTER_MAX_GAP_MINUTES}m, 365d)
                </span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.clusterCount}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Avg interval</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.avgIntervalDays !== null
                    ? `${formatRate(clusterRarity.avgIntervalDays, 1)}d`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Last similar</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.lastClusterDaysAgo !== null
                    ? `${formatRate(clusterRarity.lastClusterDaysAgo, 0)}d ago (${clusterRarity.lastClusterDate})`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Gross percentile</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.grossPercentile !== null
                    ? `P${formatRate(clusterRarity.grossPercentile, 0)}`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Pace percentile</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.pacePercentile !== null
                    ? `P${formatRate(clusterRarity.pacePercentile, 0)}`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Typical time</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.typicalTimeLabel ?? "--"}
                </span>
              </div>
              {clusterRarity.timeOfDayNote && (
                <div className="text-[10px] text-amber-300">
                  This cluster is {clusterRarity.timeOfDayNote}.
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Top weekday</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.typicalDayLabel ?? "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Top month window</span>
                <span className="font-mono text-slate-100">
                  {clusterRarity.domLabel ? `${clusterRarity.domLabel}` : "--"}
                </span>
              </div>
              {historyTruncated && (
                <div className="mt-2 text-[10px] text-amber-300">
                  History truncated at 50k rows.
                </div>
              )}
            </div>
          )}
          {!historyLoading && !historyError && !clusterRarity && (
            <div className="mt-2 text-[11px] text-slate-400">
              {historyStatusNote || "No historical clusters found."}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Post-Cluster History
          </div>
          {historyError && (
            <div className="mt-2 text-[11px] text-rose-300">
              {historyError}
            </div>
          )}
          {!historyError && historyLoading && (
            <div className="mt-2 text-[11px] text-slate-400">
              Loading post-cluster history...
            </div>
          )}
          {!historyError && !historyLoading && !postClusterHistory && (
            <div className="mt-2 text-[11px] text-slate-400">
              {historyStatusNote || "No post-cluster samples available."}
            </div>
          )}
          {!historyError && !historyLoading && postClusterHistory && (
            <div className="mt-2 space-y-1 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Similar clusters</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.sampleSize}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Follow-on 30m</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.follow30Pct !== null
                    ? `${formatRate(postClusterHistory.follow30Pct, 0)}%`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Follow-on 60m</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.follow60Pct !== null
                    ? `${formatRate(postClusterHistory.follow60Pct, 0)}%`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Follow-on 120m</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.follow120Pct !== null
                    ? `${formatRate(postClusterHistory.follow120Pct, 0)}%`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Avg gross next 2h</span>
                <span className="font-mono text-slate-100">
                  {formatNotional(postClusterHistory.avgAdditionalGross2h)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Vol drift (net payer)</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.payerVolDriftAvg !== null
                    ? formatMetricValue(postClusterHistory.payerVolDriftAvg, 2)
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Vol drift (net receiver)</span>
                <span className="font-mono text-slate-100">
                  {postClusterHistory.receiverVolDriftAvg !== null
                    ? formatMetricValue(
                        postClusterHistory.receiverVolDriftAvg,
                        2,
                      )
                    : "--"}
                </span>
              </div>
              <div className="mt-2 text-[10px] text-slate-500">
                Cross-bucket propagation requires multi-bucket history.
              </div>
            </div>
          )}
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Pattern Match
          </div>
          {historyError && (
            <div className="mt-2 text-[11px] text-rose-300">
              {historyError}
            </div>
          )}
          {!historyError && historyLoading && (
            <div className="mt-2 text-[11px] text-slate-400">
              Loading pattern history...
            </div>
          )}
          {!historyError && !historyLoading && !patternMatch && (
            <div className="mt-2 text-[11px] text-slate-400">
              {historyStatusNote || "No historical patterns available."}
            </div>
          )}
          {!historyError && !historyLoading && patternMatch && (
            <div className="mt-2 space-y-1 text-[11px]">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Pattern freq (N={summary.tradeCount})</span>
                <span className="font-mono text-slate-100">
                  {patternMatch.patternFreqPct !== null
                    ? `${formatRate(patternMatch.patternFreqPct, 0)}%`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Size profile</span>
                <span className="font-mono text-slate-100">
                  {summary.sizeProfile}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Profile freq</span>
                <span className="font-mono text-slate-100">
                  {patternMatch.sizeProfileFreqPct !== null
                    ? `${formatRate(patternMatch.sizeProfileFreqPct, 0)}%`
                    : "--"}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Anomaly score</span>
                <span className="font-mono text-slate-100">
                  {patternMatch.anomalyScore !== null
                    ? `${patternMatch.anomalyLabel.toUpperCase()} (P${formatRate(
                        patternMatch.anomalyScore,
                        0,
                      )})`
                    : "--"}
                </span>
              </div>
              {patternMatch.bestMatch && (
                <div className="mt-2 text-[10px] text-slate-400">
                  Nearest match:{" "}
                  <span className="text-slate-200">
                    {formatDateShort(patternMatch.bestMatch.startTimestamp)}
                  </span>{" "}
                  · {patternMatch.bestMatch.summary.directionPattern} ·{" "}
                  {formatNotional(patternMatch.bestMatch.grossNotional)} ·{" "}
                  {formatDurationMs(patternMatch.bestMatch.durationMs)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Pattern
          </div>
          <div className="mt-2 text-sm font-mono text-slate-100">
            {summary.directionPattern || "--"}
          </div>
          <div className="text-[10px] text-slate-500">
            {summary.directionCompact || "--"}
          </div>
          <div className="mt-2 text-[11px] text-slate-300">
            {summary.narrative}
          </div>
        </div>
        <div className="rounded border border-slate-800 bg-slate-950/60 p-3">
          <div className="text-[10px] uppercase tracking-wide text-slate-400">
            Sequence
          </div>
          <div className="mt-2 space-y-1">
            {summary.sequenceRows.map((item) => (
              <div
                key={item.id}
                className="grid grid-cols-1 items-center gap-1 text-[11px] text-slate-200 md:grid-cols-[90px_36px_90px_70px_1fr]"
              >
                <span className="font-mono text-slate-300">
                  {item.timeLabel}
                </span>
                <span className={`font-semibold ${directionTone(item.direction)}`}>
                  {item.directionSymbol}
                </span>
                <span className="font-mono">{formatNotional(item.notional)}</span>
                <span className="text-slate-400">
                  {item.platform || "--"}
                </span>
                <span className="truncate text-slate-400">{item.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {summary.warnings.length > 0 && (
        <div className="mt-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
          {summary.warnings.join(" ")}
        </div>
      )}
    </div>
  );
}

function ManualLinkModal({
  isOpen,
  selectedRows,
  currentUser,
  onUserChange,
  onClose,
  onCreated,
}: {
  isOpen: boolean;
  selectedRows: TapeRow[];
  currentUser: string;
  onUserChange: (value: string) => void;
  onClose: () => void;
  onCreated: (result?: { link_id: string; manual_package_id: string }) => void;
}) {
  const selectedIds = useMemo(
    () => selectedRows.map((row) => row.package_id),
    [selectedRows],
  );
  const selectedSummaries = useMemo(
    () =>
      selectedRows.map((row) => ({
        package_id: row.package_id,
        package_type: row.package_type,
        label: buildRichLabel(row),
        execution_start: row.execution_start,
        execution_end: row.execution_end,
        manual_link_id: row.manual_link_id,
        manual_package_id: row.manual_package_id,
      })),
    [selectedRows],
  );
  const [packageType, setPackageType] = useState(
    MANUAL_PACKAGE_TYPES[0]?.value ?? "",
  );
  const [linkReason, setLinkReason] = useState(
    MANUAL_LINK_REASONS[0]?.value ?? "",
  );
  const [comment, setComment] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [validation, setValidation] = useState<ManualLinkValidationItem[]>([]);
  const [metrics, setMetrics] = useState<Record<string, any> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const hasValidationErrors = validation.some(
    (item) => item.status === "error",
  );

  const addTag = useCallback(() => {
    const next = tagInput.trim();
    if (!next) return;
    if (tags.includes(next)) {
      setTagInput("");
      return;
    }
    setTags((prev) => [...prev, next]);
    setTagInput("");
  }, [tagInput, tags]);

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((item) => item !== tag));
  }, []);

  const validateLink = useCallback(async () => {
    if (selectedIds.length < 2) return;
    setValidating(true);
    setError(null);
    try {
      const res = await fetch("/api/swaption/links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trade_ids: selectedIds,
          package_type: packageType || undefined,
          link_reason: linkReason || undefined,
          validate_only: true,
        }),
      });
      const payload = await res.json();
      if (!res.ok) {
        setError(payload?.error || "Failed to validate manual link.");
        if (payload?.validation) {
          setValidation(payload.validation as ManualLinkValidationItem[]);
        }
        if (payload?.metrics) {
          setMetrics(payload.metrics as Record<string, any>);
        }
        return;
      }
      setValidation(payload.validation || []);
      setMetrics(payload.metrics || null);
    } catch (err: any) {
      setError(err?.message || "Failed to validate manual link.");
    } finally {
      setValidating(false);
    }
  }, [linkReason, packageType, selectedIds]);

  const handleCreate = useCallback(async () => {
    if (selectedIds.length < 2) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/swaption/links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trade_ids: selectedIds,
          package_type: packageType || undefined,
          comment: comment || undefined,
          link_reason: linkReason || undefined,
          tags,
          user: currentUser || undefined,
        }),
      });
      const payload = await res.json();
      if (!res.ok) {
        setError(payload?.error || "Failed to create manual link.");
        if (payload?.validation) {
          setValidation(payload.validation as ManualLinkValidationItem[]);
        }
        if (payload?.metrics) {
          setMetrics(payload.metrics as Record<string, any>);
        }
        return;
      }
      const created =
        payload?.link_id && payload?.manual_package_id
          ? {
              link_id: payload.link_id,
              manual_package_id: payload.manual_package_id,
            }
          : undefined;
      onCreated(created);
      onClose();
    } catch (err: any) {
      setError(err?.message || "Failed to create manual link.");
    } finally {
      setSubmitting(false);
    }
  }, [
    comment,
    currentUser,
    linkReason,
    onClose,
    onCreated,
    packageType,
    selectedIds,
    tags,
  ]);

  useEffect(() => {
    if (!isOpen) return;
    setPackageType(MANUAL_PACKAGE_TYPES[0]?.value ?? "");
    setLinkReason(MANUAL_LINK_REASONS[0]?.value ?? "");
    setComment("");
    setTags([]);
    setTagInput("");
    setValidation([]);
    setMetrics(null);
    setError(null);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    if (selectedIds.length < 2) return;
    validateLink();
  }, [isOpen, selectedIds, validateLink]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
      <div className="w-full max-w-4xl overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <Link2 className="h-4 w-4 text-slate-300" />
            Link Trades as Package
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
            aria-label="Close manual link modal"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-4">
          <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="uppercase tracking-wide">Selected Trades</span>
                <span className="font-mono">
                  {selectedSummaries.length} selected
                </span>
              </div>
              <div className="space-y-2 rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                {selectedSummaries.length ? (
                  selectedSummaries.map((row) => (
                    <div
                      key={row.package_id}
                      className="rounded border border-slate-800/70 bg-slate-900/60 px-2 py-1 text-xs text-slate-200"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono">{row.package_id}</span>
                        <span className="text-[10px] uppercase text-slate-400">
                          {row.package_type || "N/A"}
                        </span>
                      </div>
                      <div className="text-[11px] text-slate-300">
                        {row.label}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {formatExecutionWindow(
                          row.execution_start,
                          row.execution_end,
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="text-xs text-slate-400">
                    Select at least two trades to create a manual link.
                  </div>
                )}
              </div>
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                <div className="flex items-center justify-between">
                  <span className="uppercase tracking-wide text-slate-400">
                    Validation
                  </span>
                  <button
                    type="button"
                    onClick={validateLink}
                    disabled={validating || selectedIds.length < 2}
                    className="rounded border border-slate-700 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500 disabled:opacity-50"
                  >
                    {validating ? "Validating" : "Refresh"}
                  </button>
                </div>
                <div className="mt-2 space-y-2">
                  {validation.length ? (
                    validation.map((item) => (
                      <div
                        key={item.key}
                        className="flex items-start gap-2 text-xs"
                      >
                        {item.status === "ok" ? (
                          <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-400" />
                        ) : item.status === "error" ? (
                          <XCircle className="mt-0.5 h-4 w-4 text-rose-400" />
                        ) : (
                          <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-300" />
                        )}
                        <div>
                          <div className="font-semibold text-slate-200">
                            {item.label}
                          </div>
                          <div className="text-[11px] text-slate-400">
                            {item.message}
                          </div>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-[11px] text-slate-400">
                      Validation results will appear after refresh.
                    </div>
                  )}
                </div>
              </div>
              {metrics && (
                <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                  <div className="uppercase tracking-wide text-slate-400">
                    Metrics
                  </div>
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <div className="flex items-center justify-between">
                      <span>Total notional</span>
                      <span className="font-mono">
                        {formatNotional(metrics.total_notional)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Total premium</span>
                      <span className="font-mono">
                        {formatMetricValue(metrics.total_premium, 3)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>DV01</span>
                      <span className="font-mono">
                        {formatMetricValue(metrics.total_dv01, 3)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Vega01</span>
                      <span className="font-mono">
                        {formatMetricValue(metrics.total_vega01, 3)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Time spread</span>
                      <span className="font-mono">
                        {formatDurationSeconds(metrics.time_spread_seconds)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Trades</span>
                      <span className="font-mono">
                        {metrics.trade_count ?? "--"}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                <div className="uppercase tracking-wide text-slate-400">
                  Link Details
                </div>
                <div className="mt-3 space-y-3">
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      User
                    </span>
                    <input
                      value={currentUser}
                      onChange={(event) => onUserChange(event.target.value)}
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      placeholder="username or email"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      Package Type
                    </span>
                    <select
                      value={packageType}
                      onChange={(event) => setPackageType(event.target.value)}
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      {MANUAL_PACKAGE_TYPES.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      Link Reason
                    </span>
                    <select
                      value={linkReason}
                      onChange={(event) => setLinkReason(event.target.value)}
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                    >
                      {MANUAL_LINK_REASONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      Tags
                    </span>
                    <div className="mt-1 flex gap-2">
                      <input
                        value={tagInput}
                        onChange={(event) => setTagInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            addTag();
                          }
                        }}
                        className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        placeholder="comma or enter separated tags"
                      />
                      <button
                        type="button"
                        onClick={addTag}
                        className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500"
                      >
                        Add
                      </button>
                    </div>
                    {tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {tags.map((tag) => (
                          <span
                            key={tag}
                            className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200"
                          >
                            {tag}
                            <button
                              type="button"
                              onClick={() => removeTag(tag)}
                              className="text-slate-400 hover:text-slate-200"
                              aria-label={`Remove ${tag}`}
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </label>
                  <label className="block">
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      Comment
                    </span>
                    <textarea
                      value={comment}
                      onChange={(event) => setComment(event.target.value)}
                      rows={4}
                      className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                      placeholder="Add context for this manual link"
                    />
                  </label>
                </div>
              </div>
              {error && (
                <div className="rounded border border-rose-800/70 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
                  {error}
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3 text-xs">
          <div className="text-slate-400">
            {selectedSummaries.length < 2
              ? "Select at least two trades to enable linking."
              : hasValidationErrors
                ? "Resolve validation errors before creating the link."
                : "Ready to create a manual link."}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 transition hover:border-slate-500"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreate}
              disabled={
                submitting ||
                selectedSummaries.length < 2 ||
                hasValidationErrors ||
                !currentUser
              }
              className="rounded border border-emerald-500/60 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create Link"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ManualLinkDetailsModal({
  isOpen,
  linkId,
  currentUser,
  onUserChange,
  onClose,
  onUpdated,
}: {
  isOpen: boolean;
  linkId: string | null;
  currentUser: string;
  onUserChange: (value: string) => void;
  onClose: () => void;
  onUpdated: () => void;
}) {
  const [linkDetail, setLinkDetail] = useState<ManualLinkDetail | null>(null);
  const [trades, setTrades] = useState<ManualLinkTrade[]>([]);
  const [history, setHistory] = useState<ManualLinkHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [packageType, setPackageType] = useState("");
  const [linkReason, setLinkReason] = useState("");
  const [comment, setComment] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [addTradesInput, setAddTradesInput] = useState("");
  const [removeTradesInput, setRemoveTradesInput] = useState("");
  const [deactivateReason, setDeactivateReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [deactivating, setDeactivating] = useState(false);

  const manualColor = manualLinkColor(linkId);
  const metricEntries = linkDetail?.link_metrics
    ? Object.entries(linkDetail.link_metrics)
    : [];

  const addTag = useCallback(() => {
    const next = tagInput.trim();
    if (!next) return;
    if (tags.includes(next)) {
      setTagInput("");
      return;
    }
    setTags((prev) => [...prev, next]);
    setTagInput("");
  }, [tagInput, tags]);

  const removeTag = useCallback((tag: string) => {
    setTags((prev) => prev.filter((item) => item !== tag));
  }, []);

  const fetchLinkDetails = useCallback(async () => {
    if (!linkId) return;
    setLoading(true);
    setError(null);
    setLinkDetail(null);
    setTrades([]);
    setHistory([]);
    try {
      const res = await fetch(`/api/swaption/links/${linkId}`);
      const payload = await res.json();
      if (!res.ok) {
        setError(payload?.error || "Failed to load manual link.");
        return;
      }
      setLinkDetail(payload.link as ManualLinkDetail);
      setTrades(dedupeManualTrades(payload.trades || []));
      setHistory(payload.history || []);
    } catch (err: any) {
      setError(err?.message || "Failed to load manual link.");
    } finally {
      setLoading(false);
    }
  }, [linkId]);

  const handleSave = useCallback(async () => {
    if (!linkId) return;
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, any> = {
        user: currentUser || undefined,
        package_type: packageType || undefined,
        link_reason: linkReason || undefined,
        comment: comment || undefined,
        tags,
      };
      const addTrades = parseIdList(addTradesInput);
      const removeTrades = parseIdList(removeTradesInput);
      if (addTrades.length) payload.add_trades = addTrades;
      if (removeTrades.length) payload.remove_trades = removeTrades;

      const res = await fetch(`/api/swaption/links/${linkId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const responsePayload = await res.json();
      if (!res.ok) {
        setError(responsePayload?.error || "Failed to update manual link.");
        return;
      }
      setAddTradesInput("");
      setRemoveTradesInput("");
      await fetchLinkDetails();
      onUpdated();
    } catch (err: any) {
      setError(err?.message || "Failed to update manual link.");
    } finally {
      setSaving(false);
    }
  }, [
    addTradesInput,
    comment,
    currentUser,
    fetchLinkDetails,
    linkId,
    linkReason,
    onUpdated,
    packageType,
    removeTradesInput,
    tags,
  ]);

  const handleDeactivate = useCallback(async () => {
    if (!linkId) return;
    setDeactivating(true);
    setError(null);
    try {
      const res = await fetch(`/api/swaption/links/${linkId}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user: currentUser || undefined,
          reason: deactivateReason || undefined,
        }),
      });
      const responsePayload = await res.json();
      if (!res.ok) {
        setError(responsePayload?.error || "Failed to deactivate link.");
        return;
      }
      onUpdated();
      onClose();
    } catch (err: any) {
      setError(err?.message || "Failed to deactivate link.");
    } finally {
      setDeactivating(false);
    }
  }, [currentUser, deactivateReason, linkId, onClose, onUpdated]);

  useEffect(() => {
    if (!isOpen) return;
    fetchLinkDetails();
  }, [fetchLinkDetails, isOpen]);

  useEffect(() => {
    if (!linkDetail) return;
    setPackageType(linkDetail.package_type || "");
    setLinkReason(linkDetail.link_reason || "");
    setComment(linkDetail.user_comment || "");
    setTags(Array.isArray(linkDetail.tags) ? linkDetail.tags : []);
    setTagInput("");
  }, [linkDetail]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
      <div className="w-full max-w-4xl overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: manualColor || "#64748b" }}
            />
            Manual Link Details
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 p-1 text-slate-300 transition hover:border-slate-500 hover:text-slate-100"
            aria-label="Close manual link details"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-300">
              <RefreshCw className="h-4 w-4 animate-spin" />
              Loading manual link...
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="text-[11px] uppercase tracking-wide text-slate-400">
                      Manual Package
                    </div>
                    <div className="text-sm font-semibold text-slate-100">
                      {linkDetail?.manual_package_id || "--"}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {linkDetail?.is_active ? "Active" : "Inactive"}
                    </div>
                  </div>
                  <div className="space-y-1 text-right">
                    <div className="text-[11px] uppercase tracking-wide text-slate-400">
                      Created
                    </div>
                    <div className="text-[11px] text-slate-200">
                      {linkDetail?.created_by || "--"}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {formatTimestamp(linkDetail?.created_at)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Edit Link
                    </div>
                    <div className="mt-3 space-y-3">
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          User
                        </span>
                        <input
                          value={currentUser}
                          onChange={(event) =>
                            onUserChange(event.target.value)
                          }
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          placeholder="username or email"
                        />
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Package Type
                        </span>
                        <select
                          value={packageType}
                          onChange={(event) =>
                            setPackageType(event.target.value)
                          }
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        >
                          {MANUAL_PACKAGE_TYPES.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Link Reason
                        </span>
                        <select
                          value={linkReason}
                          onChange={(event) => setLinkReason(event.target.value)}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        >
                          {MANUAL_LINK_REASONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Tags
                        </span>
                        <div className="mt-1 flex gap-2">
                          <input
                            value={tagInput}
                            onChange={(event) => setTagInput(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                addTag();
                              }
                            }}
                            className="flex-1 rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="comma or enter separated tags"
                          />
                          <button
                            type="button"
                            onClick={addTag}
                            className="rounded border border-slate-700 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500"
                          >
                            Add
                          </button>
                        </div>
                        {tags.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {tags.map((tag) => (
                              <span
                                key={tag}
                                className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200"
                              >
                                {tag}
                                <button
                                  type="button"
                                  onClick={() => removeTag(tag)}
                                  className="text-slate-400 hover:text-slate-200"
                                  aria-label={`Remove ${tag}`}
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              </span>
                            ))}
                          </div>
                        )}
                      </label>
                      <label className="block">
                        <span className="text-[11px] uppercase tracking-wide text-slate-400">
                          Comment
                        </span>
                        <textarea
                          value={comment}
                          onChange={(event) => setComment(event.target.value)}
                          rows={3}
                          className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                          placeholder="Add context for this manual link"
                        />
                      </label>
                      <div className="grid gap-2 md:grid-cols-2">
                        <label className="block">
                          <span className="text-[11px] uppercase tracking-wide text-slate-400">
                            Add Trades
                          </span>
                          <input
                            value={addTradesInput}
                            onChange={(event) =>
                              setAddTradesInput(event.target.value)
                            }
                            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="trade or package ids"
                          />
                        </label>
                        <label className="block">
                          <span className="text-[11px] uppercase tracking-wide text-slate-400">
                            Remove Trades
                          </span>
                          <input
                            value={removeTradesInput}
                            onChange={(event) =>
                              setRemoveTradesInput(event.target.value)
                            }
                            className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                            placeholder="trade or package ids"
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        onClick={handleSave}
                        disabled={saving || !currentUser || !linkDetail}
                        className="rounded border border-emerald-500/60 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
                      >
                        {saving ? "Saving..." : "Save Changes"}
                      </button>
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Deactivate Link
                    </div>
                    <div className="mt-2 flex flex-col gap-2">
                      <input
                        value={deactivateReason}
                        onChange={(event) =>
                          setDeactivateReason(event.target.value)
                        }
                        className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-100"
                        placeholder="Reason for deactivation"
                      />
                      <button
                        type="button"
                        onClick={handleDeactivate}
                        disabled={deactivating || !currentUser || !linkDetail}
                        className="rounded border border-rose-500/60 bg-rose-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                      >
                        {deactivating ? "Deactivating..." : "Deactivate Link"}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Linked Trades
                    </div>
                    <div className="mt-2 space-y-2">
                      {trades.length ? (
                        trades.map((trade) => (
                          <div
                            key={trade.trade_id}
                            className="rounded border border-slate-800/70 bg-slate-900/60 px-2 py-1"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono">
                                {trade.trade_id}
                              </span>
                              <span className="text-[10px] uppercase text-slate-400">
                                {trade.product_type || "N/A"}
                              </span>
                            </div>
                            <div className="text-[11px] text-slate-300">
                              {trade.trade_label || "--"}
                            </div>
                            <div className="flex items-center justify-between text-[10px] text-slate-500">
                              <span>{trade.package_id}</span>
                              <span>
                                {formatNotional(trade.notional ?? null)}
                              </span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-slate-400">
                          No linked trades found.
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      Metrics
                    </div>
                    <div className="mt-2 space-y-2">
                      {metricEntries.length ? (
                        metricEntries.map(([key, value]) => (
                          <div
                            key={key}
                            className="flex items-center justify-between"
                          >
                            <span className="text-[11px] uppercase text-slate-400">
                              {key.replace(/_/g, " ")}
                            </span>
                            <span className="font-mono">
                              {formatManualMetricValue(value)}
                            </span>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-slate-400">
                          No metrics stored.
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-300">
                    <div className="uppercase tracking-wide text-slate-400">
                      History
                    </div>
                    <div className="mt-2 space-y-2">
                      {history.length ? (
                        history.map((item) => (
                          <div
                            key={item.history_id}
                            className="rounded border border-slate-800/70 bg-slate-900/60 px-2 py-1"
                          >
                            <div className="flex items-center justify-between text-[11px] text-slate-200">
                              <span className="font-semibold">
                                {item.action}
                              </span>
                              <span className="text-slate-500">
                                {formatTimestamp(item.changed_at)}
                              </span>
                            </div>
                            <div className="text-[10px] text-slate-400">
                              {item.changed_by}
                            </div>
                            {item.change_details && (
                              <pre className="mt-1 whitespace-pre-wrap rounded border border-slate-800 bg-slate-950/60 px-2 py-1 text-[10px] text-slate-400">
                                {JSON.stringify(item.change_details, null, 2)}
                              </pre>
                            )}
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-slate-400">
                          No history entries yet.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              {error && (
                <div className="rounded border border-rose-800/70 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
                  {error}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PackageRow({
  row,
  seriesRows,
}: {
  row: TapeRow;
  seriesRows: TapeRow[];
}) {
  return (
    <div
      className={`ml-6 rounded-lg border border-slate-800/80 ${NESTED_TABLE_BG} shadow-[inset_0_1px_0_rgba(148,163,184,0.08)]`}
    >
      <LegsSubtable row={row} seriesRows={seriesRows} />
    </div>
  );
}

export default function SwaptionTradeTape() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [rows, setRows] = useState<TapeRow[]>([]);
  const [manualLinks, setManualLinks] = useState<ManualLinkRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter] = useState("");
  const [filters, setFilters] = useState<DataTableFilterMeta>(() =>
    parseColumnFilterPayload(searchParams.get(COLUMN_FILTER_QUERY_KEY)),
  );
  const [columnFilterOperator, setColumnFilterOperator] = useState(() =>
    parseColumnFilterOperator(
      searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY),
    ),
  );
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [sortField, setSortField] = useState<string>("execution_start");
  const [sortOrder, setSortOrder] = useState<1 | -1 | 0>(-1);
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>(
    {},
  );
  const [selectedRows, setSelectedRows] = useState<TapeRow[]>([]);
  const [selectedPackageIds, setSelectedPackageIds] = useState<string[]>(() =>
    parseSelectedPackageIds(searchParams.get(SELECTED_PACKAGES_QUERY_KEY)),
  );
  const [showSelectedOnly, setShowSelectedOnly] = useState<boolean>(() =>
    parseBooleanQueryFlag(searchParams.get(SELECTED_ONLY_QUERY_KEY)),
  );
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [detailLinkId, setDetailLinkId] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState("");
  const [showManualLinksOnly, setShowManualLinksOnly] = useState(false);
  const [metricMode, setMetricMode] = useState<"NOTIONAL" | "VEGA">(
    "NOTIONAL",
  );
  const [showSequencePanel, setShowSequencePanel] = useState(false);
  const latestRef = useRef<string | null>(null);
  const fetchInFlight = useRef(false);
  const columnFilterPayload = useMemo(
    () => buildColumnFilterPayload(filters),
    [filters],
  );
  const columnFilterPayloadKey = useMemo(
    () => JSON.stringify(columnFilterPayload),
    [columnFilterPayload],
  );
  const selectedPackageIdsKey = useMemo(
    () => serializeSelectedPackageIds(selectedPackageIds),
    [selectedPackageIds],
  );
  const selectedPackageIdSet = useMemo(
    () => new Set(selectedPackageIds),
    [selectedPackageIds],
  );
  const columnFilterPayloadKeyRef = useRef(columnFilterPayloadKey);
  const columnFilterOperatorRef = useRef(columnFilterOperator);
  const selectedPackageIdsKeyRef = useRef(selectedPackageIdsKey);
  const showSelectedOnlyRef = useRef(showSelectedOnly);

  const upsertRows = useCallback((incoming: TapeRow[], replace = false) => {
    setRows((prev) => {
      const map = new Map<string, TapeRow>();
      if (!replace) {
        prev.forEach((row) => map.set(row.package_id, row));
      }
      incoming.forEach((row) => map.set(row.package_id, row));
      const merged = Array.from(map.values()).sort(
        (a, b) =>
          new Date(b.execution_start).getTime() -
          new Date(a.execution_start).getTime(),
      );
      if (merged.length > 0) {
        latestRef.current = merged[0].execution_start;
      }
      return merged;
    });
  }, []);

  const fetchTape = useCallback(
    async ({
      cursor,
      since,
      replace = false,
    }: {
      cursor?: string | null;
      since?: string | null;
      replace?: boolean;
    } = {}) => {
      if (fetchInFlight.current) {
        if (replace) setLoading(false);
        setLoadingMore(false);
        return;
      }
      fetchInFlight.current = true;
      try {
        if (replace) setLoading(true);
        setError(null);
        const params = new URLSearchParams();
        params.set("limit", "50");
        if (filter) params.set("filter", filter);
        if (columnFilterPayloadKey !== "{}") {
          params.set(COLUMN_FILTER_QUERY_KEY, columnFilterPayloadKey);
        }
        if (columnFilterOperator !== FilterOperator.AND) {
          params.set(COLUMN_FILTER_OPERATOR_QUERY_KEY, columnFilterOperator);
        }
        if (cursor) params.set("cursor", cursor);
        if (since) params.set("since", since);

        const res = await fetch(`/api/swaptions-tape?${params.toString()}`);
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || "Failed to load trade tape");
        }

        const data: TapeResponse = await res.json();
        if (replace) {
          setRows(data.rows);
          latestRef.current = data.latestExecutionStart;
        } else if (since) {
          upsertRows(data.rows, false);
        } else {
          upsertRows(data.rows, false);
        }

        if (!since) {
          setNextCursor(data.nextCursor);
          setHasMore(data.hasMore);
        }

        if (data.latestExecutionStart) {
          latestRef.current = data.latestExecutionStart;
        }
      } catch (err: any) {
        setError(err?.message || "Failed to load trade tape");
      } finally {
        fetchInFlight.current = false;
        if (replace) setLoading(false);
        setLoadingMore(false);
      }
    },
    [filter, columnFilterPayloadKey, columnFilterOperator, upsertRows],
  );

  useEffect(() => {
    const stored =
      typeof window !== "undefined"
        ? window.localStorage.getItem("swaptionManualUser")
        : null;
    if (stored) {
      setCurrentUser(stored);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (currentUser) {
      window.localStorage.setItem("swaptionManualUser", currentUser);
    } else {
      window.localStorage.removeItem("swaptionManualUser");
    }
  }, [currentUser]);

  useEffect(() => {
    const rowById = new Map<string, TapeRow>();
    rows.forEach((row) => rowById.set(row.package_id, row));
    const nextSelectedRows = selectedPackageIds
      .map((packageId) => rowById.get(packageId))
      .filter((row): row is TapeRow => !!row);
    const nextSelectionKey = serializeSelectedPackageIds(
      nextSelectedRows.map((row) => row.package_id),
    );
    setSelectedRows((prev) => {
      const prevSelectionKey = serializeSelectedPackageIds(
        prev.map((row) => row.package_id),
      );
      if (prevSelectionKey === nextSelectionKey) return prev;
      return nextSelectedRows;
    });
  }, [rows, selectedPackageIds]);

  useEffect(() => {
    columnFilterPayloadKeyRef.current = columnFilterPayloadKey;
  }, [columnFilterPayloadKey]);

  useEffect(() => {
    columnFilterOperatorRef.current = columnFilterOperator;
  }, [columnFilterOperator]);

  useEffect(() => {
    selectedPackageIdsKeyRef.current = selectedPackageIdsKey;
  }, [selectedPackageIdsKey]);

  useEffect(() => {
    showSelectedOnlyRef.current = showSelectedOnly;
  }, [showSelectedOnly]);

  useEffect(() => {
    if (!selectedPackageIds.length && showSelectedOnly) {
      setShowSelectedOnly(false);
    }
  }, [selectedPackageIds.length, showSelectedOnly]);

  useEffect(() => {
    if (selectedRows.length < 2 && showSequencePanel) {
      setShowSequencePanel(false);
    }
  }, [selectedRows.length, showSequencePanel]);

  useEffect(() => {
    const nextFilters = parseColumnFilterPayload(
      searchParams.get(COLUMN_FILTER_QUERY_KEY),
    );
    const nextFiltersKey = JSON.stringify(
      buildColumnFilterPayload(nextFilters),
    );
    if (nextFiltersKey !== columnFilterPayloadKeyRef.current) {
      setFilters(nextFilters);
    }
    const nextOperator = parseColumnFilterOperator(
      searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY),
    );
    if (nextOperator !== columnFilterOperatorRef.current) {
      setColumnFilterOperator(nextOperator);
    }
    const nextSelectedPackageIds = parseSelectedPackageIds(
      searchParams.get(SELECTED_PACKAGES_QUERY_KEY),
    );
    const nextSelectedPackageIdsKey = serializeSelectedPackageIds(
      nextSelectedPackageIds,
    );
    if (nextSelectedPackageIdsKey !== selectedPackageIdsKeyRef.current) {
      setSelectedPackageIds(nextSelectedPackageIds);
    }
    const nextShowSelectedOnly = parseBooleanQueryFlag(
      searchParams.get(SELECTED_ONLY_QUERY_KEY),
    );
    if (nextShowSelectedOnly !== showSelectedOnlyRef.current) {
      setShowSelectedOnly(nextShowSelectedOnly);
    }
  }, [searchParams]);

  useEffect(() => {
    const currentQuery = searchParams.toString();
    const nextParams = new URLSearchParams(currentQuery);
    if (columnFilterPayloadKey !== "{}") {
      nextParams.set(COLUMN_FILTER_QUERY_KEY, columnFilterPayloadKey);
    } else {
      nextParams.delete(COLUMN_FILTER_QUERY_KEY);
    }
    if (columnFilterOperator !== FilterOperator.AND) {
      nextParams.set(COLUMN_FILTER_OPERATOR_QUERY_KEY, columnFilterOperator);
    } else {
      nextParams.delete(COLUMN_FILTER_OPERATOR_QUERY_KEY);
    }
    if (selectedPackageIdsKey) {
      nextParams.set(SELECTED_PACKAGES_QUERY_KEY, selectedPackageIdsKey);
    } else {
      nextParams.delete(SELECTED_PACKAGES_QUERY_KEY);
    }
    if (showSelectedOnly) {
      nextParams.set(SELECTED_ONLY_QUERY_KEY, "1");
    } else {
      nextParams.delete(SELECTED_ONLY_QUERY_KEY);
    }
    const nextQuery = nextParams.toString();
    if (nextQuery !== currentQuery) {
      const nextUrl = nextQuery ? `${pathname}?${nextQuery}` : pathname;
      router.replace(nextUrl);
    }
  }, [
    columnFilterOperator,
    columnFilterPayloadKey,
    pathname,
    router,
    selectedPackageIdsKey,
    showSelectedOnly,
    searchParams,
  ]);

  const manualLinkStartDate = useMemo(() => {
    if (!rows.length) return null;
    let minTime = Number.POSITIVE_INFINITY;
    rows.forEach((row) => {
      const ts = new Date(row.execution_start).getTime();
      if (!Number.isNaN(ts) && ts < minTime) {
        minTime = ts;
      }
    });
    if (!Number.isFinite(minTime)) return null;
    const start = new Date(minTime);
    start.setDate(start.getDate() - 2);
    return start.toISOString();
  }, [rows]);

  const manualLinkFetchRef = useRef<string | null>(null);

  const fetchManualLinks = useCallback(async (startDate?: string | null) => {
    try {
      const params = new URLSearchParams();
      params.set("is_active", "true");
      params.set("limit", "1000");
      if (startDate) params.set("start_date", startDate);
      const res = await fetch(`/api/swaption/links?${params.toString()}`);
      if (!res.ok) return;
      const payload = await res.json();
      const rows = Array.isArray(payload?.rows) ? payload.rows : [];
      setManualLinks(rows as ManualLinkRow[]);
    } catch {
      // Silent fail; manual links are a visual enhancement.
    }
  }, []);

  useEffect(() => {
    if (!manualLinkStartDate) return;
    const prior = manualLinkFetchRef.current;
    if (prior) {
      const priorTime = new Date(prior).getTime();
      const nextTime = new Date(manualLinkStartDate).getTime();
      if (!Number.isNaN(priorTime) && !Number.isNaN(nextTime)) {
        if (nextTime >= priorTime) return;
      }
    }
    manualLinkFetchRef.current = manualLinkStartDate;
    fetchManualLinks(manualLinkStartDate);
  }, [fetchManualLinks, manualLinkStartDate]);

  const manualLinkIndex = useMemo(() => {
    const byTradeId = new Map<string, ManualLinkRow[]>();
    const byLinkId = new Map<string, Set<string>>();
    manualLinks.forEach((link) => {
      let ids: string[] = [];
      if (Array.isArray(link.linked_trade_ids)) {
        ids = link.linked_trade_ids;
      } else if (typeof link.linked_trade_ids === "string") {
        const raw = link.linked_trade_ids.trim();
        if (raw.startsWith("[") && raw.endsWith("]")) {
          try {
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
              ids = parsed.map((entry) => String(entry));
            }
          } catch {
            ids = raw.split(/[,\s]+/);
          }
        } else if (raw.startsWith("{") && raw.endsWith("}")) {
          ids = raw
            .slice(1, -1)
            .split(",")
            .map((entry: string) => entry.replace(/^"+|"+$/g, ""));
        } else {
          ids = raw.split(/[,\s]+/);
        }
      }
      const normalizedIds = ids
        .map((id) => String(id || "").trim())
        .filter(Boolean);
      if (!normalizedIds.length || !link.link_id) return;
      byLinkId.set(link.link_id, new Set(normalizedIds));
      normalizedIds.forEach((id) => {
        const normalized = String(id || "").trim();
        if (normalized) {
          const existing = byTradeId.get(normalized);
          if (existing) {
            existing.push(link);
          } else {
            byTradeId.set(normalized, [link]);
          }
        }
      });
    });
    return { byTradeId, byLinkId };
  }, [manualLinks]);

  const resolvedRows = useMemo(() => {
    if (!manualLinkIndex.byTradeId.size) return rows;
    return rows.map((row) => {
      if (row.manual_link_id || row.manual_package_id) return row;
      const tradeIds = new Set<string>();
      (row.legs_json || []).forEach((leg) => {
        if (leg.trade_id) tradeIds.add(leg.trade_id);
      });
      const tradeIdList = Array.from(tradeIds);
      if (!tradeIdList.length) return row;
      const candidates = manualLinkIndex.byTradeId.get(tradeIdList[0]) || [];
      let matched: ManualLinkRow | null = null;
      for (const candidate of candidates) {
        const set = manualLinkIndex.byLinkId.get(candidate.link_id);
        if (!set) continue;
        const coversAll = tradeIdList.every((id) => set.has(id));
        if (!coversAll) continue;
        if (matched) {
          matched = null;
          break;
        }
        matched = candidate;
      }
      if (!matched) return row;
      return {
        ...row,
        manual_link_id: matched.link_id ?? row.manual_link_id ?? null,
        manual_package_id:
          matched.manual_package_id ?? row.manual_package_id ?? null,
      };
    });
  }, [manualLinkIndex, rows]);

  const sequenceClusters = useMemo(
    () =>
      detectSequenceClusters(
        resolvedRows,
        SEQUENCE_CLUSTER_MAX_GAP_MINUTES,
        SEQUENCE_CLUSTER_MIN_TRADES,
      ),
    [resolvedRows],
  );

  const clusterByPackageId = useMemo(() => {
    const map = new Map<string, SequenceCluster>();
    sequenceClusters.forEach((cluster) => {
      cluster.rows.forEach((row) => {
        map.set(row.package_id, cluster);
      });
    });
    return map;
  }, [sequenceClusters]);

  const selectedCluster = useMemo(() => {
    if (selectedRows.length < 2) return null;
    const first = selectedRows[0];
    if (!first) return null;
    const cluster = clusterByPackageId.get(first.package_id);
    if (!cluster) return null;
    const isSameCluster = selectedRows.every(
      (row) => clusterByPackageId.get(row.package_id)?.id === cluster.id,
    );
    return isSameCluster ? cluster : null;
  }, [clusterByPackageId, selectedRows]);

  const singleSelectionCluster = useMemo(() => {
    if (selectedRows.length !== 1) return null;
    const first = selectedRows[0];
    if (!first) return null;
    return clusterByPackageId.get(first.package_id) ?? null;
  }, [clusterByPackageId, selectedRows]);

  const buildTradeLabel = useCallback(
    (row: TapeRow) => buildRichLabel(row),
    [],
  );

  const firstLegMetrics = useCallback((row: TapeRow) => {
    const leg = (row.legs_json || [])[0] as any;
    const metrics = leg?.leg_metrics || {};
    return {
      platform:
        metrics.platform_identifier ||
        metrics.platform ||
        leg?.platform_identifier ||
        row.platform_identifier ||
        row.package_metrics?.platform_identifier,
      event_action: extractPrimaryAction(row),
    };
  }, []);

  const resolveDisplayNotional = useCallback((row: TapeRow) => {
    return computeDisplayNotional(row);
  }, []);

  const resolveDisplayVega = useCallback((row: TapeRow) => {
    const metrics = row.package_metrics || {};
    const packageType = normalizePackageType(row.package_type);
    const vegaCurveValue = parseMetricSeries((metrics as any).vega_curve_vega01);
    if (vegaCurveValue !== null) return vegaCurveValue;

    if (packageType === "STRADDLE") {
      const direct = parseMetricSeries((metrics as any).straddle_vega01);
      if (direct !== null) return direct;
      const legs = row.legs_json || [];
      return parseMetricSeries((legs[0] as any)?.leg_metrics?.straddle_vega01);
    }

    if (packageType === "RISK_REVERSAL") {
      return parseMetricSeries((metrics as any).rr_vega01);
    }

    if (
      packageType === "VERTICAL_SPREAD_1X1" ||
      packageType === "VERTICAL_SPREAD_1X2"
    ) {
      const netVega = parseMetricSeries((metrics as any).vs_vega01);
      if (netVega !== null) return netVega;
      const atmVega = parseMetricSeries((metrics as any).vs_atm_vega01);
      const otmVega = parseMetricSeries((metrics as any).vs_otm_vega01);
      if (atmVega !== null || otmVega !== null) {
        return (atmVega ?? 0) + (otmVega ?? 0);
      }
      return null;
    }

    if (packageType === "OUTRIGHT") {
      const legMetrics = (row.legs_json || [])[0]?.leg_metrics || {};
      return parseMetricSeries((legMetrics as any).outright_vega01);
    }

    const legs = row.legs_json || [];
    let total: number | null = null;
    legs.forEach((leg) => {
      const legMetrics = (leg as any)?.leg_metrics || {};
      const legVega =
        parseMetricSeries(legMetrics.outright_vega01) ??
        parseMetricSeries(legMetrics.straddle_vega01) ??
        parseMetricSeries(legMetrics.rr_vega01) ??
        parseMetricSeries(legMetrics.vs_vega01) ??
        parseMetricSeries(legMetrics.vs_atm_vega01) ??
        parseMetricSeries(legMetrics.vs_otm_vega01) ??
        parseMetricSeries(legMetrics.vega01);
      if (legVega === null) return;
      total = total === null ? legVega : total + legVega;
    });
    return total;
  }, []);

  const resolveFilterValue = useCallback(
    (row: TapeRow, field: string) => {
      switch (field) {
        case "action":
          return firstLegMetrics(row).event_action || "";
        case "package_type":
          return row.package_type || "";
        case "time":
          return buildExecutionTimeFilterValue(
            row.execution_start,
            row.execution_end,
          );
        case "platform":
          return firstLegMetrics(row).platform || "";
        case "notional":
          return resolveDisplayNotional(row);
        case "label":
          return buildTradeLabel(row);
        default:
          return (row as any)[field];
      }
    },
    [buildTradeLabel, firstLegMetrics, resolveDisplayNotional],
  );

  const sortRowsByField = useCallback(
    (data: TapeRow[], field: string, order: 1 | -1 | 0) => {
      if (!field || order === 0) return data;
      const sorted = [...data].sort((a, b) => {
        const av = (a as any)[field];
        const bv = (b as any)[field];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        if (typeof av === "number" && typeof bv === "number") {
          return order === 1 ? av - bv : bv - av;
        }
        const aStr = String(av).toLowerCase();
        const bStr = String(bv).toLowerCase();
        if (aStr === bStr) return 0;
        return order === 1 ? (aStr > bStr ? 1 : -1) : aStr < bStr ? 1 : -1;
      });
      return sorted;
    },
    [],
  );

  const filteredRows = useMemo(() => {
    const activeFilters = Object.entries(filters || {}).filter(
      ([field, filterMeta]) =>
        field !== "global" && hasActiveConstraints(filterMeta),
    );
    const filtered = resolvedRows.filter((row) => {
      if (!activeFilters.length) return true;
      const matches = activeFilters.map(([field, filterMeta]) => {
        const rowValue = resolveFilterValue(row, field);
        return matchFilterMeta(rowValue, filterMeta);
      });
      return columnFilterOperator === FilterOperator.OR
        ? matches.some(Boolean)
        : matches.every(Boolean);
    });
    const manualFiltered = showManualLinksOnly
      ? filtered.filter(
          (row) => !!row.manual_package_id || !!row.manual_link_id,
        )
      : filtered;
    const selectedFiltered = showSelectedOnly
      ? manualFiltered.filter((row) => selectedPackageIdSet.has(row.package_id))
      : manualFiltered;
    if (!sortField || sortOrder === 0) return groupLinkedRows(selectedFiltered);
    const sorted = sortRowsByField(selectedFiltered, sortField, sortOrder);
    return groupLinkedRows(sorted);
  }, [
    resolvedRows,
    filters,
    resolveFilterValue,
    sortField,
    sortOrder,
    columnFilterOperator,
    showManualLinksOnly,
    showSelectedOnly,
    selectedPackageIdSet,
    sortRowsByField,
  ]);


  useEffect(() => {
    setRows([]);
    setNextCursor(null);
    fetchTape({ replace: true });
  }, [filter, fetchTape]);

  useEffect(() => {
    const id = setInterval(() => {
      if (latestRef.current) {
        fetchTape({ since: latestRef.current });
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchTape]);

  useEffect(() => {
    // Keep legacy auto-load when filtered list is very short
    const visibleRows = Math.ceil((0.7 * 1000) / ROW_ESTIMATE_PX); // approximate 70vh height
    if (
      hasMore &&
      !loadingMore &&
      !fetchInFlight.current &&
      nextCursor &&
      filteredRows.length < visibleRows + 5
    ) {
      setLoadingMore(true);
      fetchTape({ cursor: nextCursor });
    }
  }, [filteredRows.length, hasMore, loadingMore, nextCursor, fetchTape]);

  const actionTone = (action: string | null) => {
    if (!action) return "";
    const upper = action.toUpperCase();
    return ACTION_TONES[upper] || "";
  };

  const handleVirtualLoad = useCallback(
    (event: any) => {
      const last =
        typeof event.last === "number"
          ? event.last
          : (event.first || 0) + (event.rows || 0);
      if (
        hasMore &&
        !loadingMore &&
        !fetchInFlight.current &&
        nextCursor &&
        last >= filteredRows.length - 5
      ) {
        setLoadingMore(true);
        fetchTape({ cursor: nextCursor });
      }
    },
    [filteredRows.length, fetchTape, hasMore, loadingMore, nextCursor],
  );

  const openManualLinkDetails = useCallback((linkId?: string | null) => {
    if (!linkId) return;
    setDetailLinkId(linkId);
    setDetailModalOpen(true);
  }, []);

  const closeManualLinkDetails = useCallback(() => {
    setDetailModalOpen(false);
    setDetailLinkId(null);
  }, []);

  const handleLinkCreated = useCallback(
    (result?: { link_id: string; manual_package_id: string }) => {
      if (result) {
        const linkedIds = new Set<string>();
        selectedRows.forEach((row) => {
          (row.legs_json || []).forEach((leg) => {
            if (leg.trade_id) linkedIds.add(leg.trade_id);
          });
        });
        if (linkedIds.size > 0) {
          setManualLinks((prev) => {
            const next = prev.filter((link) => link.link_id !== result.link_id);
            next.unshift({
              link_id: result.link_id,
              manual_package_id: result.manual_package_id,
              linked_trade_ids: Array.from(linkedIds),
              is_active: true,
              created_at: new Date().toISOString(),
            });
            return next;
          });
        }
      }
      setSelectedPackageIds([]);
      fetchTape({ replace: true });
      fetchManualLinks(manualLinkStartDate);
    },
    [fetchManualLinks, fetchTape, manualLinkStartDate, selectedRows],
  );

  const handleLinkUpdated = useCallback(() => {
    fetchTape({ replace: true });
    fetchManualLinks(manualLinkStartDate);
  }, [fetchManualLinks, fetchTape, manualLinkStartDate]);

  const rowClassName = (row: TapeRow) => {
    const metrics = firstLegMetrics(row);
    const action = metrics.event_action;
    const isActive = action ? ACTIVE_ACTIONS.has(action.toUpperCase()) : false;
    const isSelected = selectedPackageIdSet.has(row.package_id);
    const cluster = clusterByPackageId.get(row.package_id);
    const tone = isActive
      ? packageTone(row.package_type)
      : "!bg-red-900/70 !text-red-100";
    const warning = hasActionWarning(row);
    const isManualLinked = !!row.manual_link_id || !!row.manual_package_id;
    const classes = [
      "h-10 text-sm !text-gray-200 transition-[filter,box-shadow] hover:brightness-110 hover:shadow-[inset_0_0_0_1px_rgba(148,163,184,0.5)]",
      tone,
      actionTone(action),
      isManualLinked ? "manual-linked-row" : "",
      cluster ? "clustered-row" : "",
      isSelected ? "selected-share-row" : "",
      warning && isActive ? "ring-1 ring-red-500/50" : "",
    ];
    return classes.join(" ").trim();
  };


  const toggleRowExpansion = useCallback((row: TapeRow) => {
    if (!row.legs_json || row.legs_json.length === 0) return;
    setExpandedRows((previous) => {
      const next = { ...previous };
      const rowKey = row.package_id;
      if (next[rowKey]) {
        delete next[rowKey];
      } else {
        next[rowKey] = true;
      }
      return next;
    });
  }, []);

  const expanderBody = (row: TapeRow) => {
    const canExpand = (row.legs_json || []).length > 0;
    if (!canExpand) {
      return <span className="inline-flex h-6 w-6" />;
    }
    const isExpanded = !!expandedRows[row.package_id];
    return (
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          toggleRowExpansion(row);
        }}
        className="inline-flex h-6 w-6 items-center justify-center rounded border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100"
        aria-label={isExpanded ? "Collapse legs" : "Expand legs"}
      >
        {isExpanded ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
      </button>
    );
  };

  const rowExpansionTemplate = (row: TapeRow) => (
    <div className="-mx-2 -my-1 px-0 py-0">
      <PackageRow row={row} seriesRows={filteredRows} />
    </div>
  );

  const buildFilterSummary = useCallback(
    (filterField: string) => {
      const filterMeta = ((filters || {})[filterField] as any) || null;
      if (!hasActiveConstraints(filterMeta)) return null;
      const constraints = Array.isArray(filterMeta?.constraints)
        ? filterMeta.constraints
        : [
            {
              value: filterMeta?.value,
              matchMode: filterMeta?.matchMode,
            },
          ];
      const activeConstraints = constraints.filter(
        (constraint: any) => !isEmptyFilterValue(constraint?.value),
      );
      if (!activeConstraints.length) return null;
      const operatorLabel =
        (filterMeta?.operator || FilterOperator.AND) === FilterOperator.OR
          ? "OR"
          : "AND";
      return activeConstraints
        .map((constraint: any) => {
          const modeLabel = formatMatchModeLabel(constraint.matchMode);
          const valueLabel = formatFilterValue(constraint.value);
          return `${modeLabel} ${valueLabel}`;
        })
        .join(` ${operatorLabel} `);
    },
    [filters],
  );

  const renderColumnHeader = useCallback(
    (label: string, filterField?: string) => {
      const summary = filterField ? buildFilterSummary(filterField) : null;
      return (
        <div className="flex flex-col gap-0.5">
          <span className="text-[11px] uppercase tracking-wide text-gray-400">
            {label}
          </span>
          {summary && (
            <span className="text-[10px] text-gray-500 truncate">
              {summary}
            </span>
          )}
        </div>
      );
    },
    [buildFilterSummary],
  );

  const actionBody = (row: TapeRow) => {
    const action = firstLegMetrics(row).event_action;
    return (
      <span className="font-mono text-xs text-gray-100">{action || "--"}</span>
    );
  };

  const packageBody = (row: TapeRow) => {
    const warning = hasActionWarning(row);
    const manual = isManualPackage(row);
    const manualLinkId = row.manual_link_id;
    const manualColor = manualLinkColor(
      row.manual_link_id || row.manual_package_id,
    );
    const source = row.package_source?.toUpperCase();
    const sourceLabel = source === "HYBRID" ? "Hybrid" : "Manual";
    const manualBadgeClass =
      "inline-flex items-center gap-2 rounded-full border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-200";
    return (
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-2 rounded-full px-2 py-1 text-[11px] font-semibold bg-gray-700 text-gray-100 border border-gray-500/40">
          {row.package_type || "N/A"}
          {warning && <AlertTriangle className="h-3 w-3 text-amber-300" />}
        </span>
        {manual &&
          (manualLinkId ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                openManualLinkDetails(manualLinkId);
              }}
              className={`${manualBadgeClass} hover:border-slate-500`}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: manualColor || "#64748b" }}
              />
              <span>{sourceLabel}</span>
              {row.manual_package_id && (
                <span className="text-slate-400">
                  {row.manual_package_id}
                </span>
              )}
            </button>
          ) : (
            <span className={manualBadgeClass}>
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: manualColor || "#64748b" }}
              />
              <span>{sourceLabel}</span>
              {row.manual_package_id && (
                <span className="text-slate-400">
                  {row.manual_package_id}
                </span>
              )}
            </span>
          ))}
      </div>
    );
  };

  const timeBody = (row: TapeRow) => (
    <span className="text-xs text-gray-300">
      {formatExecutionWindow(row.execution_start, row.execution_end)}
    </span>
  );

  const platformBody = (row: TapeRow) => {
    const metrics = firstLegMetrics(row);
    return (
      <span className="text-xs text-gray-300 truncate">
        {metrics.platform || "--"}
      </span>
    );
  };

  const showVega = metricMode === "VEGA";
  const metricLabel = showVega ? "Vega" : "Notional";
  const metricColumnKey = showVega ? "metric-vega" : "metric-notional";

  const metricBody = (row: TapeRow) => {
    const value = showVega
      ? resolveDisplayVega(row)
      : resolveDisplayNotional(row);
    const isCapped = !showVega && isRowNotionalCapped(row);
    const formatted = showVega
      ? formatMetricValue(value, 3)
      : formatNotional(value);
    const suffix = isCapped && formatted !== "--" ? "+" : "";
    return (
      <span className="text-xs font-mono text-gray-200">
        {formatted}
        {suffix}
      </span>
    );
  };

  const labelBody = (row: TapeRow) => (
    <span className="text-xs font-mono text-gray-200">
      {buildTradeLabel(row)}
    </span>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-300">
          <span className="text-[11px] uppercase tracking-wide text-gray-400">
            Filter Combine
          </span>
          <div className="inline-flex overflow-hidden rounded border border-gray-700">
            <button
              type="button"
              onClick={() => setColumnFilterOperator(FilterOperator.AND)}
              className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                columnFilterOperator === FilterOperator.AND
                  ? "bg-gray-700 text-gray-100"
                  : "text-gray-300 hover:bg-gray-800"
              }`}
            >
              AND
            </button>
            <button
              type="button"
              onClick={() => setColumnFilterOperator(FilterOperator.OR)}
              className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                columnFilterOperator === FilterOperator.OR
                  ? "bg-gray-700 text-gray-100"
                  : "text-gray-300 hover:bg-gray-800"
              }`}
            >
              OR
            </button>
          </div>
          <button
            type="button"
            onClick={() =>
              setMetricMode((current) =>
                current === "NOTIONAL" ? "VEGA" : "NOTIONAL",
              )
            }
            className="rounded border border-gray-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-gray-200 transition hover:border-gray-500 hover:bg-gray-800"
          >
            Toggle Notional/Vega
          </button>
          <button
            type="button"
            onClick={() => setShowManualLinksOnly((current) => !current)}
            className={`rounded border px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
              showManualLinksOnly
                ? "border-yellow-400 bg-yellow-400/10 text-yellow-100"
                : "border-gray-700 text-gray-200 hover:border-gray-500 hover:bg-gray-800"
            }`}
          >
            Manual Links
          </button>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-300">
          <span className="text-[11px] uppercase tracking-wide text-gray-400">
            User
          </span>
          <input
            value={currentUser}
            onChange={(event) => setCurrentUser(event.target.value)}
            className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-100"
            placeholder="username or email"
          />
        </div>
      </div>
      {selectedPackageIds.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-300">
          <div className="flex items-center gap-2">
            <span className="font-mono">{selectedPackageIds.length}</span>
            trades selected
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex overflow-hidden rounded border border-slate-700">
              <button
                type="button"
                onClick={() => setShowSelectedOnly(true)}
                className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  showSelectedOnly
                    ? "bg-sky-500/20 text-sky-100"
                    : "text-slate-200 hover:bg-slate-800"
                }`}
              >
                Selected Only
              </button>
              <button
                type="button"
                onClick={() => setShowSelectedOnly(false)}
                className={`px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  !showSelectedOnly
                    ? "bg-slate-700 text-slate-100"
                    : "text-slate-200 hover:bg-slate-800"
                }`}
              >
                Show All
              </button>
            </div>
            <button
              type="button"
              onClick={() => {
                setSelectedPackageIds([]);
                setShowSelectedOnly(false);
                setShowSequencePanel(false);
              }}
              className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => setShowSequencePanel((current) => !current)}
              disabled={selectedRows.length < 2}
              className={`rounded border px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                showSequencePanel
                  ? "border-sky-400/70 bg-sky-500/15 text-sky-100"
                  : "border-slate-700 text-slate-200 hover:border-slate-500"
              }`}
            >
              {showSequencePanel ? "Hide Sequence" : "Show Sequence"}
            </button>
            {singleSelectionCluster && (
              <button
                type="button"
                onClick={() => {
                  setSelectedPackageIds(
                    normalizeSelectedPackageIds(
                      singleSelectionCluster.rows.map((row) => row.package_id),
                    ),
                  );
                  setShowSelectedOnly(true);
                  setShowSequencePanel(true);
                }}
                className="rounded border border-sky-500/60 bg-sky-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-sky-200 transition hover:bg-sky-500/20"
              >
                Select Cluster ({singleSelectionCluster.rows.length})
              </button>
            )}
            <button
              type="button"
              onClick={() => setLinkModalOpen(true)}
              disabled={selectedRows.length < 2}
              className="rounded border border-emerald-500/60 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
            >
              Link Selected
            </button>
          </div>
        </div>
      )}
      {selectedRows.length >= 2 && showSequencePanel && (
        <SequenceAnalysisPanel rows={selectedRows} cluster={selectedCluster} />
      )}
      <style jsx global>{`
        .p-column-filter-overlay,
        .p-column-filter-overlay * {
          font-size: 0.7rem !important;
        }
        .swaption-tape-table .p-datatable-tbody > tr,
        .swaption-tape-table .p-datatable-tbody > tr > td {
          border: none !important;
        }
        .swaption-tape-table
          .p-datatable-tbody
          > tr.manual-linked-row
          > td {
          background-color: rgba(245, 158, 11, 0.18) !important;
        }
        .swaption-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td {
          box-shadow:
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
        .swaption-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td:first-child {
          box-shadow:
            inset 1px 0 0 rgba(125, 211, 252, 0.4),
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
        .swaption-tape-table
          .p-datatable-tbody
          > tr.selected-share-row
          > td:last-child {
          box-shadow:
            inset -1px 0 0 rgba(125, 211, 252, 0.4),
            inset 0 1px 0 rgba(125, 211, 252, 0.4),
            inset 0 -1px 0 rgba(125, 211, 252, 0.4) !important;
        }
      `}</style>
      <DataTable
        key={`datatable-${metricMode}`}
        value={filteredRows}
        dataKey="package_id"
        selection={selectedRows}
        onSelectionChange={(e) => {
          const nextSelectedRows = ((e.value as TapeRow[]) || []).filter(
            (row): row is TapeRow => !!row,
          );
          setSelectedRows(nextSelectedRows);
          setSelectedPackageIds(
            normalizeSelectedPackageIds(
              nextSelectedRows.map((row) => row.package_id),
            ),
          );
        }}
        selectionMode="multiple"
        metaKeySelection={false}
        expandedRows={expandedRows}
        rowExpansionTemplate={rowExpansionTemplate}
        filters={filters}
        filterDisplay="menu"
        onFilter={(e) => setFilters(e.filters as DataTableFilterMeta)}
        lazy
        totalRecords={hasMore ? filteredRows.length + 50 : filteredRows.length}
        scrollable
        scrollHeight="100vh"
        virtualScrollerOptions={{
          itemSize: ROW_ESTIMATE_PX,
          lazy: true,
          onLazyLoad: handleVirtualLoad,
        }}
        resizableColumns
        columnResizeMode="fit"
        rowClassName={rowClassName}
        rowHover
        pt={
          {
            bodyCell: {
              className: "py-1 px-2 text-xs !border-0",
              style: { backgroundColor: "transparent" },
            },
          } as any
        }
        className="swaption-tape-table rounded-2xl border border-gray-800 bg-gradient-to-b from-gray-950 to-gray-900 shadow-inner text-gray-200"
        size="small"
        sortMode="single"
        sortField={sortField}
        sortOrder={sortOrder}
        onSort={(e: DataTableSortEvent) => {
          setSortField((e.sortField as string) || "");
          setSortOrder((e.sortOrder as 1 | -1 | 0) ?? 0);
        }}
      >
        <Column selectionMode="multiple" style={{ width: 44 }} />
        <Column body={expanderBody} style={{ width: 48 }} />
        <Column
          field="event_action"
          header={renderColumnHeader("Action", "action")}
          body={actionBody}
          filter
          filterField="action"
          style={{ width: COLUMN_DEFS[0].width }}
        />
        <Column
          field="package_type"
          header={renderColumnHeader("Package Type", "package_type")}
          body={packageBody}
          filter
          filterField="package_type"
          style={{ width: COLUMN_DEFS[1].width }}
        />
        <Column
          field="execution_start"
          header={renderColumnHeader("Time", "time")}
          body={timeBody}
          filter
          filterField="time"
          filterMatchModeOptions={TIME_FILTER_MATCH_MODE_OPTIONS}
          style={{ width: COLUMN_DEFS[2].width }}
          sortable
        />
        <Column
          field="platform_identifier"
          header={renderColumnHeader("Platform", "platform")}
          body={platformBody}
          filter
          filterField="platform"
          style={{ width: COLUMN_DEFS[3].width }}
        />
        <Column
          key={metricColumnKey}
          field="total_notional"
          header={renderColumnHeader(metricLabel, "notional")}
          body={metricBody}
          filter
          filterField="notional"
          dataType="numeric"
          style={{ width: COLUMN_DEFS[4].width }}
          sortable
        />
        <Column
          field="label"
          header={renderColumnHeader("Trade Label", "label")}
          body={labelBody}
          filter
          filterField="label"
          style={{ width: COLUMN_DEFS[5].width }}
        />
      </DataTable>

      {loading && (
        <div className="flex items-center gap-2 text-gray-300 text-sm">
          <RefreshCw className="h-4 w-4 animate-spin" />
          Loading trade tape...
        </div>
      )}

      {loadingMore && (
        <div className="text-sm text-gray-400">Loading more packages...</div>
      )}

      <ManualLinkModal
        isOpen={linkModalOpen}
        selectedRows={selectedRows}
        currentUser={currentUser}
        onUserChange={setCurrentUser}
        onClose={() => setLinkModalOpen(false)}
        onCreated={handleLinkCreated}
      />
      <ManualLinkDetailsModal
        isOpen={detailModalOpen}
        linkId={detailLinkId}
        currentUser={currentUser}
        onUserChange={setCurrentUser}
        onClose={closeManualLinkDetails}
        onUpdated={handleLinkUpdated}
      />
    </div>
  );
}
