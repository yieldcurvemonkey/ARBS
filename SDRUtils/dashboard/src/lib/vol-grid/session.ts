import type {
  CalibrationPresetKey,
  SnapshotKind,
  VolGridSessionMeta,
  VolGridSessionMode
} from '@/features/vol-grid/types'
import {
  VOL_GRID_DEFAULT_CURVE_NAME,
  VOL_GRID_DEFAULT_SURFACE_TYPE,
  resolveSnapshotPreset
} from '@/features/vol-grid/constants'
import { query } from '@/lib/db'
import { normalizeDateKey, toEasternDateKey } from '@/features/vol-grid/utils'

const SNAPSHOTS_TABLE = 'arbs_live_atmf_grid_snapshots_v1'
const EOD_HISTORY_TABLE = 'arbs_atmf_grid_eod_history_v1'
const ET_TIMEZONE = 'America/New_York'
const MARKET_OPEN_HOUR_ET = 7
const MARKET_CLOSE_HOUR_ET = 17

function parseDateKey(value: string | Date | null | undefined): Date | null {
  const dateKey = normalizeDateKey(value)
  if (!dateKey) return null
  const match = dateKey.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null
  }
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function shiftDateKey(dateKey: string, days: number): string | null {
  const parsed = parseDateKey(dateKey)
  if (!parsed) return null
  parsed.setUTCDate(parsed.getUTCDate() + days)
  return parsed.toISOString().slice(0, 10)
}

function weekdayInEt(value: Date) {
  const weekday = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TIMEZONE,
    weekday: 'short'
  }).format(value)
  return weekday
}

function etHour(value: Date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TIMEZONE,
    hour: '2-digit',
    hourCycle: 'h23'
  }).formatToParts(value)
  const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? '0')
  return Number.isFinite(hour) ? hour : 0
}

function previousBusinessDate(dateKey: string): string {
  let cursor = dateKey
  while (true) {
    cursor = shiftDateKey(cursor, -1) ?? cursor
    const weekday = weekdayInEt(new Date(`${cursor}T12:00:00Z`))
    if (weekday !== 'Sat' && weekday !== 'Sun') {
      return cursor
    }
  }
}

function formatDisplayDate(dateKey: string) {
  const normalized = normalizeDateKey(dateKey)
  if (!normalized) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: ET_TIMEZONE,
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(new Date(`${normalized}T12:00:00Z`))
}

async function loadLatestStoredDate(
  preset: CalibrationPresetKey,
  onOrBefore: string
) {
  const result = await query<{ as_of_date: string | Date | null }>(
    `
      SELECT as_of_date
      FROM (
        SELECT as_of_date
        FROM ${SNAPSHOTS_TABLE}
        WHERE calibration_preset = $1
          AND as_of_date <= $2
        UNION
        SELECT as_of_date
        FROM ${EOD_HISTORY_TABLE}
        WHERE curve_name = $3
          AND surface_type = $4
          AND as_of_date <= $2
      ) stored_dates
      ORDER BY as_of_date DESC
      LIMIT 1
    `,
    [
      resolveSnapshotPreset(preset),
      onOrBefore,
      VOL_GRID_DEFAULT_CURVE_NAME,
      VOL_GRID_DEFAULT_SURFACE_TYPE
    ]
  )
  return normalizeDateKey(result.rows[0]?.as_of_date)
}

function buildSessionLabel(mode: VolGridSessionMode, effectiveDate: string) {
  const formattedDate = formatDisplayDate(effectiveDate)
  switch (mode) {
    case 'weekend_close':
      return `Weekend mode: showing ${formattedDate} close`
    case 'eod_close':
      return `Market closed: showing ${formattedDate} close`
    case 'preopen_close':
      return `Pre-open: showing ${formattedDate} close`
    case 'historical':
      return `Historical close: ${formattedDate}`
    case 'prior_close':
      return `Showing latest available close: ${formattedDate}`
    default:
      return `Live intraday: ${formattedDate}`
  }
}

function resolveSnapshotKinds(mode: VolGridSessionMode): {
  defaultSnapshotKind: SnapshotKind
  fallbackSnapshotKinds: SnapshotKind[]
  comparisonSnapshotKind: SnapshotKind | null
} {
  if (mode === 'live') {
    return {
      defaultSnapshotKind: 'intraday',
      fallbackSnapshotKinds: ['close_pca', 'close_mdp'],
      comparisonSnapshotKind: null
    }
  }
  return {
    defaultSnapshotKind: 'close_pca',
    fallbackSnapshotKinds: ['close_mdp', 'intraday'],
    comparisonSnapshotKind: 'close_mdp'
  }
}

export async function resolveVolGridSession(
  preset: CalibrationPresetKey,
  requestedDate?: string,
  now: Date = new Date()
): Promise<VolGridSessionMeta> {
  const normalizedRequestedDate = normalizeDateKey(requestedDate)
  if (requestedDate && !normalizedRequestedDate) {
    throw new Error(`Invalid date '${requestedDate}'. Expected YYYY-MM-DD.`)
  }
  const requested = normalizedRequestedDate ?? toEasternDateKey(now)
  let mode: VolGridSessionMode = 'live'
  let targetDate = requested

  if (requestedDate) {
    mode = 'historical'
  } else {
    const weekday = weekdayInEt(now)
    const hour = etHour(now)
    if (weekday === 'Sat' || weekday === 'Sun') {
      mode = 'weekend_close'
      targetDate = previousBusinessDate(requested)
    } else if (hour < MARKET_OPEN_HOUR_ET) {
      mode = 'preopen_close'
      targetDate = previousBusinessDate(requested)
    } else if (hour >= MARKET_CLOSE_HOUR_ET) {
      mode = 'eod_close'
      targetDate = requested
    }
  }

  const latestStoredDate = await loadLatestStoredDate(preset, targetDate)
  const effectiveDate = latestStoredDate ?? targetDate
  if (!requestedDate && mode === 'live' && effectiveDate < targetDate) {
    mode = 'prior_close'
  }
  const snapshotSelection = resolveSnapshotKinds(mode)

  return {
    mode,
    label: buildSessionLabel(mode, effectiveDate),
    requestedDate: requested,
    effectiveDate,
    isClosingView: mode !== 'live',
    defaultSnapshotKind: snapshotSelection.defaultSnapshotKind,
    fallbackSnapshotKinds: snapshotSelection.fallbackSnapshotKinds,
    comparisonSnapshotKind: snapshotSelection.comparisonSnapshotKind
  }
}
