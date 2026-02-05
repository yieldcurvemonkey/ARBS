// Database connection module for PostgreSQL.
// Wraps the 'pg' package with a shared connection pool.

import { Pool, QueryResult } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
});

/**
 * Execute a parameterized SQL query against the shared connection pool.
 */
export async function query(
  text: string,
  params?: unknown[],
): Promise<QueryResult> {
  return pool.query(text, params);
}

export default pool;
