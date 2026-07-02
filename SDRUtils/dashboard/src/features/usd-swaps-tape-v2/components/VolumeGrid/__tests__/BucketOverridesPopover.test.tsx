/**
 * @jest-environment jsdom
 */
import { describe, expect, it, jest, beforeAll } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { BucketOverridesPopover } from '../BucketOverridesPopover'

const BUCKETS = [
  { id: 'spot', label: 'Spot' },
  { id: '1w-3m', label: '1W-3M' },
  { id: '3m-6m', label: '3M-6M' },
]

describe('BucketOverridesPopover', () => {
  it('renders gear icon button', () => {
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={jest.fn()}
      />,
    )
    ;(expect(screen.getByLabelText('Customize buckets')) as any).toBeInTheDocument()
  })

  it('toggles popover open on click', () => {
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={jest.fn()}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    ;(expect(screen.getByText('Spot')) as any).toBeInTheDocument()
    ;(expect(screen.getByText('1W-3M')) as any).toBeInTheDocument()
  })

  it('unchecking a bucket adds to hidden', () => {
    const onChange = jest.fn()
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: [], merged: [] }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    const checkbox = screen.getByLabelText('Spot')
    fireEvent.click(checkbox)
    expect(onChange).toHaveBeenCalledWith({ hidden: ['spot'], merged: [] })
  })

  it('reset button clears overrides', () => {
    const onChange = jest.fn()
    render(
      <BucketOverridesPopover
        buckets={BUCKETS}
        overrides={{ hidden: ['spot'], merged: [] }}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByLabelText('Customize buckets'))
    fireEvent.click(screen.getByText('Reset'))
    expect(onChange).toHaveBeenCalledWith({ hidden: [], merged: [] })
  })
})
