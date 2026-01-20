/**
 * Side panel for viewing and editing manual link details
 */

'use client'

import { useState, useEffect, useMemo } from 'react'
import { Sidebar } from 'primereact/sidebar'
import { Button } from 'primereact/button'
import { InputTextarea } from 'primereact/inputtextarea'
import { Chips } from 'primereact/chips'
import { confirmDialog } from 'primereact/confirmdialog'
import type { ManualLink } from '@/hooks/useManualLinks'

type Trade = {
  trade_id: string
  package_id?: string
  package_type?: string | null
  execution_timestamp?: string
  notional?: number | null
  strike?: number | null
  premium?: number | null
  trade_label?: string | null
  straddle_vega01?: number | null
  straddle_dv01?: number | null
  outright_vega01?: number | null
  outright_dv01?: number | null
}

type Props = {
  visible: boolean
  onHide: () => void
  link: ManualLink | null
  trades: Trade[]
  onUpdate: (linkId: string, comment: string, tags: string[]) => Promise<boolean>
  onDelete: (linkId: string) => Promise<boolean>
}

export function ManualLinkPanel({
  visible,
  onHide,
  link,
  trades,
  onUpdate,
  onDelete
}: Props) {
  const [isEditing, setIsEditing] = useState(false)
  const [editComment, setEditComment] = useState('')
  const [editTags, setEditTags] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)

  // Reset edit state when link changes
  useEffect(() => {
    if (link) {
      setEditComment(link.user_comment || '')
      setEditTags(link.tags || [])
      setIsEditing(false)
    }
  }, [link])

  // Get trades in this link
  const linkedTrades = useMemo(() => {
    if (!link) return []
    return trades.filter(t => link.linked_trade_ids.includes(t.trade_id))
  }, [link, trades])

  // Compute aggregate metrics
  const metrics = useMemo(() => {
    if (linkedTrades.length === 0) {
      return {
        totalVega01: null,
        netDV01: null,
        totalNotional: null,
        totalPremium: null
      }
    }

    const vega01Values = linkedTrades
      .map(t => t.straddle_vega01 || t.outright_vega01 || 0)
      .filter(v => !isNaN(v))

    const dv01Values = linkedTrades
      .map(t => t.straddle_dv01 || t.outright_dv01 || 0)
      .filter(v => !isNaN(v))

    const notionals = linkedTrades
      .map(t => t.notional || 0)
      .filter(v => !isNaN(v))

    const premiums = linkedTrades
      .map(t => t.premium || 0)
      .filter(v => !isNaN(v))

    return {
      totalVega01: vega01Values.reduce((sum, v) => sum + v, 0),
      netDV01: dv01Values.reduce((sum, v) => sum + v, 0),
      totalNotional: notionals.reduce((sum, v) => sum + v, 0),
      totalPremium: premiums.reduce((sum, v) => sum + v, 0)
    }
  }, [linkedTrades])

  const formatNumber = (value: number | null, decimals = 0): string => {
    if (value === null) return '—'
    return value.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    })
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const handleSave = async () => {
    if (!link) return

    setIsSaving(true)
    try {
      const success = await onUpdate(link.link_id, editComment, editTags)
      if (success) {
        setIsEditing(false)
      }
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = () => {
    if (!link) return

    confirmDialog({
      message: `Are you sure you want to unlink these ${link.linked_trade_ids.length} trades? This action cannot be undone.`,
      header: 'Delete Link',
      icon: 'pi pi-exclamation-triangle',
      acceptClassName: 'p-button-danger',
      accept: async () => {
        const success = await onDelete(link.link_id)
        if (success) {
          onHide()
        }
      }
    })
  }

  if (!link) return null

  return (
    <Sidebar
      visible={visible}
      onHide={onHide}
      position="right"
      style={{ width: '500px' }}
      modal={false}
      dismissable
      showCloseIcon
    >
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h2 className="text-xl font-semibold mb-2">Manual Link Details</h2>
          <div className="text-sm text-gray-400">
            <div>Created by {link.created_by}</div>
            <div>{formatDate(link.created_at)}</div>
            {link.updated_at && (
              <div className="text-xs mt-1">
                Last updated {formatDate(link.updated_at)}
              </div>
            )}
          </div>
        </div>

        {/* Tags */}
        <div>
          <label className="block text-sm font-medium mb-2">Tags</label>
          {isEditing ? (
            <Chips
              value={editTags}
              onChange={(e) => setEditTags(e.value || [])}
              placeholder="Add tags"
              className="w-full"
            />
          ) : (
            <div className="flex flex-wrap gap-2">
              {link.tags && link.tags.length > 0 ? (
                link.tags.map((tag: string) => (
                  <span
                    key={tag}
                    className="px-2 py-1 bg-blue-900/50 text-blue-200 rounded text-sm"
                  >
                    {tag}
                  </span>
                ))
              ) : (
                <span className="text-gray-500 text-sm">No tags</span>
              )}
            </div>
          )}
        </div>

        {/* Comment */}
        <div>
          <label className="block text-sm font-medium mb-2">Comment</label>
          {isEditing ? (
            <InputTextarea
              value={editComment}
              onChange={(e) => setEditComment(e.target.value)}
              rows={4}
              placeholder="Add a comment"
              className="w-full"
            />
          ) : (
            <div className="p-3 bg-gray-900/50 border border-gray-700 rounded text-sm">
              {link.user_comment || (
                <span className="text-gray-500 italic">No comment</span>
              )}
            </div>
          )}
        </div>

        {/* Edit Actions */}
        <div className="flex gap-2">
          {isEditing ? (
            <>
              <Button
                label="Save"
                icon="pi pi-check"
                onClick={handleSave}
                loading={isSaving}
                disabled={isSaving}
                size="small"
              />
              <Button
                label="Cancel"
                icon="pi pi-times"
                onClick={() => {
                  setEditComment(link.user_comment || '')
                  setEditTags(link.tags || [])
                  setIsEditing(false)
                }}
                className="p-button-text"
                size="small"
              />
            </>
          ) : (
            <Button
              label="Edit"
              icon="pi pi-pencil"
              onClick={() => setIsEditing(true)}
              size="small"
            />
          )}
        </div>

        {/* Aggregate Metrics */}
        <div>
          <label className="block text-sm font-medium mb-3">
            Combined Metrics
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Total Vega01</div>
              <div className="text-xl font-mono font-semibold mt-1">
                {formatNumber(metrics.totalVega01, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Net DV01</div>
              <div className="text-xl font-mono font-semibold mt-1">
                ${formatNumber(metrics.netDV01, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Total Notional</div>
              <div className="text-xl font-mono font-semibold mt-1">
                {formatNumber(metrics.totalNotional, 0)}
              </div>
            </div>
            <div className="border border-gray-700 rounded p-3 bg-gray-900/50">
              <div className="text-xs text-gray-400">Total Premium</div>
              <div className="text-xl font-mono font-semibold mt-1">
                {formatNumber(metrics.totalPremium, 0)}
              </div>
            </div>
          </div>
        </div>

        {/* Linked Trades */}
        <div>
          <label className="block text-sm font-medium mb-3">
            Linked Trades ({linkedTrades.length})
          </label>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {linkedTrades.map((trade) => (
              <div
                key={trade.trade_id}
                className="border border-gray-700 rounded p-3 bg-gray-900/50 text-sm space-y-1"
              >
                <div className="flex justify-between items-start">
                  <span className="font-mono text-xs text-gray-400">
                    {trade.trade_id}
                  </span>
                  <span className="px-2 py-0.5 bg-purple-900/50 text-purple-200 rounded text-xs">
                    {trade.package_type || 'OUTRIGHT'}
                  </span>
                </div>
                <div className="text-gray-300">
                  {trade.trade_label || '—'}
                </div>
                <div className="flex justify-between text-xs text-gray-400">
                  <span>Notional: {formatNumber(trade.notional, 0)}</span>
                  <span>Strike: {trade.strike ? `${trade.strike}%` : '—'}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Delete Button */}
        <div className="pt-4 border-t border-gray-700">
          <Button
            label="Unlink Trades"
            icon="pi pi-trash"
            onClick={handleDelete}
            className="p-button-danger p-button-outlined w-full"
            size="small"
          />
        </div>
      </div>
    </Sidebar>
  )
}
