/**
 * @jest-environment jsdom
 */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LegsSubTable } from '../LegsSubTable'

const row = {
  package_id: 'P1',
  package_type: 'CURVE',
  legs_json: [
    { trade_id: 'T1', tenor_years: 2 },
    { trade_id: 'T2', tenor_years: 5 },
  ],
} as any

describe('LegsSubTable selection + notes', () => {
  it('renders a checkbox per leg and toggles the trade id', () => {
    const onToggleTrade = jest.fn()
    render(
      <LegsSubTable
        row={row}
        selectedTradeIds={new Set(['T1'])}
        onToggleTrade={onToggleTrade}
      />,
    )
    const cbT1 = screen.getByLabelText('select leg T1') as HTMLInputElement
    const cbT2 = screen.getByLabelText('select leg T2') as HTMLInputElement
    expect(cbT1.checked).toBe(true)
    expect(cbT2.checked).toBe(false)
    fireEvent.click(cbT2)
    expect(onToggleTrade).toHaveBeenCalledWith('T2', 'P1')
  })

  it('opens a TRADE note target from the per-leg note icon', () => {
    const onOpenNote = jest.fn()
    render(<LegsSubTable row={row} onOpenNote={onOpenNote} />)
    fireEvent.click(screen.getByLabelText('notes for leg T1'))
    expect(onOpenNote).toHaveBeenCalledWith({ target_type: 'TRADE', target_id: 'T1' })
  })
})
