import type { CalibrationFilterConfig, CalibrationPresetKey } from './types'

export const VOL_GRID_DEFAULT_CURVE_NAME = 'USD-SOFR-1D'
export const VOL_GRID_DEFAULT_SURFACE_TYPE = 'atmf_normal'

export const CORE_EXPIRY_POINTS = [
  { label: '1M', years: 1 / 12 },
  { label: '3M', years: 3 / 12 },
  { label: '6M', years: 6 / 12 },
  { label: '1Y', years: 1 },
  { label: '2Y', years: 2 },
  { label: '3Y', years: 3 },
  { label: '5Y', years: 5 },
  { label: '7Y', years: 7 },
  { label: '10Y', years: 10 },
  { label: '15Y', years: 15 },
  { label: '20Y', years: 20 }
] as const

export const CORE_TENOR_POINTS = [
  { label: '1Y', years: 1 },
  { label: '2Y', years: 2 },
  { label: '5Y', years: 5 },
  { label: '10Y', years: 10 },
  { label: '20Y', years: 20 },
  { label: '30Y', years: 30 }
] as const

export const EXPIRY_POINTS = [
  ...CORE_EXPIRY_POINTS
] as const

export const TENOR_POINTS = [
  { label: '1Y', years: 1 },
  { label: '2Y', years: 2 },
  { label: '3Y', years: 3 },
  { label: '5Y', years: 5 },
  { label: '7Y', years: 7 },
  { label: '10Y', years: 10 },
  { label: '20Y', years: 20 },
  { label: '30Y', years: 30 }
] as const

export const CORE_GRID_DEFINITION = {
  expiries: CORE_EXPIRY_POINTS.map((point) => point.label),
  tenors: CORE_TENOR_POINTS.map((point) => point.label),
  expiryYears: CORE_EXPIRY_POINTS.map((point) => point.years),
  tenorYears: CORE_TENOR_POINTS.map((point) => point.years)
}

export const GRID_DEFINITION = {
  expiries: EXPIRY_POINTS.map((point) => point.label),
  tenors: TENOR_POINTS.map((point) => point.label),
  expiryYears: EXPIRY_POINTS.map((point) => point.years),
  tenorYears: TENOR_POINTS.map((point) => point.years)
}

export const IDB_STRADDLES_PRESET: CalibrationFilterConfig = {
  platforms: { idb: true, custy: false },
  packageTypes: {
    straddle: true,
    outright: false,
    riskReversal: false,
    verticalSpread: false,
    other: false
  },
  minimumNotional: 25_000_000,
  maximumNotional: null,
  requireATMF: true,
  maxStrikeOffsetBps: null,
  actions: { newTrade: true, amendment: false, termination: false },
  observationHalfLife: 120,
  maxStalenessMinutes: 480,
  propagationLengthScale: 0.7,
  expiryWeight: 1.0,
  tenorWeight: 0.7
}

export const CUSTY_ONLY_PRESET: CalibrationFilterConfig = {
  ...IDB_STRADDLES_PRESET,
  platforms: { idb: false, custy: true }
}

export const COMBINED_STRADDLES_PRESET: CalibrationFilterConfig = {
  ...IDB_STRADDLES_PRESET,
  platforms: { idb: true, custy: true }
}

export const CALIBRATION_PRESETS: Record<CalibrationPresetKey, CalibrationFilterConfig> = {
  idb_straddles: IDB_STRADDLES_PRESET,
  all_idb: IDB_STRADDLES_PRESET,
  custy_only: CUSTY_ONLY_PRESET,
  custy_and_idb: COMBINED_STRADDLES_PRESET,
  straddles_only: COMBINED_STRADDLES_PRESET
}

export const SNAPSHOT_PRESET_ALIASES: Record<
  CalibrationPresetKey,
  'idb_straddles' | 'custy_only' | 'custy_and_idb'
> = {
  idb_straddles: 'idb_straddles',
  all_idb: 'idb_straddles',
  custy_only: 'custy_only',
  custy_and_idb: 'custy_and_idb',
  straddles_only: 'custy_and_idb'
}

export const CANONICAL_PRESET_OPTIONS: Array<{
  key: 'idb_straddles' | 'custy_only' | 'custy_and_idb'
  label: string
}> = [
  { key: 'idb_straddles', label: 'IDB Only' },
  { key: 'custy_only', label: 'Custy Only' },
  { key: 'custy_and_idb', label: 'Combined' }
]

export function resolveSnapshotPreset(
  preset: CalibrationPresetKey
): 'idb_straddles' | 'custy_only' | 'custy_and_idb' {
  return SNAPSHOT_PRESET_ALIASES[preset]
}
