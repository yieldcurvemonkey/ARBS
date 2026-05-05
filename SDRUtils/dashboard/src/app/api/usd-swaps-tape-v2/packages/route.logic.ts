export const SORTABLE = {
  risk: 'ABS(total_risk) DESC NULLS LAST',
  notional: 'ABS(total_notional) DESC NULLS LAST',
  time: 'execution_start DESC',
  legs: 'n_package_legs DESC',
} as const

export type PackagesSortBy = keyof typeof SORTABLE

export function buildPackagesSql(sortBy: PackagesSortBy, limit: number): string {
  return `
    SELECT package_id, package_structure, package_type, n_package_legs,
           legs_count, total_risk, total_notional, rate_index_clean,
           venue, ccp, tape_label, execution_start, cluster_id
    FROM arbs_usd_swap_tape_packages_v1
    WHERE as_of_date = $1::date
      AND package_type != 'OUTRIGHT'
    ORDER BY ${SORTABLE[sortBy]}
    LIMIT ${limit}
  `
}
