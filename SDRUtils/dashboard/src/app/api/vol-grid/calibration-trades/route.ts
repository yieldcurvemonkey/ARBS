// ABOUTME: Returns calibration trades feeding the live vol grid.
import { NextResponse } from 'next/server'
import { fetchCalibrationTrades } from '@/lib/vol-grid/data'
import { getCalibrationPreset } from '@/lib/vol-grid/config'
import { CALIBRATION_PRESETS } from '@/features/vol-grid/constants'
import type { CalibrationPresetKey } from '@/features/vol-grid/types'
import { resolveVolGridSession } from '@/lib/vol-grid/session'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const dateParam = searchParams.get('date')
  const presetParam = searchParams.get('calibration_preset') as CalibrationPresetKey | null

  const preset = presetParam && CALIBRATION_PRESETS[presetParam]
    ? presetParam
    : getCalibrationPreset()

  try {
    const session = await resolveVolGridSession(preset, dateParam ?? undefined)
    const result = await fetchCalibrationTrades({
      asOfDate: session.effectiveDate,
      preset,
      snapshotKinds: [
        session.defaultSnapshotKind,
        ...session.fallbackSnapshotKinds
      ]
    })
    return NextResponse.json({
      asOfDate: session.effectiveDate,
      calibrationPreset: preset,
      trades: result.calibrationTrades,
      filteredOutCount: result.filteredOutCount
    })
  } catch (error: any) {
    console.error('vol-grid/calibration-trades GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to fetch calibration trades' },
      { status: 500 }
    )
  }
}
