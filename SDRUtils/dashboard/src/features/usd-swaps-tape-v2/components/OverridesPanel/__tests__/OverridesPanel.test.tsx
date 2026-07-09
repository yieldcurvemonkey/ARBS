/** @jest-environment jsdom */
import { describe, expect, it, jest, beforeEach } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import type { TapeOverride } from '../../../types/override.types'
import type { OverrideHistoryRow } from '../../../api/overrideApi'

// Typed per the precedent in NotePopover.test.tsx: an untyped jest.fn() here
// infers a `never` parameter type from jest's UnknownFunction default, which
// tsc rejects once mockResolvedValue/mockRejectedValue is called with
// concrete payloads below.
const fetchOverrides = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const deactivateOverride = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const fetchOverrideDetail = jest.fn<(...args: unknown[]) => Promise<unknown>>()
const createOverride = jest.fn<(...args: unknown[]) => Promise<unknown>>()
jest.unstable_mockModule('../../../api/overrideApi', () => ({
  fetchOverrides,
  deactivateOverride,
  fetchOverrideDetail,
  createOverride,
}))
const { OverridesPanel } = await import('../OverridesPanel')

const SAMPLE_OVERRIDE: TapeOverride = {
  override_id: 'OV-1',
  override_type: 'GROUP',
  manual_package_id: 'SMO-1',
  trade_ids: ['t1', 't2'],
  created_by: 'chris',
  created_at: '2026-07-08T00:00:00Z',
  updated_at: null,
  is_active: true,
  reason: null,
  tags: null,
  metrics: {},
}

// The backend GET history query (route.ts: `SELECT history_id, action,
// changed_by, changed_at, change_details, previous_state FROM ...`) never
// selects override_id despite filtering on it, so real history rows arrive
// with override_id === undefined even though OverrideHistoryRow types it as
// string. Mirror that gap here so a revert-path regression (accidentally
// keying off history[].override_id instead of the row's own TapeOverride)
// fails this test instead of shipping.
const SAMPLE_HISTORY: OverrideHistoryRow[] = [
  {
    history_id: 1,
    action: 'CREATE',
    changed_by: 'chris',
    changed_at: '2026-07-08T00:05:00Z',
    change_details: null,
    previous_state: null,
  } as unknown as OverrideHistoryRow,
]

beforeEach(() => {
  fetchOverrides.mockReset().mockResolvedValue({ rows: [SAMPLE_OVERRIDE] })
  deactivateOverride.mockReset().mockResolvedValue({ success: true })
  fetchOverrideDetail.mockReset().mockResolvedValue({
    override: SAMPLE_OVERRIDE,
    members: [],
    history: SAMPLE_HISTORY,
  })
  createOverride.mockReset()
})

describe('OverridesPanel', () => {
  it('lists active overrides on open', async () => {
    render(
      <OverridesPanel user="chris" adminPassword="secret" onClose={jest.fn()} onReverted={jest.fn()} />,
    )
    expect(fetchOverrides).toHaveBeenCalledWith({ is_active: true })
    await waitFor(() => (expect(screen.getByTestId('override-row-OV-1')) as any).toBeInTheDocument())
    ;(expect(screen.getByText('GROUP')) as any).toBeInTheDocument()
    ;(expect(screen.getByText('SMO-1')) as any).toBeInTheDocument()
  })

  it("reverts using the row's own override_id, never history[].override_id", async () => {
    const onReverted = jest.fn()
    render(
      <OverridesPanel user="chris" adminPassword="secret" onClose={jest.fn()} onReverted={onReverted} />,
    )
    await waitFor(() => (expect(screen.getByTestId('override-row-OV-1')) as any).toBeInTheDocument())

    // Load history first -- it resolves rows whose override_id is undefined
    // (see SAMPLE_HISTORY comment above). If the revert path is ever rewired
    // to read an id off the loaded history instead of the row's own
    // TapeOverride, this proves the bug before it ships, not after.
    fireEvent.click(screen.getByRole('button', { name: 'History' }))
    await waitFor(() => (expect(screen.getByText('CREATE')) as any).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'revert override OV-1' }))

    await waitFor(() => expect(deactivateOverride).toHaveBeenCalled())
    expect(deactivateOverride).toHaveBeenCalledWith('OV-1', {
      user: 'chris',
      admin_password: 'secret',
    })
    expect(deactivateOverride).not.toHaveBeenCalledWith(undefined, expect.anything())

    await waitFor(() => expect(onReverted).toHaveBeenCalled())
    expect(onReverted.mock.calls[0]?.[0]).toBe('OV-1')
    expect(onReverted.mock.calls[0]?.[0]).not.toBeUndefined()
  })

  it('renders an inline error when fetchOverrides fails', async () => {
    fetchOverrides.mockReset().mockRejectedValue(new Error('network down'))
    render(
      <OverridesPanel user="chris" adminPassword="secret" onClose={jest.fn()} onReverted={jest.fn()} />,
    )
    await waitFor(() => (expect(screen.getByRole('alert')) as any).toHaveTextContent('network down'))
  })
})
