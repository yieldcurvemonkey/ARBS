// ABOUTME: Live ATMF Vol Grid page nested under USD Rates Vol Analytics.
import { Suspense } from 'react'

import VolGridDashboard from '@/features/vol-grid/components/VolGridDashboard'

export default function AtmfVolGridPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <VolGridDashboard initialTab="grid" lockTab showDatePicker={false} />
    </Suspense>
  )
}
