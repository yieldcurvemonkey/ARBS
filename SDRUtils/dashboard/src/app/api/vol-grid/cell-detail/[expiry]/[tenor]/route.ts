import { NextResponse } from 'next/server'
import {
  EXPIRY_POINTS,
  TENOR_POINTS,
  resolveSnapshotPreset
} from '@/features/vol-grid/constants'
import type {
  CalibrationObservation,
  CalibrationPresetKey,
  CellDetailResponse,
  VolGridHistorySource,
  VolGridTimeseriesPoint
} from '@/features/vol-grid/types'
import { buildNodeKey } from '@/features/vol-grid/utils'
import {
  computeTechnicalSignalsFromSeries,
  isNoVolGridDataError,
  interpolateGridValue,
  loadPreferredSnapshot
} from '@/lib/vol-grid/engine'
import { query } from '@/lib/db'
import { resolveVolGridSession } from '@/lib/vol-grid/session'

const OBSERVATIONS_TABLE = 'arbs_live_atmf_grid_observations_v1'
const EOD_HISTORY_TABLE = 'arbs_atmf_grid_eod_history_v1'
const SNAPSHOTS_TABLE = 'arbs_live_atmf_grid_snapshots_v1'

type ObservationRow = {
  package_id: string
  execution_timestamp: string
  platform_identifier: string | null
  observed_bpvol: number | string
  premium: number | string | null
  notional: number | string | null
  trade_label: string | null
  grid_node_key: string | null
  display_node_key: string | null
  expiry_label: string | null
  tenor_label: string | null
  mapping_distance: number | string | null
  staleness_weight: number | string | null
  delta_bpvol: number | string | null
}

type VolumeRow = {
  trade_count_1w: number | string
  avg_notional_1w: number | string | null
  total_notional_1w: number | string | null
  last_trade_ts: string | null
}

type NodeCountRow = {
  display_node_key: string
  trade_count: number | string
}

type HistoricalGridRow = {
  as_of_date: string | Date | null
  grid_data: Record<string, unknown>
}

function parseNumber(value: unknown) {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeObservation(row: ObservationRow): CalibrationObservation {
  return {
    packageId: row.package_id,
    executionTimestamp: new Date(row.execution_timestamp).getTime(),
    platform: row.platform_identifier,
    packageType: 'STRADDLE',
    bpvolYr: parseNumber(row.observed_bpvol) ?? 0,
    premium: parseNumber(row.premium),
    notional: parseNumber(row.notional),
    tradeLabel: row.trade_label ?? '--',
    isCalibrationTrade: true,
    gridNodeKey: row.grid_node_key,
    displayNodeKey: row.display_node_key,
    expiry: row.expiry_label,
    tenor: row.tenor_label,
    mappingDistance: parseNumber(row.mapping_distance),
    stalenessWeight: parseNumber(row.staleness_weight),
    deltaBpvol: parseNumber(row.delta_bpvol)
  }
}

function daysBetween(asOfDate: string, timestamp: number | null) {
  if (!timestamp) return null
  const end = new Date(`${asOfDate}T00:00:00Z`).getTime()
  const start = timestamp
  if (!Number.isFinite(end) || !Number.isFinite(start)) return null
  return Math.max(0, Math.floor((end - start) / (24 * 60 * 60 * 1000)))
}

function computeRarityPercentile(counts: number[], selectedCount: number) {
  if (!counts.length) return null
  const lessOrEqual = counts.filter((value) => value <= selectedCount).length
  const rank = (lessOrEqual - 1) / Math.max(counts.length - 1, 1)
  return (1 - rank) * 100
}

function median(values: number[]) {
  if (!values.length) return null
  const sorted = values.slice().sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return (sorted[middle - 1] + sorted[middle]) / 2
  }
  return sorted[middle]
}

function buildLocalDateKey(timestamp: number) {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(date)
  const year = parts.find((part) => part.type === 'year')?.value
  const month = parts.find((part) => part.type === 'month')?.value
  const day = parts.find((part) => part.type === 'day')?.value
  if (!year || !month || !day) return null
  return `${year}-${month}-${day}`
}

function buildTimeseries(points: Array<{ date: string; nvol: number }>): VolGridTimeseriesPoint[] {
  return points.map((point, index) => ({
    date: point.date,
    timestamp: new Date(`${point.date}T00:00:00Z`).getTime(),
    nvol: point.nvol,
    dailyChange:
      index === 0 ? null : point.nvol - points[index - 1].nvol
  }))
}

function computeTradeHistoryStats(trades: CalibrationObservation[]) {
  const tradeCount = trades.length
  const notionals = trades
    .map((trade) => trade.notional)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .map((value) => Math.abs(value))
  const premiums = trades
    .map((trade) => trade.premium)
    .filter((value): value is number => value !== null && Number.isFinite(value))
    .map((value) => Math.abs(value))
  const bpvols = trades
    .map((trade) => trade.bpvolYr)
    .filter((value): value is number => Number.isFinite(value))
  const timestamps = trades
    .map((trade) => trade.executionTimestamp)
    .filter((value): value is number => Number.isFinite(value))
    .slice()
    .sort((left, right) => left - right)

  let avgGapMs: number | null = null
  if (timestamps.length > 1) {
    let totalGap = 0
    for (let index = 1; index < timestamps.length; index += 1) {
      totalGap += timestamps[index] - timestamps[index - 1]
    }
    avgGapMs = totalGap / (timestamps.length - 1)
  }

  const activeDaysSet = new Set<string>()
  timestamps.forEach((timestamp) => {
    const key = buildLocalDateKey(timestamp)
    if (key) activeDaysSet.add(key)
  })
  const activeDays = activeDaysSet.size || null
  const platformCounts = new Map<string, number>()
  trades.forEach((trade) => {
    const platform = String(trade.platform ?? '--').trim() || '--'
    platformCounts.set(platform, (platformCounts.get(platform) ?? 0) + 1)
  })

  const totalNotional = notionals.length
    ? notionals.reduce((sum, value) => sum + value, 0)
    : null
  const totalPremium = premiums.length
    ? premiums.reduce((sum, value) => sum + value, 0)
    : null

  return {
    tradeCount,
    firstTradeTimestamp: timestamps[0] ?? null,
    lastTradeTimestamp: timestamps[timestamps.length - 1] ?? null,
    totalNotional,
    avgNotional: totalNotional !== null && notionals.length ? totalNotional / notionals.length : null,
    medianNotional: median(notionals),
    totalPremium,
    avgPremium: totalPremium !== null && premiums.length ? totalPremium / premiums.length : null,
    medianPremium: median(premiums),
    avgBpvol: bpvols.length ? bpvols.reduce((sum, value) => sum + value, 0) / bpvols.length : null,
    medianBpvol: median(bpvols),
    tradesPerDay: activeDays ? tradeCount / activeDays : null,
    avgGapMs,
    activeDays,
    platformBreakdown: Array.from(platformCounts.entries())
      .sort((left, right) => right[1] - left[1])
      .map(([platform, count]) => ({ platform, count }))
  }
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ expiry: string; tenor: string }> }
) {
  const resolvedParams = await params
  const expiry = resolvedParams.expiry.toUpperCase()
  const tenor = resolvedParams.tenor.toUpperCase()
  const validExpiry = EXPIRY_POINTS.some((point) => point.label === expiry)
  const validTenor = TENOR_POINTS.some((point) => point.label === tenor)

  if (!validExpiry || !validTenor) {
    return NextResponse.json(
      { error: 'Invalid expiry or tenor' },
      { status: 400 }
    )
  }

  const { searchParams } = new URL(request.url)
  const presetParam = searchParams.get('calibration_preset') as CalibrationPresetKey | null
  const presetKey = (
    presetParam && ['idb_straddles', 'all_idb', 'custy_only', 'custy_and_idb', 'straddles_only'].includes(presetParam)
      ? presetParam
      : 'idb_straddles'
  ) as CalibrationPresetKey
  const preset = resolveSnapshotPreset(presetKey)
  const displayNodeKey = buildNodeKey(expiry, tenor)

  try {
    const session = await resolveVolGridSession(presetKey, searchParams.get('date') ?? undefined)
    const snapshotMeta = await loadPreferredSnapshot(
      presetKey,
      [session.defaultSnapshotKind, ...session.fallbackSnapshotKinds],
      session.effectiveDate
    )
    if (!snapshotMeta) {
      return NextResponse.json(
        { error: 'No live ATMF snapshot available' },
        { status: 404 }
      )
    }

    const [mdpHistoryResult, pcaHistoryResult, tradeHistoryResult, volumeResult, countsResult] = await Promise.all([
      query<HistoricalGridRow>(
        `
          SELECT as_of_date, grid_data
          FROM ${EOD_HISTORY_TABLE}
          WHERE curve_name = $1
            AND surface_type = $2
            AND as_of_date <= $3
          ORDER BY as_of_date DESC
          LIMIT 520
        `,
        [snapshotMeta.curve_name, snapshotMeta.surface_type, session.effectiveDate]
      ),
      query<HistoricalGridRow>(
        `
          WITH latest AS (
            SELECT DISTINCT ON (as_of_date)
              as_of_date,
              grid_data
            FROM ${SNAPSHOTS_TABLE}
            WHERE calibration_preset = $1
              AND curve_name = $2
              AND surface_type = $3
              AND snapshot_kind = 'close_pca'
              AND as_of_date <= $4
            ORDER BY as_of_date DESC, snapshot_ts DESC
            LIMIT 520
          )
          SELECT as_of_date, grid_data
          FROM latest
          ORDER BY as_of_date ASC
        `,
        [preset, snapshotMeta.curve_name, snapshotMeta.surface_type, session.effectiveDate]
      ),
      query<ObservationRow>(
        `
          SELECT
            package_id,
            execution_timestamp,
            platform_identifier,
            observed_bpvol,
            premium,
            notional,
            trade_label,
            grid_node_key,
            display_node_key,
            expiry_label,
            tenor_label,
            mapping_distance,
            staleness_weight,
            delta_bpvol
          FROM ${OBSERVATIONS_TABLE}
          WHERE calibration_preset = $1
            AND display_node_key = $2
          ORDER BY execution_timestamp DESC
        `,
        [preset, displayNodeKey]
      ),
      query<VolumeRow>(
        `
          SELECT
            count(*) AS trade_count_1w,
            avg(notional) AS avg_notional_1w,
            sum(notional) AS total_notional_1w,
            max(execution_timestamp) AS last_trade_ts
          FROM ${OBSERVATIONS_TABLE}
          WHERE calibration_preset = $1
            AND display_node_key = $2
            AND execution_timestamp >= $3::date - interval '7 days'
        `,
        [preset, displayNodeKey, session.effectiveDate]
      ),
      query<NodeCountRow>(
        `
          SELECT display_node_key, count(*) AS trade_count
          FROM ${OBSERVATIONS_TABLE}
          WHERE calibration_preset = $1
            AND execution_timestamp >= $2::date - interval '7 days'
          GROUP BY display_node_key
        `,
        [preset, session.effectiveDate]
      )
    ])

    const mdpHistorySeries = (mdpHistoryResult.rows || [])
      .slice()
      .reverse()
      .map((row) => {
        const date =
          row.as_of_date instanceof Date
            ? row.as_of_date.toISOString().slice(0, 10)
            : String(row.as_of_date ?? '').slice(0, 10)
        const nvol = interpolateGridValue(row.grid_data, expiry, tenor)
        return nvol === null || !date ? null : { date, nvol }
      })
      .filter((point): point is { date: string; nvol: number } => point !== null)

    const pcaHistorySeries = (pcaHistoryResult.rows || [])
      .map((row) => {
        const date =
          row.as_of_date instanceof Date
            ? row.as_of_date.toISOString().slice(0, 10)
            : String(row.as_of_date ?? '').slice(0, 10)
        const nvol = interpolateGridValue(row.grid_data, expiry, tenor)
        return nvol === null || !date ? null : { date, nvol }
      })
      .filter((point): point is { date: string; nvol: number } => point !== null)

    const timeseriesBySource: Record<VolGridHistorySource, VolGridTimeseriesPoint[]> = {
      mdp: buildTimeseries(mdpHistorySeries),
      pca: buildTimeseries(pcaHistorySeries)
    }
    const availableHistorySources = (Object.entries(timeseriesBySource) as Array<
      [VolGridHistorySource, VolGridTimeseriesPoint[]]
    >)
      .filter(([, points]) => points.length > 0)
      .map(([source]) => source)
    const defaultHistorySource =
      snapshotMeta.snapshot_kind === 'close_pca' && timeseriesBySource.pca.length > 0
        ? 'pca'
        : 'mdp'

    const tradeHistory = (tradeHistoryResult.rows || []).map(normalizeObservation)
    const latestTrade = tradeHistory[0] ?? null
    const volumeRow = volumeResult.rows[0]
    const selectedCount = Math.round(parseNumber(volumeRow?.trade_count_1w) ?? 0)
    const groupedCounts = (countsResult.rows || [])
      .map((row) => Math.round(parseNumber(row.trade_count) ?? 0))
      .filter((count) => Number.isFinite(count))
    const tradeHistoryStats = computeTradeHistoryStats(tradeHistory)

    const technicalSeries = (
      (timeseriesBySource[defaultHistorySource] ?? timeseriesBySource.mdp).map((point) => ({
        date: point.date,
        nvol: point.nvol
      }))
    )

    const response: CellDetailResponse = {
      expiry,
      tenor,
      timeseries: timeseriesBySource[defaultHistorySource],
      timeseriesBySource,
      defaultHistorySource,
      availableHistorySources,
      tradeHistory,
      volumeStats: {
        tradeCount1w: selectedCount,
        avgNotional1w: parseNumber(volumeRow?.avg_notional_1w),
        totalNotional1w: parseNumber(volumeRow?.total_notional_1w),
        lastTradeDate: latestTrade
          ? new Date(latestTrade.executionTimestamp).toISOString().slice(0, 10)
          : null,
        lastTradeTimestamp: latestTrade?.executionTimestamp ?? null,
        daysSinceLastTrade: daysBetween(
          session.effectiveDate,
          latestTrade?.executionTimestamp ?? null
        ),
        rarityPercentile: computeRarityPercentile(groupedCounts, selectedCount)
      },
      technicalSignals: computeTechnicalSignalsFromSeries(technicalSeries),
      tradeHistoryStats
    }

    return NextResponse.json(response)
  } catch (error: any) {
    if (isNoVolGridDataError(error)) {
      return NextResponse.json(
        { error: error.message },
        { status: 404 }
      )
    }
    console.error('vol-grid/cell-detail GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch cell detail' },
      { status: 500 }
    )
  }
}
