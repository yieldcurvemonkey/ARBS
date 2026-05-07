// GET /api/usd-swaps-tape-v2/analytics-timeseries
// Returns pre-aggregated daily (or intraday) series split into custy + IDB
// platforms, plus daily-summed DV01 for the VOLUME view. Shape is the
// TimeseriesPointAug contract the analytics dock consumes directly.
import { analyticsQuery as query } from '@/lib/db'
import { analyticsHandler } from '@/lib/usd-swaps-tape-v2/analyticsHandler'
import {
  packageAnalyticsCtes,
  packageAnalyticsFilterPredicate,
  rangeToStartDate,
  rateToBps,
  safeNum,
} from '@/lib/usd-swaps-tape-v2/analytics'
import { ServerLru } from '@/lib/usd-swaps-tape-v2/serverLru'
import {
  buildOutrightTapeLabelCandidates,
  buildTapeLabelCandidates,
  custyNotionalOutlierPredicate,
  isOutrightTapeLabelCandidate,
  parseBooleanParam,
  riskAggregateExpression,
} from './route.logic'

// Phase 2 cutover: analytics-timeseries reads from the v2 leg table so it
// benefits from the new (filter, original_execution_timestamp DESC)
// composite indexes added in _tape_schema_v2.py. v1 stays the rollback
// target; flip this constant to revert.
const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const PACKAGES_TABLE = 'arbs_usd_swap_tape_packages_v2'

// Phase 4 contract: every analytics-dock route exposes the canonical
// underlier key under groupBy=canonical. The actual SQL filter is
// constructed by packageAnalyticsFilterPredicate() in
// @/lib/usd-swaps-tape-v2/analytics — the table below is the
// route-local view that lets the contract test (and a human reader)
// confirm the mapping without grepping the helper.
const GROUP_BY_COLUMN = {
  package: 'p.package_id',
  tape_label: 'p.tape_label',
  trade_type: 'p.package_type',
  tenor: 'l.tenor_label',
  canonical: 'l.canonical_underlier_key',
} as const
void GROUP_BY_COLUMN

// Phase 2 cap: at most this many daily rows / intraday ticks per request.
// Daily series LIMIT covers ~5y of trading days; intraday is intrinsically
// bounded by the 72h anchor window and stays at the smaller cap.
const DAILY_ROW_CAP = 2000
const INTRADAY_TICK_CAP = 5000

const LRU_MAX = Number(process.env.ANALYTICS_LRU_MAX ?? 2048)
const LRU_TTL = Number(process.env.ANALYTICS_LRU_TTL ?? 300_000)
const lru = new ServerLru<{ payload: unknown; etag: string }>({
  max: LRU_MAX,
  ttlMs: LRU_TTL,
})

const CACHE_HEADERS = {
  'Cache-Control': 'private, max-age=300, stale-while-revalidate=600',
} as const

type DailyRow = {
  day: string
  idb_close: number | null
  custy_close: number | null
  idb_open: number | null
  custy_open: number | null
  idb_high: number | null
  idb_low: number | null
  custy_high: number | null
  custy_low: number | null
  // Phase 5 (orthogonal-payload split): server returns all four
  // (gross|net) × (raw|filtered-large-custy) variants in a single
  // payload so the client toggles display without re-fetching. Legacy
  // {idb,custy}_dv01 / {idb,custy}_notional fields kept for backward
  // compatibility (populated with the requested variant).
  idb_dv01_gross: number | null
  custy_dv01_gross: number | null
  idb_dv01_net: number | null
  custy_dv01_net: number | null
  custy_dv01_gross_excl_large: number | null
  custy_dv01_net_excl_large: number | null
  idb_dv01: number | null
  custy_dv01: number | null
  idb_notional: number | null
  custy_notional: number | null
  custy_notional_excl_large: number | null
  idb_prints: number | null
  custy_prints: number | null
  custy_prints_excl_large: number | null
}

type IntradayRow = {
  ts: string
  platform: 'IDB' | 'CUSTY'
  fixed_rate: number | null
  risk: number | null
  notional: number | null
}

type AnalyticsTimeseriesPayload =
  | { error: string }
  | {
      points: Array<Record<string, unknown>>
      count: number
      view: string
      range: string
    }

function mapDailyRowsToPoints(
  rows: DailyRow[],
  useGrossDv01: boolean,
  excludeLargeCusty: boolean,
): Array<Record<string, unknown>> {
  return rows.map((r) => {
    // Phase 5: orthogonal-payload split. The legacy idbDv01 /
    // custyDv01 / *Notional / *Prints fields are populated with the
    // requested (gross|net) x (raw|excl-large) variant so existing
    // clients see no API change. New *_gross / *_net /
    // *_excl_large_custy fields let the client toggle locally.
    const idbDv01Picked = useGrossDv01
      ? safeNum(r.idb_dv01_gross)
      : safeNum(r.idb_dv01_net)
    const custyDv01Picked = excludeLargeCusty
      ? useGrossDv01
        ? safeNum(r.custy_dv01_gross_excl_large)
        : safeNum(r.custy_dv01_net_excl_large)
      : useGrossDv01
        ? safeNum(r.custy_dv01_gross)
        : safeNum(r.custy_dv01_net)
    const custyNotionalPicked = excludeLargeCusty
      ? safeNum(r.custy_notional_excl_large)
      : safeNum(r.custy_notional)
    const custyPrintsPicked = excludeLargeCusty
      ? safeNum(r.custy_prints_excl_large)
      : safeNum(r.custy_prints)
    return {
      ts: typeof r.day === 'string' ? r.day : new Date(r.day as unknown as Date).toISOString(),
      idbClose: r.idb_close != null ? rateToBps(r.idb_close) : null,
      custyClose: r.custy_close != null ? rateToBps(r.custy_close) : null,
      open: r.idb_open != null ? rateToBps(r.idb_open) : null,
      high: r.idb_high != null ? rateToBps(r.idb_high) : null,
      low: r.idb_low != null ? rateToBps(r.idb_low) : null,
      close: r.idb_close != null ? rateToBps(r.idb_close) : null,
      idbDv01: idbDv01Picked,
      custyDv01: custyDv01Picked,
      idbNotional: safeNum(r.idb_notional),
      custyNotional: custyNotionalPicked,
      idbPrints: safeNum(r.idb_prints),
      custyPrints: custyPrintsPicked,
      // Orthogonal-option payload split: full variant grid so the
      // client can flip useGrossDv01 / excludeLargeCusty without
      // re-fetching.
      idbDv01_gross: safeNum(r.idb_dv01_gross),
      idbDv01_net: safeNum(r.idb_dv01_net),
      custyDv01_gross: safeNum(r.custy_dv01_gross),
      custyDv01_net: safeNum(r.custy_dv01_net),
      custyDv01_gross_excl_large: safeNum(r.custy_dv01_gross_excl_large),
      custyDv01_net_excl_large: safeNum(r.custy_dv01_net_excl_large),
      custyNotional_raw: safeNum(r.custy_notional),
      custyNotional_excl_large: safeNum(r.custy_notional_excl_large),
      custyPrints_raw: safeNum(r.custy_prints),
      custyPrints_excl_large: safeNum(r.custy_prints_excl_large),
    }
  })
}

async function produceOutrightPackageTimeseries(args: {
  labelCandidates: string[]
  view: string
  range: string
  startDate: Date
  endDate: Date
  useGrossDv01: boolean
  excludeLargeCusty: boolean
  removeZeroRates: boolean
}): Promise<{ status: number; payload: AnalyticsTimeseriesPayload }> {
  const {
    labelCandidates,
    view,
    range,
    startDate,
    endDate,
    useGrossDv01,
    excludeLargeCusty,
    removeZeroRates,
  } = args
  const outlierPredicate = custyNotionalOutlierPredicate('b', 't', excludeLargeCusty)

  if (view === 'INTRADAY') {
    const INTRADAY_HOURS = 72
    const intradaySql = `
      WITH anchor AS (
        SELECT COALESCE(MAX(COALESCE(p.original_execution_start, p.execution_start)), NOW()) AS last_ts
        FROM ${PACKAGES_TABLE} p
        WHERE UPPER(COALESCE(p.tape_label, '')) = ANY($1::text[])
          AND UPPER(COALESCE(p.package_type, '')) = 'OUTRIGHT'
          AND NOT COALESCE(p.is_unwind, false)
      ),
      package_rows AS (
        SELECT
          COALESCE(p.original_execution_start, p.execution_start) AS ts,
          p.weighted_fixed_rate::float AS fixed_rate,
          p.total_risk::float AS risk,
          COALESCE(
            ABS(p.total_notional::float),
            ABS(p.gross_notional::float),
            0
          ) AS notional,
          p.venue
        FROM ${PACKAGES_TABLE} p
        WHERE UPPER(COALESCE(p.tape_label, '')) = ANY($1::text[])
          AND UPPER(COALESCE(p.package_type, '')) = 'OUTRIGHT'
          AND NOT COALESCE(p.is_unwind, false)
          AND COALESCE(p.original_execution_start, p.execution_start)
                >= (SELECT last_ts FROM anchor) - INTERVAL '${INTRADAY_HOURS} hours'
          AND p.weighted_fixed_rate IS NOT NULL
      ),
      base AS (
        SELECT
          ts,
          fixed_rate,
          risk,
          notional,
          CASE
            WHEN UPPER(COALESCE(r.venue, '')) = 'D2D' THEN 'IDB'
            ELSE 'CUSTY'
          END AS platform
        FROM package_rows r
      ),
      custy_threshold AS (
        SELECT
          percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
        FROM base
        WHERE platform = 'CUSTY' AND notional IS NOT NULL
      )
      SELECT
        b.ts,
        b.platform,
        b.fixed_rate,
        b.risk,
        b.notional
      FROM base b
      CROSS JOIN custy_threshold t
      WHERE ${outlierPredicate}
        ${removeZeroRates ? 'AND b.fixed_rate <> 0' : ''}
      ORDER BY b.ts ASC
      LIMIT ${INTRADAY_TICK_CAP}
    `
    const { rows } = await query<IntradayRow>(intradaySql, [labelCandidates])
    const points = rows.map((r) => ({
      ts: r.ts,
      idbClose: r.platform === 'IDB' ? rateToBps(r.fixed_rate) : null,
      custyClose: r.platform === 'CUSTY' ? rateToBps(r.fixed_rate) : null,
      idbDv01: r.platform === 'IDB'
        ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
        : 0,
      custyDv01: r.platform === 'CUSTY'
        ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
        : 0,
      idbNotional: r.platform === 'IDB' ? Math.abs(safeNum(r.notional)) : 0,
      custyNotional: r.platform === 'CUSTY' ? Math.abs(safeNum(r.notional)) : 0,
      idbPrints: r.platform === 'IDB' ? 1 : 0,
      custyPrints: r.platform === 'CUSTY' ? 1 : 0,
    }))
    return {
      status: 200,
      payload: { points, count: points.length, view, range },
    }
  }

  const dailySql = `
    WITH package_rows AS (
      SELECT
        COALESCE(p.original_execution_start, p.execution_start) AS ts,
        p.weighted_fixed_rate::float AS fixed_rate,
        p.total_risk::float AS risk,
        COALESCE(
          ABS(p.total_notional::float),
          ABS(p.gross_notional::float),
          0
        ) AS notional,
        p.venue
      FROM ${PACKAGES_TABLE} p
      WHERE UPPER(COALESCE(p.tape_label, '')) = ANY($1::text[])
        AND UPPER(COALESCE(p.package_type, '')) = 'OUTRIGHT'
        AND NOT COALESCE(p.is_unwind, false)
        AND COALESCE(p.original_execution_start, p.execution_start)
              >= $2::timestamptz
        AND COALESCE(p.original_execution_start, p.execution_start)
              <= $3::timestamptz
        AND p.weighted_fixed_rate IS NOT NULL
    ),
    base AS (
      SELECT
        ts,
        fixed_rate,
        risk,
        notional,
        CASE
          WHEN UPPER(COALESCE(r.venue, '')) = 'D2D' THEN 'IDB'
          ELSE 'CUSTY'
        END AS platform,
        DATE_TRUNC('day', ts AT TIME ZONE 'America/New_York') AS day
      FROM package_rows r
      ${removeZeroRates ? 'WHERE fixed_rate <> 0' : ''}
    ),
    custy_threshold AS (
      SELECT
        percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
      FROM base
      WHERE platform = 'CUSTY' AND notional IS NOT NULL
    ),
    classified AS (
      SELECT
        b.*,
        CASE
          WHEN b.platform <> 'CUSTY' THEN TRUE
          WHEN t.median_notional IS NULL OR t.median_notional <= 0 THEN TRUE
          WHEN ABS(COALESCE(b.notional, 0)) > t.median_notional * 5 THEN FALSE
          ELSE TRUE
        END AS excl_large_custy
      FROM base b
      CROSS JOIN custy_threshold t
    ),
    per_day_platform AS (
      SELECT
        day,
        platform,
        (array_agg(fixed_rate ORDER BY ts DESC)
          FILTER (WHERE fixed_rate IS NOT NULL))[1] AS close_rate,
        (array_agg(fixed_rate ORDER BY ts ASC)
          FILTER (WHERE fixed_rate IS NOT NULL))[1] AS open_rate,
        MAX(fixed_rate) AS high_rate,
        MIN(fixed_rate) AS low_rate,
        SUM(ABS(risk)) AS daily_dv01_gross,
        SUM(risk) AS daily_dv01_net,
        SUM(ABS(risk)) FILTER (WHERE excl_large_custy) AS daily_dv01_gross_excl_large,
        SUM(risk) FILTER (WHERE excl_large_custy) AS daily_dv01_net_excl_large,
        SUM(ABS(notional)) AS daily_notional,
        SUM(ABS(notional)) FILTER (WHERE excl_large_custy) AS daily_notional_excl_large,
        COUNT(*) AS prints,
        COUNT(*) FILTER (WHERE excl_large_custy) AS prints_excl_large
      FROM classified
      GROUP BY day, platform
    )
    SELECT
      day,
      MAX(close_rate) FILTER (WHERE platform = 'IDB')   AS idb_close,
      MAX(close_rate) FILTER (WHERE platform = 'CUSTY') AS custy_close,
      MAX(open_rate)  FILTER (WHERE platform = 'IDB')   AS idb_open,
      MAX(open_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_open,
      MAX(high_rate)  FILTER (WHERE platform = 'IDB')   AS idb_high,
      MIN(low_rate)   FILTER (WHERE platform = 'IDB')   AS idb_low,
      MAX(high_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_high,
      MIN(low_rate)   FILTER (WHERE platform = 'CUSTY') AS custy_low,
      COALESCE(MAX(daily_dv01_gross) FILTER (WHERE platform = 'IDB'),   0)            AS idb_dv01_gross,
      COALESCE(MAX(daily_dv01_gross) FILTER (WHERE platform = 'CUSTY'), 0)            AS custy_dv01_gross,
      COALESCE(MAX(daily_dv01_net)   FILTER (WHERE platform = 'IDB'),   0)            AS idb_dv01_net,
      COALESCE(MAX(daily_dv01_net)   FILTER (WHERE platform = 'CUSTY'), 0)            AS custy_dv01_net,
      COALESCE(MAX(daily_dv01_gross_excl_large) FILTER (WHERE platform = 'CUSTY'), 0) AS custy_dv01_gross_excl_large,
      COALESCE(MAX(daily_dv01_net_excl_large)   FILTER (WHERE platform = 'CUSTY'), 0) AS custy_dv01_net_excl_large,
      COALESCE(MAX(daily_notional)              FILTER (WHERE platform = 'IDB'),   0) AS idb_notional,
      COALESCE(MAX(daily_notional)              FILTER (WHERE platform = 'CUSTY'), 0) AS custy_notional,
      COALESCE(MAX(daily_notional_excl_large)   FILTER (WHERE platform = 'CUSTY'), 0) AS custy_notional_excl_large,
      COALESCE(MAX(prints)            FILTER (WHERE platform = 'IDB'),   0)           AS idb_prints,
      COALESCE(MAX(prints)            FILTER (WHERE platform = 'CUSTY'), 0)           AS custy_prints,
      COALESCE(MAX(prints_excl_large) FILTER (WHERE platform = 'CUSTY'), 0)           AS custy_prints_excl_large
    FROM per_day_platform
    GROUP BY day
    ORDER BY day ASC
    LIMIT ${DAILY_ROW_CAP}
  `
  const { rows } = await query<DailyRow>(dailySql, [
    labelCandidates,
    startDate.toISOString(),
    endDate.toISOString(),
  ])
  const points = mapDailyRowsToPoints(rows, useGrossDv01, excludeLargeCusty)
  return {
    status: 200,
    payload: { points, count: points.length, view, range },
  }
}

async function produceAnalyticsTimeseries(
  request: Request,
): Promise<{ status: number; payload: AnalyticsTimeseriesPayload }> {
  const { searchParams } = new URL(request.url)
  const value = searchParams.get('value')
  if (!value) {
    return { status: 400, payload: { error: 'value parameter is required' } }
  }
  const view = (searchParams.get('view') ?? 'DAILY_CLOSE').toUpperCase()
  const range = (searchParams.get('range') ?? '1Y').toUpperCase()
  const groupBy = (searchParams.get('groupBy') ?? 'tape_label').toLowerCase()
  const useGrossDv01 = parseBooleanParam(searchParams, 'useGrossDv01', false)
  const excludeLargeCusty = parseBooleanParam(searchParams, 'excludeLargeCusty', true)
  // Trader-requested: drop reported-0 fixed_rate prints from the
  // bucket aggregation entirely. Most are compression / off-market
  // markers and dragging the median down. Default ON; client can
  // pass `removeZeroRates=false` to inspect the raw distribution.
  const removeZeroRates = parseBooleanParam(searchParams, 'removeZeroRates', true)
  const useCandidates = groupBy === 'tape_label'
  const filterPredicate = packageAnalyticsFilterPredicate(
    groupBy, '$1', LEGS_TABLE, { candidatesMode: useCandidates },
  )
  if (!filterPredicate) {
    return { status: 400, payload: { error: `invalid groupBy: ${groupBy}` } }
  }
  const fromParam = searchParams.get('from')
  const toParam = searchParams.get('to')
  const startDate =
    range === 'CUSTOM' && fromParam ? new Date(fromParam) : rangeToStartDate(range)
  const endDate = range === 'CUSTOM' && toParam ? new Date(toParam) : new Date()

  const riskAgg = riskAggregateExpression(useGrossDv01)
  const outlierPredicate = custyNotionalOutlierPredicate('b', 't', excludeLargeCusty)
  const queryValue: unknown = useCandidates
    ? buildTapeLabelCandidates(value)
    : value

  try {
    if (groupBy === 'tape_label' && isOutrightTapeLabelCandidate(value)) {
      const fast = await produceOutrightPackageTimeseries({
        labelCandidates: buildOutrightTapeLabelCandidates(value),
        view,
        range,
        startDate,
        endDate,
        useGrossDv01,
        excludeLargeCusty,
        removeZeroRates,
      })
      if ('count' in fast.payload && fast.payload.count > 0) {
        return fast
      }
    }

    if (view === 'INTRADAY') {
      // Intraday is intrinsically a short-window view — pin the server
      // lookback to the latest N trading-ish days regardless of the
      // client's range selector. Using MAX(execution_timestamp) for the
      // bucket as the anchor keeps the window useful even on weekends
      // when "now - 1 day" would otherwise pre-date the last print.
      const INTRADAY_HOURS = 72
      const intradaySql = `
        WITH anchor AS (
          SELECT COALESCE(MAX(COALESCE(p.original_execution_start, p.execution_start)), NOW()) AS last_ts
          FROM ${PACKAGES_TABLE} p
          WHERE ${filterPredicate}
            AND NOT COALESCE(p.is_unwind, false)
        ),
        ${packageAnalyticsCtes({
          packagesTable: PACKAGES_TABLE,
          legsTable: LEGS_TABLE,
          filterPredicate,
          timePredicate: `COALESCE(p.original_execution_start, p.execution_start)
                >= (SELECT last_ts FROM anchor) - INTERVAL '${INTRADAY_HOURS} hours'`,
        })},
        custy_threshold AS (
          SELECT
            percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
          FROM package_summary
          WHERE platform = 'CUSTY' AND notional IS NOT NULL
        )
        SELECT
          b.ts,
          b.platform,
          b.fixed_rate,
          b.risk,
          b.notional
        FROM package_summary b
        CROSS JOIN custy_threshold t
        WHERE ${outlierPredicate}
          ${removeZeroRates ? 'AND b.fixed_rate <> 0' : ''}
        ORDER BY b.ts ASC
        LIMIT ${INTRADAY_TICK_CAP}
      `
      // startDate/endDate params retained for API shape parity; actual
      // window is anchor-derived above.
      void startDate; void endDate
      const { rows } = await query<IntradayRow>(intradaySql, [queryValue])
      // Project raw ticks onto the TimeseriesPointAug shape — one side
      // of the pair is null when the other platform produced the print.
      // DV01 / notional populated per-tick so the DV01 view gets proper
      // per-print bars without needing a second fetch.
      const points = rows.map((r) => ({
        ts: r.ts,
        idbClose: r.platform === 'IDB' ? rateToBps(r.fixed_rate) : null,
        custyClose: r.platform === 'CUSTY' ? rateToBps(r.fixed_rate) : null,
        idbDv01: r.platform === 'IDB'
          ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
          : 0,
        custyDv01: r.platform === 'CUSTY'
          ? useGrossDv01 ? Math.abs(safeNum(r.risk)) : safeNum(r.risk)
          : 0,
        idbNotional: r.platform === 'IDB' ? Math.abs(safeNum(r.notional)) : 0,
        custyNotional: r.platform === 'CUSTY' ? Math.abs(safeNum(r.notional)) : 0,
        idbPrints: r.platform === 'IDB' ? 1 : 0,
        custyPrints: r.platform === 'CUSTY' ? 1 : 0,
      }))
      return {
        status: 200,
        payload: { points, count: points.length, view, range },
      }
    }

    // DAILY_CLOSE / DAILY_OHLC / VOLUME — all share a daily aggregate,
    // extra columns filled in only for the OHLC / VOLUME overlays.
    //
    // Close/open are implemented via array_agg(... ORDER BY ts)[1] so we
    // get "the row that actually closed the day" rather than a numeric
    // MIN/MAX over rates. That keeps sparse days intact: if only one
    // platform printed, the other side stays NULL and the client drops
    // the point from that line instead of drawing to zero.
    //
    // Phase 5 (orthogonal-payload split): the SUM(risk) / SUM(ABS(risk))
    // / large-custy-filter dimensions all collapse into a single SQL
    // pass. We compute every (gross|net) × (raw|excluding-large-custy)
    // variant in CASE-driven aggregates so the client can toggle
    // display without re-fetching.
    //
    // The custy-large filter is implemented as `excl_large_custy` —
    // a boolean per-row flag that's TRUE for IDB and for CUSTY rows
    // below the 5x-median threshold. SUM(...) FILTER (WHERE
    // excl_large_custy) lets a single GROUP BY produce both the
    // unfiltered and filtered totals.
    const sql = `
      WITH ${packageAnalyticsCtes({
        packagesTable: PACKAGES_TABLE,
        legsTable: LEGS_TABLE,
        filterPredicate,
        timePredicate: `COALESCE(p.original_execution_start, p.execution_start)
              >= $2::timestamptz
          AND COALESCE(p.original_execution_start, p.execution_start)
              <= $3::timestamptz`,
      })},
      base AS (
        SELECT
          ts,
          fixed_rate,
          risk,
          notional,
          platform,
          DATE_TRUNC('day', ts AT TIME ZONE 'America/New_York') AS day
        FROM package_summary
        ${removeZeroRates ? 'WHERE fixed_rate <> 0' : ''}
      ),
      custy_threshold AS (
        SELECT
          percentile_cont(0.5) WITHIN GROUP (ORDER BY ABS(notional)) AS median_notional
        FROM base
        WHERE platform = 'CUSTY' AND notional IS NOT NULL
      ),
      classified AS (
        SELECT
          b.*,
          -- per-row flag: TRUE when this print survives the
          -- large-custy filter (IDB always, CUSTY only if below 5x
          -- median threshold or threshold absent).
          CASE
            WHEN b.platform <> 'CUSTY' THEN TRUE
            WHEN t.median_notional IS NULL OR t.median_notional <= 0 THEN TRUE
            WHEN ABS(COALESCE(b.notional, 0)) > t.median_notional * 5 THEN FALSE
            ELSE TRUE
          END AS excl_large_custy
        FROM base b
        CROSS JOIN custy_threshold t
      ),
      per_day_platform AS (
        SELECT
          day,
          platform,
          (array_agg(fixed_rate ORDER BY ts DESC)
            FILTER (WHERE fixed_rate IS NOT NULL))[1] AS close_rate,
          (array_agg(fixed_rate ORDER BY ts ASC)
            FILTER (WHERE fixed_rate IS NOT NULL))[1] AS open_rate,
          MAX(fixed_rate) AS high_rate,
          MIN(fixed_rate) AS low_rate,
          -- Both bases (gross / net) computed in one pass.
          SUM(ABS(risk)) AS daily_dv01_gross,
          SUM(risk) AS daily_dv01_net,
          -- Filtered variants: same aggregates, FILTER excludes large
          -- custy outliers.
          SUM(ABS(risk)) FILTER (WHERE excl_large_custy) AS daily_dv01_gross_excl_large,
          SUM(risk) FILTER (WHERE excl_large_custy) AS daily_dv01_net_excl_large,
          SUM(ABS(notional)) AS daily_notional,
          SUM(ABS(notional)) FILTER (WHERE excl_large_custy) AS daily_notional_excl_large,
          COUNT(*) AS prints,
          COUNT(*) FILTER (WHERE excl_large_custy) AS prints_excl_large
        FROM classified
        GROUP BY day, platform
      )
      SELECT
        day,
        MAX(close_rate) FILTER (WHERE platform = 'IDB')   AS idb_close,
        MAX(close_rate) FILTER (WHERE platform = 'CUSTY') AS custy_close,
        MAX(open_rate)  FILTER (WHERE platform = 'IDB')   AS idb_open,
        MAX(open_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_open,
        MAX(high_rate)  FILTER (WHERE platform = 'IDB')   AS idb_high,
        MIN(low_rate)   FILTER (WHERE platform = 'IDB')   AS idb_low,
        MAX(high_rate)  FILTER (WHERE platform = 'CUSTY') AS custy_high,
        MIN(low_rate)   FILTER (WHERE platform = 'CUSTY') AS custy_low,
        COALESCE(MAX(daily_dv01_gross) FILTER (WHERE platform = 'IDB'),   0)            AS idb_dv01_gross,
        COALESCE(MAX(daily_dv01_gross) FILTER (WHERE platform = 'CUSTY'), 0)            AS custy_dv01_gross,
        COALESCE(MAX(daily_dv01_net)   FILTER (WHERE platform = 'IDB'),   0)            AS idb_dv01_net,
        COALESCE(MAX(daily_dv01_net)   FILTER (WHERE platform = 'CUSTY'), 0)            AS custy_dv01_net,
        COALESCE(MAX(daily_dv01_gross_excl_large) FILTER (WHERE platform = 'CUSTY'), 0) AS custy_dv01_gross_excl_large,
        COALESCE(MAX(daily_dv01_net_excl_large)   FILTER (WHERE platform = 'CUSTY'), 0) AS custy_dv01_net_excl_large,
        COALESCE(MAX(daily_notional)              FILTER (WHERE platform = 'IDB'),   0) AS idb_notional,
        COALESCE(MAX(daily_notional)              FILTER (WHERE platform = 'CUSTY'), 0) AS custy_notional,
        COALESCE(MAX(daily_notional_excl_large)   FILTER (WHERE platform = 'CUSTY'), 0) AS custy_notional_excl_large,
        COALESCE(MAX(prints)            FILTER (WHERE platform = 'IDB'),   0)           AS idb_prints,
        COALESCE(MAX(prints)            FILTER (WHERE platform = 'CUSTY'), 0)           AS custy_prints,
        COALESCE(MAX(prints_excl_large) FILTER (WHERE platform = 'CUSTY'), 0)           AS custy_prints_excl_large
      FROM per_day_platform
      GROUP BY day
      ORDER BY day ASC
      LIMIT ${DAILY_ROW_CAP}
    `
    const { rows } = await query<DailyRow>(sql, [
      queryValue,
      startDate.toISOString(),
      endDate.toISOString(),
    ])
    const points = rows.map((r) => {
      // Phase 5: orthogonal-payload split. The legacy idbDv01 /
      // custyDv01 / *Notional / *Prints fields are populated with the
      // requested (gross|net) × (raw|excl-large) variant so existing
      // clients see no API change. New *_gross / *_net /
      // *_excl_large_custy fields let the client toggle locally.
      const idbDv01Picked = useGrossDv01
        ? safeNum(r.idb_dv01_gross)
        : safeNum(r.idb_dv01_net)
      const custyDv01Picked = excludeLargeCusty
        ? useGrossDv01
          ? safeNum(r.custy_dv01_gross_excl_large)
          : safeNum(r.custy_dv01_net_excl_large)
        : useGrossDv01
          ? safeNum(r.custy_dv01_gross)
          : safeNum(r.custy_dv01_net)
      const custyNotionalPicked = excludeLargeCusty
        ? safeNum(r.custy_notional_excl_large)
        : safeNum(r.custy_notional)
      const custyPrintsPicked = excludeLargeCusty
        ? safeNum(r.custy_prints_excl_large)
        : safeNum(r.custy_prints)
      return {
        ts: typeof r.day === 'string' ? r.day : new Date(r.day as unknown as Date).toISOString(),
        idbClose: r.idb_close != null ? rateToBps(r.idb_close) : null,
        custyClose: r.custy_close != null ? rateToBps(r.custy_close) : null,
        open: r.idb_open != null ? rateToBps(r.idb_open) : null,
        high: r.idb_high != null ? rateToBps(r.idb_high) : null,
        low: r.idb_low != null ? rateToBps(r.idb_low) : null,
        close: r.idb_close != null ? rateToBps(r.idb_close) : null,
        idbDv01: idbDv01Picked,
        custyDv01: custyDv01Picked,
        idbNotional: safeNum(r.idb_notional),
        custyNotional: custyNotionalPicked,
        idbPrints: safeNum(r.idb_prints),
        custyPrints: custyPrintsPicked,
        // Orthogonal-option payload split: full variant grid so the
        // client can flip useGrossDv01 / excludeLargeCusty without
        // re-fetching.
        idbDv01_gross: safeNum(r.idb_dv01_gross),
        idbDv01_net: safeNum(r.idb_dv01_net),
        custyDv01_gross: safeNum(r.custy_dv01_gross),
        custyDv01_net: safeNum(r.custy_dv01_net),
        custyDv01_gross_excl_large: safeNum(r.custy_dv01_gross_excl_large),
        custyDv01_net_excl_large: safeNum(r.custy_dv01_net_excl_large),
        custyNotional_raw: safeNum(r.custy_notional),
        custyNotional_excl_large: safeNum(r.custy_notional_excl_large),
        custyPrints_raw: safeNum(r.custy_prints),
        custyPrints_excl_large: safeNum(r.custy_prints_excl_large),
      }
    })
    return {
      status: 200,
      payload: { points, count: points.length, view, range },
    }
  } catch (error) {
    console.error('usd-swaps-tape-v2/analytics-timeseries error', error)
    const message = error instanceof Error ? error.message : 'Failed to fetch timeseries'
    return { status: 500, payload: { error: message } }
  }
}

export const GET = analyticsHandler(
  { lru, cacheHeaders: CACHE_HEADERS },
  produceAnalyticsTimeseries,
)
