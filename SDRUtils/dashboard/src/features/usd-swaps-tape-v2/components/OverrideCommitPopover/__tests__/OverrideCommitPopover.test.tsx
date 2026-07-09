/** @jest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { OverrideCommitPopover } from '../OverrideCommitPopover'

describe('OverrideCommitPopover', () => {
  let originalFetch: typeof fetch
  let fetchMock: jest.Mock<any>
  beforeEach(() => {
    originalFetch = global.fetch
    fetchMock = jest.fn() as jest.Mock<any>
    ;(global as any).fetch = fetchMock
  })
  afterEach(() => {
    ;(global as any).fetch = originalFetch
  })
  const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body } as any)

  function renderPopover(props: Partial<React.ComponentProps<typeof OverrideCommitPopover>> = {}) {
    const onSuccess = jest.fn()
    const onCancel = jest.fn()
    const onPasswordChange = jest.fn()
    render(
      <OverrideCommitPopover
        overrideType="GROUP"
        tradeIds={['t1', 't2']}
        user="chris"
        password="pw"
        onPasswordChange={onPasswordChange}
        onSuccess={onSuccess}
        onCancel={onCancel}
        {...props}
      />,
    )
    return { onSuccess, onCancel, onPasswordChange }
  }

  it('renders the override type + trade count header', () => {
    renderPopover()
    ;(expect(screen.getByText(/GROUP/)) as any).toBeInTheDocument()
    ;(expect(screen.getByText(/2 trades/)) as any).toBeInTheDocument()
  })

  it('Validate calls validateOverride and shows validation messages', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'warning', code: 'W', message: 'heads up' }], metrics: {}, linked_trade_ids: [] }),
    )
    renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }))
    await waitFor(() => (expect(screen.getByText('heads up')) as any).toBeInTheDocument())
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.validate_only).toBe(true)
  })

  it('Commit calls createOverride and fires onSuccess', async () => {
    fetchMock.mockResolvedValue(
      ok({ success: true, override_id: 'o1', manual_package_id: 'SMO-1', validation: [], metrics: {} }),
    )
    const { onSuccess } = renderPopover()
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'customer flow' } })
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await waitFor(() => expect(onSuccess).toHaveBeenCalled())
    expect(onSuccess.mock.calls[0][0]).toMatchObject({ override_id: 'o1' })
    const sent = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))
    expect(sent.reason).toBe('customer flow')
    expect(sent.validate_only).toBeUndefined()
  })

  it('surfaces the server error message inline (403)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 403, json: async () => ({ error: 'Invalid override password.' }) } as any)
    const { onSuccess } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Commit' }))
    await waitFor(() => (expect(screen.getByRole('alert')) as any).toHaveTextContent('Invalid override password.'))
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('disables Commit when a validation error is present', async () => {
    fetchMock.mockResolvedValue(
      ok({ validation: [{ level: 'error', code: 'E', message: 'bad' }], metrics: {}, linked_trade_ids: [] }),
    )
    renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Validate' }))
    await waitFor(() => (expect(screen.getByText('bad')) as any).toBeInTheDocument())
    ;(expect(screen.getByRole('button', { name: 'Commit' })) as any).toBeDisabled()
  })

  it('fires onCancel', () => {
    const { onCancel } = renderPopover()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
  })
})
