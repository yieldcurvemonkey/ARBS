'use client'
// ABOUTME: Expanded package detail panel - per-leg breakdown only.
import type { JSX } from 'react'
import { useState } from 'react'

// Centralised column count for the leg sub-table. Bump in lock-step
// with the <th> list below so the empty-state colspan + the summary
// row's trailing pad columns stay correct when a column is added.
const LEG_COL_COUNT = 16
import {
  ECONOMIC_CLASS_LABELS,
  ECONOMIC_CLASS_TONES,
  EMPTY_VALUE,
  PACKAGE_CONFIDENCE_TONES,
} from '../../constants'
import type { EconomicClass, UsdSwapTapeLeg, UsdSwapTapeRow } from '../../types'
import { computeLegSummary } from './LegsSubTable.helpers'
import { stripExecutionTags } from './TapeLabelCell.helpers'
import {
  formatDate,
  formatDv01,
  formatNotional,
  formatRate,
} from '../../utils/format'
import { computePackageConfidence } from '../../utils/packageConfidence'

function formatTime(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE
  try {
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return EMPTY_VALUE
    return d.toISOString().replace('T', ' ').slice(0, 19) + 'Z'
  } catch {
    return EMPTY_VALUE
  }
}

function classBadge(leg: UsdSwapTapeLeg) {
  const raw = leg.economic_class as string | null | undefined
  if (!raw) return <span className="text-slate-500">{EMPTY_VALUE}</span>
  const kind: EconomicClass =
    raw in ECONOMIC_CLASS_LABELS ? (raw as EconomicClass) : 'UNKNOWN'
  const className = ECONOMIC_CLASS_TONES[kind] ?? ECONOMIC_CLASS_TONES.UNKNOWN
  const label = ECONOMIC_CLASS_LABELS[kind] ?? raw
  const reason = leg.economic_class_reason ?? ''
  return (
    <span
      className={`inline-flex items-center rounded px-1 py-0.5 text-[10px] font-semibold ${className}`}
      title={reason ? `${kind}: ${reason}` : kind}
    >
      {label}
    </span>
  )
}

function execTimestampPair(leg: UsdSwapTapeLeg) {
  const orig = leg.original_execution_timestamp ?? leg.execution_timestamp
  const accepted = leg.clearing_accepted_timestamp
  const origText = formatTime(orig)
  if (!accepted) {
    return (
      <span
        className="font-mono text-[11px] text-slate-200"
        title="original execution timestamp"
      >
        {origText}
      </span>
    )
  }
  const acceptedText = formatTime(accepted)
  return (
    <div
      className="flex flex-col leading-tight"
      title="β/γ clearing leg: original alpha exec on top, clearing-accept below"
    >
      <span className="font-mono text-[11px] text-slate-200">{origText}</span>
      <span className="font-mono text-[10px] text-teal-300/80">
        ↳ {acceptedText}
      </span>
    </div>
  )
}

function tradeIdBody(leg: UsdSwapTapeLeg) {
  const tid = leg.trade_id ?? EMPTY_VALUE
  return (
    <button
      type="button"
      className="font-mono text-[11px] text-slate-300 hover:text-slate-100"
      onClick={() => {
        try {
          navigator.clipboard?.writeText(String(tid))
        } catch {
          /* ignore */
        }
      }}
      aria-label={`copy trade id ${tid}`}
    >
      {tid}
    </button>
  )
}

function maturityDateOf(leg: UsdSwapTapeLeg): string | null | undefined {
  return leg.swap_maturity_date ?? leg.expiration_date
}

// Display label for the CFTC "Cleared" field. Per Part 43 Appendix 1, the
// reported values are single-letter codes:
//   C = cleared
//   U = uncleared
//   I = intend to clear (pre-clearing window)
// Anything else (rare) is surfaced verbatim so ops can spot bad data.
const CLEARED_LABELS: Record<string, string> = {
  C: 'Cleared',
  U: 'Uncleared',
  I: 'Intent',
  Y: 'Cleared',
  N: 'Uncleared',
}

const CLEARED_BADGE_TONES: Record<string, string> = {
  C: 'bg-emerald-900/40 text-emerald-200',
  U: 'bg-rose-900/40 text-rose-200',
  I: 'bg-sky-900/40 text-sky-200',
  Y: 'bg-emerald-900/40 text-emerald-200',
  N: 'bg-rose-900/40 text-rose-200',
}

function clearedBody(leg: UsdSwapTapeLeg) {
  const raw = leg.cleared
  if (raw === null || raw === undefined || raw === '') {
    return <span className="text-slate-500">{EMPTY_VALUE}</span>
  }
  const key = String(raw).trim().toUpperCase()
  const label = CLEARED_LABELS[key] ?? key
  const tone = CLEARED_BADGE_TONES[key] ?? 'bg-slate-800/60 text-slate-300'
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase ${tone}`}
      title={`Cleared code: ${key}`}
    >
      {label}
    </span>
  )
}

function crossDayProgress(leg: UsdSwapTapeLeg) {
  const pct = leg.xd_notional_pct_remaining
  if (pct === null || pct === undefined || pct >= 0.999) {
    return <span className="text-slate-500">{EMPTY_VALUE}</span>
  }
  const bounded = Math.max(0, Math.min(1, Number(pct)))
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1 w-16 overflow-hidden rounded bg-slate-800"
        aria-label="cross-day notional remaining"
      >
        <div className="h-full bg-emerald-500" style={{ width: `${bounded * 100}%` }} />
      </div>
      <span className="text-[10px] text-slate-400">{(bounded * 100).toFixed(0)}%</span>
    </div>
  )
}

function flagBadge(
  key: string,
  label: string,
  className: string,
  ariaLabel: string,
) {
  return { key, label, className, ariaLabel }
}

function legBadges(leg: UsdSwapTapeLeg) {
  const badges = []
  if (leg.is_ufro) {
    badges.push(
      flagBadge('ufro', 'UFRO', 'bg-orange-900/40 text-orange-200', 'ufro reported'),
    )
  }
  if (leg.is_off_market) {
    badges.push(
      flagBadge(
        'off-market',
        'OFF-MKT',
        'bg-yellow-900/40 text-yellow-200',
        'off-market trade',
      ),
    )
  }
  if (leg.is_block) {
    badges.push(
      flagBadge('block', 'BLK', 'bg-orange-900/40 text-orange-200', 'block trade'),
    )
  }
  if (leg.is_capped) {
    badges.push(
      flagBadge('capped', 'CAP', 'bg-rose-900/40 text-rose-200', 'notional capped'),
    )
  }
  if (leg.is_off_date) {
    badges.push(
      flagBadge('off-date', '~', 'bg-yellow-900/40 text-yellow-200', 'off-date'),
    )
  }
  if (leg.is_non_standard_term) {
    badges.push(
      flagBadge(
        'non-standard',
        'NSTD',
        'bg-purple-900/40 text-purple-200',
        'non-standard term',
      ),
    )
  }
  // Phase 2-5 per-leg compliance / quality signals.
  if (leg.state_machine_violation) {
    badges.push(
      flagBadge(
        'violation',
        'VIOL',
        'bg-red-900/60 text-red-100',
        leg.violation_reason
          ? `state-machine violation: ${leg.violation_reason}`
          : 'state-machine violation',
      ),
    )
  }
  if (leg.cap_band_violation) {
    badges.push(
      flagBadge(
        'cap-band',
        'CAP!',
        'bg-rose-900/60 text-rose-100',
        '§43.4(f) cap-band violation: capped notional exceeds tenor cap',
      ),
    )
  }
  if (leg.frequency_anomaly) {
    badges.push(
      flagBadge(
        'freq',
        'FREQ',
        'bg-fuchsia-900/40 text-fuchsia-200',
        'underlier vs reset-frequency mismatch',
      ),
    )
  }
  if (leg.schedule_truncated) {
    badges.push(
      flagBadge(
        'truncated',
        'TRUNC',
        'bg-yellow-900/40 text-yellow-200',
        `schedule truncated to first 10 rows (full count: ${
          leg.schedule_row_count ?? '?'
        })`,
      ),
    )
  }
  if (leg.d2_missing) {
    badges.push(
      flagBadge(
        'd2-miss',
        'D2!',
        'bg-amber-900/60 text-amber-100',
        'missing Original Dissemination Identifier on lifecycle action',
      ),
    )
  }
  if (leg.lc_was_amended) {
    badges.push(
      flagBadge(
        'amended',
        'AMND',
        'bg-emerald-700/40 text-emerald-100',
        'has at least one MODI Amendment=True (real economic amendment)',
      ),
    )
  }
  if (leg.lc_was_null_filled) {
    badges.push(
      flagBadge(
        'null-fill',
        'NULL',
        'bg-slate-700/40 text-slate-200',
        'has MODI Amendment=False (null-fill / post-price backfill)',
      ),
    )
  }
  if (leg.lc_was_scheduled_amortization) {
    badges.push(
      flagBadge(
        'sched',
        'SCHED',
        'bg-cyan-700/30 text-cyan-100',
        'has scheduled amortization step (notional schedule advance)',
      ),
    )
  }
  if (
    leg.notional_source &&
    leg.notional_source !== 'p43_uncapped' &&
    leg.notional_source !== ''
  ) {
    badges.push(
      flagBadge(
        'notional-src',
        leg.notional_source.toUpperCase(),
        'bg-zinc-800/60 text-zinc-300',
        `notional sourced from: ${leg.notional_source}`,
      ),
    )
  }
  if (leg.on_p43 === false) {
    badges.push(
      flagBadge(
        'p45only',
        'P45',
        'bg-zinc-800/60 text-zinc-300',
        'event not on Part 43 public tape (P45-only)',
      ),
    )
  }
  const covered = new Set(badges.map((b) => b.label.toUpperCase()))
  const SYNONYMS: Record<string, string> = {
    OFF_MARKET: 'OFF-MKT',
    BLOCK: 'BLK',
    CAPPED: 'CAP',
    OFF_DATE: '~',
    NON_STANDARD: 'NSTD',
    STATE_MACHINE_VIOLATION: 'VIOL',
    VIOLATION: 'VIOL',
    CAP_BAND_VIOLATION: 'CAP!',
    FREQUENCY_ANOMALY: 'FREQ',
    SCHEDULE_TRUNCATED: 'TRUNC',
    D2_MISSING: 'D2!',
  }
  for (const value of leg.quality_flags ?? []) {
    const upper = value.toUpperCase()
    if (covered.has(upper)) continue
    const syn = SYNONYMS[upper]
    if (syn && covered.has(syn)) continue
    covered.add(upper)
    badges.push(
      flagBadge(
        `quality-${value}`,
        value,
        'bg-zinc-800/60 text-zinc-300',
        `quality flag ${value}`,
      ),
    )
  }
  return badges
}

function qualityFlagsBody(leg: UsdSwapTapeLeg) {
  const flags = legBadges(leg)
  if (!flags.length) return <span className="text-slate-500">{EMPTY_VALUE}</span>
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((flag) => (
        <span
          key={flag.key}
          className={`rounded px-1 py-0.5 text-[10px] font-semibold ${flag.className}`}
          aria-label={flag.ariaLabel}
        >
          {flag.label}
        </span>
      ))}
    </div>
  )
}

function PackageConfidencePanel({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const confidence = computePackageConfidence(row)
  const confidenceTone = PACKAGE_CONFIDENCE_TONES[confidence.tone]
  const [showDetails, setShowDetails] = useState(false)
  const detailsId = `confidence-details-${row.package_id}`
  const overrideActive = confidence.inferredType !== null
  const displayedType = confidence.inferredType ?? confidence.resolvedType
  return (
    <div
      className="mb-2 rounded-lg border border-slate-800/80 bg-slate-900/60 px-3 py-2"
      data-testid={`confidence-strip-${row.package_id}`}
    >
      <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wide text-slate-400">
        <span>Confidence</span>
        <span
          className={`inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] ${confidenceTone}`}
        >
          {confidence.score}/{confidence.total}
        </span>
        <span className="font-mono text-[10px] text-slate-500">
          ({displayedType})
        </span>
        <button
          type="button"
          onClick={() => setShowDetails((prev) => !prev)}
          aria-expanded={showDetails}
          aria-controls={detailsId}
          data-testid={`confidence-toggle-${row.package_id}`}
          className="ml-auto inline-flex items-center rounded border border-slate-700 bg-slate-900/70 px-2 py-0.5 font-mono text-[10px] normal-case tracking-normal text-slate-300 hover:border-slate-500 hover:text-slate-100"
        >
          {showDetails ? 'Hide Package Confidence Details' : 'Show Package Confidence Details'}
        </button>
      </div>
      {showDetails ? (
        <div id={detailsId}>
          {overrideActive ? (
            <div
              data-testid={`confidence-inferred-${row.package_id}`}
              className="mt-1.5 rounded border border-amber-500/40 bg-amber-900/20 px-2 py-1 font-mono text-[11px] text-amber-200"
            >
              <div className="text-[10px] uppercase tracking-wider text-amber-300/80">
                Inferred type: {row.package_type} → {confidence.inferredType}
              </div>
              <div className="text-amber-100/80">
                {confidence.inferredTypeReason}
              </div>
            </div>
          ) : null}
          <ul className="mt-1 space-y-0.5">
            {confidence.signals.map((s) => (
              <li
                key={s.name}
                className="flex items-baseline gap-2 font-mono text-[11px] leading-tight"
              >
                <span
                  className={s.passed ? 'text-emerald-300' : 'text-rose-300'}
                  aria-label={s.passed ? 'pass' : 'fail'}
                >
                  {s.passed ? '✓' : '✗'}
                </span>
                <span className="text-slate-200">{s.label}:</span>
                <span className="text-slate-400">{s.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

export function LegsSubTable({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  // Desk convention: render tenor-ascending so front legs (short duration)
  // appear above back legs (long duration). legs_json order from the
  // display view isn't guaranteed — sort defensively.
  const legs = [
    ...((row.legs_json ?? []) as UsdSwapTapeLeg[]),
  ].sort((a, b) => {
    const at = typeof a?.tenor_years === 'number' ? a.tenor_years : Number.POSITIVE_INFINITY
    const bt = typeof b?.tenor_years === 'number' ? b.tenor_years : Number.POSITIVE_INFINITY
    return at - bt
  })

  // PTP / PTS values live at the package level; repeat them on each leg
  // row so the expanded table reads standalone without forcing the user
  // to consult the top row.
  const ptp = row.package_transaction_price
  const ptpCurrency = row.package_transaction_price_currency
  const pts = row.package_transaction_spread
  const ptpText =
    ptp != null
      ? `${formatNotional(ptp, { compact: true })}${
          ptpCurrency && ptpCurrency !== 'USD' ? ` ${ptpCurrency}` : ''
        }`
      : EMPTY_VALUE
  const ptsText = pts != null ? String(pts) : EMPTY_VALUE

  // Package-level summary row (see LegsSubTable.helpers for the per-pkg
  // aggregation rules). Rendered as the last body row to give the desk a
  // one-glance read of the spread, risk, and other-payment totals.
  const summary = computeLegSummary(row)
  const summaryOpaText =
    summary.opa != null
      ? formatNotional(summary.opa, { compact: true })
      : EMPTY_VALUE
  const summaryPtpText =
    summary.ptp != null
      ? `${formatNotional(summary.ptp, { compact: true })}${
          ptpCurrency && ptpCurrency !== 'USD' ? ` ${ptpCurrency}` : ''
        }`
      : EMPTY_VALUE
  const summaryPtsText = summary.pts != null ? String(summary.pts) : EMPTY_VALUE

  return (
    <div
      className="rounded-xl border border-slate-800/80 bg-slate-950/70 px-4 py-1"
      data-testid={`legs-subtable-${row.package_id}`}
    >
      <PackageConfidencePanel row={row} />
      {row.package_transaction_price != null ? (
        <div className="mb-1 flex items-baseline gap-2 text-[10px] uppercase tracking-wide text-slate-400">
          <span>Package Transaction Price</span>
          <span className="font-mono text-[12px] text-slate-100">
            {formatNotional(row.package_transaction_price, { compact: true })}
            {row.package_transaction_price_currency &&
            row.package_transaction_price_currency !== 'USD'
              ? ` ${row.package_transaction_price_currency}`
              : ''}
          </span>
        </div>
      ) : null}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr
              className="text-[10px] uppercase tracking-wide text-slate-400"
              data-leg-table-header
            >
              <th className="px-2 py-1 text-left">#</th>
              <th className="px-2 py-1 text-left">Trade ID</th>
              {/* Phase 3: per-leg matrix kind */}
              <th className="px-2 py-1 text-left">Class</th>
              {/* Phase 1: original execution timestamp + clearing-accept */}
              <th className="px-2 py-1 text-left">Exec Ts</th>
              <th className="px-2 py-1 text-left">Tape Label</th>
              <th className="px-2 py-1 text-left">Effective</th>
              <th className="px-2 py-1 text-left">Maturity</th>
              <th className="px-2 py-1 text-right">Notional</th>
              <th className="px-2 py-1 text-right">Risk</th>
              <th className="px-2 py-1 text-right">Rate</th>
              <th className="px-2 py-1 text-right">OPA</th>
              <th className="px-2 py-1 text-right">PTP</th>
              <th className="px-2 py-1 text-right">PTS</th>
              <th className="px-2 py-1 text-left">Cleared</th>
              <th className="px-2 py-1 text-left">Flags</th>
              <th className="px-2 py-1 text-left">X-Day</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, index) => (
              <tr
                key={leg.trade_id ?? `${row.package_id}-${index}`}
                className="border-t border-slate-800/90 text-slate-200"
              >
                <td className="whitespace-nowrap px-2 py-1">{index + 1}</td>
                <td className="whitespace-nowrap px-2 py-1">{tradeIdBody(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">{classBadge(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">
                  {execTimestampPair(leg)}
                </td>
                <td className="max-w-[360px] px-2 py-1 font-mono text-[11px] text-slate-100">
                  {stripExecutionTags(leg.leg_tape_label ?? leg.tape_label ?? EMPTY_VALUE)}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {formatDate(leg.effective_date)}
                </td>
                <td className="whitespace-nowrap px-2 py-1">
                  {formatDate(maturityDateOf(leg))}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatNotional(leg.notional ?? null, { compact: true })}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatDv01(leg.risk ?? null)}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatRate(leg.fixed_rate ?? null)}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {(() => {
                    const sign = leg.opa_sign
                    const opa = leg.other_payment_amount
                    const ccy = leg.other_payment_currency
                    const ccySuffix = ccy && ccy !== 'USD' ? ` ${ccy}` : ''
                    if (sign != null && opa != null) {
                      const color = sign > 0 ? 'text-emerald-400' : 'text-red-400'
                      const prefix = sign > 0 ? '+' : '−'
                      return (
                        <span className={color}>
                          {prefix}{formatNotional(Math.abs(sign * opa), { compact: true })}{ccySuffix}
                        </span>
                      )
                    }
                    return opa != null
                      ? `${formatNotional(opa, { compact: true })}${ccySuffix}`
                      : EMPTY_VALUE
                  })()}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {(() => {
                    const legPtp = (leg as any).package_transaction_price
                    if (legPtp != null) {
                      const legCcy = (leg as any).package_transaction_price_currency
                      return `${formatNotional(legPtp, { compact: true })}${
                        legCcy && legCcy !== 'USD' ? ` ${legCcy}` : ''
                      }`
                    }
                    return ptpText
                  })()}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {(() => {
                    const legPts = (leg as any).package_transaction_spread
                    return legPts != null ? String(legPts) : ptsText
                  })()}
                </td>
                <td className="whitespace-nowrap px-2 py-1">{clearedBody(leg)}</td>
                <td className="px-2 py-1">{qualityFlagsBody(leg)}</td>
                <td className="whitespace-nowrap px-2 py-1">{crossDayProgress(leg)}</td>
              </tr>
            ))}
            {legs.length === 0 ? (
              <tr className="border-t border-slate-800/90 text-slate-400">
                <td className="px-2 py-2" colSpan={LEG_COL_COUNT}>
                  No leg data available.
                </td>
              </tr>
            ) : (
              <tr
                className="border-t-2 border-slate-600 bg-slate-900/80 font-semibold text-slate-100"
                data-testid={`legs-subtable-summary-${row.package_id}`}
              >
                <td className="whitespace-nowrap px-2 py-1 text-slate-400">Σ</td>
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
                <td className="px-2 py-1 text-[10px] uppercase tracking-wide text-slate-400">
                  Summary
                </td>
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatDv01(summary.risk)}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {formatRate(summary.rate, { precision: 5 })}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {summaryOpaText}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {summaryPtpText}
                </td>
                <td className="whitespace-nowrap px-2 py-1 text-right font-mono">
                  {summaryPtsText}
                </td>
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
                <td className="px-2 py-1" />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {/* Phase 5: UFRO/UWIN/PEXH per-leg breakdown when any non-zero. */}
      {legs.some(
        (l) =>
          (l.other_payment_ufro ?? 0) !== 0 ||
          (l.other_payment_uwin ?? 0) !== 0 ||
          (l.other_payment_pexh ?? 0) !== 0,
      ) ? (
        <div
          className="mt-1 flex flex-wrap items-baseline gap-3 text-[10px] uppercase tracking-wide text-slate-400"
          data-testid={`legs-subtable-other-payment-${row.package_id}`}
        >
          <span className="font-semibold text-slate-300">Other Payment:</span>
          <span>
            UFRO{' '}
            <span className="font-mono text-[12px] text-slate-100">
              {formatNotional(
                legs.reduce((s, l) => s + (l.other_payment_ufro ?? 0), 0),
                { compact: true },
              )}
            </span>
          </span>
          <span>
            UWIN{' '}
            <span className="font-mono text-[12px] text-slate-100">
              {formatNotional(
                legs.reduce((s, l) => s + (l.other_payment_uwin ?? 0), 0),
                { compact: true },
              )}
            </span>
          </span>
          <span>
            PEXH{' '}
            <span className="font-mono text-[12px] text-slate-100">
              {formatNotional(
                legs.reduce((s, l) => s + (l.other_payment_pexh ?? 0), 0),
                { compact: true },
              )}
            </span>
          </span>
        </div>
      ) : null}
      {/* Phase 5: collateralisation required-fields gaps. */}
      {legs.some(
        (l) => (l.missing_required_fields ?? []).length > 0,
      ) ? (
        <div
          className="mt-1 flex flex-wrap items-baseline gap-2 text-[10px] uppercase tracking-wide text-amber-300"
          data-testid={`legs-subtable-missing-required-${row.package_id}`}
        >
          <span className="font-semibold">Missing required fields:</span>
          {Array.from(
            new Set(
              legs.flatMap((l) => l.missing_required_fields ?? []),
            ),
          ).map((field) => (
            <span
              key={field}
              className="rounded bg-amber-900/40 px-1 py-0.5 font-mono text-[11px] normal-case text-amber-200"
              title="Appendix E required field missing for this row's collateralisation category"
            >
              {field}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
