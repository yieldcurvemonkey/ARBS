/**
 * Example: SwaptionTradeTape with Manual Links integration
 *
 * This is a simplified example showing how to integrate manual linking.
 * For the full implementation, see MANUAL_LINKS_INTEGRATION.md
 */

'use client'

import { useState, useEffect, useMemo } from 'react'
import { DataTable } from 'primereact/datatable'
import { Column } from 'primereact/column'
import { Button } from 'primereact/button'
import { ConfirmDialog } from 'primereact/confirmdialog'
import { useManualLinks } from '@/hooks/useManualLinks'
import { ManualLinkModal } from './ManualLinkModal'
import { ManualLinkBadge } from './ManualLinkBadge'
import { ManualLinkPanel } from './ManualLinkPanel'
import type { ManualLink } from '@/hooks/useManualLinks'

// Simplified TapeRow type for example
type TapeRow = {
  package_id: string
  package_type: string | null
  execution_start: string
  execution_end: string
  total_notional: number | null
  total_premium: number | null
  tenor_label: string | null
  legs_count: number
  package_metrics: Record<string, any> | null
}

export default function SwaptionTradeTapeWithLinks() {
  // ========== EXISTING STATE ==========
  const [rows, setRows] = useState<TapeRow[]>([])
  const [loading, setLoading] = useState(false)

  // ========== NEW: MANUAL LINKS STATE ==========
  const {
    links,
    isLoading: linksLoading,
    loadLinks,
    createLink,
    updateLink,
    deleteLink,
    getLinksForTrades
  } = useManualLinks()

  const [selectedTrades, setSelectedTrades] = useState<Set<string>>(new Set())
  const [showLinkModal, setShowLinkModal] = useState(false)
  const [selectedLink, setSelectedLink] = useState<ManualLink | null>(null)
  const [showLinkPanel, setShowLinkPanel] = useState(false)

  // ========== DATA LOADING ==========
  useEffect(() => {
    loadData()
  }, [])

  // Load manual links when data loads
  useEffect(() => {
    if (rows.length > 0) {
      const start = rows[rows.length - 1].execution_start
      const end = rows[0].execution_start
      loadLinks(start, end)
    }
  }, [rows, loadLinks])

  const loadData = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/swaptions-tape?limit=100')
      const data = await response.json()
      setRows(data.rows || [])
    } catch (error) {
      console.error('Failed to load data:', error)
    } finally {
      setLoading(false)
    }
  }

  // ========== ENRICHED TRADES FOR MODAL ==========
  const selectedTradesData = useMemo(() => {
    return Array.from(selectedTrades)
      .map(id => rows.find(r => r.package_id === id))
      .filter((r): r is TapeRow => r !== undefined)
      .map(row => ({
        trade_id: row.package_id,
        package_id: row.package_id,
        package_type: row.package_type,
        execution_timestamp: row.execution_start,
        notional: row.total_notional,
        strike: null, // Would need to extract from legs_json
        trade_label: row.tenor_label,
        straddle_vega01: row.package_metrics?.straddle_vega01,
        straddle_dv01: row.package_metrics?.straddle_dv01,
        outright_vega01: row.package_metrics?.outright_vega01,
        outright_dv01: row.package_metrics?.outright_dv01
      }))
  }, [selectedTrades, rows])

  // ========== HANDLERS ==========
  const handleCreateLink = async (
    tradeIds: string[],
    comment: string,
    tags: string[]
  ): Promise<boolean> => {
    const link = await createLink({
      trade_ids: tradeIds,
      comment,
      tags,
      user: 'current_user@example.com' // TODO: Replace with actual user
    })

    if (link) {
      setSelectedTrades(new Set())
      return true
    }
    return false
  }

  const handleUpdateLink = async (
    linkId: string,
    comment: string,
    tags: string[]
  ): Promise<boolean> => {
    return await updateLink({ link_id: linkId, comment, tags })
  }

  const handleDeleteLink = async (linkId: string): Promise<boolean> => {
    return await deleteLink(linkId)
  }

  // ========== COLUMN TEMPLATES ==========
  const packageIdBodyTemplate = (rowData: TapeRow) => {
    const tradeLinks = getLinksForTrades([rowData.package_id])

    return (
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs">{rowData.package_id}</span>
        {tradeLinks.length > 0 && (
          <ManualLinkBadge
            tradeId={rowData.package_id}
            links={links}
            onClick={(link) => {
              setSelectedLink(link)
              setShowLinkPanel(true)
            }}
          />
        )}
      </div>
    )
  }

  const packageTypeBodyTemplate = (rowData: TapeRow) => {
    return (
      <span className="px-2 py-1 bg-purple-900/30 rounded text-xs">
        {rowData.package_type || 'OUTRIGHT'}
      </span>
    )
  }

  const notionalBodyTemplate = (rowData: TapeRow) => {
    if (rowData.total_notional === null) return '—'
    return rowData.total_notional.toLocaleString(undefined, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    })
  }

  // ========== RENDER ==========
  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Swaption Trade Tape</h1>
        <div className="flex items-center gap-3">
          <Button
            icon="pi pi-refresh"
            onClick={loadData}
            loading={loading}
            rounded
            text
          />
          {selectedTrades.size >= 2 && (
            <Button
              label={`Link ${selectedTrades.size} Trades`}
              icon="pi pi-link"
              onClick={() => setShowLinkModal(true)}
              severity="info"
              size="small"
            />
          )}
        </div>
      </div>

      {/* DataTable */}
      <DataTable
        value={rows}
        loading={loading || linksLoading}
        selection={Array.from(selectedTrades).map(id =>
          rows.find(r => r.package_id === id)
        )}
        onSelectionChange={(e) => {
          const ids = new Set(
            (e.value || []).map((r: TapeRow) => r.package_id)
          )
          setSelectedTrades(ids)
        }}
        dataKey="package_id"
        scrollable
        scrollHeight="70vh"
        virtualScrollerOptions={{ itemSize: 50 }}
        className="text-sm"
        showGridlines
        stripedRows
      >
        {/* Selection Column */}
        <Column
          selectionMode="multiple"
          headerStyle={{ width: '3rem' }}
          frozen
        />

        {/* Package ID with Link Badge */}
        <Column
          field="package_id"
          header="Package ID"
          body={packageIdBodyTemplate}
          style={{ minWidth: '200px' }}
          frozen
        />

        {/* Package Type */}
        <Column
          field="package_type"
          header="Type"
          body={packageTypeBodyTemplate}
          style={{ minWidth: '150px' }}
        />

        {/* Execution Time */}
        <Column
          field="execution_start"
          header="Time"
          body={(row: TapeRow) =>
            new Date(row.execution_start).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
            })
          }
          style={{ minWidth: '180px' }}
        />

        {/* Notional */}
        <Column
          field="total_notional"
          header="Notional"
          body={notionalBodyTemplate}
          style={{ minWidth: '130px' }}
          align="right"
        />

        {/* Tenor */}
        <Column
          field="tenor_label"
          header="Tenor"
          style={{ minWidth: '100px' }}
        />

        {/* Legs */}
        <Column
          field="legs_count"
          header="Legs"
          style={{ minWidth: '80px' }}
          align="center"
        />
      </DataTable>

      {/* Manual Link Modal */}
      <ManualLinkModal
        visible={showLinkModal}
        onHide={() => {
          setShowLinkModal(false)
          setSelectedTrades(new Set())
        }}
        selectedTrades={selectedTradesData}
        onCreateLink={handleCreateLink}
      />

      {/* Manual Link Panel */}
      <ManualLinkPanel
        visible={showLinkPanel}
        onHide={() => {
          setShowLinkPanel(false)
          setSelectedLink(null)
        }}
        link={selectedLink}
        trades={selectedTradesData}
        onUpdate={handleUpdateLink}
        onDelete={handleDeleteLink}
      />

      {/* Confirm Dialog (for delete confirmations) */}
      <ConfirmDialog />
    </div>
  )
}
