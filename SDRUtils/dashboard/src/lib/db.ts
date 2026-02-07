// ABOUTME: PostgreSQL connection pool for Supabase with PgBouncer. Exports query function with automatic connection management.
import { Pool, QueryResult, QueryResultRow } from 'pg'

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 20,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 10000,
})

export async function query<T extends QueryResultRow = QueryResultRow>(
  text: string,
  params?: unknown[],
): Promise<QueryResult<T>> {
  const client = await pool.connect()
  try {
    return await client.query<T>(text, params)
  } finally {
    client.release()
  }
}

export default pool
