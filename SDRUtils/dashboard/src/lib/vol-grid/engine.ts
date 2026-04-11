import type {
  CalibrationObservation,
  CalibrationPresetKey,
  CalibrationFilterConfig,
  SnapshotKind,
  StalenessCategory,
  VolGridCell,
  VolGridSurfaceResponse,
  VolGridTechnicalSignals,
  VolSource
} from '@/features/vol-grid/types'
import {
  CORE_EXPIRY_POINTS,
  CORE_TENOR_POINTS,
  EXPIRY_POINTS,
  GRID_DEFINITION,
  TENOR_POINTS,
  VOL_GRID_DEFAULT_CURVE_NAME,
  VOL_GRID_DEFAULT_SURFACE_TYPE,
  resolveSnapshotPreset
} from '@/features/vol-grid/constants'
import {
  buildNodeKey,
  clamp,
  normalizeDateKey,
  normalizeGridLabel,
  parseTenorLabelToYears,
  toEasternDateKey
} from '@/features/vol-grid/utils'
import { query } from '@/lib/db'
import { resolveVolGridSession } from './session'

const SNAPSHOTS_TABLE = 'arbs_live_atmf_grid_snapshots_v1'
const EOD_HISTORY_TABLE = 'arbs_atmf_grid_eod_history_v1'
const OBSERVATIONS_TABLE = 'arbs_live_atmf_grid_observations_v1'

const STALENESS_THRESHOLDS = {
  live: 15,
  recent: 60,
  stale: 240,
  veryStale: 480
}

const DEFAULT_QUADRANT_CONFIG = {
  expiryBoundaryYears: 1.5,
  tenorBoundaryYears: 7.5,
  boundaryToleranceYears: 0.5
}

export type SnapshotRow = {
  as_of_date: string
  eod_as_of_date: string
  curve_name: string
  source: string
  snapshot_kind: SnapshotKind
  surface_type: string
  snapshot_ts: string | null
  last_observation_ts: string | null
  observation_count: number | string
  filtered_out_count: number | string
  grid_data: Record<string, unknown>
  eod_grid_data: Record<string, unknown>
  node_metadata: Record<string, any>
}

type HistoricalGridRow = {
  as_of_date: string
  grid_data: Record<string, unknown>
}

type EodHistorySnapshotRow = {
  as_of_date: string | Date | null
  curve_name: string
  surface_type: string
  source: string
  grid_data: Record<string, unknown>
}

type LatestObservationRow = {
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

type GridPoint = { label: string; years: number }
type InterpolationCorner = { key: string; weight: number }

export class NoVolGridDataError extends Error {
  constructor(
    message = 'No stored live ATMF snapshots or EOD history are available yet. Backfill EOD history and run the live-grid ingest first.'
  ) {
    super(message)
    this.name = 'NoVolGridDataError'
  }
}

export function isNoVolGridDataError(error: unknown): error is NoVolGridDataError {
  return error instanceof NoVolGridDataError
}

function parseNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function parseTimestamp(value: unknown): number | null {
  if (!value) return null
  const parsed =
    value instanceof Date
      ? value.getTime()
      : new Date(String(value)).getTime()
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeSnapshotRow(row: {
  as_of_date: string | Date | null
  eod_as_of_date: string | Date | null
  curve_name: string
  source: string
  snapshot_kind: SnapshotKind
  surface_type: string
  snapshot_ts: string | Date | null
  last_observation_ts: string | Date | null
  observation_count: number | string
  filtered_out_count: number | string
  grid_data: Record<string, unknown>
  eod_grid_data: Record<string, unknown>
  node_metadata: Record<string, any>
} | null | undefined): SnapshotRow | null {
  if (!row) return null
  const asOfDate = normalizeDateKey(row.as_of_date)
  const eodAsOfDate = normalizeDateKey(row.eod_as_of_date) ?? asOfDate
  if (!asOfDate || !eodAsOfDate) return null

  return {
    as_of_date: asOfDate,
    eod_as_of_date: eodAsOfDate,
    curve_name: row.curve_name,
    source: row.source,
    snapshot_kind: row.snapshot_kind,
    surface_type: row.surface_type,
    snapshot_ts:
      row.snapshot_ts instanceof Date
        ? row.snapshot_ts.toISOString()
        : row.snapshot_ts ?? null,
    last_observation_ts:
      row.last_observation_ts instanceof Date
        ? row.last_observation_ts.toISOString()
        : row.last_observation_ts ?? null,
    observation_count: row.observation_count,
    filtered_out_count: row.filtered_out_count,
    grid_data: row.grid_data,
    eod_grid_data: row.eod_grid_data,
    node_metadata: row.node_metadata
  }
}

function normalizeHistoricalRow(row: {
  as_of_date: string | Date | null
  grid_data: Record<string, unknown>
} | null | undefined): HistoricalGridRow | null {
  if (!row) return null
  const asOfDate = normalizeDateKey(row.as_of_date)
  if (!asOfDate) return null
  return {
    as_of_date: asOfDate,
    grid_data: row.grid_data
  }
}

function normalizeEodHistoryRow(row: EodHistorySnapshotRow | null): EodHistorySnapshotRow | null {
  if (!row) return null
  const asOfDate = normalizeDateKey(row.as_of_date)
  if (!asOfDate) return null
  return {
    ...row,
    as_of_date: asOfDate
  }
}

function normalizeSource(value: unknown): VolSource {
  if (value === 'direct_observation') return 'direct_observation'
  if (value === 'interpolated') return 'interpolated'
  if (value === 'propagated') return 'propagated'
  if (value === 'mdp_close') return 'mdp_close'
  if (value === 'prior') return 'prior'
  return 'no_data'
}

function normalizeCalibrationObservation(value: any): CalibrationObservation | null {
  if (!value || typeof value !== 'object') return null
  const executionTimestamp = parseNumber(value.executionTimestamp)
  const bpvolYr = parseNumber(value.bpvolYr)
  if (executionTimestamp === null || bpvolYr === null) return null
  return {
    packageId: String(value.packageId ?? ''),
    executionTimestamp,
    platform: value.platform ?? null,
    packageType: value.packageType ?? null,
    bpvolYr,
    premium: parseNumber(value.premium),
    notional: parseNumber(value.notional),
    tradeLabel: String(value.tradeLabel ?? '--'),
    isCalibrationTrade: Boolean(value.isCalibrationTrade ?? true),
    gridNodeKey: value.gridNodeKey ?? null,
    displayNodeKey: value.displayNodeKey ?? null,
    expiry: value.expiry ?? null,
    tenor: value.tenor ?? null,
    mappingDistance: parseNumber(value.mappingDistance),
    stalenessWeight: parseNumber(value.stalenessWeight),
    deltaBpvol: parseNumber(value.deltaBpvol)
  }
}

function normalizeObservationRow(
  row: LatestObservationRow | null | undefined
): CalibrationObservation | null {
  if (!row) return null
  const executionTimestamp = parseTimestamp(row.execution_timestamp)
  const bpvolYr = parseNumber(row.observed_bpvol)
  if (executionTimestamp === null || bpvolYr === null) return null
  return {
    packageId: row.package_id,
    executionTimestamp,
    platform: row.platform_identifier,
    packageType: 'STRADDLE',
    bpvolYr,
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

function findLogBounds(target: number, points: readonly GridPoint[]) {
  if (target === points[0].years) {
    return { lower: points[0], upper: points[0], weightLower: 1, weightUpper: 0 }
  }
  if (target < points[0].years && points.length > 1) {
    const lower = points[0]
    const upper = points[1]
    const logLower = Math.log(lower.years)
    const logUpper = Math.log(upper.years)
    const logTarget = Math.log(target)
    const span = logUpper - logLower
    const ratio = span > 0 ? (logTarget - logLower) / span : 0
    return {
      lower,
      upper,
      weightLower: 1 - ratio,
      weightUpper: ratio
    }
  }
  const last = points[points.length - 1]
  if (target === last.years) {
    return { lower: last, upper: last, weightLower: 1, weightUpper: 0 }
  }
  if (target > last.years && points.length > 1) {
    const lower = points[points.length - 2]
    const upper = last
    const logLower = Math.log(lower.years)
    const logUpper = Math.log(upper.years)
    const logTarget = Math.log(target)
    const span = logUpper - logLower
    const ratio = span > 0 ? (logTarget - logLower) / span : 0
    return {
      lower,
      upper,
      weightLower: 1 - ratio,
      weightUpper: ratio
    }
  }

  for (let index = 0; index < points.length - 1; index += 1) {
    const lower = points[index]
    const upper = points[index + 1]
    if (target >= lower.years && target <= upper.years) {
      const logLower = Math.log(lower.years)
      const logUpper = Math.log(upper.years)
      const logTarget = Math.log(target)
      const span = logUpper - logLower
      const ratio = span > 0 ? (logTarget - logLower) / span : 0
      return {
        lower,
        upper,
        weightLower: 1 - ratio,
        weightUpper: ratio
      }
    }
  }

  return { lower: last, upper: last, weightLower: 1, weightUpper: 0 }
}

export function getInterpolationCorners(
  expiryLabel: string,
  tenorLabel: string
): InterpolationCorner[] {
  const expiryYears = parseTenorLabelToYears(expiryLabel)
  const tenorYears = parseTenorLabelToYears(tenorLabel)
  if (expiryYears === null || tenorYears === null) return []

  const expiryBounds = findLogBounds(expiryYears, CORE_EXPIRY_POINTS)
  const tenorBounds = findLogBounds(tenorYears, CORE_TENOR_POINTS)
  const rawCorners = [
    {
      key: buildNodeKey(expiryBounds.lower.label, tenorBounds.lower.label),
      weight: expiryBounds.weightLower * tenorBounds.weightLower
    },
    {
      key: buildNodeKey(expiryBounds.lower.label, tenorBounds.upper.label),
      weight: expiryBounds.weightLower * tenorBounds.weightUpper
    },
    {
      key: buildNodeKey(expiryBounds.upper.label, tenorBounds.lower.label),
      weight: expiryBounds.weightUpper * tenorBounds.weightLower
    },
    {
      key: buildNodeKey(expiryBounds.upper.label, tenorBounds.upper.label),
      weight: expiryBounds.weightUpper * tenorBounds.weightUpper
    }
  ]

  const deduped = new Map<string, number>()
  for (const corner of rawCorners) {
    if (Math.abs(corner.weight) <= 1e-12) continue
    deduped.set(corner.key, (deduped.get(corner.key) ?? 0) + corner.weight)
  }

  return Array.from(deduped.entries()).map(([key, weight]) => ({ key, weight }))
}

export function interpolateGridValue(
  gridData: Record<string, unknown> | null | undefined,
  expiryLabel: string,
  tenorLabel: string
): number | null {
  if (!gridData) return null
  const directKey = buildNodeKey(expiryLabel, tenorLabel)
  const directValue = parseNumber(gridData[directKey])
  if (directValue !== null) return directValue

  const corners = getInterpolationCorners(expiryLabel, tenorLabel)
  if (!corners.length) return null

  let weightedValue = 0
  let totalWeight = 0
  for (const corner of corners) {
    const value = parseNumber(gridData[corner.key])
    if (value === null) continue
    weightedValue += value * corner.weight
    totalWeight += corner.weight
  }

  return totalWeight > 0 ? weightedValue / totalWeight : null
}

function interpolateMetadataNumber(
  metadata: Record<string, any> | null | undefined,
  expiryLabel: string,
  tenorLabel: string,
  field: string
): number | null {
  if (!metadata) return null
  const directKey = buildNodeKey(expiryLabel, tenorLabel)
  const directValue = parseNumber(metadata[directKey]?.[field])
  if (directValue !== null) return directValue

  const corners = getInterpolationCorners(expiryLabel, tenorLabel)
  let weightedValue = 0
  let totalWeight = 0
  for (const corner of corners) {
    const value = parseNumber(metadata[corner.key]?.[field])
    if (value === null) continue
    weightedValue += value * corner.weight
    totalWeight += corner.weight
  }

  return totalWeight > 0 ? weightedValue / totalWeight : null
}

function pickRepresentativeObservation(
  metadata: Record<string, any> | null | undefined,
  expiryLabel: string,
  tenorLabel: string
): CalibrationObservation | null {
  if (!metadata) return null
  const directKey = buildNodeKey(expiryLabel, tenorLabel)
  const directObservation = normalizeCalibrationObservation(
    metadata[directKey]?.last_observation
  )
  if (directObservation) return directObservation

  const corners = getInterpolationCorners(expiryLabel, tenorLabel)
  let bestObservation: CalibrationObservation | null = null
  let bestWeight = -1
  let bestTimestamp = -1

  for (const corner of corners) {
    const candidate = normalizeCalibrationObservation(
      metadata[corner.key]?.last_observation
    )
    if (!candidate) continue
    const candidateTime = candidate.executionTimestamp
    if (
      corner.weight > bestWeight ||
      (corner.weight === bestWeight && candidateTime > bestTimestamp)
    ) {
      bestObservation = candidate
      bestWeight = corner.weight
      bestTimestamp = candidateTime
    }
  }

  return bestObservation
}

function classifyQuadrant(expiryYears: number, tenorYears: number) {
  const expiryDelta = expiryYears - DEFAULT_QUADRANT_CONFIG.expiryBoundaryYears
  const tenorDelta = tenorYears - DEFAULT_QUADRANT_CONFIG.tenorBoundaryYears
  const isExpiryBoundary =
    Math.abs(expiryDelta) <= DEFAULT_QUADRANT_CONFIG.boundaryToleranceYears
  const isTenorBoundary =
    Math.abs(tenorDelta) <= DEFAULT_QUADRANT_CONFIG.boundaryToleranceYears
  const expirySide = expiryDelta < 0 ? 'SHORT' : 'LONG'
  const tenorSide = tenorDelta < 0 ? 'SHORT' : 'LONG'

  if (isExpiryBoundary || isTenorBoundary) return 'BOUNDARY'
  if (expirySide === 'SHORT' && tenorSide === 'SHORT') return 'ULC'
  if (expirySide === 'SHORT' && tenorSide === 'LONG') return 'URC'
  if (expirySide === 'LONG' && tenorSide === 'SHORT') return 'LLC'
  return 'LRC'
}

function computeStalenessCategory(
  source: VolSource,
  minutesSince: number | null
): StalenessCategory {
  if (source === 'no_data') return 'no_data'
  if (source === 'mdp_close') return 'recent'
  if (source === 'prior') return 'very_stale'
  if (source === 'interpolated') return 'stale'
  if (minutesSince === null) return source === 'propagated' ? 'stale' : 'no_data'
  if (minutesSince < STALENESS_THRESHOLDS.live) return 'live'
  if (minutesSince < STALENESS_THRESHOLDS.recent) return 'recent'
  if (minutesSince < STALENESS_THRESHOLDS.stale) return 'stale'
  if (minutesSince < STALENESS_THRESHOLDS.veryStale) return 'very_stale'
  return 'no_data'
}

function average(values: number[]) {
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function estimatePremiumChangeFromVolRatio(params: {
  premiumBps: number | null
  currentVol: number | null
  referenceVol: number | null
}) {
  const { premiumBps, currentVol, referenceVol } = params
  if (
    premiumBps === null ||
    currentVol === null ||
    referenceVol === null ||
    !Number.isFinite(premiumBps) ||
    !Number.isFinite(currentVol) ||
    !Number.isFinite(referenceVol) ||
    currentVol <= 0
  ) {
    return null
  }
  const estimatedReferencePremium = premiumBps * (referenceVol / currentVol)
  return premiumBps - estimatedReferencePremium
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return null
  const mean = average(values)
  if (mean === null) return null
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
    (values.length - 1)
  return Math.sqrt(variance)
}

function computeLag1Autocorrelation(values: number[]) {
  if (values.length < 3) return null
  const x = values.slice(1)
  const y = values.slice(0, -1)
  const meanX = average(x)
  const meanY = average(y)
  if (meanX === null || meanY === null) return null
  let numerator = 0
  let xVar = 0
  let yVar = 0
  for (let index = 0; index < x.length; index += 1) {
    const dx = x[index] - meanX
    const dy = y[index] - meanY
    numerator += dx * dy
    xVar += dx * dx
    yVar += dy * dy
  }
  if (xVar <= 0 || yVar <= 0) return null
  return numerator / Math.sqrt(xVar * yVar)
}

export function computeTechnicalSignalsFromSeries(
  timeseries: Array<{ date: string; nvol: number }>
): VolGridTechnicalSignals {
  const values = timeseries
    .map((point) => point.nvol)
    .filter((value): value is number => Number.isFinite(value))
  const autocorrelation1d = computeLag1Autocorrelation(values)
  if (values.length < 20) {
    return {
      autocorrelation1d,
      maShortVsLong: null,
      regimeLabel: null
    }
  }

  const ma5 = average(values.slice(-5))
  const ma20 = average(values.slice(-20))
  const sigma20 = standardDeviation(values.slice(-20))
  const latest = values[values.length - 1]

  let maShortVsLong: string | null = null
  if (ma5 !== null && ma20 !== null) {
    const diff = ma5 - ma20
    maShortVsLong =
      Math.abs(diff) < 0.05 ? 'flat' : diff > 0 ? 'above' : 'below'
  }

  let regimeLabel: string | null = 'range-bound'
  if (
    sigma20 !== null &&
    sigma20 > 0 &&
    ma20 !== null &&
    Math.abs(latest - ma20) / sigma20 >= 1.5
  ) {
    regimeLabel = 'breakout'
  } else if (
    autocorrelation1d !== null &&
    Math.abs(autocorrelation1d) >= 0.35 &&
    ma5 !== null &&
    ma20 !== null &&
    Math.abs(ma5 - ma20) >= Math.max(0.15, (sigma20 ?? 0) * 0.25)
  ) {
    regimeLabel = 'trending'
  }

  return {
    autocorrelation1d,
    maShortVsLong,
    regimeLabel
  }
}

function parseTimestampForSort(value: string | null | undefined) {
  if (!value) return 0
  const parsed = new Date(value).getTime()
  return Number.isFinite(parsed) ? parsed : 0
}

function sortSnapshotsByPreference(
  rows: SnapshotRow[],
  snapshotKinds: SnapshotKind[]
) {
  const priority = new Map(snapshotKinds.map((kind, index) => [kind, index]))
  return rows.slice().sort((left, right) => {
    const leftPriority = priority.get(left.snapshot_kind) ?? 999
    const rightPriority = priority.get(right.snapshot_kind) ?? 999
    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority
    }
    return parseTimestampForSort(right.snapshot_ts) - parseTimestampForSort(left.snapshot_ts)
  })
}

async function loadLatestEodHistoryRow(
  onOrBefore?: string
): Promise<EodHistorySnapshotRow | null> {
  const params: string[] = [
    VOL_GRID_DEFAULT_CURVE_NAME,
    VOL_GRID_DEFAULT_SURFACE_TYPE
  ]
  let dateClause = ''
  if (onOrBefore) {
    params.push(onOrBefore)
    dateClause = `AND as_of_date <= $${params.length}`
  }

  const result = await query<EodHistorySnapshotRow>(
    `
      SELECT
        as_of_date,
        curve_name,
        surface_type,
        source,
        grid_data
      FROM ${EOD_HISTORY_TABLE}
      WHERE curve_name = $1
        AND surface_type = $2
        ${dateClause}
      ORDER BY as_of_date DESC
      LIMIT 1
    `,
    params
  )
  return normalizeEodHistoryRow(result.rows[0] ?? null)
}

async function loadLatestHistoricalObservations(
  preset: CalibrationPresetKey,
  onOrBefore: string
): Promise<Map<string, CalibrationObservation>> {
  const displayNodeKeys = GRID_DEFINITION.expiries.flatMap((expiry) =>
    GRID_DEFINITION.tenors.map((tenor) => buildNodeKey(expiry, tenor))
  )
  const result = await query<LatestObservationRow>(
    `
      SELECT DISTINCT ON (display_node_key)
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
        AND display_node_key = ANY($2::text[])
        AND as_of_date <= $3
      ORDER BY display_node_key, execution_timestamp DESC
    `,
    [resolveSnapshotPreset(preset), displayNodeKeys, onOrBefore]
  )
  const byNode = new Map<string, CalibrationObservation>()
  for (const row of result.rows || []) {
    if (!row.display_node_key) continue
    const observation = normalizeObservationRow(row)
    if (!observation) continue
    byNode.set(row.display_node_key, observation)
  }
  return byNode
}

function buildSyntheticSnapshotFromHistory(row: EodHistorySnapshotRow): SnapshotRow {
  const asOfDate = normalizeDateKey(row.as_of_date)
  if (!asOfDate) {
    throw new NoVolGridDataError('Stored EOD history contains an invalid as_of_date.')
  }
  return {
    as_of_date: asOfDate,
    eod_as_of_date: asOfDate,
    curve_name: row.curve_name,
    source: row.source === 'GSQUANT' ? 'GSQUANT_EOD_HISTORY' : row.source,
    snapshot_kind: 'close_mdp',
    surface_type: row.surface_type,
    snapshot_ts: null,
    last_observation_ts: null,
    observation_count: 0,
    filtered_out_count: 0,
    grid_data: row.grid_data ?? {},
    eod_grid_data: row.grid_data ?? {},
    node_metadata: {}
  }
}

export async function loadPreferredSnapshot(
  preset: CalibrationPresetKey,
  snapshotKinds: SnapshotKind[],
  asOfDate?: string
): Promise<SnapshotRow> {
  const latestDateParams: Array<string | string[]> = [
    resolveSnapshotPreset(preset),
    snapshotKinds
  ]
  let latestDateClause = ''
  if (asOfDate) {
    latestDateParams.push(asOfDate)
    latestDateClause = `AND as_of_date <= $${latestDateParams.length}`
  }

  const latestDateResult = await query<{ as_of_date: string | Date | null }>(
    `
      SELECT as_of_date
      FROM ${SNAPSHOTS_TABLE}
      WHERE calibration_preset = $1
        AND snapshot_kind = ANY($2::text[])
        ${latestDateClause}
      ORDER BY as_of_date DESC
      LIMIT 1
    `,
    latestDateParams
  )
  const latestDate = normalizeDateKey(latestDateResult.rows[0]?.as_of_date)
  if (!latestDate) {
    const historyRow = await loadLatestEodHistoryRow(asOfDate)
    if (historyRow) {
      return buildSyntheticSnapshotFromHistory(historyRow)
    }
    throw new NoVolGridDataError(
      `No stored live ATMF snapshots or EOD history found for preset=${preset}. Backfill EOD history and run the live-grid ingest first.`
    )
  }

  const rowsResult = await query<{
    as_of_date: string | Date | null
    eod_as_of_date: string | Date | null
    curve_name: string
    source: string
    snapshot_kind: SnapshotKind
    surface_type: string
    snapshot_ts: string | Date | null
    last_observation_ts: string | Date | null
    observation_count: number | string
    filtered_out_count: number | string
    grid_data: Record<string, unknown>
    eod_grid_data: Record<string, unknown>
    node_metadata: Record<string, any>
  }>(
    `
      SELECT
        as_of_date,
        eod_as_of_date,
        curve_name,
        source,
        snapshot_kind,
        surface_type,
        snapshot_ts,
        last_observation_ts,
        observation_count,
        filtered_out_count,
        grid_data,
        eod_grid_data,
        node_metadata
      FROM ${SNAPSHOTS_TABLE}
      WHERE calibration_preset = $1
        AND as_of_date = $2
        AND snapshot_kind = ANY($3::text[])
      ORDER BY snapshot_ts DESC
    `,
    [resolveSnapshotPreset(preset), latestDate, snapshotKinds]
  )
  const normalizedRows = (rowsResult.rows || [])
    .map((row) => normalizeSnapshotRow(row))
    .filter((row): row is SnapshotRow => row !== null)
  const row = sortSnapshotsByPreference(normalizedRows, snapshotKinds)[0]
  if (!row) {
    const historyRow = await loadLatestEodHistoryRow(latestDate)
    if (historyRow) {
      return buildSyntheticSnapshotFromHistory(historyRow)
    }
    throw new NoVolGridDataError(
      `No stored live ATMF snapshots or EOD history found for preset=${preset} on ${latestDate}. Backfill EOD history and run the live-grid ingest first.`
    )
  }
  return row
}

export async function loadExactSnapshotByKind(
  preset: CalibrationPresetKey,
  snapshotKind: SnapshotKind,
  asOfDate: string
): Promise<SnapshotRow | null> {
  const result = await query<{
    as_of_date: string | Date | null
    eod_as_of_date: string | Date | null
    curve_name: string
    source: string
    snapshot_kind: SnapshotKind
    surface_type: string
    snapshot_ts: string | Date | null
    last_observation_ts: string | Date | null
    observation_count: number | string
    filtered_out_count: number | string
    grid_data: Record<string, unknown>
    eod_grid_data: Record<string, unknown>
    node_metadata: Record<string, any>
  }>(
    `
      SELECT
        as_of_date,
        eod_as_of_date,
        curve_name,
        source,
        snapshot_kind,
        surface_type,
        snapshot_ts,
        last_observation_ts,
        observation_count,
        filtered_out_count,
        grid_data,
        eod_grid_data,
        node_metadata
      FROM ${SNAPSHOTS_TABLE}
      WHERE calibration_preset = $1
        AND as_of_date = $2
        AND snapshot_kind = $3
      ORDER BY snapshot_ts DESC
      LIMIT 1
    `,
    [resolveSnapshotPreset(preset), asOfDate, snapshotKind]
  )
  return normalizeSnapshotRow(result.rows[0] ?? null)
}

async function loadHistoricalRows(
  curveName: string,
  surfaceType: string,
  endDate: string,
  limit = 30
): Promise<HistoricalGridRow[]> {
  const result = await query<{ as_of_date: string | Date | null; grid_data: Record<string, unknown> }>(
    `
      SELECT as_of_date, grid_data
      FROM ${EOD_HISTORY_TABLE}
      WHERE curve_name = $1
        AND surface_type = $2
        AND as_of_date <= $3
      ORDER BY as_of_date DESC
      LIMIT $4
    `,
    [curveName, surfaceType, endDate, limit]
  )

  return (result.rows || [])
    .map((row) => normalizeHistoricalRow(row))
    .filter((row): row is HistoricalGridRow => row !== null)
    .slice()
    .reverse()
}

export async function loadHistoricalRowsForAnalytics(
  snapshot: Pick<
    SnapshotRow,
    'curve_name' | 'surface_type' | 'eod_as_of_date' | 'as_of_date' | 'grid_data'
  >,
  options?: {
    limit?: number
    includeClosingGrid?: boolean
  }
): Promise<HistoricalGridRow[]> {
  const limit = options?.limit ?? 30
  const includeClosingGrid = options?.includeClosingGrid ?? false
  const baseRows = await loadHistoricalRows(
    snapshot.curve_name,
    snapshot.surface_type,
    snapshot.eod_as_of_date,
    includeClosingGrid ? Math.max(limit - 1, 1) : limit
  )

  if (!includeClosingGrid) {
    return baseRows
  }

  const rows = [...baseRows]
  if (rows.length && rows[rows.length - 1]?.as_of_date === snapshot.as_of_date) {
    rows[rows.length - 1] = {
      as_of_date: snapshot.as_of_date,
      grid_data: snapshot.grid_data
    }
    return rows.slice(-limit)
  }
  rows.push({
    as_of_date: snapshot.as_of_date,
    grid_data: snapshot.grid_data
  })
  return rows.slice(-limit)
}

function buildRegimeMap(rows: HistoricalGridRow[]) {
  const out = new Map<string, string | null>()
  for (const expiry of EXPIRY_POINTS) {
    for (const tenor of TENOR_POINTS) {
      const series = rows
        .map((row) => {
          const nvol = interpolateGridValue(row.grid_data, expiry.label, tenor.label)
          return nvol === null ? null : { date: row.as_of_date, nvol }
        })
        .filter((point): point is { date: string; nvol: number } => point !== null)

      out.set(
        buildNodeKey(expiry.label, tenor.label),
        computeTechnicalSignalsFromSeries(series).regimeLabel
      )
    }
  }
  return out
}

function buildCell(
  snapshot: SnapshotRow,
  expiryLabel: string,
  tenorLabel: string,
  regimeMap: Map<string, string | null>,
  latestObservationMap: Map<string, CalibrationObservation>,
  comparisonSnapshot?: SnapshotRow | null
): VolGridCell {
  const nodeKey = buildNodeKey(expiryLabel, tenorLabel)
  const directMetadata = snapshot.node_metadata?.[nodeKey] ?? null
  const isCoreNode =
    CORE_EXPIRY_POINTS.some((point) => point.label === expiryLabel) &&
    CORE_TENOR_POINTS.some((point) => point.label === tenorLabel)

  const atmfVol = interpolateGridValue(snapshot.grid_data, expiryLabel, tenorLabel)
  const eodVol = interpolateGridValue(snapshot.eod_grid_data, expiryLabel, tenorLabel)
  const comparisonVol = comparisonSnapshot
    ? interpolateGridValue(comparisonSnapshot.grid_data, expiryLabel, tenorLabel)
    : null
  const representativeObservation = pickRepresentativeObservation(
    snapshot.node_metadata,
    expiryLabel,
    tenorLabel
  )
  const historicalLastObservation =
    latestObservationMap.get(nodeKey) ?? representativeObservation

  let atmfVolSource: VolSource = isCoreNode
    ? normalizeSource(directMetadata?.source)
    : 'interpolated'
  let atmfVolConfidence = isCoreNode
    ? clamp(parseNumber(directMetadata?.confidence) ?? 0, 0, 1)
    : clamp(
        (interpolateMetadataNumber(
          snapshot.node_metadata,
          expiryLabel,
          tenorLabel,
          'confidence'
        ) ?? 0) * 0.85,
        0,
        1
      )
  const staleness = isCoreNode
    ? parseNumber(directMetadata?.staleness_minutes)
    : interpolateMetadataNumber(
        snapshot.node_metadata,
        expiryLabel,
        tenorLabel,
        'staleness_minutes'
      )
  const atmfPremium = isCoreNode
    ? parseNumber(directMetadata?.premium)
    : interpolateMetadataNumber(
        snapshot.node_metadata,
        expiryLabel,
        tenorLabel,
        'premium'
      )
  const atmfPremiumBps = isCoreNode
    ? parseNumber(directMetadata?.premium_bps)
    : interpolateMetadataNumber(
        snapshot.node_metadata,
        expiryLabel,
        tenorLabel,
        'premium_bps'
      )
  const eodPremiumBps = isCoreNode
    ? parseNumber(directMetadata?.eod_premium_bps)
    : interpolateMetadataNumber(
        snapshot.node_metadata,
        expiryLabel,
        tenorLabel,
        'eod_premium_bps'
      )
  const rawPremiumBpsChange = isCoreNode
    ? parseNumber(directMetadata?.change_premium_bps)
    : interpolateMetadataNumber(
        snapshot.node_metadata,
        expiryLabel,
        tenorLabel,
        'change_premium_bps'
      )
  const atmfPremiumBpsChange =
    rawPremiumBpsChange ??
    (
      atmfPremiumBps !== null && eodPremiumBps !== null
        ? atmfPremiumBps - eodPremiumBps
        : estimatePremiumChangeFromVolRatio({
            premiumBps: atmfPremiumBps,
            currentVol: atmfVol,
            referenceVol: eodVol
          })
    )
  const observationCount = isCoreNode
    ? Math.round(parseNumber(directMetadata?.observation_count) ?? 0)
    : 0
  const change = isCoreNode
    ? parseNumber(directMetadata?.change_bpvol)
    : atmfVol !== null && eodVol !== null
      ? atmfVol - eodVol
      : null
  const lastObservationTime = representativeObservation?.executionTimestamp
    ?? parseTimestamp(directMetadata?.last_observation_time)
  const lastPropagatedFrom =
    normalizeGridLabel(directMetadata?.last_propagated_from) || null

  if (atmfVol === null) {
    atmfVolSource = 'no_data'
    atmfVolConfidence = 0
  }

  const expiryYears = parseTenorLabelToYears(expiryLabel) ?? 0
  const tenorYears = parseTenorLabelToYears(tenorLabel) ?? 0
  const stalenessCategory = computeStalenessCategory(atmfVolSource, staleness)

  return {
    nodeKey,
    expiry: expiryLabel,
    tenor: tenorLabel,
    expiryYears,
    tenorYears,
    atmfVol,
    eodVol,
    atmfVolSource,
    atmfVolConfidence,
    atmfVolChange: change,
    atmfVolChangeTime: lastObservationTime,
    atmfPremium,
    atmfPremiumBps,
    atmfPremiumBpsChange,
    lastObservation: historicalLastObservation,
    observationCount,
    staleness,
    stalenessCategory,
    lastPropagatedFrom,
    propagationFactor:
      atmfVolSource === 'propagated'
        ? 1
        : atmfVolSource === 'interpolated'
          ? 0.6
          : 0,
    quadrant: classifyQuadrant(expiryYears, tenorYears),
    regimeLabel: regimeMap.get(nodeKey) ?? null,
    comparisonVol,
    comparisonDiff:
      atmfVol !== null && comparisonVol !== null
        ? atmfVol - comparisonVol
        : null
  }
}

function buildEmptySurfaceResponse(
  preset: CalibrationPresetKey,
  session: Awaited<ReturnType<typeof resolveVolGridSession>>,
  reason: string
): VolGridSurfaceResponse {
  return {
    asOfDate: session.effectiveDate,
    asOfTimestamp: Date.now(),
    calibrationPreset: preset,
    grid: GRID_DEFINITION,
    cells: [],
    curve: null,
    meta: {
      hasData: false,
      emptyReason: reason,
      lastUpdate: null,
      calibrationTradeCount: 0,
      filteredOutCount: 0,
      snapshotKind: null,
      comparison: null,
      session
    }
  }
}

export async function buildVolGridSurface(params: {
  config: CalibrationFilterConfig
  preset: CalibrationPresetKey
  includePremium: boolean
  asOfDate?: string
  snapshotKind?: SnapshotKind
}): Promise<VolGridSurfaceResponse> {
  const _ = params.config
  const session = await resolveVolGridSession(params.preset, params.asOfDate)
  const requestedDate = params.asOfDate ?? toEasternDateKey(new Date())
  const preferredSnapshotKinds: SnapshotKind[] = [
    params.snapshotKind ?? session.defaultSnapshotKind,
    ...session.fallbackSnapshotKinds.filter(
      (kind) => kind !== (params.snapshotKind ?? session.defaultSnapshotKind)
    )
  ]
  let snapshot: SnapshotRow
  try {
    snapshot = await loadPreferredSnapshot(
      params.preset,
      preferredSnapshotKinds,
      session.effectiveDate
    )
  } catch (error) {
    if (isNoVolGridDataError(error)) {
      return buildEmptySurfaceResponse(params.preset, session, error.message)
    }
    throw error
  }
  const comparisonSnapshot =
    session.comparisonSnapshotKind &&
    session.comparisonSnapshotKind !== snapshot.snapshot_kind
      ? await loadExactSnapshotByKind(
          params.preset,
          session.comparisonSnapshotKind,
          snapshot.as_of_date
        )
      : null
  const historyRows = await loadHistoricalRowsForAnalytics(
    snapshot,
    {
      limit: 30,
      includeClosingGrid: session.isClosingView || requestedDate !== snapshot.as_of_date
    }
  )
  const regimeMap = buildRegimeMap(historyRows)
  const latestObservationMap = await loadLatestHistoricalObservations(
    params.preset,
    snapshot.as_of_date
  )
  const cells: VolGridCell[] = []

  for (const expiry of EXPIRY_POINTS) {
    for (const tenor of TENOR_POINTS) {
      cells.push(
        buildCell(
          snapshot,
          expiry.label,
          tenor.label,
          regimeMap,
          latestObservationMap,
          comparisonSnapshot
        )
      )
    }
  }

  return {
    asOfDate: snapshot.as_of_date,
    asOfTimestamp: parseTimestamp(snapshot.snapshot_ts) ?? Date.now(),
    calibrationPreset: params.preset,
    grid: GRID_DEFINITION,
    cells,
    curve: {
      curveName: snapshot.curve_name,
      source: snapshot.source,
      timestamp: snapshot.snapshot_ts ?? null,
      referenceDate: snapshot.eod_as_of_date ?? null
    },
    meta: {
      hasData: true,
      emptyReason: null,
      lastUpdate:
        parseTimestamp(snapshot.last_observation_ts) ??
        parseTimestamp(snapshot.snapshot_ts),
      calibrationTradeCount: Math.round(parseNumber(snapshot.observation_count) ?? 0),
      filteredOutCount: Math.round(parseNumber(snapshot.filtered_out_count) ?? 0),
      snapshotKind: snapshot.snapshot_kind,
      comparison: comparisonSnapshot
        ? {
            snapshotKind: comparisonSnapshot.snapshot_kind,
            source: comparisonSnapshot.source,
            asOfDate: comparisonSnapshot.as_of_date,
            timestamp: comparisonSnapshot.snapshot_ts ?? null
          }
        : null,
      session
    }
  }
}
