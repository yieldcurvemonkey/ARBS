// ABOUTME: Tests for the SequenceChainDetector — surfaces
// lifecycle / clustering links between selected trades and the
// loaded row set.
//
// The v1 detector walks `cluster_id` (a real column emitted by the
// Phase 1 ingest pipeline) since `original_dissemination_id` is
// not yet projected onto UsdSwapTapeRow at the dashboard layer.
// The plan accepts this as a v1 surface; the
// `original_dissemination_id` upgrade is flagged as a follow-up.
import { describe, expect, it } from '@jest/globals'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  detectSequenceChains,
  SequenceChainDetector,
} from '../SequenceChainDetector'
import type { FocusedTrade } from '../analytics-types'
import type { UsdSwapTapeRow } from '../../../types'

function focused(overrides: Partial<FocusedTrade> = {}): FocusedTrade {
  return {
    id: 'PKG-A',
    tape_label: 'USD-SOFR 5Y Outright',
    package_structure: 'OUTRIGHT',
    package_tenors: '5Y',
    trade_type: 'OUTRIGHT',
    tenor_years: 5,
    fixed_rate_bps: 380,
    weighted_fixed_rate: 0.038,
    dv01_usd_per_bp: 25_000,
    notional_usd: 50_000_000,
    pts: null,
    side: 'PAY',
    platform: 'CUSTY',
    venue: 'BBSF',
    execution_start: '2026-04-23T09:00:00Z',
    execution_session: 'AM',
    lifecycle_type: 'NEW_RISK',
    is_block: false,
    ...overrides,
  }
}

function row(overrides: Partial<UsdSwapTapeRow> = {}): UsdSwapTapeRow {
  return {
    package_id: 'PKG-A',
    package_type: 'OUTRIGHT',
    package_structure: 'OUTRIGHT',
    package_tenors: '5Y',
    cluster_id: null,
    legs_json: [],
    ...overrides,
  } as unknown as UsdSwapTapeRow
}

describe('detectSequenceChains', () => {
  it('returns no links when sequence is empty', () => {
    expect(detectSequenceChains([], [row()])).toEqual({
      sharedParentClusters: [],
      lifecycleHints: [],
    })
  })

  it('flags shared-parent when 2+ selected trades share a cluster_id', () => {
    const seq = [
      focused({ id: 'PKG-A' }),
      focused({ id: 'PKG-B' }),
      focused({ id: 'PKG-C' }),
    ]
    const rows = [
      row({ package_id: 'PKG-A', cluster_id: 'CLUSTER-1' }),
      row({ package_id: 'PKG-B', cluster_id: 'CLUSTER-1' }),
      row({ package_id: 'PKG-C', cluster_id: 'CLUSTER-2' }),
    ]
    const result = detectSequenceChains(seq, rows)
    expect(result.sharedParentClusters).toHaveLength(1)
    expect(result.sharedParentClusters[0].clusterId).toBe('CLUSTER-1')
    expect(result.sharedParentClusters[0].memberIds).toEqual(['PKG-A', 'PKG-B'])
  })

  it('flags lifecycle-type hint when a selected trade is a CORRECTION', () => {
    const seq = [focused({ id: 'PKG-A', lifecycle_type: 'CORRECTION' })]
    const result = detectSequenceChains(seq, [row({ package_id: 'PKG-A' })])
    expect(result.lifecycleHints).toHaveLength(1)
    expect(result.lifecycleHints[0].lifecycleType).toBe('CORRECTION')
  })

  it('flags lifecycle hints for COMPRESSION / TERMINATION / NOVATION', () => {
    const seq = [
      focused({ id: 'PKG-A', lifecycle_type: 'COMPRESSION' }),
      focused({ id: 'PKG-B', lifecycle_type: 'TERMINATION' }),
      focused({ id: 'PKG-C', lifecycle_type: 'NOVATION' }),
    ]
    const result = detectSequenceChains(seq, [
      row({ package_id: 'PKG-A' }),
      row({ package_id: 'PKG-B' }),
      row({ package_id: 'PKG-C' }),
    ])
    expect(result.lifecycleHints).toHaveLength(3)
    expect(result.lifecycleHints.map((h) => h.lifecycleType).sort()).toEqual(
      ['COMPRESSION', 'NOVATION', 'TERMINATION'].sort(),
    )
  })

  it('does NOT flag NEW_RISK as a lifecycle link', () => {
    const seq = [focused({ id: 'PKG-A', lifecycle_type: 'NEW_RISK' })]
    const result = detectSequenceChains(seq, [row({ package_id: 'PKG-A' })])
    expect(result.lifecycleHints).toHaveLength(0)
  })
})

describe('SequenceChainDetector render', () => {
  it('renders the v1 empty state when no chains/hints exist', () => {
    const html = renderToStaticMarkup(
      <SequenceChainDetector
        sequence={[focused({ lifecycle_type: 'NEW_RISK' })]}
        rows={[row()]}
      />,
    )
    expect(html).toMatch(/No sequence-level chain hints/i)
  })

  it('renders shared-parent cluster chips when present', () => {
    const seq = [
      focused({ id: 'PKG-A' }),
      focused({ id: 'PKG-B' }),
    ]
    const rows = [
      row({ package_id: 'PKG-A', cluster_id: 'CLUSTER-1' }),
      row({ package_id: 'PKG-B', cluster_id: 'CLUSTER-1' }),
    ]
    const html = renderToStaticMarkup(
      <SequenceChainDetector sequence={seq} rows={rows} />,
    )
    expect(html).toMatch(/CLUSTER-1/)
    expect(html).toMatch(/Shared cluster|shared parent/i)
  })

  it('renders lifecycle hint chips when present', () => {
    const html = renderToStaticMarkup(
      <SequenceChainDetector
        sequence={[focused({ id: 'PKG-A', lifecycle_type: 'CORRECTION' })]}
        rows={[row({ package_id: 'PKG-A' })]}
      />,
    )
    expect(html).toMatch(/CORRECTION/)
  })
})
