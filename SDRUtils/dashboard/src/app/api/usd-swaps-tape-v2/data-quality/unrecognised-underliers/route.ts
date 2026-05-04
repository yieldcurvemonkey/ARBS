// GET /api/usd-swaps-tape-v2/data-quality/unrecognised-underliers
// Daily watchdog (design-doc §5.19): every distinct
// floating_rate_index seen in the last `lookbackHours` whose
// canonical_underlier_key is UNKNOWN or outside the dashboard's
// CANONICAL_BUCKETS whitelist. Surfaces count + total notional + first/
// last-seen timestamps so the index normaliser drift is visible before
// downstream canonical-bucket analytics start lying quietly.
import { NextResponse } from 'next/server'
import { query } from '@/lib/db'
import {
  aggregateUnrecognisedUnderliers,
  type UnrecognisedRow,
} from './route.logic'

const LEGS_TABLE = 'arbs_usd_swap_tape_legs_v2'
const DEFAULT_LOOKBACK_HOURS = 24
const MAX_LOOKBACK_HOURS = 24 * 30 // 30 days hard cap

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url)
  const lookbackRaw = Number(searchParams.get('lookbackHours') ?? DEFAULT_LOOKBACK_HOURS)
  const lookback = Number.isFinite(lookbackRaw) && lookbackRaw > 0
    ? Math.min(lookbackRaw, MAX_LOOKBACK_HOURS)
    : DEFAULT_LOOKBACK_HOURS
  const cutoff = new Date(Date.now() - lookback * 3600 * 1000).toISOString()

  try {
    const sql = `
      SELECT
        l.floating_rate_index AS floating_rate_index,
        l.canonical_underlier_key AS canonical_underlier_key,
        l.notional::float AS notional,
        COALESCE(l.original_execution_timestamp, l.execution_timestamp)::text AS execution_timestamp
      FROM ${LEGS_TABLE} l
      WHERE COALESCE(l.original_execution_timestamp, l.execution_timestamp) >= $1::timestamptz
    `
    const result = await query<UnrecognisedRow>(sql, [cutoff])
    const aggregates = aggregateUnrecognisedUnderliers(result.rows)
    return NextResponse.json({
      lookbackHours: lookback,
      cutoff,
      totalDistinct: aggregates.length,
      items: aggregates,
    })
  } catch (error) {
    console.error('usd-swaps-tape-v2/data-quality/unrecognised-underliers error', error)
    const message =
      error instanceof Error ? error.message : 'Failed to fetch unrecognised-underliers'
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
