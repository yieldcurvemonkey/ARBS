// ABOUTME: Pure-logic helpers for the TimestampColumnFilter. Split from the
// component so Jest can exercise the match logic without dragging in JSX
// (ts-jest runs with `jsx: preserve`, which rejects .tsx at parse time).

export type TimestampRange = [string | null, string | null] | null

/**
 * Compare a row's execution timestamp (ISO string) against a
 * from/to time-of-day tuple. Returns true if the row's time falls inside
 * the closed range; either endpoint can be null for open-ended filtering.
 */
export function matchTimestampRange(
  isoTimestamp: string | null | undefined,
  range: TimestampRange,
): boolean {
  if (!range) return true
  const [from, to] = range
  if (!from && !to) return true
  if (!isoTimestamp) return false
  const d = new Date(isoTimestamp)
  if (Number.isNaN(d.getTime())) return false
  const rowTime = `${String(d.getUTCHours()).padStart(2, '0')}:${String(
    d.getUTCMinutes(),
  ).padStart(2, '0')}:${String(d.getUTCSeconds()).padStart(2, '0')}`
  if (from && rowTime < from) return false
  if (to && rowTime > to) return false
  return true
}
