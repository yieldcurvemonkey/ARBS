/**
 * Modal for creating manual trade links
 * Frontend-driven: computes metrics and validations in real-time
 */

'use client'

import { useState, useMemo, useEffect } from 'react'
import { Dialog } from 'primereact/dialog'
import { Button } from 'primereact/button'
import { InputTextarea } from 'primereact/inputtextarea'
import { Chips } from 'primereact/chips'
import { Message } from 'primereact/message'

type Trade = {
  trade_id: string
  package_id?: string
  package_type?: string | null
  execution_timestamp?: string
  notional?: number | null
  strike?: number | null
  trade_label?: string | null
  // Greeks
  straddle_vega01?: number | null
  straddle_dv01?: number | null
  outright_vega01?: number | null
  outright_dv01?: number | null
}

type ValidationWarning = {
  type: 'time' | 'vega' | 'dv01' | 'conflict' | 'info'
  severity: 'error' | 'warn' | 'info'
  message: string
}

type Props = {
  visible: boolean
  onHide: () => void
  selectedTrades: Trade[]
  onCreateLink: (tradeIds: string[], comment: string, tags: string[]) => Promise<boolean>
  conflictingLinks?: any[]
}

const SUGGESTED_TAGS = [
  'vega_hedge',
  'customer_flow',
  'time_spread',
  'block_trade',
  'package',
  'spread'
]

export function ManualLinkModal({
  visible,
  onHide,
  selectedTrades,
  onCreateLink,
  conflictingLinks = []
}: Props) {
  const [comment, setComment] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Reset form when modal opens/closes
  useEffect(() => {
    if (!visible) {
      setComment('')
      setTags([])
      setIsSubmitting(false)
    }
  }, [visible])

  // Compute metrics from selected trades
  const metrics = useMemo(() => {
    if (selectedTrades.length === 0) {
      return {
        totalVega01: null,
        netDV01: null,
        totalNotional: null,
        avgStrike: null,
        timeSpread: null
      }
    }

    const vega01Values = selectedTrades
      .map(t => t.straddle_vega01 || t.outright_vega01 || 0)
      .filter(v => !isNaN(v))

    const dv01Values = selectedTrades
      .map(t => t.straddle_dv01 || t.outright_dv01 || 0)
      .filter(v => !isNaN(v))

    const notionals = selectedTrades
      .map(t => t.notional || 0)
      .filter(v => !isNaN(v))

    const strikes = selectedTrades
      .map(t => t.strike)
      .filter((s): s is number => s !== null && s !== undefined && !isNaN(s))

    const timestamps = selectedTrades
      .map(t => t.execution_timestamp)
      .filter((ts): ts is string => !!ts)
      .map(ts => new Date(ts).getTime())

    const totalVega01 = vega01Values.length > 0
      ? vega01Values.reduce((sum, v) => sum + v, 0)
      : null

    const netDV01 = dv01Values.length > 0
      ? dv01Values.reduce((sum, v) => sum + v, 0)
      : null

    const totalNotional = notionals.length > 0
      ? notionals.reduce((sum, v) => sum + v, 0)
      : null

    const avgStrike = strikes.length > 0
      ? strikes.reduce((sum, v) => sum + v, 0) / strikes.length
      : null

    const timeSpread = timestamps.length > 1
      ? Math.max(...timestamps) - Math.min(...timestamps)
      : null

    return {
      totalVega01,
      netDV01,
      totalNotional,
      avgStrike,
      timeSpread
    }
  }, [selectedTrades])

  // Validate link and generate warnings
  const validations = useMemo((): ValidationWarning[] => {
    const warnings: ValidationWarning[] = []

    // Conflicts
    if (conflictingLinks.length > 0) {
      warnings.push({
        type: 'conflict',
        severity: 'error',
        message: `${conflictingLinks.length} trade(s) are already in active links`
      })
    }

    // Time proximity
    if (metrics.timeSpread !== null) {
      const minutes = metrics.timeSpread / 60000
      if (minutes > 60) {
        warnings.push({
          type: 'time',
          severity: 'warn',
          message: `Trades are ${Math.round(minutes)} minutes apart`
        })
      } else if (minutes < 1) {
        warnings.push({
          type: 'time',
          severity: 'info',
          message: `Trades within same minute (likely same package)`
        })
      }
    }

    // Vega check
    if (metrics.totalVega01 !== null) {
      if (Math.abs(metrics.totalVega01) < 100) {
        warnings.push({
          type: 'vega',
          severity: 'warn',
          message: `Very low total vega01: ${metrics.totalVega01.toFixed(0)}`
        })
      }
    }

    // DV01 check
    if (metrics.netDV01 !== null) {
      if (Math.abs(metrics.netDV01) > 1000) {
        warnings.push({
          type: 'dv01',
          severity: 'warn',
          message: `Large net DV01: $${Math.round(metrics.netDV01)} (not hedged?)`
        })
      } else if (Math.abs(metrics.netDV01) < 10) {
        warnings.push({
          type: 'dv01',
          severity: 'info',
          message: `Net DV01 near zero: $${Math.round(metrics.netDV01)} (well hedged)`
        })
      }
    }

    return warnings
  }, [metrics, conflictingLinks])

  const hasErrors = validations.some(v => v.severity === 'error')

  const handleSubmit = async () => {
    if (hasErrors || selectedTrades.length < 2) return

    setIsSubmitting(true)
    try {
      const tradeIds = selectedTrades.map(t => t.trade_id)
      const success = await onCreateLink(tradeIds, comment, tags)
      if (success) {
        onHide()
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const formatNumber = (value: number | null, decimals = 0): string => {
    if (value === null) return '—'
    return value.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    })
  }

  const footer = (
    <div className="flex justify-end gap-2">
      <Button
        label="Cancel"
        icon="pi pi-times"
        onClick={onHide}
        className="p-button-text"
        disabled={isSubmitting}
      />
      <Button
        label="Create Link"
        icon="pi pi-link"
        onClick={handleSubmit}
        disabled={hasErrors || isSubmitting || selectedTrades.length < 2}
        loading={isSubmitting}
      />
    </div>
  )

  return (
    <Dialog
      header={`Link ${selectedTrades.length} Trades`}
      visible={visible}
      onHide={onHide}
      footer={footer}
      style={{ width: '600px' }}
      modal
      dismissableMask
    >
      <div className="space-y-4">
        {/* Selected Trades Preview */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Selected Trades ({selectedTrades.length})
          </label>
          <div className="border border-gray-700 rounded p-3 max-h-48 overflow-y-auto space-y-2 bg-gray-900/50">
            {selectedTrades.map((trade) => (
              <div
                key={trade.trade_id}
                className="text-sm p-2 bg-gray-800/50 rounded flex justify-between"
              >
                <span className="font-mono text-xs">{trade.trade_id}</span>
                <span className="text-gray-400">
                  {trade.package_type || 'OUTRIGHT'} •{' '}
                  {formatNumber(trade.notional)} •{' '}
                  {trade.strike ? `${trade.strike}%` : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Computed Metrics */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Combined Metrics
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Total Vega01</div>
              <div className="text-lg font-mono">
                {formatNumber(metrics.totalVega01, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Net DV01</div>
              <div className="text-lg font-mono">
                ${formatNumber(metrics.netDV01, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Total Notional</div>
              <div className="text-lg font-mono">
                {formatNumber(metrics.totalNotional, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Time Spread</div>
              <div className="text-lg font-mono">
                {metrics.timeSpread !== null
                  ? `${Math.round(metrics.timeSpread / 60000)}m`
                  : '—'}
              </div>
            </div>
          </div>
        </div>

        {/* Validations */}
        {validations.length > 0 && (
          <div className="space-y-2">
            <label className="block text-sm font-medium">
              Validation Results
            </label>
            {validations.map((warning, idx) => (
              <Message
                key={idx}
                severity={warning.severity}
                text={warning.message}
                className="w-full"
              />
            ))}
          </div>
        )}

        {/* Comment */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Comment
          </label>
          <InputTextarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={3}
            placeholder="Why are these trades linked? (optional)"
            className="w-full"
          />
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium mb-2">
            Tags
          </label>
          <Chips
            value={tags}
            onChange={(e) => setTags(e.value || [])}
            placeholder="Add tags (e.g., vega_hedge)"
            className="w-full"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <span className="text-xs text-gray-400">Suggestions:</span>
            {SUGGESTED_TAGS.map(tag => (
              <button
                key={tag}
                onClick={() => {
                  if (!tags.includes(tag)) {
                    setTags([...tags, tag])
                  }
                }}
                className="text-xs px-2 py-1 rounded bg-gray-700 hover:bg-gray-600 transition-colors"
                disabled={tags.includes(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>
      </div>
    </Dialog>
  )
}
