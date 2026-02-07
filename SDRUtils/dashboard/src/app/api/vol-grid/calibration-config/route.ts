// ABOUTME: Stores server-side calibration filter configuration for vol grid.
import { NextResponse } from 'next/server'
import {
  getCalibrationConfig,
  getCalibrationPreset,
  setCalibrationConfig,
  setCalibrationPreset
} from '@/lib/vol-grid/config'
import { CALIBRATION_PRESETS } from '@/features/vol-grid/constants'
import type { CalibrationFilterConfig, CalibrationPresetKey } from '@/features/vol-grid/types'

export const runtime = 'nodejs'

type CalibrationConfigPayload = {
  preset?: CalibrationPresetKey
  config?: CalibrationFilterConfig
}

export async function GET() {
  const preset = getCalibrationPreset()
  const config = getCalibrationConfig()
  return NextResponse.json({ preset, config })
}

export async function PUT(request: Request) {
  try {
    const payload = (await request.json()) as CalibrationConfigPayload
    const preset = payload.preset
    const config = payload.config

    if (preset && CALIBRATION_PRESETS[preset]) {
      setCalibrationPreset(preset)
      return NextResponse.json({ preset, config: getCalibrationConfig(preset) })
    }

    if (config) {
      setCalibrationConfig(config, preset)
      return NextResponse.json({ preset: getCalibrationPreset(), config })
    }

    return NextResponse.json(
      { error: 'preset or config is required' },
      { status: 400 }
    )
  } catch (error: any) {
    console.error('vol-grid/calibration-config PUT error', error)
    return NextResponse.json(
      { error: error?.message || 'Failed to update calibration config' },
      { status: 500 }
    )
  }
}
