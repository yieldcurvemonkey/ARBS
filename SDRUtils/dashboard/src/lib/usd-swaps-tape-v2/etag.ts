// ABOUTME: ETag computation + If-None-Match matching for analytics
// routes. Computes a sha-1 of the JSON-serialised payload; wraps in
// HTTP-quoted form. Strong validators only (no W/ weak ETags).

import { createHash } from 'node:crypto'

export function computeEtag(payload: unknown): string {
  const sha = createHash('sha1').update(JSON.stringify(payload)).digest('hex')
  return `"${sha}"`
}

export function matchesIfNoneMatch(
  etag: string,
  ifNoneMatch: string | null,
): boolean {
  if (!ifNoneMatch) return false
  const trimmed = ifNoneMatch.trim()
  if (trimmed === '*') return true
  return trimmed
    .split(',')
    .map((s) => s.trim())
    .includes(etag)
}
