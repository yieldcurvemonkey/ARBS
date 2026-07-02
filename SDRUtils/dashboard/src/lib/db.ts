import { Pool, types, type PoolClient, type QueryResult, type QueryResultRow } from 'pg'

// pg returns NUMERIC (1700) and BIGINT (20) as strings by default. Every
// consumer in this app treats them as numbers (formatters wrap Number(),
// the tape table sorts on them — audit 2026-07-01 found lexicographic
// spread sorting). Values are money/risk quantities well inside 2^53.
types.setTypeParser(1700, (v: string) => (v === null ? null : parseFloat(v)))
types.setTypeParser(20, (v: string) => (v === null ? null : parseInt(v, 10)))

type DbPoolHolder = {
  __swapPulsePool?: Pool
}

const globalForDb = globalThis as typeof globalThis & DbPoolHolder

function resolveConnectionString(): string {
  if (process.env.DATABASE_URL) return process.env.DATABASE_URL
  // Mirror the Python SWAPPULSE_DB_* ladder used by the ingest scripts
  // so dev runs work without an explicit DATABASE_URL set.
  const host = process.env.SWAPPULSE_DB_HOST ?? 'aws-0-us-east-1.pooler.supabase.com'
  const port = process.env.SWAPPULSE_DB_PORT ?? '6543'
  const dbname = process.env.SWAPPULSE_DB_NAME ?? 'postgres'
  const user = process.env.SWAPPULSE_DB_USER ?? 'postgres.rdobtpugtnmefxplgwyp'
  const password = process.env.SWAPPULSE_DB_PASSWORD ?? '0rbZUh8y0Fsvdlry'
  return `postgresql://${user}:${password}@${host}:${port}/${dbname}`
}

function getPool() {
  if (!globalForDb.__swapPulsePool) {
    globalForDb.__swapPulsePool = new Pool({
      connectionString: resolveConnectionString(),
      max: 10,
      idleTimeoutMillis: 30_000,
      statement_timeout: 300_000,
    })
  }
  return globalForDb.__swapPulsePool
}

export async function query<T extends QueryResultRow = any>(
  text: string,
  params?: Array<unknown>
): Promise<QueryResult<T>> {
  const pool = getPool()
  return pool.query<T>(text, params)
}

export async function analyticsQuery<T extends QueryResultRow = any>(
  text: string,
  params?: Array<unknown>
): Promise<QueryResult<T>> {
  const pool = getPool()
  return pool.query<T>(text, params)
}

export async function withClient<T>(
  fn: (client: PoolClient) => Promise<T>
): Promise<T> {
  const pool = getPool()
  const client = await pool.connect()
  try {
    return await fn(client)
  } finally {
    client.release()
  }
}
