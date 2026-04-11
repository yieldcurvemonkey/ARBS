export function normalizeStirFilterOperator(
  value: string | null | undefined
): 'and' | 'or' {
  return value?.toLowerCase() === 'or' ? 'or' : 'and'
}

export function parseIsoDate(
  value: string | null | undefined
): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

export function parseCsvList(value: string | null | undefined): string[] {
  if (!value) return []
  return value
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean)
}
