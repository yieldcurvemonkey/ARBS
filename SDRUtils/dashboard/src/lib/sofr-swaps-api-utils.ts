export type SofrSeriesKeyParseResult = {
  tenorLabel: string | null
  forwardLabel: string | null
  tenorYears: number | null
  forwardYears: number | null
  isValid: boolean
}

export type SofrColumnFilterConstraint = {
  value?: unknown
  matchMode?: string
}

export type SofrColumnFilterMeta = {
  operator?: string
  constraints?: SofrColumnFilterConstraint[]
  value?: unknown
  matchMode?: string
}

export type SofrColumnFilterPayload = Record<string, SofrColumnFilterMeta>

function parseDurationYears(token: string): number | null {
  const match = token.match(/^(\d+(?:\.\d+)?)([DWMY])$/i)
  if (!match) return null
  const magnitude = Number(match[1])
  if (!Number.isFinite(magnitude)) return null
  const unit = match[2].toUpperCase()
  if (unit === 'D') return magnitude / 365
  if (unit === 'W') return (magnitude * 7) / 365
  if (unit === 'M') return magnitude / 12
  if (unit === 'Y') return magnitude
  return null
}

export function parseSeriesKey(seriesKey: string): SofrSeriesKeyParseResult {
  const normalized = seriesKey.trim()
  const tenorMatch = normalized.match(
    /^(\d+(?:\.\d+)?[DWMY])[xX](\d+(?:\.\d+)?[DWMY])$/i
  )
  if (!tenorMatch) {
    return {
      tenorLabel: null,
      forwardLabel: null,
      tenorYears: null,
      forwardYears: null,
      isValid: false
    }
  }
  const forwardLabel = tenorMatch[1].toUpperCase()
  const tenorLabel = tenorMatch[2].toUpperCase()
  const forwardYears = parseDurationYears(forwardLabel)
  const tenorYears = parseDurationYears(tenorLabel)
  return {
    forwardLabel,
    tenorLabel,
    forwardYears,
    tenorYears,
    isValid: forwardYears !== null && tenorYears !== null
  }
}

export function normalizeFilterOperator(value: string | null | undefined) {
  return value?.toLowerCase() === 'or' ? 'or' : 'and'
}

export function parseColumnFilters(rawValue: string | null): SofrColumnFilterPayload {
  if (!rawValue) return {}
  try {
    const parsed = JSON.parse(rawValue) as SofrColumnFilterPayload
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed
  } catch {
    return {}
  }
}
