import { query } from '@/lib/db'
import type {
  StirAliasRateRow,
  StirAliasTimeseriesPoint,
  StirCurveGridCurve,
  StirFlowHistoryDay,
  StirMeetingLadderRow,
  StirOvernightForwardCurveSeries,
  StirPackageBreakdownRow,
  StirSummary,
  StirTapeRow
} from '@/features/stir-dashboard/types'

const DISPLAY_VIEW = 'arbs_stir_display_items_v1'
const PACKAGES_TABLE = 'arbs_stir_packages_v1'
const LEGS_TABLE = 'arbs_stir_legs_v1'
const CURVE_TABLE = 'arbs_stir_curve_nodes_v1'
const CURVE_CB_FALLBACK_SQL = (alias: string) =>
  `coalesce(
    nullif(${alias}.central_bank, ''),
    CASE upper(coalesce(${alias}.currency, ''))
      WHEN 'USD' THEN 'FOMC'
      WHEN 'EUR' THEN 'ECB'
      WHEN 'GBP' THEN 'BOE'
      WHEN 'JPY' THEN 'BOJ'
      WHEN 'CAD' THEN 'BOC'
      WHEN 'CHF' THEN 'SNB'
      ELSE null
    END
  )`

const ALIAS_BANK_MAP: Record<string, string> = {
  fomc: 'FOMC',
  fed: 'FOMC',
  usd: 'FOMC',
  ecb: 'ECB',
  eur: 'ECB',
  boe: 'BOE',
  gbp: 'BOE',
  boj: 'BOJ',
  jpy: 'BOJ',
  boc: 'BOC',
  cad: 'BOC',
  snb: 'SNB',
  chf: 'SNB'
}
const MEETING_ALIAS_RE = /^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\d{2}$/i

export type StirWindowFilters = {
  start?: string | null
  end?: string | null
  centralBank?: string | null
  packageType?: string | null
}

function buildWindowWhere(
  filters: StirWindowFilters,
  alias: string,
  params: unknown[]
): string[] {
  const conditions: string[] = []
  if (filters.start) {
    params.push(filters.start)
    conditions.push(`${alias}.execution_start >= $${params.length}`)
  }
  if (filters.end) {
    params.push(filters.end)
    conditions.push(`${alias}.execution_start <= $${params.length}`)
  }
  if (filters.centralBank) {
    params.push(filters.centralBank)
    conditions.push(`${alias}.policy_central_bank = $${params.length}`)
  }
  if (filters.packageType) {
    params.push(filters.packageType)
    conditions.push(`${alias}.package_type = $${params.length}`)
  }
  return conditions
}

function normalizeCentralBank(value: string | null | undefined): string | null {
  if (!value) return null
  const normalized = value.trim().toUpperCase()
  if (!normalized || normalized === 'ALL') return null
  return normalized
}

function parseAliasInput(
  alias: string,
  fallbackCentralBank?: string | null
): {
  alias: string
  meetingLabel: string | null
  requestedCentralBank: string | null
} {
  const aliasRaw = String(alias || '').trim()
  const compact = aliasRaw.toLowerCase().replace(/[^a-z0-9]+/g, '_')
  const tokens = compact.split('_').filter(Boolean)
  let meetingLabel: string | null = null
  let requestedCentralBank: string | null = null

  tokens.forEach((token) => {
    if (!meetingLabel && MEETING_ALIAS_RE.test(token)) {
      meetingLabel = token.toLowerCase()
      return
    }
    if (!requestedCentralBank && ALIAS_BANK_MAP[token]) {
      requestedCentralBank = ALIAS_BANK_MAP[token]
    }
  })

  if (!requestedCentralBank) {
    requestedCentralBank = normalizeCentralBank(fallbackCentralBank)
  }

  return { alias: aliasRaw, meetingLabel, requestedCentralBank }
}

export async function fetchStirTape(
  filters: StirWindowFilters & { cursor?: string | null; limit?: number }
) {
  const params: unknown[] = []
  const conditions = buildWindowWhere(filters, 'd', params)

  if (filters.cursor) {
    params.push(filters.cursor)
    conditions.push(`d.execution_start < $${params.length}`)
  }

  const limit = Math.min(Math.max(filters.limit ?? 200, 1), 500)
  params.push(limit + 1)

  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
  const result = await query<StirTapeRow>(
    `SELECT
      d.package_id,
      d.package_type,
      d.curve_id,
      d.policy_central_bank,
      d.cb_dated_confidence,
      d.execution_start,
      d.execution_end,
      d.effective_date,
      d.expiration_date,
      d.legs_count,
      d.total_notional,
      d.gross_notional,
      d.total_risk,
      d.gross_risk,
      d.package_metrics,
      d.legs_json
     FROM ${DISPLAY_VIEW} d
     ${whereClause}
     ORDER BY d.execution_start DESC
     LIMIT $${params.length}`,
    params
  )

  let rows = result.rows
  let hasMore = false
  if (rows.length > limit) {
    hasMore = true
    rows = rows.slice(0, limit)
  }
  const nextCursor = hasMore ? rows[rows.length - 1]?.execution_start ?? null : null
  return { rows, hasMore, nextCursor }
}

export async function fetchStirSummary(filters: StirWindowFilters): Promise<StirSummary> {
  const params: unknown[] = []
  const conditions = buildWindowWhere(filters, 'p', params)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  const totalsResult = await query<{
    total_packages: number
    total_notional: number
    total_risk: number
    unmapped_count: number
  }>(
    `SELECT
      count(*)::int AS total_packages,
      coalesce(sum(abs(total_notional)), 0)::float8 AS total_notional,
      coalesce(sum(abs(total_risk)), 0)::float8 AS total_risk,
      count(*) FILTER (
        WHERE policy_central_bank IS NULL
           OR policy_central_bank = ''
           OR upper(coalesce(curve_id, '')) = 'UNMAPPED'
      )::int AS unmapped_count
     FROM ${PACKAGES_TABLE} p
     ${whereClause}`,
    params
  )

  const byBankResult = await query<{ central_bank: string; package_count: number; gross_notional: number; gross_risk: number }>(
    `SELECT
      coalesce(nullif(policy_central_bank, ''), 'UNMAPPED') AS central_bank,
      count(*)::int AS package_count,
      coalesce(sum(abs(total_notional)), 0)::float8 AS gross_notional,
      coalesce(sum(abs(total_risk)), 0)::float8 AS gross_risk
     FROM ${PACKAGES_TABLE} p
     ${whereClause}
     GROUP BY 1
     ORDER BY package_count DESC`
  , params)

  const totals = totalsResult.rows[0] || {
    total_packages: 0,
    total_notional: 0,
    total_risk: 0,
    unmapped_count: 0
  }
  return {
    totalPackages: Number(totals.total_packages) || 0,
    totalNotional: Number(totals.total_notional) || 0,
    totalRisk: Number(totals.total_risk) || 0,
    unmappedCount: Number(totals.unmapped_count) || 0,
    byCentralBank: byBankResult.rows.map((row) => ({
      centralBank: row.central_bank,
      packageCount: Number(row.package_count) || 0,
      grossNotional: Number(row.gross_notional) || 0,
      grossRisk: Number(row.gross_risk) || 0
    }))
  }
}

export async function fetchStirFlowHistory(
  filters: Pick<StirWindowFilters, 'start' | 'end' | 'centralBank'>
): Promise<StirFlowHistoryDay[]> {
  const params: unknown[] = []
  const conditions: string[] = []
  if (filters.start) {
    params.push(filters.start)
    conditions.push(`p.execution_start >= $${params.length}`)
  }
  if (filters.end) {
    params.push(filters.end)
    conditions.push(`p.execution_start <= $${params.length}`)
  }
  if (filters.centralBank) {
    params.push(filters.centralBank)
    conditions.push(`p.policy_central_bank = $${params.length}`)
  }
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  const result = await query<{
    trade_date: string
    central_bank: string
    package_count: number
    gross_notional: number
    gross_risk: number
  }>(
    `SELECT
      p.execution_start::date AS trade_date,
      coalesce(nullif(p.policy_central_bank, ''), 'UNMAPPED') AS central_bank,
      count(*)::int AS package_count,
      coalesce(sum(abs(p.total_notional)), 0)::float8 AS gross_notional,
      coalesce(sum(abs(p.total_risk)), 0)::float8 AS gross_risk
     FROM ${PACKAGES_TABLE} p
     ${whereClause}
     GROUP BY 1, 2
     ORDER BY 1 ASC, 2 ASC`,
    params
  )

  const dayMap = new Map<string, StirFlowHistoryDay>()
  result.rows.forEach((row) => {
    const date = String(row.trade_date).slice(0, 10)
    if (!dayMap.has(date)) {
      dayMap.set(date, { date, byCentralBank: [] })
    }
    dayMap.get(date)?.byCentralBank.push({
      centralBank: row.central_bank,
      packageCount: Number(row.package_count) || 0,
      grossNotional: Number(row.gross_notional) || 0,
      grossRisk: Number(row.gross_risk) || 0
    })
  })
  return Array.from(dayMap.values()).sort((a, b) => a.date.localeCompare(b.date))
}

export async function fetchStirMeetingLadder(
  filters: Pick<StirWindowFilters, 'start' | 'end' | 'centralBank'>
): Promise<StirMeetingLadderRow[]> {
  const params: unknown[] = []
  const conditions: string[] = []
  if (filters.start) {
    params.push(filters.start)
    conditions.push(`l.execution_timestamp >= $${params.length}`)
  }
  if (filters.end) {
    params.push(filters.end)
    conditions.push(`l.execution_timestamp <= $${params.length}`)
  }
  if (filters.centralBank) {
    params.push(filters.centralBank)
    conditions.push(`l.central_bank = $${params.length}`)
  }
  conditions.push(`l.cb_meeting_start IS NOT NULL`)
  conditions.push(`l.cb_meeting_end IS NOT NULL`)
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  const result = await query<StirMeetingLadderRow>(
    `SELECT
      coalesce(l.central_bank, 'UNMAPPED') AS "centralBank",
      l.cb_meeting_start AS "startMeeting",
      l.cb_meeting_end AS "endMeeting",
      count(*)::int AS "tradeCount",
      coalesce(sum(abs(l.notional)), 0)::float8 AS "grossNotional",
      coalesce(sum(abs(l.risk)), 0)::float8 AS "grossRisk"
     FROM ${LEGS_TABLE} l
     ${whereClause}
     GROUP BY 1, 2, 3
     ORDER BY "tradeCount" DESC, "grossNotional" DESC`
  , params)

  return result.rows
}

export async function fetchStirCurveGrid(
  curveName?: string | null
): Promise<StirCurveGridCurve[]> {
  const params: unknown[] = []
  const curveFilter = curveName
    ? (() => {
        params.push(curveName)
        return `WHERE curve_name = $${params.length}`
      })()
    : ''

  const result = await query<{
    curve_name: string
    reference_key: string
    currency: string
    central_bank: string | null
    snapshot_ts: string
    node_date: string
    zero_rate: number | null
    prev_zero_rate: number | null
    discount_factor: number | null
  }>(
    `WITH ranked AS (
      SELECT
        c.*,
        dense_rank() OVER (PARTITION BY c.curve_name ORDER BY c.snapshot_ts DESC) AS snap_rank
      FROM ${CURVE_TABLE} c
      ${curveFilter}
    ),
    latest AS (
      SELECT * FROM ranked WHERE snap_rank = 1
    ),
    previous AS (
      SELECT * FROM ranked WHERE snap_rank = 2
    )
    SELECT
      l.curve_name,
      l.reference_key,
      l.currency,
      l.central_bank,
      l.snapshot_ts::text,
      l.node_date::text,
      l.zero_rate::float8,
      p.zero_rate::float8 AS prev_zero_rate,
      l.discount_factor::float8
    FROM latest l
    LEFT JOIN previous p
      ON p.curve_name = l.curve_name AND p.node_date = l.node_date
    ORDER BY l.curve_name ASC, l.node_date ASC`,
    params
  )

  const byCurve = new Map<string, StirCurveGridCurve>()
  result.rows.forEach((row) => {
    if (!byCurve.has(row.curve_name)) {
      byCurve.set(row.curve_name, {
        curveName: row.curve_name,
        referenceKey: row.reference_key,
        currency: row.currency,
        centralBank: row.central_bank || null,
        snapshotTs: row.snapshot_ts,
        nodes: []
      })
    }
    byCurve.get(row.curve_name)?.nodes.push({
      nodeDate: row.node_date,
      zeroRate: row.zero_rate === null ? null : Number(row.zero_rate),
      prevZeroRate: row.prev_zero_rate === null ? null : Number(row.prev_zero_rate),
      discountFactor: row.discount_factor === null ? null : Number(row.discount_factor)
    })
  })
  return Array.from(byCurve.values())
}

export async function fetchStirPackageBreakdown(
  filters: Pick<StirWindowFilters, 'start' | 'end' | 'centralBank'>
): Promise<StirPackageBreakdownRow[]> {
  const params: unknown[] = []
  const conditions: string[] = []
  if (filters.start) {
    params.push(filters.start)
    conditions.push(`p.execution_start >= $${params.length}`)
  }
  if (filters.end) {
    params.push(filters.end)
    conditions.push(`p.execution_start <= $${params.length}`)
  }
  if (filters.centralBank) {
    params.push(filters.centralBank)
    conditions.push(`p.policy_central_bank = $${params.length}`)
  }
  const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

  const result = await query<StirPackageBreakdownRow>(
    `SELECT
      coalesce(nullif(p.package_type, ''), 'OUTRIGHT') AS "packageType",
      count(*)::int AS "packageCount",
      coalesce(sum(abs(p.total_notional)), 0)::float8 AS "grossNotional",
      coalesce(sum(abs(p.total_risk)), 0)::float8 AS "grossRisk"
     FROM ${PACKAGES_TABLE} p
     ${whereClause}
     GROUP BY 1
     ORDER BY "packageCount" DESC, "grossNotional" DESC`,
    params
  )
  return result.rows
}

export async function fetchStirAliasRates(filters: {
  aliases: string[]
  centralBank?: string | null
  asOf?: string | null
  lookbackDays?: number
}): Promise<StirAliasRateRow[]> {
  const rawAliases = filters.aliases
    .map((entry) => String(entry || '').trim())
    .filter(Boolean)
    .slice(0, 120)
  if (!rawAliases.length) return []

  const parsed = rawAliases.map((alias) => parseAliasInput(alias, filters.centralBank))
  const aliasInputs = parsed.map((row) => row.alias)
  const meetings = parsed.map((row) => row.meetingLabel)
  const requestedBanks = parsed.map((row) => row.requestedCentralBank)

  const asOfTs = filters.asOf || new Date().toISOString()
  const lookbackDays = Math.max(1, Math.min(filters.lookbackDays ?? 30, 180))

  const result = await query<StirAliasRateRow>(
    `WITH alias_inputs AS (
      SELECT *
      FROM unnest(
        $1::text[],
        $2::text[],
        $3::text[]
      ) AS t(alias_input, meeting_label, requested_bank)
    ),
    base AS MATERIALIZED (
      SELECT
        l.central_bank,
        l.cb_curve_key,
        l.cb_meeting_start,
        l.cb_meeting_end,
        l.execution_timestamp,
        l.fixed_rate
      FROM ${LEGS_TABLE} l
      WHERE l.fixed_rate IS NOT NULL
        AND l.lifecycle_role = 'PRIMARY'
        AND l.execution_timestamp <= $4::timestamptz
        AND l.execution_timestamp >= ($4::timestamptz - make_interval(days => $5::int))
    )
    SELECT
      ai.alias_input AS "alias",
      ai.meeting_label AS "meetingLabel",
      ai.requested_bank AS "requestedCentralBank",
      latest.central_bank AS "centralBank",
      latest.cb_curve_key AS "curveKey",
      latest.cb_meeting_start AS "startMeeting",
      latest.cb_meeting_end AS "endMeeting",
      latest.execution_timestamp::text AS "lastExecutionTimestamp",
      latest.fixed_rate::float8 AS "lastFixedRate",
      agg.avg_fixed_rate::float8 AS "avgFixedRate",
      coalesce(agg.trade_count, 0)::int AS "tradeCount"
    FROM alias_inputs ai
    LEFT JOIN LATERAL (
      SELECT
        b.central_bank,
        b.cb_curve_key,
        b.cb_meeting_start,
        b.cb_meeting_end,
        b.execution_timestamp,
        b.fixed_rate
      FROM base b
      WHERE ai.meeting_label IS NOT NULL
        AND (
          lower(coalesce(b.cb_meeting_start, '')) = ai.meeting_label
          OR lower(coalesce(b.cb_meeting_end, '')) = ai.meeting_label
        )
        AND (
          ai.requested_bank IS NULL
          OR upper(coalesce(b.central_bank, '')) = ai.requested_bank
        )
      ORDER BY b.execution_timestamp DESC
      LIMIT 1
    ) latest ON TRUE
    LEFT JOIN LATERAL (
      SELECT
        count(*)::int AS trade_count,
        avg(b.fixed_rate)::float8 AS avg_fixed_rate
      FROM base b
      WHERE ai.meeting_label IS NOT NULL
        AND (
          lower(coalesce(b.cb_meeting_start, '')) = ai.meeting_label
          OR lower(coalesce(b.cb_meeting_end, '')) = ai.meeting_label
        )
        AND (
          ai.requested_bank IS NULL
          OR upper(coalesce(b.central_bank, '')) = ai.requested_bank
        )
    ) agg ON TRUE`,
    [aliasInputs, meetings, requestedBanks, asOfTs, lookbackDays]
  )

  return result.rows
}

export async function fetchStirAliasTimeseries(filters: {
  alias: string
  granularity?: 'intraday' | 'eod'
  centralBank?: string | null
  start?: string | null
  end?: string | null
  lookbackDays?: number
}): Promise<StirAliasTimeseriesPoint[]> {
  const parsed = parseAliasInput(filters.alias, filters.centralBank)
  if (!parsed.meetingLabel) return []

  const endTs = filters.end || new Date().toISOString()
  const lookbackDays = Math.max(1, Math.min(filters.lookbackDays ?? 30, 180))
  const startTs =
    filters.start ||
    new Date(Date.now() - lookbackDays * 24 * 60 * 60 * 1000).toISOString()
  const bucketExpr =
    filters.granularity === 'eod'
      ? `date_trunc('day', b.execution_timestamp)`
      : `date_trunc('hour', b.execution_timestamp)`

  const result = await query<StirAliasTimeseriesPoint>(
    `WITH base AS (
      SELECT
        l.execution_timestamp,
        l.fixed_rate
      FROM ${LEGS_TABLE} l
      WHERE l.fixed_rate IS NOT NULL
        AND l.lifecycle_role = 'PRIMARY'
        AND l.execution_timestamp >= $1::timestamptz
        AND l.execution_timestamp <= $2::timestamptz
        AND (
          lower(coalesce(l.cb_meeting_start, '')) = $3::text
          OR lower(coalesce(l.cb_meeting_end, '')) = $3::text
        )
        AND (
          $4::text IS NULL
          OR upper(coalesce(l.central_bank, '')) = $4::text
        )
    )
    SELECT
      ${bucketExpr}::text AS "bucketTs",
      count(*)::int AS "tradeCount",
      avg(b.fixed_rate)::float8 AS "avgFixedRate",
      (array_agg(b.fixed_rate ORDER BY b.execution_timestamp DESC))[1]::float8 AS "lastFixedRate"
    FROM base b
    GROUP BY 1
    ORDER BY 1 ASC`,
    [startTs, endTs, parsed.meetingLabel, parsed.requestedCentralBank]
  )

  return result.rows
}

export async function fetchStirOvernightForwardCurve(filters: {
  curveName?: string | null
  centralBank?: string | null
}): Promise<StirOvernightForwardCurveSeries[]> {
  const normalizedCurveName = String(filters.curveName || '').trim() || null
  const normalizedBank = normalizeCentralBank(filters.centralBank)

  async function runQuery(
    curveName: string | null,
    centralBank: string | null
  ) {
    const params: unknown[] = []
    const conditions: string[] = []
    if (curveName) {
      params.push(curveName)
      conditions.push(`c.curve_name = $${params.length}`)
    }
    if (centralBank && !curveName) {
      params.push(centralBank)
      conditions.push(`upper(${CURVE_CB_FALLBACK_SQL('c')}) = $${params.length}`)
    }
    const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''

    return query<{
    curveName: string
    referenceKey: string
    currency: string
    centralBank: string | null
    snapshotTs: string
    nodeDate: string
    zeroRate: number | null
    discountFactor: number | null
    forwardRate: number | null
  }>(
      `WITH ranked AS (
      SELECT
        c.*,
        dense_rank() OVER (PARTITION BY c.curve_name ORDER BY c.snapshot_ts DESC) AS snap_rank
      FROM ${CURVE_TABLE} c
      ${whereClause}
    ),
    latest AS (
      SELECT * FROM ranked WHERE snap_rank = 1
    ),
    ordered AS (
      SELECT
        l.curve_name,
        l.reference_key,
        l.currency,
        l.central_bank,
        l.snapshot_ts,
        l.node_date,
        l.zero_rate,
        l.discount_factor,
        l.forward_rate,
        lag(l.node_date) OVER (PARTITION BY l.curve_name ORDER BY l.node_date) AS prev_node_date,
        lag(l.discount_factor) OVER (PARTITION BY l.curve_name ORDER BY l.node_date) AS prev_discount_factor
      FROM latest l
    )
    SELECT
      o.curve_name AS "curveName",
      o.reference_key AS "referenceKey",
      o.currency AS "currency",
      ${CURVE_CB_FALLBACK_SQL('o')} AS "centralBank",
      o.snapshot_ts::text AS "snapshotTs",
      o.node_date::text AS "nodeDate",
      o.zero_rate::float8 AS "zeroRate",
      o.discount_factor::float8 AS "discountFactor",
      coalesce(
        o.forward_rate::float8,
        CASE
          WHEN o.prev_discount_factor IS NULL OR o.discount_factor IS NULL THEN NULL
          WHEN o.prev_discount_factor <= 0 OR o.discount_factor <= 0 THEN NULL
          WHEN o.prev_node_date IS NULL OR o.node_date <= o.prev_node_date THEN NULL
          ELSE (
            ln(o.prev_discount_factor / o.discount_factor)
            / ((o.node_date - o.prev_node_date)::float8 / 365.0)
          )::float8
        END
      ) AS "forwardRate"
    FROM ordered o
    ORDER BY o.curve_name ASC, o.node_date ASC`,
      params
    )
  }

  let result = await runQuery(normalizedCurveName, normalizedBank)
  if (!result.rows.length && normalizedCurveName) {
    result = await runQuery(null, normalizedBank)
  }
  if (!result.rows.length && normalizedBank) {
    result = await runQuery(null, null)
  }

  const byCurve = new Map<string, StirOvernightForwardCurveSeries>()
  result.rows.forEach((row) => {
    if (!byCurve.has(row.curveName)) {
      byCurve.set(row.curveName, {
        curveName: row.curveName,
        referenceKey: row.referenceKey,
        currency: row.currency,
        centralBank: row.centralBank,
        snapshotTs: row.snapshotTs,
        points: []
      })
    }
    byCurve.get(row.curveName)?.points.push({
      nodeDate: row.nodeDate,
      zeroRate: row.zeroRate === null ? null : Number(row.zeroRate),
      discountFactor:
        row.discountFactor === null ? null : Number(row.discountFactor),
      forwardRate: row.forwardRate === null ? null : Number(row.forwardRate)
    })
  })

  return Array.from(byCurve.values())
}
