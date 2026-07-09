/** @jest-environment jsdom */
import { describe, expect, it } from '@jest/globals'
import { renderHook, act } from '@testing-library/react'
import { useTradeSelection } from '../useTradeSelection'

describe('useTradeSelection', () => {
  it('starts empty', () => {
    const { result } = renderHook(() => useTradeSelection())
    expect(result.current.count).toBe(0)
    expect(result.current.selectedTradeIds.size).toBe(0)
    expect(result.current.selectedByPackage.size).toBe(0)
  })

  it('toggleTrade adds then removes a trade under its package', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    expect(result.current.selectedTradeIds.has('t1')).toBe(true)
    expect(result.current.selectedByPackage.get('PKG1')).toEqual(['t1'])
    expect(result.current.count).toBe(1)
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    expect(result.current.count).toBe(0)
    expect(result.current.selectedByPackage.has('PKG1')).toBe(false)
  })

  it('togglePackage selects all legs, and toggling again clears them', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(3)
    expect(new Set(result.current.selectedByPackage.get('PKG1'))).toEqual(new Set(['t1', 't2', 't3']))
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(0)
  })

  it('togglePackage re-selects the full set when only partially selected', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    act(() => result.current.togglePackage('PKG1', ['t1', 't2', 't3']))
    expect(result.current.count).toBe(3)
  })

  it('tracks multiple packages independently and clears all', () => {
    const { result } = renderHook(() => useTradeSelection())
    act(() => result.current.toggleTrade('t1', 'PKG1'))
    act(() => result.current.toggleTrade('t9', 'PKG2'))
    expect(result.current.selectedByPackage.size).toBe(2)
    expect(result.current.count).toBe(2)
    act(() => result.current.clear())
    expect(result.current.count).toBe(0)
    expect(result.current.selectedByPackage.size).toBe(0)
  })
})
