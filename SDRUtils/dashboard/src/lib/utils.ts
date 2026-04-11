type ClassDictionary = Record<string, boolean | undefined | null>
type ClassValue =
  | string
  | number
  | null
  | undefined
  | false
  | ClassDictionary
  | ClassValue[]

function toClassName(value: ClassValue, acc: string[]) {
  if (!value) return
  if (typeof value === 'string' || typeof value === 'number') {
    acc.push(String(value))
    return
  }
  if (Array.isArray(value)) {
    value.forEach((item) => toClassName(item, acc))
    return
  }
  if (typeof value === 'object') {
    Object.entries(value).forEach(([key, enabled]) => {
      if (enabled) acc.push(key)
    })
  }
}

export function cn(...inputs: ClassValue[]) {
  const classes: string[] = []
  inputs.forEach((input) => toClassName(input, classes))
  return classes.join(' ')
}

export const SIMPLE_ADMIN_PASSWORD = 'admin'
export const SIMPLE_ADMIN_AUTH_ERROR = 'Invalid admin password.'

export function normalizeSimpleAdminPassword(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}

export function isValidSimpleAdminPassword(value: unknown): boolean {
  return normalizeSimpleAdminPassword(value) === SIMPLE_ADMIN_PASSWORD
}
