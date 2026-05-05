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
