// ABOUTME: Dedicated Vol Plotter page under USD Rates Vol Analytics.
import { Suspense } from 'react'

import VolGridDashboard from '@/features/vol-grid/components/VolGridDashboard'

export default function AtmfGridVolatilitySurfacePage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <VolGridDashboard initialTab="surface" lockTab />
    </Suspense>
  )
}
