import { Pool, type PoolClient, type QueryResult, type QueryResultRow } from 'pg'

type DbPoolHolder = {
  __swapPulsePool?: Pool
}

const globalForDb = globalThis as typeof globalThis & DbPoolHolder

function getPool() {
  if (!globalForDb.__swapPulsePool) {
    const connectionString = process.env.DATABASE_URL
    if (!connectionString) {
      throw new Error('DATABASE_URL is not set')
    }
    globalForDb.__swapPulsePool = new Pool({
      connectionString,
      max: 10,
      idleTimeoutMillis: 30_000
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
