import { resolveSnapshotPreset } from '@/features/vol-grid/constants'
import type {
  CalibrationObservation,
  CalibrationPresetKey,
  SnapshotKind
} from '@/features/vol-grid/types'
import { query } from '@/lib/db'
import { isNoVolGridDataError, loadPreferredSnapshot } from './engine'

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

function parseNumber(value: unknown) {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export type CalibrationTradesResult = {
  calibrationTrades: CalibrationObservation[]
  filteredOutCount: number
}

export async function fetchCalibrationTrades(params: {
  asOfDate: string
  preset: CalibrationPresetKey
  snapshotKinds?: SnapshotKind[]
}): Promise<CalibrationTradesResult> {
  const snapshotPreset = resolveSnapshotPreset(params.preset)
  const snapshotKinds: SnapshotKind[] = params.snapshotKinds ?? [
    'intraday',
    'close_pca',
    'close_mdp'
  ]
  const observationResult = await query<ObservationRow>(
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
        AND as_of_date = $2
      ORDER BY execution_timestamp DESC
    `,
    [snapshotPreset, params.asOfDate]
  )

  let filteredOutCount = 0
  try {
    const snapshot = await loadPreferredSnapshot(
      params.preset,
      snapshotKinds,
      params.asOfDate
    )
    filteredOutCount = Math.round(parseNumber(snapshot.filtered_out_count) ?? 0)
  } catch (error) {
    if (!isNoVolGridDataError(error)) {
      throw error
    }
  }

  const calibrationTrades: CalibrationObservation[] = (observationResult.rows || []).map(
    (row) => ({
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
    })
  )

  return {
    calibrationTrades,
    filteredOutCount
  }
}
