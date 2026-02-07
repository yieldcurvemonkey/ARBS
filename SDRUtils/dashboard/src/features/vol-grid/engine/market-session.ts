// ABOUTME: Market session detection for USD swaptions.
// Determines if the market is currently open, and computes the last trading
// session window for weekend/after-hours lookback queries.

// US swaption market hours (Eastern Time)
const MARKET_OPEN_HOUR = 7    // 7:00 AM ET
const MARKET_CLOSE_HOUR = 17  // 5:00 PM ET

export type MarketSessionStatus = 'open' | 'pre_market' | 'after_hours' | 'weekend' | 'holiday'

export type MarketSession = {
  status: MarketSessionStatus
  isMarketOpen: boolean
  /** The trading date this grid represents (e.g. "2026-02-06" on Sat shows Friday) */
  tradingDate: string
  /** Human-readable label: "Live — Feb 6" or "Fri Feb 6 Close" */
  sessionLabel: string
  /** Start of the relevant trading session (epoch ms) */
  sessionStart: number
  /** End of the relevant trading session (epoch ms) */
  sessionEnd: number
  /** Minutes to look back from NOW to capture the relevant session's trades */
  lookbackMinutes: number
  /** Whether polling should be active */
  shouldPoll: boolean
  /** The reference time for staleness: session close time when closed, now when open */
  stalenessReferenceTime: number
}

/**
 * Get current time in Eastern timezone components.
 */
function getEasternTime(now: Date = new Date()): {
  year: number; month: number; day: number; hour: number; minute: number;
  dayOfWeek: number; dateStr: string; formatted: string
} {
  // Use Intl to get ET components
  const etParts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
    weekday: 'short',
  }).formatToParts(now)

  const get = (type: string) => etParts.find(p => p.type === type)?.value || ''
  const year = parseInt(get('year'))
  const month = parseInt(get('month'))
  const day = parseInt(get('day'))
  const hour = parseInt(get('hour'))
  const minute = parseInt(get('minute'))
  const weekdayStr = get('weekday')

  const dayOfWeekMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 }
  const dayOfWeek = dayOfWeekMap[weekdayStr] ?? now.getDay()
  const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`

  const monthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const formatted = `${dayNames[dayOfWeek]} ${monthNames[month]} ${day}`

  return { year, month, day, hour, minute, dayOfWeek, dateStr, formatted }
}

/**
 * Build a Date object for a specific ET time on a given date.
 * Approximation using UTC offset — sufficient for session boundary detection.
 */
function etToEpoch(year: number, month: number, day: number, hour: number, minute: number = 0): number {
  // Approximate ET as UTC-5 (EST) or UTC-4 (EDT).
  // For session boundary purposes, a 1-hour error is acceptable.
  // We use the JS Date constructor with a formatted string to let the engine handle DST.
  const iso = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00`
  // Create in UTC-5 as a baseline (EST). Off by 1h during EDT — acceptable for session windows.
  return new Date(iso + '-05:00').getTime()
}

/**
 * Step back from a date to the previous weekday.
 * Returns { year, month, day } of the previous business day.
 */
function previousWeekday(year: number, month: number, day: number, dayOfWeek: number): { year: number; month: number; day: number; dayOfWeek: number } {
  // Step back by days until we hit a weekday
  const d = new Date(Date.UTC(year, month - 1, day))
  let dow = dayOfWeek

  let steps = 0
  do {
    d.setUTCDate(d.getUTCDate() - 1)
    dow = (dow + 6) % 7 // step back one day of week
    steps++
  } while (dow === 0 || dow === 6) // skip Sunday(0) and Saturday(6)

  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    dayOfWeek: dow,
  }
}

/**
 * Compute the market session context for vol grid display.
 *
 * On weekdays during market hours → "open", show live data, poll
 * On weekdays before open → "pre_market", show previous close
 * On weekdays after close → "after_hours", show today's close
 * On weekends → "weekend", show Friday's close
 */
export function computeMarketSession(now: Date = new Date()): MarketSession {
  const et = getEasternTime(now)
  const nowMs = now.getTime()

  const isWeekend = et.dayOfWeek === 0 || et.dayOfWeek === 6
  const isBeforeOpen = !isWeekend && et.hour < MARKET_OPEN_HOUR
  const isAfterClose = !isWeekend && et.hour >= MARKET_CLOSE_HOUR
  const isOpen = !isWeekend && !isBeforeOpen && !isAfterClose

  if (isOpen) {
    // Market is open — show live data from today's session
    const sessionStart = etToEpoch(et.year, et.month, et.day, MARKET_OPEN_HOUR)
    const sessionEnd = etToEpoch(et.year, et.month, et.day, MARKET_CLOSE_HOUR)
    const lookbackMinutes = Math.ceil((nowMs - sessionStart) / 60_000) + 60 // buffer

    return {
      status: 'open',
      isMarketOpen: true,
      tradingDate: et.dateStr,
      sessionLabel: `Live \u2014 ${et.formatted}`,
      sessionStart,
      sessionEnd,
      lookbackMinutes: Math.max(lookbackMinutes, 120),
      shouldPoll: true,
      stalenessReferenceTime: nowMs,
    }
  }

  if (isWeekend || isBeforeOpen) {
    // Weekend or before market open — show last trading day's close
    let prev: { year: number; month: number; day: number; dayOfWeek: number }
    if (isBeforeOpen) {
      // Before today's open → show previous trading day
      prev = previousWeekday(et.year, et.month, et.day, et.dayOfWeek)
    } else {
      // Weekend → step back to Friday (or last weekday)
      prev = previousWeekday(et.year, et.month, et.day, et.dayOfWeek)
    }

    const sessionStart = etToEpoch(prev.year, prev.month, prev.day, MARKET_OPEN_HOUR)
    const sessionEnd = etToEpoch(prev.year, prev.month, prev.day, MARKET_CLOSE_HOUR)
    const lookbackMinutes = Math.ceil((nowMs - sessionStart) / 60_000) + 60

    const prevMonthNames = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    const prevDayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    const prevDateStr = `${prev.year}-${String(prev.month).padStart(2, '0')}-${String(prev.day).padStart(2, '0')}`
    const prevFormatted = `${prevDayNames[prev.dayOfWeek]} ${prevMonthNames[prev.month]} ${prev.day}`

    return {
      status: isWeekend ? 'weekend' : 'pre_market',
      isMarketOpen: false,
      tradingDate: prevDateStr,
      sessionLabel: `${prevFormatted} Close`,
      sessionStart,
      sessionEnd,
      lookbackMinutes,
      shouldPoll: false,
      stalenessReferenceTime: sessionEnd,
    }
  }

  // After market close — show today's session
  const sessionStart = etToEpoch(et.year, et.month, et.day, MARKET_OPEN_HOUR)
  const sessionEnd = etToEpoch(et.year, et.month, et.day, MARKET_CLOSE_HOUR)
  const lookbackMinutes = Math.ceil((nowMs - sessionStart) / 60_000) + 60

  return {
    status: 'after_hours',
    isMarketOpen: false,
    tradingDate: et.dateStr,
    sessionLabel: `${et.formatted} Close`,
    sessionStart,
    sessionEnd,
    lookbackMinutes,
    shouldPoll: false,
    stalenessReferenceTime: sessionEnd,
  }
}
