// ABOUTME: API endpoint that builds and returns the live ATMF vol surface grid.
// Fetches calibration trades from DB, runs them through the vol surface engine,
// and returns the full grid state with vol, premium, staleness per cell.
// Handles weekends/after-hours by looking back to the last trading session.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { VolSurfaceEngine } from '@/features/vol-grid/engine/vol-surface-engine'
import { filterCalibrationTrades } from '@/features/vol-grid/engine/calibration-filter'
import { computeMarketSession } from '@/features/vol-grid/engine/market-session'
import {
  IDB_STRADDLES_PRESET,
  CALIBRATION_PRESETS,
  PropagationConfig,
  DEFAULT_PROPAGATION_CONFIG,
  DEFAULT_STALENESS_CONFIG,
  AnnuityData,
} from '@/features/vol-grid/types'

// ---------------------------------------------------------------------------
// Fetch qualifying straddle trades from database
// ---------------------------------------------------------------------------

async function fetchTrades(sessionStart: number, sessionEnd: number) {
  // Use explicit timestamps instead of NOW() - INTERVAL to handle weekends correctly.
  // sessionStart/sessionEnd are epoch ms computed by market-session.ts
  const sql = `
    SELECT
      p.package_id,
      p.package_type,
      p.execution_start,
      p.tenor_label,
      p.forward_label,
      p.total_notional,
      p.total_premium,
      p.package_metrics,
      plat.platform_identifier,
      plat.event_action,
      (
        SELECT jsonb_agg(jsonb_build_object(
          'trade_id', l.trade_id,
          'leg_order', l.leg_order,
          'product_type', l.product_type,
          'trade_label', l.trade_label,
          'strike', l.strike,
          'notional', l.notional,
          'premium', l.premium,
          'leg_metrics', l.leg_metrics
        ) ORDER BY l.leg_order)
        FROM arbs_swaption_legs_v1 l
        WHERE l.package_id = p.package_id
      ) AS legs_json
    FROM arbs_swaption_packages_v1 p
    LEFT JOIN LATERAL (
      SELECT
        mode() WITHIN GROUP (ORDER BY l2.platform_identifier) AS platform_identifier,
        mode() WITHIN GROUP (ORDER BY l2.event_action) AS event_action
      FROM arbs_swaption_legs_v1 l2
      WHERE l2.package_id = p.package_id
    ) plat ON TRUE
    WHERE p.execution_start >= $1::timestamptz
      AND p.execution_start <= $2::timestamptz
    ORDER BY p.execution_start ASC
  `
  const startIso = new Date(sessionStart).toISOString()
  const endIso = new Date(sessionEnd).toISOString()
  const result = await query(sql, [startIso, endIso])
  return result.rows
}

// ---------------------------------------------------------------------------
// Fetch historical median vols for prior surface bootstrap
// ---------------------------------------------------------------------------

async function fetchHistoricalMedianVols(lookbackDays: number = 30) {
  const sql = `
    SELECT
      p.forward_label,
      p.tenor_label,
      PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
        COALESCE(
          (p.package_metrics->>'straddle_bpvol_yr')::numeric,
          (p.package_metrics->>'bpvol_yr')::numeric,
          (p.package_metrics->>'implied_vol_bpyr')::numeric
        )
      ) AS median_vol
    FROM arbs_swaption_packages_v1 p
    LEFT JOIN LATERAL (
      SELECT mode() WITHIN GROUP (ORDER BY l.platform_identifier) AS platform_identifier
      FROM arbs_swaption_legs_v1 l
      WHERE l.package_id = p.package_id
    ) plat ON TRUE
    WHERE p.package_type = 'STRADDLE'
      AND plat.platform_identifier IN ('BGCD', 'ISWV', 'TPSE')
      AND p.execution_start >= NOW() - INTERVAL '${lookbackDays} days'
      AND p.forward_label IS NOT NULL
      AND p.tenor_label IS NOT NULL
      AND (
        (p.package_metrics->>'straddle_bpvol_yr')::numeric IS NOT NULL
        OR (p.package_metrics->>'bpvol_yr')::numeric IS NOT NULL
        OR (p.package_metrics->>'implied_vol_bpyr')::numeric IS NOT NULL
      )
    GROUP BY p.forward_label, p.tenor_label
  `
  try {
    const result = await query(sql)
    const priors: Record<string, number> = {}
    for (const row of result.rows) {
      if (row.forward_label && row.tenor_label && row.median_vol) {
        const key = `${row.forward_label}x${row.tenor_label}`
        priors[key] = parseFloat(row.median_vol)
      }
    }
    return priors
  } catch {
    return {}
  }
}

// ---------------------------------------------------------------------------
// Optionally fetch annuity data from Python backend
// ---------------------------------------------------------------------------

async function fetchAnnuityData(
  pythonApiUrl: string | null,
): Promise<AnnuityData | null> {
  if (!pythonApiUrl) return null
  try {
    const res = await fetch(`${pythonApiUrl}/api/sofr-curve/annuities`, {
      signal: AbortSignal.timeout(10_000),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// GET handler
// ---------------------------------------------------------------------------

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const presetName = searchParams.get('calibration_preset') || 'IDB Straddles'

  // Parse propagation config overrides
  const propagationConfig: PropagationConfig = {
    ...DEFAULT_PROPAGATION_CONFIG,
    lengthScale: parseFloat(searchParams.get('length_scale') || String(DEFAULT_PROPAGATION_CONFIG.lengthScale)),
    expiryWeight: parseFloat(searchParams.get('expiry_weight') || String(DEFAULT_PROPAGATION_CONFIG.expiryWeight)),
    tenorWeight: parseFloat(searchParams.get('tenor_weight') || String(DEFAULT_PROPAGATION_CONFIG.tenorWeight)),
  }

  const calibrationConfig = CALIBRATION_PRESETS[presetName] || IDB_STRADDLES_PRESET

  try {
    // Compute the market session — this determines what time window to query
    const session = computeMarketSession()

    // Fetch trades for the relevant session window and prior in parallel
    const [rawTrades, priorVols] = await Promise.all([
      fetchTrades(session.sessionStart, session.isMarketOpen ? Date.now() : session.sessionEnd),
      fetchHistoricalMedianVols(),
    ])

    // Run calibration filter
    const { observations, filteredOutCount } = filterCalibrationTrades(rawTrades, calibrationConfig)

    // Build surface
    const engine = new VolSurfaceEngine(propagationConfig, DEFAULT_STALENESS_CONFIG, calibrationConfig)

    // Initialize prior surface
    if (Object.keys(priorVols).length > 0) {
      engine.initializeFromPrior(priorVols)
    }

    // If Python SOFR curve backend is available, use it for accurate annuities.
    // Otherwise the engine falls back to flat-rate approximation (~4.3% SOFR).
    const pythonApiUrl = process.env.VOL_GRID_PYTHON_API_URL || null
    const annuityData = await fetchAnnuityData(pythonApiUrl)
    if (annuityData) {
      engine.setAnnuityData(annuityData.grid_points, {
        curveName: annuityData.curve_name,
        source: annuityData.source,
        timestamp: annuityData.timestamp,
        referenceDate: annuityData.reference_date,
      })
    }

    // Process observations (also fills empty cells via interpolation)
    engine.processObservations(observations, filteredOutCount)

    // Build grid state — always includes premiums (flat-rate fallback if no curve)
    const gridState = engine.buildGridState(session)

    return NextResponse.json(gridState)
  } catch (error: any) {
    console.error('vol-grid/surface GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build vol surface' },
      { status: 500 },
    )
  }
}
