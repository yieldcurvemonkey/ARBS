import { EXPIRY_POINTS, TENOR_POINTS } from './constants'
import type {
  VolGridCell,
  VolGridHeatmapConfig,
  VolGridHeatmapPalette,
  VolGridHeatmapRange
} from './types'

export function normalizeDateKey(value: string | Date | null | undefined): string | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString().slice(0, 10)
  }

  const text = String(value).trim()
  if (!text) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text
  }

  const parsed = new Date(text)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10)
}

export function parseTenorLabelToYears(label: string | null | undefined): number | null {
  if (!label) return null
  const match = String(label).trim().toUpperCase().match(/^(\d+(?:\.\d+)?)([DWMY])$/)
  if (!match) return null
  const value = Number(match[1])
  if (!Number.isFinite(value)) return null
  const unit = match[2]
  switch (unit) {
    case 'D':
      return value / 365
    case 'W':
      return value / 52
    case 'M':
      return value / 12
    case 'Y':
      return value
    default:
      return null
  }
}

export function resolveGridIndex(
  expiryYears: number,
  tenorYears: number
): { expiryIndex: number; tenorIndex: number } | null {
  const expiryIndex = EXPIRY_POINTS.findIndex(
    (point) => point.years === expiryYears
  )
  const tenorIndex = TENOR_POINTS.findIndex(
    (point) => point.years === tenorYears
  )
  if (expiryIndex < 0 || tenorIndex < 0) return null
  return { expiryIndex, tenorIndex }
}

export function formatLabel(expiry: string, tenor: string) {
  return `${expiry}x${tenor}`
}

export function normalizeGridLabel(label: string | null | undefined) {
  return String(label ?? '').trim().toLowerCase()
}

export function buildNodeKey(expiry: string, tenor: string) {
  return `${normalizeGridLabel(expiry)}_${normalizeGridLabel(tenor)}`
}

export function parseHeatmapHighlightTargets(value: string | null | undefined): string[] {
  if (!value) return []

  const tokens = String(value)
    .split(/[\n,;]+/)
    .map((token) => token.trim())
    .filter(Boolean)
  const nodeKeys = new Set<string>()

  for (const token of tokens) {
    const normalized = token.replace(/\s+/g, ' ').trim()
    const match =
      normalized.match(
        /^(\d+(?:\.\d+)?[dDwWmMyY])\s*(?:x|_|\/|-)\s*(\d+(?:\.\d+)?[dDwWmMyY])$/
      ) ??
      normalized.match(/^(\d+(?:\.\d+)?[dDwWmMyY])\s+(\d+(?:\.\d+)?[dDwWmMyY])$/)
    if (!match) continue
    nodeKeys.add(buildNodeKey(match[1], match[2]))
  }

  return Array.from(nodeKeys)
}

export function toEasternDateKey(value: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(value)
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

// ── Formatting utilities ──

export function formatNumber(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  return value.toFixed(digits)
}

export function formatChange(value: number | null, digits = 1) {
  if (value === null || !Number.isFinite(value)) return '--'
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  return `${sign}${Math.abs(value).toFixed(digits)}`
}

export function formatPremiumBps(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${value.toFixed(2)} bp`
}

export function formatNotional(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  return `${(Math.abs(value) / 1_000_000).toFixed(0)}mm`
}

export function formatTime(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value))
}

export function formatDate(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: 'short',
    day: '2-digit'
  }).format(new Date(value))
}

export function formatDateTime(value: number | null) {
  if (!value) return '--'
  return `${formatDate(value)} ${formatTime(value)} ET`
}

export function formatStaleness(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '--'
  if (value < 60) return `${Math.round(value)}m`
  return `${(value / 60).toFixed(1)}h`
}

export function formatConfidence(value: number) {
  if (!Number.isFinite(value)) return '--'
  return `${(value * 100).toFixed(0)}%`
}

export function formatTimestamp(value: number | null) {
  if (!value) return '--'
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

// ── Color utilities ──

export const STALENESS_COLORS: Record<string, string> = {
  live: '#22c55e',
  recent: '#f59e0b',
  stale: '#ef4444',
  very_stale: '#6b7280',
  no_data: '#475569'
}

const NEUTRAL_CELL_BACKGROUND = 'rgba(15, 23, 42, 0.72)'
type HeatmapPaletteDefinition = {
  sequentialStops: Array<[number, number[]]>
  negativeColor: number[]
  positiveColor: number[]
}

const HEATMAP_PALETTE_DEFINITIONS: Record<
  VolGridHeatmapPalette,
  HeatmapPaletteDefinition
> = {
  icefire: {
    sequentialStops: [
      [0, [30, 60, 116]],
      [0.28, [51, 99, 160]],
      [0.55, [88, 146, 182]],
      [0.78, [163, 104, 99]],
      [1, [129, 38, 67]]
    ],
    negativeColor: [51, 99, 160],
    positiveColor: [129, 38, 67]
  },
  blue: {
    sequentialStops: [
      [0, [15, 23, 42]],
      [0.22, [30, 58, 138]],
      [0.48, [37, 99, 235]],
      [0.74, [56, 189, 248]],
      [1, [186, 230, 253]]
    ],
    negativeColor: [30, 64, 175],
    positiveColor: [56, 189, 248]
  },
  viridis: {
    sequentialStops: [
      [0, [68, 1, 84]],
      [0.25, [59, 82, 139]],
      [0.5, [33, 145, 140]],
      [0.75, [94, 201, 98]],
      [1, [253, 231, 37]]
    ],
    negativeColor: [68, 1, 84],
    positiveColor: [253, 231, 37]
  },
  red_blue: {
    sequentialStops: [
      [0, [30, 64, 175]],
      [0.3, [59, 130, 246]],
      [0.55, [191, 219, 254]],
      [0.8, [248, 113, 113]],
      [1, [185, 28, 28]]
    ],
    negativeColor: [59, 130, 246],
    positiveColor: [220, 38, 38]
  },
  teal_amber: {
    sequentialStops: [
      [0, [17, 94, 89]],
      [0.28, [20, 184, 166]],
      [0.55, [153, 246, 228]],
      [0.78, [251, 191, 36]],
      [1, [180, 83, 9]]
    ],
    negativeColor: [20, 184, 166],
    positiveColor: [245, 158, 11]
  }
}

export function interpolateColor(low: number[], high: number[], t: number) {
  const mix = (a: number, b: number) => Math.round(a + (b - a) * t)
  return `rgb(${mix(low[0], high[0])}, ${mix(low[1], high[1])}, ${mix(low[2], high[2])})`
}

function interpolateRgbaColor(low: number[], high: number[], t: number, alpha = 0.96) {
  const mix = (a: number, b: number) => Math.round(a + (b - a) * t)
  return `rgba(${mix(low[0], high[0])}, ${mix(low[1], high[1])}, ${mix(low[2], high[2])}, ${alpha})`
}

function interpolateScaleColor(stops: Array<[number, number[]]>, t: number) {
  const clamped = clamp(t, 0, 1)

  for (let index = 1; index < stops.length; index += 1) {
    const [nextStop, nextColor] = stops[index]
    if (clamped > nextStop) continue

    const [prevStop, prevColor] = stops[index - 1]
    const localT =
      nextStop > prevStop ? (clamped - prevStop) / (nextStop - prevStop) : 0

    return [
      Math.round(prevColor[0] + (nextColor[0] - prevColor[0]) * localT),
      Math.round(prevColor[1] + (nextColor[1] - prevColor[1]) * localT),
      Math.round(prevColor[2] + (nextColor[2] - prevColor[2]) * localT)
    ]
  }

  return stops[stops.length - 1][1]
}

function getHeatmapPaletteDefinition(palette: VolGridHeatmapPalette) {
  return HEATMAP_PALETTE_DEFINITIONS[palette] ?? HEATMAP_PALETTE_DEFINITIONS.icefire
}

export function getHeatColor(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  return interpolateColor([30, 64, 175], [245, 158, 11], clamp(ratio, 0, 1))
}

export function getChangeColor(value: number, maxAbs: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  const ratio = maxAbs > 0 ? Math.abs(value) / maxAbs : 0
  const base = value >= 0 ? [239, 68, 68] : [34, 197, 94]
  return interpolateColor([30, 41, 59], base, clamp(ratio, 0, 1))
}

export function getConfidenceColor(value: number) {
  if (!Number.isFinite(value)) return 'rgba(15, 23, 42, 0.8)'
  return interpolateColor([30, 41, 59], [14, 165, 233], clamp(value / 100, 0, 1))
}

function getSequentialHeatmapColor(
  value: number | null,
  min: number,
  max: number,
  stops: Array<[number, number[]]>,
  inverted: boolean
) {
  if (value === null || !Number.isFinite(value)) return NEUTRAL_CELL_BACKGROUND
  const ratio = max > min ? (value - min) / (max - min) : 0.5
  const color = interpolateScaleColor(stops, inverted ? 1 - ratio : ratio)
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, 0.96)`
}

function getDivergingHeatmapColor(
  value: number | null,
  maxAbs: number,
  negativeColor: number[],
  positiveColor: number[],
  inverted: boolean
) {
  if (value === null || !Number.isFinite(value)) return NEUTRAL_CELL_BACKGROUND
  const ratio = maxAbs > 0 ? Math.abs(value) / maxAbs : 0
  const t = clamp(ratio, 0, 1)
  const accentColor =
    value >= 0
      ? inverted
        ? negativeColor
        : positiveColor
      : inverted
        ? positiveColor
        : negativeColor
  return interpolateRgbaColor([15, 23, 42], accentColor, t)
}

export function getUnifiedCellBackground(
  cell: VolGridCell,
  heatmap: VolGridHeatmapConfig,
  range: VolGridHeatmapRange,
  highlightedNodeKeys: ReadonlySet<string> = new Set()
) {
  const palette = getHeatmapPaletteDefinition(heatmap.palette)

  switch (heatmap.strategy) {
    case 'none':
      return NEUTRAL_CELL_BACKGROUND
    case 'absolute':
      return heatmap.metric === 'premium'
        ? getSequentialHeatmapColor(
            cell.atmfPremiumBps,
            range.premiumMin,
            range.premiumMax,
            palette.sequentialStops,
            heatmap.inverted
          )
        : getSequentialHeatmapColor(
            cell.atmfVol,
            range.volMin,
            range.volMax,
            palette.sequentialStops,
            heatmap.inverted
          )
    case 'delta':
      return heatmap.metric === 'premium'
        ? getDivergingHeatmapColor(
            cell.atmfPremiumBpsChange,
            range.premiumChangeMaxAbs,
            palette.negativeColor,
            palette.positiveColor,
            heatmap.inverted
          )
        : getDivergingHeatmapColor(
            cell.atmfVolChange,
            range.volChangeMaxAbs,
            palette.negativeColor,
            palette.positiveColor,
            heatmap.inverted
          )
    case 'custom': {
      if (!highlightedNodeKeys.size) return NEUTRAL_CELL_BACKGROUND
      const isTargeted = highlightedNodeKeys.has(cell.nodeKey)
      const shouldHighlight = heatmap.inverted ? !isTargeted : isTargeted
      const highlightColor = heatmap.inverted ? palette.negativeColor : palette.positiveColor
      return shouldHighlight
        ? `rgba(${highlightColor[0]}, ${highlightColor[1]}, ${highlightColor[2]}, 0.28)`
        : 'rgba(10, 17, 30, 0.86)'
    }
    default:
      return NEUTRAL_CELL_BACKGROUND
  }
}
