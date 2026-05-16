// ABOUTME: Maps FOMC constant-maturity aliases (FOMC1, FOMC2, ...) to
// absolute meeting labels (JUN26, SEP26, ...) based on a hardcoded
// schedule of upcoming FOMC meetings. Used by FomcStripView to show
// rolling "next meeting" labels that auto-advance as dates pass.

const FOMC_MONTHS: ReadonlyArray<[number, number]> = [
  [2024, 0], [2024, 2], [2024, 4], [2024, 6], [2024, 8], [2024, 10],
  [2025, 0], [2025, 2], [2025, 4], [2025, 6], [2025, 8], [2025, 11],
  [2026, 0], [2026, 2], [2026, 4], [2026, 5], [2026, 8], [2026, 10],
  [2027, 0], [2027, 2], [2027, 4], [2027, 5], [2027, 8], [2027, 10],
]

const MONTH_LABELS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

function fomcLabelFromYearMonth(year: number, monthIdx: number): string {
  const yy = String(year % 100).padStart(2, '0')
  return `${MONTH_LABELS[monthIdx]}${yy}`
}

export function buildFomcConstantMaturityMap(now: Date = new Date()): Map<string, string> {
  const result = new Map<string, string>()
  const upcoming = FOMC_MONTHS
    .map(([y, m]) => ({ label: fomcLabelFromYearMonth(y, m), date: new Date(Date.UTC(y, m, 15)) }))
    .filter((x) => x.date.getTime() > now.getTime())
    .sort((a, b) => a.date.getTime() - b.date.getTime())

  for (let i = 0; i < upcoming.length; i++) {
    result.set(`FOMC${i + 1}`, upcoming[i].label)
  }
  return result
}

export function fomcAliasForLabel(label: string, map: Map<string, string>): string | null {
  for (const [alias, absLabel] of map) {
    if (absLabel === label) return alias
  }
  return null
}
