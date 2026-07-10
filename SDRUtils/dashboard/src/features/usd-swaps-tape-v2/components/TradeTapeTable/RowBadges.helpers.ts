// Pure helpers extracted from RowBadges.tsx — testable without React.
import {
  ECONOMIC_CLASS_LABELS,
  ECONOMIC_CLASS_TONES,
  FLAG_CHIP_TONES,
  LIFECYCLE_LABELS,
  LIFECYCLE_ORDER,
  LIFECYCLE_TONES,
  TAPE_TAG_TONES,
} from '../../constants'
import type { EconomicClass, LifecycleType, UsdSwapTapeRow } from '../../types'

export function lifecyclePillsFor(row: UsdSwapTapeRow): Array<{
  type: LifecycleType
  count: number
  className: string
  label: string
}> {
  const mix = row.lifecycle_mix ?? {}
  const pills: Array<{
    type: LifecycleType
    count: number
    className: string
    label: string
  }> = []
  for (const type of LIFECYCLE_ORDER) {
    const count = Number(mix[type] ?? 0)
    if (count > 0) {
      pills.push({
        type,
        count,
        className: LIFECYCLE_TONES[type],
        label: LIFECYCLE_LABELS[type],
      })
    }
  }
  // Drop the NEW pill when the mix also contains any non-NEW lifecycle —
  // e.g. an unwind/termination that started as a new risk shouldn't read as "new".
  const hasNonNew = pills.some((p) => p.type !== 'NEW_RISK')
  if (hasNonNew) {
    return pills.filter((p) => p.type !== 'NEW_RISK')
  }
  return pills
}

export function flagBadgesFor(row: UsdSwapTapeRow): Array<{
  key: string
  className: string
  label: string
  ariaLabel: string
}> {
  const badges: Array<{
    key: string
    className: string
    label: string
    ariaLabel: string
  }> = []
  if (row.is_block_any) {
    badges.push({
      key: 'BLK',
      className: FLAG_CHIP_TONES.BLK,
      label: 'BLK',
      ariaLabel: 'block trade',
    })
  }
  if (row.is_ufro_any) {
    badges.push({
      key: 'UFRO',
      className: FLAG_CHIP_TONES.UFRO,
      label: 'UFRO',
      ariaLabel: 'off-market rate',
    })
  }
  if (row.is_capped_any) {
    badges.push({
      key: 'CAP',
      className: FLAG_CHIP_TONES.CAPPED,
      label: 'CAP',
      ariaLabel: 'notional capped',
    })
  }
  if (row.is_off_date_any) {
    badges.push({
      key: 'ODT',
      className: FLAG_CHIP_TONES.OFF_DATE,
      label: '~',
      ariaLabel: 'off-date',
    })
  }
  return badges
}


/**
 * Phase 4-5 quality / compliance badges. Distinct from flagBadgesFor —
 * those are trader-facing trade flags (BLK/UFRO/CAP). These are
 * compliance / data-quality signals surfaced by the SDR remediation
 * (state-machine validator, cap-band check, freq anomaly, schedule
 * truncation, D2 chain). Renders red/violet tones to draw the eye.
 */
export function qualityBadgesFor(row: UsdSwapTapeRow): Array<{
  key: string
  className: string
  label: string
  ariaLabel: string
  title: string
}> {
  const badges: Array<{
    key: string
    className: string
    label: string
    ariaLabel: string
    title: string
  }> = []

  // Aggregate row-level signals from package OR any leg.
  const legs = (row.legs_json ?? []) as Array<Record<string, unknown>>
  const anyLeg = (key: string) => legs.some((l) => Boolean(l[key]))

  if (row.state_machine_violation_any || anyLeg('state_machine_violation')) {
    const reasons = legs
      .map((l) => l.violation_reason)
      .filter(Boolean)
      .join(', ')
    badges.push({
      key: 'VIOL',
      className: FLAG_CHIP_TONES.VIOL,
      label: 'VIOL',
      ariaLabel: 'lifecycle state-machine violation',
      title: reasons
        ? `state-machine violation: ${reasons}`
        : 'state-machine violation',
    })
  }
  if (anyLeg('cap_band_violation')) {
    badges.push({
      key: 'CAP-BAND',
      className: FLAG_CHIP_TONES.CAP_BAND,
      label: 'CAP!',
      ariaLabel: 'cap band violation',
      title: 'reported notional exceeds §43.4(f) cap for the trade tenor',
    })
  }
  if (anyLeg('frequency_anomaly')) {
    badges.push({
      key: 'FREQ',
      className: FLAG_CHIP_TONES.FREQ_ANOM,
      label: 'FREQ',
      ariaLabel: 'frequency anomaly',
      title: 'underlier vs reset-frequency mismatch (e.g. SOFR with yearly reset)',
    })
  }
  if (anyLeg('schedule_truncated')) {
    badges.push({
      key: 'TRUNC',
      className: FLAG_CHIP_TONES.TRUNC,
      label: 'TRUNC',
      ariaLabel: 'schedule truncated',
      title: 'schedule was truncated to first 10 rows per §43.4(d)',
    })
  }
  if (anyLeg('d2_missing')) {
    badges.push({
      key: 'D2',
      className: FLAG_CHIP_TONES.D2_MISS,
      label: 'D2!',
      ariaLabel: 'missing original dissemination identifier',
      title: 'CORR/EROR/TERM/REVI/MODI(Amend=True) without [#2] Original Dissemination Identifier',
    })
  }
  // P2-02: only flag a CLR-lag badge when the gap between original
  // execution and clearing acceptance is meaningfully long. Every β/γ
  // NEWT-CLRG row has a non-null clearing-accept timestamp by
  // definition, so the old `!= null` check fired CLR on every cleared
  // trade — pure badge noise. 60s threshold matches the SDR's typical
  // sub-second cleared-direct path (anything longer is worth the
  // trader's attention).
  const CLR_LAG_THRESHOLD_MS = 60_000
  const hasMeaningfulClearLag = (
    orig: string | Date | null | undefined,
    accept: string | Date | null | undefined,
  ): boolean => {
    if (!orig || !accept) return false
    const o = orig instanceof Date ? orig.getTime() : new Date(String(orig)).getTime()
    const a = accept instanceof Date ? accept.getTime() : new Date(String(accept)).getTime()
    if (Number.isNaN(o) || Number.isNaN(a)) return false
    return a - o >= CLR_LAG_THRESHOLD_MS
  }
  const packageHasLag = hasMeaningfulClearLag(
    row.original_execution_start,
    row.clearing_accepted_start,
  )
  const legHasLag = legs.some((l) =>
    hasMeaningfulClearLag(
      (l as { original_execution_timestamp?: string | Date | null }).original_execution_timestamp,
      l.clearing_accepted_timestamp as string | Date | null | undefined,
    ),
  )
  if (packageHasLag || legHasLag) {
    badges.push({
      key: 'CLR',
      className: FLAG_CHIP_TONES.CLR_ACC,
      label: 'CLR',
      ariaLabel: 'clearing acceptance lag',
      title: 'clearing-accept timestamp differs from original execution by ≥ 60s',
    })
  }
  if (
    row.on_p43_any === false ||
    legs.some((l) => l.on_p43 === false)
  ) {
    badges.push({
      key: 'P43-OFF',
      className: FLAG_CHIP_TONES.P43_OFF,
      label: 'P45',
      ariaLabel: 'not on Part 43 public tape',
      title: 'event not visible on Part 43 public tape (P45-only)',
    })
  }
  return badges
}


/**
 * Phase 3 economic-class badge for the dedicated tape column. Reads the
 * package-level rollup `economic_class_primary`, falling back to a
 * derivation from existing booleans for legacy rows.
 */
export function economicClassBadgeFor(row: UsdSwapTapeRow): {
  className: string
  label: string
  title: string
} | null {
  const raw = row.economic_class_primary
  let kind: EconomicClass | null = null
  if (raw && (raw as string) in ECONOMIC_CLASS_LABELS) {
    kind = raw as EconomicClass
  } else if (row.is_compression_any) {
    kind = 'ADMINISTRATIVE'
  } else if (row.is_clearing_termination_any) {
    kind = 'ADMINISTRATIVE'
  } else if (row.is_termination_any || row.is_unwind) {
    kind = 'ECONOMIC_UNWIND'
  } else if (row.is_correction_any) {
    kind = 'RESTATEMENT'
  } else if (row.is_new_risk) {
    kind = 'ECONOMIC_FLOW'
  }
  if (!kind) return null
  return {
    className: ECONOMIC_CLASS_TONES[kind] ?? ECONOMIC_CLASS_TONES.UNKNOWN,
    label: ECONOMIC_CLASS_LABELS[kind] ?? '?',
    title: `economic_class: ${kind}`,
  }
}


/**
 * Extended lifecycle pill set including AMENDMENT / NULL_FILL /
 * SCHED_AMORT distinctions (Phase 2-3) when the row's leg-level
 * lc_was_* flags are populated. Adds to the existing mix-derived list
 * without duplicating; emits at most one pill per kind even on
 * multi-leg packages.
 */
export function extendedLifecyclePillsFor(row: UsdSwapTapeRow): Array<{
  type: LifecycleType
  count: number
  className: string
  label: string
}> {
  const base = lifecyclePillsFor(row)
  const seen = new Set(base.map((p) => p.type))
  const extras: typeof base = []
  const legs = (row.legs_json ?? []) as Array<Record<string, unknown>>

  const push = (type: LifecycleType) => {
    if (seen.has(type)) return
    seen.add(type)
    extras.push({
      type,
      count: 1,
      className: LIFECYCLE_TONES[type],
      label: LIFECYCLE_LABELS[type],
    })
  }

  if (legs.some((l) => l.lc_was_amended)) push('AMENDMENT')
  if (legs.some((l) => l.lc_was_null_filled)) push('NULL_FILL')
  if (legs.some((l) => l.lc_was_scheduled_amortization)) push('SCHED_AMORT')
  if (legs.some((l) => l.state_machine_violation)) push('ERROR')

  return [...base, ...extras]
}


const DEFAULT_TAG_TONE = 'bg-zinc-700/50 text-zinc-300'

const TAG_ALIASES: Record<string, string> = {
  'OFF-MKT': 'OFFM',
  'PAST-EFF': 'OLD',
}

export function actionClassBadgeFor(row: UsdSwapTapeRow): {
  className: string
  label: string
  title: string
} | null {
  const pills = extendedLifecyclePillsFor(row)
  const classMeta = economicClassBadgeFor(row)
  const actionLabel = pills.length > 0 ? pills[0].label : null
  const classLabel = classMeta?.label ?? null
  if (!actionLabel && !classLabel) return null
  const combined = [actionLabel, classLabel].filter(Boolean).join('-')
  return {
    className: classMeta?.className ?? pills[0]?.className ?? '',
    label: combined,
    title: `lifecycle: ${pills.map((p) => p.label).join('+') || '–'} | class: ${classMeta?.title ?? '–'}`,
  }
}


export function tapeTagBadgesFor(row: UsdSwapTapeRow): Array<{
  key: string
  className: string
  label: string
}> {
  const raw = row.tape_tags
  const fromTags = raw ? raw.split(',').filter(Boolean) : []

  // Extract execution tags from tape_label for legacy rows where the
  // pipeline hasn't split them into tape_tags yet.
  const label =
    row.tape_label ??
    ((row.legs_json?.[0] as Record<string, unknown> | undefined)?.tape_label as string | undefined) ??
    ''
  const fromLabel: string[] = []
  if (typeof label === 'string') {
    const re = /\b(PARTIAL-UNWIND|XD-TERM|NOVA-IN|NOVA-OUT|OFFM|OFF-MKT|OLD|PAST-EFF|UNWIND|UFRO|BLOCK|TERM|CORR|MODI|EXER|CLRG)\b/g
    let m: RegExpExecArray | null
    while ((m = re.exec(label)) !== null) {
      if (!fromLabel.includes(m[1])) fromLabel.push(m[1])
    }
  }

  // Derive from boolean flags — these fire even when the label text
  // doesn't contain the keyword (e.g. UFRO trades where the pipeline
  // marked is_ufro but didn't append it to the label string).
  const fromFlags: string[] = []
  if (row.is_ufro_any) fromFlags.push('UFRO')
  if (row.is_block_any) fromFlags.push('BLOCK')
  const legs = (row.legs_json ?? []) as Array<Record<string, unknown>>
  if (legs.some((l) => l.is_off_market || l.lc_is_off_market_seasoned || l.xd_is_off_market_seasoned)) {
    fromFlags.push('OFFM')
  }
  if (legs.some((l) => {
    if (l.lc_has_past_effective || l.xd_has_past_effective) return true
    const eff = l.effective_date as string | undefined
    const exec = (l.execution_timestamp ?? l.original_execution_timestamp) as string | undefined
    return eff && exec && new Date(eff).getTime() < new Date(exec).getTime()
  })) {
    fromFlags.push('OLD')
  }

  const seen = new Set<string>()
  const merged: string[] = []
  for (const raw of [...fromTags, ...fromLabel, ...fromFlags]) {
    const tag = TAG_ALIASES[raw] ?? raw
    if (!seen.has(tag)) {
      seen.add(tag)
      merged.push(tag)
    }
  }
  if (merged.length === 0) return []
  return merged.map((tag) => ({
    key: tag,
    className: TAPE_TAG_TONES[tag] ?? DEFAULT_TAG_TONE,
    label: tag,
  }))
}
