// ABOUTME: Live ATMF Vol Grid dashboard page.
import { Suspense } from 'react'
import VolGridDashboard from '@/features/vol-grid/components/VolGridDashboard'

export default function VolGridPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <VolGridDashboard />
    </Suspense>
  )
}
