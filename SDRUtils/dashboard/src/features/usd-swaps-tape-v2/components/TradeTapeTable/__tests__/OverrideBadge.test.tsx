/**
 * @jest-environment jsdom
 */
import { describe, expect, it, jest } from '@jest/globals'
import { render, screen, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'
import { OverrideBadge } from '../OverrideBadge'

describe('OverrideBadge', () => {
  it('renders a REGROUPED label + package id for GROUP', () => {
    render(<OverrideBadge overrideType="GROUP" manualPackageId="SMO-20260708-ABCD1234" />)
    ;(expect(screen.getByText('REGROUPED')) as any).toBeInTheDocument()
    ;(expect(screen.getByText('SMO-20260708-ABCD1234')) as any).toBeInTheDocument()
  })

  it('renders SPLIT and DETACH labels', () => {
    const { rerender } = render(<OverrideBadge overrideType="SPLIT" />)
    ;(expect(screen.getByText('SPLIT')) as any).toBeInTheDocument()
    rerender(<OverrideBadge overrideType="DETACH" />)
    ;(expect(screen.getByText('DETACHED')) as any).toBeInTheDocument()
  })

  it('is a button that fires onClick(overrideId) when both provided', () => {
    const onClick = jest.fn()
    render(<OverrideBadge overrideType="GROUP" overrideId="o1" onClick={onClick} />)
    fireEvent.click(screen.getByTestId('override-badge'))
    expect(onClick).toHaveBeenCalledWith('o1')
  })

  it('renders a static span when no onClick', () => {
    render(<OverrideBadge overrideType="SPLIT" />)
    expect(screen.getByTestId('override-badge').tagName).toBe('SPAN')
  })
})
