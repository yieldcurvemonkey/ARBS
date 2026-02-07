// ABOUTME: Builds live ATMF vol + premium grid from calibration trades.
import { NextResponse } from 'next/server'
import { buildVolGridSurface } from '@/lib/vol-grid/engine'
import {
  getCalibrationConfig,
  getCalibrationPreset,
  setCalibrationPreset
} from '@/lib/vol-grid/config'
import type { CalibrationPresetKey } from '@/features/vol-grid/types'
import { CALIBRATION_PRESETS } from '@/features/vol-grid/constants'

export const runtime = 'nodejs'

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url)
  const presetParam = searchParams.get('calibration_preset') as CalibrationPresetKey | null
  const includePremium = searchParams.get('include_premium') === 'true'
  const asOfDate = searchParams.get('date') ?? undefined

  const preset = presetParam && CALIBRATION_PRESETS[presetParam]
    ? presetParam
    : getCalibrationPreset()

  if (presetParam && CALIBRATION_PRESETS[presetParam]) {
    setCalibrationPreset(presetParam)
  }

  const config = getCalibrationConfig(preset)

  try {
    const surface = await buildVolGridSurface({
      config,
      preset,
      includePremium,
      asOfDate
    })
    return NextResponse.json(surface)
  } catch (error: any) {
    console.error('vol-grid/surface GET error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to build vol grid surface' },
      { status: 500 }
    )
  }
}
