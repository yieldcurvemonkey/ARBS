'use client'
// ABOUTME: Sub-component of SequenceTab — surfaces sequence-level
// chain hints derived from the loaded row set + the selected
// trades. v1 surface walks two signals already projected onto
// UsdSwapTapeRow:
//
//  1. Shared cluster_id: when 2+ selected packages share the same
//     cluster_id (assigned by the Phase 2 lifecycle aggregator),
//     this is strong evidence the package chain is the same — e.g.
//     a NEWT followed by a CORR followed by a TERM.
//
//  2. Lifecycle type hints: a selected package whose lifecycle_type
//     is CORRECTION / COMPRESSION / TERMINATION / NOVATION /
//     RESET_OPT / CLEARING_TERM / EXERCISE_BORN / AMENDMENT
//     carries pricing-relevant context that's worth surfacing as a
//     chip.
//
// TODO: when the dashboard projects `original_dissemination_id`
// from the v2 schema (Phase 2 of the row schema, currently only
// surfaced in the leg-level d2_missing flag), upgrade this
// detector to walk parent → child links. The shared_parent v1
// proxy via cluster_id is conservative.
import type { JSX } from 'react'
import { useMemo } from 'react'
import type { FocusedTrade } from './analytics-types'
import type { LifecycleType, UsdSwapTapeRow } from '../../types'

const NOTABLE_LIFECYCLE_TYPES: ReadonlySet<LifecycleType> = new Set([
  'CORRECTION',
  'COMPRESSION',
  'TERMINATION',
  'NOVATION',
  'RESET_OPT',
  'CLEARING_TERM',
  'EXERCISE_BORN',
  'AMENDMENT',
  'NULL_FILL',
  'SCHED_AMORT',
  'PORT_TRANSFER',
])

export interface SharedParentCluster {
  clusterId: string
  memberIds: string[]
}

export interface SequenceLifecycleHint {
  tradeId: string
  tradeLabel: string
  lifecycleType: LifecycleType
}

export interface SequenceChainResult {
  sharedParentClusters: SharedParentCluster[]
  lifecycleHints: SequenceLifecycleHint[]
}

export function detectSequenceChains(
  sequence: readonly FocusedTrade[],
  rows: readonly UsdSwapTapeRow[],
): SequenceChainResult {
  if (sequence.length === 0) {
    return { sharedParentClusters: [], lifecycleHints: [] }
  }

  // Index loaded rows by package_id so cluster_id lookups stay O(1)
  // per selected trade — important on bigger row sets.
  const rowsById = new Map<string, UsdSwapTapeRow>()
  for (const r of rows) {
    if (r.package_id != null) rowsById.set(String(r.package_id), r)
  }

  // Group selected trades by their loaded row's cluster_id.
  const clusterMap = new Map<string, string[]>()
  for (const trade of sequence) {
    const r = rowsById.get(trade.id)
    const cid = r?.cluster_id
    if (!cid) continue
    const list = clusterMap.get(cid) ?? []
    list.push(trade.id)
    clusterMap.set(cid, list)
  }
  const sharedParentClusters: SharedParentCluster[] = []
  for (const [clusterId, memberIds] of clusterMap.entries()) {
    if (memberIds.length >= 2) {
      sharedParentClusters.push({ clusterId, memberIds })
    }
  }

  // Lifecycle hints — surface notable lifecycle types directly.
  const lifecycleHints: SequenceLifecycleHint[] = []
  for (const trade of sequence) {
    const lt = trade.lifecycle_type
    if (lt && NOTABLE_LIFECYCLE_TYPES.has(lt as LifecycleType)) {
      lifecycleHints.push({
        tradeId: trade.id,
        tradeLabel: trade.tape_label,
        lifecycleType: lt as LifecycleType,
      })
    }
  }

  return { sharedParentClusters, lifecycleHints }
}

export interface SequenceChainDetectorProps {
  sequence: readonly FocusedTrade[]
  rows: readonly UsdSwapTapeRow[]
}

export function SequenceChainDetector({
  sequence,
  rows,
}: SequenceChainDetectorProps): JSX.Element {
  const result = useMemo(
    () => detectSequenceChains(sequence, rows),
    [sequence, rows],
  )

  const hasContent =
    result.sharedParentClusters.length > 0 || result.lifecycleHints.length > 0

  if (!hasContent) {
    return (
      <div
        data-testid="sequence-chain-detector-empty"
        className="rounded border border-dashed border-slate-800 bg-slate-950/40 px-3 py-3 font-mono text-[11px] text-slate-500"
      >
        No sequence-level chain hints in the loaded row set.
      </div>
    )
  }

  return (
    <div
      data-testid="sequence-chain-detector"
      className="flex flex-col gap-2 rounded border border-slate-800 bg-slate-950/40 p-2"
    >
      {result.sharedParentClusters.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
            Shared cluster
          </div>
          <div className="flex flex-wrap gap-1">
            {result.sharedParentClusters.map((c) => (
              <span
                key={`cluster-${c.clusterId}`}
                data-testid={`sequence-cluster-${c.clusterId}`}
                className="rounded bg-fuchsia-500/15 px-1.5 py-[2px] font-mono text-[10px] text-fuchsia-200 ring-1 ring-fuchsia-500/30"
                title={`${c.memberIds.length} selected trades share cluster ${c.clusterId}`}
              >
                {c.clusterId} · {c.memberIds.length}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {result.lifecycleHints.length > 0 ? (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
            Lifecycle context
          </div>
          <div className="flex flex-wrap gap-1">
            {result.lifecycleHints.map((h) => (
              <span
                key={`lc-${h.tradeId}`}
                className="rounded bg-amber-500/15 px-1.5 py-[2px] font-mono text-[10px] text-amber-100 ring-1 ring-amber-500/30"
                title={h.tradeLabel}
              >
                {h.lifecycleType}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
