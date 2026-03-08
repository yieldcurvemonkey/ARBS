'use client'

import { memo, useMemo } from 'react'
import type {
  CellDisplayField,
  LastTradedLevelField,
  VolGridCell,
  VolGridChangeMetric
} from '../types'
import {
  STALENESS_COLORS,
  formatChange,
  formatConfidence,
  formatDate,
  formatNumber,
  formatPremiumBps,
  formatTime,
  getUnifiedCellBackground
} from '../utils'

type UnifiedGridCellProps = {
  cell: VolGridCell
  isSelected: boolean
  visibleFields: CellDisplayField[]
  lastTradedLevelFields: LastTradedLevelField[]
  changeMetric: VolGridChangeMetric
  volMin: number
  volMax: number
  onClick: () => void
}

function getChangeTone(value: number | null) {
  if (value === null || !Number.isFinite(value)) return 'text-slate-300'
  if (value > 0) return 'text-rose-300'
  if (value < 0) return 'text-emerald-300'
  return 'text-slate-200'
}

function deriveObservationPremiumBps(cell: VolGridCell) {
  const premium = cell.lastObservation?.premium ?? null
  const notional = cell.lastObservation?.notional ?? null
  if (
    premium === null ||
    notional === null ||
    !Number.isFinite(premium) ||
    !Number.isFinite(notional) ||
    notional === 0
  ) {
    return null
  }
  return (Math.abs(premium) / Math.abs(notional)) * 10_000
}

export const UnifiedGridCell = memo(function UnifiedGridCell({
  cell,
  isSelected,
  visibleFields,
  lastTradedLevelFields,
  changeMetric,
  volMin,
  volMax,
  onClick
}: UnifiedGridCellProps) {
  const dotColor = STALENESS_COLORS[cell.stalenessCategory] ?? STALENESS_COLORS.no_data
  const isFresh =
    cell.atmfVolSource === 'direct_observation' &&
    cell.staleness !== null &&
    cell.staleness <= 5
  const isStaleOrWorse =
    cell.stalenessCategory === 'stale' || cell.stalenessCategory === 'very_stale'
  const lastTradeLabel = cell.lastObservation
    ? `${formatDate(cell.lastObservation.executionTimestamp)} ${formatTime(cell.lastObservation.executionTimestamp)} ET`
    : 'No trade history'
  const lastTradePremiumBps = deriveObservationPremiumBps(cell)
  const lastTradeLevelLabel = useMemo(() => {
    if (!cell.lastObservation) return '--'

    const values = lastTradedLevelFields.flatMap((field) => {
      if (field === 'bpvol') {
        const bpvol = formatNumber(cell.lastObservation?.bpvolYr ?? null, 2)
        return bpvol === '--' ? [] : [bpvol]
      }

      const premiumBps = formatNumber(lastTradePremiumBps, 2)
      return premiumBps === '--' ? [] : [premiumBps]
    })

    return values.length ? values.join('/') : '--'
  }, [cell.lastObservation, lastTradePremiumBps, lastTradedLevelFields])

  const tooltip = [
    `${cell.expiry}x${cell.tenor}`,
    `Vol: ${formatNumber(cell.atmfVol, 2)} bpvol`,
    `Premium: ${formatPremiumBps(cell.atmfPremiumBps)}`,
    `dVol: ${formatChange(cell.atmfVolChange, 1)} bpvol`,
    `dPrem: ${formatChange(cell.atmfPremiumBpsChange, 2)} bp`,
    `Confidence: ${formatConfidence(cell.atmfVolConfidence)}`,
    `Source: ${cell.atmfVolSource}`,
    `Regime: ${cell.regimeLabel ?? '--'}`,
    cell.lastObservation
      ? `Last SDR: ${lastTradeLabel} @ ${lastTradeLevelLabel}`
      : 'Last SDR: --'
  ].join('\n')

  return (
    <button
      title={tooltip}
      onClick={onClick}
      className={`relative flex min-h-[78px] flex-col overflow-hidden border px-2 py-1.5 text-left font-mono text-white transition ${
        isSelected
          ? 'border-sky-400/80 shadow-[inset_0_0_0_1px_rgba(56,189,248,0.45)]'
          : 'border-slate-800/90 hover:border-slate-600/80'
      } ${isStaleOrWorse ? 'border-l-slate-500/80' : ''}`}
      style={{
        backgroundColor: getUnifiedCellBackground(cell.atmfVol, volMin, volMax)
      }}
    >
      <span className="absolute inset-x-0 top-0 h-[2px]" style={{ backgroundColor: dotColor }} />

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {visibleFields.includes('vol') && (
            <div className="text-[18px] font-semibold leading-none tracking-tight text-slate-50 tabular-nums">
              {formatNumber(cell.atmfVol, 2)}
            </div>
          )}
          {visibleFields.includes('premium') && (
            <div className="mt-1 text-[9px] uppercase tracking-[0.18em] text-slate-400">
              <span className="text-slate-200">{formatPremiumBps(cell.atmfPremiumBps)}</span>
            </div>
          )}
        </div>

        {visibleFields.includes('change') && (
          <div className="space-y-1 text-right text-[9px] leading-3 tabular-nums">
            <div>
              <span className="mr-1 uppercase tracking-[0.16em] text-slate-500">dV</span>
              <span className={getChangeTone(cell.atmfVolChange)}>
                {formatChange(cell.atmfVolChange, 1)}
              </span>
            </div>
            <div>
              <span className="mr-1 uppercase tracking-[0.16em] text-slate-500">dP</span>
              <span className={getChangeTone(cell.atmfPremiumBpsChange)}>
                {formatChange(cell.atmfPremiumBpsChange, 2)}
              </span>
            </div>
          </div>
        )}
      </div>

      {(visibleFields.includes('lastTradedTime') ||
        visibleFields.includes('lastTradedLevel')) && (
        <div className="mt-auto border-t border-slate-800/80 pt-1.5">
          <div className="flex items-end justify-between gap-2">
            <div className="min-w-0 text-[9px] leading-3 text-slate-400">
              <div className="uppercase tracking-[0.18em] text-slate-500">Last</div>
              {visibleFields.includes('lastTradedTime') &&
                (cell.lastObservation ? (
                  <>
                    <div className="truncate text-slate-300">
                      {formatDate(cell.lastObservation.executionTimestamp)}
                    </div>
                    <div>{formatTime(cell.lastObservation.executionTimestamp)} ET</div>
                  </>
                ) : (
                  <div>--</div>
                ))}
            </div>
            {visibleFields.includes('lastTradedLevel') && (
              <span className="text-[10px] font-semibold text-slate-200 tabular-nums">
                {lastTradeLevelLabel}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="absolute bottom-0 left-0 right-0 h-[3px] bg-slate-800/40">
        <div
          className="h-full bg-sky-400/55"
          style={{ width: `${Math.round(cell.atmfVolConfidence * 100)}%` }}
        />
      </div>
    </button>
  )
})
