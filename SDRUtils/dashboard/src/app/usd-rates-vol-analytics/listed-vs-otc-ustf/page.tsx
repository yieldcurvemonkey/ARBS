import { Suspense } from 'react'

import UstfVolDashboard from '@/features/ustf-vol/components/UstfVolDashboard'

export default function ListedVsOtcUstfPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <UstfVolDashboard />
    </Suspense>
  )
}
