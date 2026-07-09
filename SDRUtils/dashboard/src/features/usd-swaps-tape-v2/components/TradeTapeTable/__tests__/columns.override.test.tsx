/** @jest-environment jsdom */
import { describe, expect, it } from '@jest/globals'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { getColumns } from '../columns'

function renderPkg(row: any) {
  const cols = getColumns({ selection: false })
  const pkg = cols.find((c: any) => c.key === 'pkg') as any
  return render(<>{pkg.props.body(row)}</>)
}

describe('columns Pkg cell override markers', () => {
  it('shows the SPLIT badge for an override row', () => {
    renderPkg({ package_id: 'P1', package_type: 'CURVE', legs_json: [], override_type: 'SPLIT', override_map: { T1: 'o1' } })
    ;(expect(screen.getByText('SPLIT')) as any).toBeInTheDocument()
  })
  it('shows REGROUPED (not the auto ManualLinkBadge) for a GROUP row', () => {
    renderPkg({ package_id: 'P1', package_type: 'CURVE', legs_json: [], override_type: 'GROUP', manual_package_id: 'SMO-1', override_map: { T1: 'o1' } })
    ;(expect(screen.getByText('REGROUPED')) as any).toBeInTheDocument()
    expect(screen.queryByTestId('manual-link-badge')).toBeNull()
  })
})
