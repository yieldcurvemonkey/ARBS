// ABOUTME: PostgreSQL connection pool and query helper for API routes
import { Pool, QueryResult } from 'pg'

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
})

export async function query(
  text: string,
  params?: unknown[]
): Promise<QueryResult> {
  return pool.query(text, params)
}

export default pool
