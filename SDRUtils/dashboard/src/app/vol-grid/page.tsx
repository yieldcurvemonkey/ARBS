// ABOUTME: Vol Grid page - Live ATMF swaption vol surface calibrated from SDR trade prints.
import { Suspense } from 'react'
import { VolGrid } from '@/features/vol-grid/components/VolGrid'

export default function VolGridPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading vol grid...</div>}>
      <VolGrid />
    </Suspense>
  )
}
