import { Suspense } from 'react'

import OpenInterestAndVolumeDashboard from '@/features/listed-option-oi-volume/components/OpenInterestAndVolumeDashboard'

export default function OpenInterestAndVolumeDashboardPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <OpenInterestAndVolumeDashboard />
    </Suspense>
  )
}
