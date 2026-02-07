// ABOUTME: Returns all calibration trades that fed the current vol surface.
// Handles weekends/after-hours by querying the last trading session.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import { filterCalibrationTrades } from '@/features/vol-grid/engine/calibration-filter'
import { computeMarketSession } from '@/features/vol-grid/engine/market-session'
import {
  IDB_STRADDLES_PRESET,
  CALIBRATION_PRESETS,
} from '@/features/vol-grid/types'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const presetName = searchParams.get('calibration_preset') || 'IDB Straddles'
  const limit = Math.min(parseInt(searchParams.get('limit') || '100', 10), 500)

  const calibrationConfig = CALIBRATION_PRESETS[presetName] || IDB_STRADDLES_PRESET

  try {
    const session = computeMarketSession()

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
      ORDER BY p.execution_start DESC
    `
    const startIso = new Date(session.sessionStart).toISOString()
    const endIso = new Date(session.isMarketOpen ? Date.now() : session.sessionEnd).toISOString()
    const result = await query(sql, [startIso, endIso])
    const { observations, filteredOutCount } = filterCalibrationTrades(result.rows, calibrationConfig)

    // Sort by most recent first and limit
    const sorted = observations
      .sort((a, b) => b.executionTimestamp - a.executionTimestamp)
      .slice(0, limit)

    return NextResponse.json({
      trades: sorted,
      totalQualifying: observations.length,
      filteredOutCount,
      preset: presetName,
      session: {
        status: session.status,
        tradingDate: session.tradingDate,
        sessionLabel: session.sessionLabel,
      },
    })
  } catch (error: any) {
    console.error('vol-grid/calibration-trades GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch calibration trades' },
      { status: 500 },
    )
  }
}
