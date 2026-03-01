import type {
  PointGridPlatform,
  PointSignal,
} from "@/features/swaptions-tape/components/VolGridFlow/pointGridFlow.types";

const ET_TIMEZONE = "America/New_York";
export const POINT_GRID_LOOKBACK_DAYS = 365;

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toDateKey(value: string | Date | null | undefined): string | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString().slice(0, 10);
}

function parseDateKey(value: string): Date | null {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null;
  }
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function shiftDateKey(dateKey: string, days: number): string | null {
  const parsed = parseDateKey(dateKey);
  if (!parsed) return null;
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

export function toEasternDateKey(value: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: ET_TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(value);
  const year = parts.find((part) => part.type === "year")?.value ?? "";
  const month = parts.find((part) => part.type === "month")?.value ?? "";
  const day = parts.find((part) => part.type === "day")?.value ?? "";
  return `${year}-${month}-${day}`;
}

export function resolveDefaultAsOfDate(now: Date = new Date()): string {
  const todayEt = toEasternDateKey(now);
  return shiftDateKey(todayEt, -1) ?? todayEt;
}

export function computeDaysBetweenDateKeys(
  laterDateKey: string,
  earlierDateKey: string | null,
): number | null {
  if (!earlierDateKey) return null;
  const later = parseDateKey(laterDateKey);
  const earlier = parseDateKey(earlierDateKey);
  if (!later || !earlier) return null;
  const diff = (later.getTime() - earlier.getTime()) / (24 * 60 * 60 * 1000);
  if (!Number.isFinite(diff) || diff < 0) return null;
  return Math.floor(diff);
}

export function classifyPointSignal(input: {
  reportTradeCount: number | null | undefined;
  grossVs5SessionAvg: number | null | undefined;
  daysSinceLastTrade: number | null | undefined;
}): { signal: PointSignal; signalReason: string } {
  const reportTradeCount = Number(input.reportTradeCount ?? 0);
  const grossVs = Number.isFinite(input.grossVs5SessionAvg as number)
    ? Number(input.grossVs5SessionAvg)
    : null;
  const daysSince = Number.isFinite(input.daysSinceLastTrade as number)
    ? Number(input.daysSinceLastTrade)
    : null;

  if (reportTradeCount >= 2 && grossVs !== null && grossVs >= 1.5) {
    return {
      signal: "positive",
      signalReason:
        "Continuation watch: multi-print flow with gross notional at least 1.5x the 5-session baseline.",
    };
  }
  if (
    (daysSince !== null && daysSince >= 10) ||
    (reportTradeCount > 0 && grossVs !== null && grossVs <= 0.5)
  ) {
    return {
      signal: "negative",
      signalReason:
        "Stale/faded flow: point is inactive for 10+ days or current gross notional is <= 0.5x baseline.",
    };
  }
  return {
    signal: "neutral",
    signalReason: "No strong deviation: flow is within normal range for this point.",
  };
}

export function parsePointGridFlowParams(
  searchParams: URLSearchParams,
  now: Date = new Date(),
):
  | {
      ok: true;
      value: {
        platform: PointGridPlatform;
        asOfDate: string;
        lookbackStartDate: string;
        excludeLargeCustyNotional: boolean;
      };
    }
  | { ok: false; error: string } {
  const platformRaw = (searchParams.get("platform") || "combined").toLowerCase();
  if (!["combined", "idb", "custy"].includes(platformRaw)) {
    return {
      ok: false,
      error: "platform must be 'combined', 'idb', or 'custy'",
    };
  }

  const asOfDateRaw = searchParams.get("asOfDate");
  const defaultAsOfDate = resolveDefaultAsOfDate(now);
  const asOfDateCandidate = asOfDateRaw || defaultAsOfDate;
  const asOfDate = toDateKey(asOfDateCandidate);
  if (!asOfDate || !/^\d{4}-\d{2}-\d{2}$/.test(asOfDate)) {
    return {
      ok: false,
      error: "asOfDate must be YYYY-MM-DD",
    };
  }

  const lookbackStartDate = shiftDateKey(asOfDate, -POINT_GRID_LOOKBACK_DAYS);
  if (!lookbackStartDate) {
    return {
      ok: false,
      error: "failed to resolve lookback range",
    };
  }

  return {
    ok: true,
    value: {
      platform: platformRaw as PointGridPlatform,
      asOfDate,
      lookbackStartDate,
      excludeLargeCustyNotional:
        searchParams.get("excludeLargeCustyNotional") !== "false",
    },
  };
}

type DiagnosticsRow = {
  report_date?: string | null;
  previous_session_date?: string | null;
  baseline_dates?: string[] | null;
  baseline_sessions_used?: number | string | null;
  lookback_trade_count?: number | string | null;
  unmapped_trade_count?: number | string | null;
};

export function buildDiagnosticsFromRows(rows: DiagnosticsRow[]): {
  reportDate: string | null;
  previousSessionDate: string | null;
  baselineDates: string[];
  baselineSessionsUsed: number;
  lookbackTradeCount: number;
  unmappedTradeCount: number;
} {
  const baselineDates = Array.isArray(rows[0]?.baseline_dates)
    ? rows[0]?.baseline_dates || []
    : [];
  return {
    reportDate: rows[0]?.report_date || null,
    previousSessionDate: rows[0]?.previous_session_date || null,
    baselineDates,
    baselineSessionsUsed: parseNumber(rows[0]?.baseline_sessions_used) ?? 0,
    lookbackTradeCount: parseNumber(rows[0]?.lookback_trade_count) ?? 0,
    unmappedTradeCount: parseNumber(rows[0]?.unmapped_trade_count) ?? 0,
  };
}
