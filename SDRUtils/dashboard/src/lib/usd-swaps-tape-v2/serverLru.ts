// ABOUTME: Tiny per-route in-memory LRU with TTL. Used by USD swaps
// tape v2 analytics routes to memoise warehouse aggregations within a
// short window so that a focused-row toggle returning to a recently-
// viewed bucket reuses the prior response.

type Entry<V> = { value: V; expiresAt: number }

export interface ServerLruOptions {
  max: number
  ttlMs: number
}

export class ServerLru<V> {
  private map = new Map<string, Entry<V>>()
  constructor(private opts: ServerLruOptions) {}

  get(key: string): V | undefined {
    const entry = this.map.get(key)
    if (!entry) return undefined
    if (entry.expiresAt < Date.now()) {
      this.map.delete(key)
      return undefined
    }
    // Promote on hit (LRU semantics)
    this.map.delete(key)
    this.map.set(key, entry)
    return entry.value
  }

  set(key: string, value: V): void {
    if (this.map.has(key)) this.map.delete(key)
    this.map.set(key, { value, expiresAt: Date.now() + this.opts.ttlMs })
    while (this.map.size > this.opts.max) {
      const oldest = this.map.keys().next().value
      if (oldest === undefined) break
      this.map.delete(oldest)
    }
  }

  size(): number {
    return this.map.size
  }

  clear(): void {
    this.map.clear()
  }
}
