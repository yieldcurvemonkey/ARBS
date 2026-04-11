import type { CalibrationFilterConfig, CalibrationPresetKey } from '@/features/vol-grid/types'
import { CALIBRATION_PRESETS, IDB_STRADDLES_PRESET } from '@/features/vol-grid/constants'

let activePreset: CalibrationPresetKey = 'idb_straddles'
let activeConfig: CalibrationFilterConfig = { ...IDB_STRADDLES_PRESET }

function cloneConfig(config: CalibrationFilterConfig): CalibrationFilterConfig {
  return {
    platforms: {
      idb: config.platforms.idb,
      custy: config.platforms.custy,
      specificPlatforms: config.platforms.specificPlatforms
        ? [...config.platforms.specificPlatforms]
        : undefined
    },
    packageTypes: { ...config.packageTypes },
    minimumNotional: config.minimumNotional,
    maximumNotional: config.maximumNotional,
    requireATMF: config.requireATMF,
    maxStrikeOffsetBps: config.maxStrikeOffsetBps,
    actions: { ...config.actions },
    observationHalfLife: config.observationHalfLife,
    maxStalenessMinutes: config.maxStalenessMinutes,
    propagationLengthScale: config.propagationLengthScale,
    expiryWeight: config.expiryWeight,
    tenorWeight: config.tenorWeight
  }
}

export function getCalibrationPreset(): CalibrationPresetKey {
  return activePreset
}

export function getCalibrationConfig(
  presetOverride?: CalibrationPresetKey
): CalibrationFilterConfig {
  if (presetOverride && CALIBRATION_PRESETS[presetOverride]) {
    return cloneConfig(CALIBRATION_PRESETS[presetOverride])
  }
  return cloneConfig(activeConfig)
}

export function setCalibrationConfig(
  config: CalibrationFilterConfig,
  preset?: CalibrationPresetKey
) {
  activeConfig = cloneConfig(config)
  if (preset && CALIBRATION_PRESETS[preset]) {
    activePreset = preset
  }
}

export function setCalibrationPreset(preset: CalibrationPresetKey) {
  if (!CALIBRATION_PRESETS[preset]) return
  activePreset = preset
  activeConfig = cloneConfig(CALIBRATION_PRESETS[preset])
}
