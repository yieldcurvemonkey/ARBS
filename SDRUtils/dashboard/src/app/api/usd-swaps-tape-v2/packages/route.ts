// ABOUTME: GET /api/usd-swaps-tape-v2/packages — package-summary sidecar.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'

const SORTABLE = {
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

export async function GET(req: Request) {
  const url = new URL(req.url)
  const date = url.searchParams.get('date') ?? new Date().toISOString().slice(0, 10)
  const rawSort = url.searchParams.get('sortBy') ?? 'risk'
  if (!(rawSort in SORTABLE)) {
    return NextResponse.json({ error: `invalid sortBy: ${rawSort}` }, { status: 400 })
  }
  const rawLimit = Number(url.searchParams.get('limit') ?? 100)
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(Math.floor(rawLimit), 500) : 100
  try {
    const result = await query(buildPackagesSql(rawSort as PackagesSortBy, limit), [date])
    return NextResponse.json({ packages: result.rows })
  } catch (error: any) {
    return NextResponse.json({ error: error?.message ?? 'failed' }, { status: 500 })
  }
}
