/** @jest-environment jsdom */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { RegroupActionBar } from '../RegroupActionBar'
import type { SelectionContext } from '../../../hooks/useSelectionContext'

const ALL_OFF: SelectionContext = {
  canGroup: false, canSplit: false, canDetach: false, canNote: false,
}

describe('RegroupActionBar', () => {
  it('shows the selected count', () => {
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ ...ALL_OFF, canGroup: true }}
        onAction={jest.fn()}
        onClear={jest.fn()}
      />,
    )
    ;(expect(screen.getByText('2 selected')) as any).toBeInTheDocument()
  })

  it('enables only the actions allowed by context', () => {
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ canGroup: true, canSplit: false, canDetach: true, canNote: true }}
        onAction={jest.fn()}
        onClear={jest.fn()}
      />,
    )
    ;(expect(screen.getByRole('button', { name: 'Group' })) as any).toBeEnabled()
    ;(expect(screen.getByRole('button', { name: 'Split' })) as any).toBeDisabled()
    ;(expect(screen.getByRole('button', { name: 'Detach' })) as any).toBeEnabled()
    ;(expect(screen.getByRole('button', { name: 'Note' })) as any).toBeEnabled()
  })

  it('fires onAction with the action key', () => {
    const onAction = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a', 'b'])}
        context={{ ...ALL_OFF, canGroup: true }}
        onAction={onAction}
        onClear={jest.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))
    expect(onAction).toHaveBeenCalledWith('GROUP')
  })

  it('disabled action does not fire onAction', () => {
    const onAction = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a'])}
        context={ALL_OFF}
        onAction={onAction}
        onClear={jest.fn()}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Group' }))
    expect(onAction).not.toHaveBeenCalled()
  })

  it('fires onClear', () => {
    const onClear = jest.fn()
    render(
      <RegroupActionBar
        selectedTradeIds={new Set(['a'])}
        context={ALL_OFF}
        onAction={jest.fn()}
        onClear={onClear}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(onClear).toHaveBeenCalled()
  })
})
