import { Pool, type QueryResult, type QueryResultRow } from 'pg'

const pool = new Pool({
  connectionString:
    process.env.SWAPPULSE_DATABASE_URL ||
    process.env.DATABASE_URL ||
    undefined,
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 10000
})

export async function query<T extends QueryResultRow = QueryResultRow>(
  text: string,
  params?: unknown[]
): Promise<QueryResult<T>> {
  return pool.query<T>(text, params)
}

export { pool }
