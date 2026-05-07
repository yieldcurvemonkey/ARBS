import {
  normalizeAnalyticsTapeLabel,
  __analyticsLifecycleFlagTokens as LIFECYCLE_TOKENS,
} from '@/lib/usd-swaps-tape-v2/analytics'

export function parseBooleanParam(
  searchParams: URLSearchParams,
  key: string,
  defaultValue: boolean,
): boolean {
  const raw = searchParams.get(key)
  if (raw == null) return defaultValue
  const normalized = raw.trim().toLowerCase()
  if (['true', '1', 'yes', 'y'].includes(normalized)) return true
  if (['false', '0', 'no', 'n'].includes(normalized)) return false
  return defaultValue
}

export function riskAggregateExpression(useGrossDv01: boolean): string {
  return useGrossDv01 ? 'SUM(ABS(risk))' : 'SUM(risk)'
}

export function custyNotionalOutlierPredicate(
  rowAlias: string,
  thresholdAlias: string,
  excludeLargeCusty: boolean,
): string {
  if (!excludeLargeCusty) return 'TRUE'
  return `NOT (
            ${rowAlias}.platform = 'CUSTY'
            AND ${thresholdAlias}.median_notional IS NOT NULL
            AND ${thresholdAlias}.median_notional > 0
            AND ABS(COALESCE(${rowAlias}.notional, 0)) > ${thresholdAlias}.median_notional * 5
          )`
}

function compactUpperLabel(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toUpperCase()
}

function addSofrOisCompoundVariants(
  candidates: Set<string>,
  value: string,
): void {
  const compact = compactUpperLabel(value)
  candidates.add(compact)
  if (compact.startsWith('USD-SOFR-COMPOUND ')) {
    candidates.add(compact.replace(/^USD-SOFR-COMPOUND/, 'USD-SOFR-OIS COMPOUND'))
  }
  if (compact.startsWith('USD-SOFR-OIS COMPOUND ')) {
    candidates.add(compact.replace(/^USD-SOFR-OIS COMPOUND/, 'USD-SOFR-COMPOUND'))
  }
}

export function buildOutrightTapeLabelCandidates(value: string): string[] {
  const candidates = new Set<string>()
  addSofrOisCompoundVariants(candidates, value)
  addSofrOisCompoundVariants(candidates, normalizeAnalyticsTapeLabel(value))
  return [...candidates].filter((candidate) => candidate.length > 0)
}

export function isOutrightTapeLabelCandidate(value: string): boolean {
  const label = ` ${compactUpperLabel(value)} `
  return (
    label.includes(' OUTRIGHT ') &&
    !/( CURVE | FLY | MMS | PACKAGE | SPREAD )/.test(label)
  )
}

export function buildTapeLabelCandidates(value: string): string[] {
  const candidates = new Set<string>()
  addSofrOisCompoundVariants(candidates, value)
  addSofrOisCompoundVariants(candidates, normalizeAnalyticsTapeLabel(value))
  for (const token of LIFECYCLE_TOKENS) {
    const withToken = compactUpperLabel(value) + ' ' + token
    addSofrOisCompoundVariants(candidates, withToken)
    const normalized = normalizeAnalyticsTapeLabel(value)
    addSofrOisCompoundVariants(candidates, normalized + ' ' + token)
  }
  const raw = compactUpperLabel(value)
  candidates.add(raw.replace(/\bPHYS\b/g, 'PHY'))
  candidates.add(raw.replace(/\bPHYS\b/g, 'PHYSICAL'))
  return [...candidates].filter((c) => c.length > 0)
}
