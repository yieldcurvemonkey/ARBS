import { NextResponse } from "next/server";
import { query } from "@/lib/db";
import type {
  PointGridFlowResponse,
  PointGridPlatform,
  PointMetrics,
  PointRow,
  PointSignal,
} from "@/features/swaptions-tape/components/VolGridFlow/pointGridFlow.types";

type AxisNode = {
  label: string;
  years: number;
};

type PointNode = {
  pointKey: string;
  expiryLabel: string;
  tenorLabel: string;
  expiryYears: number;
  tenorYears: number;
};

type PointGridFlowDbRow = {
  point_key: string;
  expiry_label: string;
  tenor_label: string;
  expiry_years: number | string;
  tenor_years: number | string;
  last_trade_date: string | null;
  report_trade_count: number | string | null;
  report_gross_notional: number | string | null;
  report_total_premium: number | string | null;
  report_avg_premium: number | string | null;
  report_avg_bpvol_yr: number | string | null;
  report_bpvol_obs_count: number | string | null;
  prev_trade_count: number | string | null;
  prev_gross_notional: number | string | null;
  prev_total_premium: number | string | null;
  prev_avg_premium: number | string | null;
  prev_avg_bpvol_yr: number | string | null;
  prev_bpvol_obs_count: number | string | null;
  avg5_trade_count: number | string | null;
  avg5_gross_notional: number | string | null;
  avg5_total_premium: number | string | null;
  avg5_avg_premium: number | string | null;
  avg5_avg_bpvol_yr: number | string | null;
  avg5_bpvol_obs_count: number | string | null;
  report_date: string | null;
  previous_session_date: string | null;
  baseline_dates: string[] | null;
  baseline_sessions_used: number | string | null;
  lookback_trade_count: number | string | null;
  unmapped_trade_count: number | string | null;
};

const ET_TIMEZONE = "America/New_York";
const POINT_GRID_LOOKBACK_DAYS = 365;
const POINT_GRID_BASELINE_SESSIONS = 5;
const POINT_GRID_TENOR_WEIGHT = 0.7;
const COMICALLY_LARGE_CUSTY_NOTIONAL = 100_000_000_000_000;

const POINT_GRID_EXPIRIES: AxisNode[] = [
  { label: "1M", years: 1 / 12 },
  { label: "3M", years: 3 / 12 },
  { label: "6M", years: 6 / 12 },
  { label: "1Y", years: 1 },
  { label: "2Y", years: 2 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
  { label: "10Y", years: 10 },
  { label: "20Y", years: 20 },
];

const POINT_GRID_TENORS: AxisNode[] = [
  { label: "1Y", years: 1 },
  { label: "2Y", years: 2 },
  { label: "3Y", years: 3 },
  { label: "5Y", years: 5 },
  { label: "7Y", years: 7 },
  { label: "10Y", years: 10 },
  { label: "20Y", years: 20 },
  { label: "30Y", years: 30 },
];

const POINT_GRID_NODES: PointNode[] = POINT_GRID_EXPIRIES.flatMap((expiry) =>
  POINT_GRID_TENORS.map((tenor) => ({
    pointKey: `${expiry.label}x${tenor.label}`,
    expiryLabel: expiry.label,
    tenorLabel: tenor.label,
    expiryYears: expiry.years,
    tenorYears: tenor.years,
  })),
);

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

function toEasternDateKey(value: Date = new Date()): string {
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

function resolveDefaultAsOfDate(now: Date = new Date()): string {
  const todayEt = toEasternDateKey(now);
  return shiftDateKey(todayEt, -1) ?? todayEt;
}

function computeDaysBetweenDateKeys(
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

function computeGrossVsAverage(
  reportGross: number | null | undefined,
  avgGross: number | null | undefined,
): number | null {
  if (!Number.isFinite(reportGross as number)) return null;
  if (!Number.isFinite(avgGross as number) || Number(avgGross) <= 0) return null;
  return Number(reportGross) / Number(avgGross);
}

function computeMetricChange(
  currentValue: number | null | undefined,
  previousValue: number | null | undefined,
): number | null {
  if (!Number.isFinite(currentValue as number)) return null;
  if (!Number.isFinite(previousValue as number)) return null;
  return Number(currentValue) - Number(previousValue);
}

function classifyPointSignal(input: {
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

function parsePointGridFlowParams(
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

function buildNodesValuesSql() {
  return POINT_GRID_NODES.map(
    (node) =>
      `('${node.pointKey}', '${node.expiryLabel}', ${node.expiryYears}, '${node.tenorLabel}', ${node.tenorYears})`,
  ).join(",\n        ");
}

function toPointMetrics(input: {
  tradeCount: unknown;
  grossNotional: unknown;
  totalPremium: unknown;
  avgPremium: unknown;
  avgBpvolYr: unknown;
  bpvolObsCount: unknown;
}): PointMetrics {
  return {
    tradeCount: parseNumber(input.tradeCount) ?? 0,
    grossNotional: parseNumber(input.grossNotional) ?? 0,
    totalPremium: parseNumber(input.totalPremium) ?? 0,
    avgPremium: parseNumber(input.avgPremium),
    avgBpvolYr: parseNumber(input.avgBpvolYr),
    bpvolObsCount: parseNumber(input.bpvolObsCount) ?? 0,
  };
}

function buildDiagnosticsFromRows(rows: PointGridFlowDbRow[]): {
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

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const parsedParams = parsePointGridFlowParams(searchParams);
  if (!parsedParams.ok) {
    return NextResponse.json({ error: parsedParams.error }, { status: 400 });
  }
  const { platform, asOfDate, lookbackStartDate, excludeLargeCustyNotional } =
    parsedParams.value;

  try {
    const sqlParams: Array<string | number> = [
      lookbackStartDate,
      asOfDate,
      POINT_GRID_TENOR_WEIGHT,
      POINT_GRID_BASELINE_SESSIONS,
    ];
    const whereClauses: string[] = [];

    if (platform !== "combined") {
      sqlParams.push(platform);
      whereClauses.push(`platform_type = $${sqlParams.length}`);
    }
    if (excludeLargeCustyNotional) {
      sqlParams.push(COMICALLY_LARGE_CUSTY_NOTIONAL);
      whereClauses.push(
        `NOT (platform_type = 'custy' AND abs(total_notional_raw) >= $${sqlParams.length})`,
      );
    }
    const whereClause = whereClauses.length
      ? `AND ${whereClauses.join(" AND ")}`
      : "";

    const sql = `
      WITH nodes(point_key, expiry_label, expiry_years, tenor_label, tenor_years) AS (
        VALUES
        ${buildNodesValuesSql()}
      ),
      package_base AS (
        SELECT
          p.package_id,
          p.execution_start,
          p.forward_label,
          p.tenor_label,
          p.forward_start_years,
          p.tenor_years,
          p.total_notional,
          p.total_premium,
          p.package_metrics
        FROM arbs_swaption_packages_v1 p
        WHERE p.execution_start >= $1::date
          AND p.execution_start < $2::date + interval '1 day'
          AND upper(replace(coalesce(p.package_type, ''), '-', '_')) = 'STRADDLE'
      ),
      leg_info AS (
        SELECT
          l.package_id,
          mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier,
          mode() WITHIN GROUP (ORDER BY l.event_action) AS event_action,
          SUM(CASE WHEN l.premium IS NOT NULL THEN l.premium * 0.5 ELSE 0 END) AS leg_straddle_premium_sum,
          COUNT(*) FILTER (WHERE l.premium IS NOT NULL) AS leg_premium_count
        FROM arbs_swaption_legs_v1 l
        JOIN package_base p ON p.package_id = l.package_id
        GROUP BY l.package_id
      ),
      classified AS (
        SELECT
          p.package_id,
          (p.execution_start AT TIME ZONE '${ET_TIMEZONE}')::date AS et_trade_date,
          coalesce(upper(li.event_action), '') AS event_action,
          CASE
            WHEN p.forward_start_years IS NOT NULL AND p.forward_start_years > 0
              THEN p.forward_start_years
            WHEN upper(coalesce(p.forward_label, '')) ~ '^\\d+(\\.\\d+)?[DWMY]$'
              THEN CASE right(upper(p.forward_label), 1)
                WHEN 'D' THEN nullif(regexp_replace(upper(p.forward_label), '[^0-9\\.]', '', 'g'), '')::numeric / 365.0
                WHEN 'W' THEN nullif(regexp_replace(upper(p.forward_label), '[^0-9\\.]', '', 'g'), '')::numeric / 52.0
                WHEN 'M' THEN nullif(regexp_replace(upper(p.forward_label), '[^0-9\\.]', '', 'g'), '')::numeric / 12.0
                WHEN 'Y' THEN nullif(regexp_replace(upper(p.forward_label), '[^0-9\\.]', '', 'g'), '')::numeric
                ELSE NULL
              END
            ELSE NULL
          END AS forward_years,
          CASE
            WHEN p.tenor_years IS NOT NULL AND p.tenor_years > 0
              THEN p.tenor_years
            WHEN upper(coalesce(p.tenor_label, '')) ~ '^\\d+(\\.\\d+)?[DWMY]$'
              THEN CASE right(upper(p.tenor_label), 1)
                WHEN 'D' THEN nullif(regexp_replace(upper(p.tenor_label), '[^0-9\\.]', '', 'g'), '')::numeric / 365.0
                WHEN 'W' THEN nullif(regexp_replace(upper(p.tenor_label), '[^0-9\\.]', '', 'g'), '')::numeric / 52.0
                WHEN 'M' THEN nullif(regexp_replace(upper(p.tenor_label), '[^0-9\\.]', '', 'g'), '')::numeric / 12.0
                WHEN 'Y' THEN nullif(regexp_replace(upper(p.tenor_label), '[^0-9\\.]', '', 'g'), '')::numeric
                ELSE NULL
              END
            ELSE NULL
          END AS tenor_years,
          coalesce(p.total_notional, 0) AS total_notional_raw,
          abs(coalesce(p.total_notional, 0)) AS gross_notional,
          CASE
            WHEN coalesce(li.leg_premium_count, 0) > 0
              THEN coalesce(li.leg_straddle_premium_sum, 0)
            ELSE coalesce(p.total_premium, 0)
          END AS total_premium,
          CASE
            WHEN jsonb_typeof(p.package_metrics->'straddle_bpvol_yr') = 'array'
              THEN nullif((p.package_metrics->'straddle_bpvol_yr'->>0), '')::numeric
            WHEN jsonb_typeof(p.package_metrics->'straddle_bpvol_yr') = 'number'
              THEN (p.package_metrics->>'straddle_bpvol_yr')::numeric
            WHEN jsonb_typeof(p.package_metrics->'straddle_bpvol_yr') = 'string'
              THEN nullif(p.package_metrics->>'straddle_bpvol_yr', '')::numeric
            ELSE NULL
          END AS bpvol_yr,
          CASE
            WHEN li.platform_identifier IS NULL THEN 'custy'
            WHEN EXISTS (
              SELECT 1
              FROM regexp_split_to_table(upper(li.platform_identifier), '[\\s,;/]+') AS token
              WHERE token IN ('BGCD', 'ISWV', 'TPSE')
            ) THEN 'idb'
            ELSE 'custy'
          END AS platform_type
        FROM package_base p
        LEFT JOIN leg_info li ON li.package_id = p.package_id
      ),
      filtered AS (
        SELECT *
        FROM classified
        WHERE event_action IN ('NEWT-TRAD', 'MODI-TRAD', 'CORR-TRAD')
        ${whereClause}
      ),
      mapped_candidates AS (
        SELECT
          f.*,
          n.point_key,
          n.expiry_label,
          n.expiry_years,
          n.tenor_label,
          n.tenor_years,
          row_number() OVER (
            PARTITION BY f.package_id
            ORDER BY
              sqrt(
                power(ln(f.forward_years) - ln(n.expiry_years), 2) +
                power($3 * (ln(f.tenor_years) - ln(n.tenor_years)), 2)
              ) ASC,
              n.point_key ASC
          ) AS rn
        FROM filtered f
        JOIN nodes n
          ON f.forward_years > 0
         AND f.tenor_years > 0
      ),
      nearest AS (
        SELECT *
        FROM mapped_candidates
        WHERE rn = 1
      ),
      report_date_cte AS (
        SELECT max(et_trade_date) AS report_date
        FROM nearest
        WHERE et_trade_date <= $2::date
      ),
      previous_session_date_cte AS (
        SELECT max(et_trade_date) AS previous_session_date
        FROM nearest
        CROSS JOIN report_date_cte
        WHERE report_date_cte.report_date IS NOT NULL
          AND et_trade_date < report_date_cte.report_date
      ),
      baseline_dates_cte AS (
        SELECT et_trade_date AS trade_date
        FROM nearest
        CROSS JOIN report_date_cte
        WHERE report_date_cte.report_date IS NOT NULL
          AND et_trade_date < report_date_cte.report_date
        GROUP BY et_trade_date
        ORDER BY et_trade_date DESC
        LIMIT $4::int
      ),
      baseline_days_count AS (
        SELECT count(*)::int AS sessions_used
        FROM baseline_dates_cte
      ),
      report_agg AS (
        SELECT
          point_key,
          count(*)::numeric AS trade_count,
          sum(gross_notional)::numeric AS gross_notional,
          sum(total_premium)::numeric AS total_premium,
          avg(total_premium)::numeric AS avg_premium,
          avg(bpvol_yr)::numeric AS avg_bpvol_yr,
          count(bpvol_yr)::numeric AS bpvol_obs_count
        FROM nearest
        CROSS JOIN report_date_cte
        WHERE report_date_cte.report_date IS NOT NULL
          AND et_trade_date = report_date_cte.report_date
        GROUP BY point_key
      ),
      previous_session_agg AS (
        SELECT
          point_key,
          count(*)::numeric AS trade_count,
          sum(gross_notional)::numeric AS gross_notional,
          sum(total_premium)::numeric AS total_premium,
          avg(total_premium)::numeric AS avg_premium,
          avg(bpvol_yr)::numeric AS avg_bpvol_yr,
          count(bpvol_yr)::numeric AS bpvol_obs_count
        FROM nearest
        CROSS JOIN previous_session_date_cte
        WHERE previous_session_date_cte.previous_session_date IS NOT NULL
          AND et_trade_date = previous_session_date_cte.previous_session_date
        GROUP BY point_key
      ),
      baseline_agg_raw AS (
        SELECT
          point_key,
          et_trade_date,
          count(*)::numeric AS trade_count,
          sum(gross_notional)::numeric AS gross_notional,
          sum(total_premium)::numeric AS total_premium,
          avg(total_premium)::numeric AS avg_premium,
          avg(bpvol_yr)::numeric AS avg_bpvol_yr,
          count(bpvol_yr)::numeric AS bpvol_obs_count
        FROM nearest
        WHERE et_trade_date IN (SELECT trade_date FROM baseline_dates_cte)
        GROUP BY point_key, et_trade_date
      ),
      baseline_agg AS (
        SELECT
          n.point_key,
          CASE
            WHEN bdc.sessions_used > 0
              THEN coalesce(sum(coalesce(bar.trade_count, 0)), 0)::numeric / bdc.sessions_used
            ELSE 0::numeric
          END AS avg_trade_count,
          CASE
            WHEN bdc.sessions_used > 0
              THEN coalesce(sum(coalesce(bar.gross_notional, 0)), 0)::numeric / bdc.sessions_used
            ELSE 0::numeric
          END AS avg_gross_notional,
          CASE
            WHEN bdc.sessions_used > 0
              THEN coalesce(sum(coalesce(bar.total_premium, 0)), 0)::numeric / bdc.sessions_used
            ELSE 0::numeric
          END AS avg_total_premium,
          CASE
            WHEN count(*) FILTER (WHERE bar.avg_premium IS NOT NULL) > 0
              THEN avg(bar.avg_premium) FILTER (WHERE bar.avg_premium IS NOT NULL)
            ELSE NULL
          END AS avg_avg_premium,
          CASE
            WHEN count(*) FILTER (WHERE bar.avg_bpvol_yr IS NOT NULL) > 0
              THEN avg(bar.avg_bpvol_yr) FILTER (WHERE bar.avg_bpvol_yr IS NOT NULL)
            ELSE NULL
          END AS avg_avg_bpvol_yr,
          CASE
            WHEN bdc.sessions_used > 0
              THEN coalesce(sum(coalesce(bar.bpvol_obs_count, 0)), 0)::numeric / bdc.sessions_used
            ELSE 0::numeric
          END AS avg_bpvol_obs_count
        FROM nodes n
        CROSS JOIN baseline_days_count bdc
        LEFT JOIN baseline_dates_cte bd ON bdc.sessions_used > 0
        LEFT JOIN baseline_agg_raw bar
          ON bar.point_key = n.point_key
         AND bar.et_trade_date = bd.trade_date
        GROUP BY n.point_key, bdc.sessions_used
      ),
      last_trade AS (
        SELECT point_key, max(et_trade_date) AS last_trade_date
        FROM nearest
        GROUP BY point_key
      ),
      meta AS (
        SELECT
          (SELECT report_date FROM report_date_cte) AS report_date,
          (SELECT previous_session_date FROM previous_session_date_cte) AS previous_session_date,
          coalesce(
            (SELECT array_agg(to_char(trade_date, 'YYYY-MM-DD') ORDER BY trade_date DESC) FROM baseline_dates_cte),
            ARRAY[]::text[]
          ) AS baseline_dates,
          (SELECT sessions_used FROM baseline_days_count) AS baseline_sessions_used,
          (SELECT count(*)::int FROM filtered) AS lookback_trade_count,
          (
            SELECT count(*)::int
            FROM filtered
            WHERE forward_years IS NULL
              OR tenor_years IS NULL
              OR forward_years <= 0
              OR tenor_years <= 0
          ) AS unmapped_trade_count
      )
      SELECT
        n.point_key,
        n.expiry_label,
        n.tenor_label,
        n.expiry_years,
        n.tenor_years,
        to_char(lt.last_trade_date, 'YYYY-MM-DD') AS last_trade_date,
        coalesce(ra.trade_count, 0) AS report_trade_count,
        coalesce(ra.gross_notional, 0) AS report_gross_notional,
        coalesce(ra.total_premium, 0) AS report_total_premium,
        ra.avg_premium AS report_avg_premium,
        ra.avg_bpvol_yr AS report_avg_bpvol_yr,
        coalesce(ra.bpvol_obs_count, 0) AS report_bpvol_obs_count,
        coalesce(psa.trade_count, 0) AS prev_trade_count,
        coalesce(psa.gross_notional, 0) AS prev_gross_notional,
        coalesce(psa.total_premium, 0) AS prev_total_premium,
        psa.avg_premium AS prev_avg_premium,
        psa.avg_bpvol_yr AS prev_avg_bpvol_yr,
        coalesce(psa.bpvol_obs_count, 0) AS prev_bpvol_obs_count,
        coalesce(ba.avg_trade_count, 0) AS avg5_trade_count,
        coalesce(ba.avg_gross_notional, 0) AS avg5_gross_notional,
        coalesce(ba.avg_total_premium, 0) AS avg5_total_premium,
        ba.avg_avg_premium AS avg5_avg_premium,
        ba.avg_avg_bpvol_yr AS avg5_avg_bpvol_yr,
        coalesce(ba.avg_bpvol_obs_count, 0) AS avg5_bpvol_obs_count,
        to_char(meta.report_date, 'YYYY-MM-DD') AS report_date,
        to_char(meta.previous_session_date, 'YYYY-MM-DD') AS previous_session_date,
        meta.baseline_dates,
        meta.baseline_sessions_used,
        meta.lookback_trade_count,
        meta.unmapped_trade_count
      FROM nodes n
      LEFT JOIN last_trade lt ON lt.point_key = n.point_key
      LEFT JOIN report_agg ra ON ra.point_key = n.point_key
      LEFT JOIN previous_session_agg psa ON psa.point_key = n.point_key
      LEFT JOIN baseline_agg ba ON ba.point_key = n.point_key
      CROSS JOIN meta
      ORDER BY n.expiry_years ASC, n.tenor_years ASC
    `;

    const result = await query<PointGridFlowDbRow>(sql, sqlParams);
    const rows = result.rows || [];

    const diagnosticsFromRows = buildDiagnosticsFromRows(rows);

    const payloadRows: PointRow[] = rows.map((row) => {
      const pointKey = row.point_key;
      const lastTradeDate = row.last_trade_date || null;
      const daysSinceLastTrade = computeDaysBetweenDateKeys(asOfDate, lastTradeDate);
      const reportMetrics = toPointMetrics({
        tradeCount: row.report_trade_count,
        grossNotional: row.report_gross_notional,
        totalPremium: row.report_total_premium,
        avgPremium: row.report_avg_premium,
        avgBpvolYr: row.report_avg_bpvol_yr,
        bpvolObsCount: row.report_bpvol_obs_count,
      });
      const previousSessionMetrics = toPointMetrics({
        tradeCount: row.prev_trade_count,
        grossNotional: row.prev_gross_notional,
        totalPremium: row.prev_total_premium,
        avgPremium: row.prev_avg_premium,
        avgBpvolYr: row.prev_avg_bpvol_yr,
        bpvolObsCount: row.prev_bpvol_obs_count,
      });
      const avg5Metrics = toPointMetrics({
        tradeCount: row.avg5_trade_count,
        grossNotional: row.avg5_gross_notional,
        totalPremium: row.avg5_total_premium,
        avgPremium: row.avg5_avg_premium,
        avgBpvolYr: row.avg5_avg_bpvol_yr,
        bpvolObsCount: row.avg5_bpvol_obs_count,
      });
      const grossVs5SessionAvg = computeGrossVsAverage(
        reportMetrics.grossNotional,
        avg5Metrics.grossNotional,
      );
      const { signal, signalReason } = classifyPointSignal({
        reportTradeCount: reportMetrics.tradeCount,
        grossVs5SessionAvg,
        daysSinceLastTrade,
      });
      const bpvol1dChange = computeMetricChange(
        reportMetrics.avgBpvolYr,
        previousSessionMetrics.avgBpvolYr,
      );
      const avgPremium1dChange = computeMetricChange(
        reportMetrics.avgPremium,
        previousSessionMetrics.avgPremium,
      );

      return {
        pointKey,
        expiryLabel: row.expiry_label,
        tenorLabel: row.tenor_label,
        lastTradeDate,
        daysSinceLastTrade,
        reportDate: reportMetrics,
        previousSessionDate: previousSessionMetrics,
        previousSessionLabel: diagnosticsFromRows.previousSessionDate,
        avg5Sessions: avg5Metrics,
        grossVs5SessionAvg,
        bpvol1dChange,
        avgPremium1dChange,
        signal,
        signalReason,
      };
    });

    const positiveCount = payloadRows.filter((row) => row.signal === "positive").length;
    const negativeCount = payloadRows.filter((row) => row.signal === "negative").length;
    const neutralCount = payloadRows.filter((row) => row.signal === "neutral").length;

    const topGrossPoint =
      [...payloadRows]
        .sort((left, right) => right.reportDate.grossNotional - left.reportDate.grossNotional)
        .find((row) => row.reportDate.grossNotional > 0)?.pointKey ?? null;
    const topSurgePoint =
      [...payloadRows]
        .filter((row) => row.grossVs5SessionAvg !== null)
        .sort(
          (left, right) =>
            Number(right.grossVs5SessionAvg) - Number(left.grossVs5SessionAvg),
        )[0]?.pointKey ?? null;
    const stalestPoint =
      [...payloadRows]
        .filter((row) => row.daysSinceLastTrade !== null)
        .sort(
          (left, right) =>
            Number(right.daysSinceLastTrade) - Number(left.daysSinceLastTrade),
        )[0]?.pointKey ?? null;

    const response: PointGridFlowResponse = {
      meta: {
        timezone: ET_TIMEZONE as "America/New_York",
        asOfDate,
        platform,
        lookbackDays: POINT_GRID_LOOKBACK_DAYS,
        avgSessions: POINT_GRID_BASELINE_SESSIONS,
        baselineSessionsUsed: diagnosticsFromRows.baselineSessionsUsed,
      },
      nodes: POINT_GRID_NODES,
      rows: payloadRows,
      summary: {
        positiveCount,
        negativeCount,
        neutralCount,
        topGrossPoint,
        topSurgePoint,
        stalestPoint,
      },
      diagnostics: {
        reportDate: diagnosticsFromRows.reportDate,
        previousSessionDate: diagnosticsFromRows.previousSessionDate,
        baselineDates: diagnosticsFromRows.baselineDates,
        lookbackTradeCount: diagnosticsFromRows.lookbackTradeCount,
        unmappedTradeCount: diagnosticsFromRows.unmappedTradeCount,
      },
    };

    return NextResponse.json(response);
  } catch (error: any) {
    console.error("swaptions-tape/point-grid-flow GET error", error);
    return NextResponse.json(
      { error: error?.message || "Failed to fetch point-grid flow." },
      { status: 500 },
    );
  }
}
