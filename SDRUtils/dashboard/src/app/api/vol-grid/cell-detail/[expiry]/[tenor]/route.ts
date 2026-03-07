import { NextResponse } from 'next/server'
import {
  EXPIRY_POINTS,
  TENOR_POINTS,
  resolveSnapshotPreset
} from '@/features/vol-grid/constants'
import type {
  CalibrationObservation,
  CalibrationPresetKey,
  CellDetailResponse
} from '@/features/vol-grid/types'
import { buildNodeKey } from '@/features/vol-grid/utils'
import {
  computeTechnicalSignalsFromSeries,
  isNoVolGridDataError,
  interpolateGridValue,
  loadPreferredSnapshot,
  loadHistoricalRowsForAnalytics
} from '@/lib/vol-grid/engine'
import { query } from '@/lib/db'
import { resolveVolGridSession } from '@/lib/vol-grid/session'

const OBSERVATIONS_TABLE = 'arbs_live_atmf_grid_observations_v1'

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

function daysBetween(asOfDate: string, timestamp: string | null) {
  if (!timestamp) return null
  const end = new Date(`${asOfDate}T00:00:00Z`).getTime()
  const start = new Date(timestamp).getTime()
  if (!Number.isFinite(end) || !Number.isFinite(start)) return null
  return Math.max(0, Math.floor((end - start) / (24 * 60 * 60 * 1000)))
}

function computeRarityPercentile(counts: number[], selectedCount: number) {
  if (!counts.length) return null
  const lessOrEqual = counts.filter((value) => value <= selectedCount).length
  const rank = (lessOrEqual - 1) / Math.max(counts.length - 1, 1)
  return (1 - rank) * 100
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

    const [historyRows, recentTradesResult, volumeResult, countsResult] = await Promise.all([
      loadHistoricalRowsForAnalytics(snapshotMeta, {
        limit: 90,
        includeClosingGrid: session.isClosingView || session.effectiveDate !== snapshotMeta.as_of_date
      }),
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
            AND execution_timestamp >= $3::date - interval '30 days'
          ORDER BY execution_timestamp DESC
          LIMIT 20
        `,
        [preset, displayNodeKey, session.effectiveDate]
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

    const timeseries = historyRows
      .map((row) => {
        const nvol = interpolateGridValue(row.grid_data, expiry, tenor)
        return nvol === null ? null : { date: row.as_of_date, nvol }
      })
      .filter((point): point is { date: string; nvol: number } => point !== null)

    const recentTrades = (recentTradesResult.rows || []).map(normalizeObservation)
    const volumeRow = volumeResult.rows[0]
    const selectedCount = Math.round(parseNumber(volumeRow?.trade_count_1w) ?? 0)
    const groupedCounts = (countsResult.rows || [])
      .map((row) => Math.round(parseNumber(row.trade_count) ?? 0))
      .filter((count) => Number.isFinite(count))

    const response: CellDetailResponse = {
      expiry,
      tenor,
      timeseries,
      recentTrades,
      volumeStats: {
        tradeCount1w: selectedCount,
        avgNotional1w: parseNumber(volumeRow?.avg_notional_1w),
        totalNotional1w: parseNumber(volumeRow?.total_notional_1w),
        lastTradeDate: volumeRow?.last_trade_ts
          ? new Date(volumeRow.last_trade_ts).toISOString().slice(0, 10)
          : null,
        daysSinceLastTrade: daysBetween(session.effectiveDate, volumeRow?.last_trade_ts ?? null),
        rarityPercentile: computeRarityPercentile(groupedCounts, selectedCount)
      },
      technicalSignals: computeTechnicalSignalsFromSeries(timeseries)
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
