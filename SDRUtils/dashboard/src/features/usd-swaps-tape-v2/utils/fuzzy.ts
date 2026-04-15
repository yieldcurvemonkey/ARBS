// ABOUTME: Fuzzy subsequence matcher for the USD swap tape client-side filter.
// Adapted from features/ustf-vol/utils.ts scoreNormalizedQuery.

function normalize(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').trim()
}

export function fuzzyScore(query: string, candidate: string): number {
  const q = normalize(query)
  const c = normalize(candidate)
  if (!q) return 0
  if (!c) return -1

  if (q === c) return 1200 - c.length
  if (c.startsWith(q)) return 900 - (c.length - q.length)
  const idx = c.indexOf(q)
  if (idx >= 0) return 700 - idx * 4 - (c.length - q.length)

  let qi = 0
  let score = 0
  let streak = 0
  for (let ci = 0; ci < c.length; ci += 1) {
    if (c[ci] === q[qi]) {
      qi += 1
      streak += 1
      score += 14 + streak * 6
      if (qi === q.length) return 360 + score - c.length
    } else {
      streak = 0
    }
  }
  return -1
}

export function fuzzyMatches(query: string, candidate: string): boolean {
  return fuzzyScore(query, candidate) >= 0
}

// Score a row against fuzzy query by picking the best across candidate fields.
export function fuzzyBestScore(query: string, fields: Array<string | null | undefined>): number {
  if (!query) return 0
  let best = -1
  for (const f of fields) {
    if (typeof f !== 'string' || !f) continue
    const s = fuzzyScore(query, f)
    if (s > best) best = s
  }
  return best
}
