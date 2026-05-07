import { Pool, type PoolClient, type QueryResult, type QueryResultRow } from 'pg'

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
