// Number / time / tenor formatters for the USD swap tape v2 UI.
import { EMPTY_VALUE } from '../constants'
import type { UsdSwapTapeLeg, UsdSwapTapeRow } from '../types'
import { sortLegsForDisplay } from './legSort'

const COMPACT_UNITS: [number, string][] = [
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'K'],
]

// Headline ladder: the round DV01 / notional sizes traders actually
// quote. Scaled compact values that fall within HEADLINE_SNAP_TOLERANCE
// of a ladder entry are snapped onto it (49.9K -> 50K, 24.9K -> 25K,
// 72K -> 75K). Values that aren't close to any ladder entry round to
// integer instead so odd sizes like 35K / 46K stay legible.
const HEADLINE_LADDER: number[] = [
  1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10, 15, 20, 25, 30, 40, 50, 75,
  100, 150, 200, 250, 300, 400, 500, 750,
]
const HEADLINE_SNAP_TOLERANCE = 0.05

function isNullish(n: number | null | undefined): n is null | undefined {
  return n === null || n === undefined || Number.isNaN(n)
}

function snapToHeadlineLadder(scaled: number): number {
  // Returns the scaled value with the sign preserved, snapped to the
  // nearest ladder entry iff within tolerance; otherwise integer-rounded.
  const abs = Math.abs(scaled)
  let bestEntry = abs
  let bestDiff = Number.POSITIVE_INFINITY
  for (const entry of HEADLINE_LADDER) {
    const rel = Math.abs(abs - entry) / entry
    if (rel < bestDiff) {
      bestDiff = rel
      bestEntry = entry
    }
  }
  const chosen = bestDiff <= HEADLINE_SNAP_TOLERANCE ? bestEntry : Math.round(abs)
  return scaled < 0 ? -chosen : chosen
}

export function formatNotional(
  n: number | null | undefined,
  opts: { compact?: boolean; headline?: boolean } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  if (!opts.compact) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  }
  for (const [threshold, suffix] of COMPACT_UNITS) {
    if (Math.abs(value) >= threshold) {
      const scaled = value / threshold
      // "headline" mode snaps to the desk's round-size ladder
      // (49.9K -> "50K", 24.9K -> "25K", 72K -> "75K") and falls back to
      // integer rounding for values that aren't close to any ladder
      // entry. Default (non-headline) keeps the legacy 1-decimal render
      // for mid-range values so notional still shows meaningful precision
      // (e.g. 1.5M vs 1.6M).
      if (opts.headline) {
        const snapped = snapToHeadlineLadder(scaled)
        const snappedAbs = Math.abs(snapped)
        const precision = snappedAbs >= 100 || Number.isInteger(snappedAbs) ? 0 : 1
        const formatted = snapped.toFixed(precision).replace(/\.0+$/, '')
        return `${formatted}${suffix}`
      }
      const precision = Math.abs(scaled) >= 100 ? 0 : 1
      const formatted = scaled.toFixed(precision).replace(/\.0+$/, '')
      return `${formatted}${suffix}`
    }
  }
  return value.toFixed(0)
}

export function formatDv01(
  n: number | null | undefined,
  opts: { signed?: boolean; signNegativeOnly?: boolean } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  const abs = Math.abs(value)
  // RISK headline rounding: snap scaled compact values to integers so the
  // RISK column reads as traders quote it (49.9K -> 50K, 9.8K -> 10K).
  const formatted = formatNotional(abs, { compact: true, headline: true })
  if (opts.signNegativeOnly) {
    if (value < 0) return `\u2212${formatted}`
    return formatted
  }
  if (!opts.signed) return formatted
  if (value < 0) return `\u2212${formatted}`
  if (value > 0) return `+${formatted}`
  return formatted
}

export function formatRate(
  n: number | null | undefined,
  opts: { precision?: number } = {},
): string {
  if (isNullish(n)) return EMPTY_VALUE
  const value = Number(n)
  const precision = opts.precision ?? 3
  return `${(value * 100).toFixed(precision)}%`
}

export function formatRateRange(
  min: number | null | undefined,
  max: number | null | undefined,
): string {
  if (isNullish(min) && isNullish(max)) return EMPTY_VALUE
  if (isNullish(min)) return formatRate(max)
  if (isNullish(max)) return formatRate(min)
  if (Math.abs(Number(min) - Number(max)) < 1e-9) return formatRate(min)
  return `${formatRate(min)} – ${formatRate(max)}`
}

function formatSpreadBps(n: number): string {
  const bps = Number(n)
  if (Number.isNaN(bps)) return EMPTY_VALUE
  return `${bps.toFixed(1)}bp`
}

/**
 * Render the "Reported LvL" cell value.
 *
 * For CURVE and FLY packages, every leg has its own reported fixed rate
 * and the desk wants both surfaced inline:
 *
 *   CURVE  ->  "3.622% / 3.827%"
 *   FLY    ->  "3.622% / 3.800% / 4.100%"
 *
 * For BASIS swap types, the raw SDR "Spread-Leg 1" / "Spread-Leg 2"
 * fields (stored as ``basis_spread_bps`` per leg) are displayed instead
 * of fixed_rate, since the spread is the economically meaningful level
 * for basis trades.
 *
 * For every other trade type (OUTRIGHT / INVOICE / SPREADOVER / MAC / …)
 * the cell falls back to the package-level weighted_fixed_rate.
 *
 * If a CURVE/FLY row is missing per-leg rates (e.g. <2 legs populated or
 * all fixed_rate values are null), the weighted_fixed_rate is used as a
 * safety net so the cell never renders the empty marker just because a
 * leg came through without a rate.
 */
export function formatReportedLvl(row: UsdSwapTapeRow): string {
  // The tape display view only selects ``package_type`` — the row-level
  // ``trade_type`` column is not projected for aggregated package rows,
  // so ``row.trade_type`` is typically undefined on the main tape. Prefer
  // ``package_type`` and fall back to ``trade_type`` only as a backstop.
  const kind = String(row.package_type ?? row.trade_type ?? '').toUpperCase()

  // Typed as UsdSwapTapeLeg[] so the USD-specific per-leg fields
  // (basis_type / basis_spread_bps / ust_*) resolve — row.legs_json widens to
  // the base SofrSwapTapeLeg in .some() callbacks otherwise.
  const legsAll: UsdSwapTapeLeg[] = row.legs_json ?? []
  // Basis swaps are detected per-leg (basis_type / basis_spread_bps) — the
  // package_type is often plain OUTRIGHT for a single basis print, so the
  // per-leg fields are the authoritative signal for the spread render.
  const isBasis =
    kind === 'BASIS' ||
    kind === 'BASIS_SWAP' ||
    kind === 'BASIS_CURVE' ||
    kind === 'BASIS_FLY' ||
    kind === 'BASIS_HEDGE' ||
    legsAll.some(
      (l) =>
        l?.basis_type != null ||
        !isNullish(l?.basis_spread_bps),
    )
  if (isBasis) {
    const spreads = sortLegsForDisplay(legsAll)
      .map((l) => l?.basis_spread_bps)
      .filter((s): s is number => !isNullish(s as number | null | undefined))
    if (spreads.length >= 1) {
      return spreads.map((s) => formatSpreadBps(s)).join(' / ')
    }
  }

  // Composite types from the sub-package detector (e.g. SPREADOVER_CURVE,
  // MATCHED_MATURITY_FLY) are still CURVE / FLY structures — render
  // per-leg rates the same way as the base types.
  const isMultiLeg =
    kind === 'CURVE' ||
    kind === 'FLY' ||
    kind.endsWith('_CURVE') ||
    kind.endsWith('_FLY') ||
    kind === 'INVOICE_SWITCH' ||
    kind === 'INVOICE_CALENDAR'
  if (isMultiLeg) {
    const legs = row.legs_json ?? []
    // Desk convention: render front-to-back so the CURVE reads
    // "front / back" and FLY reads "short wing / belly / long wing".
    // Structure-aware ordering (leg_order) with tenor fallback.
    const sorted = sortLegsForDisplay(legs)
    const legRates = sorted
      .map((l) => l?.fixed_rate)
      .filter((r): r is number => !isNullish(r as number | null | undefined))
    if (legRates.length >= 2) {
      return legRates.map((r) => formatRate(r)).join(' / ')
    }
  }
  return formatRate(row.weighted_fixed_rate ?? null)
}

export function formatTenor(row: UsdSwapTapeRow): string {
  const leg = row.legs_json?.[0]
  return (
    leg?.tenor_display ||
    leg?.tenor_label ||
    row.tenor_label ||
    row.package_tenors ||
    EMPTY_VALUE
  )
}

export function formatTime(ts: string | null | undefined): string {
  if (!ts) return EMPTY_VALUE
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return EMPTY_VALUE
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDate(ts: string | null | undefined): string {
  if (!ts) return EMPTY_VALUE
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return EMPTY_VALUE
  // SDR date fields (Effective Date, Expiration Date) are date-only strings
  // ("2026-09-30"). new Date() parses these as UTC midnight; toLocaleDateString
  // without timeZone:'UTC' shifts them back 1 day in US timezones.
  return d.toLocaleDateString('en-US', { timeZone: 'UTC' })
}

// All tape timestamps are rendered in the NYC trading-desk timezone, regardless
// of the viewer's browser locale, to match how desk traders read the tape.
const NYC_TIMEZONE = 'America/New_York'

export function formatExecutionWindow(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start) return EMPTY_VALUE
  const startDate = new Date(start)
  if (Number.isNaN(startDate.getTime())) return EMPTY_VALUE
  const endDate = end ? new Date(end) : startDate
  if (Number.isNaN(endDate.getTime())) return EMPTY_VALUE
  const startStr = `${startDate.toLocaleDateString('en-US', {
    timeZone: NYC_TIMEZONE,
  })} ${startDate.toLocaleTimeString('en-US', {
    timeZone: NYC_TIMEZONE,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })}`
  const endStr = endDate.toLocaleTimeString('en-US', {
    timeZone: NYC_TIMEZONE,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  if (startDate.getTime() === endDate.getTime()) return startStr
  return `${startStr} / ${endStr}`
}

// Execution-vs-Event timestamp integration (2026-07-17): the report /
// dissemination lag (Event timestamp #30 − Execution timestamp #96, ≥ 0). This
// separates fresh executions from lifecycle churn / late block prints.
//   - 'unknown'  when the execution timestamp is absent (cannot anchor)
//   - 'live'     when the event timestamp is absent (not yet disseminated,
//                or a pre-cutover row that never captured it)
//   - '0s'       a same-second report
//   - '+3d 04:12' / '+04:12:30' / '+3m 20s' / '+43s' otherwise (compact,
//     largest-unit-first). A negative sign appears only on a data-quality
//     invariant breach (event before execution beyond clock-skew tolerance).
export function formatTimestampDelta(
  execIso: string | null | undefined,
  eventIso: string | null | undefined,
): string {
  if (!execIso) return 'unknown'
  if (!eventIso) return 'live'
  const exec = new Date(execIso).getTime()
  const event = new Date(eventIso).getTime()
  if (Number.isNaN(exec) || Number.isNaN(event)) return 'unknown'
  let sec = Math.round((event - exec) / 1000)
  if (sec === 0) return '0s'
  const sign = sec < 0 ? '-' : '+'
  sec = Math.abs(sec)
  const days = Math.floor(sec / 86400)
  const hrs = Math.floor((sec % 86400) / 3600)
  const mins = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  if (days > 0) return `${sign}${days}d ${pad(hrs)}:${pad(mins)}`
  if (hrs > 0) return `${sign}${pad(hrs)}:${pad(mins)}:${pad(s)}`
  if (mins > 0) return `${sign}${mins}m ${pad(s)}s`
  return `${sign}${s}s`
}

export function formatClusterSuffix(size: number | null | undefined): string {
  if (isNullish(size)) return ''
  if (size < 2) return ''
  return ` (+${size - 1})`
}

// Compact, signed, lowercase-suffix formatter for OPA / PTP cells. Distinct
// from formatNotional which uses uppercase suffixes and a >=1K threshold —
// trader readout here needs "2.1k" for -2100, not "-2,100".
function formatSignedCompact(n: number): string {
  const sign = n < 0 ? '-' : ''
  const abs = Math.abs(n)
  if (abs >= 1e9) {
    const scaled = abs / 1e9
    const precision = scaled >= 100 ? 0 : 1
    return `${sign}${scaled.toFixed(precision)}b`
  }
  if (abs >= 1e6) {
    const scaled = abs / 1e6
    const precision = scaled >= 100 ? 0 : 1
    return `${sign}${scaled.toFixed(precision)}m`
  }
  const scaled = abs / 1e3
  // P2-01: 1235 → "1.2k"; 12345 → "12k"; 123456 → "123k". Earlier
  // ternary collapsed to ``? 1 : 1`` so 123456 rendered as "123.5k"
  // (1-decimal noise on a 6-figure value). Drop to 0 fraction digits
  // once the scaled value crosses 100 so the OPA / PTP / PTS lines
  // stay narrow.
  const precision = scaled >= 100 ? 0 : 1
  return `${sign}${scaled.toFixed(precision)}k`
}

// Format the Package Transaction Spread (PTS). Rendered as-is from the
// raw SDR field — scale-aware unit inference (bp vs %) proved misleading
// given the SDR reporters disagree on the underlying units. Trim trailing
// zeros so the cell stays compact.
function formatPackageSpread(n: number): string {
  // toLocaleString with up to 6 fraction digits preserves precision for
  // small decimals (0.00025) without dragging a long tail for whole-ish
  // values (1.5 stays "1.5", not "1.500000").
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 })
}

export function formatOtherLvl(input: {
  legOpa: Array<number | null | undefined>
  ptp: number | null | undefined
  opaCurrency?: Array<string | null | undefined>
  ptpCurrency?: string | null | undefined
  /**
   * Package Transaction Spread — raw SDR field, typically a decimal
   * representing the spread over a benchmark (e.g. 0.0025 = 25bp).
   * Optional for backward compat with callers that pre-date the field.
   */
  pts?: number | null | undefined
  /**
   * Per-leg PTP / PTS arrays. Populated for CURVE / FLY packages (and
   * their composite ``*_CURVE`` / ``*_FLY`` variants) so the cell reads
   * ``"PTP: 100k / 50k"`` with one value per leg in tenor-ASC order.
   * When omitted or all-null the scalar ``ptp`` / ``pts`` falls through.
   */
  legPtp?: Array<number | null | undefined>
  legPts?: Array<number | null | undefined>
}): { opaLine: string; ptpLine: string; ptsLine: string } {
  const MAX_INLINE_LEGS = 3
  const opaParts: string[] = []
  input.legOpa.forEach((v, i) => {
    if (v === null || v === undefined || Number.isNaN(v)) return
    const ccy = input.opaCurrency?.[i]
    const formatted = formatSignedCompact(Number(v))
    opaParts.push(ccy && ccy !== 'USD' ? `${formatted} ${ccy}` : formatted)
  })
  let opaLine: string
  if (opaParts.length === 0) {
    opaLine = `OPA: ${EMPTY_VALUE}`
  } else if (opaParts.length <= MAX_INLINE_LEGS) {
    opaLine = `OPA: ${opaParts.join(' / ')}`
  } else {
    opaLine = `OPA: ${opaParts.slice(0, MAX_INLINE_LEGS).join(' / ')} ...`
  }

  // PTP line — prefer per-leg array when supplied + at least one non-null.
  const legPtpNonNull = (input.legPtp ?? []).filter(
    (v): v is number => v !== null && v !== undefined && !Number.isNaN(v),
  )
  let ptpLine: string
  if (legPtpNonNull.length >= 1) {
    const ccySuffix =
      input.ptpCurrency && input.ptpCurrency !== 'USD' ? ` ${input.ptpCurrency}` : ''
    const allLegPtpIdentical =
      legPtpNonNull.length > 1 &&
      legPtpNonNull.every((v) => v === legPtpNonNull[0])
    const parts = allLegPtpIdentical
      ? [formatSignedCompact(Number(legPtpNonNull[0]))]
      : legPtpNonNull.map((v) => formatSignedCompact(Number(v)))
    ptpLine = `PTP: ${parts.join(' / ')}${ccySuffix}`
  } else if (input.ptp === null || input.ptp === undefined || Number.isNaN(input.ptp)) {
    ptpLine = `PTP: ${EMPTY_VALUE}`
  } else {
    const formatted = formatSignedCompact(Number(input.ptp))
    ptpLine =
      input.ptpCurrency && input.ptpCurrency !== 'USD'
        ? `PTP: ${formatted} ${input.ptpCurrency}`
        : `PTP: ${formatted}`
  }

  // PTS line — same per-leg pattern.
  const legPtsNonNull = (input.legPts ?? []).filter(
    (v): v is number => v !== null && v !== undefined && !Number.isNaN(v),
  )
  let ptsLine: string
  if (legPtsNonNull.length >= 1) {
    const allLegPtsPresent = (input.legPts ?? []).length === legPtsNonNull.length
    const allLegPtsIdentical =
      allLegPtsPresent &&
      legPtsNonNull.length > 1 &&
      legPtsNonNull.every((v) => v === legPtsNonNull[0])
    const parts = allLegPtsIdentical
      ? [formatPackageSpread(Number(legPtsNonNull[0]))]
      : legPtsNonNull.map((v) => formatPackageSpread(Number(v)))
    ptsLine = `PTS: ${parts.join(' / ')}`
  } else if (input.pts === null || input.pts === undefined || Number.isNaN(input.pts)) {
    ptsLine = `PTS: ${EMPTY_VALUE}`
  } else {
    ptsLine = `PTS: ${formatPackageSpread(Number(input.pts))}`
  }

  return { opaLine, ptpLine, ptsLine }
}
