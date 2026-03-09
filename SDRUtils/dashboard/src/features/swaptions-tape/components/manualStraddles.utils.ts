export type ManualStraddleSelectionRow = {
  package_id: string
  package_type: string | null
  assumed_incomplete_straddle?: boolean
}

function normalizePackageType(type: string | null): string {
  if (!type) return ''
  return type.replace(/-/g, '_').toUpperCase()
}

function normalizeSelectedPackageIds(
  ids: Array<string | null | undefined>
): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []

  ids.forEach((entry) => {
    const value = typeof entry === 'string' ? entry.trim() : ''
    if (!value || seen.has(value)) return
    seen.add(value)
    normalized.push(value)
  })

  return normalized
}

export function getSelectedForceableStraddleIds(
  rows: ManualStraddleSelectionRow[],
  selectedPackageIds: string[]
): string[] {
  if (!selectedPackageIds.length) return []

  const selectedIdSet = new Set(selectedPackageIds)
  return normalizeSelectedPackageIds(
    rows
      .filter((row) => selectedIdSet.has(row.package_id))
      .filter((row) => {
        const packageType = normalizePackageType(row.package_type)
        return packageType === 'OUTRIGHT' && !row.assumed_incomplete_straddle
      })
      .map((row) => row.package_id)
  )
}

export function getSelectedUndoableStraddleIds(
  rows: ManualStraddleSelectionRow[],
  selectedPackageIds: string[],
  forcedPackageIds: ReadonlySet<string>
): string[] {
  if (!selectedPackageIds.length || !forcedPackageIds.size) return []

  const selectedIdSet = new Set(selectedPackageIds)
  return normalizeSelectedPackageIds(
    rows
      .filter((row) => selectedIdSet.has(row.package_id))
      .filter(
        (row) =>
          forcedPackageIds.has(row.package_id) && !!row.assumed_incomplete_straddle
      )
      .map((row) => row.package_id)
  )
}
