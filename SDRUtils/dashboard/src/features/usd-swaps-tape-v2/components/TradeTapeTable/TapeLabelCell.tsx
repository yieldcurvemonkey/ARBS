'use client'
// ABOUTME: Hero identifier cell combining rate index, reset freq, tenor, structure, flag glyphs.
import type { JSX } from 'react'
import { FLAG_CHIP_TONES } from '../../constants'
import type { UsdSwapTapeRow } from '../../types'

function indexTone(index: string | null | undefined): string {
  switch (index) {
    case 'SOFR':
      return 'bg-emerald-900/40 text-emerald-200'
    case 'FED_FUNDS':
      return 'bg-amber-900/40 text-amber-200'
    default:
      return 'bg-slate-800/60 text-slate-300'
  }
}

function Chip({ className = '', children }: { className?: string; children: React.ReactNode }) {
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${className}`}
    >
      {children}
    </span>
  )
}

function InlineFlag({
  className = '',
  children,
  ariaLabel,
}: {
  className?: string
  children: React.ReactNode
  ariaLabel: string
}) {
  return (
    <span
      role="img"
      aria-label={ariaLabel}
      className={`text-[10px] font-semibold uppercase tracking-wide ${className}`}
    >
      {children}
    </span>
  )
}

function structureOf(row: UsdSwapTapeRow): string {
  if (row.package_structure) return row.package_structure
  if (row.package_type) return String(row.package_type)
  return ''
}

export function TapeLabelCell({ row }: { row: UsdSwapTapeRow }): JSX.Element {
  const firstLeg = row.legs_json?.[0]
  const tenor = firstLeg?.tenor_display ?? firstLeg?.tenor_label ?? row.tenor_label ?? '—'
  const offDate = typeof tenor === 'string' && tenor.startsWith('~')
  const tenorClean = typeof tenor === 'string' ? tenor.replace(/^~/, '') : tenor
  return (
    <div
      className="flex items-center gap-1.5 whitespace-nowrap font-mono text-slate-100"
      data-testid="tape-label-cell"
    >
      <Chip className={indexTone(row.rate_index_clean ?? null)}>
        {row.rate_index_clean ?? '—'}
      </Chip>
      {firstLeg?.upi_reset_freq ? (
        <Chip className="bg-zinc-800/70 text-zinc-300">{firstLeg.upi_reset_freq}</Chip>
      ) : null}
      <span>
        {firstLeg?.forward_label && firstLeg.forward_label !== 'Spot'
          ? firstLeg.forward_label
          : 'Spot'}{' '}
        {offDate ? <span className="text-yellow-300">~</span> : null}
        {tenorClean}
      </span>
      <span className="text-slate-400 text-sm">{structureOf(row)}</span>
      {row.is_fomc_dated && row.fomc_meeting_label ? (
        <Chip className={FLAG_CHIP_TONES.FOMC}>\u26A1 {row.fomc_meeting_label}</Chip>
      ) : null}
      {row.is_block_any ? (
        <InlineFlag className={FLAG_CHIP_TONES.BLK} ariaLabel="block trade">
          BLK
        </InlineFlag>
      ) : null}
      {row.is_unwind ? (
        <InlineFlag className="text-red-300" ariaLabel="unwind">
          UNW
        </InlineFlag>
      ) : null}
      {row.is_ufro_any ? (
        <InlineFlag className="text-orange-300" ariaLabel="off-market rate">
          OFF-MKT
        </InlineFlag>
      ) : null}
      {row.is_off_date_any ? (
        <InlineFlag className="text-yellow-300" ariaLabel="off-date">
          OFF-DATE
        </InlineFlag>
      ) : null}
    </div>
  )
}

export const __test_helpers = { indexTone, structureOf }
