// ABOUTME: Returns calibration trades feeding the live vol grid.
import { NextResponse } from 'next/server'
import { fetchCalibrationTrades } from '@/lib/vol-grid/data'
import { getCalibrationConfig, getCalibrationPreset } from '@/lib/vol-grid/config'
import { CALIBRATION_PRESETS } from '@/features/vol-grid/constants'
import type { CalibrationPresetKey } from '@/features/vol-grid/types'
import { toEasternDateKey } from '@/features/vol-grid/utils'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const dateParam = searchParams.get('date')
  const presetParam = searchParams.get('calibration_preset') as CalibrationPresetKey | null

  const asOfDate = dateParam ?? toEasternDateKey(new Date())
  const preset = presetParam && CALIBRATION_PRESETS[presetParam]
    ? presetParam
    : getCalibrationPreset()
  const config = getCalibrationConfig(preset)

  try {
    const result = await fetchCalibrationTrades(asOfDate, config)
    return NextResponse.json({
      asOfDate,
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
