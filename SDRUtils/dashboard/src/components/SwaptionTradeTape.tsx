// ABOUTME: USD Swaptions Trade Tape table (event action + package summary) powered by arbs_swaption_display_items_v2
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { formatLargeNumber } from "@/lib/utils";
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
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  DataTable,
  DataTableFilterMeta,
  DataTableSortEvent,
} from "primereact/datatable";
import { Column } from "primereact/column";
import { FilterMatchMode, FilterOperator } from "primereact/api";
import { VirtualScrollerLazyLoadEvent } from "primereact/virtualscroller";
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
};

type TimeseriesRangeKey = "1D" | "1W" | "1M" | "3M" | "6M" | "CUSTOM" | "ALL";
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

const SAFE_ACTIONS = new Set(["NEWT", "TRAD", "MODI"]);
const ACTIVE_ACTIONS = new Set(["NEWT-TRAD", "MODI-TRAD", "CORR-TRAD"]);
const POLL_INTERVAL_MS = 5000;
const ROW_ESTIMATE_PX = 44;
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
const CUSTY_PLATFORMS = new Set(["BILT", "XXXX"]);
const STRADDLE_GREEK_FIELDS = {
  dv01: "straddle_dv01",
  vega01: "straddle_vega01",
  gamma01: "straddle_gamma01",
  theta01: "straddle_theta1d",
} as const;
const TIMESERIES_METRICS: TimeseriesMetricDefinition[] = [
  {
    key: "bpvolYr",
    label: "BPVol/Yr",
    color: "#38bdf8",
    decimals: 3,
    chartType: "line",
  },
  {
    key: "bpvolDay",
    label: "BPVol/day",
    color: "#f59e0b",
    decimals: 3,
    chartType: "line",
  },
  {
    key: "premiumBps",
    label: "Premium (bps)",
    color: "#f97316",
    decimals: 2,
    chartType: "line",
  },
  {
    key: "notional",
    label: "Notional",
    color: "#22c55e",
    decimals: 1,
    chartType: "bar",
  },
  {
    key: "premium",
    label: "Premium",
    color: "#0ea5e9",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "dv01",
    label: "DV01",
    color: "#a855f7",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "vega01",
    label: "Vega01",
    color: "#f472b6",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "gamma01",
    label: "Gamma01",
    color: "#eab308",
    decimals: 2,
    chartType: "bar",
  },
  {
    key: "theta01",
    label: "Theta1D",
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
const TIMESERIES_FETCH_LIMIT = 200;
const TIMESERIES_MAX_ROWS = 5000;
const TIMESERIES_MAX_PAGES = 50;
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
const DEFAULT_TEXT_MATCH_MODE = FilterMatchMode.CONTAINS;
const DEFAULT_NUMERIC_MATCH_MODE = FilterMatchMode.EQUALS;
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

function isCustyPlatform(platform: string | null | undefined): boolean {
  if (!platform) return false;
  return CUSTY_PLATFORMS.has(platform.trim().toUpperCase());
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

function formatNotional(notional: number | null | undefined) {
  if (!isValid(notional)) return "--";
  const mm = Number(notional) / 1_000_000;
  if (mm >= 1000) return `${(mm / 1000).toFixed(1)}BN`;
  if (Number.isInteger(mm)) return `${mm.toFixed(0)}MM`;
  return `${mm.toFixed(1)}MM`;
}

function formatStrikeAbsolute(strike?: number | null) {
  if (!isValid(strike)) return "--";
  return (Number(strike) * 100).toFixed(2);
}

function formatStrikeOffset(offset?: number | null, signAlways = true) {
  if (!isValid(offset)) return "ATMF";
  const rounded = Math.round(Number(offset));
  if (rounded === 0) return "ATMF";
  if (rounded > 0) return signAlways ? `ATMF+${rounded}bp` : `ATMF+${rounded}`;
  return signAlways ? `ATMF${rounded}bp` : `ATMF${rounded}`;
}

function formatMetricValue(value: number | null | undefined, decimals = 2) {
  if (!isValid(value)) return "--";
  const numericValue = Number(value);
  if (Math.abs(numericValue) >= 1000) {
    return formatLargeNumber(numericValue);
  }
  return numericValue.toFixed(decimals);
}

function formatMetricDisplay(value: number | null | undefined, decimals = 2) {
  if (!isValid(value)) return EMPTY_VALUE;
  return formatMetricValue(value, decimals);
}

function parseMetricNumber(value: any): number | null {
  if (!isValid(value)) return null;
  const numericValue = Number(value);
  return Number.isNaN(numericValue) ? null : numericValue;
}

function normalizeManualFlag(value: any): boolean {
  if (value === true) return true;
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === "number") return value !== 0;
  const normalized = String(value).trim().toLowerCase();
  return ["true", "1", "yes", "y", "t"].includes(normalized);
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

function parseIdList(value: string): string[] {
  if (!value) return [];
  return value
    .split(/[,\s]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function formatManualMetricValue(value: any): string {
  if (!isValid(value)) return "--";
  if (typeof value === "number") return formatMetricValue(value, 2);
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
    const constraints = Array.isArray(filterMeta.constraints)
      ? filterMeta.constraints
      : [
          {
            value: filterMeta.value,
            matchMode: filterMeta.matchMode,
          },
        ];
    const activeConstraints = constraints
      .map((constraint) => ({
        value: constraint?.value,
        matchMode: constraint?.matchMode,
      }))
      .filter((constraint) => !isEmptyFilterValue(constraint.value));
    if (!activeConstraints.length) return;
    payload[field] = {
      operator:
        filterMeta.operator === FilterOperator.OR
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
      .map((constraint) => ({
        value: normalizeFilterConstraintValue(field, constraint?.value),
        matchMode:
          typeof constraint?.matchMode === "string"
            ? constraint.matchMode
            : (INITIAL_FILTERS as any)[field]?.constraints?.[0]?.matchMode,
      }))
      .filter((constraint) => !isEmptyFilterValue(constraint.value));
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
  const numericModes = new Set([
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
    (constraint) => !isEmptyFilterValue(constraint?.value),
  );
  if (!activeConstraints.length) return true;
  const operator = filterMeta.operator || FilterOperator.AND;
  const useOr = operator === FilterOperator.OR;
  return useOr
    ? activeConstraints.some((constraint) =>
        matchFilterValue(rowValue, constraint.value, constraint.matchMode),
      )
    : activeConstraints.every((constraint) =>
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
    (constraint) => !isEmptyFilterValue(constraint?.value),
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
): number | null {
  const value = point[metricKey];
  if (!isValid(value)) return null;
  const numericValue = Number(value);
  return Number.isNaN(numericValue) ? null : numericValue;
}

function buildDailyTimeseries(
  points: StraddleTimeseriesPoint[],
  metricKey: TimeseriesMetricKey,
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
    const value = resolveTimeseriesMetricValue(point, metricKey);
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
  if (tenorLabel) return tenorLabel;
  return null;
}

function buildStraddleSeriesKey(row: TapeRow): string {
  const tenorKey = resolveTenorKey(row);
  if (tenorKey) return tenorKey;
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const underlying = extractUnderlyingBase(legs[0]?.trade_label, row);
  const cleanUnderlying = removeTrailingStyle(underlying, STRADDLE_STYLE);
  return `${cleanUnderlying} ${STRADDLE_STYLE} STRADDLE`;
}

function resolveStraddleNotional(row: TapeRow): number | null {
  const legs = Array.isArray(row.legs_json) ? row.legs_json : [];
  const firstLegNotional = legs[0]?.notional;
  if (isValid(firstLegNotional)) return Number(firstLegNotional);
  return parseMetricNumber(row.total_notional);
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
      .map((l) => l.strike)
      .filter((s) => isValid(s))
      .map(Number)
      .sort((a, b) => a - b);
    const atmf = isValid(metrics.rr_atmf)
      ? Number(metrics.rr_atmf)
      : strikes.length === 3
        ? strikes[1]
        : null;
    let width: number | null = null;
    if (isValid(metrics.rr_out_strike)) width = Number(metrics.rr_out_strike);
    else if (strikes.length >= 3 && isValid(atmf))
      width = Math.round((Math.max(...strikes) - atmf) * 10000);
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
  const isRiskReversal = packageType === "RISK_REVERSAL";
  const showStraddleSchema = isStraddle || isRiskReversal;
  const splitFactor = isStraddle ? STRADDLE_SPLIT_FACTOR : 1;
  const [showTimeseries, setShowTimeseries] = useState(false);
  const [timeseriesView, setTimeseriesView] =
    useState<TimeseriesViewKey>("INTRADAY");
  const [timeseriesMetric, setTimeseriesMetric] =
    useState<TimeseriesMetricKey>("bpvolYr");
  const [timeseriesRange, setTimeseriesRange] =
    useState<TimeseriesRangeKey>("ALL");
  const [customRangeStart, setCustomRangeStart] = useState("");
  const [customRangeEnd, setCustomRangeEnd] = useState("");
  const [showLineDots, setShowLineDots] = useState(true);
  const [excludeCusty, setExcludeCusty] = useState(false);
  const [extraTimeseriesRows, setExtraTimeseriesRows] = useState<TapeRow[]>([]);
  const [timeseriesLoading, setTimeseriesLoading] = useState(false);
  const [timeseriesError, setTimeseriesError] = useState<string | null>(null);
  const timeseriesFetchKeyRef = useRef<string | null>(null);
  const timeseriesFetchInFlight = useRef(false);
  const columnFiltersParam = searchParams.get(COLUMN_FILTER_QUERY_KEY);
  const columnFilterOpParam = searchParams.get(COLUMN_FILTER_OPERATOR_QUERY_KEY);
  const filterParam = searchParams.get("filter");
  const seriesKey = isStraddle ? buildStraddleSeriesKey(row) : null;
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
  const timeseriesData = useMemo(() => {
    if (!showTimeseries || !isStraddle || !seriesKey) return [];
    const candidates = Array.isArray(combinedSeriesRows)
      ? combinedSeriesRows
      : [];
    return candidates
      .filter(
        (candidate) => {
          if (normalizePackageType(candidate.package_type) !== "STRADDLE") {
            return false;
          }
          const action = extractPrimaryAction(candidate);
          if (action !== "NEWT-TRAD") return false;
          if (buildStraddleSeriesKey(candidate) !== seriesKey) return false;
          if (excludeCusty) {
            const platform = resolvePlatformIdentifier(candidate);
            if (isCustyPlatform(platform)) return false;
          }
          return true;
        },
      )
      .map((candidate) => buildStraddleTimeseriesPoint(candidate))
      .filter((point): point is StraddleTimeseriesPoint => point !== null)
      .sort((left, right) => left.timestamp - right.timestamp);
  }, [
    combinedSeriesRows,
    excludeCusty,
    isStraddle,
    seriesKey,
    showTimeseries,
  ]);
  const rangedTimeseriesData = useMemo(() => {
    if (!timeseriesData.length) return [];
    if (timeseriesRange === "CUSTOM") {
      const startTimestamp = parseDateInput(customRangeStart, false);
      const endTimestamp = parseDateInput(customRangeEnd, true);
      if (startTimestamp === null && endTimestamp === null) {
        return timeseriesData;
      }
      return timeseriesData.filter((point) => {
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
      (option) => option.key === timeseriesRange,
    );
    if (!rangeConfig || rangeConfig.days === null) return timeseriesData;
    const latestTimestamp = timeseriesData[timeseriesData.length - 1].timestamp;
    const cutoff =
      latestTimestamp - rangeConfig.days * 24 * 60 * 60 * 1000;
    return timeseriesData.filter((point) => point.timestamp >= cutoff);
  }, [customRangeEnd, customRangeStart, timeseriesData, timeseriesRange]);
  const selectedMetric =
    TIMESERIES_METRICS.find((metric) => metric.key === timeseriesMetric) ||
    TIMESERIES_METRICS[0];
  const intradayChartData = useMemo(
    () =>
      rangedTimeseriesData.filter((point) =>
        isValid(point[timeseriesMetric]),
      ),
    [rangedTimeseriesData, timeseriesMetric],
  );
  const dailySeries = useMemo(
    () => buildDailyTimeseries(rangedTimeseriesData, timeseriesMetric),
    [rangedTimeseriesData, timeseriesMetric],
  );
  const useDailySum =
    timeseriesView === "DAILY_CLOSE" &&
    DAILY_CLOSE_CUMULATIVE_METRICS.has(timeseriesMetric);
  const dailyCloseDataKey = useDailySum ? "daySum" : "close";
  const chartData =
    timeseriesView === "INTRADAY" ? intradayChartData : dailySeries;
  const chartValues = useMemo(() => {
    if (timeseriesView === "DAILY_OHLC") {
      return dailySeries
        .flatMap((point) => [point.open, point.high, point.low, point.close])
        .filter((value) => !Number.isNaN(value));
    }
    if (timeseriesView === "DAILY_CLOSE") {
      return dailySeries
        .map((point) => (useDailySum ? point.daySum : point.close))
        .filter((value) => !Number.isNaN(value));
    }
    return intradayChartData
      .map((point) => Number(point[timeseriesMetric]))
      .filter((value) => !Number.isNaN(value));
  }, [
    dailySeries,
    intradayChartData,
    useDailySum,
    timeseriesMetric,
    timeseriesView,
  ]);
  const metricFormatter = useCallback(
    (value: number) =>
      formatTimeseriesMetric(timeseriesMetric, value, selectedMetric.decimals),
    [selectedMetric.decimals, timeseriesMetric],
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
            <span className="font-mono">{metricFormatter(point.open)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>High</span>
            <span className="font-mono">{metricFormatter(point.high)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Low</span>
            <span className="font-mono">{metricFormatter(point.low)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Close</span>
            <span className="font-mono">{metricFormatter(point.close)}</span>
          </div>
        </div>
      );
    },
    [metricFormatter],
  );
  const includeZeroInDomain =
    (timeseriesView === "INTRADAY" && selectedMetric.chartType === "bar") ||
    (timeseriesView === "DAILY_CLOSE" && useDailySum);
  const yDomain = useMemo(
    () => buildTimeseriesDomain(chartValues, includeZeroInDomain),
    [chartValues, includeZeroInDomain],
  );
  const hasChartData =
    timeseriesView === "INTRADAY"
      ? intradayChartData.length > 0
      : dailySeries.length > 0;
  const isLineChartView =
    (timeseriesView === "DAILY_CLOSE" && !useDailySum) ||
    (timeseriesView === "INTRADAY" && selectedMetric.chartType === "line");
  const isOhlcView = timeseriesView === "DAILY_OHLC";
  const timeseriesFetchKey = useMemo(
    () =>
      `${seriesKey ?? ""}|${columnFiltersParam ?? ""}|${
        columnFilterOpParam ?? ""
      }|${filterParam ?? ""}`,
    [columnFilterOpParam, columnFiltersParam, filterParam, seriesKey],
  );

  useEffect(() => {
    setExtraTimeseriesRows([]);
    setTimeseriesError(null);
    timeseriesFetchKeyRef.current = null;
  }, [columnFilterOpParam, columnFiltersParam, filterParam, seriesKey]);

  useEffect(() => {
    if (!showTimeseries || !isStraddle || !seriesKey) return;
    if (timeseriesRange !== "ALL" && timeseriesRange !== "CUSTOM") return;
    if (timeseriesFetchInFlight.current) return;
    if (timeseriesFetchKeyRef.current === timeseriesFetchKey) return;

    let cancelled = false;
    const fetchTimeseriesRows = async () => {
      timeseriesFetchInFlight.current = true;
      setTimeseriesLoading(true);
      setTimeseriesError(null);
      const collected = new Map<string, TapeRow>();
      let cursor: string | null = null;
      let hasMore = true;
      let pages = 0;

      try {
        while (
          hasMore &&
          pages < TIMESERIES_MAX_PAGES &&
          collected.size < TIMESERIES_MAX_ROWS
        ) {
          const params = new URLSearchParams();
          params.set("limit", String(TIMESERIES_FETCH_LIMIT));
          if (columnFiltersParam) {
            params.set(COLUMN_FILTER_QUERY_KEY, columnFiltersParam);
          }
          if (columnFilterOpParam) {
            params.set(COLUMN_FILTER_OPERATOR_QUERY_KEY, columnFilterOpParam);
          }
          if (filterParam) {
            params.set("filter", filterParam);
          }
          if (cursor) params.set("cursor", cursor);

          const res = await fetch(`/api/swaptions-tape?${params.toString()}`);
          if (!res.ok) {
            const text = await res.text();
            throw new Error(text || "Failed to load timeseries data");
          }
          const data: TapeResponse = await res.json();
          data.rows.forEach((rowItem) => {
            if (normalizePackageType(rowItem.package_type) !== "STRADDLE") {
              return;
            }
            const action = extractPrimaryAction(rowItem);
            if (action !== "NEWT-TRAD") return;
            if (buildStraddleSeriesKey(rowItem) !== seriesKey) return;
            collected.set(rowItem.package_id, rowItem);
          });
          hasMore = data.hasMore;
          cursor = data.nextCursor;
          pages += 1;
          if (!cursor) break;
        }

        if (cancelled) return;
        setExtraTimeseriesRows(Array.from(collected.values()));
        timeseriesFetchKeyRef.current = timeseriesFetchKey;
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
    columnFilterOpParam,
    columnFiltersParam,
    filterParam,
    isStraddle,
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
          (highValues?.bpvolValue !== null && lowValues?.bpvolValue !== null
            ? highValues.bpvolValue - lowValues.bpvolValue
            : null);
        const totalBpvolDay =
          totalBpvolYr !== null
            ? totalBpvolYr / BPVOL_DAY_DIVISOR
            : highValues?.bpvolDayValue !== null &&
                lowValues?.bpvolDayValue !== null
              ? highValues.bpvolDayValue - lowValues.bpvolDayValue
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
      {isStraddle && (
        <div className="flex items-center justify-end px-2">
          <button
            type="button"
            onClick={() => setShowTimeseries((current) => !current)}
            className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-slate-800"
          >
            {showTimeseries ? "Hide Timeseries" : "Show Timeseries"}
          </button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
        <thead className="bg-slate-950/40 text-[11px] uppercase tracking-wide text-slate-400">
          <tr>
            <th className="px-2 py-1 text-left">Leg</th>
            <th className="px-2 py-1 text-left">Side</th>
            <th className="px-2 py-1 text-right">Strike</th>
            <th className="px-2 py-1 text-right">Notional</th>
            {showStraddleSchema && (
              <th className="px-2 py-1 text-right">Notional Capped</th>
            )}
            <th className="px-2 py-1 text-right">Premium</th>
            {showStraddleSchema && (
              <th className="px-2 py-1 text-right">Premium (bps)</th>
            )}
            <th className="px-2 py-1 text-right">BPVol/Yr</th>
            <th className="px-2 py-1 text-right">BPVol/day</th>
            <th className="px-2 py-1 text-right">DV01</th>
            <th className="px-2 py-1 text-right">Vega01</th>
            <th className="px-2 py-1 text-right">Gamma01</th>
            {showStraddleSchema && (
              <th className="px-2 py-1 text-right">Theta1D</th>
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
                {showStraddleSchema && (
                  <td className="px-1 py-1 text-right font-mono">
                    {resolveNotionalCapped(leg)}
                  </td>
                )}
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.premiumValue, 2)}
                </td>
                {showStraddleSchema && (
                  <td className="px-1 py-1 text-right font-mono">
                    {formatMetricValue(values.premiumBpsValue, 2)}
                  </td>
                )}
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.bpvolValue, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.bpvolDayValue, 3)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.dv01Value, 2)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.vega01Value, 2)}
                </td>
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(values.gamma01Value, 2)}
                </td>
                {showStraddleSchema && (
                  <td className="px-1 py-1 text-right font-mono">
                    {formatMetricValue(values.theta01Value, 2)}
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
                {formatMetricValue(riskReversalTotals.totalPremium, 2)}
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
                    {formatMetricValue(riskReversalTotals.totalDv01, 2)}
                  </span>
                  {isValid(riskReversalTotals.totalWingDv01) && (
                    <span className="text-slate-300">
                      Wing{" "}
                      {formatMetricValue(riskReversalTotals.totalWingDv01, 2)}
                    </span>
                  )}
                </div>
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalVega01, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(riskReversalTotals.totalGamma01, 2)}
              </td>
              {showStraddleSchema && (
                <td className="px-1 py-1 text-right font-mono">
                  {formatMetricValue(riskReversalTotals.totalTheta01, 2)}
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
                {formatMetricValue(straddleTotals?.premium, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.premiumBps, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono text-slate-400">
                --
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.dv01, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.vega01, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.gamma01, 2)}
              </td>
              <td className="px-1 py-1 text-right font-mono">
                {formatMetricValue(straddleTotals?.theta01, 2)}
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
            {formatMetricDisplay(riskReversalTotals?.wingToDeltaRatio, 2)}
          </span>
        </div>
      )}
      {isStraddle && showTimeseries && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 text-[11px] uppercase tracking-wide text-slate-400">
              <span className="block truncate">{seriesKey}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setExcludeCusty((current) => !current)}
                className={`rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                  excludeCusty
                    ? "bg-slate-700 text-slate-100"
                    : "text-slate-300 hover:bg-slate-800"
                }`}
              >
                No Custy
              </button>
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
            </div>
          </div>
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
          {hasChartData ? (
            <div className="mt-3 h-48">
              <ResponsiveContainer width="100%" height="100%">
                {isOhlcView ? (
                  <ComposedChart data={chartData}>
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
                    />
                    <Tooltip
                      formatter={(value: number) => metricFormatter(value)}
                      labelStyle={{ color: "#e2e8f0" }}
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        border: "1px solid #1f2937",
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey={
                        timeseriesView === "DAILY_CLOSE"
                          ? dailyCloseDataKey
                          : selectedMetric.key
                      }
                      stroke={selectedMetric.color}
                      strokeWidth={2}
                      dot={
                        showLineDots
                          ? { r: 3, fill: selectedMetric.color }
                          : false
                      }
                      activeDot={showLineDots ? { r: 4 } : false}
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
                    />
                    <Tooltip
                      formatter={(value: number) => metricFormatter(value)}
                      labelStyle={{ color: "#e2e8f0" }}
                      contentStyle={{
                        backgroundColor: "#0f172a",
                        border: "1px solid #1f2937",
                      }}
                    />
                    <Bar
                      dataKey={
                        timeseriesView === "DAILY_CLOSE"
                          ? dailyCloseDataKey
                          : selectedMetric.key
                      }
                      fill={selectedMetric.color}
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="mt-3 text-xs text-slate-400">
              {timeseriesLoading
                ? "Loading more history..."
                : timeseriesError || "No timeseries data available."}
            </div>
          )}
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
  onCreated: () => void;
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
      onCreated();
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
                        {formatMetricValue(metrics.total_premium, 2)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>DV01</span>
                      <span className="font-mono">
                        {formatMetricValue(metrics.total_dv01, 2)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Vega01</span>
                      <span className="font-mono">
                        {formatMetricValue(metrics.total_vega01, 2)}
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
      setTrades(payload.trades || []);
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
  const [linkModalOpen, setLinkModalOpen] = useState(false);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [detailLinkId, setDetailLinkId] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState("");
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
  const columnFilterPayloadKeyRef = useRef(columnFilterPayloadKey);
  const columnFilterOperatorRef = useRef(columnFilterOperator);

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
    setSelectedRows((prev) =>
      prev.filter((row) =>
        rows.some((candidate) => candidate.package_id === row.package_id),
      ),
    );
  }, [rows]);

  useEffect(() => {
    columnFilterPayloadKeyRef.current = columnFilterPayloadKey;
  }, [columnFilterPayloadKey]);

  useEffect(() => {
    columnFilterOperatorRef.current = columnFilterOperator;
  }, [columnFilterOperator]);

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
    searchParams,
  ]);

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
    return displayNotional;
  }, []);

  const resolveFilterValue = useCallback(
    (row: TapeRow, field: string) => {
      switch (field) {
        case "action":
          return firstLegMetrics(row).event_action || "";
        case "package_type":
          return row.package_type || "";
        case "time":
          return formatExecutionWindow(
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

  const filteredRows = useMemo(() => {
    const activeFilters = Object.entries(filters || {}).filter(
      ([field, filterMeta]) =>
        field !== "global" && hasActiveConstraints(filterMeta),
    );
    const filtered = rows.filter((row) => {
      if (!activeFilters.length) return true;
      const matches = activeFilters.map(([field, filterMeta]) => {
        const rowValue = resolveFilterValue(row, field);
        return matchFilterMeta(rowValue, filterMeta);
      });
      return columnFilterOperator === FilterOperator.OR
        ? matches.some(Boolean)
        : matches.every(Boolean);
    });
    if (!sortField || sortOrder === 0) return filtered;
    const sorted = [...filtered].sort((a, b) => {
      const av = (a as any)[sortField];
      const bv = (b as any)[sortField];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortOrder === 1 ? av - bv : bv - av;
      }
      const aStr = String(av).toLowerCase();
      const bStr = String(bv).toLowerCase();
      if (aStr === bStr) return 0;
      return sortOrder === 1 ? (aStr > bStr ? 1 : -1) : aStr < bStr ? 1 : -1;
    });
    return sorted;
  }, [
    rows,
    filters,
    resolveFilterValue,
    sortField,
    sortOrder,
    columnFilterOperator,
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
    (event: VirtualScrollerLazyLoadEvent) => {
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

  const handleLinkCreated = useCallback(() => {
    setSelectedRows([]);
    fetchTape({ replace: true });
  }, [fetchTape]);

  const handleLinkUpdated = useCallback(() => {
    fetchTape({ replace: true });
  }, [fetchTape]);

  const rowClassName = (row: TapeRow) => {
    const metrics = firstLegMetrics(row);
    const action = metrics.event_action;
    const isActive = action ? ACTIVE_ACTIONS.has(action.toUpperCase()) : false;
    const tone = isActive
      ? packageTone(row.package_type)
      : "!bg-red-900/70 !text-red-100";
    const warning = hasActionWarning(row);
    const classes = [
      "h-10 text-sm !text-gray-200 transition-[filter,box-shadow] hover:brightness-110 hover:shadow-[inset_0_0_0_1px_rgba(148,163,184,0.5)]",
      tone,
      actionTone(action),
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
      const filterMeta = (filters || {})[filterField];
      if (!hasActiveConstraints(filterMeta)) return null;
      const constraints = Array.isArray(filterMeta.constraints)
        ? filterMeta.constraints
        : [
            {
              value: filterMeta.value,
              matchMode: filterMeta.matchMode,
            },
          ];
      const activeConstraints = constraints.filter(
        (constraint) => !isEmptyFilterValue(constraint?.value),
      );
      if (!activeConstraints.length) return null;
      const operatorLabel =
        (filterMeta.operator || FilterOperator.AND) === FilterOperator.OR
          ? "OR"
          : "AND";
      return activeConstraints
        .map((constraint) => {
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

  const notionalBody = (row: TapeRow) => {
    return (
      <span className="text-xs font-mono text-gray-200">
        {formatNotional(resolveDisplayNotional(row))}
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
      {selectedRows.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-300">
          <div className="flex items-center gap-2">
            <span className="font-mono">{selectedRows.length}</span>
            trades selected
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelectedRows([])}
              className="rounded border border-slate-700 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:border-slate-500"
            >
              Clear
            </button>
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
      <style jsx global>{`
        .p-column-filter-overlay,
        .p-column-filter-overlay * {
          font-size: 0.7rem !important;
        }
        .swaption-tape-table .p-datatable-tbody > tr,
        .swaption-tape-table .p-datatable-tbody > tr > td {
          border: none !important;
        }
      `}</style>
      <DataTable
        value={filteredRows}
        dataKey="package_id"
        selection={selectedRows}
        onSelectionChange={(e) =>
          setSelectedRows((e.value as TapeRow[]) || [])
        }
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
        pt={{
          bodyCell: {
            className: "py-1 px-2 text-xs !border-0",
            style: { backgroundColor: "transparent" },
          },
        }}
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
          field="total_notional"
          header={renderColumnHeader("Notional", "notional")}
          body={notionalBody}
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
