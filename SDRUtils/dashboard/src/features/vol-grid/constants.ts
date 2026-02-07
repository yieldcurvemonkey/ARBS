import type { CalibrationFilterConfig, CalibrationPresetKey } from './types'

export const EXPIRY_POINTS = [
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
  { label: '20Y', years: 20 },
  { label: '30Y', years: 30 }
] as const

export const TENOR_POINTS = [
  { label: '1Y', years: 1 },
  { label: '2Y', years: 2 },
  { label: '3Y', years: 3 },
  { label: '5Y', years: 5 },
  { label: '7Y', years: 7 },
  { label: '10Y', years: 10 },
  { label: '15Y', years: 15 },
  { label: '20Y', years: 20 },
  { label: '25Y', years: 25 },
  { label: '30Y', years: 30 }
] as const

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

export const CALIBRATION_PRESETS: Record<CalibrationPresetKey, CalibrationFilterConfig> = {
  idb_straddles: IDB_STRADDLES_PRESET,
  all_idb: {
    ...IDB_STRADDLES_PRESET,
    packageTypes: {
      straddle: true,
      outright: true,
      riskReversal: true,
      verticalSpread: true,
      other: false
    }
  },
  custy_and_idb: {
    ...IDB_STRADDLES_PRESET,
    platforms: { idb: true, custy: true }
  },
  straddles_only: {
    ...IDB_STRADDLES_PRESET,
    platforms: { idb: true, custy: true }
  }
}
