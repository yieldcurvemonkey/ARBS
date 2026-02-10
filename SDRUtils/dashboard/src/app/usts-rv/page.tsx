// ABOUTME: UST relative value scatter and spline builder page.
import { Suspense } from 'react'

import UstsRvDashboard from '@/features/usts-rv/components/UstsRvDashboard'

export default function UstsRvPage() {
  return (
    <Suspense fallback={<div className="p-4 text-sm text-gray-400">Loading...</div>}>
      <UstsRvDashboard />
    </Suspense>
  )
}

