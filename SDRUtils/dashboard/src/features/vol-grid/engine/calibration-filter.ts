// ABOUTME: Calibration filter engine that determines which SDR trades qualify as vol surface inputs.

import {
  CalibrationFilterConfig,
  CalibrationObservation,
  EXPIRY_YEARS,
  TENOR_YEARS,
  ExpiryLabel,
  TenorLabel,
} from '../types'

const IDB_PLATFORMS = new Set(['BGCD', 'ISWV', 'TPSE'])

type RawTrade = {
  package_id: string
  package_type: string | null
  execution_start: string
  tenor_label: string | null
  forward_label: string | null
  total_notional: number | null
  total_premium: number | null
  platform_identifier: string | null
  event_action: string | null
  package_metrics: Record<string, any> | null
  legs_json: any[]
}

/**
 * Determine if a platform identifier indicates IDB.
 */
function isIDBPlatform(platform: string | null | undefined): boolean {
  if (!platform) return false
  const tokens = platform.toUpperCase().split(/[\s,;/]+/)
  return tokens.some(t => IDB_PLATFORMS.has(t))
}

/**
 * Extract the straddle bpvol/yr from a trade's package_metrics or leg_metrics.
 * For straddles, this is the ATMF vol signal.
 */
function extractStraddleBpvol(trade: RawTrade): number | null {
  // Check package_metrics first
  const pm = trade.package_metrics
  if (pm) {
    if (typeof pm.straddle_bpvol_yr === 'number') return pm.straddle_bpvol_yr
    if (typeof pm.bpvol_yr === 'number') return pm.bpvol_yr
    if (typeof pm.implied_vol_bpyr === 'number') return pm.implied_vol_bpyr
  }

  // Check leg metrics - for straddles, the vol should be on leg[0]
  if (trade.legs_json?.length > 0) {
    const leg0 = trade.legs_json[0]
    const lm = leg0.leg_metrics || leg0
    if (typeof lm.bpvol === 'number') return lm.bpvol
    if (typeof lm.implied_vol_bpyr === 'number') return lm.implied_vol_bpyr
    if (lm.leg_metrics && typeof lm.leg_metrics.bpvol === 'number') return lm.leg_metrics.bpvol
  }

  return null
}

/**
 * Parse a label like "10Y", "1M", "6M" into fractional years.
 */
export function parseLabelToYears(label: string | null): number | null {
  if (!label) return null
  const match = label.trim().toUpperCase().match(/^(\d+(?:\.\d+)?)\s*(M|Y|D|W)$/)
  if (!match) return null
  const value = parseFloat(match[1])
  switch (match[2]) {
    case 'Y': return value
    case 'M': return value / 12
    case 'W': return value / 52
    case 'D': return value / 365
    default: return null
  }
}

/**
 * Check if an event action qualifies.
 */
function actionQualifies(action: string | null, config: CalibrationFilterConfig): boolean {
  if (!action) return config.actions.newTrade // default: treat no action as new
  const upper = action.toUpperCase()
  if (upper.includes('NEWT') || upper.includes('NEW')) return config.actions.newTrade
  if (upper.includes('AMEND') || upper.includes('CORR')) return config.actions.amendment
  if (upper.includes('TERM')) return config.actions.termination
  return config.actions.newTrade
}

/**
 * Check if a package type qualifies.
 */
function packageTypeQualifies(pkgType: string | null, config: CalibrationFilterConfig): boolean {
  if (!pkgType) return false
  const upper = pkgType.toUpperCase().replace(/-/g, '_')
  if (upper === 'STRADDLE') return config.packageTypes.straddle
  if (upper === 'OUTRIGHT') return config.packageTypes.outright
  if (upper === 'RISK_REVERSAL' || upper === 'CUSTY_RR_STRANGLE') return config.packageTypes.riskReversal
  if (upper.startsWith('VERTICAL_SPREAD')) return config.packageTypes.verticalSpread
  return config.packageTypes.other
}

/**
 * Apply calibration filter to a raw trade. Returns a CalibrationObservation if it qualifies, null otherwise.
 */
export function applyCalibrationFilter(
  trade: RawTrade,
  config: CalibrationFilterConfig,
): CalibrationObservation | null {
  // 1. Action filter
  if (!actionQualifies(trade.event_action, config)) return null

  // 2. Package type filter
  if (!packageTypeQualifies(trade.package_type, config)) return null

  // 3. Platform filter
  const isIdb = isIDBPlatform(trade.platform_identifier)
  if (isIdb && !config.platforms.idb) return null
  if (!isIdb && !config.platforms.custy) return null
  if (config.platforms.specificPlatforms?.length) {
    const platform = trade.platform_identifier?.toUpperCase() || ''
    const tokens = platform.split(/[\s,;/]+/)
    const hasMatch = tokens.some(t => config.platforms.specificPlatforms!.includes(t))
    if (!hasMatch) return null
  }

  // 4. Notional filter
  const notional = Math.abs(trade.total_notional || 0)
  if (config.minimumNotional !== null && notional < config.minimumNotional) return null
  if (config.maximumNotional !== null && notional > config.maximumNotional) return null

  // 5. Extract ATMF vol
  const bpvol = extractStraddleBpvol(trade)
  if (bpvol === null || bpvol <= 0) return null

  // 6. Parse grid coordinates
  const expiryYears = parseLabelToYears(trade.forward_label)
  const tenorYears = parseLabelToYears(trade.tenor_label)
  if (expiryYears === null || tenorYears === null) return null

  return {
    packageId: trade.package_id,
    executionTimestamp: new Date(trade.execution_start).getTime(),
    platform: trade.platform_identifier || 'UNKNOWN',
    packageType: trade.package_type || 'UNKNOWN',
    bpvolYr: bpvol,
    premium: trade.total_premium,
    notional,
    tradeLabel: `${trade.forward_label ?? '?'}x${trade.tenor_label ?? '?'}`,
    expiryLabel: trade.forward_label || '',
    tenorLabel: trade.tenor_label || '',
    expiryYears,
    tenorYears,
    isCalibrationTrade: true,
  }
}

/**
 * Filter a batch of raw trades through the calibration engine.
 * Returns qualifying observations and the count of filtered-out trades.
 */
export function filterCalibrationTrades(
  trades: RawTrade[],
  config: CalibrationFilterConfig,
): { observations: CalibrationObservation[]; filteredOutCount: number } {
  const observations: CalibrationObservation[] = []
  let filteredOut = 0

  for (const trade of trades) {
    const obs = applyCalibrationFilter(trade, config)
    if (obs) {
      observations.push(obs)
    } else {
      filteredOut++
    }
  }

  return { observations, filteredOutCount: filteredOut }
}
